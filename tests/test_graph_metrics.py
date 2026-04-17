"""Tests for graph metrics: degree, PageRank, structural importance."""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from agentmemory.graph_metrics import (
    compute_degree_centrality,
    compute_pagerank,
    compute_structural_importance,
    structural_boost,
)
from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    OBS_TYPE_USER_STATEMENT,
    SRC_USER,
)
from agentmemory.store import MemoryStore


@pytest.fixture()
def store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    s: MemoryStore = MemoryStore(tmp_path / "test.db")
    yield s
    s.close()


def _make_belief(store: MemoryStore, content: str) -> str:
    store.insert_observation(
        content=content,
        observation_type=OBS_TYPE_USER_STATEMENT,
        source_type=SRC_USER,
        source_id="test",
    )
    belief = store.insert_belief(
        content=content,
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=2.0,
        beta_param=1.0,
    )
    return belief.id


def test_degree_empty(store: MemoryStore) -> None:
    """No beliefs means empty degree dict."""
    result: dict[str, int] = compute_degree_centrality(store)
    assert result == {}


def test_degree_with_edges(store: MemoryStore) -> None:
    """Degree counts edges correctly."""
    a: str = _make_belief(store, "Node A")
    b: str = _make_belief(store, "Node B")
    c: str = _make_belief(store, "Node C")

    store.insert_edge(a, b, "SUPPORTS", reason="test")
    store.insert_edge(a, c, "SUPPORTS", reason="test")

    degrees: dict[str, int] = compute_degree_centrality(store)
    # A has 2 edges (outgoing to B and C)
    assert degrees[a] == 2
    # B and C have 1 edge each (incoming from A)
    assert degrees[b] == 1
    assert degrees[c] == 1


def test_pagerank_empty(store: MemoryStore) -> None:
    """No edges means empty PageRank."""
    result: dict[str, float] = compute_pagerank(store)
    assert result == {}


def test_pagerank_simple_chain(store: MemoryStore) -> None:
    """A -> B -> C: C should have highest PageRank."""
    a: str = _make_belief(store, "Start")
    b: str = _make_belief(store, "Middle")
    c: str = _make_belief(store, "End")

    store.insert_edge(a, b, "SUPPORTS", reason="")
    store.insert_edge(b, c, "SUPPORTS", reason="")

    pr: dict[str, float] = compute_pagerank(store)
    assert pr[c] > pr[b] > pr[a]


def test_pagerank_hub(store: MemoryStore) -> None:
    """A hub node (many incoming edges) gets high PageRank."""
    hub: str = _make_belief(store, "Hub")
    spokes: list[str] = []
    for i in range(5):
        s: str = _make_belief(store, f"Spoke {i}")
        spokes.append(s)
        store.insert_edge(s, hub, "SUPPORTS", reason="")

    pr: dict[str, float] = compute_pagerank(store)
    # Hub should have the highest rank
    assert pr[hub] == max(pr.values())


def test_structural_importance(store: MemoryStore) -> None:
    """Combined score is between 0 and 1."""
    a: str = _make_belief(store, "A")
    b: str = _make_belief(store, "B")
    store.insert_edge(a, b, "SUPPORTS", reason="")

    importance: dict[str, float] = compute_structural_importance(store)
    for score in importance.values():
        assert 0.0 <= score <= 1.0


def test_structural_boost_no_edges() -> None:
    """Beliefs with no importance get 1.0 (no boost)."""
    assert structural_boost("nonexistent", {}) == 1.0


def test_structural_boost_high_importance() -> None:
    """High importance beliefs get up to 2.0x boost."""
    cache: dict[str, float] = {"hub": 1.0, "leaf": 0.1}
    assert structural_boost("hub", cache) == 2.0
    assert 1.0 < structural_boost("leaf", cache) < 1.5


def test_pagerank_sums_to_one(store: MemoryStore) -> None:
    """PageRank values should approximately sum to 1.0."""
    nodes: list[str] = []
    for i in range(10):
        nodes.append(_make_belief(store, f"Node {i}"))
    for i in range(9):
        store.insert_edge(nodes[i], nodes[i + 1], "SUPPORTS", reason="")

    pr: dict[str, float] = compute_pagerank(store)
    total: float = sum(pr.values())
    assert abs(total - 1.0) < 0.01, f"PageRank sum = {total}, expected ~1.0"
