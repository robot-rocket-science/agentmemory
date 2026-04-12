"""Exp 58: Decay Half-Life Calibration on Real Correction Data

Uses the alpha-seek spike DB (173 decisions) and 38 user corrections from
exp6_failures_v2.json to empirically calibrate exponential decay half-lives
per content type.

Research question: What decay half-lives best ensure that the belief the user
was trying to enforce ranks in the top-5/10/15 at the moment of each correction?

Method:
  1. Load 173 decisions, derive timestamps via DECIDED_IN -> milestone created_at.
  2. Classify each decision by content type and locked status.
  3. For each correction cluster (6 memory-failure clusters), at each correction
     timestamp, score all decisions with candidate half-lives and measure ranking
     of the correct belief.
  4. Grid-search half-lives per content type (one at a time, others held at None).
  5. Combine best individual settings and measure combined performance.
  6. Report correction prevention rates at top-5, top-10, top-15 thresholds.

Scoring: exponential decay with locked=1.0, superseded=0.01, content-type half-lives.
"""

from __future__ import annotations

import json
import math
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Final

# ============================================================
# Config
# ============================================================

ALPHA_SEEK_DB: Final[Path] = Path(
    "/Users/thelorax/projects/.gsd/workflows/spikes/"
    "260406-1-associative-memory-for-gsd-please-explor/"
    "sandbox/alpha-seek.db"
)

EXP6_FAILURES: Final[Path] = Path(
    "/Users/thelorax/projects/agentmemory/experiments/exp6_failures_v2.json"
)

RESULTS_PATH: Final[Path] = Path(
    "/Users/thelorax/projects/agentmemory/experiments/exp58_results.json"
)

# Half-life candidates in days; None = no decay (score always 1.0)
HALF_LIFE_CANDIDATES: Final[list[float | None]] = [
    1.0, 3.0, 7.0, 14.0, 30.0, 60.0, None
]

RANKING_THRESHOLDS: Final[list[int]] = [5, 10, 15]

# Epoch for converting ISO dates to days-since-project-start
PROJECT_EPOCH: Final[str] = "2026-03-25T00:00:00.000Z"


# ============================================================
# Content type classification
# ============================================================

class ContentType(Enum):
    CONSTRAINT = "CONSTRAINT"
    EVIDENCE = "EVIDENCE"
    CONTEXT = "CONTEXT"
    PROCEDURE = "PROCEDURE"
    RATIONALE = "RATIONALE"


# Scope -> content type mappings per spec
SCOPE_TO_CONSTRAINT: Final[frozenset[str]] = frozenset({
    "architecture", "infrastructure", "operations", "agent behavior"
})

SCOPE_TO_PROCEDURE: Final[frozenset[str]] = frozenset({
    "methodology", "strategy", "configuration", "tooling"
})

CATEGORY_TO_EVIDENCE: Final[frozenset[str]] = frozenset({
    "knowledge", "backtesting", "evaluation", "validation", "hypothesis"
})

CATEGORY_TO_CONTEXT: Final[frozenset[str]] = frozenset({
    "milestone", "bugfix", "reporting", "documentation"
})

RATIONALE_KEYWORDS: Final[tuple[str, ...]] = ("because", "rationale", "reason")


# ============================================================
# Data structures
# ============================================================

@dataclass
class Decision:
    id: str
    scope: str
    made_by: str
    revisable_raw: str
    decision_text: str
    rationale_text: str
    superseded_by: str | None
    created_at_days: float       # days since PROJECT_EPOCH
    content_type: ContentType
    locked: bool


@dataclass
class CorrectionCluster:
    topic_id: str
    description: str
    decision_refs: list[str]
    correction_timestamps: list[str]   # ISO strings
    is_memory_failure: bool


@dataclass
class RankingResult:
    topic_id: str
    correction_iso: str
    correct_refs_found: list[str]    # refs that exist in decisions
    best_rank: int | None            # best rank of any correct ref (1-indexed), None if not found
    total_decisions: int


@dataclass
class HalfLifeConfig:
    constraint: float | None
    evidence: float | None
    context: float | None
    procedure: float | None
    rationale: float | None

    def get(self, ct: ContentType) -> float | None:
        mapping: dict[ContentType, float | None] = {
            ContentType.CONSTRAINT: self.constraint,
            ContentType.EVIDENCE: self.evidence,
            ContentType.CONTEXT: self.context,
            ContentType.PROCEDURE: self.procedure,
            ContentType.RATIONALE: self.rationale,
        }
        return mapping[ct]


@dataclass
class SweepResult:
    content_type_swept: str          # which type was swept ("combined" for final pass)
    half_life: float | None          # the half-life tested for that type
    prevention_rate_top5: float
    prevention_rate_top10: float
    prevention_rate_top15: float
    per_cluster: dict[str, dict[str, float]] = field(default_factory=lambda: dict[str, dict[str, float]]())


# ============================================================
# Date utilities
# ============================================================

def parse_iso_days(iso_str: str, epoch_days: float) -> float:
    """Convert ISO 8601 timestamp to days since epoch."""
    # Remove trailing Z and parse
    clean: str = iso_str.replace("Z", "+00:00")
    dt: datetime = datetime.fromisoformat(clean)
    # epoch in same form
    epoch_clean: str = PROJECT_EPOCH.replace("Z", "+00:00")
    epoch_dt: datetime = datetime.fromisoformat(epoch_clean)
    delta_seconds: float = (dt - epoch_dt).total_seconds()
    return delta_seconds / 86400.0


_EPOCH_DAYS: float = 0.0  # epoch is day 0 by definition


def iso_to_days(iso_str: str) -> float:
    """Convert ISO 8601 timestamp to days since PROJECT_EPOCH."""
    clean: str = iso_str.replace("Z", "+00:00")
    dt: datetime = datetime.fromisoformat(clean)
    epoch_clean: str = PROJECT_EPOCH.replace("Z", "+00:00")
    epoch_dt: datetime = datetime.fromisoformat(epoch_clean)
    return (dt - epoch_dt).total_seconds() / 86400.0


# ============================================================
# Content type classification
# ============================================================

def _is_locked(revisable_raw: str) -> bool:
    """Return True if the revisable field starts with 'No' (case-insensitive)."""
    return revisable_raw.strip().lower().startswith("no")


def _contains_rationale_keyword(text: str) -> bool:
    lower: str = text.lower()
    return any(kw in lower for kw in RATIONALE_KEYWORDS)


def classify_decision(
    scope: str,
    revisable_raw: str,
    decision_text: str,
    rationale_text: str,
) -> ContentType:
    """Map scope and content to a ContentType per the experiment spec."""
    locked: bool = _is_locked(revisable_raw)

    # CONSTRAINT: locked + architecture/infrastructure/operations/agent behavior
    if locked and scope in SCOPE_TO_CONSTRAINT:
        return ContentType.CONSTRAINT

    # EVIDENCE: category/scope in evidence-like scopes
    if scope in CATEGORY_TO_EVIDENCE:
        return ContentType.EVIDENCE

    # CONTEXT: context-like scopes
    if scope in CATEGORY_TO_CONTEXT:
        return ContentType.CONTEXT

    # PROCEDURE: methodology/strategy/config/tooling
    if scope in SCOPE_TO_PROCEDURE:
        return ContentType.PROCEDURE

    # RATIONALE: heuristic on content text
    combined_text: str = decision_text + " " + rationale_text
    if _contains_rationale_keyword(combined_text):
        return ContentType.RATIONALE

    # Default
    return ContentType.EVIDENCE


# ============================================================
# Data loading
# ============================================================

def load_milestone_dates(conn: sqlite3.Connection) -> dict[str, float]:
    """Return mapping from milestone prefix (e.g. 'M006') to days since epoch.

    The milestones table uses IDs like 'M006-wz8eaf'.
    DECIDED_IN edges use target IDs like '_M006'.
    We match by stripping the leading underscore and taking the prefix.
    """
    cursor = conn.execute("SELECT id, created_at FROM milestones ORDER BY created_at")
    milestone_dates: dict[str, float] = {}
    for row in cursor.fetchall():
        m_id: str = row[0]           # e.g. "M006-wz8eaf"
        m_date: str = row[1]         # ISO timestamp
        prefix: str = m_id.split("-")[0]  # "M006"
        # Take the earliest date if multiple milestones share a prefix
        days: float = iso_to_days(m_date)
        if prefix not in milestone_dates or days < milestone_dates[prefix]:
            milestone_dates[prefix] = days
    return milestone_dates


def _node_id_to_milestone_prefix(node_id: str) -> str:
    """Convert '_M006' -> 'M006'."""
    return node_id.lstrip("_")


def load_decisions(conn: sqlite3.Connection) -> list[Decision]:
    """Load all 173 decisions with derived timestamps."""
    milestone_dates: dict[str, float] = load_milestone_dates(conn)

    # Build: decision_id -> list of milestone prefix dates via DECIDED_IN edges
    cursor = conn.execute(
        "SELECT from_id, to_id FROM mem_edges WHERE edge_type='DECIDED_IN'"
    )
    decision_to_milestone_days: dict[str, list[float]] = {}
    for from_id, to_id in cursor.fetchall():
        prefix: str = _node_id_to_milestone_prefix(to_id)
        if prefix in milestone_dates:
            decision_to_milestone_days.setdefault(from_id, []).append(
                milestone_dates[prefix]
            )

    # Compute median date for decisions without milestone links
    all_linked_days: list[float] = [
        d for days_list in decision_to_milestone_days.values()
        for d in days_list
    ]
    if all_linked_days:
        sorted_days: list[float] = sorted(all_linked_days)
        mid: int = len(sorted_days) // 2
        median_days: float = (
            sorted_days[mid] if len(sorted_days) % 2 == 1
            else (sorted_days[mid - 1] + sorted_days[mid]) / 2.0
        )
    else:
        median_days = 0.0

    print(
        f"[load] milestone date range: "
        f"min={min(all_linked_days):.1f}d max={max(all_linked_days):.1f}d "
        f"median={median_days:.1f}d (n={len(all_linked_days)})",
        file=sys.stderr,
    )

    cursor = conn.execute(
        "SELECT id, scope, made_by, revisable, decision, rationale, superseded_by "
        "FROM decisions"
    )
    rows = cursor.fetchall()
    decisions: list[Decision] = []

    for row in rows:
        d_id: str = row[0]
        scope: str = row[1] or ""
        made_by: str = row[2] or "agent"
        revisable_raw: str = row[3] or "Yes"
        decision_text: str = row[4] or ""
        rationale_text: str = row[5] or ""
        superseded_by: str | None = row[6]

        # Derive timestamp: earliest milestone date for this decision, or median
        linked_days_list: list[float] = decision_to_milestone_days.get(d_id, [])
        if linked_days_list:
            created_at_days: float = min(linked_days_list)
        else:
            created_at_days = median_days

        content_type: ContentType = classify_decision(
            scope, revisable_raw, decision_text, rationale_text
        )
        locked: bool = _is_locked(revisable_raw)

        decisions.append(Decision(
            id=d_id,
            scope=scope,
            made_by=made_by,
            revisable_raw=revisable_raw,
            decision_text=decision_text,
            rationale_text=rationale_text,
            superseded_by=superseded_by,
            created_at_days=created_at_days,
            content_type=content_type,
            locked=locked,
        ))

    print(f"[load] loaded {len(decisions)} decisions", file=sys.stderr)

    # Print content type distribution
    type_counts: dict[str, int] = {}
    for d in decisions:
        key: str = d.content_type.value
        type_counts[key] = type_counts.get(key, 0) + 1
    print(f"[load] content type distribution: {type_counts}", file=sys.stderr)

    locked_count: int = sum(1 for d in decisions if d.locked)
    print(f"[load] locked decisions: {locked_count}", file=sys.stderr)

    return decisions


def load_correction_clusters(failures_path: Path) -> list[CorrectionCluster]:
    """Load correction clusters from exp6_failures_v2.json."""
    with failures_path.open("r", encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)

    clusters: list[CorrectionCluster] = []
    for cluster in list[dict[str, Any]](data.get("topic_clusters", [])):
        if not cluster.get("is_memory_failure", False):
            continue  # only use memory-failure clusters for calibration

        # Extract timestamps from overrides
        timestamps: list[str] = [
            str(ov["timestamp"])
            for ov in list[dict[str, Any]](cluster.get("overrides", []))
            if "timestamp" in ov
        ]

        clusters.append(CorrectionCluster(
            topic_id=str(cluster["topic_id"]),
            description=str(cluster.get("description", "")),
            decision_refs=list[str](cluster.get("decision_refs", [])),
            correction_timestamps=timestamps,
            is_memory_failure=True,
        ))

    print(
        f"[load] loaded {len(clusters)} memory-failure correction clusters",
        file=sys.stderr,
    )
    total_corrections: int = sum(len(c.correction_timestamps) for c in clusters)
    print(f"[load] total correction events: {total_corrections}", file=sys.stderr)
    return clusters


# ============================================================
# Scoring
# ============================================================

def decay_score(
    decision: Decision,
    current_time_days: float,
    half_lives: HalfLifeConfig,
) -> float:
    """Compute decay score for a decision at a given time.

    Decisions created after current_time_days score 0.0 (did not exist yet).
    Locked decisions score 1.0 regardless of age.
    Superseded decisions score 0.01 (visible for history queries only).
    """
    age: float = current_time_days - decision.created_at_days
    # Decision did not exist yet at this point in time
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

    lam: float = math.log(2) / half_life
    return math.exp(-lam * age)


def rank_decisions(
    decisions: list[Decision],
    current_time_days: float,
    half_lives: HalfLifeConfig,
) -> list[tuple[str, float]]:
    """Return decisions sorted by decay score descending. Returns (id, score) pairs.

    Tiebreaker: more recent decisions (higher created_at_days) rank first within
    the same score bucket. This matches the intuition that when two beliefs score
    equally, the more recently established one is more relevant.
    """
    scored: list[tuple[str, float, float]] = [
        (d.id, decay_score(d, current_time_days, half_lives), d.created_at_days)
        for d in decisions
    ]
    # Primary: score descending; secondary: created_at_days descending (more recent first)
    scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return [(d_id, s) for d_id, s, _ in scored]


def find_best_rank(
    ranked: list[tuple[str, float]],
    target_ids: set[str],
) -> int | None:
    """Return 1-indexed rank of the best (highest) ranked target ID, or None."""
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
    """Evaluate a half-life config.

    Returns:
      - list of RankingResult per correction event
      - dict of prevention rate per threshold {5: rate, 10: rate, 15: rate}
      - per-cluster breakdown {topic_id: {top5: rate, top10: rate, top15: rate}}
    """
    results: list[RankingResult] = []

    # Pre-index decisions by id
    decision_ids: set[str] = {d.id for d in decisions}

    for cluster in clusters:
        target_ids: set[str] = {
            ref for ref in cluster.decision_refs if ref in decision_ids
        }
        found_refs: list[str] = list(target_ids)

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

    # Compute overall prevention rates
    total: int = len(results)
    threshold_rates: dict[int, float] = {}
    for threshold in RANKING_THRESHOLDS:
        hits: int = sum(
            1 for r in results
            if r.best_rank is not None and r.best_rank <= threshold
        )
        threshold_rates[threshold] = hits / total if total > 0 else 0.0

    # Per-cluster breakdown
    per_cluster: dict[str, dict[str, float]] = {}
    for cluster in clusters:
        cluster_results: list[RankingResult] = [
            r for r in results if r.topic_id == cluster.topic_id
        ]
        cluster_total: int = len(cluster_results)
        cluster_rates: dict[str, float] = {}
        for threshold in RANKING_THRESHOLDS:
            hits = sum(
                1 for r in cluster_results
                if r.best_rank is not None and r.best_rank <= threshold
            )
            cluster_rates[f"top{threshold}"] = (
                hits / cluster_total if cluster_total > 0 else 0.0
            )
        per_cluster[cluster.topic_id] = cluster_rates

    return results, threshold_rates, per_cluster


# ============================================================
# Grid search
# ============================================================

def _make_config_varying_one(
    content_type: ContentType,
    half_life: float | None,
    defaults: dict[ContentType, float | None],
) -> HalfLifeConfig:
    """Build a HalfLifeConfig varying one content type, others from defaults."""
    hl_map: dict[ContentType, float | None] = dict(defaults)
    hl_map[content_type] = half_life
    return HalfLifeConfig(
        constraint=hl_map[ContentType.CONSTRAINT],
        evidence=hl_map[ContentType.EVIDENCE],
        context=hl_map[ContentType.CONTEXT],
        procedure=hl_map[ContentType.PROCEDURE],
        rationale=hl_map[ContentType.RATIONALE],
    )


def _make_config_all_none() -> HalfLifeConfig:
    return HalfLifeConfig(
        constraint=None,
        evidence=None,
        context=None,
        procedure=None,
        rationale=None,
    )


def grid_search(
    decisions: list[Decision],
    clusters: list[CorrectionCluster],
) -> tuple[dict[ContentType, float | None], list[SweepResult]]:
    """Grid-search half-lives per content type independently.

    Returns:
      - best_per_type: optimal half-life per ContentType
      - all_sweep_results: full sweep data for reporting
    """
    # Baseline: all None (no decay)
    defaults: dict[ContentType, float | None] = {ct: None for ct in ContentType}
    all_sweep_results: list[SweepResult] = []

    print("\n[sweep] Phase 1: per-type independent sweep", file=sys.stderr)

    best_per_type: dict[ContentType, float | None] = {}

    for ct in ContentType:
        best_hl: float | None = None
        best_rate: float = -1.0

        print(f"  [sweep] {ct.value}:", file=sys.stderr)
        for hl in HALF_LIFE_CANDIDATES:
            config: HalfLifeConfig = _make_config_varying_one(ct, hl, defaults)
            _, threshold_rates, per_cluster = evaluate_config(decisions, clusters, config)
            r5: float = threshold_rates[5]
            r10: float = threshold_rates[10]
            r15: float = threshold_rates[15]

            hl_label: str = f"{hl}d" if hl is not None else "never"
            print(
                f"    hl={hl_label:>6}  top5={r5:.3f}  top10={r10:.3f}  top15={r15:.3f}",
                file=sys.stderr,
            )

            sweep_res = SweepResult(
                content_type_swept=ct.value,
                half_life=hl,
                prevention_rate_top5=r5,
                prevention_rate_top10=r10,
                prevention_rate_top15=r15,
                per_cluster=per_cluster,
            )
            all_sweep_results.append(sweep_res)

            # Optimize for top-10 as primary, top-5 as tiebreaker
            score: float = r10 + r5 * 0.001
            if score > best_rate:
                best_rate = score
                best_hl = hl

        best_per_type[ct] = best_hl
        print(
            f"  [sweep] {ct.value} best half-life: "
            f"{'never' if best_hl is None else f'{best_hl}d'}",
            file=sys.stderr,
        )

    return best_per_type, all_sweep_results


def sensitivity_analysis(
    decisions: list[Decision],
    clusters: list[CorrectionCluster],
    best_per_type: dict[ContentType, float | None],
) -> list[dict[str, Any]]:
    """Test 2x and 0.5x variants of best half-lives per type."""
    print("\n[sensitivity] Testing 2x and 0.5x half-lives", file=sys.stderr)
    sensitivity_results: list[dict[str, Any]] = []

    for ct in ContentType:
        best_hl: float | None = best_per_type[ct]
        if best_hl is None:
            continue  # can't vary "never"

        for multiplier, label in [(2.0, "2x"), (0.5, "0.5x")]:
            varied_hl: float = best_hl * multiplier
            config: HalfLifeConfig = _make_config_varying_one(
                ct, varied_hl, best_per_type
            )
            _, threshold_rates, _ = evaluate_config(decisions, clusters, config)
            entry: dict[str, Any] = {
                "content_type": ct.value,
                "best_hl": best_hl,
                "variant": label,
                "varied_hl": varied_hl,
                "top5": threshold_rates[5],
                "top10": threshold_rates[10],
                "top15": threshold_rates[15],
            }
            sensitivity_results.append(entry)
            print(
                f"  {ct.value} {label} ({varied_hl:.1f}d): "
                f"top5={threshold_rates[5]:.3f}  top10={threshold_rates[10]:.3f}",
                file=sys.stderr,
            )

    return sensitivity_results


# ============================================================
# Main
# ============================================================

def main() -> None:
    print("=== Exp 58: Decay Half-Life Calibration ===", file=sys.stderr)

    # Load data
    conn: sqlite3.Connection = sqlite3.connect(str(ALPHA_SEEK_DB))
    decisions: list[Decision] = load_decisions(conn)
    conn.close()

    clusters: list[CorrectionCluster] = load_correction_clusters(EXP6_FAILURES)

    # Filter to clusters with at least one known decision ref
    decision_id_set: set[str] = {d.id for d in decisions}
    active_clusters: list[CorrectionCluster] = [
        c for c in clusters
        if any(ref in decision_id_set for ref in c.decision_refs)
    ]
    print(
        f"[main] clusters with known decision refs: {len(active_clusters)} / {len(clusters)}",
        file=sys.stderr,
    )
    for c in active_clusters:
        known_refs: list[str] = [r for r in c.decision_refs if r in decision_id_set]
        print(f"  {c.topic_id}: refs={known_refs} events={len(c.correction_timestamps)}",
              file=sys.stderr)

    # Diagnostic: show locked/type breakdown of target decisions
    print("\n[diagnostic] Target decision attributes:", file=sys.stderr)
    all_target_refs: set[str] = {
        ref for c in active_clusters for ref in c.decision_refs
        if ref in decision_id_set
    }
    decision_by_id: dict[str, Decision] = {d.id: d for d in decisions}
    locked_count_all: int = sum(1 for d in decisions if d.locked)
    print(
        f"  Total locked decisions: {locked_count_all} / {len(decisions)} "
        f"({100*locked_count_all/len(decisions):.0f}%)",
        file=sys.stderr,
    )
    for ref in sorted(all_target_refs):
        d: Decision = decision_by_id[ref]
        print(
            f"  {ref}: type={d.content_type.value} locked={d.locked} "
            f"created={d.created_at_days:.1f}d",
            file=sys.stderr,
        )

    # Baseline: no decay
    print("\n[baseline] No decay (all None), recency tiebreaker", file=sys.stderr)
    baseline_config: HalfLifeConfig = _make_config_all_none()
    _, baseline_rates, baseline_per_cluster = evaluate_config(
        decisions, active_clusters, baseline_config
    )
    print(
        f"  top5={baseline_rates[5]:.3f}  top10={baseline_rates[10]:.3f}  top15={baseline_rates[15]:.3f}",
        file=sys.stderr,
    )

    # Diagnostic: print actual ranks for targets under baseline
    print("[diagnostic] Target ranks at first correction event per cluster (baseline):", file=sys.stderr)
    for cluster in active_clusters:
        if not cluster.correction_timestamps:
            continue
        ts_iso: str = cluster.correction_timestamps[0]
        current_days: float = iso_to_days(ts_iso)
        ranked: list[tuple[str, float]] = rank_decisions(
            decisions, current_days, baseline_config
        )
        target_ids: set[str] = {r for r in cluster.decision_refs if r in decision_id_set}
        for ref in sorted(target_ids):
            for i, (d_id, _s) in enumerate(ranked):
                if d_id == ref:
                    print(
                        f"  {cluster.topic_id}/{ref}: rank={i+1} score={_s:.4f}",
                        file=sys.stderr,
                    )
                    break

    # Phase 1: per-type grid search
    best_per_type, sweep_results = grid_search(decisions, active_clusters)

    # Phase 2: combined best settings
    print("\n[combined] Testing combined best half-lives", file=sys.stderr)
    combined_config: HalfLifeConfig = HalfLifeConfig(
        constraint=best_per_type[ContentType.CONSTRAINT],
        evidence=best_per_type[ContentType.EVIDENCE],
        context=best_per_type[ContentType.CONTEXT],
        procedure=best_per_type[ContentType.PROCEDURE],
        rationale=best_per_type[ContentType.RATIONALE],
    )
    print(f"  config: {best_per_type}", file=sys.stderr)
    combined_detail_results, combined_rates, combined_per_cluster = evaluate_config(
        decisions, active_clusters, combined_config
    )
    print(
        f"  top5={combined_rates[5]:.3f}  top10={combined_rates[10]:.3f}  top15={combined_rates[15]:.3f}",
        file=sys.stderr,
    )

    # Diagnostic: ranks under combined config
    print("[diagnostic] Target ranks at first correction event per cluster (combined):", file=sys.stderr)
    for cluster in active_clusters:
        if not cluster.correction_timestamps:
            continue
        ts_iso = cluster.correction_timestamps[0]
        current_days = iso_to_days(ts_iso)
        ranked = rank_decisions(decisions, current_days, combined_config)
        target_ids = {r for r in cluster.decision_refs if r in decision_id_set}
        for ref in sorted(target_ids):
            for i, (d_id, _s) in enumerate(ranked):
                if d_id == ref:
                    print(
                        f"  {cluster.topic_id}/{ref}: rank={i+1} score={_s:.4f}",
                        file=sys.stderr,
                    )
                    break

    # Rank distribution for all correction events under combined config
    rank_buckets: dict[str, int] = {"1-5": 0, "6-10": 0, "11-15": 0, "16-30": 0, "31-50": 0, "51+": 0, "not_found": 0}
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

    # Sensitivity analysis on combined best
    sensitivity_results: list[dict[str, Any]] = sensitivity_analysis(
        decisions, active_clusters, best_per_type
    )

    # Print final summary
    print("\n=== SUMMARY ===", file=sys.stderr)
    print(f"Total decisions: {len(decisions)}", file=sys.stderr)
    print(f"Active clusters: {len(active_clusters)}", file=sys.stderr)
    total_events: int = sum(len(c.correction_timestamps) for c in active_clusters)
    print(f"Total correction events: {total_events}", file=sys.stderr)
    print(f"\nBaseline (no decay): top5={baseline_rates[5]:.3f}  top10={baseline_rates[10]:.3f}  top15={baseline_rates[15]:.3f}", file=sys.stderr)
    print(f"Combined best:       top5={combined_rates[5]:.3f}  top10={combined_rates[10]:.3f}  top15={combined_rates[15]:.3f}", file=sys.stderr)
    print(f"\nOptimal half-lives:", file=sys.stderr)
    for ct, hl in best_per_type.items():
        hl_label: str = "never" if hl is None else f"{hl}d"
        print(f"  {ct.value}: {hl_label}", file=sys.stderr)

    # Build results JSON
    results: dict[str, Any] = {
        "experiment": "exp58_decay_calibration",
        "date": "2026-04-10",
        "summary": {
            "total_decisions": len(decisions),
            "active_clusters": len(active_clusters),
            "total_correction_events": total_events,
        },
        "baseline_no_decay": {
            "top5": baseline_rates[5],
            "top10": baseline_rates[10],
            "top15": baseline_rates[15],
            "per_cluster": baseline_per_cluster,
        },
        "optimal_half_lives": {
            ct.value: (hl if hl is not None else None)
            for ct, hl in best_per_type.items()
        },
        "combined_best": {
            "top5": combined_rates[5],
            "top10": combined_rates[10],
            "top15": combined_rates[15],
            "per_cluster": combined_per_cluster,
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
        "sensitivity": sensitivity_results,
        "content_type_distribution": {
            ct.value: sum(1 for d in decisions if d.content_type == ct)
            for ct in ContentType
        },
        "locked_count": sum(1 for d in decisions if d.locked),
        "rank_distribution_combined": rank_buckets,
        "interpretation": {
            "note": (
                "Decay-only ranking cannot fully separate targets because "
                f"{locked_count_all} of {len(decisions)} decisions are locked "
                "(score=1.0). Within the 1.0 tier, recency tiebreaker is used. "
                "True calibration requires a retrieval query to narrow candidates first."
            ),
            "locked_fraction": locked_count_all / len(decisions),
        },
    }

    with RESULTS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)

    print(f"\n[done] results saved to {RESULTS_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
