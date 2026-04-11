# Experiment 55: Rate-Distortion Budget Allocation -- Results

**Date:** 2026-04-10
**Status:** Complete -- NEGATIVE RESULT
**Approach:** A023

---

## Summary

Rate-distortion-optimal token allocation produces zero improvement over the fixed-ratio type-aware heuristic at any budget level (500-3000 tokens). The reason: the budget is never binding. All candidates fit within every budget tested.

## Results

| Budget | Fixed NDCG | RD NDCG | Top-k NDCG | RD Improvement |
|--------|-----------|---------|-----------|----------------|
| 500 | 0.774 | 0.774 | 0.796 | +0.0% |
| 1000 | 0.774 | 0.774 | 0.775 | +0.0% |
| 1500 | 0.774 | 0.774 | 0.774 | +0.0% |
| 2000 | 0.774 | 0.774 | 0.774 | +0.0% |
| 3000 | 0.774 | 0.774 | 0.774 | +0.0% |

All three strategies include the same ~26 beliefs. Even at 500 tokens, the fixed-ratio strategy fits all candidates (average 450 tokens used). The RD optimizer has no constraint to optimize against.

### Detailed Metrics at Budget=2000

| Metric | Fixed-ratio | RD-optimal | Top-k Full |
|--------|------------|-----------|-----------|
| NDCG | 0.774 | 0.774 | 0.774 |
| Precision | 0.219 | 0.219 | 0.219 |
| Token efficiency | **0.255** | 0.211 | 0.211 |
| Recall | 0.861 | 0.861 | 0.861 |
| Mean fidelity | 0.620 | **1.000** | **1.000** |
| Beliefs included | 26.4 | 26.4 | 26.4 |
| Tokens used | **450** | 877 | 877 |

Fixed-ratio actually uses fewer tokens (450 vs 877) because it compresses aggressively. RD and top-k both use ~877 tokens because the RD optimizer, with no binding constraint, allocates near-full fidelity to everything.

## Hypothesis Outcomes

| Hypothesis | Predicted | Observed | Verdict |
|------------|-----------|----------|---------|
| H1: RD NDCG >= 10% better | Yes | +0.0% | **FAILED** |
| H2: RD concentrates on fewer beliefs | Fewer beliefs, higher fidelity | Same beliefs, same count | **FAILED** |
| H3: At generous budget, RD degenerates to fixed | Yes | Yes (trivially: all budgets are generous) | **CONFIRMED** (but vacuously) |

## Root Cause Analysis

**Why RD allocation fails:**

1. **The budget is never binding.** FTS5 returns ~26 unique decisions per query. At average ~30 tokens/sentence and ~1 sentence per decision in the top-30 results, the total payload is ~450-877 tokens. The 2,000-token budget (REQ-003) is 2-4x larger than needed. When the constraint is slack, the Lagrange multiplier is zero and all strategies degenerate to "include everything."

2. **The experiment tests the wrong scale.** At 1,195 nodes with 173 decisions, typical retrieval returns 26 decisions. For the budget to bind, retrieval would need to return 60+ decisions -- which only happens at 5K+ node corpora where type dilution is a problem (Exp 48 showed this).

3. **NDCG is insensitive to allocation.** Since all three strategies include the same set of beliefs, NDCG depends only on rank order, which is determined by FTS5 -- not by how many tokens each belief gets. Token allocation (compression ratio) affects readability, not ranking.

**When RD allocation WOULD matter:**

- At 10K+ beliefs where retrieval returns 100+ candidates
- When token budget is smaller (e.g., 200-500 tokens for L0 always-loaded)
- When the question is which subset to include (selection), not how much of each to include (compression)

## The Real Insight

The experiment validates the Exp 42 finding from a different angle: **the token budget is not the bottleneck at current scale.** The bottleneck is retrieval quality (which beliefs are found), not budget allocation (how they're compressed). This confirms:

- REQ-003 (2K budget) is easily achievable at 1K-node scale
- The fixed-ratio heuristic is not just sufficient -- it's indistinguishable from optimal
- Investment should go into retrieval quality (Exp 47/48/52's finding), not allocation optimization

## Decision

**REJECT A023 at current scale.** The rate-distortion framework is mathematically sound (Jakob & Gershman 2023 is correct) but the precondition -- a binding capacity constraint -- does not hold at our corpus size. Revisit if corpus exceeds 5K beliefs and retrieval returns > 50 candidates per query.

## References

- [Jakob & Gershman, eLife 2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC10353860/) -- theory is valid, just not applicable at this scale
- Exp 42 -- type-aware heuristic achieves 55% compression with zero retrieval loss
- Exp 48 -- at 16K nodes, type dilution makes retrieval the bottleneck, not budget
