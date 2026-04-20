"""Session correlation analysis: conversation logs x git activity x memory signals.

Reads JSONL conversation logs and git history from the past week, correlates
them into a timeline, and produces efficiency metrics per session.

Metrics:
  - Turns per session (fewer = more efficient)
  - Corrections per session (fewer = better memory)
  - Code output: commits attributed to each session
  - Estimated tokens (from message length, ~4 chars/token)
  - Session duration (first turn to last turn)
  - Output density: commits per hour of session time
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LOG_DIR = Path.home() / ".claude" / "conversation-logs"
ARCHIVE_DIR = LOG_DIR / "archive"
REPO_DIR = Path(__file__).resolve().parent.parent
CHARS_PER_TOKEN = 4  # conservative estimate
CORRECTION_MARKERS: list[str] = [
    "no,",
    "no ",
    "don't",
    "stop",
    "wrong",
    "incorrect",
    "not that",
    "actually,",
    "actually ",
    "i said",
    "i meant",
    "that's not",
    "you should",
    "correction:",
    "fix that",
    "undo that",
]
POSITIVE_MARKERS: list[str] = [
    "good",
    "perfect",
    "great",
    "yes",
    "correct",
    "exactly",
    "nice",
    "thanks",
    "thank you",
    "looks good",
    "ship it",
    "do it",
    "go ahead",
    "proceed",
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Turn:
    timestamp: datetime
    event: str  # "user" or "assistant"
    session_id: str
    text: str
    cwd: str = ""

    @property
    def estimated_tokens(self) -> int:
        return max(1, len(self.text) // CHARS_PER_TOKEN)

    @property
    def is_correction(self) -> bool:
        lower = self.text[:200].lower()
        return self.event == "user" and any(m in lower for m in CORRECTION_MARKERS)

    @property
    def is_positive(self) -> bool:
        lower = self.text[:200].lower()
        return self.event == "user" and any(m in lower for m in POSITIVE_MARKERS)


@dataclass
class Commit:
    hash: str
    timestamp: datetime
    subject: str
    category: str = ""

    def categorize(self) -> str:
        s = self.subject.lower()
        # Conventional commit prefixes
        if s.startswith(("fix:", "fix(")):
            return "fix"
        if s.startswith(("feat:", "feat(")):
            return "feature"
        if s.startswith(("perf:", "perf(")):
            return "perf"
        if s.startswith(("test:", "test(")):
            return "test"
        if s.startswith(("docs:", "doc:")):
            return "docs"
        if "merge" in s:
            return "merge"
        if "bump version" in s or "changelog" in s:
            return "release"
        if s.startswith(("research:", "exp")):
            return "research"
        # Keyword fallback for non-conventional commits
        if any(w in s for w in ("fix", "bug", "patch", "correct", "repair")):
            return "fix"
        if any(w in s for w in ("add", "wire", "implement", "enable", "create")):
            return "feature"
        if any(w in s for w in ("test", "assert", "verify", "validate")):
            return "test"
        if any(w in s for w in ("doc", "readme", "comment", "clarif")):
            return "docs"
        if any(
            w in s for w in ("refactor", "rename", "clean", "remove", "delete", "split")
        ):
            return "refactor"
        if any(w in s for w in ("update", "upgrade", "bump")):
            return "update"
        return "other"


@dataclass
class SessionMetrics:
    session_id: str
    turns: list[Turn] = field(default_factory=lambda: list[Turn]())
    commits: list[Commit] = field(default_factory=lambda: list[Commit]())

    @property
    def start(self) -> datetime:
        return min(t.timestamp for t in self.turns)

    @property
    def end(self) -> datetime:
        return max(t.timestamp for t in self.turns)

    @property
    def active_minutes(self) -> float:
        """Duration excluding gaps > 30 min (idle/overnight)."""
        if len(self.turns) < 2:
            return 1.0
        sorted_turns = sorted(self.turns, key=lambda t: t.timestamp)
        active = 0.0
        for i in range(1, len(sorted_turns)):
            gap = (
                sorted_turns[i].timestamp - sorted_turns[i - 1].timestamp
            ).total_seconds()
            if gap < 1800:  # 30 min threshold
                active += gap
        return max(1.0, active / 60.0)

    @property
    def duration_minutes(self) -> float:
        delta = self.end - self.start
        return max(1.0, delta.total_seconds() / 60.0)

    @property
    def user_turns(self) -> int:
        return sum(1 for t in self.turns if t.event == "user")

    @property
    def assistant_turns(self) -> int:
        return sum(1 for t in self.turns if t.event == "assistant")

    @property
    def corrections(self) -> int:
        return sum(1 for t in self.turns if t.is_correction)

    @property
    def positives(self) -> int:
        return sum(1 for t in self.turns if t.is_positive)

    @property
    def correction_rate(self) -> float:
        ut = self.user_turns
        return self.corrections / ut if ut > 0 else 0.0

    @property
    def positive_rate(self) -> float:
        ut = self.user_turns
        return self.positives / ut if ut > 0 else 0.0

    @property
    def estimated_tokens_in(self) -> int:
        return sum(t.estimated_tokens for t in self.turns if t.event == "user")

    @property
    def estimated_tokens_out(self) -> int:
        return sum(t.estimated_tokens for t in self.turns if t.event == "assistant")

    @property
    def commits_per_hour(self) -> float:
        hours = self.active_minutes / 60.0
        return len(self.commits) / hours if hours > 0 else 0.0

    @property
    def commit_categories(self) -> dict[str, int]:
        cats: dict[str, int] = defaultdict(int)
        for c in self.commits:
            cats[c.category] += 1
        return dict(cats)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def load_turns() -> list[Turn]:
    """Load all JSONL conversation logs."""
    turns: list[Turn] = []
    files: list[Path] = []

    if LOG_DIR.exists():
        files.extend(LOG_DIR.glob("*.jsonl"))
    if ARCHIVE_DIR.exists():
        files.extend(ARCHIVE_DIR.glob("*.jsonl"))

    for f in files:
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts_str = d.get("timestamp", "")
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            turns.append(
                Turn(
                    timestamp=ts,
                    event=d.get("event", ""),
                    session_id=d.get("session_id", ""),
                    text=d.get("text", ""),
                    cwd=d.get("cwd", ""),
                )
            )

    turns.sort(key=lambda t: t.timestamp)
    return turns


def load_commits(since: str = "2026-04-11") -> list[Commit]:
    """Load git commits from the repo."""
    result = subprocess.run(
        ["git", "log", f"--since={since}", "--format=%H|%aI|%s", "--all"],
        capture_output=True,
        text=True,
        cwd=REPO_DIR,
    )
    commits: list[Commit] = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        try:
            ts = datetime.fromisoformat(parts[1])
        except ValueError:
            continue
        c = Commit(hash=parts[0][:7], timestamp=ts, subject=parts[2])
        c.category = c.categorize()
        commits.append(c)
    commits.sort(key=lambda c: c.timestamp)
    return commits


def attribute_commits(
    sessions: dict[str, SessionMetrics],
    commits: list[Commit],
    window_minutes: int = 30,
) -> list[Commit]:
    """Attribute commits to sessions by timestamp proximity."""
    unattributed: list[Commit] = []
    for commit in commits:
        best_session: str | None = None
        best_gap = timedelta(minutes=window_minutes)

        for sid, sm in sessions.items():
            if not sm.turns:
                continue
            # Commit should fall within session window (start - window, end + window)
            start = sm.start - timedelta(minutes=window_minutes)
            end = sm.end + timedelta(minutes=window_minutes)
            if start <= commit.timestamp <= end:
                # Pick closest session
                gap = min(
                    abs(commit.timestamp - sm.start),
                    abs(commit.timestamp - sm.end),
                )
                if gap < best_gap:
                    best_gap = gap
                    best_session = sid

        if best_session:
            sessions[best_session].commits.append(commit)
        else:
            unattributed.append(commit)
    return unattributed


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def format_duration(minutes: float) -> str:
    if minutes < 60:
        return f"{minutes:.0f}m"
    hours = minutes / 60
    return f"{hours:.1f}h"


def repeated_corrections(turns: list[Turn]) -> list[tuple[str, int]]:
    """Find correction phrases that appear across multiple sessions."""
    # Extract correction text snippets per session
    session_corrections: dict[str, list[str]] = defaultdict(list)
    for t in turns:
        if t.is_correction:
            # Take first 80 chars as the correction fingerprint
            snippet = t.text[:80].lower().strip()
            session_corrections[t.session_id].append(snippet)

    # Find phrases repeated across sessions (crude but useful)
    word_session_count: dict[str, set[str]] = defaultdict(set)
    for sid, snippets in session_corrections.items():
        for snippet in snippets:
            for word in snippet.split():
                if len(word) > 4:  # skip short words
                    word_session_count[word].add(sid)

    repeated = [
        (word, len(sids)) for word, sids in word_session_count.items() if len(sids) >= 2
    ]
    repeated.sort(key=lambda x: -x[1])
    return repeated[:15]


def print_report(
    sessions: dict[str, SessionMetrics],
    commits: list[Commit],
    unattributed: list[Commit],
    turns: list[Turn],
) -> None:
    # Filter to agentmemory sessions only
    am_sessions = {
        sid: sm
        for sid, sm in sessions.items()
        if any("agentmemory" in t.cwd for t in sm.turns)
    }

    print("=" * 78)
    print("AGENTMEMORY SESSION CORRELATION REPORT")
    print(
        f"Period: {commits[0].timestamp.strftime('%Y-%m-%d')} to "
        f"{commits[-1].timestamp.strftime('%Y-%m-%d')}"
        if commits
        else "No commits"
    )
    print(
        f"Data: {len(turns)} conversation turns, {len(commits)} commits, "
        f"{len(am_sessions)} agentmemory sessions"
    )
    print("=" * 78)

    # --- Aggregate metrics ---
    print("\n## AGGREGATE METRICS\n")
    total_user = sum(sm.user_turns for sm in am_sessions.values())
    total_asst = sum(sm.assistant_turns for sm in am_sessions.values())
    total_corrections = sum(sm.corrections for sm in am_sessions.values())
    total_positives = sum(sm.positives for sm in am_sessions.values())
    total_tok_in = sum(sm.estimated_tokens_in for sm in am_sessions.values())
    total_tok_out = sum(sm.estimated_tokens_out for sm in am_sessions.values())
    total_commits_attr = sum(len(sm.commits) for sm in am_sessions.values())
    total_active = sum(sm.active_minutes for sm in am_sessions.values())
    total_wall = sum(sm.duration_minutes for sm in am_sessions.values())

    print(f"  Sessions:            {len(am_sessions)}")
    print(
        f"  Active time:         {format_duration(total_active)} (wall: {format_duration(total_wall)})"
    )
    print(f"  User turns:          {total_user}")
    print(f"  Assistant turns:     {total_asst}")
    print(f"  Est. tokens in:      {total_tok_in:,}")
    print(f"  Est. tokens out:     {total_tok_out:,}")
    print(
        f"  Corrections:         {total_corrections} "
        f"({total_corrections / total_user * 100:.1f}% of user turns)"
        if total_user
        else ""
    )
    print(
        f"  Positive signals:    {total_positives} "
        f"({total_positives / total_user * 100:.1f}% of user turns)"
        if total_user
        else ""
    )
    print(f"  Commits attributed:  {total_commits_attr} / {len(commits)}")
    print(f"  Commits unattributed:{len(unattributed)}")

    # --- Commit breakdown ---
    print("\n## COMMIT CATEGORIES\n")
    cats: dict[str, int] = defaultdict(int)
    for c in commits:
        cats[c.category] += 1
    for cat in sorted(cats, key=lambda x: -cats[x]):
        pct = cats[cat] / len(commits) * 100
        bar = "#" * int(pct / 2)
        print(f"  {cat:12s} {cats[cat]:4d} ({pct:5.1f}%) {bar}")

    # --- Per-session table ---
    print("\n## PER-SESSION METRICS\n")
    print(
        f"  {'Session ID':<12} {'Active':>8} {'Turns':>6} {'Corr':>5} "
        f"{'Pos':>5} {'Commits':>7} {'Comm/hr':>8} {'TokOut':>8} {'Date':>11}"
    )
    print(
        f"  {'-' * 12} {'-' * 8} {'-' * 6} {'-' * 5} {'-' * 5} {'-' * 7} {'-' * 8} {'-' * 8} {'-' * 11}"
    )

    sorted_sessions = sorted(am_sessions.values(), key=lambda s: s.start)
    for sm in sorted_sessions:
        if sm.user_turns < 2:
            continue  # skip trivial sessions
        print(
            f"  {sm.session_id[:12]} "
            f"{format_duration(sm.active_minutes):>8} "
            f"{len(sm.turns):>6} "
            f"{sm.corrections:>5} "
            f"{sm.positives:>5} "
            f"{len(sm.commits):>7} "
            f"{sm.commits_per_hour:>8.1f} "
            f"{sm.estimated_tokens_out:>8,} "
            f"{sm.start.strftime('%m-%d %H:%M'):>11}"
        )

    # --- Commit attribution detail ---
    print("\n## COMMIT ATTRIBUTION (session -> commits)\n")
    for sm in sorted_sessions:
        if not sm.commits:
            continue
        cats = sm.commit_categories
        cat_str = ", ".join(
            f"{v} {k}" for k, v in sorted(cats.items(), key=lambda x: -x[1])
        )
        print(f"  {sm.session_id[:12]} ({cat_str}):")
        for c in sorted(sm.commits, key=lambda x: x.timestamp):
            print(f"    {c.hash} [{c.category:8s}] {c.subject[:65]}")

    # --- Efficiency trends ---
    print("\n## EFFICIENCY SIGNALS\n")

    # Group sessions by date
    by_date: dict[str, list[SessionMetrics]] = defaultdict(list)
    for sm in sorted_sessions:
        if sm.user_turns >= 2:
            by_date[sm.start.strftime("%Y-%m-%d")].append(sm)

    print(
        f"  {'Date':<12} {'Sessions':>8} {'Avg Turns':>10} {'Avg Corr%':>10} "
        f"{'Commits':>8} {'AvgActive':>10} {'Avg TokOut':>10}"
    )
    print(
        f"  {'-' * 12} {'-' * 8} {'-' * 10} {'-' * 10} {'-' * 8} {'-' * 10} {'-' * 10}"
    )
    for date in sorted(by_date):
        day_sessions = by_date[date]
        avg_turns = sum(len(s.turns) for s in day_sessions) / len(day_sessions)
        avg_corr = (
            sum(s.correction_rate for s in day_sessions) / len(day_sessions) * 100
        )
        total_day_commits = sum(len(s.commits) for s in day_sessions)
        avg_active = sum(s.active_minutes for s in day_sessions) / len(day_sessions)
        avg_tok = sum(s.estimated_tokens_out for s in day_sessions) / len(day_sessions)
        print(
            f"  {date:<12} {len(day_sessions):>8} {avg_turns:>10.1f} "
            f"{avg_corr:>9.1f}% {total_day_commits:>8} "
            f"{format_duration(avg_active):>10} {avg_tok:>10,.0f}"
        )

    # --- Repeated corrections ---
    print("\n## REPEATED CORRECTION KEYWORDS (across 2+ sessions)\n")
    repeated = repeated_corrections(turns)
    if repeated:
        for word, count in repeated[:10]:
            print(f"  {word:<30} {count} sessions")
    else:
        print("  (none detected)")

    # --- Unattributed commits ---
    if unattributed:
        print(f"\n## UNATTRIBUTED COMMITS ({len(unattributed)})\n")
        for c in unattributed[:20]:
            print(
                f"  {c.hash} {c.timestamp.strftime('%m-%d %H:%M')} "
                f"[{c.category}] {c.subject[:60]}"
            )

    print("\n" + "=" * 78)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    since = sys.argv[1] if len(sys.argv) > 1 else "2026-04-11"
    print(f"Loading conversation logs from {LOG_DIR} ...")
    turns = load_turns()
    print(f"  {len(turns)} turns loaded")

    print(f"Loading git commits since {since} ...")
    commits = load_commits(since)
    print(f"  {len(commits)} commits loaded")

    # Build session map
    sessions: dict[str, SessionMetrics] = {}
    for turn in turns:
        if turn.session_id not in sessions:
            sessions[turn.session_id] = SessionMetrics(session_id=turn.session_id)
        sessions[turn.session_id].turns.append(turn)

    print(f"  {len(sessions)} unique sessions")
    print("Attributing commits to sessions ...")
    unattributed = attribute_commits(sessions, commits)
    print(
        f"  {len(commits) - len(unattributed)} attributed, {len(unattributed)} unattributed\n"
    )

    print_report(sessions, commits, unattributed, turns)


if __name__ == "__main__":
    main()
