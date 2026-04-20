"""Tests for intention-space clustering and hook-path integration."""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from agentmemory.intention import build_cluster_table, build_features, cluster_beliefs
from agentmemory.store import MemoryStore


@pytest.fixture()
def store(tmp_path: Path) -> MemoryStore:
    """Store with beliefs spanning multiple types and sources."""
    s: MemoryStore = MemoryStore(tmp_path / "intention_test.db")

    # Create diverse beliefs
    for i in range(10):
        s.insert_belief(
            content=f"Factual agent belief {i} about retrieval pipeline",
            belief_type="factual",
            source_type="agent_inferred",
        )
    for i in range(5):
        s.insert_belief(
            content=f"User correction {i}: always use strict typing",
            belief_type="correction",
            source_type="user_corrected",
        )
    for i in range(3):
        s.insert_belief(
            content=f"Speculative hypothesis {i} about future architecture",
            belief_type="speculative",
            source_type="agent_inferred",
        )
    for i in range(2):
        s.insert_belief(
            content=f"Requirement {i}: system must handle 10K beliefs",
            belief_type="requirement",
            source_type="user_stated",
        )

    # Add some edges
    all_beliefs = s.connection.execute("SELECT id, belief_type FROM beliefs").fetchall()
    factuals = [r["id"] for r in all_beliefs if r["belief_type"] == "factual"]
    corrections = [r["id"] for r in all_beliefs if r["belief_type"] == "correction"]

    if len(factuals) >= 2:
        s.insert_edge(factuals[0], factuals[1], "SUPPORTS", reason="test")
    if factuals and corrections:
        s.insert_edge(corrections[0], factuals[0], "CONTRADICTS", reason="test")

    return s


class TestBuildFeatures:
    """Test feature extraction."""

    def test_returns_correct_count(self, store: MemoryStore) -> None:
        ids, features = build_features(store.connection)
        assert len(ids) == 20  # 10 + 5 + 3 + 2
        assert features.shape == (20, 37)

    def test_empty_store(self, tmp_path: Path) -> None:
        s = MemoryStore(tmp_path / "empty.db")
        ids, features = build_features(s.connection)
        assert len(ids) == 0
        assert features.shape[0] == 0
        s.close()

    def test_features_are_finite(self, store: MemoryStore) -> None:
        import numpy as np

        _, features = build_features(store.connection)
        assert np.all(np.isfinite(features)), "All features should be finite"


class TestClusterBeliefs:
    """Test k-means clustering."""

    def test_assigns_all_beliefs(self, store: MemoryStore) -> None:
        ids, features = build_features(store.connection)
        assignments = cluster_beliefs(ids, features, k=4)
        assert len(assignments) == len(ids)

    def test_correct_number_of_clusters(self, store: MemoryStore) -> None:
        ids, features = build_features(store.connection)
        assignments = cluster_beliefs(ids, features, k=4)
        unique = set(assignments)
        assert len(unique) <= 4

    def test_deterministic(self, store: MemoryStore) -> None:
        ids, features = build_features(store.connection)
        a1 = cluster_beliefs(ids, features, k=4, seed=42)
        a2 = cluster_beliefs(ids, features, k=4, seed=42)
        assert a1 == a2, "Same seed should produce same clusters"

    def test_different_seeds_may_differ(self, store: MemoryStore) -> None:
        ids, features = build_features(store.connection)
        a1 = cluster_beliefs(ids, features, k=4, seed=42)
        a2 = cluster_beliefs(ids, features, k=4, seed=999)
        # Not guaranteed to differ, but at least both should be valid
        assert len(a1) == len(a2)

    def test_fewer_beliefs_than_k(self, tmp_path: Path) -> None:
        s = MemoryStore(tmp_path / "small.db")
        for i in range(3):
            s.insert_belief(
                content=f"belief {i}",
                belief_type="factual",
                source_type="agent_inferred",
            )
        ids, features = build_features(s.connection)
        assignments = cluster_beliefs(ids, features, k=10)
        assert len(assignments) == 3
        s.close()


class TestBuildClusterTable:
    """Test end-to-end cluster table population."""

    def test_populates_table(self, store: MemoryStore) -> None:
        count = build_cluster_table(store.connection, k=4)
        assert count == 20

        rows = store.connection.execute(
            "SELECT COUNT(*) FROM belief_clusters"
        ).fetchone()[0]
        assert rows == 20

    def test_idempotent(self, store: MemoryStore) -> None:
        build_cluster_table(store.connection, k=4)
        count1 = store.connection.execute(
            "SELECT COUNT(*) FROM belief_clusters"
        ).fetchone()[0]

        build_cluster_table(store.connection, k=4)
        count2 = store.connection.execute(
            "SELECT COUNT(*) FROM belief_clusters"
        ).fetchone()[0]
        assert count2 == count1

    def test_clusters_separate_types(self, store: MemoryStore) -> None:
        """Corrections and factuals should mostly end up in different clusters."""
        build_cluster_table(store.connection, k=4)

        rows = store.connection.execute(
            """SELECT bc.cluster_id, b.belief_type
               FROM belief_clusters bc
               JOIN beliefs b ON b.id = bc.belief_id"""
        ).fetchall()

        # Group by cluster, count types
        cluster_types: dict[int, Counter[str]] = {}
        for r in rows:
            cid: int = r["cluster_id"]
            bt: str = r["belief_type"]
            if cid not in cluster_types:
                cluster_types[cid] = Counter()
            cluster_types[cid][bt] += 1

        # At least one cluster should be correction-dominated
        correction_clusters = [
            cid
            for cid, counts in cluster_types.items()
            if counts.get("correction", 0) > counts.get("factual", 0)
        ]
        assert len(correction_clusters) >= 1, (
            f"Expected at least one correction-dominated cluster, got {cluster_types}"
        )


class TestHookPathIntegration:
    """Test the SQL query pattern used by hook_search.py."""

    def test_cluster_expansion_query(self, store: MemoryStore) -> None:
        """Simulate the hook_search.py Layer 1.7 query."""
        build_cluster_table(store.connection, k=4)

        conn: sqlite3.Connection = store.connection
        # Pick a belief
        seed = conn.execute("SELECT belief_id FROM belief_clusters LIMIT 1").fetchone()
        assert seed is not None

        seed_id: str = seed["belief_id"]
        # Same query as hook_search.py Layer 1.7
        rows = conn.execute(
            """SELECT DISTINCT b.* FROM belief_clusters bc
               JOIN belief_clusters bc2 ON bc2.cluster_id = bc.cluster_id
               JOIN beliefs b ON b.id = bc2.belief_id
               WHERE bc.belief_id IN (?)
                 AND b.valid_to IS NULL
                 AND b.id NOT IN (?)
               ORDER BY b.confidence DESC
               LIMIT 5""",
            (seed_id, seed_id),
        ).fetchall()

        # Should return cluster-mates (not self)
        for r in rows:
            assert r["id"] != seed_id

    def test_missing_table_no_crash(self, tmp_path: Path) -> None:
        """Query should return empty when table doesn't exist."""
        s = MemoryStore(tmp_path / "no_clusters.db")
        s.connection.execute("DROP TABLE IF EXISTS belief_clusters")
        s.connection.commit()

        try:
            rows = s.connection.execute(
                """SELECT DISTINCT b.* FROM belief_clusters bc
                   JOIN beliefs b ON b.id = bc.belief_id
                   WHERE bc.cluster_id = 0 LIMIT 5"""
            ).fetchall()
            assert len(rows) == 0
        except sqlite3.OperationalError:
            pass  # Expected when table is missing
        s.close()
