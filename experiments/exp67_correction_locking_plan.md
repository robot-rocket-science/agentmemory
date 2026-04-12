# Experiment 67: Correction Locking Impact

**Date:** 2026-04-11
**Validates:** Exp 62-65 locked belief retrieval advantage
**Rigor tier:** Empirically tested (live DB, before/after comparison)

---

## Research Question

What happens to retrieval quality when all unlocked corrections get locked?
Corrections are high-value beliefs (type weight 2.0, source weight 1.5 for
user_corrected). Locking them should increase their scoring via lock_boost_typed.

## Hypothesis

**H1:** Locking all corrections improves MRR@10 or coverage on ground-truth
queries, because lock_boost_typed gives a 2x multiplier to locked beliefs that
match query terms.

## Null Hypothesis

Locking corrections has negligible impact because most corrections are already
highly ranked by type weight and FTS5 BM25 relevance.

## Method

1. Copy the live DB to temp.
2. Count unlocked corrections:
   `SELECT COUNT(*) FROM beliefs WHERE belief_type='correction' AND locked=0`
3. Define ground-truth queries (same 13 topics as exp66).
4. Measure baseline MRR@10 and coverage with current state.
5. Lock all corrections:
   `UPDATE beliefs SET locked=1 WHERE belief_type='correction' AND locked=0`
6. Re-measure MRR@10 and coverage.
7. Count how many corrections now appear in top-10 that were absent before.

## Metrics

| Metric | Before | After | Target |
|--------|--------|-------|--------|
| MRR@10 | baseline | post-lock | Improves or stays same |
| Coverage | baseline | post-lock | Improves or stays same |
| New top-10 corrections | 0 | N | N > 0 indicates lock boost works |

## Success Criteria

Coverage improves or MRR improves after locking corrections.

## Output

- `exp67_results.json`: before/after metrics, count of newly surfaced corrections.

## Files

- `exp67_correction_locking.py`
- `exp67_results.json`
