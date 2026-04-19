# Experiment 47: Baseline Comparison -- Can We Beat Grep?

**Date:** 2026-04-10
**Status:** Planning
**Risk level:** EXISTENTIAL. If grep wins, the project needs to understand why before building more.
**Depends on:** Exp 9/39 (ground truth topics), Exp 40 (hybrid pipeline), project-a belief corpus

---

## 1. The Question

PLAN.md Phase 0 requires: "Implement filesystem baseline (Letta's grep approach)" and compare against our architecture. Letta reported 74% LoCoMo with filesystem+grep+gpt-4o-mini. We have never run this comparison.

The question is NOT "do we beat 74% on LoCoMo?" (different benchmark, different conditions). The question is: **on our own real-world test cases (6 topics, 13 critical decisions from project-a), does our retrieval architecture outperform grep?**

If grep achieves 100% coverage on the same test set, our architecture adds complexity for zero retrieval gain. The value would then need to come from other dimensions (token efficiency, confidence, conflict detection) -- but retrieval is the foundation.

---

## 2. Methods Under Test

### A. Grep Baseline (Letta-style)
- Store all 173 decisions as individual text files in a directory
- Given a query, run `grep -i` for each query term across all files
- Return files containing any query term, ranked by term frequency (count of matches)
- No stemming, no BM25, no graph. Pure text search.

### B. Grep + Sentence Splitting
- Same as A, but on 1,195 sentence-level nodes instead of 173 decision files
- Tests whether sentence-level decomposition (Exp 16) helps even the simplest baseline

### C. FTS5 (our text baseline)
- SQLite FTS5 with porter stemming, BM25 ranking
- Single query per topic (from CRITICAL_BELIEFS)
- This is what Exp 9/39 already measured

### D. FTS5 + PRF (pseudo-relevance feedback)
- Two-pass FTS5: first pass retrieves top-5, extracts TF-IDF terms, second pass with expanded query
- From Exp 39: maintains 92% baseline, safe expansion

### E. FTS5 + HRR (full architecture)
- FTS5 seeds the retrieval, HRR walks typed edges to find structural neighbors
- From Exp 40: achieves 100% coverage including D157 vocabulary gap
- Decision-neighborhood partitioning from Exp 45

---

## 3. Test Set

### 3a. Retrieval Coverage (existing ground truth)
6 topics, 13 critical decisions. For each topic and each method: does the method return all needed decisions in its top-K results?

| Topic | Query | Needed Decisions | Why It's Hard |
|-------|-------|-----------------|---------------|
| dispatch_gate | "dispatch gate deploy protocol" | D089, D106, D137 | Multiple decisions across milestones |
| calls_puts | "calls puts equal citizens" | D073, D096, D100 | D100 is emphatic override ("STOP BRINGING IT UP") |
| capital_5k | "starting capital bankroll" | D099 | Single decision, specific terminology |
| agent_behavior | "agent behavior instructions" | D157, D188 | D157 has zero vocabulary overlap with query |
| strict_typing | "typing pyright strict" | D071, D113 | Domain-specific terms |
| gcp_primary | "GCP primary compute platform" | D078, D120 | Infrastructure context |

### 3b. Token Efficiency (new measurement)
For each method, measure the total tokens returned in the top-K results. The budget is 2,000 tokens (REQ-003). Methods that achieve high coverage with fewer tokens are better.

### 3c. Precision (new measurement)
Of the top-K results returned, what fraction are actually relevant to the topic? Methods that return noise alongside signal are worse even if coverage is high.

### 3d. Task Scenarios (new -- the real test)
Design 5 task scenarios that an agent would encounter on the project-a project. Each scenario requires specific prior decisions to produce a correct response. Measure: given each method's retrieval as context, does the agent produce the correct answer?

**Proposed scenarios:**

1. **"How should I size a new position?"** Needs D099 (capital $5K), D005 (pct_equity 0.5%), D012 (compound approximation). Correct answer: 0.5% of $5K = $25 per position.

2. **"Should I use async_bash for a long-running backtest?"** Needs D157 (async_bash BANNED). Correct answer: No, absolutely not. This is the vocabulary-gap test case.

3. **"What's the evaluation protocol for a new strategy?"** Needs D097 (walk-forward), D098/D103 (evaluation criteria). Correct answer: walk-forward with specific split ratios.

4. **"Which cloud platform should I deploy to?"** Needs D078, D120 (GCP primary). Correct answer: GCP.

5. **"A strategy is making money but the calls/puts split is uneven. Should I rebalance?"** Needs D073 (equal citizens), D096 (confirmed), D100 (STOP BRINGING IT UP). Correct answer: No -- this was decided definitively.

For task scenarios, evaluation is: does the agent response contain the correct answer and not contradict any of the needed decisions?

---

## 4. Metrics

| Metric | Formula | Target |
|--------|---------|--------|
| Coverage@K | (found decisions) / (needed decisions) per topic | >= 92% (FTS5 floor) |
| Tokens@K | Total tokens in top-K results | <= 2,000 (REQ-003) |
| Precision@K | (relevant results) / K | >= 50% (REQ-007) |
| Task accuracy | (correct answers) / (total scenarios) | >= 80% (REQ-001 threshold) |
| Mean Reciprocal Rank | 1/rank of first relevant result, averaged | Higher is better |

K = 15 for retrieval metrics (matches Exp 3 protocol).

---

## 5. What Would Change Our Mind

| If grep... | Then... |
|------------|---------|
| Coverage >= 100% AND tokens <= 2K | Our architecture adds zero retrieval value. Investigate: is the test set too easy? Are the queries too aligned with the stored text? |
| Coverage >= 92% (matches FTS5) | Stemming and BM25 ranking add negligible value over raw grep for this corpus. The value must come from HRR (structural retrieval) or confidence (Thompson sampling). |
| Coverage < 80% | Grep is not a serious competitor. Our architecture's advantage is clear. |
| Task accuracy: grep >= FTS5+HRR | Context selection doesn't matter for these tasks -- the agent can find the answer in noisy results. Token efficiency becomes the differentiator. |
| Task accuracy: FTS5+HRR > grep by >= 20% | Strong evidence that retrieval quality translates to task quality. Project justified. |

---

## 6. Implementation Plan

The experiment needs:
1. A grep-based retriever (Methods A and B)
2. Reuse existing FTS5 infrastructure (from Exp 9/39)
3. Reuse existing FTS5+HRR pipeline (from Exp 40/45)
4. A token counter for each method's output
5. A precision evaluator (needs labeled relevance per result -- extend ground truth)
6. Task scenario prompts + evaluation rubric (for task accuracy)

For the task accuracy test, we need an LLM to generate responses from each method's retrieved context. This is the one place we need an LLM call. We can use the cheapest model (haiku) since we're testing retrieval quality, not generation quality.

**Or:** skip the LLM task test for now and focus on retrieval metrics (coverage, tokens, precision, MRR). These are measurable without any LLM calls and answer the core question: does our retrieval find the right beliefs?

---

## 7. Hypotheses

**H1:** Grep achieves < 80% coverage on the 6-topic test set (because it lacks stemming and can't match morphological variants).

**H2:** FTS5 achieves >= 92% coverage (replicating Exp 9/39 results).

**H3:** FTS5+HRR achieves 100% coverage (replicating Exp 40 results, specifically D157 recovery).

**H4:** Grep returns >= 3x more tokens than FTS5+HRR for the same coverage level (because it can't rank by relevance, so it returns more noise).

**H5:** At K=15, grep precision < 30% while FTS5+HRR precision >= 50%.

**Null hypothesis:** Grep achieves >= 92% coverage with comparable token efficiency. Our architecture adds complexity without measurable retrieval benefit.
