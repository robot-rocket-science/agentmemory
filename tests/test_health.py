"""Tests for health diagnostics (credal gap, orphans, edge counts)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentmemory.models import Belief
from agentmemory.store import MemoryStore


@pytest.fixture()
def store(tmp_path: Path) -> MemoryStore:
    db_path: Path = tmp_path / "test_health.db"
    return MemoryStore(db_path)


def test_health_metrics_returns_expected_keys(store: MemoryStore) -> None:
    """get_health_metrics() returns all expected keys even on empty DB."""
    metrics: dict[str, object] = store.get_health_metrics()
    expected_keys: set[str] = {
        "active_beliefs",
        "credal_gap_count",
        "credal_gap_pct",
        "orphan_count",
        "orphan_pct",
        "contradicts_edges",
        "supports_edges",
        "supersedes_edges",
        "feedback_coverage_count",
        "feedback_coverage_pct",
        "avg_confidence",
        "stale_sessions",
        "type_priors",
    }
    assert set(metrics.keys()) == expected_keys


def test_health_empty_db(store: MemoryStore) -> None:
    """Health metrics on empty DB return zeros."""
    metrics: dict[str, object] = store.get_health_metrics()
    assert metrics["active_beliefs"] == 0
    assert metrics["credal_gap_count"] == 0
    assert metrics["orphan_count"] == 0


def test_credal_gap_counts_untested(store: MemoryStore) -> None:
    """Beliefs at their type prior are counted as untested (credal gap)."""
    # Insert 3 beliefs at default factual prior (alpha=3.0, beta=1.0)
    for i in range(3):
        store.insert_belief(
            content=f"Factual statement number {i} about the codebase architecture",
            belief_type="factual",
            source_type="agent_inferred",
            alpha=3.0,
            beta_param=1.0,
        )

    # Insert 1 belief that has received feedback (alpha shifted)
    b = store.insert_belief(
        content="This belief has been tested and confirmed useful by agent",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )
    store.update_confidence(b.id, "used", weight=2.0)

    metrics: dict[str, object] = store.get_health_metrics()
    # 3 at prior, 1 tested (alpha shifted from 3.0 to 5.0)
    assert metrics["credal_gap_count"] == 3
    assert metrics["active_beliefs"] == 4


def test_orphan_count(store: MemoryStore) -> None:
    """Beliefs with no edges are orphans."""
    store.insert_belief(
        content="Orphan belief with no connections to anything else",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )
    b2 = store.insert_belief(
        content="Connected belief that has an edge relationship",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )
    b3 = store.insert_belief(
        content="Another connected belief in the edge graph",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )
    store.insert_edge(b2.id, b3.id, "SUPPORTS", weight=0.8, reason="test")

    metrics: dict[str, object] = store.get_health_metrics()
    assert metrics["orphan_count"] == 1  # b1 is the orphan


def test_edge_type_counts(store: MemoryStore) -> None:
    """Edge type breakdown counts correctly."""
    b1 = store.insert_belief(
        content="First belief about the database configuration",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )
    b2 = store.insert_belief(
        content="Second belief about the database configuration",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )
    b3 = store.insert_belief(
        content="Third belief that contradicts the first belief",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )

    store.insert_edge(b1.id, b2.id, "SUPPORTS", weight=0.8, reason="test")
    store.insert_edge(b3.id, b1.id, "CONTRADICTS", weight=0.7, reason="test")
    store.supersede_belief(b2.id, b3.id, reason="test")

    metrics: dict[str, object] = store.get_health_metrics()
    assert metrics["supports_edges"] == 1
    assert metrics["contradicts_edges"] == 1
    assert metrics["supersedes_edges"] == 1


def test_snapshot_returns_beliefs_at_time(store: MemoryStore) -> None:
    """get_snapshot() returns beliefs active at given timestamp."""
    store.insert_belief(
        content="Early belief about project setup and configuration",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )
    store.insert_belief(
        content="Later belief about project testing and validation",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )

    # Current snapshot should include both
    snapshot: list[Belief] = store.get_snapshot()
    assert len(snapshot) == 2

    # Snapshot at future time includes both
    snapshot_future: list[Belief] = store.get_snapshot(
        at_time="2099-01-01T00:00:00+00:00"
    )
    assert len(snapshot_future) == 2


def test_snapshot_excludes_superseded(store: MemoryStore) -> None:
    """get_snapshot() excludes beliefs superseded before the snapshot time."""
    b1 = store.insert_belief(
        content="Original belief about database configuration",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )
    b2 = store.insert_belief(
        content="Updated belief about database configuration with changes",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )
    store.supersede_belief(b1.id, b2.id, reason="updated")

    snapshot: list[Belief] = store.get_snapshot()
    ids: set[str] = {b.id for b in snapshot}
    assert b2.id in ids
    assert b1.id not in ids


def test_snapshot_filters_by_type(store: MemoryStore) -> None:
    """get_snapshot() can filter by belief_type."""
    store.insert_belief(
        content="A factual statement about the codebase",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )
    store.insert_belief(
        content="A requirement for the system behavior",
        belief_type="requirement",
        source_type="user_stated",
        alpha=9.0,
        beta_param=0.5,
    )

    factual_snap: list[Belief] = store.get_snapshot(belief_type="factual")
    assert len(factual_snap) == 1
    assert factual_snap[0].belief_type == "factual"

    req_snap: list[Belief] = store.get_snapshot(belief_type="requirement")
    assert len(req_snap) == 1
    assert req_snap[0].belief_type == "requirement"
