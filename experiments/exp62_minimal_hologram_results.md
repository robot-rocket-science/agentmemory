# Experiment 62: Minimal Viable Hologram -- Results

**Date:** 2026-04-11
**Input:** Production memory.db (14,895 non-superseded beliefs)
**Method:** Coverage-vs-size sweep, type ablation, composition test
**Rigor tier:** Empirically tested (real data, 5-seed variance measurement)

---

## Summary

**H1 REJECTED.** No hologram size achieves 90% coverage. The full graph (14,895 beliefs) hits 86.1% ceiling. Top-50 achieves only 23%. Top-100 achieves 31%. No knee exists in the coverage curve.

**H2 PARTIALLY CONFIRMED.** Requirement beliefs are the only load-bearing type (removing them drops coverage 11.1pp). Factual, correction, and preference beliefs contribute 0% to coverage when removed individually. But the expected constraint catastrophe (30%+ drop) did not occur because requirements are the important type, not constraints.

**H3 REJECTED.** No knee. Coverage increases log-linearly with k. The curve is smooth, not sigmoidal.

**Root cause:** Global scoring (Thompson sample without a query) produces a ranking that is uncorrelated with query-specific retrieval needs. The scoring pipeline is designed for query-time ranking, not pre-computed global ordering.

---

## Phase 1: Coverage vs. Size

Average across 5 seeds (42, 137, 256, 314, 999):

| k | Macro Coverage | Std | Tokens |
|---|----------------|-----|--------|
| 5 | 4.4% | 3.8% | ~90 |
| 10 | 6.7% | 5.7% | ~195 |
| 20 | 15.0% | 3.8% | ~403 |
| 50 | 22.8% | 9.5% | ~1007 |
| 100 | 31.1% | 7.3% | ~1883 |
| 200 | 37.8% | 7.6% | ~3413 |
| 500 | 49.4% | 6.9% | ~8199 |
| 1000 | 58.9% | 5.7% | ~16163 |
| 2000 | 64.4% | 8.3% | ~31964 |
| 5000 | 73.3% | 4.5% | ~79448 |
| 10000 | 82.8% | 2.7% | ~158985 |
| 14895 | 86.1% | 0.0% | 237,745 |

**Observations:**

1. Variance is high at small k (3.8-9.5%), stabilizes at large k (0-2.7%). Thompson sampling noise dominates small subgraphs.
2. The 86.1% ceiling across ALL seeds at full-graph size means ~14% of ground truth targets are absent from the DB entirely.
3. No inflection point. The curve is log-linear. There is no "natural" hologram size.

---

## Phase 2: Type Ablation

| Removed Type | Count Removed | Coverage After | Delta |
|-------------|---------------|----------------|-------|
| (none -- baseline) | 0 | 86.1% | -- |
| correction | 2,592 | 86.1% | 0.0% |
| factual | 11,364 | 86.1% | 0.0% |
| preference | 158 | 86.1% | 0.0% |
| **requirement** | **781** | **75.0%** | **-11.1%** |

**Analysis:**

Only requirement-type beliefs carry retrievable signal. The other three types contain content that either (a) duplicates what requirements say, or (b) does not match any ground-truth query.

This is partly a ground-truth artifact: the 6 topics test for project-level knowledge (architecture, tools, decisions) which aligns with requirement beliefs. A different ground truth (personal preferences, historical corrections) would likely show corrections as load-bearing.

---

## Phase 3: Locked-Only Baseline

**No locked beliefs exist in the production DB.** The production DB was bulk-ingested from project scanning, which creates beliefs with `locked=False`. Locked beliefs only come from `remember()` and `correct()` MCP tools during live conversation.

This phase is vacuous for this dataset. It becomes meaningful after live usage creates locked beliefs.

---

## Phase 4: Composition

| Set | Count | Macro Coverage |
|-----|-------|----------------|
| First half (older) | 7,447 | 86.1% |
| Second half (newer) | 7,448 | 58.3% |
| Merged | 14,895 | 86.1% |

**Composition works.** Merged coverage equals the maximum of the two halves. No destructive interference.

The asymmetry is informative: the first half (older beliefs from bulk ingestion) contains the project-level knowledge that matches the ground truth. The second half (more recent ingestion) adds factual beliefs that don't help with these specific queries.

---

## Implications

### What went wrong with the hologram hypothesis

The hypothesis assumed a global relevance ranking would correlate with query-specific retrieval. It does not. The scoring pipeline's Thompson sampling, decay, and lock boost are designed to rank beliefs *for a specific query*, not globally. Without a query, the ranking is dominated by:
- Bayesian confidence (all beliefs have alpha=0.9, beta=0.1, so confidence is uniform)
- Type-based decay (corrections and requirements never decay, so they rank high -- but that's only 3,373 of 14,895 beliefs)
- Thompson sampling noise (the dominant signal at uniform confidence)

### What this means for profiles and compilation

The hologram-as-subgraph approach (freeze a ranked subset) does not work for retrieval. But the underlying question is still valid. Two alternative approaches:

1. **Type-filtered hologram.** Instead of top-k by score, select ALL beliefs of load-bearing types (requirement, correction). At 3,373 beliefs, this is 22% of the graph. Test whether this achieves higher coverage than score-based selection.

2. **Query-aware compilation (Exp 64).** Don't pre-compute a static hologram. Instead, compile context at session start using project-level queries ("what are the requirements?", "what are the constraints?", "what was corrected?"). This is query-time retrieval, not global ranking -- it uses the pipeline correctly.

3. **Profile = type weights, not belief subset.** Instead of freezing beliefs, a profile could specify type preferences (e.g., "strict reviewer" boosts requirement and correction beliefs, "exploratory researcher" boosts factual and causal). The beliefs stay in the full graph; the profile shapes how scoring weights them.

### Decision: proceed with Exp 64, adjust Exp 63

- Exp 63 (profiles) should test type-weight profiles, not frozen subgraphs.
- Exp 64 (compilation) should use query-aware retrieval, not global ranking.
- Exp 65 (diffing) is still viable -- diffing the full graph over time is meaningful even without a subgraph hologram.

---

## Limitations

- Ground truth covers 6 topics with 13 needed substrings. Ceiling is 86.1%, meaning ~2 targets are absent from the DB. A larger or recalibrated ground truth would give more resolution.
- The production DB has uniform confidence (0.9) because all beliefs were bulk-ingested with the same priors. A DB with live usage history (varied confidence from Bayesian updates) would produce different global rankings.
- No locked beliefs exist. This experiment does not test the "locked beliefs as core identity" hypothesis.

---

## Files

- `exp62_minimal_hologram.py` -- experiment code
- `exp62_results.json` -- raw data
- `exp62_minimal_hologram_plan.md` -- original design
- `exp62_minimal_hologram_results.md` -- this file
