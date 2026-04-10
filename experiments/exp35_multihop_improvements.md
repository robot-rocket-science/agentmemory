# Multi-Hop Improvement Analysis

**Date:** 2026-04-09
**Context:** Iterative HRR with cleanup improved 2-hop from 0/3 (direct) to 1/3 (iterative). D097 found at rank 1, but D175 and D167 missed (single-path targets lost in noise). What else can we try?

## Six Approaches Identified from Research Docs

### 1. Iterative HRR with cleanup (VALIDATED)

**Source:** HRR_RESEARCH.md section 4, Exp 34 follow-up
**How:** Unbind one hop, cleanup via nearest neighbor, rebind for next hop
**Result:** D097 rank 9 -> rank 1. Recall 0/3 -> 1/3.
**Limitation:** Only finds multi-path targets. D175/D167 (single path each) missed.
**Status:** Tested, works for strong targets.

### 2. Weighted edge encoding (NOT YET TESTED)

**Source:** GRAPH_CONSTRUCTION_RESEARCH.md section 2
**How:** Scale bound triples by edge weight before superposition:
```
S += edge_weight * bind(bind(node_A, edge_type), node_B)
```
**Rationale:** High-weight edges dominate the superposition. During iterative unbinding, the cleanup step preferentially recovers nodes connected by confident edges. Weak paths produce weak signal; strong paths produce strong signal.
**Expected improvement:** D175/D167 might be found if their connecting edges have higher weight relative to noise edges.
**Connection to Bayesian model:** Edge weight = min(source.confidence, target.confidence). High-confidence beliefs produce high-weight edges.

### 3. Beam search at each hop (NOT YET TESTED)

**Source:** INFORMATION_THEORY_RESEARCH.md (A020), standard graph search
**How:** At each hop, keep top-k cleaned nodes instead of just top-1. Traverse from ALL k nodes at the next hop. Aggregate results across all beams.
**Rationale:** Our iterative test already traversed from all 5 hop-1 results. Formal beam search generalizes this: at hop-2, keep top-k from EACH hop-1 node, giving k^2 candidates at depth 2.
**Expected improvement:** Single-path targets (D175, D167) are more likely to be found because more parallel paths are explored.
**Cost:** O(k^2) cleanup lookups at depth 2. At k=5 and 18 nodes, that's 25 lookups -- trivial.

### 4. HippoRAG Personalized PageRank (RESEARCHED, NOT TESTED)

**Source:** SURVEY.md (A008), Gutierrez et al. NeurIPS 2024
**How:** Run PPR from seed nodes on the explicit graph. PPR computes stationary distribution of a random walker, naturally scoring nodes reachable via many short paths.
**Overlap:** Does the same thing as our multi-path convergence finding (D097 found because 3 paths converged). PPR formalizes this.
**When to use:** On the explicit graph (SQLite adjacency), not in HRR space. Complementary to HRR: PPR for multi-path discovery, HRR for fuzzy-start typed traversal.
**Not tested because:** Requires PPR implementation on the graph. Lower priority than #2 and #3 which improve HRR directly.

### 5. Bayesian confidence along paths (RESEARCHED, NOT TESTED)

**Source:** BAYESIAN_RESEARCH.md section 4
**How:** Multiply HRR similarity at each hop by the cleaned node's Bayesian confidence:
```
hop2_score = hrr_similarity * cleaned_node.confidence
```
**Rationale:** High-confidence intermediate nodes produce more reliable paths. An uncertain intermediate should reduce the path score.
**Overlap:** Connected to weighted edges (#2) -- both use confidence to weight traversal. #2 does it at encoding time, #5 at query time.
**Not tested because:** Needs Bayesian confidence on the test nodes (which are simulation-assigned, not real). Test alongside #2.

### 6. MINERVA RL path finding (FUTURE)

**Source:** INFORMATION_THEORY_RESEARCH.md (A021), Das et al. ICLR 2018
**How:** Learn query-conditioned walks from feedback data.
**Status:** Requires training infrastructure + accumulated query-outcome data from the feedback loop. Not testable now. Candidate for future research when the system has enough usage data.

## Test Plan

**Test #2 (weighted edges) and #3 (beam search) on the D195 neighborhood.**

Same setup as Exp 34 follow-up: 18 nodes, 25 edges, DIM=2048.
Ground truth: D097_s0, D175_s0, D167_s0 (3 hop-2 targets).
Baseline: iterative with cleanup = 1/3 (D097 only).

**Test #2 setup:** Assign edge weights based on simulated confidence. Edges to D097 (highly cited) get high weight. Edges to D175/D167 get moderate weight. Encode with weights.

**Test #3 setup:** At each hop, keep top-5 (beam width = 5). At hop 2, traverse from all 5 cleaned hop-1 nodes, keep top-3 from each, aggregate by max similarity.

**Combined #2+#3:** Weighted encoding + beam search. Should be the best of both.

**Success criteria:** Recall >= 2/3 on the 3 hop-2 targets (improvement over 1/3 baseline).
