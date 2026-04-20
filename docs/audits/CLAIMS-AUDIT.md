# README.md Claims Audit

Audit date: 2026-04-18
Audited file: README.md (root)
Audited against: v2-dev branch, commit history, pyproject.toml v1.2.3

---

## 1. Feature Claims

### "Remembers automatically" -- captures decisions, corrections, preferences
**VERIFIED.** The ingestion pipeline (`src/agentmemory/ingest.py`) processes conversation turns. Classification (`src/agentmemory/classification.py`) categorizes into belief types (decision, correction, preference, etc.). Correction detection (`src/agentmemory/correction_detection.py`) handles corrections specifically. The MCP server (`src/agentmemory/server.py`) exposes `ingest`, `observe`, `remember`, and `correct` tools that fire during normal conversation.

### "Learns what matters" -- memories that help get stronger, memories that hurt get weaker
**VERIFIED.** Bayesian feedback loop implemented in `src/agentmemory/store.py:771` (`bayesian_update` method: "used" increments alpha, "harmful" increments beta_param). Thompson sampling in `src/agentmemory/scoring.py:117` (`thompson_sample` function) samples from Beta(alpha, beta_param) for ranking. The MCP `feedback` tool closes the loop.

### "Stays on your machine" -- local SQLite, no cloud, no vector DB, no telemetry unless opt-in
**VERIFIED.** Storage is SQLite (`src/agentmemory/store.py:311`, `sqlite3.connect`). Telemetry (`src/agentmemory/telemetry.py`) is local-only by default (writes to `~/.agentmemory/telemetry.jsonl`), with a `send_telemetry` function that requires explicit config to enable. No embedding or vector DB dependencies in `pyproject.toml` -- dependencies are: anthropic, datasketch, fastmcp, nltk, numpy, scipy. None are vector databases or embedding libraries.

### "Works with any MCP agent"
**VERIFIED.** Server implemented via FastMCP (`src/agentmemory/server.py:1`, `fastmcp` in dependencies). The protocol is MCP-standard, not Claude-specific.

---

## 2. Benchmark Numbers

### LoCoMo 66.1% F1
**VERIFIED (documentation-level).** The BENCHMARK_LOG.md contains detailed methodology with per-category F1 breakdown (multihop 42.2%, temporal 45.4%, open-ended 30.5%, single-hop 69.4%, adversarial 97.5%) that aggregate to 66.1%. The protocol-correct scoring script exists at `benchmarks/locomo_score_protocol.py`. The `benchmarks/locomo_adapter.py` and `benchmarks/locomo_generate.py` implement the full pipeline.

**CONCERN:** The only committed results file (`benchmarks/locomo_final_results.json`) shows `overall_f1: 0.4055`, not 0.661. The BENCHMARK_LOG.md explains this: two earlier runs had answer leakage and are invalid, and the 66.1% is from the protocol-correct run. However, the protocol-correct results JSON is not committed to the repo. The 40.55% file appears to be from a superseded run.

### MAB SH 90% Opus / 62% Haiku
**VERIFIED (documentation-level).** BENCHMARK_RESULTS.md documents these numbers with version progression (v1.0: 60% -> v1.1: 90%). Adapter code exists at `benchmarks/mab_adapter.py`, `benchmarks/mab_entity_index_adapter.py`, `benchmarks/mab_triple_adapter.py`.

### MAB MH 60% Opus
**VERIFIED (documentation-level).** BENCHMARK_RESULTS.md v1.2.1 summary table shows 60% after Exp 6 temporal coherence improvement (up from 58%). The detailed section explains chain-valid (35%) vs raw SEM (47/60%) distinction.

### StructMemEval 100% (14/14)
**VERIFIED (documentation-level).** BENCHMARK_RESULTS.md shows progression from v1.0 (29%) to v1.1 (100%) via temporal_sort fix. Adapter at `benchmarks/structmemeval_adapter.py`.

### LongMemEval 59.0%
**VERIFIED (documentation-level).** BENCHMARK_RESULTS.md shows 59.0% (295/500) with per-category breakdown. Adapter at `benchmarks/longmemeval_adapter.py`, scorer at `benchmarks/longmemeval_score.py`.

### "version 1.1.1" (README line 118)
**INCORRECT.** README states "Evaluated across 5 published benchmarks on version 1.1.1." But:
- `pyproject.toml` shows version `1.2.3`
- `CITATION.cff` shows version `1.2.3`
- `BENCHMARK_RESULTS.md` header says "v1.2.1"
- The MH 60% result specifically required Exp 6 changes (v1.2.1), not v1.1.1

The version claim is stale. The benchmarks were run across multiple versions (v1.0 through v1.2.1), not all on v1.1.1.

### "No embeddings, no vector DB" (README line 118)
**VERIFIED.** No embedding libraries in `pyproject.toml` dependencies. No imports of chromadb, pinecone, weaviate, qdrant, faiss, or sentence-transformers anywhere in `src/agentmemory/`. Retrieval uses FTS5 keyword search + HRR vocabulary bridge + BFS graph traversal.

---

## 3. Architecture Claims

### FTS5 full-text search
**VERIFIED.** `src/agentmemory/store.py:171`: `CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(...)`. Used throughout retrieval pipeline (`src/agentmemory/retrieval.py`, `src/agentmemory/hook_search.py`).

### Thompson sampling
**VERIFIED.** `src/agentmemory/scoring.py:117-118`: `def thompson_sample(alpha, beta_param)` -- "Sample from Beta(alpha, beta_param) for Thompson sampling ranking." Used in combined scoring at `scoring.py:279`.

### Bayesian belief tracking
**VERIFIED.** `src/agentmemory/store.py:297`: "SQLite-backed memory store with FTS5 search and Bayesian belief tracking." Models carry `alpha` and `beta_param` fields (`src/agentmemory/models.py:105-106`). Bayesian updates at `store.py:771` and `store.py:2246`. Multi-dimensional uncertainty tracking in `src/agentmemory/uncertainty.py` with `BetaAxis` class.

### Belief graph with SUPPORTS, CONTRADICTS, SUPERSEDES, CITES edges
**VERIFIED.** All four edge types found in:
- `src/agentmemory/obsidian.py:38-41` (edge type mapping with reverse labels)
- `src/agentmemory/cli.py:878-880` (graph metrics display)
- `src/agentmemory/hook_search.py:296` (SUPERSEDES chain lookup)
- `src/agentmemory/relationship_detector.py` (edge creation)

---

## 4. Installation Instructions

### `uv pip install git+https://github.com/yoshi280/agentmemory.git`
**UNVERIFIED.** Cannot execute the install command, but `pyproject.toml` has proper build-system config (`hatchling`), project scripts entry (`agentmemory = "agentmemory.cli:main"`), and the repo URL matches. The install mechanism is structurally sound.

### `agentmemory setup`
**VERIFIED.** CLI subcommand exists: `src/agentmemory/cli.py:385` (`def cmd_setup`) registered at `cli.py:2495-2498`. The setup command installs MCP config, commit hooks, and Obsidian vault integration.

### `/mem:onboard .`
**VERIFIED.** Onboard command defined at `src/agentmemory/cli.py:606` (`def cmd_onboard`). MCP slash command registered in server tool definitions at `server.py`. The custom command config is installed by `cmd_setup`.

---

## 5. Wonder/Reason Section

### Wonder: FTS5 seed retrieval, BFS expansion, Beta variance uncertainty, contradiction detection, three-section output
**VERIFIED.** `src/agentmemory/cli.py:1132` (`def cmd_wonder`):
- FTS5 retrieval: seeds via store search
- BFS expansion: `store.bfs_expand` called with configurable depth (`store.py:1026`)
- Beta variance uncertainty: `scoring.py:127` (normalized variance of Beta distribution)
- Contradiction detection: checks CONTRADICTS edges between results
- Three-section output (Known Facts, Connected Evidence, Open Questions): implemented in the wonder output formatting

### Reason: content-word overlap filter, consequence paths with compound confidence decay, locked constraint checking, four impasse types, five verdicts
**VERIFIED.** `src/agentmemory/cli.py:1318` (`def cmd_reason`):
- Content-word overlap: `cli.py:1347`
- Consequence paths with compound confidence decay: `store.py:1134` (`consequence_paths` method), decay at `store.py:1219`
- Locked constraint checking: `cli.py:1423-1424`
- Four impasse types: `store.py:1250-1252` (Impasse dataclass: "tie", "gap", "constraint_failure", "no_change")
- Five verdicts: `cli.py:1429-1437` (CONTRADICTORY, INSUFFICIENT, UNCERTAIN, SUFFICIENT, PARTIAL)

---

## 6. "No embeddings, no vector DB"

**VERIFIED.** Grep across all of `src/agentmemory/` for embedding, vectordb, chromadb, pinecone, weaviate, qdrant, faiss returns zero matches. The `pyproject.toml` dependencies contain no embedding or vector database packages. The HRR module (`src/agentmemory/hrr.py`) uses holographic reduced representations (numpy-based), which is a vocabulary bridging technique, not an embedding model.

---

## 7. Version Numbers and Test Counts

### Python 3.12+ badge
**VERIFIED.** `pyproject.toml:7`: `requires-python = ">=3.12"`.

### "beta" status badge
**VERIFIED.** `pyproject.toml:15`: `"Development Status :: 4 - Beta"`.

### Test count
README does not claim a specific test count. CLAUDE.md claims "260 tests passing" but actual count is **527 tests** (via `uv run pytest tests/ --co -q`). The CLAUDE.md number is stale but this is outside README scope.

---

## 8. CITATION.cff vs LICENSE vs pyproject.toml

### License
**CONSISTENT.** All three say MIT:
- `LICENSE`: "MIT License"
- `pyproject.toml:8`: `license = {text = "MIT"}`
- `CITATION.cff:9`: `license: MIT`

### Version
**CONSISTENT between pyproject.toml and CITATION.cff.** Both say `1.2.3`.
**INCONSISTENT with README benchmark section.** README line 118 says "version 1.1.1".

### Author/name
**MINOR INCONSISTENCY.** `pyproject.toml:8` uses `yoshi280` as author name. `CITATION.cff:6` and the README bibtex block use `robotrocketscience`. `LICENSE:3` uses `yoshi280`. These appear to be a GitHub username vs. a project/brand name, but it is inconsistent.

### Title
**CONSISTENT.** Both CITATION.cff and the README bibtex use "agentmemory: Persistent Memory for AI Coding Agents".

### URL
**CONSISTENT.** All point to `https://github.com/yoshi280/agentmemory`.

---

## 9. Documentation Links

All documentation links in the README resolve to existing files:

| Link | Exists |
|------|--------|
| `docs/README.md` | Yes |
| `docs/INSTALL.md` | Yes |
| `docs/WORKFLOW.md` | Yes |
| `docs/ARCHITECTURE.md` | Yes |
| `docs/BENCHMARK_RESULTS.md` | Yes |
| `docs/COMMANDS.md` | Yes |
| `docs/OBSIDIAN.md` | Yes |
| `docs/PRIVACY.md` | Yes |
| `docs/BENCHMARK_PROTOCOL.md` | Yes |
| `docs/RESEARCH_FREEZE_20260416.md` | Yes |
| `docs/pipeline-architecture.svg` | Yes |
| `CONTRIBUTING.md` | Yes |
| `LICENSE` | Yes |

---

## Summary

| Category | Verified | Unverified | Incorrect |
|----------|----------|------------|-----------|
| Feature claims (4) | 4 | 0 | 0 |
| Benchmark numbers (5) | 5* | 0 | 0 |
| Architecture claims (4) | 4 | 0 | 0 |
| Installation (3) | 2 | 1 | 0 |
| Wonder/Reason (2) | 2 | 0 | 0 |
| No embeddings (1) | 1 | 0 | 0 |
| Version/meta (3) | 1 | 0 | 2 |
| Doc links (14) | 14 | 0 | 0 |
| **Total (36)** | **33** | **1** | **2** |

*Benchmark numbers are verified at documentation level (detailed logs, adapter code, scoring scripts exist) but the only committed LoCoMo results JSON shows a different number from a superseded run.

### Items Requiring Attention

1. **INCORRECT -- Version claim (README line 118):** "Evaluated across 5 published benchmarks on version 1.1.1" should be updated. The current version is 1.2.3, benchmarks were run across v1.0-v1.2.1, and the MH 60% result specifically requires v1.2.1 changes.

2. **INCORRECT -- Author inconsistency:** README bibtex and CITATION.cff use `robotrocketscience` as author. pyproject.toml and LICENSE use `yoshi280`. Pick one canonical name.

3. **CONCERN -- LoCoMo results file:** `benchmarks/locomo_final_results.json` contains `overall_f1: 0.4055` (an earlier, superseded run). The 66.1% protocol-correct results are documented in BENCHMARK_LOG.md but the actual results JSON for that run is not in the repo. Consider either committing the correct results file or removing the stale one to avoid confusion.

4. **STALE (CLAUDE.md, not README):** CLAUDE.md claims "260 tests passing, 19 MCP tools, 18 production modules." Actual: 527 tests, 23 MCP tools, 28 modules. These numbers are in CLAUDE.md project context, not README, but worth updating.
