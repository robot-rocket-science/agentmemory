# TODO: Agentic Memory Project

**Last updated:** 2026-04-10
**Status:** Research and planning phase. No production code.

---

## Research Tasks: Ordered by Difficulty and Dependencies

```
TIER 1 -- COMPLETED
  #40 Time as graph dimension -- DONE (exp19, REVISED exp57-60).
      Original: Model 3 + Model 2 combined scoring. Exp 57: combined scores 55%, decay-only 100%.
      Revised: decay for SCORING (locked immune, content-type half-lives). TEMPORAL_NEXT for TRAVERSAL only.
      Exp 58: half-life insensitive at 13d scale; locked-belief immunity is the dominant signal.
      Exp 59: TEMPORAL_NEXT required for 2/10 query types (adjacency). SUPERSEDES for 1/10 (evolution chains).
      Exp 60: LOCK_BOOST_TYPED re-ranking on FTS5+HRR: MRR 0.589->0.867, 100% coverage at K=30.
      Remaining open Qs: half-life calibration at month+ scale, cross-project spans, decay vs Bayesian interaction.
  #41 Requirements traceability -- DONE (exp17 research + exp41 extraction). 101 entities, 1,504 edges, 17 coverage gaps found.
  #33 Automatic query expansion -- DONE (exp18 research + exp39 empirical). PRF adopted, PMI auxiliary, 8% gap confirms hybrid retrieval.

TIER 2 -- COMPLETED
  #35 Information bottleneck -- DONE (exp42). Type-aware heuristic validated: 55% token savings, 100% retrieval coverage.
      Full IB not justified. HRR DIM >= 2048 (info-bound for constraints). Dual-mode storage adopted.
  #34 Multi-project isolation -- DONE (exp43). Keyword heuristic 93% unambiguous but 47% accuracy (needs human-in-loop).
      Pre-filter (WHERE clause) only safe option. 3 scope levels: global/language/project. No framework tier needed.
  #31 Meta-cognition -- DONE (exp44). 15 triggered beliefs designed. FOK protocol: 50ms cap. 2-level depth confirmed.
      Directive enforcement is 3-TB pipeline. Overhead ~313ms/session, 100x+ ROI. Token budget is real constraint.
  #37 What replaces feedback loop at scale? -- DONE (exp38). Source-stratified priors dominate (21x ranking quality).
      Feedback loop shifts to "correct exceptions" not "calibrate all."

TIER 3 -- COMPLETED
  #36 HRR prototype -- DONE (exp45). Decision-neighborhood partitioning: 100% single-hop recall at DIM=2048 and 4096.
      Sentence-level FTS5 partly closes vocabulary gap (D157_s6 has "agent"). HRR role shifts to structural retrieval.
      19 MB at 1K nodes, 160 MB at 10K. Lazy loading makes 100K feasible.
  #39 SimHash -- DONE (exp46). NEGATIVE RESULT. 1.04x separation (near-random). Not viable for retrieval pre-filter
      or drift detection. Short sentences produce sparse TF-IDF -> hash bits dominated by noise.
      FTS5 + HRR remain co-primary retrieval axes. SimHash rejected for this use case.

TIER 3 -- IN PROGRESS (other session)
  #42 Workflow-agnostic onboarding (design, being worked on in parallel session)
```

### Remaining dependency links (soft, not hard blockers):

- #35 (IB compression) informs #36 (HRR) -- IB tells us optimal node size, HRR encodes it
- #41 (traceability, done) informs #42 (onboarding) -- the traceability structure IS the onboarding model
- #33 (query expansion, done) informs #39 (Gray code) -- both address "how to find semantically similar content"
- #31 (meta-cognition) informs #42 (onboarding) -- self-knowledge is part of how the system bootstraps
- #37 (scale, done) informs #36 (HRR) -- source priors handle scale; HRR role is vocabulary bridge, not scaling fix

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
| Time dimension | **REVISED (Exp 57).** Decay-only scores 100% vs adopted 55% on case study scenarios. Structural recency penalizes locked beliefs. Fix: decay for scoring, TEMPORAL_NEXT for traversal only. Separate concerns. | exp19_time_dimension.md, **Exp 57** |
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
| Control/data flow | CALLS + PASSES_DATA from AST; Jaccard 0.012 vs CO_CHANGED (disjoint layers); 18.9% resolution rate (Python method calls); Tier 2.5 adopted | CONTROL_DATA_FLOW_RESEARCH.md, Exp 37 |
| Feedback loop scaling | Source-stratified priors dominate: ECE 0.034 vs 0.076 at 50K, ranking quality 21x better. Feedback loop role shifts to "correct exceptions" not "calibrate all." Combined mechanism (source + hierarchical + graph prop) is production config. | FEEDBACK_LOOP_SCALING_RESEARCH.md, Exp 38 |
| Query expansion | PMI map excellent for domain associations but hurts FTS5 coverage (dilutes BM25). PRF maintains baseline. 92% coverage irreducible with text methods; 8% gap (D157) requires graph traversal. Validates hybrid retrieval. | QUERY_EXPANSION_RESEARCH.md, Exp 39 |
| Traceability extraction | 101 entities (29 REQ, 38 CS, 14 approach, 20 exp), 74 labeled edges, 1,430 co-occurrence. 17 coverage gaps: 7 REQs without experiment verification, 8 EXPs not linked to REQs, 1 orphan approach, 1 fully orphan REQ. | exp17_traceability_research.md, Exp 41 |
| **Hybrid retrieval pipeline** | **FTS5+HRR combined achieves 100% (13/13), matching hand-crafted 3-query. D157 rescued via AGENT_CONSTRAINT walk from D188 (sim=0.2487). Max 2.1x result inflation. Zero regressions. Architecture validated end-to-end.** | HRR_VOCABULARY_BRIDGE.md, Exp 40 |
| **Onboarding pipeline** | H1 PASS (89-100% LCC). H2 PASS (87-93%, dual-mode needed). H3 PARTIAL PASS (20% HRR). H4 PASS. Heuristic 30-47% on hard cases; LLM-verify adopted (A032): 2,650 tokens, 11.5x ROI, $0.001/project. Correction burden reframed as core metric. | ONBOARDING_RESEARCH.md, Exp 49-49d/50, CORRECTION_BURDEN_REFRAME.md |
| IB belief compression | Type-aware heuristic: 55% token savings (35.7K->15.9K), 100% retrieval coverage preserved. Full IB not justified (0-5% marginal). HRR DIM >= 2048 (info-bound for constraints, SNR-bound for rest). Dual-mode: full text for FTS5, type-compressed for injection. | Exp 42 |
| Multi-project isolation | Keyword heuristic: 93% unambiguous, 47% accuracy (5 FP from pyright tips). Pre-filter only safe option (post-filter/penalty leak under bugs). 3 scope levels: global/language/project. Separate HRR vectors per project with shared global nodes. | Exp 43 |
| Meta-cognition design | 15 triggered beliefs (TB-01 to TB-15) mapped to CS-003/005/006/020. FOK protocol: 50ms, 5-step. 2-level cap confirmed (SOAR/CLARION/ACT-R). Directive enforcement: 3-TB pipeline (TB-02/03/10). Overhead: 313ms + 2,350 tokens/session. Token budget is the real constraint at >10 directives. | Exp 44 |
| HRR belief prototype | Decision-neighborhood partition: 100% single-hop recall (39/39) at DIM=2048 and 4096. Sentence-level FTS5 partly closes vocab gap (D157_s6 matched via "agent"). HRR role shifts from "bridge FTS5 gaps" to "query-independent structural retrieval." 19 MB at 1K nodes, lazy loading feasible to 100K. | Exp 45 |
| SimHash binary encoding | **NEGATIVE RESULT.** 1.04x related/unrelated separation (near-random). Requires K>=45 for retrieval (no selectivity). Drift detection not viable (0.98x ratio). Root cause: short sentences -> sparse TF-IDF -> hash bits dominated by noise. SimHash rejected; FTS5+HRR confirmed as co-primary axes. | Exp 46 |
| **Baseline comparison** | **RESOLVED: WE BEAT GREP.** Exp 47 showed grep 92% vs FTS5+HRR 85% due to K=15 cutoff and union ordering. Exp 56 corrected: FTS5 K=30 + HRR = 100% (13/13) vs grep 92% (12/13). D137 recovered by wider K; D157 recovered by HRR walk. Both DIM=2048 and 4096 achieve 100%. Grep cannot bridge vocabulary gaps; HRR can. | Exp 47, **Exp 56** |
| **Multi-layer at scale** | **ALL METHODS DEGRADED.** At 16K nodes: grep 85%, FTS5 69%, FTS5+HRR 69%. Belief nodes 3.6% of graph, drowned by file/sentence/callable noise. Temporal edges 0 unique signal (commits don't reference D### IDs). Two disconnected subgraphs with no cross-type bridges. **Root cause: type-blind retrieval.** Fix: type-weighted BM25, type-filtered search, commit-to-decision linking. Extraction fast (16K in 1.87s, 71K in 4.06s). | Exp 48 |
| **Type-filtered FTS5** | Type filtering (exclude file/callable/commit) recovers FTS5 from 69%->77% (+7.7pp). Grep unchanged at 85%. Necessary but not sufficient -- doc sentences (71% of filtered set) still dominate BM25. D137/D100/D157 are lexical gaps, not dilution. Next: type-weighted BM25 or two-stage retrieval. | Exp 52 |
| **Vocabulary gap prevalence** | **31% of directives are text-unreachable** across 5 projects (3,321 directives, 1,030 gaps). 99.5% HRR-bridgeable via co-location edges. Emphatic prohibitions (29%) and uncategorized (34%) dominate gap types, not tool bans (12%). Doc-rich projects have HIGHER gap rates (33% vs 25%), not lower. HRR is essential infrastructure, not optional. | Exp 53 |
| MI re-ranking | **NEGATIVE RESULT.** PMI/NMI hurt MRR vs BM25 (-12.4% / -4.4%). | Exp 54 |
| Rate-distortion budget | **NEGATIVE RESULT.** Zero improvement; budget never binding at current scale. | Exp 55 |
| **Corrected baseline** | **WE BEAT GREP.** FTS5 K=30 + HRR = 100% (13/13) vs grep 92% (12/13). D137 recovered by wider K; D157 by HRR walk. Retrieval should be generous, injection selective. | **Exp 56** |
| **Time architecture** | **CRITICAL: adopted model WRONG.** Structural recency penalizes locked beliefs. Decay-only scores 100% vs adopted 55%. Fix: decay for scoring, TEMPORAL_NEXT for traversal only. | **Exp 57** |
| **Decay calibration** | Exp 58 (13d): insensitive. Exp 58b (4mo): top10 13%->73%. Exp 58c: hour-scale solves CS-005 (fast-sprint 0.273 vs locked 0.804). **27% failure analysis: not a decay gap.** 40% are decisions that don't exist yet (correction detection handles, 92%). 60% are ranking issues solved by retrieval+LOCK_BOOST. Full pipeline stack addresses all modes. | **Exp 58, 58b, 58c, failure analysis** |
| **Traversal utility** | TEMPORAL_NEXT required for 2/10 queries (adjacency). SUPERSEDES required for 1/10 (evolution chains). Timestamps handle 7/10. Keep both edge types for traversal, not scoring. | **Exp 59** |
| **Temporal re-ranking** | LOCK_BOOST_TYPED on FTS5+HRR: MRR 0.589->0.867, 100% coverage at K=30. Pure LOCK_BOOST is harmful (drops K=15 to 85%). Decay alone is safe but weak at short timescales. | **Exp 60** |

## Major Gaps (ordered by risk to architecture)

```
GAP 1 -- CLOSED (Exp 56). WE BEAT GREP.
  FTS5 K=30 + HRR = 100% (13/13) vs grep 92% (12/13). Exp 47's failures were
  engineering issues (K=15 cutoff, union ordering), not fundamental limitations.
  D137 recovered by wider K; D157 recovered by HRR walk (only method that can).
  Architectural implication: retrieval should be generous, injection should be selective.

GAP 7 -- DEFERRED (not a blocker). Multi-layer extraction refinement.
  Exp 48 showed disconnected subgraphs in the 16K-node multi-layer graph.
  But Exp 56 validated retrieval without multi-layer (100% on belief-only graph).
  Cross-type bridging (commit-to-decision, file-to-belief) improves extraction
  quality but is not required for the core pipeline. Address during implementation.

GAP 2 -- CLOSED (A032, Exp 50). LLM-verify at 99% accuracy, $0.001/project, 11.5x ROI.
  Keyword heuristic 47% was the baseline. Haiku classification closes the gap.
  Adopted in session 5.

GAP 3 -- CLOSED (Exp 48)
  Triggered beliefs simulated against 5 case studies: 5/5 failures prevented.
  No conflicts in multi-event test. 420 tokens, 83ms per session (under budget).
  CS-006 (locked prohibition) triggers 6 TBs including output blocking.

GAP 4 -- CLOSED (Exp 45b/45c, this session)
  Onboarding H2/H3 validated. H2 PASS (87-93%). H3 PARTIAL PASS (20% HRR value).

GAP 5 -- THIS IS THE TOP GAP. RESEARCH IS DONE.
  No multi-session test. REQ-001 needs a running SQLite + MCP skeleton.
  This gap cannot be closed by more research. It requires implementation.

GAP 6 -- CLOSED (Exp 55, Exp 42, Exp 60). TOKEN BUDGET IS NOT BINDING.
  Exp 55: rate-distortion optimization shows budget never binding at current scale.
  Exp 42: type-aware compression gives 55% savings (1,500 -> 675 tokens).
  Exp 60: full pipeline fits in ~1,500 tokens raw, well under 2K budget.
  TB-03 per-turn injection at >10 directives is a design parameter, not research.

GAP 8 -- CLOSED (Exp 57-60 + failure analysis). TIME ARCHITECTURE VALIDATED.
  Original Model 3+2 combined scoring was wrong (55%). Revised architecture:
  - SCORING: decay + locked immunity + supersession penalty + velocity scaling (Exp 57, 58b, 58c)
  - TRAVERSAL: TEMPORAL_NEXT for adjacency queries, SUPERSEDES for evolution (Exp 59)
  - INTEGRATION: LOCK_BOOST_TYPED re-ranking on FTS5+HRR, MRR 0.589->0.867 (Exp 60)
  - 27% decay ceiling is not a gap: 40% = beliefs not yet created (correction detection),
    60% = ranking without retrieval filter (solved by FTS5+HRR+LOCK_BOOST). Full stack covers all.
```

## Unexplored or Underexplored Areas

These are research questions we haven't asked yet or areas where our coverage is thin:

- HRR partition strategy resolved (Exp 45: decision-neighborhood wins)
- Sentence splitting for non-English / mixed-content documents
- Threshold for full re-onboarding vs incremental after major restructures
- Cross-project behavioral belief promotion mechanism
- Onboarding provenance and extractor versioning

## Pruned (no longer relevant)

- ~~Exp 1: Zero-LLM extraction with human annotation~~ -- replaced by Exp 6 (historical data as ground truth) and #20 (extraction on real overrides)
- ~~Exp 3: BFS vs FTS5 blind labeling~~ -- partially replaced by Exp 6. Harness built but 583-item labeling not practical. May revisit with automated evaluation.
- ~~End-to-end walkthrough~~ -- premature until more fundamentals are validated
- ~~Research vocabulary mismatch~~ -- D209 was data problem, not vocabulary problem. General vocabulary mismatch addressed in #22
