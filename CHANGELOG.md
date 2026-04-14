# Changelog

## 0.1.0 (2026-04-14)

Initial release.

### Features

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
