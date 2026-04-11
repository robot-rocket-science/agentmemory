# Implementation Plan: Agentmemory MVP

**Date:** 2026-04-10
**Goal:** Build the minimum system that passes Phase 2 acceptance tests
**Constraint:** Strict static typing, uv package manager, pyright strict mode

---

## Hypotheses

**H1: A SQLite store + FTS5 + locked beliefs + MCP server is sufficient to pass Phase 2 acceptance tests.** Phase 2 tests (CS-001, CS-002, CS-004, CS-006, CS-009, CS-013, CS-016) require: persistent beliefs, FTS5 search, locked flag, SUPERSEDES edges, and cross-session retrieval. No HRR, no graph traversal, no triggered beliefs needed.

**H2: SessionStart hook injection of locked beliefs prevents behavioral violations at the same rate as Exp 36 (0%).** The hook injects all locked beliefs into context at session start. The LLM sees them before producing any output.

**H3: The Exp 61 classification pipeline (conversation logger -> sentence extraction -> Haiku classification -> Beta priors) can be automated end-to-end with < 5s latency per turn.** Currently each step is manual. Automating the pipeline requires connecting: hook payload -> extraction -> classification -> INSERT.

**H4: FTS5 alone (without HRR) is sufficient for Phase 2 case studies.** Phase 2 doesn't include CS-022 (multi-hop) or CS-015 (vocabulary gap). The vocabulary-gap cases that require HRR are Phase 3.

**H5: Correction detection (Exp 1 V2) can run inline on every user turn with < 50ms overhead.** The detector is regex-based, no LLM. It should be fast enough to run synchronously in the UserPromptSubmit hook.

---

## Assumptions

1. **Python MCP servers can be registered in Claude Code settings.json.** MemPalace already does this as a plugin. We'll use the same mechanism.
2. **The `mcp` Python package provides the server framework.** Need to verify package name and API.
3. **SQLite WAL mode provides sufficient durability for REQ-005/REQ-012.** Standard SQLite guarantee: acknowledged writes survive process crash.
4. **Haiku API calls can be made from within the pipeline.** The anthropic SDK is already a dependency.
5. **The conversation-logger.sh hook can be extended or replaced** to feed the extraction pipeline directly.
6. **A single SQLite file per project is the right granularity.** One database at `~/.agentmemory/{project_hash}/memory.db`.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Claude Code Session                   │
│                                                         │
│  UserPromptSubmit ──► conversation-logger.sh             │
│       │                    │                             │
│       │                    ▼                             │
│       │              turns.jsonl                         │
│       │                                                 │
│  SessionStart ──► agentmemory-inject.sh                 │
│       │              │                                  │
│       │              ▼                                  │
│       │         MCP server: retrieve locked beliefs     │
│       │              │                                  │
│       │              ▼                                  │
│       │         Inject into context                     │
│                                                         │
│  MCP Tools ──► agentmemory MCP server                   │
│       │         │                                       │
│       │         ├── search(query) → ranked beliefs      │
│       │         ├── remember(text) → locked belief      │
│       │         ├── correct(text) → supersede + lock    │
│       │         ├── status() → belief counts, health    │
│       │         └── session tools                       │
│       │                                                 │
│       ▼                                                 │
│  ┌──────────────────────────┐                           │
│  │   SQLite (WAL mode)      │                           │
│  │   ~/.agentmemory/db/     │                           │
│  │                          │                           │
│  │   observations           │                           │
│  │   beliefs                │                           │
│  │   evidence               │                           │
│  │   edges                  │                           │
│  │   sessions               │                           │
│  │   checkpoints            │                           │
│  │   search_index (FTS5)    │                           │
│  │   audit_log              │                           │
│  └──────────────────────────┘                           │
└─────────────────────────────────────────────────────────┘
```

---

## Build Waves

### Wave 1: SQLite Store (foundation -- everything depends on this)

**What:** Create the database schema, connection management, and core CRUD operations.

**Files:**
- `src/agentmemory/__init__.py`
- `src/agentmemory/store.py` -- database initialization, connection, WAL mode
- `src/agentmemory/models.py` -- dataclasses for Observation, Belief, Evidence, Edge, Session, Checkpoint
- `src/agentmemory/observations.py` -- insert_observation (immutable, content-hash dedup)
- `src/agentmemory/beliefs.py` -- insert_belief, update_confidence, lock_belief, supersede_belief
- `src/agentmemory/edges.py` -- insert_edge, query_edges
- `src/agentmemory/sessions.py` -- create_session, checkpoint, complete_session, find_incomplete
- `src/agentmemory/search.py` -- FTS5 search with BM25 ranking, type filtering
- `tests/test_store.py` -- schema creation, CRUD, WAL mode, crash safety

**Test methodology:**
- Unit test each operation
- Verify observation immutability (UPDATE/DELETE must fail)
- Verify content-hash dedup (same content = same ID, no duplicate)
- Verify locked beliefs cannot have confidence reduced
- Verify SUPERSEDES creates edge and sets valid_to on old belief
- Benchmark checkpoint writes for REQ-006 (p95 < 50ms)

### Wave 2: Retrieval Pipeline (the core value -- search and rank beliefs)

**What:** FTS5 search + decay scoring + lock boost + token budget packing.

**Files:**
- `src/agentmemory/retrieval.py` -- search pipeline: FTS5 -> score -> rank -> pack
- `src/agentmemory/scoring.py` -- decay_factor, lock_boost_typed, thompson_sample
- `src/agentmemory/compression.py` -- type-aware compression (Exp 42 heuristic)
- `tests/test_retrieval.py` -- search accuracy, ranking correctness, budget compliance

**Test methodology:**
- Seed database with alpha-seek beliefs (from spike DB)
- Run 6-topic ground truth queries (from Exp 56)
- Verify coverage >= 100% at K=30
- Verify locked beliefs rank above unlocked for same query
- Verify token budget <= 2,000 after compression
- Verify superseded beliefs rank near zero

### Wave 3: Extraction Pipeline (conversation -> beliefs)

**What:** Automate the Exp 61 pipeline: sentence extraction + LLM classification + prior assignment + insertion.

**Files:**
- `src/agentmemory/extraction.py` -- sentence splitting (dumb, from Exp 57)
- `src/agentmemory/classification.py` -- LLM classification via Haiku (batch)
- `src/agentmemory/correction_detection.py` -- zero-LLM correction detector (Exp 1 V2)
- `src/agentmemory/priors.py` -- type-to-prior mapping (from Exp 61)
- `src/agentmemory/ingest.py` -- end-to-end pipeline: text -> observations -> beliefs
- `tests/test_extraction.py` -- sentence count, classification accuracy, prior assignment

**Test methodology:**
- Feed real conversation turns (from turns.jsonl) through the pipeline
- Verify sentence extraction produces ~7.8 sentences/turn (Exp 61 baseline)
- Verify classification matches Exp 61 type distribution
- Verify corrections are detected at >= 87% rate (Exp 1 V2 baseline)
- Verify corrections create locked beliefs with SUPERSEDES edges

### Wave 4: MCP Server (the interface -- how the LLM talks to the store)

**What:** MCP server exposing search, remember, correct, status tools.

**Files:**
- `src/agentmemory/server.py` -- MCP server using fastmcp or mcp SDK
- `src/agentmemory/tools.py` -- tool implementations wrapping store operations
- `tests/test_server.py` -- tool call round-trips

**Tools (MVP subset):**
- `search(query: str, budget: int = 2000) -> list[Belief]` -- FTS5 + scoring + packing
- `remember(text: str) -> Belief` -- create locked belief at Beta(9, 0.5)
- `correct(text: str, corrects: str | None = None) -> Belief` -- detect what's being corrected, create locked replacement, supersede old
- `status() -> dict` -- belief count, locked count, session info
- `observe(text: str, source: str = "user") -> Observation` -- record raw observation

**Test methodology:**
- Start server, call each tool, verify database state
- Verify remember() creates locked belief retrievable by search()
- Verify correct() creates SUPERSEDES edge
- Verify search() respects token budget

### Wave 5: Hook Integration (the enforcement -- inject beliefs into sessions)

**What:** SessionStart hook that queries the MCP server for locked/behavioral beliefs and injects them.

**Files:**
- `src/agentmemory/hooks/session_start.sh` -- query server, inject locked beliefs
- `src/agentmemory/hooks/ingest_turn.sh` -- on UserPromptSubmit, feed turn to extraction pipeline
- Configuration updates to ~/.claude/settings.json

**Test methodology:**
- Start a Claude Code session with hooks active
- Verify locked beliefs appear in context
- Verify new corrections from the session are captured
- Manual CS-002 test: say "no implementation", end session, start new session, check

### Wave 6: Phase 2 Acceptance Tests

**What:** Automated test harness for Phase 2 case studies.

**Files:**
- `tests/acceptance/test_cs001_redundant_work.py`
- `tests/acceptance/test_cs002_locked_correction.py`
- `tests/acceptance/test_cs009_supersession.py`
- `tests/acceptance/test_cs013_tool_correction.py`
- `tests/acceptance/test_req001_cross_session.py`
- `tests/acceptance/test_req005_crash_recovery.py`
- `tests/acceptance/test_req006_checkpoint_overhead.py`

**Test methodology:**
- CS-001: Insert observation "task completed." Query "do the task." Verify "already done" response possible (belief is in retrieval results).
- CS-002: Call remember("no implementation"). New session. Search for anything. Verify "no implementation" is in L0 results.
- CS-009: Call remember("use approach A"). Call correct("use approach B, not A"). Search("how to deploy"). Verify B returned, A suppressed.
- CS-013: Call remember("gcloud filter uses space-OR, not pipe"). Search("gcloud filter OR syntax"). Verify correction retrieved.
- REQ-001: 5 sessions, 10 decisions in session 1, verify 80%+ retrieved in session 5.
- REQ-005: Start session, write 20 checkpoints, SIGKILL, recover, verify >= 90% recovered.
- REQ-006: Benchmark 1,000 checkpoint writes, verify p95 < 50ms.

---

## Assumptions to Revisit

| Assumption | When to Revisit | Risk if Wrong |
|---|---|---|
| MCP Python SDK available and compatible | Wave 4 start | Need different framework; delay 1-2 days |
| SQLite WAL sufficient for crash safety | Wave 1 tests | Need fsync tuning; low risk |
| Haiku classification can run async per turn | Wave 3 integration | Need batch mode; affects latency |
| FTS5 alone sufficient for Phase 2 | Wave 2 tests | Need HRR earlier than planned; medium risk |
| Single DB file per project | Wave 1 design | Need multi-DB; low risk, easy to change |
| Correction detector < 50ms | Wave 3 benchmarks | Need to simplify patterns; low risk |

---

## What This Plan Does NOT Include (Phase 3)

- HRR encoding and structural retrieval (CS-022, CS-015)
- Triggered beliefs automation (CS-003, CS-005, CS-020, CS-021)
- Output gating for behavioral constraints (CS-006 full enforcement, CS-016)
- Edge extraction from git history (COMMIT_BELIEF, CO_CHANGED)
- Edge extraction from AST (CALLS, PASSES_DATA, IMPLEMENTS)
- Feedback loop production implementation (implicit detection layers 2-4)
- Cross-model MCP testing (REQ-011)
- Benchmark runs (LoCoMo, LongMemEval, MemoryAgentBench)

These are all designed and validated in research. They build on the Wave 1-6 foundation.

---

## Success Criteria

The MVP is done when:
1. All Phase 2 acceptance tests pass
2. REQ-001 verified (>= 80% cross-session retention)
3. REQ-005 verified (>= 90% crash recovery)
4. REQ-006 verified (p95 checkpoint < 50ms)
5. The system can be installed as an MCP server in Claude Code settings.json
6. A real user session produces beliefs that persist to the next session
