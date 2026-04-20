"""Cross-project shared scope management via SQLite ATTACH.

Provides infrastructure for sharing beliefs across project boundaries
without data duplication. Each scope is a separate SQLite database under
~/.agentmemory/shared/{scope_name}/memory.db.

Architecture (Exp 97/98):
  - Persistent ATTACH has ~1x latency overhead (no cost)
  - Budget: 12 local / 3 per shared scope (Config B)
  - FTS5 MATCH requires unqualified table name in WHERE clause
  - Shared results never displace local content from top-5 positions
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, cast

_AGENTMEMORY_HOME: Final[Path] = Path.home() / ".agentmemory"
_SHARED_DIR: Final[Path] = _AGENTMEMORY_HOME / "shared"
_SCOPES_CONFIG: Final[Path] = _AGENTMEMORY_HOME / "scopes.json"

# Budget per shared scope (Exp 98 Config B: 12 local + 3 shared)
SHARED_BUDGET_PER_SCOPE: Final[int] = 3

# Schema for shared scope databases (minimal: beliefs + FTS5)
_SHARED_SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS beliefs (
    id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    content TEXT NOT NULL,
    belief_type TEXT NOT NULL,
    alpha REAL NOT NULL DEFAULT 0.5,
    beta_param REAL NOT NULL DEFAULT 0.5,
    confidence REAL GENERATED ALWAYS AS (alpha / (alpha + beta_param)) STORED,
    source_type TEXT NOT NULL,
    locked INTEGER NOT NULL DEFAULT 0,
    valid_from TEXT,
    valid_to TEXT,
    superseded_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'global',
    origin_project TEXT NOT NULL DEFAULT '',
    origin_belief_id TEXT NOT NULL DEFAULT ''
);

CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    id,
    content,
    type,
    tokenize='porter'
);

CREATE TABLE IF NOT EXISTS scope_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _content_hash(content: str) -> str:
    """Compute 12-char content hash for dedup."""
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def get_scopes_config() -> dict[str, list[str]]:
    """Load scopes.json: maps scope names to subscribing project paths.

    Returns empty dict if config doesn't exist (backwards compatible).
    Format: {"infra": ["/path/to/project-a", "/path/to/project-b"], ...}
    """
    if not _SCOPES_CONFIG.exists():
        return {}
    try:
        raw: object = json.loads(_SCOPES_CONFIG.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        typed: dict[str, Any] = cast(dict[str, Any], raw)
        result: dict[str, list[str]] = {}
        for k, v in typed.items():
            if isinstance(v, list):
                result[k] = [str(item) for item in cast(list[Any], v)]
        return result
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_scopes_config(config: dict[str, list[str]]) -> None:
    """Persist scopes config to disk."""
    _SCOPES_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    _SCOPES_CONFIG.write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )


def get_scope_db_path(scope_name: str) -> Path:
    """Return the DB path for a named shared scope."""
    return _SHARED_DIR / scope_name / "memory.db"


def ensure_scope_db(scope_name: str) -> Path:
    """Create shared scope DB if it doesn't exist. Returns path."""
    db_path: Path = get_scope_db_path(scope_name)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        conn: sqlite3.Connection = sqlite3.connect(str(db_path))
        conn.executescript(_SHARED_SCHEMA)
        conn.execute(
            "INSERT OR REPLACE INTO scope_meta (key, value) VALUES (?, ?)",
            ("created_at", datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            "INSERT OR REPLACE INTO scope_meta (key, value) VALUES (?, ?)",
            ("scope_name", scope_name),
        )
        conn.commit()
        conn.close()
    return db_path


def list_scopes() -> list[str]:
    """Return names of all existing shared scope databases."""
    if not _SHARED_DIR.exists():
        return []
    return sorted(
        d.name
        for d in _SHARED_DIR.iterdir()
        if d.is_dir() and (d / "memory.db").exists()
    )


def get_scopes_for_project(project_path: str) -> list[str]:
    """Return scope names that include the given project path."""
    config: dict[str, list[str]] = get_scopes_config()
    resolved: str = str(Path(project_path).resolve())
    return [
        scope
        for scope, projects in config.items()
        if resolved in [str(Path(p).resolve()) for p in projects]
    ]


def share_belief(
    scope_name: str,
    belief_id: str,
    content: str,
    belief_type: str,
    source_type: str,
    alpha: float,
    beta_param: float,
    locked: bool,
    origin_project: str,
) -> str:
    """Copy a belief into a shared scope database.

    Returns the ID of the belief in the shared scope (same as original).
    Deduplicates by content_hash -- won't create duplicates.
    """
    db_path: Path = ensure_scope_db(scope_name)
    conn: sqlite3.Connection = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    content_hash: str = _content_hash(content)
    now_str: str = datetime.now(timezone.utc).isoformat()

    # Check for existing belief with same content
    existing: sqlite3.Row | None = conn.execute(
        "SELECT id FROM beliefs WHERE content_hash = ? AND valid_to IS NULL",
        (content_hash,),
    ).fetchone()

    if existing is not None:
        conn.close()
        return str(existing["id"])

    # Insert belief
    conn.execute(
        "INSERT INTO beliefs (id, content_hash, content, belief_type, "
        "alpha, beta_param, source_type, locked, created_at, updated_at, "
        "scope, origin_project, origin_belief_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            belief_id,
            content_hash,
            content,
            belief_type,
            alpha,
            beta_param,
            source_type,
            int(locked),
            now_str,
            now_str,
            "global",
            origin_project,
            belief_id,
        ),
    )
    # Index in FTS5
    conn.execute(
        "INSERT INTO search_index (id, content, type) VALUES (?, ?, ?)",
        (belief_id, content, "belief"),
    )
    conn.commit()
    conn.close()
    return belief_id


def unshare_belief(scope_name: str, belief_id: str) -> bool:
    """Remove a belief from a shared scope. Returns True if found."""
    db_path: Path = get_scope_db_path(scope_name)
    if not db_path.exists():
        return False
    conn: sqlite3.Connection = sqlite3.connect(str(db_path))
    cursor: sqlite3.Cursor = conn.execute(
        "DELETE FROM beliefs WHERE id = ?", (belief_id,)
    )
    if cursor.rowcount > 0:
        conn.execute("DELETE FROM search_index WHERE id = ?", (belief_id,))
    conn.commit()
    removed: bool = cursor.rowcount > 0
    conn.close()
    return removed


def search_shared_scopes(
    scopes: list[str],
    fts_query: str,
    budget_per_scope: int = SHARED_BUDGET_PER_SCOPE,
) -> list[tuple[str, str, str, float]]:
    """Search across shared scope databases using FTS5.

    Returns list of (scope_name, belief_id, content, bm25_score).
    Each scope is queried independently with its own budget limit.

    Uses direct sqlite3 connections (not ATTACH) for simplicity in
    the standalone search path. The ATTACH approach is used in the
    hook path where a connection already exists.
    """
    results: list[tuple[str, str, str, float]] = []
    for scope in scopes:
        db_path: Path = get_scope_db_path(scope)
        if not db_path.exists():
            continue
        try:
            conn: sqlite3.Connection = sqlite3.connect(
                f"file:{db_path}?mode=ro", uri=True
            )
            conn.row_factory = sqlite3.Row
            rows: list[sqlite3.Row] = conn.execute(
                "SELECT id, content, bm25(search_index) AS score "
                "FROM search_index WHERE search_index MATCH ? AND type = 'belief' "
                "ORDER BY bm25(search_index) LIMIT ?",
                (fts_query, budget_per_scope),
            ).fetchall()
            for r in rows:
                results.append((scope, str(r["id"]), str(r["content"]), float(r["score"])))
            conn.close()
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            continue
    return results


def attach_shared_scopes(
    conn: sqlite3.Connection,
    scopes: list[str],
) -> list[str]:
    """ATTACH shared scope databases to an existing connection.

    Returns list of schema aliases (e.g., ["shared_infra", "shared_deploy"]).
    Caller must DETACH when done.
    """
    attached: list[str] = []
    for scope in scopes:
        db_path: Path = get_scope_db_path(scope)
        if not db_path.exists():
            continue
        alias: str = f"shared_{scope}"
        try:
            conn.execute(
                f"ATTACH DATABASE ? AS {alias}", (str(db_path),)
            )
            attached.append(alias)
        except sqlite3.OperationalError:
            continue
    return attached


def detach_shared_scopes(
    conn: sqlite3.Connection,
    aliases: list[str],
) -> None:
    """DETACH previously attached shared scope databases."""
    for alias in aliases:
        try:
            conn.execute(f"DETACH DATABASE {alias}")
        except sqlite3.OperationalError:
            continue


def search_attached_scope(
    conn: sqlite3.Connection,
    alias: str,
    fts_query: str,
    limit: int = SHARED_BUDGET_PER_SCOPE,
) -> list[tuple[str, str, float]]:
    """Query FTS5 in an attached shared scope database.

    Returns list of (belief_id, content, bm25_score).
    Uses unqualified table name in MATCH (SQLite FTS5 requirement).
    """
    try:
        rows: list[tuple[str, str, float]] = conn.execute(
            f"SELECT id, content, bm25(search_index) AS score "
            f"FROM {alias}.search_index "
            f"WHERE search_index MATCH ? AND type = 'belief' "
            f"ORDER BY bm25(search_index) LIMIT ?",
            (fts_query, limit),
        ).fetchall()
        return [(str(r[0]), str(r[1]), float(r[2])) for r in rows]
    except sqlite3.OperationalError:
        return []


def subscribe_project(scope_name: str, project_path: str) -> None:
    """Subscribe a project to a shared scope."""
    config: dict[str, list[str]] = get_scopes_config()
    resolved: str = str(Path(project_path).resolve())
    if scope_name not in config:
        config[scope_name] = []
    if resolved not in config[scope_name]:
        config[scope_name].append(resolved)
    save_scopes_config(config)


def unsubscribe_project(scope_name: str, project_path: str) -> None:
    """Unsubscribe a project from a shared scope."""
    config: dict[str, list[str]] = get_scopes_config()
    resolved: str = str(Path(project_path).resolve())
    if scope_name in config and resolved in config[scope_name]:
        config[scope_name].remove(resolved)
        if not config[scope_name]:
            del config[scope_name]
    save_scopes_config(config)
