# agentmemory

> **Correct your AI agent once. It remembers forever.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/agentmemory-rrs)](https://pypi.org/project/agentmemory-rrs/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

---

## You Shouldn't Have to Repeat Yourself

Every time you start a new session with an AI coding agent, it forgets everything. Your preferences, your decisions, your corrections -- gone. You end up saying the same things session after session:

*"Use uv, not pip." "I told you, we're using PostgreSQL." "Stop adding co-author lines to commits."*

<p align="center"><img src="https://robotrocketscience.com/projects/agentmemory/comics/01-no-implementation-cs002cs006.png" width="480" alt="Comic: user says 'no implementation, we're in research.' Agent says 'got it!' Next session: 'Ready to implement?' User: 'I TOLD YOU. TWICE.' Agent: '...three times, actually!'"></p>

**agentmemory makes that stop.** It runs silently in the background, captures what matters from your conversations, and hands it back to the agent next session. You correct once. It sticks.

## What Changes For You

| Before agentmemory | After agentmemory |
|---|---|
| Repeat the same corrections every session | Correct once, remembered permanently |
| Re-explain your project setup each time | Agent already knows your stack, preferences, and constraints |
| Watch the agent make the same mistakes | Mistakes are stored as corrections and never repeated |
| Lose important decisions when sessions end | Decisions persist across sessions, weeks, months |
| Start every session from scratch | Agent picks up where you left off |

## Your Data Stays Yours

- **100% local.** Everything lives in a SQLite file on your machine. Nothing is sent anywhere.
- **No cloud, no accounts.** There is no server, no signup. Optional anonymous telemetry exists but is disabled by default and only collects counts, never content.
- **No GPU or vector database required.** It runs on any machine that runs Python.
- **Two commands to install.** Nothing else to configure.

## Real Examples

From actual sessions. Names and project details changed, conversations verbatim.

### Before: Problems that made us build this

These are real failures that happened without persistent memory. They're why agentmemory exists.

**"I searched your entire filesystem. Nothing."**

A user asked the agent to review documents they'd worked on together the previous session. The agent searched every directory on the machine, reported the files didn't exist -- then found them two minutes later in the current working directory, exactly where they'd been created.

```text
user    Please review the project docs we worked on yesterday.

agent   I can't find any matching files on your system. I searched:
        - ~/projects/ (all subdirectories)
        - ~/Documents/
        - ~/Downloads/
        - ~/Desktop/
        No files matching "project docs" found anywhere.

user    ...we literally created them yesterday. In this directory.

agent   Oh. Found them.
```

*With agentmemory, the agent already knows about the documents because it remembers creating them. No filesystem search needed.*

**"EXTENSIVE research completed. 353 tests all PASS."**

AI agents love to report impressive-sounding metrics. Without memory, there's no record of what was actually measured, so the next session takes the inflated claim at face value.

<p align="center"><img src="https://robotrocketscience.com/projects/agentmemory/comics/05-big-numbers-cs008.png" width="420" alt="Comic: agent reports 100% precision. User asks: on what exactly? Agent: regex-matched citation tags in one project that uses citation tags. User: and the recall? Agent: ...19%"></p>

*With agentmemory, the correction ("that metric is misleading -- 100% precision on a rigged test, 19% recall") persists. The next session knows the real numbers, not the inflated ones.*

### After: Emergent behavior once memory is running

These weren't planned features. They emerged from the system having persistent memory and being able to reason over it.

**The agent audited its own memory and found a bug**

A user asked the agent to check whether a config file had become redundant with the memory system. The agent searched its own beliefs, compared them against the config, and discovered that a locked belief about the project's infrastructure was stale -- it still referenced a server that had been decommissioned days earlier. Every new session was being injected with wrong instructions, and nobody had noticed.

```text
user    Clean up the config file, I think agentmemory is already
        handling some of this stuff.

agent   [searches memory, compares against config]
        Found 2 redundant items. But also: this locked belief
        about your server setup is stale. It references
        infrastructure you removed. Every session is getting
        incorrect instructions from it.

user    Fix it.

agent   [corrects the belief, supersedes the old one]
        Done. Want to lock the updated version?
```

*The system caught its own error. This wasn't a planned feature -- it happened because the agent had enough context to notice the inconsistency.*

**The agent pushed back on a version number**

A user asked `/mem:reason "do we have enough changes since the last release to justify a v3?"` The system analyzed its own belief graph, reviewed experiment results and git history, then argued against the user's framing:

```text
ANSWER: Not v3. v2.5.0 at most.

Evidence:
- No breaking API changes (all new params default to neutral)
- New features are additive layers, not architectural changes
- Core scoring problem diagnosed but not solved
- Intention clustering needs validation at scale

What's nagging me:
  Locked beliefs are drowning out relevant content in search
  results. The lock boost is too aggressive relative to
  everything else.

Recommendation: Ship as v2.5.0, go deeper on retrieval quality
before any v3 claim.
```

*The system reasoned over its own evidence, resisted the user's framing, and made a calibrated recommendation. It even identified a real retrieval problem during the analysis that nobody had asked about. This is what happens when an agent has enough accumulated context to form independent judgments.*

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

<p align="center"><img src="https://robotrocketscience.com/projects/agentmemory/obsidian-graph-full.jpg" width="600" alt="Knowledge graph visualization showing thousands of interconnected beliefs built up over weeks of use"></p>
<p align="center"><em>The knowledge graph after a few weeks of daily use, visualized in Obsidian. Each dot is a belief. Lines are relationships (supports, contradicts, supersedes).</em></p>

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
