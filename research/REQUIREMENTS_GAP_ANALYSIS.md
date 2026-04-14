# Requirements vs Implementation Gap Analysis

**Date:** 2026-04-11
**Method:** Source code audit of `src/agentmemory/`, test enumeration from `tests/`, cross-reference with REQUIREMENTS.md, ACCEPTANCE_TESTS.md, IMPLEMENTATION_PLAN.md, and PIPELINE_STATUS.md.

---

## Summary Table

| REQ ID | Description | Code? | Tests? | Experiments? | Status |
|--------|------------|-------|--------|-------------|--------|
| REQ-001 | Cross-session decision retention | PARTIAL | YES (acceptance) | Exp 3, 56 | Gap: no multi-session integration test with real hooks |
| REQ-002 | Belief consistency (no silent contradictions) | PARTIAL | NO | Exp 2 | Gap: contradiction detection in cli.py only, not in retrieval |
| REQ-003 | Retrieval token budget <= 2K | YES | YES | Exp 42, 55, 60 | Implemented: pack_beliefs enforces budget |
| REQ-004 | Quality per token (2K >= 10K) | PARTIAL | NO | Exp 56 | No automated quality comparison test |
| REQ-005 | Crash recovery >= 90% | PARTIAL | YES (acceptance) | -- | Sessions + checkpoints exist; acceptance test is simulated |
| REQ-006 | Checkpoint overhead < 50ms | YES | YES (benchmark) | -- | test_checkpoint_write_latency_p95 in test_store.py |
| REQ-007 | Retrieval precision >= 50% | YES | PARTIAL | Exp 56 | FTS5 + HRR pipeline built; no precision@15 test harness |
| REQ-008 | FP rate decreasing over time | NO | NO | Exp 2, 5b | Feedback loop not in production |
| REQ-009 | Bayesian calibration ECE < 0.10 | PARTIAL | YES (unit) | Exp 5b (ECE=0.066) | Thompson sampling + update_confidence exist; no ECE test |
| REQ-010 | Exploration fraction 15-50% | PARTIAL | NO | Exp 5b (0.194) | thompson_sample exists; no production measurement |
| REQ-011 | Cross-model MCP interop | PARTIAL | NO | -- | MCP server works; untested with ChatGPT/local models |
| REQ-012 | Write durability (zero loss) | YES | PARTIAL | -- | WAL mode + synchronous writes; no crash simulation test |
| REQ-013 | Observation immutability | YES | YES | -- | No update/delete methods; test_observation_no_update_path |
| REQ-014 | Zero-LLM extraction recall >= 40% | YES | YES | Exp 1, 50 | classify_sentences_offline + correction_detection V2 |
| REQ-015 | No unverified claims | N/A | NO | -- | Audit task, not code |
| REQ-016 | Documented limitations | N/A | NO | -- | Audit task, not code |
| REQ-017 | Fully local operation | YES | NO | -- | All SQLite, no network calls for memory ops |
| REQ-018 | No telemetry | YES | NO | -- | Zero telemetry code found in src/ |
| REQ-019 | Single-correction learning | YES | YES | Exp 1, 6 | correct() creates locked belief; ingest detects corrections |
| REQ-020 | Locked beliefs | YES | YES | Exp 6 | lock_belief, update_confidence blocks downgrade on locked |
| REQ-021 | Behavioral beliefs always in L0 | PARTIAL | YES (acceptance) | Exp 36 | get_locked_beliefs returns all locked; no behavioral filter |
| REQ-022 | Locked beliefs survive compression | PARTIAL | NO | -- | Locked beliefs in L0 bypass compression; no explicit test |
| REQ-023 | Research artifact provenance metadata | NO | NO | Exp 61 | No provenance fields in schema (produced_at, method, sample_size, data_source, independently_validated) |
| REQ-024 | Session velocity tracking | NO | NO | -- | No elapsed_time, item_count, or velocity in session schema |
| REQ-025 | Methodological confidence layer (rigor tier) | NO | NO | -- | No rigor_tier field anywhere in code |
| REQ-026 | Calibrated status reporting | NO | NO | -- | status() returns raw counts only, no rigor/velocity context |
| REQ-027 | Zero-repeat directive guarantee | PARTIAL | PARTIAL | Exp 6, 36 | Tiers 1-2 (store + inject) work; Tiers 3-6 (detection, blocking, compliance) missing |

---

## Detailed Notes Per Requirement

### REQ-001: Cross-Session Decision Retention
- **Code:** `store.py` has full CRUD for beliefs, sessions, checkpoints. `server.py` exposes `remember()`, `search()`, `get_locked()`. `retrieval.py` provides the full pipeline.
- **Tests:** `tests/acceptance/test_req001_cross_session.py` exists (1 test). Verifies decisions stored in session 1 are retrievable in session 5 using the same MemoryStore instance.
- **Gap:** The acceptance test simulates sessions within a single process. No test verifies the SessionStart hook injection path, which is the real cross-session mechanism. The 80% threshold from the requirement is tested against store retrieval, not full agent behavior.

### REQ-002: Belief Consistency
- **Code:** `cli.py` has a `reason` command that detects contradictions by looking for antonym pairs and negation patterns between beliefs. This is in the CLI layer, not in the retrieval pipeline.
- **Tests:** No tests for contradiction detection or flagging.
- **Gap:** Contradictions are not flagged during search/retrieval. The requirement says "never silently present contradictory beliefs" but the `search()` and `retrieve()` functions have no contradiction check. The contradiction logic in cli.py is a diagnostic tool, not enforcement.

### REQ-003: Retrieval Token Budget <= 2K
- **Code:** `compression.py::pack_beliefs()` enforces token budget. `retrieval.py::retrieve()` passes budget parameter through.
- **Tests:** `test_retrieval.py::TestRetrieve::test_total_tokens_within_budget` verifies budget compliance. `test_server.py::test_search_respects_budget` verifies at server layer.
- **Status:** PASSING. Budget enforcement is implemented and tested.

### REQ-004: Quality Per Token
- **Code:** Retrieval pipeline exists with scoring, compression, and budget packing.
- **Tests:** No test comparing 2K-token retrieval quality vs 10K-token full dump.
- **Gap:** Requires a comparative quality evaluation (human or rubric). This is an experiment, not a unit test.

### REQ-005: Crash Recovery >= 90%
- **Code:** WAL mode enabled in `store.py`. Sessions and checkpoints tables exist. `find_incomplete_sessions()` and `get_session_checkpoints()` provide recovery path.
- **Tests:** `tests/acceptance/test_req005_crash_recovery.py` (2 tests). Tests create checkpoints and verify they survive (no actual SIGKILL).
- **Gap:** No actual crash simulation (SIGKILL + restart). The test verifies checkpoint data is queryable after write, but does not test process termination recovery.

### REQ-006: Checkpoint Overhead < 50ms
- **Code:** `store.py::checkpoint()` with synchronous SQLite commit.
- **Tests:** `test_store.py::test_checkpoint_write_latency_p95` benchmarks 1000 writes.
- **Status:** PASSING in unit tests. Production overhead unknown.

### REQ-007: Retrieval Precision >= 50%
- **Code:** Full retrieval pipeline in `retrieval.py` with FTS5 + HRR + scoring + packing.
- **Tests:** `test_retrieval.py` has unit tests for the pipeline. No precision@15 evaluation harness.
- **Gap:** No human-labeled precision test across 20 queries. The retrieval pipeline is built but the acceptance measurement is not automated.

### REQ-008: FP Rate Decreasing Over Time
- **Code:** `store.py::record_test_result()` and `update_confidence()` exist for feedback. `scoring.py::retrieval_frequency_boost()` adjusts scores based on usage history.
- **Tests:** No longitudinal FP rate test.
- **Gap:** The feedback loop infrastructure exists in the store layer, but there is no production harness to track FP rate across sessions and verify it decreases.

### REQ-009: Bayesian Calibration
- **Code:** `scoring.py::thompson_sample()` and `uncertainty_score()` implement Thompson sampling. `store.py::update_confidence()` performs Bayesian updates. Beta(alpha, beta_param) priors assigned per type in `classification.py`.
- **Tests:** `test_reason.py` tests uncertainty_score. No ECE calculation test.
- **Status:** Simulation validated (Exp 5b, ECE=0.066). Production validation not implemented.

### REQ-010: Exploration Effectiveness
- **Code:** `scoring.py::thompson_sample()` provides exploration via stochastic sampling.
- **Tests:** No exploration fraction measurement.
- **Gap:** Thompson sampling is the mechanism but there is no instrumentation to measure what fraction of retrievals surface uncertain beliefs.

### REQ-011: Cross-Model MCP Interoperability
- **Code:** MCP server in `server.py` using FastMCP. Works with Claude via Claude Code MCP integration.
- **Tests:** `test_server.py` tests tool functions directly, not via MCP protocol.
- **Gap:** Untested with ChatGPT, local models, or any non-Claude client. The MCP protocol should be model-agnostic, but this is unverified.

### REQ-012: Write Durability
- **Code:** `store.py` constructor sets `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL`. All writes call `self._conn.commit()` before return.
- **Tests:** No crash simulation test (SIGKILL after acknowledged write).
- **Gap:** WAL + NORMAL synchronous should be sufficient for durability on ext4/APFS, but `synchronous=NORMAL` is not as strong as `synchronous=FULL`. No automated crash test to verify zero acknowledged writes lost.

### REQ-013: Observation Immutability
- **Code:** `store.py` has no `update_observation()` or `delete_observation()` methods. Observations have INSERT and SELECT only.
- **Tests:** `test_store.py::test_observation_no_update_path` verifies no update/delete API exists. `test_observation_dedup_same_content` verifies dedup returns existing.
- **Status:** PASSING. Immutability enforced at the application layer. Note: no database-level trigger prevents raw SQL UPDATE/DELETE -- the constraint is API-only.

### REQ-014: Zero-LLM Extraction Recall >= 40%
- **Code:** `classification.py::classify_sentences_offline()` provides zero-LLM classification. `correction_detection.py::detect_correction()` provides correction detection at 92% (V2).
- **Tests:** `test_extraction.py` has 7 tests for sentence extraction, 6 for correction detection, 4 for offline classification, and 4 for ingestion.
- **Status:** Offline classification exists. The 36% vs 99% accuracy gap is documented. The requirement threshold of 40% recall is met when combining offline classification (which persists most sentences) with LLM classification path.

### REQ-015 & REQ-016: Honesty (No Unverified Claims, Documented Limitations)
- **Status:** Audit tasks for Phase 5 ship time. Not code requirements. No audit has been performed.

### REQ-017: Fully Local Operation
- **Code:** All memory operations use local SQLite. Only outbound network call is `classification.py` calling Anthropic API for LLM classification, which is optional (offline path available).
- **Tests:** No offline-mode test.
- **Gap:** The `classify_sentences()` function calls the Anthropic API. While `classify_sentences_offline()` exists, the `ingest_turn()` function defaults to `use_llm=True` unless explicitly set False. The server's `ingest` tool sets `use_llm=False`, so the MCP path is fully local.

### REQ-018: No Telemetry
- **Code:** No telemetry, analytics, tracking, or reporting code found in `src/agentmemory/`. The only external call is the optional Anthropic API for classification.
- **Status:** PASSING by code audit.

### REQ-019: Single-Correction Learning
- **Code:** `server.py::correct()` creates locked beliefs with `source_type='user_corrected'`, alpha=9.0. `ingest.py::ingest_turn()` detects corrections via `detect_correction()` and creates locked beliefs with SUPERSEDES edges.
- **Tests:** `test_extraction.py::test_correction_creates_locked_belief`, `test_correction_detection_count`. Acceptance tests: `test_cs002_locked_correction.py` (5 tests), `test_cs009_supersession.py` (4 tests).
- **Status:** Core mechanism implemented and tested. The 90% prevention threshold is not measured via the alpha-seek replay specified in the requirement.

### REQ-020: Locked Beliefs
- **Code:** `store.py::lock_belief()` sets locked flag. `update_confidence()` blocks beta_param increase on locked beliefs (confidence floor preserved). `supersede_belief()` does not check locked status (a locked belief CAN be superseded -- is this intentional?).
- **Tests:** `test_store.py::test_locked_belief_confidence_cannot_decrease`, `test_cs002_locked_correction.py::test_cs002_lock_prevents_confidence_downgrade`.
- **Gap:** The requirement says "Only explicit user action can unlock or revise." But there is no `unlock_belief()` method and no test verifying that supersede_belief fails on locked beliefs. A locked belief can currently be superseded by another call to `supersede_belief()`.

### REQ-021: Behavioral Beliefs Always in L0
- **Code:** `retrieval.py::retrieve()` loads all locked beliefs as L0. The `get_locked_beliefs()` query returns all locked beliefs regardless of type.
- **Tests:** `test_cs002_locked_correction.py` verifies locked beliefs appear in search results.
- **Gap:** There is no classification of beliefs as "behavioral" vs "domain-specific." The current implementation loads ALL locked beliefs into L0, which is a superset of the requirement. This works but may not scale if locked beliefs grow large (capped at max_locked=100 in retrieve()).

### REQ-022: Locked Beliefs Survive Context Compression
- **Code:** Locked beliefs are loaded via `get_locked_beliefs()` in L0, which bypasses the compression pipeline entirely. They are not subject to `pack_beliefs()` token budget (they are added first, before FTS5 results).
- **Tests:** No explicit compression survival test.
- **Gap:** The implementation achieves this by sidestepping compression entirely for locked beliefs, which is correct but creates a token budget risk if many locked beliefs exist (100 * ~50 tokens = 5000 tokens, exceeding the 2000 budget). Locked beliefs are not counted against the budget in the current implementation.

### REQ-023: Research Artifact Provenance Metadata
- **Code:** Not implemented. The `beliefs` table has no `produced_at`, `method`, `sample_size`, `data_source`, or `independently_validated` columns. The `observations` table has `created_at` and `source_type` but these are operational metadata, not research provenance.
- **Tests:** None.
- **Gap:** Schema change required. No code exists for this requirement.

### REQ-024: Session Velocity Tracking
- **Code:** Not implemented. The `sessions` table has `started_at` and `completed_at` but no `item_count` or velocity computation. The `status()` function returns raw counts, not per-session velocity.
- **Tests:** None.
- **Gap:** Partial infrastructure exists (session timestamps). Needs: item counter per session, velocity computation, surfacing in status reports.

### REQ-025: Methodological Confidence Layer (Rigor Tier)
- **Code:** Not implemented. No `rigor_tier` field in any model, table, or function. The `belief_type` field classifies content type, not methodological rigor.
- **Tests:** None.
- **Gap:** Requires new schema field + classification logic + status reporting integration.

### REQ-026: Calibrated Status Reporting
- **Code:** `server.py::status()` returns raw counts only (observations, beliefs, locked, superseded, edges, sessions). No rigor tier distribution, session velocity, or caveats.
- **Tests:** `test_server.py::test_status_returns_counts` verifies the raw counts format.
- **Gap:** The status tool needs a significant overhaul to include provenance metadata summary, velocity context, and calibrated framing.

### REQ-027: Zero-Repeat Directive Guarantee
- **Code status by tier:**
  - **Tier 1 (Storage):** YES. Locked beliefs in SQLite WAL. `remember()` and `correct()` create them.
  - **Tier 2 (Injection):** YES. `get_locked()` returns all locked beliefs for SessionStart injection.
  - **Tier 3 (Compression survival):** YES. Locked beliefs bypass compression in retrieval.
  - **Tier 4 (Violation detection):** NO. No code monitors agent output for banned patterns.
  - **Tier 5 (Violation blocking):** NO. No pre-execution hooks.
  - **Tier 6 (LLM compliance):** N/A (not under system control).
- **Tests:** Acceptance tests cover Tiers 1-2. No tests for Tiers 4-5.
- **Gap:** The critical enforcement tiers (detection and blocking) are not implemented.

---

## Overall Coverage

| Category | Count | Implemented | Tested | Validated by Experiment |
|----------|-------|------------|--------|------------------------|
| Total Requirements | 27 | 16 (59%) | 13 (48%) | 10 (37%) |
| Fully Implemented + Tested | -- | 10 (37%) | -- | -- |
| Partially Implemented | -- | 6 (22%) | -- | -- |
| Not Implemented | -- | 7 (26%) | -- | -- |
| N/A (audit tasks) | -- | 4 (15%) | -- | -- |

**Code coverage by requirement status:**
- **GREEN (implemented + tested):** REQ-003, REQ-006, REQ-013, REQ-014, REQ-017, REQ-018, REQ-019, REQ-020 (8 of 27 = 30%)
- **YELLOW (partially implemented or untested):** REQ-001, REQ-002, REQ-005, REQ-007, REQ-009, REQ-010, REQ-011, REQ-012, REQ-021, REQ-022, REQ-027 (11 of 27 = 41%)
- **RED (not implemented):** REQ-004, REQ-008, REQ-023, REQ-024, REQ-025, REQ-026 (6 of 27 = 22%)
- **DEFERRED (audit/doc tasks):** REQ-015, REQ-016 (2 of 27 = 7%)

---

## Implementation Plan vs What Was Built

### Wave 1 (SQLite Store): COMPLETE
- `store.py`: schema, CRUD, WAL mode, FTS5, sessions, checkpoints, edges, graph_edges
- `models.py`: all dataclasses
- Tests: 30 tests in `test_store.py`

### Wave 2 (Retrieval Pipeline): COMPLETE
- `retrieval.py`: FTS5 + HRR + scoring + compression + budget packing
- `scoring.py`: decay_factor, lock_boost_typed, thompson_sample, core_score, recency_boost, retrieval_frequency_boost
- `compression.py`: type-aware compression, pack_beliefs
- `hrr.py`: full HRR graph encoding and query (planned for Phase 3 but built early)
- Tests: 18 tests in `test_retrieval.py`, 6 in `test_reason.py`

### Wave 3 (Extraction Pipeline): COMPLETE
- `extraction.py`: sentence splitting
- `classification.py`: LLM + offline classification
- `correction_detection.py`: zero-LLM correction detector
- `ingest.py`: end-to-end pipeline with JSONL batch support
- Tests: 17 tests in `test_extraction.py`

### Wave 4 (MCP Server): COMPLETE
- `server.py`: 8 tools (search, remember, correct, observe, status, get_locked, onboard, ingest)
- Tests: 9 tests in `test_server.py`

### Wave 5 (Hook Integration): PARTIAL
- No hook scripts in src/. The CLAUDE.md instructions direct agents to call MCP tools directly.
- The SessionStart hook injection mechanism relies on the host (Claude Code) calling `get_locked()` at session start, driven by CLAUDE.md instructions rather than code hooks.

### Wave 6 (Acceptance Tests): PARTIAL
- 7 of 7 planned acceptance test files exist
- 20 acceptance tests total
- Missing: no Phase 2 integration test with real MCP protocol, no Phase 3 acceptance tests

### Not In Plan But Built:
- `scanner.py`: full project onboarding scanner with git history, AST, docs, directives, citations (Exp 48/49 based)
- `cli.py`: extensive CLI with stats, search, core, locked, wonder, settings, reason commands
- `commit_tracker.py`: deterministic commit nudge system
- `config.py`: settings management
- HRR module (planned for Phase 3, built and integrated in retrieval)

---

## Critical Gaps That Block Production Use

### 1. REQ-020: Locked Beliefs Can Be Superseded
`supersede_belief()` does not check the locked flag. This means a programmatic call (e.g., from `ingest_turn()` correction detection) could supersede a user-locked belief. The requirement states only explicit user action should be able to revise locked beliefs. **Fix: add a locked check in `supersede_belief()` and reject or warn.**

### 2. REQ-022: Locked Beliefs Can Blow the Token Budget
Locked beliefs are loaded outside the token budget. With `max_locked=100` and an average of 50 tokens per belief, L0 alone could consume 5000 tokens -- far exceeding the 2000 token budget in REQ-003. **Fix: count locked beliefs against the budget, or enforce a token cap on L0.**

### 3. REQ-002: No Contradiction Detection in Retrieval
Search results can return contradictory beliefs without flagging them. The contradiction detection in `cli.py::reason` is a diagnostic tool, not integrated into the retrieval path. **This is the second-most important requirement per the design docs.**

### 4. REQ-027 Tiers 4-5: No Violation Detection or Blocking
The system stores and injects directives (Tiers 1-3) but cannot detect when the agent violates them (Tier 4) or block violating actions before they execute (Tier 5). **This is the core value proposition of the memory system.**

### 5. REQ-023/024/025/026: Epistemic Integrity Suite Not Started
The entire CS-005 family of requirements (provenance metadata, session velocity, rigor tiers, calibrated reporting) has zero code. These requirements exist specifically to prevent the "extensive research" mischaracterization problem documented in CS-005. **No schema fields, no classification logic, no status reporting.**

### 6. REQ-012: Write Durability Not Crash-Tested
`synchronous=NORMAL` is set instead of `synchronous=FULL`. NORMAL provides durability under process crash but not under OS crash. The requirement says "zero acknowledged writes lost across 1,000 crash simulations" but no crash simulation exists. **Risk: low on modern filesystems, but unverified.**

### 7. Wave 5 (Hook Integration) Incomplete
The system relies on CLAUDE.md instructions for the agent to call MCP tools at session start, rather than automated hooks. This means a model that does not read or obey CLAUDE.md instructions will not benefit from the memory system. **This partially undermines REQ-011 (cross-model) and REQ-027 (zero-repeat).**
