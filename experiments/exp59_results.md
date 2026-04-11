# Experiment 59: Temporal Traversal Utility -- Results

**Date:** 2026-04-10
**Status:** Complete
**Predecessor:** Exp 57 (separate scoring from traversal)

---

## Summary

TEMPORAL_NEXT edges are strictly required for 2/10 queries (adjacency: "what was decided immediately after/before X?"). SUPERSEDES chains are required for 1/10 queries (causal chains). Timestamp filtering handles 7/10 queries without structural edges.

## Results by Query Category

### Range Queries (Q1-Q3): Timestamps sufficient
| Query | Timestamp | TEMPORAL_NEXT | SUPERSEDES | FTS5+Time |
|---|---|---|---|---|
| Q1: Decisions in M005 | 100% | 100% | N/A | Low |
| Q2: Decisions day 3-7 | 100% | 100% | N/A | Low |
| Q3: 5 most recent | 100% | 100% | N/A | Low |

TEMPORAL_NEXT adds zero value for range queries. Timestamps do the job.

### Sequence Queries (Q4-Q6): TEMPORAL_NEXT required for adjacency
| Query | Timestamp | TEMPORAL_NEXT | SUPERSEDES | FTS5+Time |
|---|---|---|---|---|
| Q4: Immediately after D097 | **0%** | **100%** | N/A | 0% |
| Q5: 3 decisions before D157 | **0%** | **100%** | N/A | 0% |
| Q6: Same session as D073 | 100% | 100% | N/A | Low |

Q4 and Q5 require TEMPORAL_NEXT because "immediately before/after" is a structural adjacency concept that timestamp ranges cannot express. Q6 (same session) works with timestamps via milestone grouping.

### Evolution Queries (Q7-Q8): SUPERSEDES adds structural insight
| Query | Timestamp | TEMPORAL_NEXT | SUPERSEDES | FTS5+Time |
|---|---|---|---|---|
| Q7: Dispatch gate evolution | 100%* | 100%* | 100% | Low |
| Q8: Current capital decision | 100%* | 100%* | 100% | Low |

*Timestamp-only achieves completeness when ground truth IDs are known in advance. In the real-world case (no pre-known IDs), SUPERSEDES is the only method that correctly orders an evolution chain. The completeness metric understates SUPERSEDES value because the test provides IDs that the real system wouldn't have.

### Causal Chain Queries (Q9-Q10): Graph structure needed
| Query | Timestamp | TEMPORAL_NEXT | SUPERSEDES | FTS5+Time |
|---|---|---|---|---|
| Q9: Decisions citing D097, made after it | 100% | 100% | N/A | Low |
| Q10: Full correction chain for calls/puts | Partial | Partial | **100%** | Low |

Q10 requires SUPERSEDES to trace the full correction chain. CITES edges + timestamps get partial coverage but miss the supersession ordering.

## Aggregate

| Method | Mean Completeness | Queries Where Strictly Required |
|---|---|---|
| Timestamp-only | 76% | 0 (always available) |
| TEMPORAL_NEXT | ~90% | 2 (Q4, Q5) |
| SUPERSEDES | 100% on applicable queries | 1 (Q10) |
| FTS5+Time | 14% | 0 |

## Implications

1. **TEMPORAL_NEXT edges earn their place** for adjacency queries ("what happened right before/after X?"). These cannot be answered by timestamp filtering alone. But there are only 2/10 such queries -- it's a narrow use case.

2. **SUPERSEDES edges are load-bearing** for evolution and correction chain queries. Even if only 1/10 queries strictly requires them, those queries are high-value (preventing CS-009 retry loops, CS-015 dead re-proposals).

3. **Timestamp filtering handles most temporal needs.** 7/10 queries work with timestamps alone. The structural overhead of TEMPORAL_NEXT is justified only for adjacency queries.

4. **FTS5+Time is weak for temporal queries** (14% average). Keyword search is not a temporal mechanism. It finds relevant beliefs but cannot order or filter them temporally.

## Architecture Recommendation

- **Keep TEMPORAL_NEXT edges** for adjacency queries. Low overhead (O(n) edges for n events), high value for the specific "what happened right before/after?" use case.
- **Keep SUPERSEDES edges** -- they're essential for evolution queries and correction chain tracing.
- **Do not use either for scoring** (confirmed by Exp 57).
- **Timestamp metadata on nodes is the primary temporal mechanism** for most queries. Store created_at, last_retrieved, last_cited on every node.
