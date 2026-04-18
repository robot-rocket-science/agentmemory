# Exp87: Subagent Injection Validation Results

**Date:** 2026-04-18
**Branch:** feature/task-type-directive-injection

## Summary

Structural prompt analysis is a **poor predictor of actual subagent usage** but
remains a **valid trigger for directive injection**. These are different goals.

## Key Insight: Prediction vs Injection

The exp87 results show 1.8% precision for predicting when the agent WILL use
subagents. This seems like a failure but reveals an important distinction:

**Prediction question:** "Will the agent use subagents on this turn?"
- Depends on: agent assessment, conversation context, slash command invocations,
  task complexity as understood by the agent, not just prompt structure.
- 23 actual subagent uses in 676 turns (3.4% base rate).
- Many triggered by short prompts ("100 is fine", "/mem:settings") where the
  agent decided independently.
- Result: structural analysis cannot predict this. **Expected failure.**

**Injection question:** "Should the system inject 'consider using subagents'?"
- Depends on: prompt structure suggesting parallel-decomposable work.
- The injected directive is ADVICE, not a command. The agent can ignore it.
- High precision is essential (don't inject irrelevant advice).
- Recall is acceptable at 62.5-75% (missing an injection is OK).
- Result: ground truth validation (exp86) shows 100% precision on annotated
  prompts. **This is the right metric.**

## Results

### Against Real Conversation Logs (676 turn pairs)

| Metric | Value |
|--------|-------|
| Total turn pairs | 676 |
| Actual subagent usage | 23 (3.4%) |
| Predicted suitable | 56 (8.3%) |
| TP | 1 |
| FP | 55 |
| FN | 22 |
| Precision | 0.018 |
| Recall | 0.043 |

### Against Manual Ground Truth (25 annotated prompts, exp86)

| Metric | Value |
|--------|-------|
| Subagent accuracy | 88% |
| Precision | 100% |
| Recall | 62.5% |

## Why the Discrepancy

The ground truth (exp86) was annotated with the question: "SHOULD subagents be
used here?" The real-world data (exp87) measures: "WERE subagents used?" These
are different questions because:

1. **Agent autonomy:** The agent often decides to use subagents based on its own
   assessment, triggered by conversation context, not the user's prompt structure.

2. **Slash commands:** Many subagent uses are triggered by skill invocations
   (e.g., `/mem:wonder`) not direct user prompts.

3. **Short continuations:** "100 is fine", "proceed", "ok" -- the agent uses
   subagents based on what it was already doing, not what the user just said.

4. **Context dependence:** A prompt like "yeah we should be using the bayesian
   system" only makes sense in context. No structural analyzer can detect that
   this implies parallel batch classification.

## The "also" Lesson

The word "also" was initially in PARALLEL_MARKERS. This single word caused
87.8% of all subagent-suitable predictions (122/139 before fix). After removal,
predictions dropped from 139 to 56.

**Lesson:** Common words are poison for structural analysis. Any word appearing
in >5% of natural language is too noisy for a signal. Parallel markers must be
multi-word phrases ("in parallel", "at the same time") or domain-specific
terms ("spawn subagent").

## Signal Effectiveness (Post-Fix)

| Signal | % of Predictions | Assessment |
|--------|-------------------|------------|
| multi_verb_phrase | 48.2% | Medium. 3+ verb phrases suggest parallelism but FP rate is high. |
| research_breadth | 46.4% | Medium. Research tasks with >50 words. Noisy. |
| enumerated_items | 17.9% | High. Numbered lists are reliable parallelism indicators. |
| parallel_language | 14.3% | High. Explicit parallel language is unambiguous. |
| multi_entity | 14.3% | Medium. 3+ entities without sequential markers. |
| broad_scope | 10.7% | Low. Word count + entity count is too coarse. |

## Conclusions

1. **Structural analysis cannot predict agent behavior.** Agent decisions
   depend on full conversation context, not just the latest prompt.

2. **Structural analysis CAN detect prompts where parallel work is beneficial.**
   The right question is "should we SUGGEST subagents?" not "will the agent
   USE subagents?"

3. **For directive injection, precision matters more than recall.** A false
   injection wastes tokens and may confuse the agent. A missed injection
   just means the user types it manually (status quo).

4. **Ground truth validation (exp86) is the right benchmark.** 100% precision
   on 25 manually annotated prompts confirms the analyzer won't inject
   bad advice.

5. **The "also" lesson applies broadly:** any activation keyword must be
   domain-specific or multi-word to avoid noise.

## Recommendations

1. Use structural analysis for DIRECTIVE INJECTION only, not behavior prediction
2. Require 2+ subagent signals (not just 1) to trigger injection
3. Weight enumerated_items and parallel_language highest (most reliable)
4. Downweight research_breadth and broad_scope (too noisy)
5. Build feedback loop: if injected "use subagents" is ignored 3+ times for
   a given task type, reduce confidence on the directive
