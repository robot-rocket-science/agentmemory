# Experiment 70: FTS5 Top-K Scaling

**Date:** 2026-04-11
**Validates:** Exp 62-65 retrieval budget assumptions
**Rigor tier:** Empirically tested (live DB, read-only)

---

## Research Question

Does increasing FTS5 top_k from the default 30 to 50, 75, or 100 improve
retrieval coverage? Is there a point of diminishing returns where additional
candidates do not improve coverage but consume more tokens and latency?

## Hypothesis

**H1:** Coverage improves at top_k=50 compared to top_k=30.

**H2:** There is a diminishing-returns knee beyond which more candidates add
tokens but not coverage.

**H3:** top_k=50 stays within the default 2000-token budget.

## Null Hypothesis

top_k=30 already captures all relevant beliefs (coverage is 100%), so
increasing top_k only adds noise and latency.

## Method

1. Use live DB directly (read-only queries only, no writes).
2. Define 13 ground-truth queries (same topics as exp66).
3. For each top_k in [30, 50, 75, 100]:
   a. Run retrieve() with that top_k value.
   b. Measure: coverage, MRR@10, total_tokens, latency (time.perf_counter).
4. Compute marginal coverage gain per additional candidate.
5. Identify diminishing-returns knee.

## Metrics

| top_k | Coverage | MRR@10 | Tokens | Latency (ms) |
|-------|----------|--------|--------|---------------|
| 30 | ? | ? | ? | ? |
| 50 | ? | ? | ? | ? |
| 75 | ? | ? | ? | ? |
| 100 | ? | ? | ? | ? |

## Success Criteria

Coverage improves at top_k=50 without exceeding the 2000-token budget.

## Output

- `exp70_results.json`: per-top_k metrics, diminishing returns analysis.

## Files

- `exp70_fts5_topk_scaling.py`
- `exp70_results.json`
