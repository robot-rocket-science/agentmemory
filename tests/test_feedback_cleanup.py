# pyright: reportPrivateUsage=false, reportUnusedFunction=false
"""Test that pending_feedback rows are cleared after auto-feedback processing.

Regression test for the fix that adds store.clear_pending_feedback(session_id)
at the end of _process_auto_feedback(). Without the fix, rows accumulate
indefinitely in the pending_feedback table.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    Belief,
)
from agentmemory.store import MemoryStore

import agentmemory.server as server_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    s: MemoryStore = MemoryStore(tmp_path / "test_feedback_cleanup.db")
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _reset_server_globals() -> Generator[None, None, None]:
    """Reset server module globals before and after each test."""
    old_store: MemoryStore | None = server_mod._store
    old_session: str | None = server_mod._session_id
    old_retrieval: dict[str, list[tuple[str, str]]] = server_mod._retrieval_buffer
    old_ingest: list[str] = server_mod._signal_buffer
    old_explicit: set[str] = server_mod._explicit_feedback_ids

    server_mod._retrieval_buffer = {}
    server_mod._signal_buffer = []
    server_mod._explicit_feedback_ids = set()

    yield

    server_mod._store = old_store
    server_mod._session_id = old_session
    server_mod._retrieval_buffer = old_retrieval
    server_mod._signal_buffer = old_ingest
    server_mod._explicit_feedback_ids = old_explicit


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pending_feedback_cleared_after_processing(store: MemoryStore) -> None:
    """pending_feedback rows are deleted after _process_auto_feedback runs."""
    server_mod._store = store

    session = store.create_session(
        model="test-model",
        project_context="feedback-cleanup-test",
    )
    session_id: str = session.id
    server_mod._session_id = session_id

    # Insert a test belief.
    belief: Belief = store.insert_belief(
        content="Always use uv for Python package management",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    store._conn.commit()

    # Populate pending_feedback with entries (simulating what search() does).
    store.insert_pending_feedback(belief.id, belief.content, session_id)
    store.insert_pending_feedback("fake-id-aaa", "some other belief", session_id)
    store.insert_pending_feedback("fake-id-bbb", "yet another belief", session_id)

    # Confirm rows exist before processing.
    pending: list[dict[str, str]] = store.get_pending_feedback(session_id)
    assert len(pending) == 3, f"Expected 3 pending rows, got {len(pending)}"

    # Set up retrieval buffer so _process_auto_feedback has work to do.
    now_ts: str = datetime.now(timezone.utc).isoformat()
    server_mod._retrieval_buffer[session_id] = [
        (belief.id, now_ts),
    ]
    server_mod._signal_buffer.append("uv package manager python")

    # Process auto-feedback.
    count: int = server_mod._process_auto_feedback(session_id)
    assert count >= 1

    # Verify pending_feedback is cleared for this session.
    remaining: list[dict[str, str]] = store.get_pending_feedback(session_id)
    assert len(remaining) == 0, (
        f"Expected 0 pending rows after processing, got {len(remaining)}"
    )


def test_pending_feedback_cleared_when_no_signal(store: MemoryStore) -> None:
    """pending_feedback is cleared even when there is no ingested signal text."""
    server_mod._store = store

    session = store.create_session(model="test-model")
    session_id: str = session.id

    belief: Belief = store.insert_belief(
        content="Kubernetes pods restart on health check failure",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    store._conn.commit()

    store.insert_pending_feedback(belief.id, belief.content, session_id)

    pending: list[dict[str, str]] = store.get_pending_feedback(session_id)
    assert len(pending) == 1

    # Retrieval buffer has an entry but signal buffer is empty.
    now_ts: str = datetime.now(timezone.utc).isoformat()
    server_mod._retrieval_buffer[session_id] = [(belief.id, now_ts)]
    # _signal_buffer stays empty -- triggers the "no ingested text" path.

    count: int = server_mod._process_auto_feedback(session_id)
    assert count == 1

    remaining: list[dict[str, str]] = store.get_pending_feedback(session_id)
    assert len(remaining) == 0, (
        f"Expected 0 pending rows after no-signal processing, got {len(remaining)}"
    )


def test_pending_feedback_other_session_untouched(store: MemoryStore) -> None:
    """Clearing pending_feedback for one session does not affect another."""
    server_mod._store = store

    session_a = store.create_session(model="test-model", project_context="session-a")
    session_b = store.create_session(model="test-model", project_context="session-b")

    belief: Belief = store.insert_belief(
        content="Schema migrations need versioning",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    store._conn.commit()

    # Insert pending feedback for both sessions.
    store.insert_pending_feedback(belief.id, belief.content, session_a.id)
    store.insert_pending_feedback(belief.id, belief.content, session_b.id)

    # Process only session A.
    now_ts: str = datetime.now(timezone.utc).isoformat()
    server_mod._retrieval_buffer[session_a.id] = [(belief.id, now_ts)]
    server_mod._signal_buffer.append("schema migrations versioning")

    server_mod._process_auto_feedback(session_a.id)

    # Session A's pending feedback should be gone.
    remaining_a: list[dict[str, str]] = store.get_pending_feedback(session_a.id)
    assert len(remaining_a) == 0

    # Session B's pending feedback should still exist.
    remaining_b: list[dict[str, str]] = store.get_pending_feedback(session_b.id)
    assert len(remaining_b) == 1, (
        f"Expected 1 pending row for session B, got {len(remaining_b)}"
    )
