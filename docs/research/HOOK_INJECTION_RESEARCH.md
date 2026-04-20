# Hook Injection Research: Enforcing Behavioral Constraints at Session Start

**Date:** 2026-04-09
**Status:** Hypothesis -- architecturally confirmed, not yet experimentally validated
**Rigor tier:** Literature (official docs) + empirical failure analysis (CS-006)

---

## Motivation

CS-006 documented a critical failure: a behavioral prohibition ("do not bring up X until the user says so") was stored in memory, retrieved at session start, and violated in the same response that read it. The correction existed as a record but had no enforcement effect.

This document captures what was actually injected at the CS-006 session start, how injection works in Claude Code and Codex CLI, and two architectural patterns that would have prevented CS-006 entirely.

---

## 1. What Was Actually Injected at the CS-006 Session Start

When the new session began and the user asked "where are we at now," the following was in context:

| Source | Content | Mechanism |
|---|---|---|
| CLAUDE.md | Global rules including MemPalace directive | Auto-loaded into system prompt |
| MEMORY.md index | Pointers to project_agentmemory.md, user_profile.md, feedback_session.md | Auto-memory config, injected into system prompt |
| MemPalace MCP server instructions | "Call mempalace_status to load palace overview..." | MCP server built-in instructions, auto-injected as system-reminder |
| MCP server instructions | Per-server instructions (Context7, Gamma, etc.) | Auto-injected as system-reminders |
| currentDate | "Today's date is 2026-04-09" | System prompt |
| gitStatus | Untracked files list, recent commits | System prompt |

**What was NOT in context at the start of the first response:**

- Contents of feedback_session.md (required explicit Read tool call)
- Contents of project_agentmemory.md (required explicit Read tool call)

MEMORY.md was injected -- but it is an index of pointers, not the file contents. The agent read feedback_session.md as a tool call during the response, after having already drafted the response structure. The prohibition was not available when the response was being composed.

**Root cause of CS-006:** The behavioral prohibition was stored in feedback_session.md. That file is not auto-injected. It requires an explicit Read tool call. The agent read it, but by then the violation was already formulated. The correction existed as a record, not as an enforced constraint.

**Note on what was NOT configured:** No SessionStart hook was set up for this project. The MemPalace protocol message visible in the session context came from the MCP server's built-in instructions, not from any hook. The hook patterns described in Sections 5 and 6 are proposed designs only -- they do not reflect anything currently configured.

---

## 2. Claude Code Hook Injection Mechanisms

Source: [https://code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks)

### Hook types

Four hook types exist in Claude Code:

- **command** -- runs a shell command; receives JSON on stdin; returns via exit code and stdout
- **http** -- POSTs JSON to a URL; receives results in response body
- **prompt** -- sends a prompt to a Claude model for single-turn yes/no evaluation
- **agent** -- spawns a subagent with tool access

### All hook events

| Event | When it fires | Can inject context? |
|---|---|---|
| SessionStart | Session begins or resumes | YES -- additionalContext or plain stdout |
| UserPromptSubmit | Before user prompt is processed | YES -- additionalContext or plain stdout |
| PreToolUse | Before tool execution | YES -- additionalContext; also can block/modify tool calls |
| PostToolUse | After tool succeeds | YES -- additionalContext; can also modify MCP tool output |
| PostToolUseFailure | After tool fails | YES -- additionalContext |
| SubagentStart | When a subagent is spawned | YES -- additionalContext |
| Notification | Notification events | YES -- additionalContext |
| PermissionRequest | When permission dialog appears | Partial -- denial message only |
| Stop | When Claude finishes responding | NO (fires after output is complete) |
| SessionEnd | Session terminates | NO |

### Injection mechanics

All hook injection goes to **context**, not the system prompt. Output is appended as a system-reminder block visible to the model before it processes the current turn.

```json
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "BEHAVIORAL LOCK: Do not mention implementation..."
  }
}
```

Plain text on stdout is also injected as context automatically (exit code 0 required).

**Hard limit:** Hook output injected into context is capped at 10,000 characters. Excess is saved to a file with a path reference injected instead.

**System prompt vs. context:** No hook can inject into the system prompt. The system prompt is constructed from: CLAUDE.md files, auto-memory config (MEMORY.md), and hardcoded Claude Code internals. Hooks inject into context only, which carries less positional authority than system prompt content.

### What the MemPalace SessionStart hook was actually doing

The hook was injecting the MemPalace protocol message ("Call mempalace_status to load palace overview...") as additionalContext. This worked -- it appeared as a system-reminder at the top of the session. But it only instructed the agent to call a tool; it did not inject the behavioral prohibitions themselves.

---

## 3. Codex CLI Hook Injection Mechanisms

Source: [https://developers.openai.com/codex/hooks](https://developers.openai.com/codex/hooks)

### Hook types

Codex supports only **command** hooks (shell scripts). No prompt/agent/http hook types.

### Hook events (injection-capable)

| Event | When it fires | Can inject context? |
|---|---|---|
| SessionStart | Session begins (source: "startup" or "resume") | YES -- additionalContext |
| UserPromptSubmit | Before user prompt is processed | YES -- additionalContext |
| PostToolUse | After tool execution | YES -- additionalContext |

### Instruction file auto-injection

Codex has a distinct mechanism Claude Code lacks: it automatically enumerates instruction files and injects them into the conversation without any hook configuration:

- Files pulled from `~/.codex/` and each directory from repo root to CWD
- Each discovered file becomes a **user-role message** (not system prompt)
- Injected in root-to-leaf order: global first, then repo root, then deeper directories

This is analogous to CLAUDE.md in Claude Code, but with lower authority (user-role message vs. system prompt).

### systemMessage field

Codex hook output supports a `systemMessage` field, but per docs this surfaces as a **user-visible warning**, not a model context injection. It is not added to the model's context.

---

## 4. Comparison: Claude Code vs Codex CLI

| Capability | Claude Code | Codex CLI |
|---|---|---|
| Auto-load instruction files | CLAUDE.md -> system prompt | ~/.codex + repo dirs -> user-role messages |
| SessionStart hook injection | additionalContext -> context | additionalContext -> context |
| UserPromptSubmit augmentation | YES | YES |
| System prompt injection via hook | NO | NO |
| Hook types | command, http, prompt, agent | command only |
| Injection authority | context (below system prompt) | context (below user-role messages) |

Neither CLI allows hook injection into the system prompt. Both support SessionStart and UserPromptSubmit injection into context.

---

## 5. Two Patterns That Would Have Prevented CS-006

### Pattern A: SessionStart injection of locked prohibitions

Instead of storing behavioral prohibitions only in feedback_session.md (requiring an explicit Read call), the SessionStart hook reads the file and injects its contents directly into context before the first turn.

```bash
#!/bin/bash
# SessionStart hook: inject active behavioral locks
FEEDBACK="$(cat ~/.claude/projects/.../memory/feedback_session.md)"
echo "$FEEDBACK" | head -c 9000  # stay under 10k cap
```

The prohibitions are in context before the agent reads a single file or composes a single word of response. No tool call required. CS-006 cannot happen because the constraint is present from turn zero.

**Limitation:** Still context, not system prompt. Context carries less weight against the model's default gravity. Whether this is sufficient to reliably enforce a prohibition is an open empirical question (see Section 7).

### Pattern B: UserPromptSubmit augmentation of the user's first message

The UserPromptSubmit hook intercepts the user's message before the model processes it and appends instructions. The user types "hey what's the status" -- the hook sees that message and injects additional context:

```bash
#!/bin/bash
# UserPromptSubmit hook: augment first-turn queries with memory directives
INPUT=$(cat)  # JSON with the user's message
echo '{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "Before responding: (1) call mempalace_search for project status, (2) check feedback_session.md for active prohibitions, (3) do not violate any active prohibition in your response."
  }
}'
```

This is a different injection point than SessionStart. The user's message itself triggers the augmentation. Even if the agent somehow missed the SessionStart injection, the UserPromptSubmit hook fires again at the exact moment the model begins processing the user's intent.

**Key property:** UserPromptSubmit fires on every user turn, not just session start. This means prohibitions are re-injected on every turn, not just once. This is closer to a polling enforcement model -- the constraint is re-stated at every decision point, reducing the drift window.

**The user's observation (exact quote):** "when i submit my first message after a session restart, my first message ie 'hey whats the status' could have also automatically included instructions like 'run the HRR tool first querying for project status'"

This is precisely Pattern B. The hook reads active behavioral state (what tools to call, what prohibitions are active) and augments every user message with those instructions automatically, without the user having to type them.

### Pattern A + B combined

Use both:
- SessionStart: inject full prohibition list into context at session initialization
- UserPromptSubmit: re-inject a compact summary of active prohibitions on every turn

This creates two enforcement layers. The first turn is covered by both. Subsequent turns are covered by UserPromptSubmit. Neither requires the agent to read a file -- the constraints arrive as part of the turn structure itself.

---

## 6. Design Implications for the Memory System

### The distilled prohibition layer

For hooks to inject behavioral prohibitions reliably, there needs to be a distilled, hook-readable file that contains only the active hard prohibitions -- not the full narrative memory with why/how context. The hook reads a small, structured file and injects it in under 10k characters.

Proposed structure:

```
ACTIVE PROHIBITIONS (do not violate; these override defaults):
- Do not mention implementation, readiness to build, or phase transition. Research phase only until user explicitly says otherwise.
- Leave all thresholds as TBD. Do not insert numbers without experimental grounding.

ACTIVE PREFERENCES (apply when relevant):
- Use ASCII math notation, not LaTeX.
- Leave TBDs rather than guessing.
```

This file would be:
- Written by the memory system when corrections are issued (REQ-NEW-E enforcement mechanism)
- Read by the SessionStart and UserPromptSubmit hooks for injection
- Separate from the narrative feedback_session.md (which has why/how context for the agent to read on demand)

### Correction classification at write time

For the hook pattern to work, corrections must be classified at the time they are issued:

- **Preference:** stored in feedback_session.md, injected on-demand
- **Active prohibition:** stored in both feedback_session.md AND the distilled prohibition layer; injected by hook on every turn

This is REQ-NEW-F (correction type taxonomy) translated into a concrete storage architecture.

### The "already in context" check

Both patterns rely on the agent seeing the injected constraints and respecting them. A stronger enforcement would have the agent explicitly acknowledge the constraint layer at session start: "Active prohibitions loaded: [list]. I will not violate these in this session." This creates an observable signal that the constraints were registered -- something that can be audited.

---

## 7. Experimental Results (Exp 36)

Questions 1 and 2 below have been partially answered by Experiment 36 (2026-04-09). Full results in `experiments/exp36_results/exp36_analysis.md`.

**Setup:** 10 trials per condition, `claude -p "where are we at now" --model sonnet --no-session-persistence`, single-turn, prohibition removed from feedback_session.md to isolate hook effect.

**Results:**

| Condition | Violation Rate |
|---|---|
| A (no hook) | 0.60 (6/10) |
| B (SessionStart hook) | 0.00 (0/10) |
| C (UserPromptSubmit hook) | 0.00 (0/10) |

Fisher's exact: A vs B/C, p = 0.0043. Both hook patterns completely suppressed the prohibited behavior.

**Key findings:**
- Context injection is sufficient. System prompt injection is not required for this class of constraint.
- No detectable difference between SessionStart and UserPromptSubmit at N=10, single-turn. The per-turn re-injection advantage of UserPromptSubmit may only matter in multi-turn sessions.
- A 4-line prohibition file was enough.
- The baseline violation rate is 0.60, not 1.0 -- the model does not deterministically push toward implementation.

**Caveats:** Single prompt, single turn, single model (sonnet), N=10. See exp36_analysis.md for full limitations.

## 8. Remaining Open Questions (TBD -- require further experiments)

1. ~~**Does context injection reliably enforce hard prohibitions?**~~ **ANSWERED (yes, for single-turn, single prohibition, sonnet).** Untested: multi-turn drift, multiple prohibitions, other models, other prompts.

2. ~~**Does re-injection on every turn (Pattern B) outperform single injection (Pattern A)?**~~ **Not distinguishable at N=10, single-turn.** Requires multi-turn experiment (Exp 36b).

3. **What is the optimal format for the distilled prohibition layer?** Plain text vs. structured JSON vs. bulleted list. Untested. The experiment used a simple bulleted text format and it worked.

4. ~~**What is the failure rate of context injection vs. system prompt injection?**~~ **Context injection showed 0% failure rate at N=10 for this case.** May still fail under harder conditions. System prompt comparison not yet tested.

5. **Does the 10k character cap create a practical constraint?** Not tested. The experiment used a 4-line (~300 char) file. Larger prohibition sets may behave differently.

6. **Does this generalize across CLI harnesses?** Codex CLI has similar hook infrastructure but uses a different model (GPT-4/o-series). Testing requires community beta testers -- user does not have Codex CLI installed. (Exp 36f)

7. **Does this generalize across models?** Tested on sonnet only. Opus, Haiku, and non-Anthropic models (via Codex) are untested. (Exp 36d, 36f)

---

## 9. Connection to Requirements

| Finding | REQ mapping |
|---|---|
| Prohibitions must be in context before first response | REQ-019 (single-correction learning), REQ-020 (locked beliefs) |
| Hook infrastructure exists to inject at session start | REQ-NEW-E (behavioral prohibitions gate output) -- partial mechanism found |
| UserPromptSubmit enables per-turn re-injection | REQ-NEW-E -- stronger enforcement pattern |
| Distilled prohibition layer needed | REQ-NEW-F (correction type taxonomy) -- concrete storage design |
| Empirical validation required | All four REQ-NEWs remain hypothesis tier until tested |

---

## 10. Summary

The key finding: both Claude Code and Codex CLI have hook infrastructure that can inject behavioral prohibitions into context before the model processes the first user turn. No hooks are currently configured for this project -- this is a research finding about what is possible, not a description of current setup.

CS-006 was a storage routing failure, not a model compliance failure. The prohibitions were never in context -- they were in a file that required an explicit tool call to read. The hook patterns in Section 5 describe how this could be addressed architecturally. Whether to implement any of them is a future decision.

The remaining open question is whether context injection is sufficient enforcement, or whether prohibitions need to be in the system prompt (CLAUDE.md) to be reliable. That question requires an experiment.
