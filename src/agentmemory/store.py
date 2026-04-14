"""MemoryStore: SQLite-backed persistent memory for AI coding agents.

WAL mode, FTS5 full-text search, Bayesian belief confidence, session recovery.
All writes are synchronous and durable before return.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from agentmemory.models import (
    Belief,
    Checkpoint,
    Edge,
    Evidence,
    Observation,
    Session,
    TestResult,
)

_SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    model TEXT,
    project_context TEXT,
    summary TEXT,
    retrieval_tokens INTEGER NOT NULL DEFAULT 0,
    classification_tokens INTEGER NOT NULL DEFAULT 0,
    beliefs_created INTEGER NOT NULL DEFAULT 0,
    corrections_detected INTEGER NOT NULL DEFAULT 0,
    searches_performed INTEGER NOT NULL DEFAULT 0,
    feedback_given INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    content TEXT NOT NULL,
    observation_type TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL DEFAULT '',
    source_path TEXT NOT NULL DEFAULT '',
    session_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

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
    FOREIGN KEY (superseded_by) REFERENCES beliefs(id)
);

CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    belief_id TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    source_weight REAL NOT NULL DEFAULT 1.0,
    relationship TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (belief_id) REFERENCES beliefs(id),
    FOREIGN KEY (observation_id) REFERENCES observations(id)
);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (from_id) REFERENCES beliefs(id),
    FOREIGN KEY (to_id) REFERENCES beliefs(id)
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    checkpoint_type TEXT NOT NULL,
    content TEXT NOT NULL,
    "references" TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    belief_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    retrieval_context TEXT,
    outcome TEXT NOT NULL,
    outcome_detail TEXT,
    detection_layer TEXT NOT NULL,
    evidence_weight REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (belief_id) REFERENCES beliefs(id),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation TEXT NOT NULL,
    target_table TEXT NOT NULL,
    target_id TEXT NOT NULL,
    agent_id TEXT,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS confidence_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    belief_id TEXT NOT NULL,
    alpha REAL NOT NULL,
    beta_param REAL NOT NULL,
    event_type TEXT NOT NULL,
    event_detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (belief_id) REFERENCES beliefs(id)
);

CREATE INDEX IF NOT EXISTS idx_confhist_belief ON confidence_history(belief_id);
CREATE INDEX IF NOT EXISTS idx_confhist_time ON confidence_history(created_at);

CREATE TABLE IF NOT EXISTS onboarding_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_path TEXT NOT NULL,
    commit_hash TEXT,
    nodes_extracted INTEGER NOT NULL DEFAULT 0,
    edges_extracted INTEGER NOT NULL DEFAULT 0,
    beliefs_created INTEGER NOT NULL DEFAULT 0,
    observations_created INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_graph_edges_from ON graph_edges(from_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_to ON graph_edges(to_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_type ON graph_edges(edge_type);

CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    id,
    content,
    type,
    tokenize='porter'
);

CREATE INDEX IF NOT EXISTS idx_beliefs_content_hash ON beliefs(content_hash);
CREATE INDEX IF NOT EXISTS idx_observations_content_hash ON observations(content_hash);
CREATE INDEX IF NOT EXISTS idx_beliefs_valid_to ON beliefs(valid_to);
CREATE INDEX IF NOT EXISTS idx_beliefs_locked ON beliefs(locked);
CREATE INDEX IF NOT EXISTS idx_beliefs_created_at ON beliefs(created_at);
CREATE INDEX IF NOT EXISTS idx_beliefs_temporal ON beliefs(created_at, valid_to);
CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints(session_id);
CREATE INDEX IF NOT EXISTS idx_evidence_belief ON evidence(belief_id);
CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_id);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_id);

CREATE TABLE IF NOT EXISTS pending_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    belief_id TEXT NOT NULL,
    belief_content TEXT NOT NULL,
    session_id TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pending_feedback_session ON pending_feedback(session_id);
"""


def _new_id() -> str:
    """Generate a short readable ID: 12-char UUID hex."""
    return uuid.uuid4().hex[:12]


def _content_hash(content: str) -> str:
    """SHA-256 of content, truncated to 12 hex chars for dedup key."""
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def _now() -> str:
    """Current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _row_to_observation(row: sqlite3.Row) -> Observation:
    keys: list[str] = list(row.keys())
    return Observation(
        id=row["id"],
        content_hash=row["content_hash"],
        content=row["content"],
        observation_type=row["observation_type"],
        source_type=row["source_type"],
        source_id=row["source_id"],
        source_path=row["source_path"] if "source_path" in keys else "",
        session_id=row["session_id"],
        created_at=row["created_at"],
    )


def _row_to_belief(row: sqlite3.Row) -> Belief:
    keys: list[str] = list(row.keys())
    return Belief(
        id=row["id"],
        content_hash=row["content_hash"],
        content=row["content"],
        belief_type=row["belief_type"],
        alpha=row["alpha"],
        beta_param=row["beta_param"],
        confidence=row["confidence"],
        source_type=row["source_type"],
        locked=bool(row["locked"]),
        valid_from=row["valid_from"],
        valid_to=row["valid_to"],
        superseded_by=row["superseded_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        event_time=row["event_time"] if "event_time" in keys else None,
        session_id=row["session_id"] if "session_id" in keys else None,
        classified_by=row["classified_by"] if "classified_by" in keys else "offline",
        rigor_tier=row["rigor_tier"] if "rigor_tier" in keys else "hypothesis",
        method=row["method"] if "method" in keys else None,
        sample_size=row["sample_size"] if "sample_size" in keys else None,
        scope=row["scope"] if "scope" in keys else "project",
        last_retrieved_at=row["last_retrieved_at"] if "last_retrieved_at" in keys else None,
    )


def _row_to_session(row: sqlite3.Row) -> Session:
    keys: list[str] = list(row.keys())
    return Session(
        id=row["id"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        model=row["model"],
        project_context=row["project_context"],
        summary=row["summary"],
        retrieval_tokens=int(row["retrieval_tokens"]) if "retrieval_tokens" in keys else 0,
        classification_tokens=int(row["classification_tokens"]) if "classification_tokens" in keys else 0,
        beliefs_created=int(row["beliefs_created"]) if "beliefs_created" in keys else 0,
        corrections_detected=int(row["corrections_detected"]) if "corrections_detected" in keys else 0,
        searches_performed=int(row["searches_performed"]) if "searches_performed" in keys else 0,
        feedback_given=int(row["feedback_given"]) if "feedback_given" in keys else 0,
        velocity_items_per_hour=float(row["velocity_items_per_hour"]) if "velocity_items_per_hour" in keys and row["velocity_items_per_hour"] is not None else None,
        velocity_tier=row["velocity_tier"] if "velocity_tier" in keys else None,
        topics_json=row["topics_json"] if "topics_json" in keys else None,
    )


def _row_to_checkpoint(row: sqlite3.Row) -> Checkpoint:
    return Checkpoint(
        id=row["id"],
        session_id=row["session_id"],
        checkpoint_type=row["checkpoint_type"],
        content=row["content"],
        references=row["references"],
        created_at=row["created_at"],
    )


class MemoryStore:
    """SQLite-backed memory store with FTS5 search and Bayesian belief tracking."""

    def __init__(self, db_path: str | Path) -> None:
        """Open or create the database. Enable WAL mode. Create tables if needed."""
        self._db_path: Path = Path(db_path)
        self._conn: sqlite3.Connection = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        """Create all tables and FTS5 index if they don't exist."""
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._migrate_sessions()
        self._migrate_beliefs()

    def _migrate_beliefs(self) -> None:
        """Run belief-table migrations."""
        # NOTE: backfill_lock_corrections() was removed. The system must not
        # auto-lock beliefs. Only explicit user confirmation via lock() is
        # allowed to set locked=True.
        cols: list[sqlite3.Row] = self._conn.execute(
            "PRAGMA table_info(beliefs)"
        ).fetchall()
        col_names: set[str] = {row["name"] for row in cols}
        # Wave 1B: bitemporal event_time (when fact occurred vs when ingested)
        if "event_time" not in col_names:
            self._conn.execute(
                "ALTER TABLE beliefs ADD COLUMN event_time TEXT"
            )
        # Wave 1B: session_id for session replay queries
        if "session_id" not in col_names:
            self._conn.execute(
                "ALTER TABLE beliefs ADD COLUMN session_id TEXT"
            )
        # Track which classifier produced this belief ("offline" or "llm").
        if "classified_by" not in col_names:
            self._conn.execute(
                "ALTER TABLE beliefs ADD COLUMN classified_by TEXT NOT NULL DEFAULT 'offline'"
            )
        # REQ-025: rigor tier (hypothesis/simulated/empirically_tested/validated)
        if "rigor_tier" not in col_names:
            self._conn.execute(
                "ALTER TABLE beliefs ADD COLUMN rigor_tier TEXT NOT NULL DEFAULT 'hypothesis'"
            )
        # REQ-023: provenance metadata
        if "method" not in col_names:
            self._conn.execute(
                "ALTER TABLE beliefs ADD COLUMN method TEXT"
            )
        if "sample_size" not in col_names:
            self._conn.execute(
                "ALTER TABLE beliefs ADD COLUMN sample_size INTEGER"
            )
        # Cross-project scope: "project" (default) or "global"
        if "scope" not in col_names:
            self._conn.execute(
                "ALTER TABLE beliefs ADD COLUMN scope TEXT NOT NULL DEFAULT 'project'"
            )
        # Track when a belief was last retrieved
        if "last_retrieved_at" not in col_names:
            self._conn.execute(
                "ALTER TABLE beliefs ADD COLUMN last_retrieved_at TEXT"
            )
        self._conn.commit()
        # Create index on session_id (safe to run even if already exists)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_beliefs_session_id ON beliefs(session_id)"
        )
        self._conn.commit()
        self._migrate_observations()

    def _migrate_observations(self) -> None:
        """Add source_path column to observations if missing (existing DBs)."""
        cols: list[sqlite3.Row] = self._conn.execute(
            "PRAGMA table_info(observations)"
        ).fetchall()
        col_names: set[str] = {row["name"] for row in cols}
        if "source_path" not in col_names:
            self._conn.execute(
                "ALTER TABLE observations ADD COLUMN source_path TEXT NOT NULL DEFAULT ''"
            )
            self._conn.commit()

    def backfill_lock_corrections(self) -> int:
        """Lock all correction-type beliefs that are currently unlocked.
        Returns the number of beliefs locked."""
        cursor: sqlite3.Cursor = self._conn.execute(
            "UPDATE beliefs SET locked = 1 WHERE belief_type = 'correction' AND locked = 0"
        )
        self._conn.commit()
        return cursor.rowcount

    def _migrate_sessions(self) -> None:
        """Add token tracking and velocity columns to sessions if missing."""
        cols: list[sqlite3.Row] = self._conn.execute(
            "PRAGMA table_info(sessions)"
        ).fetchall()
        col_names: set[str] = {row["name"] for row in cols}
        new_cols: list[str] = [
            "retrieval_tokens", "classification_tokens",
            "beliefs_created", "corrections_detected", "searches_performed",
            "feedback_given",
        ]
        for col in new_cols:
            if col not in col_names:
                self._conn.execute(
                    f"ALTER TABLE sessions ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0"
                )
        # Velocity tracking columns (Wave 1D)
        if "velocity_items_per_hour" not in col_names:
            self._conn.execute(
                "ALTER TABLE sessions ADD COLUMN velocity_items_per_hour REAL"
            )
        if "velocity_tier" not in col_names:
            self._conn.execute(
                "ALTER TABLE sessions ADD COLUMN velocity_tier TEXT"
            )
        if "topics_json" not in col_names:
            self._conn.execute(
                "ALTER TABLE sessions ADD COLUMN topics_json TEXT"
            )
        self._conn.commit()

    # --- Observations (immutable) ---

    def insert_observation(
        self,
        content: str,
        observation_type: str,
        source_type: str,
        source_id: str = "",
        source_path: str = "",
        session_id: str | None = None,
    ) -> Observation:
        """Insert an observation. Content-hash dedup: if same hash exists, return existing.

        Args:
            source_id: Unique identifier for the source -- a file path, commit SHA,
                turn ID, or document hash. Must NOT be the source type string
                (use source_type for that). Empty string means unknown provenance.
        """
        ch: str = _content_hash(content)
        existing: sqlite3.Row | None = self._conn.execute(
            "SELECT * FROM observations WHERE content_hash = ?", (ch,)
        ).fetchone()
        if existing is not None:
            return _row_to_observation(existing)

        obs_id: str = _new_id()
        ts: str = _now()
        self._conn.execute(
            """INSERT INTO observations
               (id, content_hash, content, observation_type, source_type, source_id, source_path, session_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (obs_id, ch, content, observation_type, source_type, source_id, source_path, session_id, ts),
        )
        self._conn.execute(
            "INSERT INTO search_index(id, content, type) VALUES (?, ?, ?)",
            (obs_id, content, "observation"),
        )
        self._conn.commit()
        return Observation(
            id=obs_id,
            content_hash=ch,
            content=content,
            observation_type=observation_type,
            source_type=source_type,
            source_id=source_id,
            source_path=source_path,
            session_id=session_id,
            created_at=ts,
        )

    # --- Beliefs ---

    def insert_belief(
        self,
        content: str,
        belief_type: str,
        source_type: str,
        alpha: float = 0.5,
        beta_param: float = 0.5,
        locked: bool = False,
        observation_id: str | None = None,
        created_at: str | None = None,
        event_time: str | None = None,
        session_id: str | None = None,
        classified_by: str = "offline",
        rigor_tier: str = "hypothesis",
        method: str | None = None,
        sample_size: int | None = None,
    ) -> Belief:
        """Insert a belief with optional evidence link. Content-hash dedup.

        Also inserts into FTS5 search_index. If the same content hash already
        exists, returns the existing belief without modification.

        If created_at is provided, uses that timestamp instead of now().
        This enables source-truth dating (e.g., git commit dates).

        event_time is the bitemporal "when the fact occurred" timestamp,
        distinct from created_at (when the system ingested it).
        session_id links the belief to the session that created it.
        """
        ch: str = _content_hash(content)
        existing: sqlite3.Row | None = self._conn.execute(
            "SELECT * FROM beliefs WHERE content_hash = ?", (ch,)
        ).fetchone()
        if existing is not None:
            return _row_to_belief(existing)

        belief_id: str = _new_id()
        ts: str = created_at if created_at is not None else _now()
        confidence: float = alpha / (alpha + beta_param)
        locked_int: int = 1 if locked else 0

        self._conn.execute(
            """INSERT INTO beliefs
               (id, content_hash, content, belief_type, alpha, beta_param,
                source_type, locked, valid_from, valid_to, superseded_by,
                created_at, updated_at, event_time, session_id, classified_by,
                rigor_tier, method, sample_size)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (belief_id, ch, content, belief_type, alpha, beta_param,
             source_type, locked_int, ts, ts, event_time, session_id, classified_by,
             rigor_tier, method, sample_size),
        )
        self._conn.execute(
            "INSERT INTO search_index(id, content, type) VALUES (?, ?, ?)",
            (belief_id, content, "belief"),
        )

        if observation_id is not None:
            ev_ts: str = _now()
            # Determine source_weight from source_type
            weight: float = 1.0 if source_type in ("user_stated", "user_corrected") else 0.5
            self._conn.execute(
                """INSERT INTO evidence
                   (belief_id, observation_id, source_weight, relationship, created_at)
                   VALUES (?, ?, ?, 'supports', ?)""",
                (belief_id, observation_id, weight, ev_ts),
            )

        self._conn.commit()
        return Belief(
            id=belief_id,
            content_hash=ch,
            content=content,
            belief_type=belief_type,
            alpha=alpha,
            beta_param=beta_param,
            confidence=confidence,
            source_type=source_type,
            locked=locked,
            valid_from=None,
            valid_to=None,
            superseded_by=None,
            created_at=ts,
            updated_at=ts,
            event_time=event_time,
            session_id=session_id,
            classified_by=classified_by,
            rigor_tier=rigor_tier,
            method=method,
            sample_size=sample_size,
        )

    def lock_belief(self, belief_id: str) -> None:
        """Mark a belief as locked. Locked beliefs cannot have confidence reduced."""
        ts: str = _now()
        self._conn.execute(
            "UPDATE beliefs SET locked = 1, updated_at = ? WHERE id = ?",
            (ts, belief_id),
        )
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT alpha, beta_param FROM beliefs WHERE id = ?", (belief_id,)
        ).fetchone()
        if row is not None:
            self._record_confidence(belief_id, row["alpha"], row["beta_param"], "locked")
        self._conn.commit()

    def delete_belief(self, belief_id: str) -> bool:
        """Soft-delete a belief by setting valid_to = now.

        Returns True if the belief existed and was deleted, False if not found
        or already deleted.
        """
        ts: str = _now()
        cursor: sqlite3.Cursor = self._conn.execute(
            "UPDATE beliefs SET valid_to = ?, updated_at = ? "
            "WHERE id = ? AND valid_to IS NULL",
            (ts, ts, belief_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def bulk_delete_beliefs(self, belief_ids: list[str]) -> int:
        """Soft-delete multiple beliefs. Returns number actually deleted."""
        ts: str = _now()
        deleted: int = 0
        for belief_id in belief_ids:
            cursor: sqlite3.Cursor = self._conn.execute(
                "UPDATE beliefs SET valid_to = ?, updated_at = ? "
                "WHERE id = ? AND valid_to IS NULL",
                (ts, ts, belief_id),
            )
            deleted += cursor.rowcount
        self._conn.commit()
        return deleted

    def supersede_belief(self, old_id: str, new_id: str, reason: str) -> None:
        """Mark old belief as superseded. Sets valid_to, creates a SUPERSEDES edge.

        Locked beliefs cannot be superseded -- they are authoritative (REQ-020).
        """
        old_row: sqlite3.Row | None = self._conn.execute(
            "SELECT locked FROM beliefs WHERE id = ?", (old_id,)
        ).fetchone()
        if old_row is not None and bool(old_row["locked"]):
            return  # Locked beliefs are immune to supersession.

        ts: str = _now()
        self._conn.execute(
            "UPDATE beliefs SET valid_to = ?, superseded_by = ?, updated_at = ? WHERE id = ?",
            (ts, new_id, ts, old_id),
        )
        self._conn.execute(
            """INSERT INTO edges (from_id, to_id, edge_type, weight, reason, created_at)
               VALUES (?, ?, 'SUPERSEDES', 1.0, ?, ?)""",
            (new_id, old_id, reason, ts),
        )
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT alpha, beta_param FROM beliefs WHERE id = ?", (old_id,)
        ).fetchone()
        if row is not None:
            self._record_confidence(old_id, row["alpha"], row["beta_param"], "superseded", new_id)
        self._conn.commit()

    def _record_confidence(
        self, belief_id: str, alpha: float, beta_param: float,
        event_type: str, event_detail: str = "",
    ) -> None:
        """Append a snapshot to confidence_history for trajectory analysis."""
        ts: str = _now()
        self._conn.execute(
            """INSERT INTO confidence_history
               (belief_id, alpha, beta_param, event_type, event_detail, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (belief_id, alpha, beta_param, event_type, event_detail, ts),
        )

    def update_confidence(
        self, belief_id: str, outcome: str, weight: float = 1.0,
    ) -> bool:
        """Bayesian update: 'used' increments alpha, 'harmful' increments beta_param.

        Locked beliefs cannot have beta_param increased (confidence floor preserved).
        Returns True if the belief dropped below 0.5 confidence (TB-15 warning).
        """
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT alpha, beta_param, locked FROM beliefs WHERE id = ?",
            (belief_id,),
        ).fetchone()
        if row is None:
            return False

        old_alpha: float = row["alpha"]
        old_beta: float = row["beta_param"]
        alpha: float = old_alpha
        beta: float = old_beta
        is_locked: bool = bool(row["locked"])
        ts: str = _now()

        if outcome == "used":
            alpha += weight
        elif outcome == "harmful":
            if not is_locked:
                beta += weight
        # ignored and contradicted do not adjust parameters

        self._conn.execute(
            "UPDATE beliefs SET alpha = ?, beta_param = ?, updated_at = ? WHERE id = ?",
            (alpha, beta, ts, belief_id),
        )
        self._record_confidence(belief_id, alpha, beta, f"feedback_{outcome}")
        self._conn.commit()

        # TB-15: detect significant confidence drop
        old_conf: float = old_alpha / (old_alpha + old_beta) if (old_alpha + old_beta) > 0 else 0.5
        new_conf: float = alpha / (alpha + beta) if (alpha + beta) > 0 else 0.5
        return old_conf >= 0.5 and new_conf < 0.5

    def get_reclassifiable(self, limit: int = 200) -> list[dict[str, str]]:
        """Return unlocked, offline-classified beliefs eligible for LLM reclassification."""
        rows: list[dict[str, str]] = []
        cursor = self._conn.execute(
            """SELECT id, content, belief_type, source_type
               FROM beliefs
               WHERE locked = 0
                 AND superseded_by IS NULL
                 AND valid_to IS NULL
                 AND classified_by = 'offline'
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        )
        for row in cursor:
            rows.append({
                "id": row["id"],
                "content": row["content"],
                "type": row["belief_type"],
                "source": row["source_type"],
            })
        return rows

    def update_belief_classification(
        self,
        belief_id: str,
        belief_type: str,
        alpha: float,
        beta_param: float,
    ) -> None:
        """Update a belief's type and priors (for reclassification).

        Also sets classified_by='llm' to mark the belief as LLM-classified.
        """
        ts: str = _now()
        self._conn.execute(
            """UPDATE beliefs SET belief_type = ?, alpha = ?, beta_param = ?,
               classified_by = 'llm', updated_at = ? WHERE id = ?""",
            (belief_type, alpha, beta_param, ts, belief_id),
        )
        self._conn.commit()

    def soft_delete_belief(self, belief_id: str) -> None:
        """Soft-delete a belief by setting valid_to."""
        ts: str = _now()
        self._conn.execute(
            "UPDATE beliefs SET valid_to = ?, updated_at = ? WHERE id = ?",
            (ts, ts, belief_id),
        )
        self._conn.commit()

    # --- Edges ---

    def insert_edge(
        self,
        from_id: str,
        to_id: str,
        edge_type: str,
        weight: float = 1.0,
        reason: str = "",
    ) -> int:
        """Insert a directed edge between two beliefs. Returns the new edge row ID."""
        ts: str = _now()
        cursor: sqlite3.Cursor = self._conn.execute(
            """INSERT INTO edges (from_id, to_id, edge_type, weight, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (from_id, to_id, edge_type, weight, reason, ts),
        )
        self._conn.commit()
        row_id: int | None = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("Edge insert did not return a rowid")
        return row_id

    def get_neighbors(
        self,
        belief_id: str,
        edge_types: list[str] | None = None,
        direction: str = "both",
    ) -> list[tuple[Belief, Edge]]:
        """Get beliefs connected to belief_id via edges.

        Args:
            belief_id: The belief to find neighbors of.
            edge_types: If provided, only return edges of these types.
            direction: "outgoing" (from_id=belief_id), "incoming" (to_id=belief_id),
                       or "both".

        Returns list of (neighbor_belief, connecting_edge) pairs.
        Excludes superseded beliefs (valid_to IS NOT NULL).
        """
        results: list[tuple[Belief, Edge]] = []
        directions: list[tuple[str, str]] = []
        if direction in ("outgoing", "both"):
            directions.append(("from_id", "to_id"))
        if direction in ("incoming", "both"):
            directions.append(("to_id", "from_id"))

        for match_col, neighbor_col in directions:
            sql: str = (
                f"SELECT e.id AS eid, e.from_id, e.to_id, e.edge_type, "
                f"e.weight, e.reason, e.created_at AS ecreated, "
                f"b.* FROM edges e "
                f"JOIN beliefs b ON b.id = e.{neighbor_col} "
                f"WHERE e.{match_col} = ? AND b.valid_to IS NULL"
            )
            params: list[object] = [belief_id]
            if edge_types:
                placeholders: str = ", ".join("?" for _ in edge_types)
                sql += f" AND e.edge_type IN ({placeholders})"
                params.extend(edge_types)
            sql += " ORDER BY e.weight DESC, e.created_at ASC"

            rows: list[sqlite3.Row] = self._conn.execute(sql, tuple(params)).fetchall()
            for row in rows:
                belief: Belief = _row_to_belief(row)
                edge: Edge = Edge(
                    id=row["eid"],
                    from_id=row["from_id"],
                    to_id=row["to_id"],
                    edge_type=row["edge_type"],
                    weight=row["weight"],
                    reason=row["reason"],
                    created_at=row["ecreated"],
                )
                results.append((belief, edge))

        return results

    # Edge-type traversal weights for BFS expansion. Semantic edges are
    # preferred over structural edges during graph traversal. The stored
    # edge.weight is multiplied by this type weight to produce the
    # effective priority. Default for unlisted types is 0.5.
    _EDGE_TYPE_WEIGHTS: dict[str, float] = {
        # Semantic edges (high priority)
        "CONTRADICTS": 2.0,
        "SUPPORTS": 1.8,
        "IMPLEMENTS": 1.5,
        "TESTS": 1.5,
        "CALLS": 1.3,
        "CITES": 1.3,
        # Structural edges (lower priority)
        "CO_CHANGED": 0.8,
        "TEMPORAL_NEXT": 0.6,
        "COMMIT_TOUCHES": 0.4,
        "CONTAINS": 0.3,
        "SENTENCE_IN_FILE": 0.2,
        "WITHIN_SECTION": 0.2,
    }

    def expand_graph(
        self,
        seed_ids: list[str],
        depth: int = 2,
        edge_types: list[str] | None = None,
        max_nodes: int = 50,
    ) -> dict[str, list[tuple[Belief, str, int]]]:
        """BFS expansion from seed beliefs along edges.

        Args:
            seed_ids: Starting belief IDs.
            depth: Maximum number of hops (1, 2, or 3).
            edge_types: If provided, only traverse these edge types.
                        SUPERSEDES edges are always excluded.
            max_nodes: Cap on total expanded nodes to prevent blowup.

        Returns dict mapping belief_id to list of
        (neighbor_belief, edge_type, hop_distance) tuples.
        Deterministic: neighbors sorted by effective weight (edge weight *
        type weight) DESC, then created_at ASC.
        """
        from collections import deque

        # Exclude SUPERSEDES edges (point to dead beliefs)
        excluded: frozenset[str] = frozenset({"SUPERSEDES"})
        effective_types: list[str] | None = None
        if edge_types is not None:
            effective_types = [t for t in edge_types if t not in excluded]
        # When no explicit types, we filter SUPERSEDES in post-processing

        visited: set[str] = set(seed_ids)
        result: dict[str, list[tuple[Belief, str, int]]] = {}
        queue: deque[tuple[str, int]] = deque()

        for sid in seed_ids:
            queue.append((sid, 0))

        total_expanded: int = 0

        while queue and total_expanded < max_nodes:
            current_id, current_depth = queue.popleft()
            if current_depth >= depth:
                continue

            neighbors: list[tuple[Belief, Edge]] = self.get_neighbors(
                current_id,
                edge_types=effective_types,
                direction="both",
            )

            # Re-sort by effective weight: edge.weight * type_weight
            def _effective_weight(pair: tuple[Belief, Edge]) -> tuple[float, str]:
                _, e = pair
                type_w: float = self._EDGE_TYPE_WEIGHTS.get(e.edge_type, 0.5)
                # Negate for descending sort; created_at for deterministic tiebreak
                return (-e.weight * type_w, e.created_at)

            neighbors.sort(key=_effective_weight)

            for neighbor_belief, edge in neighbors:
                # Skip SUPERSEDES when no explicit type filter
                if edge_types is None and edge.edge_type in excluded:
                    continue

                if neighbor_belief.id in visited:
                    continue
                if total_expanded >= max_nodes:
                    break

                visited.add(neighbor_belief.id)
                hop: int = current_depth + 1

                if neighbor_belief.id not in result:
                    result[neighbor_belief.id] = []
                result[neighbor_belief.id].append(
                    (neighbor_belief, edge.edge_type, hop)
                )

                queue.append((neighbor_belief.id, hop))
                total_expanded += 1

        return result

    # --- HRR graph ---

    def insert_graph_edge(
        self,
        from_id: str,
        to_id: str,
        edge_type: str,
        weight: float = 1.0,
        reason: str = "",
    ) -> int:
        """Insert a structural graph edge (no FK constraints). For scanner/HRR use."""
        ts: str = _now()
        cursor: sqlite3.Cursor = self._conn.execute(
            """INSERT INTO graph_edges (from_id, to_id, edge_type, weight, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (from_id, to_id, edge_type, weight, reason, ts),
        )
        self._conn.commit()
        row_id: int | None = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("graph_edge insert did not return a rowid")
        return row_id

    def get_all_edge_triples(self) -> list[tuple[str, str, str]]:
        """Return all edges (belief + graph) as triples for HRR encoding."""
        triples: list[tuple[str, str, str]] = []
        # Belief edges (SUPERSEDES, etc.)
        rows: list[sqlite3.Row] = self._conn.execute(
            "SELECT from_id, to_id, edge_type FROM edges"
        ).fetchall()
        triples.extend((str(r["from_id"]), str(r["to_id"]), str(r["edge_type"])) for r in rows)
        # Graph edges (CITES, CALLS, CONTAINS, etc.)
        g_rows: list[sqlite3.Row] = self._conn.execute(
            "SELECT from_id, to_id, edge_type FROM graph_edges"
        ).fetchall()
        triples.extend((str(r["from_id"]), str(r["to_id"]), str(r["edge_type"])) for r in g_rows)
        return triples

    # --- Search ---

    @staticmethod
    def _sanitize_fts5_query(query: str) -> str:
        """Sanitize a query for FTS5 MATCH.

        FTS5 treats hyphens as NOT, quotes as phrase delimiters, etc.
        Split into words, quote each term, join with OR for broad matching.
        """
        import re
        # Strip FTS5 operators and punctuation, keep alphanumeric and spaces
        words: list[str] = re.findall(r"[a-zA-Z0-9]+", query)
        if not words:
            return '""'
        # Quote each term and join with OR for broad matching
        quoted: list[str] = [f'"{w}"' for w in words]
        return " OR ".join(quoted)

    def search(self, query: str, top_k: int = 30) -> list[Belief]:
        """FTS5 BM25 search on beliefs. Excludes superseded (valid_to IS NOT NULL)."""
        safe_query: str = self._sanitize_fts5_query(query)
        rows: list[sqlite3.Row] = self._conn.execute(
            """SELECT id, content, type, bm25(search_index) AS score
               FROM search_index
               WHERE search_index MATCH ? AND type = 'belief'
               ORDER BY bm25(search_index)
               LIMIT ?""",
            (safe_query, top_k),
        ).fetchall()

        if not rows:
            return []

        # Batch lookup: single query instead of N+1 individual fetches.
        ids: list[str] = [r["id"] for r in rows]
        placeholders: str = ",".join("?" for _ in ids)
        belief_rows: list[sqlite3.Row] = self._conn.execute(
            f"SELECT * FROM beliefs WHERE id IN ({placeholders}) AND valid_to IS NULL",
            ids,
        ).fetchall()

        # Preserve FTS5 BM25 rank order.
        by_id: dict[str, sqlite3.Row] = {r["id"]: r for r in belief_rows}
        beliefs: list[Belief] = []
        for r in rows:
            row: sqlite3.Row | None = by_id.get(r["id"])
            if row is not None:
                beliefs.append(_row_to_belief(row))

        # Update last_retrieved_at for all returned beliefs.
        if beliefs:
            now: str = _now()
            returned_ids: list[str] = [b.id for b in beliefs]
            ph: str = ",".join("?" for _ in returned_ids)
            self._conn.execute(
                f"UPDATE beliefs SET last_retrieved_at = ? WHERE id IN ({ph})",
                [now, *returned_ids],
            )
            self._conn.commit()

        return beliefs

    def search_observations(self, query: str, top_k: int = 15) -> list[Observation]:
        """FTS5 BM25 search on observations."""
        safe_query: str = self._sanitize_fts5_query(query)
        rows: list[sqlite3.Row] = self._conn.execute(
            """SELECT id, content, type, bm25(search_index) AS score
               FROM search_index
               WHERE search_index MATCH ? AND type = 'observation'
               ORDER BY bm25(search_index)
               LIMIT ?""",
            (safe_query, top_k),
        ).fetchall()

        observations: list[Observation] = []
        for r in rows:
            obs: sqlite3.Row | None = self._conn.execute(
                "SELECT * FROM observations WHERE id = ?",
                (r["id"],),
            ).fetchone()
            if obs is not None:
                observations.append(_row_to_observation(obs))
        return observations

    def get_observation(self, observation_id: str) -> Observation | None:
        """Get a single observation by ID."""
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT * FROM observations WHERE id = ?", (observation_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_observation(row)

    def get_locked_beliefs(self) -> list[Belief]:
        """Return all locked beliefs (for L0 context injection)."""
        rows: list[sqlite3.Row] = self._conn.execute(
            "SELECT * FROM beliefs WHERE locked = 1 AND valid_to IS NULL"
        ).fetchall()
        return [_row_to_belief(r) for r in rows]

    def get_behavioral_beliefs(self, limit: int = 10) -> list[Belief]:
        """Return high-confidence unlocked behavioral beliefs (L1 layer).

        Behavioral beliefs are procedural constraints that should be in context
        regardless of query. Identified by: source_type='directive', OR
        high-confidence requirement/procedural beliefs with behavioral keywords.
        Locked beliefs are already in L0; this returns unlocked ones.
        """
        rows: list[sqlite3.Row] = self._conn.execute(
            """SELECT * FROM beliefs
               WHERE locked = 0
                 AND valid_to IS NULL
                 AND superseded_by IS NULL
                 AND (
                   source_type = 'directive'
                   OR (
                     belief_type IN ('requirement', 'procedural')
                     AND confidence >= 0.8
                     AND (
                       content LIKE '%never %'
                       OR content LIKE '%always %'
                       OR content LIKE '%must not%'
                       OR content LIKE '%do not%'
                       OR content LIKE '%must %'
                     )
                   )
                 )
               ORDER BY confidence DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [_row_to_belief(r) for r in rows]

    def get_belief(self, belief_id: str) -> Belief | None:
        """Get a single belief by ID."""
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT * FROM beliefs WHERE id = ?", (belief_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_belief(row)

    def get_belief_by_hash(self, content_hash: str) -> Belief | None:
        """Get a belief by content hash. Used to bridge scanner node IDs to belief IDs."""
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT * FROM beliefs WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_belief(row)

    # --- Sessions ---

    def create_session(
        self,
        model: str | None = None,
        project_context: str | None = None,
    ) -> Session:
        """Create a new session. Incomplete predecessors are left for manual recovery."""
        session_id: str = _new_id()
        ts: str = _now()
        self._conn.execute(
            """INSERT INTO sessions (id, started_at, completed_at, model, project_context, summary)
               VALUES (?, ?, NULL, ?, ?, NULL)""",
            (session_id, ts, model, project_context),
        )
        self._conn.commit()
        return Session(
            id=session_id,
            started_at=ts,
            completed_at=None,
            model=model,
            project_context=project_context,
            summary=None,
        )

    def checkpoint(
        self,
        session_id: str,
        checkpoint_type: str,
        content: str,
        references: list[str] | None = None,
    ) -> Checkpoint:
        """Write a session checkpoint. Synchronous: committed before return."""
        refs_json: str = json.dumps(references if references is not None else [])
        ts: str = _now()
        cursor: sqlite3.Cursor = self._conn.execute(
            """INSERT INTO checkpoints (session_id, checkpoint_type, content, "references", created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, checkpoint_type, content, refs_json, ts),
        )
        self._conn.commit()
        row_id: int | None = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("Checkpoint insert did not return a rowid")
        return Checkpoint(
            id=row_id,
            session_id=session_id,
            checkpoint_type=checkpoint_type,
            content=content,
            references=refs_json,
            created_at=ts,
        )

    def complete_session(self, session_id: str, summary: str = "") -> None:
        """Mark session as complete with velocity computation."""
        ts: str = _now()
        # Compute velocity from session metrics
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT started_at, beliefs_created, corrections_detected FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        velocity: float | None = None
        tier: str | None = None
        if row is not None:
            started: str = row["started_at"]
            items: int = int(row["beliefs_created"]) + int(row["corrections_detected"])
            try:
                from datetime import datetime as _dt
                t0: _dt = _dt.fromisoformat(started)
                t1: _dt = _dt.fromisoformat(ts)
                hours: float = max(0.5, (t1 - t0).total_seconds() / 3600.0)
                velocity = items / hours
                if velocity > 10.0:
                    tier = "sprint"
                elif velocity >= 5.0:
                    tier = "moderate"
                elif velocity >= 2.0:
                    tier = "steady"
                else:
                    tier = "deep"
            except (ValueError, TypeError):
                pass
        self._conn.execute(
            """UPDATE sessions SET completed_at = ?, summary = ?,
               velocity_items_per_hour = ?, velocity_tier = ?
               WHERE id = ?""",
            (ts, summary if summary else None, velocity, tier, session_id),
        )
        self._conn.commit()

    def increment_session_metrics(
        self,
        session_id: str,
        retrieval_tokens: int = 0,
        classification_tokens: int = 0,
        beliefs_created: int = 0,
        corrections_detected: int = 0,
        searches_performed: int = 0,
        feedback_given: int = 0,
    ) -> None:
        """Atomically increment session token/correction counters."""
        self._conn.execute(
            """UPDATE sessions SET
                retrieval_tokens = retrieval_tokens + ?,
                classification_tokens = classification_tokens + ?,
                beliefs_created = beliefs_created + ?,
                corrections_detected = corrections_detected + ?,
                searches_performed = searches_performed + ?,
                feedback_given = feedback_given + ?
               WHERE id = ?""",
            (
                retrieval_tokens, classification_tokens,
                beliefs_created, corrections_detected,
                searches_performed, feedback_given, session_id,
            ),
        )
        self._conn.commit()

    def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID."""
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return _row_to_session(row) if row is not None else None

    def find_incomplete_sessions(self) -> list[Session]:
        """Find sessions where completed_at IS NULL (crashed or interrupted)."""
        rows: list[sqlite3.Row] = self._conn.execute(
            "SELECT * FROM sessions WHERE completed_at IS NULL ORDER BY started_at DESC"
        ).fetchall()
        return [_row_to_session(r) for r in rows]

    def get_session_checkpoints(self, session_id: str) -> list[Checkpoint]:
        """Get all checkpoints for a session ordered by creation time."""
        rows: list[sqlite3.Row] = self._conn.execute(
            "SELECT * FROM checkpoints WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
        return [_row_to_checkpoint(r) for r in rows]

    # --- Temporal queries (Wave 2) ---

    def timeline(
        self,
        topic: str | None = None,
        start: str | None = None,
        end: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[Belief]:
        """Return beliefs ordered by time, optionally filtered by topic/time/session.

        Uses FTS5 for topic filtering when provided, otherwise pure SQL.
        """
        if topic:
            # FTS5 search with temporal filtering
            sql: str = """
                SELECT b.* FROM search_index si
                JOIN beliefs b ON b.id = si.id
                WHERE search_index MATCH ?
                  AND b.valid_to IS NULL
            """
            params: list[object] = [topic]
            if start:
                sql += " AND b.created_at >= ?"
                params.append(start)
            if end:
                sql += " AND b.created_at <= ?"
                params.append(end)
            if session_id:
                sql += " AND b.session_id = ?"
                params.append(session_id)
            sql += " ORDER BY b.created_at ASC LIMIT ?"
            params.append(limit)
        else:
            sql = "SELECT * FROM beliefs WHERE valid_to IS NULL"
            params = []
            if start:
                sql += " AND created_at >= ?"
                params.append(start)
            if end:
                sql += " AND created_at <= ?"
                params.append(end)
            if session_id:
                sql += " AND session_id = ?"
                params.append(session_id)
            sql += " ORDER BY created_at ASC LIMIT ?"
            params.append(limit)

        rows: list[sqlite3.Row] = self._conn.execute(sql, params).fetchall()
        return [_row_to_belief(r) for r in rows]

    def evolution(
        self,
        belief_id: str | None = None,
        topic: str | None = None,
        limit: int = 50,
    ) -> list[Belief]:
        """Trace belief evolution over time.

        If belief_id: follow SUPERSEDES chain in both directions.
        If topic: all beliefs about topic chronologically, marking superseded ones.
        """
        if belief_id:
            # Walk backward to find the root
            chain: list[Belief] = []
            visited: set[str] = set()
            # Walk backward (find what this belief superseded)
            current_id: str | None = belief_id
            backward: list[Belief] = []
            while current_id and current_id not in visited:
                visited.add(current_id)
                row: sqlite3.Row | None = self._conn.execute(
                    "SELECT * FROM beliefs WHERE id = ?", (current_id,)
                ).fetchone()
                if row is None:
                    break
                backward.append(_row_to_belief(row))
                # Find what this belief superseded (old belief with superseded_by = current)
                prev: sqlite3.Row | None = self._conn.execute(
                    "SELECT * FROM beliefs WHERE superseded_by = ?", (current_id,)
                ).fetchone()
                current_id = prev["id"] if prev is not None else None
            backward.reverse()
            chain.extend(backward)

            # Walk forward from original belief_id (find what supersedes it)
            current_id = belief_id
            while current_id and current_id not in visited:
                visited.add(current_id)
                row = self._conn.execute(
                    "SELECT * FROM beliefs WHERE id = ?", (current_id,)
                ).fetchone()
                if row is None:
                    break
                b: Belief = _row_to_belief(row)
                chain.append(b)
                current_id = b.superseded_by

            return chain[:limit]

        if topic:
            rows: list[sqlite3.Row] = self._conn.execute(
                """SELECT b.* FROM search_index si
                   JOIN beliefs b ON b.id = si.id
                   WHERE search_index MATCH ?
                   ORDER BY b.created_at ASC LIMIT ?""",
                (topic, limit),
            ).fetchall()
            return [_row_to_belief(r) for r in rows]

        return []

    def diff(
        self,
        since: str,
        until: str | None = None,
    ) -> dict[str, list[Belief]]:
        """Show what changed in the belief store between two timestamps.

        Returns dict with keys: added, removed, evolved.
        """
        end: str = until if until else _now()

        added_rows: list[sqlite3.Row] = self._conn.execute(
            "SELECT * FROM beliefs WHERE created_at >= ? AND created_at <= ? ORDER BY created_at",
            (since, end),
        ).fetchall()

        removed_rows: list[sqlite3.Row] = self._conn.execute(
            "SELECT * FROM beliefs WHERE valid_to >= ? AND valid_to <= ? ORDER BY valid_to",
            (since, end),
        ).fetchall()

        evolved_rows: list[sqlite3.Row] = self._conn.execute(
            """SELECT new.* FROM beliefs old
               JOIN beliefs new ON old.superseded_by = new.id
               WHERE old.valid_to >= ? AND old.valid_to <= ?
               ORDER BY new.created_at""",
            (since, end),
        ).fetchall()

        return {
            "added": [_row_to_belief(r) for r in added_rows],
            "removed": [_row_to_belief(r) for r in removed_rows],
            "evolved": [_row_to_belief(r) for r in evolved_rows],
        }

    def search_at_time(
        self,
        query: str,
        at_time: str,
        top_k: int = 10,
    ) -> list[Belief]:
        """Search for beliefs that were active at a specific point in time.

        Returns beliefs created before at_time that had not been superseded by then.
        """
        rows: list[sqlite3.Row] = self._conn.execute(
            """SELECT b.* FROM search_index si
               JOIN beliefs b ON b.id = si.id
               WHERE search_index MATCH ?
                 AND b.created_at <= ?
                 AND (b.valid_to IS NULL OR b.valid_to > ?)
               ORDER BY rank
               LIMIT ?""",
            (query, at_time, at_time, top_k),
        ).fetchall()
        return [_row_to_belief(r) for r in rows]

    # --- Stats ---

    def status(self) -> dict[str, int]:
        """Return counts: observations, beliefs, locked, superseded, edges, sessions."""
        def count(sql: str) -> int:
            row: sqlite3.Row = self._conn.execute(sql).fetchone()
            val: object = row[0]
            if not isinstance(val, int):
                return 0
            return val

        return {
            "observations": count("SELECT COUNT(*) FROM observations"),
            "beliefs": count("SELECT COUNT(*) FROM beliefs"),
            "locked": count("SELECT COUNT(*) FROM beliefs WHERE locked = 1"),
            "superseded": count("SELECT COUNT(*) FROM beliefs WHERE valid_to IS NOT NULL"),
            "edges": count("SELECT COUNT(*) FROM edges"),
            "sessions": count("SELECT COUNT(*) FROM sessions"),
        }

    def get_health_metrics(self) -> dict[str, object]:
        """Return diagnostic health metrics for the memory system.

        Includes credal gap (beliefs at type prior), orphan count,
        edge type breakdown, feedback coverage, and stale sessions.
        """
        def count(sql: str) -> int:
            row: sqlite3.Row = self._conn.execute(sql).fetchone()
            val: object = row[0]
            if not isinstance(val, int):
                return 0
            return val

        def count_float(sql: str) -> float:
            row: sqlite3.Row = self._conn.execute(sql).fetchone()
            val: object = row[0]
            if val is None:
                return 0.0
            return float(str(val))

        active: int = count(
            "SELECT COUNT(*) FROM beliefs WHERE valid_to IS NULL"
        )

        # Credal gap: beliefs whose (alpha, beta_param) match the most
        # common prior for their type (within epsilon). These have never
        # received feedback.
        # Detect type priors by most common (alpha, beta_param) per type.
        type_prior_rows: list[sqlite3.Row] = self._conn.execute(
            """SELECT belief_type,
                      ROUND(alpha, 1) AS a, ROUND(beta_param, 1) AS b,
                      COUNT(*) AS cnt
               FROM beliefs WHERE valid_to IS NULL
               GROUP BY belief_type, a, b
               ORDER BY belief_type, cnt DESC"""
        ).fetchall()

        # Pick the most common (alpha, beta) per type
        type_priors: dict[str, tuple[float, float]] = {}
        for row in type_prior_rows:
            bt: str = str(row["belief_type"])
            if bt not in type_priors:
                type_priors[bt] = (float(str(row["a"])), float(str(row["b"])))

        # Count beliefs at their type prior
        at_prior: int = 0
        epsilon: float = 0.15
        belief_rows: list[sqlite3.Row] = self._conn.execute(
            "SELECT belief_type, alpha, beta_param FROM beliefs WHERE valid_to IS NULL"
        ).fetchall()
        for row in belief_rows:
            bt = str(row["belief_type"])
            prior = type_priors.get(bt)
            if prior is None:
                continue
            if (abs(float(str(row["alpha"])) - prior[0]) < epsilon
                    and abs(float(str(row["beta_param"])) - prior[1]) < epsilon):
                at_prior += 1

        # Orphans: beliefs with no edges at all
        orphan: int = count(
            """SELECT COUNT(*) FROM beliefs b
               WHERE b.valid_to IS NULL
                 AND b.id NOT IN (SELECT from_id FROM edges)
                 AND b.id NOT IN (SELECT to_id FROM edges)"""
        )

        # Edge type breakdown
        contradicts: int = count(
            "SELECT COUNT(*) FROM edges WHERE edge_type = 'CONTRADICTS'"
        )
        supports: int = count(
            "SELECT COUNT(*) FROM edges WHERE edge_type = 'SUPPORTS'"
        )
        supersedes: int = count(
            "SELECT COUNT(*) FROM edges WHERE edge_type = 'SUPERSEDES'"
        )

        # Feedback coverage: beliefs with at least one test result
        with_feedback: int = count(
            """SELECT COUNT(DISTINCT belief_id) FROM tests"""
        )

        # Average confidence
        avg_conf: float = count_float(
            "SELECT AVG(confidence) FROM beliefs WHERE valid_to IS NULL"
        )

        # Stale sessions
        stale: int = count(
            "SELECT COUNT(*) FROM sessions WHERE completed_at IS NULL"
        )

        credal_gap_pct: float = (at_prior / active * 100) if active > 0 else 0.0
        orphan_pct: float = (orphan / active * 100) if active > 0 else 0.0
        feedback_pct: float = (with_feedback / active * 100) if active > 0 else 0.0

        return {
            "active_beliefs": active,
            "credal_gap_count": at_prior,
            "credal_gap_pct": round(credal_gap_pct, 1),
            "orphan_count": orphan,
            "orphan_pct": round(orphan_pct, 1),
            "contradicts_edges": contradicts,
            "supports_edges": supports,
            "supersedes_edges": supersedes,
            "feedback_coverage_count": with_feedback,
            "feedback_coverage_pct": round(feedback_pct, 1),
            "avg_confidence": round(avg_conf, 3),
            "stale_sessions": stale,
            "type_priors": type_priors,
        }

    # --- Bulk maintenance ---

    def get_active_belief_ids(self) -> list[str]:
        """Return all active (non-superseded) belief IDs, ordered by creation."""
        rows: list[sqlite3.Row] = self._conn.execute(
            "SELECT id FROM beliefs WHERE valid_to IS NULL ORDER BY created_at"
        ).fetchall()
        return [str(r["id"]) for r in rows]

    def count_edges_for(self, belief_id: str) -> int:
        """Count SUPPORTS + CONTRADICTS edges connected to a belief."""
        row: sqlite3.Row = self._conn.execute(
            """SELECT COUNT(*) FROM edges
               WHERE (from_id = ? OR to_id = ?)
                 AND edge_type IN ('SUPPORTS', 'CONTRADICTS')""",
            (belief_id, belief_id),
        ).fetchone()
        val: object = row[0]
        return int(val) if isinstance(val, int) else 0

    def bulk_update_confidence(
        self,
        belief_ids: list[str],
        outcome: str,
        weight: float = 0.5,
    ) -> int:
        """Apply a Bayesian update to multiple beliefs. Returns count updated."""
        if not belief_ids:
            return 0

        ts: str = _now()
        updated: int = 0
        for belief_id in belief_ids:
            row: sqlite3.Row | None = self._conn.execute(
                "SELECT alpha, beta_param, locked FROM beliefs WHERE id = ?",
                (belief_id,),
            ).fetchone()
            if row is None:
                continue

            alpha: float = float(str(row["alpha"]))
            beta: float = float(str(row["beta_param"]))
            is_locked: bool = bool(row["locked"])

            if outcome == "used":
                alpha += weight
            elif outcome == "harmful":
                if not is_locked:
                    beta += weight
            else:
                continue

            self._conn.execute(
                "UPDATE beliefs SET alpha = ?, beta_param = ?, updated_at = ? WHERE id = ?",
                (alpha, beta, ts, belief_id),
            )
            updated += 1

        self._conn.commit()
        return updated

    # --- Onboarding provenance ---

    def record_onboarding_run(
        self,
        project_path: str,
        commit_hash: str | None,
        nodes_extracted: int,
        edges_extracted: int,
        beliefs_created: int,
        observations_created: int,
    ) -> int:
        """Record an onboarding run for provenance tracking."""
        ts: str = _now()
        cursor: sqlite3.Cursor = self._conn.execute(
            """INSERT INTO onboarding_runs
               (project_path, commit_hash, nodes_extracted, edges_extracted,
                beliefs_created, observations_created, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (project_path, commit_hash, nodes_extracted, edges_extracted,
             beliefs_created, observations_created, ts),
        )
        self._conn.commit()
        row_id: int | None = cursor.lastrowid
        return row_id if row_id is not None else 0

    def get_last_onboarding(self, project_path: str | None = None) -> dict[str, str] | None:
        """Return the most recent onboarding run, optionally filtered by project."""
        if project_path:
            row: sqlite3.Row | None = self._conn.execute(
                """SELECT * FROM onboarding_runs
                   WHERE project_path = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (project_path,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM onboarding_runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return {k: str(row[k]) for k in row.keys()}

    def promote_to_global(self, belief_id: str) -> bool:
        """Mark a belief as global scope (cross-project).

        Global beliefs are visible across all projects via the global DB.
        Returns True if the belief was promoted, False if not found.
        Requires user confirmation before calling (enforced by MCP tool).
        """
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT id FROM beliefs WHERE id = ? AND valid_to IS NULL",
            (belief_id,),
        ).fetchone()
        if row is None:
            return False
        self._conn.execute(
            "UPDATE beliefs SET scope = 'global', updated_at = ? WHERE id = ?",
            (_now(), belief_id),
        )
        self._conn.commit()
        return True

    def get_global_beliefs(self, limit: int = 20) -> list[Belief]:
        """Return beliefs marked as global scope (cross-project)."""
        rows: list[sqlite3.Row] = self._conn.execute(
            """SELECT * FROM beliefs
               WHERE scope = 'global' AND valid_to IS NULL
               ORDER BY confidence DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [_row_to_belief(r) for r in rows]

    def get_rigor_distribution(self) -> dict[str, int]:
        """Return count of active beliefs per rigor_tier."""
        rows: list[sqlite3.Row] = self._conn.execute(
            """SELECT rigor_tier, COUNT(*) as cnt FROM beliefs
               WHERE valid_to IS NULL
               GROUP BY rigor_tier ORDER BY cnt DESC"""
        ).fetchall()
        return {str(r["rigor_tier"]): int(r["cnt"]) for r in rows}

    def get_last_completed_session(self) -> Session | None:
        """Return the most recently completed session (for velocity reporting)."""
        row: sqlite3.Row | None = self._conn.execute(
            """SELECT * FROM sessions
               WHERE completed_at IS NOT NULL
               ORDER BY completed_at DESC LIMIT 1"""
        ).fetchone()
        if row is None:
            return None
        return _row_to_session(row)

    def get_snapshot(
        self,
        at_time: str | None = None,
        belief_type: str | None = None,
        limit: int = 200,
    ) -> list[Belief]:
        """Return beliefs that were active at a specific point in time.

        If at_time is None, returns currently active beliefs.
        Excludes superseded beliefs (valid_to <= at_time).
        """
        if at_time is None:
            at_time = _now()

        sql: str = """SELECT * FROM beliefs
                      WHERE created_at <= ?
                        AND (valid_to IS NULL OR valid_to > ?)"""
        params: list[object] = [at_time, at_time]

        if belief_type is not None:
            sql += " AND belief_type = ?"
            params.append(belief_type)

        sql += " ORDER BY confidence DESC LIMIT ?"
        params.append(limit)

        rows: list[sqlite3.Row] = self._conn.execute(sql, tuple(params)).fetchall()
        return [_row_to_belief(r) for r in rows]

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def query(self, sql: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        """Execute a read-only SQL query and return all rows.

        Intended for tests and diagnostic tooling. Not for production write paths.
        """
        return self._conn.execute(sql, params).fetchall()  # type: ignore[return-value]

    # --- Evidence (direct access) ---

    def insert_evidence(
        self,
        belief_id: str,
        observation_id: str,
        source_weight: float = 1.0,
        relationship: str = "supports",
    ) -> Evidence:
        """Insert an evidence link from an observation to a belief."""
        ts: str = _now()
        cursor: sqlite3.Cursor = self._conn.execute(
            """INSERT INTO evidence (belief_id, observation_id, source_weight, relationship, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (belief_id, observation_id, source_weight, relationship, ts),
        )
        self._conn.commit()
        row_id: int | None = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("Evidence insert did not return a rowid")
        return Evidence(
            id=row_id,
            belief_id=belief_id,
            observation_id=observation_id,
            source_weight=source_weight,
            relationship=relationship,
            created_at=ts,
        )

    # --- Document tracing ---

    def get_source_documents(self, belief_ids: list[str]) -> list[str]:
        """Trace beliefs back to source file paths via evidence -> observations.

        Returns deduplicated list of source_path values for the given beliefs.
        """
        if not belief_ids:
            return []
        placeholders: str = ",".join("?" * len(belief_ids))
        rows: list[sqlite3.Row] = self._conn.execute(
            f"""SELECT DISTINCT o.source_path
                FROM evidence e
                JOIN observations o ON o.id = e.observation_id
                WHERE e.belief_id IN ({placeholders})
                  AND o.source_path != ''""",
            belief_ids,
        ).fetchall()
        return [row["source_path"] for row in rows]

    # --- Retrieval stats (Tier 3) ---

    def get_retrieval_stats(self, belief_id: str) -> dict[str, int]:
        """Return retrieval count and use rate for a belief.

        Queries the tests table for outcome history. Returns zeros if no
        retrieval data exists yet (Tier 3 activates once beliefs are tested).
        """
        row: sqlite3.Row | None = self._conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN outcome = 'used' THEN 1 ELSE 0 END) as used,
                SUM(CASE WHEN outcome = 'ignored' THEN 1 ELSE 0 END) as ignored,
                SUM(CASE WHEN outcome = 'harmful' THEN 1 ELSE 0 END) as harmful
            FROM tests WHERE belief_id = ?""",
            (belief_id,),
        ).fetchone()
        if row is None or row["total"] == 0:
            return {"retrieval_count": 0, "used": 0, "ignored": 0, "harmful": 0}
        return {
            "retrieval_count": int(str(row["total"])),
            "used": int(str(row["used"])),
            "ignored": int(str(row["ignored"])),
            "harmful": int(str(row["harmful"])),
        }

    def get_retrieval_stats_batch(self, belief_ids: list[str]) -> dict[str, dict[str, int]]:
        """Batch retrieval stats for multiple beliefs.

        Returns {belief_id: {retrieval_count, used, ignored, harmful}}.
        Beliefs with no test data are omitted from the result.
        """
        if not belief_ids:
            return {}
        placeholders: str = ",".join("?" for _ in belief_ids)
        rows: list[sqlite3.Row] = self._conn.execute(
            f"""SELECT
                belief_id,
                COUNT(*) as total,
                SUM(CASE WHEN outcome = 'used' THEN 1 ELSE 0 END) as used,
                SUM(CASE WHEN outcome = 'ignored' THEN 1 ELSE 0 END) as ignored,
                SUM(CASE WHEN outcome = 'harmful' THEN 1 ELSE 0 END) as harmful
            FROM tests
            WHERE belief_id IN ({placeholders})
            GROUP BY belief_id""",
            belief_ids,
        ).fetchall()
        result: dict[str, dict[str, int]] = {}
        for row in rows:
            result[row["belief_id"]] = {
                "retrieval_count": int(str(row["total"])),
                "used": int(str(row["used"])),
                "ignored": int(str(row["ignored"])),
                "harmful": int(str(row["harmful"])),
            }
        return result

    # --- Stale belief detection ---

    def get_stale_beliefs(self, days_threshold: int = 30, limit: int = 50) -> list[Belief]:
        """Return beliefs not retrieved in the last N days.

        Excludes locked beliefs (always relevant) and beliefs created
        within the threshold period (too new to be stale).
        Returns at most ``limit`` beliefs, ordered by staleness (oldest first).
        """
        rows: list[sqlite3.Row] = self._conn.execute(
            """SELECT * FROM beliefs
               WHERE valid_to IS NULL
                 AND locked = 0
                 AND created_at < datetime('now', ? || ' days')
                 AND (last_retrieved_at IS NULL
                      OR last_retrieved_at < datetime('now', ? || ' days'))
               ORDER BY COALESCE(last_retrieved_at, created_at) ASC
               LIMIT ?""",
            (f"-{days_threshold}", f"-{days_threshold}", limit),
        ).fetchall()
        return [_row_to_belief(r) for r in rows]

    def count_stale_beliefs(self, days_threshold: int = 30) -> int:
        """Count beliefs not retrieved in the last N days (excludes locked and new)."""
        row: sqlite3.Row = self._conn.execute(
            """SELECT COUNT(*) FROM beliefs
               WHERE valid_to IS NULL
                 AND locked = 0
                 AND created_at < datetime('now', ? || ' days')
                 AND (last_retrieved_at IS NULL
                      OR last_retrieved_at < datetime('now', ? || ' days'))""",
            (f"-{days_threshold}", f"-{days_threshold}"),
        ).fetchone()
        val: object = row[0]
        if not isinstance(val, int):
            return 0
        return val

    # --- Test results ---

    def record_test_result(
        self,
        belief_id: str,
        session_id: str,
        outcome: str,
        detection_layer: str,
        retrieval_context: str | None = None,
        outcome_detail: str | None = None,
        evidence_weight: float = 1.0,
    ) -> TestResult:
        """Record the outcome of a belief retrieval. Also updates belief confidence."""
        ts: str = _now()
        cursor: sqlite3.Cursor = self._conn.execute(
            """INSERT INTO tests
               (belief_id, session_id, retrieval_context, outcome, outcome_detail,
                detection_layer, evidence_weight, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (belief_id, session_id, retrieval_context, outcome, outcome_detail,
             detection_layer, evidence_weight, ts),
        )
        self._conn.commit()
        row_id: int | None = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("TestResult insert did not return a rowid")
        self.update_confidence(belief_id, outcome, evidence_weight)
        return TestResult(
            id=row_id,
            belief_id=belief_id,
            session_id=session_id,
            retrieval_context=retrieval_context,
            outcome=outcome,
            outcome_detail=outcome_detail,
            detection_layer=detection_layer,
            evidence_weight=evidence_weight,
            created_at=ts,
        )

    # --- Pending feedback ---

    def insert_pending_feedback(
        self,
        belief_id: str,
        belief_content: str,
        session_id: str | None = None,
    ) -> None:
        """Store a retrieved belief for later feedback matching."""
        ts: str = _now()
        self._conn.execute(
            """INSERT INTO pending_feedback
               (belief_id, belief_content, session_id, created_at)
               VALUES (?, ?, ?, ?)""",
            (belief_id, belief_content, session_id, ts),
        )
        self._conn.commit()

    def get_pending_feedback(
        self,
        session_id: str | None = None,
    ) -> list[dict[str, str]]:
        """Get pending feedback entries, optionally filtered by session."""
        if session_id is not None:
            rows: list[sqlite3.Row] = self._conn.execute(
                "SELECT belief_id, belief_content, session_id, created_at "
                "FROM pending_feedback WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT belief_id, belief_content, session_id, created_at "
                "FROM pending_feedback ORDER BY created_at",
            ).fetchall()
        return [
            {
                "belief_id": row["belief_id"],
                "belief_content": row["belief_content"],
                "session_id": row["session_id"] if row["session_id"] else "",
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def clear_pending_feedback(
        self,
        session_id: str | None = None,
    ) -> int:
        """Remove pending feedback entries after processing. Returns count removed."""
        if session_id is not None:
            cursor: sqlite3.Cursor = self._conn.execute(
                "DELETE FROM pending_feedback WHERE session_id = ?",
                (session_id,),
            )
        else:
            cursor = self._conn.execute("DELETE FROM pending_feedback")
        self._conn.commit()
        return cursor.rowcount

    def get_session_observation_texts(
        self,
        session_id: str,
        limit: int = 200,
    ) -> list[str]:
        """Return observation content strings for a given session, most recent first."""
        rows: list[sqlite3.Row] = self._conn.execute(
            "SELECT content FROM observations WHERE session_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [row["content"] for row in rows]
