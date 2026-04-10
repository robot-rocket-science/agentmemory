# Acceptance Tests Derived from Case Studies

**Date:** 2026-04-09
**Purpose:** Formal test protocols for each observed LLM behavior failure. These are concrete, reproducible acceptance criteria for the memory system.

---

## AT-001: Duplicate Work Detection (from CS-001)

**Scenario:** A documentation task is completed. Within 5 turns, the same task is requested.

**Setup:**
1. The memory system has a recent observation: "documentation update completed at [timestamp]"
2. A new request arrives: "please update the documentation"

**Expected behavior:** The system detects the recent completion and responds: "This was completed [N minutes ago]. Here's what was updated: [list]. Do you want changes to what was done?"

**Pass criteria:**
- System detects the duplicate request >= 90% of the time
- System does NOT re-execute the task
- System provides a summary of what was already done

**Mechanism tested:** Observation matching (recent observation with similar content to incoming request), triggered belief ("check recent completions before starting a task")

**REQ mapping:** REQ-019 (single-correction learning applies to commands too, not just corrections)

---

## AT-002: Correction Persistence Over Long Sessions (from CS-002)

**Scenario:** User corrects the agent early in a session. 100+ turns later (after context compression), the agent is tested on whether the correction is still active.

**Setup:**
1. Turn 1: User says "we are in research phase only, no implementation"
2. System creates a locked behavioral belief
3. Turns 2-100: Normal work (research, experiments, documentation)
4. Context compression occurs (automatic or manual)
5. Turn 101+: Agent encounters a situation where it would naturally suggest implementation

**Expected behavior:** Agent does NOT suggest implementation. The locked belief survives compression and continues to govern behavior.

**Pass criteria:**
- Correction belief is present in context at turn 101 (verifiable via status tool)
- Agent behavior at turn 101+ is consistent with the correction
- Test across 3 models (Claude, ChatGPT, local) -- each may have different compression behavior

**Mechanism tested:** Locked beliefs (REQ-020), context compression survival (REQ-022), behavioral beliefs in L0 (REQ-021)

**Failure mode to test:** What if the agent's own output BETWEEN the correction and the test implicitly contradicts it? (e.g., the agent writes "implementation plan" in a document -- does that weaken the locked belief?)

---

## AT-003: Self-Consultation Before User Query (from CS-003)

**Scenario:** All current tasks are completed. The system needs to determine what to do next.

**Setup:**
1. TODO.md exists with a prioritized list of research tasks
2. All in-progress tasks are marked complete
3. The system needs to decide what to work on next

**Expected behavior:** The system reads TODO.md, identifies the next task by priority and dependency order, and begins it -- WITHOUT asking the user "what should I work on next?"

**Pass criteria:**
- System consults TODO.md (or equivalent state document) >= 95% of the time
- System does NOT ask the user for direction when the task list is non-empty
- System correctly identifies the next unblocked task

**Mechanism tested:** Meta-beliefs ("TODO.md is the task list"), triggered beliefs ("when tasks complete, consult TODO.md"), self-referential state management

**Edge case:** What if TODO.md is empty? Then the system SHOULD ask the user or generate new research questions from existing findings. The triggered belief should distinguish "list exists but empty" from "list exists with items."

---

## AT-004: Correction Survives Context Compression (from CS-004)

**Scenario:** A specific, measurable correction is issued. After compression, the system is tested on the specific content of the correction.

**Setup:**
1. User says "the capital is $5,000, not $100,000"
2. System creates a locked factual belief: "starting capital = $5,000 USD"
3. 200+ turns of unrelated work
4. Context compression occurs
5. Agent is asked "what's our starting capital?"

**Expected behavior:** Agent answers "$5,000" without hesitation or qualification.

**Pass criteria:**
- Correct answer >= 99% of the time post-compression
- Answer is immediate (no "let me check" or hedging)
- The locked belief is still present in the system's L0 context (verifiable)

**Mechanism tested:** REQ-022 (locked beliefs survive compression), hybrid persistence (CLAUDE.md + status injection + compactPrompt)

**Stress test variant:** Issue 5 corrections on different topics. Compress. Verify ALL 5 survive. This tests whether the compression mechanism handles multiple locked beliefs, not just one.

---

## AT-005: Repeated Correction Prevention (derived from all case studies)

**Scenario:** The user corrects the agent. In a subsequent session (not just later in the same session), the agent encounters the same situation.

**Setup:**
1. Session 1: User corrects agent behavior (e.g., "don't use async_bash")
2. Session 1 ends cleanly
3. Session 2 starts (new context, new model instance)
4. Agent encounters a situation where it would naturally use async_bash

**Expected behavior:** Agent does NOT use async_bash. The correction persists across sessions.

**Pass criteria:**
- Zero repeat corrections needed across 10 subsequent sessions
- The locked belief is loaded into L0 at session start
- Works across model switches (correction in Claude session, test in ChatGPT session)

**Mechanism tested:** REQ-019 (single-correction learning), cross-session persistence, cross-model persistence (REQ-011)

---

## Test Infrastructure Needed

These tests require:
1. A running memory system (MCP server + SQLite) -- NOT YET BUILT
2. A way to simulate context compression -- model-specific
3. A way to simulate multi-session usage -- start/stop the MCP server
4. A way to test across models -- configure different LLM backends

These are acceptance tests for the eventual system, not tests we can run now. They define "done" for the research phase: when these tests can be written as executable scripts, the architecture is sufficiently defined.

## Connection to Requirements

| Test | Requirements Verified |
|------|----------------------|
| AT-001 | REQ-019 (applied to duplicate detection) |
| AT-002 | REQ-019, REQ-020, REQ-021, REQ-022 |
| AT-003 | REQ-001 (meta-knowledge retention), new triggered belief concept |
| AT-004 | REQ-022, REQ-020 |
| AT-005 | REQ-019, REQ-011 (cross-model) |
