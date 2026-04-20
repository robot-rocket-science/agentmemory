# Wonder: Loose Ends and Unanswered Questions (2026-04-19)

Query: "unanswered questions, loose ends, hanging feature branches, unimplemented
features, bug fixes needed, angles to improve user experience, overall performance,
match code with claims and design intent and requirements"

## 1. Stale Documentation (High Priority)

DESIGN_VS_REALITY.md lists 7 features as "NOT BUILT" that are all now built:
- Feedback loop (Exp 66, auto-feedback in server.py)
- Triggered beliefs (TB-01 through TB-15, Phase 4)
- Output gating (TB-10 PreToolUse directive gate)
- Provenance metadata (rigor_tier, method, sample_size, Phase 5)
- Session velocity tracking (velocity_items_per_hour in sessions)
- Contradiction detection (flag_contradictions in retrieve)
- Calibrated status reporting (improved status() output)

This doc actively misleads anyone reading it.

## 2. Hanging Branches (4 remaining)

| Branch | Status | Action |
|--------|--------|--------|
| feature/org-migration | Blocked (GitHub username locked) | Keep |
| claude/clarify-benchmark-notes-OeWOG | Merged to main | Force-delete |
| docs/update-project-status | Superseded by rebase | Force-delete |
| fix/live-pipeline-gaps | All work in main | Force-delete |

## 3. Requirements Gap

REQ-011 (cross-model MCP testing) is the only unclosed requirement. Blocked on
ChatGPT/Gemini MCP access.

## 4. UX Pain Points

User stated: "need to fix onboarding, mcp install and tool call issues,
/mem:command problems" and "not production-ready because we need the / commands
and the onboarding and install to be flawless."

- Install flow not tested end-to-end on a clean machine
- MCP registration uses --project . (only works from agentmemory dir)
- 17 /mem commands exist but untested by external users

## 5. Retrieval Quality Gaps

| Limitation | Impact | Potential Fix |
|------------|--------|--------------|
| Semantic gap | "database choice" misses "PostgreSQL" | Entity-aware L2 expansion |
| Negation noise | "don't use X" matches "use X" | Negation-aware scoring |
| Cold start | New projects have no beliefs | Faster onboarding |
| Single-user | No multi-user isolation | Project-level separation (untested) |

## 6. Claims vs Evidence

| Claim | Evidence | Gap |
|-------|----------|-----|
| Memories get stronger over time | Feedback loop, +22% MRR sim | No longitudinal production data |
| System tunes itself | Thompson sampling implemented | Simulation only |
| Works with any MCP agent | Claude Code only | REQ-011 open |
| Correction rate decreases | 1.7% -> 0.5% trend | n=15, not significant |
| Token reduction | Budget fill improving | No reduction in total usage |

## 7. Open Experiments

| Exp | Question | Status |
|-----|----------|--------|
| 67-70 | Locking, priors, recency, top_k | Designed |
| 85 | LoCoMo multi-run variance | Planned |
| 86 | Retrieval-reader isolation | Planned |
| 87 | Multi-query LongMemEval | Planned |
| 88 | Correction burden A/B | Preliminary done |
| 89 | FTS5 query reformulation | Planned |

## 8. Architecture Angles

- Belief promotion (core -> locked) -- auto-promote consistently-used beliefs
- Belief deletion -- needs careful design for graph integrity
- Local model support -- privacy feature, not nice-to-have
- SQLite encryption (sqlcipher) -- optional for sensitive projects
- Temporal evolution tracking -- no way to trace how thinking evolved
