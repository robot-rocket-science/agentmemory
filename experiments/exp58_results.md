# Experiment 58: Decay Half-Life Calibration -- Results

**Date:** 2026-04-10
**Status:** Complete
**Predecessor:** Exp 57 (decay-only scores 100% on case study scenarios)

---

## Summary

Content-aware decay with short half-lives (1 day across all types) improves correction prevention from 16.7% to 50% at top-5, and from 63.3% to 76.7% at top-15. The improvement comes entirely from suppressing unlocked decisions below locked ones via aggressive decay, not from fine-grained type differentiation.

## Results

| Config | Top-5 | Top-10 | Top-15 |
|---|---|---|---|
| No decay (baseline) | 16.7% | 30.0% | 63.3% |
| Combined best (1d all types) | 50.0% | 66.7% | 76.7% |

## Key Findings

1. **Locked beliefs are the dominant signal.** 44/173 decisions (25%) are locked (revisable="No"). When decay suppresses everything else, locked beliefs rise to the top. The correction prevention improvement is almost entirely from this mechanism.

2. **Half-life value is insensitive.** 2x and 0.5x variants produce identical rates. What matters is the presence of decay (any half-life), not the specific value. This makes sense: at a 13-day timeline, even a 60-day half-life provides meaningful separation between locked (1.0) and unlocked (~0.87) beliefs.

3. **Per-type differentiation is minimal.** Sweeping one content type while holding others at "never" shows no variation across half-life candidates. The types don't have enough temporal separation in a 13-day window for type-specific decay to matter.

4. **gcp_primary cluster is unreachable.** D112 has no milestone link and gets the median date, placing it after some corrections. Decay cannot help when the correct belief doesn't exist yet at correction time. This is a retrieval problem, not a scoring problem.

5. **agent_behavior cluster achieves 100%.** D157 and D188 are behavioral beliefs that score high regardless of decay settings (either locked or matched by FTS5).

## Implications

- Decay half-lives don't need fine-grained calibration at this project scale (13 days, 173 decisions). Any reasonable decay is sufficient.
- The real value of decay is binary: locked beliefs score 1.0, everything else scores less. The gradient within "less" doesn't matter much.
- At larger scale (10K+ beliefs over months), type-specific half-lives will likely matter more as the temporal spread increases.
- Decay is necessary but not sufficient: 50% at top-5 means half the corrections are still not prevented by scoring alone. Retrieval (FTS5+HRR) must narrow candidates first.

## What This Means for Architecture

Decay scoring should be implemented with the following priorities:
1. **Locked beliefs immune** (score = 1.0) -- this is the highest-leverage mechanism
2. **Superseded beliefs suppressed** (score = 0.01)
3. **Content-aware decay as a tiebreaker** -- use default half-lives (evidence=14d, context=3d, procedure=21d, rationale=30d) but don't over-invest in calibrating them
4. **The real work is in retrieval** -- decay re-ranking is a post-retrieval polish, not the primary mechanism
