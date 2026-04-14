"""CS-019: Death by a Thousand Cuts.

Pass criterion: CALLS edges enable pipeline traversal via BFS, and stages
without TESTS edges are detectable as untested.
"""
from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    Belief,
)
from agentmemory.store import MemoryStore


def test_cs019_pipeline_traversable_via_bfs(store: MemoryStore) -> None:
    """Insert 4 pipeline stage beliefs (A, B, C, D) connected by CALLS edges.
    BFS from A with depth 3 should reach D."""
    stages: dict[str, Belief] = {}
    for label in ("A", "B", "C", "D"):
        b: Belief = store.insert_belief(
            content=f"Pipeline stage {label}: processes input and forwards to next stage",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )
        stages[label] = b

    # Create CALLS chain: A -> B -> C -> D
    store.insert_graph_edge(from_id=stages["A"].id, to_id=stages["B"].id, edge_type="CALLS")
    store.insert_graph_edge(from_id=stages["B"].id, to_id=stages["C"].id, edge_type="CALLS")
    store.insert_graph_edge(from_id=stages["C"].id, to_id=stages["D"].id, edge_type="CALLS")

    # BFS from A: collect all reachable nodes within depth 3.
    conn = store._conn  # pyright: ignore[reportPrivateUsage]
    visited: set[str] = set()
    frontier: list[str] = [stages["A"].id]
    for _depth in range(3):
        if not frontier:
            break
        next_frontier: list[str] = []
        for node in frontier:
            if node in visited:
                continue
            visited.add(node)
            rows = conn.execute(
                "SELECT to_id FROM graph_edges WHERE from_id = ? AND edge_type = 'CALLS'",
                (node,),
            ).fetchall()
            next_frontier.extend(str(r["to_id"]) for r in rows)
        frontier = next_frontier

    # Include final frontier nodes.
    visited.update(frontier)

    assert stages["D"].id in visited, (
        f"BFS from stage A should reach stage D within depth 3. "
        f"Visited: {visited}"
    )


def test_cs019_untested_stages_detectable(store: MemoryStore) -> None:
    """Insert 4 pipeline stages. Add TESTS edges only for A and B. Stages C and
    D should be identifiable as untested via graph_edges query."""
    stages: dict[str, Belief] = {}
    for label in ("A", "B", "C", "D"):
        b: Belief = store.insert_belief(
            content=f"Pipeline stage {label}: integration component",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )
        stages[label] = b

    # TESTS edges exist only for A and B.
    store.insert_graph_edge(
        from_id="test:test_stage_a.py", to_id=stages["A"].id, edge_type="TESTS"
    )
    store.insert_graph_edge(
        from_id="test:test_stage_b.py", to_id=stages["B"].id, edge_type="TESTS"
    )

    conn = store._conn  # pyright: ignore[reportPrivateUsage]
    tested_rows = conn.execute(
        "SELECT DISTINCT to_id FROM graph_edges WHERE edge_type = 'TESTS'"
    ).fetchall()
    tested_ids: set[str] = {str(r["to_id"]) for r in tested_rows}

    all_stage_ids: set[str] = {b.id for b in stages.values()}
    untested: set[str] = all_stage_ids - tested_ids

    assert stages["C"].id in untested, (
        f"Stage C should be untested. Tested: {tested_ids}"
    )
    assert stages["D"].id in untested, (
        f"Stage D should be untested. Tested: {tested_ids}"
    )
    assert stages["A"].id not in untested, "Stage A has a TESTS edge"
    assert stages["B"].id not in untested, "Stage B has a TESTS edge"
