"""Dry-run audit of stale beliefs: find active contradiction pairs and report
which ones could be auto-superseded by provenance hierarchy.

Provenance hierarchy (highest to lowest):
  1. locked (any source_type with locked=1)
  2. user_corrected (locked=0)
  3. user_stated (locked=0)
  4. agent_inferred

When two active beliefs share a CONTRADICTS edge:
  - If one outranks the other, the lower one is flagged for auto-supersede.
  - If they are the same rank, flagged as "same-level" (needs manual review).

This script is READ-ONLY. It does not modify the database.
"""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path


DB_PATH: Path = Path.home() / ".agentmemory" / "projects" / "2e7ed55e017a" / "memory.db"


@dataclass(frozen=True)
class BeliefSummary:
    id: str
    content: str
    source_type: str
    locked: int
    confidence: float
    created_at: str

    @property
    def rank(self) -> int:
        """Higher rank = higher provenance authority."""
        if self.locked:
            return 3
        if self.source_type == "user_corrected":
            return 2
        if self.source_type == "user_stated":
            return 1
        return 0  # agent_inferred


@dataclass
class ContradictionPair:
    edge_id: int
    higher: BeliefSummary
    lower: BeliefSummary
    same_level: bool


def provenance_label(b: BeliefSummary) -> str:
    if b.locked:
        return f"locked/{b.source_type}"
    return b.source_type


def load_active_belief(cur: sqlite3.Cursor, belief_id: str) -> BeliefSummary | None:
    cur.execute(
        """SELECT id, content, source_type, locked, confidence, created_at
           FROM beliefs
           WHERE id = ? AND valid_to IS NULL""",
        (belief_id,),
    )
    row: tuple[str, str, str, int, float, str] | None = cur.fetchone()
    if row is None:
        return None
    return BeliefSummary(
        id=row[0],
        content=row[1],
        source_type=row[2],
        locked=row[3],
        confidence=row[4],
        created_at=row[5],
    )


def run_audit(db_path: Path) -> None:
    if not db_path.exists():
        print(f"ERROR: database not found at {db_path}")
        sys.exit(1)

    conn: sqlite3.Connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur: sqlite3.Cursor = conn.cursor()

    # Count totals for context
    cur.execute("SELECT COUNT(*) FROM beliefs WHERE valid_to IS NULL")
    total_active: int = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM edges WHERE edge_type = 'CONTRADICTS'")
    total_contradiction_edges: int = cur.fetchone()[0]

    print(f"Database: {db_path}")
    print(f"Active beliefs (valid_to IS NULL): {total_active}")
    print(f"Total CONTRADICTS edges: {total_contradiction_edges}")
    print()

    # Fetch all CONTRADICTS edges
    cur.execute(
        """SELECT e.id, e.from_id, e.to_id
           FROM edges e
           WHERE e.edge_type = 'CONTRADICTS'"""
    )
    edges: list[tuple[int, str, str]] = cur.fetchall()

    auto_supersede: list[ContradictionPair] = []
    same_level: list[ContradictionPair] = []
    skipped_inactive: int = 0

    for edge_id, from_id, to_id in edges:
        a: BeliefSummary | None = load_active_belief(cur, from_id)
        b: BeliefSummary | None = load_active_belief(cur, to_id)

        # Skip if either side is already superseded/expired
        if a is None or b is None:
            skipped_inactive += 1
            continue

        if a.rank == b.rank:
            same_level.append(
                ContradictionPair(edge_id=edge_id, higher=a, lower=b, same_level=True)
            )
        elif a.rank > b.rank:
            auto_supersede.append(
                ContradictionPair(edge_id=edge_id, higher=a, lower=b, same_level=False)
            )
        else:
            auto_supersede.append(
                ContradictionPair(edge_id=edge_id, higher=b, lower=a, same_level=False)
            )

    conn.close()

    # Report
    print("=" * 70)
    print("RESULTS (dry run, no writes)")
    print("=" * 70)
    print(f"Contradiction edges where both beliefs are active: {len(auto_supersede) + len(same_level)}")
    print(f"Contradiction edges where one/both sides already inactive: {skipped_inactive}")
    print()
    print(f"Auto-supersedable (lower provenance can be retired): {len(auto_supersede)}")
    print(f"Same-level conflicts (needs manual review):         {len(same_level)}")
    print()

    if auto_supersede:
        # Break down by provenance matchup
        matchups: dict[str, int] = {}
        for pair in auto_supersede:
            key: str = f"{provenance_label(pair.higher)} > {provenance_label(pair.lower)}"
            matchups[key] = matchups.get(key, 0) + 1

        print("Auto-supersede breakdown by provenance matchup:")
        for matchup, count in sorted(matchups.items(), key=lambda x: -x[1]):
            print(f"  {matchup}: {count}")
        print()

        print("Sample auto-supersedable pairs (up to 5):")
        for pair in auto_supersede[:5]:
            print(f"  Edge {pair.edge_id}:")
            print(f"    KEEP  [{provenance_label(pair.higher)}] {pair.higher.id[:12]}...")
            print(f"          conf={pair.higher.confidence:.3f} | {pair.higher.content[:80]}")
            print(f"    DROP  [{provenance_label(pair.lower)}] {pair.lower.id[:12]}...")
            print(f"          conf={pair.lower.confidence:.3f} | {pair.lower.content[:80]}")
            print()

    if same_level:
        # Break down by level
        level_counts: dict[str, int] = {}
        for pair in same_level:
            key = provenance_label(pair.higher)
            level_counts[key] = level_counts.get(key, 0) + 1

        print("Same-level conflict breakdown:")
        for level, count in sorted(level_counts.items(), key=lambda x: -x[1]):
            print(f"  {level} vs {level}: {count}")
        print()

        print("Sample same-level conflicts (up to 5):")
        for pair in same_level[:5]:
            print(f"  Edge {pair.edge_id}:")
            print(f"    A [{provenance_label(pair.higher)}] {pair.higher.id[:12]}...")
            print(f"      conf={pair.higher.confidence:.3f} | {pair.higher.content[:80]}")
            print(f"    B [{provenance_label(pair.lower)}] {pair.lower.id[:12]}...")
            print(f"      conf={pair.lower.confidence:.3f} | {pair.lower.content[:80]}")
            print()


if __name__ == "__main__":
    run_audit(DB_PATH)
