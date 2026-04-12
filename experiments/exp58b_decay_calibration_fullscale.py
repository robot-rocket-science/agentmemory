"""Exp 58b: Decay Half-Life Calibration -- Full Scale (4-Month Lineage)

Extends Exp 58 by replacing the narrow 13-day alpha-seek spike DB with 4 months
of real project history: optimus-prime (Dec 2025 - Mar 2026) -> alpha-seek
(Mar-Apr 2026) -> alpha-seek-memtest (Mar-Apr 2026).

Data sources:
  - /Users/thelorax/projects/alpha-seek-memtest/.gsd/DECISIONS.md (183 active)
  - /Users/thelorax/projects/alpha-seek/docs/DECISIONS-ARCHIVE.md (35 superseded)
  - /Users/thelorax/projects/agentmemory/experiments/exp6_failures_v2.json (38 corrections)
  - git log from optimus-prime + alpha-seek + alpha-seek-memtest repos

Research questions:
  1. Are half-lives still insensitive at 4-month scale (13 days was too short)?
  2. Do superseded decisions rank below their replacements at all half-lives?
  3. Do inherited (optimus-prime) decisions decay to near-zero by alpha-seek phase?
  4. What half-life achieves best correction prevention for each content type?

Additional analyses vs Exp 58:
  - Decay factor distribution at each half-life setting
  - Locked vs unlocked separation by half-life
  - Superseded vs active ordering check
  - Inherited (optimus-prime) vs recent (alpha-seek) score comparison
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
from typing import Final

# ============================================================
# Paths
# ============================================================

DECISIONS_MD: Final[Path] = Path(
    "/Users/thelorax/projects/alpha-seek-memtest/.gsd/DECISIONS.md"
)
ARCHIVE_MD: Final[Path] = Path(
    "/Users/thelorax/projects/alpha-seek/docs/DECISIONS-ARCHIVE.md"
)
EXP6_FAILURES: Final[Path] = Path(
    "/Users/thelorax/projects/agentmemory/experiments/exp6_failures_v2.json"
)
RESULTS_PATH: Final[Path] = Path(
    "/Users/thelorax/projects/agentmemory/experiments/exp58b_results.json"
)

OPTIMUS_PRIME_REPO: Final[Path] = Path("/Users/thelorax/projects/optimus-prime")
ALPHA_SEEK_REPO: Final[Path] = Path("/Users/thelorax/projects/alpha-seek")
ALPHA_SEEK_MEMTEST_REPO: Final[Path] = Path(
    "/Users/thelorax/projects/alpha-seek-memtest"
)

# ============================================================
# Config
# ============================================================

# Days since PROJECT_EPOCH (Dec 2025 optimus-prime start)
# All timestamps normalised to this.  optimus-prime first commit: 2025-12-01
PROJECT_EPOCH: Final[str] = "2025-12-01T00:00:00+00:00"

# Half-life sweep candidates in days; None = no decay
HALF_LIFE_CANDIDATES: Final[list[float | None]] = [
    1.0, 3.0, 7.0, 14.0, 30.0, 60.0, 90.0, 180.0, None
]

RANKING_THRESHOLDS: Final[list[int]] = [5, 10, 15]

# ============================================================
# Enums and data structures
# ============================================================


class ContentType(Enum):
    CONSTRAINT = "CONSTRAINT"
    EVIDENCE = "EVIDENCE"
    CONTEXT = "CONTEXT"
    PROCEDURE = "PROCEDURE"


# Classification rules (per spec)
SCOPE_CONSTRAINT: Final[frozenset[str]] = frozenset({
    "architecture", "infrastructure", "operations", "agent behavior", "code-quality",
})
SCOPE_EVIDENCE: Final[frozenset[str]] = frozenset({
    "strategy", "signal-model", "backtesting", "evaluation", "validation",
})
SCOPE_CONTEXT: Final[frozenset[str]] = frozenset({
    "milestone", "bugfix", "reporting", "documentation",
})
SCOPE_PROCEDURE: Final[frozenset[str]] = frozenset({
    "methodology", "configuration", "tooling",
})


@dataclass
class Decision:
    d_id: str              # "D002", "D073", etc.
    when_raw: str          # raw "When" field from markdown
    scope: str
    decision_text: str
    choice_text: str
    rationale_text: str
    revisable_raw: str
    made_by: str
    superseded_by: str | None  # D### that supersedes this, or None
    is_archived: bool      # True if from DECISIONS-ARCHIVE.md
    created_at_days: float  # days since PROJECT_EPOCH
    content_type: ContentType
    locked: bool
    is_inherited: bool     # True if when_raw == "inherited"


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
    best_rank: int | None   # 1-indexed; None if not in decisions
    total_decisions: int


@dataclass
class HalfLifeConfig:
    constraint: float | None
    evidence: float | None
    context: float | None
    procedure: float | None

    def get(self, ct: ContentType) -> float | None:
        mapping: dict[ContentType, float | None] = {
            ContentType.CONSTRAINT: self.constraint,
            ContentType.EVIDENCE: self.evidence,
            ContentType.CONTEXT: self.context,
            ContentType.PROCEDURE: self.procedure,
        }
        return mapping[ct]


@dataclass
class SweepResult:
    content_type_swept: str
    half_life: float | None
    prevention_rate_top5: float
    prevention_rate_top10: float
    prevention_rate_top15: float
    per_cluster: dict[str, dict[str, float]] = field(default_factory=dict)


# ============================================================
# Date utilities
# ============================================================

def _epoch_dt() -> datetime:
    return datetime.fromisoformat(PROJECT_EPOCH)


def iso_to_days(iso_str: str) -> float:
    """Convert ISO 8601 string to days since PROJECT_EPOCH."""
    clean: str = iso_str.replace("Z", "+00:00")
    dt: datetime = datetime.fromisoformat(clean)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = dt - _epoch_dt()
    return delta.total_seconds() / 86400.0


# ============================================================
# Git log helpers
# ============================================================

def load_git_log(repo: Path) -> list[tuple[str, str, str]]:
    """Run git log on a repo and return list of (sha, iso_date, subject)."""
    result = subprocess.run(
        [
            "git", "log", "--all", "--format=%H %ad %s", "--date=iso",
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    entries: list[tuple[str, str, str]] = []
    for raw_line in result.stdout.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        # Format: "<sha> <YYYY-MM-DD HH:MM:SS +HHMM> <subject...>"
        # sha is 40 hex chars + space; then date is "YYYY-MM-DD HH:MM:SS +HHMM" (25 chars)
        if len(raw_line) < 67:
            continue
        sha: str = raw_line[:40]
        date_str: str = raw_line[41:66]   # "YYYY-MM-DD HH:MM:SS +HHMM"
        subject: str = raw_line[67:]
        entries.append((sha, date_str.strip(), subject))
    return entries


def build_milestone_date_index(
    repos: list[Path],
) -> dict[str, float]:
    """Search git logs across repos to find the first commit referencing each milestone ID.

    Milestone IDs have the form M###-xxxxxx (e.g., M006-wz8eaf).
    Returns: milestone_id -> days since PROJECT_EPOCH (earliest occurrence).
    """
    # Pattern: M followed by digits, dash, 6 alphanumerics
    milestone_pattern: re.Pattern[str] = re.compile(r"M\d+-[a-z0-9]{6}", re.IGNORECASE)

    # Also collect broader prefix patterns for "M006"-style refs (no hash suffix)
    prefix_pattern: re.Pattern[str] = re.compile(r"\b(M\d+)-[a-z0-9]{6}\b", re.IGNORECASE)

    # milestone_id (full, e.g. "M006-wz8eaf") -> earliest date in days
    full_id_dates: dict[str, float] = {}

    for repo in repos:
        entries = load_git_log(repo)
        for _sha, date_str, subject in entries:
            # Parse date: "YYYY-MM-DD HH:MM:SS +HHMM"
            try:
                dt: datetime = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")
            except ValueError:
                continue
            days: float = (dt - _epoch_dt()).total_seconds() / 86400.0

            matches = milestone_pattern.findall(subject)
            for m in matches:
                m_upper = m.upper()
                if m_upper not in full_id_dates or days < full_id_dates[m_upper]:
                    full_id_dates[m_upper] = days

    # Also build prefix -> earliest date (e.g. "M006" -> earliest M006-xxx date)
    prefix_dates: dict[str, float] = {}
    for full_id, days in full_id_dates.items():
        prefix = full_id.split("-")[0].upper()
        if prefix not in prefix_dates or days < prefix_dates[prefix]:
            prefix_dates[prefix] = days

    print(
        f"[git] milestone IDs with git dates: {len(full_id_dates)} full, "
        f"{len(prefix_dates)} unique prefixes",
        file=sys.stderr,
    )
    return full_id_dates


def extract_milestone_ids_from_when(when_raw: str) -> list[str]:
    """Extract milestone IDs from a 'When' field string.

    Handles forms like:
      - "M001-vfx89r S02 T01"
      - "M002-ocnmgv planning, post-M001-vfx89r seal"
      - "M008-xnku0q S03"
      - "cross-examine 260402-38, M030-n5kwzk"
      - "inherited" -> returns []
    """
    pattern: re.Pattern[str] = re.compile(r"M\d+-[a-z0-9]{6}", re.IGNORECASE)
    return [m.upper() for m in pattern.findall(when_raw)]


# ============================================================
# Markdown parsers
# ============================================================

_PIPE_SPLIT: re.Pattern[str] = re.compile(r"\s*\|\s*")


def _parse_decisions_md_row(line: str) -> tuple[str, ...] | None:
    """Parse a markdown table row like '| D002 | inherited | arch | ... |'.

    Returns (d_id, when_raw, scope, decision, choice, rationale, revisable, made_by)
    or None if the line doesn't match.
    """
    line = line.strip()
    if not line.startswith("| D"):
        return None
    # Strip leading/trailing pipes
    inner: str = line.strip("|")
    parts: list[str] = [p.strip() for p in inner.split("|")]
    if len(parts) < 8:
        return None
    d_id = parts[0].strip()
    if not re.match(r"D\d+$", d_id):
        return None
    # Columns: #, When, Scope, Decision, Choice, Rationale, Revisable?, Made By
    return (
        parts[0].strip(),   # D###
        parts[1].strip(),   # When
        parts[2].strip(),   # Scope
        parts[3].strip(),   # Decision
        parts[4].strip(),   # Choice
        parts[5].strip(),   # Rationale
        parts[6].strip(),   # Revisable?
        parts[7].strip(),   # Made By
    )


def _find_supersedes_in_text(text: str) -> list[str]:
    """Extract D### references from 'Supersedes D###' patterns in free text."""
    return re.findall(r"[Ss]upersedes?\s+(D\d+)", text)


def load_active_decisions(
    path: Path,
    milestone_dates: dict[str, float],
    optimus_earliest_days: float,
    median_days: float,
) -> list[Decision]:
    """Parse DECISIONS.md markdown table into Decision objects."""
    raw: str = path.read_text(encoding="utf-8")
    decisions: list[Decision] = []

    for line in raw.splitlines():
        parsed = _parse_decisions_md_row(line)
        if parsed is None:
            continue
        d_id, when_raw, scope, decision_text, choice_text, rationale_text, revisable_raw, made_by = parsed

        # Derive timestamp
        created_at_days: float = _derive_timestamp(
            when_raw, milestone_dates, optimus_earliest_days, median_days
        )

        # Check if superseded from text
        superseded_by: str | None = None
        combined_text: str = choice_text + " " + rationale_text
        supers_refs: list[str] = _find_supersedes_in_text(combined_text)
        # This is decisions that SUPERSEDE others; the decision itself is not superseded
        # (superseded decisions are in archive). No superseded_by for active decisions.

        locked: bool = revisable_raw.strip().lower().startswith("no")
        content_type: ContentType = _classify(scope, locked)
        is_inherited: bool = when_raw.strip().lower() == "inherited"

        decisions.append(Decision(
            d_id=d_id,
            when_raw=when_raw,
            scope=scope,
            decision_text=decision_text,
            choice_text=choice_text,
            rationale_text=rationale_text,
            revisable_raw=revisable_raw,
            made_by=made_by,
            superseded_by=None,  # active decisions are not superseded
            is_archived=False,
            created_at_days=created_at_days,
            content_type=content_type,
            locked=locked,
            is_inherited=is_inherited,
        ))

    print(f"[parse] active decisions: {len(decisions)}", file=sys.stderr)
    return decisions


def _superseded_by_from_archive_block(block: str) -> str | None:
    """Extract 'Superseded by: D###' from an archive block."""
    m = re.search(r"\*\*Superseded by:\*\*\s*(D\d+)", block, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def _when_from_archive_block(block: str) -> str:
    m = re.search(r"\*\*When:\*\*\s*([^\n]+)", block)
    if m:
        return m.group(1).strip()
    return ""


def _scope_from_archive_block(block: str) -> str:
    m = re.search(r"\*\*Scope:\*\*\s*([^\n]+)", block)
    if m:
        return m.group(1).strip()
    return ""


def _choice_from_archive_block(block: str) -> str:
    m = re.search(r"\*\*Choice:\*\*\s*([\s\S]*?)(?=\*\*Rationale:|$)", block)
    if m:
        return m.group(1).strip()
    return ""


def _rationale_from_archive_block(block: str) -> str:
    m = re.search(r"\*\*Rationale:\*\*\s*([\s\S]*?)(?=###|$)", block)
    if m:
        return m.group(1).strip()
    return ""


def load_archived_decisions(
    path: Path,
    milestone_dates: dict[str, float],
    optimus_earliest_days: float,
    median_days: float,
) -> list[Decision]:
    """Parse DECISIONS-ARCHIVE.md into Decision objects (all superseded)."""
    raw: str = path.read_text(encoding="utf-8")
    decisions: list[Decision] = []

    # Split on ### D### headers
    blocks = re.split(r"(?=^### D\d+:)", raw, flags=re.MULTILINE)
    for block in blocks:
        m = re.match(r"^### (D\d+):", block.strip())
        if m is None:
            continue
        d_id: str = m.group(1)
        when_raw: str = _when_from_archive_block(block)
        scope: str = _scope_from_archive_block(block)
        choice_text: str = _choice_from_archive_block(block)
        rationale_text: str = _rationale_from_archive_block(block)
        superseded_by: str | None = _superseded_by_from_archive_block(block)

        created_at_days: float = _derive_timestamp(
            when_raw, milestone_dates, optimus_earliest_days, median_days
        )

        # Archived decisions are never locked (they were superseded)
        locked: bool = False
        content_type: ContentType = _classify(scope, locked)
        is_inherited: bool = when_raw.strip().lower() == "inherited"

        decisions.append(Decision(
            d_id=d_id,
            when_raw=when_raw,
            scope=scope,
            decision_text=d_id,    # archive format doesn't always have separate decision text
            choice_text=choice_text,
            rationale_text=rationale_text,
            revisable_raw="Yes",
            made_by="unknown",
            superseded_by=superseded_by,
            is_archived=True,
            created_at_days=created_at_days,
            content_type=content_type,
            locked=locked,
            is_inherited=is_inherited,
        ))

    print(f"[parse] archived decisions: {len(decisions)}", file=sys.stderr)
    return decisions


def _derive_timestamp(
    when_raw: str,
    milestone_dates: dict[str, float],
    optimus_earliest_days: float,
    median_days: float,
) -> float:
    """Derive a float timestamp (days since PROJECT_EPOCH) from a 'When' field."""
    if when_raw.strip().lower() == "inherited":
        return optimus_earliest_days

    # Extract milestone IDs and find the earliest git date
    milestone_ids: list[str] = extract_milestone_ids_from_when(when_raw)
    matched_days: list[float] = []
    for mid in milestone_ids:
        if mid in milestone_dates:
            matched_days.append(milestone_dates[mid])

    if matched_days:
        return min(matched_days)

    # Try prefix matching: extract "MXXX" prefixes and look for any milestone in that prefix
    prefix_pattern: re.Pattern[str] = re.compile(r"\b(M\d+)\b", re.IGNORECASE)
    prefixes: list[str] = [p.upper() for p in prefix_pattern.findall(when_raw)]
    for prefix in prefixes:
        for mid, d in milestone_dates.items():
            if mid.startswith(prefix):
                matched_days.append(d)
    if matched_days:
        return min(matched_days)

    return median_days


# ============================================================
# Content type classification
# ============================================================

def _classify(scope: str, locked: bool) -> ContentType:
    """Classify a decision by scope and locked status per experiment spec."""
    scope_lower: str = scope.lower().strip()

    # CONSTRAINT: scope in constraint set AND locked
    if locked and scope_lower in SCOPE_CONSTRAINT:
        return ContentType.CONSTRAINT
    # CONSTRAINT: code-quality + locked (spec includes code-quality)
    if locked and scope_lower == "code-quality":
        return ContentType.CONSTRAINT

    # EVIDENCE: scope in evidence set (revisable or not)
    if scope_lower in SCOPE_EVIDENCE:
        return ContentType.EVIDENCE

    # CONTEXT: milestone, bugfix, reporting, documentation
    if scope_lower in SCOPE_CONTEXT:
        return ContentType.CONTEXT

    # PROCEDURE: methodology, configuration, tooling
    if scope_lower in SCOPE_PROCEDURE:
        return ContentType.PROCEDURE

    # Unlocked constraint-type scopes -> EVIDENCE (revisable architecture etc.)
    if scope_lower in SCOPE_CONSTRAINT:
        return ContentType.EVIDENCE

    # Default
    return ContentType.EVIDENCE


# ============================================================
# Correction cluster loading
# ============================================================

def load_correction_clusters(path: Path) -> list[CorrectionCluster]:
    with path.open("r", encoding="utf-8") as fh:
        data: dict = json.load(fh)

    clusters: list[CorrectionCluster] = []
    for cluster in data.get("topic_clusters", []):
        timestamps: list[str] = [
            ov["timestamp"]
            for ov in cluster.get("overrides", [])
            if "timestamp" in ov
        ]
        clusters.append(CorrectionCluster(
            topic_id=cluster["topic_id"],
            description=cluster.get("description", ""),
            decision_refs=cluster.get("decision_refs", []),
            correction_timestamps=timestamps,
            is_memory_failure=cluster.get("is_memory_failure", False),
        ))

    print(
        f"[load] {len(clusters)} total clusters, "
        f"{sum(1 for c in clusters if c.is_memory_failure)} memory-failure clusters",
        file=sys.stderr,
    )
    total: int = sum(len(c.correction_timestamps) for c in clusters)
    print(f"[load] total correction events: {total}", file=sys.stderr)
    return clusters


# ============================================================
# Scoring and ranking
# ============================================================

def decay_score(
    decision: Decision,
    current_time_days: float,
    half_lives: HalfLifeConfig,
) -> float:
    """Compute decay score for a decision at a given time.

    - Decision not yet created: 0.0
    - Locked: 1.0 (no decay regardless of age)
    - Superseded: 0.01 (demoted but visible for history)
    - Otherwise: exponential decay by half-life for content type
    """
    age: float = current_time_days - decision.created_at_days
    if age < 0.0:
        return 0.0

    if decision.locked:
        return 1.0

    if decision.superseded_by is not None:
        return 0.01

    half_life: float | None = half_lives.get(decision.content_type)
    if half_life is None:
        return 1.0

    if age == 0.0:
        return 1.0

    lam: float = math.log(2.0) / half_life
    return math.exp(-lam * age)


def rank_decisions(
    decisions: list[Decision],
    current_time_days: float,
    half_lives: HalfLifeConfig,
) -> list[tuple[str, float]]:
    """Return (d_id, score) pairs sorted by score descending.

    Tiebreaker: more recent decisions rank higher within the same score bucket.
    """
    scored: list[tuple[str, float, float]] = [
        (d.d_id, decay_score(d, current_time_days, half_lives), d.created_at_days)
        for d in decisions
    ]
    scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return [(d_id, s) for d_id, s, _ in scored]


def find_best_rank(
    ranked: list[tuple[str, float]],
    target_ids: set[str],
) -> int | None:
    for i, (d_id, _score) in enumerate(ranked):
        if d_id in target_ids:
            return i + 1
    return None


# ============================================================
# Evaluation
# ============================================================

def evaluate_config(
    decisions: list[Decision],
    clusters: list[CorrectionCluster],
    half_lives: HalfLifeConfig,
) -> tuple[list[RankingResult], dict[int, float], dict[str, dict[str, float]]]:
    """Evaluate a half-life config against all correction events.

    Returns:
      - list[RankingResult]
      - prevention rates {5: float, 10: float, 15: float}
      - per-cluster breakdown {topic_id: {top5: float, ...}}
    """
    decision_ids: set[str] = {d.d_id for d in decisions}
    results: list[RankingResult] = []

    for cluster in clusters:
        target_ids: set[str] = {
            ref for ref in cluster.decision_refs if ref in decision_ids
        }
        found_refs: list[str] = sorted(target_ids)

        for ts_iso in cluster.correction_timestamps:
            current_days: float = iso_to_days(ts_iso)
            ranked: list[tuple[str, float]] = rank_decisions(
                decisions, current_days, half_lives
            )
            best_rank: int | None = find_best_rank(ranked, target_ids)
            results.append(RankingResult(
                topic_id=cluster.topic_id,
                correction_iso=ts_iso,
                correct_refs_found=found_refs,
                best_rank=best_rank,
                total_decisions=len(decisions),
            ))

    total: int = len(results)
    threshold_rates: dict[int, float] = {}
    for thresh in RANKING_THRESHOLDS:
        hits: int = sum(
            1 for r in results
            if r.best_rank is not None and r.best_rank <= thresh
        )
        threshold_rates[thresh] = hits / total if total > 0 else 0.0

    per_cluster: dict[str, dict[str, float]] = {}
    for cluster in clusters:
        cluster_results: list[RankingResult] = [
            r for r in results if r.topic_id == cluster.topic_id
        ]
        ct_total: int = len(cluster_results)
        ct_rates: dict[str, float] = {}
        for thresh in RANKING_THRESHOLDS:
            hits = sum(
                1 for r in cluster_results
                if r.best_rank is not None and r.best_rank <= thresh
            )
            ct_rates[f"top{thresh}"] = hits / ct_total if ct_total > 0 else 0.0
        per_cluster[cluster.topic_id] = ct_rates

    return results, threshold_rates, per_cluster


# ============================================================
# Grid search
# ============================================================

def _make_all_none() -> HalfLifeConfig:
    return HalfLifeConfig(constraint=None, evidence=None, context=None, procedure=None)


def _make_config_vary_one(
    ct: ContentType,
    hl: float | None,
    defaults: dict[ContentType, float | None],
) -> HalfLifeConfig:
    m: dict[ContentType, float | None] = dict(defaults)
    m[ct] = hl
    return HalfLifeConfig(
        constraint=m[ContentType.CONSTRAINT],
        evidence=m[ContentType.EVIDENCE],
        context=m[ContentType.CONTEXT],
        procedure=m[ContentType.PROCEDURE],
    )


def grid_search(
    decisions: list[Decision],
    clusters: list[CorrectionCluster],
) -> tuple[dict[ContentType, float | None], list[SweepResult]]:
    """Per-type independent half-life sweep."""
    defaults: dict[ContentType, float | None] = {ct: None for ct in ContentType}
    all_results: list[SweepResult] = []
    best_per_type: dict[ContentType, float | None] = {}

    print("\n[sweep] Phase 1: per-type independent sweep", file=sys.stderr)

    for ct in ContentType:
        best_hl: float | None = None
        best_score: float = -1.0

        print(f"  [{ct.value}]", file=sys.stderr)
        for hl in HALF_LIFE_CANDIDATES:
            config: HalfLifeConfig = _make_config_vary_one(ct, hl, defaults)
            _, rates, per_cluster = evaluate_config(decisions, clusters, config)
            r5: float = rates[5]
            r10: float = rates[10]
            r15: float = rates[15]

            hl_label: str = f"{hl}d" if hl is not None else "never"
            print(
                f"    hl={hl_label:>7}  top5={r5:.3f}  top10={r10:.3f}  top15={r15:.3f}",
                file=sys.stderr,
            )

            all_results.append(SweepResult(
                content_type_swept=ct.value,
                half_life=hl,
                prevention_rate_top5=r5,
                prevention_rate_top10=r10,
                prevention_rate_top15=r15,
                per_cluster=per_cluster,
            ))

            combined_score: float = r10 + r5 * 0.001
            if combined_score > best_score:
                best_score = combined_score
                best_hl = hl

        best_per_type[ct] = best_hl
        label: str = "never" if best_hl is None else f"{best_hl}d"
        print(f"    -> best half-life: {label}", file=sys.stderr)

    return best_per_type, all_results


# ============================================================
# Additional analyses
# ============================================================

def decay_factor_distribution(
    decisions: list[Decision],
    half_life_days: float,
    eval_at_days: float,
) -> dict[str, float]:
    """Compute summary stats of decay factors (not scores) for non-locked, non-superseded decisions."""
    lam: float = math.log(2.0) / half_life_days
    factors: list[float] = []
    for d in decisions:
        if d.locked or d.superseded_by is not None:
            continue
        age: float = eval_at_days - d.created_at_days
        if age < 0.0:
            continue
        factors.append(math.exp(-lam * age))

    if not factors:
        return {"n": 0, "mean": 0.0, "min": 0.0, "max": 0.0, "median": 0.0}

    factors_sorted: list[float] = sorted(factors)
    n: int = len(factors_sorted)
    mid: int = n // 2
    median: float = (
        factors_sorted[mid]
        if n % 2 == 1
        else (factors_sorted[mid - 1] + factors_sorted[mid]) / 2.0
    )
    return {
        "n": n,
        "mean": sum(factors) / n,
        "min": factors_sorted[0],
        "max": factors_sorted[-1],
        "median": median,
    }


def locked_vs_unlocked_separation(
    decisions: list[Decision],
    half_lives: HalfLifeConfig,
    eval_at_days: float,
) -> dict[str, float]:
    """Measure score gap between locked and unlocked decisions at a given time."""
    locked_scores: list[float] = []
    unlocked_scores: list[float] = []

    for d in decisions:
        s: float = decay_score(d, eval_at_days, half_lives)
        if s <= 0.0:
            continue
        if d.locked:
            locked_scores.append(s)
        else:
            unlocked_scores.append(s)

    def _mean(lst: list[float]) -> float:
        return sum(lst) / len(lst) if lst else 0.0

    return {
        "locked_mean": _mean(locked_scores),
        "unlocked_mean": _mean(unlocked_scores),
        "locked_count": len(locked_scores),
        "unlocked_count": len(unlocked_scores),
        "separation": _mean(locked_scores) - _mean(unlocked_scores),
    }


def superseded_ordering_check(
    decisions: list[Decision],
    half_lives: HalfLifeConfig,
    eval_at_days: float,
) -> dict[str, float | int]:
    """Check whether superseded decisions rank below their replacements.

    For each archived decision with a superseded_by field, check that the
    replacement scores higher than the archived decision at eval_at_days.
    """
    decision_by_id: dict[str, Decision] = {d.d_id: d for d in decisions}
    total_pairs: int = 0
    correct_order: int = 0

    for d in decisions:
        if d.superseded_by is None:
            continue
        replacement_id: str = d.superseded_by
        if replacement_id not in decision_by_id:
            continue
        total_pairs += 1
        old_score: float = decay_score(d, eval_at_days, half_lives)
        new_score: float = decay_score(
            decision_by_id[replacement_id], eval_at_days, half_lives
        )
        if new_score > old_score:
            correct_order += 1

    return {
        "total_pairs": total_pairs,
        "correct_order": correct_order,
        "fraction": correct_order / total_pairs if total_pairs > 0 else 0.0,
    }


def inherited_vs_recent_scores(
    decisions: list[Decision],
    half_lives: HalfLifeConfig,
    eval_at_days: float,
) -> dict[str, float]:
    """Compare mean scores of inherited (optimus-prime) vs recent (alpha-seek) decisions."""
    inherited_scores: list[float] = []
    recent_scores: list[float] = []

    for d in decisions:
        s: float = decay_score(d, eval_at_days, half_lives)
        if d.is_inherited:
            inherited_scores.append(s)
        else:
            recent_scores.append(s)

    def _mean(lst: list[float]) -> float:
        return sum(lst) / len(lst) if lst else 0.0

    return {
        "inherited_mean": _mean(inherited_scores),
        "inherited_count": len(inherited_scores),
        "recent_mean": _mean(recent_scores),
        "recent_count": len(recent_scores),
        "ratio_recent_over_inherited": (
            _mean(recent_scores) / _mean(inherited_scores)
            if _mean(inherited_scores) > 0
            else 0.0
        ),
    }


# ============================================================
# Main
# ============================================================

def main() -> None:
    print("=== Exp 58b: Decay Calibration (Full-Scale, 4-Month Lineage) ===",
          file=sys.stderr)

    # --- Step 1: Build milestone-to-date index from git logs ---
    print("\n[git] Loading git logs from 3 repos...", file=sys.stderr)
    milestone_dates: dict[str, float] = build_milestone_date_index([
        OPTIMUS_PRIME_REPO,
        ALPHA_SEEK_REPO,
        ALPHA_SEEK_MEMTEST_REPO,
    ])

    # Optimus-prime earliest commit date (used for "inherited" decisions)
    print("[git] Fetching optimus-prime earliest commit date...", file=sys.stderr)
    op_result = subprocess.run(
        ["git", "log", "--all", "--format=%ad", "--date=iso", "--reverse"],
        cwd=str(OPTIMUS_PRIME_REPO),
        capture_output=True,
        text=True,
        check=True,
    )
    optimus_earliest_days: float = 0.0
    for raw_line in op_result.stdout.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            dt = datetime.strptime(raw_line[:25], "%Y-%m-%d %H:%M:%S %z")
            optimus_earliest_days = (dt - _epoch_dt()).total_seconds() / 86400.0
            break
        except ValueError:
            continue
    print(f"[git] optimus-prime earliest: {optimus_earliest_days:.1f}d since epoch",
          file=sys.stderr)

    # Compute median across all milestone dates for fallback
    all_dates: list[float] = sorted(milestone_dates.values())
    if all_dates:
        mid: int = len(all_dates) // 2
        median_days: float = (
            all_dates[mid] if len(all_dates) % 2 == 1
            else (all_dates[mid - 1] + all_dates[mid]) / 2.0
        )
    else:
        median_days = optimus_earliest_days
    print(f"[git] milestone date range: {min(all_dates):.1f}d - {max(all_dates):.1f}d, "
          f"median={median_days:.1f}d",
          file=sys.stderr)

    # --- Step 2: Parse decisions ---
    print("\n[parse] Loading decisions...", file=sys.stderr)
    active: list[Decision] = load_active_decisions(
        DECISIONS_MD, milestone_dates, optimus_earliest_days, median_days
    )
    archived: list[Decision] = load_archived_decisions(
        ARCHIVE_MD, milestone_dates, optimus_earliest_days, median_days
    )
    all_decisions: list[Decision] = active + archived

    print(f"[parse] total decisions: {len(all_decisions)} "
          f"({len(active)} active + {len(archived)} archived)",
          file=sys.stderr)

    # Date range of decisions
    created_dates: list[float] = [d.created_at_days for d in all_decisions]
    print(f"[parse] decision date range: "
          f"{min(created_dates):.1f}d - {max(created_dates):.1f}d "
          f"({max(created_dates)-min(created_dates):.1f}d span)",
          file=sys.stderr)

    # Content type distribution
    type_counts: dict[str, int] = {}
    for d in all_decisions:
        key: str = d.content_type.value
        type_counts[key] = type_counts.get(key, 0) + 1
    locked_count: int = sum(1 for d in all_decisions if d.locked)
    inherited_count: int = sum(1 for d in all_decisions if d.is_inherited)
    superseded_count: int = sum(1 for d in all_decisions if d.superseded_by is not None)
    print(f"[parse] content types: {type_counts}", file=sys.stderr)
    print(f"[parse] locked: {locked_count}, inherited: {inherited_count}, "
          f"superseded: {superseded_count}",
          file=sys.stderr)

    # --- Step 3: Load corrections ---
    print("\n[load] Loading correction clusters...", file=sys.stderr)
    all_clusters: list[CorrectionCluster] = load_correction_clusters(EXP6_FAILURES)
    memory_failure_clusters: list[CorrectionCluster] = [
        c for c in all_clusters if c.is_memory_failure
    ]

    # Filter to clusters with at least one known decision ref
    decision_id_set: set[str] = {d.d_id for d in all_decisions}
    active_clusters: list[CorrectionCluster] = [
        c for c in memory_failure_clusters
        if any(ref in decision_id_set for ref in c.decision_refs)
    ]
    print(f"[load] active clusters (has known refs): {len(active_clusters)} / "
          f"{len(memory_failure_clusters)}",
          file=sys.stderr)
    for c in active_clusters:
        known: list[str] = [r for r in c.decision_refs if r in decision_id_set]
        print(f"  {c.topic_id}: known_refs={known} events={len(c.correction_timestamps)}",
              file=sys.stderr)

    # Diagnostic: target decision attributes
    print("\n[diagnostic] Target decision attributes:", file=sys.stderr)
    decision_by_id: dict[str, Decision] = {d.d_id: d for d in all_decisions}
    all_target_refs: set[str] = {
        ref
        for c in active_clusters
        for ref in c.decision_refs
        if ref in decision_id_set
    }
    for ref in sorted(all_target_refs):
        d: Decision = decision_by_id[ref]
        print(
            f"  {ref}: type={d.content_type.value} locked={d.locked} "
            f"inherited={d.is_inherited} created={d.created_at_days:.1f}d",
            file=sys.stderr,
        )

    # --- Step 4: Baseline ---
    print("\n[baseline] No decay (all half-lives = None)", file=sys.stderr)
    baseline_config: HalfLifeConfig = _make_all_none()
    _, baseline_rates, baseline_per_cluster = evaluate_config(
        all_decisions, active_clusters, baseline_config
    )
    print(
        f"  top5={baseline_rates[5]:.3f}  top10={baseline_rates[10]:.3f}  "
        f"top15={baseline_rates[15]:.3f}",
        file=sys.stderr,
    )

    # Diagnostic: ranks under baseline
    print("[diagnostic] Target ranks at first correction event (baseline):", file=sys.stderr)
    for cluster in active_clusters:
        if not cluster.correction_timestamps:
            continue
        ts_iso: str = cluster.correction_timestamps[0]
        current_days: float = iso_to_days(ts_iso)
        ranked: list[tuple[str, float]] = rank_decisions(
            all_decisions, current_days, baseline_config
        )
        target_ids: set[str] = {r for r in cluster.decision_refs if r in decision_id_set}
        for ref in sorted(target_ids):
            for i, (d_id, s) in enumerate(ranked):
                if d_id == ref:
                    print(
                        f"  {cluster.topic_id}/{ref}: rank={i+1} score={s:.4f} "
                        f"(locked={decision_by_id[ref].locked})",
                        file=sys.stderr,
                    )
                    break

    # --- Step 5: Per-type grid search ---
    best_per_type, sweep_results = grid_search(all_decisions, active_clusters)

    # --- Step 6: Combined best settings ---
    print("\n[combined] Testing combined best half-lives", file=sys.stderr)
    combined_config: HalfLifeConfig = HalfLifeConfig(
        constraint=best_per_type[ContentType.CONSTRAINT],
        evidence=best_per_type[ContentType.EVIDENCE],
        context=best_per_type[ContentType.CONTEXT],
        procedure=best_per_type[ContentType.PROCEDURE],
    )
    print(f"  config: {best_per_type}", file=sys.stderr)
    combined_detail_results, combined_rates, combined_per_cluster = evaluate_config(
        all_decisions, active_clusters, combined_config
    )
    print(
        f"  top5={combined_rates[5]:.3f}  top10={combined_rates[10]:.3f}  "
        f"top15={combined_rates[15]:.3f}",
        file=sys.stderr,
    )

    # Rank distribution under combined config
    rank_buckets: dict[str, int] = {
        "1-5": 0, "6-10": 0, "11-15": 0, "16-30": 0, "31-50": 0, "51+": 0, "not_found": 0
    }
    for rr in combined_detail_results:
        if rr.best_rank is None:
            rank_buckets["not_found"] += 1
        elif rr.best_rank <= 5:
            rank_buckets["1-5"] += 1
        elif rr.best_rank <= 10:
            rank_buckets["6-10"] += 1
        elif rr.best_rank <= 15:
            rank_buckets["11-15"] += 1
        elif rr.best_rank <= 30:
            rank_buckets["16-30"] += 1
        elif rr.best_rank <= 50:
            rank_buckets["31-50"] += 1
        else:
            rank_buckets["51+"] += 1
    print(f"[diagnostic] Rank distribution (combined): {rank_buckets}", file=sys.stderr)

    # --- Step 7: Additional analyses ---
    print("\n[additional] Decay factor distributions per half-life setting", file=sys.stderr)
    # Evaluate at the median correction timestamp
    all_correction_days: list[float] = sorted([
        iso_to_days(ts)
        for c in active_clusters
        for ts in c.correction_timestamps
    ])
    mid_corr: int = len(all_correction_days) // 2
    eval_at_days: float = (
        all_correction_days[mid_corr]
        if all_correction_days
        else median_days
    )
    print(f"  Evaluating at median correction time: {eval_at_days:.1f}d since epoch",
          file=sys.stderr)

    decay_distributions: dict[str, dict[str, float]] = {}
    for hl in HALF_LIFE_CANDIDATES:
        if hl is None:
            continue
        dist: dict[str, float] = decay_factor_distribution(
            all_decisions, hl, eval_at_days
        )
        key: str = f"{hl}d"
        decay_distributions[key] = dist
        print(f"  hl={hl}d: n={dist['n']} mean={dist['mean']:.3f} "
              f"min={dist['min']:.3f} max={dist['max']:.3f}",
              file=sys.stderr)

    print("\n[additional] Locked vs unlocked separation per half-life", file=sys.stderr)
    locked_unlocked_by_hl: dict[str, dict[str, float]] = {}
    for hl in HALF_LIFE_CANDIDATES:
        test_config: HalfLifeConfig = HalfLifeConfig(
            constraint=hl, evidence=hl, context=hl, procedure=hl
        )
        sep: dict[str, float] = locked_vs_unlocked_separation(
            all_decisions, test_config, eval_at_days
        )
        key = f"{hl}d" if hl is not None else "never"
        locked_unlocked_by_hl[key] = sep
        print(
            f"  hl={key}: locked_mean={sep['locked_mean']:.3f} "
            f"unlocked_mean={sep['unlocked_mean']:.3f} "
            f"separation={sep['separation']:.3f}",
            file=sys.stderr,
        )

    print("\n[additional] Superseded ordering check per half-life", file=sys.stderr)
    superseded_ordering_by_hl: dict[str, dict[str, float | int]] = {}
    for hl in HALF_LIFE_CANDIDATES:
        test_config = HalfLifeConfig(
            constraint=hl, evidence=hl, context=hl, procedure=hl
        )
        check: dict[str, float | int] = superseded_ordering_check(
            all_decisions, test_config, eval_at_days
        )
        key = f"{hl}d" if hl is not None else "never"
        superseded_ordering_by_hl[key] = check
        print(
            f"  hl={key}: {check['correct_order']}/{check['total_pairs']} "
            f"correct ({check['fraction']:.2f})",
            file=sys.stderr,
        )

    print("\n[additional] Inherited vs recent scores per half-life", file=sys.stderr)
    inherited_recent_by_hl: dict[str, dict[str, float]] = {}
    for hl in HALF_LIFE_CANDIDATES:
        test_config = HalfLifeConfig(
            constraint=hl, evidence=hl, context=hl, procedure=hl
        )
        ir: dict[str, float] = inherited_vs_recent_scores(
            all_decisions, test_config, eval_at_days
        )
        key = f"{hl}d" if hl is not None else "never"
        inherited_recent_by_hl[key] = ir
        print(
            f"  hl={key}: inherited_mean={ir['inherited_mean']:.3f} "
            f"recent_mean={ir['recent_mean']:.3f} "
            f"ratio={ir['ratio_recent_over_inherited']:.2f}x",
            file=sys.stderr,
        )

    # --- Final summary ---
    print("\n=== SUMMARY ===", file=sys.stderr)
    print(f"Total decisions: {len(all_decisions)} ({len(active)} active + {len(archived)} archived)",
          file=sys.stderr)
    print(f"  Locked: {locked_count}  Inherited: {inherited_count}  "
          f"Superseded: {superseded_count}",
          file=sys.stderr)
    print(f"  Content types: {type_counts}", file=sys.stderr)
    span_days: float = max(created_dates) - min(created_dates)
    print(f"  Temporal span: {span_days:.1f} days ({span_days/30:.1f} months)",
          file=sys.stderr)
    print(f"Active correction clusters: {len(active_clusters)}", file=sys.stderr)
    total_events: int = sum(len(c.correction_timestamps) for c in active_clusters)
    print(f"Total correction events: {total_events}", file=sys.stderr)
    print(f"\nBaseline (no decay): top5={baseline_rates[5]:.3f}  "
          f"top10={baseline_rates[10]:.3f}  top15={baseline_rates[15]:.3f}",
          file=sys.stderr)
    print(f"Combined best:       top5={combined_rates[5]:.3f}  "
          f"top10={combined_rates[10]:.3f}  top15={combined_rates[15]:.3f}",
          file=sys.stderr)
    print(f"\nOptimal half-lives:", file=sys.stderr)
    for ct, hl in best_per_type.items():
        print(f"  {ct.value}: {'never' if hl is None else f'{hl}d'}",
              file=sys.stderr)
    print(f"\nRank distribution (combined): {rank_buckets}", file=sys.stderr)

    # --- Build results JSON ---
    results_json: dict = {
        "experiment": "exp58b_decay_calibration_fullscale",
        "date": "2026-04-10",
        "data_sources": {
            "active_decisions_file": str(DECISIONS_MD),
            "archived_decisions_file": str(ARCHIVE_MD),
            "corrections_file": str(EXP6_FAILURES),
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
            "temporal_span_days": round(max(created_dates) - min(created_dates), 1),
            "temporal_span_months": round((max(created_dates) - min(created_dates)) / 30, 1),
            "active_clusters": len(active_clusters),
            "total_correction_events": total_events,
            "content_type_distribution": type_counts,
        },
        "baseline_no_decay": {
            "top5": baseline_rates[5],
            "top10": baseline_rates[10],
            "top15": baseline_rates[15],
            "per_cluster": baseline_per_cluster,
        },
        "sweep_results": [
            {
                "content_type": sr.content_type_swept,
                "half_life": sr.half_life,
                "top5": sr.prevention_rate_top5,
                "top10": sr.prevention_rate_top10,
                "top15": sr.prevention_rate_top15,
                "per_cluster": sr.per_cluster,
            }
            for sr in sweep_results
        ],
        "optimal_half_lives": {
            ct.value: hl for ct, hl in best_per_type.items()
        },
        "combined_best": {
            "top5": combined_rates[5],
            "top10": combined_rates[10],
            "top15": combined_rates[15],
            "per_cluster": combined_per_cluster,
        },
        "rank_distribution_combined": rank_buckets,
        "additional_analyses": {
            "eval_at_days": round(eval_at_days, 1),
            "decay_factor_distributions": {
                k: {kk: round(vv, 4) for kk, vv in v.items()}
                for k, v in decay_distributions.items()
            },
            "locked_vs_unlocked_by_hl": {
                k: {kk: round(vv, 4) for kk, vv in v.items()}
                for k, v in locked_unlocked_by_hl.items()
            },
            "superseded_ordering_by_hl": superseded_ordering_by_hl,
            "inherited_vs_recent_by_hl": {
                k: {kk: round(vv, 4) for kk, vv in v.items()}
                for k, v in inherited_recent_by_hl.items()
            },
        },
        "interpretation": {
            "note": (
                f"4-month full-scale calibration. {len(all_decisions)} decisions "
                f"spanning {round((max(created_dates)-min(created_dates))/30, 1)} months "
                f"(vs 173 decisions over 13 days in Exp 58). "
                f"Superseded decisions: {superseded_count}. "
                f"Inherited (optimus-prime) decisions: {inherited_count}. "
                f"Locked fraction: {locked_count}/{len(all_decisions)}="
                f"{locked_count/len(all_decisions):.2f}. "
                "If half-lives are still insensitive, the issue is the same: "
                "too many locked decisions all score 1.0 and dominate the top of the ranking."
            ),
            "locked_fraction": round(locked_count / len(all_decisions), 3),
        },
    }

    with RESULTS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(results_json, fh, indent=2)

    print(f"\n[done] results saved to {RESULTS_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
