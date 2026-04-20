# Contributing to agentmemory

## Quick Start

```bash
git clone https://github.com/robot-rocket-science/agentmemory.git
cd agentmemory
uv sync --all-groups
uv run pytest tests/ -x -q
```

If you're using Claude Code to contribute, the `CLAUDE.md` file at the project root will automatically configure it with project conventions and the agentmemory MCP server.

## How This Project Works

agentmemory is built through experiment-driven development. Every design decision is backed by a numbered experiment in `experiments/`. When proposing a change:

1. **Check existing experiments.** Your idea may already have been tested.
2. **Write an experiment** if the change involves a design tradeoff
3. **Run the test suite** to verify nothing breaks

The research behind design decisions lives in `docs/research/`. The architecture is documented in `docs/ARCHITECTURE.md`.

## Project Structure

```
src/agentmemory/       Source code (33 modules)
tests/                 954 tests (unit + acceptance)
tests/acceptance/      Case study replay tests (CS-001 through CS-038)
experiments/           98 experiments documenting design decisions
benchmarks/            5 academic benchmark adapters
docs/                  User and contributor documentation
  docs/research/       Research notes behind design decisions
  docs/audits/         Claims audits and verification
  docs/website/        Website and marketing content
scripts/               Build and release tooling
```

## Code Style

- All Python files must have `from __future__ import annotations`
- All code must pass `pyright --typeCheckingMode strict`
- Use `uv` for all package management
- Commits use conventional prefixes: `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `exp:`
- Commits should be atomic and concise

## Running Tests

```bash
# Full suite
uv run pytest tests/ -x -q

# Type checking (strict mode)
uv run pyright src/

# Single test file
uv run pytest tests/acceptance/test_cs001_redundant_work.py -v

# Acceptance tests only
uv run pytest tests/acceptance/ -x -q
```

## Pre-commit Hooks

The repo uses pre-commit hooks for formatting and type checking. They run automatically on commit. If a hook fails:

1. `ruff format`: fix formatting first, then re-stage
2. `pyright`: fix type errors (strict mode, no `Any` allowed)
3. Re-stage changed files and commit again

## Key Documentation

| Doc | Purpose |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design and module relationships |
| [COMMANDS.md](docs/COMMANDS.md) | MCP tool and slash command reference |
| [BENCHMARK_RESULTS.md](docs/BENCHMARK_RESULTS.md) | Academic benchmark scores |
| [LIMITATIONS.md](docs/LIMITATIONS.md) | Known limitations and constraints |
| [RELEASE.md](docs/RELEASE.md) | Release procedure and troubleshooting |

## Adding a New Feature

1. Check `experiments/` for prior art on the problem
2. Write an experiment if needed (`experiments/exp{N}_{name}.py`)
3. Implement in `src/agentmemory/`
4. Add tests in `tests/`
5. If it adds an MCP tool, register it in `server.py`
6. Run the full test suite before submitting
