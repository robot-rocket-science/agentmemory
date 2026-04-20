"""CS-018: Dual-Source-of-Truth State Machine Bug.

Pass criterion: IMPLEMENTS edges can detect missing roadmap-to-DB mappings --
milestones without IMPLEMENTS edges are identifiable as unimplemented.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_REQUIREMENT,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.store import MemoryStore


def test_cs018_missing_implements_detectable(store: MemoryStore) -> None:
    """Of three roadmap milestones, only S01 has an IMPLEMENTS edge.
    S02 and S03 are identifiable as unimplemented gaps."""
    # Insert three milestone beliefs.
    s01: Belief = store.insert_belief(
        content="Milestone M005 S01: database schema migration",
        belief_type=BELIEF_REQUIREMENT,
        source_type=BSRC_USER_STATED,
    )
    s02: Belief = store.insert_belief(
        content="Milestone M005 S02: API endpoint creation",
        belief_type=BELIEF_REQUIREMENT,
        source_type=BSRC_USER_STATED,
    )
    s03: Belief = store.insert_belief(
        content="Milestone M005 S03: integration test suite",
        belief_type=BELIEF_REQUIREMENT,
        source_type=BSRC_USER_STATED,
    )

    # Only S01 has an IMPLEMENTS edge from a code file.
    store.insert_graph_edge(
        from_id="file:db/m005_s01.py",
        to_id="req:M005-S01",
        edge_type="IMPLEMENTS",
    )

    # Query IMPLEMENTS edges to find which requirements are covered.
    conn = store._conn  # pyright: ignore[reportPrivateUsage]
    rows = conn.execute(
        "SELECT DISTINCT to_id FROM graph_edges WHERE edge_type = 'IMPLEMENTS'"
    ).fetchall()
    implemented_reqs: set[str] = {r["to_id"] for r in rows}

    assert "req:M005-S01" in implemented_reqs, "S01 should have an IMPLEMENTS edge"

    # S02 and S03 requirement IDs have no IMPLEMENTS edges.
    # Check that their corresponding req: identifiers are absent.
    assert "req:M005-S02" not in implemented_reqs, (
        "S02 should NOT have an IMPLEMENTS edge -- it is a gap"
    )
    assert "req:M005-S03" not in implemented_reqs, (
        "S03 should NOT have an IMPLEMENTS edge -- it is a gap"
    )

    # Verify the beliefs themselves are still in the store (not lost).
    all_milestones: list[Belief] = store.search("Milestone M005")
    milestone_ids: set[str] = {b.id for b in all_milestones}
    assert {s01.id, s02.id, s03.id} <= milestone_ids, (
        f"All three milestone beliefs must be retrievable. Got: {milestone_ids}"
    )
