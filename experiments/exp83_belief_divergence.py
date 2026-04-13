"""Experiment 83: Belief Divergence Over Time.

Measures how the agent's belief state changes across time by computing
distance metrics between B(t1) and B(t2).

Uses Jensen-Shannon divergence over confidence distributions and
set-based metrics (Jaccard distance) over statement sets.

Builds on Exp 81 snapshots. Tests whether the belief state is:
  - Stable (low divergence between adjacent time points)
  - Monotonically growing (new statements only, no revision)
  - Actively revised (statements appear and disappear)

Success criteria:
  - JSD computed between snapshot pairs
  - Jaccard index shows overlap between time-adjacent snapshots
  - Characterize whether growth is additive or revisionary
"""
from __future__ import annotations

import math
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH: str = str(
    Path.home() / ".agentmemory" / "projects" / "2e7ed55e017a" / "memory.db"
)

# Time points (hourly granularity through the bulk of the data)
TIME_POINTS: list[tuple[str, str]] = [
    ("T0: Pre-onboard", "2026-04-10T23:00:00"),
    ("T1: Onboard start", "2026-04-11T00:00:00"),
    ("T2: +2h", "2026-04-11T02:00:00"),
    ("T3: +4h", "2026-04-11T04:00:00"),
    ("T4: +6h", "2026-04-11T06:00:00"),
    ("T5: +8h", "2026-04-11T08:00:00"),
    ("T6: Midday", "2026-04-11T12:00:00"),
    ("T7: End Day 2", "2026-04-12T00:00:00"),
    ("T8: Current", "2026-04-13T00:00:00"),
]


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class SnapshotState:
    label: str
    timestamp: str
    statement_ids: set[str]
    confidence_vector: dict[str, float]  # id -> confidence
    total: int
    locked_count: int
    avg_confidence: float
    type_counts: dict[str, int]


@dataclass
class DivergenceResult:
    label_a: str
    label_b: str
    jaccard_index: float  # overlap of statement sets
    jaccard_distance: float
    added_count: int  # in B but not A
    removed_count: int  # in A but not B (superseded between snapshots)
    shared_count: int
    confidence_shift: float  # avg change in confidence for shared statements
    jsd: float  # Jensen-Shannon divergence of confidence distributions
    growth_type: str  # "additive", "revisionary", or "mixed"


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------

def kl_divergence(p: list[float], q: list[float]) -> float:
    """KL(P || Q) for discrete distributions."""
    total: float = 0.0
    for pi, qi in zip(p, q):
        if pi > 0 and qi > 0:
            total += pi * math.log2(pi / qi)
    return total


def jensen_shannon_divergence(p: list[float], q: list[float]) -> float:
    """JSD(P || Q) = 0.5 * KL(P||M) + 0.5 * KL(Q||M) where M = (P+Q)/2."""
    m: list[float] = [(pi + qi) / 2 for pi, qi in zip(p, q)]
    return 0.5 * kl_divergence(p, m) + 0.5 * kl_divergence(q, m)


def confidence_to_histogram(confidences: list[float], bins: int = 20) -> list[float]:
    """Convert confidence values to a normalized histogram (probability distribution)."""
    counts: list[int] = [0] * bins
    for c in confidences:
        idx = min(int(c * bins), bins - 1)
        counts[idx] += 1
    total: int = sum(counts)
    if total == 0:
        return [1.0 / bins] * bins  # uniform
    # Add small smoothing to avoid zero bins
    smoothed: list[float] = [(c + 0.1) / (total + 0.1 * bins) for c in counts]
    return smoothed


# ---------------------------------------------------------------------------
# Snapshot extraction
# ---------------------------------------------------------------------------

def get_snapshot(label: str, timestamp: str) -> SnapshotState:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, confidence, locked, belief_type
        FROM beliefs
        WHERE created_at <= ?
          AND (valid_to IS NULL OR valid_to > ?)
    """, (timestamp, timestamp))

    rows: list[sqlite3.Row] = cursor.fetchall()
    conn.close()

    ids: set[str] = set()
    conf_vec: dict[str, float] = {}
    locked: int = 0
    type_counts: dict[str, int] = Counter()

    for row in rows:
        bid: str = row["id"]
        ids.add(bid)
        conf_vec[bid] = row["confidence"]
        if row["locked"]:
            locked += 1
        type_counts[row["belief_type"]] += 1

    avg_conf = sum(conf_vec.values()) / len(conf_vec) if conf_vec else 0.0

    return SnapshotState(
        label=label,
        timestamp=timestamp,
        statement_ids=ids,
        confidence_vector=conf_vec,
        total=len(ids),
        locked_count=locked,
        avg_confidence=avg_conf,
        type_counts=dict(type_counts),
    )


# ---------------------------------------------------------------------------
# Divergence computation
# ---------------------------------------------------------------------------

def compute_divergence(a: SnapshotState, b: SnapshotState) -> DivergenceResult:
    shared = a.statement_ids & b.statement_ids
    added = b.statement_ids - a.statement_ids
    removed = a.statement_ids - b.statement_ids
    union = a.statement_ids | b.statement_ids

    jaccard = len(shared) / len(union) if union else 1.0

    # Confidence shift for shared statements
    shifts: list[float] = []
    for sid in shared:
        if sid in a.confidence_vector and sid in b.confidence_vector:
            shifts.append(b.confidence_vector[sid] - a.confidence_vector[sid])
    avg_shift = sum(shifts) / len(shifts) if shifts else 0.0

    # JSD over confidence distributions
    confs_a = list(a.confidence_vector.values()) if a.confidence_vector else [0.5]
    confs_b = list(b.confidence_vector.values()) if b.confidence_vector else [0.5]
    hist_a = confidence_to_histogram(confs_a)
    hist_b = confidence_to_histogram(confs_b)
    jsd = jensen_shannon_divergence(hist_a, hist_b)

    # Classify growth type
    if len(removed) == 0 and len(added) > 0:
        growth_type = "additive"
    elif len(removed) > 0 and len(added) > len(removed):
        growth_type = "mixed (growth + revision)"
    elif len(removed) > 0 and len(added) <= len(removed):
        growth_type = "revisionary"
    elif len(added) == 0 and len(removed) == 0:
        growth_type = "stable"
    else:
        growth_type = "unknown"

    return DivergenceResult(
        label_a=a.label,
        label_b=b.label,
        jaccard_index=jaccard,
        jaccard_distance=1.0 - jaccard,
        added_count=len(added),
        removed_count=len(removed),
        shared_count=len(shared),
        confidence_shift=avg_shift,
        jsd=jsd,
        growth_type=growth_type,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 70)
    print("EXPERIMENT 83: BELIEF DIVERGENCE OVER TIME")
    print("=" * 70)

    # Build all snapshots
    snapshots: list[SnapshotState] = []
    for label, ts in TIME_POINTS:
        snap = get_snapshot(label, ts)
        snapshots.append(snap)
        if snap.total > 0:
            print(f"  {label}: {snap.total} statements, {snap.locked_count} locked, "
                  f"avg_conf={snap.avg_confidence:.3f}")

    # Pairwise divergence (adjacent pairs)
    print(f"\n--- Adjacent Pair Divergence ---")
    print(f"{'Pair':<35} {'Jaccard':>8} {'JSD':>8} {'Added':>7} {'Removed':>8} {'Shift':>8} {'Type'}")
    divergences: list[DivergenceResult] = []
    for i in range(len(snapshots) - 1):
        if snapshots[i].total == 0 and snapshots[i + 1].total == 0:
            continue
        div = compute_divergence(snapshots[i], snapshots[i + 1])
        divergences.append(div)
        pair_label = f"{div.label_a} -> {div.label_b}"
        print(f"  {pair_label:<33} {div.jaccard_index:>7.3f} {div.jsd:>7.4f} "
              f"{div.added_count:>7} {div.removed_count:>8} {div.confidence_shift:>+7.4f} "
              f"{div.growth_type}")

    # First-to-last divergence
    if snapshots[0].total > 0 and snapshots[-1].total > 0:
        total_div = compute_divergence(snapshots[0], snapshots[-1])
        print(f"\n--- Total Divergence (first -> last) ---")
        print(f"  Jaccard index: {total_div.jaccard_index:.4f} (distance: {total_div.jaccard_distance:.4f})")
        print(f"  JSD: {total_div.jsd:.4f}")
        print(f"  Added: {total_div.added_count}, Removed: {total_div.removed_count}, Shared: {total_div.shared_count}")
        print(f"  Growth type: {total_div.growth_type}")

    # Characterize overall dynamics
    print(f"\n--- Dynamics Summary ---")
    total_added = sum(d.added_count for d in divergences)
    total_removed = sum(d.removed_count for d in divergences)
    revision_ratio = total_removed / total_added if total_added > 0 else 0

    print(f"Total statements added across all intervals: {total_added}")
    print(f"Total statements removed (superseded): {total_removed}")
    print(f"Revision ratio (removed/added): {revision_ratio:.3f}")
    if revision_ratio < 0.05:
        print(f"Assessment: PREDOMINANTLY ADDITIVE -- the system mostly accumulates, rarely revises")
    elif revision_ratio < 0.2:
        print(f"Assessment: GROWTH WITH LIGHT REVISION -- mostly additive with some cleanup")
    else:
        print(f"Assessment: ACTIVELY REVISIONARY -- significant belief revision happening")

    jsd_values = [d.jsd for d in divergences if d.jsd > 0]
    if jsd_values:
        print(f"\nJSD range: [{min(jsd_values):.4f}, {max(jsd_values):.4f}]")
        print(f"JSD mean:  {sum(jsd_values)/len(jsd_values):.4f}")

    # Growth rate
    print(f"\n--- Growth Rate ---")
    for i, snap in enumerate(snapshots):
        if i == 0 or snap.total == 0:
            continue
        prev = snapshots[i - 1]
        if prev.total == 0:
            print(f"  {prev.label} -> {snap.label}: 0 -> {snap.total} (genesis)")
        else:
            growth = snap.total - prev.total
            growth_pct = growth / prev.total * 100
            print(f"  {prev.label} -> {snap.label}: {growth:+d} ({growth_pct:+.1f}%)")


if __name__ == "__main__":
    main()
