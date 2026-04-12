# Session: System Audit, Bug Fixes, and Validation Experiment Design

**Date:** 2026-04-11
**Scope:** Full design-vs-reality audit, 6 code fixes, 5 validation experiments designed, 3 stale docs updated

---

## What Was Done

### Bug Fix: feedback_given Migration (CRITICAL)
- **File:** `src/agentmemory/store.py`
- **Problem:** `_migrate_sessions()` added 5 columns for existing DBs but missed `feedback_given`. Every `search()` call crashed on DBs created before that column existed.
- **Crash path:** `search()` -> `_process_auto_feedback()` -> `increment_session_metrics(feedback_given=count)` -> SQL error
- **Fix:** Added `"feedback_given"` to the migration list.
- **Commit:** `f62ad0e`

### Fix: Auto-lock Correction Backfill
- **File:** `src/agentmemory/store.py`
- **Problem:** 2,592 correction-type beliefs from bulk ingestion were `locked=False`. Only `remember()` and `correct()` set `locked=True`.
- **Fix:** Added `backfill_lock_corrections()` method and `_migrate_beliefs()` called from `_init_schema()`. Runs once on DB open.

### Fix: Differentiated Type Priors
- **File:** `src/agentmemory/classification.py`
- **Problem:** All types (REQUIREMENT, CORRECTION, PREFERENCE, FACT, ASSUMPTION) had identical (9.0, 1.0) = 90% prior. Thompson sampling could not differentiate them.
- **Fix:** Spread priors:
  - REQUIREMENT: (9.0, 0.5) = 94.7%
  - CORRECTION: (9.0, 0.5) = 94.7%
  - PREFERENCE: (7.0, 1.0) = 87.5%
  - FACT: (3.0, 1.0) = 75.0%
  - ASSUMPTION: (2.0, 1.0) = 66.7%
  - DECISION: (5.0, 1.0) = 83.3% (unchanged)
  - ANALYSIS: (2.0, 1.0) = 66.7% (unchanged)
- Also updated `classify_sentences_offline` to look up from TYPE_PRIORS instead of hardcoding.

### Fix: Wire Scoring Components
- **File:** `src/agentmemory/scoring.py`
- **Problem:** `score_belief()` used only decay + lock_boost + Thompson sampling. Ignored `_TYPE_WEIGHTS`, `_SOURCE_WEIGHTS`, and `recency_boost()` which all existed in the same module.
- **Fix:** Normal belief score now: `type_w * source_w * sample * decay * recency`. Locked beliefs unchanged: `boost * sample`.

### Fix: FTS5 Top-K Increase
- **File:** `src/agentmemory/retrieval.py`
- **Problem:** Default `top_k=30` was 0.2% coverage at 15K beliefs.
- **Fix:** Increased default to `top_k=50`. Removed hardcoded `top_k=30` in `cli.py`.
- **Note:** User reverted retrieval.py change; top_k remains at 30 pending exp70 validation.

### Test Fixes
- **File:** `tests/test_server.py`, `tests/test_retrieval.py`
- Updated to match new locking workflow (remember/correct no longer auto-lock per CLAUDE.md change).

### Documentation Updates
- **REQUIREMENTS.md:** Updated 8 requirement statuses from "Not started" to "Implemented" or "Verified" with evidence.
- **PIPELINE_STATUS.md:** User reverted; original preserved.
- **TODO.md:** User reverted; original preserved.

---

## Validation Experiments Designed (Exp 66-70)

| Exp | Question | Method | Success Criteria |
|-----|----------|--------|-----------------|
| 66 | Does feedback loop improve retrieval? | 50-round simulation with used/ignored feedback | MRR improves >= 10% over 50 rounds |
| 67 | Impact of locking all corrections? | Before/after MRR on copied DB | Coverage or MRR improves |
| 68 | Do spread priors make scoring meaningful? | Compare score variance and MRR with old vs new priors | Score variance increases, MRR does not decrease |
| 69 | Does recency_boost help new beliefs surface? | Insert 20 new corrections, compare top-10 with/without boost | New beliefs appear in top-10 with boost, not without |
| 70 | Does increasing top_k improve coverage? | Run retrieve at K=30, 50, 75, 100 | Coverage improves at K=50 without exceeding budget |

---

## Test Results

**216 tests passing, 1 skipped** after all fixes.

---

## Key Findings from Audit

### What's Working
- SQLite + WAL persistence, observation immutability, locked beliefs, FTS5 search, type-aware compression, HRR vocabulary bridge, correction detection, MCP server (10 tools), project onboarding scanner, temporal decay + lock boost

### What's Not Working
1. Search was broken (fixed: feedback_given migration)
2. Feedback loop has never fired in production (auto-feedback now wired but unvalidated)
3. 2,592 unlocked corrections (fixed: backfill migration)
4. Uniform type priors (fixed: differentiated)
5. Unused scoring components (fixed: wired in)

### Design Gaps (not built)
- Output gating (locked beliefs inform but don't block)
- Triggered beliefs automation (15 designs simulated, not wired)
- Contradiction detection (no semantic conflict alerting)
- L1 behavioral layer (implementation skips L0 to L2)

### Research Challenges to Design (Exp 62-65)
1. Global scoring without query = noise (FTS5 is the real signal)
2. Pre-prompt compilation loses to on-demand retrieval
3. Multi-layer extraction is regressive at scale
4. New beliefs can't surface without recency boost (now wired)
5. FTS5 K=30 too low at 15K (pending exp70 validation)
