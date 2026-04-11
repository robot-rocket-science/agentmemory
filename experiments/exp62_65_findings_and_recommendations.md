# Experiments 62-65: Hologram Research -- Consolidated Findings

**Date:** 2026-04-11
**Experiments:** 62 (Minimal Hologram), 63 (Profiles), 64 (Pre-Prompt Compilation), 65 (Diffing)
**Status:** 62-64 complete, 65 in progress

---

## What We Tested

Can the belief graph be projected into a portable "hologram" -- a frozen snapshot that preserves agent identity, enables behavioral profiles, supports pre-prompt context injection, and allows meaningful diffing over time?

## What We Found

### 1. Global scoring is uncorrelated with retrieval needs (Exp 62)

`score_belief()` without a query produces rankings dominated by Thompson sampling noise at uniform confidence. Coverage increases log-linearly with subgraph size -- no knee, no natural hologram boundary. At top-100: only 31% coverage. Full graph (14,895 beliefs): 86% ceiling.

**Implication:** A "freeze the top-k beliefs" hologram is not viable. The scoring pipeline is designed for query-time ranking, not global ordering.

### 2. FTS5 is the only retrieval signal that works (Exp 62, 64)

On-demand FTS5 retrieval with topic-specific queries achieves 69.2% coverage. Every other mechanism (global scoring, type weighting, pre-compilation) added zero unique signal. The retrieval pipeline is functionally a BM25 search engine.

**Implication:** Investment in scoring sophistication is wasted until the Bayesian feedback loop creates confidence variance. FTS5 text matching does the actual work.

### 3. Type-weight profiles produce divergent sets but need FTS5 (Exp 63)

Strict Reviewer vs Explorer profiles: Jaccard distance 1.0 (zero overlap in top-30). Profiles deterministically control which types dominate results. But without text matching, within-type ranking is random.

**Implication:** Profiles are a valid concept as a MODIFIER on the retrieval pipeline (type weights applied after FTS5 ranking), not as a standalone mechanism.

### 4. Pre-prompt compilation adds nothing vs on-demand retrieval (Exp 64)

Compiled context at 2000 tokens: 23.1% coverage. On-demand retrieval: 69.2%. Random selection at 2000 tokens: 33.1%. Compilation is worse than random because 5 broad queries saturate at 137 unique results from 15K+ beliefs.

No cage detected -- on-demand retrieval is independently sufficient regardless of compiled context size.

**Implication:** Do not build a compilation pipeline. On-demand retrieval is the right approach. Pre-prompt context should be limited to locked beliefs (the existing `get_locked` design).

### 5. Only requirement-type beliefs are load-bearing (Exp 62)

Removing all 11,364 factual beliefs: 0% coverage change. Removing 781 requirements: -11.1%. Corrections, preferences: 0% change when removed.

**Implication:** The offline classifier may be putting requirement-like content into the factual bucket. Or the ground truth is biased toward requirement-style queries. Either way, the type distribution (76% factual) suggests most stored beliefs contribute nothing to retrieval.

---

## Core Architecture Issues Surfaced

### A. The Bayesian feedback loop has never fired

`record_test_result()` -- the mechanism that updates belief confidence based on usage -- has never been called. All beliefs sit at their ingestion priors. Thompson sampling on uniform priors is random noise. The entire value proposition of Bayesian belief tracking is untested.

**Recommended action:** Implement and test the feedback loop. Exp 66 design: replay recorded retrievals, simulate used/ignored outcomes, measure whether confidence differentiation improves retrieval quality over 50 rounds.

### B. Bulk-ingested corrections are not locked

2,592 correction-type beliefs exist with `locked=False`. The live `correct()` MCP tool creates locked beliefs; the bulk ingestion pipeline does not. These corrections are scored identically to factual beliefs, defeating the purpose of correction detection.

**Recommended action:** Either auto-lock corrections during ingestion, or retroactively lock existing corrections. Exp 67 design: measure retrieval impact of locking all 2,592 corrections.

### C. Ingestion priors are uniform

`TYPE_PRIORS` in classification.py assigns (9.0, 1.0) to REQUIREMENT, CORRECTION, PREFERENCE, FACT, and ASSUMPTION. This gives all five types identical 90% confidence. Thompson sampling cannot differentiate them.

**Recommended action:** Spread priors by type. Suggested values (needs validation):
- REQUIREMENT: (9.0, 0.5) = 94.7%
- CORRECTION: (9.0, 0.5) = 94.7%
- PREFERENCE: (7.0, 1.0) = 87.5%
- FACT: (3.0, 1.0) = 75.0%
- ASSUMPTION: (2.0, 1.0) = 66.7%

Exp 68 design: vary priors, re-run Exp 62 coverage sweep, measure whether scoring becomes meaningful.

### D. New beliefs cannot surface at scale

Exp 63 dynamic shaping: adding 20 new corrections to a pool of 3,283 produces zero drift in top-k. The system is saturated at the type level. Without temporal recency boosting or active confidence differentiation, the system increasingly ignores new information as it grows.

**Recommended action:** Add a recency boost to `score_belief()`. A `recency_boost()` function already exists in scoring.py (added by linter) but is not wired into `score_belief()`. Also: `score_belief()` does not use `_TYPE_WEIGHTS` or `_SOURCE_WEIGHTS` that already exist in the module -- only `core_score()` uses them. Wiring these into retrieval scoring would give requirements/corrections a natural advantage.

### E. FTS5 top_k=30 is too low at 15K+ beliefs

The retrieval pipeline defaults to `top_k=30`. At 15K beliefs, this is 0.2% of the graph. Exp 64 showed compilation across 5 queries saturated at 137 beliefs because each query was capped at 30. Increasing to 50 or 100 would improve candidate diversity.

---

## What Still Works

- **`get_locked` for L0 context** -- injecting locked beliefs unconditionally at session start remains the right design for persistent constraints
- **FTS5 BM25 search** -- the core retrieval mechanism works and achieves 69.2% on ground truth
- **Type-aware compression** -- Exp 42's 55% token savings are still valid
- **Correction detection** -- the zero-LLM pipeline detects corrections; the issue is what happens after detection (they should be locked)
- **Serialization** -- profiles serialize at sub-ms cost; round-trip is lossless

## Recommended Next Experiments

| Exp | Question | Why It Matters |
|-----|----------|----------------|
| 66 | Does the feedback loop improve retrieval? | Core value proposition of the system |
| 67 | What happens when corrections are locked? | 2,592 beliefs immediately elevated |
| 68 | Do spread priors make scoring meaningful? | Unlocks Thompson sampling from noise to signal |
| 69 | Does recency boost help new beliefs surface? | Fixes the saturation problem |
| 70 | Does increasing top_k improve coverage? | Cheapest possible retrieval improvement |

Experiments 67 and 70 are the cheapest (parameter changes, no new code). 66 is the most important (validates the core architecture). 68 and 69 are the most impactful for day-to-day usage.

---

## Files

| File | Description |
|------|-------------|
| exp62_minimal_hologram_plan.md | Original Exp 62 design |
| exp62_minimal_hologram.py | Exp 62 code |
| exp62_results.json | Exp 62 raw data |
| exp62_minimal_hologram_results.md | Exp 62 analysis |
| exp63_hologram_profiles_plan.md | Original Exp 63 design |
| exp63_hologram_profiles.py | Exp 63 code |
| exp63_results.json | Exp 63 raw data |
| exp63_hologram_profiles_results.md | Exp 63 analysis |
| exp64_preprompt_compilation_plan.md | Original Exp 64 design |
| exp64_preprompt_compilation.py | Exp 64 code |
| exp64_results.json | Exp 64 raw data |
| exp64_preprompt_compilation_results.md | Exp 64 analysis |
| exp65_hologram_diffing_plan.md | Original Exp 65 design |
| exp65_hologram_diffing.py | Exp 65 code (in progress) |
