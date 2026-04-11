# Experiment 58b: Decay Half-Life Calibration at Full Scale -- Results

**Date:** 2026-04-10
**Status:** Complete
**Predecessor:** Exp 58 (13-day scale, insensitive), Exp 57 (decay-only 100%)

---

## Summary

At 4-month scale (218 decisions, Dec 2025 - Apr 2026), decay calibration shows meaningful differentiation that was invisible at 13 days.

**Combined best (1d all types): top5=53%, top10=73%, top15=80%** vs baseline (no decay): top5=13%, top10=13%, top15=53%.

Correction prevention improves 4x at top-5 and 5.5x at top-10 with aggressive decay.

## Results

| Config | Top-5 | Top-10 | Top-15 |
|---|---|---|---|
| No decay (baseline) | 13.3% | 13.3% | 53.3% |
| Combined best (1d all types) | **53.3%** | **73.3%** | **80.0%** |

## Key Findings vs Exp 58

| Finding | Exp 58 (13 days) | Exp 58b (4 months) |
|---|---|---|
| Half-life sensitivity | Insensitive | **EVIDENCE type matters**: finite vs never changes top10 from 13% to 57% |
| Baseline correction prevention (top-10) | 30% | 13% (harder problem at scale) |
| Best correction prevention (top-10) | 67% | **73%** |
| Locked/unlocked separation at 1d | N/A | 0.946 (strong) |
| Locked/unlocked separation at never | N/A | 0.047 (no separation) |
| Superseded ordering | N/A | 7/7 correct at all half-lives |
| Inherited vs recent (7-14d) | N/A | Recent 3x higher than inherited |

## What Changes at Scale

1. **EVIDENCE decay is load-bearing.** At 13 days, all decisions are so close in time that decay factors range 0.85-1.0 (minimal separation). At 4 months, "inherited" decisions from optimus-prime (Dec 2025) are 90+ days old -- their decay factor at 14d half-life is 0.01, effectively removing them from competition. This lets recent, relevant decisions rank higher.

2. **The baseline is harder.** With 218 decisions (vs 173), there's more noise competing for the top-K slots. Baseline top-10 drops from 30% to 13%. Decay is more valuable because there's more to suppress.

3. **Supersession works cleanly.** All 35 archived decisions score 0.01 and rank below their replacements. The flat penalty is sufficient -- no need for chain-aware scoring.

4. **Inherited decisions need decay.** Without decay, the 21 "inherited" decisions from optimus-prime compete equally with recent decisions. With 7-14d half-life, they score 3x lower, which is appropriate since many are stale (e.g., old signal model configs, dead approach parameters).

5. **Irreducible failures exist.** 3 corrections reference decisions that hadn't been created yet at correction time (score=0.0). No scoring function can surface a belief that doesn't exist yet. These require the correction detection pipeline (Exp 1 V2: 92%) to capture the correction and create the belief.

## Architecture Implications

1. **Decay half-lives matter at month+ scale.** The Exp 58 finding ("insensitive") was an artifact of the 13-day window. At realistic project timescales, content-type-specific decay provides meaningful signal.

2. **Recommended defaults:** 
   - Constraints: never (locked beliefs are immune)
   - Evidence: 14-30 days (stale experimental results fade)
   - Context: 3-7 days (activities and WIP fade fast)
   - Procedures: 21-30 days (protocols are semi-stable)
   - Rationale: 30-60 days (reasoning is long-lived)

3. **The exact value still matters less than the presence of decay.** 1d and 7d both outperform "never" by large margins. The gradient between 7d and 30d is small. Implement with reasonable defaults and don't over-invest in tuning.

4. **Decay + locked immunity + supersession penalty = the complete temporal scoring stack.** No structural time (TEMPORAL_NEXT) needed for scoring. Confirmed at both 13-day and 4-month scales.
