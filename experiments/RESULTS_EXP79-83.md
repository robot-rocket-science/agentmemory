# Experiments 79-83: Statements vs Beliefs -- Empirical Validation

**Branch:** wonder/statements-vs-beliefs
**Date:** 2026-04-12

## Summary

Five experiments validating the statement/belief ontological distinction proposed in WONDER_STATEMENTS_VS_BELIEFS.md.

---

## Exp 79: Ontological Audit

**Question:** What fraction of stored "beliefs" are actually statements (raw propositions) vs agent-view items (meta-cognitive)?

**Result:** **97.6% are statements.** Only 2.3% are agent-view (meta-cognitive about the system itself).

| belief_type | STATEMENT | AGENT_VIEW |
|-------------|-----------|------------|
| factual | 97.8% | 2.2% |
| correction | 96.4% | 3.4% |
| requirement | 95.9% | 3.6% |
| preference | 99.5% | 0.5% |

**Finding:** The hypothesis holds overwhelmingly. Nearly every stored item is a proposition about the project, not the agent's stance toward a proposition.

---

## Exp 80: Consistency Graph Analysis

**Question:** What does the edge graph look like? Are there contradicting clusters?

**Result:** The graph is **supersession-only**.

- 2,550 edges total -- **all SUPERSEDES**
- Zero CONTRADICTS edges, zero SUPPORTS edges
- 80% of statements are orphans (no edges at all)
- 1,039 connected components, all consistent (trivially -- no contradiction edges exist)
- Largest supersession chain: 41 nodes

**Finding:** The graph cannot support "maximal consistent subgraph" analysis because CONTRADICTS and SUPPORTS edges are never created by the current pipeline. This is a gap: the extraction/ingest pipeline should be creating these edge types.

---

## Exp 81: Belief Snapshot Prototype

**Question:** Can we reconstruct B(t) -- the agent's "belief state" at a past moment?

**Result:** **Yes.** Point-in-time snapshots work:

| Snapshot | Statements | Locked | Superseded (excluded) | Avg Conf |
|----------|-----------|--------|----------------------|----------|
| T1: End Day 1 | 30 | 22 | 0 | 0.905 |
| T2: Mid Day 2 | 14,863 | 1,707 | 1,204 | 0.898 |
| T3: Current | 16,791 | 1,146 | 2,559 | 0.878 |

Topic clustering produces meaningful groups ("plan trace phase", "memory solution store", "thompson sampling jeffreys", "holographic reduced representations").

**Finding:** The infrastructure for temporal belief snapshots exists. Supersession filtering correctly excludes outdated statements. This validates the proposed `get_beliefs_at(session)` API.

---

## Exp 82: Credal State Analysis

**Question:** What does the agent's uncertainty profile look like?

**Result:** **76.5% of statements have never been tested** (still at type prior).

- 84.1% of confidence values in the 90-100% band
- 80% have low uncertainty (Beta variance 0.005-0.01)
- Highest uncertainty: factual items at alpha=2.0, beta=1.0 (variance=0.0556)
- Detected type priors: all types at alpha=9.0, beta=1.0 (conf=0.900)

**Finding:** The credal state is dominated by untested priors. The agent's "beliefs" about 12,848 statements are type-based defaults, not empirically validated credences. This validates the theoretical concern: calling these "beliefs" is misleading because there is no agent stance -- just a prior that was never updated.

---

## Exp 83: Belief Divergence Over Time

**Question:** How does the belief state change across time?

**Result:** **Predominantly additive** (revision ratio = 0.060).

- Bulk onboard at T5->T6 added 14,840 statements in one burst (Jaccard dropped to 0.002)
- T7->T8 shows 1,038 supersessions (active revision, 6% of additions)
- Only 5 statements survived from T0 to T8 (Jaccard = 0.0003)
- JSD range: [0.0001, 0.0707], mean 0.020

| Interval | Added | Removed | Type |
|----------|-------|---------|------|
| Pre-onboard -> Onboard start | 5 | 0 | additive |
| +8h -> Midday | 14,840 | 29 | mixed |
| End Day 2 -> Current | 2,933 | 1,038 | mixed |

**Finding:** The system mostly accumulates statements with light revision. The bulk onboard dominates the timeline. True "belief revision" (supersession) is happening but at only 6% of the addition rate.

---

## Cross-Experiment Conclusions

1. **The rename is justified.** 97.6% of stored items are propositions, not propositional attitudes.

2. **The graph is underdeveloped.** Only SUPERSEDES edges exist. CONTRADICTS and SUPPORTS edges would enable the consistency analysis needed for true belief extraction.

3. **Temporal snapshots are feasible.** The data supports point-in-time reconstruction via created_at/valid_to filtering.

4. **The credal state is shallow.** 76.5% of items sit at their type prior, never tested. The agent doesn't really "believe" these -- it just has them at default confidence.

5. **Growth is additive, not revisionary.** The system accumulates more than it revises, suggesting the "belief revision" layer (AGM contraction/revision) is underutilized.

## Proposed Next Steps

- Create CONTRADICTS and SUPPORTS edges during ingest (requires LLM or embedding similarity)
- Implement `synthesize_beliefs(timestamp)` as a proper store method
- Build a "credal gap" metric: fraction of high-confidence statements with zero feedback
- Test whether belief snapshots improve session-start injection quality
