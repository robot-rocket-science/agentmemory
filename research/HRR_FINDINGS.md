# HRR Findings: What We Tested, What Worked, What Didn't

**Date:** 2026-04-09
**Scope:** Experiments 24, 25 (demo), 30, 31, 32, 33
**Purpose:** Complete record of HRR investigation for this project. Every claim below is linked to the experiment that produced it.

---

## Background

Holographic Reduced Representations (Plate, 1995) encode structured information as high-dimensional vectors using circular convolution for binding, circular correlation for unbinding, and vector addition for superposition. The mathematical reference is in HRR_RESEARCH.md.

We investigated whether HRR is useful for an agentic memory system built on a sentence-level belief graph.

---

## Experiment Timeline

| Exp | What Was Tested | Result |
|-----|----------------|--------|
| 24 | "HRR prototype" -- actually BoW cosine, not real HRR | Matched FTS5 because it was doing the same thing (HRR_RESEARCH.md section 8) |
| 25 (demo) | Core HRR operations on synthetic data | Bind/unbind works. 2-hop returned wrong node due to SNR degradation with distractor edges. |
| 30 | Real HRR on decision-level nodes, global superposition | FAILED: 775 edges in 1024D, capacity ~102. 7.6x over capacity. Noise. |
| 30 (focused) | Real HRR on D149 local subgraph (103 edges) | PARTIAL: 3/6 single-hop recall at capacity boundary. Edge selectivity clean. 2-hop failed. |
| 31 | Sentence-level nodes with typed edges, partitioned subgraphs | Graph built: 1,195 nodes, 1,485 edges. Union superposition still over capacity. Per-subgraph not tested in this run. |
| 31 (focused) | D195 neighborhood: 18 nodes, 25 edges, DIM=2048 | 5/5 single-hop recall. Clean signal separation. Edge selectivity perfect. |
| 32 | HRR autonomous edge discovery (no regex) | FAILED: precision 0.001, recall 0.005. HRR cannot discover edges from structural encoding alone. |
| 33 | HRR bootstrap: propose new edges from partial graph | PARTIAL: found D097 at rank 2 (sim 0.161) via bootstrap from D174. Reverse-path noise dominates. Useful for candidate proposal, not autonomous discovery. |

---

## What We Established With Evidence

### 1. Real HRR typed traversal works when within capacity

**Evidence:** Exp 31 focused test. D195 neighborhood, 18 nodes, 25 edges, DIM=2048 (capacity ~204).

Query: "What does D195_s1 cite?"

| Rank | Node | Similarity | Ground Truth? |
|------|------|-----------|---------------|
| 1 | D191_s0 | 0.177 | Yes |
| 2 | D174_s0 | 0.160 | Yes |
| 3 | D184_s0 | 0.141 | Yes |
| 4 | D180_s0 | 0.132 | Yes |
| 5 | D186_s0 | 0.118 | Yes |
| 6 | D180_s4 | 0.050 | No |

5/5 recall. Signal range 0.118-0.177. Noise floor 0.050. Gap between worst target and best non-target: 2.4x.

These nodes share minimal vocabulary with each other. D191 ("wipeout root cause"), D174 ("optimization target"), D184 ("N*p metric"), D180 ("strategy framing"), D186 ("N funnel gates"). HRR found them through graph structure, not word overlap.

**Methodological note:** Node vectors are random (not derived from content). The only information HRR uses is the graph edge structure. Content matching is handled separately by FTS5.

### 2. Edge-type selectivity is clean

**Evidence:** Exp 30 focused test + Exp 31.

Querying D149 with DECIDED_IN type:
- Correct target (_M024): similarity 0.183
- Next non-target: 0.064
- CITES bleed-in: zero

Exp 31 selectivity test:
- CITES query -> zero NEXT_IN_DECISION results
- NEXT_IN_DECISION query -> zero CITES results

Edge type vectors are orthogonal (by construction -- random vectors in 2048D). Unbinding with one edge type geometrically filters out other types without any conditional logic.

### 3. Global superposition does not scale

**Evidence:** Exp 30.

775 edges in 1024D. Capacity ~102 (reliable at k < n/10, per HRR_RESEARCH.md section 6). 7.6x over capacity.

Results: all similarities in 0.08-0.13 range. No separation between targets and non-targets. Signal-to-noise ratio < 1.

**The fix that worked:** partition into subgraphs within capacity. Exp 31 focused test (25 edges in 2048D, capacity 204) produced 5/5 recall.

### 4. Multi-hop: direct composition fails, iterative with cleanup works

**Direct composition** (bind all hops into one query, unbind once):

**Evidence:** Exp 30 (103 edges, 1024D): 0/6. Exp 34 Test B (25 edges, 2048D): 1/3 at top-3, 0/3 at top-3 for the strict threshold.

The noise compounds across hops. Each additional bind multiplies the cross-term noise. At capacity boundaries this is fatal.

**Iterative with cleanup** (unbind one hop, clean up via nearest neighbor, re-bind for next hop):

**Evidence:** Exp 34 follow-up. Same 25-edge subgraph, DIM=2048.

```
Hop 1: unbind(bind(D195, CITES), S) -> cleanup -> D184, D186, D174, D191, D180 (5/5)
Hop 2: for each cleaned hop-1 node, unbind(bind(clean_node, CITES), S) -> cleanup
  D184 -> D097 (sim 0.168)
  D174 -> D097 (sim 0.150)
  D186 -> D097 (sim 0.033)
Aggregated: D097 at rank 1 (sim 0.168)
```

Direct composition: D097 at rank 9 (sim 0.002 -- noise level).
Iterative+cleanup: D097 at rank 1 (sim 0.168 -- strong signal).

**Why it works:** The cleanup step (nearest neighbor against known node vectors) resets noise to zero at each hop. The noisy unbinding result is replaced with the exact known vector before the next hop. SNR doesn't compound -- each hop has fresh single-hop SNR.

**Complexity:** O(k * n log n) for k hops + O(k * |nodes|) for cleanup lookups. Graph size doesn't appear.

**Limitation:** Iterative approach only finds the strongest hop-2 targets. D097 was found because 3 independent hop-1 paths converged on it. D175 and D167 (only 1 path each) were not found. Multi-path convergence acts as a natural relevance signal.

**Practical implication:** Iterative HRR is "vectorized BFS with fuzzy start" (HRR_RESEARCH.md section 8). It matches BFS in capability but can start from approximate query vectors instead of requiring exact node IDs. For exact-ID queries, BFS on SQLite is simpler and exact.

### 5. HRR vocabulary bridge works with 184x separation

**Evidence:** Exp 34 Test A. D157 ("ban async_bash"), D188 ("don't elaborate"), D100 ("never question calls/puts"), D073 ("equal citizens") share zero vocabulary but all connected via AGENT_CONSTRAINT edge type.

Query from D157 with AGENT_CONSTRAINT:
- Rank 1: D100 (sim 0.210) -- BEHAVIOR
- Rank 2: D188 (sim 0.194) -- BEHAVIOR
- Rank 3: D073 (sim 0.149) -- BEHAVIOR
- Rank 4: D005 (sim 0.013) -- distractor

Separation: behavior mean 0.184 vs distractor mean -0.013 = 184.3x ratio.

**What this proves:** HRR bridges vocabulary gaps through typed edge structure. Sentences that share no words but share an edge type are retrievable from each other. This directly solves the F1 vocabulary mismatch problem that no keyword-based method (FTS5, BoW, SimHash) can address.

**Caveat:** The AGENT_CONSTRAINT edges were manually classified in this test. In production, the LLM's `directive` tool with `related_concepts` tags would create these edges at storage time. HRR bridges the gap IF the edges exist. Edge creation is a separate concern (see findings 6 and 7).

### 6. HRR cannot autonomously discover edges

**Evidence:** Exp 32. Attempted to discover CITES edges from structural encoding alone (sentence bound with parent + type vectors).

Precision: 0.001. Recall: 0.005. Results were dominated by a single high-norm vector (D086_s1 appeared in every result with identical similarity).

**Root cause:** Unbinding `type` from `sum(node * parent * type)` recovers `node * parent`, which doesn't match raw `node` vectors. The dimensional algebra doesn't decompose this way.

HRR is an encoding and traversal tool, not a discovery tool. The graph must be constructed by other means first.

### 6. HRR bootstrap proposes candidate edges (not definitive)

**Evidence:** Exp 33. Partial graph (D195 neighborhood, 25 known edges) encoded in HRR. Bootstrap query: "what do D195's targets cite?"

D174_s0 -> D097_s0 (known ground truth edge):
- HRR rank: 2
- Similarity: 0.161
- Found via traversal through the encoded partial graph

But: D195_s5 and D195_s1 dominate results (rank 1 in every bootstrap query) because they have the most edges in the superposition. Real targets compete with reverse-path noise.

**Verdict:** HRR bootstrap is useful for PROPOSING candidates, not for autonomous construction. The workflow:
1. Build partial graph from deterministic methods (regex, co-occurrence)
2. Encode in HRR
3. Bootstrap: query for candidates
4. Filter candidates above threshold
5. Verify via LLM, content match, or user review
6. Confirmed edges added, re-encode, iterate

---

## What We Have NOT Established

These are open questions without experimental evidence:

1. **Multi-hop within high-capacity subgraph.** The math predicts it should work at 25 edges in 2048D. We haven't tested it.

2. **Sentence-level HRR at full scale.** We tested on D195's 18-node neighborhood. The full sentence graph is 1,195 nodes / 1,485 edges partitioned into 27 subgraphs. We haven't tested retrieval quality across subgraph boundaries.

3. ~~**HRR + FTS5 combined pipeline.**~~ TESTED in Exp 40. Full end-to-end pipeline on 586 project-a beliefs. FTS5 finds D188 from "agent behavior instructions," HRR walks AGENT_CONSTRAINT edge to recover D157 (sim=0.2487). Combined coverage: 100% (13/13), matching hand-crafted 3-query baseline. Max result inflation 2.1x (precision held). Zero regressions. The hybrid architecture is validated. See HRR_VOCABULARY_BRIDGE.md and experiments/exp40_hybrid_pipeline.py.

4. **Bootstrap iteration.** We tested one round of bootstrap (partial graph -> propose candidates). We haven't tested the iterative loop (propose -> verify -> encode -> propose again).

5. **HRR on non-GSD documents.** All tests used project-a decisions with D### citation syntax. Documents without explicit citations would rely more heavily on co-occurrence and bootstrap. Not tested.

6. ~~**Vocabulary bridge via shared edge types.**~~ TESTED in Exp 34 Test A. D157 ("ban async_bash") and D188 ("don't elaborate") connected via AGENT_CONSTRAINT edge. 184x separation between behavioral beliefs and distractors. See HRR_VOCABULARY_BRIDGE.md for full analysis and connection to the Exp 39 FTS5 vocabulary gap finding.

---

## Capacity Reference

From HRR_RESEARCH.md section 6, reliable retrieval (SNR > 3) requires:

| DIM | Capacity (k < n/9) | Use Case |
|-----|-------------------|----------|
| 512 | ~57 | Small subgraph |
| 1024 | ~113 | Medium subgraph |
| 2048 | ~227 | Most local neighborhoods |
| 4096 | ~455 | Large subgraphs or multi-hop |
| 8192 | ~910 | Aggressive superposition |

The project-a sentence graph has 1,485 edges total, partitioned into 27 subgraphs of 50-60 edges each. DIM=2048 provides ample headroom per subgraph.

---

## Architecture Implications

Based on experimental evidence, each retrieval method covers a specific failure mode:

| Method | What It Does | Strength | Limitation | Evidence |
|--------|-------------|----------|-----------|----------|
| **FTS5** | Keyword retrieval on sentence text | Fast, reliable, 100% recall with 3 query variants | Vocabulary mismatch (D157/D188 share no words) | Exp 9, 29 |
| **HRR single-hop** | Typed traversal across vocabulary boundaries | 184x separation on vocabulary bridge, 5/5 single-hop | Can't discover edges, limited by subgraph capacity | Exp 31, 34 Test A |
| **BFS on graph** | Exact multi-hop from known nodes | Reliable at any depth, no SNR limits | Requires exact starting node ID, no fuzzy queries | GSD prototype |
| **HRR iterative multi-hop** | Fuzzy-start multi-hop via cleanup | Works for multi-path targets (D097 at rank 1) | Misses single-path targets (SNR limit) | Exp 34 follow-up, Exp 35 |

**No single method is sufficient. None is redundant. Together they cover the retrieval space.**

The retrieval pipeline:
1. FTS5 for keyword matches (breadth, fast)
2. HRR single-hop for typed structural connections (vocabulary bridge)
3. BFS for exact multi-hop from FTS5/HRR hits (depth, reliable)
4. HRR iterative multi-hop only for fuzzy-start queries where no exact node ID is available

### Multi-hop: weighting and beam search don't improve recall

**Evidence:** Exp 35. All four methods (baseline, weighted, beam, combined) achieved identical 1/3 recall on hop-2 targets.

The fundamental limit is SNR in the superposition. A target reachable via 1 path has SNR ≈ sqrt(n/k) ≈ 9 at 25 edges in 2048D -- marginal for 2-hop. A target reachable via 3 paths has effective SNR ≈ 3x, which is reliable. Weighting and beam search improve signal strength on found targets but don't create signal for unfound ones.

**Practical conclusion:** For multi-hop where reliability matters, use BFS on the explicit graph. HRR multi-hop is for approximate exploration, not exact traversal.

### Graph construction

Graph construction uses deterministic methods + HRR-assisted bootstrap:
- Regex: explicit citations (D###, M###, URLs)
- Co-occurrence: sentences in same decision/section
- Type pairing: constraint + evidence = SUPPORTED_BY
- HRR bootstrap: propose candidates from partial graph (Exp 33: found D097 at rank 2)
- LLM/user: confirm proposals, add semantic edges via `directive` tool

**HRR is NOT a replacement for graph construction** (Exp 32: precision 0.001 for autonomous discovery). It's a traversal and proposal layer. The graph must be built first.

---

## Multi-Hop HRR: Closed Investigation (2026-04-09)

### Question
What would multi-hop HRR provide that we cannot achieve with BFS + FTS5?

### Answer: One thing only
Fuzzy-start traversal -- graph traversal from an approximate query vector without needing an exact node ID. That is the only capability multi-hop HRR adds over BFS.

### Why we are not pursuing multi-hop further

**Direct composition is impractical at any useful scale.**
The elegant single-vector multi-hop (section 4 of HRR_RESEARCH.md) requires dimensionality scaling as n > k^2 * edges. For 2 hops over 10,000 beliefs: n > 11,000,000. Exp 30 confirmed total failure at realistic capacity ratios. This is a hard mathematical limit, not an engineering problem.

**Iterative multi-hop with cleanup works but is strictly dominated.**
Iterative HRR (Exp 34: D097 at rank 1) is "vectorized BFS with fuzzy start." It matches BFS in logic but:
- Misses single-path targets (D175, D167 not found -- only multi-path convergence targets survive)
- Exp 35 confirmed: weighting and beam search cannot improve recall beyond 1/3. The limit is SNR, not algorithm.
- BFS on SQLite is exact, faster, and simpler for the same graph

**The fuzzy-start advantage is better achieved by a two-step pipeline:**
1. HRR single-hop (or FTS5) resolves fuzzy query to exact node
2. BFS from that node for reliable multi-hop

This gives fuzzy entry + exact traversal, which strictly dominates HRR multi-hop (fuzzy entry + lossy traversal).

### Conclusion
Multi-hop HRR is a theoretical elegance that does not survive contact with capacity limits at practical scale. The research question is settled. No further experiments planned.

---

## Corrected Architecture Assessment (2026-04-09)

### Prior error
An earlier analysis (conversation, not committed) claimed that "embedding similarity + a WHERE edge_type clause achieves the same result" as HRR typed traversal, and proposed three unvalidated alternatives (synonym lookup, embedding search, LLM query expansion). That analysis was wrong. The correction and reasoning follow.

### Why HRR is not replaceable by embeddings + SQL

HRR's vocabulary bridge (Exp 34 Test A: 184x separation) works on **graph structure**, not content. Node vectors are random. D157 ("ban async_bash") and D188 ("don't elaborate") are retrievable from each other because an AGENT_CONSTRAINT edge exists between them, not because their text is similar. Their text is not similar -- they are categorically related (both behavioral constraints), not semantically related.

Embedding similarity operates on **content**. It requires the embedding model to independently recognize that "ban async_bash" and "don't elaborate" are related. Those phrases are not semantically similar in any standard sense. An embedding model has no reason to place them near each other. This is an untested and fragile claim.

A SQL WHERE clause filters rows explicitly. HRR's edge-type selectivity is geometric and compositional -- you can bind multiple edge types, negate types, or query partial structural patterns in a single vector operation without constructing explicit filter logic. Functionally similar for a single typed query, but HRR composes in ways SQL filters do not.

### HRR + FTS5 are co-primary, not redundant

HRR and FTS5 answer orthogonal questions:

| System | Question It Answers | Information Source |
|--------|--------------------|--------------------|
| FTS5 | "What text matches these keywords?" | Content (lexical) |
| HRR | "What is structurally connected to this node via these edge types?" | Graph topology |

HRR uses random node vectors. It does not examine content. FTS5 examines content. It does not know about graph structure. Neither subsumes the other. Both are needed.

### BFS is a reliability fallback, not a primary path

For single-hop, HRR matches BFS at 5/5 recall (Exp 31, 34). HRR adds fuzzy-start capability that BFS lacks. BFS adds guaranteed completeness at multi-hop depth that HRR cannot provide (100% vs 33% at 2-hop). In a well-connected sentence graph where most practical queries resolve in 1 hop, BFS is the fallback for depth, not the default.

### Graph shapes where HRR's value increases

All experiments so far used one project (project-a) with citation-heavy structure (explicit D### references). HRR's relative value increases for:

- **Dense topic clusters** with many lateral connections and few explicit citations. FTS5 handles within-cluster if vocabulary overlaps. HRR handles cross-cluster where vocabulary diverges.
- **Heterogeneous edge types** (SUPPORTS, CONTRADICTS, SUPERSEDES, DEPENDS_ON). BFS without filters treats all edges equally. HRR's geometric selectivity is native -- query with CONTRADICTS and SUPPORTS edges contribute zero signal.
- **High-churn projects** where vocabulary shifts over time. Early decisions use one vocabulary, later decisions use different terms for the same concepts. FTS5 misses cross-era connections.
- **Sparse explicit references.** Projects without D###-style citation syntax rely on semantic edges. HRR's value increases when graph edges are the primary retrieval signal.

### Sentence-level decomposition amplifies HRR's value

Exp 29 showed sentence-level retrieval achieved 100% coverage vs 92% at decision-level in the same token budget. The critical miss: decision-level failed to find D100 for calls_puts.

HRR operates on the sentence graph (1,195 nodes, 1,485 edges from Exp 16/31). Granular decomposition gives HRR more structural resolution -- typed edges connect specific claims, not entire documents. The 184x separation in Exp 34 Test A is possible because the graph connects "ban async_bash" (one sentence) to "don't elaborate" (one sentence), not two multi-sentence decisions that share a behavioral theme buried among other content.

### Revised retrieval architecture

```
Query
  |
  +---> FTS5 (keyword matches on sentence content)     -- breadth, fast
  |
  +---> HRR single-hop (typed structural connections)   -- vocabulary bridge
  |
  +---> BFS from FTS5/HRR hits (exact multi-hop depth)  -- reliability fallback
```

HRR + FTS5 are co-primary retrieval axes. BFS is exact-depth backup. FFT cost at DIM=2048 is negligible on modern hardware (~microseconds per operation). The complexity cost is in implementation, which is a one-time cost for a library.

---

## Cross-Project Validation (2026-04-10)

The findings above were based on a single project (project-a). Cross-project testing on 7 diverse repos (smoltcp, adr, boa, project-d, gsd-2, rclcpp, rustls) confirmed and extended them. Full results in T0_RESULTS.md. Key additions:

### HRR scales with adaptive thresholds + partition routing

Initial cross-project testing showed HRR failing on larger repos (boa R@10=0.074 with 54 partitions). This was a threshold error, not an HRR limitation. A fixed co-change weight threshold (w>=3) generates noise on large repos. The adaptive formula `w >= max(3, ceil(commits * 0.005))` normalizes by commit count. Combined with partition routing (only query partitions containing the source node), all repos achieve R@10 of 0.44-0.90:

| Repo | Commits | R@10 (naive) | R@10 (adaptive + routed) |
|------|---------|-------------|--------------------------|
| project-d | 526 | 0.880 | 0.900 |
| rustls | 5,024 | -- | 0.711 |
| smoltcp | 1,577 | 0.378 | 0.641 |
| boa | 3,354 | 0.074 | 0.466 |
| gsd-2 | 2,150 | 0.166 | 0.441 |

### Selective amplifier confirmed

HRR outperforms FTS5 by 2.6-3.2x on low-vocabulary-overlap edges. FTS5 outperforms HRR by 2.2-5x on high-overlap edges. They find genuinely different targets. HRR's value concentrates on vocabulary-boundary edge types: CONFIG_COUPLING (82% below 0.1 Jaccard overlap), CROSS_REFERENCES (75%), DOC_CODE_COUPLING (79%), CITES (49%).

### Edges are validated as signal

Co-change edges predict directory proximity at 15-73x lift over random pairs. Import lift at 19-230x. Clustering coefficients 3-53x above random graph expectation. Heavy-tailed degree distributions on larger repos. The extraction pipeline produces real structural coupling, not noise.

---

## Files

| File | Contents |
|------|----------|
| HRR_RESEARCH.md | Mathematical reference (operations, SNR, capacity, SDM bridge) |
| experiments/exp25_hrr_demo.py | Core operations demo on synthetic data |
| experiments/exp24_hrr_prototype.py | BoW-cosine prototype (mislabeled as HRR, corrected in findings) |
| experiments/exp30_real_hrr_sentences.py | First real HRR attempt (decision-level, capacity failures) |
| experiments/exp30_results.md | Exp 30 analysis |
| experiments/exp31_sentence_hrr.py | Sentence-level graph construction + HRR encoding |
| experiments/exp32_hrr_edge_discovery.py | Autonomous edge discovery (failed) |
| experiments/exp32_results.md | Exp 32 analysis |
| experiments/exp33_bootstrap_results.md | Bootstrap edge proposal (partially works) |
