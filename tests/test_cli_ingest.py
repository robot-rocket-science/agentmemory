"""Functional tests for ingest_jsonl (CLI ingest subcommand backend)."""
from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import pytest

from agentmemory.ingest import IngestResult, ingest_jsonl
from agentmemory.store import MemoryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    s: MemoryStore = MemoryStore(tmp_path / "test.db")
    yield s
    s.close()


SAMPLE_TURNS: list[dict[str, str]] = [
    {
        "timestamp": "2026-04-18T10:00:00Z",
        "event": "user",
        "session_id": "sess-001",
        "text": "Always use uv for Python package management.",
    },
    {
        "timestamp": "2026-04-18T10:00:05Z",
        "event": "assistant",
        "session_id": "sess-001",
        "text": "Understood. I will use uv for all Python packaging tasks going forward.",
    },
    {
        "timestamp": "2026-04-18T10:00:10Z",
        "event": "user",
        "session_id": "sess-001",
        "text": "The deployment target is Ubuntu 22.04 with Python 3.12.",
    },
]


def _write_jsonl(path: Path, records: list[dict[str, str]]) -> Path:
    """Write records as a JSONL file and return the path."""
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ingest_jsonl_creates_observations(
    store: MemoryStore, tmp_path: Path
) -> None:
    """Each non-empty JSONL line should produce one observation."""
    jsonl_file: Path = _write_jsonl(tmp_path / "turns.jsonl", SAMPLE_TURNS)

    result: IngestResult = ingest_jsonl(store, jsonl_file)

    assert result.observations_created == len(SAMPLE_TURNS)

    rows = store.query("SELECT COUNT(*) FROM observations")
    obs_count: int = int(rows[0][0])
    assert obs_count == len(SAMPLE_TURNS)


def test_ingest_jsonl_creates_beliefs(
    store: MemoryStore, tmp_path: Path
) -> None:
    """Ingested turns with substantive content should produce beliefs."""
    jsonl_file: Path = _write_jsonl(tmp_path / "turns.jsonl", SAMPLE_TURNS)

    result: IngestResult = ingest_jsonl(store, jsonl_file)

    assert result.beliefs_created > 0

    rows = store.query("SELECT COUNT(*) FROM beliefs")
    belief_count: int = int(rows[0][0])
    assert belief_count == result.beliefs_created


def test_ingest_jsonl_creates_edges(
    store: MemoryStore, tmp_path: Path
) -> None:
    """Related beliefs should produce edges via detect_relationships."""
    jsonl_file: Path = _write_jsonl(tmp_path / "turns.jsonl", SAMPLE_TURNS)

    ingest_jsonl(store, jsonl_file)

    rows = store.query("SELECT COUNT(*) FROM edges")
    edge_count: int = int(rows[0][0])
    # With related turns about Python/uv, at least one edge should exist
    assert edge_count > 0


def test_ingest_jsonl_skips_empty_lines(
    store: MemoryStore, tmp_path: Path
) -> None:
    """Blank lines and whitespace-only lines should be silently skipped."""
    content: str = (
        json.dumps(SAMPLE_TURNS[0]) + "\n"
        + "\n"
        + "   \n"
        + json.dumps(SAMPLE_TURNS[1]) + "\n"
    )
    jsonl_file: Path = tmp_path / "sparse.jsonl"
    jsonl_file.write_text(content, encoding="utf-8")

    result: IngestResult = ingest_jsonl(store, jsonl_file)

    assert result.observations_created == 2


def test_ingest_jsonl_skips_missing_fields(
    store: MemoryStore, tmp_path: Path
) -> None:
    """Lines missing required fields (event or text) should be skipped."""
    bad_records: list[dict[str, str]] = [
        {"timestamp": "2026-04-18T10:00:00Z", "session_id": "s1", "text": "no event field"},
        {"timestamp": "2026-04-18T10:00:00Z", "event": "user", "session_id": "s1"},
        {"timestamp": "2026-04-18T10:00:00Z", "event": "user", "session_id": "s1", "text": ""},
    ]
    jsonl_file: Path = _write_jsonl(tmp_path / "bad.jsonl", bad_records)

    result: IngestResult = ingest_jsonl(store, jsonl_file)

    assert result.observations_created == 0
    assert result.beliefs_created == 0


def test_ingest_jsonl_empty_file(
    store: MemoryStore, tmp_path: Path
) -> None:
    """An empty JSONL file should produce zero results without error."""
    jsonl_file: Path = tmp_path / "empty.jsonl"
    jsonl_file.write_text("", encoding="utf-8")

    result: IngestResult = ingest_jsonl(store, jsonl_file)

    assert result.observations_created == 0
    assert result.beliefs_created == 0
