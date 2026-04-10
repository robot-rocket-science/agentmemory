# Experiment 34 Results: Three Closing HRR Tests

**Date:** 2026-04-09

## Test A: Vocabulary Bridge -- VALIDATED

**Question:** Can HRR connect D157 ("ban async_bash") and D188 ("don't elaborate") despite zero vocabulary overlap?

**Result:** YES. 184.3x separation between behavior nodes and distractors. All 3 behavior nodes ranked above all 5 distractors.

| Rank | Node | Similarity | Category |
|------|------|-----------|----------|
| 1 | D100_s0 | 0.210 | BEHAVIOR (never question calls/puts) |
| 2 | D188_s0 | 0.194 | BEHAVIOR (execute exactly, don't elaborate) |
| 3 | D073_s0 | 0.149 | BEHAVIOR (equal citizens) |
| 4 | D005_s0 | 0.013 | distractor |
| 5-9 | ... | -0.05 to 0.00 | distractors |

**What this proves:** When sentences share an edge type (AGENT_CONSTRAINT) in the HRR graph, they're retrievable from each other regardless of vocabulary. The connection is structural, not lexical.

**Caveat:** The AGENT_CONSTRAINT edges were manually assigned in this test (we classified these 4 decisions as behavioral). In production, the LLM's `directive` tool with `related_concepts` tags would provide this classification. The HRR works IF the edges exist. The question of how edges are created is separate (Exp 32/33 addressed this).

## Test B: Multi-hop -- MARGINAL

**Question:** Does 2-hop traversal work at 25 edges in 2048D?

**Result:** 1/3 recall at top-3. D175_s0 found at rank 3 (sim 0.029). D097_s0 at rank 8 (sim 0.010). D167_s0 not found.

Single-hop remains 5/5. 2-hop is noisy but not random -- real targets appear in the top 10, just below hop-1 residuals and cross-terms.

**What this proves:** 2-hop traversal works at DIM=2048 with 25 edges, but recall is reduced (~33% at top-k). For reliable 2-hop, need higher dimension (DIM=4096 would give SNR ~5.4 per hop).

**What this doesn't prove:** That multi-hop is necessary for our use case. If single-hop reliably finds direct connections (5/5), and the graph is well-connected enough that important nodes are reachable in 1 hop, multi-hop may be unnecessary.

## Test C: Combined Pipeline -- INCONCLUSIVE

**Question:** Does HRR + FTS5 find things neither finds alone?

**Result:** On this test, FTS5 already found everything. HRR added D073 (correct but not needed). The combined pipeline didn't improve over FTS5 alone.

**Why inconclusive:** FTS5's success on the agent_behavior query contradicts the earlier finding (Exp 25) where D157 was missed. The difference is query formulation -- this test used "agent behavior instructions" which has enough OR-terms to match both D157 and D188. A query with fewer terms (or completely different vocabulary like "tool bans and communication rules") would likely miss D157 in FTS5 but find it via HRR.

**What this means:** The combined pipeline's value depends on query formulation. When FTS5 has good keyword overlap with targets, HRR doesn't add value. When FTS5 misses (vocabulary mismatch), HRR is the only path. We need a test case that FTS5 genuinely can't solve to demonstrate the combined value.

## Summary

| Test | Result | Confidence |
|------|--------|-----------|
| Vocabulary bridge | WORKS (184x separation) | HIGH -- clear, reproducible, large effect size |
| Multi-hop at capacity | MARGINAL (1/3 at 2-hop) | MEDIUM -- works but noisy, needs more DIM for reliability |
| Combined pipeline | INCONCLUSIVE | LOW -- FTS5 happened to succeed, need a harder test case |
