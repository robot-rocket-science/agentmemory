# Experiment 54: Mutual Information Scoring for Retrieval Ranking

**Date:** 2026-04-10
**Status:** Planned
**Depends on:** Exp 9 (ground truth), Exp 42 (compression data), Exp 47 (baseline), Exp 52 (type-filtered FTS5)
**Approach:** A017

---

## Research Question

Does replacing FTS5's BM25 ranking with a mutual-information-based score improve retrieval precision and recall on our 6-topic ground truth?

## Background

Phadke (2025, arXiv:2512.00378) proved that semantic similarity IS mutual information (Theorem 4.1: overlap-information isomorphism). Our current retrieval pipeline uses FTS5's BM25 variant, which scores based on term frequency and inverse document frequency. BM25 is a good approximation of relevance, but it is not MI-optimal -- it does not account for the information content of matching vs non-matching terms.

MI-RAG (Springer KAIS, 2025) demonstrated MI-based subgraph retrieval outperforming cosine similarity in RAG settings. The question is whether this translates to our sentence-level belief retrieval on short text.

## Hypothesis

**H1:** MI-based scoring will re-rank FTS5 results such that ground-truth beliefs appear at higher ranks (lower k) than BM25 alone. Specifically: mean reciprocal rank (MRR) of ground-truth beliefs improves by >= 10% over BM25.

**H2:** MI scoring will NOT improve coverage (recall@15) -- FTS5 already achieves 92% coverage (Exp 47). MI re-ranking changes order, not membership, of the candidate set.

**H3:** MI scoring will improve precision@5 by >= 15% over BM25. The top-5 results should be more concentrated with ground-truth beliefs.

## Null Hypotheses

**NH1:** MRR difference between MI-ranked and BM25-ranked is < 5% (within noise).
**NH2:** Precision@5 difference is < 5%.

If the nulls hold, MI scoring adds complexity without benefit at our scale.

## Method

### Step 1: Build term statistics from the belief corpus

Using the 1,195 sentence-level nodes from Exp 16/42:
- Compute document frequency (df) for every unique stemmed token
- Compute corpus-level term probability p(t) = df(t) / N
- Compute per-document term probability p(t|d) = tf(t,d) / len(d)

### Step 2: Compute pointwise MI for query-document pairs

For each query q and document d:

```
PMI(q, d) = sum over shared terms t of:
    log2( p(t|d) * p(t|q) / p(t)^2 )
```

This is the pointwise mutual information between the query's term distribution and the document's term distribution. High PMI means the document and query share terms that are rare in the corpus (high information content) rather than common terms (low information content).

Normalize by joint entropy to get normalized MI (NMI) in [0, 1]:

```
NMI(q, d) = PMI(q, d) / H(q, d)
```

### Step 3: Compare rankings on ground truth

For each of the 6 topics x 3 queries = 18 queries:
1. Run FTS5 query, get BM25-ranked top-30 results
2. Re-rank the same top-30 by MI score
3. Compute for both rankings:
   - Precision@5, Precision@10, Precision@15
   - Recall@15
   - MRR (mean reciprocal rank of first ground-truth hit)
   - NDCG@15 (normalized discounted cumulative gain)

### Step 4: Statistical test

Paired Wilcoxon signed-rank test on per-query MRR (BM25 vs MI), n=18. Report p-value and effect size (r = Z / sqrt(N)).

## Materials

- 1,195 sentence nodes from alpha-seek (Exp 16 decomposition)
- 6-topic ground truth with 13 critical decisions (Exp 9)
- 18 queries (3 per topic)
- FTS5 with porter stemmer (same config as Exp 42/47)

## Expected Results

| Metric | BM25 (expected) | MI (expected) | Reasoning |
|--------|-----------------|---------------|-----------|
| Recall@15 | 92% | 92% | Same candidate set, just reordered |
| Precision@5 | ~40-50% | ~55-65% | MI penalizes common terms harder |
| MRR | ~0.4-0.5 | ~0.5-0.6 | Ground truth beliefs use specific terms |
| NDCG@15 | ~0.5-0.6 | ~0.6-0.7 | Better concentration at top |

## Decision Criteria

| Result | Action |
|--------|--------|
| MRR improvement >= 10%, p < 0.05 | Adopt MI scoring as re-ranker on FTS5 candidates |
| MRR improvement 5-10%, p < 0.10 | Note as marginal; test on jose-bully/debserver for confirmation |
| MRR improvement < 5% or p > 0.10 | Reject. BM25 is sufficient at this scale |
| MI DECREASES ranking quality | Reject. Document why (likely: short documents make MI estimates noisy) |

## Risks

1. **Short document problem:** MI estimation requires sufficient term overlap. Sentence-level beliefs average 13 tokens compressed, ~30 tokens full. Sparse term vectors make PMI estimates high-variance. Mitigate: use Laplace smoothing on term probabilities.

2. **Query length:** Our queries are 3-5 terms. Very short queries produce noisy MI estimates. Mitigate: test with both original 3-term queries and expanded queries from Exp 39.

3. **Computational cost:** PMI computation is O(|Q| * |D| * |V|) per query. At 18 queries x 1,195 docs x ~3,000 vocab terms, this is ~64M operations. Trivial.

## Implementation Notes

- Zero external dependencies. numpy + sqlite3 only.
- Porter stemming to match FTS5 tokenization.
- Reuse Exp 42's sentence decomposition and ground truth infrastructure.
- Output: exp54_results.json with per-query rankings under both scoring methods.

## References

- [Phadke 2025: Information Theory of Similarity (arXiv:2512.00378)](https://arxiv.org/html/2512.00378)
- [MI-RAG (Springer KAIS, 2025)](https://link.springer.com/article/10.1007/s10115-025-02624-x)
- [RankMI: MI Maximizing Ranking Loss (CVPR 2020)](https://openaccess.thecvf.com/content_CVPR_2020/papers/Kemertas_RankMI_A_Mutual_Information_Maximizing_Ranking_Loss_CVPR_2020_paper.pdf)
