# Experiment 18: Query Expansion Without LLM -- Research

**Date:** 2026-04-09
**Context:** FTS5 (BM25) over ~1,195 sentence-level belief nodes. Exp 9 showed 3 query formulations per topic achieve 100% critical belief coverage. The goal: automatically generate those multiple formulations without calling an LLM.

---

## 1. Stemming / Lemmatization

**What it is:** Reduce words to root forms. Porter stemmer maps "deploying" -> "deploy", "verification" -> "verif". Snowball is a refined Porter variant.

**FTS5 already uses `tokenize='porter'`.** This means stemming is already applied at both index and query time. Adding a second layer of stemming (e.g., via NLTK's PorterStemmer in Python before passing to FTS5) would be redundant -- FTS5's porter tokenizer already handles this.

**Where additional lemmatization helps:** The porter stemmer is aggressive and purely rule-based. A lemmatizer (e.g., spaCy's `en_core_web_sm`) uses vocabulary lookup, so "better" -> "good", "ran" -> "run". These cases are rare in technical/belief corpora but do exist.

**Computational cost:** Negligible. Porter stemming is O(n) string manipulation, ~1 microsecond per word. spaCy lemmatization requires loading a model (~15MB) but is still <1ms per sentence.

**At our corpus size:** Already in place via FTS5 porter. Additional lemmatization adds minimal value for technical content.

**Literature:** Porter (1980) "An algorithm for suffix stripping." The original. FTS5 docs confirm their porter implementation follows this. Snowball (Porter2) handles some edge cases better but the difference is marginal for English technical text.

**Recommendation:** No action needed. FTS5 porter tokenizer already covers this. Do not add a second stemming layer.

---

## 2. Synonym Expansion via Static Resources

### 2a. WordNet Synsets

**What it is:** WordNet provides synonym sets (synsets) for English words. "deploy" -> {deploy, use, employ, utilize}. Query term "deploy" gets expanded to "deploy OR use OR employ OR utilize" before FTS5 search.

**Problem for our domain:** WordNet is a general-purpose lexical database. For domain-specific terms like "dispatch gate", "GCP", "pyright", WordNet provides either no synonyms or misleading ones ("gate" -> fence, barrier, logic gate). Exp 9's hand-curated SYNONYMS dict outperforms WordNet for this reason.

**Computational cost:** NLTK's WordNet is a disk-based lookup. ~1ms per word. Loading NLTK data adds ~50MB to the environment.

**At our corpus size:** Marginal benefit. The vocabulary is domain-specific enough that WordNet synonyms introduce more noise than signal.

### 2b. Corpus-Derived Synonym Map (Co-occurrence Statistics)

**What it is:** Build a synonym-like mapping by analyzing which words appear together in the same belief nodes. If "dispatch" and "gate" frequently co-occur, and "deploy" and "protocol" also co-occur with similar context words, they may be related.

**Method:** Pointwise Mutual Information (PMI).

```
PMI(x, y) = log2( P(x,y) / (P(x) * P(y)) )
```

Where P(x,y) is the fraction of documents containing both x and y. High PMI pairs are strongly associated. This builds an association map, not true synonyms, but for query expansion the effect is similar.

**Implementation sketch:**
1. Tokenize all 1,195 nodes
2. Build a word-document co-occurrence matrix (sparse)
3. Compute PMI for all word pairs co-occurring in >= 3 documents
4. For each word, keep top-5 PMI associates as expansion terms
5. Store as a JSON dict, load at query time

**Computational cost:** One-time build is O(V^2) where V is vocabulary size. For 1,195 short sentences, V is likely 2,000-4,000 unique terms after stopword removal. The co-occurrence matrix is small -- easily fits in memory. Build time: <1 second. Query-time lookup: O(1) per term.

**At our corpus size:** This is viable and well-suited. PMI works better on smaller, focused corpora than on large web corpora because the co-occurrence signal is less diluted. With 1,195 nodes, you get clear domain-specific associations that WordNet would miss entirely.

**Literature:** Church & Hanks (1990) "Word Association Norms, Mutual Information, and Lexicography." Foundational PMI paper. Turney & Pantel (2010) survey shows PMI-based methods competitive with neural methods on small corpora. No source link -- these are well-cited ACL papers available through ACL Anthology.

**Recommendation:** Build a PMI-based co-occurrence map from the belief corpus. This is the single highest-value technique on this list for our use case. It captures domain-specific associations that no off-the-shelf resource can provide.

---

## 3. Pseudo-Relevance Feedback (PRF)

**What it is:** A two-pass retrieval strategy.
1. Run the original query against FTS5, take top-k results (k=5 to 10)
2. Extract the most informative terms from those results (by TF-IDF weight)
3. Add the top-n new terms to the query
4. Re-run the expanded query

This is the Rocchio algorithm (1971), adapted for text retrieval. It assumes the top results from the initial query are mostly relevant ("pseudo" relevance).

**Why it works for our problem:** The user queries "deploy protocol" and gets 5 results. Those results contain "dispatch", "gate", "GCP", "runbook". These terms get added to the expanded query, which then retrieves the nodes that mention "dispatch gate" but not "deploy protocol". This is exactly the multi-formulation effect Exp 9 achieved manually.

**Implementation sketch:**
1. First pass: FTS5 search, take top-5 results
2. TF-IDF extract: for each term in the top-5 results, compute TF-IDF. Keep terms with high TF in results but low DF across the full corpus (these are the distinctive terms).
3. Take top-10 new terms not in original query
4. Second pass: FTS5 search with original terms OR new terms

**Computational cost:** Two FTS5 queries instead of one. TF-IDF computation is trivial at our scale. Total latency: ~2x baseline, so perhaps 2-5ms instead of 1-2ms.

**At our corpus size:** PRF is well-studied on small collections. The key risk is "query drift" -- if the initial top-k results are off-topic, expansion makes things worse. With 1,195 nodes and BM25 (which is reasonably good at ranking), the top-5 results are usually relevant enough. Using a conservative expansion (only high-TF-IDF terms, only 5-10 new terms) mitigates drift.

**Literature:** Rocchio (1971) in the SMART retrieval system. Lavrenko & Croft (2001) "Relevance-Based Language Models" formalizes PRF. Lv & Zhai (2009) "A Comparative Study of Methods for Estimating Query Language Models with Pseudo Feedback" -- tested on TREC collections (some as small as ~1K docs). PRF consistently adds 10-20% MAP improvement.

**Recommendation:** Implement this. It is the classic no-LLM query expansion technique and directly replicates the multi-formulation effect. Combined with the PMI map from technique #2, it should approach the coverage of manually crafted 3-query formulations.

---

## 4. Query Expansion via Co-occurrence in the Belief Graph

**What it is:** A variant of technique #2, but leveraging the graph structure. If belief nodes are connected (e.g., D089 links to D106 via a "supports" edge), the terms in connected nodes are semantically related. Use the graph topology to weight co-occurrence: terms that co-occur in directly connected nodes get a higher association score than terms that merely co-occur in the same node.

**Method:** Graph-weighted PMI.

```
PMI_graph(x, y) = PMI_same_node(x, y) + alpha * PMI_linked_nodes(x, y)
```

Where alpha weights the contribution of graph links vs. simple co-occurrence.

**Computational cost:** Requires traversing edges in the belief graph. For 1,195 nodes with average degree ~3 (estimated), this is ~3,600 edge traversals. Trivial.

**At our corpus size:** If the graph structure exists and is meaningful, this provides better associations than plain co-occurrence. If edges are sparse or noisy, it adds little over technique #2.

**Literature:** Navigli & Velardi (2003) "An Analysis of Ontology-based Query Expansion Strategies" -- tested graph-based expansion on small domain ontologies. Results: 5-15% improvement over flat co-occurrence when the ontology is well-structured.

**Recommendation:** Worth trying if the belief graph has meaningful edges. If edges are just temporal (insertion order), skip this and use plain PMI (#2). If edges encode semantic relationships (supports, contradicts, refines), this is valuable.

---

## 5. Word2Vec / FastText on Local Corpus

**What it is:** Train word embeddings on the belief corpus. For a query term, find its k-nearest neighbors in embedding space and add them to the query.

**The corpus size problem:** Word2Vec needs millions of tokens to produce reliable embeddings. Our corpus has ~1,195 sentences * ~15 words = ~18,000 tokens. This is 2-3 orders of magnitude too small. The resulting vectors would be unreliable, with high variance and poor generalization.

**FastText is slightly better** because it uses subword (character n-gram) information, so it can handle morphological variants even with limited data. But it still needs substantially more data for semantic relationships.

**Mitigations:**
- **Pre-trained vectors:** Use pre-trained GloVe (6B tokens, 400K vocab) or FastText (Common Crawl) and filter to your vocabulary. This gives you general English semantics for free. Then fine-tune on your corpus if desired.
- **Augmented training:** Concatenate your corpus with related text (e.g., GCP docs, Python typing docs) to increase training data.

**Computational cost:** Using pre-trained vectors: load time ~1-5 seconds for a filtered subset, 50-300MB on disk. Query-time nearest-neighbor: <1ms with a small vocabulary. Training from scratch: seconds (corpus is tiny), but results are poor.

**At our corpus size:** Pre-trained vectors work. Training from scratch does not. The gap between pre-trained general vectors and domain-specific associations means you still want the PMI map (#2) for domain terms like "dispatch", "gate", "archon".

**Literature:** Mikolov et al. (2013) "Efficient Estimation of Word Representations in Vector Space" -- original Word2Vec. Bojanowski et al. (2017) "Enriching Word Vectors with Subword Information" -- FastText. Diaz et al. (2016) "Query Expansion with Locally-Trained Word Embeddings" (ACL) -- showed that locally-trained embeddings outperform global embeddings for query expansion, BUT their "local" corpora were 100K+ documents. At 1K documents, global pre-trained vectors are safer.

**Recommendation:** Low priority. Pre-trained FastText vectors could supplement PMI for general vocabulary, but the domain-specific terms (which matter most) are better served by corpus PMI. If you implement this, use pre-trained vectors, do not train from scratch.

---

## 6. Character N-gram Overlap

**What it is:** Represent each word as a set of character n-grams (typically 3-grams). "deploy" -> {dep, epl, plo, loy}. Match queries to documents by character n-gram overlap rather than exact word match. This handles typos ("depoly" shares n-grams with "deploy") and morphological variants ("deploying" shares most n-grams with "deploy").

**Implementation:** FTS5 supports custom tokenizers, but adding a character n-gram tokenizer requires C code (FTS5 tokenizer API). A simpler approach: build a separate lookup table mapping character trigrams to words in the corpus. At query time, convert query words to trigrams, find candidate words by trigram overlap, then use those words in FTS5 queries.

**Computational cost:** Building the trigram index: O(V * avg_word_length). Query expansion: O(query_length * V) in the naive case, but with an inverted trigram index it's O(query_length * k) where k is the average number of words sharing a trigram. At V=3,000, this is sub-millisecond.

**At our corpus size:** This solves a different problem than the others -- it handles typos and morphological edge cases the porter stemmer misses. It does not help with semantic gaps (e.g., "deploy" vs. "dispatch"). Useful as a defensive layer but not a primary expansion technique.

**Literature:** Gravano et al. (2001) "Using q-grams in a DBMS for Approximate String Processing." FTS5 trigram tokenizer is documented in SQLite docs for the separate `fts5vocab` and trigram options. However, FTS5's built-in trigram tokenizer is designed for substring matching, not fuzzy word matching.

**Recommendation:** Low priority for query expansion. Consider adding only if typo resilience becomes a measured problem. The porter stemmer already handles most morphological variation.

---

## Practical Recommendations (Ranked by Expected Impact)

### Tier 1: Implement Now

| Technique | Expected Impact | Effort | Notes |
|-----------|----------------|--------|-------|
| **Pseudo-Relevance Feedback** | High -- directly replicates multi-query effect | 2-4 hours | Two-pass FTS5 with TF-IDF term extraction. Most studied, most reliable. |
| **Corpus PMI Map** | High -- captures domain-specific associations | 2-3 hours | One-time build, JSON artifact, O(1) lookup. Unique to your domain. |

### Tier 2: Add If Tier 1 Insufficient

| Technique | Expected Impact | Effort | Notes |
|-----------|----------------|--------|-------|
| **Graph-weighted PMI** | Medium -- only if graph edges are semantic | 1-2 hours on top of #2 | Extension of corpus PMI. Skip if edges are only temporal. |
| **Pre-trained FastText vectors** | Medium -- helps with general vocabulary | 2-3 hours | Good supplement, not replacement, for PMI. Adds a dependency (~300MB). |

### Tier 3: Skip Unless Specific Need

| Technique | Expected Impact | Effort | Notes |
|-----------|----------------|--------|-------|
| Additional stemming/lemmatization | Negligible | N/A | FTS5 porter already handles this. |
| WordNet synsets | Low to negative | 1 hour | Too general, introduces noise for domain terms. |
| Character n-gram overlap | Low | 3-4 hours | Solves typos, not semantic gaps. |
| Train Word2Vec from scratch | Negative | 2 hours | Corpus too small, vectors would be unreliable. |

### Proposed Architecture

```
User Query
    |
    v
[1] Corpus PMI Expansion
    |  - Look up each query term in PMI map
    |  - Add top-3 associated terms per query term
    v
[2] FTS5 Pass 1 (expanded query)
    |  - BM25 ranking, take top-5
    v
[3] Pseudo-Relevance Feedback
    |  - TF-IDF extract from top-5 results
    |  - Add top-5 distinctive new terms
    v
[4] FTS5 Pass 2 (further expanded query)
    |  - BM25 ranking, take top-k
    v
Final Results
```

Total query latency: ~5-10ms (two FTS5 passes + dictionary lookups). No LLM calls. No external API dependencies. The PMI map is a one-time build artifact (~100KB JSON) that gets rebuilt whenever the belief corpus changes materially.

### Key Measurement

The success metric from Exp 9 is clear: does a single automatically-expanded query match the coverage of 3 manually-crafted queries? Design the next experiment (Exp 19) to compare:

- **Baseline:** single query, no expansion (Exp 9 "1 formulation" condition)
- **Treatment A:** single query + PMI expansion
- **Treatment B:** single query + PRF (2-pass)
- **Treatment C:** single query + PMI + PRF (the pipeline above)
- **Gold standard:** 3 manual query formulations (Exp 9 "3 formulations" condition)

Target: Treatment C achieves >= 95% of gold standard coverage.
