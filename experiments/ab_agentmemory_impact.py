"""A/B comparison: sessions with agentmemory vs without.

Analyzes conversation logs to compare session efficiency metrics
between projects that have agentmemory installed and those that don't.

PRIVACY: All output is fully anonymized. No project names, paths, user
names, session IDs, or any identifying information is printed. Projects
are labeled Treatment-1, Treatment-2, Control-1, etc.
"""
from __future__ import annotations

import json
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_LOGS_DIR: Path = Path.home() / ".claude" / "conversation-logs"
_ARCHIVE_DIR: Path = _LOGS_DIR / "archive"

# Projects with agentmemory installed (detected by .mcp.json presence)
# We detect this automatically rather than hardcoding paths.

_CORRECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bno[,.]?\s+(not |that'?s |it'?s )", re.IGNORECASE),
    re.compile(r"\b(wrong|incorrect|that'?s not right)\b", re.IGNORECASE),
    re.compile(r"\b(i (already|just) (said|told|mentioned))\b", re.IGNORECASE),
    re.compile(r"\b(stop doing|don'?t do that|not what i)\b", re.IGNORECASE),
    re.compile(r"\b(i said|as i said|like i said)\b", re.IGNORECASE),
    re.compile(r"\b(try again|redo|undo that)\b", re.IGNORECASE),
]

_MIN_SESSION_TURNS: int = 4


# ---------------------------------------------------------------------------
# Anonymization
# ---------------------------------------------------------------------------

def _build_labels(
    projects: dict[str, str],
) -> dict[str, str]:
    """Map real project paths to anonymous labels."""
    labels: dict[str, str] = {}
    t_count: int = 0
    c_count: int = 0

    for path in sorted(projects.keys()):
        group: str = projects[path]
        if group == "treatment":
            t_count += 1
            labels[path] = f"Treatment-{t_count}"
        else:
            c_count += 1
            labels[path] = f"Control-{c_count}"

    return labels


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Turn:
    timestamp: datetime
    event: str
    text: str
    session_id: str
    cwd: str


@dataclass
class SessionStats:
    label: str  # anonymized project label
    group: str
    total_turns: int = 0
    user_turns: int = 0
    assistant_turns: int = 0
    duration_minutes: float = 0.0
    avg_user_turn_chars: float = 0.0
    avg_assistant_turn_chars: float = 0.0
    correction_count: int = 0
    compaction_events: int = 0
    user_chars_total: int = 0
    assistant_chars_total: int = 0


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _detect_treatment_projects(turns: list[Turn]) -> set[str]:
    """Detect which projects have agentmemory by checking for .mcp.json."""
    cwds: set[str] = {t.cwd for t in turns if t.cwd}
    treatment: set[str] = set()
    for cwd in cwds:
        mcp_path: Path = Path(cwd) / ".mcp.json"
        if not mcp_path.exists():
            continue
        try:
            with mcp_path.open() as f:
                config: dict[str, object] = json.loads(f.read())
            servers: object = config.get("mcpServers", {})
            if isinstance(servers, dict) and "agentmemory" in servers:
                treatment.add(cwd)
        except (json.JSONDecodeError, OSError):
            continue
    return treatment


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _load_all_turns() -> list[Turn]:
    """Load all conversation turns from current + archive logs."""
    turns: list[Turn] = []

    files: list[Path] = []
    main_log: Path = _LOGS_DIR / "turns.jsonl"
    if main_log.exists():
        files.append(main_log)
    if _ARCHIVE_DIR.is_dir():
        files.extend(sorted(_ARCHIVE_DIR.glob("*.jsonl")))

    for fpath in files:
        with fpath.open("r", encoding="utf-8") as fh:
            for line_raw in fh:
                line_raw = line_raw.strip()
                if not line_raw:
                    continue
                try:
                    rec: dict[str, str] = json.loads(line_raw)
                except json.JSONDecodeError:
                    continue

                ts_str: str = rec.get("timestamp", "")
                event: str = rec.get("event", "")
                text: str = rec.get("text", "")
                sid: str = rec.get("session_id", "")
                cwd: str = rec.get("cwd", "")

                if not ts_str or not sid:
                    continue

                try:
                    ts: datetime = datetime.fromisoformat(
                        ts_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    continue

                turns.append(Turn(
                    timestamp=ts,
                    event=event,
                    text=text,
                    session_id=sid,
                    cwd=cwd,
                ))

    return turns


def _count_corrections(text: str) -> int:
    """Count correction signals in a user turn."""
    count: int = 0
    for pat in _CORRECTION_PATTERNS:
        if pat.search(text):
            count += 1
    return count


def _compute_sessions(
    turns: list[Turn],
    treatment_projects: set[str],
    labels: dict[str, str],
) -> list[SessionStats]:
    """Group turns by session and compute per-session metrics."""
    sessions: dict[str, list[Turn]] = defaultdict(list)
    for t in turns:
        sessions[t.session_id].append(t)

    results: list[SessionStats] = []
    for _sid, session_turns in sessions.items():
        session_turns.sort(key=lambda t: t.timestamp)

        # Determine project from most common cwd
        cwds: dict[str, int] = defaultdict(int)
        for t in session_turns:
            if t.cwd:
                cwds[t.cwd] += 1
        if not cwds:
            continue
        project: str = max(cwds, key=lambda c: cwds[c])

        # Skip worktrees and temp dirs
        if ".claude/worktrees" in project or project == "/tmp":
            continue

        if project not in labels:
            continue

        group: str = "treatment" if project in treatment_projects else "control"
        label: str = labels[project]

        user_turns: list[Turn] = [t for t in session_turns if t.event == "user"]
        asst_turns: list[Turn] = [t for t in session_turns if t.event == "assistant"]
        compactions: int = sum(
            1 for t in session_turns if t.event == "compaction_start"
        )

        total: int = len(user_turns) + len(asst_turns)
        if total < _MIN_SESSION_TURNS:
            continue

        first_ts: datetime = session_turns[0].timestamp
        last_ts: datetime = session_turns[-1].timestamp
        duration_min: float = (last_ts - first_ts).total_seconds() / 60.0

        user_chars: list[int] = [len(t.text) for t in user_turns]
        asst_chars: list[int] = [len(t.text) for t in asst_turns]

        corrections: int = sum(_count_corrections(t.text) for t in user_turns)

        results.append(SessionStats(
            label=label,
            group=group,
            total_turns=total,
            user_turns=len(user_turns),
            assistant_turns=len(asst_turns),
            duration_minutes=round(duration_min, 1),
            avg_user_turn_chars=(
                round(statistics.mean(user_chars), 0) if user_chars else 0.0
            ),
            avg_assistant_turn_chars=(
                round(statistics.mean(asst_chars), 0) if asst_chars else 0.0
            ),
            correction_count=corrections,
            compaction_events=compactions,
            user_chars_total=sum(user_chars),
            assistant_chars_total=sum(asst_chars),
        ))

    return results


# ---------------------------------------------------------------------------
# Reporting (fully anonymized)
# ---------------------------------------------------------------------------

def _safe_median(vals: list[float]) -> float:
    return round(statistics.median(vals), 1) if vals else 0.0


def _safe_mean(vals: list[float]) -> float:
    return round(statistics.mean(vals), 1) if vals else 0.0


def _report(sessions: list[SessionStats]) -> None:
    """Print fully anonymized A/B comparison report."""
    treatment: list[SessionStats] = [s for s in sessions if s.group == "treatment"]
    control: list[SessionStats] = [s for s in sessions if s.group == "control"]

    print("=" * 72)
    print("A/B COMPARISON: agentmemory Impact on Session Efficiency")
    print("=" * 72)
    print()

    # Group summary (anonymized)
    print(f"Treatment (agentmemory installed): {len(treatment)} sessions")
    for lbl in sorted({s.label for s in treatment}):
        n: int = sum(1 for s in treatment if s.label == lbl)
        print(f"  {lbl}: {n} sessions")
    print()

    print(f"Control (no agentmemory): {len(control)} sessions")
    for lbl in sorted({s.label for s in control}):
        n = sum(1 for s in control if s.label == lbl)
        print(f"  {lbl}: {n} sessions")
    print()

    if not control:
        print("No control sessions found. Cannot compare.")
        return

    # Metrics comparison
    print("-" * 72)
    print(f"{'Metric':<35} {'Treatment':>12} {'Control':>12} {'Delta':>10}")
    print("-" * 72)

    metrics: list[tuple[str, str, list[float], list[float]]] = [
        ("Session duration (min)", "median",
         [s.duration_minutes for s in treatment],
         [s.duration_minutes for s in control]),
        ("Total turns/session", "median",
         [float(s.total_turns) for s in treatment],
         [float(s.total_turns) for s in control]),
        ("User turns/session", "median",
         [float(s.user_turns) for s in treatment],
         [float(s.user_turns) for s in control]),
        ("Avg user turn length (chars)", "median",
         [s.avg_user_turn_chars for s in treatment],
         [s.avg_user_turn_chars for s in control]),
        ("Avg assistant turn length", "median",
         [s.avg_assistant_turn_chars for s in treatment],
         [s.avg_assistant_turn_chars for s in control]),
        ("Corrections/session", "mean",
         [float(s.correction_count) for s in treatment],
         [float(s.correction_count) for s in control]),
        ("Corrections/user turn", "mean",
         [s.correction_count / max(s.user_turns, 1) for s in treatment],
         [s.correction_count / max(s.user_turns, 1) for s in control]),
        ("Compactions/session", "mean",
         [float(s.compaction_events) for s in treatment],
         [float(s.compaction_events) for s in control]),
        ("User chars/session", "median",
         [float(s.user_chars_total) for s in treatment],
         [float(s.user_chars_total) for s in control]),
        ("Assistant chars/session", "median",
         [float(s.assistant_chars_total) for s in treatment],
         [float(s.assistant_chars_total) for s in control]),
    ]

    for name, agg, t_vals, c_vals in metrics:
        fn = _safe_median if agg == "median" else _safe_mean
        t_val: float = fn(t_vals)
        c_val: float = fn(c_vals)
        if c_val != 0:
            delta_pct: str = f"{((t_val - c_val) / c_val) * 100:+.0f}%"
        else:
            delta_pct = "n/a"
        print(f"{name:<35} {t_val:>12.1f} {c_val:>12.1f} {delta_pct:>10}")

    print("-" * 72)
    print()

    # Per-project breakdown (anonymized)
    print("PER-PROJECT DETAIL:")
    print("-" * 72)
    print(
        f"{'Label':<20} {'Group':<10} {'N':>4} "
        f"{'Med Turns':>10} {'Med Dur':>8} {'Corr/Turn':>10}"
    )
    print("-" * 72)
    for lbl in sorted({s.label for s in sessions}):
        proj_sessions: list[SessionStats] = [s for s in sessions if s.label == lbl]
        if not proj_sessions:
            continue
        g: str = proj_sessions[0].group
        n = len(proj_sessions)
        med_turns: float = _safe_median(
            [float(s.total_turns) for s in proj_sessions]
        )
        med_dur: float = _safe_median(
            [s.duration_minutes for s in proj_sessions]
        )
        corr_rate: float = _safe_mean([
            s.correction_count / max(s.user_turns, 1) for s in proj_sessions
        ])
        print(
            f"{lbl:<20} {g:<10} {n:>4} "
            f"{med_turns:>10.0f} {med_dur:>8.1f} {corr_rate:>10.3f}"
        )

    print()
    print("CAVEATS:")
    print("  - Treatment/control assignment is by project, not random")
    print("  - agentmemory projects may have more total usage (selection bias)")
    print("  - Correction detection is heuristic (regex patterns)")
    print("  - No token counts available; char length is a proxy")
    print("  - Duration measures wall clock, not active time")
    print("  - All project identifiers are anonymized")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    turns: list[Turn] = _load_all_turns()
    print(f"Loaded {len(turns)} turns from conversation logs\n")

    # Auto-detect treatment projects
    treatment_projects: set[str] = _detect_treatment_projects(turns)
    all_cwds: set[str] = {
        t.cwd for t in turns
        if t.cwd
        and ".claude/worktrees" not in t.cwd
        and t.cwd != "/tmp"
    }

    # Build group mapping
    project_groups: dict[str, str] = {}
    for cwd in sorted(all_cwds):
        project_groups[cwd] = (
            "treatment" if cwd in treatment_projects else "control"
        )

    # Build anonymous labels
    labels: dict[str, str] = _build_labels(project_groups)

    t_count: int = sum(1 for g in project_groups.values() if g == "treatment")
    c_count: int = sum(1 for g in project_groups.values() if g == "control")
    print(f"Detected {t_count} treatment projects, {c_count} control projects\n")

    sessions: list[SessionStats] = _compute_sessions(
        turns, treatment_projects, labels,
    )
    print(
        f"Computed stats for {len(sessions)} sessions "
        f"(>= {_MIN_SESSION_TURNS} turns each)\n"
    )

    _report(sessions)


if __name__ == "__main__":
    main()
