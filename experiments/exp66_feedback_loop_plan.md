# Experiment 66: Feedback Loop Validation

**Date:** 2026-04-11
**Validates:** Exp 62-65 Bayesian feedback assumptions
**Rigor tier:** Empirically tested (live DB, simulated sessions)

---

## Research Question

Does the Bayesian feedback loop (alpha/beta updates via `record_test_result`)
improve retrieval quality over simulated sessions? Specifically, does MRR@10
increase when beliefs are rewarded for relevance and penalized for irrelevance
across 50 retrieval rounds?

## Hypothesis

**H1:** MRR@10 improves by >= 10% from round 1 to round 50 when the feedback
loop updates alpha/beta parameters on each retrieval cycle.

## Null Hypothesis

MRR@10 does not improve (or degrades) because Thompson sampling noise and FTS5
BM25 ranking dominate the score, making alpha/beta shifts negligible.

## Method

1. Copy the live DB to a temp location (read-write copy, original untouched).
2. Define 13 ground-truth queries with known-relevant belief IDs (topic queries
   covering locked beliefs, FTS5 retrieval, correction detection, type priors,
   HRR vocabulary bridge, scoring pipeline, recency boost, token budgeting,
   session tracking, edge graph, observation pipeline, compression, and
   classification).
3. For each of 50 rounds:
   a. Run `retrieve()` for each query with `top_k=30`.
   b. For each retrieved belief: if `belief.id` in ground truth for that query,
      call `record_test_result` with outcome="used"; else outcome="ignored".
   c. (Confidence updates happen inside `record_test_result`.)
4. After each round, measure MRR@10 across all 13 queries.
5. Compare round 1 MRR vs round 50 MRR.

## Metrics

| Metric | Formula | Target |
|--------|---------|--------|
| MRR@10 | mean(1/rank of first relevant hit, capped at 10) | Improves >= 10% |
| Per-round MRR | MRR@10 after each of 50 rounds | Monotonically trending up |

## Success Criteria

MRR@10 at round 50 is >= 10% higher than MRR@10 at round 1.

## Output

- `exp66_results.json`: per-round MRR array, initial/final comparison, delta.

## Files

- `exp66_feedback_loop.py`
- `exp66_results.json`
