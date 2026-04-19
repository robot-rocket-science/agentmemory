# Research: Time as a Graph Dimension

**Date:** 2026-04-09
**Task:** #40

## Current State of Temporal Data

From the project-a timeline (1,790 events):
- 1,743 events have timestamps (97%)
- Temporal span: 16 days (Mar 24 - Apr 9, 2026)
- 213 active hours
- 221 DECIDED_IN edges (decision -> milestone, temporal context)
- 0 SUPERSEDES edges (no supersession tracked in the spike DB)
- 0 TEMPORAL_NEXT edges (no sequence tracking)
- 140/173 decisions have milestone context (81%)

**What's missing:** explicit temporal ordering between events, supersession chains, and decay metadata.

## Three Models for Time in the Graph

### Model 1: Time as Edge Metadata

Every edge gets a timestamp. Traversal can filter by recency.

```
D097 --CITES(2026-03-27)--> D103
D174 --CITES(2026-04-01)--> D097
```

**Pros:** Simple. No new structure. Queries like "what cited D097 in the last week?" are straightforward.
**Cons:** Time is attached to relationships, not to the nodes themselves. A node's "age" is ambiguous -- created_at? last_referenced_at? last_modified_at?

### Model 2: Time as a Node Property with Decay Function

Each node has temporal properties that affect its retrieval score:

```
Node D097:
  created_at: 2026-03-27
  last_retrieved: 2026-04-09
  last_cited: 2026-04-05
  retrieval_count: 47
  decay_score: f(time_since_last_use, content_type)
```

Decay function is content-aware:
- **Facts** (capital = $5K): no decay. True until explicitly superseded.
- **Activities** (debugging DuckDB crash): fast decay. Irrelevant after resolution.
- **Procedures** (dispatch gate protocol): slow decay. Relevant until process changes.
- **Evidence** (backtest showed 2/14 profitable years): moderate decay. Stale as new data arrives.

From our sentence type distribution (Exp 16):
- Constraints (11%): no decay
- Evidence (29%): moderate decay
- Context (49%): fast decay
- Rationale (3%): slow decay
- Implementation (4%): moderate decay (code changes)
- Supersession (4%): no decay (it's a pointer, not content)

**Pros:** Content-aware decay is smarter than uniform decay. Constraints persist, activities fade.
**Cons:** Decay function needs tuning. What's the right half-life for evidence? How do we validate it?

### Model 3: Time as a Structural Dimension (Recommended)

Time is not metadata on nodes -- it's a dimension of the graph itself. Events accumulate along the time axis. The graph is a directed acyclic graph where one edge type is TEMPORAL_NEXT.

```
Session 1 (Mar 27):
  D089 --TEMPORAL_NEXT--> D097 --TEMPORAL_NEXT--> D099

Session 2 (Mar 30):
  D137 --TEMPORAL_NEXT--> D157

Cross-session:
  D089 --SUPERSEDES(never, still active)--> (nothing)
  D099 --SUPERSEDES(2026-04-06)--> D209
```

The time dimension enables:
- **"What happened after X?"** -- follow TEMPORAL_NEXT from X
- **"What was the latest decision about topic Y?"** -- find all Y-related nodes, sort by position on time axis
- **"What's changed since last session?"** -- find all nodes created after session start timestamp
- **"What's superseded?"** -- follow SUPERSEDES edges, skip old versions

Git commits are natural TEMPORAL_NEXT chains. Each commit links to the next. Decision sequences within a milestone are also temporal chains. Cross-cutting: decisions from different milestones can share a TEMPORAL_NEXT edge if they happened consecutively.

**Pros:** Time is queryable as structure, not just filterable as metadata. "Show me the evolution of our sizing strategy" becomes a graph traversal.
**Cons:** More edges (every event links to its successor). O(n) TEMPORAL_NEXT edges for n events.

## Recommendation: Model 3 with Model 2 Decay

Use TEMPORAL_NEXT edges for structural time (enables temporal queries and traversal), plus content-aware decay scores for retrieval ranking (ensures stale context fades while facts persist).

The decay score feeds into the Thompson sampling retrieval ranking:
```
score = Beta_sample * relevance * decay_factor
```

Where `decay_factor`:
- = 1.0 for constraints and locked beliefs (no decay)
- = exp(-lambda * days_since_last_use) for activities and context
- lambda depends on content type (fast for activities, slow for procedures)

## Connection to Granular Decomposition (Exp 16)

Sentence-level nodes make temporal decay more precise. In D073 (calls/puts equal citizens, 11 sentences):
- Sentence [0] (the core rule): NO decay -- it's a locked constraint
- Sentence [6] (the user override context from 2026-03-26): MODERATE decay -- the context fades but the rule persists
- Sentence [4] (the recurring flip-flop pattern): FAST decay -- historical context, not current

With whole-decision nodes, D073 either decays entirely or not at all. With sentence nodes, each sentence decays independently based on its role.

## Connection to Scaling Problem (Exp 15)

Temporal decay partially addresses the scaling problem. At 10K beliefs:
- Without decay: all 10K compete equally for retrieval slots
- With decay: stale beliefs have lower scores, effectively reducing the active set
- If 70% of beliefs have decayed significantly, the effective pool is ~3K -- within the range where Thompson sampling works (Exp 15 showed good performance at 1K)

This isn't a complete solution (new beliefs still need testing), but it reduces the effective scale.

## Open Questions

1. **What's the right decay half-life for each content type?** This needs empirical calibration against real usage patterns.
2. **Should TEMPORAL_NEXT edges span across projects?** If the user works on project A then project B, is there a temporal link?
3. **How does git history integrate?** Commits are dense (552 in 16 days). Do all commits become TEMPORAL_NEXT-linked nodes, or only signal commits (259 with D###/M### references)?
4. **Does temporal decay interact with the Bayesian confidence?** A belief with high confidence but old age -- should it decay? Our locked beliefs (REQ-020) say no for corrections. But what about agent-inferred beliefs that were confident but stale?
