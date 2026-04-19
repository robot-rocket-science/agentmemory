# Holographic Reduced Representations: Mathematical Reference

**Date:** 2026-04-09
**Status:** Reference document -- math, properties, and application to belief graph retrieval
**Applies to:** agentmemory architecture, A016 (APPROACHES.md)

---

## 1. Setup

All vectors are n-dimensional real-valued: v in R^n, n typically 512-8192.

Vectors are drawn from N(0, 1/n) -- zero mean, variance 1/n per component. This normalization makes the expected dot product between two random vectors exactly 0, and the variance of the dot product 1/n. As n grows, random vectors become nearly orthogonal with high probability:

```
P( |cos(a, b)| > eps )  <  2 * exp( -n * eps^2 / 2 )
```

This exponential concentration is the foundation everything else rests on. At n=512, two random vectors have cosine similarity within +/-0.1 of zero with probability ~0.9999.

---

## 2. The Three Operations

### 2.1 Circular Convolution (Binding):  a * b

```
(a * b)[k] = sum_{j=0}^{n-1}  a[j] * b[(k-j) mod n]
```

Efficient computation via FFT (O(n log n)):

```
a * b = IFFT( FFT(a) .* FFT(b) )
```

where .* is elementwise multiplication of complex vectors.

**Properties:**
- Commutative:    a * b = b * a
- Associative:    (a * b) * c = a * (b * c)
- Distributes over addition:  a * (b + c) = a*b + a*c
- Same dimensionality as inputs (the holographic property)
- Result is approximately orthogonal to both a and b:
    cos(a*b, a) ≈ 0,   cos(a*b, b) ≈ 0
- Acts as multiplication in the Fourier domain -- convolution in time = product in frequency

The result looks like noise to an outside observer, but contains the bound information
retrievable by the inverse operation.

### 2.2 Circular Correlation (Approximate Unbinding):  a # b

```
(a # b)[k] = sum_{j=0}^{n-1}  a[j] * b[(k+j) mod n]
```

In Fourier space (note conjugate instead of product):

```
a # b = IFFT( conj(FFT(a)) .* FFT(b) )
```

Correlation is the approximate inverse of convolution. If c = a * b, then:

```
a # c = a # (a * b) = (a # a) * b ≈ delta * b = b
```

This works because the circular autocorrelation of a random vector approximates a delta
function:

```
(a # a)[0]   ≈ 1         (self-similarity peak)
(a # a)[k>0] ≈ N(0, 1/n) (off-peak noise)
```

The approximation improves with n. At n=512, signal-to-noise ratio is approximately
sqrt(512) ≈ 22.6 after a single bind/unbind cycle.

**Key asymmetry:** a * b = b * a (convolution commutes), but a # b != b # a (correlation
does not commute). This means unbinding is directional:

```
a # (a * b) ≈ b    (recover b given a)
b # (a * b) ≈ a    (recover a given b)
```

Both directions work -- you can retrieve either element of a bound pair given the other.

### 2.3 Superposition (Bundling):  a + b

Plain vector addition. The result is similar to all constituent vectors:

```
cos(a + b, a) ≈ 1/sqrt(2)  ≈  0.707
cos(a + b, b) ≈ 1/sqrt(2)  ≈  0.707
cos(a + b, c) ≈ 0           (for random c unrelated to a or b)
```

Superposition encodes multiple bindings in a single vector. A superposition of k bound
pairs:

```
S = (a1 * b1) + (a2 * b2) + ... + (ak * bk)
```

When queried with a1:

```
a1 # S = a1 # (a1*b1) + a1 # (a2*b2) + ... + a1 # (ak*bk)
       ≈ b1  + noise    + noise    + ... + noise
```

Each cross-term a1 # (ai * bi) for i != 1 is noise (size ~1/sqrt(n)) because a1 is
approximately orthogonal to ai. The signal-to-noise ratio is:

```
SNR ≈ sqrt(n) / sqrt(k-1)  ≈  sqrt(n/k)
```

**Capacity:** A superposition of k bindings remains queryable (SNR > 1) while:

```
k < n
```

In practice, reliable retrieval degrades around k ≈ n/10 for single-element queries.
At n=1024, you can superpose ~100 bindings and still retrieve individuals reliably.

---

## 3. Encoding a Typed Graph

### Node vectors

Each unique entity (node, concept, belief) is assigned a random vector:

```
node_A = random_unit_vector()
node_B = random_unit_vector()
```

Node vectors are stored in a cleanup memory (lookup table) for nearest-neighbor matching.

### Edge type vectors

Each edge type is a distinct random vector:

```
SUPPORTS    = random_unit_vector()
CONTRADICTS = random_unit_vector()
CITES       = random_unit_vector()
TEMPORAL_NEXT = random_unit_vector()
SOURCED_FROM  = random_unit_vector()
```

Edge type vectors are fixed and shared across all edges of that type.

### Encoding a directed edge

Edge  A -[SUPPORTS]-> B  is encoded as:

```
e_AB = node_A * SUPPORTS
```

This produces a vector that, when queried with node_A, approximately recovers SUPPORTS,
and when used as part of a larger superposition, allows retrieval of B via:

```
query = node_A * SUPPORTS   (reconstruct the bound vector)
result = nearest_neighbor(query, all_node_vectors)  -->  node_B
```

Alternatively, store the full triple:

```
e_AB = node_A * SUPPORTS * node_B
```

which enables bidirectional lookup and typed multi-hop.

### Encoding a subgraph

Superpose all edges:

```
S = (node_A * SUPPORTS * node_B)
  + (node_A * CITES    * node_C)
  + (node_B * SUPPORTS * node_D)
  + ...
```

S is a single vector of dimension n containing the entire subgraph.

---

## 4. Traversal

### Single-hop forward traversal

"What does A support?"

```
query = node_A * SUPPORTS
result_vec = query # S
best_match = nearest_neighbor(result_vec, all_node_vectors)
--> node_B
```

### Single-hop reverse traversal

"What supports B?"

```
query = node_B * SUPPORTS    (note: correlation is directional)
result_vec = query # S
best_match = nearest_neighbor(result_vec, all_node_vectors)
--> node_A
```

### Multi-hop traversal (no intermediate nodes visited)

"What does A support that also cites something?"

```
A -[SUPPORTS]-> B -[CITES]-> C

result_vec = (node_A * SUPPORTS * CITES) # S
best_match = nearest_neighbor(result_vec, all_node_vectors)
--> node_C
```

The composition node_A * SUPPORTS * CITES is computed in O(n log n). No BFS, no
intermediate node lookup. The entire two-hop traversal is a single vector operation.

This generalizes to arbitrary depth:

```
k-hop result = (node_A * e1 * e2 * ... * ek) # S
```

where e1..ek are the edge type vectors for each hop. Still O(n log n) per operation,
O(k * n log n) total. Graph size does not appear in the complexity.

### Edge-type selective traversal

Because edge type vectors are random and nearly orthogonal to each other:

```
SUPPORTS # (node_A * CONTRADICTS * node_B) ≈ 0
```

Querying with SUPPORTS selectively activates SUPPORTS edges in the superposition.
CONTRADICTS edges contribute only noise. This is geometric selectivity -- no filtering
code required.

---

## 5. Cleanup Memory

After unbinding, the recovered vector is approximate (corrupted by noise from other
superposed bindings). To identify the intended node, compare against all known node
vectors and return the nearest neighbor by cosine similarity:

```
result_vec = (query) # S                         (approximately noisy)
best = argmax_v  cos(result_vec, v)  for v in all_node_vectors
```

This is the "item memory" or "cleanup memory" in VSA terminology. At small scale
(< 100K nodes), linear scan is fine. At larger scale, use approximate nearest neighbor
(HNSW, FAISS).

---

## 6. Capacity and Error Analysis

### Single binding SNR

After one bind/unbind cycle with no superposition:

```
SNR = cos(recovered, target) / std(noise)  ≈  1.0 / sqrt(1/n) = sqrt(n)
```

At n=512: SNR ≈ 22.6
At n=1024: SNR ≈ 32.0
At n=4096: SNR ≈ 64.0

### Superposition of k bindings

```
SNR ≈ sqrt(n) / sqrt(k-1)
```

Retrieval probability > 0.99 requires SNR > ~3, which gives:

```
k_max ≈ n / 9
```

At n=1024: ~113 bindings reliable
At n=4096: ~455 bindings reliable

For a belief graph with thousands of edges, store subgraph-level superpositions (by
task domain, topic cluster, etc.) rather than a single global superposition.

### Multi-hop SNR degradation

Each additional hop multiplies the noise:

```
SNR(k hops) ≈ (sqrt(n))^k / sqrt(k * (k_bindings - 1))
```

In practice, 2-3 hops are reliable at n=1024 with moderate superposition load.
Beyond 3 hops, dimensionality must increase or intermediate cleanup steps are needed.

---

## 7. Connection to Transformer Attention (Bricken & Pehlevan, NeurIPS 2021)

Transformer attention:

```
Attention(Q, K, V) = softmax( Q K^T / sqrt(d) ) * V
```

Kanerva SDM (Sparse Distributed Memory, 1988):
- Hard addresses: binary hypervectors in {0,1}^n
- Storage: write content c to all addresses within Hamming radius r of address a
- Retrieval: for query q, activate all stored addresses within radius r, return
  weighted sum of their contents

Bricken & Pehlevan showed: with L2-normalized vectors and softmax temperature
beta = 1/sqrt(d), transformer attention converges to SDM retrieval. The softmax
is a smooth relaxation of SDM's hard Hamming threshold. Confirmed empirically in
pre-trained GPT-2 -- attention patterns match SDM intersection geometry.

**Implication:** LLM attention layers are already performing holographic distributed
memory retrieval over the context window. An external HRR memory system augments an
internal one using the same mathematical primitives. The external system provides
persistence and structure; the internal one provides in-context integration.

---

## 8. Why HRR is NOT the Same as Bag-of-Words + Cosine Similarity

A naive implementation that encodes text as a sum of random word vectors and retrieves
by cosine similarity is NOT using HRR's unique capabilities. That is a random projection
of a bag-of-words model -- it approximates TF-IDF in a lower-dimensional space and will
perform similarly to FTS5 (BM25).

HRR's distinguishing capabilities are:

1. **Compositional queries:** Binding multiple roles/relations into a single query vector.
   BoW cannot do this -- there is no notion of "A supports something that cites B."

2. **Multi-hop traversal in vector space:** Successive convolution traverses graph edges
   without BFS. BoW retrieval requires explicit graph traversal.

3. **Edge-type selectivity:** Orthogonal edge type vectors filter traversal directions
   geometrically. BoW has no mechanism for typed edge filtering.

4. **Subgraph superposition:** An entire subgraph is a single vector. Query it from any
   angle. BoW stores documents independently with no structural composition.

If an HRR experiment shows performance equivalent to FTS5, the binding/unbinding
operations are not being used -- only the cosine similarity step. See EXPERIMENTS.md
Exp 24 and Exp 25 for comparison.

---

## 9. Exp26 Findings: Real HRR vs BFS on Alpha-Seek Graph (2026-04-09)

### Setup
- 586 nodes, 775 typed edges (CITES, RELATES_TO, DECIDED_IN, SOURCED_FROM)
- n=8192 (covers 775 edges with ~135 bindings of headroom above capacity floor)
- Ground truth: BFS on SQLite (exact)
- HRR: bound triples convolve(node_A, edge_type, node_B), superposed into S

### Results

| Query Type | P@5 | R@5 | P@10 | R@10 |
|---|---|---|---|---|
| Single-hop forward (CITES) | 0.133 | 0.500 | 0.092 | 0.667 |
| Single-hop reverse (CITES) | 0.283 | 0.794 | 0.167 | 0.881 |
| Two-hop (CITES->DECIDED_IN) | 0.000 | 0.000 | 0.000 | 0.000 |

### Why Single-Hop Works

At n=8192 with 775 bindings, SNR ≈ sqrt(8192/775) ≈ 3.3 -- marginally above reliable threshold.
Single-hop forward R@10=0.667 and reverse R@10=0.881 demonstrate real HRR retrieval.
Reverse outperforms forward because correlate(convolve(edge_type, node_target), S) gets
cleaner separation than the forward direction at this capacity level.

### Why Two-Hop (S^2) Failed Completely

The S^2 approach -- convolve(S, S) to approximate 2-hop reachability -- failed:
- We are at 85% of theoretical capacity (775/910). S is near-saturated.
- convolve(S, S) convolves two near-saturated superpositions. Noise compounds.
- The B*B ≈ delta approximation (required for the 2-hop math) breaks down when B
  appears simultaneously across hundreds of entangled bindings in S.

### Why S^2 Is The Wrong Approach, Not Just Underpowered

For reliable two-hop via S^k, dimensionality must scale roughly as n > k^2 * edges:
- 2 hops, 775 edges: n > ~66,000
- 2 hops, 10,000 beliefs: n > ~11,000,000
Not practical at any useful scale.

### The Correct Two-Hop Approach: Iterative with Cleanup

```
hop1_noisy   = correlate(query_vec, S)
clean_node_B = nearest_neighbor(hop1_noisy, node_vecs)   # cleanup memory
hop2_noisy   = correlate(convolve(clean_node_B, e2_vec), S)
clean_node_C = nearest_neighbor(hop2_noisy, node_vecs)
```

No LLM calls. Pure FFT + dot-product. Each hop resets noise to zero via cleanup.
Complexity: O(k * n log n) where k = number of hops. Graph size does not appear.

This is vectorized BFS: same hops as BFS, just via FFT correlation instead of SQL joins,
with nearest-neighbor lookup at each step instead of index scan.

### The Real Advantage Over BFS: Fuzzy Starting Queries

BFS requires an exact source node ID. HRR iterative can start from an approximate query
vector -- a description encoded as a sum of word vectors -- and land on the nearest node
even without an exact match.

Use case: "Find decisions related to dispatch-gate-like constraints" -- no exact node ID.
HRR: encode the description, find nearest node_B, run BFS from node_B.
BFS alone: requires knowing the node ID of node_B first.

HRR earns its cost when the traversal's starting point is itself fuzzy. For exact-ID
queries, BFS on SQLite is simpler, faster, and exact.

## 10. Empirical Hop Depth Measurements (from cross-project reference graphs, 2026-04-10)

### Setup

We built document reference graphs from 4 projects' markdown files (parsing D###/M### cross-references as edges) and measured what fraction of reachable node pairs are within N hops:

| Project | Nodes | Edges | 1-hop | 2-hop cum | 3-hop cum | Max useful depth |
|---|---|---|---|---|---|---|
| project-a | 101 | 603 | 10.0% | 83.1% | 99.7% | 3 |
| project-d | 85 | 196 | 6.7% | 46.4% | 77.4% | 5 |
| gsd-2 | 214 | 562 | 2.7% | 26.1% | 66.7% | 5 |
| project-b | 929 | 6558 | 1.4% | 26.7% | 81.3% | 4 |

### Key Implications for HRR Multi-Hop

1. The earlier conclusion that "multi-hop doesn't matter, just use fuzzy-start" was calibrated on project-a, which has an unusually shallow graph (83% within 2 hops). For sparser projects like gsd-2 and project-d, 2 hops only covers 26-46%. Multi-hop traversal IS needed for these project types.

2. S^2 (2-hop HRR) covers 83% of connections in project-a but only 26-46% in deeper projects. The question "can S^2 work mathematically" is less important than "do we need more than 2 hops" -- and the answer is project-dependent.

3. Graph topology predicts required traversal depth. Dense citation graphs (project-a: avg degree ~12) are shallow. Sparse planning graphs (project-d: avg degree ~4.6) are deep. This is measurable at graph construction time.

4. The recommended architecture: HRR single-hop for fuzzy entry + BFS depth 3-4 from entry points. The memory system should detect topology at construction time and set traversal depth accordingly.

5. This is a correction to the earlier finding. The original HRR research was done on project-a only, which gave a misleadingly optimistic picture of how far single-hop retrieval gets you. Cross-project testing revealed the bias.

---

## Sources

- [HRR (Plate, 1995)](https://ieeexplore.ieee.org/document/377968/)
- [Learning with HRRs (Ganesan et al., NeurIPS 2021)](https://proceedings.neurips.cc/paper/2021/file/d71dd235287466052f1630f31bde7932-Paper.pdf)
- [Attention Approximates SDM (Bricken & Pehlevan, NeurIPS 2021)](https://arxiv.org/abs/2111.05498)
- [Sparse Distributed Memory (Kanerva, 1988)](https://mitpress.mit.edu/9780262111911/)
- [VSA Survey Part I (ACM 2022)](https://dl.acm.org/doi/10.1145/3538531)
