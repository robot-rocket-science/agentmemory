# Exp 23: Gray Code Binary Encoding for Semantic Similarity

**Date:** 2026-04-09
**Input:** 1,195 sentence-level belief nodes from Exp 16

## 1. Gray Code and Hypercube Traversal

An n-bit Gray code is a sequence of all 2^n binary strings where consecutive strings differ
in exactly 1 bit. This is equivalent to a Hamiltonian path on the n-dimensional hypercube
graph Q_n, where vertices are n-bit strings and edges connect strings differing in 1 bit.

For belief encoding, the key property is: if we assign belief nodes to hypercube vertices
such that semantically similar beliefs get Gray-code-adjacent codes, then Hamming distance
between any two codes approximates their semantic distance. A 1-bit difference = immediate
neighbor; a k-bit difference = k hops on the hypercube.

The tesseract (4-cube, Q_4) has 16 vertices and a Gray code traversal visits all 16 by
flipping one bit at a time. Scale this to n=128: the hypercube has 2^128 vertices, and our
1,195 nodes occupy a sparse subset. The challenge is not enumerating the hypercube -- it is
assigning nodes to vertices so that the Hamming metric is semantically meaningful.

Source: Wikipedia, "Gray code"; Savage, "A Survey of Combinatorial Gray Codes" (1997)

## 2. Semantic Hashing (Salakhutdinov & Hinton 2009)

Semantic hashing trains a deep autoencoder (stack of RBMs) to compress documents into binary
codes such that similar documents land at nearby Hamming addresses. The encoder learns to
push activations toward 0/1, producing compact binary codes.

**Can we skip the deep autoencoder?** Yes. The core insight -- Hamming distance as similarity
metric -- does not require learned representations. Simhash and random projection achieve the
same structural goal (binary codes where Hamming ~ semantic distance) without training. The
autoencoder gives better codes for a given bit-width, but at 1K nodes the gap is small.

Source: Salakhutdinov & Hinton, "Semantic Hashing," Int. J. Approximate Reasoning, 2009

## 3. Simhash / Random Hyperplane Projection

Simhash (Charikar 2002) works as follows:
1. Compute a real-valued vector for each node (TF-IDF, sentence embedding, etc.)
2. Generate k random hyperplanes (k = desired bit-width)
3. For each node, each bit = sign(dot(vector, hyperplane_normal)): 0 or 1
4. The resulting k-bit code preserves cosine similarity as Hamming similarity

This is zero-LLM, zero-training, and fast. For 1,195 nodes with TF-IDF vectors:
- Build TF-IDF matrix: ~1,195 x V (V = vocabulary, typically 2K-5K for sentence nodes)
- Generate 128 random unit vectors in R^V
- Multiply: 1,195 x V times V x 128 = 1,195 x 128 matrix
- Threshold at 0: binary codes

Total compute: under 1 second on a laptop. No GPU, no API calls.

**Theoretical guarantee (Johnson-Lindenstrauss):** Pr[h(a) != h(b)] = theta(a,b)/pi, where
theta is the angle between vectors a and b. Hamming distance is an unbiased estimator of
angular distance, which is monotonically related to cosine similarity.

Source: Charikar, "Similarity Estimation Techniques from Rounding Algorithms," STOC 2002

## 4. LSH Indexing for Hamming Distance

For fast nearest-neighbor lookup on binary codes, multi-probe LSH or multi-index hashing:
- **Multi-index hashing (Norouzi et al. 2012):** Split the b-bit code into m substrings.
  Build a hash table on each substring. Query by looking up exact matches in each substring
  table, then verify full Hamming distance on candidates. For 128-bit codes split into 4
  chunks of 32 bits, this gives sub-linear lookup.
- **At 1K-10K nodes, brute force wins.** Hamming distance on 128-bit integers is a single
  popcount instruction. Scanning 10K codes = 10K popcount ops = microseconds. LSH indexing
  only matters above ~100K nodes.

Source: Norouzi et al., "Fast Exact Search in Hamming Space," IEEE TPAMI, 2014

## 5. Dimensionality: How Many Bits?

**Capacity:** n bits can address 2^n unique codes. We need at least ceil(log2(1195)) = 11
bits to uniquely encode all nodes. But we need slack for semantic separation.

**Empirical guidance from semantic hashing literature:**
- 32 bits: works for coarse similarity (topic-level clustering)
- 64 bits: good for medium-grained similarity among <10K documents
- 128 bits: fine-grained similarity, preserves subtle distinctions
- 256 bits: diminishing returns for our scale, useful above 100K docs

**Recommendation for 1,195 nodes: 128 bits.** This gives ~2^128 / 1,195 ~ 10^35 available
codes per node -- enormous slack for semantic separation. 64 bits would also work but 128
gives headroom for growth to 10K nodes and finer distinctions between belief types.

## 6. Practical Prototype Path

```
Sentence nodes (1,195 texts)
    |
    v
TF-IDF vectorization (scikit-learn, V ~ 3K terms)
    |
    v
Random projection to 128 dims (numpy: W ~ N(0,1), shape V x 128)
    |
    v
Sign threshold -> 128-bit binary codes
    |
    v
Hamming distance matrix (scipy.spatial.distance.hamming or popcount)
    |
    v
Gray code ordering: sort codes by reflected Gray code for traversal
```

**Expected quality:** Simhash on TF-IDF will cluster nodes that share key terms. Nodes about
"walk-forward evaluation" will have similar codes; nodes about "capital allocation" will have
different codes. It will NOT capture deep semantic similarity (paraphrase detection) -- for
that you would need embedding-based vectors (e.g., sentence-transformers) as the input to
random projection. But TF-IDF is a solid zero-dependency starting point.

**Gray code ordering caveat:** A reflected Gray code gives ONE Hamiltonian path through the
hypercube. Our 1,195 nodes are a sparse subset of 2^128 vertices. Ordering them by their
position on the Gray code path gives a 1D traversal where consecutive nodes tend to be
similar -- but it is a lossy projection of 128D structure onto 1D. It is useful for sequential
scanning, not as a replacement for Hamming-based k-NN.

## 7. Connection to the Directed Graph

Binary codes are a LAYER on the existing belief graph, not a replacement:

- **Graph edges** = precise semantic relationships (supports, contradicts, refines, scopes)
- **Binary codes** = approximate neighborhood membership ("which cluster is this belief in?")

Use cases for the binary code layer:
1. **Fast approximate retrieval:** Given a query, encode it to 128 bits, find all nodes
   within Hamming distance <= 5. This is the candidate set. Then re-rank with graph edges.
2. **Neighborhood discovery:** Two nodes with Hamming distance 2 but no graph edge between
   them are candidates for edge discovery -- they are topically related but unlinked.
3. **Compression routing:** When context budget is tight, load the Hamming neighborhood
   (cheap to compute) rather than traversing graph edges (which may pull in distant nodes).
4. **Drift detection:** If a new belief's binary code is far from all existing codes, it
   represents a genuinely new topic -- flag it for the agent.

The binary code layer costs 128 bits x 1,195 nodes = ~19 KB. Negligible storage. The
Hamming distance matrix (1,195 x 1,195) is ~1.4M entries, storable as uint8 (max Hamming
distance 128 fits in a byte) = ~1.4 MB. Both fit in memory trivially.

## Next Steps

1. Implement simhash on Exp 16 sentence nodes (TF-IDF + random projection)
2. Compute Hamming distance matrix, compare against cosine similarity on TF-IDF
3. Evaluate: do small Hamming distances correspond to semantically related beliefs?
4. If yes, integrate as a retrieval layer in the prototype
