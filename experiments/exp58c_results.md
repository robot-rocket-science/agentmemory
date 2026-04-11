# Experiment 58c: Hour-Scale Decay Calibration -- Results

**Date:** 2026-04-10
**Status:** Complete
**Predecessors:** Exp 58 (13d, insensitive), Exp 58b (4mo, evidence decay load-bearing)

---

## Summary

Hour-scale decay does not improve the 73% correction prevention ceiling (that's a retrieval/existence problem, not a scoring problem). But it **solves CS-005 (maturity inflation)**: fast-sprint outputs score 0.273 vs locked constraints at 0.804 by next morning. Velocity-scaled decay (half-life * 0.1 for >10 items/hour) is the strongest version.

## Correction Prevention Results

| Strategy | Top-5 | Top-10 | Top-15 |
|---|---|---|---|
| Flat 0.5h | 53.3% | 73.3% | 80.0% |
| Flat 4h | 53.3% | 73.3% | 80.0% |
| Flat 24h | 53.3% | 73.3% | 80.0% |
| Flat 720h (1mo) | 53.3% | 73.3% | 80.0% |
| Type-aware | 53.3% | 73.3% | 80.0% |
| Velocity-scaled | 53.3% | 73.3% | 80.0% |

**All identical.** The target decisions are locked (score=1.0). Decay speed is irrelevant for correction prevention because the mechanism is lock immunity, not decay.

## CS-005 Simulation (Primary Finding)

Fastest milestone: M006-WZ8EAF, velocity = 22 decisions/hour.

| Belief group | Score at milestone_end + 12h |
|---|---|
| Locked constraints | 0.804 |
| Fast-sprint unlocked | 0.273 |
| Fast-sprint velocity-scaled | ~0.0 |

**Hypothesis confirmed.** A new agent reading decay scores would see fast-sprint outputs as substantially lower-confidence than locked constraints. This is the calibrated picture CS-005 demands: "3 locked findings you can trust, 8 unlocked findings from a fast sprint that need validation."

## Velocity Distribution

| Velocity class | Threshold | Decisions | Scale factor |
|---|---|---|---|
| Very fast | >10 items/hr | 20 | 0.1 |
| Moderate | 5-10/hr | 33 | 0.5 |
| Medium | 2-5/hr | 19 | 0.8 |
| Deep | <2/hr | 146 | 1.0 |

## Why 73% Is the Ceiling for Decay

The 27% failures (8 of 30 correction events) break down into:
- **Decisions not yet created at correction time** (score=0.0): no scoring function can surface a belief that doesn't exist. These require the correction detection pipeline (Exp 1 V2: 92%) to capture the correction and create the belief.
- **Correct decisions not in retrieval set**: decay can only re-rank what was retrieved. If FTS5+HRR doesn't return the correct belief, temporal scoring can't help.

These are problems at other layers of the pipeline (extraction, correction detection, retrieval), not the scoring layer.

## Architecture Implications

1. **Hour-scale decay is the right granularity for velocity signaling.** Day-scale decay (Exp 58b) works for cross-session separation but can't distinguish a 4-hour sprint from an 8-hour deep session.

2. **Velocity-scaled half-lives are the strongest mechanism for CS-005.** Items from fast sprints (>10/hr) get 0.1x half-life, decaying 10x faster than deep-work items. This is a direct proxy for "how much scrutiny did this finding receive?"

3. **Decay scoring is complete.** The stack is: locked immunity (1.0) + supersession penalty (0.01) + content-type decay + velocity scaling. No further tuning will improve correction prevention beyond 73% -- that ceiling is set by other pipeline layers.

4. **The 27% gap must be attacked at other layers:**
   - Correction detection (Exp 1 V2: 92%) for beliefs that don't exist yet
   - Retrieval improvements (FTS5+HRR) for beliefs not in the result set
