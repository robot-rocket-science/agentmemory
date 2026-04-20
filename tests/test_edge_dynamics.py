"""Tests for dynamic edge scoring and traversal tracking."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_CORRECTED,
    Belief,
)
from agentmemory.store import MemoryStore


@pytest.fixture()
def store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    s: MemoryStore = MemoryStore(tmp_path / "test_edge_dynamics.db")
    yield s
    s.close()


# --- Schema migration ---


def test_edge_columns_exist(store: MemoryStore) -> None:
    """Migration adds alpha, beta_param, traversal_count, last_traversed_at, pruned_at."""
    cols = store.query("PRAGMA table_info(edges)")
    col_names: set[str] = {row["name"] for row in cols}
    assert "alpha" in col_names
    assert "beta_param" in col_names
    assert "traversal_count" in col_names
    assert "last_traversed_at" in col_names
    assert "pruned_at" in col_names


# --- Edge insert with priors ---


def test_insert_edge_default_priors(store: MemoryStore) -> None:
    """Edges created without explicit priors get Beta(1,1)."""
    a: Belief = store.insert_belief(
        "Belief A about testing", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    b: Belief = store.insert_belief(
        "Belief B about testing", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    edge_id: int = store.insert_edge(a.id, b.id, "SUPPORTS", weight=0.8)

    row = store.query("SELECT alpha, beta_param FROM edges WHERE id = ?", (edge_id,))[0]
    assert float(str(row["alpha"])) == 1.0
    assert float(str(row["beta_param"])) == 1.0


def test_insert_edge_custom_priors(store: MemoryStore) -> None:
    """Edges created with explicit priors preserve them."""
    a: Belief = store.insert_belief(
        "Belief A correction", BELIEF_FACTUAL, BSRC_USER_CORRECTED
    )
    b: Belief = store.insert_belief(
        "Belief B original", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    edge_id: int = store.insert_edge(
        a.id, b.id, "SUPERSEDES", alpha=9.0, beta_param=1.0
    )

    row = store.query("SELECT alpha, beta_param FROM edges WHERE id = ?", (edge_id,))[0]
    assert float(str(row["alpha"])) == 9.0
    assert float(str(row["beta_param"])) == 1.0


# --- Edge exists check ---


def test_edge_exists(store: MemoryStore) -> None:
    a: Belief = store.insert_belief("Belief X", BELIEF_FACTUAL, BSRC_AGENT_INFERRED)
    b: Belief = store.insert_belief("Belief Y", BELIEF_FACTUAL, BSRC_AGENT_INFERRED)
    c: Belief = store.insert_belief("Belief Z", BELIEF_FACTUAL, BSRC_AGENT_INFERRED)
    store.insert_edge(a.id, b.id, "SUPPORTS")

    assert store.edge_exists(a.id, b.id)
    assert store.edge_exists(b.id, a.id)  # either direction
    assert not store.edge_exists(a.id, c.id)


# --- Traversal tracking ---


def test_expand_graph_records_traversals(store: MemoryStore) -> None:
    """BFS expansion increments traversal_count and sets last_traversed_at."""
    a: Belief = store.insert_belief(
        "Seed belief about architecture", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    b: Belief = store.insert_belief(
        "Connected belief about design", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    edge_id: int = store.insert_edge(a.id, b.id, "SUPPORTS", weight=0.9)

    # Before expansion
    row_before = store.query(
        "SELECT traversal_count, last_traversed_at FROM edges WHERE id = ?", (edge_id,)
    )[0]
    assert int(str(row_before["traversal_count"])) == 0
    assert row_before["last_traversed_at"] is None

    # Expand from seed
    result = store.expand_graph([a.id], depth=1)
    assert b.id in result

    # After expansion
    row_after = store.query(
        "SELECT traversal_count, last_traversed_at FROM edges WHERE id = ?", (edge_id,)
    )[0]
    assert int(str(row_after["traversal_count"])) == 1
    assert row_after["last_traversed_at"] is not None


def test_expand_graph_stores_traversal_log(store: MemoryStore) -> None:
    """BFS expansion populates _last_traversed_edges for feedback propagation."""
    a: Belief = store.insert_belief(
        "Root node belief", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    b: Belief = store.insert_belief("Hop 1 belief", BELIEF_FACTUAL, BSRC_AGENT_INFERRED)
    c: Belief = store.insert_belief("Hop 2 belief", BELIEF_FACTUAL, BSRC_AGENT_INFERRED)
    e1: int = store.insert_edge(a.id, b.id, "SUPPORTS", weight=0.9)
    e2: int = store.insert_edge(b.id, c.id, "RELATES_TO", weight=0.7)

    store.expand_graph([a.id], depth=2)

    log = store._last_traversed_edges  # pyright: ignore[reportPrivateUsage]
    assert b.id in log
    assert any(eid == e1 for eid, _ in log[b.id])
    assert c.id in log
    assert any(eid == e2 for eid, _ in log[c.id])


# --- Feedback propagation ---


def test_feedback_propagates_to_edges(store: MemoryStore) -> None:
    """When a belief gets 'used' feedback, edges that led to it are strengthened."""
    a: Belief = store.insert_belief(
        "Source belief for propagation", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    b: Belief = store.insert_belief(
        "Destination belief for propagation", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    edge_id: int = store.insert_edge(a.id, b.id, "SUPPORTS")

    # Simulate traversal
    store.expand_graph([a.id], depth=1)

    # Apply feedback
    store.update_confidence(b.id, "used")

    # Check edge was strengthened
    row = store.query("SELECT alpha, beta_param FROM edges WHERE id = ?", (edge_id,))[0]
    alpha: float = float(str(row["alpha"]))
    assert alpha > 1.0  # was 1.0, should have been incremented


def test_harmful_feedback_weakens_edges(store: MemoryStore) -> None:
    """'harmful' feedback on a belief weakens edges that led to it."""
    a: Belief = store.insert_belief(
        "Source for harmful test", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    b: Belief = store.insert_belief(
        "Harmful destination test", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    edge_id: int = store.insert_edge(a.id, b.id, "RELATES_TO")

    store.expand_graph([a.id], depth=1)
    store.update_confidence(b.id, "harmful")

    row = store.query("SELECT alpha, beta_param FROM edges WHERE id = ?", (edge_id,))[0]
    beta: float = float(str(row["beta_param"]))
    assert beta > 1.0  # was 1.0, should have been incremented


def test_hop_distance_discounts_feedback(store: MemoryStore) -> None:
    """Hop 2 edges get less feedback credit than hop 1."""
    a: Belief = store.insert_belief(
        "Hop discount root", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    b: Belief = store.insert_belief(
        "Hop discount mid", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    c: Belief = store.insert_belief(
        "Hop discount leaf", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    store.insert_edge(a.id, b.id, "SUPPORTS", weight=0.9)
    e2: int = store.insert_edge(b.id, c.id, "SUPPORTS", weight=0.9)

    store.expand_graph([a.id], depth=2)

    # Feedback on hop-2 belief
    store.update_confidence(c.id, "used")

    r2 = store.query("SELECT alpha FROM edges WHERE id = ?", (e2,))[0]
    alpha_e2: float = float(str(r2["alpha"]))
    # e2 is hop 1 from b to c (hop=1 in the traversal log for c)
    # But c was reached at hop 2 from root -- the edge e2 was the hop-2 edge
    # Discount = 0.5^(2-1) = 0.5
    assert alpha_e2 > 1.0  # should be incremented by discounted amount


# --- Edge health metrics ---


def test_edge_health_metrics(store: MemoryStore) -> None:
    """get_edge_health returns expected structure."""
    a: Belief = store.insert_belief(
        "Health metric A", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    b: Belief = store.insert_belief(
        "Health metric B", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    store.insert_edge(a.id, b.id, "SUPPORTS")

    health: dict[str, object] = store.get_edge_health()
    assert health["active_edges"] == 1
    assert health["pruned_edges"] == 0
    assert health["never_traversed_edges"] == 1
    assert health["edge_credal_gap"] == 1  # at default prior


# --- BFS uses Bayesian scoring ---


def test_bfs_prefers_high_confidence_edges(store: MemoryStore) -> None:
    """BFS should prefer edges with higher Bayesian confidence."""
    root: Belief = store.insert_belief(
        "BFS scoring root", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    weak: Belief = store.insert_belief(
        "Weakly connected", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    strong: Belief = store.insert_belief(
        "Strongly connected", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )

    # Same edge type and weight, but different alpha/beta
    store.insert_edge(
        root.id, weak.id, "SUPPORTS", weight=1.0, alpha=1.0, beta_param=5.0
    )
    store.insert_edge(
        root.id, strong.id, "SUPPORTS", weight=1.0, alpha=9.0, beta_param=1.0
    )

    result = store.expand_graph([root.id], depth=1, max_nodes=1)
    # With max_nodes=1, only the highest-scoring edge should be traversed
    assert strong.id in result
    assert weak.id not in result


# --- Pruned edges excluded ---


def test_pruned_edges_excluded_from_neighbors(store: MemoryStore) -> None:
    """Edges with pruned_at set are excluded from get_neighbors."""
    a: Belief = store.insert_belief(
        "Pruned test A", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    b: Belief = store.insert_belief(
        "Pruned test B", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    edge_id: int = store.insert_edge(a.id, b.id, "RELATES_TO")

    # Manually prune the edge
    store.query(  # pyright: ignore[reportUnusedCallResult]
        "SELECT 1"  # dummy -- we need to use _conn directly
    )
    store._conn.execute(  # pyright: ignore[reportPrivateUsage]
        "UPDATE edges SET pruned_at = '2026-01-01T00:00:00Z' WHERE id = ?",
        (edge_id,),
    )
    store._conn.commit()  # pyright: ignore[reportPrivateUsage]

    neighbors = store.get_neighbors(a.id)
    assert len(neighbors) == 0
