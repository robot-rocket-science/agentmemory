# agentmemory

**[Read the full writeup at robotrocketscience.com/projects/agentmemory](https://robotrocketscience.com/projects/agentmemory)**

Persistent, graph-backed memory for AI coding agents. Turns conversation into scored beliefs, retrieves the best ones when asked, and learns from feedback.

Built on SQLite (WAL mode), FTS5 full-text search, Bayesian confidence tracking, and holographic reduced representations (HRR) for structural retrieval. Ships as a CLI and an MCP server for Claude Code.

## Architecture

```
                            INGESTION
                            =========

  Conversation Turn              Project Directory
        |                              |
        v                              v
  +-------------+              +--------------+
  |   ingest()  |              |  scanner.py  |
  | extraction  |              | 9 extractors |
  | + sentences |              | (files, git, |
  +------+------+              |  AST, docs)  |
         |                     +------+-------+
         v                            v
  +-------------+              +--------------+
  | correction  |              |  graph_edges |
  |  detection  |              | CALLS, CITES |
  | (92%, 0-LLM)|             | TESTS, IMPL  |
  +------+------+              | CO_CHANGED   |
         |                     +--------------+
         v
  +-------------+     +-------------+
  |    LLM      |     | relationship|
  | classifier  |     |  detector   |
  | (Haiku,99%) |     | CONTRADICTS |
  +------+------+     |  SUPPORTS   |
         |            +------+------+
         v                   |
  +------+-------------------+------+
  |                                 |
  |     SQLite Store (WAL mode)     |
  |                                 |
  |  beliefs    observations        |
  |  edges      graph_edges         |
  |  sessions   checkpoints         |
  |  beliefs_fts (FTS5 index)       |
  |                                 |
  +-----------------+---------------+
                    |
                    |
                            RETRIEVAL
                            =========

                    Query: "what do we know about X?"
                            |
                            v
            +-------------------------------+
            |       Retrieval Pipeline      |
            |-------------------------------|
            |                               |
            |  L0: Locked beliefs           |
            |      (non-negotiable)         |
            |              |                |
            |  L1: Behavioral beliefs       |
            |      (directives)             |
            |              |                |
            |  L2: FTS5 keyword search      |
            |      (BM25 ranking)           |
            |              |                |
            |  L3: HRR vocab bridge         |
            |      (structural neighbors    |
            |       FTS5 would miss)        |
            |              |                |
            |  L3: BFS multi-hop            |
            |      (edge-weighted graph     |
            |       traversal, depth 2)     |
            |              |                |
            |  Merge + deduplicate          |
            |              |                |
            |  Score (Bayesian confidence   |
            |    x decay x type weight      |
            |    x lock boost x recency)    |
            |              |                |
            |  Compress + pack into budget  |
            |              |                |
            +-------------------------------+
                           |
                           v
                  Ranked belief list
                  (fits in token budget)


                            FEEDBACK
                            ========

            Agent uses/ignores a belief
                        |
                        v
                +---------------+
                |   feedback()  |
                | Bayesian      |
                | update:       |
                |  used  -> a+1 |
                |  ignored -> 0 |
                |  harmful -> b+|
                +-------+-------+
                        |
                        v
              Confidence adjusts over time
              (Thompson sampling explores
               uncertain beliefs)
```

## Features

- **Bayesian confidence** -- Beta-Bernoulli model with Thompson sampling. Beliefs that help get stronger; beliefs that hurt get weaker.
- **Multi-layer retrieval** -- Locked constraints (L0) + behavioral directives (L1) + FTS5 keyword search (L2) + HRR structural bridge + BFS graph traversal (L3). Compressed to fit a token budget.
- **Graph-backed knowledge** -- 7 edge types (SUPERSEDES, CONTRADICTS, SUPPORTS, CALLS, CITES, TESTS, IMPLEMENTS) enable multi-hop traversal and contradiction detection.
- **Correction detection** -- 92% accuracy, zero LLM cost. Corrections auto-create high-confidence beliefs.
- **LLM classification** -- Haiku classifies belief type/persistence at 99% accuracy, ~$0.005/session.
- **Project onboarding** -- Scanner extracts structure from git history, AST, docs, citations, and directives.
- **Temporal decay** -- Content-aware half-lives (corrections never decay, facts decay in 14 days). Session velocity scaling.
- **Per-project isolation** -- Each project gets its own SQLite database at `~/.agentmemory/projects/<hash>/`.

## Privacy and Security

These are verifiable properties of the codebase, not marketing claims. Each can be confirmed by reading the source.

**Your data never leaves your machine.** The MCP server, retrieval pipeline, scoring, and all belief operations run locally using SQLite and pure math (Bayesian updates, FTS5, HRR). Zero network libraries are imported (`grep -r "requests\|httpx\|urllib\|socket" src/` returns nothing). The only network call in the entire system is the optional LLM classification step during onboarding, which uses Claude Code subagents (not direct API calls from agentmemory).

**No telemetry by default.** Telemetry is disabled on install (`config.py` defaults `telemetry.enabled = false`). If you opt in during `agentmemory setup`, only content-free metrics are recorded: token counts, correction rates, feedback ratios, belief lifecycle counts. No belief content, project paths, file paths, session IDs, or user-identifying information is ever included. Data is stored locally at `~/.agentmemory/telemetry.jsonl` and never transmitted. Disable anytime with `/mem:disable-telemetry`.

**Per-project isolation.** Each project gets a separate SQLite database keyed by SHA-256 hash of the project path. Beliefs from project A cannot leak into project B. Cross-project queries require explicit opt-in via the `project_path` parameter and are read-only (no feedback or confidence updates to the foreign database). Mutation tools (`feedback`, `lock`, `delete`) reject cross-project belief IDs.

**You control all writes.** Beliefs created by `remember()` and `correct()` are not locked until you explicitly confirm via `lock()`. Only locked beliefs persist as non-negotiable constraints. You can soft-delete any belief with `/mem:delete`, and the system cannot create locked beliefs without your confirmation.

**SQLite only.** No external database, no vector DB, no cloud storage. All data lives in `~/.agentmemory/`. WAL mode for crash safety. Fully rebuildable from source files.

**When the cloud LLM is involved.** When agentmemory injects context into your Claude Code prompt, the cloud LLM provider (Anthropic) sees that context as part of the prompt. This is inherent to using any cloud LLM. agentmemory mitigates exposure by injecting only the relevant subset of beliefs (2,000 token budget) rather than a full memory dump, and per-project isolation prevents cross-project context bleed.

## Installation

```bash
uv pip install git+https://github.com/yoshi280/agentmemory.git

# Set up Claude Code integration (commands, hooks, MCP config)
agentmemory setup
```

Restart Claude Code after setup. Commands appear as `/mem:*`.

## Quick Start

### As an MCP Server (Claude Code)

After `agentmemory setup`, the MCP server runs automatically. Use it through Claude Code:

```
/mem:onboard .              # Scan and ingest current project
/mem:search "retrieval"     # Search beliefs
/mem:core 10                # Top 10 beliefs by confidence
/mem:stats                  # System analytics
/mem:locked                 # Show locked constraints
```

### As a CLI

```bash
agentmemory onboard /path/to/project
agentmemory search "query terms"
agentmemory core --top 10
agentmemory stats
agentmemory lock "always use strict typing"
agentmemory reason "how does the retrieval pipeline work?" --depth 2
agentmemory wonder "what are the open questions about decay?"
```

### As a Python Library

```python
from agentmemory import MemoryStore, Belief

store = MemoryStore("path/to/memory.db")

# Insert a belief
belief = store.insert_belief(
    content="The API uses REST conventions",
    belief_type="factual",
    source_type="user_stated",
    locked=True,
)

# Search
results = store.search("API conventions")

# Full retrieval pipeline
from agentmemory.retrieval import retrieve
result = retrieve(store, "what conventions do we follow?", budget=2000)
for belief in result.beliefs:
    print(f"[{belief.confidence:.0%}] {belief.content}")

store.close()
```

## Configuration

Settings are stored per-project in the SQLite database:

```bash
agentmemory settings                    # View all settings
agentmemory settings set llm.model haiku  # Change LLM model
```

Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `llm.enabled` | `true` | Use LLM for classification |
| `llm.model` | `haiku` | Anthropic model for classification |
| `reason.depth` | `2` | BFS graph traversal depth |
| `fts5.top_k` | `50` | Max FTS5 results per query |

## Benchmarks (v1.2.1)

Evaluated across 5 published benchmarks. All results are protocol-correct with
contamination-proof isolation (separate GT files, verified by `verify_clean.py`).
No embeddings, no vector DB.

| Benchmark | Metric | agentmemory | Best Published | Delta |
|---|---|---|---|---|
| LoCoMo (ACL 2024) | F1 | **66.1%** | 51.6% (GPT-4o-turbo) | +14.5pp |
| MAB SH 262K (ICLR 2026) | SEM | **90%** Opus / **62%** Haiku | 45% (GPT-4o-mini) | +45pp / +17pp |
| MAB MH 262K (ICLR 2026) | SEM | **60%** Opus | <=7% (all methods) | **8.6x ceiling** |
| StructMemEval (2026) | Accuracy | **100%** (14/14) | vector stores fail | temporal_sort fix |
| LongMemEval (ICLR 2025) | Opus judge | **59.0%** | 60.6% (GPT-4o) | -1.6pp |

**Multi-hop conflict resolution (MAB MH 262K):** All published methods score <=7%
on this task. agentmemory's entity-index retrieval achieves 60% (Opus) with 96%
of ground truth answers reachable in retrieved context (Exp 6). The conservative
chain-valid score is 35%, identical for both Opus and Haiku, confirming the
improvement comes from retrieval, not the reader model.

**LongMemEval:** 59.0% overall (295/500), within noise of the published GPT-4o
pipeline at 60.6%. Uses Opus as judge (paper specifies GPT-4o); comparison
carries an asterisk. Strongest categories: single-session-user (91.4%),
single-session-preference (80.0%), knowledge-update (70.5%).

agentmemory uses FTS5 + entity-index (L2.5) + HRR + BFS retrieval with a
2000-token budget per query. Full methodology, contamination protocol, and
per-benchmark details in [docs/BENCHMARK_RESULTS.md](docs/BENCHMARK_RESULTS.md).
Research article at [robotrocketscience.com/projects/agentmemory](https://robotrocketscience.com/projects/agentmemory).

## Acceptance Tests

35 documented LLM behavioral failures (across Claude and Codex) were cataloged
into case studies with root cause analysis. Each maps to a concrete acceptance
test with pass/fail criteria.

| Metric | Value |
|---|---|
| Total tests | 65 |
| Passed | 62 |
| Failed | 0 |
| Skipped | 3 (require behavioral hooks not yet built) |
| Duration | 1.65s |
| Test files | 29 |
| Case studies covered | 23 of 25 |

The 3 skipped tests require capabilities outside the memory system itself:
CS-012 (PostEdit hook for syntax validation), CS-024 (sycophantic collapse
detection), CS-026 (permission-gated behavioral beliefs).

Run acceptance tests:

```bash
uv run pytest tests/acceptance/ -x -q
```

## Research

This project is documented in a research article: [Persistent Memory for LLM Agents](https://robotrocketscience.com/projects/agentmemory).

85+ experiments during core development, plus 6 benchmark-phase experiments.
Each experiment had a pre-registered hypothesis, measurement protocol,
documented results, and an explicit proceed/revise/abandon decision. Negative
findings are documented with the same rigor as positive findings.

Key research documents in `docs/`:

| Document | Contents |
|---|---|
| [BENCHMARK_RESULTS.md](docs/BENCHMARK_RESULTS.md) | All benchmark scores, methodology, version progression |
| [BENCHMARK_PROTOCOL.md](docs/BENCHMARK_PROTOCOL.md) | Contamination-proof evaluation protocol |
| [RESEARCH_FREEZE_20260416.md](docs/RESEARCH_FREEZE_20260416.md) | Final findings, ceilings, future levers |
| [EXP1_PERHOP_FAILURE_ANALYSIS.md](docs/EXP1_PERHOP_FAILURE_ANALYSIS.md) | Multi-hop root cause analysis |
| [EXP5_RESULTS.md](docs/EXP5_RESULTS.md) | Regex vs LLM entity extraction |
| [EXP6_TEMPORAL_COHERENCE.md](docs/EXP6_TEMPORAL_COHERENCE.md) | Temporal branching results |

Experiment logs in `research/EXPERIMENTS.md`. Case studies in `research/CASE_STUDIES.md`.

## Development

```bash
git clone https://github.com/robotrocketscience/agentmemory.git
cd agentmemory
uv sync --all-groups
uv run pytest tests/ -x -q        # 362 tests
uv run pyright src/                # strict mode, 0 errors
```

## License

MIT
