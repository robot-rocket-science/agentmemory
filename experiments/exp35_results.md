# Experiment 35 Results: Multi-Hop Improvements

**Date:** 2026-04-09

## Results

| Method | Recall@3 | D097 Rank | D097 Sim | D175 | D167 |
|--------|----------|-----------|----------|------|------|
| A. Baseline iterative | 1/3 | 2 | 0.151 | not found | not found |
| B. Weighted edges | 1/3 | 1 | 0.258 | not found | not found |
| C. Beam search (k=5) | 1/3 | 1 | 0.151 | not found | not found |
| D. Weighted + beam | 1/3 | 1 | 0.032 | not found | not found |

## Analysis

**Neither weighting nor beam search improved recall.** All methods find D097 (multi-path target) and miss D175/D167 (single-path targets).

**Why weighting didn't help recall:** Weighting strengthens already-strong signals (D097: 0.151 -> 0.258) but doesn't create signal where there is none. D175 and D167 are each reachable via exactly 1 hop-1 path. A single path through a 25-edge superposition at DIM=2048 produces similarity at the noise floor (~0.03-0.05). No amount of weighting lifts a single-path signal above the noise of 24 other edges.

**Why beam search didn't help recall:** Beam search explores more paths, but at hop-1 there are exactly 5 valid paths (D195 cites exactly 5 nodes). Beam width > 5 adds noise, not signal. All 5 beams traverse the same 5 hop-1 nodes and find the same hop-2 results.

**The fundamental limit:** In a superposition of k edges, a single target edge has SNR ≈ sqrt(n/k). At n=2048, k=25: SNR ≈ 9 for single-hop. For a 2-hop query, the signal passes through the superposition twice. Even with cleanup between hops, the hop-2 query unbinds against the same noisy superposition. A target reachable by 1 path has effective SNR ≈ 9/sqrt(25) ≈ 1.8 (marginal). A target reachable by 3 paths has effective SNR ≈ 3*9/sqrt(25) ≈ 5.4 (reliable). This is why D097 (3 paths) is found and D175/D167 (1 path each) are not.

**What WOULD help:**
1. **Higher dimension:** DIM=4096 gives SNR ≈ 12.8 per hop. Single-path targets get SNR ≈ 2.6 (still marginal but above 1).
2. **Smaller subgraphs:** Partition the 25-edge neighborhood into 2 subgraphs of ~12 edges each. SNR per hop ≈ 13. Single-path SNR ≈ 3.8 (reliable).
3. **Sub-query partitioning:** Separate the hop-1 query and hop-2 query into different subgraph superpositions. Hop-1 unbinds against S_195 (only D195's edges). Hop-2 unbinds against S_target (only the target decision's edges). Each subgraph is smaller, so SNR is higher.

Option 3 is the most interesting -- it means the system queries DIFFERENT subgraph superpositions at each hop, matching the hop to the relevant partition. This is "smart routing" of HRR queries.

## Verdict

Weighting and beam search are useful for signal strength but not for recall on single-path targets. The multi-hop recall problem is fundamentally about SNR in the superposition, which is addressed by dimension or partitioning, not by query-side improvements.

For practical use: single-hop HRR (5/5 proven) + explicit graph BFS for multi-hop is likely the right split. HRR handles fuzzy-start typed queries; BFS handles exact multi-hop traversal where the starting node is known.
