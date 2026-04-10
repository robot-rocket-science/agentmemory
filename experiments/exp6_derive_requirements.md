# Experiment 6 Phase D: Requirements Derived from Historical Failures

**Date:** 2026-04-09

For each observed failure pattern, we determine what the memory system needed to provide to prevent it, and check whether our current requirements (REQ-001 through REQ-018) cover it.

---

## Failure-to-Requirement Mapping

### F1: Dispatch Gate Forgotten (13 overrides, 5 days)

**What happened:** The agent repeatedly failed to follow the dispatch gate protocol, causing failed deployments and requiring cleanup. The user had to re-explain the protocol ~2.6 times/day.

**What memory needed:** A procedural belief like "ALWAYS follow the dispatch gate: verify image version, check config diff, confirm deploy gate before any GCP dispatch" loaded into EVERY session's context, non-negotiable. This is an L0 belief -- it must be present even when the task seems unrelated to dispatch.

**What the user actually did:** Created dispatch-runbook.md (29KB, D137) and added it as a mandatory reference in CLAUDE.md. This reduced overrides by 67%.

**Requirements coverage:**
- REQ-001 (cross-session retention): YES -- the dispatch gate decision must persist
- REQ-002 (belief consistency): YES -- agent must not contradict the gate protocol
- **GAP: No requirement for automatic L0 promotion.** When a user issues the same override 3+ times, the system should automatically promote that belief to always-loaded context. Currently REQ-001 just says "decisions must be retrievable" -- it doesn't say "repeatedly-overridden decisions must be always-loaded."

**Proposed new requirement:**
> **REQ-019: Automatic L0 promotion.** When a user overrides the agent on the same topic 2+ times, the corresponding belief must be automatically promoted to always-loaded context (L0/L1). The user should never have to issue the same correction three times.

---

### F2: Calls/Puts Equal Citizens (4 overrides, 11 days)

**What happened:** The agent kept questioning whether to include puts alongside calls, despite D073 settling this permanently. The user escalated from explanation (D073) to clarification (D096) to anger (D100: "STOP BRINGING IT UP").

**What memory needed:** A factual belief with maximum confidence that never gets questioned. Not just "retrieved when relevant" but "always present and never debatable." The final override (D100) explicitly marks this as a HARD RULE.

**Requirements coverage:**
- REQ-001: YES -- the decision persists
- REQ-002: YES -- no contradictions
- **GAP: No concept of "non-debatable" beliefs.** Some beliefs should be marked as settled and never surfaced for reconsideration. Our Bayesian model treats everything as revisable. There should be a class of beliefs that are locked -- they can only be changed by explicit user override, not by evidence accumulation.

**Proposed new requirement:**
> **REQ-020: Locked beliefs.** Users must be able to lock a belief, marking it as non-debatable. Locked beliefs cannot be downgraded by the Bayesian feedback loop or superseded by agent inference. Only explicit user action can unlock or revise them.

---

### F3: Capital = $5K (3 overrides, 10 days)

**What happened:** The agent kept using $100K or asking about capital increases. The user corrected twice on the same day (Mar 27), then again 10 days later (Apr 6: "do not ask about it again").

**What memory needed:** A factual belief at L0 (always-loaded). Simple, permanent, non-negotiable.

**Requirements coverage:**
- REQ-001: YES
- REQ-019 (proposed): YES -- 3 overrides would trigger auto-promotion
- REQ-020 (proposed): YES -- lockable

No additional gap.

---

### F4: Agent Behavior / Don't Elaborate (3 overrides, 2 days)

**What happened:** The agent kept producing unsolicited analysis, elaboration, and philosophy when the user wanted precise execution. Two overrides within 1 minute (D157: async_bash ban). Then D188: explicit "execute exactly, return control."

**What memory needed:** A behavioral constraint at L0. This is a preference/procedural belief that governs HOW the agent operates, not WHAT it works on.

**Requirements coverage:**
- REQ-001: YES
- REQ-019 (proposed): YES
- **GAP: No distinction between domain beliefs and behavioral beliefs.** "Use PostgreSQL" is a domain belief. "Don't elaborate" is a behavioral belief. Behavioral beliefs should probably be in a separate always-loaded category because they apply to EVERY task, not just tasks in a specific domain.

**Proposed new requirement:**
> **REQ-021: Behavioral beliefs always-loaded.** Beliefs about agent behavior (how to communicate, what tools to use/avoid, interaction style) must always be in L0 context regardless of task domain. They are cross-cutting by nature.

---

### F5: Strict Typing (4 overrides, 4 days)

**What happened:** The user told the agent to use strict typing (D071), then had to repeat it 3 more times. Eventually solved by adding a pyright pre-commit hook (automation) and CLAUDE.md rule.

**What memory needed:** A procedural belief. But the real fix was automation (pre-commit hook), not memory. This is an important distinction: some problems are better solved by enforcement mechanisms than by memory.

**Requirements coverage:**
- REQ-001: YES
- **Observation:** The pre-commit hook is a more reliable solution than memory for this specific case. Memory can remind the agent; the hook prevents the violation. Our system should recognize when a procedural belief would be better served by automation and suggest it.

No new requirement, but a design note: **memory is not always the right solution.** Some constraints are better enforced by tooling.

---

### F6: GCP Primary Compute (3 overrides, 7 days)

**What happened:** The agent kept trying to use archon for primary compute when GCP was the designated platform.

**What memory needed:** Factual belief at L1 (loaded when compute-related tasks are active).

**Requirements coverage:**
- REQ-001: YES
- REQ-019 (proposed): YES

No additional gap.

---

## Summary of Coverage

| Failure | REQ-001 | REQ-002 | REQ-019 (new) | REQ-020 (new) | REQ-021 (new) | Other |
|---------|---------|---------|---------------|---------------|---------------|-------|
| Dispatch gate | YES | YES | YES | - | - | - |
| Calls/puts | YES | YES | YES | YES | - | - |
| Capital $5K | YES | YES | YES | YES | - | - |
| Agent behavior | YES | - | YES | - | YES | - |
| Strict typing | YES | - | YES | - | - | Automation > memory |
| GCP primary | YES | - | YES | - | - | - |

### New Requirements Proposed

| ID | Requirement | Derived From | Priority |
|----|-------------|-------------|----------|
| REQ-019 | Auto L0 promotion after 2+ overrides on same topic | Dispatch gate (13 overrides!), all clusters | HIGH |
| REQ-020 | Locked beliefs (non-debatable, user-only override) | Calls/puts (D100: "STOP"), capital (D209: "do not ask again") | HIGH |
| REQ-021 | Behavioral beliefs always in L0 | Agent behavior (D157, D188) | MEDIUM |

### Scaling Observation

The manual approach (CLAUDE.md + runbook) reduced overrides by 49-67% but plateaued. At 50+ milestones, the manual approach was overwhelmed. This confirms:
- Memory is needed at scale
- The L0/L1/L2/L3 progressive loading design is correct
- Automatic promotion from "learned belief" to "always-loaded belief" is the key automation gap
- Some beliefs need to be locked against automated revision
