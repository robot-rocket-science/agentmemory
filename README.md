# agentmemory

Persistent memory for AI coding agents. When you close a session and open a new one, the agent starts from scratch. agentmemory fixes that.

It records what you discuss, what you decide, what you correct, and what works. Next session, the agent already knows your project, your preferences, and what was tried before. No manual context files. No copy-pasting from last session. It just remembers.

**[Full writeup at robotrocketscience.com/projects/agentmemory](https://robotrocketscience.com/projects/agentmemory)**

## Install

```bash
uv pip install git+https://github.com/yoshi280/agentmemory.git
agentmemory setup
# restart Claude Code, then:
/mem:onboard .
```

Full prerequisites, verification, and troubleshooting: [docs/INSTALL.md](docs/INSTALL.md).

## Documentation

| Topic | Location |
|---|---|
| Installation and troubleshooting | [docs/INSTALL.md](docs/INSTALL.md) |
| Day-to-day workflow | [docs/WORKFLOW.md](docs/WORKFLOW.md) |
| Architecture and retrieval internals | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Privacy and security properties | [docs/PRIVACY.md](docs/PRIVACY.md) |
| `/mem:` command reference | [docs/COMMANDS.md](docs/COMMANDS.md) |
| Obsidian integration | [docs/OBSIDIAN.md](docs/OBSIDIAN.md) |
| Benchmark methodology | [docs/BENCHMARK_PROTOCOL.md](docs/BENCHMARK_PROTOCOL.md) |
| Benchmark results (detailed) | [docs/BENCHMARK_RESULTS.md](docs/BENCHMARK_RESULTS.md) |
| Research freeze (final findings) | [docs/RESEARCH_FREEZE_20260416.md](docs/RESEARCH_FREEZE_20260416.md) |
| Contributing | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Changelog | [CHANGELOG.md](CHANGELOG.md) |

## Benchmarks (v1.1.1)

Evaluated across 5 published benchmarks. All results are protocol-correct with
contamination-proof isolation (separate GT files, verified by `verify_clean.py`).
No embeddings, no vector DB.

**A note on these results.** I run and publish benchmarks because I believe
objective, replicable methodology and transparent result reporting matter, and
that readers deserve to see them. I place limited personal weight on the
numbers themselves. V&V for agent memory systems is a specialized area where
I do not have deep hands-on experience, and I cannot be fully confident that
Claude and I have exercised these systems as rigorously as a dedicated
evaluator would. What I can commit to is the scientific rigor I was trained
on and the professional engineering standards I am obligated to uphold:
pre-registered hypotheses, contamination protocols, protocol-correct
evaluation, and full methodology disclosure. I welcome constructive
criticism, independent replication, and analysis that refutes or supports any
of these claims, and I would be glad to collaborate with anyone interested in
strengthening the evaluation.

| Benchmark | Metric | agentmemory | Best Published | Delta |
|---|---|---|---|---|
| LoCoMo (ACL 2024) | F1 | **66.1%** | 51.6% (GPT-4o-turbo) | +14.5pp |
| MAB SH 262K (ICLR 2026) | SEM | **90%** Opus / **62%** Haiku | 45% (GPT-4o-mini) | +45pp / +17pp |
| MAB MH 262K (ICLR 2026) | SEM | **60%** Opus | <=7% (all methods) | **8.6x ceiling** |
| StructMemEval (2026) | Accuracy | **100%** (14/14) | vector stores fail | temporal_sort fix |
| LongMemEval (ICLR 2025) | Opus judge | **59.0%** | 60.6% (GPT-4o) | -1.6pp |

Full methodology and per-benchmark details in [docs/BENCHMARK_RESULTS.md](docs/BENCHMARK_RESULTS.md).

## Research

84 experiments during core development, plus 6 benchmark-phase experiments.
Each experiment had a pre-registered hypothesis, measurement protocol,
documented results, and an explicit proceed/revise/abandon decision. Logs
in `research/EXPERIMENTS.md`. Case studies in `research/CASE_STUDIES.md`.

This project's research phase drew heavily on Leonard Lin's
[agentic-memory](https://github.com/lhl/agentic-memory) collection, which
surveys 35+ papers, 14+ community systems, and 6 benchmarks.

```bibtex
@misc{lin_agentic_memory_2026,
  author       = {Leonard Lin},
  title        = {agentic-memory: Agentic Memory Research Collection (Summaries and Analyses)},
  year         = {2026},
  howpublished = {GitHub repository},
  url          = {https://github.com/lhl/agentic-memory},
}
```

## Development

```bash
git clone https://github.com/yoshi280/agentmemory.git
cd agentmemory
uv sync --all-groups
uv run pytest tests/ -x -q
uv run pyright src/                # strict mode, 0 errors
```

## License

MIT
