---
name: agentmemory
description: Persistent memory for AI coding agents. Use when asked about agentmemory, memory system, onboarding projects, searching beliefs, or memory status.
allowed-tools: Bash, Read
---

# agentmemory

Persistent memory system for AI coding agents. Provides project onboarding, belief search, corrections, and locked constraints.

## CLI Commands

Run via bash:

```bash
uv run --project /Users/thelorax/projects/agentmemory agentmemory <command>
```

Commands: `onboard <path>`, `status`, `search <query>`, `locked`
