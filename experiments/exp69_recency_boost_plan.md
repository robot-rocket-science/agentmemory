# Experiment 69: Recency Boost for New Belief Surfacing

**Date:** 2026-04-11
**Validates:** Exp 63 finding that new beliefs cannot penetrate existing top-k
**Rigor tier:** Empirically tested (live DB, controlled insertion)

---

## Research Question

Does `recency_boost()` help newly inserted beliefs appear in the top-10
retrieval results, overcoming the incumbency advantage of established beliefs
with high alpha values?

## Hypothesis

**H1:** New correction beliefs with current timestamps appear in top-10 results
when recency_boost is applied, but NOT without it.

**H2:** After 48 simulated hours, recency_boost decays to approximately 1.0,
removing the advantage for stale "new" beliefs.

## Null Hypothesis

New beliefs appear in top-10 regardless of recency_boost (FTS5 BM25 relevance
alone is sufficient), or new beliefs never appear even with recency_boost
(incumbency is too strong).

## Method

1. Copy live DB to temp.
2. Insert 20 new correction beliefs with current timestamps, covering known
   topics (locked beliefs, retrieval pipeline, scoring, etc.).
3. Run retrieve() without recency boost -- check top-10 for new belief IDs.
4. Monkey-patch score_belief to include recency_boost:
   `final_score = base_score * recency_boost(belief, now, half_life_hours=24.0)`
5. Re-run retrieve() -- check top-10 for new belief IDs.
6. Test decay: fake a timestamp 48 hours in the future, re-run with
   recency_boost, check that new beliefs no longer appear.

## Metrics

| Metric | Without Boost | With Boost | After 48h |
|--------|--------------|------------|-----------|
| New beliefs in top-10 | Expected: 0 | Expected: > 0 | Expected: ~0 |
| Average rank of new beliefs | Expected: > 10 | Expected: < 10 | Expected: > 10 |

## Success Criteria

New beliefs appear in top-10 with recency boost but not without it.

## Output

- `exp69_results.json`: per-query new-belief ranks, with/without boost, decay test.

## Files

- `exp69_recency_boost.py`
- `exp69_results.json`
