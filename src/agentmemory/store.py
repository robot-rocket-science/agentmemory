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
    summary TEXT
);

CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    content TEXT NOT NULL,
    observation_type TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL DEFAULT '',
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
CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints(session_id);
CREATE INDEX IF NOT EXISTS idx_evidence_belief ON evidence(belief_id);
CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_id);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_id);
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
    return Observation(
        id=row["id"],
        content_hash=row["content_hash"],
        content=row["content"],
        observation_type=row["observation_type"],
        source_type=row["source_type"],
        source_id=row["source_id"],
        session_id=row["session_id"],
        created_at=row["created_at"],
    )


def _row_to_belief(row: sqlite3.Row) -> Belief:
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
    )


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        model=row["model"],
        project_context=row["project_context"],
        summary=row["summary"],
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

    # --- Observations (immutable) ---

    def insert_observation(
        self,
        content: str,
        observation_type: str,
        source_type: str,
        source_id: str = "",
        session_id: str | None = None,
    ) -> Observation:
        """Insert an observation. Content-hash dedup: if same hash exists, return existing."""
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
               (id, content_hash, content, observation_type, source_type, source_id, session_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (obs_id, ch, content, observation_type, source_type, source_id, session_id, ts),
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
    ) -> Belief:
        """Insert a belief with optional evidence link. Content-hash dedup.

        Also inserts into FTS5 search_index. If the same content hash already
        exists, returns the existing belief without modification.

        If created_at is provided, uses that timestamp instead of now().
        This enables source-truth dating (e.g., git commit dates).
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
                source_type, locked, valid_from, valid_to, superseded_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?)""",
            (belief_id, ch, content, belief_type, alpha, beta_param,
             source_type, locked_int, ts, ts),
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
        )

    def lock_belief(self, belief_id: str) -> None:
        """Mark a belief as locked. Locked beliefs cannot have confidence reduced."""
        ts: str = _now()
        self._conn.execute(
            "UPDATE beliefs SET locked = 1, updated_at = ? WHERE id = ?",
            (ts, belief_id),
        )
        self._conn.commit()

    def supersede_belief(self, old_id: str, new_id: str, reason: str) -> None:
        """Mark old belief as superseded. Sets valid_to, creates a SUPERSEDES edge."""
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
        self._conn.commit()

    def update_confidence(self, belief_id: str, outcome: str, weight: float = 1.0) -> None:
        """Bayesian update: 'used' increments alpha, 'harmful' increments beta_param.

        Locked beliefs cannot have beta_param increased (confidence floor preserved).
        """
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT alpha, beta_param, locked FROM beliefs WHERE id = ?",
            (belief_id,),
        ).fetchone()
        if row is None:
            return

        alpha: float = row["alpha"]
        beta: float = row["beta_param"]
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
        Deterministic: neighbors processed by weight DESC, created_at ASC.
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

        beliefs: list[Belief] = []
        for r in rows:
            belief: sqlite3.Row | None = self._conn.execute(
                "SELECT * FROM beliefs WHERE id = ? AND valid_to IS NULL",
                (r["id"],),
            ).fetchone()
            if belief is not None:
                beliefs.append(_row_to_belief(belief))
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

    def get_locked_beliefs(self) -> list[Belief]:
        """Return all locked beliefs (for L0 context injection)."""
        rows: list[sqlite3.Row] = self._conn.execute(
            "SELECT * FROM beliefs WHERE locked = 1 AND valid_to IS NULL"
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
        """Mark session as complete with optional summary."""
        ts: str = _now()
        self._conn.execute(
            "UPDATE sessions SET completed_at = ?, summary = ? WHERE id = ?",
            (ts, summary if summary else None, session_id),
        )
        self._conn.commit()

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
