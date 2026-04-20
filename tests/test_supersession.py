"""Tests for temporal supersession detector."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agentmemory.models import Belief
from agentmemory.store import MemoryStore
from agentmemory.supersession import (
    SupersessionResult,
    check_temporal_supersession,
    extract_terms,
    jaccard_similarity,
)


@pytest.fixture()
def store(tmp_path: Path) -> MemoryStore:
    db_path: Path = tmp_path / "test_supersession.db"
    return MemoryStore(db_path)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _hours_ago(hours: float) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(hours=hours))


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


def test_extract_terms_filters_stopwords() -> None:
    terms: set[str] = extract_terms("The database is PostgreSQL and it uses WAL mode")
    assert "the" not in terms
    assert "is" not in terms
    assert "and" not in terms
    assert "database" in terms
    assert "postgresql" in terms
    assert "wal" in terms
    assert "mode" in terms


def test_extract_terms_minimum_length() -> None:
    terms: set[str] = extract_terms("a b cd efg")
    assert "a" not in terms
    assert "b" not in terms
    assert "cd" in terms
    assert "efg" in terms


def test_jaccard_identical_sets() -> None:
    s: set[str] = {"database", "postgresql", "wal"}
    assert jaccard_similarity(s, s) == pytest.approx(  # pyright: ignore[reportUnknownMemberType]
1.0)


def test_jaccard_disjoint_sets() -> None:
    a: set[str] = {"database", "postgresql"}
    b: set[str] = {"frontend", "react"}
    assert jaccard_similarity(a, b) == pytest.approx(  # pyright: ignore[reportUnknownMemberType]
0.0)


def test_jaccard_partial_overlap() -> None:
    a: set[str] = {"database", "postgresql", "production"}
    b: set[str] = {"database", "sqlite", "production"}
    # intersection = {database, production} = 2
    # union = {database, postgresql, production, sqlite} = 4
    assert jaccard_similarity(a, b) == pytest.approx(  # pyright: ignore[reportUnknownMemberType]
0.5)


def test_jaccard_empty_sets() -> None:
    assert jaccard_similarity(set(), set()) == pytest.approx(  # pyright: ignore[reportUnknownMemberType]
0.0)
    assert jaccard_similarity({"a"}, set()) == pytest.approx(  # pyright: ignore[reportUnknownMemberType]
0.0)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


def test_supersedes_older_overlapping_belief(store: MemoryStore) -> None:
    """Old belief about same topic gets superseded by new belief."""
    old: Belief = store.insert_belief(
        content="The database uses PostgreSQL for all storage needs.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=9.0,
        beta_param=1.0,
        created_at=_hours_ago(5),
    )

    new: Belief = store.insert_belief(
        content="The database uses SQLite for all storage needs.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=9.0,
        beta_param=1.0,
    )

    result: SupersessionResult = check_temporal_supersession(store, new)

    assert result.checked is True
    assert result.superseded_id == old.id
    assert result.jaccard > 0.4
    assert result.age_gap_hours > 0.0

    # Verify old belief is marked superseded
    refreshed: Belief | None = store.get_belief(old.id)
    assert refreshed is not None
    assert refreshed.valid_to is not None
    assert refreshed.superseded_by == new.id


def test_no_supersession_different_topics(store: MemoryStore) -> None:
    """Beliefs about different topics should not supersede each other."""
    store.insert_belief(
        content="The database uses PostgreSQL for all storage needs.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=9.0,
        beta_param=1.0,
        created_at=_hours_ago(5),
    )

    new: Belief = store.insert_belief(
        content="The frontend framework is React with TypeScript.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=9.0,
        beta_param=1.0,
    )

    result: SupersessionResult = check_temporal_supersession(store, new)

    assert result.checked is True
    assert result.superseded_id == ""


def test_no_supersession_when_old_is_locked(store: MemoryStore) -> None:
    """Locked beliefs must never be superseded."""
    old: Belief = store.insert_belief(
        content="Always use strict typing in all Python files.",
        belief_type="requirement",
        source_type="user_stated",
        alpha=9.0,
        beta_param=0.5,
        locked=True,
        created_at=_hours_ago(5),
    )

    new: Belief = store.insert_belief(
        content="Use relaxed typing in all Python files.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=9.0,
        beta_param=1.0,
    )

    result: SupersessionResult = check_temporal_supersession(store, new)

    assert result.superseded_id == ""

    # Verify old belief is still active
    refreshed: Belief | None = store.get_belief(old.id)
    assert refreshed is not None
    assert refreshed.valid_to is None


def test_time_gate_respected(store: MemoryStore) -> None:
    """Beliefs created close together should NOT supersede each other."""
    from datetime import datetime, timezone
    now: str = datetime.now(timezone.utc).isoformat()

    store.insert_belief(
        content="The experiment shows accuracy of 92 percent on the test set.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=9.0,
        beta_param=1.0,
        created_at=now,  # same time as new
    )

    new: Belief = store.insert_belief(
        content="The experiment shows accuracy of 95 percent on the test set.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=9.0,
        beta_param=1.0,
        created_at=now,
    )

    result: SupersessionResult = check_temporal_supersession(store, new)

    assert result.superseded_id == ""
    assert "no overlapping" in result.reason


def test_short_beliefs_skipped(store: MemoryStore) -> None:
    """Beliefs with fewer than MIN_TERMS significant words are skipped."""
    store.insert_belief(
        content="def build_fts",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=2.0,
        beta_param=1.0,
        created_at=_hours_ago(5),
    )

    new: Belief = store.insert_belief(
        content="def build_fts5",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=2.0,
        beta_param=1.0,
    )

    result: SupersessionResult = check_temporal_supersession(store, new)

    assert result.checked is True
    assert result.superseded_id == ""
    assert "too short" in result.reason


def test_hypothesis_then_failure_superseded(store: MemoryStore) -> None:
    """Classic research pattern: hypothesis created, then failure recorded later."""
    hypothesis: Belief = store.insert_belief(
        content="H2: Multi-layer edges increase HRR retrieval value.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=5.0,
        beta_param=1.0,
        created_at=_hours_ago(48),
    )

    failure: Belief = store.insert_belief(
        content="H2: Multi-layer edges increase HRR retrieval value -- FAIL.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=9.0,
        beta_param=1.0,
    )

    result: SupersessionResult = check_temporal_supersession(store, failure)

    assert result.superseded_id == hypothesis.id
    assert result.age_gap_hours > 40.0


def test_already_superseded_not_re_superseded(store: MemoryStore) -> None:
    """A belief already superseded should not be superseded again."""
    old: Belief = store.insert_belief(
        content="The retrieval system uses BM25 ranking for all queries.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=9.0,
        beta_param=1.0,
        created_at=_hours_ago(10),
    )
    mid: Belief = store.insert_belief(
        content="The retrieval system uses BM25 ranking with decay for all queries.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=9.0,
        beta_param=1.0,
        created_at=_hours_ago(5),
    )

    # First supersession: mid supersedes old
    result1: SupersessionResult = check_temporal_supersession(store, mid)
    assert result1.superseded_id == old.id

    # New belief arrives
    newest: Belief = store.insert_belief(
        content="The retrieval system uses BM25 ranking with decay and recency boost for all queries.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=9.0,
        beta_param=1.0,
    )

    # Second supersession: newest supersedes mid (not old, which is already superseded)
    result2: SupersessionResult = check_temporal_supersession(store, newest)
    assert result2.superseded_id == mid.id
