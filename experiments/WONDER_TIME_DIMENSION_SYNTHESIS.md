# Wonder Synthesis: Time as a Structural Dimension

**Date:** 2026-04-12
**Query:** Exhaustive exploration of Exp 19's recommendation -- time as a first-class graph dimension
**Research agents:** 6 parallel (prior art, data analysis, belief chains, query surface, velocity/sessions, evolution/snapshots)

---

## Executive Summary

Your instinct is correct. The time dimension has been researched wide but not deep. Exp 19 proposed "time as a structural dimension" (Model 3) on 2026-04-09 and was adopted as a design decision, but the implementation trail is thin:

- **What was built:** Content-aware decay scoring, SUPERSEDES edges, commit-level TEMPORAL_NEXT (useless), recency boost
- **What was validated but not built:** Velocity-scaled decay (exp58c), belief-level temporal chains (exp19 design)
- **What was never even designed:** Bitemporal timestamps, episodic layer, temporal query tools, cross-session linking, belief evolution chains, confidence history, turn provenance

The data analysis reveals the situation is worse than expected: **all 31K beliefs have ingestion timestamps, not authoring timestamps. Sessions table has 0 rows. source_id is broken (stores type strings, not identifiers). 70% of corrections are orphaned with no SUPERSEDES link.**

## The Core Problem

The system treats time as a **scoring modifier** (decay function applied to a flat timestamp) but not as a **structural dimension** of the knowledge graph. This means:

1. You can ask "what's relevant now?" (decay-ranked search) but NOT "what was relevant last Tuesday?"
2. You can find a belief but NOT "what was discussed right before it"
3. You can see a correction but NOT the full chain of understanding that led to it
4. You can query a topic but NOT "how did our thinking about this topic evolve?"

---

## What Prior Art Shows

| System | Temporal Innovation | Our Gap |
|---|---|---|
| **Zep/Graphiti** (arxiv 2501.13956) | Bitemporal model (event time + ingestion time), edge validity intervals, automated supersession | We have ingestion time only. No edge validity. |
| **AgentMem** (oxgeneral) | SQLite-native temporal versioning + fact evolution chains | Validates our approach is feasible at scale |
| **DE-SimplE** (TKG research) | Diachronic embeddings: multiply vectors by time-dependent sigmoid | Could extend our HRR with minimal cost |
| **SDRT** (discourse theory) | Temporal-causal edge types: NARRATES, ELABORATES, CAUSES, RESULTS_FROM | We have SUPERSEDES only |
| **Tulving** (cognitive science) | Episodic-to-semantic consolidation pathway | We have no episodic layer at all |
| **ChronoQA** (benchmark) | "What was true at time T?" queries | We cannot do this |

**Key insight from prior art:** The most mature systems (Zep, AgentMem) all separate **event time** (when the fact occurred) from **ingestion time** (when the system learned it). We conflate these entirely. This is the root cause of most temporal blind spots.

---

## What the Data Shows

Analysis of the actual database (31K beliefs, 17K observations, 1.7K edges):

| Signal | Status | Recovery? |
|---|---|---|
| Belief creation time | EXISTS but = ingestion time (64-minute window) | No |
| Session boundaries | MISSING (0 rows in sessions table) | No |
| Turn ordering | MISSING | No |
| Co-occurrence (same source) | PARTIAL (54% of beliefs share an observation) | Yes |
| Correction chains | PARTIAL (30% linked via SUPERSEDES, 70% orphaned) | Partial |
| Source document identity | MISSING (source_id = source_type string) | No |
| TEMPORAL_NEXT edges | ZERO exist | Must build |
| Original authoring time | MISSING | Partial (git dates recoverable) |

**The timestamp problem is fundamental.** 99.6% of consecutive belief pairs have gaps < 10ms because they were bulk-inserted during onboarding. The timestamps encode "order of scanning," not "order of discussion." Any experiment that relies on created_at for temporal reasoning will be testing scan order, not conversational structure.

---

## Proposed Experiments (10 total)

### Foundation Layer (fix the data)

| Exp | Name | What It Tests | Priority | Effort |
|---|---|---|---|---|
| **71** | Belief-level TEMPORAL_NEXT | Does creating temporal chains between beliefs improve adjacency queries? Decision gate: if timestamp collision rate > 50%, pivot to observation-level chains. | P0 | Small |
| **75** | Session velocity measurement | Reconstruct session boundaries from timestamps. Profile velocity. Test velocity-scaled decay vs flat decay. | P0 | Medium |

### Structural Layer (new edge types and queries)

| Exp | Name | What It Tests | Priority | Effort |
|---|---|---|---|---|
| **72** | Thread detection via topic continuity | Can Jaccard similarity on TEMPORAL_NEXT chains detect conversation threads? | P1 | Medium |
| **73** | Temporal co-occurrence signal | Do CO_OCCURRED edges between same-turn beliefs improve vocabulary-gap retrieval? | P1 | Medium |
| **76** | Cross-session topic continuity | Do CROSS_SESSION edges linking the same topic across sessions improve evolution queries? | P1 | Medium |

### Query Layer (temporal retrieval surface)

| Exp | Name | What It Tests | Priority | Effort |
|---|---|---|---|---|
| **74** | Traversal vs filtering integration | Which method wins for each query category (range, topic+time, adjacency+time)? | P2 | Small |
| **79** | Point-in-time snapshots | "What did we know about X at time T?" with temporal window filtering | P1 | Small |

### Evolution Layer (belief lifecycle)

| Exp | Name | What It Tests | Priority | Effort |
|---|---|---|---|---|
| **77** | Belief evolution chains | DEEPENS edges between beliefs that progressively refine understanding (not contradiction) | P2 | Large |
| **78** | Confidence history | Does confidence trajectory (rise-then-fall vs always-low) predict future usefulness? | P2 | Medium |
| **80** | Turn provenance | Does grouping beliefs by conversation turn improve "why did we decide X?" queries? | P2 | Medium |

---

## Proposed MCP Tools (3 new)

| Tool | What It Does | Query Categories Covered |
|---|---|---|
| `timeline(topic, start, end, session_id, limit)` | Time-ordered beliefs with optional FTS5 filter | RANGE, SESSION REPLAY |
| `evolution(belief_id, topic)` | SUPERSEDES chain traversal or topic chronology | EVOLUTION |
| `diff(since, until, session_id)` | ADDED/REMOVED/EVOLVED since a point in time | DIFFERENTIAL |

Key finding: **3 of 10 test queries are impossible with keyword search** (diff, session replay, "what's new since X"). 3 more lose supersession chain information. Only 4 can be approximated by current search.

---

## Schema Changes Required

### Immediate (no data migration)
```sql
CREATE INDEX IF NOT EXISTS idx_beliefs_created_at ON beliefs(created_at);
CREATE INDEX IF NOT EXISTS idx_beliefs_temporal ON beliefs(created_at, valid_to);
```

### Short-term (additive columns)
```sql
ALTER TABLE beliefs ADD COLUMN session_id TEXT;
ALTER TABLE beliefs ADD COLUMN event_time TEXT;  -- bitemporal: when fact occurred
CREATE INDEX IF NOT EXISTS idx_beliefs_session_id ON beliefs(session_id);

ALTER TABLE sessions ADD COLUMN velocity_items_per_hour REAL;
ALTER TABLE sessions ADD COLUMN velocity_tier TEXT;
ALTER TABLE sessions ADD COLUMN topics_json TEXT;
```

### Medium-term (new tables)
```sql
CREATE TABLE confidence_history (...);      -- exp78
CREATE TABLE conversation_turns (...);      -- exp80
```

---

## Implementation Roadmap

### Wave 1: Fix the Foundation (can start now)
1. Add `created_at` index (trivial, immediate query speedup)
2. Add `event_time` column to beliefs (bitemporal -- store original authoring time when available)
3. Fix `source_id` bug (store actual file paths/commit SHAs, not type strings)
4. Populate sessions table (server.py already creates sessions; ensure completion + velocity)
5. Run Exp 75 (velocity measurement on existing data)

### Wave 2: Temporal Query Surface (depends on Wave 1)
6. Implement `timeline()` MCP tool + CLI command
7. Implement `evolution()` MCP tool + CLI command
8. Implement `diff()` MCP tool + CLI command
9. Add `search_at_time()` to store.py (Exp 79)
10. Run Exp 74 (validate temporal queries vs keyword search)

### Wave 3: Temporal Structure (depends on Wave 1-2 validation)
11. Run Exp 71 (belief-level TEMPORAL_NEXT) -- with decision gate
12. Run Exp 73 (co-occurrence edges)
13. Run Exp 72 (thread detection) -- depends on 71
14. Run Exp 76 (cross-session linking) -- depends on 75
15. Wire velocity-scaled decay into scoring.py

### Wave 4: Evolution Layer (depends on Wave 2-3 validation)
16. Run Exp 77 (DEEPENS edge detection)
17. Add confidence_history table (Exp 78)
18. Add conversation_turns table (Exp 80)
19. Diachronic HRR (time-dependent sigmoid on vectors)

---

## Key Design Decisions Emerging

1. **TEMPORAL_NEXT is NOT worth building into ingest** (query surface agent finding). ISO 8601 sub-second timestamps provide sufficient ordering. Only SUPERSEDES chains provide information timestamps alone cannot. This contradicts Exp 19's Model 3 recommendation -- the data shows structural temporal edges are only needed for 2/10 query types.

2. **Session-level decay is NOT recommended** (velocity agent finding). Velocity-scaled belief-level decay handles the signal without risking penalizing good decisions from brainstorm sessions. Session character should be tracked for diagnostics only.

3. **Bitemporal timestamps are the highest-value change** (prior art finding). Separating event_time from ingested_at unlocks temporal windowing immediately and is just one extra column.

4. **The episodic layer is the biggest conceptual gap** (cognitive science finding). Raw conversation turns should be stored as episodes; beliefs extracted from them become semantic memory. The episodic layer is the audit trail that makes "why?" queries answerable.

5. **The source_id bug must be fixed first** (data analysis finding). Without actual source identifiers, no temporal provenance chain can be reconstructed.

---

## What This Changes About Our Understanding

Before this wonder:
> "We have time as a decay modifier. Exp 19 said we should have temporal edges. We haven't built them yet."

After this wonder:
> "We have a deeper problem than missing edges. Our timestamps are ingestion-time only, our sessions are untracked, our source provenance is broken, and 70% of correction chains are orphaned. Before we can model temporal structure, we need to fix the data foundation. The good news: the fixes are incremental (indexes, columns, bug fixes) and the query surface (3 MCP tools) provides immediate value even before structural edges exist."

---

## Source Documents

- [Prior art survey](wonder_time_prior_art.md) -- Zep, Mem0, MemGPT, TKGs, discourse theory, cognitive science
- [Data analysis](wonder_time_data_analysis.md) -- SQL queries against live DB, quantified gaps
- [Belief chain experiments](wonder_time_belief_chains.md) -- Exp 71-74 designs
- [Query surface design](wonder_time_query_surface.md) -- 3 MCP tools, schema changes, validation experiment
- [Velocity & sessions](wonder_time_velocity_sessions.md) -- Exp 75-76, session metadata, velocity-scaled decay
- [Evolution & snapshots](wonder_time_evolution.md) -- Exp 77-80, confidence history, turn provenance
