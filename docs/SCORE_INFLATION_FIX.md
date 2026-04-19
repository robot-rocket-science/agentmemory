# Score Inflation Fix Plan

**Branch:** fix/bayesian-score-inflation
**Priority:** Emergency release
**Date:** 2026-04-18

## Bug Description

The Bayesian scoring system is non-functional due to inflated alpha priors.

**Root cause:** The scanner/ingest pipeline inserts agent-inferred beliefs at alpha=9.5 instead of the Jeffreys prior (alpha=0.5, beta=0.5) defined in scoring.py. This means every belief starts at ~95% confidence regardless of actual evidence.

**Impact:**
- 90% of beliefs (14,101) cluster at 90-95% confidence
- Thompson sampling spread is 0.48 (vs 1.0 at Jeffreys) -- cannot discriminate
- A single "used" feedback event moves confidence by +0.005 (negligible)
- A belief needs 9 "ignored" events to drop from 90% to 50%
- Zero beliefs below 40% confidence in the entire DB
- The feedback loop (+22% MRR, Exp 66) is real but operating in a narrow band

**Verified data:**
- 9,745 factual beliefs inserted at alpha=9.5 (62% of DB)
- Median alpha across all beliefs: 9.5
- p75 alpha: 9.5, p90: 10.0 -- the distribution is a spike, not a curve
- Only 1 belief at its correct type prior in the entire DB

## Fix Plan

### Phase 1: Diagnostic baseline (before any changes)

1. Write `tests/validation/test_score_inflation.py` capturing current state
2. Measure: confidence distribution, Thompson spread, feedback impact
3. These tests document the bug and will verify the fix

### Phase 2: Fix insertion defaults

4. Fix `ingest.py` -- agent-inferred beliefs must use Jeffreys prior (0.5, 0.5)
5. Fix `scanner.py` -- same: agent-inferred beliefs use type-appropriate priors
6. Fix any other insertion paths that inflate alpha
7. Verify: new beliefs inserted at correct priors

### Phase 3: Deflation pass for existing data

8. Add `recalibrate()` to store.py -- proportional deflation for agent-inferred beliefs
9. Deflation formula: `new_alpha = alpha * 0.2` for agent-inferred at scanner default
10. User-sourced beliefs (user_corrected, user_stated) are NOT touched
11. Locked beliefs are NOT touched
12. Wire into CLI as `agentmemory recalibrate` command
13. Wire into MCP as `recalibrate` tool

### Phase 4: Verification

14. Run deflation on test DB, verify confidence distribution is healthy
15. Run existing test suite -- all 861 tests must still pass
16. Run retrieval quality check -- verify FTS5 + scoring still produces sensible rankings
17. Verify Thompson sampling now has discriminative power

### Phase 5: Feedback audit trail

18. Ensure feedback events are logged (the test_results table issue)
19. Add feedback_count / ignore_count tracking per belief for audit

## Acceptance criteria

- [ ] Agent-inferred beliefs start at Jeffreys prior (0.5, 0.5)
- [ ] Post-deflation confidence distribution spans 40-100% (not 90-95%)
- [ ] Thompson sampling spread > 0.8 for Jeffreys-prior beliefs
- [ ] A single "used" event moves confidence by > 0.10 for fresh beliefs
- [ ] All existing tests pass
- [ ] User-sourced and locked beliefs are untouched by deflation
- [ ] Retrieval quality does not regress (search results still relevant)

## Risk assessment

- **Deflation too aggressive:** Beliefs that were correctly high-confidence get demoted. Mitigated by only deflating agent-inferred beliefs and preserving user-sourced.
- **Retrieval regression:** Scoring changes could reorder search results. Mitigated by verifying against known-good queries.
- **Benchmark impact:** Benchmark results were achieved with inflated scores. If deflation changes retrieval quality, benchmark numbers may change. This is acceptable -- the current numbers were achieved with a broken scorer.
