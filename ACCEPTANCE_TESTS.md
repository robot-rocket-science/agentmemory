# Acceptance Tests: Derived From Case Studies CS-001 through CS-022

**Date:** 2026-04-10
**Purpose:** Concrete pass/fail criteria for validating the memory system against real observed failures.
**Source:** Every test maps to a documented case study with a verbatim failure transcript.
**Rule:** A test passes only when the failure condition is impossible, not just unlikely.

---

## Test Registry

| CS | Scenario | Pass Criterion | Components Required |
|---|---|---|---|
| CS-001 | User requests task completed 30 seconds ago | Agent says "already done" + lists what was updated. Does NOT re-execute. | FTS5 (recent observation search) |
| CS-002 | User corrects "no implementation" once | Zero implementation suggestions after first correction. Holds indefinitely. | Locked beliefs, L0 behavioral, REQ-019 |
| CS-003 | All tasks done, agent about to ask "what's next?" | Agent reads TODO.md before asking. Never overwrites state doc without reading it first. | TB-01, FTS5 (state doc lookup), L0 behavioral |
| CS-004 | Locked correction issued before context compression | Locked belief survives compression verbatim. Agent obeys without re-prompting. | Locked beliefs, TB-06 (compression survival) |
| CS-005 | New session on 4-hour-old project | Status summary includes time spent, rigor tier per finding, and does NOT say "extensive" or "validated" for quick-sprint work. | Source priors, provenance metadata, TB-05 (FOK check) |
| CS-006 | "No implementation" stored in memory; new session starts | Status response contains zero references to implementation, building, or phase transition. | Locked beliefs, TB-02/03/10, output gating |
| CS-007 | Extraction produces 11K edges, asked "how solid?" | Agent distinguishes volume from precision. Identifies what validation is still needed. | Rigor tier tracking, TB-14 (FOK rigor check) |
| CS-007b | Structural validation run (neg sampling, clustering) | Agent reports "not random" is necessary-but-not-sufficient. Identifies precision measurement gap. | Rigor tier tracking, tautological validation detection |
| CS-008 | Experiment: 100% precision (narrow), 19% recall | Agent leads with scope and limitations. Presents precision AND recall together. | L0 behavioral (results-reporting rule), REQ-019 |
| CS-009 | Correction "use B not A" issued. Session resets. | Agent starts with B, not A. Holds across unlimited session boundaries. | COMMIT_BELIEF, SUPERSEDES edges, locked beliefs |
| CS-010 | "Write tests" requested | Agent prioritizes untested critical-path code over already-tested utilities. | TESTS edges, TEST_COVERAGE_GAP composite |
| CS-011 | Multi-run sweep about to launch | Agent runs single config locally before dispatching. Checks resource constraints. | COMMIT_BELIEF, behavioral constraint |
| CS-012 | Python file edited by agent | File parses without SyntaxError after every edit. | L0 behavioral ("verify parse after edit") |
| CS-013 | gcloud filter command being written | Correct syntax used. Tool-specific correction retrieved at command time. | COMMIT_BELIEF, FTS5 retrieval |
| CS-014 | Research says "use --delta-lo 0.10"; execution runs | Execution includes all research-specified flags. Missing flags detected before run. | IMPLEMENTS edges, BFS traversal |
| CS-015 | Agent proposes approach X | System checks X against dead approaches. If match, surfaces the killing decision. | SUPERSEDES edges, FTS5 + HRR |
| CS-016 | Data shows puts underperform; agent considers removing | Agent acknowledges data but does NOT suggest removing puts. Cites D073 if asked. | Locked beliefs, output gating |
| CS-017 | Default parameter changed in one commit | System identifies all call sites relying on that default. Flags for review. | CO_CHANGED, COMMIT_BELIEF |
| CS-018 | Milestone completion check with conflicting sources | System detects roadmap vs DB discrepancy before declaring complete. | IMPLEMENTS edges, consistency check |
| CS-019 | Multi-stage pipeline declared complete | End-to-end test verified to have run (not just per-stage tests). | CALLS/PASSES_DATA, BFS from entry point |
| CS-020 | User says "Build #41." | File numbered 41, not 40. Collision with existing exp40 detected before write. | TB-04, L0 belief ("current task is #41"), collision detection |
| CS-021 | Research task requested | Before "done," verify: hypotheses, protocol, results, analysis present. If missing, flag as design. | TB-14, research quality gate |
| CS-022 | "Get current positions" for 4 paper trading agents | All 4 agents identified. Correct machine (local, not willow). All 4 states read in 1 turn. Aggregated table returned. | COMMIT_BELIEF, CONTAINS edges, CALLS edges, behavioral belief (machine location), HRR traversal |

---

## Component Coverage Analysis

How many case studies depend on each component:

| Component | Case Studies | Count | Priority |
|-----------|-------------|------:|----------|
| Locked beliefs / L0 behavioral | 001, 002, 003, 004, 006, 008, 009, 011, 012, 016, 020 | 11 | **Critical** |
| COMMIT_BELIEF (git-derived) | 009, 011, 012, 013, 017, 022 | 6 | High |
| FTS5 retrieval | 001, 003, 009, 013, 015, 022 | 6 | High |
| Triggered beliefs (TB-01 to TB-15) | 003, 004, 005, 006, 020, 021 | 6 | High |
| Source priors / provenance | 005, 007, 007b, 008, 021 | 5 | High |
| SUPERSEDES edges | 009, 011, 015, 017 | 4 | Medium |
| IMPLEMENTS / CALLS / CO_CHANGED | 014, 017, 018, 019, 022 | 5 | Medium |
| Output gating (enforcement) | 006, 016 | 2 | **Critical** (severity, not count) |
| HRR typed traversal | 009, 015, 022 | 3 | Medium |
| TESTS / coverage edges | 010 | 1 | Low |

### What This Tells Us About Implementation Priority

**Locked beliefs + output gating are the #1 priority.** 11 case studies require locked beliefs, and the 2 that require output gating (CS-006, CS-016) are among the most severe failures (multi-session correction violations). Without locked beliefs that gate output, the system cannot prevent the user's most frequent correction: "I already told you not to do that."

**COMMIT_BELIEF + FTS5 are the foundation.** 12 case studies between them. These are the retrieval backbone. The system needs to find stored knowledge (FTS5) from durable sources (git-derived beliefs).

**Triggered beliefs are the enforcement layer.** 6 case studies require TBs. Without them, the system stores knowledge but doesn't act on it (the CS-006 pattern: "correction stored, correction read, correction violated").

---

## Execution Protocol

### Phase 1: Unit Tests (No Running System Needed)

These can be tested with the current experiment infrastructure:

| Test | How to Run | Status |
|------|-----------|--------|
| CS-003 (TB-01 self-check) | Exp 48 simulation | **DONE** (5/5 prevented) |
| CS-005 (TB-05 FOK check) | Exp 48 simulation | **DONE** (5/5 prevented) |
| CS-006 (TB-02/03/10 output gate) | Exp 48 simulation | **DONE** (5/5 prevented, output blocked) |
| CS-020 (TB-04 task ID verify) | Exp 48 simulation | **DONE** (5/5 prevented) |
| CS-021 (TB-14 research quality) | Exp 48 simulation | **DONE** (5/5 prevented) |

#### What Phase 1 Proves vs What It Doesn't

Phase 1 tests are **trace-based simulations**, not live tests. They replay the event sequence from each case study and verify the TB activation logic: the right events trigger the right conditions, which trigger the right actions.

**What Phase 1 proves:**
- The TB registry's event/condition/action mappings are correct for all 5 tested case studies
- Priority ordering resolves without conflicts
- Session overhead is within budget (420 tokens, 83ms)
- The *detection* mechanism works: the system would notice the problem

**What Phase 1 does NOT prove:**
- That the *recovery* works after detection. TB-10 blocks output for CS-006, but we didn't test what the replacement output looks like. Blocking bad output is half the job; producing correct output is the other half.
- That TBs work in a live agent loop where events arrive unpredictably, conditions depend on real database state, and actions must compose with the agent's response generation.
- That the TB overhead (420 tokens, 83ms) holds under real conditions where multiple TBs might fire per turn with real FTS5 queries instead of simulated ones.
- That TB-14 (research quality gate) can actually distinguish a design spec from research in practice. The simulation checked "does the output claim validation?" but didn't test the FOK check's ability to verify rigor tiers against real document content.

**The gap:** Phase 1 validates the alarm system rings. Phase 2 must validate that the alarm leads to the correct response. Phase 3 must validate the complete loop: detect problem -> block output -> produce correct replacement -> user never sees the failure.

### Phase 2: Integration Tests (Requires SQLite + MCP Skeleton)

| Test | Requires |
|------|---------|
| CS-001 (duplicate detection) | Observation store + recent-query FTS5 |
| CS-002/004/006/016 (locked beliefs across sessions) | Belief store + locked flag + multi-session test harness |
| CS-009 (correction persists across resets) | SUPERSEDES edges + belief retrieval |
| CS-022 (multi-hop operational query) | Full graph: file_tree + COMMIT_TOUCHES + CALLS + behavioral beliefs + HRR |

### Phase 3: Acceptance Tests (Requires Full System)

| Test | Requires |
|------|---------|
| CS-005/007/008/021 (calibrated reporting) | Provenance metadata + rigor tiers + FOK protocol |
| CS-010/014/017/018/019 (code-level coverage) | IMPLEMENTS/CALLS/TESTS edges + graph traversal |
| CS-011 (resource constraint checking) | Behavioral beliefs + pre-dispatch checks |
| CS-015 (dead approach detection) | Full approach history + SUPERSEDES edges + HRR vocabulary bridge |

---

## Success Criteria for Implementation

The memory system is ready for production when:

1. **All Phase 1 tests pass** (TB simulation). Status: **DONE** (Exp 48).
2. **All Phase 2 tests pass** (SQLite + MCP integration). Status: NOT STARTED.
3. **>= 80% of Phase 3 tests pass** (full system). Status: NOT STARTED.
4. **Zero regressions** on any previously-passing test when new features are added.
5. **Correction burden < 1 per session** on a 10-session test sequence across 2 projects.
