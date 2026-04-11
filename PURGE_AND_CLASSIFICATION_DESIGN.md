# Purge and Manual Classification: Design Approaches

**Date:** 2026-04-10
**Status:** Research -- design options under evaluation
**Requirements:** REQ-028 (Purge Tool), REQ-029 (Manual Classification Pipeline)
**Constraint:** Privacy and security are hard requirements. Graph structure preservation is a design consideration.

---

## Purge: Graph Structure Preservation

### Approach 1: Content-Structure Separation

Split storage into two tables: a **structure table** (node IDs, edges, types, timestamps, metadata) and a **content table** (node ID -> text blob). They're joined at retrieval time.

- Tombstone: `DELETE FROM content WHERE id = ?`. Structure stays. Edge traversal still works. Derived beliefs see `evidence_status: redacted` because the content join returns null.
- Hard delete: `DELETE FROM content` + `DELETE FROM structure` + cascade edges.

**Tradeoff:** Adds a JOIN to every retrieval query. But it makes the purge boundary clean -- content is in exactly one place, and removing it is one DELETE. No risk of content surviving in a denormalized column somewhere.

**Graph impact:** Minimal for tombstone. BFS, HRR partitioning, and edge traversal all operate on structure. They don't need the content to traverse. Content is only needed at the final "render results to user" step.

### Approach 2: Soft-Delete Flag with Index Rebuild

Add `purged_at TIMESTAMP`, `purge_mode TEXT` columns to observations and beliefs. All retrieval queries get `WHERE purged_at IS NULL`. Tombstone overwrites content in-place.

- Simpler schema (no table split)
- But content and structure are co-located, so "did I actually scrub everything?" is harder to verify
- FTS5 index needs rebuild after purge (FTS5 doesn't support UPDATE well -- you'd `DELETE FROM fts_index WHERE rowid = ?` then the row is gone from search)
- HRR: re-encode any partition containing the purged node

**Tradeoff:** Simpler queries (no join), harder to audit completeness.

### Approach 3: Append-Only Purge Ledger

Never mutate the main tables. Instead, maintain a `purge_ledger` table: `(purged_id, purge_mode, purged_at, cascade_ids)`. All retrieval queries join against the ledger to exclude purged IDs.

- Main tables are truly append-only (REQ-013 stays pure)
- Content still exists on disk until VACUUM -- which matters for the "secret in hex dump" requirement
- Need a `VACUUM` + WAL checkpoint step as the final purge action to actually reclaim pages

**Tradeoff:** Philosophically cleanest (no mutation of source of truth), but the content is technically recoverable until VACUUM runs. For the secret-pasted-accidentally use case, that gap might be unacceptable.

### Recommendation: Approach 1 (content-structure separation)

The JOIN cost is negligible at the scale we're operating (sub-10K nodes). The purge boundary is unambiguous. Content lives in one place; when it's gone, it's gone. Structure survives for graph traversal. And it's auditable -- `SELECT count(*) FROM content WHERE id IN (purged_ids)` returns 0, done.

---

## Purge: Derived Index Consistency

Regardless of which approach above, derived data structures that contain copies of purged content must be handled:

| Derived Structure | What to do |
|---|---|
| **FTS5 index** | `DELETE FROM fts_index WHERE rowid = ?`. FTS5 supports this natively. |
| **HRR encodings** | Re-encode the partition containing the purged node. Partition size is 50-65 edges (from Exp 45), so this is cheap -- one partition re-encode, not a full rebuild. |
| **Cached contexts** | Invalidate any cached L0/L1/L2 context packs that included the purged node. Simple: keep a `cache_generation` counter, increment on purge, compare on cache read. |
| **WAL / journal** | After hard delete: `PRAGMA wal_checkpoint(TRUNCATE)` + `VACUUM`. Advise user that without VACUUM, deleted content may persist in reclaimed pages. |

---

## Orphaned Subgraphs After Hard Delete

Three options, not mutually exclusive:

**Option A -- Cascade delete.** If belief B's only evidence was observation O, and O is hard-deleted, delete B too. If B was the only source for belief C, delete C too. Recursive. This is the simplest but most destructive -- a single hard delete could ripple through a chain.

**Option B -- Flag as ungrounded.** Set `evidence_status: lost` on orphaned beliefs. They remain in the graph but get a confidence penalty (or drop to floor confidence). They still participate in traversal but rank last. User can review and decide.

**Option C -- Prompt the user.** During the hard-delete confirmation step, show the cascade tree: "Deleting O-42 will orphan beliefs B-17, B-23, B-41. What do you want to do with them? [delete / keep as ungrounded / cancel]". This is the most user-controlled but requires interactive CLI flow.

**Recommendation:** Option C for the confirmation step (show the user what they're about to break), with Option B as the non-interactive default (flag as ungrounded, don't silently delete things the user didn't ask to delete). This respects the principle that hard delete is already behind a confirmation gate -- the user is already in "careful mode" and can handle the decision.

---

## Manual Classification: Integration with Automated Pipeline

### Override Table Pattern

```sql
user_overrides (
    node_id       TEXT PRIMARY KEY,
    override_type TEXT,          -- 'type', 'irrelevant', 'project', 'rank', 'lock'
    value         TEXT,          -- the classification value
    created_at    TIMESTAMP,
    locked        BOOLEAN DEFAULT TRUE,
    source        TEXT DEFAULT 'user_manual'
)

user_edges (
    source_id  TEXT,
    target_id  TEXT,
    edge_type  TEXT,
    created_at TIMESTAMP,
    source     TEXT DEFAULT 'user_manual',
    PRIMARY KEY (source_id, target_id, edge_type)
)
```

At retrieval time, the pipeline checks `user_overrides` before automated classification. The merge logic:

1. If `user_overrides` has an entry for this node and `locked = TRUE`: use the override, skip automated classification entirely
2. If `user_overrides` has `irrelevant = TRUE`: exclude from retrieval results, don't consume token budget
3. If `user_overrides` has a `project` scope: apply as a retrieval filter (`WHERE project_scope = current_project OR project_scope IS NULL`)
4. User edges from `user_edges` are loaded into the graph alongside automated edges, same weight, same traversal rules

### Project Scoping at Retrieval Time

Two approaches:

**Filter approach:** Add `project_scope` to the override table. At query time, exclude items scoped to other projects. Items with no scope are global (visible everywhere). This is simple and the user controls it explicitly.

**Namespace approach:** Partition the FTS5 index and HRR encodings by project. Queries only search the current project's partition. Cross-project search requires an explicit flag. This is more expensive (multiple indexes) but provides stronger isolation.

**Recommendation:** Filter approach. At our scale, a single index with a WHERE clause is simpler and equally fast. Namespace partitioning is premature unless we're dealing with 100K+ nodes across dozens of projects.

---

## Open Design Questions

1. **Should tombstoned nodes still participate in BFS traversal?** If yes, they act as structural bridges (you can traverse through them but can't read their content). If no, tombstoning effectively severs the graph at that point. Lean: yes -- the structure is not sensitive, the content is.

2. **Should the purge tool operate on beliefs derived from a purged observation, or just the observation itself?** If the user pastes a secret and it gets extracted into a belief "API key is sk-abc123", tombstoning the observation but leaving the belief defeats the purpose. The purge should search both observations AND beliefs for the target content.

3. **How does purge interact with HRR encoding?** If a node is tombstoned, its random vector still exists in the HRR partition encoding. The vector itself doesn't contain content (it's random), but its presence affects similarity scores for neighboring nodes. Removing it from the encoding changes retrieval behavior for nearby nodes. Probably fine -- the change is small and doesn't leak information.

4. **Should `classify --irrelevant` be reversible?** If the user marks something irrelevant and later changes their mind, can they undo it? Lean: yes -- `classify <id> --relevant` removes the irrelevant flag. This is different from purge (which is intentionally destructive).
