# Installing agentmemory

## Quick Start

```bash
# Install
pip install agentmemory    # or: uv tool install agentmemory

# Setup (writes commands, hooks, verifies CLI)
agentmemory setup

# Restart Claude Code, then:
/mem:onboard .
```

## What setup does

`agentmemory setup` performs these steps automatically:

1. Creates `~/.claude/commands/mem/*.md` (14 slash commands)
2. Removes legacy `~/.claude/skills/mem-*` files if present
3. Installs commit tracker hook in `~/.claude/settings.json`
4. Verifies database access
5. Runs a smoke test

After setup, restart Claude Code. Commands appear as `/mem:*`.

## Commands

```
/mem:onboard <path>     Scan and ingest a project
/mem:stats              Detailed analytics
/mem:health             Diagnostics
/mem:core [N]           Top N beliefs by confidence
/mem:search <query>     Search beliefs
/mem:locked             Show locked beliefs
/mem:new-belief <text>  Store a new belief
/mem:lock <text>        Create a locked belief
/mem:wonder <topic>     Deep research from graph context
/mem:settings           View or update settings
/mem:demote             Demote least-relevant locked beliefs
/mem:disable            Stop agentmemory for this session
/mem:enable             Resume agentmemory
/mem:help               Command reference
```

## Per-project isolation

Each project gets its own database at `~/.agentmemory/projects/<hash>/memory.db`. The hash is derived from the project's absolute path. The CLI auto-detects the project from cwd.

Override with `--project /path/to/project` or `AGENTMEMORY_DB=/path/to/db.sqlite`.

## Disabling

```bash
# In session: /mem:disable (stops tool calls for this session)
# Permanently: agentmemory uninstall (removes commands, keeps data)
# Nuclear: rm -rf ~/.agentmemory/ (deletes all data)
```

## Direct CLI usage

All commands work from the terminal without Claude Code:

```bash
agentmemory onboard /path/to/project
agentmemory search "query terms"
agentmemory core --top 10
agentmemory stats
agentmemory lock "always use strict typing"
```
