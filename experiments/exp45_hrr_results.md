# Experiment 45: HRR Belief Prototype Results

**Date:** 2026-04-10
**Input:** 1,195 sentence nodes from 173 decisions, 1,485 edges (alpha-seek)
**Builds on:** Exp 31 (sentence HRR), 34 (vocabulary bridge), 35 (multi-hop), 40 (hybrid pipeline), 42 (IB)
**Method:** Full prototype with partition strategies, DIM comparison, integrated pipeline, vocabulary-gap test, capacity analysis
**Rigor tier:** Empirically tested (real data, single dataset)

---

## Q1: Partition Strategy

**Result: Decision-neighborhood partitioning achieves 100% single-hop recall at both DIM=2048 and DIM=4096. Edge-type partitioning fails. Fixed-size partitioning is good but not perfect.**

### Recall by Strategy and Dimension

| Strategy | Partitions | Avg Size | Max Size | DIM=2048 Recall | DIM=4096 Recall |
|----------|-----------|----------|----------|-----------------|-----------------|
| Decision neighborhood | 27 | 55 | 65 | **24/24 (1.000)** | **24/24 (1.000)** |
| Fixed-size (k=100) | 15 | 99 | 100 | 20/24 (0.833) | 23/24 (0.958) |
| Edge-type | 3 | 495 | 1,022 | 4/24 (0.167) | 9/24 (0.375) |

### Per-Query Detail (Decision Neighborhood, DIM=2048)

| Source | Targets | Found | Recall | Best Target Sim | Best Noise Sim |
|--------|---------|-------|--------|-----------------|----------------|
| D195_s1 | 5 | 5 | 1.000 | 0.1203 | 0.0589 |
| D195_s5 | 5 | 5 | 1.000 | 0.1451 | 0.0609 |
| D199_s4 | 5 | 5 | 1.000 | 0.1326 | 0.0727 |
| D200_s2 | 5 | 5 | 1.000 | 0.1313 | 0.0540 |
| D147_s5 | 4 | 4 | 1.000 | 0.1359 | 0.0672 |

### Analysis

**Decision-neighborhood** groups edges by the parent decision of the source sentence, then merges small groups until each partition has 50+ edges. This keeps related edges together and maintains locality. At 50-65 edges per partition vs capacity ~227 (DIM=2048) or ~455 (DIM=4096), headroom is 3.5-7x. This is well within the reliable regime.

**Edge-type partitioning** puts all CITES edges in one partition (223 edges), all NEXT_IN_DECISION in another (1,022 edges), and all SAME_TOPIC in a third (240 edges). The NEXT_IN_DECISION partition is 4.5x over capacity at DIM=2048. Even at DIM=4096, it exceeds capacity (1,022 > 455). This strategy is fundamentally unworkable for the alpha-seek graph because NEXT_IN_DECISION edges dominate.

**Fixed-size partitioning** splits edges into chunks of 100. This works better than edge-type (staying within capacity) but splits decision neighborhoods across partition boundaries. A CITES edge from D195_s1 to D174_s0 may land in a different partition than D195_s1's other CITES edges, breaking the routing logic. DIM=4096 partially compensates with higher SNR (0.958 recall).

**Verdict:** Decision-neighborhood partitioning is the clear winner. It preserves locality, stays well within capacity, and achieves perfect recall. Use this for all subsequent tests.

---

## Q2: DIM=4096 vs DIM=2048

**Result: Both achieve 100% recall on single-hop queries. DIM=4096 provides better signal separation (avg 2.5x vs 1.8x) at 2x memory and modest latency increase.**

### Summary

| Metric | DIM=2048 | DIM=4096 |
|--------|----------|----------|
| Recall | 39/39 (1.000) | 39/39 (1.000) |
| Encode time | 0.205 s | 0.407 s |
| Avg query time | 0.59 ms | 0.76 ms |
| Memory | 19.1 MB | 38.3 MB |

### Per-Query Separation (target/noise ratio)

| Query | DIM=2048 Sep | DIM=4096 Sep | DIM=2048 Avg Sim | DIM=4096 Avg Sim |
|-------|-------------|-------------|------------------|------------------|
| D195_s1 (5 targets) | 1.25x | 1.88x | 0.0987 | 0.0990 |
| D199_s4 (5 targets) | 1.83x | 2.26x | 0.0978 | 0.1069 |
| D200_s2 (5 targets) | 1.70x | 2.44x | 0.1001 | 0.1002 |
| D147_s5 (4 targets) | 1.82x | 3.59x | 0.1139 | 0.1185 |
| D149_s6 (4 targets) | 1.28x | 2.42x | 0.1203 | 0.0997 |
| D194_s3 (4 targets) | 1.54x | 1.70x | 0.1038 | 0.1052 |
| D112_s2 (3 targets) | 3.08x | 2.02x | 0.1251 | 0.1113 |
| D123_s3 (3 targets) | 1.96x | 3.50x | 0.1112 | 0.1234 |
| D132_s2 (3 targets) | 1.73x | 3.06x | 0.1151 | 0.1151 |
| D154_s8 (3 targets) | 2.06x | 1.88x | 0.1128 | 0.1072 |

### Analysis

Both dimensions achieve perfect recall because the decision-neighborhood partition strategy keeps partition sizes (50-65) well below the capacity threshold at either dimension (227 for 2048, 455 for 4096).

**DIM=4096 improves signal separation.** Average separation across queries: 2048 averages ~1.9x, 4096 averages ~2.5x. The improvement is not uniform -- D147_s5 jumps from 1.82x to 3.59x, while D112_s2 drops from 3.08x to 2.02x (random seed effects). But the trend is clear: higher dimensionality provides cleaner signal.

**DIM=4096 matters for robustness, not recall.** At the current graph scale with decision-neighborhood partitioning, DIM=2048 is sufficient. DIM=4096 becomes important when: (a) partitions grow larger (more edges per decision as the graph densifies), (b) edge types multiply (more noise per unbinding), or (c) the system scales to 10K+ nodes where partition merging produces larger groups.

**Connection to Exp 42 IB analysis.** Exp 42 predicted DIM >= 1,174 for constraint information capacity and DIM >= 625 for SNR. Both 2048 and 4096 clear these bars. Exp 42's recommendation of DIM=4096 as "theoretically safe" is confirmed: it works, with better separation, at 2x memory cost. Whether that cost is worth it depends on scale.

**Recommendation:** DIM=2048 for development and testing. DIM=4096 for production at scale. The 2x memory cost (19 MB vs 38 MB) is negligible at the current scale. At 100K nodes it becomes 1.6 GB vs 3.2 GB, which may matter.

---

## Q3: Integrated Single-Hop HRR + BFS Multi-Hop Pipeline

**Result: 13/13 critical decisions found (100% coverage). For the 6 critical topics, FTS5 alone achieves 100% at sentence level. HRR and BFS add zero incremental recall on this ground truth.**

| Topic | Needed | FTS5 | +HRR | +BFS | Combined |
|-------|--------|------|------|------|----------|
| dispatch_gate | 3 | 3/3 | +0 | +0 | 3/3 |
| calls_puts | 3 | 3/3 | +0 | +0 | 3/3 |
| capital_5k | 1 | 1/1 | +0 | +0 | 1/1 |
| agent_behavior | 2 | 2/2 | +0 | +0 | 2/2 |
| strict_typing | 2 | 2/2 | +0 | +0 | 2/2 |
| gcp_primary | 2 | 2/2 | +0 | +0 | 2/2 |
| **OVERALL** | **13** | **13/13** | **+0** | **+0** | **13/13** |

### Why FTS5 Finds D157 at Sentence Level

This contradicts Exp 39's finding that D157 is an "irreducible miss" for FTS5. The explanation: **sentence-level decomposition changes the FTS5 dynamics.**

D157_s6 ("Despite AGENTS.md already restricting these for SSH/long-running commands, the agent kept using them for 'bounded' tasks") contains the word "agent", which matches the query "agent behavior instructions." At decision-level, D157's full text is a single document dominated by "async_bash," "await_job," and "bg_shell" -- terms that suppress "agent" in BM25 scoring. At sentence-level, D157_s6 is a standalone 15-word sentence where "agent" has high TF-IDF weight.

This is an independent confirmation that sentence-level decomposition improves retrieval breadth (consistent with Exp 29: 100% vs 92% at decision-level). The "vocabulary gap" that motivated HRR (Exp 39) was real at decision-level but partially closed by sentence-level FTS5.

### Revised Assessment of HRR's Value

FTS5 at sentence level covers more than the 92% reported at decision level. The remaining gap is smaller, but HRR remains valuable for:

1. **Queries that share zero vocabulary with any sentence in the target.** The "agent" match in D157_s6 is a lucky overlap. A different query -- say, "tool restrictions" -- would miss D157 entirely at any granularity.
2. **Structural retrieval.** "What is connected to D188 via AGENT_CONSTRAINT?" is a question FTS5 cannot answer regardless of vocabulary overlap.
3. **Cross-vocabulary clusters.** As the belief graph grows beyond one project (alpha-seek), vocabulary gaps between projects will dominate.

### Pipeline Architecture (Validated)

```
Query
  |
  +---> FTS5 on sentence nodes (keyword breadth)
  |
  +---> HRR single-hop (typed structural connections)
  |
  +---> BFS 2-hop from FTS5+HRR hits (exact depth)
  |
  +---> Union + rank
```

The pipeline runs correctly with zero errors. HRR adds no false positives on this ground truth. BFS from the union of FTS5+HRR seeds reaches all 2-hop neighbors. The architecture is sound even though the test data does not exercise the HRR path.

---

## Q4: Vocabulary-Gap Retrieval (D157 Recovery)

**Result: HRR recovers D157 from D188 with similarity 0.2391 and 3.4x behavioral/distractor separation. The combined FTS5+HRR pipeline finds D157 through both paths.**

### Comparison

| Method | D157 Found | D188 Found | Mechanism |
|--------|-----------|-----------|-----------|
| FTS5-only | Yes (rank ~10) | Yes (rank 2) | "agent" in D157_s6 |
| HRR-only (from D188) | Yes (sim 0.2391) | -- | AGENT_CONSTRAINT walk |
| Combined | Yes | Yes | Both paths |

### HRR Walk from D188 via AGENT_CONSTRAINT

| Rank | Node | Similarity | Category |
|------|------|-----------|----------|
| 1 | D100_s0 | 0.2551 | BEHAVIORAL |
| 2 | D157_s0 | 0.2391 | BEHAVIORAL |
| 3 | D073_s0 | 0.2334 | BEHAVIORAL |
| 4 | D188_s3 | 0.0575 | BEHAVIORAL (same decision, different sentence) |
| 5 | D186_s4 | 0.0555 | distractor |
| 6 | D069_s2 | 0.0536 | distractor |
| 7 | D156_s4 | 0.0492 | distractor |
| 8 | D157_s1 | 0.0478 | BEHAVIORAL (D157 second sentence) |

**Separation:** Behavioral mean = 0.1666, distractor mean = 0.0496, ratio = **3.4x**.

### Comparison to Exp 34

Exp 34 Test A reported 184x separation. The difference:

- **Exp 34** used a minimal 9-node subgraph (4 behavioral + 5 distractors) with only AGENT_CONSTRAINT edges. Zero noise from other edge types.
- **Exp 45** uses the full partitioned graph. The behavioral partition contains AGENT_CONSTRAINT edges, but behavioral nodes also appear in decision-neighborhood partitions with CITES and NEXT_IN_DECISION edges. Cross-partition noise reduces separation.

3.4x separation is still clean -- all 3 behavioral beliefs (D100, D157, D073) rank above all distractors. The HRR walk correctly identifies the behavioral cluster despite operating on the full graph rather than a curated test set.

### The D157 Paradox

Exp 39 identified D157 as an "irreducible miss" for FTS5. At sentence level, FTS5 finds D157 at rank ~10 via the word "agent" in D157_s6. This means:

1. **HRR is not required for D157 at sentence level with the specific query "agent behavior instructions."** But it would be required with queries like "tool bans," "command restrictions," or "execution rules" -- none of which share vocabulary with D157.
2. **HRR's value is query-independent.** FTS5's ability to find D157 depends on the query containing a word that happens to appear in one of D157's 9 sentences. HRR's ability to find D157 depends only on the graph edge existing -- any query that reaches D188 (or D100, or D073) can walk to D157 via AGENT_CONSTRAINT.

The vocabulary bridge is a robust retrieval path that does not depend on lucky lexical overlap. FTS5 coverage at sentence level is higher than decision level, but it remains fragile.

---

## Q5: Capacity Analysis

### Current Graph

| Metric | Value |
|--------|-------|
| Nodes | 1,195 |
| Edges | 1,485 |
| Partitions (decision-neighborhood) | 27 |
| Partition sizes | min=50, max=65, mean=55.0, median=54.0 |
| Edge types | CITES (223), NEXT_IN_DECISION (1,022), SAME_TOPIC (240) |

### Capacity Headroom

| Dimension | Capacity (n/9) | Max Partition | Headroom | Partitions Over Capacity |
|-----------|---------------|---------------|----------|--------------------------|
| DIM=2048 | 227 | 65 | 3.5x | 0 |
| DIM=4096 | 455 | 65 | 7.0x | 0 |

All 27 partitions are well within capacity at both dimensions. The decision-neighborhood strategy inherently limits partition size because decisions have a natural scale (5-10 sentences, 5-15 CITES references).

### Memory Footprint

| Dimension | Partition Vecs | Node Vecs | Edge-Type Vecs | Total Vecs | Memory |
|-----------|---------------|-----------|---------------|------------|--------|
| DIM=2048 | 27 | 1,195 | 3 | 1,225 | **19.1 MB** |
| DIM=4096 | 27 | 1,195 | 3 | 1,225 | **38.3 MB** |

Node vectors dominate the memory budget (97.5% of total vectors). Partition superposition vectors are negligible (2.2%).

### Scaling Projections

| Nodes | Edges (projected) | Partitions | DIM=2048 | DIM=4096 |
|-------|-------------------|------------|----------|----------|
| 1,195 | 1,485 | 27 | 19.1 MB | 38.3 MB |
| 10,000 | 12,426 | 226 | 159.8 MB | 319.7 MB |
| 100,000 | 124,267 | 2,260 | 1,597.9 MB | 3,195.7 MB |

**Assumptions:** Edges scale linearly with nodes (1.24 edges/node, observed ratio). Partition size stays ~55 edges (same decision-neighborhood strategy). Node vectors dominate at all scales.

### Analysis

**At 10K nodes** (a few dozen projects worth of beliefs), the system needs 160-320 MB. This is comfortable for a desktop process.

**At 100K nodes** (a large organization's entire belief corpus), the system needs 1.6-3.2 GB. This is still feasible but requires care. Two optimizations are available:

1. **Lazy loading.** Only load partition vectors for active projects. Node vectors can be loaded on demand. If only 10% of nodes are active, memory drops to ~160-320 MB.
2. **Dimensionality reduction.** If DIM=2048 provides sufficient recall (as shown in Q2), use it instead of 4096 -- halving memory at all scales.

The key insight: **node vectors are the bottleneck, not partitions.** At 100K nodes, the 2,260 partition vectors consume only 35 MB (DIM=2048). The 100K node vectors consume 1,563 MB. Any optimization effort should focus on node vector management (lazy loading, quantization, or dimensionality reduction).

---

## Summary of Findings

| Question | Answer | Key Evidence |
|----------|--------|-------------|
| Q1: Best partition strategy | Decision-neighborhood | 100% recall, 27 partitions of 50-65 edges |
| Q2: DIM=4096 vs 2048 | Both achieve 100% recall; 4096 has better separation (2.5x vs 1.9x avg) | 39/39 at both; 2x memory tradeoff |
| Q3: Integrated pipeline | Works correctly; FTS5 alone covers 100% at sentence level | Sentence decomposition closes decision-level vocab gap |
| Q4: Vocabulary gap | HRR recovers D157 from D188 (sim 0.2391, 3.4x separation) | FTS5 also finds D157 at sentence level via lucky "agent" match |
| Q5: Capacity at scale | 19 MB current, 160 MB at 10K, 1.6 GB at 100K (DIM=2048) | Node vectors dominate; lazy loading enables scaling |

## Implications for Architecture

1. **Decision-neighborhood partitioning is the production strategy.** It preserves locality, stays within capacity, and achieves perfect recall. No need to explore alternatives.

2. **DIM=2048 is sufficient for development.** DIM=4096 is recommended for production only when partition sizes grow beyond ~150 edges (which happens with denser graphs or multi-project corpora).

3. **Sentence-level decomposition is more valuable than previously estimated.** It independently closes part of the FTS5 vocabulary gap that was attributed to HRR. HRR remains essential for structural queries and robust cross-vocabulary retrieval, but its marginal contribution on the 6-topic ground truth is zero at sentence level.

4. **The HRR value proposition shifts from "bridging FTS5 gaps" to "structural query capability."** The query "what is structurally connected to D188 via AGENT_CONSTRAINT?" is not expressible in FTS5 at any granularity. This is HRR's irreducible contribution.

5. **Memory at 100K nodes is manageable with lazy loading.** The system does not need to hold all node vectors in memory simultaneously.

---

## Files

| File | Contents |
|------|----------|
| experiments/exp45_hrr_belief_prototype.py | Full prototype: 5 tests, strict typing, pyright clean |
| experiments/exp45_results.json | Raw JSON results |
| experiments/exp45_hrr_results.md | This document |
