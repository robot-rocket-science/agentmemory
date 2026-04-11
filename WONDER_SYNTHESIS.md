# Wonder Synthesis: Prototype Status Assessment

**Date:** 2026-04-11
**Method:** 5 parallel research agents audited requirements, pipeline, integration, memory quality, and design-vs-reality. This document synthesizes their findings.

---

## Verdict

The prototype works for basic memory operations (store, search, retrieve, lock). It does not yet deliver the system's core differentiator: the feedback loop that tests and revises beliefs from real usage. The research is rigorous and ahead of the code.

**Tested:** MCP server, 8 tools, SQLite store, FTS5+HRR retrieval, correction detection, locked beliefs, project onboarding, 176 passing tests.

**Guess:** That the feedback loop, triggered beliefs, and output gating will work as designed when implemented. No code validates this beyond simulation.

---

## The Numbers

| Metric | Value | Source |
|---|---|---|
| Requirements fully implemented | 8/27 (30%) | REQUIREMENTS_GAP_ANALYSIS.md |
| Requirements partially implemented | 11/27 (41%) | REQUIREMENTS_GAP_ANALYSIS.md |
| Requirements with zero code | 8/27 (30%) | REQUIREMENTS_GAP_ANALYSIS.md |
| Pipeline stages wired end-to-end | 8/13 (62%) | PIPELINE_AUDIT.md |
| Case studies addressable today | 8-10/26 (31-38%) | DESIGN_VS_REALITY.md |
| Research findings reflected in code | ~60-70% | DESIGN_VS_REALITY.md |
| Tests passing | 176/177 (1 skipped) | pytest |
| Belief signal-to-noise ratio | ~2:1 | MEMORY_QUALITY_AUDIT.md |
| Beliefs stuck at 0.9 confidence | 98.4% | MEMORY_QUALITY_AUDIT.md |
| Correction classifier precision (production) | ~60% | MEMORY_QUALITY_AUDIT.md |
| Live conversation turns ingested | ~0.5% of captures | MEMORY_QUALITY_AUDIT.md |

---

## Top 10 Issues (Ranked by Impact)

### P0: Defects

1. **REQ-020 bug: `supersede_belief()` ignores locked flag.** Programmatic code can supersede user-locked beliefs. This directly violates the locked belief guarantee -- the system's most important trust contract.
   - Source: REQUIREMENTS_GAP_ANALYSIS.md
   - Fix: Add `if belief.locked: raise` guard in `supersede_belief()`

2. **MCP `remember` creates locked beliefs; CLI `remember` creates unlocked.** Same command, different semantics depending on interface. Users will be confused; the system will behave inconsistently.
   - Source: INTEGRATION_AUDIT.md
   - Fix: Pick one behavior and make both interfaces match

3. **`/mem:demote` calls nonexistent CLI subcommand.** Skill is broken, will error on every invocation.
   - Source: INTEGRATION_AUDIT.md
   - Fix: Change skill to call `unlock` instead of `demote`

### P1: Pipeline Gaps

4. **Feedback loop is dead code.** The `tests` table, `record_test_result()`, and `update_confidence()` exist but nothing collects data. The core differentiator ("scientific method" belief revision) is not operational. 98.4% of beliefs sit at exactly 0.9 confidence because nothing ever updates them.
   - Source: PIPELINE_AUDIT.md, MEMORY_QUALITY_AUDIT.md, DESIGN_VS_REALITY.md
   - Fix: Build retrieval-outcome tracking (was belief used? ignored? corrected?)

5. **LLM classification disabled in production.** `server.py` hardcodes `use_llm=False`. All ingestion uses the 36% accuracy offline classifier instead of the 99% Haiku path. This means the majority of beliefs are misclassified.
   - Source: PIPELINE_AUDIT.md
   - Fix: Make LLM classification the default, with offline as fallback

6. **Live conversation not flowing into memory.** 304 turns captured by logger, but ~0.5% reached the belief store. The conversation logger writes JSONL but nothing ingests it. `agentmemory-ingest-stop.sh` exists but isn't wired into settings.json.
   - Source: MEMORY_QUALITY_AUDIT.md
   - Fix: Wire the ingest hook into settings.json Stop event

7. **Correction classifier over-triggering at ~60% precision.** Negation patterns in document text are flagged as corrections even when no prior belief is being corrected. ~1,000+ misclassified beliefs.
   - Source: MEMORY_QUALITY_AUDIT.md
   - Fix: Add context requirement -- a "correction" needs a prior belief to correct, not just negation language

### P2: Missing Features

8. **No contradiction detection (REQ-002).** The retrieval path can return contradictory beliefs without flagging them. `cli.py` has a diagnostic tool but it's not in the pipeline.
   - Source: REQUIREMENTS_GAP_ANALYSIS.md

9. **Epistemic integrity suite has zero code (REQ-023/024/025/026).** Provenance metadata, session velocity, rigor tiers, and calibrated reporting -- the entire quality assurance layer is unimplemented.
   - Source: REQUIREMENTS_GAP_ANALYSIS.md

10. **Triggered beliefs and output gating not built (REQ-027 tiers 3-6).** The system stores directives but cannot detect or prevent violations. 15 triggered beliefs designed and simulated but not automated.
    - Source: DESIGN_VS_REALITY.md, REQUIREMENTS_GAP_ANALYSIS.md

---

## What Works Well

- **The core loop is solid.** Ingest -> extract -> classify -> store -> search -> score -> compress -> retrieve. This path is tested and functional.
- **Locked beliefs work as designed.** Protected from automated downgrade, loaded at session start, persist across sessions.
- **FTS5+HRR retrieval beats grep.** 100% coverage vs 92%, validated in Exp 56. HRR bridges vocabulary gaps that text search cannot.
- **Project onboarding scanner** extracts git, docs, AST, citations, directives. Works end-to-end.
- **Self-hosting is live validation.** The system manages its own project context. Real usage, not just tests.
- **176 tests pass** including 20 acceptance tests across 5 requirement groups.

---

## Stale Documentation

These files are misleading and should be updated:

| File | Issue |
|---|---|
| PIPELINE_STATUS.md | Says Stage 5 "NOT BUILT" -- it IS built |
| TODO.md | Lists research as "in progress" that's been done for weeks |
| SESSION_LOG.md | Frozen at session 1 content |

---

## Recommended Path Forward

### Phase A: Fix defects (1-2 days)
- [ ] Guard `supersede_belief()` against locked beliefs
- [ ] Align `remember` locked/unlocked between MCP and CLI
- [ ] Fix `/mem:demote` to call `unlock`
- [ ] Add input validation (reject empty strings) to MCP tools
- [ ] Add timeout to `commit-check` hook
- [ ] Fix MCP `onboard` to use scanner-to-belief ID mapping (match CLI behavior)

### Phase B: Close pipeline gaps (3-5 days)
- [ ] Enable LLM classification by default (add `use_llm` config setting)
- [ ] Wire `agentmemory-ingest-stop.sh` into settings.json (use `ingest` not `remember`)
- [ ] Wire `agentmemory-autosearch.sh` into settings.json for passive retrieval
- [ ] Fix correction classifier: require prior-belief context for correction flag
- [ ] Filter noise at ingestion: min length, skip function signatures, skip file paths
- [ ] Differentiate confidence: type-based priors, source-based priors, not flat 9.0/0.5

### Phase C: Activate the feedback loop (3-5 days)
- [ ] Build retrieval-outcome tracking: which beliefs were retrieved, used, ignored, corrected
- [ ] Wire `record_test_result()` into the pipeline
- [ ] Enable real Bayesian updating so confidence reflects actual usage
- [ ] Connect dead scoring functions (`recency_boost`, `retrieval_frequency_boost`, `uncertainty_score`)

### Phase D: Clean up (1 day)
- [ ] Update PIPELINE_STATUS.md to reflect current state
- [ ] Update TODO.md to reflect completed research
- [ ] Update SESSION_LOG.md or archive it
- [ ] Run real multi-session acceptance tests (not synthetic single-process)

---

## Audit Artifacts

| File | Contents |
|---|---|
| REQUIREMENTS_GAP_ANALYSIS.md | Per-requirement code/test/experiment coverage |
| PIPELINE_AUDIT.md | 13-stage pipeline wiring assessment |
| INTEGRATION_AUDIT.md | MCP, CLI, hooks, and skills reliability audit |
| MEMORY_QUALITY_AUDIT.md | Database statistics, belief quality, signal-to-noise |
| DESIGN_VS_REALITY.md | Architecture drift and case study coverage |
| WONDER_SYNTHESIS.md | This file (unified synthesis) |
