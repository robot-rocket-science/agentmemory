"""CS-025: Point-Fix Correction Without Generalization.

Pass criterion: Corrections are findable by related queries (shared vocabulary),
and SUPPORTS edges enable generalization from specific corrections to broader rules.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_CORRECTION,
    BELIEF_PROCEDURAL,
    BSRC_USER_CORRECTED,
    Belief,
)
from agentmemory.store import MemoryStore


def test_cs025_correction_findable_by_related_query(store: MemoryStore) -> None:
    """A correction about subprocess.run timeout is retrievable when searching
    for 'running shell commands' due to shared vocabulary."""
    correction: Belief = store.insert_belief(
        content="Do not use subprocess.run without timeout parameter.",
        belief_type=BELIEF_CORRECTION,
        source_type=BSRC_USER_CORRECTED,
    )

    # Search with related but not identical terms. FTS5 porter stemming
    # should match "subprocess" and "run" tokens present in the correction.
    results: list[Belief] = store.search("subprocess run timeout")
    result_ids: list[str] = [r.id for r in results]
    assert correction.id in result_ids, (
        "Correction about subprocess.run must be findable by related query. "
        f"Got IDs: {result_ids}"
    )


def test_cs025_correction_with_supports_edge(store: MemoryStore) -> None:
    """A SUPPORTS edge from a specific correction to a general rule enables
    BFS to discover the generalization from the point fix."""
    c1: Belief = store.insert_belief(
        content="Do not use subprocess.run without timeout parameter.",
        belief_type=BELIEF_CORRECTION,
        source_type=BSRC_USER_CORRECTED,
    )
    c2: Belief = store.insert_belief(
        content="All external process calls need timeout guards.",
        belief_type=BELIEF_PROCEDURAL,
        source_type=BSRC_USER_CORRECTED,
    )

    # Link the specific correction to the general rule.
    store.insert_edge(from_id=c1.id, to_id=c2.id, edge_type="SUPPORTS")

    # BFS from C1 should find C2.
    graph: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph(
        seed_ids=[c1.id], depth=1
    )

    reached_ids: set[str] = set(graph.keys())
    assert c2.id in reached_ids, (
        "General rule C2 should be reachable from correction C1 via SUPPORTS edge. "
        f"Reached: {reached_ids}"
    )

    # Verify edge type is SUPPORTS.
    c2_entries: list[tuple[Belief, str, int]] = graph[c2.id]
    edge_types: list[str] = [etype for _, etype, _ in c2_entries]
    assert "SUPPORTS" in edge_types, f"Edge type should be SUPPORTS. Got: {edge_types}"
