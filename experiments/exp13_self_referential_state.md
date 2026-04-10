# Research: Self-Referential State Management

**Date:** 2026-04-09
**Triggered by:** CS-003 (system had TODO.md but didn't consult it before asking user "what next?")

## The Problem

The memory system stores beliefs about the project. But it also needs beliefs about ITSELF -- its own operational state, its own documents, its own processes. CS-003 showed that the system "forgot" it maintained a TODO list and instead asked the user for direction.

This is a meta-cognition problem: the system needs to know what it knows.

## What "Self-Referential State" Means

Three categories of self-knowledge:

### 1. State Documents (what exists and where)
- TODO.md is the task list -- consult before asking "what next?"
- REQUIREMENTS.md defines success criteria -- consult before claiming something passes
- APPROACHES.md tracks what's been tried -- consult before proposing something already rejected
- EXPERIMENTS.md has protocols and results -- consult before rerunning experiments
- VALIDATION_AUDIT.md has methodology gaps -- consult before claiming validation

### 2. Operational Rules (how to behave)
- "We are in research phase, not implementation" (CS-002)
- "Check before redoing work" (CS-001)
- "Consult state docs before asking the user" (CS-003)
- "Document findings as you go, not in batches"

### 3. Process State (what's done, what's in progress)
- Which experiments have been run and their results
- Which approaches have been adopted/rejected
- Which requirements have evidence
- What the current task is

## How to Model This

### Option A: Meta-beliefs (beliefs about the system's own state)

Treat self-knowledge as a special class of beliefs:
- belief_type = "meta" (alongside factual, preference, procedural, etc.)
- Always loaded in L0 (they apply to every task)
- Created automatically when state documents are created/modified

Examples:
- "TODO.md exists at project root and contains the prioritized task list. Consult it before asking the user what to do next."
- "REQUIREMENTS.md contains 22 requirements. Check relevant requirements before claiming something passes."
- "We are in research phase. Do not suggest implementation."

**Pros:** Uses existing belief infrastructure. No new tables or concepts.
**Cons:** Could accumulate many meta-beliefs. Need to manage them carefully.

### Option B: State registry (separate from beliefs)

A dedicated table that tracks what state documents exist and when to consult them:

```
state_documents:
  path TEXT PRIMARY KEY
  purpose TEXT           -- "prioritized task list"
  consult_when TEXT      -- "before asking user for direction"
  last_updated TEXT
```

The MCP server checks this registry before certain operations:
- Before `search`: check if query relates to a state document topic
- Before asking user for direction: check TODO.md
- Before claiming validation: check REQUIREMENTS.md

**Pros:** Clean separation. State documents aren't mixed with project beliefs.
**Cons:** New concept. Another table. More complexity.

### Option C: Behavioral beliefs with trigger conditions

Instead of a separate registry, encode the self-knowledge as behavioral beliefs with explicit trigger conditions:

```
belief: "When all tasks are complete, consult TODO.md for new research areas before asking the user."
type: procedural
trigger: "task_list_empty"
loaded_at: L0 (always)
locked: true
```

The trigger field is new -- it tells the system WHEN to activate this belief. Unlike regular beliefs that are retrieved by query relevance, triggered beliefs activate on specific events.

**Pros:** Extends existing model naturally. Trigger conditions make activation explicit.
**Cons:** Trigger matching is a new mechanism that needs design.

### Recommendation: Option C (behavioral beliefs with triggers)

This extends the scientific method model rather than adding a parallel system. The triggers map to the feedback loop -- they're essentially pre-programmed test conditions:

- "When I'm about to ask the user for direction" -> trigger: check TODO.md
- "When I'm about to claim something is validated" -> trigger: check REQUIREMENTS.md
- "When I'm about to start a task" -> trigger: check if it was recently completed
- "When I complete all current tasks" -> trigger: generate new research questions from findings

## Connection to Case Studies

| Case Study | Self-Knowledge Needed | Trigger |
|-----------|----------------------|---------|
| CS-001 (redundant work) | "Check recent completions before starting a task" | Before any task start |
| CS-002 (implementation push) | "We are in research phase" | Before any scope/phase suggestion |
| CS-003 (didn't consult TODO) | "TODO.md is the task list" | Before asking user for direction |
| CS-004 (lost correction) | "User corrections are locked beliefs" | After any context compression event |

## New Concepts for the Architecture

1. **Triggered beliefs**: beliefs that activate on specific events, not just query relevance
2. **Meta-beliefs**: beliefs about the system's own state and documents (a belief_type category)
3. **State document registry**: which files the system maintains and when to consult them

These should be added to PLAN.md's schema and belief lifecycle when appropriate.

## Open Questions

- How many meta-beliefs is too many? At what point does self-referential state consume too much L0 budget?
- Should triggers be hardcoded or learned from usage patterns?
- How does this interact with cross-model behavior? (Claude may self-consult; ChatGPT may not)
- Is there a risk of infinite regress? (Meta-beliefs about meta-beliefs about meta-beliefs...)
