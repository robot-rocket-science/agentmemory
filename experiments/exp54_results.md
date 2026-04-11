# Experiment 54: Mutual Information Scoring -- Results

**Date:** 2026-04-10
**Status:** Complete -- NEGATIVE RESULT
**Approach:** A017

---

## Summary

MI-based re-ranking of FTS5 results does NOT improve ranking quality over BM25. Both PMI and NMI variants either match or degrade BM25 performance.

## Results

| Metric | BM25 | PMI | NMI |
|--------|------|-----|-----|
| Mean MRR | **0.843** | 0.738 | 0.806 |
| Mean P@5 | **0.300** | 0.300 | 0.300 |
| Mean P@10 | **0.183** | 0.183 | 0.183 |
| Mean P@15 | **0.126** | 0.126 | 0.126 |
| Mean R@15 | **0.861** | 0.861 | 0.861 |
| Mean NDCG@15 | **0.766** | 0.698 | 0.749 |

MRR change: PMI -12.4%, NMI -4.4%.

### Statistical Test

Wilcoxon BM25 vs PMI: W=4, p=0.188, n=6 nonzero pairs. Not significant.
Wilcoxon BM25 vs NMI: Only 1 nonzero difference. Insufficient data.

### Per-Query Analysis

BM25 already achieves MRR=1.0 on 13/18 queries. There is almost no room for improvement. The 5 queries where BM25 < 1.0 are:

| Query | BM25 MRR | PMI MRR | NMI MRR | Notes |
|-------|----------|---------|---------|-------|
| dispatch gate deploy | 0.500 | 0.500 | 0.500 | Tied -- both rank D089 at position 2 |
| initial investment amount | 0.000 | 0.000 | 0.000 | Zero hits -- vocabulary gap, no method helps |
| agent behavior instructions | 0.500 | **1.000** | 0.500 | PMI wins here (only case) |
| cloud compute infrastructure | 0.167 | **0.500** | 0.167 | PMI wins here |
| archon overflow only | **1.000** | 0.500 | **1.000** | PMI hurts |

PMI improves 2 queries but hurts 3 others. Net negative.

## Hypothesis Outcomes

| Hypothesis | Predicted | Observed | Verdict |
|------------|-----------|----------|---------|
| H1: MRR improves >= 10% | Yes | -12.4% (PMI), -4.4% (NMI) | **FAILED** |
| H2: Recall unchanged | R@15 = 92% | R@15 = 86.1% for all methods | **CONFIRMED** (all methods equal) |
| H3: P@5 improves >= 15% | Yes | 0% change | **FAILED** |

## Root Cause Analysis

**Why MI scoring fails on this corpus:**

1. **BM25 is already near-ceiling.** MRR = 0.843 means the first relevant result is typically at rank 1-2. Re-ranking within rank 1-5 produces marginal or negative effects.

2. **Short documents.** Sentence-level beliefs average ~30 tokens. Term frequency distributions over ~5-8 unique terms are too sparse for MI estimation to outperform BM25's IDF weighting. BM25 was designed for exactly this regime.

3. **Small corpus.** 1,195 documents and 2,876 terms. Document frequency estimates are precise enough that BM25's IDF is already a good approximation of term information content. MI's theoretical advantage (accounting for term co-occurrence) doesn't manifest because co-occurrence patterns are simple in a domain-specific corpus.

4. **Query-document term overlap is sparse.** Most queries share 1-2 terms with relevant documents. PMI on 1-2 shared terms is high-variance and dominated by a single term's weight.

## Decision

**REJECT A017.** BM25 is sufficient at this scale and document length. MI scoring adds computation without benefit.

MI scoring might be valuable on:
- Larger corpora (10K+ documents) where IDF becomes less precise
- Longer documents where term co-occurrence patterns are richer
- Multi-hop queries where compositional MI could capture relationships

None of these conditions hold for our current retrieval architecture.

## References

- [Phadke 2025: arXiv:2512.00378](https://arxiv.org/html/2512.00378) -- theoretical framework (correct, but practical gains require different operating regime)
- [MI-RAG](https://link.springer.com/article/10.1007/s10115-025-02624-x) -- their gains were on longer documents with embedding-based MI, not term-level PMI
