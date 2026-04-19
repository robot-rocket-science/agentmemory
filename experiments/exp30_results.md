# Experiment 30 Results: Real HRR on Project-A Graph

**Date:** 2026-04-09

## What Was Tested

Real HRR (not BoW cosine) on the project-a graph:
- Random node vectors (not derived from content)
- Typed edges encoded via circular convolution binding
- Cleanup memory for nearest-neighbor recovery
- Single-hop, reverse, edge-selective, and 2-hop traversal

## Results

### Global superposition (775 edges in 1024D): FAILED
- Capacity ~102 bindings, graph has 775 -- 7.6x over capacity
- All results were noise (similarities 0.08-0.13, indistinguishable from random)
- **Lesson: global superposition doesn't scale. Must partition.**

### Local subgraph (103 edges in 1024D): PARTIALLY WORKED
- D149's 2-hop neighborhood: 79 nodes, 103 edges
- Right at capacity boundary (~102)

| Test | Result | Score Range | Verdict |
|------|--------|-------------|---------|
| Single-hop CITES | 3/6 correct | 0.09-0.12 (noise ~0.06) | Works but recall limited by capacity |
| Edge-type selectivity | Clean separation | DECIDED_IN: 0.18, CITES bleed: 0.00 | Edge orthogonality works |
| 2-hop traversal | 0/6 correct | 0.03-0.07 (noise level) | Fails at capacity boundary |

### Verification: Is this actually working or lucky?

The edge-type selectivity test is the strongest evidence. When querying D149 with DECIDED_IN:
- _M024 (correct target) scores 0.183
- Next best non-target scores 0.064
- That's a 2.9x gap -- real signal, not luck

When querying with CITES:
- D146 (correct) scores 0.122
- First non-target scores 0.068
- 1.8x gap -- weaker but still signal

For comparison, random vectors at DIM=1024 have expected cos_sim of 0.0 with std ~0.031.
Scores of 0.12-0.18 are 4-6 standard deviations above noise.

### What This Means for the Architecture

1. **HRR works for typed single-hop traversal** when subgraphs are within capacity
2. **Multi-hop requires higher DIM or smaller subgraphs** (DIM=4096 would give capacity ~455)
3. **Sentence-level decomposition helps HRR** -- more nodes but edges partition into smaller topical subgraphs
4. **HRR and FTS5 are genuinely complementary now** -- FTS5 finds by keyword, HRR finds by graph structure. Different capabilities, not redundant like Exp 25 showed with BoW.
5. **The vocabulary mismatch problem (D157) is addressable via HRR**: if D157 and D188 share an edge (both are AGENT_BEHAVIOR type), HRR can traverse from one to the other without shared vocabulary

### Bugs and Methodological Issues in This Experiment

1. **D097 test failed because D097 has zero outgoing CITES edges** in this database. The edges are incoming. Fixed by switching to D149 which has 6 outgoing CITES.
2. **Global superposition was predictably over capacity** -- should have been subgraph-partitioned from the start. The HRR_RESEARCH.md section 6 states capacity ~n/10.
3. **The local subgraph (103 edges) was still slightly over capacity (102)**. A cleaner test would use ~50 edges. Results at the boundary are noisy but not random.
4. **Division by zero when BFS found 0 edges** -- fixed in subsequent run.

### Next Steps

- Test at DIM=4096 (capacity ~455, easily holds any local subgraph)
- Partition the full 775-edge graph into topic clusters of ~50-80 edges each
- Encode sentence-level nodes (from Exp 16/29) instead of decision-level
- Test whether HRR can bridge the D157-D188 vocabulary gap via shared edge types
