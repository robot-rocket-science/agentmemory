# Pipeline Status: Design vs Reality

**Date:** 2026-04-11
**Purpose:** Honest assessment of what exists, what's validated, and what's missing.

---

## The Full Pipeline (Design vs Reality)

```
STAGE                          STATUS          EVIDENCE
=====                          ======          ========
1. Conversation capture        WORKING         Hooks active, conversation-logger.sh
   (hooks -> JSONL)                            installed, JSONL batch ingest works

2. Sentence extraction         WORKING         extract_sentences() in extraction.py
   (dumb split, no LLM)                       Strips code, markdown, URLs, splits on
                                               punctuation. ~7.8 sentences/turn.

3. LLM classification          WORKING         classify_sentences() in classification.py
   (type + persist/ephemeral)                  Haiku 99% accuracy (Exp 50), $0.005/session
                                               Offline fallback at 36% accuracy

4. Bayesian prior assignment   WORKING         TYPE_PRIORS in classification.py
   (type -> Beta(a,b))                         Differentiated priors (2026-04-11):
                                               REQ/CORR 94.7%, PREF 87.5%, FACT 75%, ASSM 66.7%

5. Belief graph insertion      WORKING         MemoryStore in store.py. 9-table SQLite schema.
   (SQLite + FTS5 + edges)                     Content-hash dedup, evidence linking,
                                               SUPERSEDES edges, locked flag. 176+ tests passing.

6. FTS5 + HRR retrieval       WORKING          retrieve() in retrieval.py
   (query -> candidates)                       FTS5 BM25 + HRR vocabulary bridge
                                               Exp 56: 100% coverage (13/13) at K=50

7. Temporal re-ranking         WORKING          score_belief() in scoring.py
   (decay + lock boost +                       Type/source weights, recency boost,
    type/source weights)                       Thompson sampling, lock boost
                                               Exp 60: MRR 0.867 with LOCK_BOOST_TYPED

8. Type-aware compression      WORKING          compress_belief() + pack_beliefs()
   (full -> compressed)                        in compression.py
                                               Exp 42: 55% savings, zero retrieval loss

9. Context injection           WORKING          SessionStart hook loads locked beliefs
   (hooks inject beliefs)                      via get_locked() MCP tool
                                               Exp 36: 0% violation rate

10. Correction detection       WORKING          detect_correction() in correction_detection.py
    (detect user corrections)                  V2: 92% accuracy, 7 signal types
                                               Auto-locked on detection (2026-04-11 fix)

11. Feedback loop              PARTIALLY BUILT  Auto-feedback in server.py
    (test outcomes -> conf)                    record_test_result() exists and is called
                                               by _process_auto_feedback() after each search.
                                               NOT YET VALIDATED: Exp 66 will test whether
                                               feedback improves retrieval quality over time.

12. Triggered beliefs          SIMULATED        5/5 case study failures prevented (Exp 51)
    (meta-cognitive checks)                    15 TBs designed, not automated

13. Output gating              NOT BUILT        No code path blocks violating agent output
    (block violating output)                   Locked beliefs inform but don't enforce
```

---

## MCP Server Tools (10 registered)

| Tool | Status | Notes |
|------|--------|-------|
| search | WORKING | FTS5 + HRR + scoring + compression. K=50 default. |
| remember | WORKING | Creates locked high-confidence belief |
| correct | WORKING | Creates locked correction, supersedes existing |
| observe | WORKING | Raw observation without belief creation |
| ingest | WORKING | Full pipeline: extract -> classify -> store |
| onboard | WORKING | Project scanner with 9 extractors |
| status | WORKING | Memory system health check with session metrics |
| get_locked | WORKING | Returns all locked beliefs for context injection |
| feedback | WORKING | Records test result, updates Bayesian confidence |
| settings | WORKING | View/update agentmemory config |

---

## Production Modules (16 in src/agentmemory/)

| Module | LOC | Purpose |
|--------|-----|---------|
| store.py | ~900 | SQLite MemoryStore with WAL mode, FTS5, migrations |
| server.py | ~600 | MCP server (FastMCP), auto-feedback loop, session tracking |
| retrieval.py | ~180 | Full pipeline: FTS5 + HRR + scoring + compression |
| ingest.py | ~270 | End-to-end: extraction -> classification -> store |
| scoring.py | ~225 | Decay, lock boost, Thompson sampling, type/source weights, recency |
| classification.py | ~360 | LLM (Haiku) + offline classifiers, Bayesian priors |
| extraction.py | ~100 | Sentence extraction with noise stripping |
| correction_detection.py | ~150 | Zero-LLM correction detector, 92% accuracy |
| compression.py | ~120 | Type-aware compression, token budget packing |
| hrr.py | ~300 | Holographic Reduced Representations for graph encoding |
| scanner.py | ~680 | Project onboarding: git, docs, code, directives |
| cli.py | ~800 | CLI: setup, onboard, stats, health, search, etc. |
| config.py | ~100 | JSON configuration management |
| commit_tracker.py | ~150 | Deterministic commit status checker |
| models.py | ~150 | Dataclass domain models |
| __init__.py | ~20 | Public API exports |

---

## Known Issues (2026-04-11)

### Fixed This Session
- **feedback_given migration bug** -- `_migrate_sessions()` was missing the `feedback_given` column, crashing search on existing DBs. Fixed.
- **Unlocked corrections** -- 2,592 correction-type beliefs from bulk ingestion were not locked. Migration added to auto-lock on DB open.
- **Uniform type priors** -- All types started at 90% confidence. Differentiated: REQ/CORR 94.7%, PREF 87.5%, FACT 75%, ASSM 66.7%.
- **FTS5 K=30 too low** -- Default increased to K=50.
- **Unused scoring components** -- _TYPE_WEIGHTS, _SOURCE_WEIGHTS, and recency_boost() wired into score_belief().

### Open Issues
- **Feedback loop unvalidated** -- Auto-feedback fires but we don't know if it improves retrieval. Exp 66 will test.
- **Output gating not built** -- Locked beliefs inform but don't block violating output.
- **Triggered beliefs not automated** -- 15 designs simulated, not wired to events.
- **Contradiction detection absent** -- No semantic conflict alerting on insertion.
- **L1 behavioral layer missing** -- Design has L0/L1/L2/L3; implementation skips L1.

### Research Findings That Challenge the Design (Exp 62-65)
1. Global scoring without query produces Thompson sampling noise. FTS5 is the real signal.
2. Pre-prompt compilation (23.1% coverage) loses to on-demand retrieval (69.2%). Don't build it.
3. Multi-layer extraction is regressive at scale (16K nodes worse than 586). More nodes != better.
4. New beliefs struggle to surface at scale without recency boost. Now wired (2026-04-11).
5. FTS5 K=30 was 0.2% coverage at 15K beliefs. Now K=50.

---

## Requirements Coverage Summary

See REQUIREMENTS.md for full details. Quick status:

| Status | Count | Requirements |
|--------|-------|-------------|
| Verified/Passing | 6 | REQ-003, REQ-007, REQ-009, REQ-010, REQ-017, REQ-018 |
| Implemented (needs formal verification) | 8 | REQ-001, REQ-005, REQ-006, REQ-012, REQ-013, REQ-019, REQ-020, REQ-021 |
| Partially implemented | 4 | REQ-002, REQ-008, REQ-011, REQ-027 |
| Not started | 8 | REQ-004, REQ-014, REQ-015, REQ-016, REQ-023, REQ-024, REQ-025, REQ-026 |
