# Experiment 5 Results: LLM Entity Extraction for Multi-Hop Retrieval

## Status: COMPLETE

## Summary

**Treatment A (extended regex) improves MH from 47% to 55% raw SEM (+8pp).**
**Treatment B (LLM extraction) is worse than baseline at 43% raw SEM (-4pp).**

The improvement comes from coverage (closing the 4.9% regex gap), not from
LLM normalization. LLM extraction introduces property fragmentation (94
unique properties vs 41 for regex) and 4.6% structural errors that hurt
conflict resolution and entity-index linking.

## Results

### Raw SEM (Substring Exact Match)

| Condition | Opus | Haiku | Delta vs Control |
|-----------|------|-------|------------------|
| Control (95.1% regex, 34 patterns) | 47% | 48% | baseline |
| Treatment A (100% regex, 41 patterns) | **55%** | **54%** | **+8pp / +6pp** |
| Treatment B (LLM extraction, Haiku) | 43% | 45% | -4pp / -3pp |

### Retrieval-Level Diagnostics

| Metric | Control | Treatment A | Treatment B |
|--------|---------|-------------|-------------|
| Extraction rate | 95.1% | 100% | 100% (4.6% structural errors) |
| Unique entities | 9,209 | 9,463 | 9,882 |
| Total facts | 17,435 | 18,332 | 18,332 |
| Conflicts resolved | 6,875 | 7,234 | 5,887 |
| Answer in context | 51/100 | **59/100** | 51/100 |
| Unique properties | 41 | 41 | 58 (after normalization; 94 raw) |

### Chain Validation

All correct answers in all conditions have the GT answer string present in
the retrieved context. Zero incidental matches. This is expected: entity-index
retrieval only produces chain-traversal facts, so any correct answer is by
definition chain-valid.

Note: The v1.1 baseline reported 35% chain-valid using a stricter definition
(required question entity found in index). The 47% control here uses the
same retrieval code as v1.1 but a different chain validation method
(answer-in-context check). The relative comparison between conditions is
valid; absolute numbers should not be compared to v1.1 without using the
same validator.

## Hypothesis Evaluation

**H1 (Coverage): SUPPORTED.** Closing the 4.9% extraction gap improved MH
SEM by +8pp (Opus) / +6pp (Haiku). The 897 previously missed facts included
intermediate entities needed for hop-2 chaining. Evidence: answer-in-context
jumped from 51 to 59 (+8 questions became answerable).

**H2 (Normalization): REJECTED.** LLM extraction produced more unique
entities (9,882 vs 9,463) but FEWER resolved conflicts (5,887 vs 7,234)
and WORSE scores (-4pp vs control). The property fragmentation across
subagent batches (94 raw property names for 41 distinct relations)
prevented the entity-index from detecting conflicts correctly. Even after
manual normalization to 58 properties, 851 entries (4.6%) had structural
errors (relationship text stuffed into entity/value fields instead of
clean property extraction).

**H3 (Null): REJECTED.** The missed 4.9% DID participate in multi-hop
chains. Coverage improvement produced a measurable score increase.

## Root Cause Analysis: Why LLM Extraction Failed

### 1. Property Fragmentation (Primary)

The LLM used inconsistent property names across batches:
- `religion` / `affiliated_religion` / `affiliated_with_religion` (3 names)
- `sport` / `associated_sport` / `associated_with_sport` (3 names)
- `born_in` / `born_in_city` (2 names)
- `plays_position` / `position` (2 names)

The entity-index groups facts by (entity, property). Different property
names for the same relation prevent conflict detection: if one batch says
(entity="Alice", property="citizen_of", value="France") and another says
(entity="Alice", property="nationality", value="Germany"), the index sees
two non-conflicting facts instead of a conflict requiring resolution.

Result: 5,887 conflicts detected (LLM) vs 7,234 (regex). The 1,347 missed
conflicts mean stale facts persist in the index.

### 2. Structural Errors (Secondary)

851/18,332 entries (4.6%) had the LLM fail to decompose the triple
correctly. Common failure modes:
- Entity includes prefix: "The univeristy where Sonny Perdue" instead of "Sonny Perdue"
- Value includes relationship: "employed by Detroit Tigers" instead of "Detroit Tigers"
- Property is generic "property" instead of a specific relation name

These entries pollute the index with malformed facts that won't match
entity lookups.

### 3. Normalization Advantage Not Realized

The hypothesis was that LLM would normalize entity names better
(e.g., "the author of American Pastoral" -> entity="American Pastoral").
In practice, the regex already handles this via pattern-specific capture
groups. The LLM's normalization was not better than regex's and was
often worse (including prefixes in entity names).

## Implications for agentmemory

1. **Extended regex is the correct approach for MAB FactConsolidation.**
   Adding 7 patterns to `triple_extraction.py` gives 100% coverage with
   zero structural errors and consistent property names.

2. **LLM entity extraction is not worth the cost for structured fact data.**
   The property consistency problem is fundamental to multi-batch LLM
   extraction. It could be mitigated with a fixed property schema, but
   that would make the LLM extraction equivalent to regex with extra steps.

3. **For natural language (non-MAB) data**, LLM extraction might still
   have value since regex patterns require pre-known sentence structures.
   This experiment does not test that case.

4. **The extended regex patterns should be merged to master** as they
   improve MH from 47% raw to 55% raw SEM.

## Protocol Compliance

- verify_clean.py passed on all 3 retrieval files (CLEAN)
- GT files separate (_gt.json), identical across conditions
- Two-pass protocol: generation then scoring
- Dual reader (Opus + Haiku) on all 3 conditions (6 total runs)
- Same dataset, same EntityIndex, same multi_hop_retrieve()
- Single variable isolated: extraction method
- No contamination detected

## Reproduction

```bash
# Control (run from master branch)
git checkout master
uv run python benchmarks/mab_entity_index_adapter.py --retrieve-only /tmp/exp5_control.json
uv run python benchmarks/verify_clean.py /tmp/exp5_control.json

# Treatment A (extended regex)
git checkout exp/llm-entity-extraction
uv run python benchmarks/mab_entity_index_adapter.py --retrieve-only /tmp/exp5_treatment_a.json
uv run python benchmarks/verify_clean.py /tmp/exp5_treatment_a.json

# Treatment B (LLM extraction)
uv run python benchmarks/exp5_export_lines.py /tmp/exp5_lines.json
# [orchestrate Haiku subagents for entity extraction]
uv run python benchmarks/exp5_build_index.py /tmp/exp5_lines.json /tmp/exp5_llm_triples.json \
  --retrieve-only /tmp/exp5_treatment_b.json
uv run python benchmarks/verify_clean.py /tmp/exp5_treatment_b.json

# Score all
uv run python benchmarks/exp5_score.py
```

## Files

| File | Purpose |
|------|---------|
| `docs/EXP5_LLM_ENTITY_EXTRACTION.md` | Experiment design |
| `docs/EXP5_RESULTS.md` | This results document |
| `benchmarks/exp5_score.py` | Scoring script |
| `benchmarks/exp5_export_lines.py` | Phase 1: export lines |
| `benchmarks/exp5_build_index.py` | Phase 2: build index from LLM triples |
| `benchmarks/llm_entity_extraction.py` | LLM extraction module (unused, kept for reference) |
| `benchmarks/mab_llm_entity_adapter.py` | Original LLM adapter (unused, kept for reference) |
| `src/agentmemory/triple_extraction.py` | Extended regex patterns (+7 patterns) |
