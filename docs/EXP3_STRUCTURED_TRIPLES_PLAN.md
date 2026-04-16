# Experiment 3: Structured Triple Extraction with SUPERSEDES Chains

## Hypotheses

**H1:** Parsing FactConsolidation facts into (entity, property, value, serial)
triples and creating SUPERSEDES edges between conflicting triples about the
same (entity, property) pair will improve MH 262K accuracy from 6% to >30%.

**H2:** The improvement comes specifically from the SUPERSEDES filtering
(stale facts excluded from retrieval), not from the triple structure itself.
Test: run with triples but WITHOUT SUPERSEDES edges. If accuracy is still
~6%, H2 is confirmed.

**H3:** Entity-level graph nodes enable BFS multi-hop traversal that chains
conflict-resolved intermediate values. Test: after triple ingestion with
SUPERSEDES, run BFS from the query entity through property edges to reach
the final answer without FTS5.

**Null hypothesis (H0):** The improvement from structured triples is <5pp
over the current 6%, because the reader LLM's world knowledge override
(root cause #2 from Exp 1) dominates regardless of retrieval quality.

## Controls

- **Baseline:** Current pipeline (6% MH 262K, already measured)
- **Control A:** Triples WITHOUT SUPERSEDES edges (tests H2)
- **Control B:** Triples WITH SUPERSEDES but FTS5-only retrieval (no BFS)
- **Treatment:** Triples WITH SUPERSEDES AND BFS entity traversal

All conditions use the same:
- Dataset: factconsolidation_mh_262k from MAB
- Reader: Opus 4.6 (same model, same prompt)
- DB isolation: fresh tempfile DB per run
- Ground truth: separate _gt.json file (no leakage)
- Scoring: substring_exact_match (paper metric)

## Implementation Plan

### Phase 1: Triple Extractor (new module)

File: `src/agentmemory/triple_extraction.py`

- `FactTriple` dataclass: entity, property_name, value, serial, source_text
- `extract_triple_regex()`: Pattern-match "Entity property Value" from
  FactConsolidation-formatted text. Returns None if no match.
- `find_conflicting_triple()`: Given a new triple, search the store for
  existing beliefs with the same (entity, property) pair and different value.
- No LLM calls in this phase. Regex only.

### Phase 2: Modified Benchmark Ingestion

File: `benchmarks/mab_triple_adapter.py` (new, separate from mab_adapter.py)

- Same chunking and data loading as mab_adapter.py
- After chunking, split each chunk into individual fact lines
- For each line, attempt triple extraction
- If triple extracted: create belief with entity/property/value metadata,
  search for conflicting triples, create SUPERSEDES edge if found
- If no triple: fall through to standard ingest_turn (no regression)
- Support --no-supersedes flag for Control A
- Support --no-bfs flag for Control B

### Phase 3: Modified Retrieval for Entity Traversal

- Use existing temporal_sort=True (already implemented)
- Add entity-based query expansion: if question mentions an entity,
  also retrieve via entity edges (ABOUT_ENTITY)
- Use existing BFS expand_graph() with SUPERSEDES edges INCLUDED
  (currently excluded) to walk supersession chains

### Phase 4: Scoring

- Same scoring as current: substring_exact_match against GT
- Same reader prompt (Opus, no ground truth in retrieval file)
- Report per-condition accuracy with 95% CI via binomial proportion

## Success Criteria

- H1 confirmed: Treatment > 30% (5x improvement over baseline 6%)
- H2 confirmed: Control A accuracy within 5pp of baseline 6%
- H3 confirmed: Treatment > Control B by >10pp
- H0 rejected: Treatment > 15% (meaningfully above noise)

## What We Learn If It Fails

- If Treatment <= 15%: Reader world knowledge override dominates.
  The retrieval is good enough but the reader won't use it.
  Next step: experiment with reader prompting strategies.
- If Control A >> 6%: Triple structure alone helps (even without
  SUPERSEDES), meaning the benefit is in entity-level retrieval,
  not conflict resolution. Revise hypothesis.
- If Treatment ~ Control B: BFS adds nothing, meaning FTS5 with
  SUPERSEDES filtering is sufficient. Simpler architecture wins.

## Isolation Requirements

- Fresh DB per condition (tempfile)
- No shared state between conditions
- Same random seed for Thompson sampling (set in scoring.py)
- Same Opus reader model and prompt for all conditions
- Ground truth in separate file, never in retrieval output
- Each condition runs end-to-end independently
