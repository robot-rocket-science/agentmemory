# Experiment 64: Pre-Prompt Compilation Pipeline

**Date:** 2026-04-11
**Builds on:** Exp 42 (IB compression), Exp 62 (minimal hologram), Exp 47/48 (retrieval baselines)
**Rigor tier:** Empirically tested (real data, ablation + budget sweep)

---

## Research Question

Can a compilation step -- run before any user prompt -- select, compress, and pack beliefs into a token-budgeted context payload that improves retrieval quality compared to the current flat `get_locked` injection? And at what point does injecting more compiled context start HURTING rather than helping (the "cage" threshold)?

## Hypothesis

**H1 (Compilation beats flat):** A compiled context payload (scored, type-compressed, budget-packed) will achieve higher coverage than flat locked-belief injection on the 6-topic ground truth. Expected: compiled >= 90% coverage vs. locked-only ~50% (from Exp 62 estimate).

**H2 (Budget curve has a plateau):** There exists a token budget B* above which adding more compiled context yields <2% additional coverage per 500 tokens. This is the diminishing-returns point.

**H3 (The cage exists):** There exists a budget B_cage above which compiled context actively degrades a downstream metric. Specifically: if we simulate "retrieval given pre-loaded context" by measuring how many of the 13 ground-truth beliefs appear in the UNION of (compiled context + on-demand retrieval), injecting too much compiled context will push on-demand retrieval to return redundant or lower-quality results, effectively wasting the on-demand budget.

**H4 (Compilation cost is acceptable):** The compilation step completes in under 500ms for graphs up to 2,000 nodes. This is fast enough to run in a SessionStart hook without perceptible delay.

## Null Hypothesis

Compiled context provides no coverage advantage over flat locked-belief injection. The scoring/compression overhead adds latency without retrieval benefit. The agent is better off with a minimal context and full on-demand retrieval budget.

## Why This Matters

Pre-prompt compilation is the mechanism by which the hologram "projects" into the agent's context. If it works:
- The agent starts every session already oriented to the project
- Retrieval is augmented, not replaced: the compiled context handles common/stable knowledge, on-demand retrieval handles novel queries
- The compilation budget becomes a tunable knob (like the commit tracker thresholds -- configurable, deterministic)

If the cage threshold is low (e.g., B_cage = 1000 tokens), the feature is useful but constrained. If B_cage is high (e.g., 4000+), there is room for rich pre-loading.

## Materials

**Dataset:** Alpha-seek belief graph (1,195 nodes, 1,485 edges).

**Ground truth:** 6-topic, 13-belief set from Exp 47.

**Scoring pipeline:** Existing `scoring.py` (Thompson + decay + lock boost).

**Compression:** Existing type-aware compression from Exp 42 (constraint=1.0x, evidence=0.54x, context=0.23x, rationale=0.36x).

**Token estimation:** chars/4 (consistent with Exp 42).

**On-demand retrieval budget:** 2,000 tokens (REQ-003).

## Methodology

### Phase 1: Compilation pipeline implementation

The compilation pipeline is a function with this signature:

```python
def compile_context(
    store: MemoryStore,
    budget: int,           # max tokens for compiled output
    project_hint: str = "",  # optional project name for relevance boost
) -> CompiledContext:
    """Select, score, compress, and pack beliefs into a token budget."""
```

Steps:
1. Retrieve all non-superseded beliefs from the store.
2. Score each belief using `scoring.py` (Thompson sample + decay + lock boost). No query -- this is global relevance.
3. Sort by score descending.
4. Apply type-aware compression (from Exp 42 ratios).
5. Greedily pack beliefs into the token budget, highest-score first.
6. Return the packed beliefs + metadata (count, types, total tokens, beliefs excluded).

### Phase 2: Coverage vs. budget sweep

1. For each budget in [250, 500, 750, 1000, 1500, 2000, 3000, 4000, 6000, 8000]:
   a. Run the compilation pipeline with that budget.
   b. Build an FTS5 index over the compiled beliefs.
   c. Run the 6 ground-truth queries against the compiled index.
   d. Record: coverage, belief count, type distribution, compilation time.
2. Plot coverage vs. budget. Identify B* (plateau onset) and the coverage ceiling.

### Phase 3: Baseline comparison

3. Run the same 6 queries against:
   a. **Flat locked:** Only locked beliefs, no scoring, no compression (current `get_locked` behavior).
   b. **Random-k:** Randomly select k beliefs where k matches the compiled set's count at each budget. This controls for "more beliefs = more coverage" regardless of selection quality.
   c. **Full graph:** All 1,195 beliefs (upper bound).
4. Compare compiled vs. flat locked vs. random at each budget level.

### Phase 4: Cage detection

5. Simulate a session with BOTH compiled context AND on-demand retrieval:
   a. The compiled context occupies B tokens of a total 4,000-token context window.
   b. The remaining (4,000 - B) tokens are available for on-demand retrieval.
   c. For each budget B in [0, 500, 1000, 1500, 2000, 2500, 3000, 3500, 4000]:
      - Compile B tokens of context.
      - For each ground-truth query, retrieve additional beliefs from the FULL graph using the remaining budget (4000 - B).
      - Measure UNION coverage: beliefs found in compiled context OR on-demand retrieval.
   d. The cage threshold B_cage is the budget where UNION coverage starts declining (compiled beliefs crowd out better on-demand results).

### Phase 5: Compilation latency

6. Measure compilation time for graphs of different sizes:
   a. 100 nodes (subsample)
   b. 500 nodes (subsample)
   c. 1,195 nodes (full graph)
   d. 2,000 nodes (synthetic: duplicate graph with shuffled IDs)
7. Each size: 20 repetitions. Report p50, p95, max.

## Metrics

| Metric | Formula | Target | Interpretation |
|--------|---------|--------|----------------|
| Compiled coverage@B | (found beliefs at budget B) / 13 | >= 90% at B=2000 | Compilation is useful |
| Coverage lift vs. locked | compiled_coverage - locked_coverage at same token count | >= 20pp | Scoring adds value |
| Coverage lift vs. random | compiled_coverage - random_coverage at same belief count | >= 15pp | Selection quality matters |
| Plateau onset B* | smallest B where d(coverage)/dB < 2% per 500 tokens | B* < 3000 | Diminishing returns are bounded |
| Cage threshold B_cage | smallest B where union_coverage(B) < union_coverage(B-500) | B_cage > 2000 or none | Over-injection is not a risk until high budgets |
| Compilation latency p95 | 95th percentile at 1,195 nodes | < 500ms | Acceptable for SessionStart hook |

## Expected Results

| Budget | Compiled Coverage | Locked Coverage | Random Coverage |
|--------|-------------------|-----------------|-----------------|
| 500 | 60-70% | 40-50% | 30-40% |
| 1000 | 80-90% | 40-50% | 50-60% |
| 2000 | 90-100% | 40-50% | 65-75% |
| 4000 | 100% | 40-50% | 80-90% |

**Cage prediction:** B_cage will be at 2500-3000 tokens. Below this, compiled context adds unique beliefs not found by on-demand retrieval. Above this, the compiled context overlaps heavily with on-demand retrieval and wastes context window space.

## Decision Criteria

| If This Happens | Then Do This |
|-----------------|--------------|
| Compiled >= 90% at B<=2000, lift vs. locked >= 20pp | Implement compilation as a SessionStart pipeline step. Add `compile_budget` to config. |
| Compiled coverage = locked coverage at all budgets | Scoring adds no value. The locked beliefs ARE the hologram. Simplify. |
| Random coverage = compiled coverage | Selection quality does not matter -- just inject more beliefs. Budget is the only lever. |
| B_cage < 1500 | The cage is real and tight. Default budget must be conservative (1000 tokens). Warn users who increase it. |
| B_cage does not exist (union coverage monotonically increases) | No cage. Let users set budget as high as their context window allows. |
| Latency > 1s at 1,195 nodes | Compilation is too slow for SessionStart. Pre-compile on ingest or on a background timer instead. |

## Confounds and Controls

- **Ground truth size:** 13 beliefs across 6 topics is small. At high budgets, even random selection may find all 13. Mitigation: measure precision (how many irrelevant beliefs are included) alongside coverage.
- **Compression interacts with selection:** Compressing a belief changes its token footprint, which changes how many beliefs fit in the budget, which changes selection. The greedy packing is sensitive to compression ratios. Mitigation: report the type distribution of selected beliefs at each budget level.
- **On-demand retrieval is query-dependent, compilation is not.** The cage test compares a query-agnostic compilation against query-specific retrieval. The compilation may never beat targeted retrieval for specific queries -- its value is in covering the "common case" so retrieval handles the "novel case." Mitigation: measure per-query results, not just aggregate.

---

## Files

- `exp64_preprompt_compilation.py` -- all phases
- `exp64_results.json` -- budget sweep data, cage detection, latency
- `exp64_preprompt_compilation_results.md` -- analysis
