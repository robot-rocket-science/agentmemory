# agentmemory

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

## Installation

```bash
pip install agentmemory    # or: uv tool install agentmemory

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

## Benchmarks

Evaluated across 5 published benchmarks. All results are protocol-correct with
contamination-proof isolation (separate GT files, verified by `verify_clean.py`).

| Benchmark | Metric | agentmemory | Best Published | Delta |
|---|---|---|---|---|
| LoCoMo (ACL 2024) | F1 | **66.1%** | 51.6% (GPT-4o-turbo) | +14.5pp |
| MAB SH 262K (ICLR 2026) | SEM | **60.0%** | 45% (GPT-4o-mini) | +15.0pp |
| MAB MH 262K (ICLR 2026) | SEM | **32.0%** | <=7% (all methods) | **4.5x ceiling** |
| StructMemEval (2026) | Accuracy | **100%** | vector stores fail | temporal fix |
| LongMemEval (ICLR 2025) | proxy | 12.6% | 60.6% (GPT-4o) | needs LLM judge |

**Multi-hop conflict resolution (MAB MH 262K):** All published methods score <=7%
on this task. agentmemory's entity-index retrieval with SUPERSEDES-based conflict
resolution achieves 32%, a 4.5x improvement over the field ceiling.

agentmemory uses FTS5 + entity-index + HRR + BFS retrieval (no embeddings, no
vector DB) with a 2000-token budget per query. Full methodology and per-benchmark
details in [docs/BENCHMARK_RESULTS.md](docs/BENCHMARK_RESULTS.md).

## Development

```bash
git clone https://github.com/yoshi280/agentmemory.git
cd agentmemory
uv sync --all-groups
uv run pytest tests/ -x -q        # 362 tests
uv run pyright src/                # strict mode, 0 errors
```

## License

MIT
