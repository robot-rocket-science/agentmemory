"""CS-006: Implementation Pressure After Explicit Multi-Session Prohibition.

Pass criterion: A locked correction created in session 1 is still retrievable
and highly ranked in session 2, proving cross-session enforcement works.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_CORRECTION,
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_CORRECTED,
    Belief,
    Session,
)
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore

_CORRECTION_TEXT: str = "Do not suggest implementation. We are in research phase only."


def test_cs006_correction_survives_session_boundary(store: MemoryStore) -> None:
    """Insert a locked correction in session 1. Complete session 1, start
    session 2. get_locked_beliefs() must still contain the correction.

    This validates that locked beliefs persist across session boundaries.
    """
    # Session 1: create and insert locked correction.
    session1: Session = store.create_session(
        model="test", project_context="agentmemory"
    )
    locked: Belief = store.insert_belief(
        content=_CORRECTION_TEXT,
        belief_type=BELIEF_CORRECTION,
        source_type=BSRC_USER_CORRECTED,
        alpha=9.0,
        beta_param=0.5,
        locked=True,
        session_id=session1.id,
    )
    store.complete_session(session1.id, summary="session 1 done")

    # Session 2: start fresh.
    session2: Session = store.create_session(
        model="test", project_context="agentmemory"
    )
    assert session2.id != session1.id

    # Locked beliefs must survive the session boundary.
    locked_beliefs: list[Belief] = store.get_locked_beliefs()
    locked_ids: list[str] = [b.id for b in locked_beliefs]
    assert locked.id in locked_ids, (
        f"Locked correction must survive session boundary. "
        f"Expected {locked.id} in locked beliefs, got: {locked_ids}"
    )


def test_cs006_correction_outranks_suggestions(store: MemoryStore) -> None:
    """In session 2 (after inserting locked correction in session 1), insert
    an unlocked belief suggesting implementation. Use retrieve() and verify
    the locked correction ranks above the suggestion.
    """
    # Session 1: locked correction.
    session1: Session = store.create_session(
        model="test", project_context="agentmemory"
    )
    store.insert_belief(
        content=_CORRECTION_TEXT,
        belief_type=BELIEF_CORRECTION,
        source_type=BSRC_USER_CORRECTED,
        alpha=9.0,
        beta_param=0.5,
        locked=True,
        session_id=session1.id,
    )
    store.complete_session(session1.id, summary="session 1 done")

    # Session 2: competing suggestion.
    session2: Session = store.create_session(
        model="test", project_context="agentmemory"
    )
    store.insert_belief(
        content="Let's build the prototype and start implementation now.",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=0.5,
        beta_param=0.5,
        locked=False,
        session_id=session2.id,
    )

    result: RetrievalResult = retrieve(
        store, "implementation next steps research phase"
    )
    assert result.beliefs, "Expected results from retrieve()"

    # The locked correction must rank above the unlocked suggestion.
    top_belief: Belief = result.beliefs[0]
    assert top_belief.locked is True, (
        f"Expected locked correction to rank first in session 2. "
        f"Top belief: '{top_belief.content}' locked={top_belief.locked}"
    )
