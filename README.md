# agentmemory

> Your AI coding agent forgets everything when the session ends. agentmemory fixes that.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/agentmemory-rrs)](https://pypi.org/project/agentmemory-rrs/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

---

## The Problem

Every time you start a new session with Claude (or any AI coding agent), it starts from zero. It doesn't remember that you prefer uv over poetry, that you decided on SQLite last week, or that you corrected it about your API three times already. You end up repeating yourself, re-explaining your project, and watching the same mistakes happen again.

## The Solution

agentmemory runs in the background and gives your agent a persistent memory. It captures what you discuss, decide, and correct during normal conversation -- no manual notes, no copying context, no extra work from you.

```text
Session 1
you    We decided to use uv for this project, not poetry.
agent  Got it.

   ...session ends, days pass, new session starts...

Session 2
you    Set up the environment please.
agent  Using uv, per the project decision from last week.
       Pinning Python 3.12 as configured. Proceeding.
```

The second session starts already knowing. That's it. That's the whole thing.

## What It Remembers

- **Your decisions.** "We're using PostgreSQL." "Deploy to Cloudflare." "Never auto-commit."
- **Your corrections.** "No, use X not Y." It won't make the same mistake twice.
- **Your preferences.** Coding style, tool choices, communication preferences.
- **Project context.** Architecture decisions, who's doing what, deadlines, constraints.

## What It Doesn't Do

- It doesn't send your data anywhere. Everything stays in a local file on your machine.
- It doesn't require any setup beyond two commands.
- It doesn't slow down your workflow. It runs silently in the background.
- It doesn't need a GPU, a vector database, or an API key (beyond what Claude already uses).

## Install

```bash
pip install agentmemory-rrs
agentmemory setup
```

Restart Claude Code, then in any project:

```
/mem:onboard .
```

That's it. From now on, your agent remembers across sessions.

Full prerequisites and troubleshooting: [docs/INSTALL.md](docs/INSTALL.md).

## Daily Use

You don't need to learn any commands. agentmemory works automatically:

1. **It listens** to your conversations and picks up decisions, corrections, and preferences.
2. **It retrieves** relevant memories at the start of each turn and injects them into the agent's context.
3. **It learns** which memories are useful and which aren't -- helpful ones get stronger, unhelpful ones fade.

If you want to explicitly tell it something important:

```
/mem:lock "always use uv, never poetry"
```

That creates a permanent rule that persists across every session.

### Power User Commands

| Command | What it does |
|---|---|
| `/mem:search <query>` | Find specific memories |
| `/mem:lock <rule>` | Create a permanent rule |
| `/mem:wonder <topic>` | Deep research across the memory graph |
| `/mem:reason <question>` | Test a hypothesis against stored evidence |
| `/mem:stats` | See what's in memory |
| `/mem:health` | Check system health |

Full command reference: [docs/COMMANDS.md](docs/COMMANDS.md).

## How It Works (For the Curious)

Conversations are broken into individual beliefs stored in a local SQLite database. Each belief carries a confidence score that updates over time based on whether it helped or hurt. When the agent needs context, the system retrieves the most relevant beliefs within a fixed token budget using full-text search and graph traversal.

There are no embeddings, no vector database, and no external API calls in the retrieval pipeline.

For the full technical deep dive: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## Documentation

The full handbook is at **[docs/README.md](docs/README.md)**:

- **Getting Started:** [Installation](docs/INSTALL.md) -- [Workflow](docs/WORKFLOW.md)
- **Reference:** [Commands](docs/COMMANDS.md) -- [Obsidian Integration](docs/OBSIDIAN.md) -- [Privacy](docs/PRIVACY.md)
- **Technical:** [Architecture](docs/ARCHITECTURE.md) -- [Benchmarks](docs/BENCHMARK_RESULTS.md) -- [Research](docs/RESEARCH_FREEZE_20260416.md)

## Benchmarks

agentmemory has been evaluated against 5 published academic benchmarks with protocol-correct methodology, contamination-proof isolation, and pre-registered hypotheses. Highlights:

| Benchmark | Score | Context |
|---|---|---|
| MAB Single-Hop 262K | 92% | 2x the published GPT-4o-mini ceiling |
| StructMemEval | 100% | Perfect state tracking (14/14) |
| MAB Multi-Hop 262K | 58% | 8x the published 7% ceiling |
| LongMemEval | 59.6% | Near GPT-4o pipeline (60.6%) |

Full results, methodology, and audit trails: [docs/BENCHMARK_RESULTS.md](docs/BENCHMARK_RESULTS.md).

## Development

```bash
git clone https://github.com/robot-rocket-science/agentmemory.git
cd agentmemory
uv sync --all-groups
uv run pytest tests/ -x -q
```

Contributions welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Citation

```bibtex
@software{agentmemory2026,
  author    = {robotrocketscience},
  title     = {agentmemory: Persistent Memory for AI Coding Agents},
  year      = {2026},
  url       = {https://github.com/robot-rocket-science/agentmemory},
  license   = {MIT}
}
```

## License

[MIT](LICENSE)
