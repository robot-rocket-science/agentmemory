# Research: Automatic Query Expansion Without LLM

**Date:** 2026-04-10
**Type:** Experimental research
**Question:** Can corpus-derived PMI maps and pseudo-relevance feedback automatically replicate the coverage of hand-crafted multi-query formulations?
**Dependencies:** Exp 9 (retrieval baseline), Exp 18 (technique survey), alpha-seek belief corpus (586 nodes)

---

## 1. Background

Exp 9 demonstrated that 3 hand-crafted query formulations per topic achieve 100% critical belief coverage (13/13 decisions across 6 topics) on the alpha-seek corpus. A single query achieves 92% (12/13). The gap is one decision: D157 (async_bash banning), retrievable only via vocabulary that shares no terms with the natural query "agent behavior instructions."

Exp 18 surveyed 6 zero-LLM expansion techniques and recommended two for implementation: corpus PMI and pseudo-relevance feedback (PRF).

---

## 2. Hypotheses

### H1: PMI expansion improves single-query coverage

PMI co-occurrence maps capture domain-specific term associations (e.g., "capital" -> "5k", "100k"; "pyright" -> "strict", "untyped") that are invisible to FTS5's porter stemmer.

**Prediction:** PMI-expanded queries achieve >= 92% coverage (at least match baseline).

### H2: PRF improves single-query coverage

Two-pass retrieval extracts distinctive terms from initial results and feeds them back into the query.

**Prediction:** PRF achieves >= 92% coverage and finds at least one decision missed by the baseline.

### H3: Combined PMI+PRF matches hand-crafted 3-query formulations

**Prediction:** PMI+PRF achieves 100% coverage (13/13).

**Null for all:** Expansion methods do not improve coverage over single-query baseline.

---

## 3. Method

### 3.1 Corpus

586 active belief nodes from alpha-seek DB (decisions D001-D209, milestones, knowledge nodes). FTS5 index with porter tokenizer.

### 3.2 PMI Map Construction

1. Tokenize all 586 nodes (lowercase, alpha-only, stopword removal)
2. Build word-document co-occurrence matrix
3. Compute PMI for pairs co-occurring in >= 3 documents and <= 50% of corpus
4. Keep top-5 PMI associates per word
5. Result: 423 words in map

### 3.3 Methods Tested

| Method | Description |
|--------|------------|
| baseline | Single FTS5 query, top-30 results |
| pmi_expansion | Expand each query term with top-3 PMI associates, then FTS5 |
| prf | Two-pass: FTS5 top-5, extract top-10 TF-IDF terms, re-query |
| pmi_plus_prf | PMI expand first, then PRF on expanded query |
| multi_pmi_3query | Three queries: original + PMI-replaced terms + PRF, union results |
| union_all | Union of all four single-method results |

### 3.4 Ground Truth

6 topics from Exp 9, 13 critical decisions total. Coverage = fraction of needed decisions found in retrieved results.

---

## 4. Results

### 4.1 Coverage

| Method | Coverage | Found/Needed | Missed |
|--------|---------|-------------|--------|
| baseline | 92% | 12/13 | D157 |
| pmi_expansion | 85% | 11/13 | D137, D157 |
| prf | 92% | 12/13 | D157 |
| pmi_plus_prf | 92% | 12/13 | D157 |
| multi_pmi_3query | 92% | 12/13 | D157 |
| union_all | 92% | 12/13 | D157 |
| **Exp 9 hand-crafted** | **100%** | **13/13** | -- |

### 4.2 PMI Map Quality (Qualitative)

The PMI associations are domain-accurate:

| Term | Top Associates | Quality |
|------|---------------|---------|
| capital | 100k(5.9), 5k(5.7), vs(3.0), trade(2.9) | Excellent -- exact domain terms |
| calls | citizens(6.2), equal(5.8), puts(5.4), direction(4.5) | Excellent -- alpha-seek specific |
| pyright | untyped(5.2), cast(5.2), strict(5.0), type(3.1) | Excellent |
| deploy | sh(5.4), docker(3.6), gate(3.0), archon(2.9) | Good -- infrastructure context |
| dispatch | tag(4.1), head(3.8), image(3.7), batch(3.7) | Weak -- Docker image terms dominate |
| gcp | standard(3.6), extension(3.6), c2d(3.6), vms(3.6) | Good -- GCP-specific |

### 4.3 The Irreducible Miss: D157

D157 content: "Whether to allow async_bash and await_job for background command execution: BANNED. Never use async_bash or await_job..."

The query "agent behavior instructions" shares zero content terms with D157. The only Exp 9 query that finds D157 is "execute precisely return control" -- vocabulary that requires knowing D157 exists.

**No statistical expansion method can bridge this gap.** There is no co-occurrence path from "behavior" to "async_bash" in the corpus. The connection is semantic: both relate to agent behavioral constraints, but that relationship exists only in the user's mental model, not in any corpus statistics.

---

## 5. Analysis

### 5.1 H1 (PMI): FAIL

PMI expansion **reduced** coverage from 92% to 85%. The noisy terms (tag, head, image) for "dispatch" pushed relevant results off the top-30 list. PMI is excellent for term association but harmful when used to expand FTS5 queries because it dilutes BM25 ranking.

### 5.2 H2 (PRF): PARTIAL PASS

PRF maintained baseline coverage (92%) and produced high-quality expansion terms (e.g., "pontificating philosophizing" for agent_behavior, "5k 25k usd" for capital). It did not improve coverage but it did not hurt it either.

### 5.3 H3 (Combined matches hand-crafted): FAIL

No automatic method reaches 100%. The gap is D157, an irreducible vocabulary mismatch.

### 5.4 Why the Baseline Is Already 92%

The single-query baseline in this experiment uses a well-chosen initial query per topic. Exp 9 showed that the *first* query in each 3-query set already retrieves most decisions. The expansion techniques are fighting for the last 8% -- the hardest cases where the vocabulary gap is widest.

### 5.5 Where PMI Adds Value

PMI doesn't help FTS5 coverage but its associations are genuinely useful for other purposes:
- **Query suggestion:** "Did you mean: 5k, 100k?" when user queries "capital"
- **Graph edge weighting:** PMI scores between co-occurring terms can weight belief graph edges
- **HRR selectivity:** PMI associates define the vocabulary neighborhood for HRR binding

The PMI map is a useful artifact; it just doesn't belong in the FTS5 query pipeline.

### 5.6 The Vocabulary Gap Is the Graph's Job

D157 is unreachable by any text expansion method. It requires knowing that "agent behavior" and "async_bash banning" are related through the concept "agent behavioral constraints." This is exactly what the belief graph should encode:

```
D157 (async_bash ban) --[RELATES_TO]--> D188 (execute precisely)
D188 (execute precisely) --[RELATES_TO]--> "agent behavior" topic
```

FTS5 + query expansion handles the 92% of cases where vocabulary overlaps. Graph traversal (BFS, HRR) handles the 8% where it doesn't. This validates the hybrid retrieval architecture from PLAN.md: FTS5 for keyword matches, graph for semantic hops.

---

## 6. Decision

### Adopt: PRF as Default Retrieval Enhancement

PRF is zero-cost (one extra FTS5 query), zero-risk (maintains baseline coverage), and produces better expanded queries for debugging and transparency. Use as the standard retrieval mode: every query gets a PRF pass automatically.

### Adopt: PMI Map as Auxiliary Artifact (Not for FTS5 Expansion)

The PMI map is valuable for:
- Query suggestion / "related terms" display
- Graph edge weighting (PMI as edge confidence)
- HRR vocabulary neighborhood definitions
- Debugging retrieval misses

Do NOT use PMI to expand FTS5 queries. It dilutes BM25 ranking and can reduce coverage.

### Confirm: Hybrid Retrieval Architecture

The 8% coverage gap (D157) is unreachable by any text-based method. This validates the design in PLAN.md: FTS5 handles vocabulary-overlap cases, graph traversal (BFS/HRR) handles semantic-gap cases. Neither alone is sufficient.

### Revise: Exp 9 Baseline Was Already Strong

Single-query FTS5 achieves 92% on these 6 topics. The hand-crafted 3-query approach's extra 8% comes from human knowledge of specific belief content, not from systematic query expansion. The real retrieval improvement will come from graph traversal, not from better text queries.

---

## 7. References

1. Rocchio, J.J. "Relevance Feedback in Information Retrieval." The SMART System, 1971.
2. Church, K.W., Hanks, P. "Word Association Norms, Mutual Information, and Lexicography." Computational Linguistics, 1990.
3. Lavrenko, V., Croft, W.B. "Relevance-Based Language Models." SIGIR, 2001.
4. Lv, Y., Zhai, C. "A Comparative Study of Methods for Estimating Query Language Models with Pseudo Feedback." CIKM, 2009.
5. Exp 9: experiments/exp9_retrieval_improvements.py
6. Exp 18: experiments/exp18_query_expansion_research.md
7. Exp 39: experiments/exp39_query_expansion.py
