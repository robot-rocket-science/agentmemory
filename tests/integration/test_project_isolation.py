"""Project isolation validation.

Verifies that separate database files have no data leakage between them.
Each MemoryStore instance operating on a different DB path must be fully
independent -- beliefs inserted in one must never appear in another.
Also validates cross-project feedback firewall and readonly store mode.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agentmemory.models import BELIEF_FACTUAL, BSRC_AGENT_INFERRED, Belief
from agentmemory.store import MemoryStore


def test_separate_dbs_no_leakage(tmp_path: Path) -> None:
    """Beliefs in separate DB files must never leak across stores."""
    db_a: Path = tmp_path / "a.db"
    db_b: Path = tmp_path / "b.db"

    # Store A: insert a React belief.
    store_a: MemoryStore = MemoryStore(db_a)
    belief_a: Belief = store_a.insert_belief(
        content="Project A uses React for the frontend framework",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    store_a.close()

    # Store B: insert a Vue belief.
    store_b: MemoryStore = MemoryStore(db_b)
    belief_b: Belief = store_b.insert_belief(
        content="Project B uses Vue for the frontend framework",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    store_b.close()

    # Reopen A: must see React, must NOT see Vue.
    store_a2: MemoryStore = MemoryStore(db_a)
    a_results_vue: list[Belief] = store_a2.search("Vue")
    a_results_react: list[Belief] = store_a2.search("React")

    assert len(a_results_vue) == 0, (
        f"Store A leaked: found {len(a_results_vue)} Vue results"
    )
    assert any(b.id == belief_a.id for b in a_results_react), (
        "Store A must find its own React belief"
    )
    store_a2.close()

    # Reopen B: must see Vue, must NOT see React.
    store_b2: MemoryStore = MemoryStore(db_b)
    b_results_react: list[Belief] = store_b2.search("React")
    b_results_vue: list[Belief] = store_b2.search("Vue")

    assert len(b_results_react) == 0, (
        f"Store B leaked: found {len(b_results_react)} React results"
    )
    assert any(b.id == belief_b.id for b in b_results_vue), (
        "Store B must find its own Vue belief"
    )
    store_b2.close()


def test_foreign_id_detection() -> None:
    """IDs with ':' are detected as foreign (cross-project)."""
    import agentmemory.server as _srv

    is_foreign = _srv._is_foreign_id  # pyright: ignore[reportPrivateUsage]
    assert is_foreign("abc123:def456") is True
    assert is_foreign("4b0f8c37972f:a1b2c3d4e5f6") is True
    assert is_foreign("a1b2c3d4e5f6") is False
    assert is_foreign("") is False


def test_readonly_store_rejects_writes(tmp_path: Path) -> None:
    """A readonly store must reject insert_belief with OperationalError."""
    db: Path = tmp_path / "ro.db"
    # Create the DB first with a normal store
    rw_store: MemoryStore = MemoryStore(db)
    rw_store.insert_belief(
        content="seed belief",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    rw_store.close()

    # Open readonly
    ro_store: MemoryStore = MemoryStore(db, readonly=True)
    assert ro_store.readonly is True

    # Reads must work
    results: list[Belief] = ro_store.search("seed")
    assert len(results) == 1

    # Writes must fail
    with pytest.raises(sqlite3.OperationalError):
        ro_store.insert_belief(
            content="should fail",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )
    ro_store.close()


def test_readonly_store_skips_schema_init(tmp_path: Path) -> None:
    """A readonly store must not attempt schema creation."""
    db: Path = tmp_path / "ro2.db"
    # Create DB normally first
    rw_store: MemoryStore = MemoryStore(db)
    rw_store.close()

    # Reopen readonly -- should not crash even though schema already exists
    ro_store: MemoryStore = MemoryStore(db, readonly=True)
    ro_store.close()


def test_promote_to_global_removed() -> None:
    """promote_to_global and get_global_beliefs must no longer exist."""
    assert not hasattr(MemoryStore, "promote_to_global")
    assert not hasattr(MemoryStore, "get_global_beliefs")
