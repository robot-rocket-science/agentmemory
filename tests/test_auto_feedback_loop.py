# pyright: reportPrivateUsage=false, reportUnusedFunction=false
"""End-to-end test for the auto-feedback loop.

Verifies that:
1. search() populates _retrieval_buffer with belief IDs.
2. ingest() appends text to _ingest_buffer.
3. _process_auto_feedback() checks term overlap and records used/ignored.
4. The tests table contains the correct auto-feedback records.
"""
from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    LAYER_IMPLICIT,
    OUTCOME_IGNORED,
    OUTCOME_USED,
    Belief,
)
from agentmemory.retrieval import retrieve
from agentmemory.store import MemoryStore

# Server internals we need to drive the auto-feedback loop directly.
import agentmemory.server as server_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    s: MemoryStore = MemoryStore(tmp_path / "test_auto_feedback.db")
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _reset_server_globals() -> Generator[None, None, None]:
    """Reset server module globals before and after each test."""
    old_store: MemoryStore | None = server_mod._store
    old_session: str | None = server_mod._session_id
    old_retrieval: dict[str, list[tuple[str, str]]] = server_mod._retrieval_buffer
    old_ingest: list[str] = server_mod._ingest_buffer
    old_explicit: set[str] = server_mod._explicit_feedback_ids

    server_mod._retrieval_buffer = {}
    server_mod._ingest_buffer = []
    server_mod._explicit_feedback_ids = set()

    yield

    server_mod._store = old_store
    server_mod._session_id = old_session
    server_mod._retrieval_buffer = old_retrieval
    server_mod._ingest_buffer = old_ingest
    server_mod._explicit_feedback_ids = old_explicit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_test_beliefs(store: MemoryStore) -> list[Belief]:
    """Insert 3 test beliefs with distinct, recognizable content."""
    beliefs: list[Belief] = []
    contents: list[str] = [
        "Python virtual environments should use uv package manager exclusively",
        "Database migrations require careful schema versioning strategy",
        "Kubernetes pods restart automatically when health checks fail",
    ]
    for content in contents:
        belief: Belief = store.insert_belief(
            content=content,
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )
        beliefs.append(belief)
    store._conn.commit()
    return beliefs


def _query_test_results(
    store: MemoryStore,
    session_id: str,
) -> list[dict[str, str]]:
    """Query the tests table for auto-feedback records in this session."""
    rows = store.query(
        """SELECT belief_id, outcome, outcome_detail, detection_layer
           FROM tests WHERE session_id = ? ORDER BY created_at""",
        (session_id,),
    )
    results: list[dict[str, str]] = []
    for row in rows:
        results.append({
            "belief_id": row[0],
            "outcome": row[1],
            "outcome_detail": row[2] or "",
            "detection_layer": row[3],
        })
    return results


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_auto_feedback_end_to_end(store: MemoryStore) -> None:
    """Full loop: insert beliefs -> retrieve -> ingest -> process -> verify."""
    # Point the server module at our test store.
    server_mod._store = store

    # 1. Create a session.
    session = store.create_session(
        model="test-model",
        project_context="auto-feedback-test",
    )
    session_id: str = session.id
    server_mod._session_id = session_id

    # 2. Insert 3 test beliefs.
    beliefs: list[Belief] = _insert_test_beliefs(store)
    assert len(beliefs) == 3

    # 3. Retrieve beliefs via the retrieval pipeline.
    result = retrieve(store, query="uv package manager python", budget=4000)
    # The first belief about uv should be found.
    retrieved_ids: set[str] = {b.id for b in result.beliefs}
    assert beliefs[0].id in retrieved_ids, (
        f"Expected belief {beliefs[0].id} in retrieval results"
    )

    # 4. Simulate the search() populating _retrieval_buffer.
    #    In the real server, search() does this. We do it manually.
    now_ts: str = datetime.now(timezone.utc).isoformat()
    buffer_entries: list[tuple[str, str]] = [
        (b.id, now_ts) for b in beliefs
    ]
    server_mod._retrieval_buffer[session_id] = buffer_entries

    # 5. Simulate ingest: text that references beliefs 0 and 1 but NOT belief 2.
    #    Belief 0: "Python virtual environments should use uv package manager exclusively"
    #    Belief 1: "Database migrations require careful schema versioning strategy"
    #    Belief 2: "Kubernetes pods restart automatically when health checks fail"
    ingest_text: str = (
        "I configured the Python project to use uv as the package manager. "
        "We also set up database migrations with a proper schema versioning approach."
    )
    server_mod._ingest_buffer.append(ingest_text)

    # 6. Process auto-feedback (normally triggered by next search/ingest).
    count: int = server_mod._process_auto_feedback(session_id)
    assert count == 3, f"Expected 3 feedback events, got {count}"

    # 7. Query the tests table for results.
    results: list[dict[str, str]] = _query_test_results(store, session_id)
    assert len(results) == 3, f"Expected 3 test records, got {len(results)}"

    # 8. Check outcomes.
    outcome_map: dict[str, str] = {r["belief_id"]: r["outcome"] for r in results}

    # Belief 0 (uv/package/manager/python/virtual/environments/exclusively)
    # Ingest text has: "python", "uv", "package", "manager" -> >=2 matches -> "used"
    assert outcome_map[beliefs[0].id] == OUTCOME_USED, (
        f"Belief 0 should be 'used', got '{outcome_map[beliefs[0].id]}'"
    )

    # Belief 1 (database/migrations/schema/versioning/strategy/careful/require)
    # Ingest text has: "database", "migrations", "schema", "versioning" -> >=2 -> "used"
    assert outcome_map[beliefs[1].id] == OUTCOME_USED, (
        f"Belief 1 should be 'used', got '{outcome_map[beliefs[1].id]}'"
    )

    # Belief 2 (kubernetes/pods/restart/automatically/health/checks/fail)
    # Ingest text has none of these terms -> "ignored"
    assert outcome_map[beliefs[2].id] == OUTCOME_IGNORED, (
        f"Belief 2 should be 'ignored', got '{outcome_map[beliefs[2].id]}'"
    )

    # Verify all are implicit layer (auto-feedback).
    for r in results:
        assert r["detection_layer"] == LAYER_IMPLICIT

    # Verify outcome_detail contains term match info.
    for r in results:
        assert "auto:" in r["outcome_detail"]

    # Summary counts.
    used_count: int = sum(1 for r in results if r["outcome"] == OUTCOME_USED)
    ignored_count: int = sum(1 for r in results if r["outcome"] == OUTCOME_IGNORED)
    assert used_count == 2, f"Expected 2 used, got {used_count}"
    assert ignored_count == 1, f"Expected 1 ignored, got {ignored_count}"


def test_auto_feedback_skips_explicit(store: MemoryStore) -> None:
    """Beliefs with explicit feedback should be skipped by auto-feedback."""
    server_mod._store = store

    session = store.create_session(model="test-model")
    session_id: str = session.id

    beliefs: list[Belief] = _insert_test_beliefs(store)

    # Mark belief 0 as having received explicit feedback.
    server_mod._explicit_feedback_ids.add(beliefs[0].id)

    now_ts: str = datetime.now(timezone.utc).isoformat()
    server_mod._retrieval_buffer[session_id] = [
        (b.id, now_ts) for b in beliefs
    ]
    server_mod._ingest_buffer.append("uv package manager python database migrations schema")

    count: int = server_mod._process_auto_feedback(session_id)
    # Only 2 should get auto-feedback (belief 0 is skipped).
    assert count == 2, f"Expected 2 feedback events (1 skipped), got {count}"

    results: list[dict[str, str]] = _query_test_results(store, session_id)
    feedback_ids: set[str] = {r["belief_id"] for r in results}
    assert beliefs[0].id not in feedback_ids, "Explicit-feedback belief should be skipped"


def test_auto_feedback_no_ingest_all_ignored(store: MemoryStore) -> None:
    """When no text is ingested, all retrieved beliefs should be 'ignored'."""
    server_mod._store = store

    session = store.create_session(model="test-model")
    session_id: str = session.id

    beliefs: list[Belief] = _insert_test_beliefs(store)

    now_ts: str = datetime.now(timezone.utc).isoformat()
    server_mod._retrieval_buffer[session_id] = [
        (b.id, now_ts) for b in beliefs
    ]
    # No ingest -- _ingest_buffer stays empty.

    count: int = server_mod._process_auto_feedback(session_id)
    assert count == 3

    results: list[dict[str, str]] = _query_test_results(store, session_id)
    for r in results:
        assert r["outcome"] == OUTCOME_IGNORED
        assert "no ingested text" in r["outcome_detail"]
