"""Experiment 74: Temporal queries vs keyword search.

Tests whether the new temporal tools (timeline, evolution, diff) produce
results that keyword search (FTS5 via search()) cannot.

10 test queries across 3 categories:
  - IMPOSSIBLE with search: diff/session replay (T5, T6, T9)
  - LOSES CHAIN INFO: evolution/supersession (T3, T4, T10)
  - LOSES TIME PRECISION: range queries (T1, T2, T7, T8)
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH: str = str(
    Path.home() / ".agentmemory" / "projects" / "2e7ed55e017a" / "memory.db"
)


@dataclass
class QueryResult:
    query_id: str
    category: str
    description: str
    temporal_count: int
    search_count: int
    temporal_only: int  # results temporal found that search didn't
    search_only: int    # results search found that temporal didn't
    overlap: int
    temporal_ms: float
    search_ms: float
    temporal_possible: bool  # can the temporal tool answer this at all?
    search_possible: bool    # can keyword search answer this at all?


def run_fts5_search(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[str]:
    """Run FTS5 search and return belief IDs."""
    rows: list[sqlite3.Row] = conn.execute(
        """SELECT b.id FROM search_index si
           JOIN beliefs b ON b.id = si.id
           WHERE search_index MATCH ? AND b.valid_to IS NULL
           ORDER BY rank LIMIT ?""",
        (query, limit),
    ).fetchall()
    return [r["id"] for r in rows]


def run_timeline(
    conn: sqlite3.Connection,
    topic: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 20,
) -> list[str]:
    """Run timeline query and return belief IDs."""
    if topic:
        sql: str = """
            SELECT b.id FROM search_index si
            JOIN beliefs b ON b.id = si.id
            WHERE search_index MATCH ? AND b.valid_to IS NULL
        """
        params: list[object] = [topic]
        if start:
            sql += " AND b.created_at >= ?"
            params.append(start)
        if end:
            sql += " AND b.created_at <= ?"
            params.append(end)
        sql += " ORDER BY b.created_at ASC LIMIT ?"
        params.append(limit)
    else:
        sql = "SELECT id FROM beliefs WHERE valid_to IS NULL"
        params = []
        if start:
            sql += " AND created_at >= ?"
            params.append(start)
        if end:
            sql += " AND created_at <= ?"
            params.append(end)
        sql += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)

    rows: list[sqlite3.Row] = conn.execute(sql, params).fetchall()
    return [r["id"] for r in rows]


def run_diff(conn: sqlite3.Connection, since: str, until: str | None = None) -> list[str]:
    """Run diff query and return belief IDs (added + removed + evolved)."""
    end: str = until or datetime.now(timezone.utc).isoformat()
    added: list[sqlite3.Row] = conn.execute(
        "SELECT id FROM beliefs WHERE created_at >= ? AND created_at <= ?",
        (since, end),
    ).fetchall()
    removed: list[sqlite3.Row] = conn.execute(
        "SELECT id FROM beliefs WHERE valid_to >= ? AND valid_to <= ?",
        (since, end),
    ).fetchall()
    ids: set[str] = {r["id"] for r in added} | {r["id"] for r in removed}
    return list(ids)


def run_evolution(conn: sqlite3.Connection, topic: str, limit: int = 20) -> list[str]:
    """Run evolution query (topic mode) and return belief IDs."""
    rows: list[sqlite3.Row] = conn.execute(
        """SELECT b.id FROM search_index si
           JOIN beliefs b ON b.id = si.id
           WHERE search_index MATCH ?
           ORDER BY b.created_at ASC LIMIT ?""",
        (topic, limit),
    ).fetchall()
    return [r["id"] for r in rows]


def main() -> None:
    conn: sqlite3.Connection = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    now: datetime = datetime.now(timezone.utc)
    yesterday: str = (now - timedelta(hours=24)).isoformat()
    last_week: str = (now - timedelta(days=7)).isoformat()

    # Define test queries
    tests: list[dict[str, object]] = [
        {
            "id": "T1", "category": "RANGE",
            "description": "What happened in the last 24 hours?",
            "temporal_fn": lambda: run_timeline(conn, start=yesterday),
            "search_fn": lambda: run_fts5_search(conn, "recent changes"),
            "search_possible": True,
        },
        {
            "id": "T2", "category": "RANGE",
            "description": "What was decided right after HRR?",
            "temporal_fn": lambda: run_timeline(conn, topic="HRR", limit=10),
            "search_fn": lambda: run_fts5_search(conn, "HRR decision"),
            "search_possible": True,
        },
        {
            "id": "T3", "category": "EVOLUTION",
            "description": "How did retrieval strategy evolve?",
            "temporal_fn": lambda: run_evolution(conn, "retrieval strategy"),
            "search_fn": lambda: run_fts5_search(conn, "retrieval strategy"),
            "search_possible": True,
        },
        {
            "id": "T4", "category": "EVOLUTION",
            "description": "How did decay architecture evolve?",
            "temporal_fn": lambda: run_evolution(conn, "decay architecture"),
            "search_fn": lambda: run_fts5_search(conn, "decay architecture"),
            "search_possible": True,
        },
        {
            "id": "T5", "category": "DIFF",
            "description": "What changed since yesterday?",
            "temporal_fn": lambda: run_diff(conn, since=yesterday),
            "search_fn": lambda: run_fts5_search(conn, "changed yesterday"),
            "search_possible": False,
        },
        {
            "id": "T6", "category": "RANGE",
            "description": "Show all beliefs from the last week",
            "temporal_fn": lambda: run_timeline(conn, start=last_week, limit=50),
            "search_fn": lambda: run_fts5_search(conn, "belief recent"),
            "search_possible": False,
        },
        {
            "id": "T7", "category": "RANGE",
            "description": "What 3 beliefs preceded typing correction?",
            "temporal_fn": lambda: run_timeline(conn, topic="typing annotation", limit=5),
            "search_fn": lambda: run_fts5_search(conn, "typing annotation"),
            "search_possible": True,
        },
        {
            "id": "T8", "category": "RANGE",
            "description": "All corrections in last 24h",
            "temporal_fn": lambda: (
                conn.execute(
                    "SELECT id FROM beliefs WHERE created_at >= ? AND belief_type='correction' AND valid_to IS NULL ORDER BY created_at LIMIT 50",
                    (yesterday,),
                ).fetchall()
            ),
            "search_fn": lambda: run_fts5_search(conn, "correction"),
            "search_possible": True,
        },
        {
            "id": "T9", "category": "DIFF",
            "description": "What beliefs were superseded in last 24h?",
            "temporal_fn": lambda: (
                conn.execute(
                    "SELECT id FROM beliefs WHERE valid_to >= ? ORDER BY valid_to LIMIT 50",
                    (yesterday,),
                ).fetchall()
            ),
            "search_fn": lambda: run_fts5_search(conn, "superseded removed"),
            "search_possible": False,
        },
        {
            "id": "T10", "category": "EVOLUTION",
            "description": "Full history of scoring algorithm topic",
            "temporal_fn": lambda: run_evolution(conn, "scoring algorithm"),
            "search_fn": lambda: run_fts5_search(conn, "scoring algorithm"),
            "search_possible": True,
        },
    ]

    results: list[QueryResult] = []
    print(f"{'ID':>4} {'Category':>10} {'Temporal':>9} {'Search':>8} {'T-Only':>7} {'S-Only':>7} {'Over':>5} {'T(ms)':>7} {'S(ms)':>7} {'S-able':>6}")
    print("-" * 85)

    for t in tests:
        # Run temporal query
        t0: float = time.perf_counter()
        t_raw: object = t["temporal_fn"]
        assert callable(t_raw)
        t_result: object = t_raw()
        t_ms: float = (time.perf_counter() - t0) * 1000

        # Normalize results
        t_ids: set[str]
        if isinstance(t_result, list) and t_result and isinstance(t_result[0], sqlite3.Row):
            t_ids = {r["id"] for r in t_result}
        elif isinstance(t_result, list):
            t_ids = set(t_result)
        else:
            t_ids = set()

        # Run search query
        s0: float = time.perf_counter()
        s_raw: object = t["search_fn"]
        assert callable(s_raw)
        s_result: object = s_raw()
        s_ms: float = (time.perf_counter() - s0) * 1000
        s_ids: set[str] = set(s_result) if isinstance(s_result, list) else set()

        overlap: int = len(t_ids & s_ids)
        t_only: int = len(t_ids - s_ids)
        s_only: int = len(s_ids - t_ids)

        qr: QueryResult = QueryResult(
            query_id=str(t["id"]),
            category=str(t["category"]),
            description=str(t["description"]),
            temporal_count=len(t_ids),
            search_count=len(s_ids),
            temporal_only=t_only,
            search_only=s_only,
            overlap=overlap,
            temporal_ms=t_ms,
            search_ms=s_ms,
            temporal_possible=True,
            search_possible=bool(t["search_possible"]),
        )
        results.append(qr)

        print(
            f"{qr.query_id:>4} {qr.category:>10} {qr.temporal_count:>9} {qr.search_count:>8} "
            f"{qr.temporal_only:>7} {qr.search_only:>7} {qr.overlap:>5} "
            f"{qr.temporal_ms:>7.1f} {qr.search_ms:>7.1f} "
            f"{'Y' if qr.search_possible else 'N':>6}"
        )

    # Summary
    impossible: int = sum(1 for r in results if not r.search_possible)
    temporal_unique_total: int = sum(r.temporal_only for r in results)
    search_unique_total: int = sum(r.search_only for r in results)

    print(f"\n=== Summary ===")
    print(f"Queries impossible with search: {impossible}/10")
    print(f"Total results only temporal found: {temporal_unique_total}")
    print(f"Total results only search found: {search_unique_total}")
    print(f"Avg temporal latency: {sum(r.temporal_ms for r in results)/len(results):.1f}ms")
    print(f"Avg search latency: {sum(r.search_ms for r in results)/len(results):.1f}ms")

    # Save results
    out: list[dict[str, object]] = [
        {
            "query_id": r.query_id,
            "category": r.category,
            "description": r.description,
            "temporal_count": r.temporal_count,
            "search_count": r.search_count,
            "temporal_only": r.temporal_only,
            "search_only": r.search_only,
            "overlap": r.overlap,
            "temporal_ms": round(r.temporal_ms, 2),
            "search_ms": round(r.search_ms, 2),
            "search_possible": r.search_possible,
        }
        for r in results
    ]
    out_path: Path = Path(__file__).parent / "exp74_temporal_vs_keyword_results.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nResults saved to {out_path}")

    conn.close()


if __name__ == "__main__":
    main()
