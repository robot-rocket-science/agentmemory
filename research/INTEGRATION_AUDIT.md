# Agentmemory Integration Audit

Date: 2026-04-11

---

## 1. MCP Server (server.py)

8 tools registered via FastMCP. Entry point: `python -m agentmemory.server`.
Config: `.mcp.json` uses `uv run --project ... python -m agentmemory.server` (stdio transport).

### Tool-by-Tool Assessment

| Tool | Status | Notes |
|------|--------|-------|
| `search` | **Working** | Delegates to `retrieve()` pipeline (FTS5 + scoring + packing). Returns formatted text. Empty-DB case handled ("No beliefs found"). Budget parameter works. |
| `remember` | **Working** | Creates locked belief with alpha=9.0, beta=0.5. Creates session on first call. Returns confirmation with ID. |
| `correct` | **Working** | Creates locked correction belief. `replaces` parameter triggers FTS5 search to find and supersede old belief. Skips self-match and already-superseded beliefs. Only supersedes first match -- this is intentional. |
| `observe` | **Working** | Records raw observation without belief creation. Session-scoped. |
| `status` | **Working** | Returns counts dict from `store.status()`. Works on empty DB. |
| `get_locked` | **Working** | Returns all locked beliefs. Empty case handled. |
| `onboard` | **Working** | Scans project via `scan_project()`, feeds nodes through ingest pipeline, stores graph edges. Validates path is directory. |
| `ingest` | **Working** | Full pipeline: sentence extraction, correction detection, classification, belief creation. `use_llm=False` (offline-only). |

### Edge Cases and Issues

1. **No timeout on store operations.** A corrupted or locked SQLite DB will hang the MCP server indefinitely. FastMCP has no per-tool timeout.
2. **Store singleton never closes.** `_store` is created once and never closed. On normal MCP shutdown this is fine (process exit closes the file), but if the process is kept alive across sessions, the connection accumulates WAL data.
3. **Session is never explicitly ended.** `_ensure_session()` creates a session on first tool call but there is no end-session logic. This is acceptable for MCP (one session per process lifecycle), but the session table will accumulate rows with no `ended_at`.
4. **`correct` supersedes only the first match.** If the user says "X is wrong" and there are multiple beliefs about X, only one gets superseded. The rest remain active. This could leave contradictory beliefs in the store.
5. **`onboard` stores edges with scanner IDs, not belief IDs.** The MCP server's `onboard` tool does NOT do the scanner-to-belief ID mapping that the CLI version does (lines 400-432 of cli.py). This means graph edges from MCP onboard have dangling references.
6. **No input validation on `remember`/`correct` for empty strings.** Passing `text=""` creates a belief with empty content. The CLI validates; the MCP tools do not.

---

## 2. CLI (cli.py)

Entry point: `agentmemory` (installed at `/home/user/.local/bin/agentmemory`).

### Command-by-Command Assessment

| Command | Status | Notes |
|---------|--------|-------|
| `setup` | **Working** | Creates command .md files, cleans legacy skills, verifies DB, installs commit hook, runs smoke test. |
| `onboard` | **Working** | Full scan + ingest with node-to-belief ID mapping (better than MCP version). Progress reporting. |
| `stats` | **Working** | Shows counts, type/source breakdown, confidence distribution (p25/p50/p75). Uses raw SQL queries. |
| `health` | **Stub** | Calls `cmd_stats`, then prints TODO placeholders. No actual diagnostics implemented. |
| `core` | **Working** | Fetches all active beliefs, scores with `core_score()`, shows top N. |
| `search` | **Working** | Uses `retrieve()` pipeline with budget control. |
| `locked` | **Working** | Shows locked beliefs with warn/cap thresholds from config. |
| `remember` | **Working** | Creates belief (NOT locked, unlike MCP `remember` which IS locked). This is a semantic difference. |
| `lock` | **Working** | Creates locked belief. |
| `wonder` | **Partial stub** | Retrieves beliefs via `retrieve()`, prints them, then says "Deep research prompt template: TODO". The slash command `/mem:wonder` fills the gap by having Claude spawn subagents, but the CLI alone is incomplete. |
| `reason` | **Working** | Full graph-aware reasoning: FTS5 retrieval, BFS graph expansion, uncertainty scoring, contradiction detection. Well-implemented. |
| `unlock` | **Working** | Scores locked beliefs, unlocks the N lowest-scoring. Uses private `_conn` attribute directly. |
| `settings` | **Working** | View and update config for wonder/reason/core/locked modules. |
| `commit-check` | **Working** | Checks time/changes since last commit. Always exits 0 (safe for hooks). |
| `commit-config` | **Working** | View/update commit tracker thresholds. |
| `mcp` | **Working** | Starts MCP server via `mcp.run()`. |
| `uninstall` | **Working** | Removes command files and legacy skills. Preserves data. |

### CLI Issues

1. **`remember` (CLI) vs `remember` (MCP) semantic mismatch.** CLI `remember` creates an UNLOCKED belief. MCP `remember` creates a LOCKED belief. Users who mix CLI and MCP will get inconsistent behavior. CLAUDE.md tells the agent to use MCP `remember` for permanent rules, so MCP behavior is "correct" per design, but the CLI command name is misleading.
2. **No `demote` CLI subcommand.** The slash command `/mem:demote` calls `uv run agentmemory demote --count N`, but no `demote` subcommand exists. This will fail with a parse error. The actual CLI command is `unlock`.
3. **`health` is a stub.** Prints TODO items. `/mem:health` routes to it, so users get no real diagnostics.
4. **`unlock` accesses `store._conn` directly.** Uses private attribute, bypassing any store-level invariants. Not a functional bug, but fragile.

---

## 3. Hooks

### SessionStart: agentmemory-inject.sh

**Status: Working**

- Runs inline Python3 + SQLite (no `uv run` dependency) for fast startup (~120ms)
- Resolves per-project DB via SHA-256 hash of cwd
- Injects up to 20 locked beliefs and 10 core beliefs as `additionalContext`
- Gracefully exits 0 if DB doesn't exist (new project)
- All exceptions caught and silenced -- prevents hook from blocking Claude startup
- **Executable: yes** (rwxr-xr-x)

**Issues:**
- Core belief ranking uses a simplified type/source/length heuristic, not the full `core_score()` function. This means injected core beliefs may differ from what `agentmemory core` shows.
- Hard limit of 20 locked beliefs. If the user has more, excess are silently dropped. No warning.

### UserPromptSubmit + Stop: conversation-logger.sh

**Status: Working (with caveats)**

- Captures user prompts and assistant responses to `~/.claude/conversation-logs/turns.jsonl`
- Log file exists and has active data (273KB, entries from Apr 10-11)
- **Executable: yes** (rwxr-xr-x)

**Issues:**
- Reads `hook_event_name` (snake_case) from payload. Claude Code hooks may send this differently across versions. Currently works based on evidence (log file has real data), but the field name is not documented in official Claude Code hook specs.
- Stop hook payload field `last_assistant_message` -- unclear if Claude Code actually populates this. The `stop_reason` field appears empty in logged entries, suggesting the payload format may be partially unsupported.
- No log rotation. The JSONL file grows forever. At ~273KB for 2 days of use, it will reach several MB in weeks.

### PreToolUse: commit-check

**Status: Working**

- Runs on every Bash tool use (matcher: "Bash")
- Calls `agentmemory commit-check` (found on PATH)
- Always exits 0 (never blocks operations)
- **No timeout specified** in settings.json hook config. If `agentmemory commit-check` hangs (e.g., SQLite lock), it could block every Bash tool call indefinitely.

### Hooks NOT Wired in settings.json

| Hook File | Status |
|-----------|--------|
| `agentmemory-autosearch.sh` | **Not active.** Exists on disk but NOT referenced in settings.json. Would auto-search memory on every user prompt and inject relevant beliefs. |
| `agentmemory-ingest-stop.sh` | **Not active.** Exists on disk but NOT referenced in settings.json. Would ingest conversation text on Stop hook. Has a bug: uses `uv run agentmemory remember` to ingest raw conversation JSON, which stores it as a single belief rather than running the ingest pipeline. |

---

## 4. Skills (Slash Commands)

17 skill files in `~/.claude/commands/mem/`.

### Command-by-Command Assessment

| Skill | CLI Backend | Status | Notes |
|-------|-------------|--------|-------|
| `/mem:onboard` | `agentmemory onboard` | **Working** | |
| `/mem:stats` | `agentmemory stats` | **Working** | |
| `/mem:health` | `agentmemory health` | **Stub** | Backend is a stub |
| `/mem:core` | `agentmemory core` | **Working** | |
| `/mem:search` | `agentmemory search` | **Working** | |
| `/mem:locked` | `agentmemory locked` | **Working** | |
| `/mem:new-belief` | `agentmemory remember` | **Working** | Creates unlocked belief (CLI semantics) |
| `/mem:lock` | `agentmemory lock` | **Working** | |
| `/mem:wonder` | `agentmemory wonder` + subagents | **Partial** | CLI output is sparse; skill definition orchestrates subagents to fill gap |
| `/mem:settings` | `agentmemory settings` | **Working** | |
| `/mem:demote` | `agentmemory demote` | **BROKEN** | No `demote` subcommand exists. Should be `unlock`. |
| `/mem:disable` | (behavior only) | **Working** | Tells Claude to stop calling MCP tools. No backend needed. |
| `/mem:enable` | (behavior only) | **Working** | Tells Claude to resume MCP tools. No backend needed. |
| `/mem:help` | (text only) | **Working** | Displays command reference |

### Skills NOT in commands/ but referenced in CLI _COMMAND_DEFS

| Skill Definition | Slash Command File | Status |
|------------------|--------------------|--------|
| `reason` | Not in `~/.claude/commands/mem/` | **Missing.** CLI has full `reason` command but no slash command routes to it. |
| `unlock` | Not in `~/.claude/commands/mem/` | **Missing.** CLI has `unlock` command but no slash command (only `/mem:demote` which calls wrong name). |

---

## 5. Integration Gaps

### A. MCP onboard vs CLI onboard (Edge ID mapping)
The MCP `onboard` tool stores graph edges with raw scanner node IDs. The CLI `onboard` command maps scanner IDs to belief IDs via content hash. This means projects onboarded via MCP (the `/mem:onboard` path that Claude would naturally use) have a broken knowledge graph with dangling edge references.

### B. Autosearch hook is not wired
`agentmemory-autosearch.sh` exists and would automatically inject relevant memories on every user prompt -- a core UX feature for passive memory retrieval. But it is not in settings.json, so it never runs. Users only get memory context from the SessionStart hook (locked + core beliefs) and explicit MCP search calls.

### C. Ingest-stop hook is not wired AND is buggy
`agentmemory-ingest-stop.sh` exists but is not in settings.json. Even if wired, it has a bug: it runs `agentmemory remember "$CONV_TEXT"` which stores the raw text as a single belief, rather than `agentmemory ingest` which would run the full pipeline (sentence extraction, correction detection, classification).

### D. No `/mem:reason` skill
The `reason` command is the most sophisticated CLI feature (graph-aware BFS + uncertainty + contradiction detection) but there is no slash command to invoke it. Users would need to know to run `uv run agentmemory reason "query"` manually.

### E. `/mem:demote` calls nonexistent command
The skill file calls `agentmemory demote` but the CLI subcommand is `unlock`. This will fail every time.

### F. Conversation logger captures but does not ingest
The conversation logger writes to JSONL, but nothing reads that JSONL back into agentmemory. The MCP `onboard` tool scans project files, not conversation logs. There is an `onboard` CLI/MCP tool, but it uses `scan_project()` which scans git/docs/code -- not JSONL conversation logs.

---

## 6. Reliability Issues

### Critical
1. **`/mem:demote` is broken.** Will error on every invocation due to nonexistent `demote` CLI subcommand.
2. **MCP `onboard` produces dangling graph edges.** Any project onboarded via the MCP tool (which is the natural path) will have broken graph references, degrading `reason` and graph-expansion features.

### High
3. **No timeout on commit-check PreToolUse hook.** If SQLite locks up, every Bash tool call hangs. Add `"timeout": 5` to the hook config.
4. **Empty string input not validated on MCP tools.** `remember("")` and `correct("")` create empty beliefs that pollute search results.
5. **Autosearch hook not wired.** Without it, Claude only has SessionStart context (stale by definition) and must explicitly call `search` for every question. The CLAUDE.md instructions tell the agent to search, but agents often skip this step.

### Medium
6. **CLI `remember` vs MCP `remember` semantic mismatch.** `/mem:new-belief` creates unlocked beliefs (via CLI). MCP `remember` creates locked beliefs. A user who says "remember X" via slash command vs MCP tool gets different results.
7. **SessionStart injects max 20 locked beliefs silently.** No warning if more exist. User could have 50 locked beliefs and only see 20 at session start.
8. **Conversation logs never ingested.** Raw JSONL accumulates but is not processed into the memory store. The pipeline exists (`ingest_turn()`) but nothing connects the log file to it.
9. **`health` is a stub.** `/mem:health` shows stats + TODO messages. No actual diagnostic checks.

### Low
10. **Session rows never get `ended_at`.** Minor data quality issue in the sessions table.
11. **No log rotation on conversation-logger.sh.** Will grow without bound.
12. **`unlock` uses `store._conn` directly.** Works but bypasses store encapsulation.

---

## 7. Recommendations (by impact)

### Immediate fixes (minutes each)

1. **Fix `/mem:demote` skill:** Change `agentmemory demote` to `agentmemory unlock` in the skill definition and the `_COMMAND_DEFS` dict, or add `demote` as a CLI alias for `unlock`.

2. **Add timeout to commit-check hook:** In `settings.json`, add `"timeout": 5` to the agentmemory commit-check hook entry.

3. **Add empty-string validation to MCP tools:** In `remember()` and `correct()`, return an error message if `text.strip()` is empty.

### High-value improvements (hours each)

4. **Wire autosearch hook:** Add `agentmemory-autosearch.sh` to settings.json under UserPromptSubmit. This gives passive memory retrieval on every prompt -- the single biggest UX improvement possible.

5. **Port CLI onboard's ID mapping to MCP onboard:** Copy the `node_to_belief` mapping logic from `cmd_onboard()` into the MCP `onboard` tool so graph edges reference real belief IDs.

6. **Create `/mem:reason` skill:** Add `reason.md` to `~/.claude/commands/mem/` routing to `uv run agentmemory reason "$ARGUMENTS"`. This exposes the most powerful retrieval mode.

7. **Fix ingest-stop hook and wire it:** Change `agentmemory remember` to route through `ingest` instead, and add it to settings.json under the Stop hook.

### Structural improvements (days)

8. **Build conversation log ingestion pipeline:** Create a command that reads `turns.jsonl` and feeds each turn through `ingest_turn()`. This closes the loop: conversation -> log -> memory store.

9. **Implement `health` diagnostics:** Orphaned beliefs, FTS5 integrity check, graph connectivity, stale sessions.

10. **Unify remember semantics:** Decide if CLI `remember` should create locked or unlocked beliefs. Align with MCP behavior or rename the CLI command to avoid confusion.
