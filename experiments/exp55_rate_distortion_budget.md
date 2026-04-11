# Experiment 55: Rate-Distortion Theory for Token Budget Allocation

**Date:** 2026-04-10
**Status:** Planned
**Depends on:** Exp 42 (compression data), Exp 9 (ground truth), Exp 16 (type decomposition)
**Approach:** A023

---

## Research Question

Does rate-distortion-optimal token budget allocation across retrieved beliefs produce better retrieval quality than the current fixed-ratio type-aware heuristic (A035)?

## Background

Jakob & Gershman (eLife, 2023) formalized working memory as a rate-distortion problem: when N items compete for encoding into capacity C, each item's precision decreases to stay within capacity. Their key result, validated against monkey prefrontal cortex data: optimal memory is lossy and task-dependent.

Our system has the same structure:
- **Items:** Retrieved beliefs (10-30 per query)
- **Capacity:** 2,000-token budget (REQ-003)
- **Distortion:** Loss of information that would have helped the agent

Currently, we allocate tokens by type with fixed ratios (Exp 42/A035):
- constraints: 1.0x (full text)
- evidence: 0.6x
- context: 0.3x
- rationale: 0.4x
- supersession: pointer (~5 tokens)
- implementation: 0.3x

This is query-independent. A constraint about exit rules gets the same 1.0x allocation whether the query is about exit rules (high relevance) or about typing conventions (zero relevance). Rate-distortion theory says the optimal allocation should be query-dependent: allocate more tokens to beliefs with higher relevance to the current query.

## Hypothesis

**H1 (Primary):** Query-dependent rate-distortion allocation produces higher NDCG@budget than fixed-ratio allocation, at the same total token cost. Expected improvement: >= 10% NDCG.

**H2 (Secondary):** The RD-optimal allocation concentrates tokens on fewer beliefs (higher precision@budget) compared to uniform spreading. Expected: RD retrieves 30-50% fewer beliefs but at higher per-belief fidelity.

**H3 (Boundary):** When retrieved beliefs are all equally relevant (uniform relevance), RD allocation degenerates to the fixed-ratio heuristic (equal allocation per type). This confirms the heuristic is a special case of the RD solution.

## Null Hypothesis

NDCG@budget difference between RD allocation and fixed-ratio is < 5%. The type-aware heuristic is already close to optimal and query-dependent allocation adds complexity without meaningful gain.

## Method

### Step 1: Define the rate-distortion objective

Given:
- N retrieved beliefs b_1, ..., b_N with relevance scores r_i (from FTS5 BM25 or MI score from Exp 54)
- Token lengths l_i for each belief (full text)
- Total budget B = 2,000 tokens
- Compression function: c_i in [0, 1] = fraction of belief i's tokens to include

Objective (reverse water-filling):

```
maximize sum_i r_i * f(c_i)
subject to sum_i c_i * l_i <= B
           0 <= c_i <= 1 for all i
```

Where f(c_i) is the information fidelity function -- how much of the belief's useful information is preserved at compression ratio c_i.

### Step 2: Estimate the fidelity function f(c)

We need to know: if we truncate a belief to fraction c of its tokens, how much retrieval/comprehension value remains?

Use Exp 42 data. For each belief type, we measured retrieval coverage at full (1.0), type-compressed (variable), and keyword-only (minimal). Fit a concave fidelity curve per type:

```
f_constraint(c) = c^0.3    (diminishing returns -- first words carry most info)
f_evidence(c)   = c^0.5    (moderate returns)
f_context(c)    = c^0.7    (more linear -- context words are less front-loaded)
```

The exponents are estimated from the Exp 42 observation that aggressive truncation (0.23x for context) preserved 100% retrieval. We validate these by testing retrieval at intermediate compression levels in this experiment.

### Step 3: Solve the allocation problem

This is a convex optimization (concave objective, linear constraint). Solve via Lagrangian:

```
L = sum_i r_i * f(c_i) - lambda * (sum_i c_i * l_i - B)

KKT: r_i * f'(c_i) = lambda * l_i   for all active i
```

This is reverse water-filling: beliefs with high relevance r_i and short length l_i get more allocation. Beliefs with low relevance get truncated harder or dropped entirely (c_i = 0).

Solve numerically with scipy.optimize.minimize (SLSQP) or analytically for power-law f(c).

### Step 4: Compare allocation strategies on ground truth

For each of 18 queries (6 topics x 3 queries):
1. Retrieve top-30 candidates via FTS5
2. Apply three allocation strategies within 2,000-token budget:
   a. **Fixed-ratio (baseline):** Exp 42 type-aware compression. Include as many beliefs as fit.
   b. **RD-optimal:** Solve the optimization above. Variable compression per belief.
   c. **Top-k full text:** Include beliefs at full text until budget exhausted (no compression, greedy).
3. Compute for each strategy:
   - **NDCG@budget:** Normalized DCG of the included beliefs, weighted by relevance
   - **Precision@budget:** Fraction of included beliefs that are ground-truth relevant
   - **Token efficiency:** Relevant tokens / total tokens (how much of the budget goes to signal)
   - **Beliefs included:** How many beliefs fit in the budget
   - **Fidelity score:** Mean f(c_i) across included beliefs

### Step 5: Sensitivity analysis

Vary the budget B in {500, 1000, 1500, 2000, 3000} and measure how each strategy degrades. The RD advantage should be largest at tight budgets (500-1000) where allocation decisions matter most, and smallest at generous budgets (3000) where everything fits.

### Step 6: Statistical test

Paired Wilcoxon signed-rank test on per-query NDCG@budget (fixed-ratio vs RD-optimal), n=18.

## Materials

- 1,195 sentence nodes with type labels and token lengths (Exp 16/42)
- 6-topic ground truth with relevance labels (Exp 9)
- 18 queries
- Exp 42 compression results (type-specific compression ratios and retrieval outcomes)

## Expected Results

| Metric | Fixed-ratio | RD-optimal | Top-k full | Reasoning |
|--------|------------|------------|-----------|-----------|
| NDCG@2000 | ~0.55 | ~0.65 | ~0.50 | RD concentrates budget on high-relevance beliefs |
| Precision@budget | ~0.45 | ~0.55 | ~0.60 | Top-k has highest precision but worst coverage |
| Beliefs included | ~150 | ~80-120 | ~50-60 | RD is between fixed-ratio (spread thin) and top-k (concentrated) |
| Token efficiency | ~0.40 | ~0.55 | ~0.50 | RD minimizes tokens spent on low-relevance beliefs |

At tight budget (500 tokens):
- Fixed-ratio includes ~35 beliefs at heavy compression, many irrelevant
- RD includes ~15-20 beliefs at moderate compression, mostly relevant
- Top-k includes ~12-15 at full text, highest relevance but misses some

## Decision Criteria

| Result | Action |
|--------|--------|
| NDCG improvement >= 10%, p < 0.05 | Adopt RD allocation for production retrieval |
| NDCG improvement 5-10%, p < 0.10 | Adopt only for tight budgets (L0/L1). Keep fixed-ratio for L2/L3 |
| NDCG improvement < 5% | Reject. Fixed-ratio heuristic is near-optimal. Document why |
| RD DECREASES quality | Reject. Likely cause: fidelity function f(c) is wrong |

## Risks

1. **Fidelity function estimation:** f(c) is the critical unknown. If the power-law assumption is wrong (e.g., information is uniformly distributed in text rather than front-loaded), the RD solution degenerates to uniform allocation. Mitigate: test 3 fidelity function families (power-law, logarithmic, linear) and report which fits best.

2. **Relevance score quality:** RD allocation amplifies relevance score errors. If BM25 gives a high score to an irrelevant belief, RD allocates more tokens to it. Mitigate: test with both BM25 scores and binary ground-truth relevance labels (oracle scenario).

3. **Solver sensitivity:** The optimization landscape should be convex (concave f, linear constraint) but numerical issues could arise with very small or very large c_i. Mitigate: clamp c_i to [0.05, 1.0] to avoid degenerate solutions.

## Connection to Existing Work

- **Exp 42 (IB compression):** Showed 55% token savings with type-aware heuristic. This experiment tests whether query-dependent allocation does better.
- **Exp 20 (IB theory):** Established IB framing. This experiment operationalizes the rate-distortion side of it.
- **REQ-003:** 2,000-token budget. This experiment directly optimizes for that constraint.
- **REQ-004:** Quality per token. RD allocation is designed to maximize exactly this.
- **Jakob & Gershman (eLife 2023):** The theoretical foundation. We test their model on our specific domain.

## Implementation Notes

- Dependencies: numpy, scipy (for SLSQP optimizer). Both already in the environment.
- Reuse Exp 42's sentence decomposition, FTS5 index, and ground truth.
- Output: exp55_results.json with per-query allocation vectors and quality metrics under each strategy.
- Visualization: allocation heatmap (beliefs x strategies) showing how tokens are distributed.

## References

- [Jakob & Gershman, eLife 2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC10353860/)
- [Tishby et al., "The Information Bottleneck Method," 1999](https://arxiv.org/abs/physics/0004057)
- [Shannon, "A Mathematical Theory of Communication," 1948](https://people.math.harvard.edu/~ctm/home/text/others/shannon/entropy/entropy.pdf)
