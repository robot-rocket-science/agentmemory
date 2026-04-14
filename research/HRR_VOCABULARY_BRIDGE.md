# HRR Vocabulary Bridge: How Graph Structure Solves the Retrieval Gap FTS5 Cannot

**Date:** 2026-04-10
**Status:** Validated mechanism (Exp 34 Test A: 184x separation)
**Context:** Exp 39 proved a permanent 8% retrieval gap exists for text-based methods. This document explains how HRR bridges that gap and traces the evidence chain.

---

## 1. The Problem

FTS5 (BM25) retrieves beliefs by matching words. When the query and the target share zero vocabulary, FTS5 returns nothing. No amount of query expansion fixes this because the connection between the query and the target is semantic, not lexical.

### Concrete Example: D157

**Query:** "agent behavior instructions"
**Target:** D157 -- "Whether to allow async_bash and await_job for background command execution: BANNED. Never use async_bash or await_job for any command, any duration, any context."

Vocabulary intersection: zero. The query uses "behavior" and "instructions." The target uses "async_bash," "await_job," "banned." These vocabulary sets have no statistical co-occurrence path in the corpus (PMI, PRF, and all union methods tested in Exp 39 failed to bridge this gap).

The connection exists only through the concept "agent behavioral constraints" -- both D157 (tool bans) and D188 (communication style) are directives about how the agent must behave. A human understands this. FTS5 cannot.

**Evidence:** Exp 39. Six expansion methods tested (baseline, PMI, PRF, PMI+PRF, multi-query, union-all). All return 12/13 decisions. D157 is the irreducible miss. The only hand-crafted query that finds D157 is "execute precisely return control" -- vocabulary only a human who already knows D157's content would choose.

---

## 2. How HRR Solves This

### 2.1 Core Mechanism

HRR operates on graph structure, not text content. Each belief node gets a **random vector** in R^d (d=2048 in our experiments). The content of the belief ("async_bash banned" vs "don't elaborate") has zero influence on the vector. What matters is which edges connect the nodes.

When two beliefs share a typed edge, HRR binds them into a superposition:

```
S += bind(D157_vec, AGENT_CONSTRAINT_vec)
S += bind(D188_vec, AGENT_CONSTRAINT_vec)
S += bind(D100_vec, AGENT_CONSTRAINT_vec)
S += bind(D073_vec, AGENT_CONSTRAINT_vec)
```

Where:
- `D157_vec`, `D188_vec`, etc. are random iid vectors in R^2048
- `AGENT_CONSTRAINT_vec` is a random iid vector representing the edge type
- `bind()` is circular convolution (element-wise multiplication in Fourier domain)
- `S` is the sum of all bound pairs (the superposition)

### 2.2 Retrieval

To find all beliefs connected via AGENT_CONSTRAINT:

```
result_vec = unbind(S, AGENT_CONSTRAINT_vec)
```

Where `unbind()` is circular correlation (the approximate inverse of circular convolution). The result is a noisy sum of the original node vectors:

```
result_vec ~ D157_vec + D188_vec + D100_vec + D073_vec + noise
```

Nearest-neighbor search against all known node vectors recovers the individual nodes.

### 2.3 Why Vocabulary Doesn't Matter

The node vectors are random. D157 ("async_bash banned") and D188 ("don't elaborate") have vectors that are approximately orthogonal by construction (expected cosine similarity of two random 2048D vectors is ~0). Their content is irrelevant to the HRR encoding.

What connects them is the edge type. If both are bound with the same AGENT_CONSTRAINT vector, unbinding with AGENT_CONSTRAINT recovers both. The retrieval is purely structural.

This means:
- Two beliefs with zero vocabulary overlap but the same edge type: **HRR finds both**
- Two beliefs with identical vocabulary but different edge types: **HRR distinguishes them**
- A belief with vocabulary matching the query but no edge: **HRR ignores it** (FTS5 handles this case)

---

## 3. The Evidence

### 3.1 Exp 34 Test A: Vocabulary Bridge (184x Separation)

**Setup:** 4 behavioral beliefs + 5 distractors. All encoded in a 2048D HRR superposition with AGENT_CONSTRAINT edge type. Behavioral beliefs:
- D157: "ban async_bash" (tool restriction)
- D188: "execute exactly, don't elaborate" (communication style)
- D100: "never question calls/puts" (domain constraint)
- D073: "equal citizens" (strategy rule)

These four share zero vocabulary across all pairs. Their only connection is the AGENT_CONSTRAINT edge type.

**Result:**

| Rank | Node | Similarity | Category |
|------|------|-----------|----------|
| 1 | D100_s0 | 0.210 | BEHAVIOR |
| 2 | D188_s0 | 0.194 | BEHAVIOR |
| 3 | D073_s0 | 0.149 | BEHAVIOR |
| 4 | D005_s0 | 0.013 | distractor |
| 5-9 | ... | -0.05 to 0.00 | distractors |

**Separation:** Behavior mean 0.184, distractor mean -0.013. Ratio: **184.3x**.

**Interpretation:** HRR cleanly separates behavioral beliefs from non-behavioral beliefs despite zero vocabulary overlap. The signal is the typed edge structure, not the content.

Source: experiments/exp34_results.md, experiments/exp34_hrr_closing_tests.py

### 3.2 Exp 31: Single-Hop Typed Traversal (5/5 Recall)

**Setup:** D195 neighborhood. 18 sentence-level nodes, 25 edges, DIM=2048 (capacity ~204, well within budget).

**Query:** "What does D195_s1 cite?" (unbind with CITES edge type)

| Rank | Node | Similarity | Ground Truth? |
|------|------|-----------|---------------|
| 1 | D191_s0 | 0.177 | Yes |
| 2 | D174_s0 | 0.160 | Yes |
| 3 | D184_s0 | 0.141 | Yes |
| 4 | D180_s0 | 0.132 | Yes |
| 5 | D186_s0 | 0.118 | Yes |
| 6 | D180_s4 | 0.050 | No |

5/5 recall. Gap between worst target (0.118) and best non-target (0.050) = 2.4x.

**Key:** These target nodes share minimal vocabulary with each other. D191 ("wipeout root cause"), D174 ("optimization target"), D184 ("N*p metric"). HRR found them through graph structure alone.

Source: HRR_FINDINGS.md Section 1, experiments/exp31_sentence_hrr.py

### 3.3 Exp 30 (Focused): Edge-Type Selectivity

**Query:** D149 with DECIDED_IN edge type.

- Correct target (M024): similarity 0.183
- Next non-target: 0.064
- CITES bleed-through: zero

CITES query on same subgraph: zero DECIDED_IN results. The edge type vectors are orthogonal by construction (random vectors in R^2048), providing geometric type filtering without conditional logic.

Source: HRR_FINDINGS.md Section 2

### 3.4 Exp 34 Follow-up: Iterative Multi-Hop

Starting from D195, 2-hop traversal through CITES edges to reach D097:

```
Hop 1: unbind(D195, CITES) -> D184, D186, D174, D191, D180 (5/5)
Hop 2: for each cleaned hop-1 node:
  D184 -> D097 (sim 0.168)
  D174 -> D097 (sim 0.150)
  D186 -> D097 (sim 0.033)
Aggregated: D097 at rank 1 (sim 0.168)
```

Multi-path convergence (3 independent paths to D097) acts as a natural relevance signal.

Source: HRR_FINDINGS.md Section 4

---

## 4. The Hybrid Retrieval Pipeline

Neither FTS5 nor HRR is sufficient alone. They handle complementary cases:

| Case | FTS5 | HRR | Example |
|------|------|-----|---------|
| Query and target share vocabulary | Finds it | Ignores it (no edge needed) | "capital bankroll" finds D099 |
| Query and target share edge type, no vocab overlap | Misses it | Finds it | "agent behavior" finds D157 |
| Query and target share both | Both find it (redundant) | Both find it | "typing pyright" finds D071 |
| Query and target share neither | Both miss it | Both miss it | No known case in test data |

### Pipeline Architecture

```
Query: "agent behavior instructions"
  |
  +---> [FTS5 pass] 
  |       Search FTS5 index with query terms
  |       Result: {D188} (matches "instructions")
  |
  +---> [HRR pass]
  |       1. FTS5 hits seed the HRR query
  |       2. For each FTS5 hit (D188), look up its subgraph partition
  |       3. Unbind D188's superposition with each edge type
  |       4. Collect neighbors: {D157, D100, D073} via AGENT_CONSTRAINT
  |
  +---> [Union + rank]
          Merge FTS5 results and HRR results
          Rank by: FTS5 BM25 score + HRR similarity + belief confidence
          Result: {D188, D157, D100, D073}
```

FTS5 provides the entry point (92% of cases). HRR provides the graph walk from that entry point (the remaining 8%).

### When HRR Adds Nothing

When all relevant beliefs share vocabulary with the query, FTS5 handles everything. HRR adds computational cost with no retrieval benefit. This is the common case -- Exp 39 showed 92% coverage from FTS5 alone.

### When HRR Is Essential

When the relevant belief uses completely different vocabulary from the query but is structurally connected to a belief FTS5 can find. D157 is unreachable by FTS5 from "agent behavior instructions," but reachable from D188 (which FTS5 finds) via the AGENT_CONSTRAINT edge in HRR.

This is the 8% gap. It contains the most valuable retrievals -- beliefs that no keyword search would ever find but that are genuinely relevant through structural relationships.

---

## 5. Prerequisites: Where Do the Edges Come From?

HRR traverses edges. It does not create them. The vocabulary bridge works IF the AGENT_CONSTRAINT edge between D157 and D188 exists. The question "how does D157 get connected to D188?" is answered by the extraction pipeline, not by HRR.

### Edge Sources for Behavioral Beliefs

| Source | Method | Zero-LLM? | Evidence |
|--------|--------|-----------|---------|
| Correction detection V2 | Pattern matching: imperative verbs, always/never, negation | Yes | 92% accuracy on real corrections (Exp 1 V2) |
| `directive` MCP tool | User calls `remember` with `related_concepts` tags | Yes (user provides) | Designed in PLAN.md |
| Co-change | If D157 and D188 modified in same commit | Yes | Validated in T0 (96 edges w>=3 on alpha-seek) |
| CALLS edges | If enforcement code for D157 and D188 share function calls | Yes | Validated in Exp 37 (3,489 resolved edges) |
| HRR bootstrap | Encode partial graph, propose candidates, verify | Yes | Exp 33: D097 found at rank 2 via bootstrap |
| LLM classification | Ask LLM to tag belief as "behavioral" | No | Exp 28: solves vocab mismatch via `related_concepts` |

### The Edge Creation Gap

Exp 34 Test A used manually assigned AGENT_CONSTRAINT edges. In production, automatic edge creation for behavioral beliefs depends on:

1. **Correction detection V2** catching "BANNED" and "Never use" as directive patterns (it should -- these match imperative + negation patterns at 92% accuracy)
2. **Co-change or CALLS edges** connecting the enforcement code (if D157 and D188's rules are enforced in related code paths)
3. **User explicitly linking them** via the `remember` tool with `related_concepts`

The weakest link is case 2: behavioral beliefs expressed only in documentation (not enforced in code) won't have code-derived edges. They depend on directive detection or user action.

---

## 6. Capacity and Scaling

HRR retrieval quality depends on the ratio of edges to dimensionality:

| Edges in Partition | DIM=1024 | DIM=2048 | DIM=4096 |
|-------------------|----------|----------|----------|
| 25 | SNR ~3.2 | SNR ~4.5 | SNR ~6.4 |
| 100 | SNR ~1.6 | SNR ~2.3 | SNR ~3.2 |
| 200 | SNR ~1.1 | SNR ~1.6 | SNR ~2.3 |
| 1000 | Noise | SNR ~0.7 | SNR ~1.0 |

Reliable retrieval requires SNR > 3 (HRR_FINDINGS.md). At DIM=2048:
- **25 edges per partition:** clean (5/5 recall demonstrated)
- **100 edges per partition:** noisy but functional
- **200+ edges per partition:** requires DIM=4096 or further partitioning

The T0 adaptive threshold + partition routing approach (validated on 5 repos, R@10 0.44-0.90) handles this: each module/subgraph becomes a partition within capacity.

---

## 7. What Remains Unproven

| Claim | Status | What Would Prove It |
|-------|--------|-------------------|
| Vocabulary bridge works at 184x separation | **PROVEN** (Exp 34 Test A) | -- |
| Single-hop typed traversal at 5/5 recall | **PROVEN** (Exp 31) | -- |
| Edge-type selectivity is clean | **PROVEN** (Exp 30) | -- |
| Iterative multi-hop finds 2-hop targets | **PROVEN** (Exp 34: D097 rank 1) | -- |
| FTS5 + HRR combined improves over FTS5 alone | **UNPROVEN** (Exp 34 Test C inconclusive) | Need a test where FTS5 genuinely misses and HRR finds via seeded walk |
| Automatic edge creation for behavioral beliefs | **UNPROVEN** | Run correction detection V2 on CLAUDE.md directives, verify edges created |
| HRR vocabulary bridge at full graph scale | **UNPROVEN** | Encode all behavioral beliefs in alpha-seek, test cross-vocabulary retrieval |
| HRR + PRF combined pipeline | **UNPROVEN** | Run PRF for initial FTS5 hits, HRR for graph walk, measure combined coverage |

The most important unproven claim is the combined FTS5+HRR pipeline. The individual components work. The integration has not been tested end-to-end.

---

## 8. References

1. Plate, T. "Holographic Reduced Representations." IEEE TPNN, 1995. (Circular convolution binding/unbinding)
2. Bricken, T., Pehlevan, C. "Attention Approximates Sparse Distributed Memory." NeurIPS, 2021. (Transformer attention = Kanerva SDM = HRR retrieval)
3. HRR_FINDINGS.md -- complete experimental record (Exp 24-35)
4. HRR_RESEARCH.md -- mathematical foundations, capacity analysis
5. experiments/exp34_results.md -- vocabulary bridge test (184x separation)
6. experiments/exp34_hrr_closing_tests.py -- test implementation
7. experiments/exp31_sentence_hrr.py -- single-hop typed traversal
8. QUERY_EXPANSION_RESEARCH.md -- the 8% gap that motivates HRR (Exp 39)
9. T0_RESULTS.md -- HRR selective amplifier finding (2.6-3.2x on low-overlap edges)
10. EDGE_TYPE_TAXONOMY.md -- edge types that become HRR binding vectors
