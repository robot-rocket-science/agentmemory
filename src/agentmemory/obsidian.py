"""Obsidian vault export for agentmemory beliefs.

Exports beliefs as markdown files with YAML frontmatter and wikilinked
edges into an Obsidian vault. Supports incremental sync via content-hash
comparison against a sync state file.

Phase A: one-way export (agentmemory -> Obsidian).
Phase B (future): bidirectional sync with import support.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, cast

from agentmemory.config import get_str_setting
from agentmemory.models import Belief, Edge
from agentmemory.store import MemoryStore

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_BELIEFS_SUBFOLDER: Final[str] = "beliefs"
_DEFAULT_ARCHIVE_SUBFOLDER: Final[str] = "beliefs/_archive"
_DEFAULT_INDEX_SUBFOLDER: Final[str] = "_index"
_SYNC_STATE_FILE: Final[str] = ".agentmemory_sync.json"

# Edge type display names when the edge is incoming (reversed perspective)
_INCOMING_LABELS: Final[dict[str, str]] = {
    "SUPERSEDES": "SUPERSEDED_BY",
    "SUPPORTS": "SUPPORTED_BY",
    "CONTRADICTS": "CONTRADICTED_BY",
    "CITES": "CITED_BY",
    "TESTS": "TESTED_BY",
    "IMPLEMENTS": "IMPLEMENTED_BY",
}


@dataclass
class ObsidianConfig:
    """Configuration for Obsidian vault sync."""
    vault_path: Path
    beliefs_subfolder: str = _DEFAULT_BELIEFS_SUBFOLDER
    archive_subfolder: str = _DEFAULT_ARCHIVE_SUBFOLDER
    index_subfolder: str = _DEFAULT_INDEX_SUBFOLDER


def load_obsidian_config(vault_override: str | None = None) -> ObsidianConfig | None:
    """Load obsidian config from settings or override.

    Returns None if no vault path is configured or provided.
    """
    vault_str: str = vault_override or get_str_setting("obsidian", "vault_path")
    if not vault_str:
        return None
    beliefs_sub: str = get_str_setting("obsidian", "beliefs_subfolder") or _DEFAULT_BELIEFS_SUBFOLDER
    return ObsidianConfig(
        vault_path=Path(vault_str),
        beliefs_subfolder=beliefs_sub,
        archive_subfolder=f"{beliefs_sub}/_archive",
    )


# ---------------------------------------------------------------------------
# Serialization: Belief -> Markdown
# ---------------------------------------------------------------------------

def belief_to_markdown(
    belief: Belief,
    edges: list[tuple[str, str, str]],
) -> str:
    """Convert a Belief and its edges into Obsidian-compatible markdown.

    Args:
        belief: The belief to serialize.
        edges: List of (other_belief_id, edge_type, reason) tuples.
            edge_type is from the perspective of this belief
            (outgoing = as-is, incoming = reversed label).

    Returns:
        Full markdown file content with YAML frontmatter.
    """
    # Build tags
    tags: list[str] = [f"belief/{belief.belief_type}"]
    if belief.locked:
        tags.append("locked")
    if belief.rigor_tier and belief.rigor_tier != "hypothesis":
        tags.append(f"rigor/{belief.rigor_tier}")
    tags.append(f"source/{belief.source_type}")

    # Frontmatter
    lines: list[str] = ["---"]
    lines.append(f"id: {belief.id}")
    lines.append(f"type: {belief.belief_type}")
    lines.append(f"confidence: {belief.confidence:.3f}")
    lines.append(f"alpha: {belief.alpha}")
    lines.append(f"beta: {belief.beta_param}")
    lines.append(f"source: {belief.source_type}")
    lines.append(f"locked: {'true' if belief.locked else 'false'}")
    lines.append(f"scope: {belief.scope}")
    if belief.rigor_tier:
        lines.append(f"rigor: {belief.rigor_tier}")
    lines.append(f"content_hash: {belief.content_hash}")
    if belief.created_at:
        lines.append(f"created: {belief.created_at}")
    if belief.updated_at:
        lines.append(f"updated: {belief.updated_at}")
    if belief.session_id:
        lines.append(f"session: {belief.session_id}")
    if belief.superseded_by:
        lines.append(f"superseded_by: {belief.superseded_by}")
    # Aliases for wikilink resolution
    lines.append("aliases:")
    lines.append(f"  - {belief.id}")
    # Tags
    lines.append("tags:")
    for tag in tags:
        lines.append(f"  - {tag}")
    lines.append("---")
    lines.append("")

    # Body: heading + content
    lines.append(f"# {belief.id}")
    lines.append("")
    lines.append(belief.content)
    lines.append("")

    # Relationships section
    if edges:
        lines.append("## Relationships")
        lines.append("")
        for other_id, edge_type, reason in edges:
            reason_suffix: str = f" - {reason}" if reason else ""
            lines.append(f"- **{edge_type}** [[{other_id}]]{reason_suffix}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Frontmatter parsing (for sync state comparison)
# ---------------------------------------------------------------------------

_FRONTMATTER_RE: Final[re.Pattern[str]] = re.compile(
    r"^---\n(.*?)\n---\n", re.DOTALL
)


def parse_belief_frontmatter(md_content: str) -> dict[str, str]:
    """Parse YAML frontmatter from a belief markdown file.

    Returns a dict of key -> value (all strings). Only parses simple
    key: value pairs, not nested structures.
    """
    match: re.Match[str] | None = _FRONTMATTER_RE.match(md_content)
    if match is None:
        return {}
    result: dict[str, str] = {}
    for line in match.group(1).split("\n"):
        if ":" in line and not line.startswith("  ") and not line.startswith("-"):
            key, _, val = line.partition(":")
            cleaned: str = val.strip().strip('"')
            result[key.strip()] = cleaned
    return result


# ---------------------------------------------------------------------------
# Edge collection
# ---------------------------------------------------------------------------

def collect_edges_for_belief(
    belief_id: str,
    all_edges: dict[str, list[Edge]],
) -> list[tuple[str, str, str]]:
    """Get edges for a belief as (other_id, display_type, reason) tuples.

    Normalizes direction: outgoing edges use the edge_type as-is,
    incoming edges use reversed labels (SUPERSEDES -> SUPERSEDED_BY).
    """
    edges: list[Edge] | None = all_edges.get(belief_id)
    if not edges:
        return []
    result: list[tuple[str, str, str]] = []
    seen: set[int] = set()
    for edge in edges:
        if edge.id in seen:
            continue
        seen.add(edge.id)
        if edge.from_id == belief_id:
            # Outgoing edge
            result.append((edge.to_id, edge.edge_type, edge.reason))
        else:
            # Incoming edge: reverse the label
            label: str = _INCOMING_LABELS.get(edge.edge_type, edge.edge_type)
            result.append((edge.from_id, label, edge.reason))
    return result


# ---------------------------------------------------------------------------
# Sync state persistence
# ---------------------------------------------------------------------------

def _read_sync_state(vault_path: Path) -> dict[str, str]:
    """Read content_hash map from sync state file.

    Returns dict of belief_id -> content_hash. Empty dict if no state file.
    """
    state_path: Path = vault_path / _SYNC_STATE_FILE
    if not state_path.exists():
        return {}
    try:
        raw: str = state_path.read_text(encoding="utf-8")
        data: object = json.loads(raw)
        if isinstance(data, dict):
            data_dict: dict[str, Any] = cast("dict[str, Any]", data)
            hashes_raw: object = data_dict.get("content_hashes", {})
            if isinstance(hashes_raw, dict):
                typed_hashes: dict[str, Any] = cast("dict[str, Any]", hashes_raw)
                return {str(k): str(v) for k, v in typed_hashes.items()}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _write_sync_state(
    vault_path: Path,
    sync_time: str,
    content_hashes: dict[str, str],
) -> None:
    """Write sync state atomically."""
    state_path: Path = vault_path / _SYNC_STATE_FILE
    data: dict[str, object] = {
        "last_sync_at": sync_time,
        "belief_count": len(content_hashes),
        "content_hashes": content_hashes,
    }
    # Atomic write via temp file + rename
    fd: int
    tmp_name: str
    fd, tmp_name = tempfile.mkstemp(
        dir=str(vault_path), suffix=".tmp", prefix=".sync_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        os.rename(tmp_name, str(state_path))
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


# ---------------------------------------------------------------------------
# File writing
# ---------------------------------------------------------------------------

def _write_belief_file(
    belief: Belief,
    edges: list[tuple[str, str, str]],
    beliefs_dir: Path,
) -> None:
    """Write a single belief's markdown file atomically."""
    content: str = belief_to_markdown(belief, edges)
    target: Path = beliefs_dir / f"{belief.id}.md"
    # Atomic: write to temp, then rename
    fd: int
    tmp_name: str
    fd, tmp_name = tempfile.mkstemp(
        dir=str(beliefs_dir), suffix=".tmp", prefix=f".{belief.id}_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.rename(tmp_name, str(target))
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _archive_stale_files(
    active_ids: set[str],
    beliefs_dir: Path,
    archive_dir: Path,
) -> int:
    """Move .md files from beliefs/ to _archive/ if not in active set.

    Returns count of archived files.
    """
    archived: int = 0
    if not beliefs_dir.exists():
        return 0
    for md_file in beliefs_dir.glob("*.md"):
        belief_id: str = md_file.stem
        if belief_id not in active_ids:
            archive_dir.mkdir(parents=True, exist_ok=True)
            dest: Path = archive_dir / md_file.name
            shutil.move(str(md_file), str(dest))
            archived += 1
    return archived


# ---------------------------------------------------------------------------
# Index generation
# ---------------------------------------------------------------------------

def _generate_by_type_index(beliefs: list[Belief], index_dir: Path) -> None:
    """Write _index/by-type.md grouping beliefs by type."""
    by_type: dict[str, list[Belief]] = {}
    for b in beliefs:
        by_type.setdefault(b.belief_type, []).append(b)

    lines: list[str] = [
        "---",
        "tags: [index, auto-generated]",
        "---",
        "",
        "# Beliefs by Type",
        "",
    ]
    for btype in sorted(by_type.keys()):
        group: list[Belief] = by_type[btype]
        lines.append(f"## {btype} ({len(group)})")
        lines.append("")
        # Show top 50 by confidence for each type
        sorted_group: list[Belief] = sorted(group, key=lambda b: b.confidence, reverse=True)
        for b in sorted_group[:50]:
            preview: str = b.content[:80].replace("\n", " ")
            lines.append(f"- [[{b.id}]] ({b.confidence:.0%}) {preview}")
        if len(group) > 50:
            lines.append(f"- ... and {len(group) - 50} more")
        lines.append("")

    (index_dir / "by-type.md").write_text("\n".join(lines), encoding="utf-8")


def _generate_locked_index(beliefs: list[Belief], index_dir: Path) -> None:
    """Write _index/locked.md listing all locked beliefs."""
    locked: list[Belief] = [b for b in beliefs if b.locked]
    locked.sort(key=lambda b: b.confidence, reverse=True)

    lines: list[str] = [
        "---",
        "tags: [index, auto-generated, locked]",
        "---",
        "",
        f"# Locked Beliefs ({len(locked)})",
        "",
    ]
    for b in locked:
        preview: str = b.content[:80].replace("\n", " ")
        lines.append(f"- [[{b.id}]] ({b.confidence:.0%}) {preview}")
    lines.append("")

    (index_dir / "locked.md").write_text("\n".join(lines), encoding="utf-8")


def _generate_recent_index(
    beliefs: list[Belief],
    index_dir: Path,
    limit: int = 50,
) -> None:
    """Write _index/recent.md with the last N modified beliefs."""
    sorted_beliefs: list[Belief] = sorted(
        beliefs, key=lambda b: b.updated_at or b.created_at, reverse=True
    )

    lines: list[str] = [
        "---",
        "tags: [index, auto-generated]",
        "---",
        "",
        f"# Recent Beliefs (last {limit})",
        "",
    ]
    for b in sorted_beliefs[:limit]:
        preview: str = b.content[:80].replace("\n", " ")
        ts: str = (b.updated_at or b.created_at)[:10]
        lines.append(f"- [[{b.id}]] ({ts}) {preview}")
    lines.append("")

    (index_dir / "recent.md").write_text("\n".join(lines), encoding="utf-8")


def _generate_confidence_index(beliefs: list[Belief], index_dir: Path) -> None:
    """Write _index/by-confidence.md with tier groupings."""
    high: list[Belief] = []
    medium: list[Belief] = []
    low: list[Belief] = []
    for b in beliefs:
        if b.confidence >= 0.8:
            high.append(b)
        elif b.confidence >= 0.5:
            medium.append(b)
        else:
            low.append(b)

    lines: list[str] = [
        "---",
        "tags: [index, auto-generated]",
        "---",
        "",
        "# Beliefs by Confidence",
        "",
        f"## High (>= 80%) -- {len(high)} beliefs",
        "",
    ]
    for b in sorted(high, key=lambda b: b.confidence, reverse=True)[:50]:
        preview: str = b.content[:80].replace("\n", " ")
        lines.append(f"- [[{b.id}]] ({b.confidence:.0%}) {preview}")
    if len(high) > 50:
        lines.append(f"- ... and {len(high) - 50} more")
    lines.append("")

    lines.append(f"## Medium (50-79%) -- {len(medium)} beliefs")
    lines.append("")
    for b in sorted(medium, key=lambda b: b.confidence, reverse=True)[:50]:
        preview: str = b.content[:80].replace("\n", " ")
        lines.append(f"- [[{b.id}]] ({b.confidence:.0%}) {preview}")
    if len(medium) > 50:
        lines.append(f"- ... and {len(medium) - 50} more")
    lines.append("")

    lines.append(f"## Low (< 50%) -- {len(low)} beliefs")
    lines.append("")
    for b in sorted(low, key=lambda b: b.confidence, reverse=True)[:50]:
        preview: str = b.content[:80].replace("\n", " ")
        lines.append(f"- [[{b.id}]] ({b.confidence:.0%}) {preview}")
    if len(low) > 50:
        lines.append(f"- ... and {len(low) - 50} more")
    lines.append("")

    (index_dir / "by-confidence.md").write_text("\n".join(lines), encoding="utf-8")


def _generate_corrections_index(
    beliefs: list[Belief],
    store: MemoryStore,
    index_dir: Path,
) -> None:
    """Write _index/corrections.md with correction beliefs and chains."""
    corrections: list[Belief] = [b for b in beliefs if b.belief_type == "correction"]
    corrections.sort(key=lambda b: b.created_at, reverse=True)

    lines: list[str] = [
        "---",
        "tags: [index, auto-generated, correction]",
        "---",
        "",
        f"# Corrections ({len(corrections)})",
        "",
    ]
    for b in corrections[:100]:
        preview: str = b.content[:80].replace("\n", " ")
        chain: str = ""
        if b.superseded_by:
            chain = f" -> [[{b.superseded_by}]]"
        lines.append(f"- [[{b.id}]]{chain} {preview}")
    if len(corrections) > 100:
        lines.append(f"- ... and {len(corrections) - 100} more")
    lines.append("")

    (index_dir / "corrections.md").write_text("\n".join(lines), encoding="utf-8")


def generate_index_notes(
    beliefs: list[Belief],
    store: MemoryStore,
    config: ObsidianConfig,
) -> int:
    """Generate all index notes. Returns count of files written."""
    index_dir: Path = config.vault_path / config.index_subfolder
    index_dir.mkdir(parents=True, exist_ok=True)

    _generate_by_type_index(beliefs, index_dir)
    _generate_locked_index(beliefs, index_dir)
    _generate_recent_index(beliefs, index_dir)
    _generate_confidence_index(beliefs, index_dir)
    _generate_corrections_index(beliefs, store, index_dir)
    return 5


# ---------------------------------------------------------------------------
# Main sync engine
# ---------------------------------------------------------------------------

@dataclass
class SyncResult:
    """Result of a vault sync operation."""
    beliefs_written: int
    beliefs_archived: int
    beliefs_unchanged: int
    index_notes_written: int
    elapsed_seconds: float


def sync_vault(
    store: MemoryStore,
    config: ObsidianConfig,
    full: bool = False,
) -> SyncResult:
    """Export beliefs from the store to the Obsidian vault.

    Incremental by default: only writes files where the belief's
    content_hash has changed since the last sync.

    Args:
        store: The MemoryStore to read beliefs from.
        config: Obsidian vault configuration.
        full: If True, rewrite all files unconditionally.

    Returns:
        SyncResult with counts and timing.
    """
    start: float = time.monotonic()

    # Ensure directories exist
    beliefs_dir: Path = config.vault_path / config.beliefs_subfolder
    archive_dir: Path = config.vault_path / config.archive_subfolder
    beliefs_dir.mkdir(parents=True, exist_ok=True)

    # Load sync state (skip on full sync)
    prev_hashes: dict[str, str] = {} if full else _read_sync_state(config.vault_path)

    # Fetch all active beliefs
    all_beliefs: list[Belief] = store.get_all_active_beliefs()
    active_ids: set[str] = {b.id for b in all_beliefs}
    belief_ids: list[str] = list(active_ids)

    # Bulk-fetch all edges
    all_edges: dict[str, list[Edge]] = store.get_edges_by_belief_ids(belief_ids)

    # Write changed beliefs
    written: int = 0
    unchanged: int = 0
    new_hashes: dict[str, str] = {}

    for belief in all_beliefs:
        new_hashes[belief.id] = belief.content_hash
        if not full and prev_hashes.get(belief.id) == belief.content_hash:
            unchanged += 1
            continue
        edges: list[tuple[str, str, str]] = collect_edges_for_belief(
            belief.id, all_edges
        )
        _write_belief_file(belief, edges, beliefs_dir)
        written += 1

    # Archive stale files
    archived: int = _archive_stale_files(active_ids, beliefs_dir, archive_dir)

    # Generate index notes
    index_count: int = generate_index_notes(all_beliefs, store, config)

    # Save sync state
    sync_time: str = datetime.now(timezone.utc).isoformat()
    _write_sync_state(config.vault_path, sync_time, new_hashes)

    elapsed: float = time.monotonic() - start
    return SyncResult(
        beliefs_written=written,
        beliefs_archived=archived,
        beliefs_unchanged=unchanged,
        index_notes_written=index_count,
        elapsed_seconds=round(elapsed, 2),
    )
