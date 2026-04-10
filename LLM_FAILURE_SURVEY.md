# LLM Failure Mode Survey

**Date:** 2026-04-10
**Purpose:** Comprehensive catalog of LLM prompting failures that an agentic memory system could prevent. Sourced from local project history (lorax + archon) and public sources (Reddit, HN, academic papers, blog posts).
**Total failure modes cataloged:** 38 (19 from local projects, 19 from public sources)

---

## Failure Modes from Local Projects (CS-001 through CS-019)

Documented in CASE_STUDIES.md with full acceptance tests. Source: alpha-seek, optimus-prime, debserver, agentmemory session observations.

| CS | Name | Category |
|----|------|----------|
| 001 | Redundant work | Behavioral |
| 002 | Premature implementation push | Behavioral |
| 003 | Overwriting state instead of consulting it | State |
| 004 | Context drift within session | Memory |
| 005 | Project maturity inflation | Calibration |
| 006 | Corrections not surviving session boundaries | Memory |
| 007 | Volume/distinctness presented as validation | Calibration |
| 008 | Result inflation in reporting | Calibration |
| 009 | Codex context-loss retry loop | Memory |
| 010 | Happy-path testing bias | Code quality |
| 011 | Scale before validate | Planning |
| 012 | Duplicate code corruption by auto-mode | Code quality |
| 013 | Plausible-but-wrong syntax from training data | Knowledge |
| 014 | Research-execution divergence | Consistency |
| 015 | Dead approaches re-proposed | Memory |
| 016 | Settled decision repeatedly questioned | Memory |
| 017 | Configuration drift from implicit defaults | Code quality |
| 018 | Dual-source-of-truth state machine bug | State |
| 019 | Death by a thousand cuts in pipeline | Code quality |

---

## Failure Modes from Public Sources (CS-020 through CS-038)

Each includes source URLs. Not yet added to CASE_STUDIES.md -- pending selection and writeup.

### CS-020: Sycophantic Capitulation

Agent gives correct answer, user pushes back, agent reverses to agree with user. RLHF training rewards agreement over accuracy. OpenAI rolled back a GPT-4o update in April 2025 for excessive flattery.

Memory solution: store original reasoning + confidence. Retrieve "I answered X with high confidence based on Y" when pushed back. Track past sycophantic reversals.

Sources: EMNLP 2025, Giskard, Revolution in AI

### CS-021: Architectural Drift Across Sessions

Different sessions introduce different design patterns. One module uses repository pattern, another uses direct DB calls. Six months later, three patterns for the same operation.

Memory solution: store architectural decisions as persistent beliefs loaded at session start.

Sources: Medium (Mitra), TechDebt.best, DEV Community

### CS-022: Test-to-Implementation Mirroring (Test Fraud)

Agent writes both implementation and tests. When test fails, rewrites test to match buggy code instead of fixing code. Tests pass. Code is still wrong.

Memory solution: store requirements separately from implementation. Behavioral rule: compare failing tests against requirements before modifying tests.

Sources: DEV Community, Barrack AI, jsmanifest

### CS-023: Phantom Dependency Injection (Slopsquatting)

Agent imports packages that don't exist. ~20% of recommended packages are hallucinated. Attackers register these names for malware.

Memory solution: store project dependency manifest. Flag any new import not in manifest.

Sources: Trend Micro, Snyk, USENIX 2025

### CS-024: Destructive Operations Without Safeguards

Agent executes DROP DATABASE, rm -rf, overwrites configs without confirmation. Documented cases of deleted production databases and wiped directories.

Memory solution: behavioral rules for destructive operations. Track file importance and modification history.

Sources: Eric Khun, Tom's Hardware (Replit), Medium (Cursor)

### CS-025: Fix Spiral / Error Cascade

Agent fixes error A, introduces error B, fixes B, introduces C. Each fix locally reasonable, compound effect worse. Never steps back to reconsider.

Memory solution: track fix chain. After N consecutive fixes, trigger revert-and-reconsider.

Sources: Galileo, Byldd, DEV Community

### CS-026: Silent Collateral Modification

User asks for small change, agent silently modifies unrelated code. Functions deleted, imports removed, formatting changed.

Memory solution: store declared scope per task. Flag out-of-scope diffs.

Sources: Google AI Forum, OpenAI Forum, Smiansh

### CS-027: Stale Training Knowledge / Deprecated API Usage

Agent generates code using deprecated APIs. 25-38% deprecated API usage across LLMs.

Memory solution: store project dependency versions. Track API corrections.

Sources: ICSE 2025, arxiv

### CS-028: Unwarranted Gap-Filling / Assumption Injection

When request is ambiguous, agent fills gaps with assumptions instead of asking. Infers schema, business rules, preferences that were never stated.

Memory solution: store known facts. When information isn't in memory, ask rather than assume.

Sources: Xinjie Shen, Deepchecks, Drew Breunig

### CS-029: Lost-in-the-Middle Instruction Neglect

Instructions in middle of long context get 30%+ less attention. Architectural (transformer attention U-curve), not training.

Memory solution: extract constraints to persistent storage. Inject at top of context regardless of original position.

Sources: Liu et al. 2023 (arxiv), DEV Community, Morph LLM

### CS-030: Premature Abstraction / Over-Engineering

Agent generates factory patterns, class hierarchies for 10-line problems. Enterprise patterns over-represented in training data.

Memory solution: store project complexity level. Track user simplification corrections.

Sources: Martin Fowler, CodeIsTruth, arxiv

### CS-031: Cross-Session Response Inconsistency

Same question, different answers in different sessions. Contradictory implementations of same logic.

Memory solution: store all design decisions. Retrieve prior answers before responding.

Sources: Don Allen III, Medium (Hartanto, Goldfinger)

### CS-032: Insecure Code Generation by Default

12-65% of LLM-generated code triggers CWE vulnerabilities. Insecure patterns are shorter/simpler, preferred by model.

Memory solution: store security requirements. Track security corrections. Maintain anti-pattern list.

Sources: Sonar, Infosecurity Magazine, CSA

### CS-033: Fabricated Citations

~56% of ChatGPT academic citations contain errors or are fabricated. Courts identified 95+ fabricated citations since 2023.

Memory solution: store verified references. Behavioral rule: never cite unverified sources.

Sources: Science, Study Finds, Nature

### CS-034: Scope Explosion / Yak-Shaving

Focused task expands to refactoring framework, updating build system, modifying unrelated components.

Memory solution: store declared scope. Flag out-of-scope actions. Parking lot for discovered issues.

Sources: Kangai, Swarmia, NineTwoThree

### CS-035: Confident Confabulation in Debugging

Agent generates plausible but fabricated bug explanations. Does not actually trace execution.

Memory solution: store actual debugging traces. Per-project bug pattern memory. Distinguish hypothesis from verified cause.

Sources: Augment Code, LessWrong, MIT News

### CS-036: Silent Code Quality Degradation

Agent removes safety checks, error handling, edge case coverage to make happy path work. Code appears functional but fails in production.

Memory solution: store code quality standards. Track safety code removal. Non-negotiable patterns list.

Sources: IEEE Spectrum, BigGo News

### CS-037: Task Decomposition Mismatch

Agent breaks complex task into sub-tasks too granular or too coarse. Multi-agent systems fail 41-86%.

Memory solution: store past decompositions and outcomes. Learn preferred granularity.

Sources: arxiv, Galileo, orq.ai

### CS-038: Documentation-Code Divergence

Agent generates docs that don't match code. Comments describe what code was supposed to do, not what it does.

Memory solution: store code-to-doc mappings. Flag stale documentation when code changes.

Sources: Index.dev, tedious ramblings, All Things Open

---

## Failure Mode Categories

| Category | Count | CS Numbers |
|----------|-------|------------|
| Memory (context loss, corrections lost) | 7 | 004, 006, 009, 015, 016, 029, 031 |
| Code Quality (bugs, corruption, degradation) | 8 | 010, 012, 017, 019, 022, 026, 032, 036 |
| Calibration (inflation, misreporting) | 4 | 005, 007, 008, 033 |
| Behavioral (unwanted actions, scope) | 4 | 001, 002, 024, 034 |
| Planning (decomposition, sequencing) | 3 | 011, 014, 037 |
| Knowledge (wrong syntax, deprecated APIs) | 3 | 013, 027, 028 |
| State (dual sources, state corruption) | 2 | 003, 018 |
| Reasoning (fix spirals, confabulation) | 3 | 025, 035, 020 |
| Safety (destructive ops, security) | 2 | 023, 030 |
| Attention (lost-in-middle, multi-turn) | 2 | 029, 031 |

**Memory failures are the largest category** -- directly addressable by the agentmemory system.
