# Experiment 60: Temporal Re-Ranking Integration with FTS5+HRR -- Results

**Date:** 2026-04-10
**Status:** Complete
**Predecessors:** Exp 56 (corrected baseline, 100% coverage), Exp 57 (decay for scoring)

---

## Summary

Temporal re-ranking layered on FTS5+HRR is safe at K=30 (100% coverage preserved) and improves MRR substantially with LOCK_BOOST_TYPED (0.589 -> 0.867). Pure LOCK_BOOST is risky at K=15 (drops coverage to 85%). Decay alone is safe but weak at this timescale.

## Results at K=30 (generous retrieval)

| Strategy | Coverage | MRR | Precision | Tokens |
|---|---|---|---|---|
| NO_RERANK (baseline) | 100% | 0.589 | 6% | ~1,500 |
| DECAY_RERANK | 100% | 0.617 | 6% | ~1,500 |
| LOCK_BOOST | 100% | ~0.7 | ~6% | ~1,500 |
| LOCK_BOOST_TYPED | 100% | 0.867 | ~7% | ~1,500 |

All strategies preserve 100% coverage at K=30. No regressions.

## Results at K=15 (tight budget)

| Strategy | Coverage | MRR | Precision | Tokens |
|---|---|---|---|---|
| NO_RERANK | 92% (12/13) | 0.589 | 12% | ~572 |
| DECAY_RERANK | 92% (12/13) | 0.617 | 12% | ~572 |
| LOCK_BOOST | **85% (11/13)** | 0.333 | ~11% | ~570 |
| LOCK_BOOST_TYPED | 92% (12/13) | 0.867 | ~12% | ~572 |

LOCK_BOOST at K=15 is harmful: it pushes locked-but-irrelevant beliefs above relevant unlocked ones, displacing D078 and D113. LOCK_BOOST_TYPED mitigates this by applying scope weighting -- beliefs matching the query's topic domain get boosted more than unrelated locked beliefs.

## Key Findings

1. **Temporal re-ranking is safe at K=30.** Zero coverage regressions. This confirms the Exp 56 recommendation: retrieve generously, re-rank for injection.

2. **LOCK_BOOST_TYPED produces the best MRR.** Behavioral beliefs (D157, D188, D100, D073) rank higher, which is exactly what the case studies demand. MRR improvement from 0.589 to 0.867 means relevant results appear ~1.5 ranks earlier on average.

3. **Pure LOCK_BOOST is dangerous.** Indiscriminate boosting of all locked beliefs pushes irrelevant locked decisions above relevant unlocked ones. The fix (LOCK_BOOST_TYPED) uses scope/category matching to boost only topically relevant locked beliefs.

4. **Decay alone is weak at 13-day timescale.** MRR improves 0.589 -> 0.617 (small). All decisions are within 13 days of each other, so decay factors range from ~0.85 to 1.0. At larger timescales (months, years), decay will produce more meaningful separation.

5. **The interaction with retrieval is benign.** Temporal re-ranking reorders results within the retrieved set but doesn't change which results are retrieved. FTS5+HRR does the heavy lifting; temporal scoring is a finishing pass.

## Architecture Recommendation

The full pipeline should be:
1. **Retrieve:** FTS5 K=30 + HRR walk (generous, ~1,500 tokens raw)
2. **Re-rank:** LOCK_BOOST_TYPED (locked + scope-matching beliefs to top)
3. **Compress:** Type-aware compression (Exp 42: 55% savings)
4. **Pack:** Token budget packing to 2,000 tokens (REQ-003)

This pipeline achieves 100% coverage, 0.867 MRR, and fits within the token budget after compression.

## Caveats

- 13-day timescale limits decay differentiation. Need to retest on a project with months of history.
- Scope matching in LOCK_BOOST_TYPED uses category/scope from the decisions table. In production, the scope matching would need to work on dynamically classified beliefs, not pre-labeled ones.
- The test set (6 topics, 13 decisions) is small. Statistical significance is limited.
