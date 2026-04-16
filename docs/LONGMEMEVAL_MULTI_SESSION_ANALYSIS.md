# LongMemEval Multi-Session Failure Analysis

## Date: 2026-04-16

## Current Scores (Opus Reader + Opus Judge, 500 questions)

| Category | Correct | Total | Accuracy |
|---|---|---|---|
| single-session-user | 64 | 70 | 91.4% |
| single-session-preference | 24 | 30 | 80.0% |
| single-session-assistant | 41 | 56 | 73.2% |
| knowledge-update | 55 | 78 | 70.5% |
| temporal-reasoning | 79 | 133 | 59.4% |
| multi-session | 32 | 133 | 24.1% |
| **OVERALL** | **295** | **500** | **59.0%** |

## Multi-Session Failure Breakdown (101 wrong / 133 total)

### Failure Type Split

| Category | Count | % of failures |
|---|---|---|
| Retrieval miss (GT not in context) | 68 | 67% |
| Reasoning fail (GT in context, wrong answer) | 33 | 33% |

### Retrieval Miss Subcategories

| Question Type | Count | % of misses |
|---|---|---|
| Counting/aggregation ("how many", "how much") | 57 | 84% |
| Non-counting (averages, comparisons, percentages) | 11 | 16% |

### Example Retrieval Misses

- "How many model kits have I worked on or bought?" (GT: 5, Pred: 4)
- "How many days did I spend on camping trips?" (GT: 8 days, Pred: unknown)
- "How much total money have I spent on bike expenses?" (GT: $185, Pred: unknown)
- "How many different doctors did I visit?" (GT: 3, Pred: unknown)

### Example Reasoning Failures (GT in context)

- "How many items of clothing do I need to return?" (GT: 3, Pred: 2)
- "How many plants did I acquire last month?" (GT: 3, Pred: 2)
- "How many babies were born to friends/family?" (GT: 5, Pred: 4)

## Root Cause Analysis

### The Core Problem

Multi-session counting questions require retrieving ALL mentions of a
topic scattered across different sessions. FTS5 retrieval returns the
most relevant snippets, but completeness is not guaranteed. When 1 of
5 mentions is missing from the context, the reader undercounts.

### Why temporal_sort Won't Help

The problem is not ordering. The reader sees relevant facts but misses
some. Reordering the same incomplete set doesn't add missing facts.

### Why the Temporal Coherence Mechanism (Exp 6) Won't Help

Exp 6's resolve_all() is for structured entity-property facts with
serial numbers. LongMemEval conversations are unstructured natural
language. There are no entities to index, no serial numbers to resolve,
and no property conflicts. It's a different problem entirely.

## What Would Help

### For Retrieval Misses (68 questions)

1. **Higher retrieval budget**: Currently 2000 tokens. Increasing to
   4000-8000 may capture more scattered mentions. Cheapest test.

2. **Multi-query retrieval**: For counting questions, extract the topic
   ("model kits", "camping trips", "bike expenses") and run a focused
   FTS5 query for that topic specifically, then merge with the main
   retrieval results.

3. **Session-enumeration**: For questions that ask about "all sessions"
   or "over time", retrieve a sample from EVERY session rather than
   relevance-ranked across all sessions.

### For Reasoning Failures (33 questions)

1. **Better reader prompt**: Instruct the reader to list each item
   before counting. Chain-of-thought counting.

2. **Accept the ceiling**: Some counting tasks are genuinely hard for
   LLMs even with complete context.

## Quick Experiments to Run

1. **Budget sweep**: Re-run LongMemEval multi-session with budget
   2000/4000/8000. Measure GT-in-context rate at each level.
2. **Retrieval completeness audit**: For the 57 counting questions,
   manually check how many of the expected mentions appear in the
   2000-token retrieval vs the full ingested store.
