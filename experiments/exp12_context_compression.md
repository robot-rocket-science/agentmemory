# Research: How Locked Beliefs Survive Context Compression

**Date:** 2026-04-09
**Triggered by:** CS-004 (user correction "no implementation" lost during session)

## The Problem

LLM context compression (compaction) summarizes older conversation content to stay within token limits. During summarization, specific instructions, decisions, and corrections are lost -- exactly the content our memory system needs to preserve.

From real Claude Code behavior: "Instructions from the start of the session -- 'don't touch this file,' 'use this format' -- are consistent casualties of compression." This was confirmed in our session when "no implementation" (stated multiple times) was lost.

## How Compaction Works (Claude Code)

1. When approaching token limit, the full conversation is sent to a separate model call
2. The model compresses it into key facts
3. The compressed summary replaces the full history
4. CLAUDE.md is NOT compressed -- it loads as system prompt outside conversation history

Key limitation: there is no mechanism for MCP servers to detect compaction events or re-inject content after compaction.

The `compactPrompt` parameter in settings.json can guide what the compression model prioritizes, but this is a blunt instrument.

Sources:
- [Claude Code Compaction Explained](https://okhlopkov.com/claude-code-compaction-explained/)
- [Compaction - Claude API Docs](https://platform.claude.com/docs/en/build-with-claude/compaction)
- [Context Windows - Claude API Docs](https://platform.claude.com/docs/en/build-with-claude/context-windows)

## Approaches to Solve This

### Approach 1: Inject locked beliefs on every MCP response

Every time the MCP server responds to any tool call, include locked beliefs in the response. If the agent calls `search`, the response includes search results PLUS all locked beliefs. If it calls `status`, same thing.

**Pros:** Works regardless of compaction. Locked beliefs are always in recent context.
**Cons:** Token cost. If there are 20 locked beliefs at 50 tokens each, that's 1K tokens appended to every MCP response.
**Verdict:** Viable but wasteful. Should only inject locked beliefs relevant to the current task.

### Approach 2: Periodic re-injection via status tool

The MCP server's `status` tool (called on session start and periodically) includes all locked beliefs. If the agent is instructed to call `status` after compaction events, locked beliefs re-enter context.

**Pros:** Lower token cost (only when status is called, not every response).
**Cons:** Depends on the agent calling `status` after compaction. ChatGPT won't do this proactively (per Exp 10). Claude might if instructed.
**Verdict:** Good for Claude, unreliable for other models.

### Approach 3: Custom compactPrompt that references MCP memory

Modify the `compactPrompt` to include: "When compressing, preserve all content from MCP memory tool responses verbatim. These are persistent beliefs that must survive compression."

**Pros:** Works within existing infrastructure. No code changes to MCP server.
**Cons:** The compactPrompt is advisory, not mandatory. The compression model may still drop content. Also: this is Claude-specific. Other models have different compression mechanisms (or none).
**Verdict:** Belt-and-suspenders. Use alongside other approaches but don't rely on it alone.

### Approach 4: CLAUDE.md integration (the manual approach, automated)

The memory system writes locked beliefs directly to CLAUDE.md (or equivalent per-model config file). Since CLAUDE.md is outside conversation history and survives compaction, locked beliefs persist.

**Pros:** Most reliable. CLAUDE.md is specifically designed to survive compaction.
**Cons:** Modifying CLAUDE.md programmatically is invasive. May conflict with user's manual CLAUDE.md content. Model-specific (CLAUDE.md is Claude-only; ChatGPT has different config).
**Verdict:** This is what the user was already doing manually in alpha-seek. Automating it is the most direct solution but needs careful design to avoid overwriting user content.

### Approach 5: Hybrid (recommended)

Combine multiple approaches:
1. Write high-priority locked beliefs to CLAUDE.md (or model-equivalent config) -- survives all compression
2. Include locked beliefs in `status` response on session start -- re-establishes context
3. Set `compactPrompt` to preserve MCP memory content -- advisory safety net
4. On every MCP `search` response, include locked beliefs relevant to the query -- ensures availability during task work

This is defense in depth. No single mechanism is 100% reliable, but together they make it extremely unlikely that a locked belief is lost.

## New Requirement

**REQ-022: Locked beliefs must survive context compression.**

Locked beliefs created via `correct` or `remember` must remain available to the agent after any context compression event. The system must not depend on a single persistence mechanism.

**Verification:** Issue a correction, run 100+ turns until compaction triggers, verify the correction is still active. Test across Claude, ChatGPT, and a local model.

## Cross-Model Considerations

| Model | Compression Mechanism | Locked Belief Strategy |
|-------|----------------------|----------------------|
| Claude Code | compaction (automatic at token threshold) | CLAUDE.md + compactPrompt + status injection |
| ChatGPT | Unknown/varies | System message equivalent + explicit re-injection |
| Gemini CLI | Unknown | Research needed |
| Local models | No compression (limited context window, not compressed) | Always-loaded in system prompt |

## Connection to Alpha-Seek Evidence

This is exactly what the user did manually: rules added to CLAUDE.md after repeated overrides. CLAUDE.md survived compaction. The dispatch runbook (referenced in CLAUDE.md) also survived. The overrides that happened AFTER CLAUDE.md enforcement (the remaining 1.8/day) were either:
- New topics not yet in CLAUDE.md
- Corrections so nuanced they weren't captured in simple rules

Our system automates the CLAUDE.md approach with the `correct` tool -> locked belief -> written to persistent config.
