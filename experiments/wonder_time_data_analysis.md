# Temporal Signal Analysis: What Exists and What's Lost

Analysis of `~/.agentmemory/memory.db.bak-pre-gitdates` (30MB, the most complete backup).

## Database Counts

| Table | Rows |
|-------|------|
| beliefs | 30,874 |
| observations | 16,637 |
| evidence | 30,875 |
| edges | 1,702 |
| sessions | 0 |
| checkpoints | 0 |
| audit_log | 0 |

## Q1: What timestamps exist on beliefs?

**Schema fields:** `created_at`, `updated_at`, `valid_from`, `valid_to`

**Time range:** All 30,874 beliefs were created on a single date: 2026-04-11, within a
64-minute window (06:45 - 07:49 UTC). Two bursts:

| Hour | Beliefs |
|------|---------|
| 06:45 (1 minute) | 15,009 |
| 07:48-07:49 (2 minutes) | 15,865 |

**Timestamp granularity:** Microsecond-precision ISO 8601 strings. However:
- 30,741 of 30,873 consecutive pairs (99.6%) have gaps < 10ms
- 30,872 pairs (99.997%) have gaps < 100ms
- Only 1 gap > 1 second (the 63-minute gap between the two bursts)

```sql
SELECT strftime("%Y-%m-%d %H:%M", created_at) as m, COUNT(*) as c
FROM beliefs GROUP BY m ORDER BY c DESC LIMIT 5;
-- 2026-04-11 06:45: 15009
-- 2026-04-11 07:49: 12110
-- 2026-04-11 07:48: 3755
```

**Conclusion:** All beliefs were created by bulk onboarding, not live conversation. The
timestamps reflect ingestion time, NOT when the original content was authored.

## Q2: TEMPORAL_NEXT edges

**Zero.** No TEMPORAL_NEXT edges exist. All 1,702 edges are SUPERSEDES type.

```sql
SELECT edge_type, COUNT(*) FROM edges GROUP BY edge_type;
-- SUPERSEDES: 1702
```

There is no temporal adjacency graph at all.

## Q3: Session IDs and conversation ordering

**sessions table: 0 rows.** The table exists but was never populated.

**observations.session_id: all NULL.** Every single observation (16,637) has
`session_id = NULL`.

```sql
SELECT COUNT(*) FROM observations WHERE session_id IS NOT NULL AND session_id != '';
-- 0
```

**Conclusion:** There is no way to reconstruct conversation order, session boundaries,
or turn sequence from the current data. The session infrastructure exists in the schema
but was never used during onboarding.

## Q4: Distribution -- bursty or spread?

**100% bursty.** Two massive onboarding dumps:

- Burst 1 (06:45): ~15,009 beliefs in <5 seconds
- 63-minute gap (no activity)
- Burst 2 (07:48-07:49): ~15,865 beliefs in <2 minutes

Observations show the same pattern:
- 14,444 observations created in the 06:45 minute
- 1,789 in the 07:49 minute

The smaller backup (memory.db.bak-20260410, 14MB) shows the same: 14,829 of 14,830
beliefs created in a single minute (04:21), with 1 belief at 01:04.

**No live-conversation beliefs exist in either backup.**

## Q5: Can you reconstruct co-occurring beliefs from the same turn?

**Partially, through the evidence table.** Each belief links to exactly one observation
via the evidence table. Observations that produced multiple beliefs represent "same turn"
co-occurrence:

| Beliefs per observation | Observation count | Total beliefs |
|------------------------|-------------------|---------------|
| 1 | 14,120 | 14,120 |
| 2-10 | 1,946 | ~8,100 |
| 11-50 | ~240 | ~5,500 |
| 51-100 | ~15 | ~1,100 |
| 100+ | ~20 | ~2,000 |

**2,255 observations produced multiple beliefs (16,755 beliefs total -- 54% of all beliefs).**

The largest single observation produced 356 beliefs. The top producers are all
`<task-notification>` XML chunks (sub-agent results from onboarding).

**However:** This co-occurrence is "same source document" not "same conversation turn."
Since all data came from bulk onboarding of files and git history, these don't represent
conversational temporal co-occurrence.

## Q6: Gap between consecutive beliefs in same session

Since session_id is always NULL, this reduces to the global gap analysis:

| Gap range | Count | Percentage |
|-----------|-------|------------|
| < 10ms | 30,741 | 99.6% |
| 10ms - 100ms | 131 | 0.4% |
| 100ms - 1s | 0 | 0% |
| > 1 minute | 1 | 0.003% |

The 10ms gaps are just processing time between sequential inserts. No natural
conversation cadence exists.

## Q7: Observation temporal ordering and source info

**source_type distribution:**

| source_type | Count |
|-------------|-------|
| document | 13,652 |
| assistant | 1,688 |
| code | 760 |
| user | 504 |
| git | 28 |
| directive | 5 |

**source_id:** Contains the same value as source_type (bug: source_id = source_type
string instead of a unique identifier).

```sql
SELECT DISTINCT source_id FROM observations WHERE source_id != '';
-- git, document, code, directive, user, assistant
```

**No file paths, commit SHAs, conversation IDs, or turn numbers** are stored in
source_id. The field is misused as a duplicate of source_type.

## Temporal Signal Being LOST

### 1. Conversation turn co-occurrence (LOST)
- 2,255 observations produced multiple beliefs. When retrieved individually, these
  beliefs lose their "born together" context.
- A user correction and the fact it corrects often share the same observation but have
  no explicit temporal link.

### 2. Causal correction chains (PARTIALLY PRESERVED)
- 5,605 correction beliefs exist, but only 1,702 have SUPERSEDES edges.
- **3,903 corrections (70%) have no link to what they correct.**
- Of the 1,702 SUPERSEDES edges, chain depths are:
  - Depth 1: 1,201 (simple A supersedes B)
  - Depth 2: 332
  - Depth 3: 96
  - Depth 4-7: 42
- Max chain depth: 7 (a belief corrected 7 times).

### 3. Session boundaries (COMPLETELY LOST)
- Sessions table: 0 rows
- session_id on observations: always NULL
- No way to distinguish "this was session 1" from "this was session 14"

### 4. Source document identity (LOST)
- source_id contains type strings ("document", "user") instead of actual identifiers
- No file paths, git SHAs, or conversation turn IDs
- Cannot trace a belief back to its original source document

### 5. Original authoring time (LOST)
- created_at reflects bulk ingestion time (all within minutes), not when the content
  was originally written
- Git commit dates, file modification times, conversation timestamps -- all discarded
- valid_from is never set; valid_to is only set on superseded beliefs

### 6. Belief ordering within a turn (AMBIGUOUS)
- Microsecond timestamps provide some ordering within the same second
- But 3,298 observations share the same second (06:45:35), making ordering unreliable

## Summary Table

| Signal | Status | Recovery possible? |
|--------|--------|--------------------|
| Belief creation time | EXISTS but = ingestion time, not authoring time | No (original time not stored) |
| Session boundaries | MISSING (0 sessions, all session_id NULL) | No |
| Turn ordering | MISSING | No |
| Co-occurrence (same source) | PARTIAL via evidence table | Yes (join through evidence.observation_id) |
| Correction chains | PARTIAL (30% linked, 70% orphaned) | Partial (could re-match by content similarity) |
| Source document identity | MISSING (source_id = source_type) | No |
| TEMPORAL_NEXT edges | ZERO exist | No (would need to rebuild) |
| Original authoring time | MISSING | Partial (git dates recoverable from repo) |

## SQL Queries Used

All queries run against: `~/.agentmemory/memory.db.bak-pre-gitdates`

```sql
-- Schema inspection
PRAGMA table_info(beliefs);
PRAGMA table_info(observations);
PRAGMA table_info(edges);

-- Time range
SELECT MIN(created_at), MAX(created_at) FROM beliefs;

-- Distribution by minute
SELECT strftime("%Y-%m-%d %H:%M", created_at) as m, COUNT(*) FROM beliefs GROUP BY m;

-- Edge types
SELECT edge_type, COUNT(*) FROM edges GROUP BY edge_type;

-- Session usage
SELECT COUNT(*) FROM observations WHERE session_id IS NOT NULL AND session_id != '';

-- Co-occurrence
SELECT observation_id, COUNT(*) as c FROM evidence GROUP BY observation_id HAVING c > 1;

-- Correction orphans
SELECT COUNT(*) FROM beliefs WHERE belief_type='correction';
SELECT COUNT(*) FROM edges WHERE edge_type='SUPERSEDES';

-- Source ID bug
SELECT DISTINCT source_id FROM observations WHERE source_id != '';
```
