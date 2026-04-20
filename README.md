# agentmemory

> **Correct your AI agent once. It remembers forever.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/agentmemory-rrs)](https://pypi.org/project/agentmemory-rrs/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

---

You tell your AI agent "never commit .env files." It says "got it." Next session, it stages `.env` in a commit. You correct it again. And again. And again.

**agentmemory makes the next correction your last.** It captures what matters from your conversations -- corrections, decisions, preferences -- stores them locally, and injects them into every future session. Silently. Automatically. You stop repeating yourself.

```bash
pip install agentmemory-rrs
agentmemory setup
```

Restart Claude Code. In any project: `/mem:onboard .`

That's it. Three commands. Your agent now remembers permanently.

<p align="center"><img src="https://robotrocketscience.com/projects/agentmemory/comics/01-no-implementation-cs002cs006.png" width="480" alt="Comic: user says 'no implementation, we're in research.' Agent says 'got it!' Next session: 'Ready to implement?' User: 'I TOLD YOU. TWICE.' Agent: '...three times, actually!'"></p>

---

## What It Actually Does

Here's a real example. You type `push the release to github`. Before the agent sees your message, agentmemory's hook fires and runs a 7-layer search in ~50ms:

```
Layer 0: Structural analysis    -> task type: deployment, target: github
Layer 1: FTS5 full-text search  -> 4 hits (publish script, CI checks, remote config)
Layer 2: Entity expansion       -> "github" links to 3 beliefs about repo setup
Layer 3: Action-context         -> "push to github" triggers activation condition
Layer 4: Supersession check     -> old remote URL excluded (superseded)
Layer 5: Recent observations    -> correction from 2 days ago about publish script
Layer 6: Cross-project scopes   -> checks shared infra beliefs
```

The agent receives this context injection alongside your message:

```
== OPERATIONAL STATE ==
[!] GitHub account renamed (changed 2d ago)

== STANDING CONSTRAINTS ==
- NEVER use git push github directly. Use scripts/publish-to-github.sh
- Pre-push hook scans for PII; direct push bypasses safety checks
- To release with tag: bash scripts/publish-to-github.sh --tag vX.Y.Z

== BACKGROUND ==
- Remote 'github' points to git@github.com:robot-rocket-science/agentmemory.git
```

Without agentmemory, the agent takes "push to github" literally and runs `git push github main`, bypassing every safety check. With it, the agent heard three words and executed the full procedure -- publish script, PII guards, pre-push hook. That procedure was never taught in one session. It accumulated from corrections over weeks.

---

## What It Remembers

| You say | It stores |
|---|---|
| "Never commit .env files" | Permanent rule. Injected every session. |
| "The endpoint moved to /v2" | Correction. Replaces the old belief. |
| "I prefer terse commits" | Preference. Shapes behavior silently. |

Beliefs accumulate over time. Each one carries a Bayesian confidence score that strengthens when the belief proves useful and fades when it doesn't. After a few weeks:

```
/mem:stats
Beliefs: 312 (18 locked, 294 learned)
Sessions: 47
Corrections surfaced this session: 3
Last locked: "never force-push to main" (4 weeks ago)
```

---

## Your Data Stays Yours

- **100% local.** SQLite on your machine. No network calls in the retrieval pipeline.
- **No cloud, no accounts.** No server, no signup, no telemetry by default.
- **No GPU or vector database.** Runs on any machine that runs Python.

---

## What Happens After Install

agentmemory works in the background:

1. **It listens** -- picks up decisions, corrections, and preferences from your conversations
2. **It retrieves** -- injects relevant beliefs before the agent responds to each prompt
3. **It learns** -- beliefs that help get stronger; beliefs that don't, fade

To explicitly lock a permanent rule:

```
/mem:lock "never commit .env files"
```

For deeper exploration:

| Command | What it does |
|---|---|
| `/mem:search <query>` | Find specific memories |
| `/mem:lock <rule>` | Create a permanent rule |
| `/mem:wonder <topic>` | Deep parallel research across the memory graph |
| `/mem:reason <question>` | Test a hypothesis against stored evidence |
| `/mem:stats` | See what's in memory |

Full command reference: [docs/COMMANDS.md](docs/COMMANDS.md).

---

## Emergent Behavior

These weren't planned features. They emerged from persistent memory + reasoning tools.

**The agent audited its own memory and found a bug**

```text
user    Clean up the config file, I think agentmemory handles this now.

agent   [searches memory, compares against config]
        Found 2 redundant items. But also: this locked belief about
        your server setup is stale -- it references infrastructure
        you removed. Every session is getting incorrect instructions.

user    Fix it.

agent   [corrects the belief, supersedes the old one]
        Done. Want to lock the updated version?
```

The system caught its own error because it had enough accumulated context to notice the inconsistency. [More examples and a full session transcript showing wonder + reason in action](docs/case-study-positioning.md).

---

## Under the Hood

Conversations are broken into individual beliefs stored in a local SQLite database. Retrieval uses full-text search, graph traversal, and vocabulary bridging -- no embeddings, no vector database, no external API calls.

98 experiments drove every design decision. 954 tests. 5 academic benchmarks. Architecture details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

<p align="center"><img src="https://robotrocketscience.com/projects/agentmemory/obsidian-graph-full.jpg" width="600" alt="Knowledge graph visualization showing thousands of interconnected beliefs built up over weeks of use"></p>
<p align="center"><em>The knowledge graph after a few weeks of daily use. Each dot is a belief. Lines are relationships (supports, contradicts, supersedes).</em></p>

---

## Compatibility

Currently supports **Claude Code** via MCP (Model Context Protocol). The architecture is agent-agnostic -- any MCP-compatible client can use agentmemory as a memory backend.

---

## Documentation

- **Getting Started:** [Installation](docs/INSTALL.md) -- [Workflow](docs/WORKFLOW.md)
- **Reference:** [Commands](docs/COMMANDS.md) -- [Obsidian Integration](docs/OBSIDIAN.md) -- [Privacy](docs/PRIVACY.md)
- **Technical:** [Architecture](docs/ARCHITECTURE.md) -- [Benchmarks](docs/BENCHMARK_RESULTS.md) -- [Case Studies](docs/case-study-positioning.md)

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
