# Clean Reinstall Verification Plan

Verify the published install and onboarding instructions work from scratch on a real machine.

## Pre-Uninstall: Backup State

### Step 1: Snapshot current state (DO NOT SKIP)

```bash
# Back up all project databases (91K total beliefs across 4 projects)
cp -r ~/.agentmemory ~/.agentmemory.bak

# Record current git commit hash
cd ~/projects/agentmemory && git rev-parse HEAD > ~/.agentmemory.bak/git-commit.txt

# Snapshot installed hooks
ls -la ~/.claude/hooks/agentmemory* > ~/.agentmemory.bak/hooks-list.txt

# Snapshot MCP configs
cp ~/projects/project-c/.mcp.json ~/.agentmemory.bak/project-c-mcp.json
cp ~/projects/agentmemory/.mcp.json ~/.agentmemory.bak/agentmemory-mcp.json
```

Current footprint:
- Tool binary: `/home/user/.local/bin/agentmemory` (installed via `uv tool`)
- Data directory: `~/.agentmemory/` (config, root DB, 4 project DBs, 3 backup DBs)
- 9 hook scripts: `~/.claude/hooks/agentmemory-*.sh` and `agentmemory-*.py`
- Conversation logger: `~/.claude/hooks/conversation-logger.sh` (referenced in settings.json UserPromptSubmit hooks)
- MCP configs: `.mcp.json` in project-c and agentmemory projects
- Settings.json hooks: inject, directive-gate, commit-check, search-inject entries

## Uninstall: Remove Everything

### Step 2: Remove the tool binary

```bash
uv tool uninstall agentmemory
# Verify: which agentmemory should return nothing
```

### Step 3: Remove data directory

```bash
mv ~/.agentmemory ~/.agentmemory.bak  # already done in step 1 if you followed it
# Verify: ls ~/.agentmemory/ should not exist
```

### Step 4: Remove hooks

```bash
# Remove agentmemory hook scripts
rm ~/.claude/hooks/agentmemory-autosearch.sh
rm ~/.claude/hooks/agentmemory-db-path.py
rm ~/.claude/hooks/agentmemory-directive-gate.sh
rm ~/.claude/hooks/agentmemory-ingest-stop.sh
rm ~/.claude/hooks/agentmemory-inject.sh
rm ~/.claude/hooks/agentmemory-precompact-guard.sh
rm ~/.claude/hooks/agentmemory-search-inject.sh
rm ~/.claude/hooks/agentmemory-search-inline.py
rm ~/.claude/hooks/agentmemory-session-end.sh

# Remove agentmemory entries from settings.json
# (manual edit -- remove all hook entries referencing agentmemory or conversation-logger)
# Verify: grep agentmemory ~/.claude/settings.json should return nothing
```

### Step 5: Remove MCP configs

```bash
# Remove agentmemory entry from project .mcp.json files
# project-c:
python3 -c "
import json; p='$HOME/projects/project-c/.mcp.json'
d=json.loads(open(p).read())
d['mcpServers'].pop('agentmemory',None)
open(p,'w').write(json.dumps(d,indent=4))
"

# agentmemory project:
python3 -c "
import json; p='$HOME/projects/agentmemory/.mcp.json'
d=json.loads(open(p).read())
d['mcpServers'].pop('agentmemory',None)
open(p,'w').write(json.dumps(d,indent=4))
"
```

### Step 6: Verify clean

```bash
which agentmemory                        # should return nothing
ls ~/.agentmemory/ 2>/dev/null           # should not exist
ls ~/.claude/hooks/agentmemory* 2>/dev/null  # should return nothing
grep agentmemory ~/.claude/settings.json     # should return nothing
# Restart Claude Code, verify no agentmemory tools appear
```

## Reinstall: Follow Published Instructions

### Step 7: Clone and install from GitHub (as a new user would)

Follow the README at github.com/robotrocketscience/agentmemory exactly.
Do NOT reference the local dev copy at ~/projects/agentmemory.
Install via the published method.

### Step 8: Configure MCP server

Follow the published MCP setup instructions.
Verify the server starts and tools appear in Claude Code.

### Step 9: Configure hooks

Follow published hook setup instructions.
Verify UserPromptSubmit hooks fire on first message.

### Step 10: Onboard a project

Run the published onboard command against a test project.
Verify beliefs are created, DB exists, search returns results.

## Post-Reinstall: Restore and Verify

### Step 11: Restore project databases (OPTIONAL)

```bash
# If you want accumulated context back:
cp -r ~/.agentmemory.bak/projects/* ~/.agentmemory/projects/

# If you want a fully clean start: leave them gone
```

### Step 12: Run A/B test with fresh install

Fresh DB (zero beliefs) vs session logs from the mature install.
This is the organic maturation comparison.

## What Could Go Wrong

| Risk | Mitigation |
|---|---|
| Published README missing steps | That's the point -- find and fix them |
| Hooks reference hardcoded paths | Verify hooks use `which agentmemory` not absolute paths |
| Config assumes existing state | Verify config.json is created fresh on first run |
| Onboarding fails without prior DB | Verify _resolve_server_db() creates dirs correctly |
| MCP server fails without onboarding | Verify search returns clean "no beliefs" message |
