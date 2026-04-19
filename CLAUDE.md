# Agentmemory Project Instructions

## Memory System: agentmemory MCP Server

This project has a persistent memory system running as an MCP server. You MUST use it.

### Mandatory Behaviors

1. **At session start:** Call `mcp__agentmemory__status` to see what's in memory. Call `mcp__agentmemory__get_locked` to load active constraints. Obey all locked beliefs without exception.

2. **Before answering questions about past work, decisions, or project history:** Call `mcp__agentmemory__search` with relevant keywords. Do not guess or rely on training data for project-specific context.

3. **When the user corrects you:** Call `mcp__agentmemory__correct` with the correction text. If it replaces something specific, use the `replaces` parameter. This creates a locked belief that persists forever.

4. **When the user states a permanent rule or preference:** Call `mcp__agentmemory__remember` with the statement. This creates a locked belief.

5. **When you learn something new about the project:** Call `mcp__agentmemory__observe` to record it as an observation.

6. **When processing conversation turns for the pipeline:** Call `mcp__agentmemory__ingest` with the text and source.

7. **After using or rejecting a retrieved belief:** Call `mcp__agentmemory__feedback` with the belief ID and outcome ("used", "ignored", or "harmful"). This closes the Bayesian feedback loop -- beliefs that help get stronger over time, beliefs that hurt get weaker. You do not need to call this for every belief in every search result; focus on beliefs you explicitly acted on or deliberately rejected.

### Available Tools

| Tool | When to Use | Example |
|---|---|---|
| `mcp__agentmemory__search` | Before answering questions about project context | `search("retrieval architecture")` |
| `mcp__agentmemory__remember` | When user states a rule or decision | `remember("always use uv for Python")` |
| `mcp__agentmemory__correct` | When user corrects you | `correct("use B not A", replaces="approach A")` |
| `mcp__agentmemory__lock` | ONLY after user explicitly confirms locking | `lock("a1b2c3d4e5f6")` |
| `mcp__agentmemory__observe` | When you learn something notable | `observe("user prefers terse responses")` |
| `mcp__agentmemory__ingest` | To process conversation text through classification pipeline | `ingest("the full turn text", source="user")` |
| `mcp__agentmemory__onboard` | To bulk-ingest conversation logs | `onboard("~/.claude/conversation-logs/turns.jsonl")` |
| `mcp__agentmemory__feedback` | After using or rejecting a retrieved belief | `feedback("a1b2c3d4e5f6", "used")` |
| `mcp__agentmemory__status` | To check memory system health | `status()` |
| `mcp__agentmemory__get_locked` | To load all active constraints | `get_locked()` |

### Locking Workflow

Beliefs created by `remember()` and `correct()` are NOT locked by default. After creating a belief, you MUST ask the user if they want to lock it. Only call `lock(belief_id)` after the user explicitly confirms. Never lock a belief without user confirmation.

### What NOT to Do

- Do not ignore locked beliefs. They are non-negotiable constraints.
- Do not call `lock()` without explicit user confirmation. This is the most important rule.
- Do not store ephemeral content (greetings, status updates, "ok", "proceed"). Only persist decisions, corrections, facts, requirements, preferences.
- Do not re-ask the user for information that might be in memory. Search first.

## Emergency: Disable Memory System

If the memory system causes a context loop, hallucination spiral, or other problems:

1. The user can say "disable agentmemory" -- stop calling all agentmemory tools for the rest of the session.
2. The data is still accessible via direct SQLite at `~/.agentmemory/memory.db`. The user can query it manually.
3. To fully remove: delete `.mcp.json` from the project root and remove the SessionStart hook from `~/.claude/settings.json`.

To re-enable after disabling: the user says "enable agentmemory" and you resume calling tools.

## Behavioral Enforcement (TB-01/04/12/14)

These rules are not enforceable via hooks. You must self-enforce them.

1. **Before asking the user what to do next:** Check TODO.md first. If it has pending items, present them instead of asking. Do not say "What would you like to work on?" when the answer is in the task list. (TB-01, CS-003)

2. **Verify entity IDs from instructions:** When the user references a specific experiment number, belief ID, requirement ID, or file name, verify it exists before acting on it. Do not substitute a different ID. If you generate output referencing an ID, confirm it matches the user's instruction. (TB-04, CS-020)

3. **Load task context on task switch:** When the user shifts to a different topic or task, search agentmemory for relevant beliefs about that topic before responding. Do not carry assumptions from the previous task. (TB-12)

4. **Do not overclaim rigor:** When describing project findings or status, do not use "extensive", "thoroughly validated", "comprehensive", or equivalent without qualifying the rigor tier. Most findings are from simulation or single-project testing. Say "simulated" or "tested on N samples" instead of implying broad validation. Check the source_type distribution before summarizing maturity. (TB-14, CS-005)

## Coding Guidelines

- All code must use strict static typing (pyright strict mode)
- Use `from __future__ import annotations` in every Python file
- Use uv for all package management
- Commits should be atomic and concise
- Do not commit large data files or results
- Do not use em dashes

## Project Context

This IS the agentmemory project -- a persistent memory system for AI coding agents. The system you are using (the MCP server) is the artifact this project builds. Testing the system on itself is intentional.

Phases 1-4 complete. Phase 5 complete (except REQ-011 cross-model, blocked on external access). v2.4.0, 84 experiments, 902 tests, 29 MCP tools, 29 production modules. All 15 triggered beliefs implemented. All 35 case studies have acceptance tests. All open research questions closed. Production system in daily use.
