# Experiment 65: Hologram Diffing and Drift Detection -- Results

**Date:** 2026-04-11
**Input:** Production memory.db (29,172 non-superseded beliefs)
**Method:** Set-theoretic diffing, simulated drift, correction impact, noise floor
**Rigor tier:** Empirically tested (real data, controlled insertions)

---

## Summary

**H1 CONFIRMED.** Diff computation is fast: p50=17ms for self-diff, p50=19ms for modified diff. Well under 100ms target at 29K beliefs.

**H2 PARTIALLY REJECTED.** 50 simulated turns produce zero top-100 turnover (Jaccard 0.0). The diff correctly detects 50 added beliefs, but none penetrate the top-100 because all new and existing beliefs share identical confidence (0.9). This confirms Exp 63's saturation finding.

**H3 CONFIRMED.** Each correction produces a clean single-belief diff. All three corrections appear in the top-100 (confidence 0.947 from alpha=9.0, beta=0.5). Top-100 turnover per correction: 0.0198 (exactly 1 entry replaced out of ~100).

**H4 CONFIRMED.** Noise floor is exactly zero. Two snapshots with no changes produce an empty diff. Since confidence is a stored value (not sampled), there is no stochastic noise in the diff.

---

## Phase 1: Diff Performance

| Operation | p50 | p95 |
|-----------|-----|-----|
| Self-diff (29,172 beliefs) | 16.8ms | 17.8ms |
| Modified diff (10 confidence changes) | 18.5ms | 20.2ms |

Fast enough for real-time use. Could run on every tool call if needed.

---

## Phase 2: Simulated Drift

| Turn | Added | Top-100 Turnover |
|------|-------|-----------------|
| 5 | 5 | 0.000 |
| 10 | 10 | 0.000 |
| 20 | 20 | 0.000 |
| 30 | 30 | 0.000 |
| 40 | 40 | 0.000 |
| 50 | 50 | 0.000 |

**50 new beliefs, zero top-100 impact.** The diff correctly reports 50 added beliefs, but the top-100 (sorted by confidence descending) doesn't change because new beliefs at 0.9 confidence tie with existing beliefs, and the original beliefs were inserted first (stable sort).

This is the same saturation problem from Exp 63. The diff mechanism works -- it detects additions. But the top-k metric is meaningless when confidence is uniform.

---

## Phase 3: Correction Impact

| Correction | Clean Signal | In Top-100 | Turnover |
|-----------|-------------|-----------|----------|
| C1: "HRR only useful for fuzzy-start" | Yes (1 added) | Yes | 0.0198 |
| C2: "Token budget must be 3000" | Yes (1 added) | Yes | 0.0198 |
| C3: "Temporal edges add zero signal" | Yes (1 added) | Yes | 0.0198 |

**Corrections produce clean, detectable signals.** Each correction is the ONLY change in its diff (clean_signal=true). Each one enters the top-100 because its confidence (94.7%) exceeds the uniform 90% of existing beliefs.

This validates the core idea: locked, high-confidence corrections are detectable in diffs. The 4.7pp confidence gap (94.7% vs 90%) is enough to surface them.

---

## Phase 4: Noise Floor

| Metric | Value |
|--------|-------|
| Total diffs | 0 |
| Added | 0 |
| Removed | 0 |
| Confidence changed | 0 |
| Top-100 turnover | 0.000 |

**Zero noise.** Confidence is a stored computed column, not sampled. Diffs are deterministic. This means ANY non-zero diff represents a real change -- there is no noise floor to contend with.

---

## Implications

### Diffing works, but top-k turnover is the wrong metric (for now)

The diff mechanism itself is fast, deterministic, and noise-free. It correctly detects additions, removals, and confidence changes. But top-100 turnover is useless when confidence is uniform -- it only detects changes when the new belief has HIGHER confidence than existing ones (i.e., locked corrections).

Once the Bayesian feedback loop creates confidence variance (Issue A from the consolidated findings), top-k turnover becomes meaningful. Until then, the useful diff outputs are:
- **Added beliefs** (always detected)
- **Locked belief changes** (always detected, always in top-k)
- **Confidence shifts** (only meaningful after feedback loop runs)

### Recommended use cases for diffing

1. **Session changelog:** "Since your last session, 12 beliefs were added, 2 corrections were recorded, 1 belief was superseded." This uses added/removed counts, not top-k turnover.
2. **Correction audit:** "These 3 corrections were recorded in the last week." Clean signal, no noise.
3. **Confidence drift** (future): Once feedback loop runs, diff can show "these beliefs gained confidence (used frequently) and these lost confidence (ignored)."

---

## Limitations

- Drift simulation used synthetic content at uniform priors. Real conversation would produce varied types and (eventually) varied confidence.
- The "in top-100" metric depends on confidence ranking, which is meaningless at uniform priors. A better metric (for future work) would be FTS5 rank for a specific query.
- Only 3 corrections tested. More subtle corrections (lower alpha) might not penetrate top-100.

---

## Files

- `exp65_hologram_diffing.py` -- experiment code
- `exp65_results.json` -- raw data
- `exp65_hologram_diffing_plan.md` -- original design
- `exp65_hologram_diffing_results.md` -- this file
