# Confidence Differentiation Fix (v2.4.0)

## Problem

57.9% of 16,591 active beliefs cluster at confidence=0.66 (alpha=1.9, beta=1.0).
Gini coefficient: 0.026 (near-zero diversity). Thompson sampling degenerates to
random selection within this cluster. The feedback loop has 3.3x lower sensitivity
at the plateau than at the correct prior.

## Root Causes

1. **Incomplete recalibration:** Original recalibrate_scores() applied uniform
   deflation (alpha * 0.2) instead of type-specific priors. Left 9,416 beliefs
   at alpha=1.9 instead of correct values (FACT=0.6, REQ=1.8, PREF=1.4).

2. **Offline classifier funneling:** The "because" keyword triggers ANALYSIS
   classification (alpha=2.0, beta=1.0 = 0.667). Technical text is saturated
   with causal language, so most onboarded content becomes ANALYSIS.

3. **Diminishing returns in Beta mean:** alpha/(alpha+beta) converges
   logarithmically. After 20 "used" events, each adds only +0.004. Early
   feedback has 10x more impact than late feedback, but most beliefs never
   receive enough events to differentiate.

4. **No population-aware normalization:** Nothing adjusts beliefs relative
   to the distribution. If 60% cluster at one value, nothing corrects that.

## Fix Components (ordered by implementation)

### Fix 1: Type-Aware Recalibration (DONE, committed)

Reset alpha=1.9 beliefs to correct type-specific priors. Already in store.py.
Needs to be APPLIED to production DB.

Expected: Gini 0.026 -> 0.20

### Fix 2: Source-Type Decay Modifiers

Agent-inferred beliefs decay faster than user-sourced beliefs of the same type.
Implemented in scoring.py decay_factor().

```
SOURCE_DECAY_MODIFIER = {
    "user_corrected": 2.0,   # 2x half-life (slower decay)
    "user_stated": 1.5,
    "agent_inferred": 0.3,   # 0.3x half-life (fast decay)
}
effective_half_life = base_half_life * source_modifier
```

Agent-inferred FACT: effective half-life = 336h * 0.3 = 100h (~4 days)
User correction: effective half-life = 1344h * 2.0 = 2688h (~112 days)
After 30 days: agent fact at ~0.001, user correction at ~0.85.

Expected: Gini +0.10-0.15 on aged corpus

### Fix 3: First-Signal Amplification (FSRS-inspired)

The first feedback event applies 3x weight. Subsequent events use normal weight.
Implemented in store.py update_confidence().

```
weight_multiplier = 3.0 if belief.feedback_count == 0 else 1.0
effective_weight = weight * weight_multiplier
```

A belief's first "used" feedback moves it from 0.375 to 0.531 (+15.6pp) instead
of 0.375 to 0.438 (+6.3pp). One event creates meaningful separation.

Expected: faster initial differentiation, +0.05-0.10 Gini

### Fix 4: UCB Exploration Bonus

Add exploration bonus to score_belief() that boosts under-retrieved beliefs.

```
exploration_bonus = C * sqrt(ln(total_retrievals) / max(1, belief_retrievals))
```

C = 0.1 (tunable). Beliefs retrieved 0 times get maximum bonus. Beliefs
retrieved 100 times get near-zero bonus. Ensures all beliefs eventually surface.

Expected: better coverage, indirect Gini improvement via more feedback events

### Fix 5: Asymmetric Feedback (SM-2-inspired)

Negative feedback applies 2x the weight of positive feedback. A single "harmful"
event is twice as impactful as a single "used" event.

```
VALENCE_MAP = {
    "confirmed": +1.0,
    "used": +0.5,
    "ignored": -0.1,   # was 0.0 (legacy path did beta += 0.1)
    "weak": -0.6,      # was -0.3
    "harmful": -2.0,   # was -1.0
}
```

Expected: faster separation when negative evidence arrives

## Validation Plan

Before implementing, run validation scripts to verify assumptions:

1. `validate_recalibration.py` -- simulate recalibration on a copy of the DB,
   measure Gini before/after, verify no data corruption
2. `validate_decay_modifiers.py` -- compute projected confidence distribution
   at T+7d, T+30d, T+90d with new decay rates
3. `validate_first_signal.py` -- simulate 100 feedback events with 3x first
   weight, verify distribution spread
4. `validate_ucb_bonus.py` -- compute UCB scores for all beliefs, verify
   under-retrieved beliefs get meaningful boost
5. `validate_asymmetric.py` -- simulate feedback scenarios, verify beliefs
   separate faster with 2x negative weight

## Success Criteria

- [ ] Gini >= 0.20 after recalibration (currently 0.026)
- [ ] Gini >= 0.30 after all fixes applied
- [ ] No single confidence bucket contains > 30% of beliefs
- [ ] Thompson sampling produces distinguishable rankings (test: sample
      1000 pairs from the same type, measure P(different rank) > 0.8)
- [ ] Existing tests still pass (872+)
- [ ] Benchmark scores not degraded (re-run contamination checks)

## Release Plan

- Branch: fix/confidence-differentiation (or continue fix/confidence-recalibration)
- Version: v2.4.0
- Commits: one per fix component, atomic and testable
- Tests: add validation tests for each component
- Benchmarks: re-run Exp 90 after each fix to measure Gini progression

## Prior Art References

- FSRS (Free Spaced Repetition Scheduler): first-signal difficulty estimation
- UCB1 (Auer et al., 2002): exploration bonus for under-sampled arms
- Dynamic Prior Thompson Sampling (arXiv 2602.00943, Jan 2026): cold-start priors
- SM-2 (SuperMemo): asymmetric ease factor updates
- Noisy-OR (KG confidence aggregation): multi-evidence combination
- BM25 IDF: corpus-level rarity signal for content differentiation
