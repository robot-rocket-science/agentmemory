"""CS-022: Multi-Hop Operational Query Collapse.

Pass criterion: BFS traversal via expand_graph can answer multi-hop queries --
depth=2 reaches two hops away, depth=1 does not.
"""
from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    Belief,
)
from agentmemory.store import MemoryStore


def test_cs022_two_hop_traversal(store: MemoryStore) -> None:
    """BFS depth=2 from belief A reaches belief C (two hops: A->B->C)."""
    a: Belief = store.insert_belief(
        content="Server runs on port 8080",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    b: Belief = store.insert_belief(
        content="Port 8080 is configured in config.yaml",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    c: Belief = store.insert_belief(
        content="config.yaml is in /etc/app/",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    # Create edges: A->B (SUPPORTS), B->C (CITES).
    store.insert_edge(from_id=a.id, to_id=b.id, edge_type="SUPPORTS")
    store.insert_edge(from_id=b.id, to_id=c.id, edge_type="CITES")

    # BFS depth=2 from A.
    graph: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph(
        seed_ids=[a.id], depth=2
    )

    reached_ids: set[str] = set(graph.keys())
    assert b.id in reached_ids, f"B should be reachable at depth 1. Reached: {reached_ids}"
    assert c.id in reached_ids, f"C should be reachable at depth 2. Reached: {reached_ids}"

    # Verify hop distances.
    b_hops: list[int] = [hop for _, _, hop in graph[b.id]]
    c_hops: list[int] = [hop for _, _, hop in graph[c.id]]
    assert 1 in b_hops, f"B should be at hop 1. Hops: {b_hops}"
    assert 2 in c_hops, f"C should be at hop 2. Hops: {c_hops}"


def test_cs022_single_hop_insufficient(store: MemoryStore) -> None:
    """BFS depth=1 from belief A reaches B but NOT C, proving the depth
    limit prevents multi-hop collapse."""
    a: Belief = store.insert_belief(
        content="Server runs on port 9090",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    b: Belief = store.insert_belief(
        content="Port 9090 is configured in settings.yaml",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    c: Belief = store.insert_belief(
        content="settings.yaml is in /opt/service/",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    store.insert_edge(from_id=a.id, to_id=b.id, edge_type="SUPPORTS")
    store.insert_edge(from_id=b.id, to_id=c.id, edge_type="CITES")

    # BFS depth=1 from A.
    graph: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph(
        seed_ids=[a.id], depth=1
    )

    reached_ids: set[str] = set(graph.keys())
    assert b.id in reached_ids, f"B should be reachable at depth 1. Reached: {reached_ids}"
    assert c.id not in reached_ids, (
        f"C should NOT be reachable at depth 1. Reached: {reached_ids}"
    )
