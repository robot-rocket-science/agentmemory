# Experiment 11: Scientific Method Model vs Human Memory Categories

**Status:** Design only (implementation needed to run)

## The Question

We adopted observe/believe/test/revise because it's conceptually appealing and addresses known weaknesses of human memory categories. But we have zero empirical evidence it produces better outcomes. What if episodic/semantic/procedural is actually fine and our model adds complexity for no gain?

## What We'd Need to Compare

### Model A: Scientific Method (our design)
- Observations (immutable raw events)
- Beliefs (derived claims with Bayesian confidence)
- Tests (retrieval feedback loop)
- Revisions (explicit supersession with provenance)
- Thompson sampling + Jeffreys for ranking

### Model B: Human Memory Categories (standard approach)
- Episodic memory (events as they happened)
- Semantic memory (facts, preferences, knowledge)
- Procedural memory (how-to, rules, processes)
- No feedback loop (no test/revise cycle)
- Recency + relevance scoring for ranking (no Bayesian confidence)

### What's Actually Different

| Feature | Model A | Model B | Testable Difference |
|---------|---------|---------|-------------------|
| Feedback loop | Yes (test outcomes update confidence) | No | Does retrieval quality improve over sessions? |
| Bayesian confidence | Yes (Thompson + Jeffreys) | No (static or recency-decayed) | Do high-confidence beliefs actually perform better? |
| Immutable observations | Yes (never modified) | No (episodic memories can be reconsolidated) | Does immutability prevent data corruption? |
| Explicit revision | Yes (supersession chains) | No (overwrite or accumulate) | Can the system explain WHY a belief changed? |
| Correction detection | Yes (V2, 92%) | No (corrections treated same as new input) | Are user corrections handled better? |
| Locked beliefs | Yes (REQ-020) | No | Do repeated corrections stop after locking? |

## The Honest Assessment

Most of the difference isn't about the category names (observation vs episodic). It's about the feedback loop. If we took the human memory categories and added:
- Bayesian confidence to semantic memories
- A feedback loop that tracks whether retrieved memories were useful
- Correction detection and locking

...we'd get essentially the same system with different labels.

The scientific method framing is valuable as a **design philosophy** (always test your beliefs, never trust without evidence, revise when wrong). Whether it produces measurably different software behavior depends on whether the feedback loop works -- and we've already validated that (Exp 2, 5, 5b, 7).

## What's Actually Untested

The one thing we haven't validated is whether the **observation/belief separation** matters. In our model, raw events (observations) are stored separately from derived claims (beliefs). In the human model, episodic memories and semantic memories are both stored, but there's no explicit derivation chain.

The question: does keeping observations immutable and deriving beliefs from them produce better provenance and conflict resolution than storing interpreted memories directly?

This is testable but requires implementation:
1. Build both models on the same SQLite schema
2. Ingest the same alpha-seek data
3. Introduce contradictions (simulating the calls/puts and capital overrides)
4. Measure: which model detects contradictions faster? Which produces better provenance chains? Which is easier to correct?

## Recommendation

**Don't implement Model B just to compare.** The evidence we have supports the design:
- The feedback loop works (Exp 2, 5, 5b, 7)
- Correction detection works (V2, 92%)
- The override analysis shows where human memory categories fail (no mechanism for locking, no feedback, no correction detection)

The scientific method model's advantage is architectural (feedback loop, immutable observations, explicit revision) not categorical (observation vs episodic). If someone built a "human memory" system with the same feedback loop and locking, it would work similarly.

**The model name doesn't matter. The feedback loop, correction detection, and locked beliefs matter.** Those are validated.

## What Remains Unvalidated

1. Does observation/belief separation improve provenance in practice? (Needs implementation)
2. Does the revision chain (old belief -> new belief with reason) help the agent make better decisions? (Needs implementation + longitudinal testing)
3. Is the schema overhead of separate tables (observations, beliefs, evidence, tests, revisions) worth it vs a simpler flat store? (Needs implementation + performance comparison)

These are implementation-stage questions, not research-stage questions.
