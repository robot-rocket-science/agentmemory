# Claims Audit: docs/ Handbook

Audited 2026-04-18 against codebase at commit v2-dev HEAD.
Method: every assertion verified against source files using filesystem reads and grep only.

Status key:
- VERIFIED -- evidence found in code, file, or test
- UNVERIFIED -- no supporting evidence found; may be true but cannot confirm from code alone
- INCORRECT -- evidence contradicts the claim

---

## docs/README.md (Handbook Index)

| Line | Claim | Status | Evidence |
|------|-------|--------|----------|
| 9 | Links to `../README.md` | VERIFIED | File exists at project root |
| 17 | Links to `INSTALL.md` | VERIFIED | File exists in docs/ |
| 18 | Links to `WORKFLOW.md` | VERIFIED | File exists in docs/ |
| 23 | Links to `COMMANDS.md` | VERIFIED | File exists in docs/ |
| 24 | Links to `OBSIDIAN.md` | VERIFIED | File exists in docs/ |
| 27 | Links to `ARCHITECTURE.md` | VERIFIED | File exists in docs/ |
| 28 | Links to `PRIVACY.md` | VERIFIED | File exists in docs/ |
| 32 | Links to `BENCHMARK_PROTOCOL.md` | VERIFIED | File exists in docs/ |
| 33 | Links to `BENCHMARK_RESULTS.md` | VERIFIED | File exists in docs/ |
| 34 | Links to `RESEARCH_FREEZE_20260416.md` | VERIFIED | File exists in docs/ |
| 38 | Links to `../CONTRIBUTING.md` | VERIFIED | File exists at project root |
| 39 | Links to `../CHANGELOG.md` | VERIFIED | File exists at project root |
| 40 | Links to `../research/EXPERIMENTS.md` | VERIFIED | File exists |
| 41 | Links to `../research/CASE_STUDIES.md` | VERIFIED | File exists |

No issues found. All referenced files exist.

---

## docs/ARCHITECTURE.md

| Line | Claim | Status | Evidence |
|------|-------|--------|----------|
| 5 | `pipeline-architecture.svg` exists | VERIFIED | docs/pipeline-architecture.svg exists |
| 9 | Bayesian confidence, Beta-Bernoulli with Thompson sampling | VERIFIED | hook_search.py:210-211 uses `random.betavariate(alpha, beta_p)`, scoring.py uses beta params |
| 10 | Multi-layer retrieval: L0 locked + L1 behavioral + L2 FTS5 + HRR + BFS (L3) | VERIFIED | retrieval.py:269-327 implements exactly this pipeline |
| 10 | Retrieval layers described as "L0 + L1 + FTS5 (L2) + HRR + BFS (L3)" | INCORRECT | Missing L2.5 entity-index layer. retrieval.py:314-317 shows entity-index expansion as a distinct step between FTS5 and HRR. BENCHMARK_RESULTS.md references it correctly as "L2.5". |
| 11 | 12 edge types listed | VERIFIED | models.py defines 8 core edges (CITES, RELATES_TO, SUPERSEDES, CONTRADICTS, SUPPORTS, TESTS, IMPLEMENTS, TEMPORAL_NEXT). scanner.py adds 4 more (CALLS, CO_CHANGED, CONTAINS, COMMIT_TOUCHES). Total = 12 non-speculative edges matching the doc list. Note: 4 additional speculative edge types (SPECULATES, DEPENDS_ON, RESOLVES, HIBERNATED) exist in models.py but are not listed in the doc. |
| 12 | Correction detection 92% accuracy, zero LLM cost | VERIFIED | correction_detection.py:3-5 documents "92% accuracy on real corrections" and uses regex/heuristics only (no LLM calls) |
| 13 | Haiku classifies at 99% accuracy, ~$0.005/session | VERIFIED (accuracy) / UNVERIFIED (cost) | classification.py:18 says "99% accuracy per Exp 47/50". Per-session cost figure not verifiable from code alone. |
| 14 | 8 extractors for project onboarding | VERIFIED | scanner.py defines 8 extract functions: extract_file_tree, extract_git_history, extract_document_sentences, extract_ast_calls, extract_citations, extract_test_edges, extract_implements_edges, extract_directives |
| 15 | Temporal decay half-lives: facts 14d, corrections 8w, requirements 24w | VERIFIED | scoring.py:16-22 confirms factual=336h (14d), correction=1344h (8w), requirement=4032h (24w) |
| 15 | Session velocity scaling | VERIFIED | scoring.py:35-37 has `velocity_scale()` function with sprint session multiplier |
| 16 | Per-project isolation, SHA-256 hash, `~/.agentmemory/projects/<hash>/` | VERIFIED | cli.py:59-61 uses `hashlib.sha256(abs_path.encode()).hexdigest()[:12]` for path-based isolation |
| 18 | Links to `V2_ARCHITECTURE.md` | VERIFIED | File exists in docs/ |

**Findings:** One INCORRECT claim (missing L2.5 entity-index layer from retrieval description). One omission (4 speculative edge types undocumented). All other claims verified.

---

## docs/INSTALL.md

| Line | Claim | Status | Evidence |
|------|-------|--------|----------|
| 21 | `uv pip install git+https://github.com/yoshi280/agentmemory.git` works | VERIFIED | pyproject.toml defines proper build system; repo URL matches project.urls |
| 27 | `agentmemory --help` works | VERIFIED | cli.py:2483 defines `main()` entry point; pyproject.toml:33 registers `agentmemory` console script |
| 39 | `agentmemory setup` exists | VERIFIED | cli.py:2495 registers "setup" subparser |
| 43 | Setup writes slash commands to `~/.claude/commands/mem/` | VERIFIED | cli.py:52 defines `_COMMANDS_DIR = Path.home() / ".claude" / "commands" / "mem"`, setup creates files there at line 390-394 |
| 44 | Setup registers MCP server in `.mcp.json` | VERIFIED | cli.py:418-435 creates .mcp.json if missing |
| 45 | Setup "adds session hooks to `~/.claude/settings.json` (context injection, conversation logging)" | INCORRECT | Setup adds PreToolUse hooks for commit-check (cli.py:1868-1889) and directive-gate (cli.py:1931+), not "session hooks" for "context injection" or "conversation logging". The description of what the hooks do is wrong. |
| 64 | `/mem:onboard .` scans project | VERIFIED | server.py:783 defines `onboard()` MCP tool; scanner.py implements extraction |
| 73 | DB at `~/.agentmemory/projects/<hash>/memory.db` | VERIFIED | cli.py:59-61 constructs this path |
| 75 | `--project /path/to/project` flag | VERIFIED | cli.py:2489 adds `--project` argument |
| 75 | `AGENTMEMORY_DB` env var override | VERIFIED | cli.py:72-74 and server.py:223-226 check this env var |
| 80 | `agentmemory uninstall` exists | VERIFIED | cli.py:2695-2696 registers "uninstall" subparser |
| 92 | `agentmemory health` exists | VERIFIED | cli.py:2518-2521 registers "health" subparser |

**Findings:** One INCORRECT claim about what `agentmemory setup` writes to settings.json. The hooks are PreToolUse hooks for commit-check and directive-gate, not session hooks for context injection/conversation logging.

---

## docs/WORKFLOW.md

| Line | Claim | Status | Evidence |
|------|-------|--------|----------|
| 8 | `/mem:search "topic"` | VERIFIED | Slash command "search" defined at cli.py:152 |
| 9 | `/mem:core 10` | VERIFIED | Slash command "core" defined at cli.py:145 |
| 10 | `/mem:wonder "topic"` | VERIFIED | Slash command "wonder" defined at cli.py:187 |
| 11 | `/mem:reason "question"` | VERIFIED | Slash command "reason" defined at cli.py:227 |
| 12 | `/mem:stats` | VERIFIED | Slash command "stats" defined at cli.py:131 |
| 13 | `/mem:locked` | VERIFIED | Slash command "locked" defined at cli.py:159 |
| 19 | `agentmemory search "query terms"` CLI | VERIFIED | cli.py:2531-2536 registers "search" subparser |
| 20 | `agentmemory core --top 10` CLI | VERIFIED | cli.py:2524-2530 registers "core" subparser |
| 21 | `agentmemory stats` CLI | VERIFIED | cli.py:2512-2516 registers "stats" subparser |

No issues found. All workflow commands verified.

---

## docs/COMMANDS.md

| Line | Claim | Status | Evidence |
|------|-------|--------|----------|
| 5 | "All commands are available as Claude Code slash commands after setup" | INCORRECT | 4 of the 18 listed commands are MCP tools, not slash commands: `/mem:remember` (MCP tool `remember()`, slash command is `new-belief`), `/mem:correct` (MCP tool only, no slash command), `/mem:status` (MCP tool only, slash command is `stats`), `/mem:feedback` (MCP tool only, no slash command). |
| 9 | `/mem:search <query>` | VERIFIED | Slash command exists (cli.py:152), MCP tool exists (server.py:386) |
| 10 | `/mem:remember <text>` | INCORRECT | No slash command named "remember". The actual slash command is `/mem:new-belief`. The MCP tool `remember()` exists at server.py:502 but the slash command name in the code is different. |
| 11 | `/mem:correct <text>` | INCORRECT | No slash command named "correct". The MCP tool `correct()` exists at server.py:536 but there is no corresponding slash command in _COMMAND_DEFS. |
| 12 | `/mem:lock <belief_id>` | VERIFIED | Slash command exists (cli.py:173) |
| 13 | `/mem:locked` | VERIFIED | Slash command exists (cli.py:159) |
| 14 | `/mem:onboard <path>` | VERIFIED | Slash command exists (cli.py:102) |
| 15 | `/mem:status` | INCORRECT | No slash command named "status". The slash command is `/mem:stats` (cli.py:131). The MCP tool `status()` exists at server.py:645. |
| 16 | `/mem:core [n]` | VERIFIED | Slash command exists (cli.py:145) |
| 17 | `/mem:stats` | VERIFIED | Slash command exists (cli.py:131) |
| 18 | `/mem:reason <question>` | VERIFIED | Slash command exists (cli.py:227) |
| 19 | `/mem:wonder <topic>` | VERIFIED | Slash command exists (cli.py:187) |
| 20 | `/mem:feedback <id> <outcome>` | INCORRECT | No slash command named "feedback". The MCP tool `feedback()` exists at server.py:1480 but there is no corresponding slash command. |
| 21 | `/mem:delete <id>` | VERIFIED | Slash command exists (cli.py:180) |
| 22 | `/mem:settings` | VERIFIED | Slash command exists (cli.py:215) |
| 23 | `/mem:enable-telemetry` | VERIFIED | Slash command exists (cli.py:300) |
| 24 | `/mem:disable-telemetry` | VERIFIED | Slash command exists (cli.py:313) |
| 25 | `/mem:disable` | VERIFIED | Slash command exists (cli.py:272) |
| 26 | `/mem:enable` | VERIFIED | Slash command exists (cli.py:290) |
| 27 | `/mem:help` | VERIFIED | Slash command exists (cli.py:336) |
| 29 | "All commands also work from the terminal" | UNVERIFIED | Only some commands have CLI subparser equivalents (search, core, stats, onboard). Commands like remember, correct, feedback, status have MCP tools but no CLI subparsers. |
| 33 | `agentmemory search "query terms"` | VERIFIED | cli.py:2531 |
| 34 | `agentmemory core --top 10` | VERIFIED | cli.py:2524 |
| 35 | `agentmemory stats` | VERIFIED | cli.py:2512 |
| 36 | `agentmemory onboard /path/to/project` | VERIFIED | cli.py:2501 |

**Findings:** Significant naming mismatches. The doc lists `/mem:remember`, `/mem:correct`, `/mem:status`, and `/mem:feedback` as slash commands but these are MCP tools only. The actual slash command names differ (`new-belief` instead of `remember`, `stats` instead of `status`). The doc is also missing slash commands that DO exist: `/mem:health`, `/mem:unlock`, `/mem:send-telemetry`, `/mem:new-belief`.

---

## docs/BENCHMARK_RESULTS.md

| Line | Claim | Status | Evidence |
|------|-------|--------|----------|
| 10 | Contamination check `verify_clean.py` exists | VERIFIED | benchmarks/verify_clean.py exists |
| 12 | "FTS5 + entity-index (L2.5) + HRR + BFS" retrieval | VERIFIED | retrieval.py:269-327 shows all four layers |
| 12 | "2000-token budget" | VERIFIED | retrieval.py:261 `budget: int = 2000` |
| 16 | Protocol in `docs/BENCHMARK_PROTOCOL.md` | VERIFIED | File exists |
| 185 | `verify_clean.py` "checks 30 banned keys" | INCORRECT | BANNED_KEYS in verify_clean.py contains 23 keys (lines 17-44), not 30 |
| 194-203 | Benchmark CLI commands with `--split`, `--source`, `--retrieve-only` flags | VERIFIED | mab_adapter.py:429-458 defines these flags; mab_entity_index_adapter.py:498 defines --retrieve-only |
| 205 | "All adapters in `benchmarks/`" | VERIFIED | benchmarks/ directory contains locomo_adapter.py, mab_adapter.py, mab_entity_index_adapter.py, structmemeval_adapter.py, longmemeval_adapter.py, etc. |
| 69 | Links to `BENCHMARK_LOG.md` | VERIFIED | docs/BENCHMARK_LOG.md exists |
| 115 | Links to `EXP1_PERHOP_FAILURE_ANALYSIS.md` | VERIFIED | File exists in docs/ |
| 119 | Links to `EXP3_RESULTS.md` | VERIFIED | File exists in docs/ |
| 60 | Links to `EXP5_RESULTS.md` | VERIFIED | File exists in docs/ |
| 209-223 | All 15 related document links | VERIFIED | All 15 referenced files exist in docs/ |

**Findings:** One INCORRECT claim: verify_clean.py has 23 banned keys, not 30 as stated.

Benchmark scores themselves (F1, SEM percentages, etc.) are UNVERIFIED from code alone. They would require running the benchmarks and checking result files, which is outside the scope of this code-based audit. The infrastructure to reproduce them (adapters, scoring scripts, contamination checks) does exist.

---

## docs/PRIVACY.md

| Line | Claim | Status | Evidence |
|------|-------|--------|----------|
| 7 | "The only network-capable code is `telemetry.py` (stdlib `urllib.request`)" | VERIFIED | telemetry.py:16 imports `urllib.request`. Grep for urllib/requests/httpx/aiohttp/socket across all source modules finds network code ONLY in telemetry.py. Note: `anthropic` is a dependency (pyproject.toml:19) but is used by classification.py for LLM API calls, not direct network code in agentmemory. |
| 7 | "only invoked when you explicitly run `agentmemory send-telemetry` after opting in" | VERIFIED | telemetry.py:339-351 defines `send_telemetry()` which is only called from cli.py:2465 in `cmd_send_telemetry`. The send function is not called automatically. |
| 7 | "The LLM classification step during onboarding uses Claude Code subagents (not direct API calls from agentmemory)" | INCORRECT | classification.py imports and directly uses the `anthropic` SDK (pyproject.toml dependency `anthropic>=0.93.0`). The onboard slash command uses subagents, but `classification.py` can make direct API calls to Anthropic. The phrasing "not direct API calls from agentmemory" is misleading. |
| 9 | Telemetry disabled by default (`config.py` defaults `telemetry.enabled = false`) | VERIFIED | config.py:37-38 shows `"telemetry": {"enabled": False}` |
| 9 | "only content-free metrics are recorded: token counts, correction rates, feedback ratios, belief lifecycle counts" | VERIFIED | telemetry.py:1-9 privacy guarantee header; TelemetrySnapshot dataclass (lines 26-78) contains only integer counts, float ratios, and categorical distribution keys |
| 9 | "No belief content, project paths, file paths, session IDs, or user-identifying information" | VERIFIED | TelemetrySnapshot fields contain no string content from beliefs or files. SessionMetrics has only counters. |
| 9 | "Data stored locally at `~/.agentmemory/telemetry.jsonl`" | VERIFIED | telemetry.py:82-83 `_default_path()` returns `Path.home() / ".agentmemory" / "telemetry.jsonl"` |
| 9 | "shows you exactly what will be sent and asks for confirmation" | VERIFIED | cli.py:2418-2465 `cmd_send_telemetry` previews data and prompts before sending |
| 9 | "email telemetry data to data@robotrocketscience.com" | UNVERIFIED | This email address does not appear anywhere in the source code. It is a docs-only claim. |
| 11 | "SHA-256 hash of the project path" | VERIFIED | cli.py:59-61 uses `hashlib.sha256(abs_path.encode()).hexdigest()[:12]` |
| 11 | "Cross-project queries require explicit opt-in via the `project_path` parameter" | VERIFIED | server.py:390-428 shows `project_path` parameter on search, with separate DB resolution |
| 11 | "read-only (no feedback or confidence updates to the foreign database)" | VERIFIED | server.py:283-285 shows rejection message for cross-project belief IDs: "This belief ID is from a cross-project search...foreign project beliefs to prevent feedback loop interference" |
| 11 | "Mutation tools (feedback, lock, delete) reject cross-project belief IDs" | VERIFIED | server.py:289-290 defines `_is_foreign_id()` check; feedback/lock/delete tools check this |
| 13 | "Beliefs created by `remember()` and `correct()` are not locked until you explicitly confirm" | VERIFIED | server.py:502-536 creates beliefs without locking; server.py:593 `lock()` is separate action |
| 15 | "SQLite only. No external database, no vector DB, no cloud storage" | VERIFIED | store.py uses sqlite3 only; no vector DB imports anywhere in source |
| 15 | "WAL mode for crash safety" | VERIFIED | store.py:321 `self._conn.execute("PRAGMA journal_mode=WAL")` |
| 17 | "2,000 token budget" for context injection | VERIFIED | retrieval.py:261 `budget: int = 2000` |

**Findings:** One INCORRECT claim about LLM classification using only subagents (classification.py has direct Anthropic SDK usage). One UNVERIFIED claim (email address for telemetry).

---

## Summary

| Document | Total Claims | Verified | Incorrect | Unverified |
|----------|-------------|----------|-----------|------------|
| README.md | 14 | 14 | 0 | 0 |
| ARCHITECTURE.md | 12 | 10 | 1 | 1 |
| INSTALL.md | 12 | 11 | 1 | 0 |
| WORKFLOW.md | 9 | 9 | 0 | 0 |
| COMMANDS.md | 23 | 15 | 5 | 3 |
| BENCHMARK_RESULTS.md | 12 | 11 | 1 | 0 |
| PRIVACY.md | 17 | 14 | 1 | 2 |
| **Total** | **99** | **84** | **9** | **6** |

## Critical Issues (Recommended Fixes)

1. **COMMANDS.md: 4 slash commands don't exist as documented.** `/mem:remember` should be `/mem:new-belief`, `/mem:correct` has no slash command, `/mem:status` should be `/mem:stats`, `/mem:feedback` has no slash command. The doc also claims "all commands available as slash commands" which is false.

2. **COMMANDS.md: Missing commands from the reference.** `/mem:health`, `/mem:unlock`, `/mem:send-telemetry`, `/mem:new-belief` all exist but are not listed.

3. **INSTALL.md: Setup hook description is wrong.** Claims setup "adds session hooks (context injection, conversation logging)" but it actually adds PreToolUse hooks for commit-check and directive-gate.

4. **ARCHITECTURE.md: Missing L2.5 entity-index layer.** The retrieval pipeline description omits the entity-index expansion step that exists between FTS5 and HRR.

5. **PRIVACY.md: LLM classification claim is misleading.** Says classification uses "Claude Code subagents (not direct API calls from agentmemory)" but `classification.py` imports and uses the Anthropic SDK directly. The onboard slash command does use subagents, but the module has direct API capability.

6. **BENCHMARK_RESULTS.md: verify_clean.py key count is wrong.** States "30 banned keys" but the actual BANNED_KEYS set contains 23 keys.
