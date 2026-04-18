# The agentmemory Handbook

Welcome. This is the long-form documentation for **agentmemory**, a persistent
memory system for AI coding agents. The chapters are meant to be read top to
bottom on your first pass, but every page stands on its own and can be used as
a reference later.

If you landed here by accident, the [project overview is in the repo
README](../README.md).

---

## Contents

### Part I - Getting Started

1. [**Installation**](INSTALL.md) - prerequisites, step-by-step install, verification, and troubleshooting.
2. [**Workflow**](WORKFLOW.md) - the discuss / explore / focus / build / repeat loop, and the daily commands you will use.

### Part II - Reference

3. [**Command Reference**](COMMANDS.md) - every `/mem:` slash command and its CLI equivalent.
4. [**Obsidian Integration**](OBSIDIAN.md) - syncing the belief graph into an Obsidian vault for browsing and visualization.

### Part III - Under the Hood

5. [**Architecture**](ARCHITECTURE.md) - retrieval layers, the belief graph, and the scoring model.
6. [**Privacy and Security**](PRIVACY.md) - verifiable properties of the codebase, what lives on your machine, and what (if anything) leaves it.

### Part IV - Benchmarks and Research

7. [**Benchmark Protocol**](BENCHMARK_PROTOCOL.md) - the contamination-proof evaluation methodology used across all runs.
8. [**Benchmark Results**](BENCHMARK_RESULTS.md) - per-benchmark scores, methodology notes, and version progression.
9. [**Research Freeze (April 2026)**](RESEARCH_FREEZE_20260416.md) - final findings, observed ceilings, and open questions.

### Also in the repo

- [Contributing guide](../CONTRIBUTING.md)
- [Changelog](../CHANGELOG.md)
- [Experiment logs](../research/EXPERIMENTS.md)
- [Case studies](../research/CASE_STUDIES.md)

---

## How to read this handbook

- **New here?** Read [Installation](INSTALL.md), then [Workflow](WORKFLOW.md). That is enough to use the system productively.
- **Want to understand what the system is actually doing?** Jump to [Architecture](ARCHITECTURE.md) and [Privacy](PRIVACY.md).
- **Evaluating for adoption or review?** Start at [Benchmark Protocol](BENCHMARK_PROTOCOL.md) and [Benchmark Results](BENCHMARK_RESULTS.md).
- **Looking up a specific command?** [Command Reference](COMMANDS.md) is the index.

Every chapter has a navigation bar at the top and bottom with links to the
previous chapter, this contents page, and the next chapter, so you can move
through the book without coming back here each time.

---

[Start reading → Chapter 1: Installation](INSTALL.md)
