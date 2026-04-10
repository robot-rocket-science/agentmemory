# Experiment 33: HRR Partial Graph Bootstrap

**Date:** 2026-04-09
**Question:** Can HRR propose new edges by bootstrapping from a partial graph?

## Setup

- D195 neighborhood: 18 nodes, 25 edges (within DIM=2048 capacity)
- Known edges: D195's CITES targets + those targets' own CITES edges
- Bootstrap query: "given what D195's targets cite, what else connects?"

## Results

### Single-hop (validation): 5/5 PERFECT
Same result as Exp 31. Known citations all found with clear signal.

### Bootstrap traversal: PARTIALLY WORKS

| Query | Target | HRR Rank | HRR Similarity | Found? |
|-------|--------|----------|----------------|--------|
| D174_s0 -> D097_s0 | D097_s0 | 2 | 0.161 | Yes (rank 2) |
| D180_s0 -> D097_s0 | D097_s0 | 4 | 0.021 | Weak signal |
| D180_s0 -> D174_s0 | D174_s0 | not in top 5 | - | No |
| D180_s0 -> D175_s0 | D175_s0 | not in top 5 | - | No |

### What's happening

The superposition contains reverse paths back to D195 (which has strong bindings). These dominate the bootstrap results. Real targets are present but compete with reverse-path noise.

D195_s5 and D195_s1 appear at top of every bootstrap query because they have the most edges in the superposition -- they're the "hubs" of this subgraph and act like gravitational centers.

## Verdict

**HRR bootstrap works for PROPOSING candidate edges, not for definitively discovering them.**

The workflow:
1. Build partial graph from obvious edges (regex, co-occurrence)
2. Encode in HRR
3. Bootstrap query: "what else might connect here?"
4. Filter: candidates above threshold -> PROPOSED edges
5. Verify proposals via other methods (LLM, FTS5 content match, user)

This is graph construction with HRR-assisted candidate generation. Not autonomous, but valuable for surfacing relationships that pure keyword matching misses.

## Connection to Onboarding

During onboarding:
1. Parse documents into sentences (Exp 16: 1,195 nodes)
2. Extract obvious edges: regex citations, co-occurrence, type pairing (132 SUPPORTED_BY from Exp 32 demo)
3. Encode partial graph in HRR
4. Bootstrap: propose additional edges from HRR traversal
5. Present proposed edges to LLM or user for confirmation
6. Confirmed edges added to graph, re-encoded, next bootstrap round

The graph grows iteratively: obvious edges -> HRR proposals -> confirmation -> richer graph -> better proposals.

## What HRR IS and ISN'T for this architecture

**IS:** Graph encoding, typed traversal, compositional queries, edge proposal
**ISN'T:** Autonomous edge discovery, replacement for regex/co-occurrence, one-shot graph construction
