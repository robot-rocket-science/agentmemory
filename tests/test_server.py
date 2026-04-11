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
    get_locked,
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
    assert "locked: False" in result
    assert "100%" in result or "95%" in result or "%" in result

    store: MemoryStore = server_mod._get_store()  # pyright: ignore[reportPrivateUsage]
    locked: list[Belief] = store.get_locked_beliefs()
    assert len(locked) == 0

    # Verify the belief exists and has high confidence but is NOT locked
    beliefs: list[sqlite3.Row] = store.query("SELECT * FROM beliefs WHERE valid_to IS NULL")
    assert len(beliefs) == 1
    belief: Belief | None = store.get_belief(str(beliefs[0]["id"]))
    assert belief is not None
    assert belief.content == text
    assert belief.locked is False
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
    assert "locked: False" in result
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
    # correct() no longer creates locked beliefs
    locked: list[Belief] = store.get_locked_beliefs()
    assert len(locked) == 0

    # But it should create a high-confidence unlocked belief
    beliefs: list[sqlite3.Row] = store.query("SELECT * FROM beliefs WHERE valid_to IS NULL")
    assert len(beliefs) == 1
    belief: Belief | None = store.get_belief(str(beliefs[0]["id"]))
    assert belief is not None
    assert belief.source_type == "user_corrected"
    assert belief.locked is False
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
    assert "observations: 1" in result
    assert "beliefs: 2" in result
    assert "locked: 0" in result


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
