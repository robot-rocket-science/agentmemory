"""Tests for graph traversal (get_neighbors, expand_graph) and uncertainty_score.

Covers the new store methods and scoring function added for /mem:reason.
"""
from __future__ import annotations

from pathlib import Path

from agentmemory.models import Belief, Edge
from agentmemory.scoring import uncertainty_score
from agentmemory.store import MemoryStore


def _make_store(tmp_path: Path) -> MemoryStore:
    """Create an in-memory store with test data."""
    store: MemoryStore = MemoryStore(tmp_path / "test.db")

    # Insert 5 beliefs
    store.insert_belief("Alpha requirement", "requirement", "user_stated", alpha=9.0, beta_param=0.5)
    store.insert_belief("Beta fact", "factual", "agent_inferred", alpha=3.0, beta_param=1.0)
    store.insert_belief("Gamma correction", "correction", "user_corrected", alpha=9.0, beta_param=0.5)
    store.insert_belief("Delta preference", "preference", "user_stated", alpha=0.5, beta_param=0.5)
    store.insert_belief("Epsilon causal", "causal", "agent_inferred", alpha=5.0, beta_param=5.0)

    # Get IDs
    rows = store.query("SELECT id, content FROM beliefs ORDER BY content")
    ids: dict[str, str] = {r["content"]: r["id"] for r in rows}

    # Insert edges
    store.insert_edge(ids["Alpha requirement"], ids["Beta fact"], "SUPPORTS", weight=0.8)
    store.insert_edge(ids["Beta fact"], ids["Gamma correction"], "RELATES_TO", weight=0.5)
    store.insert_edge(ids["Alpha requirement"], ids["Delta preference"], "CONTRADICTS", weight=0.9)
    store.insert_edge(ids["Gamma correction"], ids["Epsilon causal"], "CITES", weight=0.7)

    return store


# ---------------------------------------------------------------------------
# uncertainty_score
# ---------------------------------------------------------------------------


def test_uncertainty_jeffreys_prior() -> None:
    """Jeffreys prior (0.5, 0.5) is maximum uncertainty."""
    score: float = uncertainty_score(0.5, 0.5)
    assert score == 1.0


def test_uncertainty_high_confidence() -> None:
    """Strong evidence in one direction is low uncertainty."""
    score: float = uncertainty_score(9.0, 0.5)
    assert score < 0.1


def test_uncertainty_balanced_many_observations() -> None:
    """Many observations but balanced is moderate uncertainty."""
    score: float = uncertainty_score(50.0, 50.0)
    assert 0.0 < score < 0.15  # low variance due to many observations


def test_uncertainty_zero_total() -> None:
    """Zero parameters returns maximum uncertainty."""
    assert uncertainty_score(0.0, 0.0) == 1.0


def test_uncertainty_asymmetric() -> None:
    """Asymmetric params have lower uncertainty than symmetric."""
    symmetric: float = uncertainty_score(5.0, 5.0)
    asymmetric: float = uncertainty_score(9.0, 1.0)
    assert asymmetric < symmetric


# ---------------------------------------------------------------------------
# get_neighbors
# ---------------------------------------------------------------------------


def test_get_neighbors_outgoing(tmp_path: Path) -> None:
    """Outgoing neighbors of Alpha requirement."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]

    neighbors: list[tuple[Belief, Edge]] = store.get_neighbors(
        alpha_id, direction="outgoing"
    )
    contents: set[str] = {b.content for b, _ in neighbors}
    assert "Beta fact" in contents
    assert "Delta preference" in contents
    assert len(neighbors) == 2
    store.close()


def test_get_neighbors_incoming(tmp_path: Path) -> None:
    """Incoming neighbors of Beta fact."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Beta fact'")
    beta_id: str = rows[0]["id"]

    neighbors: list[tuple[Belief, Edge]] = store.get_neighbors(
        beta_id, direction="incoming"
    )
    contents: set[str] = {b.content for b, _ in neighbors}
    assert "Alpha requirement" in contents
    assert len(neighbors) == 1
    store.close()


def test_get_neighbors_both_directions(tmp_path: Path) -> None:
    """Both directions for Beta fact (incoming from Alpha, outgoing to Gamma)."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Beta fact'")
    beta_id: str = rows[0]["id"]

    neighbors: list[tuple[Belief, Edge]] = store.get_neighbors(
        beta_id, direction="both"
    )
    contents: set[str] = {b.content for b, _ in neighbors}
    assert "Alpha requirement" in contents
    assert "Gamma correction" in contents
    assert len(neighbors) == 2
    store.close()


def test_get_neighbors_filter_by_edge_type(tmp_path: Path) -> None:
    """Filter to CONTRADICTS edges only."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]

    neighbors: list[tuple[Belief, Edge]] = store.get_neighbors(
        alpha_id, edge_types=["CONTRADICTS"]
    )
    assert len(neighbors) == 1
    assert neighbors[0][0].content == "Delta preference"
    assert neighbors[0][1].edge_type == "CONTRADICTS"
    store.close()


def test_get_neighbors_excludes_superseded(tmp_path: Path) -> None:
    """Superseded beliefs are excluded from neighbor results."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Beta fact'")
    beta_id: str = rows[0]["id"]
    rows2 = store.query("SELECT id FROM beliefs WHERE content = 'Gamma correction'")
    gamma_id: str = rows2[0]["id"]

    # Supersede Gamma
    store.supersede_belief(gamma_id, beta_id, reason="test")

    neighbors: list[tuple[Belief, Edge]] = store.get_neighbors(
        beta_id, direction="outgoing"
    )
    contents: set[str] = {b.content for b, _ in neighbors}
    assert "Gamma correction" not in contents
    store.close()


# ---------------------------------------------------------------------------
# expand_graph
# ---------------------------------------------------------------------------


def test_expand_graph_depth_1(tmp_path: Path) -> None:
    """1-hop expansion from Alpha finds Beta and Delta."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]

    expanded: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph(
        [alpha_id], depth=1
    )
    found_contents: set[str] = set()
    for entries in expanded.values():
        for b, _, _ in entries:
            found_contents.add(b.content)

    assert "Beta fact" in found_contents
    assert "Delta preference" in found_contents
    # Gamma and Epsilon are 2+ hops away
    assert "Gamma correction" not in found_contents
    store.close()


def test_expand_graph_depth_2(tmp_path: Path) -> None:
    """2-hop expansion from Alpha finds Beta, Delta, Gamma, and maybe Epsilon."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]

    expanded: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph(
        [alpha_id], depth=2
    )
    found_contents: set[str] = set()
    for entries in expanded.values():
        for b, _, _ in entries:
            found_contents.add(b.content)

    assert "Beta fact" in found_contents
    assert "Gamma correction" in found_contents  # 2 hops via Beta
    store.close()


def test_expand_graph_max_nodes_cap(tmp_path: Path) -> None:
    """max_nodes cap is respected."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]

    expanded: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph(
        [alpha_id], depth=3, max_nodes=2
    )
    total: int = len(expanded)
    assert total <= 2
    store.close()


def test_expand_graph_skips_supersedes(tmp_path: Path) -> None:
    """SUPERSEDES edges are excluded by default."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]
    rows2 = store.query("SELECT id FROM beliefs WHERE content = 'Epsilon causal'")
    epsilon_id: str = rows2[0]["id"]

    # Add a SUPERSEDES edge
    store.insert_edge(alpha_id, epsilon_id, "SUPERSEDES", weight=1.0)

    expanded: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph(
        [alpha_id], depth=1
    )
    found_contents: set[str] = set()
    for entries in expanded.values():
        for b, etype, _ in entries:
            found_contents.add(b.content)
            assert etype != "SUPERSEDES"

    # Epsilon should NOT be found via SUPERSEDES (only via longer path)
    store.close()


def test_expand_graph_empty_seeds(tmp_path: Path) -> None:
    """Empty seed list returns empty result."""
    store: MemoryStore = _make_store(tmp_path)
    expanded: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph([], depth=2)
    assert expanded == {}
    store.close()


def test_expand_graph_deterministic(tmp_path: Path) -> None:
    """Two calls with same inputs produce identical results."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]

    r1: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph(
        [alpha_id], depth=2
    )
    r2: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph(
        [alpha_id], depth=2
    )

    assert set(r1.keys()) == set(r2.keys())
    for key in r1:
        ids1: list[str] = [b.id for b, _, _ in r1[key]]
        ids2: list[str] = [b.id for b, _, _ in r2[key]]
        assert ids1 == ids2
    store.close()
