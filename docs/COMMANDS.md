# `/mem:` Command Reference

All commands are available as Claude Code slash commands after setup.

| Command | Description |
|---------|-------------|
| `/mem:search <query>` | Search beliefs relevant to a query |
| `/mem:remember <text>` | Store a new belief |
| `/mem:correct <text>` | Record a user correction (supersedes conflicting beliefs) |
| `/mem:lock <belief_id>` | Lock a belief as a permanent constraint |
| `/mem:locked` | Show all locked beliefs |
| `/mem:onboard <path>` | Scan and ingest a project directory |
| `/mem:status` | System analytics |
| `/mem:core [n]` | Top N beliefs by confidence |
| `/mem:stats` | Detailed analytics |
| `/mem:reason <question>` | Graph-aware hypothesis testing |
| `/mem:wonder <topic>` | Deep research with graph context |
| `/mem:feedback <id> <outcome>` | Provide feedback on a belief (used/harmful/ignored) |
| `/mem:delete <id>` | Soft-delete a belief |
| `/mem:settings` | View or update settings |
| `/mem:enable-telemetry` | Enable anonymous performance logging |
| `/mem:disable-telemetry` | Disable anonymous performance logging |
| `/mem:disable` | Disable agentmemory for the session |
| `/mem:enable` | Re-enable agentmemory |
| `/mem:help` | Command reference |

All commands also work from the terminal without Claude Code:

```bash
agentmemory search "query terms"
agentmemory core --top 10
agentmemory stats
agentmemory onboard /path/to/project
```
