# CLAUDE.md Overlap Audit (2026-04-11)

## Context

After bulk-unlocking 2,914 auto-locked beliefs (created before user-confirmation workflow),
we compared the formerly-locked beliefs against directives in both CLAUDE.md files
(global: ~/.claude/CLAUDE.md and project: ./CLAUDE.md).

## Method

- Extracted 33 distinct directives from both CLAUDE.md files
- Compared each of 2,910 formerly-locked beliefs using keyword overlap (40%) + sequence similarity (60%)
- Threshold: combined > 0.25 or keyword overlap > 0.4

## Results

43 beliefs overlap with CLAUDE.md instructions. 11 are exact or near-exact duplicates.

### Exact duplicates (belief restates CLAUDE.md line verbatim)

| Belief ID | Content | CLAUDE.md source |
|-----------|---------|-----------------|
| 0f52c99bd79d | Use uv for all package management | project |
| c13c83409eb9 | Do not commit large data files or results | project |
| 4c8bec9318e4 | Do not use em dashes | both |
| 50ed2c8c4f87 | Commits should be atomic and concise | project |
| d3c48003d8e8 | Do not store ephemeral content (greetings, status updates, "ok", "proceed") | project |
| d2479c42e705 | Do not re-ask the user for information that might be in memory | project |
| 31e0e283dabb | Do not add co-authorship to any generated files | global |
| 4a124c6d2bdd | This IS the agentmemory project -- a persistent memory system for AI coding agents | project |
| 32739f58825e | Do not ignore locked beliefs | project |
| e48b4f9bdd85 | Add strict static typing to all Python files | project |
| c669782640e4 | Use __future__ annotations in every Python file | project |

### Near-duplicates (belief references CLAUDE.md content with minor variation)

| Belief ID | Content | Related directive |
|-----------|---------|------------------|
| 66ba16aac097 | Example: User says "always use uv for package management" -> agent calls... | uv_package_manager |
| 85644d7aea1b | Let's settle this -- we're using uv for package management, not pip or poetry | uv_package_manager |
| f639846ed94d | [factual] Let's settle this -- we're using uv for package management... | uv_package_manager |
| 97fea7ea166c | Behavioral rule: never cite unverified sources | cite_sources |

### Contextual references (discuss the topic, don't restate the rule)

Remaining ~28 beliefs mention locked beliefs, MCP, uv, typing etc. in context of
research findings and case studies. These are not duplicates -- they're project knowledge
that happens to reference the same topics.

## Blocker: No deletion mechanism

As of this audit, agentmemory has no API or CLI command to delete individual beliefs.
The only removal option is `rm -rf ~/.agentmemory/` (full wipe).

### What's needed

- `mcp__agentmemory__delete(belief_id)` -- soft-delete (set valid_to = now)
- `/mem:delete <id>` or `/mem:forget <id>` -- CLI command
- Bulk variant: `delete_where(source_type=..., content_like=...)` for cleanup operations like this one
- Policy question: should deleted beliefs be hard-deleted or soft-deleted (valid_to set, still queryable with flag)?

### Recommendation

Soft-delete via `valid_to` is the safer path -- it's already in the schema and
the retrieval pipeline already filters on it. A hard delete loses audit trail.

## Action items

- [ ] Implement belief deletion (soft-delete via valid_to)
- [ ] Expose as MCP tool and CLI command
- [ ] Once available: delete the 11 exact duplicates listed above
- [ ] Consider: auto-detect CLAUDE.md overlap at ingestion time and skip/warn
