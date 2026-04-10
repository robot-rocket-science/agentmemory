# TODO: Agentic Memory Project

**Last updated:** 2026-04-09
**Status:** Research and planning phase. No production code.

---

## Research Tasks: Ordered by Difficulty and Dependencies

```
TIER 1 -- Quick, independent, no blockers (do first, any order)
  #40 Time as graph dimension (research, uses existing data)
  #41 Requirements traceability as graph structure (research, uses existing data)
  #33 Automatic query expansion without LLM (research + small test)

TIER 2 -- Medium, may use Tier 1 findings
  #35 Information bottleneck for belief compression (research + math, uses sentence nodes from Exp 16)
  #37 What replaces feedback loop at scale? (research, uses scaling data from Exp 15)
  #34 Multi-project belief isolation (research, uses privacy threat model)
  #31 Meta-cognition deep research (research, agent failed last time -- rerun)

TIER 3 -- Harder, builds on Tier 1-2
  #39 Gray code / binary semantic encoding (research + prototype, needs sentence nodes)
  #36 HRR prototype for beliefs (research + prototype, needs sentence nodes + possibly IB from #35)
  #42 Workflow-agnostic onboarding (design, needs sentence splitting + traceability from #40/#41)
```

### Possible dependency links (soft, not hard blockers):

- #35 (IB compression) informs #36 (HRR) -- IB tells us optimal node size, HRR encodes it
- #40 (time dimension) informs #37 (scale) -- temporal decay might solve the coverage problem
- #41 (traceability) informs #42 (onboarding) -- the traceability structure IS the onboarding model
- #33 (query expansion) informs #39 (Gray code) -- both address "how to find semantically similar content"
- #31 (meta-cognition) informs #42 (onboarding) -- self-knowledge is part of how the system bootstraps
- #37 (scale) informs #36 (HRR) -- if the feedback loop is replaced, HRR might be the replacement mechanism

## Backlog (do after top 5)

### [#22] Test information-theoretic retrieval improvements
**Blocked by:** #19 (need to know if ranking or retrieval is the gap)
**What:** MinHash, local embeddings, query expansion. Do any improve retrieval without LLM calls?

### [#23] Validate scientific method model vs alternatives
**Blocked by:** #19 and #20
**What:** Compare observe/believe/test/revise against episodic/semantic/procedural. Does our model actually produce better outcomes? Hardest validation -- may need implementation first.

### [#24] Cross-model MCP behavior differences
**Independent but lower priority**
**What:** Research how Claude, ChatGPT, Gemini, local models handle MCP tool calls differently. Affects design but not foundational theory.

## Remaining Research Tasks

**We are in planning and research phase.** No implementation until the user says it's time.

### From Case Studies (highest priority -- these are real failures we just observed)

1. **CS-004 investigation: How do locked beliefs survive context compression?** The current design has locked beliefs in SQLite, but within a single session, context compression can erase corrections. Research: how do Claude Code, ChatGPT, Gemini handle long-context compression? Can the MCP server re-inject locked beliefs after compression events? This is a new requirement dimension.

2. **CS-003 investigation: Self-referential state management.** The memory system needs to know about its own state documents (TODO.md, REQUIREMENTS.md, etc.) and consult them before asking the user. Research: how should the system's own operational state be modeled? Is it a special class of beliefs? Always-loaded meta-beliefs?

3. **Design acceptance tests from case studies.** CS-001 through CS-004 are concrete test scenarios. Write formal test protocols (like the experiment protocols) for each.

### From Open Questions in VALIDATION_AUDIT.md

4. **Scaling behavior of feedback loop.** Exp 2/5/7 tested 200 beliefs over 50 sessions. What happens at 1K, 10K, 100K beliefs over hundreds of sessions? Does Thompson sampling degrade? Does the belief graph become unwieldy?

5. **Observation/belief separation in practice.** Does keeping raw observations separate from derived beliefs actually improve provenance and conflict resolution? We argued it theoretically but have no empirical evidence.

6. **Automatic query expansion.** Exp 9 showed 3 query formulations beat 1 for FTS5. How should the system automatically generate multiple query formulations without an LLM? Stemming? Synonym tables? Co-occurrence statistics from the belief graph?

### From Research Documents

7. **Information bottleneck for belief compression.** INFORMATION_THEORY_RESEARCH.md identified the IB method (Tishby 1999) as a principled approach to "how short can a belief be while preserving query relevance?" Research: what would an IB-based belief compression look like concretely?

8. **Holographic reduced representations.** The research found strong theoretical grounding (Plate HRR, Bricken attention=SDM proof). Can we prototype a small test of HRR encoding for beliefs and compare retrieval quality to FTS5?

9. **Multi-project belief isolation.** The privacy threat model doesn't address belief isolation between projects. If the user works on project A and project B, should beliefs from A bleed into B? When should they? How is this managed?

### From the Broader Design Space

10. **What does "good enough" look like for research phase?** We need criteria for when research is sufficient and design is ready for architecture. This is a meta-question the user should answer, not the system.

## Completed Research Tasks

### ~~1. [#26] Research zero-LLM correction detection improvement~~ DONE
V2 detector: 92% on actual corrections (was 26%). Added imperative verbs, always/never, declarative, emphasis, prior references, directive patterns. Pipeline updated.

### 2. [#22] Test information-theoretic retrieval improvements
**Unblocked** (was blocked by #19, now done)
**Why:** FTS5 has vocabulary limitations. Test MinHash, local embeddings, query expansion.
**Effort:** 2-3 hours
**What:** Do any improve retrieval without LLM calls?

### 3. [#24] Cross-model MCP behavior differences
**Unblocked, lower priority**
**Why:** Different LLMs handle MCP tools differently. Affects design.
**Effort:** 1-2 hours research
**What:** How do Claude, ChatGPT, Gemini handle tool calls?

### 4. [#23] Validate scientific method model vs alternatives
**Blocked by #26**
**Why:** Hardest validation. Need correction detection resolved first.
**Effort:** 3-4 hours
**What:** observe/believe/test/revise vs episodic/semantic/procedural

---

## Completed (this session)

- [x] Literature survey (35+ systems, 6 benchmarks) -> SURVEY.md
- [x] Architecture design (scientific method model) -> PLAN.md
- [x] 29 approaches cataloged -> APPROACHES.md
- [x] 21 requirements with traceability -> REQUIREMENTS.md
- [x] Bayesian confidence model validated (Thompson + Jeffreys) -> Exp 2, 5, 5b
- [x] Alpha-seek timeline built (1,790 events) -> Exp 6A
- [x] Memory failure patterns detected (38 overrides, 6 clusters) -> Exp 6B
- [x] Before/after analysis (49% override reduction with manual enforcement) -> Exp 6C
- [x] Requirements derived from failures (REQ-019, 020, 021) -> Exp 6D
- [x] Token budget analysis (100% coverage at 1K tokens after D209 data fix; original 93% was caused by stale DB, not retrieval failure) -> Exp 4
- [x] Validation audit (methodology gaps identified) -> VALIDATION_AUDIT.md
- [x] D209 finding corrected (was data problem, not vocabulary mismatch) -> Exp 4 rerun: 100% at 1K
- [x] Exp 6 clustering verified (79% -> ~66%, dispatch_gate 13 -> 7 after removing false matches)
- [x] Zero-LLM extraction tested on real overrides (87% extract beliefs, but only 26% detect corrections)
- [x] Privacy threat model completed (416 lines, 8 threats, 9 architectural decisions) -> PRIVACY_THREAT_MODEL.md
- [x] Variable-relevance Thompson test PASSES (ECE=0.053, exploration=0.250, domain_precision=0.862) -> Exp 7
- [x] Temporal quality mapping (feature count correlates with overrides rho=+0.637; early > late quality) -> Exp 8
- [x] Correction detection V2: 26% -> 92% on actual corrections. Zero-LLM viable for REQ-019.
- [x] Privacy threat model completed (PRIVACY_THREAT_MODEL.md)
- [x] `remember` and `correct` MCP tools designed -> PLAN.md
- [x] Information-theoretic research (holographic memory, MI, Shannon entropy) -> INFORMATION_THEORY_RESEARCH.md
- [x] Bayesian research (Beta-Bernoulli, priors, conflict resolution) -> BAYESIAN_RESEARCH.md

## Design Space Explored So Far

| Area | Key Finding | Document |
|------|------------|----------|
| Bayesian confidence | Thompson + Jeffreys, validated at variable relevance (ECE=0.053) | Exp 2/5/5b/7 |
| Scaling | Degrades at 10K; hierarchical propagation helps (ECE 0.169->0.133) | Exp 15/22 |
| Granular decomposition | 86% token reduction with sentence-level nodes (1,195 from 173 decisions) | Exp 16 |
| HRR encoding | Works: 60-80% FTS5 overlap, 73x bind/unbind S/N, superposition viable | Exp 24 |
| Gray code / SimHash | SimHash on TF-IDF -> 128-bit codes, brute-force Hamming at scale | exp23_gray_code_research.md |
| Time dimension | TEMPORAL_NEXT edges + content-aware decay (constraints persist, activities fade) | exp19_time_dimension.md |
| Traceability | Aerospace DO-178C maps to our graph; our scientific method IS a traceability chain | exp17_traceability_research.md |
| Query expansion | Corpus PMI map + pseudo-relevance feedback, zero-LLM, ~5-10ms | exp18_query_expansion_research.md |
| Meta-cognition | SOAR impasse-substate analog; triggered beliefs as ECA rules; 2-level cap on regress | METACOGNITION_RESEARCH.md |
| Information bottleneck | Type-aware heuristic captures ~90% of IB benefit; full IB marginal for now | exp20_information_bottleneck.md |
| Multi-project isolation | Single DB with project_id namespace; behavioral=global, domain=scoped | exp21_multi_project.md |
| Privacy | 8 threats, local-first, cloud LLM sees context (documented tradeoff) | PRIVACY_THREAT_MODEL.md |
| Cross-model MCP | ChatGPT won't call tools proactively; server must not depend on it | exp10_cross_model_mcp.md |
| Correction detection | V2 at 92% on real data; imperative verbs + always/never + declarative | Exp 1 |
| Context compression | Hybrid persistence: CLAUDE.md + status injection + compactPrompt | exp12_context_compression.md |
| Case studies | CS-001 to CS-005: redundant work, correction loss, self-consultation, compression survival, epistemic integrity | CASE_STUDIES.md |
| Epistemic integrity | REQ-023 to REQ-026: provenance metadata, velocity tracking, rigor tiers, calibrated reporting | REQUIREMENTS.md |

## Unexplored or Underexplored Areas

These are research questions we haven't asked yet or areas where our coverage is thin:

(to be populated -- this is where we need to think about what's missing)

## Pruned (no longer relevant)

- ~~Exp 1: Zero-LLM extraction with human annotation~~ -- replaced by Exp 6 (historical data as ground truth) and #20 (extraction on real overrides)
- ~~Exp 3: BFS vs FTS5 blind labeling~~ -- partially replaced by Exp 6. Harness built but 583-item labeling not practical. May revisit with automated evaluation.
- ~~End-to-end walkthrough~~ -- premature until more fundamentals are validated
- ~~Research vocabulary mismatch~~ -- D209 was data problem, not vocabulary problem. General vocabulary mismatch addressed in #22
