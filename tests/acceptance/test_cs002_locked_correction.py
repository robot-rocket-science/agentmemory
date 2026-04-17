"""CS-002/CS-004/CS-006: Locked correction persists across sessions and resists downgrade.

Pass criterion: A locked belief inserted via store.insert_belief(locked=True)
survives session boundaries, ranks above unlocked beliefs, and cannot have
confidence reduced by a 'harmful' outcome update.

Note: remember() no longer creates locked beliefs. Only explicit
store.insert_belief(..., locked=True) creates locked beliefs.
"""
from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_STATED,
    Belief,
    Session,
)
from agentmemory.store import MemoryStore

_LOCKED_TEXT: str = "We are in research phase. Do not suggest implementation."


def _insert_locked_belief(store: MemoryStore) -> Belief:
    """Helper: insert a locked belief directly via the store."""
    return store.insert_belief(
        content=_LOCKED_TEXT,
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )


def test_cs002_insert_creates_locked_belief(store: MemoryStore) -> None:
    """store.insert_belief(locked=True) must create a belief with locked=True and high confidence."""
    b: Belief = _insert_locked_belief(store)

    assert b.locked is True
    assert b.confidence > 0.8, f"Expected high confidence, got {b.confidence}"

    beliefs: list[Belief] = store.get_locked_beliefs()
    assert len(beliefs) == 1
    assert beliefs[0].locked is True


def test_cs002_locked_belief_survives_new_session(store: MemoryStore) -> None:
    """Locked belief is visible in a brand-new session (cross-session retrieval)."""
    _insert_locked_belief(store)

    # Simulate session 1 completing.
    session1: Session = store.create_session(model="test", project_context="agentmemory")
    store.complete_session(session1.id, summary="session 1 done")

    # Session 2 starts. Locked beliefs must still be present.
    session2: Session = store.create_session(model="test", project_context="agentmemory")
    assert session2.id != session1.id

    locked: list[Belief] = store.get_locked_beliefs()
    assert locked, "Locked belief must survive session boundary"

    contents: list[str] = [b.content for b in locked]
    assert any("research phase" in c for c in contents), (
        f"'no implementation' belief not found across session boundary. Got: {contents}"
    )


def test_cs002_locked_belief_in_search_results(store: MemoryStore) -> None:
    """After a session boundary, searching for 'what should we do next' returns
    the locked correction."""
    _insert_locked_belief(store)

    # Insert an unlocked belief that could compete.
    store.insert_belief(
        content="Next step is to build a prototype",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=0.5,
        beta_param=0.5,
        locked=False,
    )

    # FTS5 AND semantics: use tokens present in the locked belief content.
    results: list[Belief] = store.search("research implementation")
    assert results, "Expected at least one search result"

    locked_results: list[Belief] = [b for b in results if b.locked]
    assert locked_results, (
        "The locked 'no implementation' belief must appear in search results. "
        f"Got beliefs: {[b.content for b in results]}"
    )


def test_cs002_locked_belief_ranks_above_unlocked(store: MemoryStore) -> None:
    """When both a locked and unlocked belief are returned, the locked one
    must appear first (highest score) due to lock_boost."""
    from agentmemory.retrieval import RetrievalResult, retrieve

    _insert_locked_belief(store)

    store.insert_belief(
        content="We should implement the feature next",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=0.5,
        beta_param=0.5,
        locked=False,
    )

    # FTS5 AND semantics: search for tokens present in locked belief content.
    result: RetrievalResult = retrieve(store, "research phase implementation")
    assert result.beliefs, "Expected results from retrieve()"

    # The first belief must be the locked one because lock_boost elevates its score.
    top_belief: Belief = result.beliefs[0]
    assert top_belief.locked is True, (
        f"Expected locked belief to rank first. Top belief: '{top_belief.content}' "
        f"locked={top_belief.locked}"
    )


def test_cs002_lock_resists_weak_evidence(store: MemoryStore) -> None:
    """Weak 'harmful' evidence must NOT decrease confidence of a locked belief."""
    b: Belief = _insert_locked_belief(store)
    original_beta: float = b.beta_param

    # Weak evidence (weight < 3.0) should be resisted
    store.update_confidence(b.id, outcome="harmful", weight=1.0)

    updated: Belief | None = store.get_belief(b.id)
    assert updated is not None
    assert updated.beta_param == original_beta, (
        f"Locked belief beta_param must not increase on weak 'harmful' evidence. "
        f"Before: {original_beta}, after: {updated.beta_param}"
    )


def test_cs002_lock_yields_to_strong_evidence(store: MemoryStore) -> None:
    """Strong 'harmful' evidence (weight >= 3.0) CAN decrease locked belief confidence."""
    b: Belief = _insert_locked_belief(store)
    original_beta: float = b.beta_param

    # Strong evidence (weight >= 3.0) should get through
    store.update_confidence(b.id, outcome="harmful", weight=5.0)

    updated: Belief | None = store.get_belief(b.id)
    assert updated is not None
    assert updated.beta_param > original_beta, (
        f"Locked belief beta_param MUST increase on strong 'harmful' evidence. "
        f"Before: {original_beta}, after: {updated.beta_param}"
    )
