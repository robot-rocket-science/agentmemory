"""Experiment 81: Belief Snapshot Prototype.

Reconstructs B(t) -- the agent's synthesized "belief state" at a given timestamp --
by aggregating active statements, grouping by topic/type, resolving supersession chains,
and producing a human-readable summary.

Tests on 3 time points:
  T1: End of day 1 (2026-04-10)
  T2: Mid day 2 (2026-04-11 12:00)
  T3: Current (2026-04-12)

The output is a prototype of what "get_beliefs_at(timestamp)" would return.

Success criteria:
  - Snapshots at different times show different statement counts
  - Superseded statements are excluded from snapshots
  - Topic clustering produces meaningful groups
"""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH: str = str(
    Path.home() / ".agentmemory" / "projects" / "2e7ed55e017a" / "memory.db"
)

SNAPSHOTS: list[tuple[str, str]] = [
    ("T1: End of Day 1", "2026-04-11T00:00:00"),
    ("T2: Mid Day 2", "2026-04-11T12:00:00"),
    ("T3: Current", "2026-04-13T00:00:00"),  # future bound to capture everything
]

# Simple topic extraction: first N significant words
STOP_WORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "and", "but", "or",
    "nor", "not", "no", "so", "if", "then", "than", "that", "this",
    "these", "those", "it", "its", "we", "our", "they", "their",
}


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class StatementAtTime:
    belief_id: str
    content: str
    belief_type: str
    source_type: str
    confidence: float
    locked: bool
    created_at: str


@dataclass
class TopicCluster:
    topic_words: list[str]
    statements: list[StatementAtTime]
    avg_confidence: float
    locked_count: int
    type_distribution: dict[str, int]


@dataclass
class BeliefSnapshot:
    label: str
    timestamp: str
    total_statements: int
    locked_count: int
    by_type: dict[str, int]
    by_source: dict[str, int]
    avg_confidence: float
    top_clusters: list[TopicCluster]
    superseded_excluded: int


# ---------------------------------------------------------------------------
# Topic extraction (simple bigram)
# ---------------------------------------------------------------------------

def extract_topic_key(content: str) -> str:
    """Extract a simple topic key from content for grouping."""
    words: list[str] = []
    for w in content.lower().split():
        cleaned = w.strip(".,;:!?()[]{}\"'`")
        if cleaned and cleaned not in STOP_WORDS and len(cleaned) > 2:
            words.append(cleaned)
            if len(words) >= 3:
                break
    return " ".join(words) if words else "unknown"


# ---------------------------------------------------------------------------
# Snapshot construction
# ---------------------------------------------------------------------------

def build_snapshot(label: str, timestamp: str) -> BeliefSnapshot:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row

    # Get all statements that were active at the given timestamp:
    # - created_at <= timestamp
    # - (valid_to IS NULL OR valid_to > timestamp)  -- not yet superseded at that time
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, content, belief_type, source_type, confidence, locked, created_at,
               superseded_by
        FROM beliefs
        WHERE created_at <= ?
          AND (valid_to IS NULL OR valid_to > ?)
    """, (timestamp, timestamp))

    rows: list[sqlite3.Row] = cursor.fetchall()
    conn.close()

    # Count superseded items we excluded
    # (items created before timestamp but with valid_to <= timestamp)
    conn2 = sqlite3.connect(DB_PATH, timeout=10)
    cursor2 = conn2.cursor()
    cursor2.execute("""
        SELECT COUNT(*) FROM beliefs
        WHERE created_at <= ? AND valid_to IS NOT NULL AND valid_to <= ?
    """, (timestamp, timestamp))
    superseded_excluded: int = cursor2.fetchone()[0]
    conn2.close()

    statements: list[StatementAtTime] = []
    for row in rows:
        statements.append(StatementAtTime(
            belief_id=row["id"],
            content=row["content"],
            belief_type=row["belief_type"],
            source_type=row["source_type"],
            confidence=row["confidence"],
            locked=bool(row["locked"]),
            created_at=row["created_at"],
        ))

    # Aggregate stats
    by_type: dict[str, int] = Counter()
    by_source: dict[str, int] = Counter()
    locked_count: int = 0
    total_conf: float = 0.0

    for s in statements:
        by_type[s.belief_type] += 1
        by_source[s.source_type] += 1
        if s.locked:
            locked_count += 1
        total_conf += s.confidence

    avg_confidence: float = total_conf / len(statements) if statements else 0.0

    # Topic clustering
    topic_groups: dict[str, list[StatementAtTime]] = defaultdict(list)
    for s in statements:
        key = extract_topic_key(s.content)
        topic_groups[key].append(s)

    # Build top clusters (by size)
    clusters: list[TopicCluster] = []
    for key, stmts in sorted(topic_groups.items(), key=lambda x: -len(x[1])):
        if len(stmts) < 2:
            continue  # skip singletons for readability
        avg_c = sum(s.confidence for s in stmts) / len(stmts)
        type_dist: dict[str, int] = Counter(s.belief_type for s in stmts)
        lk = sum(1 for s in stmts if s.locked)
        clusters.append(TopicCluster(
            topic_words=key.split(),
            statements=stmts,
            avg_confidence=avg_c,
            locked_count=lk,
            type_distribution=dict(type_dist),
        ))

    return BeliefSnapshot(
        label=label,
        timestamp=timestamp,
        total_statements=len(statements),
        locked_count=locked_count,
        by_type=dict(by_type),
        by_source=dict(by_source),
        avg_confidence=avg_confidence,
        top_clusters=clusters[:15],
        superseded_excluded=superseded_excluded,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 70)
    print("EXPERIMENT 81: BELIEF SNAPSHOT PROTOTYPE")
    print("=" * 70)

    snapshots: list[BeliefSnapshot] = []
    for label, ts in SNAPSHOTS:
        snap = build_snapshot(label, ts)
        snapshots.append(snap)

    # Compare snapshots
    print("\n--- Snapshot Comparison ---")
    print(f"{'Label':<25} {'Statements':>10} {'Locked':>8} {'Superseded':>10} {'Avg Conf':>10}")
    for snap in snapshots:
        print(f"{snap.label:<25} {snap.total_statements:>10} {snap.locked_count:>8} "
              f"{snap.superseded_excluded:>10} {snap.avg_confidence:>10.3f}")

    growth_t1_t2: int = snapshots[1].total_statements - snapshots[0].total_statements
    growth_t2_t3: int = snapshots[2].total_statements - snapshots[1].total_statements
    print(f"\nGrowth T1->T2: +{growth_t1_t2} statements")
    print(f"Growth T2->T3: +{growth_t2_t3} statements")

    # Detailed view of each snapshot
    for snap in snapshots:
        print(f"\n{'='*50}")
        print(f"SNAPSHOT: {snap.label} (at {snap.timestamp})")
        print(f"{'='*50}")
        print(f"Total statements: {snap.total_statements}")
        print(f"Locked: {snap.locked_count}")
        print(f"Superseded (excluded): {snap.superseded_excluded}")
        print(f"Avg confidence: {snap.avg_confidence:.3f}")

        print(f"\nBy type:")
        for bt, count in sorted(snap.by_type.items(), key=lambda x: -x[1]):
            print(f"  {bt:>15}: {count}")

        print(f"\nBy source:")
        for src, count in sorted(snap.by_source.items(), key=lambda x: -x[1]):
            print(f"  {src:>20}: {count}")

        print(f"\nTop topic clusters (>1 statement):")
        for i, cluster in enumerate(snap.top_clusters[:10]):
            topic = " ".join(cluster.topic_words)
            types = ", ".join(f"{t}={c}" for t, c in cluster.type_distribution.items())
            lk_tag = f" [{cluster.locked_count} locked]" if cluster.locked_count else ""
            print(f"  #{i+1}: \"{topic}\" -- {len(cluster.statements)} stmts, "
                  f"avg_conf={cluster.avg_confidence:.2f}, {types}{lk_tag}")

    # Success criteria
    print(f"\n--- Success Criteria ---")
    sizes_differ = len(set(s.total_statements for s in snapshots)) > 1
    print(f"Snapshots show different counts? {'PASS' if sizes_differ else 'FAIL'}")
    any_superseded = any(s.superseded_excluded > 0 for s in snapshots)
    print(f"Superseded statements excluded? {'PASS' if any_superseded else 'FAIL'}")
    any_clusters = any(len(s.top_clusters) > 0 for s in snapshots)
    print(f"Topic clustering produces groups? {'PASS' if any_clusters else 'FAIL'}")


if __name__ == "__main__":
    main()
