# agentmemory Installation Pattern

## Research findings (2026-04-10)

### How GSD registers slash commands in Claude Code

GSD (get-shit-done) uses an npm package with an installer script:

```
npx get-shit-done-cc --claude --global
```

This runs `bin/install.js` which copies files into `~/.claude/`:
- `~/.claude/commands/gsd/*.md` -- slash commands (one .md per command)
- `~/.claude/agents/gsd-*.md` -- agent definitions
- `~/.claude/skills/gsd-*/SKILL.md` -- skills
- `.claude/get-shit-done/workflows/` -- workflow files referenced by commands

Commands appear as `/gsd:command-name`. The filename (minus .md) becomes the command name. The directory name becomes the namespace prefix.

### How MemPalace registers as a Claude Code plugin

MemPalace uses the Claude Code plugin marketplace system:

```
claude plugin marketplace add milla-jovovich/mempalace
claude plugin install --scope user mempalace
```

This clones the GitHub repo to `~/.claude/plugins/marketplaces/mempalace/` and reads `.claude-plugin/plugin.json` which declares:
- MCP server launch command
- Hooks (Stop, PreCompact)
- Commands in `.claude-plugin/commands/*.md`

Commands appear as `/mempalace:command-name`.

### Where Claude Code discovers slash commands

Three paths, in order of reliability (based on testing):

1. **`~/.claude/commands/<namespace>/*.md`** -- global user commands. Works reliably. This is what GSD uses. Commands appear as `/<namespace>:<filename>`.

2. **`.claude/commands/*.md`** (project-level) -- project-scoped commands. Works. Tested and confirmed in this session. Commands appear as `/<filename>`.

3. **`.claude-plugin/commands/*.md`** (plugin system) -- requires marketplace registration + plugin install. More complex. This is what MemPalace uses.

### Chosen pattern for agentmemory

Use the GSD pattern:
- Distribute as a Python package via PyPI (`uv tool install agentmemory` or `pip install agentmemory`)
- Package includes an installer: `agentmemory setup --claude --global`
- Installer copies command .md files to `~/.claude/commands/mem/`
- Installer writes MCP config to project `.mcp.json` or global config
- Commands appear as `/mem:onboard`, `/mem:status`, etc.

### Command .md format (GSD style)

```yaml
---
name: mem:command-name
description: One-line description
allowed-tools:
  - Bash
  - Read
---
<objective>
What this command does.
</objective>

<process>
Step-by-step instructions for Claude to execute.
</process>
```

### Key insight

The slash command system is always LLM-mediated -- Claude reads the .md file as a prompt and executes it. But by making the command prompt say "run this CLI command and show the output", the LLM overhead is minimal (one tool call, no reasoning).
