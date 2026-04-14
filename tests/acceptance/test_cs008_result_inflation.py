"""CS-008: Result Inflation.

Pass criterion: rigor_tier metadata is preserved through insert and retrieval,
allowing consumers to distinguish validated findings from unvalidated ones.
"""
from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    Belief,
)
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore


def test_cs008_rigor_tier_preserved_in_retrieval(store: MemoryStore) -> None:
    """Insert beliefs at three rigor tiers. retrieve() returns all three with
    their rigor_tier intact, so consumers can distinguish validation levels."""
    tiers: list[tuple[str, str]] = [
        ("hypothesis", "HRR binding may improve retrieval recall"),
        ("simulated", "HRR binding simulated on 500 synthetic queries, 0.82 recall"),
        ("empirically_tested", "HRR binding tested on live agentmemory traffic, 0.79 recall"),
    ]
    inserted: dict[str, str] = {}  # id -> expected tier
    for tier, content in tiers:
        b: Belief = store.insert_belief(
            content=content,
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
            rigor_tier=tier,
        )
        inserted[b.id] = tier

    result: RetrievalResult = retrieve(store, "HRR binding retrieval recall")
    returned_ids: set[str] = {b.id for b in result.beliefs}

    for belief_id, expected_tier in inserted.items():
        assert belief_id in returned_ids, (
            f"Belief {belief_id} (tier={expected_tier}) not returned by retrieve()"
        )

    for b in result.beliefs:
        if b.id in inserted:
            assert b.rigor_tier == inserted[b.id], (
                f"Belief {b.id} rigor_tier mismatch: "
                f"expected {inserted[b.id]}, got {b.rigor_tier}"
            )


def test_cs008_mixed_rigor_distinguishable(store: MemoryStore) -> None:
    """Insert 5 beliefs with mixed rigor tiers. SQL query on the beliefs table
    can filter by rigor_tier, proving the store supports tier-based filtering."""
    entries: list[tuple[str, str]] = [
        ("hypothesis", "Proposed: event sourcing for belief history"),
        ("hypothesis", "Proposed: CRDT merge for multi-agent beliefs"),
        ("simulated", "Simulated: event sourcing handles 10k beliefs in 200ms"),
        ("empirically_tested", "Tested: CRDT merge on 2 agents, 0 conflicts in 50 runs"),
        ("validated", "Validated: FTS5 search latency under 5ms on 10k beliefs"),
    ]
    for tier, content in entries:
        store.insert_belief(
            content=content,
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
            rigor_tier=tier,
        )

    conn = store._conn  # pyright: ignore[reportPrivateUsage]

    # Filter by each tier and verify counts.
    for expected_tier, expected_count in [
        ("hypothesis", 2),
        ("simulated", 1),
        ("empirically_tested", 1),
        ("validated", 1),
    ]:
        rows = conn.execute(
            "SELECT COUNT(*) AS cnt FROM beliefs WHERE rigor_tier = ? AND valid_to IS NULL",
            (expected_tier,),
        ).fetchone()
        assert rows is not None
        assert int(rows["cnt"]) == expected_count, (
            f"Expected {expected_count} beliefs with rigor_tier={expected_tier}, "
            f"got {rows['cnt']}"
        )
