# Changelog

## [Unreleased]

## [2.2.0] - 2026-04-18

### Added
- Structural prompt analysis (Layer 0) in hook_search -- detects 6 task types (planning, deployment, debugging, implementation, validation, research) and subagent suitability from prompt structure (90.5% accuracy, 3.4x over keyword baseline)
- activation_condition evaluation -- previously dead schema field now has live predicate logic (task_type, keyword_any/all, structural, subagent predicates with AND/OR operators)
- Edge-based vocabulary expansion (Layer 1.5) in hook_search -- traverses graph edges from FTS5 hits to bridge directive vocabulary gaps without numpy overhead
- L1 behavioral beliefs injected at SessionStart -- high-confidence unlocked procedural beliefs now surface alongside locked (L0) beliefs
- 23 new integration tests for structural analysis and activation_condition

### Performance
- Onboard: batch graph edge inserts (single transaction vs 21k individual commits)
- Onboard: skip FTS5 relationship checks during bulk ingest, defer commits
- Onboard: eliminate double markdown render and atomic temp files during vault sync
- Structural analysis latency: 0.02-0.10ms (effectively free)
- Full hook pipeline: 45-82ms against 15K beliefs (within 100ms budget)

### Added (Infrastructure)
- Project isolation verification tests (CS-030)
- End-to-end timing breakdown in onboard output

## [2.1.0] - 2026-04-18

### Fixed
- Add CLI `ingest` subcommand -- PostCompact hook called `agentmemory ingest` but the command did not exist, blocking all conversation-to-belief ingestion from daily usage
- Clear pending_feedback entries after auto-feedback processing -- rows accumulated indefinitely (1,436+ stale entries) because processed feedback was never deleted

### Verified (not broken)
- VaultStore write-through is functional -- beliefs created via MCP server are written to Obsidian vault .md files automatically
- Bayesian confidence updates are wired -- record_test_result() calls update_confidence() which updates alpha/beta
- Edge creation during daily usage is wired -- detect_relationships() runs for every belief created via ingest_turn()

## [2.0.0] - 2026-04-18

### Added
- Obsidian vault integration (VaultStore, sync, import, export)
- Uncertainty module with multi-dimensional confidence vectors
- Graph metrics and visualization
- Telemetry (opt-in, local-only)
- Hook search for SessionStart/UserPromptSubmit context injection
- Deduplication engine
- Document linker for cross-referencing project docs
- Email ingest worker (Cloudflare)
- Wonder/Reason deep research pipelines
- CITATION.cff for academic citation

### Changed
- Architecture: vault-first with SQLite as derived index
- Version bump from 1.x to 2.0.0

## [0.1.0] - 2026-04-14

### Added
- SQLite-backed persistent memory with WAL mode and crash recovery
- Bayesian confidence tracking (Beta-Bernoulli model with Thompson sampling)
- FTS5 full-text search with BM25 ranking
- HRR (Holographic Reduced Representations) vocabulary bridge for structural retrieval
- BFS multi-hop graph traversal with edge-type weighting
- 7 edge types: SUPERSEDES, CONTRADICTS, SUPPORTS, CALLS, CITES, TESTS, IMPLEMENTS
- Locked beliefs (non-negotiable constraints) with L0 auto-loading
- Correction detection (92% accuracy, zero-LLM)
- LLM classification via Anthropic Haiku (99% accuracy, $0.005/session)
- Type-aware compression (55% token savings)
- Content-aware temporal decay with velocity scaling
- Project onboarding scanner (9 extractors)
- MCP server (19 tools) for Claude Code integration
- CLI with 23 commands
- Per-project database isolation
- 285 tests passing, pyright strict mode
