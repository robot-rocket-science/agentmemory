<sub>[← Chapter 2 - Workflow](WORKFLOW.md) · [Contents](README.md) · Next: [Chapter 4 - Obsidian Integration →](OBSIDIAN.md)</sub>

# Chapter 3. Command Reference

Most commands are available as Claude Code slash commands after setup. Some tools (e.g., `correct`, `feedback`) are MCP-only and called by the agent automatically.

| Command | Description |
|---------|-------------|
| `/mem:search <query>` | Search beliefs relevant to a query |
| `/mem:new-belief <text>` | Store a new belief |
| `/mem:lock <belief_id>` | Lock a belief as a permanent constraint |
| `/mem:unlock <belief_id>` | Unlock a belief |
| `/mem:locked` | Show all locked beliefs |
| `/mem:onboard <path>` | Scan and ingest a project directory |
| `/mem:core [n]` | Top N beliefs by confidence |
| `/mem:stats` | Detailed analytics |
| `/mem:health` | Run diagnostics on the memory system |
| `/mem:reason <question>` | Graph-aware hypothesis testing |
| `/mem:wonder <topic>` | Deep research with graph context |
| `/mem:delete <id>` | Soft-delete a belief |
| `/mem:demote` | Demote least-relevant locked beliefs to regular beliefs |
| `/mem:settings` | View or update settings |
| `/mem:disable` | Disable agentmemory for the session |
| `/mem:enable` | Re-enable agentmemory |
| `/mem:help` | Command reference |

Additional tools are available via MCP (called by the agent automatically): `remember`, `correct`, `observe`, `feedback`, `ingest`, `search`, `status`, `create_beliefs`, `reclassify`, `bulk_delete`, `snapshot`, `timeline`, `evolution`, `diff`, `graph_metrics`, `link_docs`, `import_obsidian`, `sync_obsidian`.

All commands also work from the terminal without Claude Code:

```bash
agentmemory search "query terms"
agentmemory core --top 10
agentmemory stats
agentmemory onboard /path/to/project
```

---

<sub>[← Chapter 2 - Workflow](WORKFLOW.md) · [Contents](README.md) · Next: [Chapter 4 - Obsidian Integration →](OBSIDIAN.md)</sub>
