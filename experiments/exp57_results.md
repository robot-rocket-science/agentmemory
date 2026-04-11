# Experiment 57: Time Architecture Evaluation -- Results

**Date:** 2026-04-10
**Status:** Complete -- CRITICAL FINDING

---

## Summary

The adopted time architecture (Model 3 structural edges + Model 2 decay) scores **55% (6/11)** on case study temporal scenarios. Decay-only (Model 2) scores **100% (11/11)**. Adding structural time to decay makes retrieval scoring **worse, not better**.

The root cause: **TEMPORAL_NEXT ordering penalizes locked beliefs for being old.** Locked constraints created early in the timeline (e.g., "no implementation") get low structural recency scores, causing them to be outranked by newer but less important beliefs.

## Results

| Architecture | PASS | PARTIAL | FAIL | Rate |
|---|---|---|---|---|
| A. No time | 8 | 3 | 0 | 73% |
| **B. Decay only** | **11** | **0** | **0** | **100%** |
| C. Structural only | 6 | 5 | 0 | 55% |
| D. Adopted (structural + decay) | 6 | 5 | 0 | 55% |
| E. Event-sourced | 6 | 5 | 0 | 55% |

## The Critical Finding

Decay-only (B) beats every other architecture because it correctly handles the **two properties that matter most**:

1. **Locked beliefs are immune to decay** (score = 1.0 regardless of age)
2. **Superseded beliefs are near-zero** (score = 0.01)

The structural scoring function (`score = recency_rank / max_rank`) assigns LOW scores to OLD beliefs. When multiplied with the decay factor, this creates a catastrophic interaction: locked beliefs that should score 1.0 get multiplied by their structural recency (0.33-0.50), dropping them below non-locked recent beliefs.

### Where the adopted architecture fails

| Scenario | Failure | Root Cause |
|---|---|---|
| CS-004 | Locked "no implementation" (0.33) outranked by recent "ready to build" (1.0) | Structural recency penalizes early-created lock |
| CS-006 | Locked correction (0.50) outranked by recent work (1.0) | Same: age penalty on locked belief |
| CS-009 | approach_b (0.70) outranked by approach_b_ok (0.88) | Evidence ranked above procedure by recency |
| CS-016 | Locked "calls/puts axiom" (0.50) outranked by recent "puts underperform" (1.0) | Same: locked axiom penalized for being old |
| CS-022 | "machine_rule" (0.33) ranked lowest despite being a constraint | 5-day-old constraint penalized vs 3-day-old facts |

The pattern is clear: 4 of 5 failures involve locked beliefs or constraints being penalized by structural recency.

## Hypothesis Results

| Hypothesis | Result | Detail |
|---|---|---|
| H1: Adopted handles >= 80% | **FAIL** (55%) | 5 PARTIAL results |
| H2: At least one gap exists | **PASS** | 5 scenarios with gaps |
| H3: Event-sourced covers gaps | **FAIL** | E also scores 55% -- same structural recency problem |
| H4: Decay prevents CS-005, CS-015 | **PASS** | Both pass with decay-only |
| H5: SUPERSEDES chains load-bearing | **FAIL** | Supersession works via score=0 in all architectures, not just structural |

## Architectural Implications

### 1. Separate temporal querying from temporal scoring

TEMPORAL_NEXT edges are valuable for **traversal queries** ("what happened after X?", "show me the evolution of this decision"). They are harmful when used as a **multiplicative scoring factor** for retrieval ranking.

**Corrected architecture:**
- **Retrieval scoring** = content-aware decay only (Model 2). Locked/constraint beliefs score 1.0 regardless of age.
- **Temporal traversal** = TEMPORAL_NEXT edges for structural queries (Model 3). Used for navigation, not ranking.
- These are two independent capabilities, not a combined scoring function.

### 2. Locked beliefs must be immune to ALL temporal signals

The adopted architecture correctly made locked beliefs immune to decay but failed to make them immune to structural recency. The fix: any scoring function must check the locked flag first and return 1.0 before applying any temporal adjustment.

### 3. Content-aware decay is the dominant temporal mechanism

Decay handles:
- Constraint persistence (no decay)
- Activity fading (fast decay)
- Evidence staleness (moderate decay)
- Supersession (near-zero score)
- Lock immunity (bypass)

Structural time handles:
- "What happened after X?" (traversal)
- "Show me the history of topic Y" (query)
- "What changed since last session?" (filtering)

These are different use cases. Trying to unify them into a single scoring function creates the failure we observed.

### 4. Event-sourced adds velocity but doesn't fix the core problem

The event-sourced architecture (E) adds session velocity discounting (CS-005: fast sprint beliefs get 0.7x penalty). This is valuable for calibration but doesn't fix the locked-belief ranking problem. E scores 55%, same as D, because it still uses recency-based ranking that penalizes old locked beliefs.

The velocity discount from E should be adopted as an **additional scoring layer** on top of decay, not as part of structural time:

```
score = decay_factor * velocity_discount * (1.0 if locked else confidence)
```

### 5. SUPERSEDES is handled by score assignment, not temporal structure

All architectures that assign score ~0 to superseded beliefs handle CS-001, CS-015, CS-017 correctly. This is a belief lifecycle property, not a temporal structure property. SUPERSEDES edges are useful for traversal ("what replaced X?") but the scoring effect is just a flag check.

## Revised Architecture Recommendation

Replace Model 3 + Model 2 combined scoring with:

```
if belief.locked or belief.content_type == CONSTRAINT:
    score = 1.0   # immune to all temporal signals
elif belief.superseded_by is not None:
    score = 0.01  # near-zero, visible for history queries
else:
    decay = exp(-lambda * age)  # content-type-specific lambda
    velocity = velocity_discount(session)  # from event-sourced design
    score = decay * velocity
```

Keep TEMPORAL_NEXT edges for **structural traversal only**:
- "What decisions were made in session 5?"
- "What superseded approach A?"
- "Show me the timeline of this topic"

This cleanly separates the two temporal capabilities without the destructive interaction.

## What Remains Untested

1. **Decay half-life calibration.** The half-lives used (3d, 14d, 21d, 30d) are guesses. Need empirical calibration against real usage patterns.
2. **Velocity discount thresholds.** The 10 items/hour and 5 items/hour thresholds are arbitrary. Need data on what "fast" vs "deep" looks like in practice.
3. **Structural traversal value.** This experiment tested scoring only. The traversal queries TEMPORAL_NEXT enables ("show me the evolution of X") were not evaluated.
4. **Interaction with FTS5+HRR retrieval.** Temporal scoring is a post-retrieval re-ranking step. How it interacts with BM25 ranking and HRR similarity needs testing.
5. **Scale behavior.** All scenarios have 2-5 beliefs. At 10K+ beliefs, does decay alone still produce useful rankings?
