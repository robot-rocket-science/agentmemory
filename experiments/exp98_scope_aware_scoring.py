"""Exp 98: Scope-aware scoring for cross-project retrieval.

Builds on Exp 97 (ATTACH-based federated FTS5). Tests whether budget tuning
and score penalties prevent shared-scope results from flooding project-scoped
queries while maintaining recall on cross-scope queries.

Hypotheses:
  H1: Reducing shared budget from 5 to 3 eliminates flooding (foreign <=20%
      of full result set) without reducing cross-scope recall below 80%.
  H2: A BM25 score penalty (1.5x multiplier on shared results) further
      reduces foreign presence in project-scoped queries.
  H3: Reserved-slot allocation (top-12 local, then fill remaining from shared)
      provides best precision/recall tradeoff vs UNION approach.
  H4: Optimal configuration achieves >=90% cross-scope recall AND <=10%
      flooding in project-scoped queries simultaneously.

Methodology:
  - Reuse Exp 97 test data (500 web beliefs, 20 infra beliefs, 10+10 queries)
  - Test 4 configurations:
    Config A: Budget 10/5 (Exp 97 baseline)
    Config B: Budget 12/3 (tighter shared budget)
    Config C: Budget 10/5 + 1.5x score penalty on shared
    Config D: Reserved-slot (top-12 local guaranteed, shared fills remainder)
  - Measure recall, precision, flooding, and displacement per config

Usage:
    uv run python experiments/exp98_scope_aware_scoring.py
"""

from __future__ import annotations

import hashlib
import random
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

# ---------------------------------------------------------------------------
# Reuse Exp 97 schema and test data
# ---------------------------------------------------------------------------

_SCHEMA: Final[str] = """
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
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    scope TEXT NOT NULL DEFAULT 'project'
);

CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    id,
    content,
    type,
    tokenize='porter'
);
"""

_WEB_APP_TOPICS: Final[list[str]] = [
    "Django REST framework serializer for user model",
    "PostgreSQL connection pooling with pgbouncer",
    "Redis cache invalidation on user profile update",
    "Celery task queue for email sending",
    "JWT authentication middleware",
    "SQLAlchemy ORM session management",
    "Alembic migration for adding indexes",
    "pytest fixtures for database integration tests",
    "Docker compose for local development",
    "Nginx reverse proxy configuration",
    "CORS middleware configuration for React frontend",
    "Pydantic model validation for API inputs",
    "Rate limiting with token bucket algorithm",
    "WebSocket handler for real-time notifications",
    "OpenAPI schema generation from type hints",
    "Database query optimization with EXPLAIN ANALYZE",
    "Connection retry logic with exponential backoff",
    "Structured logging with structlog",
    "Health check endpoint returning DB status",
    "Background job scheduler for report generation",
]

_INFRA_BELIEFS: Final[list[str]] = [
    "Deploy to production: run scripts/deploy.sh --env prod --tag latest",
    "Rollback procedure: git revert HEAD && deploy.sh --env prod --force",
    "Server SSH access: ssh deploy@mintaka.internal -i ~/.ssh/deploy_key",
    "Nginx config lives at /etc/nginx/sites-enabled/app.conf on mintaka",
    "Database backups run daily at 03:00 UTC via cron on db-primary",
    "Monitoring alerts go to #ops-alerts Slack channel",
    "Load balancer health check path is /healthz on port 8080",
    "TLS certificates auto-renew via certbot cron every 60 days",
    "Redis sentinel cluster: redis-1, redis-2, redis-3 on port 26379",
    "Container registry: registry.mintaka.internal:5000",
    "CI pipeline: push to main triggers build, test, deploy stages",
    "Secrets management: all secrets in Vault at vault.mintaka.internal",
    "Log aggregation: all services ship to Loki via promtail sidecar",
    "DNS managed in Cloudflare; internal DNS on mintaka-dns",
    "Service mesh: Consul Connect for inter-service mTLS",
    "Incident runbook: check Grafana dashboard, then Loki logs, then SSH",
    "Capacity planning: scale web pods when CPU > 70% for 5 minutes",
    "Feature flags: LaunchDarkly SDK in all services, kill switch via API",
    "Database failover: promote replica via pg_ctl promote on db-replica",
    "Disaster recovery: restore from S3 backup, re-run migrations",
]

_CROSS_SCOPE_QUERIES: Final[list[str]] = [
    "how do I deploy to production",
    "rollback procedure",
    "server access SSH",
    "database backup schedule",
    "monitoring and alerting setup",
    "TLS certificate renewal",
    "container registry URL",
    "CI pipeline stages",
    "secrets management vault",
    "incident response runbook",
]

_PROJECT_SCOPED_QUERIES: Final[list[str]] = [
    "what database does this project use",
    "ORM session management",
    "test fixtures and pytest setup",
    "API serializer for user model",
    "cache invalidation strategy",
    "authentication middleware",
    "rate limiting configuration",
    "WebSocket real-time handler",
    "structured logging setup",
    "background job scheduling",
]


def _make_id() -> str:
    return hashlib.sha256(random.randbytes(16)).hexdigest()[:12]


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def _generate_beliefs(topics: list[str], count: int) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for i in range(count):
        base: str = topics[i % len(topics)]
        suffix: str = f" (variant {i // len(topics)})" if i >= len(topics) else ""
        results.append((_make_id(), base + suffix))
    return results


def _create_db(path: Path, beliefs: list[tuple[str, str]], scope: str = "project") -> None:
    conn: sqlite3.Connection = sqlite3.connect(str(path))
    conn.executescript(_SCHEMA)
    for belief_id, content in beliefs:
        conn.execute(
            "INSERT INTO beliefs (id, content_hash, content, belief_type, "
            "source_type, scope) VALUES (?, ?, ?, ?, ?, ?)",
            (belief_id, _content_hash(content), content, "factual",
             "agent_inferred", scope),
        )
        conn.execute(
            "INSERT INTO search_index (id, content, type) VALUES (?, ?, ?)",
            (belief_id, content, "belief"),
        )
    conn.commit()
    conn.close()


def _sanitize_fts5(query: str) -> str:
    allowed: list[str] = []
    for ch in query:
        if ch.isalnum() or ch == " ":
            allowed.append(ch)
    tokens: list[str] = [t for t in "".join(allowed).split() if t]
    return " OR ".join(tokens)


def _is_infra_content(content: str) -> bool:
    for infra in _INFRA_BELIEFS:
        if infra in content or content in infra:
            return True
    return False


# ---------------------------------------------------------------------------
# Retrieval configurations
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    belief_id: str
    content: str
    score: float
    origin: str  # "local" or "shared"


@dataclass
class ConfigResult:
    name: str
    cross_scope_recall: float = 0.0
    project_flood_max: float = 0.0
    project_flood_avg: float = 0.0
    avg_displacement: float = 0.0  # how many local results pushed out


def _query_config_a(
    conn: sqlite3.Connection, query: str, total: int = 15
) -> list[SearchResult]:
    """Config A: Budget 10 local / 5 shared, straight UNION."""
    sanitized: str = _sanitize_fts5(query)
    if not sanitized.strip():
        return []
    local = conn.execute(
        "SELECT id, content, bm25(search_index) AS score FROM main.search_index "
        "WHERE search_index MATCH ? AND type = 'belief' ORDER BY bm25(search_index) LIMIT 10",
        (sanitized,),
    ).fetchall()
    shared = conn.execute(
        "SELECT id, content, bm25(search_index) AS score FROM shared.search_index "
        "WHERE search_index MATCH ? AND type = 'belief' ORDER BY bm25(search_index) LIMIT 5",
        (sanitized,),
    ).fetchall()
    results = [SearchResult(r[0], r[1], r[2], "local") for r in local]
    results += [SearchResult(r[0], r[1], r[2], "shared") for r in shared]
    results.sort(key=lambda r: r.score)
    return results[:total]


def _query_config_b(
    conn: sqlite3.Connection, query: str, total: int = 15
) -> list[SearchResult]:
    """Config B: Budget 12 local / 3 shared, tighter shared allocation."""
    sanitized: str = _sanitize_fts5(query)
    if not sanitized.strip():
        return []
    local = conn.execute(
        "SELECT id, content, bm25(search_index) AS score FROM main.search_index "
        "WHERE search_index MATCH ? AND type = 'belief' ORDER BY bm25(search_index) LIMIT 12",
        (sanitized,),
    ).fetchall()
    shared = conn.execute(
        "SELECT id, content, bm25(search_index) AS score FROM shared.search_index "
        "WHERE search_index MATCH ? AND type = 'belief' ORDER BY bm25(search_index) LIMIT 3",
        (sanitized,),
    ).fetchall()
    results = [SearchResult(r[0], r[1], r[2], "local") for r in local]
    results += [SearchResult(r[0], r[1], r[2], "shared") for r in shared]
    results.sort(key=lambda r: r.score)
    return results[:total]


def _query_config_c(
    conn: sqlite3.Connection, query: str, total: int = 15
) -> list[SearchResult]:
    """Config C: Budget 10/5 + 1.5x score penalty on shared results."""
    sanitized: str = _sanitize_fts5(query)
    if not sanitized.strip():
        return []
    local = conn.execute(
        "SELECT id, content, bm25(search_index) AS score FROM main.search_index "
        "WHERE search_index MATCH ? AND type = 'belief' ORDER BY bm25(search_index) LIMIT 10",
        (sanitized,),
    ).fetchall()
    shared = conn.execute(
        "SELECT id, content, bm25(search_index) AS score FROM shared.search_index "
        "WHERE search_index MATCH ? AND type = 'belief' ORDER BY bm25(search_index) LIMIT 5",
        (sanitized,),
    ).fetchall()
    # BM25 scores are negative (lower = better). Penalty makes shared worse.
    # Multiply by 1.5 means more negative = pushed down in ranking.
    # Actually: BM25 in FTS5 returns negative values where MORE negative = better match.
    # So to penalize shared, we divide by penalty (make less negative = worse rank).
    penalty: float = 1.5
    results = [SearchResult(r[0], r[1], r[2], "local") for r in local]
    results += [SearchResult(r[0], r[1], r[2] / penalty, "shared") for r in shared]
    results.sort(key=lambda r: r.score)
    return results[:total]


def _query_config_d(
    conn: sqlite3.Connection, query: str, total: int = 15
) -> list[SearchResult]:
    """Config D: Reserved-slot -- top-12 always local, shared fills 13-15."""
    sanitized: str = _sanitize_fts5(query)
    if not sanitized.strip():
        return []
    local = conn.execute(
        "SELECT id, content, bm25(search_index) AS score FROM main.search_index "
        "WHERE search_index MATCH ? AND type = 'belief' ORDER BY bm25(search_index) LIMIT 12",
        (sanitized,),
    ).fetchall()
    shared = conn.execute(
        "SELECT id, content, bm25(search_index) AS score FROM shared.search_index "
        "WHERE search_index MATCH ? AND type = 'belief' ORDER BY bm25(search_index) LIMIT ?",
        (sanitized, total - len(local)),
    ).fetchall()
    # Local gets priority slots, shared fills remainder
    results = [SearchResult(r[0], r[1], r[2], "local") for r in local]
    results += [SearchResult(r[0], r[1], r[2], "shared") for r in shared]
    return results[:total]


# ---------------------------------------------------------------------------
# Experiment runner
# ---------------------------------------------------------------------------

_CONFIGS: Final[list[tuple[str, type]]] = [
    ("A: 10/5 UNION", "_query_config_a"),
    ("B: 12/3 tight", "_query_config_b"),
    ("C: 10/5 + penalty", "_query_config_c"),
    ("D: reserved-slot", "_query_config_d"),
]


def _evaluate_config(
    conn: sqlite3.Connection,
    query_fn: object,
    name: str,
) -> ConfigResult:
    """Evaluate a single retrieval config against all test queries."""
    result = ConfigResult(name=name)
    assert callable(query_fn)

    # Cross-scope recall
    hits: int = 0
    for q in _CROSS_SCOPE_QUERIES:
        results: list[SearchResult] = query_fn(conn, q)
        top5: list[SearchResult] = results[:5]
        if any(_is_infra_content(r.content) for r in top5):
            hits += 1
    result.cross_scope_recall = hits / len(_CROSS_SCOPE_QUERIES)

    # Project-scoped flooding
    flood_ratios: list[float] = []
    for q in _PROJECT_SCOPED_QUERIES:
        results = query_fn(conn, q)
        if results:
            foreign: int = sum(1 for r in results if r.origin == "shared")
            flood_ratios.append(foreign / len(results))
        else:
            flood_ratios.append(0.0)
    result.project_flood_max = max(flood_ratios) if flood_ratios else 0.0
    result.project_flood_avg = sum(flood_ratios) / len(flood_ratios) if flood_ratios else 0.0

    # Displacement: for project queries, how many of top-5 are shared?
    displacements: list[int] = []
    for q in _PROJECT_SCOPED_QUERIES:
        results = query_fn(conn, q)
        top5 = results[:5]
        displacements.append(sum(1 for r in top5 if r.origin == "shared"))
    result.avg_displacement = sum(displacements) / len(displacements) if displacements else 0.0

    return result


def run_experiment() -> list[ConfigResult]:
    random.seed(42)

    with TemporaryDirectory() as tmpdir:
        tmp: Path = Path(tmpdir)
        project_a_path: Path = tmp / "project_a.db"
        shared_infra_path: Path = tmp / "shared_infra.db"

        # Generate test data
        web_beliefs: list[tuple[str, str]] = _generate_beliefs(_WEB_APP_TOPICS, 500)
        infra_beliefs: list[tuple[str, str]] = [(_make_id(), c) for c in _INFRA_BELIEFS]

        _create_db(project_a_path, web_beliefs)
        _create_db(shared_infra_path, infra_beliefs, scope="global")

        # Open with persistent ATTACH
        conn: sqlite3.Connection = sqlite3.connect(str(project_a_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("ATTACH DATABASE ? AS shared", (str(shared_infra_path),))

        # Evaluate each config
        query_fns = [_query_config_a, _query_config_b, _query_config_c, _query_config_d]
        results: list[ConfigResult] = []
        for i, (name, _) in enumerate(_CONFIGS):
            cr: ConfigResult = _evaluate_config(conn, query_fns[i], name)
            results.append(cr)

        conn.close()

    return results


def main() -> None:
    print("=" * 70)
    print("Exp 98: Scope-Aware Scoring for Cross-Project Retrieval")
    print("=" * 70)
    print()

    results: list[ConfigResult] = run_experiment()

    # Results table
    print(f"{'Config':<22} {'Recall':>8} {'Flood Max':>10} {'Flood Avg':>10} {'Displace':>10}")
    print("-" * 62)
    for r in results:
        print(
            f"{r.name:<22} {r.cross_scope_recall:>7.0%} "
            f"{r.project_flood_max:>9.1%} {r.project_flood_avg:>9.1%} "
            f"{r.avg_displacement:>9.2f}"
        )
    print()

    # Determine best config (highest recall with flood_max <= 20%)
    passing: list[ConfigResult] = [r for r in results if r.project_flood_max <= 0.20]
    if passing:
        best: ConfigResult = max(passing, key=lambda r: r.cross_scope_recall)
        print(f"Best config (flood <= 20%): {best.name}")
        print(f"  Recall: {best.cross_scope_recall:.0%}")
        print(f"  Flood max: {best.project_flood_max:.1%}")
        print(f"  Displacement: {best.avg_displacement:.2f}")
    else:
        print("No config achieves <= 20% flooding. Need stronger controls.")

    print()
    # H4: Does any config achieve >=90% recall AND <=10% flooding?
    h4_pass: list[ConfigResult] = [
        r for r in results
        if r.cross_scope_recall >= 0.90 and r.project_flood_max <= 0.10
    ]
    print(f"H4 (>=90% recall + <=10% flooding): "
          f"{'PASS' if h4_pass else 'FAIL'}")
    if h4_pass:
        for r in h4_pass:
            print(f"  {r.name}: recall={r.cross_scope_recall:.0%}, "
                  f"flood={r.project_flood_max:.1%}")

    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
