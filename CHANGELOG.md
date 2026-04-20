# Changelog

## [Unreleased]

## [3.0.1] - 2026-04-20

### Changed
- Complete README rewrite: visceral opening, install at line 10, github-push example moved above fold, killed generic before/after table, added compatibility section, added /mem:stats visibility block.
- PyPI description updated to match new positioning.

## [3.0.0] - 2026-04-20

Cross-project shared scopes and automatic update notifications. Beliefs can now
flow between projects without data duplication, and users get notified when a
newer version is available.

### Added
- `shared_scopes.py`: cross-project belief sharing via SQLite ATTACH federation. Separate DB per scope under `~/.agentmemory/shared/{scope}/`. Content-hash dedup prevents duplicates.
- 2 new MCP tools: `share_belief` (copy belief to a shared scope), `manage_scopes` (list/subscribe/unsubscribe/create scopes)
- Hook search Layer 6: automatically queries subscribed shared scopes with budget 3 per scope (Exp 98 Config B)
- `update_check.py`: PyPI version check with 24-hour file cache, 2-second timeout, silent on failure
- SessionStart hook integration: shows "Update available: vX.Y.Z -> vA.B.C" when outdated
- README "Under the Hood" section: real example of 7-layer search pipeline and 4-zone context injection
- Exp 97: cross-project retrieval via ATTACH (100% recall, 0% top-5 contamination, 1.06x latency)
- Exp 98: scope-aware scoring comparison (4 configs; Config B 12/3 wins)
- 19 new tests in test_shared_scopes.py

### Fixed
- README benchmark table: added missing LoCoMo (50.8%) entry
- README layer count: corrected "6-layer" to "7-layer" after Layer 6 addition

## [2.5.0] - 2026-04-20

Retrieval quality overhaul: beliefs that answer the question now outrank beliefs
that just match keywords. Three new retrieval layers, two new modules, zero
breaking changes.

### Added
- `intention.py`: intention-space clustering for vocabulary-gap bridging (Exp 94b: 98% of same-cluster pairs share <10% vocab). Hook search Layer 1.7 expands FTS5 results by pulling same-cluster beliefs.
- `multimodel.py`: archaeology-style Bayesian model selection (SIGNAL/NOISE/STALE/CONTESTED) from Wikipedia Bayesian inference framework. Applied as 0.6-1.3x multiplier on beliefs with feedback; neutral on beliefs without.
- Precomputed HRR neighbors: `hrr_neighbors` table populated during graph build. Hook search Layer 1.5 now does SQL JOIN (0.03ms) instead of skipping HRR entirely.
- `belief_clusters` table for intention cluster assignments, rebuilt on graph changes.
- `HRRGraph.node_ids()` and `HRRGraph.has_node()` public API methods.
- Exploration sampling: 3 random never-feedback beliefs added to pending_feedback per search for long-tail coverage.
- Exp 92: Lagrangian factorial sweep (2 kinetic x 3 potential energy definitions)
- Exp 93/93b/93c: multi-model Bayesian scoring experiments
- Exp 94: HRR performance profiling (bottleneck identified: cleanup memory cosine, not FFT)
- Exp 94b: intention-space clustering (97.9% vocab gap in same-cluster pairs)
- Exp 95: entity layer scoring calibration (relevance-gated weights)
- Exp 96: hierarchical clustering (k=40 drops mega-cluster from 81% to 29%)
- 34 new tests across test_hrr_hook_path.py, test_intention.py, test_multimodel.py

### Fixed
- Relevance-gated type/source weights: correction (2.0) * user_corrected (1.5) compound boost now interpolated by query term overlap. Irrelevant corrections no longer dominate results. Entity scores dropped from 43x to 14-22x.
- O(n^2) intention cluster self-join rewritten as subquery (16.7s -> 150ms per query).
- Intention cluster count increased from k=8 to k=40 (Exp 96: largest cluster 81% -> 29%).
- `score_belief()` extended with `ignored_count` and `harmful_count` params (backwards compatible, default 0).

### Changed
- Hook search Layer 1.5 upgraded from edge-only traversal to precomputed HRR neighbors with edge fallback.
- PyPI package renamed to `agentmemory-rrs` with `tool.hatch.build.targets.wheel` config.

## [2.4.1] - 2026-04-19

### Added
- Exp 90: Jacobian + Hamiltonian scoring dynamics analysis
- Exp 90 post-fix validation (Gini 0.026 -> 0.148, 5.7x improvement)

### Fixed
- CI lint: ruff format entire codebase, resolve pyright strict errors in hrr.py
- Exclude benchmarks/ and scripts/ from pyright strict (not production code)

## [2.4.0] - 2026-04-19

### Added
- Exploratory wonder: 3 new MCP tools (wonder, wonder_ingest, wonder_gc)
- Gap analysis, parallel subagent research, speculative belief ingestion
- TTL-based garbage collection for unvalidated speculative beliefs
- UCB exploration bonus for under-retrieved beliefs (Fix 4)

### Fixed
- Confidence differentiation (Fixes 2-5):
  - Fix 2: Source-type decay modifiers (agent-inferred 0.5x, user-corrected 2.0x half-life)
  - Fix 3: First-signal amplification (3x weight on first feedback event)
  - Fix 4: UCB exploration bonus (under-retrieved beliefs surface for feedback)
  - Fix 5: Asymmetric feedback weights (harmful=-2.0, weak=-0.6, ignored=-0.1)

## [2.3.2] - 2026-04-19

### Added
- onboard: `use_llm` parameter to opt into LLM classification during bulk ingest (default False keeps zero-LLM path)

### Maintenance
- Documentation: refresh stale counts (tests, MCP tools, modules) and URLs across CLAUDE.md, TODO.md, INSTALL.md

## [2.3.1] - 2026-04-19

### Fixed
- onboard end-to-end: scan, classify, and create beliefs in a single pipeline (previously stopped after scan)
- workers: PII leaked through diff-based guard path; guard now operates on full tracked content
- PII sanitization: complete case-insensitive pass across tracked files; pre-push guard enhanced to block remaining variants

## [2.3.0] - 2026-04-19

### Fixed
- Bayesian score inflation: deflate insertion priors for agent-inferred content
- Complete case-insensitive PII sanitization for public release
- Remove diff-based guard check, fix workers PII
- Sanitize filesystem paths in error messages

### Added
- `recalibrate_scores()` with 13 diagnostic tests for score inflation
- 3-tier `lock_level` schema (none/promoted/user)
- `--tier` and `--max-beliefs` filters for Obsidian sync
- 27 acceptance tests for case studies CS-012 through CS-035
- 25 acceptance tests for REQ-003/023/024/025/026/027
- 181 tests for scoring, correction_detection, classification
- 19 validation tests for open design questions
- REQ-015/016 claims audit (20 claims, zero unverified) + LIMITATIONS.md

### Changed
- Wire `recalibrate` into CLI and MCP server
- Close all open research questions (R2/R3/D1/D2/D3/F4/F5/C1)
- Set `ingest.use_llm` default to False
- Add ruff to dev dependencies for pre-commit hooks

### Security
- Full PII sanitization sweep across tracked files ahead of public release

## [2.2.2] - 2026-04-19

### Fixed
- vault_store: rebuild_index() now runs in a single transaction (crash mid-rebuild rolls back instead of corrupting index)
- server: global buffers (_retrieval_buffer, _signal_buffer, _explicit_feedback_ids) now bounded to prevent unbounded memory growth
- store: clear_pending_feedback() respects transaction context (was committing prematurely)
- store: flush implicit transaction before BEGIN IMMEDIATE in transaction()

### Security
- Database files now set to 0600 permissions on open (was 644)

## [2.2.1] - 2026-04-18

### Fixed
- Hook feedback now records outcomes to test_results table. The hook-based search was updating alpha/beta directly but not recording outcomes, making "used" detection invisible to trend measurement (0% used rate since Apr 15 despite active hook usage).

### Maintenance
- Deleted 26 stale branches fully merged into main

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
