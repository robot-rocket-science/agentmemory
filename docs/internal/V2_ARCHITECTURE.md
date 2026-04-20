# agentmemory v2: Vault-First Architecture

## Summary

v2 inverts the storage model: the Obsidian vault (.md files) becomes the
canonical store for beliefs. SQLite becomes a derived read-optimized index
that can be fully rebuilt from the vault at any time.

## Design Principles

1. **Vault is truth.** Delete a .md file, the belief is gone. Edit it, the belief changes.
2. **Index is derived.** SQLite can be rebuilt from vault via `agentmemory rebuild-index`.
3. **Retrieval stays fast.** All reads go through the SQLite index (FTS5, HRR, BFS). No performance loss.
4. **Human edits are first-class.** Changes made in Obsidian are picked up automatically.
5. **Backwards compatible.** MCP tools and CLI commands keep the same interface.

## Vault Schema (Canonical Belief Format)

Each belief is a .md file in `beliefs/{id}.md`:

```yaml
---
id: a1b2c3d4e5f6
type: correction
confidence: 0.947
alpha: 9.0
beta: 0.5
source: user_corrected
locked: true
scope: project
rigor: validated
content_hash: f7a8b9c0d1e2
created: 2026-04-10T14:30:00+00:00
updated: 2026-04-16T22:00:00+00:00
session: e5f6a7b8c9d0
superseded_by: null
classified_by: llm
event_time: null
data_source: conversation
method: null
sample_size: null
independently_validated: false
aliases:
  - a1b2c3d4e5f6
---

# a1b2c3d4e5f6

Always use pyright strict mode for all Python files in this project.

## Relationships

- **SUPPORTS** [[b2c3d4e5f6a7]] - code quality enforcement
- **RELATES_TO** [[c3d4e5f6a7b8]] - typing standards
- **SUPERSEDES** [[d4e5f6a7b8c9]] - replaced looser type checking
```

All Belief dataclass fields are represented in frontmatter. The body contains
the belief content text. Relationships are wikilinks parsed into edges on
index rebuild.

## Architecture Layers

```
Layer 1: Vault (.md files)          <- source of truth
  |
  v (parsed on write + periodic rebuild)
Layer 2: SQLite Index               <- derived, rebuildable
  |
  v (read at query time)
Layer 3: HRR Encoding               <- derived from index edges
  |
  v
Layer 4: Retrieval Pipeline          <- unchanged from v1
```

## Write Path

When `insert_belief()` is called:

```
1. Generate belief ID + content hash
2. Create .md file in beliefs/{id}.md with full frontmatter + content
3. Insert into SQLite beliefs table (index)
4. Insert into FTS5 search_index
5. Run relationship detector -> create edges
6. Write wikilinks to .md file for new edges
7. Mark HRR cache dirty (re-encode on next query)
```

When `update_confidence()` is called (feedback):

```
1. Update SQLite alpha/beta/confidence (fast)
2. Update .md frontmatter alpha/beta/confidence (rewrite file)
3. Log to confidence_history (SQLite only -- audit trail)
```

When belief is edited in Obsidian:

```
1. File watcher or explicit import detects changed .md file
2. Parse frontmatter + body text
3. If content changed: update SQLite content + content_hash + FTS5
4. If frontmatter changed: update SQLite metadata fields
5. If relationships changed: reconcile edges table
6. Mark HRR cache dirty
```

## Read Path (Unchanged)

`retrieve()` reads from SQLite index exactly as in v1:
- L0: locked beliefs from index
- L1: behavioral beliefs from index
- L2: FTS5 keyword search
- L3a: HRR vocabulary bridge
- L3b: BFS graph traversal
- Scoring via scoring.py (confidence, decay, Thompson, structural boost)

No performance change. The index is always up-to-date with the vault.

## Index Rebuild

`agentmemory rebuild-index` reconstructs SQLite from vault:

```python
def rebuild_index(vault_path: Path, db_path: Path) -> RebuildResult:
    """Destroy and reconstruct the SQLite index from vault .md files."""
    1. Drop all beliefs, edges, search_index rows
    2. Scan beliefs/*.md files
    3. For each file:
       a. Parse frontmatter -> Belief fields
       b. Parse body -> content text
       c. Parse ## Relationships -> edges (wikilinks)
       d. INSERT into beliefs table
       e. INSERT into search_index (FTS5)
       f. INSERT edges
    4. Scan _docs/*.md files -> graph_edges (doc-belief links)
    5. Rebuild HRR encoding from new edge set
    6. Report: beliefs indexed, edges created, time elapsed
```

This is the recovery mechanism. If SQLite is corrupted or lost, `rebuild-index`
restores everything from the vault.

## What Stays in SQLite Only

Some data is transient/operational and does not belong in .md files:

| Table | In vault? | Rationale |
|-------|-----------|-----------|
| beliefs | Yes (.md files) | Canonical store |
| edges | Yes (wikilinks) | Parsed from ## Relationships |
| search_index | No (derived) | Rebuilt from belief content |
| sessions | No | Operational metadata, not knowledge |
| checkpoints | No | Session state, ephemeral |
| tests | No | Feedback events, operational |
| confidence_history | No | Audit trail, append-only |
| observations | No | Raw input, not curated knowledge |
| graph_edges | Partially (_docs/ links) | Document cross-references |
| onboarding_runs | No | Operational metadata |
| pending_feedback | No | Queue, ephemeral |

Rule of thumb: if a human would want to read or edit it, it goes in the vault.
If it's machine bookkeeping, it stays in SQLite.

## New Module: VaultStore

```python
class VaultStore:
    """Vault-backed belief storage with SQLite index."""

    def __init__(self, vault_path: Path, index_path: Path):
        self.vault_path = vault_path
        self.index = MemoryStore(index_path)  # existing SQLite store
        self.beliefs_dir = vault_path / "beliefs"

    def insert_belief(self, ...) -> Belief:
        # 1. Write .md file
        # 2. Index in SQLite
        # 3. Detect relationships
        # 4. Update .md with wikilinks

    def update_confidence(self, belief_id, outcome, weight):
        # 1. Update SQLite (fast path)
        # 2. Rewrite .md frontmatter (async or batched)

    def soft_delete_belief(self, belief_id):
        # 1. Move .md to _archive/
        # 2. Set valid_to in SQLite

    def get_belief(self, belief_id) -> Belief:
        # Read from SQLite index (fast)
        return self.index.get_belief(belief_id)

    def rebuild_index(self):
        # Parse all .md files, reconstruct SQLite
```

VaultStore wraps MemoryStore. The retrieval pipeline, MCP server, and CLI
use VaultStore instead of MemoryStore directly. The interface is identical.

## Edge Storage

Edges live in two places:
1. **In .md files** as wikilinks in ## Relationships section (human-visible)
2. **In SQLite edges table** as indexed rows (machine-queryable)

On write: create edge in both places.
On rebuild: parse wikilinks from .md files to reconstruct edges table.
On Obsidian edit: if user adds/removes a wikilink, reconcile edges table.

## HRR Integration

HRR currently calls `store.get_all_edge_triples()` which reads from SQLite.
No change needed -- the index always reflects the vault state.

For document-level edges (from doc_linker), these go into graph_edges and
are included in HRR encoding. Queries can traverse: belief -> document ->
other beliefs in that document, all via HRR vocabulary bridge.

## File Watcher Strategy

Two modes:
1. **Explicit sync** (default): `agentmemory import-obsidian` or MCP `import_obsidian()`
2. **Auto-sync** (opt-in): fsevents watcher on beliefs/ directory, debounced 2s

Start with explicit sync. Auto-sync is a future enhancement after the core
vault-first model is proven.

## Migration Path (v1 -> v2)

```
1. Run sync_vault(full=True) to export all beliefs to .md files
2. Verify: belief count in vault == belief count in SQLite
3. Switch MemoryStore -> VaultStore in server.py and cli.py
4. Run rebuild-index to verify roundtrip: vault -> index -> same data
5. Delete old SQLite (or keep as backup)
```

This is a non-destructive migration. The vault is already populated from
our v1 export work. We just flip which one is authoritative.

## Implementation Order

1. **VaultStore class** wrapping MemoryStore with vault write-through
2. **rebuild-index command** parsing .md files back to SQLite
3. **Roundtrip test** export -> rebuild -> compare (data integrity)
4. **Wire VaultStore** into server.py and cli.py
5. **Confidence update write-through** to .md frontmatter
6. **Edge reconciliation** on import (wikilink parsing)
7. **Migration script** for existing installations
8. **File watcher** (future, after core model is proven)
