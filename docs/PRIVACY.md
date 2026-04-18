# Privacy and Security

These are verifiable properties of the codebase, not marketing claims. Each can be confirmed by reading the source.

**Your data never leaves your machine.** The MCP server, retrieval pipeline, scoring, and all belief operations run locally using SQLite and pure math (Bayesian updates, FTS5, HRR). The only network-capable code is `telemetry.py` (stdlib `urllib.request`), which is only invoked when you explicitly run `agentmemory send-telemetry` after opting in. No network calls happen during normal operation. The LLM classification step during onboarding uses Claude Code subagents (not direct API calls from agentmemory).

**No telemetry by default.** Telemetry is disabled on install (`config.py` defaults `telemetry.enabled = false`). If you opt in during `agentmemory setup`, only content-free metrics are recorded: token counts, correction rates, feedback ratios, belief lifecycle counts. No belief content, project paths, file paths, session IDs, or user-identifying information is ever included. Data is stored locally at `~/.agentmemory/telemetry.jsonl` and never transmitted automatically. To share your usage data, run `agentmemory send-telemetry`. It shows you exactly what will be sent and asks for confirmation before transmitting. You can also email telemetry data to data@robotrocketscience.com. Disable anytime with `/mem:disable-telemetry`.

**Per-project isolation.** Each project gets a separate SQLite database keyed by SHA-256 hash of the project path. Beliefs from project A cannot leak into project B. Cross-project queries require explicit opt-in via the `project_path` parameter and are read-only (no feedback or confidence updates to the foreign database). Mutation tools (`feedback`, `lock`, `delete`) reject cross-project belief IDs.

**You control all writes.** Beliefs created by `remember()` and `correct()` are not locked until you explicitly confirm via `lock()`. Only locked beliefs persist as non-negotiable constraints. You can soft-delete any belief with `/mem:delete`, and the system cannot create locked beliefs without your confirmation.

**SQLite only.** No external database, no vector DB, no cloud storage. All data lives in `~/.agentmemory/`. WAL mode for crash safety. Fully rebuildable from source files.

**When the cloud LLM is involved.** When agentmemory injects context into your Claude Code prompt, the cloud LLM provider (Anthropic) sees that context as part of the prompt. This is inherent to using any cloud LLM. agentmemory mitigates exposure by injecting only the relevant subset of beliefs (2,000 token budget) rather than a full memory dump, and per-project isolation prevents cross-project context bleed.
