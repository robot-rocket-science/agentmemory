# Experiment 46: SimHash Binary Encoding -- Empirical Results

**Date:** 2026-04-10
**Input:** 1,195 sentence nodes from 173 decisions (Exp 16 decomposition)
**Builds on:** Exp 23 (theory), Exp 16 (sentence nodes), Exp 9/39 (ground truth), Exp 34 (HRR vocabulary bridge)
**Method:** TF-IDF + random hyperplane projection (SimHash/Charikar 2002). Zero-LLM.
**Rigor tier:** Empirically tested (real alpha-seek corpus, 6-topic ground truth)

---

## Q1: Encoding Performance and Storage

**Result: 44ms total encoding, 19 KB usable storage (128 bits per node).**

| Metric | Value |
|--------|-------|
| Vocabulary size | 1,929 terms |
| TF-IDF matrix | 1,195 x 1,929 (0.6% nonzero -- very sparse) |
| TF-IDF build time | 20ms |
| SimHash projection time | 24ms |
| Total encoding time | 44ms |
| Code width | 128 bits per node |
| Storage (as uint8 array) | 149 KB (includes overhead; raw = 19 KB) |
| Storage (raw bits) | 1,195 x 128 bits = 19,120 bytes = 18.7 KB |

The raw 128-bit codes for all 1,195 nodes fit in 19 KB. The TF-IDF matrix (required for query encoding) is ~18 MB dense, but at 0.6% fill it could be stored sparse at ~110 KB. The random hyperplane matrix (1,929 x 128) is ~2 MB. Total footprint for the encoding system: under 3 MB.

Encoding is sub-50ms on a laptop. Re-encoding the full corpus after adding new beliefs is negligible.

---

## Q2: Hamming Distance Distribution

**Result: Tightly concentrated around 64 (half of 128 bits). Nearly Gaussian. Very few close pairs.**

| Statistic | Value |
|-----------|-------|
| Total pairs | 713,415 |
| Mean | 63.7 |
| Median | 64.0 |
| Std dev | 5.8 |
| Min | 0 |
| Max | 90 |
| P5 | 54 |
| P25 | 60 |
| P75 | 68 |
| P95 | 73 |

### Fraction of pairs within Hamming distance thresholds

| Threshold (K) | Pairs | Fraction |
|---------------|-------|----------|
| <= 5 | 13 | 0.0018% |
| <= 10 | 14 | 0.0020% |
| <= 15 | 15 | 0.0021% |
| <= 20 | 17 | 0.0024% |
| <= 25 | 22 | 0.0031% |
| <= 30 | 41 | 0.0057% |

### Distribution shape

The distribution is nearly Gaussian centered at 64, which is exactly half of 128 bits. This is the expected behavior for random hyperplane hashing: when most documents share very few terms (TF-IDF vectors are nearly orthogonal), the expected Hamming distance is n_bits/2 = 64.

The extremely tight concentration (std = 5.8 out of 128 bits) means the hash is operating near its resolution limit. Only 13 pairs out of 713K have Hamming distance <= 5. The useful signal is compressed into the left tail of the distribution.

**This is a critical finding:** At 128 bits with TF-IDF on short sentences (avg ~25 tokens), the SimHash codes provide very little discriminative power. Most pairs land at 60-68, with only a thin tail of genuinely close pairs. The hash is working correctly (similar pairs do get closer), but the signal-to-noise ratio is poor for sentence-level documents.

**Root cause:** Short sentences have sparse TF-IDF vectors. Two sentences sharing 2-3 terms out of 10 produce a small cosine similarity (~0.15), which maps to Hamming distance ~54 (close to the 64 baseline). The dynamic range from "totally unrelated" (H=64) to "shares some terms" (H=54) is only 10 bits.

---

## Q3: Semantic Quality -- Related vs Unrelated Pairs

**Result: Weak separation. Related pairs average H=60.5, unrelated pairs average H=62.7. Ratio: 1.04x.**

### Related pairs (siblings or cross-references)

| Pair | Reason | Hamming |
|------|--------|---------|
| D002_s0 / D002_s1 | siblings in D002 | 67 |
| D003_s0 / D003_s1 | siblings in D003 | 59 |
| D004_s0 / D004_s1 | siblings in D004 | 66 |
| D005_s0 / D005_s1 | siblings in D005 | 62 |
| D006_s0 / D006_s1 | siblings in D006 | 60 |
| D007_s0 / D007_s1 | siblings in D007 | 63 |
| D008_s0 / D008_s1 | siblings in D008 | 48 |
| D009_s0 / D009_s1 | siblings in D009 | 54 |
| D010_s0 / D010_s1 | siblings in D010 | 75 |
| D011_s0 / D011_s1 | siblings in D011 | 69 |
| D098_s0 / D103_s1 | both cite D097 | 65 |
| D098_s4 / D103_s1 | both cite D097 | 52 |
| D098_s6 / D103_s1 | both cite D097 | 60 |
| D098_s8 / D103_s1 | both cite D097 | 63 |
| D103_s1 / D107_s1 | both cite D097 | 44 |

**Related: mean=60.5, median=62, std=7.9**

### Unrelated pairs (distant decisions)

| Pair | Hamming |
|------|---------|
| D002 vs D199 | 67 |
| D002 vs D200 | 58 |
| D002 vs D201 | 58 |
| D002 vs D202 | 55 |
| D002 vs D203 | 58 |
| D002 vs D204 | 61 |
| D002 vs D205 | 69 |
| D002 vs D206 | 60 |
| D002 vs D207 | 75 |
| D002 vs D208 | 57 |
| D003 vs D199 | 67 |
| D003 vs D200 | 52 |
| D003 vs D201 | 64 |
| D003 vs D202 | 75 |
| D003 vs D203 | 64 |

**Unrelated: mean=62.7, median=61, std=6.7**

### Assessment

The 1.04x separation ratio is not operationally useful. The distributions overlap almost completely. Some related pairs (D010_s0/D010_s1 at H=75) are MORE distant than some unrelated pairs (D003/D200 at H=52).

**Why this happens:** Sibling sentences within a decision often use different vocabulary. "Minimum per-trade return target: Minimum 2x return on premium" and "Contract selection constraint, not exit target" are in the same decision (D002) but share almost no terms after stopword removal.

The few genuinely close pairs (H < 50) are cases where sentences share specific domain terms: D103_s1 and D107_s1 (H=44) both discuss D097 using the same vocabulary.

**Verdict:** SimHash on TF-IDF at 128 bits does not provide reliable semantic quality for sentence-level beliefs. The resolution is too coarse for short documents.

---

## Q4: Retrieval Pre-filter vs FTS5

**Result: SimHash is a poor pre-filter. FTS5 achieves 100% coverage on all 6 topics. SimHash requires K >= 45-50 to match, at which point the candidate set is too large to be useful as a pre-filter.**

| Topic | FTS5 | SimHash K=25 | SimHash K=35 | SimHash K=45 | Min K for 100% |
|-------|------|-------------|-------------|-------------|----------------|
| dispatch_gate | 3/3 | 0/3 | 0/3 | 0/3 | 50 |
| calls_puts | 3/3 | 0/3 | 2/3 | 3/3 | 45 |
| capital_5k | 1/1 | 0/1 | 0/1 | 1/1 | 45 |
| agent_behavior | 2/2 | 0/2 | 0/2 | 1/2 | None* |
| strict_typing | 2/2 | 0/2 | 0/2 | 2/2 | 45 |
| gcp_primary | 2/2 | 0/2 | 1/2 | 2/2 | 45 |

*agent_behavior never reaches 100% -- D157 is never captured even at K=50. The query "agent behavior instructions" shares no content terms with D157 ("ban async_bash"). This is exactly the vocabulary gap problem.

### Analysis

At K=45, SimHash captures 4-5 candidates per topic but still misses vocabulary-gap cases. At K=50, it captures more but the candidate set grows toward hundreds of nodes, providing no selectivity benefit over scanning the full corpus (1,195 nodes).

The fundamental problem: a query with 3-4 terms produces a TF-IDF vector that is highly sparse. Its SimHash code is nearly random -- most bits are determined by the signs of near-zero dot products. The meaningful signal is confined to the few bits aligned with the query terms, but 128 random hyperplanes only occasionally align with those specific dimensions.

**FTS5 wins decisively.** It uses exact token matching (with stemming), which is the right tool for sparse short-document retrieval. SimHash's probabilistic guarantee (Hamming approximates cosine) holds in expectation but the variance is too high for sentences.

---

## Q5: Drift Detection

**Result: No. Isolated beliefs do NOT have higher minimum Hamming distance.**

| Isolated Decision | Min Hamming | Mean Hamming | Close Neighbors (min+5) |
|-------------------|-------------|--------------|-------------------------|
| D005 (sizing strategy) | 35 | 62.7 | 1 |
| D008 (MCTS allocator) | 42 | 63.3 | 6 |
| D009 (sector cap) | 39 | 63.5 | 2 |
| D012 (compound sizing) | 42 | 63.2 | 6 |
| D017 (SDT framework) | 46 | 63.4 | 21 |

Global minimum-distance statistics:
- Mean: 41.6
- Median: 43
- P90: 46
- P95: 47

**Isolated beliefs average min-distance: 40.8 (ratio to global: 0.981x)**

The isolated beliefs are indistinguishable from the general population in their Hamming distance profile. This is consistent with Q2/Q3: the SimHash codes have too little dynamic range at this scale to distinguish "new topic" from "same topic, different words."

**Verdict:** SimHash on TF-IDF at 128 bits cannot serve as a drift detector for sentence-level beliefs. The code resolution is insufficient.

---

## Q6: SimHash vs HRR Comparison

**Result: Confirmed. SimHash FAILS on vocabulary-gap cases where HRR SUCCEEDS. They are complementary, not substitutes.**

### Vocabulary-gap cases (AGENT_CONSTRAINT edge, no shared vocabulary)

| Pair | Hamming | Jaccard Overlap | Token Overlap | HRR Result |
|------|---------|----------------|---------------|------------|
| D157 vs D188 | 65 | 0.000 | [] | PASS (184x separation) |
| D157 vs D100 | 55 | 0.059 | [whether] | PASS |
| D157 vs D073 | 52 | 0.000 | [] | PASS |
| D188 vs D100 | 64 | 0.050 | [agent] | PASS |
| D188 vs D073 | 65 | 0.000 | [] | PASS |
| D100 vs D073 | 59 | 0.045 | [strategy] | PASS |

All vocabulary-gap pairs have Hamming distances of 52-65, firmly in the "indistinguishable from random" zone (global mean: 63.7). SimHash cannot detect that these beliefs are related because they share no content terms.

HRR (Exp 34 Test A) achieved 184x separation between behavioral beliefs and distractors by traversing the AGENT_CONSTRAINT edge. The edge encodes the structural relationship that content analysis cannot see.

### Content-similar case

| Pair | Hamming | Jaccard Overlap |
|------|---------|----------------|
| D071 vs D113 (strict typing) | 44 | 0.15 |

This pair shares vocabulary ("typing", "pyright", "strict") and their Hamming distance (44) is below the global mean, placing them roughly at the P10 mark. SimHash correctly identifies them as more related than average, but the separation is modest (44 vs 64 mean -- about 3.5 standard deviations).

### Explicit D157 vs D188 test

- **D157:** "Whether to allow async_bash and await_job for background command execution: BANNED..."
- **D188:** "How the agent should respond to direct user instructions: Execute exactly what..."
- **Hamming distance:** 65 (above the global mean -- SimHash sees them as LESS related than average)
- **Token overlap:** zero
- **SimHash verdict: FAIL**
- **HRR verdict: PASS** (184x separation via AGENT_CONSTRAINT edge, Exp 34)

### Where each method wins

| Scenario | SimHash | HRR | Winner |
|----------|---------|-----|--------|
| Content-similar beliefs (shared terms) | Weak signal (H=44 vs 64 mean) | No signal (random node vectors) | SimHash (weakly) |
| Vocabulary-gap beliefs (shared edge type) | No signal (H=65, random-level) | Strong signal (184x separation) | HRR (decisively) |
| Query-to-corpus matching | Poor (needs K >= 45, misses vocab gaps) | N/A (not designed for query matching) | FTS5 |
| New topic detection | Not viable (no separation) | Not tested for this use case | Neither |
| Storage efficiency | 19 KB for 1,195 codes | ~2 MB for DIM=2048 graph encoding | SimHash |
| Computation | 44ms encode, microseconds per query | ~10ms per single-hop query | SimHash (marginally) |

---

## Summary of Findings

| Question | Answer | Confidence |
|----------|--------|------------|
| Q1: Encoding cost? | 44ms, 19 KB. Negligible. | High |
| Q2: Distribution shape? | Gaussian at 64, std=5.8. Very concentrated. | High |
| Q3: Semantic quality? | 1.04x separation. Not operationally useful. | High |
| Q4: Retrieval pre-filter? | No. Requires K >= 45 (useless selectivity). FTS5 dominates. | High |
| Q5: Drift detection? | No. Isolated beliefs are indistinguishable from population. | High |
| Q6: vs HRR? | Complementary but weak. SimHash fails on vocab gaps, which is HRR's strength. | High |

## Root Cause Analysis

The poor SimHash performance is not a bug in the implementation. It is a fundamental property of TF-IDF SimHash on short documents:

1. **Short sentences have sparse TF-IDF vectors.** Average sentence has ~6 unique non-stopword tokens out of a 1,929-term vocabulary. The TF-IDF vector is > 99% zeros.

2. **Sparse vectors produce near-random hash codes.** When dot(vector, hyperplane) is close to zero for most hyperplanes (because the vector has mass on only ~6 of 1,929 dimensions), the sign is determined by noise. Most of the 128 bits are uninformative.

3. **The useful signal is confined to a few bits.** Only the hyperplanes that happen to align with the ~6 active dimensions carry meaningful information. At 128 random hyperplanes over 1,929 dimensions, each hyperplane has ~6/1929 = 0.3% chance of aligning with any given active dimension. The effective bit-width for semantic content is dramatically less than 128.

4. **This would improve with longer documents or denser representations.** Decision-level encoding (concatenating all sentences per decision) would produce denser TF-IDF vectors. Sentence embeddings from a language model would produce dense 384-768D vectors where all dimensions carry signal. SimHash on dense representations would have much better resolution.

## Implications for Architecture

1. **SimHash on TF-IDF is not viable as a retrieval layer for sentence-level beliefs.** The signal is too weak at this document length and vocabulary scale.

2. **FTS5 remains the primary content-based retrieval method.** It is exact, fast, and handles sparse short documents correctly because it matches individual tokens, not aggregate vector representations.

3. **HRR remains the primary structural retrieval method.** Its 184x separation on vocabulary-gap cases is orders of magnitude beyond what SimHash can achieve on any case.

4. **If binary codes are revisited,** the input should be dense sentence embeddings (from a language model or pre-trained encoder), not TF-IDF. Dense inputs would give SimHash codes real discriminative power. But this introduces an LLM or model dependency, which contradicts the zero-LLM design goal.

5. **The drift detection use case is better served by other methods.** Topic modeling on TF-IDF (LDA, NMF) or simply monitoring new-term frequency would detect new topics more reliably than Hamming distance on SimHash codes.

6. **The original Exp 23 prototype path was correct in its theory but underestimated the document-length problem.** The theoretical guarantee (Hamming approximates angular distance) holds exactly, but angular distance itself has very low dynamic range for sparse, short documents.

---

## Files

| File | Contents |
|------|----------|
| experiments/exp46_simhash_prototype.py | Full experiment code (strict typed, pyright clean) |
| experiments/exp46_simhash_results.json | Raw numeric results |
| experiments/exp46_simhash_results.md | This analysis |
| experiments/exp23_gray_code_research.md | Prior theoretical research |
