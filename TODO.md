# TODO: Agentic Memory Project

**Last updated:** 2026-04-13
**Status:** Phase 3 in progress. 18 production modules, 260 tests passing, 19 MCP tools, MCP server active.

---

## Current Priority: Harden and Validate Cross-Session

Research phase is complete (83 experiments). Phase 2 MVP is built and self-hosting. Feedback loop validated (Exp 66: +22% MRR). Current focus is cross-session validation and closing remaining Phase 3 gaps.

### Active Experiments (Exp 66-83)

| Exp | Question | Status |
|-----|----------|--------|
| 66 | Does the feedback loop improve retrieval quality? | **PASS** (+22% MRR over 10 rounds) |
| 67 | What is the retrieval impact of locking all corrections? | Designed |
| 68 | Do differentiated priors make Thompson sampling meaningful? | Designed |
| 69 | Does recency_boost() help new beliefs surface at scale? | Designed |
| 70 | Does increasing top_k from 30 to 50/100 improve coverage? | Designed |
| 74 | Temporal queries vs keyword search | Complete |
| 75 | Session velocity measurement and calibration | Complete |
| 78 | Confidence trajectory analysis | Complete |
| 79-83 | Statement vs belief ontological distinction | Complete |

### Code Fixes Applied (2026-04-11)

- [x] Fix feedback_given migration bug (search was broken on existing DBs)
- [x] Auto-lock correction-type beliefs (2,592 were unlocked from bulk ingestion)
- [x] Differentiate type priors (was uniform 90%; now REQ 94.7%, FACT 75%, ASSM 66.7%)
- [x] Increase FTS5 default K from 30 to 50
- [x] Wire _TYPE_WEIGHTS, _SOURCE_WEIGHTS, recency_boost() into score_belief()
- [x] Update stale docs (PIPELINE_STATUS.md, TODO.md, REQUIREMENTS.md)

### Code Fixes Applied (2026-04-12/13)

- [x] Wire CONTRADICTS/SUPPORTS edge detection into remember() and correct()
- [x] Retrieve performance: 10s -> 0.7s avg (batch FTS5, datetime caching, HRR filtering)
- [x] Auto-feedback fires on ingest() + atexit flush for session end
- [x] Add classified_by column (offline/llm/user) for reclassification targeting
- [x] get_reclassifiable() scoped to offline-classified beliefs only

---

## Phase Roadmap

### Phase 1: Foundation (COMPLETE)
- [x] SQLite store with WAL mode
- [x] Observation immutability
- [x] Session checkpointing
- [x] Crash recovery path

### Phase 2: Core Belief Graph and Retrieval (COMPLETE)
- [x] Belief insertion with source-informed priors
- [x] FTS5 search pipeline
- [x] Locked beliefs + L0 auto-loading
- [x] SUPERSEDES edges
- [x] Decay scoring + lock boost + type/source weights + recency boost
- [x] Correction detection V2 (92%, zero-LLM)
- [x] MCP server (19 tools)
- [x] Project onboarding scanner (9 extractors)
- [x] Type-aware compression (55% savings)
- [x] HRR vocabulary bridge
- [x] Auto-feedback loop (wired in server.py)
- [x] CLI tools (setup, onboard, stats, health, search, etc.)

### Phase 3: Feedback Loop and Advanced Retrieval (IN PROGRESS)
- [x] Validate auto-feedback improves retrieval (Exp 66: +22% MRR)
- [x] Contradiction detection on belief insertion (CONTRADICTS/SUPPORTS edges)
- [x] Retrieve performance optimization (10s -> 0.7s)
- [x] classified_by tracking for reclassification targeting
- [x] Auto-feedback fires on ingest() + atexit session flush
- [x] Multi-session validation harness (Exp 84: 10/10 checks pass)
- [x] CALLS (3,518), CITES (758), CONTAINS (720) edges from scanner (in graph_edges table)
- [ ] IMPLEMENTS/TESTS edge extraction (requirement-to-code, test-to-code traceability)
- [ ] Cross-model MCP testing (Claude, ChatGPT, Gemini)
- [ ] BFS graph traversal with edge weighting (HRR single-hop exists)

### Phase 4: Behavioral Enforcement (COMPLETE)
- [x] TB-02: Session start locked belief injection (agentmemory-inject.sh)
- [x] TB-03: Per-prompt directive injection (agentmemory-search-inject.sh)
- [x] TB-10: PreToolUse directive violation gate (agentmemory-directive-gate.sh)
- [x] Session-end hook: complete session + auto-ingest turns from conversation log
- [x] TB-06: PreCompact guard warns about locked beliefs before compression
- [x] TB-07: Empty retrieval escalation (suggests asking user or observe())
- [x] TB-08: Corrections auto-promoted (correct() creates high-conf belief)
- [x] TB-09: Contradictions surfaced (flag_contradictions() in retrieve)
- [x] TB-11: Stale context detection (>24h gap warning at session start)
- [x] TB-05: Maturity note when <20% user-validated beliefs (CS-005)
- [x] TB-13: Locked belief access audit counter in status()
- [x] TB-15: Confidence drop warning when belief falls below 50%
- [x] TB-01/04/12/14: Behavioral guidance (enforced via CLAUDE.md rules)
- [x] BFS multi-hop traversal (depth-2, expand_graph in retrieve, 129ms overhead)
- [x] L1 behavioral layer (get_behavioral_beliefs between L0 and L2)

### Phase 5: Epistemic Integrity and Validation (PLANNED)
- [ ] Provenance metadata (rigor tier, method, sample size)
- [ ] Session velocity tracking
- [ ] Calibrated status reporting
- [ ] Cross-model benchmarking
- [ ] Comprehensive acceptance testing (22 case study replays)

---

## Research Completed (83 Experiments)

### Key Validated Findings

| Finding | Experiment | Confidence |
|---------|-----------|------------|
| FTS5+HRR beats grep: 100% vs 92% coverage | Exp 56 | Empirically tested |
| Correction detection at 92% (zero-LLM) | Exp 1 V2 | Empirically tested |
| Bayesian calibration ECE=0.066 | Exp 5b | Simulated |
| Type-aware compression: 55% savings, zero loss | Exp 42 | Empirically tested |
| LOCK_BOOST_TYPED: MRR 0.589 -> 0.867 | Exp 60 | Empirically tested |
| LLM classification (Haiku): 99%, $0.005/session | Exp 50 | Empirically tested |
| 31% of directives have vocabulary gaps; HRR bridges 100% | Exp 53 | Empirically tested |

### Key Negative Findings

| Finding | Experiment |
|---------|-----------|
| Multi-layer extraction regressive at scale (16K worse than 586) | Exp 48 |
| SimHash not viable (1.04x separation, near-random) | Exp 46 |
| MI re-ranking hurts MRR vs BM25 | Exp 54 |
| Rate-distortion optimization unnecessary at current scale | Exp 55 |
| Pre-prompt compilation worse than on-demand retrieval | Exp 64 |
| Global scoring without query is noise | Exp 62 |

---

## Backlog

- Sentence splitting for non-English / mixed-content documents
- Threshold for full re-onboarding vs incremental after major restructures
- Cross-project behavioral belief promotion mechanism
- Onboarding provenance and extractor versioning
- HRR partition strategy for 10K+ node graphs

## Pruned (no longer relevant)

- ~~MemPalace spatial metaphor~~ -- rejected in favor of scientific method model
- ~~SimHash clustering~~ -- Exp 46 negative result
- ~~Embedding-only retrieval~~ -- FTS5+HRR validated as superior for this use case
- ~~Pre-prompt compilation~~ -- Exp 64 negative result
- ~~Human memory categories (episodic/semantic/procedural)~~ -- rejected early
