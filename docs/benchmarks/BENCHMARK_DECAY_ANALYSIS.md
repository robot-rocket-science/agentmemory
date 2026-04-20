# Decay and Promotion Rate Analysis for Benchmark Performance

## Question

Would increasing the belief decay rate and/or increasing the belief promotion
rate improve benchmark performance?

## Short Answer

**Decay rate: No, and it would actively hurt LoCoMo/LongMemEval.**
**Promotion rate: Irrelevant for benchmarks. Promotion is a cross-session mechanism
and benchmarks are single-session.**

The real bottleneck is not decay or promotion. It is **temporal ordering in the
retrieval output** and **reader LLM capability**.

## Detailed Analysis

### 1. How Decay Affects Each Benchmark

#### LoCoMo (66.1% F1, beats baseline)

LoCoMo ingests multi-session conversations spanning months. All sessions are
ingested in sequence within a single benchmark run. The ingestion timestamps are
real (parsed from LoCoMo date strings like "1:56 pm on 8 May 2023").

Current half-lives:
- factual: 14 days
- correction: 8 weeks

**Impact of faster decay:** LoCoMo conversations span 3-12 months. With a 14-day
factual half-life, beliefs from session 1 (January) are heavily decayed by the
time queries run (after all sessions ingested, effectively "now" = last session
date). This means early-session facts score lower than late-session facts.

For LoCoMo categories:
- **Temporal reasoning (cat 2):** Needs facts from specific sessions. Faster decay
  would suppress old-session facts needed to answer "when did X happen?"
- **Multi-hop (cat 1):** Needs facts from multiple sessions. Faster decay would
  suppress the older hop's evidence.
- **Single-hop (cat 4):** Benefits from decay IF the answer is in a recent session.
  Hurts if the answer is in an old session.
- **Adversarial (cat 5):** Needs to recognize something was "not mentioned." Decay
  is irrelevant here.

**Verdict:** Faster decay would hurt temporal and multi-hop categories. The current
14-day factual half-life already decays 3-month-old facts to ~0.004 of their
original score. That is aggressive enough.

#### MAB FactConsolidation (60% SH, 6% MH)

FactConsolidation has facts with serial numbers where newer = higher serial.
All facts are ingested in sequence within a single run. The key challenge is
resolving CONFLICTS between facts about the same entity.

**Critical insight:** All facts in a single FactConsolidation context are ingested
within seconds of each other (they're chunked from one document). The time
difference between "fact #1" and "fact #500" is milliseconds. Decay is
effectively 1.0 for all facts because the age difference is negligible.

**Impact of faster decay:** Zero. All facts have essentially the same timestamp.
The decay factor is ~1.0 for every fact. Changing the decay rate from 14 days
to 1 day would still produce ~1.0 for all facts.

**What actually matters for MAB:** Serial number resolution. The retrieval needs
to surface facts in an order that lets the reader identify which has the
highest serial number. This is an ingestion order / source_id problem, not a
decay problem.

#### StructMemEval (28.6%, 4/14)

Sessions represent moves over time. Each session is about a different city.

**Current behavior:** All sessions are ingested with the same timestamp
(benchmark ingestion happens in seconds). Decay is ~1.0 for all.

**Impact of faster decay:** If sessions had realistic timestamps (months apart),
faster decay WOULD help because it would suppress old-city beliefs. But in the
benchmark, all timestamps are within seconds, so decay cannot distinguish
session 1 from session 9.

**What actually matters:** The `created_at` timestamps need to reflect the
narrative timeline, not the wall-clock ingestion time. If we set session 1
to January and session 9 to September, the current decay would already
suppress session 1 facts by ~0.004 (14-day half-life, 8-month age).

This is an **adapter design issue**, not a scoring parameter issue.

#### LongMemEval (12.6% keyword proxy)

Similar to LoCoMo: multi-session conversations with realistic timestamps.

**Impact of faster decay:** Same analysis as LoCoMo. Would hurt temporal
and multi-session categories that need old facts.

### 2. How Promotion Affects Each Benchmark

Promotion has two forms in agentmemory:
- **Locking:** marks belief as permanent (2x boost, immune to decay)
- **Cross-project promotion:** marks belief as global scope

**Neither applies to benchmarks.** Benchmarks use fresh, isolated DBs.
There are no prior sessions to promote from. No beliefs are locked.
No feedback loop has fired (zero retrieval_count, zero used_count).

**Impact of faster promotion:** Zero. There is nothing to promote in a
benchmark context. Promotion is a cross-session learning mechanism.

### 3. What WOULD Actually Improve Scores

#### A. Temporal metadata in retrieval output (StructMemEval fix)

**Problem:** Retrieved beliefs are concatenated in FTS5 rank order, not
chronological order. The reader sees "[Moving to Bali]" next to
"[Moving to Istanbul]" with no way to know which is more recent.

**Fix:** Include explicit temporal markers in the retrieval output:
```
[Session 9, most recent] Life in Sydney: ...
[Session 5, older] Moving to Bali: ...
```

**Expected impact:** StructMemEval could jump from 28.6% to 80%+ because
the reader would know which session is current.

**Risk:** Adds tokens to the retrieval budget. May push out relevant
content for other benchmarks.

#### B. Realistic timestamps in benchmark ingestion (StructMemEval/MAB)

**Problem:** All beliefs get wall-clock timestamps within seconds of each
other, making decay useless for temporal ordering.

**Fix:** Parse narrative timestamps and use them as `created_at`:
- StructMemEval: session 1 = month 1, session 9 = month 9
- MAB FactConsolidation: fact #1 = T+0, fact #500 = T+500s

**Expected impact:** Decay would then correctly suppress old facts.
For StructMemEval, 14-day half-life over 8 months of narrative time
would decay session 1 to 0.004 vs session 9 at 1.0.

**Risk:** Assumes narrative timestamps are available and meaningful.
Not all benchmarks provide them.

#### C. Better reader LLM (universal)

**Evidence:** MAB SH 262K retrieval finds the answer 98% of the time,
but Opus extracts the correct answer only 60% of the time. The gap is
the reader's ability to identify the newest conflicting fact.

**Expected impact:** A reader trained for conflict resolution would
close the 98%-to-60% gap on SH and potentially break the 7% ceiling
on MH.

**Risk:** Reader quality is outside agentmemory's scope. We can only
optimize retrieval.

#### D. Return beliefs sorted by creation time (simple)

**Problem:** Beliefs are returned sorted by FTS5 rank (relevance).
For state tracking, chronological order is more useful.

**Fix:** Add a `sort_by_time=True` option to retrieve() that sorts
results newest-first within the token budget.

**Expected impact:** Reader would see the most recent beliefs first,
improving state tracking without temporal metadata annotations.

**Risk:** May hurt relevance-dependent tasks (LoCoMo temporal reasoning).

### 4. Parameter Sensitivity Analysis

Current parameters and their sensitivity:

| Parameter | Current | Increase Effect | Decrease Effect |
|-----------|---------|-----------------|-----------------|
| Factual half-life | 14d | Old facts persist longer. Helps LoCoMo temporal, hurts StructMemEval if timestamps are realistic. | Old facts vanish. Hurts LoCoMo temporal/multi-hop. |
| Correction half-life | 8w | Corrections persist. Good for knowledge-update tasks. | Corrections forgotten. Hurts LongMemEval knowledge-update. |
| Recency boost half-life | 24h | Longer new-info window. Helps MAB if chunks have timestamp spread. | Shorter window. No effect when all ingested simultaneously. |
| Type weight (correction) | 2.0 | Corrections rank higher. Helps MAB SH (newest fact = correction). | Corrections rank lower. |
| Thompson sampling | Beta(a,b) | More exploration at low a+b. | More exploitation at high a+b. |
| Token budget | 2000 | More context = more chance of including answer. More noise too. | Less context = may miss answer. |

### 5. Recommendation

**Do NOT tune decay or promotion rates for benchmark performance.**

Reasons:
1. Decay is irrelevant when all facts share timestamps (MAB, StructMemEval).
2. Faster decay hurts LoCoMo/LongMemEval temporal categories.
3. Promotion has no effect on single-session benchmarks.
4. Tuning to benchmarks risks overfitting to their specific distributions.

**Instead, fix the root causes:**
1. Annotate retrieval output with chronological ordering metadata.
2. Use narrative timestamps (when available) as created_at during ingestion.
3. Add a `sort_by_time` retrieval option for state-tracking queries.
4. These are architectural improvements, not parameter tuning.

The correct posture: solve the **mechanism** (temporal ordering in retrieval),
not the **knob** (decay rate). A mechanism fix transfers to real-world usage.
A parameter tune transfers only to the specific benchmark distribution.
