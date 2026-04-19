---
name: Project agentmemory
description: Current state, decisions, and open threads for the agentmemory project
type: project
---

## What This Project Is

Building an agentic memory system for LLMs -- MCP server backed by SQLite, stores observations (immutable) and beliefs (Bayesian confidence), typed graph for retrieval. Scientific method model: observe/believe/test/revise. Zero-LLM by default.

**Status:** Research phase only. No production code. One session (~1 day) of high-velocity work.

**Why:** Calibration note for new agents -- all research was done in ~1 day of fast prompting. Findings are hypotheses and simulations, not validated results. Do not describe as "extensive" without qualification. See CS-005 in CASE_STUDIES.md.

## Key Architecture Decisions (stable)

- SQLite + WAL, fully local, zero network calls from memory server
- Scientific method model: observation/belief/test/revision (not human memory categories)
- Thompson sampling + Jeffreys prior Beta(0.5,0.5) for retrieval ranking (validated in simulation)
- MCP server interface, cross-model from day one
- Zero-LLM default; local models are a first-class privacy option
- Progressive context loading: L0 (always-loaded behavioral) / L1 / L2 / L3 (deep on-demand)

## Where We Left Off (2026-04-09)

### What was completed this session

- Literature survey, architecture design, 9 experiments (Exp 1-9)
- Exp 2/5b: Thompson + Jeffreys ECE=0.066, exploration=0.194 -- PASSING
- Exp 6: 38 overrides, ~66% are repeated topics (was 79%, corrected after audit)
- Exp 26: Real HRR vs BFS on project-a graph (586 nodes, 775 edges, n=8192)
  - Single-hop forward R@10=0.667, reverse R@10=0.881
  - Two-hop (S^2) failed completely -- near-saturated at 85% capacity
  - Correct two-hop: iterative with cleanup memory (vectorized BFS, no LLM)
  - Real value of HRR over BFS: fuzzy starting queries, not multi-hop mechanics

### Research documents produced

- PLAN.md -- architecture, schema, MCP tools, session recovery
- REQUIREMENTS.md -- REQ-001 through REQ-030
- APPROACHES.md -- 29 approaches tracked, A016 (HRR) has real exp26 results
- EXPERIMENTS.md -- protocols for Exp 1-9+
- CASE_STUDIES.md -- CS-001 through CS-005 (CS-005 is project maturity inflation)
- PRIVACY_THREAT_MODEL.md -- T1/T2 unmitigable (cloud LLM properties), T3 hygiene-only, T4-T7 mitigable
- HRR_RESEARCH.md -- full math + exp26 findings + S^2 vs iterative analysis
- GRAPH_CONSTRUCTION_RESEARCH.md -- typed nodes, edge weights, epistemic uncertainty, interview loop
- INFORMATION_THEORY_RESEARCH.md, BAYESIAN_RESEARCH.md, SURVEY.md

### Open design threads

1. **Interview loop for uncertainty:** When conflict_ratio or entropy is above threshold (TBD), system enters back-and-forth interview loop (GSD-style) until uncertainty drops below acceptable level (TBD). Not one question -- as many as needed.

2. **Edge weight uncertainty signal:** SUPPORTS and CONTRADICTS both feed `conflict_ratio = contradict_weight / (support_weight + contradict_weight)`. Near 0.5 = maximum uncertainty. Thresholds: TBD. CRITICAL: contradicted nodes are NOT penalized in traversal -- they are PRIORITIZED in the escalation queue. Weighted BFS uses SUPPORTS weights for confidence ranking only. CONTRADICTS is a separate escalation signal.

3. **Typed nodes:** Node types (OBSERVATION, BELIEF with subtypes, TEST, REVISION, SESSION, MILESTONE) with edge constraint table. Low cost, prevents silent graph corruption at scale.

4. **HRR in architecture (v2):** Real value is fuzzy-start traversal, not multi-hop. Iterative HRR = vectorized BFS. S^2 doesn't scale. Defer to v2 pending confirmation retrieval is the bottleneck (Exp #22 shows it may not be).

5. **REQ-028/029/030** newly added -- epistemic state tagging, uncertainty-triggered interview sessions, edge weights from confidence.

6. **TBD thresholds throughout** -- interview loop exit threshold, conflict_ratio escalation threshold, confidence tiers. Leave as TBD; numbers will come from experiments.

### Next logical steps (from TODO.md)

- Design the interview loop MCP tool (what questions it generates, how it loops)
- Add REQ-028/029/030 formally to REQUIREMENTS.md with full traceability
- Decide whether research phase is sufficient to begin architecture/implementation
