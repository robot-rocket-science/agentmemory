<sub>[Contents](README.md) · Next: [Chapter 2 - Workflow →](WORKFLOW.md)</sub>

# Chapter 1. Installation

## Prerequisites

**[uv](https://docs.astral.sh/uv/)** (Python package manager). uv handles Python installation automatically, you do not need Python installed separately.

```bash
# Install uv if you do not have it
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** (or any MCP-compatible agent CLI). agentmemory runs as an MCP server inside the agent.

**[Obsidian](https://obsidian.md)** (optional). For browsing and visualizing the belief graph. Not required for core functionality. See [OBSIDIAN.md](OBSIDIAN.md).

## Step 1: Install agentmemory

```bash
uv pip install git+https://github.com/yoshi280/agentmemory.git
```

Verify it installed:

```bash
agentmemory --help
```

If you get `command not found`, try installing as a tool instead:

```bash
uv tool install git+https://github.com/yoshi280/agentmemory.git
```

## Step 2: Run setup

```bash
agentmemory setup
```

This does three things:
1. Writes `/mem:*` slash commands to `~/.claude/commands/mem/`
2. Registers the MCP server in your project's `.mcp.json`
3. Adds session hooks to `~/.claude/settings.json` (context injection, conversation logging)

## Step 3: Restart Claude Code

Close and reopen Claude Code. The MCP server starts automatically on launch.

## Step 4: Verify it works

In Claude Code, run:

```
/mem:status
```

You should see a status report with belief counts, session info, and system health. If you see an error, check Troubleshooting below.

## Step 5: Onboard your project

```
/mem:onboard .
```

This scans your project directory and ingests structure from git history, code, docs, and configuration. Takes 10-30 seconds depending on project size.

That is it. agentmemory will automatically capture decisions, corrections, and context from your conversations.

## Per-project isolation

Each project gets its own database at `~/.agentmemory/projects/<hash>/memory.db`. The hash is derived from the project's absolute path. The CLI auto-detects the project from cwd.

Override with `--project /path/to/project` or `AGENTMEMORY_DB=/path/to/db.sqlite`.

## Disabling

```bash
# In session:     /mem:disable       (stops tool calls for this session)
# Permanently:    agentmemory uninstall   (removes commands, keeps data)
# Nuclear:        rm -rf ~/.agentmemory/  (deletes all data)
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `agentmemory: command not found` | Run `uv tool install git+https://github.com/yoshi280/agentmemory.git` or check that `~/.local/bin` is in your PATH |
| `/mem:status` returns an error | Restart Claude Code. The MCP server needs a fresh start after setup |
| Slash commands not showing up | Run `agentmemory setup` again, then restart Claude Code |
| MCP tools not responding | Check `.mcp.json` exists in your project root. If not, run `agentmemory setup` from the project directory |
| SQLite lock errors | Run `agentmemory health` to diagnose, or manually clear the WAL: `python3 -c "import sqlite3; sqlite3.connect('~/.agentmemory/projects/<hash>/memory.db').execute('PRAGMA wal_checkpoint(TRUNCATE)')"` |

---

<sub>[Contents](README.md) · Next: [Chapter 2 - Workflow →](WORKFLOW.md)</sub>
