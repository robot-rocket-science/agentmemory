"""Tests for duplicate detection and deduplication."""
from __future__ import annotations

import hashlib
from collections.abc import Generator
from pathlib import Path

import pytest

from agentmemory.dedup import (
    DeduplicationResult,
    find_and_report,
    find_exact_duplicates,
    find_near_duplicates,
    merge_duplicates,
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


def _make_belief(store: MemoryStore, content: str, alpha: float = 2.0) -> str:
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
        alpha=alpha,
        beta_param=1.0,
    )
    return belief.id


def _insert_raw_belief(store: MemoryStore, content: str, alpha: float = 2.0) -> str:
    """Insert a belief bypassing content-hash dedup (for testing exact dupes)."""
    import uuid
    bid: str = uuid.uuid4().hex[:12]
    ch: str = hashlib.sha256(content.encode()).hexdigest()[:12]
    ts: str = "2026-01-01T00:00:00+00:00"
    store.query(
        """INSERT INTO beliefs
           (id, content_hash, content, belief_type, alpha, beta_param,
            source_type, locked, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
        (bid, ch, content, BELIEF_FACTUAL, alpha, 1.0, BSRC_AGENT_INFERRED, ts, ts),
    )
    store.query(
        "INSERT INTO search_index(id, content, type) VALUES (?, ?, ?)",
        (bid, content, "belief"),
    )
    return bid


def test_no_duplicates(store: MemoryStore) -> None:
    """Unique beliefs produce no clusters."""
    _make_belief(store, "First unique belief about topic A")
    _make_belief(store, "Second unique belief about topic B")

    exact = find_exact_duplicates(store)
    assert len(exact) == 0


def test_exact_duplicates(store: MemoryStore) -> None:
    """Identical content with different IDs produces exact duplicate cluster."""
    _insert_raw_belief(store, "Exact same content here", alpha=5.0)
    _insert_raw_belief(store, "Exact same content here", alpha=2.0)

    clusters = find_exact_duplicates(store)
    assert len(clusters) == 1
    assert len(clusters[0].duplicate_ids) == 1
    assert clusters[0].similarity == 1.0


def test_exact_duplicate_canonical_is_highest_confidence(store: MemoryStore) -> None:
    """Canonical belief in a cluster has highest confidence."""
    low: str = _insert_raw_belief(store, "Duplicate content for test", alpha=1.0)
    high: str = _insert_raw_belief(store, "Duplicate content for test", alpha=9.0)

    clusters = find_exact_duplicates(store)
    assert len(clusters) == 1
    assert clusters[0].canonical_id == high
    assert low in clusters[0].duplicate_ids


def test_near_duplicates(store: MemoryStore) -> None:
    """Beliefs with high word overlap are near-duplicates."""
    _make_belief(
        store,
        "The retrieval pipeline uses FTS5 for keyword search and HRR for vocabulary bridging across beliefs"
    )
    _make_belief(
        store,
        "The retrieval pipeline uses FTS5 for keyword matching and HRR for vocabulary bridge across beliefs"
    )

    clusters = find_near_duplicates(store, threshold=0.65)
    assert len(clusters) == 1
    assert clusters[0].similarity >= 0.65


def test_near_duplicates_below_threshold(store: MemoryStore) -> None:
    """Different beliefs below threshold are not grouped."""
    _make_belief(store, "The retrieval pipeline uses FTS5 for keyword search")
    _make_belief(store, "PostgreSQL database with WAL mode and foreign keys enabled")

    clusters = find_near_duplicates(store, threshold=0.8)
    assert len(clusters) == 0


def test_merge_duplicates(store: MemoryStore) -> None:
    """Merging soft-deletes duplicate beliefs."""
    b1: str = _insert_raw_belief(store, "Merge test content here", alpha=5.0)
    b2: str = _insert_raw_belief(store, "Merge test content here", alpha=2.0)

    clusters = find_exact_duplicates(store)
    merged: int = merge_duplicates(store, clusters)

    assert merged == 1
    # The lower-confidence one should be soft-deleted
    deleted = store.get_belief(b2)
    assert deleted is not None
    assert deleted.valid_to is not None
    # The canonical should still be active
    kept = store.get_belief(b1)
    assert kept is not None
    assert kept.valid_to is None


def test_find_and_report(store: MemoryStore) -> None:
    """Full report captures both exact and near duplicates."""
    _insert_raw_belief(store, "Exact dup content for report test case")
    _insert_raw_belief(store, "Exact dup content for report test case")
    _make_belief(
        store,
        "The scoring function combines type weight and source weight and length multiplier for ranking"
    )
    _make_belief(
        store,
        "The scoring function combines type weight and source weight and length penalty for ranking"
    )

    result: DeduplicationResult = find_and_report(store, near_threshold=0.7)
    assert len(result.exact_clusters) == 1
    assert result.total_duplicates >= 1
