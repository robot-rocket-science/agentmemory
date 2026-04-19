"""CS-029: Partial Fix Undone by Background Process.

Pass criterion: Cross-session state changes are detectable. A belief about
unlocking should conflict with a re-locked state.
"""

from __future__ import annotations

from pathlib import Path

from agentmemory.models import (
    BELIEF_CORRECTION,
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_CORRECTED,
    Belief,
)
from agentmemory.relationship_detector import detect_relationships
from agentmemory.store import MemoryStore


def test_cs029_incomplete_fix_warning_stored(store: MemoryStore) -> None:
    """A warning about an incomplete fix should persist and be retrievable."""
    store.insert_belief(
        content=(
            "Fixed auto-locking in remember() and correct(). "
            "NOT fixed: backfill_lock_corrections() in store.py still runs "
            "on every DB open and re-locks everything."
        ),
        belief_type=BELIEF_CORRECTION,
        source_type=BSRC_USER_CORRECTED,
        locked=True,
    )

    results: list[Belief] = store.search("locked beliefs re-locked backfill")
    assert len(results) >= 1
    assert any("backfill" in r.content for r in results)


def test_cs029_temporal_state_contradiction(store: MemoryStore) -> None:
    """Beliefs with opposing claims about the same state should be detected
    as related. The zero-LLM detector catches negation divergence (one has
    negation, the other doesn't). When both contain negation with opposing
    meaning, it detects SUPPORTS (high overlap) -- a known limitation."""
    # Positive claim (no negation words)
    store.insert_belief(
        content="The auto-locking bug in remember and correct is fixed, beliefs stay unlocked",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    # Negative claim (has negation)
    regression: Belief = store.insert_belief(
        content="The auto-locking bug in remember and correct is not fixed, beliefs are still locked",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    result = detect_relationships(store, regression)
    assert result.edges_created > 0, (
        f"Should detect relationship between fixed and not-fixed beliefs. "
        f"Got: {result.details}"
    )
    # With proper negation divergence (one positive, one negative),
    # this should now be detected as CONTRADICTS
    assert result.contradictions > 0, (
        f"Expected CONTRADICTS via negation divergence. Got: {result.details}"
    )


def test_cs029_cross_session_state_persists(tmp_path: Path) -> None:
    """State from session 1 should be queryable in session 2."""
    db_path: Path = tmp_path / "cross_session.db"

    # Session 1: record the fix
    s1: MemoryStore = MemoryStore(db_path)
    s1.insert_belief(
        content="Bulk-unlocked 2914 beliefs, re-locked only 4 by user choice",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    s1.close()

    # Session 2: query the state
    s2: MemoryStore = MemoryStore(db_path)
    results: list[Belief] = s2.search("locked beliefs count unlock")
    s2.close()

    assert len(results) >= 1
    assert any("unlocked" in r.content.lower() or "2914" in r.content for r in results)
