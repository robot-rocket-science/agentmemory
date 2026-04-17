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
uv tool install agentmemory

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

### `/mem:` Command Reference

All commands are available as Claude Code slash commands after setup.

| Command | Description |
|---------|-------------|
| `/mem:search <query>` | Search beliefs relevant to a query. Uses the full retrieval pipeline (FTS5 + scoring + packing into token budget). Supports `--temporal` for newest-first re-ranking. |
| `/mem:remember <text>` | Store a new belief. Automatically classified by type (factual, preference, correction, requirement, procedural). |
| `/mem:correct <text>` | Record a user correction. Stored at high confidence (94.7%) and triggers supersession of conflicting beliefs. Prompts to lock. |
| `/mem:lock <belief_id>` | Lock a belief permanently. Locked beliefs cannot decay, are immune to feedback, and are injected into every prompt. Only the user can unlock. |
| `/mem:locked` | Show all locked beliefs (non-negotiable constraints). |
| `/mem:onboard <path>` | Scan a project directory and ingest structure: git history, AST, docs, citations, directives. Creates beliefs, edges, and entity index. |
| `/mem:status` | System analytics: belief count by type, confidence distribution, scoring features, session metrics. |
| `/mem:core [n]` | Show the top N highest-confidence beliefs. Default 10. |
| `/mem:stats` | Detailed analytics: confidence distribution, beliefs by type, age breakdown. |
| `/mem:timeline` | Temporal view of beliefs. Supports `--since` and `--until` for date ranges. |
| `/mem:evolution <topic>` | Track how beliefs about a topic changed over time. Shows supersession chains. |
| `/mem:diff` | Compare belief state between two points in time. |
| `/mem:reason <question>` | Graph-aware reasoning: retrieves beliefs, follows edges, synthesizes an answer using structural context. |
| `/mem:wonder <topic>` | Deep-dive research on a hypothesis or question using memory graph context and uncertainty analysis. |
| `/mem:feedback <id> <outcome>` | Manually provide feedback on a belief. Outcomes: `used`, `harmful`, `ignored`, `contradicted`. Updates Bayesian confidence. |
| `/mem:delete <id>` | Soft-delete a belief. Excluded from search/retrieval but remains in database. |
| `/mem:promote <id>` | Promote a belief to global scope (visible across all projects). |
| `/mem:snapshot` | Save a point-in-time snapshot of belief state for later comparison. |
| `/mem:new-belief <text>` | Store a new belief (alias for remember). |
| `/mem:settings` | View or update agentmemory settings (LLM model, retrieval depth, FTS5 top_k). |
| `/mem:disable` | Disable agentmemory for the rest of the current session. |
| `/mem:enable` | Re-enable agentmemory after `/mem:disable`. |
| `/mem:help` | Show available commands and usage guide. |
| `/mem:health` | Run diagnostics: DB integrity, index consistency, orphaned edges. |


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

## Benchmarks (v1.0)

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
git clone <repo-url>
cd agentmemory
uv sync --all-groups
uv run pytest tests/ -x -q
uv run pyright src/                # strict mode, 0 errors
```

## License

MIT
