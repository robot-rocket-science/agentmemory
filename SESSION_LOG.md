# Session Log: 2026-04-09

## What Happened This Session

### Research Phase
1. Launched 4 parallel research agents: lhl/agentic-memory repo analysis, prior GSD work exploration, systems survey, evaluation methodology
2. Surveyed 35+ agentic memory systems, 6 benchmarks, documented the field's credibility crisis
3. Analyzed MemPalace architecture -- conceptually similar to GSD prototype, but our graph traversal is deeper
4. Researched Bayesian statistics for belief updating -- Beta-Bernoulli conjugate priors adopted
5. Researched information-theoretic approaches: holographic memory (Plate HRR, Kanerva SDM, Bricken proof that attention=SDM), anti-cryptography (LSH, mutual information), Shannon entropy, information bottleneck

### Architecture Decisions
- Adopted scientific method model: observe/believe/test/revise (replacing human memory categories)
- Adopted Thompson sampling + Jeffreys prior Beta(0.5, 0.5) for retrieval ranking
- Rejected source-informed priors (experiments showed they're harmful)
- Designed `remember` and `correct` MCP tools for single-correction learning
- Designed session recovery with continuous checkpointing
- Added REQ-017/018 (fully local, no telemetry) and REQ-019/020/021 (single-correction learning, locked beliefs, behavioral beliefs in L0)

### Experiments Run
- **Exp 2** (Bayesian calibration): Source-informed priors FAILED. Calibration metric bug found and fixed (IGNORED denominator). Uniform priors ECE=0.042.
- **Exp 2b** (parameter sweep): 42 configs, zero pass both requirements with static exploration weight.
- **Exp 2c** (diagnosis): Root cause = IGNORED rate inflating denominator. Oracle test confirmed model works.
- **Exp 5** (explore/exploit strategies): Thompson sampling best. Phased and decoupled strategies rejected.
- **Exp 5b** (Thompson + Jeffreys): PASSES BOTH requirements. ECE=0.066, exploration=0.194. Adopted.
- **Exp 6A** (timeline): 1,790 events extracted from alpha-seek (173 decisions, 84 milestones, 1,154 commits, 775 edges)
- **Exp 6B** (failure detection): 38 overrides, 79% in 6 repeated clusters (dispatch gate=13, calls/puts=4, typing=4, capital=3, behavior=3, GCP=3)
- **Exp 6C** (before/after): Override rate dropped 49% after manual CLAUDE.md enforcement. Plateaued at 1.8/day.
- **Exp 6D** (derive requirements): 3 new requirements from failure patterns.
- **Exp 4** (token budget): 100% critical belief coverage at 1,000 tokens (after fixing D209 data error).

### Key Findings
1. The user was already building a memory system manually (CLAUDE.md rules = L0 context). Our project automates this.
2. 79% of user corrections are re-statements of things already decided. Single-correction learning (REQ-019) would prevent nearly all of them.
3. Thompson + Jeffreys naturally balances calibration and exploration without tuning parameters.
4. 1,000 tokens is sufficient for all critical beliefs. Our 2,000 token L2 budget is generous.
5. Source-informed priors are counterproductive -- they resist correction from evidence.

### Validation Audit Findings
- D209 "vocabulary mismatch" was actually missing data (FIXED)
- Exp 6 clustering (79%) needs verification -- some false matches likely
- Bayesian simulation untested with variable relevance
- Scientific method model adopted on theory, not empirical comparison
- Zero-LLM extraction built but untested on real data
- Privacy requirements stated but not designed

### Files Created/Modified
- SURVEY.md (landscape analysis)
- PLAN.md (architecture, schema, lifecycle, MCP tools)
- APPROACHES.md (29 approaches tracked)
- REQUIREMENTS.md (21 requirements with traceability)
- EXPERIMENTS.md (6 experiments with protocols and results)
- BAYESIAN_RESEARCH.md (Beta-Bernoulli implementation)
- INFORMATION_THEORY_RESEARCH.md (holographic memory, MI, entropy)
- VALIDATION_AUDIT.md (methodology self-examination)
- TODO.md (prioritized task list)
- SESSION_LOG.md (this file)
- experiments/ directory (8 Python scripts, multiple result/log files)
- pyproject.toml, uv.lock (Python project setup)

### Additional Work (continued session)

- **#25 DONE:** D209 finding corrected. Exp 4 rerun: 100% coverage at 1K tokens.
- **#18 DONE:** Exp 6 clustering audited. 79% -> ~66%. dispatch_gate 13 -> 7 after removing false matches.
- **#20 DONE:** Zero-LLM extraction on OVERRIDES.md. 87% extract beliefs, 26% detect corrections (V1).
- **#21 DONE:** Privacy threat model. 416 lines, 8 threats, 9 architectural decisions. Key: "fully local" = memory system makes zero network calls, but cloud LLM sees context.
- **#19 DONE:** Variable-relevance Thompson test. PASSES: ECE=0.053, exploration=0.250, domain_precision=0.862. Better than uniform relevance.
- **#27 DONE:** Temporal quality mapping. Feature count positively correlates with overrides (rho=+0.637). Early project higher quality than late. Context drift at scale confirmed.
- **#26 DONE:** Correction detection V2. 26% -> 92% on actual corrections. Zero-LLM viable for REQ-019. Imperative verbs (34%), negation (29%), declarative (21%), always/never (18%) are the key patterns.
- **Exp 7** (variable relevance): Thompson + Jeffreys works even better with variable relevance.
- **Exp 8** (temporal quality): Mapped productive vs chaotic days across project timeline.

### Additional Work (continued)
- **#22 DONE:** Info-theoretic retrieval. FTS5 baseline already 100% with 3 query variants. MinHash alone 31% (poor). Query formulation > retrieval algorithm.
- **#24 DONE:** Cross-model MCP. ChatGPT won't proactively call tools; Claude will. Architecture decision: server must not depend on model calling tools.
- **#23 DONE:** Scientific method validation. The advantage is the feedback loop, not the category names. Validated conceptually; full comparison needs implementation.
- **Exp 9** (retrieval improvements): FTS5 sufficient. MinHash poor. Query expansion is the real lever.
- **Exp 10** (cross-model MCP): Behavior differs fundamentally by model training. Server must be model-agnostic.
- **Exp 11** (model comparison design): Framed but deferred to implementation phase.

### Continued Research (session 2)

- **Exp 25 (combined retrieval):** All methods redundant on this dataset with BoW encoding. D157 missed by all.
- **Exp 26 (real topology hierarchical):** No difference at 586 nodes. Hierarchical only matters at 5K+.
- **Exp 27 (epistemic schema):** Designed schema for REQ-023-026. Rigor tiers, provenance, velocity.
- **Exp 28 (directive detection):** LLM-in-the-loop solves vocab mismatch. `directive` tool with `related_concepts`.
- **Exp 29 (sentence vs decision retrieval):** Windowed sentences win: 12/12 vs 11/12, more breadth.
- **Exp 30-31 (real HRR):** 5/5 single-hop within capacity. Global superposition fails (over capacity).
- **Exp 32 (HRR edge discovery):** FAILED. Precision 0.001. HRR can't discover edges autonomously.
- **Exp 33 (HRR bootstrap):** D097 at rank 2 via partial graph bootstrap. Useful for proposals, not discovery.
- **Exp 34 (closing HRR tests):** Vocabulary bridge 184x separation. Multi-hop iterative: D097 rank 1. Combined pipeline inconclusive.
- **Exp 35 (multi-hop improvements):** Weighting + beam search don't improve recall (1/3 for all methods). SNR limit is fundamental.
- **Case studies CS-001 to CS-005** documented as acceptance tests.
- **REQ-023 to REQ-027** added (epistemic integrity, directive enforcement).
- **OPEN_QUESTIONS.md** created with F1-F5, R1-R3, D1-D3.
- **HRR_FINDINGS.md** comprehensive with all evidence.
- **Architecture split established:** FTS5 (keywords) + HRR single-hop (vocabulary bridge) + BFS (exact multi-hop) + HRR iterative (fuzzy multi-hop).

### Status
Research and planning phase. 27 requirements. 35 experiments. ~16 open research threads in OPEN_QUESTIONS.md. No implementation.

### Files Created This Session
Total: 24 files in project root + experiments/ directory.
Key documents: SURVEY.md, PLAN.md, APPROACHES.md, REQUIREMENTS.md, EXPERIMENTS.md, BAYESIAN_RESEARCH.md, INFORMATION_THEORY_RESEARCH.md, PRIVACY_THREAT_MODEL.md, VALIDATION_AUDIT.md, TODO.md, SESSION_LOG.md
