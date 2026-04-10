# Exp 20: Information Bottleneck for Belief Compression

**Date:** 2026-04-09
**Input:** Exp 16 results (1,195 sentence nodes, 36K tokens, 6 types)

## 1. The Information Bottleneck (Formal)

Tishby, Pereira & Bialek (1999) define IB as finding a compressed representation T of input X
that preserves maximal information about a relevance variable Y:

    min_{p(t|x)} I(X;T) - beta * I(T;Y)

- I(X;T) = cost of the representation (how much of X we keep)
- I(T;Y) = utility of the representation (how much it tells us about Y)
- beta = tradeoff parameter. beta -> 0 = maximum compression, beta -> inf = no compression

The IB curve traces the Pareto frontier of compression vs. relevance. Every point on
that curve is optimal -- you cannot get more relevance for less bits at that operating point.

Source: Tishby et al., "The Information Bottleneck Method," 1999 (arXiv:physics/0004057)

## 2. Mapping IB to Belief Nodes

For our system:
- X = full sentence-level belief node (e.g., "Select contracts with enough convexity that
  a recovery move delivers >=2x." -- 18 tokens)
- T = compressed representation of that node
- Y = query relevance (does this node help answer a retrieval query?)

The IB question becomes: what is the shortest representation of each belief node that
preserves its ability to be retrieved by relevant queries and understood by the agent?

This is exactly rate-distortion: we want the minimum-rate encoding that keeps distortion
(retrieval failure, misunderstanding) below a threshold.

## 3. Practical Computation

**Classical IB (Blahut-Arimoto):** Iterative algorithm on discrete distributions p(x), p(y|x).
Requires enumerating all x values and computing joint distributions. For 1,195 nodes this is
tractable -- the bottleneck is estimating p(y|x), which requires a relevance model.

**Variational IB (Alemi et al., 2017):** Uses neural networks to parameterize the encoder
p(t|x). Applicable when X is continuous (embeddings). Trains via SGD on:
    L = I(X;T) - beta * I(T;Y)
with I(X;T) bounded by a KL term and I(T;Y) bounded by a variational decoder.

**Deep IB:** Same idea, deeper networks. Overkill for our scale.

**Practical for us:** We do not need to run IB optimization. The theoretical framework
gives us the *principle* -- compress to preserve retrieval relevance -- and the type
classification from Exp 16 already approximates the IB solution by hand:

| Type        | Count | Avg Tokens | IB Interpretation                          |
|-------------|-------|------------|--------------------------------------------|
| constraint  | 132   | 36.7       | High I(T;Y) -- must preserve nearly fully  |
| evidence    | 349   | 28.5       | Medium I(T;Y) -- core claim matters        |
| context     | 585   | 30.2       | Low I(T;Y) -- most compressible            |
| rationale   | 39    | 35.1       | Low I(T;Y) unless debugging a decision     |
| supersession| 47    | 28.3       | Temporal pointer -- compress to reference   |
| implementation| 43  | 32.6       | Low I(T;Y) -- operational detail           |

## 4. Connection to Rate-Distortion (Jakob & Gershman 2023)

Jakob & Gershman model working memory as a rate-distortion problem: the brain compresses
observations into a capacity-limited working memory, keeping what predicts future reward.
Their key result: optimal memory is *lossy* and *task-dependent*.

This maps directly to our system:
- Working memory = agent context window (limited tokens)
- Rate = tokens used by belief nodes in context
- Distortion = retrieval failures + stale/wrong beliefs influencing decisions
- Task = current query/agent objective

The implication: there is no single "right" compression level. Optimal compression depends
on the query. A constraint node should be nearly lossless when the query touches that
constraint's domain, but can be heavily compressed (or omitted) for unrelated queries.

Source: Jakob & Gershman, "Rate-distortion theory of neural coding and its implications for
working memory," 2023 (PsyArXiv, also presented at CogSci 2023)

## 5. Can IB Determine Optimal Belief Length?

Yes, in principle. The IB curve tells us the minimum bits needed at each relevance threshold.
But computing it requires:
1. A relevance model p(y|x) -- which queries does each node serve?
2. A compression model p(t|x) -- how to shorten each node?

We can approximate this empirically without full IB optimization:
- Take each node, progressively truncate/compress it
- Measure retrieval recall at each compression level (using Exp 3's eval framework)
- The point where recall drops sharply = the IB-optimal length for that node type

Predicted results based on the type structure:
- **Constraints (132 nodes):** Near-lossless. Average 36.7 tokens is already compact.
  Compressing below ~30 tokens likely drops critical specifics.
- **Context (585 nodes):** Highly compressible. Many are elaborations. Could compress
  to ~15-20 tokens (50% reduction) with minimal retrieval loss.
- **Evidence (349 nodes):** Moderate compression. The core claim in ~20 tokens suffices.
- **Rationale/Implementation (82 nodes):** Aggressive compression or omit at retrieval
  time unless the query specifically asks "why" or "how."
- **Supersession (47 nodes):** Compress to pointer format: "D097 supersedes D045" (~8 tokens).

Estimated savings: from 35,741 tokens to ~22,000-25,000 tokens (30-38% reduction)
while preserving retrieval quality for the important node types.

## 6. Tractability at Our Scale

**1K nodes (current):** Trivially tractable. Even full Blahut-Arimoto runs in seconds.
The bottleneck is building the relevance model, not the IB computation itself.

**10K nodes (projected):** Still tractable for classical IB on discrete types. If we
use embeddings + variational IB, training takes minutes on a laptop GPU.

**100K+ nodes:** Would need approximate methods, but we would also need hierarchical
organization at that point (decisions > topics > domains), and IB could operate at
each level independently.

The real cost is not IB computation -- it is building the evaluation data (queries +
relevance judgments) needed to estimate p(y|x). We partially have this from Exp 3.

## 7. IB vs. Simple Heuristics

**Simple heuristic: keep first sentence of each decision.**
- Captures the primary assertion ~70% of the time
- Misses constraints stated in sentence 2+ (~30% of constraints are not sentence 0)
- Misses cross-references entirely
- Estimated retrieval recall: ~60-70% vs. full nodes

**Type-aware heuristic (from Exp 16): keep constraints + first evidence sentence.**
- Preserves all 132 core constraint nodes fully
- Keeps the lead assertion from evidence nodes
- Drops context/rationale/implementation unless queried
- Estimated retrieval recall: ~85-90%
- Token cost: ~7,000-8,000 tokens (vs. 35,741 full, vs. 4,839 core-only)

**Full IB-optimal compression: type-specific compression ratios.**
- Best theoretical performance but requires building the relevance model
- Marginal gain over type-aware heuristic: likely 3-5% retrieval improvement
- Engineering cost: significant (need eval data, compression pipeline, tuning)

## 8. Recommendation

**Use the type-aware heuristic now. IB is the theoretical justification, not the
implementation.** The Exp 16 type classification already performs an implicit IB
partition -- constraints have high mutual information with queries, context has low.

Concrete plan:
1. Store all 1,195 nodes at full fidelity (they are only 36K tokens on disk)
2. At retrieval time, apply type-aware filtering: return constraints fully,
   compress context/rationale to first clause, omit implementation details
3. Use the IB framework to *validate* compression choices: run the truncation
   experiment from Section 5 to confirm that type-based compression matches
   the empirical IB curve
4. If we later need tighter compression (e.g., fitting into 4K context windows),
   use variational IB on embeddings to find the true minimum-rate encoding

The IB framework is valuable as theory -- it tells us compression should be
type-dependent and query-dependent, not uniform. But at 1K-10K nodes, the
type-aware heuristic captures ~90% of the IB benefit at ~5% of the engineering cost.

**Bottom line:** IB says "compress context nodes hard, preserve constraint nodes fully."
We already knew this from Exp 16. IB confirms it is principled, not arbitrary.
