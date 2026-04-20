"""Validation tests: check assumptions before building the Obsidian export layer.

These tests run against the live DB and filesystem to verify that our
design assumptions hold. They are not unit tests -- they validate the
environment and data we will operate on.
"""

from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_project_db() -> Path:
    """Find the agentmemory DB for this project."""
    import hashlib

    cwd: str = str(Path("/home/user/projects/agentmemory").resolve())
    path_hash: str = hashlib.sha256(cwd.encode()).hexdigest()[:12]
    db_path: Path = Path.home() / ".agentmemory" / "projects" / path_hash / "memory.db"
    return db_path


@pytest.fixture()
def live_conn() -> sqlite3.Connection:
    """Connect to the live project DB (read-only)."""
    db_path: Path = _find_project_db()
    if not db_path.exists():
        pytest.skip(f"Live DB not found at {db_path}")
    conn: sqlite3.Connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# 1. Vault already exists
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("CI") == "true",
    reason="Obsidian vault only exists in local dev environment",
)
def test_obsidian_vault_exists() -> None:
    """The agentmemory project root has .obsidian/ -- it is already a vault."""
    vault_marker: Path = Path("/home/user/projects/agentmemory/.obsidian")
    assert vault_marker.is_dir(), ".obsidian/ directory missing at project root"


# ---------------------------------------------------------------------------
# 2. Belief IDs are filesystem-safe
# ---------------------------------------------------------------------------


def test_belief_ids_are_hex(live_conn: sqlite3.Connection) -> None:
    """All active belief IDs are 12-char hex strings (safe as filenames)."""
    rows: list[sqlite3.Row] = live_conn.execute(
        "SELECT id FROM beliefs WHERE valid_to IS NULL"
    ).fetchall()
    assert len(rows) > 0, "No active beliefs found"
    hex_pattern: re.Pattern[str] = re.compile(r"^[0-9a-f]{12}$")
    bad_ids: list[str] = [r["id"] for r in rows if not hex_pattern.match(r["id"])]
    assert len(bad_ids) == 0, f"Found {len(bad_ids)} non-hex IDs: {bad_ids[:5]}"


# ---------------------------------------------------------------------------
# 3. Content hashes exist and are populated
# ---------------------------------------------------------------------------


def test_content_hashes_populated(live_conn: sqlite3.Connection) -> None:
    """Every active belief has a non-empty content_hash."""
    rows: list[sqlite3.Row] = live_conn.execute(
        "SELECT COUNT(*) AS cnt FROM beliefs "
        "WHERE valid_to IS NULL AND (content_hash IS NULL OR content_hash = '')"
    ).fetchall()
    assert rows[0]["cnt"] == 0, f"{rows[0]['cnt']} beliefs have empty content_hash"


# ---------------------------------------------------------------------------
# 4. Active belief count is in expected range
# ---------------------------------------------------------------------------


def test_active_belief_count(live_conn: sqlite3.Connection) -> None:
    """We expect 10K+ active beliefs based on prior observation (16,810)."""
    count: int = live_conn.execute(
        "SELECT COUNT(*) FROM beliefs WHERE valid_to IS NULL"
    ).fetchone()[0]
    assert count > 10000, f"Only {count} active beliefs, expected 10K+"


# ---------------------------------------------------------------------------
# 5. Edges reference valid belief IDs
# ---------------------------------------------------------------------------


def test_edges_reference_valid_beliefs(live_conn: sqlite3.Connection) -> None:
    """Edge from_id and to_id should point to existing beliefs (not dangling)."""
    dangling: list[sqlite3.Row] = live_conn.execute(
        "SELECT e.id, e.from_id, e.to_id FROM edges e "
        "LEFT JOIN beliefs b1 ON e.from_id = b1.id "
        "LEFT JOIN beliefs b2 ON e.to_id = b2.id "
        "WHERE b1.id IS NULL OR b2.id IS NULL "
        "LIMIT 10"
    ).fetchall()
    assert len(dangling) == 0, (
        f"Found {len(dangling)} edges with dangling references: "
        f"{[(r['id'], r['from_id'], r['to_id']) for r in dangling]}"
    )


# ---------------------------------------------------------------------------
# 6. YAML frontmatter roundtrip (format correctness)
# ---------------------------------------------------------------------------


def test_yaml_frontmatter_format() -> None:
    """A simple frontmatter block can be written and parsed back."""
    frontmatter: str = (
        "---\n"
        "id: a1b2c3d4e5f6\n"
        "type: factual\n"
        "confidence: 0.75\n"
        'content_hash: "f7a8b9c0d1e2"\n'
        "locked: false\n"
        "tags:\n"
        "  - belief/factual\n"
        "---\n"
    )
    # Parse it back with regex
    match: re.Match[str] | None = re.match(
        r"^---\n(.*?)\n---\n", frontmatter, re.DOTALL
    )
    assert match is not None, "Frontmatter block not parseable"
    body: str = match.group(1)
    # Extract key-value pairs
    pairs: dict[str, str] = {}
    for line in body.split("\n"):
        if ":" in line and not line.startswith("  "):
            key, _, val = line.partition(":")
            pairs[key.strip()] = val.strip().strip('"')
    assert pairs["id"] == "a1b2c3d4e5f6"
    assert pairs["content_hash"] == "f7a8b9c0d1e2"
    assert pairs["type"] == "factual"


# ---------------------------------------------------------------------------
# 7. Atomic rename works on this OS
# ---------------------------------------------------------------------------


def test_atomic_rename() -> None:
    """os.rename is atomic on macOS/Linux (POSIX guarantee)."""
    with tempfile.TemporaryDirectory() as tmp:
        src: Path = Path(tmp) / "tmp_write.md"
        dst: Path = Path(tmp) / "final.md"
        src.write_text("test content", encoding="utf-8")
        os.rename(src, dst)
        assert dst.exists()
        assert not src.exists()
        assert dst.read_text(encoding="utf-8") == "test content"


# ---------------------------------------------------------------------------
# 8. Belief types match expected set
# ---------------------------------------------------------------------------


def test_belief_types_known(live_conn: sqlite3.Connection) -> None:
    """All active belief types are in our known set."""
    known_types: set[str] = {
        "factual",
        "preference",
        "relational",
        "procedural",
        "causal",
        "correction",
        "requirement",
        "speculative",
    }
    rows: list[sqlite3.Row] = live_conn.execute(
        "SELECT DISTINCT belief_type FROM beliefs WHERE valid_to IS NULL"
    ).fetchall()
    actual_types: set[str] = {r["belief_type"] for r in rows}
    unknown: set[str] = actual_types - known_types
    assert len(unknown) == 0, f"Unknown belief types: {unknown}"


# ---------------------------------------------------------------------------
# 9. Edge types match expected set
# ---------------------------------------------------------------------------


def test_edge_types_known(live_conn: sqlite3.Connection) -> None:
    """All edge types are in our known set."""
    known_types: set[str] = {
        "CITES",
        "RELATES_TO",
        "SUPERSEDES",
        "CONTRADICTS",
        "SUPPORTS",
        "TESTS",
        "IMPLEMENTS",
        "TEMPORAL_NEXT",
        "SPECULATES",
        "DEPENDS_ON",
        "RESOLVES",
        "HIBERNATED",
    }
    rows: list[sqlite3.Row] = live_conn.execute(
        "SELECT DISTINCT edge_type FROM edges"
    ).fetchall()
    actual_types: set[str] = {r["edge_type"] for r in rows}
    unknown: set[str] = actual_types - known_types
    assert len(unknown) == 0, f"Unknown edge types: {unknown}"


# ---------------------------------------------------------------------------
# 10. Bulk query performance is acceptable
# ---------------------------------------------------------------------------


def test_bulk_query_performance(live_conn: sqlite3.Connection) -> None:
    """Fetching all active beliefs completes in under 2 seconds."""
    import time

    start: float = time.monotonic()
    rows: list[sqlite3.Row] = live_conn.execute(
        "SELECT * FROM beliefs WHERE valid_to IS NULL"
    ).fetchall()
    elapsed: float = time.monotonic() - start
    assert elapsed < 2.0, f"Bulk query took {elapsed:.2f}s (expected <2s)"
    assert len(rows) > 10000
