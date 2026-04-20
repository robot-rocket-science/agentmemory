# Valence Propagation: Implementation Plan

Status: Ready to execute (2026-04-17)
Design doc: docs/SPECTRUM_FEEDBACK.md

## File changes

### 1. src/agentmemory/models.py

Add new constants:

```python
# New outcomes
OUTCOME_CONFIRMED: Final[str] = "confirmed"
OUTCOME_WEAK: Final[str] = "weak"

# Valence map: string outcome -> continuous score
VALENCE_MAP: dict[str, float] = {
    "confirmed": +1.0,
    "used":      +0.5,
    "ignored":    0.0,
    "weak":      -0.3,
    "harmful":   -1.0,
}

# Edge-type valence multipliers
EDGE_VALENCE: dict[str, float] = {
    "SUPPORTS":      1.0,
    "DEPENDS_ON":    0.8,
    "ELABORATES":    0.7,   # not yet in edge types, future
    "IMPLEMENTS":    0.7,
    "CITES":         0.5,
    "CO_OCCURRED":   0.5,   # not yet in edge types, future
    "RELATES_TO":    0.3,
    "CONTRADICTS":  -0.5,   # INVERTS the valence
    "SUPERSEDES":    0.0,   # historical, no propagation
    "TEMPORAL_NEXT": 0.0,   # structural, no propagation
    "TESTS":         0.5,
    "SPECULATES":    0.3,
    "RESOLVES":      0.5,
}

# Propagation parameters
VALENCE_DECAY: Final[float] = 0.5
VALENCE_MAX_HOPS: Final[int] = 3
VALENCE_MIN_THRESHOLD: Final[float] = 0.05
CONFIRM_WEIGHT: Final[float] = 2.0
SESSION_HUB_BOOST: Final[float] = 2.0
```

### 2. src/agentmemory/store.py

**Schema migration** (_migrate_tests, _migrate_sessions):

```python
# In _migrate_tests (new method or extend existing):
if "valence" not in col_names:
    ALTER TABLE tests ADD COLUMN valence REAL

# In _migrate_sessions:
if "quality_score" not in col_names:
    ALTER TABLE sessions ADD COLUMN quality_score REAL
```

**Modify update_confidence()** (line 762):
- Accept optional `valence: float | None` parameter
- If valence is provided, use it directly instead of outcome string
- If valence > 0: alpha += abs(valence) * weight
- If valence < 0: beta += abs(valence) * weight
- Backward compat: if valence is None, use existing outcome-based logic

**New method: propagate_valence()**:
- Multi-hop BFS propagation with edge-type modulation
- Uses EDGE_VALENCE multipliers from models.py
- Decays by VALENCE_DECAY per hop
- Stops at VALENCE_MIN_THRESHOLD
- CONTRADICTS edges invert the valence sign
- Returns count of beliefs updated and total propagation reach

**New method: get_session_retrieval_subgraph()**:
- Query tests table for all belief_ids in a session
- Query edges table for edges between those beliefs
- Compute degree centrality per belief in the subgraph
- Return: belief_ids, edges, centrality scores

**Modify record_test_result()**:
- Accept optional `valence: float | None` parameter
- Store it in the new valence column
- Pass to update_confidence

### 3. src/agentmemory/server.py

**Modify _VALID_OUTCOMES** (line 1351):
- Add "confirmed" and "weak"

**Modify feedback()** (line 1425):
- Accept optional `score: float | None` parameter
- If score is provided, map to valence directly
- If string outcome, look up in VALENCE_MAP
- Call propagate_valence() after belief update

**New tool: confirm()** (~20 lines):
- Takes belief_id and optional detail
- Records test_result with outcome="confirmed", valence=+1.0
- Calls update_confidence with weight=CONFIRM_WEIGHT
- Calls propagate_valence from the confirmed belief
- Returns updated confidence

**New tool: session_quality()** (~40 lines):
- Takes score: float [-1.0, +1.0] and optional detail
- Calls get_session_retrieval_subgraph()
- Computes hub-weighted valence per belief
- Applies valence to each belief (heavier for high-centrality)
- Records in sessions.quality_score
- Returns summary

**Modify _process_auto_feedback()** (line 96):
- Replace binary used/ignored with gradient:
  score = matched_terms / total_terms (continuous 0.0-1.0)
- Weight by belief degree (from edge count): degree * overlap_ratio
- Sort by weighted score, process highest first
- Record valence in test_result

### 4. Tests to write (tests/test_valence.py, ~200 lines)

1. test_valence_map_backward_compat -- string outcomes still work
2. test_continuous_valence_positive -- score=+0.7 increments alpha
3. test_continuous_valence_negative -- score=-0.3 increments beta
4. test_contradicts_inverts_valence -- confirming A weakens A's CONTRADICTS
5. test_propagation_decay -- hop 2 gets decay^2 of original
6. test_propagation_stops_at_threshold -- very small valence doesn't propagate
7. test_confirm_boosts_alpha -- confirm() adds CONFIRM_WEIGHT to alpha
8. test_confirm_propagates -- confirm() triggers valence propagation
9. test_session_quality_hub_weighted -- hubs get more weight
10. test_session_quality_records -- sessions.quality_score is set
11. test_gradient_auto_feedback -- overlap_ratio produces continuous valence
12. test_auto_feedback_hub_routing -- high-degree beliefs get priority

### 5. Acceptance tests (tests/acceptance/test_valence_acceptance.py)

1. Full loop: ingest -> retrieve -> confirm -> verify propagation
2. Contradiction resolution: confirm one side, verify other side drops
3. Session quality propagation through real graph
4. Gradient auto-feedback produces better calibration than binary

## Execution order

1. models.py -- add constants (no dependencies)
2. store.py -- schema migration + update_confidence + propagate_valence
3. server.py -- modify feedback, add confirm/session_quality
4. server.py -- upgrade auto-feedback to gradient
5. Run existing 260+ tests (regression check)
6. Write + run new valence tests
7. Write + run acceptance tests
8. Benchmark evaluation

## Benchmark strategy

Benchmarks where valence propagation should help:

**LongMemEval multi-session (24.1%)**: The weakness is cross-session entity
linking. Valence propagation through SUPPORTS/RELATES_TO edges could
strengthen pathways between related beliefs from different sessions,
improving retrieval for multi-session queries. Pre-registered hypothesis:
+5pp on multi-session category (24.1% -> 29%).

**MAB MH 262K**: The 35% chain-valid score is limited by hop-2 entity
coverage. If valence propagation strengthens entity-chain edges after
successful retrievals, subsequent queries on the same entity chains should
benefit. But this is a fresh-DB benchmark (no prior feedback), so valence
only helps via auto-feedback during the benchmark run itself.

**StructMemEval**: Already at 100%. No room for improvement.

**LoCoMo**: At 66.1%. Possible improvement in temporal consistency if
valence strengthens temporal edges. Pre-registered hypothesis: +2pp.

Contamination protocol: follow BENCHMARK_PROTOCOL.md exactly. Use haiku
for answer generation where model quality is disputed. Separate retrieval
and GT files. Run verify_clean.py before any LLM touches data.
