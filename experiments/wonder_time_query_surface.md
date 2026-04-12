# Temporal Query Surface Design

Date: 2026-04-11
Status: Design document
Depends on: exp59 (traversal utility taxonomy), store.py schema, server.py MCP tools

## 1. Taxonomy of Temporal Queries an Agent Actually Asks

Exp59 identified 4 categories (RANGE, SEQUENCE, EVOLUTION, CAUSAL) across 10 queries.
Mapping those to natural agent questions and extending with real usage patterns:

### Category A: RANGE (time-window filtering)
- "What happened in session N?"
- "What was discussed between March 25 and March 28?"
- "What are the 5 most recent beliefs?"
- "What beliefs were active at time T?" (point-in-time snapshot)
- "What changed between session 5 and session 10?"

**Exp59 finding:** TIMESTAMP_ONLY achieves 100% completeness on all RANGE queries.
No graph traversal needed. Pure SQL on created_at, valid_from, valid_to.

### Category B: SEQUENCE (adjacency/ordering)
- "What was decided right before/after X?"
- "What was the conversation flow around decision Y?"
- "What 3 beliefs preceded this correction?"

**Exp59 finding:** TEMPORAL_NEXT edges required for Q4 (immediately after D097)
and Q5 (3 before D157). Timestamp ties break adjacency -- two beliefs at the same
timestamp have no ordering without TEMPORAL_NEXT. However, in the agentmemory
production schema, beliefs have ISO 8601 timestamps with sub-second precision.
Ties are rare. TEMPORAL_NEXT provides structural certainty but timestamp ORDER BY
is sufficient for most cases.

### Category C: EVOLUTION (supersession chains)
- "How did our understanding of Y evolve over time?"
- "What's the current version of decision X?"
- "What's the full correction chain for topic Z?"

**Exp59 finding:** SUPERSEDES chains are the ONLY method that answers Q7 (dispatch
gate evolution), Q8 (current capital decision), Q10 (calls/puts chain) with correct
completeness. Neither timestamps nor FTS5 can reconstruct which belief replaced which.

### Category D: CAUSAL (citation/dependency chains)
- "What decisions were influenced by X?"
- "What's the decision chain that led to conclusion W?"
- "What evidence supports belief B?"

**Exp59 finding:** Requires CITES edges + temporal filter. Neither FTS5 nor
TEMPORAL_NEXT encodes citation relationships.

### Category E: SESSION REPLAY (not in exp59, new)
- "What happened in session abc123?"
- "Replay the conversation from last Tuesday"
- "What beliefs were created in my last session?"

This is a join between beliefs/observations and session tracking. Currently,
observations have session_id but beliefs do NOT. Beliefs are linked to sessions
only via checkpoints (which store belief IDs in references).

### Category F: DIFFERENTIAL (not in exp59, new)
- "What changed between session 5 and session 10?"
- "What beliefs were added/removed/modified since yesterday?"
- "What's new since my last session?"

Requires comparing two time snapshots. Can be answered with created_at + valid_to
ranges: beliefs with created_at in range = added, beliefs with valid_to in range
= removed/superseded.


## 2. Per-Query-Type Analysis

### A: RANGE queries

**Data structures needed:** created_at index on beliefs table.
**Schema changes:** Add `CREATE INDEX idx_beliefs_created_at ON beliefs(created_at)`.
Currently missing -- queries would do full table scan at 17K beliefs.
**Algorithm:** `SELECT * FROM beliefs WHERE created_at >= ? AND created_at < ? AND valid_to IS NULL ORDER BY created_at`
**Latency at 17K:** <5ms with index, ~50ms without.
**Surface:** Both MCP tool and CLI.

### B: SEQUENCE queries

**Data structures needed:** created_at index (for timestamp-based adjacency).
TEMPORAL_NEXT edges in the edges table (for structural adjacency when timestamps
tie). Currently no TEMPORAL_NEXT edges exist in production -- ingest.py does not
create them.
**Schema changes:** Same created_at index. Optionally, ingest pipeline could
create TEMPORAL_NEXT edges between consecutive beliefs within a session.
**Algorithm (timestamp-based):**
```sql
-- Next after belief X
SELECT * FROM beliefs
WHERE created_at > (SELECT created_at FROM beliefs WHERE id = ?)
  AND valid_to IS NULL
ORDER BY created_at ASC LIMIT ?
```
**Algorithm (edge-based):** BFS on edges WHERE edge_type = 'TEMPORAL_NEXT'.
**Latency at 17K:** <5ms with index. BFS: <1ms (adjacency list, 1-3 hops).
**Surface:** MCP tool only. CLI has no adjacency use case.

### C: EVOLUTION queries

**Data structures needed:** SUPERSEDES edges in the edges table (already created
by supersede_belief()). The superseded_by column on beliefs.
**Schema changes:** None. Already supported.
**Algorithm:**
```sql
-- Follow supersession chain forward from belief X
-- Recursive CTE:
WITH RECURSIVE chain AS (
    SELECT id, content, superseded_by, created_at, 0 AS depth
    FROM beliefs WHERE id = ?
  UNION ALL
    SELECT b.id, b.content, b.superseded_by, b.created_at, c.depth + 1
    FROM beliefs b
    JOIN chain c ON b.superseded_by = c.id  -- who superseded me?
    WHERE c.depth < 20
)
SELECT * FROM chain ORDER BY depth;
```
Wait -- superseded_by points FROM old TO new (old.superseded_by = new.id). So
following the chain forward: start at old, find beliefs where other.superseded_by
IS the current id... no. superseded_by on old is set to new_id. So to find what
superseded old: look for beliefs where old.superseded_by = new.id. To go backward
from new: new.id appears in some old.superseded_by.

Correct forward traversal from old_id:
```sql
WITH RECURSIVE chain AS (
    SELECT id, content, superseded_by, created_at, 0 AS depth
    FROM beliefs WHERE id = :start_id
  UNION ALL
    SELECT b.id, b.content, b.superseded_by, b.created_at, c.depth + 1
    FROM beliefs b
    JOIN chain c ON c.superseded_by = b.id
    WHERE c.depth < 20
)
SELECT * FROM chain ORDER BY depth;
```

Correct backward traversal from new_id:
```sql
WITH RECURSIVE chain AS (
    SELECT id, content, superseded_by, created_at, 0 AS depth
    FROM beliefs WHERE id = :start_id
  UNION ALL
    SELECT b.id, b.content, b.superseded_by, b.created_at, c.depth + 1
    FROM beliefs b
    JOIN chain c ON b.superseded_by = c.id
    WHERE c.depth < 20
)
SELECT * FROM chain ORDER BY depth;
```

Also useful: topic-based evolution via FTS5 + time ordering, which shows ALL
beliefs about a topic over time (not just the supersession chain).

**Latency at 17K:** <1ms (recursive CTE on indexed superseded_by, chains are
short -- typically 2-5 hops).
**Surface:** MCP tool (primary). CLI (useful for audits).

### D: CAUSAL queries

**Data structures needed:** CITES edges in edges or graph_edges table.
**Schema changes:** None, but CITES edges are only created by the scanner
(onboard). Ingest does not create them.
**Algorithm:** BFS on edges WHERE edge_type = 'CITES', filtered by created_at.
**Latency at 17K:** <5ms.
**Surface:** MCP tool only. Too graph-heavy for CLI.
**Priority:** Low. CITES edges are sparse. Defer to phase 2.

### E: SESSION REPLAY

**Data structures needed:** Checkpoints table (session_id, references containing
belief IDs). Observations table (has session_id). Beliefs table (no session_id).
**Schema changes:** Add `session_id TEXT` column to beliefs table. Populate on
insert. This is the biggest gap. Without it, session replay requires joining
through checkpoints, which only captures remember/correct/lock operations, not
ingest-created beliefs.
**Algorithm (with session_id on beliefs):**
```sql
SELECT * FROM beliefs WHERE session_id = ? ORDER BY created_at
```
**Algorithm (without, using checkpoints):**
```sql
SELECT b.* FROM beliefs b
JOIN checkpoints c ON json_each.value = b.id
JOIN json_each(c."references") ON true
WHERE c.session_id = ?
ORDER BY b.created_at
```
This is slow and incomplete (misses ingest-created beliefs).
**Latency at 17K:** <5ms with session_id column and index. ~100ms via checkpoint join.
**Surface:** Both MCP tool and CLI.

### F: DIFFERENTIAL

**Data structures needed:** created_at and valid_to indexes on beliefs.
**Schema changes:** created_at index (same as RANGE).
**Algorithm:**
```sql
-- Added between T1 and T2
SELECT * FROM beliefs WHERE created_at >= ? AND created_at < ? ORDER BY created_at;
-- Removed between T1 and T2
SELECT * FROM beliefs WHERE valid_to >= ? AND valid_to < ? ORDER BY valid_to;
-- Modified (superseded and replaced)
SELECT old.id AS old_id, old.content AS old_content,
       new.id AS new_id, new.content AS new_content
FROM beliefs old
JOIN beliefs new ON old.superseded_by = new.id
WHERE old.valid_to >= ? AND old.valid_to < ?
ORDER BY old.valid_to;
```
**Latency at 17K:** <10ms with indexes.
**Surface:** MCP tool and CLI.


## 3. Proposed MCP Tools

Based on the taxonomy, three tools cover 90%+ of temporal query needs.
Category D (causal) is deferred -- it requires denser CITES edges than we have.

### Tool 1: `timeline(topic, start, end, session_id, limit)`

Covers: Categories A (RANGE), E (SESSION REPLAY), F (DIFFERENTIAL, partial).

```python
@mcp.tool
def timeline(
    topic: str | None = None,
    start: str | None = None,
    end: str | None = None,
    session_id: str | None = None,
    limit: int = 50,
) -> str:
    """Return beliefs ordered by time, filtered by topic and/or time range.

    - topic: FTS5 keyword filter (optional). If omitted, returns all beliefs in range.
    - start: ISO 8601 timestamp or "last_session" or "-7d" (relative).
    - end: ISO 8601 timestamp (optional, defaults to now).
    - session_id: filter to a specific session (requires session_id on beliefs).
    - limit: max beliefs to return (default 50).

    Use cases:
      timeline(topic="deployment") -- all deployment beliefs chronologically
      timeline(start="-7d") -- everything from the last 7 days
      timeline(session_id="abc123") -- replay session abc123
      timeline(topic="capital", start="2026-03-25", end="2026-03-28")
    """
```

**Implementation notes:**
- If topic is provided: FTS5 search, then filter by time range, order by created_at.
- If session_id is provided: filter by session_id column on beliefs (requires schema migration).
- Relative time parsing: "-7d" = now minus 7 days, "-24h" = now minus 24 hours, "last_session" = start time of most recent completed session.
- Output format: chronological list with timestamps, belief type, confidence.

### Tool 2: `evolution(belief_id, topic)`

Covers: Category C (EVOLUTION).

```python
@mcp.tool
def evolution(
    belief_id: str | None = None,
    topic: str | None = None,
) -> str:
    """Trace how a belief or topic evolved over time.

    Two modes:
    1. belief_id provided: follow the SUPERSEDES chain in both directions.
       Shows: original belief -> correction 1 -> correction 2 -> current.
    2. topic provided: FTS5 search + time ordering. Shows all beliefs about
       the topic chronologically, marking which ones superseded others.

    Use cases:
      evolution(belief_id="a1b2c3d4e5f6") -- full chain for this belief
      evolution(topic="dispatch gate") -- how dispatch gate policy evolved
    """
```

**Implementation notes:**
- belief_id mode: Recursive CTE on superseded_by. Walk backward to find the
  original, then forward to find the current. Return the full chain with
  timestamps and confidence at each step.
- topic mode: FTS5 search, order by created_at, annotate superseded beliefs
  with arrows showing replacement. This catches topic evolution even when
  supersession edges are missing (e.g., two beliefs about the same topic
  that were never formally linked).
- For each belief in the chain, show: ID, content, created_at, confidence,
  whether it's the current version or superseded.

### Tool 3: `diff(since, until, session_id)`

Covers: Category F (DIFFERENTIAL).

```python
@mcp.tool
def diff(
    since: str | None = None,
    until: str | None = None,
    session_id: str | None = None,
) -> str:
    """Show what changed in the belief store over a time period.

    Returns three sections:
    - ADDED: beliefs created in the period
    - REMOVED: beliefs soft-deleted or superseded in the period
    - EVOLVED: beliefs that were superseded and replaced (shows old -> new)

    - since: ISO 8601 or relative ("-7d", "-24h", "last_session")
    - until: ISO 8601 (defaults to now)
    - session_id: scope to changes from a specific session

    Use cases:
      diff(since="last_session") -- what changed since my last session
      diff(since="-7d") -- weekly diff
      diff(session_id="abc123") -- what session abc123 did
    """
```

**Implementation notes:**
- Three SQL queries (added, removed, evolved) as described in section 2F.
- "last_session" resolved by finding the most recent session with completed_at IS NOT NULL.
- Compact output: group by type (factual, correction, preference, etc.), show counts.


## 4. Proposed CLI Commands

```
agentmemory timeline [--topic TOPIC] [--since SINCE] [--until UNTIL] [--session SESSION] [--limit N]
agentmemory evolution <belief_id | --topic TOPIC>
agentmemory diff [--since SINCE] [--until UNTIL] [--session SESSION]
agentmemory sessions [--limit N]         # list sessions with start/end times
```

The CLI commands wrap the same logic as the MCP tools but format output for
terminal display (tables, color, truncation).


## 5. Required Schema Changes

### Migration 1: Index on beliefs.created_at (non-breaking)
```sql
CREATE INDEX IF NOT EXISTS idx_beliefs_created_at ON beliefs(created_at);
```
Required for all RANGE and DIFFERENTIAL queries. Without it, every temporal
query does a full table scan.

### Migration 2: session_id on beliefs (non-breaking, additive)
```sql
ALTER TABLE beliefs ADD COLUMN session_id TEXT DEFAULT NULL;
CREATE INDEX IF NOT EXISTS idx_beliefs_session_id ON beliefs(session_id);
```
Required for session replay. Without it, the only path from session to
beliefs is through checkpoints, which only captures manual operations
(remember, correct, lock), not ingest-created beliefs.

The ingest pipeline must be updated to pass session_id through to
insert_belief(). The insert_belief() method already accepts created_at
as an optional parameter; adding session_id follows the same pattern.

### Migration 3: Index on beliefs.valid_to (already exists)
`idx_beliefs_valid_to` already exists. Used by DIFFERENTIAL queries to
find beliefs removed in a time range.

### No new tables needed.
All temporal queries work against existing tables + the two new indexes
and one new column.


## 6. Experiment Design: Temporal Queries vs Keyword Search

### Hypothesis
For Categories C (EVOLUTION) and B (SEQUENCE), temporal query tools produce
results that keyword search (FTS5 via the existing `search` tool) cannot.
For Category A (RANGE), keyword search can approximate but with lower
precision (irrelevant results mixed in).

### Method

Use the production agentmemory DB (~17K beliefs, as reported by status).

**Setup:**
1. Identify 10 test queries spanning all categories.
2. For each query, run both the temporal tool and equivalent keyword search.
3. Measure: precision, recall, ordering correctness, unique results.

**Test queries:**

| # | Natural question | Category | Temporal tool | Keyword search equivalent |
|---|---|---|---|---|
| T1 | "What happened in the last 24 hours?" | RANGE | `timeline(start="-24h")` | `search("recent changes")` |
| T2 | "What was decided right after we chose HRR?" | SEQUENCE | `timeline(topic="HRR", limit=5)` then take next | `search("HRR decision")` |
| T3 | "How did the retrieval strategy evolve?" | EVOLUTION | `evolution(topic="retrieval")` | `search("retrieval strategy")` |
| T4 | "What's the current version of the commit hook decision?" | EVOLUTION | `evolution(belief_id=<commit_hook_belief>)` | `search("commit hook")` |
| T5 | "What changed since yesterday?" | DIFF | `diff(since="-24h")` | impossible with search |
| T6 | "Replay my last session" | SESSION | `timeline(session_id=<last>)` | impossible with search |
| T7 | "What 3 beliefs preceded the HRR module creation?" | SEQUENCE | `timeline(end=<hrr_created_at>, limit=3)` | `search("before HRR")` |
| T8 | "Show all corrections in the last week" | RANGE | `timeline(start="-7d")` + filter type=correction | `search("correction")` |
| T9 | "What's new since session X?" | DIFF | `diff(since=<session_X_start>)` | impossible with search |
| T10 | "Full history of the scoring algorithm topic" | EVOLUTION | `evolution(topic="scoring algorithm")` | `search("scoring algorithm")` |

**Metrics per query:**
- **Recall:** Does the method find all relevant beliefs?
- **Precision:** Does it avoid returning irrelevant beliefs?
- **Order correctness:** Are results in correct chronological order?
- **Unique value:** Results this method finds that search cannot.

**Expected results:**
- T5, T6, T9: Keyword search returns 0 useful results (no concept of "what changed" or "session replay").
- T3, T4, T10: Keyword search finds the beliefs but cannot show which superseded which or chronological order.
- T1, T7, T8: Keyword search finds some results but with noise (beliefs matching keywords but from wrong time period).
- T2: Keyword search finds HRR beliefs but cannot determine adjacency.

### Implementation

```python
"""Exp: Temporal query tools vs keyword search.

For each test query, run both temporal and keyword approaches against
the production DB. Compare recall, precision, and ordering correctness.
"""
```

The experiment should:
1. Open the production DB read-only.
2. For each query, execute both approaches.
3. For queries with known ground truth (manually curated), measure precision/recall.
4. For queries without ground truth, measure: result count, ordering, and whether keyword search can answer at all.
5. Output a summary table showing which query categories REQUIRE temporal tools.


## 7. Implementation Priority

1. **Migration 1** (created_at index): trivial, zero risk, immediate benefit.
2. **timeline() MCP tool + CLI**: highest-value tool. Covers RANGE + SESSION.
3. **evolution() MCP tool + CLI**: second-highest. Only way to answer "how did X evolve?"
4. **diff() MCP tool + CLI**: third. "What changed since last time?" is a common session-start question.
5. **Migration 2** (session_id on beliefs): required for timeline(session_id=...) to work properly.
6. **Validation experiment**: run after tools are built to confirm the hypothesis.

Estimated implementation: ~200 lines for store.py methods, ~150 lines for server.py tools, ~100 lines for CLI commands, ~50 lines for migrations. Total: ~500 lines.


## 8. What We Are NOT Building

- **TEMPORAL_NEXT edge creation in ingest**: Exp59 showed timestamps are sufficient for adjacency in nearly all cases. The structural guarantee is not worth the write amplification (one extra edge insert per belief).
- **CITES traversal tool**: CITES edges are sparse (only from scanner/onboard). Until the ingest pipeline detects citations, a dedicated tool would mostly return empty results.
- **Point-in-time snapshot tool**: "What beliefs were active at time T?" is just `timeline(end=T)` with an implicit `valid_to IS NULL OR valid_to > T` filter. Not worth a separate tool.
- **Cross-session comparison tool**: "What changed between session 5 and session 10?" is `diff(since=session5.started_at, until=session10.completed_at)`. Covered by diff().
