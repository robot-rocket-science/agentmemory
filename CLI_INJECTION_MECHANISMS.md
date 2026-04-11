# CLI Injection & Enforcement Mechanisms Research

**Date:** 2026-04-10
**Type:** Reference document -- verbatim transcript of mechanism survey
**Context:** Exploring what hooks Claude CLI and Codex CLI expose for prompt injection and enforcement, relevant to the onboarding system design.

---

> let's discuss onboarding and more specifically what mechanisms are available in claude cli and
codex cli for handling the sort of prompt injecting and enforcement we want to do

MemPalace doesn't have specific entries on this topic. Let me check what's already been researched
in this project.

Good context. Now I understand the frame: your onboarding system needs to inject memory context
into agent sessions and enforce retrieval behavior, and you want to understand what hooks the two
major CLI tools actually expose for that.

Let me lay out what I know, then we can identify gaps.

## Claude CLI (Claude Code) Mechanisms

### 1. CLAUDE.md files (system-level prompt injection)
- `~/.claude/CLAUDE.md` -- global, always loaded
- `<project>/.claude/CLAUDE.md` -- per-project, loaded when cwd matches
- `~/.claude/projects/<hash>/CLAUDE.md` -- user-private per-project instructions
- These are prepended to the system prompt. The agent sees them as authoritative instructions.
- **Limitation:** Static text. No conditional logic, no templating, no "if this project has X, inject Y."

### 2. Hooks (settings.json)
- Event-driven shell commands that fire on: `PreToolUse`, `PostToolUse`, `Notification`, `Stop`, `SubagentStop`
- Can read/modify tool inputs, block tool calls, inject feedback
- Hooks run as shell commands and return JSON to influence behavior
- **Key for you:** A hook on `PreToolUse` or session start could run your onboarding pipeline and inject results. But hooks communicate back via stdout JSON, not by modifying the system prompt mid-conversation.

### 3. MCP Servers (tool-based injection)
- This is what you're already using with MemPalace. Custom tools the agent can call.
- The agent must choose to call them (or be instructed to via CLAUDE.md).
- **Key limitation:** The agent decides when to call. You can instruct "always call mempalace_status at session start" in CLAUDE.md, but enforcement is soft -- the model can skip it.

### 4. `/` commands (Skills)
- User-invocable, defined in SKILL.md files
- Can contain full prompts that get expanded when triggered
- Could be used for "run onboarding now" type flows

### 5. System prompt injection via SessionStart hook
- You already have this: `SessionStart hook additional context: MEMPALACE PROTOCOL...`
- This is the closest thing to hard enforcement -- it gets injected into every conversation start.

## Codex CLI (OpenAI) Mechanisms

### 1. `AGENTS.md` / `codex.md`
- Equivalent to CLAUDE.md. Project-level instructions loaded at session start.
- Same limitation: static text.

### 2. No hooks system
- Codex CLI does not have an equivalent to Claude's hooks system as of my last knowledge. It's much simpler -- prompt in, response out.
- No event-driven middleware.

### 3. No MCP support (natively)
- Codex CLI uses OpenAI's function calling, not MCP. You'd need to build tool integrations differently.

### 4. `--instructions` flag
- Can pass instructions at invocation time via CLI flag or file reference.
- This is more flexible than CLAUDE.md for dynamic injection -- a wrapper script could generate instructions on the fly.

## The Enforcement Problem

Here's the core tension for your system:

| Mechanism | Injection Power | Enforcement Level |
|-----------|----------------|-------------------|
| CLAUDE.md / AGENTS.md | Always loaded | Soft (model can ignore) |
| SessionStart hook | Always fires | Medium (injects text, model still chooses to act) |
| MCP tools | Rich interaction | Soft (model must choose to call) |
| PreToolUse hooks | Can block/modify | Hard for tool calls, but reactive not proactive |
| CLI wrapper script | Full control of initial prompt | Hard at session start, none after |

None of these give you **hard enforcement** that the model will retrieve and apply memory before answering. The best you can do today is layer multiple soft mechanisms:

1. SessionStart hook injects the protocol instruction
2. CLAUDE.md reinforces "always check memory first"
3. MCP tools are available when the model complies

**The gap:** there's no way to **block the model from responding** until it has called your memory retrieval tool. A `PreToolUse` hook can block tool calls, but there's no `PreResponse` hook that gates the model's text output on having called a specific tool first.

## Open Questions

- How to maximize compliance with soft enforcement?
- Whether a wrapper/proxy architecture could give harder guarantees?
- Cross-platform compatibility (making the same system work in both CLIs)?
