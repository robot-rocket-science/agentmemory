# Experiment 68: Spread Type Priors

**Date:** 2026-04-11
**Validates:** Exp 62-65 Thompson sampling differentiation
**Rigor tier:** Empirically tested (live DB, before/after comparison)

---

## Research Question

Do differentiated Bayesian priors (alpha/beta_param per belief type) make
Thompson sampling scoring meaningful? Currently most beliefs start at the
Jeffreys prior (0.5, 0.5). If requirements start at (9.0, 0.5) and assumptions
at (2.0, 1.0), does score variance increase and do high-value types rank higher?

## Hypothesis

**H1:** Score variance across belief types increases when priors are spread,
AND MRR@10 does not decrease compared to baseline uniform priors.

**H2:** Requirements and corrections rank higher than factual beliefs for the
same query when priors are spread.

## Null Hypothesis

Spreading priors has no measurable effect on MRR because FTS5 BM25 ranking
and lock_boost_typed already dominate the final score.

## Method

1. Copy live DB to temp.
2. Define new priors per type:
   - REQUIREMENT: alpha=9.0, beta_param=0.5
   - CORRECTION: alpha=9.0, beta_param=0.5
   - PREFERENCE: alpha=7.0, beta_param=1.0
   - FACT: alpha=3.0, beta_param=1.0
   - ASSUMPTION (causal, relational, procedural): alpha=2.0, beta_param=1.0
3. Measure baseline score distribution and MRR@10 on original DB copy.
4. Apply priors: UPDATE beliefs SET alpha=X, beta_param=Y WHERE belief_type=T.
5. Re-measure score distribution and MRR@10 on updated DB copy.
6. Compare: (a) score variance across types, (b) MRR@10, (c) rank of
   requirements/corrections vs factual beliefs.

## Metrics

| Metric | Target |
|--------|--------|
| Score variance (std of scores per type) | Increases |
| MRR@10 | Does not decrease |
| Rank of requirement/correction vs factual | Higher (lower rank number) |

## Success Criteria

Score variance increases AND MRR does not decrease.

## Output

- `exp68_results.json`: baseline vs spread score stats, MRR comparison, rank analysis.

## Files

- `exp68_spread_type_priors.py`
- `exp68_results.json`
