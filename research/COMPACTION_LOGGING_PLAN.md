# Compaction-Aware Conversation Logging

## Problem

Claude Code sessions rack up huge token counts. The built-in compaction mechanism compresses older context when approaching limits. Currently:
- `conversation-logger.sh` logs every turn to `~/.claude/conversation-logs/turns.jsonl`
- No awareness of when compaction happens
- No rotation -- file grows forever
- No way to evaluate whether compaction lost important information

## Architecture

```
UserPromptSubmit / Stop hooks (existing)
    |
    v
conversation-logger.sh --> turns.jsonl (full uncompacted ground truth)
    |
PreCompact hook (new)
    |-- log compaction boundary marker to turns.jsonl
    |-- rotate: move turns.jsonl to turns-{timestamp}.jsonl
    |
PostCompact hook (new)
    |-- log compaction-complete marker
    |-- trigger agentmemory ingestion of the rotated segment
```

## What Changes

### 1. Update conversation-logger.sh

Add handling for PreCompact and PostCompact hook events:
- PreCompact: write a `{"event": "compaction_start", ...}` marker to turns.jsonl, then rotate the file
- PostCompact: write a `{"event": "compaction_complete", ...}` marker to the new turns.jsonl

### 2. Add hooks to settings.json

```json
"PreCompact": [
  {
    "hooks": [
      {
        "type": "command",
        "command": "/home/user/.claude/hooks/conversation-logger.sh"
      }
    ]
  }
],
"PostCompact": [
  {
    "hooks": [
      {
        "type": "command",
        "command": "/home/user/.claude/hooks/conversation-logger.sh"
      }
    ]
  }
]
```

### 3. Add rotation logic

On PreCompact:
1. Write compaction boundary marker to current turns.jsonl
2. Move turns.jsonl to `turns-{ISO8601-timestamp}.jsonl` in an `archive/` subdirectory
3. New turns start in a fresh turns.jsonl

This means each archived segment represents one compaction window -- the full conversation from session start (or last compaction) through the compaction trigger.

### 4. Add agentmemory ingestion trigger

On PostCompact, run `agentmemory ingest` on the most recently archived segment. This feeds the pre-compaction conversation into the memory system before it's lost to compression.

## Compaction Quality Evaluation (Future)

With this in place, agentmemory has:
- The full pre-compaction conversation (archived segment)
- The post-compaction session context (ongoing turns.jsonl)
- Timestamps marking exactly when compaction occurred

Future work: compare what the agent "knows" post-compaction against what was in the full log. Beliefs that were in the pre-compaction conversation but absent from post-compaction behavior = compaction information loss. This is a natural test case generator.

## Files Modified

1. `~/.claude/hooks/conversation-logger.sh` -- add PreCompact/PostCompact handling + rotation
2. `~/.claude/settings.json` -- add PreCompact and PostCompact hook entries
