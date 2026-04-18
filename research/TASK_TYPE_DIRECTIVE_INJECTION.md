# Task-Type Directive Injection: Design Document

**Date:** 2026-04-18
**Branch:** feature/task-type-directive-injection
**Status:** Research & Validation

## Problem Statement

Users repeatedly issue the same procedural instructions across sessions:
- "make a plan, make a todo list, follow the plan exactly, verify the steps"
- "refer to the runbook/best practices doc"
- "use subagents if it's convenient"

These instructions are context-dependent -- they apply when the task type matches
(planning, deployment, parallel-decomposable work) but are irrelevant otherwise.
When users forget to include them, the agent proceeds without guardrails that the
user expects.

**Prior evidence:** Pattern P4 analysis (exp6) found 9 clusters of repeated
instructions causing 30 overrides across 5-11 day spans. 79% of user overrides
were re-statements of already-decided directives. The dispatch runbook case study
showed a 67% reduction in override rate after making directives always-loaded.

## Key Finding: Keyword Classification Fails

**H1 REJECTED.** A zero-LLM keyword classifier achieves only ~27% accuracy on
real conversation prompts (tested against 1,551 prompts from conversation logs).
Failure modes:

1. **Keyword polysemy (31.8%):** Common words carry task-type meaning only in
   specific syntactic frames ("new accounts" != implementation)
2. **System noise (26.7%):** Hook-injected XML contains task keywords
3. **Short directives (22.7%):** "yes", "do 3 and 5", "just push" -- depend
   entirely on conversation context

## Proposed Solution: Structural Prompt Analysis

Instead of keyword matching, analyze prompt **structure** to detect task type:

### Structural Signals

| Signal | Detection Method | Indicates |
|--------|-----------------|-----------|
| Enumerated items | Regex: numbered lists, comma-separated items, "and" conjunctions | Parallel work, subagent suitability |
| Multi-system references | Entity extraction: 2+ distinct system/file/service names | Cross-cutting task, needs coordination |
| Scope breadth | Word count + unique entity count | Large task, needs planning |
| Action verb class | Verb taxonomy: fix/debug vs deploy/ship vs plan/design | Task type |
| Imperative density | Count of imperative verbs per sentence | Command vs question vs discussion |
| Conditional language | "if", "when", "unless" patterns | Decision-making, needs context |

### Task Type Taxonomy

| Task Type | Key Structural Signals | Directives to Inject |
|-----------|----------------------|---------------------|
| **planning** | High scope breadth, design verbs, future tense | "make a plan", "verify steps", "follow plan exactly" |
| **parallel-work** | Enumerated items >= 3, independent references | "use subagents if convenient" |
| **deployment** | Action verbs (deploy/push/ship/release) + target entity | "refer to runbook", "check gate rules" |
| **debugging** | Error terms, fix verbs, specific file/line references | "identify root cause", "isolate failure" |
| **validation** | Test/verify/check verbs, reference to prior work | "run tests", "compare to acceptance criteria" |
| **research** | Question form, explore/investigate verbs, broad scope | "document findings", "cite sources" |

### Subagent Suitability Detection

A prompt is subagent-suitable when it contains:

1. **Enumerated independent items** (>= 3 items OR >= 2 with different entity targets)
2. **Research breadth** (>= 2 distinct topics/angles to investigate)
3. **Multi-file operations** (references to >= 3 distinct files/modules)
4. **Explicit parallel language** ("also", "in parallel", "at the same time", "meanwhile")

Counter-signals (sequential work, NOT subagent-suitable):
- "then", "after that", "next" (sequential dependency)
- Single entity focus
- "be careful", "step by step" (cautious, sequential intent)

## Architecture: Where This Fits

### Current Pipeline (UserPromptSubmit hook)

```
User prompt
  -> Layer 1: FTS5 keyword search
  -> Layer 2: Entity-aware search (user corrections)
  -> Layer 3: Action-context detection (deploy/push targets)
  -> Layer 4: Supersession following
  -> Layer 5: Recent observations
  -> Score + pack into 6000-char budget
```

### Proposed Pipeline (with structural analysis)

```
User prompt
  -> NEW Layer 0: Structural prompt analysis
     -> Detect task type(s)
     -> Detect subagent suitability
     -> Retrieve task-type-tagged directives
  -> Layer 1: FTS5 keyword search
  -> Layer 2: Entity-aware search
  -> Layer 3: Action-context detection
  -> Layer 4: Supersession following
  -> Layer 5: Recent observations
  -> Layer 6: activation_condition evaluation
  -> Score + pack into 6000-char budget
```

### Persistence: activation_condition Field

The `activation_condition` field already exists in the beliefs schema (TEXT,
nullable) but has zero evaluation logic. Proposed format:

```
task_type:planning,parallel-work
structural:enumerated_items>=3
keyword_any:deploy,ship,push,release
keyword_all:git,force
```

Evaluation at search time:
1. Parse activation_condition into condition type + parameters
2. Match against structural analysis output
3. If matched, inject the belief with a boost score

### Confidence-Weighted Injection

Directives are NOT static rules. They accumulate confidence through the feedback
loop:

1. User says "use subagents" on a parallel-decomposable task -> observe()
2. System infers: task_type=parallel-work -> directive="use subagents"
3. Next time a parallel-work prompt appears, inject the directive
4. If agent uses subagents and user doesn't correct -> feedback("used") -> confidence++
5. If user says "no, do this sequentially" -> feedback("harmful") -> confidence--

Over time, the system learns WHICH directives apply to WHICH task types for THIS
user.

## Auto-Promotion to L1 (Not L0)

The "auto-promote after 3+ overrides" belief is compatible with the "no auto-lock"
policy:

- **L0 (locked):** Requires explicit user confirmation. No auto-promotion.
- **L1 (behavioral):** High-confidence procedural beliefs with behavioral keywords.
  Can be auto-promoted when confidence crosses threshold (0.8).

The existing `get_behavioral_beliefs()` in store.py already selects L1 candidates.
The missing piece is confidence-triggered promotion from regular belief -> L1
behavioral directive.

## HRR Vocabulary Bridging

Experiment 53 showed 31% of directives have vocabulary gaps (user says "ship it"
but directive says "deploy"). HRR achieves 100% bridgeability on these gaps.

**Problem:** HRR is wired into retrieval.py but NOT hook_search.py.
**Solution:** Add cached HRR queries to hook_search.py Layer 0.

Latency budget: 50-100ms total for hook. Cached HRR queries: ~20-30ms.
Full graph build: ~117ms (too slow for hook). Solution: pre-built graph cached
at session start.

## Validation Plan

### Experiment 86: Structural Prompt Analysis

1. Extract all user prompts from conversation logs
2. Run structural analyzer on each
3. Compare detected task types against manual ground truth (sample of 50 prompts)
4. Measure: precision, recall, F1 per task type
5. Measure: subagent suitability detection accuracy
6. Compare to keyword-only baseline (27%)

### Success Criteria

- Structural analysis accuracy >= 60% (2x keyword baseline)
- Subagent suitability detection precision >= 70%
- False positive rate < 15% (injecting wrong directives is worse than missing them)
- Hook latency stays under 100ms total

## Open Questions

1. How many task types are sufficient? Starting with 6, but may need more.
2. Should activation_condition evaluation be AND or OR when multiple conditions?
3. What's the minimum confidence threshold before auto-injection?
4. How to handle prompts that span multiple task types?
5. Should subagent injection be a directive belief or a hardcoded structural rule?

## Files That Would Change (Implementation Phase)

| File | Change |
|------|--------|
| `src/agentmemory/hook_search.py` | Add Layer 0 structural analysis |
| `src/agentmemory/models.py` | Document activation_condition format |
| `src/agentmemory/store.py` | Add `get_directives_by_activation()` query |
| `src/agentmemory/retrieval.py` | Wire activation_condition into full pipeline |
| `hooks/agentmemory-search-inject.sh` | Pass structural analysis results to search |

## Prior Art

No existing system combines (a) automatic detection of repeated user instructions
across sessions, (b) typed belief graph with Bayesian confidence, and (c) proactive
injection by task context. Static rule files (Cursor, Copilot) require manual
authoring. Memory-augmented agents (MemGPT/Letta) retrieve reactively, not
proactively. This approach appears novel.

**Sources:**
- MemGPT (Packer et al., 2023): arxiv.org/abs/2310.08560
- PAMU (2025): arxiv.org/html/2510.09720v1
- Graph-based Agent Memory Taxonomy (2025): arxiv.org/html/2602.05665v1
- PersonalLLM (ICLR 2025)
- Letta agent memory: letta.com/blog/agent-memory
