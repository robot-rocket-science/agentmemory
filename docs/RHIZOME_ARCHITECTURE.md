# Rhizome Architecture: Cross-Project Memory

Status: Design proposal (2026-04-17)
Origin: Wonder session in robotrocketscience project

## Problem

Each project gets an isolated SQLite database keyed by SHA256 hash of its
absolute path. This prevents contamination but creates complete silos. Useful
knowledge is trapped -- a deploy workflow learned in project A can't be found
when working in project B.

An A/B test (2026-04-15) showed that when cross-project beliefs do leak
through, 25% are relevant and 75% are noise. The signal exists but needs
filtering.

## Metaphor: Bamboo Rhizome Network

Each project vault is a culm (visible stalk). An underground rhizome connects
them. Key biological properties that inform the design:

- **Demand-driven transfer.** Culms send nutrients when new shoots signal need,
  not as broadcast. Cross-vault search should be pull-based.
- **Containment is genetic.** Clumping vs running behavior is hardcoded at the
  species level. Vault propagation rules should be declared at creation.
- **Severed sections deplete.** Orphaned vaults should have a TTL before going
  read-only.
- **Age-based roles.** Young vaults store, mature vaults transport, old vaults
  archive.
- **Mycorrhizal > pure rhizome for cross-project flows.** Fungal networks are
  loosely coupled brokers with negotiated exchange. Cross-project flows should
  go through a neutral intermediary, not direct vault-to-vault connections.

Source: PMC10780645 (bamboo rhizome-culm system), Frontiers (water transfer
between culms), Wikipedia (mycorrhizal networks).

## Architecture

```
~/.agentmemory/
  rhizome.db                <-- vault registry + promoted beliefs + FTS5 index
  projects/
    <hash>/memory.db        <-- culm: project-local beliefs (unchanged)
    <hash>/memory.db        <-- culm: project-local beliefs (unchanged)
```

### Core rules

1. **Writes are always vault-local.** `remember`, `onboard`, `lock` write to
   the current project's memory.db only.
2. **Cross-vault reads go through the rhizome.** Never open a foreign vault
   directly. The rhizome mediates all cross-project queries.
3. **No cross-vault edges.** Beliefs in vault A never get SUPPORTS/CONTRADICTS
   edges pointing to beliefs in vault B.
4. **Promoted beliefs are copies, not references.** When a belief is promoted
   to rhizome.db, it's copied with provenance metadata. The original stays
   in its vault.

### rhizome.db schema

```sql
CREATE TABLE vaults (
    hash TEXT PRIMARY KEY,
    project_path TEXT NOT NULL,
    project_name TEXT NOT NULL,
    belief_count INTEGER DEFAULT 0,
    active_count INTEGER DEFAULT 0,
    last_session TEXT,
    maturity TEXT DEFAULT 'bootstrap',  -- bootstrap | operating | legacy
    sensitivity TEXT DEFAULT 'normal',  -- normal | sensitive | restricted
    onboarded_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE promoted_beliefs (
    id TEXT PRIMARY KEY,
    source_vault TEXT NOT NULL REFERENCES vaults(hash),
    content TEXT NOT NULL,
    confidence REAL,
    belief_type TEXT,
    source_type TEXT,
    promoted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    promoted_by TEXT,  -- 'user' | 'auto'
    retrieval_count INTEGER DEFAULT 0
);

-- FTS5 index for promoted beliefs only (not all beliefs across all vaults)
CREATE VIRTUAL TABLE promoted_fts USING fts5(content, content=promoted_beliefs);
```

### Why this schema

- **FTS5 cannot span attached databases.** Both the FTS index and content table
  must reside in the same DB file. A unified cross-vault FTS5 index is
  impossible via ATTACH. Source: sqlite.org/fts5.html
- **ATTACH DATABASE has a hard limit of 125 DBs.** At 50+ vaults, ATTACH-based
  federation breaks. Source: sqlite.org/limits.html
- **swarmvtab is read-only and only efficient on rowid range queries.** Not
  suitable for full-text search. Source: sqlite.org/swarmvtab.html
- **WAL mode supports concurrent reads.** Multiple Claude Code sessions can
  read rhizome.db simultaneously. Source: sqlite.org/wal.html

The promoted_beliefs table solves the FTS5 limitation: instead of searching
all vaults, the rhizome maintains its own FTS5 index of explicitly promoted
beliefs. This is write-side governance -- deciding what should be shared, not
just what can be found.

## Promotion model: hybrid auto-candidate + user confirm

Neither pure explicit nor pure automatic promotion works alone.

**Against pure explicit:** A single developer won't manually curate 39K+
beliefs. The locked beliefs system proves this -- only 2 locked beliefs exist
across all projects despite months of use.

**Against pure automatic:** The A/B test (75% noise) proves automatic sharing
without governance creates contamination. Retrieval frequency within one
project doesn't correlate with cross-project value.

### Hybrid approach

1. **Auto-candidate**: beliefs meeting ALL of:
   - confidence >= 0.85
   - source_type IN ('user_stated', 'user_corrected')
   - Retrieved in 2+ distinct sessions
   - Content is not project-specific (heuristic: no project-local paths,
     file names, or domain-specific entities)

2. **Promotion queue**: candidates surface via `agentmemory candidates` or
   during session start. User confirms with a single keystroke.

3. **Auto-promote locked beliefs**: anything the user locks is important enough
   to be global. Already the behavior -- locked beliefs inject via SessionStart
   hook regardless of project.

4. **Decay**: promoted beliefs un-retrieved for 90 days get demoted back to
   vault-local. Prevents rhizome from accumulating stale knowledge.

### Open questions in this model

- The "not project-specific" heuristic is the weakest part. Distinguishing
  "deploy to Cloudflare" (cross-project) from "deploy solar-wallpaper endpoint"
  (project-specific) needs semantic understanding that FTS5 can't provide.
- Retrieval count across vaults (not just within one vault) would be a stronger
  signal for auto-candidating, but requires cross-vault retrieval tracking that
  doesn't exist yet.
- Beliefs from sensitivity=restricted vaults should never auto-candidate.

## CLI extensions

```
agentmemory onboard <path>       # auto-registers vault in rhizome.db
agentmemory promote <belief-id>  # copy belief to rhizome promoted_beliefs
agentmemory candidates           # show auto-candidate beliefs pending review
agentmemory search --cross-vault # search rhizome FTS5 + current vault FTS5
agentmemory vaults               # list registered vaults from rhizome
agentmemory propagate            # update promoted beliefs when source changes
agentmemory demote <belief-id>   # remove from rhizome, return to vault-local
```

### search --cross-vault behavior

1. Search current vault's FTS5 index (existing behavior)
2. Search rhizome.db promoted_fts
3. Merge results, tagging each with source vault name
4. Rank by confidence, with current-vault results boosted
5. Return merged results with provenance labels

## Failure modes and mitigations

| Failure | Impact | Mitigation |
|---------|--------|------------|
| rhizome.db corrupts | Cross-vault search unavailable | Vaults fully independent; degrade to single-vault |
| Project renamed (hash changes) | Orphaned vault in registry | Store path + name; registry cleanup command |
| Contradictions across vaults | Ambiguous retrieval | Provenance tags; no conflict resolution attempted |
| Sensitive beliefs leak | Privacy violation | Per-vault sensitivity flag; restricted vaults excluded from cross-vault search |
| Noise from irrelevant vaults | Poor retrieval quality | Filter by confidence >= 0.8, source_type = user_stated/user_corrected |
| Concurrent writes to rhizome.db | SQLite busy errors | WAL mode; promote operations are infrequent |

## Experiments to validate

Priority order (run C first as safety gate):

| # | Question | Method | Success criteria | Effort |
|---|----------|--------|-----------------|--------|
| C | Zero write side effects? | Instrument reads, run 20 cross-vault queries | Zero mutations | 3-4h |
| A | Can noise drop below 30%? | Filter by confidence/type/source, annotate 50 queries | Precision >= 70% | 4-5h |
| D | Latency at 50 vaults? | Synthetic vaults, benchmark search | p95 < 500ms at 50 vaults | 6-7h |
| B | Do promoted beliefs help? | Mock rhizome with ~200 hub beliefs, measure MRR | MRR +10% in 3+ vaults | 5-6h |
| E | Does knowledge actually transfer? | Real task aided by cross-vault context | Coverage +20%, zero contradictions | 7-8h |

## Prior art

- **Neo4j 4.0+**: separate DBs per tenant, no cross-database edges. Same
  isolation model.
- **CockroachDB REGIONAL BY TABLE**: writes isolated to single region, reads
  can span. Direct analog.
- **Microsoft FedX**: sync distilled knowledge across silos, not raw data.
  Rhizome stores promoted (distilled) beliefs, not copies of everything.
- **Graphiti/FalkorDB**: group_id-based isolation for multi-tenant agent memory.

## Relationship to V2_ARCHITECTURE.md

V2 makes the Obsidian vault canonical and SQLite derived. The rhizome
architecture is orthogonal: it connects vaults across projects. They compose:

- Each project's vault-first store is a culm
- rhizome.db is the root network connecting them
- promoted_beliefs in rhizome.db could sync to an Obsidian "grove" vault
  containing only cross-project beliefs

## Migration path

1. Add vault auto-registration to `onboard` command
2. Create rhizome.db with vaults table
3. Add `promote` command
4. Add `search --cross-vault` flag
5. Add promoted_fts index
6. Wipe and re-onboard all projects with new architecture

No existing data needs migration. The rhizome is additive.
