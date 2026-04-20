"""Tests for VaultStore: vault-first storage with SQLite index."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.vault_store import RebuildResult, VaultStore


@pytest.fixture()
def vstore(tmp_path: Path) -> Generator[VaultStore, None, None]:
    vault: Path = tmp_path / "vault"
    vault.mkdir()
    idx: Path = tmp_path / "index.db"
    vs: VaultStore = VaultStore(vault, idx)
    yield vs
    vs.close()


# ------------------------------------------------------------------
# Write path tests
# ------------------------------------------------------------------


def test_insert_belief_writes_md(vstore: VaultStore) -> None:
    """Inserting a belief creates a .md file in the vault."""
    belief: Belief = vstore.insert_belief(
        content="Test belief for vault write",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    md_path: Path = vstore.beliefs_dir / f"{belief.id}.md"
    assert md_path.exists()
    content: str = md_path.read_text(encoding="utf-8")
    assert "Test belief for vault write" in content
    assert f"id: {belief.id}" in content


def test_insert_belief_indexes(vstore: VaultStore) -> None:
    """Inserting a belief also indexes it in SQLite."""
    belief: Belief = vstore.insert_belief(
        content="Indexed belief",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    found: Belief | None = vstore.get_belief(belief.id)
    assert found is not None
    assert found.content == "Indexed belief"


def test_soft_delete_archives_file(vstore: VaultStore) -> None:
    """Soft-deleting moves .md to _archive/ and sets valid_to."""
    belief: Belief = vstore.insert_belief(
        content="Will be archived",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    vstore.soft_delete_belief(belief.id)

    assert not (vstore.beliefs_dir / f"{belief.id}.md").exists()
    assert (vstore.archive_dir / f"{belief.id}.md").exists()

    deleted: Belief | None = vstore.get_belief(belief.id)
    assert deleted is not None
    assert deleted.valid_to is not None


def test_lock_updates_md(vstore: VaultStore) -> None:
    """Locking a belief rewrites .md with locked: true."""
    belief: Belief = vstore.insert_belief(
        content="Lockable belief",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
    )
    vstore.lock_belief(belief.id)

    content: str = (vstore.beliefs_dir / f"{belief.id}.md").read_text(encoding="utf-8")
    assert "locked: true" in content


def test_insert_edge_updates_both_files(vstore: VaultStore) -> None:
    """Inserting an edge rewrites both endpoint .md files with wikilinks."""
    b1: Belief = vstore.insert_belief(
        content="First node",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    b2: Belief = vstore.insert_belief(
        content="Second node",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    vstore.insert_edge(b1.id, b2.id, "SUPPORTS", reason="test")

    content1: str = (vstore.beliefs_dir / f"{b1.id}.md").read_text(encoding="utf-8")
    content2: str = (vstore.beliefs_dir / f"{b2.id}.md").read_text(encoding="utf-8")
    assert f"[[{b2.id}]]" in content1
    assert f"[[{b1.id}]]" in content2


# ------------------------------------------------------------------
# Read path tests (delegation)
# ------------------------------------------------------------------


def test_read_from_index(vstore: VaultStore) -> None:
    """Reads go through SQLite index."""
    b: Belief = vstore.insert_belief(
        content="Read test",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    result: Belief | None = vstore.get_belief(b.id)
    assert result is not None
    assert result.content == "Read test"


def test_get_all_active(vstore: VaultStore) -> None:
    """get_all_active_beliefs returns all non-deleted beliefs."""
    for i in range(5):
        vstore.insert_belief(
            content=f"Belief {i}",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )
    all_beliefs: list[Belief] = vstore.get_all_active_beliefs()
    assert len(all_beliefs) == 5


# ------------------------------------------------------------------
# Rebuild index tests
# ------------------------------------------------------------------


def test_rebuild_index_roundtrip(vstore: VaultStore) -> None:
    """Insert beliefs, rebuild index, verify data survives."""
    ids: list[str] = []
    for i in range(3):
        b: Belief = vstore.insert_belief(
            content=f"Rebuild test belief number {i}",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
            alpha=5.0,
            beta_param=1.0,
        )
        ids.append(b.id)

    # Add an edge
    vstore.insert_edge(ids[0], ids[1], "SUPPORTS", reason="roundtrip test")

    # Rebuild (destroys and reconstructs index)
    result: RebuildResult = vstore.rebuild_index()

    assert result.beliefs_indexed == 3
    assert result.edges_created >= 1
    assert len(result.errors) == 0

    # Verify beliefs survived
    for bid in ids:
        found: Belief | None = vstore.get_belief(bid)
        assert found is not None


def test_rebuild_empty_vault(vstore: VaultStore) -> None:
    """Rebuilding an empty vault produces no errors."""
    result: RebuildResult = vstore.rebuild_index()
    assert result.beliefs_indexed == 0
    assert result.edges_created == 0
    assert len(result.errors) == 0


def test_rebuild_preserves_locked(vstore: VaultStore) -> None:
    """Locked status survives rebuild."""
    b: Belief = vstore.insert_belief(
        content="Locked belief survives rebuild",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
    )
    vstore.lock_belief(b.id)

    vstore.rebuild_index()

    found: Belief | None = vstore.get_belief(b.id)
    assert found is not None
    assert found.locked is True
