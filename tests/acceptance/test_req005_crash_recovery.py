"""REQ-005: Crash recovery >= 90%.

Pass criterion: 20 checkpoints written to a session that is never completed
(simulating a crash) must be recoverable at >= 90% (>= 18 of 20).
"""

from __future__ import annotations

from agentmemory.models import (
    CKPT_DECISION,
    CKPT_FILE_CHANGE,
    CKPT_TASK_STATE,
    Checkpoint,
    Session,
)
from agentmemory.store import MemoryStore

_NUM_CHECKPOINTS: int = 20
_MIN_RECOVERED: int = 18  # 90% of 20


def test_req005_crash_recovery(store: MemoryStore) -> None:
    """Sessions that crash (no complete_session call) must have >= 90% checkpoint
    recovery via find_incomplete_sessions + get_session_checkpoints."""
    # Create a session but do NOT call complete_session (simulating crash).
    session: Session = store.create_session(
        model="claude", project_context="crash-recovery-test"
    )
    assert session.completed_at is None

    checkpoint_types: list[str] = [CKPT_DECISION, CKPT_FILE_CHANGE, CKPT_TASK_STATE]
    written_ids: list[int] = []

    for i in range(_NUM_CHECKPOINTS):
        ctype: str = checkpoint_types[i % len(checkpoint_types)]
        cp: Checkpoint = store.checkpoint(
            session_id=session.id,
            checkpoint_type=ctype,
            content=f"Checkpoint {i}: task state at step {i * 10}",
            references=[f"ref_{i}"],
        )
        written_ids.append(cp.id)

    # --- Recovery path (simulating a new process reading the crashed session) ---

    # Step 1: find incomplete sessions.
    incomplete: list[Session] = store.find_incomplete_sessions()
    incomplete_ids: list[str] = [s.id for s in incomplete]
    assert session.id in incomplete_ids, (
        f"Crashed session {session.id} must appear in find_incomplete_sessions(). "
        f"Found: {incomplete_ids}"
    )

    # Step 2: recover all checkpoints.
    recovered: list[Checkpoint] = store.get_session_checkpoints(session.id)
    recovered_ids: set[int] = {cp.id for cp in recovered}

    matched: int = sum(1 for wid in written_ids if wid in recovered_ids)
    recovery_rate: float = matched / _NUM_CHECKPOINTS

    assert matched >= _MIN_RECOVERED, (
        f"REQ-005 FAILED: recovered {matched}/{_NUM_CHECKPOINTS} checkpoints "
        f"({recovery_rate:.0%} < 90%). "
        f"Missing IDs: {[wid for wid in written_ids if wid not in recovered_ids]}"
    )


def test_req005_completed_session_not_incomplete(store: MemoryStore) -> None:
    """A properly completed session must NOT appear in find_incomplete_sessions()."""
    session: Session = store.create_session(model="claude", project_context="normal")
    store.checkpoint(session.id, CKPT_DECISION, "final decision")
    store.complete_session(session.id, summary="all done")

    incomplete: list[Session] = store.find_incomplete_sessions()
    incomplete_ids: list[str] = [s.id for s in incomplete]
    assert session.id not in incomplete_ids, (
        f"Completed session {session.id} must not appear in find_incomplete_sessions()"
    )
