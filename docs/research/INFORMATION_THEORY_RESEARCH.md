# Information-Theoretic Approaches to Agentic Memory

**Date:** 2026-04-09
**Status:** Research complete -- integration decisions pending

---

## 1. Anti-Cryptography: Maximizing Meaning Discoverability

"Anti-cryptography" is not a named field, but the underlying math is well-established.

### The Formal Inverse of Cryptographic Hashing

Cryptographic hash functions maximize the avalanche effect: similar inputs produce maximally different outputs. **Locality-Sensitive Hashing (LSH)** does the exact opposite: similar inputs hash to the same buckets with high probability.

Variants relevant to memory systems:
- **MinHash** -- approximates Jaccard similarity |A intersect B| / |A union B|. Unbiased estimator: P(min-hash match) = J(A,B). Directly applicable to belief deduplication.
- **SimHash** -- targets cosine similarity / Hamming distance. Better for continuous vectors.
- **Semantic Hashing** (Salakhutdinov & Hinton, 2009) -- deep autoencoders learn binary codes where semantically similar documents map to nearby memory addresses.

### Mutual Information as the Foundation of Retrieval

**"The Information Theory of Similarity"** (Phadke, 2025, arXiv:2512.00378) is the key paper:

- **Theorem 4.1 (Overlap-Information Isomorphism):** Witness overlap between concepts is mathematically equivalent to mutual information between witness distributions.
- **Theorem 8.1 (Fundamental Lower Bound):** Any encoding preserving top-k similarity rankings requires Omega((log N)/Delta^2) bits per comparison. This is information-theoretic, not algorithmic -- no cleverness can beat it.
- **Theorem 6.2:** Ranking compression follows rate-distortion constraints.

This means: semantic similarity IS mutual information, and there's a provable floor on how compact your retrieval index can be while preserving ranking quality.

### Implication for Our System

Our retrieval pipeline (FTS5 + BFS + confidence ranking) is implicitly approximating mutual information between the query and stored beliefs. We could make this explicit by:
1. Using MI-based scoring instead of ad hoc relevance * confidence
2. Applying the information bottleneck to determine optimal compression of beliefs
3. Using the fundamental lower bound to know when we've reached theoretical limits

**Sources:**
- [Phadke 2025: Information Theory of Similarity (arXiv:2512.00378)](https://arxiv.org/html/2512.00378)
- [MI-RAG: Mutual information-based RAG (Springer KAIS, 2025)](https://link.springer.com/article/10.1007/s10115-025-02624-x)
- [Semantic Hashing (Salakhutdinov & Hinton, 2009)](https://www.sciencedirect.com/science/article/pii/S0888613X08001813)
- [RankMI: MI Maximizing Ranking Loss (CVPR 2020)](https://openaccess.thecvf.com/content_CVPR_2020/papers/Kemertas_RankMI_A_Mutual_Information_Maximizing_Ranking_Loss_CVPR_2020_paper.pdf)

---

## 2. Holographic Memory Projections

This direction has the deepest academic roots. Three independent research lines converge.

### Holographic Reduced Representations (Plate, 1995)

Circular convolution binds vectors representing different concepts into a single vector of the **same dimensionality** (the holographic property -- the whole is encoded in the same space as the parts). Retrieval via circular correlation (approximate inverse).

**NeurIPS 2021 update** (Ganesan et al.): "Learning with Holographic Reduced Representations" added a projection step, improving concept retrieval by over 100x. Demonstrated on knowledge graph completion.

### Sparse Distributed Memory (Kanerva, 1988)

Memory traces are distributed across many overlapping locations. Similar addresses activate together. Reconstruction via superposition. Degrades gracefully under noise.

**Critical finding:** Bricken & Pehlevan (NeurIPS 2021) proved that **Transformer attention is mathematically equivalent to Kanerva's SDM** under certain conditions. Requirements: L2-normalized vectors and a beta coefficient for softmax approximating SDM's circle intersection decay. Confirmed in pre-trained GPT-2.

**Implication:** The mechanism LLMs already use to process context IS a holographic distributed memory retrieval. Our external memory system is augmenting an internal holographic memory.

### Hyperdimensional Computing / Vector Symbolic Architectures

The broader family (survey: Kleyko et al., ACM Computing Surveys, 2022):
- Binary Spatter Codes (XOR binding)
- Multiply-Add-Permute (MAP)
- HRR (circular convolution)
- Tensor Product Representations

VSA provides an **item/cleanup memory** that retrieves the best-matching hypervector for a query -- exactly the "anti-cryptographic" retrieval described in Direction 1.

### Holonomic Brain Theory (Pribram & Bohm)

The cognitive science foundation. Memories stored holographically: each part contains information about the entire pattern at lower resolution. Brain maintains function and memory even when damaged. Recent work continues this line (PMC, 2024).

### What This Means for Our Citation Graph

Our citation graph with typed edges (CITES, SUPPORTS, CONTRADICTS, etc.) is a multi-dimensional structure. Each BFS subgraph retrieved for a task is a **projection** -- a lower-resolution view of the full knowledge structure from a specific angle (defined by the seed terms and edge types traversed).

The multiple edge types are literally multiple "viewing angles." A query about causation traverses SUPPORTS/CONTRADICTS edges. A query about provenance traverses CITES/SOURCED_FROM edges. A query about temporal evolution traverses TEMPORAL_NEXT edges. Same graph, different projections.

This isn't metaphor -- it maps to the formal properties of holographic representations where the same high-dimensional structure can be queried from different angles to recover different aspects of the encoded information.

**Practical application:** We could encode beliefs as hyperdimensional vectors using HRR, where the binding operation captures typed relationships. BFS becomes a sequence of unbinding operations. This would give us:
- Approximate nearest-neighbor retrieval via similarity in hyperdimensional space
- Composable queries (bind query terms together, unbind against stored beliefs)
- Graceful degradation (partial matches still retrieve partial information)

**Cost:** Adds vector computation. May not be worth it for v1 given that FTS5 + BFS already works. But it's a principled upgrade path for v2.

**Sources:**
- [HRR (Plate, 1995)](https://ieeexplore.ieee.org/document/377968/)
- [Learning with HRRs (NeurIPS 2021)](https://proceedings.neurips.cc/paper/2021/file/d71dd235287466052f1630f31bde7932-Paper.pdf)
- [Attention Approximates SDM (Bricken & Pehlevan, NeurIPS 2021)](https://arxiv.org/abs/2111.05498)
- [VSA Survey Part I (ACM 2022)](https://dl.acm.org/doi/10.1145/3538531)
- [Holonomic Brain Theory (PMC 2024)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10889214/)

---

## 3. Viterbi and Path Finding on Belief Graphs

### The HMM Framing

The Viterbi algorithm finds the most likely sequence through a Hidden Markov Model. Applied to our belief graph:
- Hidden states = relevant beliefs
- Observations = query terms
- Transitions = graph edges (weighted by edge confidence)
- Viterbi finds the most probable PATH through the belief graph

This generalizes to the max-sum algorithm on arbitrary graphical models (Bayesian networks, Markov random fields, CRFs).

### RL-Based Path Finding Has Overtaken HMM

**MINERVA** (Das et al., ICLR 2018) uses RL to learn query-conditioned walks on knowledge graphs. Advantages over Viterbi:
- No prespecified transition probabilities (learned from data)
- Handles combinatorially many paths via learned policy
- Reasoning paths are interpretable

Follow-up work:
- Multi-hop reasoning with reward shaping (Lin et al., EMNLP 2018) -- handles incomplete KGs
- Path spuriousness-aware RL (EACL 2023) -- avoids paths that reach correct answers by accident

### Comparison

| Approach | When to Use |
|----------|-------------|
| BFS + hub damping (current) | Simple, fast, no training needed. Good for exploring neighborhood. |
| Viterbi / max-sum | When you have a known probabilistic model of the graph. Good for finding single best path. |
| RL path finding (MINERVA) | When you can train on query-answer pairs. Best quality but needs data. |
| Beam search | Middle ground: explores top-k paths simultaneously. No training needed. |

**Recommendation for v1:** Stick with BFS + hub damping. Add beam search as an alternative for L3 deep queries. Viterbi is intellectually sound but RL has overtaken it. Consider MINERVA-style path finding for v2 if we accumulate enough query-outcome data from the feedback loop.

**Sources:**
- [MINERVA (ICLR 2018)](https://arxiv.org/pdf/1711.05851)
- [Multi-hop reasoning with reward shaping (EMNLP 2018)](https://aclanthology.org/D18-1362.pdf)
- [Graph optimization with HMMs (Journal of Big Data, 2021)](https://journalofbigdata.springeropen.com/articles/10.1186/s40537-021-00485-z)

---

## 4. Shannon Entropy and Boolean Similarity

### Shannon Entropy of Beta Distributions = Exploration Bonus

This connection is direct and already in our architecture:

```
H[Beta(alpha, beta)] = log B(alpha, beta)
                     - (alpha - 1) * psi(alpha)
                     - (beta - 1) * psi(beta)
                     + (alpha + beta - 2) * psi(alpha + beta)

Where B is the Beta function and psi is the digamma function.
```

High entropy = uncertain = worth testing = exploration bonus in the expected utility ranking. This is the same principle as **information gain in active learning**: test the belief that resolves the most uncertainty.

### Mutual Information for Retrieval Ranking

MI-RAG (Springer KAIS, 2025) uses mutual information as the evaluation metric for subgraph retrieval. The scoring function:

```
MI(belief, query) = H(belief) - H(belief | query)
                  = how much knowing the query reduces uncertainty about the belief
```

A high MI score means the belief is highly relevant to the query. This is more principled than cosine similarity or BM25, which measure surface-level overlap rather than information content.

### Jaccard Similarity and MinHash for Dedup

For our content-hash dedup layer:
- **Jaccard similarity** J(A,B) = |A intersect B| / |A union B| on token/concept sets
- **MinHash** creates compact signatures preserving Jaccard: P(hash match) = J(A,B)
- Two beliefs with J > 0.8 are probably duplicates; add evidence link instead of creating new belief

This is more nuanced than SHA-256 content hashing, which only catches exact duplicates. MinHash catches near-duplicates (same belief, different wording).

**Sources:**
- [Shannon Entropy (Wikipedia)](https://en.wikipedia.org/wiki/Entropy_(information_theory))
- [MI-RAG (Springer KAIS, 2025)](https://link.springer.com/article/10.1007/s10115-025-02624-x)
- [Active learning with Shannon entropy (IEEE 2020)](https://ieeexplore.ieee.org/document/9199831/)

---

## 5. Unified Information-Theoretic Memory Framework

### Memory as a Communication Channel

**"An Information-Theoretic Framework for RAG Systems"** (Electronics, 2025) models RAG as four cascading information channels. Key result: end-to-end performance is bounded by the minimum capacity across all channels (Shannon's data processing inequality). The retrieval channel is typically the bottleneck.

Applied to our system:

```
Observation channel:  raw events -> observations          (high bandwidth, low loss)
Extraction channel:   observations -> beliefs             (lossy, this is where quality matters)
Storage channel:      beliefs -> graph + SQLite            (lossless, capacity = disk)
Retrieval channel:    query -> relevant beliefs            (THE BOTTLENECK: token budget limits)
Integration channel:  beliefs -> agent context             (formatting, budget packing)
```

The token budget (L0=100, L1=500, L2=1000 tokens) is a hard capacity constraint on the retrieval channel. Information theory tells us we should maximize mutual information between the query and retrieved beliefs within that budget.

### The Information Bottleneck

Tishby et al. (1999): minimize I(X;T) (compression) subject to maintaining I(T;Y) (relevance).

For our memory system: T is the compressed belief representation, X is the full observation, Y is the query relevance. The information bottleneck tells us the optimal compression -- how short a belief can be while preserving its relevance to future queries.

This is more principled than MemPalace's AAAK compression or heuristic summarization. It could determine the optimal belief content length, not as an arbitrary character limit, but as the information-theoretically optimal representation.

### Rate-Distortion for Working Memory

Jakob & Gershman (eLife, 2023) formalized working memory as a rate-distortion problem:
- Minimize expected distortion D subject to rate constraint R <= C
- When more items compete for encoding, precision decreases to stay within capacity
- Validated against monkey prefrontal cortex recordings

This directly models our L1/L2 budget allocation problem. When more beliefs are relevant (high-density topic), each gets less token budget (lower resolution projection). Rate-distortion theory can optimize this allocation.

**Sources:**
- [IT Framework for RAG (Electronics, 2025)](https://www.mdpi.com/2079-9292/14/15/2925)
- [Information Bottleneck (Tishby, 1999)](https://en.wikipedia.org/wiki/Information_bottleneck_method)
- [Deep Learning and Information Bottleneck (arXiv:1503.02406)](https://arxiv.org/abs/1503.02406)
- [Rate-distortion for working memory (eLife, 2023)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10353860/)

---

## 6. Closest Existing System: SuperLocalMemory V3

SuperLocalMemory V3 (arXiv:2603.14588) is doing something very close to what we're building. Key overlap:

| Their Approach | Our Approach | Comparison |
|---|---|---|
| Fisher Information retrieval metric | BFS + BM25 + Bayesian confidence ranking | They're more mathematically rigorous; we're more practical |
| Riemannian Langevin dynamics for decay | No decay; revision mechanism instead | Different philosophies: they forget gracefully, we supersede explicitly |
| Cellular sheaf cohomology for contradictions | CONTRADICTS edges + Bayesian conflict resolution | They have a mathematical guarantee (non-trivial H^1 = irreconcilable); we have a practical workflow |
| Four-channel retrieval | Hybrid FTS5 + BFS + confidence ranking | Similar spirit, different implementation |
| Bayesian trust scoring | Bayesian belief confidence | Same Beta-Binomial foundation |

**Where we differentiate:**
1. Scientific method model (observation/belief/test/revision) vs their memory categories
2. Test feedback loop with Bayesian updating -- they don't close this loop
3. Session recovery as a first-class feature
4. Zero-LLM default (they require LLM for Mode C, their best-performing mode)
5. Cross-model MCP interface

**Where they're ahead:**
1. Fisher Information metric is more principled than BM25
2. Sheaf cohomology for contradiction detection has mathematical guarantees
3. They have published benchmark results (75% zero-LLM, 87.7% with LLM on LoCoMo)

**Sources:**
- [SuperLocalMemory V3 (arXiv:2603.14588)](https://arxiv.org/abs/2603.14588)
- [SuperLocalMemory V3.3 (arXiv:2604.04514)](https://arxiv.org/abs/2604.04514)
- [GitHub: qualixar/superlocalmemory](https://github.com/qualixar/superlocalmemory)

---

## 7. Integration Recommendations

### v1 (practical, implementable now)

1. **MinHash for near-duplicate detection** -- upgrade from exact SHA-256 to approximate Jaccard similarity. Catches "same belief, different wording" duplicates. Low implementation cost.

2. **Shannon entropy as exploration bonus** -- already designed into MACLA-inspired EU ranking. Make the connection to information gain explicit in documentation and measurement.

3. **Information Bottleneck framing for token budget** -- use IB theory to reason about optimal belief compression rather than arbitrary character limits.

4. **Beam search as L3 alternative** -- for deep queries, explore top-k paths simultaneously instead of BFS. No training needed, better than BFS for finding specific distant targets.

### v2 (research-grade, needs more work)

5. **Holographic Reduced Representations for belief encoding** -- encode beliefs as hyperdimensional vectors with typed edge binding. Enables composable queries and graceful degradation. Adds vector computation overhead.

6. **Mutual information scoring for retrieval** -- replace BM25 with MI-based scoring per Phadke (2025). More principled but requires estimating mutual information.

7. **Fisher Information retrieval metric** -- per SuperLocalMemory V3. More geometrically principled than cosine similarity. Requires computing Fisher information of belief distributions.

8. **MINERVA-style RL path finding** -- learn query-conditioned graph walks from accumulated feedback data. Requires training infrastructure and enough query-outcome pairs.

### Probably not worth pursuing

9. **Full sheaf cohomology for contradiction detection** -- mathematically elegant but overkill. Our CONTRADICTS edges + Bayesian comparison + human resolution workflow is simpler and more transparent.

10. **Riemannian Langevin dynamics for decay** -- we've deliberately chosen "no decay, only revision." Adding stochastic decay contradicts our design principle that nothing is forgotten, only downgraded.
