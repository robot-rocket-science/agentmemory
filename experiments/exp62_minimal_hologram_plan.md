# Experiment 62: Minimal Viable Hologram

**Date:** 2026-04-11
**Builds on:** Exp 42 (IB compression), Exp 47/48 (retrieval baselines), Exp 45 (HRR belief prototype)
**Rigor tier:** Empirically tested (real data, ablation study)

---

## Research Question

What is the smallest belief subgraph that preserves agent identity for a given task? Specifically: how many beliefs (and which types) must be included in a "hologram" -- a frozen projection of the full belief graph -- before retrieval quality and behavioral fidelity degrade below acceptable thresholds?

## Hypothesis

**H1:** A hologram containing only locked beliefs + top-k beliefs by Thompson-sampled score (k=50) will preserve >=90% retrieval coverage on the 6-topic ground truth, compared to the full graph (1,195 nodes).

**H2:** Removing all beliefs of a single type (e.g., all "context" beliefs) will degrade coverage by no more than 10%, except for "constraint" beliefs whose removal will degrade coverage by >=30%.

**H3:** There exists a "knee" in the coverage-vs-size curve below which coverage drops sharply. This knee represents the minimal viable hologram size.

## Null Hypothesis

Coverage degrades linearly with subgraph size (no knee). The full graph is the only viable hologram. Compression to a portable artifact is not feasible without retrieval loss.

## Why This Matters

If a small subgraph preserves agent identity, we can:
- Serialize it as a portable "agent profile" (JSON, SQLite snapshot, HRR vector)
- Load it into a fresh session as pre-prompt context without the full database
- Diff two holograms to see how an agent's worldview shifted over time
- Compose holograms (user prefs + project posture + domain expertise)

If there is no knee, the hologram concept is theoretically interesting but practically useless -- you always need the full graph.

## Materials

**Dataset:** The existing alpha-seek belief graph (1,195 nodes, 1,485 edges, 173 decisions). Same 6-topic ground truth from Exp 47 (13 critical beliefs needed).

**Scoring pipeline:** Thompson sampling + temporal decay + lock boost (existing `scoring.py` implementation).

**Retrieval:** FTS5 BM25 with porter stemming (existing `retrieval.py`).

**Random seed:** 42 (for Thompson sampling stochasticity).

## Methodology

### Phase 1: Coverage-vs-size curve

1. Score all 1,195 beliefs using the existing scoring pipeline (no query -- global ranking by Thompson-sampled confidence).
2. Sort beliefs by score descending.
3. For each k in [5, 10, 20, 30, 50, 75, 100, 150, 200, 300, 500, 750, 1000, 1195]:
   a. Take the top-k beliefs as the hologram.
   b. Build an in-memory FTS5 index over only those k beliefs.
   c. Run all 6 ground-truth queries against the reduced index.
   d. Measure coverage (found/needed), precision, token count.
4. Plot coverage vs. k. Identify the knee (second derivative peak of coverage curve).

### Phase 2: Type ablation

5. For each belief type [constraint, evidence, context, rationale, supersession, implementation]:
   a. Remove ALL beliefs of that type from the full graph.
   b. Re-run the 6 ground-truth queries.
   c. Measure coverage delta vs. full-graph baseline.

### Phase 3: Locked-only baseline

6. Build a hologram containing only locked beliefs (no scoring).
7. Run the 6 ground-truth queries.
8. Measure coverage. This is the "zero-effort" hologram -- what you get if you just persist locked beliefs.

### Phase 4: Composition test

9. Build two holograms: one from the first 50% of sessions (by creation date), one from the second 50%.
10. Merge them (union). Run ground-truth queries.
11. Compare merged coverage vs. full graph. This tests whether holograms compose without interference.

## Metrics

| Metric | Formula | Target | Interpretation |
|--------|---------|--------|----------------|
| Coverage@k | (found beliefs at subgraph size k) / (13 needed) | >=90% at k<=100 | Hologram is viable |
| Knee point | argmax(d2(coverage)/dk2) | k < 200 | Minimal viable hologram exists |
| Type ablation delta | coverage(full) - coverage(full minus type T) | <10% for non-constraint types | Type importance ranking |
| Locked-only coverage | coverage(locked beliefs only) | >=50% | Locked beliefs carry core identity |
| Composition coverage | coverage(merged) / coverage(full) | >=95% | Holograms compose cleanly |
| Hologram tokens | sum of tokens in minimal hologram | <=4000 | Fits in pre-prompt injection |

## Expected Results

| Condition | Expected Coverage | Reasoning |
|-----------|-------------------|-----------|
| Full graph (1,195) | 100% | Baseline (confirmed in Exp 47) |
| Top-50 | 85-95% | Constraint + high-confidence beliefs cover most ground truth |
| Top-100 | 95-100% | Comfortable margin |
| Top-20 | 60-75% | Missing some evidence/context nodes |
| Locked only | 40-60% | Locked beliefs are rules/corrections, not all retrieval targets |
| Minus constraints | 60-70% | Constraints are the backbone (H2) |
| Minus context | 90-100% | Context is filler (confirmed in Exp 42) |

## Decision Criteria

| If This Happens | Then Do This |
|-----------------|--------------|
| Knee exists at k<=100 with >=90% coverage | Hologram is viable. Design the serialization format (Exp 63 profiles). |
| Knee exists but at k>300 | Hologram is viable but large. Investigate type-weighted selection to shrink it. |
| No knee (linear degradation) | Hologram concept is not viable at current graph density. The full database is the profile. |
| Locked-only >=80% | Locked beliefs alone are a useful "lightweight profile." |
| Composition coverage <90% | Holograms interfere when merged. Composition requires dedup or conflict resolution. |

## Confounds and Controls

- **Ground truth bias:** The 6-topic ground truth is small (13 beliefs needed). A belief could be "important" for agent identity but not appear in the ground truth. Mitigation: Phase 2 type ablation tests structural importance, not just retrieval importance.
- **Thompson sampling variance:** Scores are stochastic. Mitigation: Use fixed seed=42. Report mean and std over 5 seeds for the knee-point measurement.
- **Temporal skew:** More recent beliefs may be scored higher regardless of importance. Mitigation: Phase 4 composition test explicitly splits by time.

---

## Files

- `exp62_minimal_hologram.py` -- all phases
- `exp62_results.json` -- raw coverage-vs-k data, type ablation deltas
- `exp62_minimal_hologram_results.md` -- analysis
