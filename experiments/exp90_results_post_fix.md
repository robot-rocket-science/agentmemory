# Exp 90: Post-Fix Validation Results

**Date:** 2026-04-19
**Database:** ~/.agentmemory/projects/2e7ed55e017a/memory.db (16,675 active beliefs)
**Context:** Re-running exp90_scoring_dynamics.py after v2.4.0 fixes (Fixes 1-5) to measure actual improvement.

## Before/After Comparison

| Metric | Pre-fix (commit 305e93b) | Post-fix (this run) | Change |
|---|---|---|---|
| Gini coefficient | 0.026 | 0.1476 | 5.7x improvement |
| Regime | (not recorded) | ACCUMULATION | Healthy |
| Conservation | (not recorded) | WEAKLY_DISSIPATIVE | Feedback reshaping distribution |
| Dominant cluster | 57.9% at 0.66 | 83.6% at 0.374 (low tier) | Cluster shifted to correct prior |
| Tier separation | Near-zero | 0.374 vs 0.925 (low vs locked) | 0.55 gap between tiers |

## Jacobian (unchanged -- mathematical constants)

| Operating Point | Conf | dC/dalpha | Used/10pp | Harm->50 |
|---|---|---|---|---|
| Agent FACT (0.66 cluster) | 0.655 | 0.1189 | 0.8 | 0.9 |
| Agent FACT (correct 0.375) | 0.375 | 0.3906 | 0.3 | 0.0 |
| User correction | 0.947 | 0.0055 | 18.1 | 8.5 |

Sensitivity ratio: 3.3x (beliefs at correct prior are 3.3x more responsive to feedback).

## Hamiltonian

| Component | Value |
|---|---|
| Kinetic energy (T) | 529.58 |
| Potential energy (V) | -7473.14 |
| Hamiltonian (H=T+V) | -6943.55 |
| Regime | ACCUMULATION |
| Conservation | WEAKLY_DISSIPATIVE |

## Tier Breakdown

| Tier | Count | Avg Confidence |
|---|---|---|
| locked/correction (>=0.9) | 1,456 | 0.925 |
| high (0.7-0.9) | 969 | 0.788 |
| medium (0.5-0.7) | 207 | 0.579 |
| low (0.3-0.5) | 13,942 | 0.374 |
| very_low (<0.3) | 101 | 0.231 |

## Diagnosis

- Gini at 0.148 is just below the 0.15 "adequate" threshold (was 0.026 pre-fix)
- Population is no longer uniform -- clear tier separation exists
- 83.6% of beliefs are in the low tier at the correct prior (0.374), ready for feedback-driven differentiation
- Regime is ACCUMULATION (healthy), not QUIESCENT (frozen)
- Conservation is WEAKLY_DISSIPATIVE: feedback IS reshaping the distribution

## Verdict

**Fixes worked.** The population shifted from a frozen uniform distribution (Gini 0.026) to a differentiated population accumulating confidence (Gini 0.148). The remaining gap below 0.15 is expected -- the feedback loop needs more production cycles to further spread the distribution. Exp 91 (multi-axis scoring) may help by adding more dimensions for differentiation.

## Fixes Applied (v2.4.0)

1. **Fix 1: Type-aware recalibration** -- recalibrate_scores() resets inflated priors
2. **Fix 2: Source-type decay** -- agent_inferred gets 0.5x half-life modifier
3. **Fix 3: First-signal amplification** -- 3x weight on first feedback event
4. **Fix 4: UCB exploration bonus** -- under-retrieved beliefs get surfaced
5. **Fix 5: Asymmetric feedback** -- harmful=-2.0, weak=-0.6, ignored=-0.1
