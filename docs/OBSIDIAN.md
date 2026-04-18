# Obsidian Integration

agentmemory can sync its belief graph into an [Obsidian](https://obsidian.md) vault. Each belief becomes a markdown note with YAML frontmatter and wikilinked edges, so you can browse, search, and visualize your agent's knowledge using Obsidian's graph view and Dataview plugin.

![Obsidian graph view of an agentmemory belief network](images/obsidian-graph.png)

## Setup

```bash
# Point agentmemory at your vault
agentmemory settings obsidian.vault_path ~/obsidian-vault

# Sync beliefs to the vault (incremental, only writes changes)
agentmemory sync-obsidian
```

Or from Claude Code:

```
/mem:settings obsidian.vault_path ~/obsidian-vault
```

Sync is one-way by default (agentmemory -> Obsidian). Beliefs appear as markdown files in a `beliefs/` subfolder with auto-generated index notes grouped by type, confidence, and recency. The sync is incremental. It tracks content hashes and only writes files that changed.

For bidirectional sync, use `/mem:import-obsidian` to pull edits made in Obsidian back into the belief store.
