# Experiments 58-60: Time Architecture Validation Plan

**Date:** 2026-04-10
**Predecessor:** Exp 57 (time architecture evaluation -- decay-only 100% vs adopted 55%)
**Goal:** Validate the revised time architecture (decay for scoring, structural edges for traversal) on real data and test remaining uncertainties.

---

## Context

Exp 57 found that the adopted time architecture (TEMPORAL_NEXT scoring + decay) scores 55% on case study scenarios because structural recency penalizes locked beliefs. Decay-only scores 100%. The revised proposal:
- Decay for retrieval scoring (locked beliefs immune, content-type-specific half-lives)
- TEMPORAL_NEXT edges for traversal queries only (not ranking)
- Velocity discount from event-sourced design as additional scoring layer

Three uncertainties remain:
1. Are the decay half-lives correct? (Currently guesses: 3d/14d/21d/30d)
2. Do TEMPORAL_NEXT edges provide traversal value that timestamps alone can't?
3. Does temporal re-ranking help or hurt when layered on FTS5+HRR retrieval?

---

## Experiment 58: Decay Half-Life Calibration on Real Data

### Research question
Which decay half-lives per content type maximize correction prevention on the project-a timeline?

### Data source
- Alpha-seek spike DB: 173 decisions, 586 sentence nodes
- Exp 6 correction data: 38 user corrections with timestamps, clustered into 6 topics
- CLAUDE.md locked beliefs: known locked decisions (D073, D100, D157, D188, etc.)
- Git history: 552 commits with timestamps for temporal metadata

### Method
1. Load all 173 decisions with creation timestamps (from spike DB or git history).
2. Classify each decision by content type (constraint, evidence, context, rationale, procedure) using the patterns from Exp 42 (type-aware compression).
3. Tag locked decisions from CLAUDE.md / known behavioral beliefs.
4. Tag superseded decisions from SUPERSEDES edges in the spike DB (if any) or from Exp 6 correction clusters.
5. For each of the 38 corrections from Exp 6:
   a. Set current_time to the correction timestamp.
   b. Score all decisions using decay function with candidate half-lives.
   c. Check: does the correct belief (the one the user was trying to enforce) rank in the top 5? Top 10?
   d. Record hit/miss.
6. Sweep half-lives: for each content type, test [1, 3, 7, 14, 30, 60, never] days.
7. Measure: correction prevention rate (what fraction of the 38 corrections would have been prevented if the decayed ranking had surfaced the right belief?).

### Expected output
- Optimal half-life per content type
- Correction prevention rate at optimal settings
- Sensitivity analysis: how much does the rate degrade with 2x or 0.5x half-life?

### Success criteria
- Correction prevention rate >= 80% at optimal half-lives
- Locked beliefs always rank in top 5 regardless of age
- Superseded beliefs never rank in top 10

### Risks
- The spike DB may not have enough temporal metadata (creation timestamps) for all 173 decisions. Fallback: use git commit timestamps for decisions that reference D### IDs.
- The 38 corrections may not all have clear "right answer" beliefs. Some corrections may be about behavior, not about specific decisions.

---

## Experiment 59: Temporal Traversal Utility

### Research question
Do TEMPORAL_NEXT edges enable useful queries that timestamp filtering alone cannot answer?

### Data source
- Alpha-seek spike DB: 173 decisions with timestamps
- Alpha-seek git history: 552 commits
- Session boundaries: milestone boundaries as proxy for session boundaries

### Method
1. Build two temporal indexes from the project-a timeline:
   a. **Timestamp-only:** each decision has a created_at timestamp. Queries use range filters (created_at > X, created_at BETWEEN X AND Y).
   b. **TEMPORAL_NEXT edges:** decisions linked in creation order. SUPERSEDES edges where applicable. Session boundary markers.

2. Design 10 temporal queries in 4 categories:
   - **Range queries** (3): "What decisions were made in milestone M005?", "What changed in the last 3 days?", "Decisions from sessions 1-5?"
   - **Sequence queries** (3): "What was decided immediately after D097?", "What's the next decision after the capital change?", "What preceded D157?"
   - **Evolution queries** (2): "Show me all decisions about capital/sizing over time", "How did the dispatch gate protocol evolve?"
   - **Causal chain queries** (2): "What superseded approach A?", "Trace the correction chain for calls/puts"

3. For each query, attempt to answer using:
   a. Timestamp filtering only (SQL WHERE on created_at)
   b. TEMPORAL_NEXT traversal (BFS/DFS on temporal edges)
   c. SUPERSEDES chain following
   d. FTS5 + timestamp (keyword match + time range)

4. Evaluate: completeness (did the method find all relevant decisions?), precision (what fraction of results are relevant?), and whether the answer is structurally different (e.g., traversal reveals ordering that timestamps don't).

### Expected output
- Per-query comparison of 4 methods
- Classification: which queries REQUIRE structural edges vs which can be answered by timestamps alone
- Assessment: is the structural edge overhead justified by the query types it uniquely enables?

### Success criteria
- At least 3/10 queries where TEMPORAL_NEXT traversal finds results that timestamp filtering misses
- SUPERSEDES chains are the only way to answer evolution/causal queries correctly
- Clear categorization of query types by which temporal mechanism they need

### Risks
- The project-a spike DB may not have SUPERSEDES edges populated. Fallback: infer supersession from Exp 6 correction clusters (if decision B corrects decision A, A is superseded by B).
- Session boundaries may not be available. Fallback: use milestone boundaries or day boundaries.

---

## Experiment 60: Temporal Re-Ranking Integration with FTS5+HRR

### Research question
Does adding temporal re-ranking as a post-retrieval step improve or degrade the FTS5+HRR pipeline results from Exp 56?

### Data source
- Alpha-seek spike DB: 586 sentence nodes
- Exp 56 pipeline: FTS5 K=30 + HRR (100% coverage, 13/13)
- Temporal metadata: creation timestamps for each decision (from git history or spike DB)

### Method
1. Load the Exp 56 pipeline (FTS5 K=30 + HRR DIM=2048, AGENT_CONSTRAINT + CITES edges).
2. Add temporal metadata to each node: created_at, content_type, locked status.
3. Run the pipeline on all 6 topics.
4. Apply temporal re-ranking as a post-retrieval step:
   a. **No re-rank (baseline):** Exp 56 results as-is.
   b. **Decay re-rank:** multiply each result's retrieval score by its decay factor.
   c. **Decay + lock boost:** decay re-rank, but locked/constraint beliefs get score boosted to top of results.
   d. **Decay + velocity discount:** decay re-rank with session velocity penalty (if session metadata available).
5. Evaluate at K=15 and K=30: coverage, precision, MRR, tokens.
6. Key question: does temporal re-ranking change which decisions are in the top 15? Does it improve MRR (relevant decisions rank higher)?

### Expected output
- Coverage comparison (should stay at 100% if re-ranking doesn't drop relevant results below K)
- MRR comparison (should improve if locked/behavioral beliefs get boosted)
- Precision comparison (should improve if stale irrelevant beliefs get demoted)
- Token comparison (should decrease if stale beliefs drop out of top K)

### Success criteria
- Coverage does not decrease (no regressions from Exp 56)
- MRR improves or stays the same
- Locked behavioral beliefs (D157, D188, D100, D073) rank higher after temporal re-ranking than before

### Risks
- Temporal metadata may be sparse. If most decisions lack timestamps, re-ranking has little to work with.
- The 586-node test set may be too small for temporal effects to matter (all decisions are from a 16-day window, so decay differences are small).
- Velocity discount requires session metadata that may not be available in the spike DB.

---

## Execution Order

All three experiments are independent and can run in parallel. No dependencies between them.

If sequential: Exp 58 first (most important -- validates the core claim that decay scoring prevents corrections), then Exp 60 (validates integration), then Exp 59 (validates traversal utility -- lowest risk, most likely to confirm existing hypothesis).

## Files to Produce

- experiments/exp58_decay_calibration.py
- experiments/exp58_results.json
- experiments/exp58_results.md
- experiments/exp59_traversal_utility.py
- experiments/exp59_results.json
- experiments/exp59_results.md
- experiments/exp60_temporal_reranking.py
- experiments/exp60_results.json
- experiments/exp60_results.md
- TODO.md updated with findings
- SESSION_LOG.md updated
