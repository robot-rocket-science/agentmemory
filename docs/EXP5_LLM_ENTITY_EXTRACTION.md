# Experiment 5: LLM Entity Extraction for Multi-Hop Retrieval

## Status: DESIGN

## Motivation

v1.1.0 achieves 35% chain-valid on MAB MH 262K using regex-based triple
extraction + entity-index retrieval. Root cause analysis (Exp 1) shows 58%
of failures are chaining gaps: the intermediate entity exists in the data
but the entity-index cannot link to it.

The regex triple extractor (`triple_extraction.py`) matches 95.1% of facts
(17,435/18,332). The 4.9% miss rate (897 facts) comes from 5 patterns not
covered by the 34 existing regex rules:

| Pattern | Count | Example |
|---------|-------|---------|
| head of X government is Y | 304 | "The name of the current head of the Pittsburgh government is Bill Peduto" |
| X written in language Y | 191 | "Daily Planet was written in the language of English" |
| X founded in city Y | 133 | "Advanced Micro Devices was founded in the city of Sunnyvale" |
| CEO of X is Y | 114 | "The chief executive officer of Philips is Frans van Houten" |
| X's child is Y | 89 | "Satyajit Ray's child is Sandip Ray" |
| Other (unique titles) | 66 | "The Prime Minister of India is Narendra Modi" |

## Hypotheses

**H1 (Coverage):** Closing the 4.9% extraction gap improves MH chain-valid
score above 35%. Mechanism: missed facts include intermediate entities needed
for hop-2 chaining.

**H2 (Normalization):** LLM extraction normalizes entity names more
consistently than regex, improving hop-2 entity key matching beyond what
coverage alone provides. Example: LLM might normalize "the current head of
the Pittsburgh government" to entity="Pittsburgh" property="head_of_government"
while regex would need a specific pattern for each phrasing.

**H3 (Null):** The 4.9% miss is uniformly distributed across entities and
does not disproportionately affect multi-hop chains. Adding coverage does
not improve MH scores.

## Design

Three conditions, single variable (extraction method):

| Condition | Extraction | Expected Coverage |
|-----------|-----------|-------------------|
| Control | Current regex (34 patterns) | 95.1% |
| Treatment A | Extended regex (+5 patterns) | ~99.5% |
| Treatment B | LLM (Haiku) extraction | ~99%+ |

Everything else held constant:
- Same EntityIndex data structure
- Same multi_hop_retrieve() with 4-hop chaining
- Same 18,332-line MH 262K context
- Same 100 MH questions
- Same scoring (SEM with chain validation)
- Same readers (Opus + Haiku)

### Why three conditions?

If Treatment A (regex) matches Treatment B (LLM), then H1 is supported
and H2 is rejected: coverage matters, normalization does not. This saves
future engineering effort (no need for LLM in the extraction pipeline).

If Treatment B > Treatment A, then H2 is supported: LLM normalization
provides value beyond coverage.

If neither beats Control, H3 is supported: the missed 4.9% does not
participate in multi-hop chains.

## Metrics

Primary:
- **MH chain-valid SEM** (reader-independent, conservative)
- **MH raw SEM** (both readers)

Diagnostic:
- Triples extracted (count, %)
- Unique entities in index
- Hop-2 entity matches (values that exist as entity keys)
- Per-question retrieval context length

## Protocol

Follows docs/BENCHMARK_PROTOCOL.md exactly. Additional constraints:

1. All three conditions use the same dataset load (cached, verified row count)
2. verify_clean.py mandatory before any reader touches retrieval files
3. Chain validation on all correct answers (same validator as Exp 4)
4. Dual reader (Opus + Haiku) on all three retrieval conditions
5. LLM extraction calls (Treatment B) are logged with full prompts/responses
6. Automatic 0% on any contamination detection

### LLM Extraction Prompt (Treatment B)

The Haiku prompt extracts (entity, property, value) triples from numbered
fact statements. It does NOT classify persist/type. It only does entity
extraction, keeping the variable isolated.

```
Extract structured facts from these numbered statements.
For each statement, extract:
- entity: the primary subject
- property: what is being stated about the entity
- value: the answer/object

Normalize entity names to their canonical form (e.g., "the current head
of the Pittsburgh government" -> entity: "Pittsburgh", property: "head_of_government").

Return JSON array: [{"id": 1, "entity": "...", "property": "...", "value": "..."}]

If a statement does not express a factual relationship, return null for that id.

Statements:
{statements}
```

### Batch Strategy

18,332 facts / 20 per batch = 917 Haiku calls.
At ~$0.00002/call = ~$0.018 total. Negligible cost.

## Step-by-Step Execution

### Step 1: Dataset Load + Baseline Diagnostics

```bash
uv run python benchmarks/mab_entity_index_adapter.py \
  --retrieve-only /tmp/exp5_control.json
uv run python benchmarks/verify_clean.py /tmp/exp5_control.json
```

Record: entity_count, fact_count, conflict_count, extraction rate.

### Step 2: Treatment A (Extended Regex)

Add 5 new patterns to triple_extraction.py (on experiment branch only).
Re-run adapter with same dataset.

```bash
uv run python benchmarks/mab_entity_index_adapter.py \
  --retrieve-only /tmp/exp5_treatment_a.json
uv run python benchmarks/verify_clean.py /tmp/exp5_treatment_a.json
```

### Step 3: Treatment B (LLM Extraction)

Run new LLM adapter with Haiku extraction.

```bash
uv run python benchmarks/mab_llm_entity_adapter.py \
  --retrieve-only /tmp/exp5_treatment_b.json
uv run python benchmarks/verify_clean.py /tmp/exp5_treatment_b.json
```

### Step 4: Dual Reader Scoring (6 runs total)

For each condition (control, treatment_a, treatment_b):
- Opus reader -> predictions file
- Haiku reader -> predictions file
- Score each against GT
- Chain-validate correct answers

### Step 5: Analysis

Compare across all 6 condition*reader combinations.
Report with full audit trail per BENCHMARK_PROTOCOL.md.

## Files

| File | Purpose |
|------|---------|
| `docs/EXP5_LLM_ENTITY_EXTRACTION.md` | This design document |
| `benchmarks/mab_llm_entity_adapter.py` | Treatment B adapter |
| `benchmarks/llm_entity_extraction.py` | LLM extraction module |
| `docs/EXP5_RESULTS.md` | Results (written after experiment) |

## Success Criteria

The experiment succeeds (produces a valid result) if:
1. All contamination checks pass
2. All conditions use the same dataset
3. Chain validation applied to all scores
4. Both readers tested on all conditions
5. Results documented with full audit trail

The hypothesis is supported if MH chain-valid > 35% for treatment conditions.
The null hypothesis is supported if no treatment exceeds 35%.
