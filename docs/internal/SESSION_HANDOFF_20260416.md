# Session Handoff: 2026-04-16

## What Was Done

### Experiment 5: LLM Entity Extraction (COMPLETE)

Three-condition experiment testing whether LLM extraction improves MH:

| Condition | Opus SEM | Haiku SEM |
|---|---|---|
| Control (95.1% regex, 34 patterns) | 47% | 48% |
| Treatment A (100% regex, 41 patterns) | 55% | 54% |
| Treatment B (LLM Haiku extraction) | 43% | 45% |

**Result:** Extended regex wins (+8pp). LLM extraction rejected (-4pp) due
to property fragmentation (94 vs 41 names) and 4.6% structural errors.
H1 (coverage) supported. H2 (normalization) rejected.

Branch merged to master. 7 new patterns in `triple_extraction.py`.

### LongMemEval Proper Scoring (COMPLETE)

500 questions, Opus reader + Opus binary judge.

| Category | Score |
|---|---|
| single-session-user | 91.4% |
| single-session-preference | 80.0% |
| single-session-assistant | 73.2% |
| knowledge-update | 70.5% |
| temporal-reasoning | 59.4% |
| multi-session | 24.1% |
| **OVERALL** | **59.0%** |

Reference: GPT-4o + LongMemEval_S pipeline = 60.6% (-1.6pp).
Previous proxy (12.6%) retired.

### Entity Extraction Quick Win (COMPLETE)

Fixed `extract_entity_from_question()` in `mab_entity_index_adapter.py`.
8 of 9 failures fixed. MH score: 55% -> **58%** (+3pp).

GT reachable went from 59/100 to 62/100.

### Code Audit (COMPLETE)

Opus subagent reviewed all 6 benchmark files. No result-invalidating bugs.
Two medium code quality issues documented in `CODE_AUDIT_EXP5.md`.

### Deep Failure Analysis (COMPLETE, key finding)

Of 42 remaining MH failures:
- 31 chaining gap (entity found, GT not reachable via latest-serial chain)
- 7 retrieval miss (entity not found or no entity extracted)
- 4 reader errors (GT in context, reader got it wrong)

**Root cause of chaining gap: temporal coherence.**

Our entity-index resolves each (entity, property) to the globally latest
serial independently. The benchmark GT follows chains where intermediate
hops use earlier serials. Example Q2:

```
Our chain:     American Pastoral -> FSF (10793) -> Carl Lumbly (16800)
               -> Colombia (9097) -> Antarctica (7238)

GT chain:      American Pastoral -> FSF (10793) -> Zelda Fitzgerald (8453)
               -> Australia (10172) -> Oceania (2465)
```

Both chains are valid given the data. Our chain uses latest serial at every
hop. The GT chain uses a non-latest spouse (Zelda, serial 8453, not Carl
Lumbly serial 16800). The GT produces Oceania; ours produces Antarctica.

This is NOT entity aliasing. It is NOT breadth-cap pruning (removing the
cap gives 0 improvement). It is a fundamental issue with how we resolve
multi-hop chains when entities have multiple historical values.

## Current Benchmark Numbers

| Benchmark | Score | Paper Best |
|---|---|---|
| MAB SH 262K | 90% Opus / 62% Haiku | 45% |
| MAB MH 262K | 58% Opus | <=7% |
| StructMemEval | 100% | fail |
| LoCoMo | 66.1% | 51.6% |
| LongMemEval | 59.0% | 60.6% |

## Next Session: Temporal Coherence

### The Problem (Generalized)

**Direct supersession** (handled): when two facts about the same
(entity, property) conflict, the newer one supersedes the older.
agentmemory creates a SUPERSEDES edge.

**Transitive supersession** (not handled): when fact A is stated in the
same temporal context as fact B, and fact B is later superseded, fact A
becomes potentially stale. No SUPERSEDES edge exists for A because nobody
explicitly contradicted it.

Real-world example: user says "use PostgreSQL" and "config in config.yaml"
in the same session. Later says "switch to SQLite." The config.yaml fact is
linked to PostgreSQL and may be stale, but there's no SUPERSEDES edge on it.

### The Proposed Mechanism: Session-Coherent Supersession

When a belief is superseded, check if other beliefs from the same
observation/session might also be stale. Options:

1. **Lower confidence** on co-temporal beliefs (soft signal)
2. **Create POTENTIALLY_STALE edges** (queryable but not auto-excluded)
3. **Serial-proximity grouping** (facts within N serials of each other
   form a coherent bundle)

### The Test for Generality

The mechanism is general (not benchmark-specific) if and only if it
improves BOTH:
- MAB MH 262K (serial-ordered structured facts)
- LongMemEval multi-session (24.1%, conversational memory)

If it only helps MAB, it's gaming the benchmark.

### agentmemory Infrastructure Already Available

- `session_id` on beliefs (same-session grouping)
- `observation_id` linking beliefs to source turns
- `created_at` timestamps (temporal proximity)
- SUPERSEDES edges (direct conflict resolution)
- `valid_to` field (belief expiration)

The mechanism needs:
1. A way to identify co-temporal beliefs (same session, same observation,
   or serial proximity)
2. A cascade rule: when belief X is superseded, what happens to beliefs
   co-temporal with X?
3. Retrieval integration: how does the retrieval pipeline use stale signals?

### User's Key Insight

The user noted: "LLMs have problems parsing and distinguishing between
serialized data, particularly if it's enumerated. The LLM could interpret
a serial number as a hash rather than as an incremented integer that
supersedes a prior serial number."

This is correct. The entity-index approach bypasses the LLM entirely for
resolution (mechanical, not LLM-based). The proposed temporal coherence
mechanism should also be mechanical: same-session beliefs form a bundle,
SUPERSEDES cascades within bundles. No LLM needed for the cascade logic.

The concern about gaming: "it has to be generalizable and replicable, and
it could fall under the category of gaming the benchmark, though the
benchmark is based on a real problem LLMs have, so the concern is that we
game the benchmark without solving the actual problem."

The validation: test on both MAB and LongMemEval. If both improve, it's
general. If only MAB improves, it's gaming.

## Files Modified This Session

| File | Change |
|---|---|
| `src/agentmemory/triple_extraction.py` | +7 regex patterns (100% MAB coverage) |
| `benchmarks/mab_entity_index_adapter.py` | Improved entity extraction (+3pp) |
| `benchmarks/exp5_score.py` | New: Exp 5 scoring script |
| `benchmarks/exp5_export_lines.py` | New: LLM extraction Phase 1 |
| `benchmarks/exp5_build_index.py` | New: LLM extraction Phase 2 |
| `benchmarks/llm_entity_extraction.py` | New: LLM extraction module |
| `benchmarks/mab_llm_entity_adapter.py` | New: LLM adapter (unused) |
| `benchmarks/longmemeval_score.py` | New: LongMemEval scoring |
| `benchmarks/__init__.py` | New: package init |
| `docs/EXP5_LLM_ENTITY_EXTRACTION.md` | New: Exp 5 design |
| `docs/EXP5_RESULTS.md` | New: Exp 5 results |
| `docs/CODE_AUDIT_EXP5.md` | New: code audit |
| `docs/NEXT_STEPS.md` | New: research priorities |
| `docs/PUBLISH_STRATEGY.md` | New: publish decision |
| `docs/BENCHMARK_SESSION_LOG_V12.md` | New: session narrative |
| `docs/BENCHMARK_RESULTS.md` | Updated with all new numbers |

## Git Log (This Session)

```
86f0786  Improve MH question entity extraction: 58% SEM (was 55%, +3pp)
bed8963  Update NEXT_STEPS with deep MH failure analysis findings
e018ee5  Add publish strategy decision (2026-04-16)
78e8d4a  v1.2 session write-up: Exp 5 + LongMemEval proper scoring narrative
a8e35a1  LongMemEval: 59.0% accuracy (Opus judge, 500 questions)
8005ee7  Add LongMemEval scoring script with per-category accuracy
25bbf24  Add code audit results: no result-invalidating bugs found
df49542  Add NEXT_STEPS.md: post-benchmark research priorities
592e701  Merge exp/llm-entity-extraction: +8pp MH via extended regex
33206ab  Exp 5 results: extended regex +8pp MH, LLM extraction -4pp
b58450e  Exp 5: add scoring script for all condition*reader combinations
e85921f  Exp 5: add two-phase adapter for subagent-based LLM extraction
e809e70  Exp 5: LLM entity extraction setup + extended regex patterns
```
