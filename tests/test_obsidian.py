"""Tests for Obsidian vault export: serialization, sync, index generation."""

from __future__ import annotations

import json
import time
from collections.abc import Generator
from pathlib import Path

import pytest

from agentmemory.models import (
    BELIEF_FACTUAL,
    Belief,
    BSRC_AGENT_INFERRED,
    OBS_TYPE_USER_STATEMENT,
    SRC_USER,
    Edge,
)
from agentmemory.obsidian import (
    ObsidianConfig,
    SyncResult,
    belief_to_markdown,
    beliefs_to_canvas,
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


def test_belief_to_markdown_locked_property(store: MemoryStore) -> None:
    """Locked beliefs have locked: true in frontmatter (not as a tag)."""
    bid: str = _make_belief(store, "Never use em dashes", locked=True)
    belief = store.get_belief(bid)
    assert belief is not None

    md: str = belief_to_markdown(belief, [])

    assert "locked: true" in md
    # locked should NOT be a tag (avoids duplicate graph nodes in Obsidian)
    lines: list[str] = md.split("\n")
    tag_lines: list[str] = [line for line in lines if line.strip() == "- locked"]
    assert len(tag_lines) == 0


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
        id=1,
        from_id="aaa",
        to_id="bbb",
        edge_type="SUPPORTS",
        weight=1.0,
        reason="test",
        created_at="2026-01-01T00:00:00Z",
    )
    result = collect_edges_for_belief("aaa", {"aaa": [edge]})
    assert len(result) == 1
    assert result[0] == ("bbb", "SUPPORTS", "test")


def test_collect_edges_incoming_reversed() -> None:
    """Incoming edges get reversed labels."""
    edge: Edge = Edge(
        id=1,
        from_id="bbb",
        to_id="aaa",
        edge_type="SUPERSEDES",
        weight=1.0,
        reason="replaced",
        created_at="2026-01-01T00:00:00Z",
    )
    result = collect_edges_for_belief("aaa", {"aaa": [edge]})
    assert len(result) == 1
    assert result[0] == ("bbb", "SUPERSEDED_BY", "replaced")


def test_collect_edges_dedup() -> None:
    """Same edge ID is not duplicated."""
    edge: Edge = Edge(
        id=1,
        from_id="aaa",
        to_id="bbb",
        edge_type="RELATES_TO",
        weight=1.0,
        reason="",
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

    assert result.index_notes_written == 11  # 5 index + 6 dashboards
    index_dir: Path = vault_path / "_index"
    assert (index_dir / "by-type.md").exists()
    assert (index_dir / "locked.md").exists()
    assert (index_dir / "recent.md").exists()
    assert (index_dir / "by-confidence.md").exists()
    assert (index_dir / "corrections.md").exists()
    # Dataview dashboards
    dash_dir: Path = vault_path / "_dashboards"
    assert (dash_dir / "overview.md").exists()
    assert (dash_dir / "corrections.md").exists()
    assert (dash_dir / "stale.md").exists()
    assert (dash_dir / "high-confidence.md").exists()
    assert (dash_dir / "sessions.md").exists()
    assert (dash_dir / "locked.md").exists()

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
    assert incr_elapsed < 1.0, (
        f"Incremental sync took {incr_elapsed:.2f}s (expected <1s)"
    )


# ---------------------------------------------------------------------------
# Bidirectional sync tests (Play B)
# ---------------------------------------------------------------------------


def test_detect_no_changes(store: MemoryStore, vault_path: Path) -> None:
    """No changes detected after a clean sync."""
    from agentmemory.obsidian import detect_vault_changes

    _make_belief(store, "Untouched belief")
    config: ObsidianConfig = ObsidianConfig(vault_path=vault_path)
    sync_vault(store, config, full=True)

    changes = detect_vault_changes(config)
    assert len(changes) == 0


def test_detect_modified_file(store: MemoryStore, vault_path: Path) -> None:
    """Editing a belief file is detected as modified."""
    from agentmemory.obsidian import VaultChange, detect_vault_changes

    bid: str = _make_belief(store, "Original content")
    config: ObsidianConfig = ObsidianConfig(vault_path=vault_path)
    sync_vault(store, config, full=True)

    # Simulate user editing the file in Obsidian
    md_path: Path = vault_path / "beliefs" / f"{bid}.md"
    content: str = md_path.read_text(encoding="utf-8")
    # Change the content_hash in frontmatter to simulate an edit
    modified: str = content.replace("Original content", "Edited in Obsidian")
    md_path.write_text(modified, encoding="utf-8")

    changes: list[VaultChange] = detect_vault_changes(config)
    assert len(changes) == 1
    assert changes[0].change_type == "modified"
    assert changes[0].belief_id == bid
    assert changes[0].new_text is not None
    assert "Edited in Obsidian" in changes[0].new_text


def test_detect_deleted_file(store: MemoryStore, vault_path: Path) -> None:
    """Deleting a belief file is detected as deleted."""
    from agentmemory.obsidian import detect_vault_changes

    bid: str = _make_belief(store, "Will be deleted")
    config: ObsidianConfig = ObsidianConfig(vault_path=vault_path)
    sync_vault(store, config, full=True)

    # Simulate user deleting the file
    (vault_path / "beliefs" / f"{bid}.md").unlink()

    changes = detect_vault_changes(config)
    assert len(changes) == 1
    assert changes[0].change_type == "deleted"
    assert changes[0].belief_id == bid


def test_detect_new_file(store: MemoryStore, vault_path: Path) -> None:
    """A new .md file in beliefs/ is detected as new."""
    from agentmemory.obsidian import detect_vault_changes

    config: ObsidianConfig = ObsidianConfig(vault_path=vault_path)
    # Sync with empty DB to create the directory and sync state
    sync_vault(store, config, full=True)

    # Simulate user creating a new note in Obsidian
    new_path: Path = vault_path / "beliefs" / "aabbccddeeff.md"
    new_path.write_text(
        "---\nid: aabbccddeeff\ncontent_hash: newfile12345\n---\n\n"
        "# aabbccddeeff\n\nA belief created in Obsidian.\n",
        encoding="utf-8",
    )

    changes = detect_vault_changes(config)
    assert len(changes) == 1
    assert changes[0].change_type == "new"
    assert changes[0].belief_id == "aabbccddeeff"
    assert changes[0].new_text is not None
    assert "created in Obsidian" in changes[0].new_text


def test_import_modified(store: MemoryStore, vault_path: Path) -> None:
    """Importing a modified file updates the belief in the DB."""
    from agentmemory.obsidian import (
        ImportResult,
        detect_vault_changes,
        import_vault_changes,
    )

    bid: str = _make_belief(store, "Before edit")
    config: ObsidianConfig = ObsidianConfig(vault_path=vault_path)
    sync_vault(store, config, full=True)

    # Edit the file
    md_path: Path = vault_path / "beliefs" / f"{bid}.md"
    content: str = md_path.read_text(encoding="utf-8")
    md_path.write_text(
        content.replace("Before edit", "After edit in Obsidian"),
        encoding="utf-8",
    )

    changes = detect_vault_changes(config)
    result: ImportResult = import_vault_changes(store, changes)

    assert result.modified == 1
    updated: Belief | None = store.get_belief(bid)
    assert updated is not None
    assert "After edit in Obsidian" in updated.content


def test_import_deleted(store: MemoryStore, vault_path: Path) -> None:
    """Importing a deletion soft-deletes the belief."""
    from agentmemory.obsidian import (
        ImportResult,
        detect_vault_changes,
        import_vault_changes,
    )

    bid: str = _make_belief(store, "To be deleted via Obsidian")
    config: ObsidianConfig = ObsidianConfig(vault_path=vault_path)
    sync_vault(store, config, full=True)

    (vault_path / "beliefs" / f"{bid}.md").unlink()

    changes = detect_vault_changes(config)
    result: ImportResult = import_vault_changes(store, changes)

    assert result.deleted == 1
    deleted_belief: Belief | None = store.get_belief(bid)
    assert deleted_belief is not None
    assert deleted_belief.valid_to is not None


# ---------------------------------------------------------------------------
# Canvas export tests
# ---------------------------------------------------------------------------


def test_canvas_basic(store: MemoryStore, vault_path: Path) -> None:
    """Canvas export produces valid JSON with nodes and edges."""
    bid1: str = _make_belief(store, "Canvas node one")
    bid2: str = _make_belief(store, "Canvas node two")
    b1: Belief | None = store.get_belief(bid1)
    b2: Belief | None = store.get_belief(bid2)
    assert b1 is not None and b2 is not None

    edge_id: int = store.insert_edge(bid1, bid2, "SUPPORTS", reason="test")

    from agentmemory.models import Edge as EdgeModel

    edges: list[EdgeModel] = [
        EdgeModel(
            id=edge_id,
            from_id=bid1,
            to_id=bid2,
            edge_type="SUPPORTS",
            weight=1.0,
            reason="test",
            created_at="2026-01-01T00:00:00Z",
        )
    ]

    canvas_path: Path = vault_path / "_canvas" / "test.canvas"
    result: dict[str, object] = beliefs_to_canvas(
        [b1, b2], edges, title="Test", output_path=canvas_path
    )

    assert "nodes" in result
    assert "edges" in result
    assert canvas_path.exists()

    import json
    from typing import Any, cast

    data: dict[str, Any] = cast(
        "dict[str, Any]", json.loads(canvas_path.read_text(encoding="utf-8"))
    )
    nodes: list[Any] = cast("list[Any]", data["nodes"])
    assert len(nodes) == 2
    canvas_edges: list[Any] = cast("list[Any]", data["edges"])
    assert len(canvas_edges) == 1


def test_canvas_empty(store: MemoryStore) -> None:
    """Canvas with no beliefs produces empty nodes/edges."""
    from typing import Any, cast

    result: dict[str, object] = beliefs_to_canvas([], [], title="Empty")
    nodes: list[Any] = cast("list[Any]", result["nodes"])
    assert len(nodes) == 0
