# Installing agentmemory

## Fresh Environment Setup

```bash
# 1. Clone the project
git clone <repo-url> agentmemory
cd agentmemory

# 2. Install dependencies
uv sync

# 3. Verify tests pass
uv run pytest tests/ -v

# 4. Register MCP server with Claude Code (project-scoped)
claude mcp add agentmemory --scope project -- \
  uv run --project /path/to/agentmemory fastmcp run src/agentmemory/server.py

# 5. Add SessionStart hook for locked belief injection
# Add this to ~/.claude/settings.json under hooks.SessionStart:
#
# {
#   "hooks": [{
#     "type": "command",
#     "command": "/path/to/agentmemory/.claude/hooks/agentmemory-inject.sh",
#     "statusMessage": "Loading agentmemory locked beliefs..."
#   }]
# }
#
# Or copy the hook script:
cp src/agentmemory/hooks/session_start.sh ~/.claude/hooks/agentmemory-inject.sh
chmod +x ~/.claude/hooks/agentmemory-inject.sh

# 6. Verify MCP server loads
uv run python -c "from agentmemory.server import mcp; print(f'Server: {mcp.name}')"
```

The database is created automatically at `~/.agentmemory/memory.db` on first use.

## Onboarding a Project

Start a new Claude Code session in the project directory. The MCP server will be available.

```
# In Claude Code conversation:

> onboard the conversation logs
# Claude calls: agentmemory_onboard("~/.claude/conversation-logs/turns.jsonl")

> remember: always use uv for package management
# Claude calls: agentmemory_remember("always use uv for package management")

> remember: this project uses PostgreSQL, not MySQL
# Claude calls: agentmemory_remember("this project uses PostgreSQL, not MySQL")

> status
# Claude calls: agentmemory_status()
```

## Verifying the System Works

```
# Check locked beliefs are injected at session start:
# Start a new session. You should see "Loading agentmemory locked beliefs..."
# in the status area, and locked beliefs will appear in the context.

# Check search works:
> search for our database decision
# Claude calls: agentmemory_search("database decision")
# Should return the PostgreSQL belief.

# Check corrections work:
> correct: we switched to SQLite, not PostgreSQL
# Claude calls: agentmemory_correct("we switched to SQLite, not PostgreSQL", replaces="PostgreSQL")
# Old belief superseded. New belief locked.
```

## Disabling the System

If the system causes problems:

```bash
# Option 1: Remove the MCP server registration
rm .mcp.json

# Option 2: Disable the SessionStart hook (comment out in settings.json)

# Option 3: In conversation, say "disable agentmemory"
# The LLM will stop calling tools for the rest of the session.
```

The database remains at `~/.agentmemory/memory.db` and can be queried directly:

```bash
# View all locked beliefs
sqlite3 ~/.agentmemory/memory.db "SELECT content FROM beliefs WHERE locked = 1 AND valid_to IS NULL"

# View all beliefs
sqlite3 ~/.agentmemory/memory.db "SELECT id, belief_type, locked, content FROM beliefs WHERE valid_to IS NULL ORDER BY created_at DESC LIMIT 20"

# View status
sqlite3 ~/.agentmemory/memory.db "SELECT 'beliefs' as type, count(*) FROM beliefs UNION SELECT 'locked', count(*) FROM beliefs WHERE locked=1 UNION SELECT 'observations', count(*) FROM observations"
```

## Resetting the System

```bash
# Full reset (lose all data)
rm ~/.agentmemory/memory.db

# The database is recreated automatically on next MCP server start.
```
