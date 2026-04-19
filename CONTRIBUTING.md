# Contributing

## Setup

```bash
git clone https://github.com/robot-rocket-science/agentmemory.git
cd agentmemory
uv sync --all-groups
```

## Development

```bash
# Run tests
uv run pytest tests/ -x -q

# Type checking (strict mode)
uv run pyright src/

# Run a single test file
uv run pytest tests/acceptance/test_cs001_redundant_work.py -v
```

## Code Style

- All Python files must have `from __future__ import annotations`
- All code must pass `pyright --typeCheckingMode strict`
- Use `uv` for all package management
- Commits should be atomic and concise

## Testing

- Unit tests go in `tests/`
- Acceptance tests (case study replays) go in `tests/acceptance/`
- Every new feature should have tests that exercise the store/retrieval API

## Project Structure

```
src/agentmemory/
  store.py          # SQLite storage layer
  retrieval.py      # Multi-stage retrieval pipeline
  scoring.py        # Bayesian scoring and decay
  hrr.py            # Holographic reduced representations
  scanner.py        # Project onboarding extractors
  server.py         # MCP server (FastMCP)
  cli.py            # CLI commands
  models.py         # Data models
  ingest.py         # Conversation ingestion
  classification.py # LLM belief classification
  ...
```
