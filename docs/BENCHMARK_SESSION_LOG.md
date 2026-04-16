# Benchmark Session Log: 2026-04-15

## Session Objective

Run agentmemory against standard benchmarks with scientific rigor.
Identify gaps. Test hypotheses for closing them.

## Benchmarks Run

### 1. LoCoMo (ACL 2024) - PRIOR SESSION

- **Score: 66.1% F1** (beats GPT-4o-turbo 51.6% by 14.5pp)
- Protocol-correct: exact LoCoMo prompts, forced-choice adversarial
- Reader: Opus 4.6

### 2. MemoryAgentBench FactConsolidation (ICLR 2026)

**Single-Hop 262K:**
- **Score: 60% SEM** (beats GPT-4o-mini 45% by 15pp)
- Retrieval finds answer in context 98% of the time
- Reader extracts correct answer 60% of the time

**Multi-Hop 262K:**
- **Score: 6% SEM** (field ceiling: <=7%)
- All conditions tested: 4-10% depending on configuration
- See Exp 1 and Exp 3 for detailed failure analysis

### 3. StructMemEval (2026 preprint)

**Before fix:** 4/14 (28.6%) on location state tracking
**After temporal_sort fix:** 14/14 (100%)

Fix: synthetic narrative timestamps (30d apart per session) + temporal_sort
in retrieval (newest beliefs presented first). Two mechanism changes,
not parameter tuning.

### 4. LongMemEval (ICLR 2025)

- 500 questions, oracle sessions
- 12.6% keyword overlap proxy (conservative lower bound)
- Needs GPT-4o judge for fair comparison to published numbers
- Retrieval stats: avg 53 beliefs/query, 9.8ms latency

### 5. AMA-Bench (ICLR 2026 Workshop)

- 600 QA pairs from 50 episodes (retrieval only, not scored with reader)

## Contamination Incidents

### Incident 1: GT in retrieval output

All adapters initially wrote ground truth answer fields into the
retrieve-only JSON. This meant LLM readers could see correct answers.
Discovered when MAB MH 262K scored 100% (impossibly high).

**Fix:** Separate retrieval and GT into two files. Adapter writes
`name.json` (no answers) and `name_gt.json` (answers only).
All 4 adapters patched. verify_clean.py gatekeeper added.

### Incident 2: LLM self-judging with answer visible

LongMemEval Opus reader was asked to generate answers AND judge them
against ground truth in the same prompt. The model could see the
answer during generation.

**Fix:** Two-pass protocol. Pass 1: generate (no GT visible).
Pass 2: score (separate script or separate LLM call).

## Experiment Results

### Exp 1: Per-Hop Failure Analysis (diagnostic)

Classified 100 MH failures into three root causes:
- **58% chaining gap:** Entity found, wrong intermediate value (stale fact)
- **17% reader override:** Answer in context, reader uses world knowledge
- **11% retrieval miss:** Topic completely missed by FTS5

Key finding: the bottleneck is CHAINING, not conflict resolution.

### Exp 3: Structured Triple Extraction

Built triple_extraction.py (95.1% extraction rate) and
mab_triple_adapter.py. Tested 4 conditions:

| Condition | SEM | Context Size |
|-----------|-----|-------------|
| Baseline (chunks) | 6% | 3909 chars |
| Ctrl A (triples, no SUPERSEDES) | 10% | 1992 chars |
| Ctrl B (SUPERSEDES, no BFS) | 1% | 1090 chars |
| Treatment (SUPERSEDES + BFS) | 4% | 1856 chars |

**All hypotheses rejected.** SUPERSEDES correctly filters stale facts
but reduces context volume, hurting multi-hop by making the context
smaller. The bottleneck is query decomposition (single FTS5 query
can't chain entity relationships), not conflict resolution.

## Mechanism Fixes Shipped

### 1. temporal_sort parameter in retrieve()

Added `temporal_sort: bool = False` to retrieve(). When True, packed
beliefs are re-sorted newest-first after relevance-based selection.
Selection still uses scores; presentation order changes.

Impact: StructMemEval 28.6% -> 100%.

### 2. Data isolation in all adapters

All benchmark adapters now write separate retrieval and GT files.
verify_clean.py checks for 30 banned keys before any LLM touches data.

### 3. Triple extraction module

`src/agentmemory/triple_extraction.py`: 25 regex patterns, 95.1%
extraction on FactConsolidation. General-purpose, falls through
gracefully on unmatched text.

## Code Artifacts

All on branch `benchmark/multi-benchmark`:

```
benchmarks/
  locomo_adapter.py          - LoCoMo benchmark adapter
  locomo_score_protocol.py   - Protocol-correct LoCoMo scoring
  locomo_generate.py         - Answer generation stub
  mab_adapter.py             - MAB benchmark adapter
  mab_triple_adapter.py      - MAB with triple extraction (Exp 3)
  longmemeval_adapter.py     - LongMemEval adapter
  structmemeval_adapter.py   - StructMemEval adapter (with temporal fix)
  amabench_adapter.py        - AMA-Bench adapter
  verify_clean.py            - Contamination verification gatekeeper

src/agentmemory/
  triple_extraction.py       - Structured fact triple extraction
  retrieval.py               - Added temporal_sort parameter

docs/
  BENCHMARK_RESULTS.md       - Clean results summary
  BENCHMARK_PROTOCOL.md      - Contamination-proof evaluation protocol
  BENCHMARK_PLAN.md          - Original benchmark plan
  BENCHMARK_DECAY_ANALYSIS.md - Decay/promotion rate analysis
  BENCHMARK_LOG.md           - LoCoMo detailed methodology
  WONDER_MULTIHOP_CONFLICT.md - Multi-hop conflict resolution research
  EXP1_PERHOP_FAILURE_ANALYSIS.md - Per-hop failure diagnostic
  EXP3_STRUCTURED_TRIPLES_PLAN.md - Exp 3 design
  EXP3_RESULTS.md            - Exp 3 results (hypotheses rejected)
```

## Open Questions for Next Session

### Immediate (testable now):

1. **PRF-chained retrieval:** Use pseudo-relevance feedback iteratively
   for multi-hop. Pass 1 finds hop-1 entity, extract terms, pass 2
   finds hop-2. Already validated for single-hop (Exp 18).

2. **Entity-index retrieval:** Simple dict lookup bypassing FTS5.
   During ingest: `entity_index[entity] = [belief_ids]`.
   At query time: extract entity, look up directly. Cheapest fix.

3. **LLM query decomposition:** Haiku decomposes multi-hop into
   sub-queries. ~$0.0001/question. Most likely to work.

4. **4K token budget:** Does doubling budget recover volume advantage
   while keeping SUPERSEDES precision? (Run in progress.)

### Medium-term:

5. **HippoRAG PPR (A008):** Personalized PageRank from entity nodes.
   20% improvement on multi-hop in their paper.

6. **Beam search (A020):** Top-k path exploration instead of BFS.

### Fundamental question:

Is multi-hop conflict resolution at 262K tokens the right goal for
agentmemory? Our single-hop results are strong (60% SH, 100% state
tracking). Multi-hop with counterfactual data is an adversarial benchmark
that doesn't map directly to real-world agent memory usage. The UX
value is in single-hop corrections and state tracking, not in chaining
two counterfactual facts about fictional sports origins.
