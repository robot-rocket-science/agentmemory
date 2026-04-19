# Experiment 40: FTS5 + HRR Hybrid Retrieval End-to-End Test

**Date:** 2026-04-10
**Type:** Integration test
**Question:** Does the FTS5 -> HRR graph walk pipeline recover beliefs that FTS5 alone misses, without flooding results with noise?
**Critical test case:** Query "agent behavior instructions" -> FTS5 finds D188 -> HRR walks AGENT_CONSTRAINT edge -> D157 recovered.
**Dependencies:** Exp 31 (HRR single-hop), Exp 34 (vocabulary bridge), Exp 39 (FTS5 baseline + the 8% gap)

---

## Why This Matters

Every piece works in isolation:
- FTS5 retrieves 92% of critical beliefs (Exp 39)
- HRR bridges vocabulary gaps with 184x separation (Exp 34 Test A)
- Source-stratified priors handle confidence at scale (Exp 38)

But the integrated pipeline -- FTS5 seeds the HRR walk, HRR neighbors get merged with FTS5 results -- has never been tested. If integration fails (noise compounds, partitions misalign, precision collapses), the hybrid architecture in PLAN.md is theoretical, not validated.

---

## What We're Testing

```
Query: "agent behavior instructions"
  |
  v
[Step 1: FTS5 search] -> top-30 results
  |   FTS5 finds D188 ("execute exactly, don't elaborate")
  |   FTS5 misses D157 ("ban async_bash") -- zero vocabulary overlap
  v
[Step 2: Seed HRR walk] -> for each FTS5 hit:
  |   Look up which HRR partition contains this node
  |   Unbind the partition superposition with each edge type
  |   Collect neighbors above similarity threshold
  v
[Step 3: Union + deduplicate]
  |   Merge FTS5 results + HRR neighbors
  |   Remove duplicates
  v
[Step 4: Rank]
  |   FTS5-only hits ranked by BM25
  |   HRR-only hits ranked by HRR similarity
  |   Hits found by both get a boost
  v
[Output] -> should contain both D188 (from FTS5) and D157 (from HRR)
```

---

## Hypotheses

### H1: Combined pipeline achieves 100% coverage (13/13)

FTS5 alone: 12/13 (misses D157). Combined: 13/13.

**Null:** Combined pipeline still misses D157 (HRR walk doesn't reach it, or noise buries it).

### H2: Precision doesn't collapse

HRR walk from FTS5 seeds should add 5-15 relevant neighbors, not 100+ noise results.

**Measured as:** Total unique results returned by combined pipeline vs FTS5-only. If combined returns > 3x the results of FTS5-only, precision is degrading.

**Null:** Combined pipeline returns > 3x the results of FTS5-only due to HRR noise.

### H3: Automatic edge detection finds behavioral beliefs

Correction detection V2 patterns (imperative verbs, always/never, negation) applied to the 586 belief nodes should identify D157, D188, D100, D073 as directives and connect them via AGENT_CONSTRAINT edges without manual classification.

**Null:** V2 misses >= 2 of the 4 known behavioral beliefs.

---

## Phase 1: Mechanism Test (Manual Edges)

Tests: does the pipeline work when edges are provided?

### Step 1: Prepare the belief corpus

**Data source:** Alpha-seek DB (586 active belief nodes, same as Exp 39).

**What to do:**
1. Load all 586 nodes from the project-a DB
2. Extract D### citation references from each node's content -> CITES edges
3. Manually tag known behavioral beliefs as AGENT_CONSTRAINT:
   - D157: "ban async_bash/await_job"
   - D188: "execute exactly, don't elaborate"
   - D100: "never question calls/puts direction"
   - D073: "calls and puts are equal citizens"
   - Scan for additional candidates: search for "BANNED", "Never", "always", "must not", "do not" in belief content

**Output:** A graph with nodes (586 beliefs), CITES edges (from D### references), and AGENT_CONSTRAINT edges (manual + scan).

### Step 2: Encode the graph in HRR

**What to do:**
1. Assign random vectors (DIM=2048) to each of the 586 belief nodes
2. Assign random vectors to each edge type: CITES, AGENT_CONSTRAINT (and any others present)
3. Partition the graph into subgraphs that fit within HRR capacity (< 200 edges per partition at DIM=2048)
   - Partitioning strategy: group by decision neighborhood (all sentences from D157 + its CITES targets + its AGENT_CONSTRAINT neighbors form one partition)
   - If a partition exceeds 200 edges, split further
   - Behavioral beliefs MUST share a partition (or connected partitions) for the vocabulary bridge to work
4. For each partition, build the HRR superposition: S = sum(bind(node_i, edge_type_j)) for all edges
5. Verify single-hop retrieval works within each partition (sanity check: replicate Exp 31's 5/5 recall)

**Output:** Dictionary mapping partition_id -> superposition vector. Lookup table mapping node_id -> partition_id.

### Step 3: Build the pipeline

**What to do:**
1. FTS5 pass: search query against FTS5 index, collect top-30 results with BM25 scores
2. HRR pass: for each FTS5 hit:
   a. Look up its partition_id
   b. Load the partition superposition
   c. Unbind with each edge type vector: `unbind(S, AGENT_CONSTRAINT_vec)`, `unbind(S, CITES_vec)`
   d. Compute cosine similarity of the unbound result against all node vectors in this partition
   e. Collect nodes above a similarity threshold (use 0.10 based on Exp 34: worst behavior node was 0.149, best distractor was 0.013)
3. Union: merge FTS5 results + HRR neighbors, deduplicate by node ID
4. Rank: FTS5-only results keep BM25 rank. HRR-only results ranked by similarity. Both-found results get top rank.

**Output:** Ranked list of belief nodes for each query.

### Step 4: Evaluate

**What to do:**
1. Run all 6 Exp 9/39 topics through the pipeline
2. For each topic, record:
   - FTS5-only hits (with BM25 scores)
   - HRR-only hits (with similarity scores, which edge type produced them)
   - Combined hits
   - Coverage: which of the needed decisions were found?
   - Precision proxy: total results returned
3. Compare:
   - FTS5-only: expected 12/13 (baseline from Exp 39)
   - Combined: target 13/13
   - Hand-crafted 3-query: 13/13 (from Exp 9)

**Key diagnostic:** For the agent_behavior topic specifically:
- Did FTS5 find D188? (Expected: yes)
- Did HRR walk from D188 via AGENT_CONSTRAINT find D157? (This is THE test)
- What else did HRR return? (Expect D100, D073. If it returns 50 random nodes, precision collapsed)

---

## Phase 2: Automatic Edge Detection

Tests: can edges be created without manual classification?

### Step 5: Run correction detection V2 on belief corpus

**What to do:**
1. Apply V2 directive patterns to all 586 belief nodes:
   - Imperative verbs: "use", "run", "never", "always", "must", "ban"
   - Negation patterns: "do not", "don't", "never", "BANNED"
   - Declarative+emphasis: ALL CAPS words, exclamation marks
   - always/never absolutes: "always X", "never Y"
2. Classify detected directives
3. Auto-assign AGENT_CONSTRAINT edges between all detected directive beliefs
4. Report: which beliefs were detected? Did it find D157, D188, D100, D073?

**Output:** Automatically-detected edge set. Comparison against manual edge set from Phase 1.

### Step 6: Re-run pipeline with automatic edges

**What to do:**
1. Replace manual AGENT_CONSTRAINT edges with auto-detected ones
2. Re-encode HRR superpositions
3. Re-run all 6 topics
4. Compare coverage: does automatic edge detection maintain 13/13?

**Key question:** Does correction detection V2 find D157? The content "BANNED. Never use async_bash or await_job" contains "BANNED" (ALL CAPS), "Never" (absolute), "use" (imperative verb). All three V2 patterns match. High probability of detection, but not guaranteed because V2 was trained on user corrections in conversation, not document-level directives.

---

## Phase 3: Stress Tests (If Phases 1-2 Pass)

### Step 7: Cross-partition retrieval

**What to do:** Deliberately place D157 and D188 in different HRR partitions. Run the pipeline. Does it still find D157?

**Expected:** It should fail -- HRR only walks within a partition. This validates that partition design matters and that behavioral beliefs must share a partition.

### Step 8: Multiple edge types simultaneously

**What to do:** Walk both CITES and AGENT_CONSTRAINT from the same FTS5 seed. Do the results make sense? Does CITES bleed into AGENT_CONSTRAINT results?

**Expected:** No bleed (edge type vectors are orthogonal, confirmed in Exp 30). But verify at full graph scale.

### Step 9: All extraction layers combined

**What to do:** Add CALLS edges (from Exp 37b), CO_CHANGED edges (from git), and CITES edges alongside AGENT_CONSTRAINT. Encode the full multi-type graph. Does HRR selectivity hold with 4+ edge types?

**Expected:** Should work at DIM=2048 with up to ~15 edge types (per EDGE_TYPE_TAXONOMY.md capacity table). But verify empirically.

---

## Success Criteria

| Phase | Criterion | Pass/Fail Threshold |
|-------|----------|-------------------|
| Phase 1 | Combined pipeline finds D157 | D157 in results for agent_behavior topic |
| Phase 1 | Coverage reaches 13/13 | All 6 topics at 100% |
| Phase 1 | Precision doesn't collapse | Combined results < 3x FTS5-only results per topic |
| Phase 2 | V2 detects D157 as directive | D157 in auto-detected set |
| Phase 2 | Auto edges maintain 13/13 | Same coverage as manual edges |
| Phase 3 | Cross-partition fails gracefully | D157 not found, no crash, clear diagnostic |
| Phase 3 | Edge types don't bleed | CITES walk returns 0 AGENT_CONSTRAINT-only nodes |

---

## What You Need to Do (Step by Step)

### Prerequisites
- Alpha-seek DB available at the existing path (verified: 5.7MB, 586 nodes)
- numpy available (for HRR vectors)
- Experiment scripts from Exp 31/34/39 available (for reuse)

### Your Steps

1. **Review this plan.** Flag anything that seems wrong or missing.

2. **Say "go" for Phase 1.** I'll build one experiment script (exp40_hybrid_pipeline.py) that:
   - Loads the 586 nodes + builds FTS5 index (from Exp 39)
   - Scans for behavioral beliefs (manual list + directive pattern scan)
   - Extracts CITES edges from D### references
   - Encodes graph in HRR with partition routing
   - Runs the full FTS5 -> HRR -> union pipeline on all 6 topics
   - Reports coverage, precision, and per-topic diagnostics

3. **Review Phase 1 results.** If D157 is found and precision is acceptable, say "go" for Phase 2. If not, we diagnose why.

4. **Say "go" for Phase 2.** I'll add automatic directive detection to the same script and re-run.

5. **Review Phase 2 results.** If auto edges maintain coverage, say "go" for Phase 3 stress tests. If not, we identify the edge creation gap.

6. **Phase 3 is optional.** Only needed if Phases 1-2 pass and you want to push the boundaries.

### Time Estimate

Phase 1 script + run: one prompt cycle (I build it, run it, report results).
Phase 2: one additional prompt cycle.
Phase 3: one prompt cycle per stress test.

### What Could Go Wrong

| Risk | Impact | Mitigation |
|------|--------|-----------|
| D157 and D188 end up in different partitions | Phase 1 fails | Force behavioral beliefs into same partition by design |
| HRR noise buries D157 below threshold | Phase 1 fails | Lower threshold, report at what threshold D157 appears |
| V2 doesn't detect D157 as directive | Phase 2 fails | Phase 1 already proved the pipeline works with manual edges; document V2 gap |
| FTS5 doesn't find D188 for this query | Phase 1 fails at step 1 | Verified in Exp 39: FTS5 finds D188. If it doesn't, use PRF (also proven) |
| Precision collapse from HRR noise | Phase 1 H2 fails | Report exact counts, adjust threshold, analyze noise sources |
