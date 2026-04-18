# Activation Condition Evaluation Design

**Date:** 2026-04-18
**Branch:** feature/task-type-directive-injection
**Status:** Design (not implemented)

## Overview

The `activation_condition` field exists in the beliefs schema (TEXT, nullable,
added via ALTER TABLE migration) but has zero evaluation logic. This document
designs the evaluation system that would run at UserPromptSubmit hook time.

## Current State

```python
# models.py:164
activation_condition: str | None = None  # Event-based trigger for prospective beliefs

# store.py:411-413 (migration)
if "activation_condition" not in col_names:
    self._conn.execute("ALTER TABLE beliefs ADD COLUMN activation_condition TEXT")

# store.py:2916 (used only in create_speculative_belief)
```

The field is stored, read into the Belief dataclass, but never evaluated.

## Proposed Condition Format

Activation conditions are simple predicate expressions, one per line.
Multiple conditions on separate lines are ORed (any match triggers).
Conditions on the same line separated by `+` are ANDed.

```
task_type:planning
task_type:deployment+keyword_any:production,staging
structural:enumerated_items>=3
keyword_any:deploy,ship,push,release
keyword_all:git,force
```

### Condition Types

| Type | Syntax | Semantics |
|------|--------|-----------|
| `task_type` | `task_type:<type>` | Matches structural analysis task type |
| `keyword_any` | `keyword_any:<w1>,<w2>,...` | Any keyword present in prompt |
| `keyword_all` | `keyword_all:<w1>,<w2>,...` | All keywords present in prompt |
| `structural` | `structural:<signal><op><value>` | Structural signal threshold |
| `entity` | `entity:<name>` | Named entity present in prompt |
| `subagent` | `subagent:true` | Subagent suitability detected |

### Structural Signals Available

| Signal | Type | Description |
|--------|------|-------------|
| `enumerated_items` | int | Count of list items in prompt |
| `unique_entities` | int | Count of distinct code entities |
| `word_count` | int | Total words in prompt |
| `imperative_density` | float | Fraction of imperative sentences |
| `verb_phrase_count` | int | Count of independent verb phrases |

## Evaluation Architecture

### Where It Runs

The evaluation runs inside `search_for_prompt()` in hook_search.py as a new
Layer 0, before FTS5 search. It receives the `StructuralAnalysis` result from
the prompt analyzer.

```python
def search_for_prompt(db, prompt, budget_chars=TOKEN_BUDGET_CHARS):
    # NEW: Layer 0 -- structural analysis + activation condition matching
    analysis = analyze_prompt(prompt)
    activated = evaluate_activation_conditions(db, analysis, prompt)

    # Existing layers 1-5...
    # ...

    # Merge activated beliefs into scored results with boost
    for belief in activated:
        sb = score_belief(belief, query_words, now)
        sb.via = "activation"
        sb.score *= 2.0  # Boost activated directives
        all_scored.append(sb)
```

### Evaluation Logic

```python
def evaluate_activation_conditions(
    db: sqlite3.Connection,
    analysis: StructuralAnalysis,
    prompt: str,
) -> list[sqlite3.Row]:
    """Find beliefs whose activation_condition matches current prompt."""
    # Fetch all beliefs with non-null activation_condition
    rows = db.execute(
        "SELECT * FROM beliefs WHERE activation_condition IS NOT NULL "
        "AND valid_to IS NULL"
    ).fetchall()

    prompt_lower = prompt.lower()
    prompt_words = set(re.findall(r'\b\w+\b', prompt_lower))
    matched = []

    for row in rows:
        condition = row["activation_condition"]
        if _evaluate_condition(condition, analysis, prompt_words):
            matched.append(row)

    return matched


def _evaluate_condition(
    condition: str,
    analysis: StructuralAnalysis,
    prompt_words: set[str],
) -> bool:
    """Evaluate an activation condition string. Lines are ORed."""
    for line in condition.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # AND-separated predicates on same line
        predicates = line.split("+")
        if all(_eval_predicate(p.strip(), analysis, prompt_words) for p in predicates):
            return True
    return False


def _eval_predicate(
    pred: str,
    analysis: StructuralAnalysis,
    prompt_words: set[str],
) -> bool:
    """Evaluate a single predicate."""
    if ":" not in pred:
        return False

    ptype, pvalue = pred.split(":", 1)

    if ptype == "task_type":
        return pvalue in analysis.task_types

    elif ptype == "keyword_any":
        keywords = {k.strip() for k in pvalue.split(",")}
        return bool(keywords & prompt_words)

    elif ptype == "keyword_all":
        keywords = {k.strip() for k in pvalue.split(",")}
        return keywords.issubset(prompt_words)

    elif ptype == "structural":
        return _eval_structural(pvalue, analysis)

    elif ptype == "entity":
        return pvalue.lower() in " ".join(
            e.lower() for e in extract_entities(
                " ".join(prompt_words)
            )
        )

    elif ptype == "subagent":
        return analysis.subagent_suitable

    return False
```

## Performance Budget

The hook has a 50-100ms total budget. Activation condition evaluation adds:

| Operation | Estimated Cost |
|-----------|---------------|
| Structural analysis (CPU) | ~1ms |
| SQLite query for activation_condition IS NOT NULL | ~2ms |
| Condition evaluation (string matching) | ~1ms per belief |

Expected total overhead: **3-10ms** depending on number of beliefs with
activation conditions. Well within budget.

### Optimization: Cache Activated Belief IDs

If the number of beliefs with activation_conditions grows large (>100),
pre-compute a condition index at session start:

```python
# SessionStart: build condition index
condition_index = {
    "task_type:planning": [belief_id_1, belief_id_2],
    "task_type:deployment": [belief_id_3],
    ...
}
```

This reduces per-prompt evaluation to a dict lookup.

## Integration with Feedback Loop

When an activated belief is injected:

1. Record it in `pending_feedback` (existing mechanism)
2. On next search, check if the user acted on the directive
3. If used -> confidence++ on the belief
4. If ignored -> no change (maybe the directive wasn't relevant this time)
5. If contradicted ("no, don't do that") -> confidence-- and possibly
   remove or narrow the activation_condition

This creates a self-tuning system: directives that help get injected more
often, directives that don't help fade.

## Example Directives with Activation Conditions

```
Belief: "When planning work, make a todo list and follow it step by step"
activation_condition: "task_type:planning"

Belief: "Use subagents for parallel-decomposable work"
activation_condition: "subagent:true"

Belief: "Always refer to the dispatch runbook before deploying"
activation_condition: "task_type:deployment\nkeyword_any:dispatch,gate,runbook"

Belief: "Run the full test suite before merging to main"
activation_condition: "task_type:deployment+keyword_any:merge,main,master"

Belief: "Check docs/BENCHMARK_RESULTS.md when running benchmarks"
activation_condition: "keyword_any:benchmark,locomo,mab,structmemeval"
```

## Migration Path

1. **Phase 1 (current):** Design and validate (this document)
2. **Phase 2:** Add `analyze_prompt()` to hook_search.py
3. **Phase 3:** Add `evaluate_activation_conditions()` to hook_search.py
4. **Phase 4:** Create MCP tool for setting activation conditions on beliefs
5. **Phase 5:** Auto-suggest activation conditions when creating directives

## Open Questions

1. Should activation_condition evaluation run in retrieval.py too (MCP search)
   or only in hook_search.py (UserPromptSubmit)?
   - Recommendation: both, but hook_search is higher priority.

2. How to handle conflicting activated directives? (e.g., "use subagents" and
   "do this step by step" both activate)
   - Recommendation: include both, let the LLM resolve the conflict given context.

3. Should there be a maximum number of activated directives per prompt?
   - Recommendation: 5, to avoid token budget bloat. Rank by confidence.

4. How to create activation_conditions? Manual only, or auto-inferred?
   - Phase 1: manual via MCP tool
   - Phase 2: auto-suggest based on when the belief was created (what was
     the task type of the prompt that triggered the correction?)
