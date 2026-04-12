# TODO: Agentic Memory Project

**Last updated:** 2026-04-11
**Status:** Phase 2 MVP built and in live testing. 16 production modules, 176+ tests passing, MCP server active.

---

## Current Priority: Validate and Harden

Research phase is complete (65 experiments). Phase 2 MVP is built and self-hosting. Current focus is validating the feedback loop (core differentiator) and hardening what exists.

### Active Experiments (Exp 66-70)

| Exp | Question | Status |
|-----|----------|--------|
| 66 | Does the feedback loop improve retrieval quality over 50 rounds? | Designed |
| 67 | What is the retrieval impact of locking all corrections? | Designed |
| 68 | Do differentiated priors make Thompson sampling meaningful? | Designed |
| 69 | Does recency_boost() help new beliefs surface at scale? | Designed |
| 70 | Does increasing top_k from 30 to 50/100 improve coverage? | Designed |

### Code Fixes Applied (2026-04-11)

- [x] Fix feedback_given migration bug (search was broken on existing DBs)
- [x] Auto-lock correction-type beliefs (2,592 were unlocked from bulk ingestion)
- [x] Differentiate type priors (was uniform 90%; now REQ 94.7%, FACT 75%, ASSM 66.7%)
- [x] Increase FTS5 default K from 30 to 50
- [x] Wire _TYPE_WEIGHTS, _SOURCE_WEIGHTS, recency_boost() into score_belief()
- [x] Update stale docs (PIPELINE_STATUS.md, TODO.md, REQUIREMENTS.md)

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
- [x] MCP server (10 tools)
- [x] Project onboarding scanner (9 extractors)
- [x] Type-aware compression (55% savings)
- [x] HRR vocabulary bridge
- [x] Auto-feedback loop (wired in server.py)
- [x] CLI tools (setup, onboard, stats, health, search, etc.)

### Phase 3: Feedback Loop and Advanced Retrieval (IN PROGRESS)
- [ ] Validate auto-feedback improves retrieval (Exp 66)
- [ ] Contradiction detection on belief insertion
- [ ] Full graph edge extraction (CALLS, IMPLEMENTS, TESTS edges)
- [ ] Cross-model MCP testing (Claude, ChatGPT, Gemini)
- [ ] BFS graph traversal with edge weighting

### Phase 4: Behavioral Enforcement (PLANNED)
- [ ] Triggered belief automation (15 TB designs ready)
- [ ] Output gating middleware (pre-execution hooks)
- [ ] Directed graph traversal for multi-hop queries
- [ ] L1 behavioral layer in retrieval pipeline

### Phase 5: Epistemic Integrity and Validation (PLANNED)
- [ ] Provenance metadata (rigor tier, method, sample size)
- [ ] Session velocity tracking
- [ ] Calibrated status reporting
- [ ] Cross-model benchmarking
- [ ] Comprehensive acceptance testing (22 case study replays)

---

## Research Completed (65 Experiments)

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
