# agentmemory

> Persistent memory for AI coding agents. Your agent remembers what you discussed, decided, and corrected, so the next session does not start from scratch.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Status](https://img.shields.io/badge/status-beta-orange.svg)](#)

**[Read the handbook](docs/README.md)** · [Install](docs/INSTALL.md) · [Workflow](docs/WORKFLOW.md) · [Architecture](docs/ARCHITECTURE.md) · [Benchmarks](docs/BENCHMARK_RESULTS.md) · [Project writeup](https://robotrocketscience.com/projects/agentmemory)

---

## Why

When a session ends, your agent forgets everything. You end up re-explaining the project, re-stating the same preferences, and watching the same mistakes happen again.

agentmemory captures decisions, corrections, and context as you work, and hands them back to the agent next time. No manual notes. No context files. Just memory.

## Install

```bash
uv pip install git+https://github.com/robot-rocket-science/agentmemory.git
agentmemory setup
```

Restart Claude Code, then in any project:

```
/mem:onboard .
```

Full prerequisites and troubleshooting: [docs/INSTALL.md](docs/INSTALL.md).

## What it does

- **Remembers automatically.** Captures decisions, corrections, and preferences from your conversations without you lifting a finger.
- **Learns what matters.** Memories that help get stronger over time. Memories that hurt get weaker. The system tunes itself to your project.
- **Stays on your machine.** Everything lives in local SQLite. No cloud, no vector database, no telemetry unless you opt in.
- **Works with any MCP agent.** Claude Code is the primary target, but any MCP-compatible client can connect to the server.

## A sketch of what using it feels like

```text
Session 1
─────────
you    We decided to use uv for this project, not poetry.
agent  Got it.

   ...session ends, days pass, new session opens...

Session 2
─────────
you    Set up the environment please.
agent  Using uv, per the project decision from last week.
       Pinning Python 3.12 as configured. Proceeding.
```

The second session starts already knowing. That is the whole pitch.

## How it works

Conversations become scored beliefs in a local graph. Each belief gets stronger or weaker based on whether it helped. Retrieval pulls the most relevant subset into the agent's context on every turn, within a fixed token budget.

![agentmemory pipeline: ingestion, retrieval, and feedback](docs/pipeline-architecture.svg)

Deep dive in the handbook: [Chapter 5 - Architecture](docs/ARCHITECTURE.md).

## Documentation

The full handbook is at **[docs/README.md](docs/README.md)** and is structured as a short book with prev/next navigation on every page. Jump to a chapter:

- **Part I - Getting Started:** [Installation](docs/INSTALL.md) · [Workflow](docs/WORKFLOW.md)
- **Part II - Reference:** [Commands](docs/COMMANDS.md) · [Obsidian](docs/OBSIDIAN.md)
- **Part III - Under the Hood:** [Architecture](docs/ARCHITECTURE.md) · [Privacy](docs/PRIVACY.md)
- **Part IV - Benchmarks and Research:** [Protocol](docs/BENCHMARK_PROTOCOL.md) · [Results](docs/BENCHMARK_RESULTS.md) · [Research Freeze](docs/RESEARCH_FREEZE_20260416.md)

## Wonder and Reason

agentmemory includes two graph-aware research commands that go beyond simple keyword search. They use the belief graph -- edges like SUPPORTS, CONTRADICTS, SUPERSEDES, CITES -- to surface connected evidence and detect reasoning gaps.

### `/mem:wonder <topic>` -- Deep Research

Wonder is exploratory. You give it a topic and it fans out across the belief graph to collect everything relevant, even things you did not directly search for.

1. **Retrieves** seed beliefs via FTS5 keyword search
2. **Expands** outward along graph edges (BFS, configurable depth)
3. **Scores uncertainty** for each belief using Beta distribution variance
4. **Detects contradictions** between beliefs in the result set
5. **Outputs** a structured context block with three sections: Known Facts (direct hits), Connected Evidence (reached via graph traversal), and Open Questions (high-uncertainty beliefs)

Use wonder when you want to survey what the system knows about a topic before making a decision. It answers: "what do we know, what is connected, and where are we uncertain?"

### `/mem:reason <question>` -- Hypothesis Testing

Reason is focused. You give it a question or hypothesis and it builds branching consequence paths to evaluate whether the evidence supports it.

1. **Retrieves** seed beliefs, then checks relevance (content-word overlap filter)
2. **Builds consequence paths** -- chains of beliefs linked by edges, with compound confidence decay at each hop
3. **Checks constraints** -- compares paths against locked beliefs for conflicts
4. **Detects impasses** -- four types: ties (contradicting beliefs at similar confidence), gaps (dead-end paths), constraint failures (conflicts with locked beliefs), and no-change (all low-confidence evidence)
5. **Issues a verdict**: SUFFICIENT, INSUFFICIENT, UNCERTAIN, CONTRADICTORY, or PARTIAL

Use reason when you need to evaluate a specific claim or decision. It answers: "does the evidence support this, and if not, where does the reasoning break down?"

### The difference

Wonder is divergent -- cast a wide net, see what is out there. Reason is convergent -- evaluate a specific claim against the evidence. Together they form a research loop: wonder to survey the landscape, reason to test specific hypotheses that emerge from it.

## Benchmarks

> [!NOTE]
> **About these numbers.** I run and publish benchmarks because I believe objective, replicable methodology and transparent result reporting matter, and that readers deserve to see them. I place limited personal weight on the numbers themselves. V&V for agent memory systems is a specialized area where I do not have deep hands-on experience, and I cannot be fully confident that Claude and I have exercised these systems as rigorously as a dedicated evaluator would.
>
> What I can commit to is the scientific rigor I was trained on and the professional engineering standards I am obligated to uphold: pre-registered hypotheses, contamination protocols, protocol-correct evaluation, and full methodology disclosure.
>
> I welcome constructive criticism, independent replication, and analysis that refutes or supports any of these claims, and I would be glad to collaborate with anyone interested in strengthening the evaluation.

Evaluated across 5 published benchmarks. All results are protocol-correct with contamination-proof isolation (separate GT files, verified by `verify_clean.py`, enforced by 65 pytest protocol tests). No embeddings, no vector DB.

| Benchmark | Metric | v2.2.2 | v1.2.1 | Best Published |
|---|---|---|---|---|
| MAB SH 262K (ICLR 2026) | SEM | **92%** | 90% | 45% (GPT-4o-mini) |
| MAB MH 262K (ICLR 2026) | SEM | **58%** | 60% | <=7% (all methods) |
| StructMemEval (2026) | Accuracy | **100%** (14/14) | 100% | vector stores fail |
| LongMemEval (ICLR 2025) | Opus judge | **59.6%** | 59.0% | 60.6% (GPT-4o) |
| LoCoMo (ACL 2024) | F1 | **50.8%** | 66.1% | 51.6% (GPT-4o-turbo) |

The LoCoMo v2.2.2 score (50.8%) is lower than v1.2.1 (66.1%) due to reader variance from different sub-agent batching strategies. Retrieval code is unchanged between versions. This is a single-run result; per Lin's methodology checklist, multi-run reporting (>=5 runs with mean +/- std) is needed to quantify reader variance. See the full analysis in the results doc.

Methodology, per-benchmark details, and audit trails: [Chapter 8 - Benchmark Results](docs/BENCHMARK_RESULTS.md).

## Development

```bash
git clone https://github.com/robot-rocket-science/agentmemory.git
cd agentmemory
uv sync --all-groups
uv run pytest tests/ -x -q
uv run pyright src/
```

Contributions welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Citation

If you use agentmemory in your research or project, please cite:

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

[MIT](LICENSE) -- free for personal, commercial, and any other use. Citation appreciated.
