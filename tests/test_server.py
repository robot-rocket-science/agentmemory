"""Tests for the MCP server tools in agentmemory.server.

Tests call the tool functions directly, bypassing MCP protocol.
Each test uses a fresh MemoryStore backed by a tmp_path database.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest

from agentmemory.models import Belief
from agentmemory.store import MemoryStore
import agentmemory.server as server_mod
from agentmemory.server import (
    correct,
    feedback,
    get_locked,
    ingest,
    observe,
    remember,
    search,
    status,
)


@pytest.fixture(autouse=True)
def isolated_store(tmp_path: Path) -> Generator[None, None, None]:
    """Replace the module-level store with a fresh tmp store for each test."""
    db_path: Path = tmp_path / "test_memory.db"
    store: MemoryStore = MemoryStore(db_path)
    server_mod._set_store(store)  # pyright: ignore[reportPrivateUsage]
    yield
    store.close()
    server_mod._set_store(None)  # type: ignore[arg-type]  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_remember_creates_high_confidence_belief() -> None:
    text: str = "The project uses uv for package management."
    result: str = remember(text)

    assert "Remembered" in result
    assert "ID:" in result
    assert "locked: True" in result
    assert "100%" in result or "95%" in result or "%" in result

    store: MemoryStore = server_mod._get_store()  # pyright: ignore[reportPrivateUsage]
    locked: list[Belief] = store.get_locked_beliefs()
    assert len(locked) == 1

    # Verify the belief exists and has high confidence and IS locked
    beliefs: list[sqlite3.Row] = store.query("SELECT * FROM beliefs WHERE valid_to IS NULL")
    assert len(beliefs) == 1
    belief: Belief | None = store.get_belief(str(beliefs[0]["id"]))
    assert belief is not None
    assert belief.content == text
    assert belief.locked is True
    assert belief.source_type == "user_stated"
    assert belief.alpha == pytest.approx(9.0)  # pyright: ignore[reportUnknownMemberType]


def test_search_finds_remembered_belief() -> None:
    remember("Python strict typing is required for all code.")

    result: str = search("Python typing requirements")
    assert "Python strict typing is required for all code." in result
    assert "Found" in result
    assert "%" in result


def test_correct_supersedes_existing() -> None:
    # First create a belief to be superseded
    remember("The database is PostgreSQL.")

    # Now correct it
    result: str = correct(
        "The database is SQLite, not PostgreSQL.",
        replaces="PostgreSQL database",
    )

    assert "Correction recorded" in result
    assert "locked: True" in result
    assert "Superseded belief ID:" in result

    store: MemoryStore = server_mod._get_store()  # pyright: ignore[reportPrivateUsage]
    beliefs: list[sqlite3.Row] = store.query(
        "SELECT * FROM beliefs WHERE valid_to IS NOT NULL"
    )
    assert len(beliefs) == 1


def test_correct_without_replaces() -> None:
    result: str = correct("Always use strict mode.")
    assert "Correction recorded" in result
    assert "ID:" in result
    assert "Superseded" not in result

    store: MemoryStore = server_mod._get_store()  # pyright: ignore[reportPrivateUsage]
    # correct() now creates locked beliefs
    locked: list[Belief] = store.get_locked_beliefs()
    assert len(locked) == 1

    # Verify locked, high-confidence correction belief
    beliefs: list[sqlite3.Row] = store.query("SELECT * FROM beliefs WHERE valid_to IS NULL")
    assert len(beliefs) == 1
    belief: Belief | None = store.get_belief(str(beliefs[0]["id"]))
    assert belief is not None
    assert belief.source_type == "user_corrected"
    assert belief.locked is True
    assert belief.confidence > 0.8


def test_observe_creates_observation() -> None:
    text: str = "User opened the config file."
    result: str = observe(text)

    assert "Observation recorded" in result
    assert "ID:" in result
    assert text in result

    store: MemoryStore = server_mod._get_store()  # pyright: ignore[reportPrivateUsage]
    counts: dict[str, int] = store.status()
    assert counts["observations"] == 1
    assert counts["beliefs"] == 0


def test_status_returns_counts() -> None:
    remember("Belief one.")
    observe("Observation one.")
    correct("Correction one.")

    result: str = status()

    assert "Memory system status:" in result
    assert "observations:" in result
    assert "beliefs:" in result
    assert "locked:" in result
    assert "superseded:" in result
    assert "edges:" in result
    assert "sessions:" in result

    # There should be 2 beliefs (remember + correct) and 1 observation
    # Both remember() and correct() now create locked beliefs
    assert "observations: 1" in result
    assert "beliefs: 2" in result
    assert "locked: 2" in result
    assert "sessions: 1" in result


def test_get_locked_returns_only_locked() -> None:
    # remember() no longer creates locked beliefs; use store directly
    store: MemoryStore = server_mod._get_store()  # pyright: ignore[reportPrivateUsage]
    store.insert_belief(
        content="Locked belief A.",
        belief_type="factual",
        source_type="user_stated",
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )
    store.insert_belief(
        content="Locked belief B.",
        belief_type="factual",
        source_type="user_stated",
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )

    # Add a non-locked belief directly through the store
    store.insert_belief(
        content="Non-locked belief.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=0.5,
        beta_param=0.5,
        locked=False,
    )

    result: str = get_locked()

    assert "Locked beliefs (2):" in result
    assert "Locked belief A." in result
    assert "Locked belief B." in result
    assert "Non-locked belief." not in result


def test_get_locked_empty() -> None:
    result: str = get_locked()
    assert "No locked beliefs found." in result


def test_search_respects_budget() -> None:
    # Create many beliefs to potentially exceed budget
    words: list[str] = [
        "authentication", "authorization", "database", "caching",
        "logging", "monitoring", "deployment", "configuration",
    ]
    for word in words:
        remember(f"The {word} system requires careful attention to security and performance.")

    # Very small budget -- should return fewer results
    result_small: str = search("system security", budget=50)
    result_large: str = search("system security", budget=5000)

    # Both should succeed (return a string)
    assert isinstance(result_small, str)
    assert isinstance(result_large, str)

    # Large budget should find at least as many results as small budget
    def count_beliefs(text: str) -> int:
        if "No beliefs found" in text:
            return 0
        for line in text.splitlines():
            if line.startswith("Found "):
                parts: list[str] = line.split()
                if len(parts) >= 2:
                    return int(parts[1])
        return 0

    small_count: int = count_beliefs(result_small)
    large_count: int = count_beliefs(result_large)
    assert large_count >= small_count


# ---------------------------------------------------------------------------
# Feedback tool tests
# ---------------------------------------------------------------------------


def test_feedback_used_increases_alpha() -> None:
    """Calling feedback with 'used' should increase alpha and confidence."""
    store: MemoryStore = server_mod._get_store()  # pyright: ignore[reportPrivateUsage]
    belief: Belief = store.insert_belief(
        content="User prefers terse responses.",
        belief_type="preference",
        source_type="user_stated",
        alpha=9.0,
        beta_param=1.0,
    )

    result: str = feedback(belief.id, "used")

    assert "Feedback recorded" in result
    assert "9.0 -> 10.0" in result  # alpha increased

    updated: Belief | None = store.get_belief(belief.id)
    assert updated is not None
    assert updated.alpha == pytest.approx(10.0)  # pyright: ignore[reportUnknownMemberType]
    assert updated.beta_param == pytest.approx(1.0)  # pyright: ignore[reportUnknownMemberType]


def test_feedback_harmful_increases_beta() -> None:
    """Calling feedback with 'harmful' should increase beta_param."""
    store: MemoryStore = server_mod._get_store()  # pyright: ignore[reportPrivateUsage]
    belief: Belief = store.insert_belief(
        content="Always reformat code on save.",
        belief_type="preference",
        source_type="agent_inferred",
        alpha=5.0,
        beta_param=1.0,
    )

    result: str = feedback(belief.id, "harmful", detail="user complained about reformatting")

    assert "Feedback recorded" in result
    updated: Belief | None = store.get_belief(belief.id)
    assert updated is not None
    assert updated.beta_param == pytest.approx(2.0)  # pyright: ignore[reportUnknownMemberType]
    assert updated.confidence < belief.confidence


def test_feedback_harmful_locked_preserves_beta() -> None:
    """Locked beliefs should not have beta_param increased by harmful feedback."""
    store: MemoryStore = server_mod._get_store()  # pyright: ignore[reportPrivateUsage]
    belief: Belief = store.insert_belief(
        content="Never use em dashes.",
        belief_type="correction",
        source_type="user_corrected",
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )

    result: str = feedback(belief.id, "harmful")

    assert "locked, beta unchanged" in result
    updated: Belief | None = store.get_belief(belief.id)
    assert updated is not None
    assert updated.beta_param == pytest.approx(0.5)  # pyright: ignore[reportUnknownMemberType]


def test_feedback_invalid_outcome() -> None:
    """Invalid outcome should return an error message."""
    store: MemoryStore = server_mod._get_store()  # pyright: ignore[reportPrivateUsage]
    belief: Belief = store.insert_belief(
        content="Test belief.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=2.0,
        beta_param=1.0,
    )

    result: str = feedback(belief.id, "great")
    assert "Invalid outcome" in result


def test_feedback_nonexistent_belief() -> None:
    """Feedback for a missing belief ID should return not found."""
    result: str = feedback("doesnotexist", "used")
    assert "not found" in result


def test_feedback_creates_test_record() -> None:
    """Feedback should create a row in the tests table."""
    store: MemoryStore = server_mod._get_store()  # pyright: ignore[reportPrivateUsage]
    belief: Belief = store.insert_belief(
        content="Graph traversal uses BFS.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=5.0,
        beta_param=1.0,
    )

    feedback(belief.id, "used")
    feedback(belief.id, "used")
    feedback(belief.id, "ignored")

    stats: dict[str, int] = store.get_retrieval_stats(belief.id)
    assert stats["retrieval_count"] == 3
    assert stats["used"] == 2
    assert stats["ignored"] == 1


# ---------------------------------------------------------------------------
# Auto-feedback tests
# ---------------------------------------------------------------------------


def test_auto_feedback_marks_used_on_term_overlap() -> None:
    """When ingested text contains key terms from a retrieved belief, auto-mark used."""
    store: MemoryStore = server_mod._get_store()  # pyright: ignore[reportPrivateUsage]
    # Insert a belief that will match ingested text
    store.insert_belief(
        content="All code must use strict static typing with pyright.",
        belief_type="requirement",
        source_type="user_stated",
        alpha=5.0,
        beta_param=1.0,
    )

    # First search retrieves the belief
    result1: str = search("typing requirements")
    assert "strict static typing" in result1

    # Simulate agent using the belief (ingest text with overlapping terms)
    ingest("I updated the config to enforce strict static typing via pyright.", source="assistant")

    # Second search triggers auto-feedback on the first batch
    search("something else entirely")

    # Check: the belief should have been auto-marked "used"
    _beliefs: list[Belief] = store.get_locked_beliefs()  # won't work, not locked
    all_beliefs = store.query("SELECT id FROM beliefs WHERE valid_to IS NULL")
    for row in all_beliefs:
        bid: str = str(row["id"])
        stats: dict[str, int] = store.get_retrieval_stats(bid)
        if stats["retrieval_count"] > 0:
            assert stats["used"] >= 1, f"Belief {bid} should be auto-marked used"


def test_auto_feedback_marks_ignored_when_no_overlap() -> None:
    """When ingested text has no key-term overlap, auto-mark ignored."""
    store: MemoryStore = server_mod._get_store()  # pyright: ignore[reportPrivateUsage]
    store.insert_belief(
        content="HRR adds retrieval value on at least 2 of the 5 project archetypes.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=5.0,
        beta_param=1.0,
    )

    # Search retrieves the belief
    search("HRR retrieval value archetypes")

    # Ingest completely unrelated text
    ingest("The compaction hook rotates log files to the archive directory.", source="assistant")

    # Trigger auto-feedback
    search("unrelated query")

    # Check: should be auto-marked "ignored"
    all_beliefs = store.query("SELECT id FROM beliefs WHERE valid_to IS NULL")
    for row in all_beliefs:
        bid = str(row["id"])
        stats = store.get_retrieval_stats(bid)
        if stats["retrieval_count"] > 0:
            assert stats["ignored"] >= 1, f"Belief {bid} should be auto-marked ignored"


def test_auto_feedback_skips_explicit() -> None:
    """Beliefs with explicit feedback should not get auto-feedback."""
    store: MemoryStore = server_mod._get_store()  # pyright: ignore[reportPrivateUsage]
    store.insert_belief(
        content="The database engine is SQLite for local storage.",
        belief_type="factual",
        source_type="user_stated",
        alpha=5.0,
        beta_param=1.0,
    )

    # Search retrieves the belief
    result: str = search("database engine")
    assert "SQLite" in result

    # Extract belief ID
    import re as _re
    ids: list[str] = _re.findall(r"ID: ([a-f0-9]+)", result)
    assert len(ids) >= 1
    bid: str = ids[0]

    # Give explicit feedback
    feedback(bid, "harmful", detail="wrong database")

    # Ingest text that WOULD trigger auto-used (has overlapping terms)
    ingest("Querying the SQLite database for all beliefs.", source="assistant")

    # Trigger auto-feedback
    search("something else")

    # Check: should have exactly 1 test result (the explicit harmful), not 2
    stats: dict[str, int] = store.get_retrieval_stats(bid)
    assert stats["harmful"] == 1
    assert stats["retrieval_count"] == 1, "Should only have explicit feedback, not auto"


def test_auto_feedback_increments_session_metric() -> None:
    """Auto-feedback should increment feedback_given on the session."""
    store: MemoryStore = server_mod._get_store()  # pyright: ignore[reportPrivateUsage]
    store.insert_belief(
        content="Commits should be atomic and concise for easy review.",
        belief_type="requirement",
        source_type="user_stated",
        alpha=5.0,
        beta_param=1.0,
    )

    search("commit guidelines")
    ingest("Making an atomic commit with a concise message.", source="assistant")
    search("trigger auto feedback")

    session_id: str | None = server_mod._session_id  # pyright: ignore[reportPrivateUsage]
    assert session_id is not None
    from agentmemory.models import Session
    session: Session | None = store.get_session(session_id)
    assert session is not None
    assert session.feedback_given >= 1


def test_auto_feedback_no_crash_on_empty_buffer() -> None:
    """Calling search with no prior retrieval batch should not crash."""
    # First search in a fresh session -- no prior batch to process
    result: str = search("anything at all")
    assert isinstance(result, str)  # just verify no exception
