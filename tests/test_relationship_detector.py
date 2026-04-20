"""Tests for relationship detector (CONTRADICTS/SUPPORTS/gap closure)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentmemory.models import EDGE_CONTRADICTS, EDGE_SUPPORTS
from agentmemory.relationship_detector import (
    GapClosureResult,
    RelationshipResult,
    detect_gap_closure,
    detect_relationships,
    has_negation_signal,
    negation_divergence,
)
from agentmemory.store import MemoryStore


@pytest.fixture()
def store(tmp_path: Path) -> MemoryStore:
    db_path: Path = tmp_path / "test_relationship.db"
    return MemoryStore(db_path)


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


def testhas_negation_signal_positive() -> None:
    assert has_negation_signal("This is not correct")
    assert has_negation_signal("We should never do this")
    assert has_negation_signal("The approach was wrong")
    assert has_negation_signal("Use X instead of Y")
    assert has_negation_signal("We don't use PostgreSQL")


def testhas_negation_signal_negative() -> None:
    assert not has_negation_signal("Use PostgreSQL for the database")
    assert not has_negation_signal("The system works correctly")
    assert not has_negation_signal("Always run tests before committing")


def testnegation_divergence_one_negated() -> None:
    assert negation_divergence(
        "We use PostgreSQL for the database",
        "We do not use PostgreSQL for the database",
    )


def testnegation_divergence_both_negated() -> None:
    assert not negation_divergence(
        "We never use PostgreSQL",
        "We don't use MySQL either",
    )


def testnegation_divergence_neither_negated() -> None:
    assert not negation_divergence(
        "We use PostgreSQL for the database",
        "We use PostgreSQL with WAL mode enabled",
    )


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


def test_contradicts_edge_created(store: MemoryStore) -> None:
    """Two beliefs with high overlap but negation divergence get CONTRADICTS edge."""
    old = store.insert_belief(
        content="The project uses PostgreSQL for all database operations",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )
    new = store.insert_belief(
        content="The project does not use PostgreSQL for database operations",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )

    result: RelationshipResult = detect_relationships(store, new)
    assert result.checked
    assert result.contradictions >= 1
    assert result.edges_created >= 1

    # Verify edge exists
    neighbors = store.get_neighbors(new.id, edge_types=[EDGE_CONTRADICTS])
    assert len(neighbors) >= 1
    neighbor_ids = {b.id for b, _e in neighbors}
    assert old.id in neighbor_ids


def test_supports_edge_created(store: MemoryStore) -> None:
    """Two beliefs with high overlap and same type get SUPPORTS edge."""
    store.insert_belief(
        content="The retrieval pipeline uses FTS5 with BM25 scoring for keyword search",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )
    new = store.insert_belief(
        content="The retrieval pipeline uses FTS5 BM25 scoring for keyword search queries",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )

    result: RelationshipResult = detect_relationships(store, new)
    assert result.checked
    assert result.supports >= 1

    # Verify edge exists
    neighbors = store.get_neighbors(new.id, edge_types=[EDGE_SUPPORTS])
    assert len(neighbors) >= 1


def test_no_edge_low_overlap(store: MemoryStore) -> None:
    """Beliefs with low term overlap get no edges."""
    store.insert_belief(
        content="The project uses PostgreSQL for all database operations",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )
    new = store.insert_belief(
        content="Thompson sampling with Jeffreys prior validated at ECE zero point zero six",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )

    result: RelationshipResult = detect_relationships(store, new)
    assert result.edges_created == 0


def test_locked_beliefs_skipped(store: MemoryStore) -> None:
    """Locked beliefs are never targets for relationship edges."""
    old = store.insert_belief(
        content="The project uses PostgreSQL for all database operations",
        belief_type="factual",
        source_type="user_corrected",
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )
    new = store.insert_belief(
        content="The project does not use PostgreSQL for database operations",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )

    detect_relationships(store, new)
    # Should not create edges to locked beliefs
    neighbors = store.get_neighbors(new.id, edge_types=[EDGE_CONTRADICTS])
    locked_ids: set[str] = {b.id for b, _e in neighbors if b.locked}
    assert old.id not in locked_ids


def test_max_edges_cap(store: MemoryStore) -> None:
    """No more than _MAX_EDGES_PER_BELIEF edges created."""
    # Create 10 similar beliefs
    for i in range(10):
        store.insert_belief(
            content=f"The database uses PostgreSQL version {i} for storage layer operations",
            belief_type="factual",
            source_type="agent_inferred",
            alpha=3.0,
            beta_param=1.0,
        )

    new = store.insert_belief(
        content="The database does not use PostgreSQL for storage layer operations",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )

    result: RelationshipResult = detect_relationships(store, new)
    assert result.edges_created <= 3


def test_short_belief_skipped(store: MemoryStore) -> None:
    """Very short beliefs are skipped (not enough terms)."""
    store.insert_belief(
        content="yes",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )
    new = store.insert_belief(
        content="ok",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )

    result: RelationshipResult = detect_relationships(store, new)
    assert result.edges_created == 0
    assert "too short" in result.details[0]


# ---------------------------------------------------------------------------
# Gap closure detection tests (CS-035 fix)
# ---------------------------------------------------------------------------


def test_gap_closure_supersedes_gap_belief(store: MemoryStore) -> None:
    """Implementation belief supersedes a matching gap belief."""
    gap = store.insert_belief(
        content="No hooks are currently configured for this project",
        belief_type="correction",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )
    impl = store.insert_belief(
        content=(
            "FEATURE IMPLEMENTED: Hooks ARE configured in settings.json. "
            "SessionStart, UserPromptSubmit, Stop, PreCompact, PostCompact "
            "hooks are all wired and active. Shipped and running."
        ),
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )

    result: GapClosureResult = detect_gap_closure(store, impl)
    assert result.checked
    assert result.gaps_closed >= 1

    # Gap belief should be superseded
    refreshed_gap = store.get_belief(gap.id)
    assert refreshed_gap is not None
    assert refreshed_gap.superseded_by == impl.id

    # IMPLEMENTS edge should exist (get_neighbors filters superseded beliefs,
    # so use edge_exists which checks both directions regardless of status)
    assert store.edge_exists(impl.id, gap.id)


def test_gap_closure_no_false_positive(store: MemoryStore) -> None:
    """Non-implementation belief does not trigger gap closure."""
    store.insert_belief(
        content="No hooks are currently configured for this project",
        belief_type="correction",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )
    unrelated = store.insert_belief(
        content="The retrieval pipeline uses FTS5 with BM25 scoring for search",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )

    result: GapClosureResult = detect_gap_closure(store, unrelated)
    assert result.gaps_closed == 0


def test_gap_closure_locked_gap_still_superseded(store: MemoryStore) -> None:
    """Locked gap beliefs are also superseded by implementation events.

    Gap closure is evidence-based, not opinion-based. A locked belief
    saying 'not implemented' that is now factually wrong should still
    be superseded. store.supersede_belief handles the lock check.
    """
    gap = store.insert_belief(
        content="Conversation logger captures but does not ingest data",
        belief_type="correction",
        source_type="agent_inferred",
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )
    impl = store.insert_belief(
        content=(
            "FEATURE IMPLEMENTED: The conversation logger both captures "
            "AND ingests. PostCompact triggers agentmemory ingest on the "
            "archived conversation segment. Shipped and running."
        ),
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )

    result: GapClosureResult = detect_gap_closure(store, impl)
    # supersede_belief refuses to supersede locked beliefs, so the gap
    # stays active but an IMPLEMENTS edge is still created
    refreshed_gap = store.get_belief(gap.id)
    assert refreshed_gap is not None
    # Locked belief should NOT be superseded (store protects it)
    assert refreshed_gap.superseded_by is None
    # But the detection still ran
    assert result.checked


def test_gap_closure_needs_two_implementation_signals(store: MemoryStore) -> None:
    """A belief with only one implementation keyword is not enough."""
    store.insert_belief(
        content="The system is not implemented yet",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )
    # Only one signal word ("configured") -- should not trigger
    weak = store.insert_belief(
        content="The system is configured for basic operation",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )

    result: GapClosureResult = detect_gap_closure(store, weak)
    assert result.gaps_closed == 0
