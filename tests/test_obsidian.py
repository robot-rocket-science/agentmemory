"""Tests for Obsidian vault export: serialization, sync, index generation."""
from __future__ import annotations

import json
import time
from collections.abc import Generator
from pathlib import Path

import pytest

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    OBS_TYPE_USER_STATEMENT,
    SRC_USER,
    Edge,
)
from agentmemory.obsidian import (
    ObsidianConfig,
    SyncResult,
    belief_to_markdown,
    collect_edges_for_belief,
    parse_belief_frontmatter,
    sync_vault,
)
from agentmemory.store import MemoryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    s: MemoryStore = MemoryStore(tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture()
def vault_path(tmp_path: Path) -> Path:
    vault: Path = tmp_path / "vault"
    vault.mkdir()
    return vault


def _make_belief(
    store: MemoryStore,
    content: str,
    belief_type: str = BELIEF_FACTUAL,
    source_type: str = BSRC_AGENT_INFERRED,
    locked: bool = False,
    alpha: float = 2.0,
    beta: float = 1.0,
) -> str:
    """Helper to insert a belief and return its ID."""
    store.insert_observation(
        content=content,
        observation_type=OBS_TYPE_USER_STATEMENT,
        source_type=SRC_USER,
        source_id="test",
    )
    belief = store.insert_belief(
        content=content,
        belief_type=belief_type,
        source_type=source_type,
        alpha=alpha,
        beta_param=beta,
    )
    if locked:
        store.lock_belief(belief.id)
    return belief.id


# ---------------------------------------------------------------------------
# Unit tests: belief_to_markdown
# ---------------------------------------------------------------------------


def test_belief_to_markdown_basic(store: MemoryStore) -> None:
    """A belief with no edges produces valid frontmatter and content."""
    bid: str = _make_belief(store, "Always use pyright strict mode")
    belief = store.get_belief(bid)
    assert belief is not None

    md: str = belief_to_markdown(belief, [])

    assert md.startswith("---\n")
    assert "id: " + bid in md
    assert "type: factual" in md
    assert "Always use pyright strict mode" in md
    assert "## Relationships" not in md  # no edges


def test_belief_to_markdown_with_edges(store: MemoryStore) -> None:
    """Edges appear as wikilinks in the Relationships section."""
    bid: str = _make_belief(store, "Use uv for Python packages")
    belief = store.get_belief(bid)
    assert belief is not None

    edges: list[tuple[str, str, str]] = [
        ("aabbccddee11", "SUPPORTS", "related tooling"),
        ("112233445566", "CONTRADICTS", "conflicting approach"),
    ]
    md: str = belief_to_markdown(belief, edges)

    assert "## Relationships" in md
    assert "[[aabbccddee11]]" in md
    assert "**SUPPORTS**" in md
    assert "[[112233445566]]" in md
    assert "**CONTRADICTS**" in md


def test_belief_to_markdown_special_chars(store: MemoryStore) -> None:
    """Content with YAML-unsafe characters is properly handled."""
    bid: str = _make_belief(store, 'Use config: {"key": "value"} for setup')
    belief = store.get_belief(bid)
    assert belief is not None

    md: str = belief_to_markdown(belief, [])

    # Should not break YAML frontmatter
    assert md.startswith("---\n")
    # The content should appear in the body
    assert '{"key": "value"}' in md


def test_belief_to_markdown_locked_tags(store: MemoryStore) -> None:
    """Locked beliefs get the 'locked' tag."""
    bid: str = _make_belief(store, "Never use em dashes", locked=True)
    belief = store.get_belief(bid)
    assert belief is not None

    md: str = belief_to_markdown(belief, [])

    assert "locked: true" in md
    assert "  - locked" in md


def test_belief_to_markdown_aliases(store: MemoryStore) -> None:
    """Belief ID appears in aliases for wikilink resolution."""
    bid: str = _make_belief(store, "Test belief")
    belief = store.get_belief(bid)
    assert belief is not None

    md: str = belief_to_markdown(belief, [])

    assert f"  - {bid}" in md
    assert "aliases:" in md


# ---------------------------------------------------------------------------
# Unit tests: parse_belief_frontmatter
# ---------------------------------------------------------------------------


def test_parse_frontmatter_roundtrip(store: MemoryStore) -> None:
    """Serialize then parse back: id and content_hash survive."""
    bid: str = _make_belief(store, "Roundtrip test belief")
    belief = store.get_belief(bid)
    assert belief is not None

    md: str = belief_to_markdown(belief, [])
    parsed: dict[str, str] = parse_belief_frontmatter(md)

    assert parsed["id"] == bid
    assert parsed["content_hash"] == belief.content_hash
    assert parsed["type"] == "factual"


def test_parse_frontmatter_empty() -> None:
    """Non-frontmatter content returns empty dict."""
    result: dict[str, str] = parse_belief_frontmatter("no frontmatter here")
    assert result == {}


# ---------------------------------------------------------------------------
# Unit tests: collect_edges_for_belief
# ---------------------------------------------------------------------------


def test_collect_edges_outgoing() -> None:
    """Outgoing edges keep their type as-is."""
    edge: Edge = Edge(
        id=1, from_id="aaa", to_id="bbb",
        edge_type="SUPPORTS", weight=1.0, reason="test",
        created_at="2026-01-01T00:00:00Z",
    )
    result = collect_edges_for_belief("aaa", {"aaa": [edge]})
    assert len(result) == 1
    assert result[0] == ("bbb", "SUPPORTS", "test")


def test_collect_edges_incoming_reversed() -> None:
    """Incoming edges get reversed labels."""
    edge: Edge = Edge(
        id=1, from_id="bbb", to_id="aaa",
        edge_type="SUPERSEDES", weight=1.0, reason="replaced",
        created_at="2026-01-01T00:00:00Z",
    )
    result = collect_edges_for_belief("aaa", {"aaa": [edge]})
    assert len(result) == 1
    assert result[0] == ("bbb", "SUPERSEDED_BY", "replaced")


def test_collect_edges_dedup() -> None:
    """Same edge ID is not duplicated."""
    edge: Edge = Edge(
        id=1, from_id="aaa", to_id="bbb",
        edge_type="RELATES_TO", weight=1.0, reason="",
        created_at="2026-01-01T00:00:00Z",
    )
    # Same edge appearing twice (could happen in bulk fetch)
    result = collect_edges_for_belief("aaa", {"aaa": [edge, edge]})
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Integration tests: sync_vault
# ---------------------------------------------------------------------------


def test_sync_vault_initial(store: MemoryStore, vault_path: Path) -> None:
    """First sync writes all beliefs as .md files."""
    for i in range(5):
        _make_belief(store, f"Belief number {i}")

    config: ObsidianConfig = ObsidianConfig(vault_path=vault_path)
    result: SyncResult = sync_vault(store, config, full=True)

    assert result.beliefs_written == 5
    assert result.beliefs_unchanged == 0

    beliefs_dir: Path = vault_path / "beliefs"
    md_files: list[Path] = list(beliefs_dir.glob("*.md"))
    assert len(md_files) == 5


def test_sync_vault_incremental(store: MemoryStore, vault_path: Path) -> None:
    """Second sync skips unchanged beliefs."""
    for i in range(5):
        _make_belief(store, f"Belief number {i}")

    config: ObsidianConfig = ObsidianConfig(vault_path=vault_path)

    # First sync
    sync_vault(store, config, full=True)

    # Second sync (no changes)
    result: SyncResult = sync_vault(store, config, full=False)

    assert result.beliefs_written == 0
    assert result.beliefs_unchanged == 5


def test_sync_vault_archives_superseded(store: MemoryStore, vault_path: Path) -> None:
    """Soft-deleted beliefs are moved to _archive/."""
    bid: str = _make_belief(store, "Old belief to archive")

    config: ObsidianConfig = ObsidianConfig(vault_path=vault_path)

    # First sync: write the belief
    sync_vault(store, config, full=True)
    beliefs_dir: Path = vault_path / "beliefs"
    assert (beliefs_dir / f"{bid}.md").exists()

    # Soft-delete the belief
    store.soft_delete_belief(bid)

    # Second sync: should archive it
    result: SyncResult = sync_vault(store, config)

    assert not (beliefs_dir / f"{bid}.md").exists()
    archive_dir: Path = vault_path / "beliefs" / "_archive"
    assert (archive_dir / f"{bid}.md").exists()
    assert result.beliefs_archived == 1


def test_sync_vault_index_notes(store: MemoryStore, vault_path: Path) -> None:
    """Index notes are generated with wikilinks."""
    bid: str = _make_belief(store, "Important indexed belief", locked=True)

    config: ObsidianConfig = ObsidianConfig(vault_path=vault_path)
    result: SyncResult = sync_vault(store, config, full=True)

    assert result.index_notes_written == 5
    index_dir: Path = vault_path / "_index"
    assert (index_dir / "by-type.md").exists()
    assert (index_dir / "locked.md").exists()
    assert (index_dir / "recent.md").exists()
    assert (index_dir / "by-confidence.md").exists()
    assert (index_dir / "corrections.md").exists()

    # Locked index should contain our belief
    locked_content: str = (index_dir / "locked.md").read_text(encoding="utf-8")
    assert f"[[{bid}]]" in locked_content


def test_sync_vault_idempotent(store: MemoryStore, vault_path: Path) -> None:
    """Running sync twice with no changes writes zero belief files on second run."""
    for i in range(3):
        _make_belief(store, f"Idempotent belief {i}")

    config: ObsidianConfig = ObsidianConfig(vault_path=vault_path)

    sync_vault(store, config, full=True)
    result: SyncResult = sync_vault(store, config, full=False)

    assert result.beliefs_written == 0
    assert result.beliefs_unchanged == 3


def test_sync_vault_sync_state_persisted(store: MemoryStore, vault_path: Path) -> None:
    """Sync state file is written and contains expected data."""
    _make_belief(store, "State persistence test")

    config: ObsidianConfig = ObsidianConfig(vault_path=vault_path)
    sync_vault(store, config, full=True)

    state_file: Path = vault_path / ".agentmemory_sync.json"
    assert state_file.exists()

    data: dict[str, object] = json.loads(state_file.read_text(encoding="utf-8"))
    assert "last_sync_at" in data
    assert "content_hashes" in data
    assert data["belief_count"] == 1


# ---------------------------------------------------------------------------
# Integration tests: edges in sync
# ---------------------------------------------------------------------------


def test_sync_vault_with_edges(store: MemoryStore, vault_path: Path) -> None:
    """Beliefs with edges produce wikilinks in exported files."""
    bid1: str = _make_belief(store, "First belief")
    bid2: str = _make_belief(store, "Second belief that supports first")

    store.insert_edge(bid2, bid1, "SUPPORTS", reason="agreement")

    config: ObsidianConfig = ObsidianConfig(vault_path=vault_path)
    sync_vault(store, config, full=True)

    # Check bid2's file has a wikilink to bid1
    md2: str = (vault_path / "beliefs" / f"{bid2}.md").read_text(encoding="utf-8")
    assert f"[[{bid1}]]" in md2
    assert "SUPPORTS" in md2


# ---------------------------------------------------------------------------
# Performance test
# ---------------------------------------------------------------------------


def test_sync_performance_bulk(store: MemoryStore, vault_path: Path) -> None:
    """1K beliefs sync in <5s, incremental re-sync <1s."""
    for i in range(1000):
        _make_belief(store, f"Bulk belief number {i} with some content to pad it out")

    config: ObsidianConfig = ObsidianConfig(vault_path=vault_path)

    # Full sync
    start: float = time.monotonic()
    result: SyncResult = sync_vault(store, config, full=True)
    full_elapsed: float = time.monotonic() - start

    assert result.beliefs_written == 1000
    assert full_elapsed < 5.0, f"Full sync took {full_elapsed:.2f}s (expected <5s)"

    # Incremental sync (no changes)
    start = time.monotonic()
    result = sync_vault(store, config, full=False)
    incr_elapsed: float = time.monotonic() - start

    assert result.beliefs_written == 0
    assert result.beliefs_unchanged == 1000
    assert incr_elapsed < 1.0, f"Incremental sync took {incr_elapsed:.2f}s (expected <1s)"
