# Next Steps: Post-Benchmark Research Priorities

## Current State (2026-04-16)

### Benchmark Results (v1.2, post-Exp 5)

| Benchmark | Our Score | Paper Best | Status |
|-----------|----------|------------|--------|
| MAB SH 262K | 90% Opus / 62% Haiku | 45% GPT-4o-mini | 2x paper best (Opus) |
| MAB MH 262K | 55% Opus / 54% Haiku (raw SEM) | <=7% (all methods) | 7.8x paper ceiling |
| StructMemEval | 100% (14/14) | vector stores fail | Solved |
| LoCoMo | 66.1% F1 | 51.6% GPT-4o-turbo | +14.5pp |
| LongMemEval | TBD (being re-scored with Opus judge) | 60.6% GPT-4o pipeline | Pending |

### Architecture

- FTS5 + entity-index (L2.5) + HRR + BFS retrieval
- Regex triple extraction (41 patterns, 100% on MAB dataset)
- SUPERSEDES-based conflict resolution
- temporal_sort for state-tracking queries
- 2000-token retrieval budget
- No embeddings, no vector DB

### Codebase

- 18 production modules, 19 MCP tools
- 362+ tests passing
- Strict pyright typing on all code
- Contamination-proof benchmark protocol (verify_clean.py)

## Research Priorities (Ordered)

### Priority 1: LongMemEval Proper Scoring

**Status:** In progress (retrieval running, Opus judge pending)
**Why:** The 12.6% proxy score is meaningless. Keyword overlap systematically
underestimates accuracy. We need the actual binary-judge score to know where
we stand. This is the only benchmark where we're below published baselines.
**Risk:** May reveal a real weakness in our retrieval for conversational
memory (vs structured facts).

### Priority 2: MH Entity Aliasing

**Status:** Identified in Exp 5, not yet addressed
**Why:** The remaining 45% MH gap is primarily hop-2 entity matching.
When fact A says value="NBC" and fact B uses entity="National Broadcasting
Company", the entity-index can't link them.
**Approach:** Add an alias resolution layer to EntityIndex that maps common
abbreviations and alternate names. Could be regex-based (like triple
extraction) or use a small lookup table built from the dataset.
**Expected impact:** Unknown. Need to first quantify how many of the 45
failing MH questions have aliasing as root cause vs other issues.

### Priority 3: Cross-Benchmark Generalization

**Status:** Not started
**Why:** All improvements have been tested on MAB FactConsolidation.
The triple extraction and entity-index are designed for that dataset's
structured fact format. Need to verify they don't regress on other benchmarks
(LoCoMo, StructMemEval) which use conversational text.
**Approach:** Re-run LoCoMo and StructMemEval with v1.2 codebase. Results
should be >= v1.1 scores.

### Priority 4: AMA-Bench

**Status:** Adapter not built
**Why:** New benchmark (ICLR 2026 Workshop) covering a different use case
(agentic memory for task completion). Would broaden our evaluation coverage.
**Approach:** Build adapter following established protocol.

### Priority 5: Production Pipeline Integration

**Status:** Design complete, implementation partial
**Why:** The benchmark improvements (triple extraction, entity-index,
temporal_sort) are tested in isolation but not all wired into the live
MCP server pipeline. The production `ingest_turn()` uses triple extraction
and SUPERSEDES, but entity-index retrieval is benchmark-only.
**Approach:** Add entity-index as an optional retrieval layer in the
production `retrieve()` function. Gate behind a flag initially.

## Completed Research

| Experiment | Finding | Impact |
|-----------|---------|--------|
| Exp 1 | MH failure root cause: 58% chaining gap, 17% world knowledge, 11% retrieval miss | Directed all subsequent work |
| Exp 2 | SUPERSEDES helps SH (+30pp) but not MH (+1pp) | Narrowed focus to entity-level chaining |
| Exp 3 | Triples decomposition: +4pp MH | Foundation for entity-index |
| Exp 4 | Entity-index retrieval: +29pp MH (6% -> 35%) | Core breakthrough |
| Exp 5 | Extended regex +8pp MH. LLM extraction -4pp (property fragmentation) | Settled regex vs LLM question |

## Risks and Known Limitations

1. **Counterfactual benchmark bias:** MAB FactConsolidation uses deliberately
   wrong facts. LLM readers use world knowledge ~17% of the time despite
   instructions. This inflates false negatives.

2. **Single-dataset optimization:** Most improvements target MAB's structured
   fact format. Conversational benchmarks (LoCoMo, LongMemEval) may not
   benefit from the same techniques.

3. **Reader-dependent scores:** SH scores vary by 28pp between Opus and Haiku.
   MH scores are reader-independent (entity-index does the work). This
   distinction matters for reporting.

4. **LongMemEval underscored:** The 12.6% proxy is not comparable to published
   baselines. Must use proper judge before drawing conclusions.
