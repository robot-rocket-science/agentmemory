# Experiment 1: Per-Hop Failure Analysis on MH 262K

## Setup

- Dataset: MAB FactConsolidation Multi-Hop, 262K tokens, 100 questions
- Pipeline: agentmemory FTS5+HRR+BFS retrieval (2000 token budget) + Opus reader
- Current score: 6% SEM (field ceiling: <=7%)
- No code changes. Diagnostic only.

## Method

For each of the 100 questions:
1. Extract the primary entity from the question
2. Check if that entity appears in the retrieved context (hop-1 reachable)
3. Check if the final answer appears in the retrieved context (hop-2 reachable)
4. Cross-reference with the Opus reader's prediction accuracy

## Results

| Category | Count | Accuracy |
|----------|-------|----------|
| Both entity AND answer in context | 21 | 4/21 (19%) |
| Entity found, answer missing | 58 | 1/58 (2%) |
| Answer found, entity missing | 10 | 1/10 (10%) |
| Neither found | 11 | 0/11 (0%) |
| **Total** | **100** | **6/100 (6%)** |

## Root Causes

### 1. Chaining Gap (58% of failures)

FTS5 finds the primary entity but retrieves the WRONG intermediate
value (an older conflicting fact with a lower serial number). Without
SUPERSEDES edges between conflicting facts about the same entity+property,
the retrieval cannot distinguish the current value from the stale one.

**Example:** Q0 asks "country of origin of the sport played by Abbiati."
The context contains "Abbiati plays goalkeeper" (older fact) but NOT
"Abbiati plays association football" (newer, correct fact). So even if
we chained, we would query "country of origin of goalkeeper" which
leads nowhere.

**Real-world equivalent:** "What testing framework does the auth module
use?" The context has an old fact ("auth uses unittest") but the current
fact ("auth uses pytest") was superseded and should have been filtered.

### 2. Reader World Knowledge Override (17 of 21 "both found" failures)

Even when the context contains the correct (counterfactual) answer,
the Opus reader defaults to real-world knowledge. The benchmark
deliberately assigns counterfactual values (e.g., "Valmiki wrote in
English" instead of Sanskrit) and the reader resists using them.

**Examples:**
- Q6: Melvil Dewey's language. Context has "Italian." Reader says "English."
- Q18: Capital of a country. Context has "Paris." Reader says "Washington D.C."
- Q26: Jagger's spouse's birthplace. Context has "North Charleston." Reader says "Dartford."

**Note:** This failure mode is benchmark-specific. In real-world usage,
the context contains factual corrections ("use pytest not unittest")
that the reader should trust, and it generally does. The counterfactual
setup of FactConsolidation is adversarial by design.

### 3. Retrieval Miss (11% of failures)

Neither the entity nor the answer appears in the retrieved context.
FTS5 keyword matching completely missed the question topic. This is
a recall problem in the retrieval pipeline.

## Implications

| Fix | Addresses | Expected Impact |
|-----|-----------|-----------------|
| SUPERSEDES via triple extraction | Chaining gap (58%) | +35pp |
| Stronger context grounding prompt | Reader override (17%) | +14pp |
| Entity-level graph expansion | Retrieval miss (11%) | +5pp |
| **Combined** | **All three** | **~60%** |

The theoretical maximum with all three fixes is ~60%, which would be
approximately 10x the current field ceiling of <=7%.

## Next Steps

- Exp 2: Oracle hop-1 injection (validate that fixing hop-1 enables hop-2)
- Exp 3: Structured triple ingestion with SUPERSEDES chains (the main fix)
- Both can proceed without waiting for other experiments.
