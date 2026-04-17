"""Anonymous telemetry: local-only performance snapshots.

Collects content-free metrics about agentmemory machinery performance
and appends them as JSONL to ~/.agentmemory/telemetry.jsonl on session end.

PRIVACY GUARANTEE: No belief content, project paths, file paths, session IDs,
user names, or any string field from any table is ever included. Only integer
counts, float ratios, and categorical distribution keys (belief_type names,
source_type names, edge_type names) are collected.

Users can disable telemetry via config: {"telemetry": {"enabled": false}}
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentmemory.store import MemoryStore


@dataclass
class SessionMetrics:
    """Per-session counters (no content)."""
    retrieval_tokens: int = 0
    classification_tokens: int = 0
    beliefs_created: int = 0
    corrections_detected: int = 0
    searches_performed: int = 0
    feedback_given: int = 0
    velocity_items_per_hour: float | None = None
    velocity_tier: str | None = None
    duration_seconds: float | None = None


@dataclass
class FeedbackMetrics:
    """Feedback loop health (aggregated counts only)."""
    outcome_counts: dict[str, int] = field(default_factory=lambda: {})
    detection_layer_counts: dict[str, int] = field(default_factory=lambda: {})
    feedback_rate: float = 0.0


@dataclass
class BeliefMetrics:
    """Belief lifecycle metrics (counts and distributions only)."""
    total_active: int = 0
    total_superseded: int = 0
    total_locked: int = 0
    confidence_distribution: dict[str, int] = field(default_factory=lambda: {})
    type_distribution: dict[str, int] = field(default_factory=lambda: {})
    source_distribution: dict[str, int] = field(default_factory=lambda: {})
    churn_rate: float = 0.0
    orphan_count: int = 0


@dataclass
class GraphMetrics:
    """Graph health metrics (counts only)."""
    total_edges: int = 0
    edge_type_distribution: dict[str, int] = field(default_factory=lambda: {})
    avg_edges_per_belief: float = 0.0


@dataclass
class TelemetrySnapshot:
    """Complete telemetry snapshot. Content-free by construction."""
    v: int = 1
    ts: str = ""
    session: SessionMetrics = field(default_factory=SessionMetrics)
    feedback: FeedbackMetrics = field(default_factory=FeedbackMetrics)
    beliefs: BeliefMetrics = field(default_factory=BeliefMetrics)
    graph: GraphMetrics = field(default_factory=GraphMetrics)
    window_7: dict[str, Any] = field(default_factory=lambda: {})
    window_30: dict[str, Any] = field(default_factory=lambda: {})


def _default_path() -> Path:
    """Default telemetry output path."""
    return Path.home() / ".agentmemory" / "telemetry.jsonl"


def collect_session_metrics(store: MemoryStore, session_id: str) -> SessionMetrics:
    """Extract per-session counters from the sessions table."""
    row = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
        """SELECT retrieval_tokens, classification_tokens, beliefs_created,
                  corrections_detected, searches_performed, feedback_given,
                  velocity_items_per_hour, velocity_tier,
                  started_at, completed_at
           FROM sessions WHERE id = ?""",
        (session_id,),
    ).fetchone()
    if row is None:
        return SessionMetrics()

    duration: float | None = None
    started: str | None = row["started_at"]
    completed: str | None = row["completed_at"]
    if started and completed:
        try:
            t0: datetime = datetime.fromisoformat(started)
            t1: datetime = datetime.fromisoformat(completed)
            duration = (t1 - t0).total_seconds()
        except (ValueError, TypeError):
            pass

    vel: object = row["velocity_items_per_hour"]
    tier: object = row["velocity_tier"]
    return SessionMetrics(
        retrieval_tokens=int(row["retrieval_tokens"]),
        classification_tokens=int(row["classification_tokens"]),
        beliefs_created=int(row["beliefs_created"]),
        corrections_detected=int(row["corrections_detected"]),
        searches_performed=int(row["searches_performed"]),
        feedback_given=int(row["feedback_given"]),
        velocity_items_per_hour=float(str(vel)) if vel is not None else None,
        velocity_tier=str(tier) if tier is not None else None,
        duration_seconds=duration,
    )


def collect_feedback_metrics(store: MemoryStore, session_id: str) -> FeedbackMetrics:
    """Aggregate feedback outcomes for a session."""
    conn = store._conn  # pyright: ignore[reportPrivateUsage]

    # Outcome distribution
    outcome_rows = conn.execute(
        """SELECT outcome, COUNT(*) as cnt FROM tests
           WHERE session_id = ? GROUP BY outcome""",
        (session_id,),
    ).fetchall()
    outcome_counts: dict[str, int] = {str(r["outcome"]): int(r["cnt"]) for r in outcome_rows}

    # Detection layer distribution
    layer_rows = conn.execute(
        """SELECT detection_layer, COUNT(*) as cnt FROM tests
           WHERE session_id = ? GROUP BY detection_layer""",
        (session_id,),
    ).fetchall()
    layer_counts: dict[str, int] = {str(r["detection_layer"]): int(r["cnt"]) for r in layer_rows}

    # Feedback rate
    session_row = conn.execute(
        "SELECT searches_performed, feedback_given FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    rate: float = 0.0
    if session_row is not None:
        searches: int = int(session_row["searches_performed"])
        fb: int = int(session_row["feedback_given"])
        if searches > 0:
            rate = fb / searches

    return FeedbackMetrics(
        outcome_counts=outcome_counts,
        detection_layer_counts=layer_counts,
        feedback_rate=rate,
    )


def collect_belief_metrics(store: MemoryStore) -> BeliefMetrics:
    """Aggregate belief lifecycle metrics (no content)."""
    conn = store._conn  # pyright: ignore[reportPrivateUsage]

    def count(sql: str) -> int:
        row = conn.execute(sql).fetchone()
        val: object = row[0]
        return int(val) if isinstance(val, int) else 0

    active: int = count("SELECT COUNT(*) FROM beliefs WHERE valid_to IS NULL")
    superseded: int = count("SELECT COUNT(*) FROM beliefs WHERE valid_to IS NOT NULL")
    locked: int = count("SELECT COUNT(*) FROM beliefs WHERE locked = 1 AND valid_to IS NULL")

    # Confidence histogram
    conf_rows = conn.execute(
        """SELECT
             CASE
               WHEN confidence < 0.25 THEN '<25%'
               WHEN confidence < 0.50 THEN '25-50%'
               WHEN confidence < 0.75 THEN '50-75%'
               ELSE '>75%'
             END AS bucket,
             COUNT(*) as cnt
           FROM beliefs WHERE valid_to IS NULL
           GROUP BY bucket"""
    ).fetchall()
    conf_dist: dict[str, int] = {str(r["bucket"]): int(r["cnt"]) for r in conf_rows}

    # Type distribution
    type_rows = conn.execute(
        """SELECT belief_type, COUNT(*) as cnt FROM beliefs
           WHERE valid_to IS NULL GROUP BY belief_type"""
    ).fetchall()
    type_dist: dict[str, int] = {str(r["belief_type"]): int(r["cnt"]) for r in type_rows}

    # Source distribution
    src_rows = conn.execute(
        """SELECT source_type, COUNT(*) as cnt FROM beliefs
           WHERE valid_to IS NULL GROUP BY source_type"""
    ).fetchall()
    src_dist: dict[str, int] = {str(r["source_type"]): int(r["cnt"]) for r in src_rows}

    # Churn rate
    total: int = active + superseded
    churn: float = superseded / total if total > 0 else 0.0

    # Orphan count
    orphan: int = count(
        """SELECT COUNT(*) FROM beliefs b
           WHERE b.valid_to IS NULL
             AND b.id NOT IN (SELECT from_id FROM edges)
             AND b.id NOT IN (SELECT to_id FROM edges)"""
    )

    return BeliefMetrics(
        total_active=active,
        total_superseded=superseded,
        total_locked=locked,
        confidence_distribution=conf_dist,
        type_distribution=type_dist,
        source_distribution=src_dist,
        churn_rate=round(churn, 4),
        orphan_count=orphan,
    )


def collect_graph_metrics(store: MemoryStore) -> GraphMetrics:
    """Aggregate graph health metrics (counts only)."""
    conn = store._conn  # pyright: ignore[reportPrivateUsage]

    total_row = conn.execute("SELECT COUNT(*) FROM edges").fetchone()
    total_edges: int = int(total_row[0]) if total_row[0] is not None else 0

    edge_rows = conn.execute(
        "SELECT edge_type, COUNT(*) as cnt FROM edges GROUP BY edge_type"
    ).fetchall()
    edge_dist: dict[str, int] = {str(r["edge_type"]): int(r["cnt"]) for r in edge_rows}

    active_row = conn.execute(
        "SELECT COUNT(*) FROM beliefs WHERE valid_to IS NULL"
    ).fetchone()
    active: int = int(active_row[0]) if active_row[0] is not None else 0
    avg: float = total_edges / active if active > 0 else 0.0

    return GraphMetrics(
        total_edges=total_edges,
        edge_type_distribution=edge_dist,
        avg_edges_per_belief=round(avg, 3),
    )


def collect_rolling_window(store: MemoryStore, n_sessions: int) -> dict[str, Any]:
    """Aggregate session-level metrics over the last N completed sessions."""
    conn = store._conn  # pyright: ignore[reportPrivateUsage]

    rows = conn.execute(
        """SELECT retrieval_tokens, classification_tokens, beliefs_created,
                  corrections_detected, searches_performed, feedback_given
           FROM sessions
           WHERE completed_at IS NOT NULL
           ORDER BY completed_at DESC
           LIMIT ?""",
        (n_sessions,),
    ).fetchall()

    if not rows:
        return {"sessions_in_window": 0}

    totals: dict[str, int] = {
        "retrieval_tokens": 0,
        "classification_tokens": 0,
        "beliefs_created": 0,
        "corrections_detected": 0,
        "searches_performed": 0,
        "feedback_given": 0,
    }
    for row in rows:
        for key in totals:
            totals[key] += int(row[key])

    count: int = len(rows)
    searches: int = totals["searches_performed"]
    result: dict[str, Any] = {
        "sessions_in_window": count,
        "totals": totals,
        "averages": {k: round(v / count, 2) for k, v in totals.items()},
        "feedback_rate": round(totals["feedback_given"] / searches, 3) if searches > 0 else 0.0,
        "correction_rate": round(totals["corrections_detected"] / count, 3),
    }
    return result


def collect_snapshot(store: MemoryStore, session_id: str) -> TelemetrySnapshot:
    """Collect a complete telemetry snapshot for a session."""
    return TelemetrySnapshot(
        v=1,
        ts=datetime.now(timezone.utc).isoformat(),
        session=collect_session_metrics(store, session_id),
        feedback=collect_feedback_metrics(store, session_id),
        beliefs=collect_belief_metrics(store),
        graph=collect_graph_metrics(store),
        window_7=collect_rolling_window(store, 7),
        window_30=collect_rolling_window(store, 30),
    )


def write_snapshot(snapshot: TelemetrySnapshot, path: Path | None = None) -> Path:
    """Append a telemetry snapshot as a single JSON line to the output file."""
    out: Path = path or _default_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    line: str = json.dumps(asdict(snapshot), separators=(",", ":"))
    with open(out, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return out
