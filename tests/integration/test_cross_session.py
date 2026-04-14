"""Cross-session retention validation.

Verifies that the memory system's core guarantees hold across session
boundaries: locked beliefs persist, corrections rank high, superseded
beliefs are excluded, feedback persists, and stale detection works.
"""
from __future__ import annotations

from pathlib import Path

from agentmemory.models import (
    BELIEF_CORRECTION,
    BELIEF_FACTUAL,
    BELIEF_REQUIREMENT,
    BSRC_AGENT_INFERRED,
    BSRC_USER_CORRECTED,
    BSRC_USER_STATED,
    Belief,
    Session,
)
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open(db_path: Path) -> MemoryStore:
    """Open a MemoryStore on the given path (simulates a new session)."""
    return MemoryStore(db_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_locked_beliefs_persist_across_sessions(db_path: Path) -> None:
    """Locked beliefs must survive store close/reopen on the same DB file."""
    # Session 1: insert locked belief, create + complete session, close.
    store1: MemoryStore = _open(db_path)
    belief: Belief = store1.insert_belief(
        content="Never use async_bash",
        belief_type=BELIEF_REQUIREMENT,
        source_type=BSRC_USER_STATED,
        locked=True,
    )
    session: Session = store1.create_session(model="test")
    store1.complete_session(session.id, summary="locked belief test")
    store1.close()

    # Session 2: reopen, verify locked belief survived.
    store2: MemoryStore = _open(db_path)
    locked: list[Belief] = store2.get_locked_beliefs()
    locked_ids: list[str] = [b.id for b in locked]
    assert belief.id in locked_ids, (
        f"Locked belief {belief.id} not found after session boundary"
    )
    assert any(b.content == "Never use async_bash" for b in locked)
    store2.close()


def test_correction_ranks_above_original(db_path: Path) -> None:
    """A locked correction must rank above the original belief after reopen."""
    # Session 1: insert original + correction, supersede original.
    store1: MemoryStore = _open(db_path)
    original: Belief = store1.insert_belief(
        content="Use PostgreSQL for the database layer",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    correction: Belief = store1.insert_belief(
        content="Use SQLite not PostgreSQL for the database layer",
        belief_type=BELIEF_CORRECTION,
        source_type=BSRC_USER_CORRECTED,
        locked=True,
    )
    store1.supersede_belief(original.id, correction.id, reason="user correction")
    session: Session = store1.create_session(model="test")
    store1.complete_session(session.id, summary="correction test")
    store1.close()

    # Session 2: retrieve and verify ranking.
    store2: MemoryStore = _open(db_path)
    result: RetrievalResult = retrieve(store2, "database choice")
    result_ids: list[str] = [b.id for b in result.beliefs]

    # Correction must appear.
    assert correction.id in result_ids, "Correction not found in retrieval results"

    # Original should be excluded (superseded -> valid_to set).
    assert original.id not in result_ids, (
        "Superseded original belief should be excluded from retrieval"
    )
    store2.close()


def test_superseded_excluded_across_sessions(db_path: Path) -> None:
    """Superseded beliefs must not appear in search after reopen."""
    # Session 1: insert A, insert B, supersede A with B.
    store1: MemoryStore = _open(db_path)
    belief_a: Belief = store1.insert_belief(
        content="Deploy to Heroku for hosting",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    belief_b: Belief = store1.insert_belief(
        content="Deploy to Railway instead of Heroku for hosting",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
    )
    store1.supersede_belief(belief_a.id, belief_b.id, reason="user preference")
    store1.close()

    # Session 2: search must return B but not A.
    store2: MemoryStore = _open(db_path)
    results: list[Belief] = store2.search("hosting deploy")
    result_ids: list[str] = [b.id for b in results]

    assert belief_a.id not in result_ids, "Superseded belief A must be excluded"
    assert belief_b.id in result_ids, "Replacement belief B must appear in search"
    store2.close()


def test_feedback_persists_across_sessions(db_path: Path) -> None:
    """Test results (feedback) must survive across session boundaries."""
    # Session 1: insert belief, record test result.
    store1: MemoryStore = _open(db_path)
    session1: Session = store1.create_session(model="test")
    belief: Belief = store1.insert_belief(
        content="Always run type checks before committing",
        belief_type=BELIEF_REQUIREMENT,
        source_type=BSRC_USER_STATED,
    )
    store1.record_test_result(
        belief_id=belief.id,
        session_id=session1.id,
        outcome="used",
        detection_layer="explicit",
    )
    store1.complete_session(session1.id, summary="feedback test")
    store1.close()

    # Session 2: verify stats persisted.
    store2: MemoryStore = _open(db_path)
    stats: dict[str, int] = store2.get_retrieval_stats(belief.id)
    assert stats["retrieval_count"] == 1, (
        f"Expected retrieval_count=1, got {stats['retrieval_count']}"
    )
    assert stats["used"] == 1, f"Expected used=1, got {stats['used']}"
    store2.close()


def test_stale_detection_across_sessions(db_path: Path) -> None:
    """Stale detection must work on beliefs created in a prior session.

    Uses days_threshold=0 so any belief not retrieved today counts as stale.
    The belief must also be older than the threshold to qualify, so we
    backdate its created_at timestamp.
    """
    # Session 1: insert a belief with a backdated created_at.
    store1: MemoryStore = _open(db_path)
    belief: Belief = store1.insert_belief(
        content="Legacy deployment process uses FTP",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        created_at="2020-01-01T00:00:00Z",
    )
    store1.close()

    # Session 2: stale detection should find the belief.
    store2: MemoryStore = _open(db_path)
    stale: list[Belief] = store2.get_stale_beliefs(days_threshold=0)
    stale_ids: list[str] = [b.id for b in stale]
    assert belief.id in stale_ids, (
        f"Belief {belief.id} should appear as stale (never retrieved, old created_at)"
    )
    store2.close()


def test_pending_feedback_survives_session(db_path: Path) -> None:
    """Pending feedback entries must persist across session boundaries."""
    # Session 1: insert pending feedback.
    store1: MemoryStore = _open(db_path)
    belief: Belief = store1.insert_belief(
        content="Use structured logging with JSON output",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    store1.insert_pending_feedback(
        belief_id=belief.id,
        belief_content=belief.content,
        session_id=None,
    )
    store1.close()

    # Session 2: pending feedback must still be there.
    store2: MemoryStore = _open(db_path)
    pending: list[dict[str, str]] = store2.get_pending_feedback()
    assert len(pending) >= 1, "Pending feedback should survive session boundary"
    assert any(p["belief_id"] == belief.id for p in pending), (
        "Pending feedback for the inserted belief must exist"
    )

    # Clear and verify.
    cleared: int = store2.clear_pending_feedback()
    assert cleared >= 1, f"Expected at least 1 cleared, got {cleared}"
    remaining: list[dict[str, str]] = store2.get_pending_feedback()
    assert len(remaining) == 0, "Pending feedback should be empty after clear"
    store2.close()
