# Design vs Reality: Architectural Gap Assessment

**Date:** 2026-04-11
**Assessor:** Automated analysis of design documents vs deployed code

---

## 1. Executive Summary

Agentmemory is a research project that has done genuine, rigorous research (60 experiments, 27 requirements, 26 case studies) and then built a working MVP that implements the core pipeline end-to-end. The system delivers real cross-session memory via an MCP server backed by SQLite with FTS5, Bayesian confidence tracking, HRR vocabulary-bridge retrieval, sentence extraction, correction detection, and a project onboarding scanner. The gap between design and reality is smaller than the design documents suggest -- PIPELINE_STATUS.md was written before the Phase 2 MVP existed, and most of what it calls "NOT BUILT" is now built. The honest gap: the feedback loop (belief testing/revision from real usage) is not implemented, multi-session acceptance tests have not been run against real projects beyond self-hosting, and several advanced features (triggered beliefs, output gating, provenance metadata, session velocity tracking) remain unimplemented. The system works today for basic remember/correct/search/ingest/onboard workflows. It does not yet enforce directives or detect violations.

---

## 2. Scorecard: Design Promise vs Delivery

| Design Promise | Status | Evidence |
|---|---|---|
| Cross-session memory persistence | **DELIVERED** | SQLite WAL, per-project DB isolation, MCP server running |
| FTS5 full-text search on beliefs | **DELIVERED** | `store.search()` with BM25 ranking, porter tokenizer |
| Bayesian confidence (Beta priors) | **DELIVERED** | Alpha/beta on every belief, Thompson sampling in scoring |
| Locked beliefs (user corrections permanent) | **DELIVERED** | `locked` column, `lock_belief()`, protected in `update_confidence()` |
| Correction detection (zero-LLM) | **DELIVERED** | V2 detector at 92% accuracy, 7 signal types |
| HRR vocabulary-bridge retrieval | **DELIVERED** | `hrr.py` with partitioned encoding, forward/reverse queries |
| Sentence extraction pipeline | **DELIVERED** | `extraction.py` strips code/URLs/markdown, splits on boundaries |
| LLM classification (Haiku) | **DELIVERED** | `classification.py` with batch prompting, type-to-prior mapping |
| Offline classification fallback | **DELIVERED** | `classify_sentences_offline()` with keyword heuristics |
| Type-aware compression | **DELIVERED** | `compression.py` with ~55% savings validated |
| Temporal decay scoring | **DELIVERED** | Content-type half-lives, locked immunity, supersession penalty |
| LOCK_BOOST_TYPED re-ranking | **DELIVERED** | `scoring.py` with query-relevance boost for locked beliefs |
| Project onboarding scanner | **DELIVERED** | `scanner.py` extracts git, docs, AST, citations, directives |
| MCP server with 8 tools | **DELIVERED** | search, remember, correct, observe, status, get_locked, onboard, ingest |
| Content-hash dedup | **DELIVERED** | SHA-256 truncated to 12 hex chars on observations and beliefs |
| SUPERSEDES edges | **DELIVERED** | `supersede_belief()` with edge creation and valid_to marking |
| BFS graph expansion | **DELIVERED** | `expand_graph()` with depth limit, max nodes, edge type filtering |
| Evidence chain (observation to belief) | **DELIVERED** | `evidence` table with source_weight and relationship |
| Session tracking + checkpoints | **DELIVERED** | Sessions table, checkpoint writes, incomplete session detection |
| Retrieval pipeline (FTS5+HRR+scoring+packing) | **DELIVERED** | `retrieval.py` combines all components into budget-aware pipeline |
| Feedback loop (test/revise cycle) | **NOT BUILT** | `tests` table exists in schema, `record_test_result()` exists, but nothing calls it automatically |
| Triggered beliefs (meta-cognitive checks) | **NOT BUILT** | Designed (15 TBs), simulated (5/5 pass), not automated |
| Output gating (block violating output) | **NOT BUILT** | No implementation |
| Provenance metadata (rigor tiers) | **NOT BUILT** | No `rigor_tier` or `method` fields in schema |
| Session velocity tracking | **NOT BUILT** | No elapsed time or item count tracking |
| Calibrated status reporting | **NOT BUILT** | `status()` returns raw counts only |
| Contradiction detection | **NOT BUILT** | No mechanism to detect or flag belief conflicts |
| Cross-model MCP testing | **NOT TESTED** | Only used with Claude Code |
| Crash recovery validation | **PARTIALLY TESTED** | Schema and WAL mode support it; acceptance test exists but not stress-tested |
| Multi-session acceptance test (REQ-001) | **NOT RUN** | Test file exists (`test_req001_cross_session.py`) but the scenario is synthetic |

---

## 3. What Works (With Evidence)

**Tested and passing (176 tests, 1 skipped):**

- **SQLite store with full schema:** 9 tables (observations, beliefs, evidence, edges, checkpoints, tests, sessions, audit_log, graph_edges) plus FTS5 index. WAL mode enabled. Foreign keys enforced. All CRUD operations tested. Path: `src/agentmemory/store.py`.

- **MCP server is operational:** 8 tools exposed via FastMCP (search, remember, correct, observe, status, get_locked, onboard, ingest). Configured in `.mcp.json` to run via `uv run python -m agentmemory.server`. Per-project DB isolation via SHA-256 hash of cwd.

- **Ingestion pipeline end-to-end:** `ingest_turn()` chains extraction -> correction detection -> classification -> belief insertion. Corrections auto-lock. JSONL batch ingestion also works. Tested in `test_extraction.py`.

- **Retrieval pipeline end-to-end:** `retrieve()` chains locked beliefs (L0) + FTS5 search (L2) + HRR expansion (L3) -> scoring -> compression -> budget packing. Returns `RetrievalResult` with token accounting. Tested in `test_retrieval.py`.

- **Onboarding scanner:** Scans project directories for git history, docs, AST call graphs, citations, and directives. Feeds extracted nodes through ingest pipeline. Tested in `test_scanner.py`.

- **Locked beliefs work as designed:** Cannot have beta_param increased by automated processes. Protected in `update_confidence()`. Loaded via `get_locked_beliefs()`. Tested in acceptance tests.

- **Self-hosting works:** The CLAUDE.md instructs agents to call agentmemory MCP tools. The system is being used to manage its own project context. This is live validation, not just tests.

- **CLI with 12 commands:** setup, onboard, stats, health, core, search, locked, remember, lock, commit-check, commit-config, help. Path: `src/agentmemory/cli.py`.

---

## 4. What Doesn't Work (With Evidence)

**Not built:**

1. **Feedback loop is dead code.** The `tests` table schema exists. `record_test_result()` exists and correctly updates confidence. But nothing in the pipeline automatically records whether a retrieved belief was used, ignored, or harmful. The entire "scientific method" feedback cycle -- the core differentiator from every other memory system -- is not operational. This is the most significant gap.

2. **Triggered beliefs (TB-01 through TB-15) are not automated.** They were simulated in Exp 48/51 and passed 5/5 case study simulations. But no code implements the event/condition/action framework. The system stores knowledge but does not act on it proactively.

3. **Output gating does not exist.** CS-006 and CS-016 require the system to block agent output that violates locked beliefs. No code path implements this. The system can tell the agent what rules exist (via `get_locked`); it cannot prevent violations.

4. **Contradiction detection is absent.** REQ-002 requires 100% of contradictions flagged. There is no mechanism to detect when a newly inserted belief contradicts an existing one. `insert_belief()` does content-hash dedup (exact duplicates) but not semantic conflict detection.

5. **Provenance metadata not in schema.** REQ-023 requires `produced_at`, `method`, `sample_size`, `data_source`, `independently_validated` on research artifacts. None of these fields exist in the beliefs table. The `belief_type` and `source_type` fields provide rough categorization but not provenance depth.

6. **Session velocity not tracked.** REQ-024 requires elapsed time, item count, and velocity per session. The `sessions` table has `started_at` and `completed_at` but no item count or velocity computation.

**Misleading or stale:**

7. **PIPELINE_STATUS.md is outdated.** Written before Phase 2 MVP. Claims "belief graph insertion: NOT BUILT" and "retrieval function: PROTOTYPED" -- both are now fully built and tested. The document's "honest assessment" says "what's blocking us is a database and a server" -- that blocker no longer exists.

8. **TODO.md header says "No production code"** but there are 16 production Python modules with 176 passing tests.

9. **Requirements status column.** REQUIREMENTS.md shows most requirements as "Not started" when several are now partially or fully addressed by the codebase (REQ-017 fully local, REQ-018 no telemetry, REQ-020 locked beliefs, etc.).

**Partially working:**

10. **Offline classification is low accuracy.** `classify_sentences_offline()` acknowledges "36% vs 99% LLM" in its docstring. The default `ingest` MCP tool uses `use_llm=False`, meaning live ingestion runs the low-accuracy path. This is a deliberate tradeoff (cost/offline) but users should know.

11. **Correction supersession is fragile.** When a correction is detected, `ingest.py` searches for existing beliefs using the first 5 words >3 chars. This is a rough heuristic. It only supersedes beliefs with the same `belief_type`. A correction to a "factual" belief from a "correction" type won't supersede it.

---

## 5. Architecture Drift Analysis

**Where implementation matches design:**

- The scientific method model (observe/believe/test/revise) is faithfully reflected in the schema. Observations are immutable (insert-only with content-hash dedup). Beliefs carry Bayesian priors. Evidence links observations to beliefs. The structure is sound.

- Progressive context loading (L0 locked + L2 FTS5 + L3 HRR) matches the PLAN.md layered retrieval design.

- The MCP server interface matches the design intent. Tool names slightly differ from PLAN.md's original naming but the semantics are correct.

**Where implementation diverged:**

1. **Feedback loop deferred, not canceled.** The design's core differentiator ("the critical piece nobody has built well") is the test/revise feedback cycle. The schema supports it. The code has the API. But nothing wires it up. The system is currently write-and-retrieve with no automatic learning from retrieval outcomes -- exactly the pattern the design criticized in other systems.

2. **LLM classification is off by default.** The design envisioned "zero-LLM by default, LLM-enriched optionally." The implementation flipped this for classification: `ingest` MCP tool passes `use_llm=False`, using the 36%-accuracy offline classifier. The 99%-accuracy LLM classifier exists but is not the default path for live turns. This means most ingested beliefs from conversation turns are poorly classified.

3. **No L1 layer.** PLAN.md describes progressive loading as L0 (always-loaded), L1 (task-relevant behavioral), L2 (query-matched), L3 (deep search). The implementation has L0 (locked beliefs) and L2 (FTS5) and L3 (HRR), but no distinct L1 layer for behavioral beliefs that aren't locked.

4. **Graph edges (belief-level) vs graph_edges (structural).** The schema has two edge tables: `edges` (FK-constrained between beliefs) and `graph_edges` (no FK, used by scanner/HRR). This split was not in the original design and creates two parallel graph structures that are only merged at query time in `get_all_edge_triples()`.

5. **Onboarding scanner was not in the original Phase 2 scope.** PLAN.md Phase 2 focused on the core belief graph. The scanner (`scanner.py`, 683 lines) is a significant addition that was not planned -- it emerged from the onboarding research (Exp 49). This is drift in a positive direction but it's unplanned complexity.

---

## 6. Recommended Path Forward (Prioritized)

### Priority 1: Fix what's misleading (1 day)

- Update PIPELINE_STATUS.md to reflect current state (most "NOT BUILT" items are now built)
- Update TODO.md header to remove "No production code"
- Update REQUIREMENTS.md status column for requirements now covered by code
- These stale documents will mislead any new agent or contributor

### Priority 2: Wire up the feedback loop (3-5 days)

- This is the design's core differentiator and it's 80% built
- The `tests` table exists, `record_test_result()` works, `update_confidence()` respects locks
- What's missing: automatic detection of whether a retrieved belief was used/ignored/harmful
- Simplest path: after each `search()` call, track which belief IDs were returned. On the next `ingest()` of an assistant turn, check if any retrieved belief content appears in the response. If yes, record "used". If the user's next turn is a correction, record "harmful" for recently retrieved beliefs
- This closes the feedback loop with zero additional infrastructure

### Priority 3: Switch live ingestion to LLM classification (1 day)

- The offline classifier at 36% accuracy means most conversation turns are poorly classified
- The LLM classifier at 99% accuracy costs $0.005/session
- Add a config toggle (default: LLM on if API key present, offline if not)
- This dramatically improves belief quality for anyone with an Anthropic API key

### Priority 4: Run real multi-session acceptance tests (2-3 days)

- REQ-001 (the core requirement) has never been validated on a real project
- Design a 5-session test on a real project (not self-hosting)
- Establish 10 decisions in session 1, verify retrieval in sessions 2-5
- This is the single highest-value validation that hasn't been done

### Priority 5: Add contradiction detection (2-3 days)

- REQ-002 requires zero silent contradictions
- On belief insertion, run FTS5 search for semantically similar existing beliefs
- Flag when a new belief appears to contradict an existing one
- Start simple (keyword overlap + opposite sentiment signals), improve later

### Priority 6: Implement triggered beliefs for top-3 case studies (3-5 days)

- TB-02/03/10 (directive enforcement) covers CS-006 -- the most severe failure pattern
- TB-01 (self-check state docs) covers CS-003
- TB-04 (task ID verify) covers CS-020
- The event/condition/action model is designed; it needs code

### Deferred (do later):

- Output gating (requires platform-specific hooks, complex)
- Provenance metadata and rigor tiers (REQ-023-026, important but not blocking core value)
- Session velocity tracking (nice to have, not critical path)
- Cross-model testing (blocked until other model users test it)

---

## 7. Honest Assessment: On Track or Off the Rails?

**On track, with one structural risk.**

The project did something unusual: it did the research first, thoroughly, and then built code that reflects the research. The 60 experiments are not window dressing -- they produced real findings that shaped the architecture (SimHash rejected, HRR role narrowed to vocabulary bridge, decay architecture revised twice, feedback loop role shifted to exception correction). The code is clean, strictly typed, well-tested (176 tests), and architecturally coherent.

The structural risk is the feedback loop. The entire design philosophy -- "the scientific method, not human memory" -- rests on the test/revise cycle. Without it, this is a write-and-retrieve system with good priors and locked beliefs. That's better than grep and better than MemPalace's raw conversation archive, but it's not what the design promises. The feedback loop is the difference between "a good memory store" and "a memory system that learns." Priority 2 above is the path to closing this gap.

The secondary risk is stale documentation. The design documents (PIPELINE_STATUS.md, TODO.md, REQUIREMENTS.md) describe a state that no longer exists. A new agent reading them would conclude "nothing is built" when in fact the core pipeline is operational. This creates exactly the CS-005 problem (maturity miscalibration) that the project identified as a critical failure mode. Fix this first.

**Case study coverage estimate:** Of the 26 case studies documented, the current system can plausibly address 8-10 today (CS-001, CS-002, CS-004, CS-008, CS-009, CS-012, CS-013, CS-015, CS-016 partially, CS-025 partially) through locked beliefs + FTS5 retrieval. Another 6-8 become addressable with the feedback loop and triggered beliefs (priorities 2 and 6). The remaining 8-10 require full graph traversal, output gating, or cross-model features that are further out.

**Research-to-code ratio:** Roughly 60-70% of experiment findings are reflected in code. The major incorporated findings: FTS5+HRR beats grep (Exp 56), decay architecture (Exp 57-60), type-aware compression (Exp 42), correction detection V2 (Exp 1), LLM classification (Exp 50/61), source-stratified priors (Exp 38), onboarding pipeline (Exp 49). The major unincorporated findings: triggered beliefs (Exp 44/51), multi-project isolation scope levels (Exp 43), information bottleneck DIM bounds (Exp 42), traceability graph structure (Exp 41/17).

**Bottom line:** This is a real system that works today for basic cross-session memory. It is not a research prototype pretending to be a product, nor is it a product with unvalidated claims. It is a research-backed MVP with a clear path to its design goals. The feedback loop and stale documentation are the two things that need attention.
