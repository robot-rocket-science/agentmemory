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

## Real Examples

These are from actual sessions, sanitized for privacy but otherwise verbatim.

### "Stop asking me the same thing"

Without memory, every session starts from scratch. You end up correcting the agent on the same points over and over:

```text
Session 3:  "Use uv, not pip."
Session 7:  "I told you, use uv."
Session 12: "Why are you using pip again?"
```

With agentmemory, the first correction sticks. The agent remembers "use uv, not pip" with high confidence, and it gets injected into every future session automatically. You correct once, it learns permanently.

### Catching stale information before it causes problems

In a real session, the user asked the agent to audit a configuration file for redundancy. The agent searched memory and found that a locked belief about the project's git remote setup was stale -- it still referenced a remote that had been removed days earlier. Every new session was getting injected with incorrect instructions.

```text
user    Clean up the config file, I think memory is already
        handling some of this stuff.

agent   [searches memory, compares against config]
        Found overlap. But also: this locked belief about your git
        remotes is stale. It references a remote you removed.
        Every session is getting wrong instructions from it.

user    Fix it.

agent   [corrects the belief, asks to lock the updated version]
```

Without memory, the stale information would have persisted indefinitely. The system detected its own error.

### Deep research with /mem:wonder

A user ran `/mem:wonder "state tracking formal design framework"` to explore whether the project needed a formal state machine. The system:

1. Found 64 existing beliefs about state tracking (64.7% coverage)
2. Identified 7 contradictions between them
3. Found 3 gaps where the system had no beliefs at all
4. Spawned 4 research agents in parallel to investigate the gaps
5. Ingested the findings as low-confidence speculative beliefs with a 14-day expiration

The speculative beliefs either get confirmed by evidence (and promoted to real beliefs) or expire and get garbage collected. The system explores on its own, but doesn't pollute the knowledge base with unvalidated claims.

### Hypothesis testing with /mem:reason

A user asked `/mem:reason "do we have enough changes since the last release to justify a v3?"` The system analyzed its own belief graph and git history, then pushed back:

```text
ANSWER: Not v3. v2.5.0 at most.

Evidence:
- No breaking API changes (all new params default to neutral)
- New features are additive layers, not architectural changes
- Core scoring problem diagnosed but not solved
- Intention clustering needs validation at scale

What's nagging me:
  Locked beliefs are drowning out relevant content in search results.
  7 of 10 top results for a technical query were irrelevant locked
  beliefs about git remotes. The lock boost is too aggressive.

Recommendation: Ship as v2.5.0, go deeper on retrieval quality
before any v3 claim.
```

The system reasoned over its own evidence, resisted the user's framing, identified a real problem it discovered during its own analysis, and made a calibrated recommendation. This is what memory-backed reasoning looks like in practice.

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
