# Experiment 64: Pre-Prompt Compilation -- Results

**Date:** 2026-04-11
**Input:** Production memory.db (14,895+ non-superseded beliefs)
**Method:** Query-aware compilation, budget sweep, cage detection, baseline comparison
**Rigor tier:** Empirically tested (real data, adjusted design based on Exp 62)

---

## Summary

**H1 PARTIALLY CONFIRMED.** Compiled context beats flat locked-belief injection (impossible to compare -- no locked beliefs exist). Compiled context at 2000 tokens achieves 23.1% coverage using query-aware FTS5 retrieval. This is a real signal but far below the 90% target.

**H2 CONFIRMED.** A clear plateau exists at budget=3000 tokens (137 beliefs, 2111 tokens). Above this, FTS5 returns no additional results -- the compilation queries are saturated. This is the natural budget ceiling.

**H3 (Cage) REJECTED.** No cage detected. Union coverage is constant at 69.2% regardless of compiled budget. On-demand retrieval always finds 69.2%, and the compiled beliefs are a strict subset. Compilation adds zero unique coverage beyond what on-demand retrieval provides.

**H4 CONFIRMED.** Compilation latency: p50=21.8ms, p95=22.9ms. Well under the 500ms target.

---

## Phase 2: Compilation Budget Sweep

| Budget | Beliefs Packed | Tokens Used | Coverage |
|--------|---------------|-------------|----------|
| 250 | 19 | 250 | 7.7% |
| 500 | 31 | 497 | 15.4% |
| 750 | 49 | 749 | 15.4% |
| 1000 | 67 | 1,000 | 23.1% |
| 1500 | 97 | 1,500 | 23.1% |
| 2000 | 130 | 1,997 | 23.1% |
| 3000 | 137 | 2,111 | 23.1% |
| 4000 | 137 | 2,111 | 23.1% |
| 6000 | 137 | 2,111 | 23.1% |

**Observations:**
1. Coverage plateaus at 23.1% (3/13 ground truth hits) beyond budget=1000.
2. FTS5 saturates at 137 beliefs across 5 compilation queries (top_k=30 per query, minus duplicates).
3. Budgets above 3000 are wasted -- FTS5 doesn't return more results.

---

## Phase 4: Baseline Comparison

| Budget | Compiled | Random (mean) | Type-Filtered |
|--------|----------|---------------|---------------|
| 250 | 7.7% | 7.7% | 0.0% |
| 500 | 15.4% | 11.6% | 0.0% |
| 1000 | 23.1% | 21.6% | 15.4% |
| 2000 | 23.1% | 33.1% | 23.1% |
| 4000 | 23.1% | 33.1% | 30.8% |
| 6000 | 23.1% | 33.1% | 38.5% |

**Random beats compiled at large budgets.** At 2000+ tokens, random selection of beliefs achieves 33.1% vs compiled's 23.1%. Why: random selection draws from the full 14,895-belief pool. FTS5 compilation is limited to the 137 beliefs matching the 5 compilation queries. Random sampling from a larger pool has more chances to hit ground-truth substrings.

**Type-filtered beats compiled at large budgets.** At 6000 tokens, type-filtered (requirement + correction only) achieves 38.5%. These types contain the load-bearing information (confirmed in Exp 62).

---

## Phase 5: Cage Detection

| Compiled Budget | Compiled | On-Demand | Union |
|-----------------|----------|-----------|-------|
| 0 | 0.0% | 69.2% | 69.2% |
| 500 | 15.4% | 69.2% | 69.2% |
| 1000 | 23.1% | 69.2% | 69.2% |
| 2000 | 23.1% | 69.2% | 69.2% |
| 3000 | 23.1% | 69.2% | 69.2% |

**No cage exists.** On-demand retrieval with topic-specific queries always finds 69.2% regardless of what's in the compiled context. The compiled beliefs are a subset of what on-demand retrieval would find anyway.

**Key implication:** Pre-prompt compilation adds zero unique value when on-demand retrieval is available. Its only value would be:
1. Reducing latency on the first retrieval (beliefs are pre-loaded)
2. Providing context when the agent hasn't yet asked a question

---

## Phase 6: Compilation Latency

| Metric | Value |
|--------|-------|
| p50 | 21.8ms |
| p95 | 22.9ms |
| max | 22.9ms |
| mean | 21.7ms |

Fast enough for a SessionStart hook. Not a bottleneck.

---

## Root Cause Analysis

### Why compiled coverage is low (23.1%)

The 5 compilation queries are broad ("project requirements constraints rules", etc.). FTS5 matches many beliefs, but the RELEVANT beliefs (ones containing ground-truth substrings) are diluted among thousands of vaguely matching results. At top_k=30 per query, 137 unique beliefs are selected. Only 3 of 13 ground-truth substrings appear in those 137.

The compilation queries are not targeted enough. A query like "HRR vocabulary bridge" would find HRR beliefs, but the broad "architecture design decisions" query does not rank HRR beliefs highly enough to make the top-30.

### Why random beats compiled at large budgets

Random selection from 14,895 beliefs at 2000 tokens samples ~130 beliefs. With 14,895 beliefs in the pool, the probability of hitting at least one belief containing a ground-truth substring is higher than the probability of that substring being in the top-30 of a broad FTS5 query. This is a coverage-by-volume effect.

### Why on-demand always dominates

On-demand retrieval uses the TOPIC-SPECIFIC query (e.g., "HRR hyperdimensional vocabulary bridge traversal"). This is maximally targeted. The compilation queries are broad. Targeted retrieval will always beat broad pre-compilation for specific topics.

---

## Implications

### Pre-prompt compilation is not useful for retrieval

It adds zero unique coverage beyond on-demand retrieval. The only scenario where it helps is if the agent needs context BEFORE asking a question -- e.g., to decide which question to ask.

### What would make compilation useful

1. **Locked beliefs as L0 context.** Locked beliefs are not retrieved by query -- they are injected unconditionally. This is the original `get_locked` design and it remains the right approach for persistent constraints.
2. **Recent-change context.** Instead of broad queries, compile "what changed since last session" -- new beliefs, recent corrections, confidence shifts. This is NOT retrieval; it's a changelog.
3. **Profile + FTS5 combined.** Per Exp 63 findings, a profile modifies type weights during query-time retrieval. This is more useful than pre-compilation.

### Recommended design

Do not build a compilation pipeline. Instead:
- Keep `get_locked` for L0 context (locked beliefs, unconditional)
- Add "recent changes" summary to SessionStart (new beliefs since last session, corrections)
- Invest in profile-weighted retrieval for query-time shaping

---

## Limitations

- Only 5 compilation queries tested. More targeted queries might improve compiled coverage.
- Ground truth has 86% ceiling in the full graph (Exp 62). 69.2% on-demand ceiling is already 80% of maximum.
- No locked beliefs exist, so the most natural pre-prompt content (locked constraints) was not testable.
- The random baseline has high variance (0-15.4% std) due to the small ground truth size.

---

## Files

- `exp64_preprompt_compilation.py` -- experiment code
- `exp64_results.json` -- raw data
- `exp64_preprompt_compilation_plan.md` -- original design (pre-adjustment)
- `exp64_preprompt_compilation_results.md` -- this file
