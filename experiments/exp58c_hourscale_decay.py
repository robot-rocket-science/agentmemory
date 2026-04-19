"""Exp 58c: Hour-Scale Decay + Velocity-Scaled Decay

Hypothesis: decay should operate on the scale of HOURS, not days.
Items from a fast sprint (>10 items/hour) should be substantially decayed by
the next session. Hour-scale decay creates natural separation between
fast-sprint findings and locked constraints from months of use.

Data sources (same as Exp 58b):
  - /home/user/projects/project-a-test/.gsd/DECISIONS.md (183 active)
  - /home/user/projects/project-a/docs/DECISIONS-ARCHIVE.md (35 superseded)
  - /home/user/projects/agentmemory/experiments/exp6_failures_v2.json (38 corrections)
  - git log from project-b + project-a + project-a-test repos

KEY CHANGE vs Exp 58b:
  - ALL timestamps stored and compared in HOURS since project start (not days).
  - A decision from Dec 2025 is ~2,500h old by April 2026.
  - A fast-sprint decision from yesterday is ~4h old.

Three decay strategies tested:
  A. Flat hour-scale decay (half-life sweep in hours)
  B. Content-type-aware decay using best flat half-life from A
  C. Velocity-scaled decay: half-life *= velocity_scale based on session pace

Special CS-005 test: simulate next-session ranking of the fastest-sprint
milestone to verify fast-sprint decisions fall below locked constraints.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from collections.abc import Callable
from typing import Any, Final

# ============================================================
# Paths
# ============================================================

DECISIONS_MD: Final[Path] = Path("/home/user/projects/project-a-test/.gsd/DECISIONS.md")
ARCHIVE_MD: Final[Path] = Path(
    "/home/user/projects/project-a/docs/DECISIONS-ARCHIVE.md"
)
EXP6_FAILURES: Final[Path] = Path(
    "/home/user/projects/agentmemory/experiments/exp6_failures_v2.json"
)
RESULTS_PATH: Final[Path] = Path(
    "/home/user/projects/agentmemory/experiments/exp58c_results.json"
)

OPTIMUS_PRIME_REPO: Final[Path] = Path("/home/user/projects/project-b")
ALPHA_SEEK_REPO: Final[Path] = Path("/home/user/projects/project-a")
ALPHA_SEEK_MEMTEST_REPO: Final[Path] = Path("/home/user/projects/project-a-test")

# ============================================================
# Config
# ============================================================

# Project epoch: earliest project-b commit (Dec 2025)
# Used for "inherited" decisions and as t=0 for all hour-scale measurements.
PROJECT_EPOCH: Final[str] = "2025-12-01T00:00:00+00:00"

# Half-life sweep candidates in HOURS
HALF_LIFE_CANDIDATES_H: Final[list[float]] = [
    0.5,
    1.0,
    2.0,
    4.0,
    8.0,
    12.0,
    24.0,
    48.0,
    168.0,
    336.0,
    720.0,
]

RANKING_THRESHOLDS: Final[list[int]] = [5, 10, 15]

# Content-type multipliers for Strategy B
CONTENT_TYPE_MULTIPLIERS: Final[dict[str, float]] = {
    "CONSTRAINT": 0.0,  # never decays (locked) -- special-cased in scorer
    "EVIDENCE": 1.0,
    "CONTEXT": 0.25,
    "PROCEDURE": 2.0,
    "RATIONALE": 3.0,
}

# Velocity thresholds (decisions per hour)
VELOCITY_FAST: Final[float] = 10.0  # > 10 items/hour
VELOCITY_MOD_HI: Final[float] = 10.0
VELOCITY_MOD_LO: Final[float] = 5.0
VELOCITY_DEEP_HI: Final[float] = 5.0
VELOCITY_DEEP_LO: Final[float] = 2.0


# Velocity scale factors for Strategy C
def velocity_scale(velocity: float) -> float:
    """Map session velocity (decisions/hour) to half-life scale factor."""
    if velocity > VELOCITY_FAST:
        return 0.1
    if velocity >= VELOCITY_MOD_LO:
        return 0.5
    if velocity >= VELOCITY_DEEP_LO:
        return 0.8
    return 1.0


# ============================================================
# Enums and data structures
# ============================================================


class ContentType(Enum):
    CONSTRAINT = "CONSTRAINT"
    EVIDENCE = "EVIDENCE"
    CONTEXT = "CONTEXT"
    PROCEDURE = "PROCEDURE"


SCOPE_CONSTRAINT: Final[frozenset[str]] = frozenset(
    {
        "architecture",
        "infrastructure",
        "operations",
        "agent behavior",
        "code-quality",
    }
)
SCOPE_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        "strategy",
        "signal-model",
        "backtesting",
        "evaluation",
        "validation",
    }
)
SCOPE_CONTEXT: Final[frozenset[str]] = frozenset(
    {
        "milestone",
        "bugfix",
        "reporting",
        "documentation",
    }
)
SCOPE_PROCEDURE: Final[frozenset[str]] = frozenset(
    {
        "methodology",
        "configuration",
        "tooling",
    }
)


@dataclass
class MilestoneInfo:
    milestone_id: str
    first_commit_hours: float  # hours since PROJECT_EPOCH
    last_commit_hours: float  # hours since PROJECT_EPOCH
    decision_count: int = 0

    @property
    def duration_hours(self) -> float:
        """Duration from first to last commit referencing this milestone."""
        dur: float = self.last_commit_hours - self.first_commit_hours
        # Minimum 0.5h to avoid division-by-zero with single-commit milestones
        return max(dur, 0.5)

    @property
    def velocity(self) -> float:
        """Decisions per hour within the milestone."""
        if self.decision_count == 0:
            return 0.0
        return self.decision_count / self.duration_hours


@dataclass
class Decision:
    d_id: str
    when_raw: str
    scope: str
    decision_text: str
    choice_text: str
    rationale_text: str
    revisable_raw: str
    made_by: str
    superseded_by: str | None
    is_archived: bool
    created_at_hours: float  # HOURS since PROJECT_EPOCH (key change from 58b)
    content_type: ContentType
    locked: bool
    is_inherited: bool
    milestone_id: str | None  # primary milestone ID (for velocity lookup)
    session_velocity: float  # decisions/hour for the session that produced this


@dataclass
class CorrectionCluster:
    topic_id: str
    description: str
    decision_refs: list[str]
    correction_timestamps: list[str]
    is_memory_failure: bool


@dataclass
class RankingResult:
    topic_id: str
    correction_iso: str
    correct_refs_found: list[str]
    best_rank: int | None
    total_decisions: int


@dataclass
class FlatSweepResult:
    half_life_hours: float
    prevention_rate_top5: float
    prevention_rate_top10: float
    prevention_rate_top15: float
    per_cluster: dict[str, dict[str, float]] = field(
        default_factory=lambda: dict[str, dict[str, float]]()
    )


@dataclass
class StrategyBResult:
    base_half_life_hours: float
    prevention_rate_top5: float
    prevention_rate_top10: float
    prevention_rate_top15: float
    per_cluster: dict[str, dict[str, float]] = field(
        default_factory=lambda: dict[str, dict[str, float]]()
    )
    locked_unlocked_separation: dict[str, float] = field(
        default_factory=lambda: dict[str, float]()
    )
    score_distribution: dict[str, int] = field(default_factory=lambda: dict[str, int]())


@dataclass
class StrategyCResult:
    base_half_life_hours: float
    prevention_rate_top5: float
    prevention_rate_top10: float
    prevention_rate_top15: float
    per_cluster: dict[str, dict[str, float]] = field(
        default_factory=lambda: dict[str, dict[str, float]]()
    )
    locked_unlocked_separation: dict[str, float] = field(
        default_factory=lambda: dict[str, float]()
    )
    score_distribution: dict[str, int] = field(default_factory=lambda: dict[str, int]())


@dataclass
class CS005Result:
    fastest_milestone_id: str
    fastest_milestone_velocity: float
    fast_sprint_decision_count: int
    eval_at_hours: float  # milestone end + 12h
    fast_sprint_avg_score: float
    locked_avg_score: float
    inherited_avg_score: float
    fast_sprint_below_locked: bool
    fast_sprint_ranks: list[tuple[str, int, float]]  # (d_id, rank, score)
    locked_ranks: list[tuple[str, int, float]]
    inherited_ranks: list[tuple[str, int, float]]


# ============================================================
# Date utilities (HOURS not days)
# ============================================================


def _epoch_dt() -> datetime:
    return datetime.fromisoformat(PROJECT_EPOCH)


def iso_to_hours(iso_str: str) -> float:
    """Convert ISO 8601 string to HOURS since PROJECT_EPOCH."""
    clean: str = iso_str.replace("Z", "+00:00")
    dt: datetime = datetime.fromisoformat(clean)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = dt - _epoch_dt()
    return delta.total_seconds() / 3600.0


def git_date_to_hours(date_str: str) -> float:
    """Convert git log date string 'YYYY-MM-DD HH:MM:SS +HHMM' to hours since epoch."""
    dt: datetime = datetime.strptime(date_str.strip(), "%Y-%m-%d %H:%M:%S %z")
    return (dt - _epoch_dt()).total_seconds() / 3600.0


# ============================================================
# Git log helpers
# ============================================================


def load_git_log(repo: Path) -> list[tuple[str, str, str]]:
    """Run git log and return list of (sha, date_str, subject)."""
    result = subprocess.run(
        ["git", "log", "--all", "--format=%H %ad %s", "--date=iso"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    entries: list[tuple[str, str, str]] = []
    for raw_line in result.stdout.splitlines():
        raw_line = raw_line.strip()
        if not raw_line or len(raw_line) < 67:
            continue
        sha: str = raw_line[:40]
        date_str: str = raw_line[41:66]
        subject: str = raw_line[67:]
        entries.append((sha, date_str.strip(), subject))
    return entries


def build_milestone_hour_index(repos: list[Path]) -> dict[str, MilestoneInfo]:
    """Build milestone_id -> MilestoneInfo (first/last commit hours) across all repos.

    Scans git commit messages for milestone IDs of the form M\\d+-[a-z0-9]{6}.
    Returns a dict keyed by uppercase milestone ID.
    """
    milestone_pattern: re.Pattern[str] = re.compile(r"M\d+-[a-z0-9]{6}", re.IGNORECASE)

    # milestone_id -> (first_hours, last_hours)
    first_hours: dict[str, float] = {}
    last_hours: dict[str, float] = {}

    for repo in repos:
        entries = load_git_log(repo)
        for _sha, date_str, subject in entries:
            h: float
            try:
                h = git_date_to_hours(date_str)
            except ValueError:
                continue
            matches = milestone_pattern.findall(subject)
            for m in matches:
                m_upper: str = m.upper()
                if m_upper not in first_hours or h < first_hours[m_upper]:
                    first_hours[m_upper] = h
                if m_upper not in last_hours or h > last_hours[m_upper]:
                    last_hours[m_upper] = h

    result: dict[str, MilestoneInfo] = {}
    for mid, fh in first_hours.items():
        result[mid] = MilestoneInfo(
            milestone_id=mid,
            first_commit_hours=fh,
            last_commit_hours=last_hours.get(mid, fh),
            decision_count=0,
        )

    print(
        f"[git] milestone IDs indexed: {len(result)}",
        file=sys.stderr,
    )
    return result


def extract_primary_milestone(when_raw: str) -> str | None:
    """Extract the first milestone ID (M###-xxxxxx) from a When field."""
    pattern: re.Pattern[str] = re.compile(r"M\d+-[a-z0-9]{6}", re.IGNORECASE)
    m = pattern.search(when_raw)
    if m:
        return m.group(0).upper()
    return None


def extract_all_milestones(when_raw: str) -> list[str]:
    """Extract all milestone IDs from a When field."""
    pattern: re.Pattern[str] = re.compile(r"M\d+-[a-z0-9]{6}", re.IGNORECASE)
    return [m.upper() for m in pattern.findall(when_raw)]


# ============================================================
# Markdown parsers
# ============================================================


def _parse_decisions_row(line: str) -> tuple[str, ...] | None:
    """Parse '| D### | when | scope | ... |' into 8-field tuple."""
    line = line.strip()
    if not line.startswith("| D"):
        return None
    inner: str = line.strip("|")
    parts: list[str] = [p.strip() for p in inner.split("|")]
    if len(parts) < 8:
        return None
    d_id: str = parts[0].strip()
    if not re.match(r"D\d+$", d_id):
        return None
    return (
        parts[0].strip(),  # D###
        parts[1].strip(),  # When
        parts[2].strip(),  # Scope
        parts[3].strip(),  # Decision
        parts[4].strip(),  # Choice
        parts[5].strip(),  # Rationale
        parts[6].strip(),  # Revisable?
        parts[7].strip(),  # Made By
    )


def _derive_hours(
    when_raw: str,
    milestone_index: dict[str, MilestoneInfo],
    optimus_earliest_hours: float,
    median_hours: float,
) -> float:
    """Derive creation time in HOURS since PROJECT_EPOCH from a When field."""
    if when_raw.strip().lower() == "inherited":
        return optimus_earliest_hours

    mids: list[str] = extract_all_milestones(when_raw)
    matched_hours: list[float] = [
        milestone_index[mid].first_commit_hours
        for mid in mids
        if mid in milestone_index
    ]
    if matched_hours:
        return min(matched_hours)

    # Prefix fallback: look for M### without hash suffix
    prefix_pattern: re.Pattern[str] = re.compile(r"\b(M\d+)\b", re.IGNORECASE)
    for prefix in [p.upper() for p in prefix_pattern.findall(when_raw)]:
        for mid, info in milestone_index.items():
            if mid.startswith(prefix):
                matched_hours.append(info.first_commit_hours)
    if matched_hours:
        return min(matched_hours)

    return median_hours


def _classify(scope: str, locked: bool) -> ContentType:
    s: str = scope.lower().strip()
    if locked and (s in SCOPE_CONSTRAINT or s == "code-quality"):
        return ContentType.CONSTRAINT
    if s in SCOPE_EVIDENCE:
        return ContentType.EVIDENCE
    if s in SCOPE_CONTEXT:
        return ContentType.CONTEXT
    if s in SCOPE_PROCEDURE:
        return ContentType.PROCEDURE
    if s in SCOPE_CONSTRAINT:
        return ContentType.EVIDENCE  # unlocked constraint-type -> evidence
    return ContentType.EVIDENCE


def load_active_decisions(
    path: Path,
    milestone_index: dict[str, MilestoneInfo],
    optimus_earliest_hours: float,
    median_hours: float,
) -> list[Decision]:
    raw: str = path.read_text(encoding="utf-8")
    decisions: list[Decision] = []

    for line in raw.splitlines():
        parsed = _parse_decisions_row(line)
        if parsed is None:
            continue
        (
            d_id,
            when_raw,
            scope,
            decision_text,
            choice_text,
            rationale_text,
            revisable_raw,
            made_by,
        ) = parsed

        created_at_hours: float = _derive_hours(
            when_raw, milestone_index, optimus_earliest_hours, median_hours
        )
        locked: bool = revisable_raw.strip().lower().startswith("no")
        content_type: ContentType = _classify(scope, locked)
        is_inherited: bool = when_raw.strip().lower() == "inherited"
        primary_mid: str | None = extract_primary_milestone(when_raw)

        # Velocity is resolved after all decisions loaded (second pass)
        decisions.append(
            Decision(
                d_id=d_id,
                when_raw=when_raw,
                scope=scope,
                decision_text=decision_text,
                choice_text=choice_text,
                rationale_text=rationale_text,
                revisable_raw=revisable_raw,
                made_by=made_by,
                superseded_by=None,
                is_archived=False,
                created_at_hours=created_at_hours,
                content_type=content_type,
                locked=locked,
                is_inherited=is_inherited,
                milestone_id=primary_mid,
                session_velocity=1.0,  # filled in populate_velocities()
            )
        )

    print(f"[parse] active decisions: {len(decisions)}", file=sys.stderr)
    return decisions


def _superseded_by_from_block(block: str) -> str | None:
    m = re.search(r"\*\*Superseded by:\*\*\s*(D\d+)", block, re.IGNORECASE)
    return m.group(1) if m else None


def _field_from_block(block: str, field_name: str) -> str:
    m = re.search(rf"\*\*{field_name}:\*\*\s*([^\n]+)", block)
    return m.group(1).strip() if m else ""


def _choice_from_block(block: str) -> str:
    m = re.search(r"\*\*Choice:\*\*\s*([\s\S]*?)(?=\*\*Rationale:|$)", block)
    return m.group(1).strip() if m else ""


def _rationale_from_block(block: str) -> str:
    m = re.search(r"\*\*Rationale:\*\*\s*([\s\S]*?)(?=###|$)", block)
    return m.group(1).strip() if m else ""


def load_archived_decisions(
    path: Path,
    milestone_index: dict[str, MilestoneInfo],
    optimus_earliest_hours: float,
    median_hours: float,
) -> list[Decision]:
    raw: str = path.read_text(encoding="utf-8")
    decisions: list[Decision] = []

    blocks = re.split(r"(?=^### D\d+:)", raw, flags=re.MULTILINE)
    for block in blocks:
        m = re.match(r"^### (D\d+):", block.strip())
        if m is None:
            continue
        d_id: str = m.group(1)
        when_raw: str = _field_from_block(block, "When")
        scope: str = _field_from_block(block, "Scope")
        choice_text: str = _choice_from_block(block)
        rationale_text: str = _rationale_from_block(block)
        superseded_by: str | None = _superseded_by_from_block(block)

        created_at_hours: float = _derive_hours(
            when_raw, milestone_index, optimus_earliest_hours, median_hours
        )
        locked: bool = False  # archived decisions are not locked
        content_type: ContentType = _classify(scope, locked)
        is_inherited: bool = when_raw.strip().lower() == "inherited"
        primary_mid: str | None = extract_primary_milestone(when_raw)

        decisions.append(
            Decision(
                d_id=d_id,
                when_raw=when_raw,
                scope=scope,
                decision_text=d_id,
                choice_text=choice_text,
                rationale_text=rationale_text,
                revisable_raw="Yes",
                made_by="unknown",
                superseded_by=superseded_by,
                is_archived=True,
                created_at_hours=created_at_hours,
                content_type=content_type,
                locked=locked,
                is_inherited=is_inherited,
                milestone_id=primary_mid,
                session_velocity=1.0,  # filled in populate_velocities()
            )
        )

    print(f"[parse] archived decisions: {len(decisions)}", file=sys.stderr)
    return decisions


# ============================================================
# Velocity computation (second pass)
# ============================================================


def populate_velocities(
    decisions: list[Decision],
    milestone_index: dict[str, MilestoneInfo],
) -> None:
    """Compute and store session velocity for each decision.

    - Group decisions by primary milestone ID.
    - Count decisions per milestone, populate MilestoneInfo.decision_count.
    - velocity = count / milestone_duration_hours.
    - Decisions with no milestone get velocity = 1.0 (assumed deep work).
    - "inherited" decisions get velocity = 1.0.
    """
    # Count decisions per milestone
    milestone_counts: dict[str, int] = {}
    for d in decisions:
        if d.milestone_id is not None and not d.is_inherited:
            milestone_counts[d.milestone_id] = (
                milestone_counts.get(d.milestone_id, 0) + 1
            )

    # Update MilestoneInfo counts
    for mid, count in milestone_counts.items():
        if mid in milestone_index:
            milestone_index[mid].decision_count = count

    # Assign velocity to each decision
    for d in decisions:
        if d.is_inherited or d.milestone_id is None:
            d.session_velocity = 1.0
        elif d.milestone_id in milestone_index:
            info: MilestoneInfo = milestone_index[d.milestone_id]
            info.decision_count = milestone_counts.get(d.milestone_id, 0)
            d.session_velocity = info.velocity
        else:
            d.session_velocity = 1.0


# ============================================================
# Correction cluster loading
# ============================================================


def load_correction_clusters(path: Path) -> list[CorrectionCluster]:
    with path.open("r", encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)

    clusters: list[CorrectionCluster] = []
    for cluster in list[dict[str, Any]](data.get("topic_clusters", [])):
        timestamps: list[str] = [
            str(ov["timestamp"])
            for ov in list[dict[str, Any]](cluster.get("overrides", []))
            if "timestamp" in ov
        ]
        clusters.append(
            CorrectionCluster(
                topic_id=str(cluster["topic_id"]),
                description=str(cluster.get("description", "")),
                decision_refs=list[str](cluster.get("decision_refs", [])),
                correction_timestamps=timestamps,
                is_memory_failure=bool(cluster.get("is_memory_failure", False)),
            )
        )

    total: int = sum(len(c.correction_timestamps) for c in clusters)
    mf_count: int = sum(1 for c in clusters if c.is_memory_failure)
    print(
        f"[load] {len(clusters)} clusters, {mf_count} memory-failure, "
        f"{total} total correction events",
        file=sys.stderr,
    )
    return clusters


# ============================================================
# Scoring -- Strategy A (flat hour-scale)
# ============================================================


def decay_score_flat(
    decision: Decision,
    current_time_hours: float,
    half_life_hours: float,
) -> float:
    """Flat exponential decay; locked=1.0, superseded=0.01."""
    age_h: float = current_time_hours - decision.created_at_hours
    if age_h < 0.0:
        return 0.0
    if decision.locked:
        return 1.0
    if decision.superseded_by is not None:
        return 0.01
    lam: float = math.log(2.0) / half_life_hours
    return math.exp(-lam * age_h)


# ============================================================
# Scoring -- Strategy B (content-type-aware)
# ============================================================


def decay_score_type_aware(
    decision: Decision,
    current_time_hours: float,
    base_half_life_hours: float,
) -> float:
    """Content-type-differentiated decay using CONTENT_TYPE_MULTIPLIERS."""
    age_h: float = current_time_hours - decision.created_at_hours
    if age_h < 0.0:
        return 0.0
    if decision.locked:
        return 1.0
    if decision.superseded_by is not None:
        return 0.01

    multiplier: float = CONTENT_TYPE_MULTIPLIERS.get(decision.content_type.value, 1.0)
    if multiplier == 0.0:
        # CONSTRAINT with multiplier 0 = never decays (same as locked)
        return 1.0

    effective_hl: float = base_half_life_hours * multiplier
    lam: float = math.log(2.0) / effective_hl
    return math.exp(-lam * age_h)


# ============================================================
# Scoring -- Strategy C (velocity-scaled)
# ============================================================


def decay_score_velocity(
    decision: Decision,
    current_time_hours: float,
    base_half_life_hours: float,
) -> float:
    """Velocity-scaled decay: half_life *= velocity_scale(session_velocity).

    Fast sprint items vanish quickly; deep-work items persist.
    Uses content-type multipliers from Strategy B, then applies velocity scale.
    """
    age_h: float = current_time_hours - decision.created_at_hours
    if age_h < 0.0:
        return 0.0
    if decision.locked:
        return 1.0
    if decision.superseded_by is not None:
        return 0.01

    ct_multiplier: float = CONTENT_TYPE_MULTIPLIERS.get(
        decision.content_type.value, 1.0
    )
    if ct_multiplier == 0.0:
        return 1.0

    vel_scale: float = velocity_scale(decision.session_velocity)
    effective_hl: float = base_half_life_hours * ct_multiplier * vel_scale
    # Floor at 0.1h to avoid numerical issues
    effective_hl = max(effective_hl, 0.1)
    lam: float = math.log(2.0) / effective_hl
    return math.exp(-lam * age_h)


# ============================================================
# Ranking helpers
# ============================================================


def rank_by_scores(
    decisions: list[Decision],
    scores: list[float],
) -> list[tuple[str, float]]:
    """Sort (d_id, score) pairs by score desc, then by recency as tiebreaker."""
    assert len(decisions) == len(scores)
    combined: list[tuple[str, float, float]] = [
        (d.d_id, s, d.created_at_hours) for d, s in zip(decisions, scores)
    ]
    combined.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return [(d_id, score) for d_id, score, _ in combined]


def find_best_rank(
    ranked: list[tuple[str, float]],
    target_ids: set[str],
) -> int | None:
    for i, (d_id, _) in enumerate(ranked):
        if d_id in target_ids:
            return i + 1
    return None


# ============================================================
# Evaluation
# ============================================================


def _score_all_flat(
    decisions: list[Decision],
    current_time_hours: float,
    half_life_hours: float,
) -> list[float]:
    return [decay_score_flat(d, current_time_hours, half_life_hours) for d in decisions]


def evaluate_flat(
    decisions: list[Decision],
    clusters: list[CorrectionCluster],
    half_life_hours: float,
    decision_id_set: set[str],
) -> tuple[list[RankingResult], dict[int, float], dict[str, dict[str, float]]]:
    """Evaluate flat decay strategy against all correction events."""
    results: list[RankingResult] = []

    for cluster in clusters:
        target_ids: set[str] = {
            r for r in cluster.decision_refs if r in decision_id_set
        }
        found_refs: list[str] = sorted(target_ids)

        for ts_iso in cluster.correction_timestamps:
            current_h: float = iso_to_hours(ts_iso)
            scores = _score_all_flat(decisions, current_h, half_life_hours)
            ranked = rank_by_scores(decisions, scores)
            best_rank: int | None = find_best_rank(ranked, target_ids)
            results.append(
                RankingResult(
                    topic_id=cluster.topic_id,
                    correction_iso=ts_iso,
                    correct_refs_found=found_refs,
                    best_rank=best_rank,
                    total_decisions=len(decisions),
                )
            )

    total: int = len(results)
    rates: dict[int, float] = {
        t: sum(1 for r in results if r.best_rank is not None and r.best_rank <= t)
        / total
        if total > 0
        else 0.0
        for t in RANKING_THRESHOLDS
    }

    per_cluster: dict[str, dict[str, float]] = {}
    for cluster in clusters:
        crs = [r for r in results if r.topic_id == cluster.topic_id]
        ct = len(crs)
        per_cluster[cluster.topic_id] = {
            f"top{t}": (
                sum(1 for r in crs if r.best_rank is not None and r.best_rank <= t) / ct
                if ct > 0
                else 0.0
            )
            for t in RANKING_THRESHOLDS
        }

    return results, rates, per_cluster


def evaluate_typed(
    decisions: list[Decision],
    clusters: list[CorrectionCluster],
    base_hl: float,
    decision_id_set: set[str],
    scorer_fn: Callable[[Decision, float, float], float],
) -> tuple[list[RankingResult], dict[int, float], dict[str, dict[str, float]]]:
    """Evaluate a content-type-aware or velocity scorer."""
    results: list[RankingResult] = []

    for cluster in clusters:
        target_ids: set[str] = {
            r for r in cluster.decision_refs if r in decision_id_set
        }
        found_refs: list[str] = sorted(target_ids)

        for ts_iso in cluster.correction_timestamps:
            current_h: float = iso_to_hours(ts_iso)
            scores = [scorer_fn(d, current_h, base_hl) for d in decisions]
            ranked = rank_by_scores(decisions, scores)
            best_rank: int | None = find_best_rank(ranked, target_ids)
            results.append(
                RankingResult(
                    topic_id=cluster.topic_id,
                    correction_iso=ts_iso,
                    correct_refs_found=found_refs,
                    best_rank=best_rank,
                    total_decisions=len(decisions),
                )
            )

    total: int = len(results)
    rates: dict[int, float] = {
        t: sum(1 for r in results if r.best_rank is not None and r.best_rank <= t)
        / total
        if total > 0
        else 0.0
        for t in RANKING_THRESHOLDS
    }

    per_cluster: dict[str, dict[str, float]] = {}
    for cluster in clusters:
        crs = [r for r in results if r.topic_id == cluster.topic_id]
        ct = len(crs)
        per_cluster[cluster.topic_id] = {
            f"top{t}": (
                sum(1 for r in crs if r.best_rank is not None and r.best_rank <= t) / ct
                if ct > 0
                else 0.0
            )
            for t in RANKING_THRESHOLDS
        }

    return results, rates, per_cluster


# ============================================================
# Score distribution histogram
# ============================================================


def score_distribution(scores: list[float]) -> dict[str, int]:
    """Bucket scores into histogram bands."""
    buckets: dict[str, int] = {"gt_0.9": 0, "0.5-0.9": 0, "0.1-0.5": 0, "lt_0.1": 0}
    for s in scores:
        if s > 0.9:
            buckets["gt_0.9"] += 1
        elif s >= 0.5:
            buckets["0.5-0.9"] += 1
        elif s >= 0.1:
            buckets["0.1-0.5"] += 1
        else:
            buckets["lt_0.1"] += 1
    return buckets


# ============================================================
# Locked vs unlocked separation
# ============================================================


def locked_unlocked_separation(
    scores: list[float], decisions: list[Decision]
) -> dict[str, float]:
    locked_s: list[float] = [s for d, s in zip(decisions, scores) if d.locked]
    unlocked_s: list[float] = [
        s for d, s in zip(decisions, scores) if not d.locked and d.superseded_by is None
    ]

    def _mean(lst: list[float]) -> float:
        return sum(lst) / len(lst) if lst else 0.0

    return {
        "locked_mean": _mean(locked_s),
        "unlocked_mean": _mean(unlocked_s),
        "locked_count": len(locked_s),
        "unlocked_count": len(unlocked_s),
        "separation": _mean(locked_s) - _mean(unlocked_s),
    }


# ============================================================
# Strategy A: Flat hour-scale sweep
# ============================================================


def run_strategy_a(
    decisions: list[Decision],
    clusters: list[CorrectionCluster],
    decision_id_set: set[str],
) -> tuple[list[FlatSweepResult], float]:
    """Sweep flat half-lives in hours. Return sweep results and best half-life."""
    print("\n=== Strategy A: Flat Hour-Scale Decay Sweep ===", file=sys.stderr)
    sweep_results: list[FlatSweepResult] = []
    best_hl: float = HALF_LIFE_CANDIDATES_H[0]
    best_score: float = -1.0

    for hl in HALF_LIFE_CANDIDATES_H:
        _, rates, per_cluster = evaluate_flat(decisions, clusters, hl, decision_id_set)
        r5 = rates[5]
        r10 = rates[10]
        r15 = rates[15]
        print(
            f"  hl={hl:6.1f}h  top5={r5:.3f}  top10={r10:.3f}  top15={r15:.3f}",
            file=sys.stderr,
        )
        sweep_results.append(
            FlatSweepResult(
                half_life_hours=hl,
                prevention_rate_top5=r5,
                prevention_rate_top10=r10,
                prevention_rate_top15=r15,
                per_cluster=per_cluster,
            )
        )
        # Prefer top10, use top5 as tiebreaker
        combined: float = r10 + r5 * 0.001
        if combined > best_score:
            best_score = combined
            best_hl = hl

    print(f"  -> Best flat half-life: {best_hl}h", file=sys.stderr)
    return sweep_results, best_hl


# ============================================================
# Strategy B: Content-type-aware
# ============================================================


def run_strategy_b(
    decisions: list[Decision],
    clusters: list[CorrectionCluster],
    decision_id_set: set[str],
    base_hl: float,
    eval_at_hours: float,
) -> StrategyBResult:
    """Content-type-differentiated decay using best flat half-life from A."""
    print(
        f"\n=== Strategy B: Content-Type-Aware (base_hl={base_hl}h) ===",
        file=sys.stderr,
    )
    _, rates, per_cluster = evaluate_typed(
        decisions, clusters, base_hl, decision_id_set, decay_score_type_aware
    )
    print(
        f"  top5={rates[5]:.3f}  top10={rates[10]:.3f}  top15={rates[15]:.3f}",
        file=sys.stderr,
    )

    # Score distribution and locked/unlocked separation at median correction time
    scores_at_eval = [
        decay_score_type_aware(d, eval_at_hours, base_hl) for d in decisions
    ]
    sep = locked_unlocked_separation(scores_at_eval, decisions)
    dist = score_distribution(scores_at_eval)
    print(
        f"  locked_mean={sep['locked_mean']:.3f}  unlocked_mean={sep['unlocked_mean']:.3f}  "
        f"separation={sep['separation']:.3f}",
        file=sys.stderr,
    )
    print(f"  score_dist: {dist}", file=sys.stderr)

    return StrategyBResult(
        base_half_life_hours=base_hl,
        prevention_rate_top5=rates[5],
        prevention_rate_top10=rates[10],
        prevention_rate_top15=rates[15],
        per_cluster=per_cluster,
        locked_unlocked_separation=sep,
        score_distribution=dist,
    )


# ============================================================
# Strategy C: Velocity-scaled
# ============================================================


def run_strategy_c(
    decisions: list[Decision],
    clusters: list[CorrectionCluster],
    decision_id_set: set[str],
    base_hl: float,
    eval_at_hours: float,
) -> StrategyCResult:
    """Velocity-scaled decay: fast sprints get aggressive decay."""
    print(
        f"\n=== Strategy C: Velocity-Scaled Decay (base_hl={base_hl}h) ===",
        file=sys.stderr,
    )
    _, rates, per_cluster = evaluate_typed(
        decisions, clusters, base_hl, decision_id_set, decay_score_velocity
    )
    print(
        f"  top5={rates[5]:.3f}  top10={rates[10]:.3f}  top15={rates[15]:.3f}",
        file=sys.stderr,
    )

    scores_at_eval = [
        decay_score_velocity(d, eval_at_hours, base_hl) for d in decisions
    ]
    sep = locked_unlocked_separation(scores_at_eval, decisions)
    dist = score_distribution(scores_at_eval)
    print(
        f"  locked_mean={sep['locked_mean']:.3f}  unlocked_mean={sep['unlocked_mean']:.3f}  "
        f"separation={sep['separation']:.3f}",
        file=sys.stderr,
    )
    print(f"  score_dist: {dist}", file=sys.stderr)

    # Velocity distribution across decisions
    velocity_buckets: dict[str, int] = {
        "very_fast_gt10": 0,
        "moderate_5to10": 0,
        "medium_2to5": 0,
        "deep_lt2": 0,
    }
    for d in decisions:
        v: float = d.session_velocity
        if v > VELOCITY_FAST:
            velocity_buckets["very_fast_gt10"] += 1
        elif v >= VELOCITY_MOD_LO:
            velocity_buckets["moderate_5to10"] += 1
        elif v >= VELOCITY_DEEP_LO:
            velocity_buckets["medium_2to5"] += 1
        else:
            velocity_buckets["deep_lt2"] += 1
    print(f"  velocity distribution: {velocity_buckets}", file=sys.stderr)

    return StrategyCResult(
        base_half_life_hours=base_hl,
        prevention_rate_top5=rates[5],
        prevention_rate_top10=rates[10],
        prevention_rate_top15=rates[15],
        per_cluster=per_cluster,
        locked_unlocked_separation=sep,
        score_distribution=dist,
    )


# ============================================================
# CS-005 Simulation
# ============================================================


def run_cs005_simulation(
    decisions: list[Decision],
    milestone_index: dict[str, MilestoneInfo],
    base_hl: float,
) -> CS005Result:
    """Simulate the CS-005 scenario: a new session reviews fast-sprint decisions.

    Identify the fastest milestone (highest velocity), then evaluate all
    decisions at (milestone_end + 12h) using Strategy C (velocity-scaled).
    Report: do fast-sprint decisions rank below locked constraints?
    """
    print("\n=== CS-005 Simulation ===", file=sys.stderr)

    # Find the fastest milestone that has decisions
    milestones_with_decisions: list[MilestoneInfo] = [
        info for info in milestone_index.values() if info.decision_count > 0
    ]
    if not milestones_with_decisions:
        # Fallback: compute from decision data
        mid_counts: dict[str, int] = {}
        mid_last: dict[str, float] = {}
        for d in decisions:
            if d.milestone_id is not None:
                mid_counts[d.milestone_id] = mid_counts.get(d.milestone_id, 0) + 1
                mid_last[d.milestone_id] = max(
                    mid_last.get(d.milestone_id, 0.0), d.created_at_hours
                )
        # Use first available milestone
        fastest_mid = max(mid_counts, key=lambda k: mid_counts[k])
        fastest_velocity = 0.0
        eval_at = mid_last.get(fastest_mid, 0.0) + 12.0
    else:
        fastest: MilestoneInfo = max(
            milestones_with_decisions, key=lambda x: x.velocity
        )
        fastest_mid = fastest.milestone_id
        fastest_velocity = fastest.velocity
        eval_at = fastest.last_commit_hours + 12.0

    print(f"  Fastest milestone: {fastest_mid}", file=sys.stderr)
    print(f"  Velocity: {fastest_velocity:.2f} decisions/hour", file=sys.stderr)
    print(f"  Evaluation time: t={eval_at:.1f}h (milestone_end + 12h)", file=sys.stderr)

    # Decisions from the fastest milestone
    fast_sprint_decisions: list[Decision] = [
        d for d in decisions if d.milestone_id == fastest_mid
    ]
    locked_decisions: list[Decision] = [d for d in decisions if d.locked]
    inherited_decisions: list[Decision] = [
        d for d in decisions if d.is_inherited and not d.locked
    ]

    print(
        f"  fast_sprint_decisions={len(fast_sprint_decisions)} "
        f"locked={len(locked_decisions)} inherited={len(inherited_decisions)}",
        file=sys.stderr,
    )

    # Score all decisions
    all_scores: list[float] = [
        decay_score_velocity(d, eval_at, base_hl) for d in decisions
    ]
    ranked_all: list[tuple[str, float]] = rank_by_scores(decisions, all_scores)

    # Build rank lookup
    rank_lookup: dict[str, int] = {
        d_id: i + 1 for i, (d_id, _) in enumerate(ranked_all)
    }
    score_lookup: dict[str, float] = {d_id: s for d_id, s in ranked_all}

    def _avg_score(ds: list[Decision]) -> float:
        if not ds:
            return 0.0
        return sum(score_lookup.get(d.d_id, 0.0) for d in ds) / len(ds)

    fast_avg = _avg_score(fast_sprint_decisions)
    locked_avg = _avg_score(locked_decisions)
    inherited_avg = _avg_score(inherited_decisions)

    fast_sprint_below_locked: bool = fast_avg < locked_avg

    print(
        f"  fast_sprint_avg={fast_avg:.4f}  locked_avg={locked_avg:.4f}  "
        f"inherited_avg={inherited_avg:.4f}",
        file=sys.stderr,
    )
    print(
        f"  fast_sprint_below_locked: {fast_sprint_below_locked}",
        file=sys.stderr,
    )

    # Show top-ranked fast sprint decisions
    fast_ranks: list[tuple[str, int, float]] = sorted(
        [
            (d.d_id, rank_lookup.get(d.d_id, 9999), score_lookup.get(d.d_id, 0.0))
            for d in fast_sprint_decisions
        ],
        key=lambda x: x[1],
    )[:20]  # limit to top 20

    locked_ranks: list[tuple[str, int, float]] = sorted(
        [
            (d.d_id, rank_lookup.get(d.d_id, 9999), score_lookup.get(d.d_id, 0.0))
            for d in locked_decisions
        ],
        key=lambda x: x[1],
    )[:10]

    inherited_ranks: list[tuple[str, int, float]] = sorted(
        [
            (d.d_id, rank_lookup.get(d.d_id, 9999), score_lookup.get(d.d_id, 0.0))
            for d in inherited_decisions
        ],
        key=lambda x: x[1],
    )[:10]

    print("\n  Top fast-sprint decisions (rank, score):", file=sys.stderr)
    for d_id, rank, score in fast_ranks[:5]:
        print(f"    {d_id}: rank={rank} score={score:.4f}", file=sys.stderr)

    print("  Locked decisions (rank, score):", file=sys.stderr)
    for d_id, rank, score in locked_ranks[:5]:
        print(f"    {d_id}: rank={rank} score={score:.4f}", file=sys.stderr)

    return CS005Result(
        fastest_milestone_id=fastest_mid,
        fastest_milestone_velocity=fastest_velocity,
        fast_sprint_decision_count=len(fast_sprint_decisions),
        eval_at_hours=eval_at,
        fast_sprint_avg_score=fast_avg,
        locked_avg_score=locked_avg,
        inherited_avg_score=inherited_avg,
        fast_sprint_below_locked=fast_sprint_below_locked,
        fast_sprint_ranks=fast_ranks,
        locked_ranks=locked_ranks,
        inherited_ranks=inherited_ranks,
    )


# ============================================================
# Main
# ============================================================


def main() -> None:
    print("=== Exp 58c: Hour-Scale Decay + Velocity-Scaled Decay ===", file=sys.stderr)

    # --- Step 1: Git log index (in hours) ---
    print("\n[git] Building milestone hour index from 3 repos...", file=sys.stderr)
    milestone_index: dict[str, MilestoneInfo] = build_milestone_hour_index(
        [
            OPTIMUS_PRIME_REPO,
            ALPHA_SEEK_REPO,
            ALPHA_SEEK_MEMTEST_REPO,
        ]
    )

    # Optimus-prime earliest commit (hours since epoch) for "inherited" decisions
    print("[git] Fetching project-b earliest commit...", file=sys.stderr)
    op_result = subprocess.run(
        ["git", "log", "--all", "--format=%ad", "--date=iso", "--reverse"],
        cwd=str(OPTIMUS_PRIME_REPO),
        capture_output=True,
        text=True,
        check=True,
    )
    optimus_earliest_hours: float = 0.0
    for raw_line in op_result.stdout.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            optimus_earliest_hours = git_date_to_hours(raw_line[:25])
            break
        except ValueError:
            continue
    print(
        f"[git] project-b earliest: {optimus_earliest_hours:.1f}h since epoch "
        f"({optimus_earliest_hours / 24:.1f} days)",
        file=sys.stderr,
    )

    all_milestone_hours: list[float] = sorted(
        info.first_commit_hours for info in milestone_index.values()
    )
    mid_idx: int = len(all_milestone_hours) // 2
    median_hours: float = (
        all_milestone_hours[mid_idx] if all_milestone_hours else optimus_earliest_hours
    )
    print(
        f"[git] milestone hour range: {min(all_milestone_hours):.1f}h - "
        f"{max(all_milestone_hours):.1f}h  median={median_hours:.1f}h",
        file=sys.stderr,
    )

    # --- Step 2: Parse decisions ---
    print("\n[parse] Loading decisions...", file=sys.stderr)
    active: list[Decision] = load_active_decisions(
        DECISIONS_MD, milestone_index, optimus_earliest_hours, median_hours
    )
    archived: list[Decision] = load_archived_decisions(
        ARCHIVE_MD, milestone_index, optimus_earliest_hours, median_hours
    )
    all_decisions: list[Decision] = active + archived

    print(
        f"[parse] total: {len(all_decisions)} ({len(active)} active + {len(archived)} archived)",
        file=sys.stderr,
    )

    # --- Step 3: Populate session velocities ---
    populate_velocities(all_decisions, milestone_index)

    # Summary stats
    created_hours: list[float] = [d.created_at_hours for d in all_decisions]
    span_h: float = max(created_hours) - min(created_hours)
    locked_count: int = sum(1 for d in all_decisions if d.locked)
    inherited_count: int = sum(1 for d in all_decisions if d.is_inherited)
    superseded_count: int = sum(1 for d in all_decisions if d.superseded_by is not None)
    type_counts: dict[str, int] = {}
    for d in all_decisions:
        type_counts[d.content_type.value] = type_counts.get(d.content_type.value, 0) + 1

    print(
        f"[parse] span: {span_h:.0f}h ({span_h / 24:.1f}d, {span_h / 720:.1f} months)",
        file=sys.stderr,
    )
    print(
        f"[parse] locked={locked_count} inherited={inherited_count} superseded={superseded_count}",
        file=sys.stderr,
    )
    print(f"[parse] content types: {type_counts}", file=sys.stderr)

    # Velocity distribution summary
    velocities: list[float] = [
        d.session_velocity for d in all_decisions if not d.is_inherited
    ]
    if velocities:
        velocities_sorted = sorted(velocities)
        n_v = len(velocities_sorted)
        med_vel = velocities_sorted[n_v // 2]
        print(
            f"[velocity] n={n_v} min={min(velocities):.2f} max={max(velocities):.2f} "
            f"median={med_vel:.2f} decisions/hour",
            file=sys.stderr,
        )

    # --- Step 4: Load corrections ---
    print("\n[load] Loading correction clusters...", file=sys.stderr)
    all_clusters: list[CorrectionCluster] = load_correction_clusters(EXP6_FAILURES)
    mf_clusters: list[CorrectionCluster] = [
        c for c in all_clusters if c.is_memory_failure
    ]

    decision_id_set: set[str] = {d.d_id for d in all_decisions}
    active_clusters: list[CorrectionCluster] = [
        c for c in mf_clusters if any(ref in decision_id_set for ref in c.decision_refs)
    ]
    print(
        f"[load] active_clusters: {len(active_clusters)} / {len(mf_clusters)}",
        file=sys.stderr,
    )
    for c in active_clusters:
        known = [r for r in c.decision_refs if r in decision_id_set]
        print(
            f"  {c.topic_id}: known_refs={known} events={len(c.correction_timestamps)}",
            file=sys.stderr,
        )

    total_events: int = sum(len(c.correction_timestamps) for c in active_clusters)

    # Median correction time for secondary analyses
    all_corr_hours: list[float] = sorted(
        iso_to_hours(ts) for c in active_clusters for ts in c.correction_timestamps
    )
    mid_corr: int = len(all_corr_hours) // 2
    eval_at_hours: float = all_corr_hours[mid_corr] if all_corr_hours else median_hours

    # --- Step 5: Baseline (no decay, flat with large half-life) ---
    # Using half-life=720h (1 month) as "effectively no decay" baseline
    print("\n[baseline] Flat half-life=720h (effectively no decay):", file=sys.stderr)
    _, baseline_rates, baseline_per_cluster = evaluate_flat(
        all_decisions, active_clusters, 720.0, decision_id_set
    )
    print(
        f"  top5={baseline_rates[5]:.3f}  top10={baseline_rates[10]:.3f}  "
        f"top15={baseline_rates[15]:.3f}",
        file=sys.stderr,
    )

    # --- Step 6: Strategy A ---
    sweep_a, best_hl_a = run_strategy_a(all_decisions, active_clusters, decision_id_set)

    # --- Step 7: Strategy B ---
    result_b = run_strategy_b(
        all_decisions, active_clusters, decision_id_set, best_hl_a, eval_at_hours
    )

    # --- Step 8: Strategy C ---
    result_c = run_strategy_c(
        all_decisions, active_clusters, decision_id_set, best_hl_a, eval_at_hours
    )

    # --- Step 9: CS-005 Simulation ---
    cs005 = run_cs005_simulation(all_decisions, milestone_index, best_hl_a)

    # --- Summary ---
    print("\n=== SUMMARY ===", file=sys.stderr)
    print(
        f"Total decisions: {len(all_decisions)} ({len(active)} active + {len(archived)} archived)",
        file=sys.stderr,
    )
    print(
        f"Temporal span: {span_h:.0f}h ({span_h / 24:.1f}d / {span_h / 720:.1f} months)",
        file=sys.stderr,
    )
    print(f"Content types: {type_counts}", file=sys.stderr)
    print(f"Active correction clusters: {len(active_clusters)}", file=sys.stderr)
    print(f"Total correction events: {total_events}", file=sys.stderr)
    print(
        f"\nBaseline (720h ~ no decay): top5={baseline_rates[5]:.3f}  "
        f"top10={baseline_rates[10]:.3f}  top15={baseline_rates[15]:.3f}",
        file=sys.stderr,
    )
    print(f"Strategy A best half-life: {best_hl_a}h", file=sys.stderr)
    print(
        f"Strategy A best:           top5={sweep_a[-1].prevention_rate_top5:.3f}  "
        f"top10={sweep_a[-1].prevention_rate_top10:.3f}  "
        f"top15={sweep_a[-1].prevention_rate_top15:.3f}",
        file=sys.stderr,
    )
    # Find the actual best result
    best_a = max(
        sweep_a, key=lambda r: r.prevention_rate_top10 + r.prevention_rate_top5 * 0.001
    )
    print(
        f"Strategy A best (hl={best_a.half_life_hours}h): "
        f"top5={best_a.prevention_rate_top5:.3f}  "
        f"top10={best_a.prevention_rate_top10:.3f}  "
        f"top15={best_a.prevention_rate_top15:.3f}",
        file=sys.stderr,
    )
    print(
        f"Strategy B:                top5={result_b.prevention_rate_top5:.3f}  "
        f"top10={result_b.prevention_rate_top10:.3f}  "
        f"top15={result_b.prevention_rate_top15:.3f}",
        file=sys.stderr,
    )
    print(
        f"Strategy C:                top5={result_c.prevention_rate_top5:.3f}  "
        f"top10={result_c.prevention_rate_top10:.3f}  "
        f"top15={result_c.prevention_rate_top15:.3f}",
        file=sys.stderr,
    )
    print(
        f"\nCS-005: fastest_milestone={cs005.fastest_milestone_id} "
        f"velocity={cs005.fastest_milestone_velocity:.2f}/h "
        f"n={cs005.fast_sprint_decision_count}",
        file=sys.stderr,
    )
    print(
        f"  fast_sprint_avg={cs005.fast_sprint_avg_score:.4f}  "
        f"locked_avg={cs005.locked_avg_score:.4f}  "
        f"fast_below_locked={cs005.fast_sprint_below_locked}",
        file=sys.stderr,
    )

    # --- Build and save results JSON ---
    results_json: dict[str, Any] = {
        "experiment": "exp58c_hourscale_decay",
        "date": "2026-04-10",
        "key_change_vs_58b": "All timestamps in HOURS (not days). Adds velocity-scaled decay.",
        "data_sources": {
            "active_decisions": str(DECISIONS_MD),
            "archived_decisions": str(ARCHIVE_MD),
            "corrections": str(EXP6_FAILURES),
            "git_repos": [
                str(OPTIMUS_PRIME_REPO),
                str(ALPHA_SEEK_REPO),
                str(ALPHA_SEEK_MEMTEST_REPO),
            ],
        },
        "summary": {
            "total_decisions": len(all_decisions),
            "active_decisions": len(active),
            "archived_decisions": len(archived),
            "locked_count": locked_count,
            "inherited_count": inherited_count,
            "superseded_count": superseded_count,
            "temporal_span_hours": round(span_h, 1),
            "temporal_span_days": round(span_h / 24, 1),
            "temporal_span_months": round(span_h / 720, 1),
            "active_clusters": len(active_clusters),
            "total_correction_events": total_events,
            "content_type_distribution": type_counts,
        },
        "baseline_720h": {
            "half_life_hours": 720.0,
            "top5": baseline_rates[5],
            "top10": baseline_rates[10],
            "top15": baseline_rates[15],
            "per_cluster": baseline_per_cluster,
        },
        "strategy_a_flat_sweep": [
            {
                "half_life_hours": r.half_life_hours,
                "top5": r.prevention_rate_top5,
                "top10": r.prevention_rate_top10,
                "top15": r.prevention_rate_top15,
                "per_cluster": r.per_cluster,
            }
            for r in sweep_a
        ],
        "strategy_a_best_half_life_hours": best_hl_a,
        "strategy_b_type_aware": {
            "base_half_life_hours": result_b.base_half_life_hours,
            "content_type_multipliers": CONTENT_TYPE_MULTIPLIERS,
            "top5": result_b.prevention_rate_top5,
            "top10": result_b.prevention_rate_top10,
            "top15": result_b.prevention_rate_top15,
            "per_cluster": result_b.per_cluster,
            "locked_unlocked_separation": result_b.locked_unlocked_separation,
            "score_distribution": result_b.score_distribution,
        },
        "strategy_c_velocity_scaled": {
            "base_half_life_hours": result_c.base_half_life_hours,
            "velocity_thresholds": {
                "very_fast_gt10_scale": 0.1,
                "moderate_5to10_scale": 0.5,
                "medium_2to5_scale": 0.8,
                "deep_lt2_scale": 1.0,
            },
            "top5": result_c.prevention_rate_top5,
            "top10": result_c.prevention_rate_top10,
            "top15": result_c.prevention_rate_top15,
            "per_cluster": result_c.per_cluster,
            "locked_unlocked_separation": result_c.locked_unlocked_separation,
            "score_distribution": result_c.score_distribution,
        },
        "cs005_simulation": {
            "scenario": "CS-005: new agent mistakes fast-sprint findings for months of research",
            "fastest_milestone_id": cs005.fastest_milestone_id,
            "fastest_milestone_velocity_per_hour": round(
                cs005.fastest_milestone_velocity, 4
            ),
            "fast_sprint_decision_count": cs005.fast_sprint_decision_count,
            "eval_at_hours": round(cs005.eval_at_hours, 2),
            "eval_description": "milestone_end + 12 hours (simulating next session)",
            "fast_sprint_avg_score": round(cs005.fast_sprint_avg_score, 6),
            "locked_avg_score": round(cs005.locked_avg_score, 6),
            "inherited_avg_score": round(cs005.inherited_avg_score, 6),
            "fast_sprint_below_locked": cs005.fast_sprint_below_locked,
            "fast_sprint_ranks": [
                {"d_id": d_id, "rank": rank, "score": round(score, 6)}
                for d_id, rank, score in cs005.fast_sprint_ranks
            ],
            "locked_ranks": [
                {"d_id": d_id, "rank": rank, "score": round(score, 6)}
                for d_id, rank, score in cs005.locked_ranks
            ],
            "inherited_ranks": [
                {"d_id": d_id, "rank": rank, "score": round(score, 6)}
                for d_id, rank, score in cs005.inherited_ranks
            ],
        },
    }

    RESULTS_PATH.write_text(json.dumps(results_json, indent=2), encoding="utf-8")
    print(f"\n[done] Results saved to {RESULTS_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
