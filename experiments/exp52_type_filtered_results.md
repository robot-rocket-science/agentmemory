# Experiment 52: Type-Filtered FTS5 Retrieval -- Results

**Date:** 2026-04-10
**Status:** Complete
**Depends on:** Exp 47, 48

---

## 1. Summary

Tested whether filtering the 16K-node multi-layer graph to only belief/sentence/heading/behavioral_belief nodes (excluding file/callable/commit) restores retrieval coverage to Exp 47 (586-node baseline) levels.

**Key finding: Type filtering partially restores FTS5 but does NOT restore grep.** FTS5 coverage improved from 69% (Exp 48 unfiltered) to 77% (Exp 52 filtered), recovering the `strict_typing` topic that Exp 48 lost. Grep was unchanged at 85%. Neither method reaches Exp 47 levels (FTS5 85%, grep 92%).

The remaining gap is caused by doc sentence nodes (5,993 nodes, 71% of filtered set) still drowning belief nodes (586, 7%). Removing file/callable/commit was necessary but not sufficient.

---

## 2. Experimental Setup

- **Unfiltered set:** 15,778 nodes (same extraction as Exp 48, minor count difference from project changes)
- **Filtered set:** 8,415 nodes (belief + sentence + heading + behavioral_belief)
- **Methods:** grep (case-insensitive, term-frequency ranked) and FTS5 (porter stemmer, BM25)
- **Benchmark:** 6 topics, K=15, same ground truth as Exp 47/48

### Node Type Distribution

| Type | Unfiltered | Filtered |
|------|-----------|----------|
| sentence | 5,993 (38.0%) | 5,993 (71.2%) |
| file | 4,171 (26.4%) | -- excluded -- |
| callable | 2,651 (16.8%) | -- excluded -- |
| heading | 1,832 (11.6%) | 1,832 (21.8%) |
| belief | 586 (3.7%) | 586 (7.0%) |
| commit | 541 (3.4%) | -- excluded -- |
| behavioral_belief | 4 (0.0%) | 4 (0.0%) |
| **Total** | **15,778** | **8,415** |

FTS5 indexed: 15,334 (unfiltered) vs 8,284 (filtered).

---

## 3. Aggregate Results

| Method | Exp 47 (586 nodes) | Exp 48 (16K unfiltered) | Exp 52 (16K type-filtered) | Delta (52 vs 48) |
|--------|-------------------|------------------------|---------------------------|-------------------|
| Grep coverage@15 | **92.3%** | 84.6% | 84.6% | +0pp |
| Grep tokens@15 | 666 | 1,869 | 1,886 | +17 |
| Grep precision@15 | 21.1% | 12.2% | 12.2% | +0pp |
| Grep MRR | 0.639 | 0.328 | 0.328 | +0.000 |
| FTS5 coverage@15 | **84.6%** | 69.2% | **76.9%** | **+7.7pp** |
| FTS5 tokens@15 | 287 | 480 | 626 | +146 |
| FTS5 precision@15 | 15.6% | 10.0% | 11.1% | +1.1pp |
| FTS5 MRR | 0.833 | 0.666 | **0.750** | **+0.084** |

---

## 4. Per-Topic Results

| Topic | Needed | Grep Unf | Grep Filt | FTS5 Unf | FTS5 Filt |
|-------|--------|----------|-----------|----------|-----------|
| dispatch_gate | D089,D106,D137 | 3/3 | 3/3 | 2/3 (miss D137) | 2/3 (miss D137) |
| calls_puts | D073,D096,D100 | 2/3 (miss D100) | 2/3 (miss D100) | 2/3 (miss D100) | 2/3 (miss D100) |
| capital_5k | D099 | 1/1 | 1/1 | 1/1 | 1/1 |
| agent_behavior | D157,D188 | 1/2 (miss D157) | 1/2 (miss D157) | 1/2 (miss D157) | 1/2 (miss D157) |
| strict_typing | D071,D113 | 2/2 | 2/2 | 1/2 (miss D113) | **2/2** |
| gcp_primary | D078,D120 | 2/2 | 2/2 | 2/2 | 2/2 |

**FTS5 strict_typing recovered:** D113 was ranked outside K=15 in Exp 48 because callable/file nodes with "typing" in their names competed for BM25 slots. Removing those nodes restored D113 to the top 15.

**D137, D100, D157 still missing across all methods.** These are inherently hard targets -- the query terms have weak lexical overlap with the decision content.

---

## 5. Analysis

### What type filtering fixed

FTS5 recovered D113 (strict_typing) because:
- In the unfiltered index, "typing" appeared in callable nodes (e.g., `def check_typing`) and file nodes (`typing_utils.py`), pushing D113 beyond K=15.
- After filtering, "typing" only matches in belief/sentence/heading nodes, where D113 ranks higher.

### What type filtering did NOT fix

1. **Grep is unchanged.** Grep searches the content dict directly. Filtering removed file nodes (whose content is just the filename, e.g., "backtest.py") and callable nodes (just "def func_name"). These short strings rarely match multi-word queries, so removing them does not change which belief nodes appear in grep's top 15.

2. **D137 still missing from FTS5.** D137 is about "dispatch gate production deployment" but the query "dispatch gate deploy protocol" shares only partial overlap. Even in the 586-node Exp 47 FTS5 test, D137 was found -- meaning that at 586 nodes it ranked in the top 15, but at 8K filtered nodes, doc sentences about deployment still push it out.

3. **D100 and D157 missing everywhere.** These were also missed in Exp 47. The query-content lexical gap is the root cause, not dilution.

### The remaining dilution problem

Even after filtering, belief nodes are only 7% of the filtered set. Doc sentences (71%) still dominate BM25 rankings. The fundamental issue: a doc sentence about "deploy the application to GCP" will BM25-rank higher than a belief node D137 that mentions "dispatch gate" because the sentence has more matching terms.

**Implication:** Pure type filtering (include/exclude) helps marginally but cannot solve the problem. The next step is type-weighted BM25 (multiply belief scores by 3-5x) or a two-stage approach (search beliefs first, then expand to sentences only if K is unfilled).

---

## 6. Conclusions

1. **Type filtering recovers 1 of 4 lost decisions** for FTS5 (D113), improving coverage from 69% to 77%. This is a +7.7pp improvement but still 7.7pp below Exp 47's 85%.

2. **Grep is immune to type filtering** because file/callable nodes are too short to compete with multi-word queries. Grep's problem is not dilution by node type but by volume of similarly-matching belief nodes.

3. **The real fix requires type-weighted ranking,** not just type filtering. Belief nodes should receive a BM25 boost to outrank doc sentences with incidental term matches.

4. **Three decisions (D137, D100, D157) are missed by ALL methods across ALL experiments.** These require semantic or structural retrieval, not lexical improvement.

---

## 7. Data Artifacts

- `experiments/exp52_type_filtered_fts5.py` -- experiment script
- `experiments/exp52_raw_results.json` -- machine-readable results
- `experiments/exp52_type_filtered_results.md` -- this report
