"""VaultStore: Vault-first belief storage with SQLite index.

Wraps MemoryStore with vault write-through. All belief mutations write
to .md files first (source of truth), then update the SQLite index.
Reads go through SQLite for performance (FTS5, indexed queries).

The vault can reconstruct the index at any time via rebuild_index().
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agentmemory.models import Belief, Edge
from agentmemory.obsidian import (
    FRONTMATTER_RE,
    collect_edges_for_belief,
    parse_belief_frontmatter,
    write_belief_file,
)
from agentmemory.store import MemoryStore

_BELIEFS_SUBFOLDER: Final[str] = "beliefs"
_ARCHIVE_SUBFOLDER: Final[str] = "beliefs/_archive"


@dataclass
class RebuildResult:
    """Result of an index rebuild operation."""
    beliefs_indexed: int
    edges_created: int
    elapsed_seconds: float
    errors: list[str]


class VaultStore:
    """Vault-backed belief storage with SQLite index.

    The vault (.md files) is the source of truth. SQLite is a derived
    index for fast retrieval. All writes go to vault first.

    Usage:
        store = VaultStore(vault_path, index_path)
        # Use store.index for all read operations (unchanged from v1)
        # Use store methods for writes (vault + index)
    """

    def __init__(self, vault_path: Path, index_path: Path) -> None:
        self.vault_path: Path = vault_path
        self.index: MemoryStore = MemoryStore(index_path)
        self.beliefs_dir: Path = vault_path / _BELIEFS_SUBFOLDER
        self.archive_dir: Path = vault_path / _ARCHIVE_SUBFOLDER
        self.beliefs_dir.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        """Close the underlying SQLite index."""
        self.index.close()

    # ------------------------------------------------------------------
    # Write path: vault first, then index
    # ------------------------------------------------------------------

    def insert_belief(
        self,
        content: str,
        belief_type: str,
        source_type: str,
        alpha: float = 0.5,
        beta_param: float = 0.5,
        locked: bool = False,
        observation_id: str | None = None,
        created_at: str | None = None,
        event_time: str | None = None,
        session_id: str | None = None,
        classified_by: str = "offline",
        rigor_tier: str = "hypothesis",
        method: str | None = None,
        sample_size: int | None = None,
        data_source: str = "",
        independently_validated: bool = False,
    ) -> Belief:
        """Insert a belief: write .md file, then index in SQLite."""
        # Index first (generates ID, handles dedup)
        belief: Belief = self.index.insert_belief(
            content=content,
            belief_type=belief_type,
            source_type=source_type,
            alpha=alpha,
            beta_param=beta_param,
            locked=locked,
            observation_id=observation_id,
            created_at=created_at,
            event_time=event_time,
            session_id=session_id,
            classified_by=classified_by,
            rigor_tier=rigor_tier,
            method=method,
            sample_size=sample_size,
            data_source=data_source,
            independently_validated=independently_validated,
        )

        # Write vault file
        edges: list[tuple[str, str, str]] = self._get_edges_for_belief(belief.id)
        write_belief_file(belief, edges, self.beliefs_dir)

        return belief

    def update_confidence(
        self,
        belief_id: str,
        outcome: str,
        evidence_weight: float = 1.0,
    ) -> None:
        """Update confidence: SQLite first (fast), then .md frontmatter."""
        self.index.update_confidence(belief_id, outcome, evidence_weight)

        # Rewrite the .md file with updated frontmatter
        belief: Belief | None = self.index.get_belief(belief_id)
        if belief is not None:
            edges: list[tuple[str, str, str]] = self._get_edges_for_belief(belief_id)
            write_belief_file(belief, edges, self.beliefs_dir)

    def soft_delete_belief(self, belief_id: str) -> None:
        """Soft-delete: move .md to archive, set valid_to in index."""
        import shutil

        # Archive the vault file
        md_path: Path = self.beliefs_dir / f"{belief_id}.md"
        if md_path.exists():
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(md_path), str(self.archive_dir / md_path.name))

        # Update index
        self.index.soft_delete_belief(belief_id)

    def lock_belief(self, belief_id: str) -> None:
        """Lock a belief: update index + rewrite .md."""
        self.index.lock_belief(belief_id)
        belief: Belief | None = self.index.get_belief(belief_id)
        if belief is not None:
            edges: list[tuple[str, str, str]] = self._get_edges_for_belief(belief_id)
            write_belief_file(belief, edges, self.beliefs_dir)

    def update_belief_content(
        self,
        belief_id: str,
        new_content: str,
        new_content_hash: str,
    ) -> None:
        """Update belief content: rewrite .md + update index."""
        self.index.update_belief_content(belief_id, new_content, new_content_hash)
        belief: Belief | None = self.index.get_belief(belief_id)
        if belief is not None:
            edges: list[tuple[str, str, str]] = self._get_edges_for_belief(belief_id)
            write_belief_file(belief, edges, self.beliefs_dir)

    def insert_edge(
        self,
        from_id: str,
        to_id: str,
        edge_type: str,
        weight: float = 1.0,
        reason: str = "",
    ) -> int:
        """Insert edge: index + update both endpoint .md files."""
        edge_id: int = self.index.insert_edge(from_id, to_id, edge_type, weight, reason)

        # Rewrite both endpoint files to include the new wikilink
        for bid in (from_id, to_id):
            belief: Belief | None = self.index.get_belief(bid)
            if belief is not None and belief.valid_to is None:
                edges: list[tuple[str, str, str]] = self._get_edges_for_belief(bid)
                write_belief_file(belief, edges, self.beliefs_dir)

        return edge_id

    # ------------------------------------------------------------------
    # Read path: delegate to index (unchanged performance)
    # ------------------------------------------------------------------

    def get_belief(self, belief_id: str) -> Belief | None:
        return self.index.get_belief(belief_id)

    def get_locked_beliefs(self) -> list[Belief]:
        return self.index.get_locked_beliefs()

    def get_all_active_beliefs(self, limit: int = 50000) -> list[Belief]:
        return self.index.get_all_active_beliefs(limit)

    def get_neighbors(
        self,
        belief_id: str,
        edge_types: list[str] | None = None,
        direction: str = "both",
    ) -> list[tuple[Belief, Edge]]:
        return self.index.get_neighbors(belief_id, edge_types, direction)

    def get_edges_by_belief_ids(
        self,
        belief_ids: list[str],
    ) -> dict[str, list[Edge]]:
        return self.index.get_edges_by_belief_ids(belief_ids)

    # Delegate all other reads to the index
    def __getattr__(self, name: str) -> object:
        """Delegate any unhandled method to the underlying MemoryStore index."""
        return getattr(self.index, name)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_edges_for_belief(self, belief_id: str) -> list[tuple[str, str, str]]:
        """Get edges formatted for .md file rendering."""
        all_edges: dict[str, list[Edge]] = self.index.get_edges_by_belief_ids([belief_id])
        return collect_edges_for_belief(belief_id, all_edges)

    # ------------------------------------------------------------------
    # Index rebuild from vault
    # ------------------------------------------------------------------

    def rebuild_index(self) -> RebuildResult:
        """Reconstruct the SQLite index from vault .md files.

        Drops all beliefs, edges, and search_index rows, then re-parses
        every .md file in the beliefs/ directory.  The entire operation
        runs in a single transaction so a crash mid-rebuild rolls back
        instead of leaving a half-deleted index.
        """
        start: float = time.monotonic()
        errors: list[str] = []

        with self.index.transaction():
            # Clear existing index data (order matters for FK constraints)
            self.index.query("DELETE FROM evidence")
            self.index.query("DELETE FROM tests")
            self.index.query("DELETE FROM confidence_history")
            self.index.query("DELETE FROM edges")
            self.index.query("DELETE FROM graph_edges")
            self.index.query("DELETE FROM search_index")
            self.index.query("DELETE FROM beliefs")

            beliefs_indexed: int = 0
            edges_created: int = 0

            # Collect pending edges for second pass (FK targets must exist first)
            _OUTGOING_TYPES: set[str] = {
                "SUPERSEDES", "SUPPORTS", "CONTRADICTS",
                "RELATES_TO", "CITES", "TESTS", "IMPLEMENTS",
            }
            pending_edges: list[tuple[str, str, str]] = []

            # Pass 1: Insert all beliefs
            for md_file in sorted(self.beliefs_dir.glob("*.md")):
                try:
                    content: str = md_file.read_text(encoding="utf-8")
                    fm: dict[str, str] = parse_belief_frontmatter(content)

                    if "id" not in fm:
                        errors.append(f"No id in frontmatter: {md_file.name}")
                        continue

                    belief_id: str = fm["id"]

                    # Extract body text (between frontmatter and ## Relationships)
                    fm_match: re.Match[str] | None = FRONTMATTER_RE.match(content)
                    body: str = content[fm_match.end():] if fm_match else content
                    body_lines: list[str] = body.strip().split("\n")
                    text_lines: list[str] = []
                    in_relationships: bool = False
                    for line in body_lines:
                        if line.startswith("# ") and len(line.strip()) <= 14:
                            continue
                        if line.startswith("## Relationships"):
                            in_relationships = True
                            continue
                        if in_relationships:
                            if line.startswith("## "):
                                in_relationships = False
                            else:
                                continue
                        text_lines.append(line)
                    belief_text: str = "\n".join(text_lines).strip()

                    if not belief_text:
                        errors.append(f"Empty body: {md_file.name}")
                        continue

                    alpha: float = float(fm.get("alpha", "0.5"))
                    beta: float = float(fm.get("beta", "0.5"))
                    locked_str: str = fm.get("locked", "false")
                    locked_val: bool = locked_str.lower() == "true"

                    # Direct SQL insert to preserve the original belief ID
                    content_hash: str = hashlib.sha256(
                        belief_text.encode("utf-8")
                    ).hexdigest()[:12]
                    ts: str = fm.get("created", fm.get("updated", ""))
                    updated: str = fm.get("updated", ts)
                    locked_int: int = 1 if locked_val else 0
                    self.index.query(
                        """INSERT OR IGNORE INTO beliefs
                           (id, content_hash, content, belief_type, alpha, beta_param,
                            source_type, locked, created_at, updated_at,
                            classified_by, rigor_tier, data_source)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (belief_id, content_hash, belief_text,
                         fm.get("type", "factual"), alpha, beta,
                         fm.get("source", "agent_inferred"), locked_int,
                         ts, updated,
                         fm.get("classified_by", "offline"),
                         fm.get("rigor", "hypothesis"),
                         fm.get("data_source", "")),
                    )
                    # Add to FTS5 index
                    self.index.query(
                        "INSERT INTO search_index(id, content, type) VALUES (?, ?, ?)",
                        (belief_id, belief_text, fm.get("type", "factual")),
                    )
                    beliefs_indexed += 1

                    # Collect edges for second pass
                    for line in body_lines:
                        wl_match: re.Match[str] | None = re.search(
                            r"\*\*(\w+)\*\*\s+\[\[([0-9a-f]{12})\]\]", line
                        )
                        if wl_match:
                            edge_type: str = wl_match.group(1)
                            target_id: str = wl_match.group(2)
                            if edge_type in _OUTGOING_TYPES:
                                pending_edges.append((belief_id, target_id, edge_type))

                except Exception as e:
                    errors.append(f"Error parsing {md_file.name}: {e}")

            # Pass 2: Insert edges (all beliefs now exist)
            indexed_ids: set[str] = set(self.index.get_active_belief_ids())
            for from_id, to_id, edge_type in pending_edges:
                if from_id in indexed_ids and to_id in indexed_ids:
                    try:
                        self.index.insert_edge(
                            from_id, to_id, edge_type,
                            reason="rebuilt from vault",
                        )
                        edges_created += 1
                    except Exception as e:
                        errors.append(f"Edge {from_id}->{to_id}: {e}")

        elapsed: float = time.monotonic() - start
        return RebuildResult(
            beliefs_indexed=beliefs_indexed,
            edges_created=edges_created,
            elapsed_seconds=round(elapsed, 2),
            errors=errors,
        )
