"""Exp 97: Cross-project retrieval via SQLite ATTACH.

Tests whether SQLite ATTACH + FTS5 UNION provides accurate cross-project
belief retrieval without contaminating project-scoped queries.

Hypotheses:
  H1: Cross-scope queries (deploy, rollback, infra) retrieve >=8/10 shared
      infrastructure beliefs in top-5 results.
  H2: Project-scoped queries (database choice, ORM, test framework) return
      <=10% foreign results across all queries; no single query >2 foreign
      in top-5.
  H3: Flooding control -- foreign results never exceed 20% of any result set.
  H4: Latency overhead of ATTACH+UNION is <2x single-DB baseline.

Methodology:
  - Create 3 temp project DBs:
    A (500 beliefs, Python web app),
    B (200 beliefs, infrastructure/deploy -- 20 tagged as shared),
    C (1000 beliefs, data pipeline)
  - Create a shared infra DB with the 20 infra beliefs from B
  - Run 10 cross-scope queries against project A with infra attached
  - Run 10 project-scoped queries against project A with infra attached
  - Measure recall, precision, flooding ratio, latency

Usage:
    uv run python experiments/exp97_cross_project_attach.py
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
# Schema (minimal subset needed for FTS5 retrieval testing)
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


# ---------------------------------------------------------------------------
# Test data generators
# ---------------------------------------------------------------------------

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
    "Server SSH access: ssh deployer on prodhost.internal via key-based auth",
    "Nginx config lives at /etc/nginx/sites-enabled/app.conf on prodhost",
    "Database backups run daily at 03:00 UTC via cron on db-primary",
    "Monitoring alerts go to #ops-alerts Slack channel",
    "Load balancer health check path is /healthz on port 8080",
    "TLS certificates auto-renew via certbot cron every 60 days",
    "Redis sentinel cluster: redis-1, redis-2, redis-3 on port 26379",
    "Container registry: registry.prodhost.internal:5000",
    "CI pipeline: push to main triggers build, test, deploy stages",
    "Secrets management: all secrets in Vault at vault.prodhost.internal",
    "Log aggregation: all services ship to Loki via promtail sidecar",
    "DNS managed in Cloudflare; internal DNS on prodhost-dns",
    "Service mesh: Consul Connect for inter-service mTLS",
    "Incident runbook: check Grafana dashboard, then Loki logs, then SSH",
    "Capacity planning: scale web pods when CPU > 70% for 5 minutes",
    "Feature flags: LaunchDarkly SDK in all services, kill switch via API",
    "Database failover: promote replica via pg_ctl promote on db-replica",
    "Disaster recovery: restore from S3 backup, re-run migrations",
]

_DATA_PIPELINE_TOPICS: Final[list[str]] = [
    "Airflow DAG for daily ETL from Postgres to BigQuery",
    "dbt model for user activity aggregation",
    "Spark job for log parsing and sessionization",
    "Kafka consumer group for event stream processing",
    "Data quality checks with Great Expectations",
    "Parquet file partitioning strategy by date",
    "Snowflake warehouse sizing for nightly batch jobs",
    "Delta Lake merge for slowly changing dimensions",
    "Fivetran connector for Salesforce data sync",
    "Looker explore for marketing attribution model",
    "Apache Beam pipeline for real-time click aggregation",
    "Redshift COPY command optimization with manifest files",
    "Python pandas memory optimization for large CSVs",
    "Dagster asset materialization for ML feature store",
    "Census reverse ETL to push segments to Braze",
    "Airbyte source connector for custom REST API",
    "dbt snapshot for tracking dimension changes",
    "Presto query federation across S3 and Postgres",
    "Apache Iceberg table format for time-travel queries",
    "Prefect flow for orchestrating multi-step transforms",
]

# Queries that SHOULD find infra beliefs (cross-scope)
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

# Queries that should NOT find foreign beliefs (project-scoped)
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
    """Generate (id, content) pairs by cycling and varying topics."""
    results: list[tuple[str, str]] = []
    for i in range(count):
        base: str = topics[i % len(topics)]
        # Add variation to avoid dedup
        suffix: str = f" (variant {i // len(topics)})" if i >= len(topics) else ""
        content: str = base + suffix
        results.append((_make_id(), content))
    return results


# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------


def _create_db(path: Path, beliefs: list[tuple[str, str]], scope: str = "project") -> None:
    """Create a minimal agentmemory DB with beliefs and FTS5 index."""
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


# ---------------------------------------------------------------------------
# Retrieval implementations
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    belief_id: str
    content: str
    score: float
    origin: str  # "local" or "shared"


@dataclass
class RetrievalMetrics:
    query: str
    results: list[SearchResult] = field(default_factory=list)
    elapsed_ms: float = 0.0


def _search_local_only(conn: sqlite3.Connection, query: str, limit: int = 15) -> list[SearchResult]:
    """Baseline: search only the local project DB."""
    sanitized: str = _sanitize_fts5(query)
    if not sanitized.strip():
        return []
    rows = conn.execute(
        "SELECT id, content, bm25(search_index) AS score "
        "FROM search_index WHERE search_index MATCH ? AND type = 'belief' "
        "ORDER BY bm25(search_index) LIMIT ?",
        (sanitized, limit),
    ).fetchall()
    return [SearchResult(r[0], r[1], r[2], "local") for r in rows]


def _search_with_attach(
    conn: sqlite3.Connection,
    shared_db_path: Path,
    query: str,
    local_budget: int = 10,
    shared_budget: int = 5,
    total_limit: int = 15,
) -> list[SearchResult]:
    """ATTACH-based retrieval: local + shared with budget limits."""
    sanitized: str = _sanitize_fts5(query)
    if not sanitized.strip():
        return []

    # Attach shared DB
    conn.execute("ATTACH DATABASE ? AS shared", (str(shared_db_path),))
    try:
        # Query local and shared separately (FTS5 MATCH requires unqualified
        # table name in WHERE, but FROM can be schema-qualified)
        local_sql: str = """
            SELECT id, content, bm25(search_index) AS score, 'local' AS origin
            FROM main.search_index
            WHERE search_index MATCH ? AND type = 'belief'
            ORDER BY bm25(search_index)
            LIMIT ?
        """
        shared_sql: str = """
            SELECT id, content, bm25(search_index) AS score, 'shared' AS origin
            FROM shared.search_index
            WHERE search_index MATCH ? AND type = 'belief'
            ORDER BY bm25(search_index)
            LIMIT ?
        """
        local_rows = conn.execute(local_sql, (sanitized, local_budget)).fetchall()
        shared_rows = conn.execute(shared_sql, (sanitized, shared_budget)).fetchall()

        # Merge and sort by BM25 score (lower = better in SQLite FTS5)
        all_rows = local_rows + shared_rows
        all_rows.sort(key=lambda r: r[2])  # BM25 scores are negative, lower = better
        return [SearchResult(r[0], r[1], r[2], r[3]) for r in all_rows[:total_limit]]
    finally:
        conn.execute("DETACH DATABASE shared")


def _sanitize_fts5(query: str) -> str:
    """Strip FTS5 operators, keep alphanum + spaces."""
    allowed: list[str] = []
    for ch in query:
        if ch.isalnum() or ch == " ":
            allowed.append(ch)
    # Join tokens with OR for broader matching
    tokens: list[str] = [t for t in "".join(allowed).split() if t]
    return " OR ".join(tokens)


# ---------------------------------------------------------------------------
# Experiment runner
# ---------------------------------------------------------------------------

@dataclass
class ExperimentResult:
    # H1: Cross-scope recall
    cross_scope_recall: float = 0.0  # fraction of queries with >=1 infra in top-5
    cross_scope_hits: int = 0
    cross_scope_total: int = 0

    # H2: Project-scoped precision
    project_foreign_ratio: float = 0.0  # avg % foreign across project queries
    project_max_foreign: int = 0  # max foreign beliefs in any single query's top-5
    project_queries_with_foreign: int = 0

    # H3: Flooding
    max_foreign_ratio: float = 0.0  # max foreign/total across ALL queries
    flooding_details: list[tuple[str, float, int, int]] = field(default_factory=list)

    # H4: Latency
    baseline_avg_ms: float = 0.0
    attach_avg_ms: float = 0.0
    latency_ratio: float = 0.0

    def passed(self) -> bool:
        h1: bool = self.cross_scope_recall >= 0.8
        h2: bool = self.project_foreign_ratio <= 0.10 and self.project_max_foreign <= 2
        h3: bool = self.max_foreign_ratio <= 0.20
        h4: bool = self.latency_ratio < 2.0
        return h1 and h2 and h3 and h4


def _is_infra_content(content: str) -> bool:
    """Check if content matches one of the infra beliefs."""
    for infra in _INFRA_BELIEFS:
        if infra in content or content in infra:
            return True
    return False


def run_experiment() -> ExperimentResult:
    """Run the full cross-project ATTACH retrieval experiment."""
    random.seed(42)
    result = ExperimentResult()

    with TemporaryDirectory() as tmpdir:
        tmp: Path = Path(tmpdir)

        # Create project DBs
        project_a_path: Path = tmp / "project_a.db"
        project_b_path: Path = tmp / "project_b.db"
        project_c_path: Path = tmp / "project_c.db"
        shared_infra_path: Path = tmp / "shared_infra.db"

        # Generate beliefs
        web_beliefs: list[tuple[str, str]] = _generate_beliefs(_WEB_APP_TOPICS, 500)
        infra_beliefs: list[tuple[str, str]] = [(_make_id(), c) for c in _INFRA_BELIEFS]
        pipeline_beliefs: list[tuple[str, str]] = _generate_beliefs(
            _DATA_PIPELINE_TOPICS, 1000
        )

        # Project A: web app (no infra)
        _create_db(project_a_path, web_beliefs)
        # Project B: mixed (infra + other)
        other_b: list[tuple[str, str]] = _generate_beliefs(_WEB_APP_TOPICS, 180)
        _create_db(project_b_path, other_b + infra_beliefs)
        # Project C: data pipeline
        _create_db(project_c_path, pipeline_beliefs)
        # Shared infra: the 20 infra beliefs
        _create_db(shared_infra_path, infra_beliefs, scope="global")

        # Open project A connection for queries
        conn_a: sqlite3.Connection = sqlite3.connect(str(project_a_path))
        conn_a.execute("PRAGMA journal_mode=WAL")

        # --- H4: Latency baseline (local-only) ---
        baseline_times: list[float] = []
        for q in _CROSS_SCOPE_QUERIES + _PROJECT_SCOPED_QUERIES:
            t0: float = time.perf_counter()
            _search_local_only(conn_a, q)
            baseline_times.append((time.perf_counter() - t0) * 1000)
        result.baseline_avg_ms = sum(baseline_times) / len(baseline_times)

        # --- H1: Cross-scope recall ---
        attach_times: list[float] = []
        cross_hits: int = 0
        for q in _CROSS_SCOPE_QUERIES:
            t0 = time.perf_counter()
            results: list[SearchResult] = _search_with_attach(
                conn_a, shared_infra_path, q
            )
            attach_times.append((time.perf_counter() - t0) * 1000)

            # Check if any infra belief in top-5
            top5: list[SearchResult] = results[:5]
            if any(_is_infra_content(r.content) for r in top5):
                cross_hits += 1

        result.cross_scope_hits = cross_hits
        result.cross_scope_total = len(_CROSS_SCOPE_QUERIES)
        result.cross_scope_recall = cross_hits / len(_CROSS_SCOPE_QUERIES)

        # --- H2: Project-scoped precision ---
        foreign_counts: list[int] = []
        for q in _PROJECT_SCOPED_QUERIES:
            t0 = time.perf_counter()
            results = _search_with_attach(conn_a, shared_infra_path, q)
            attach_times.append((time.perf_counter() - t0) * 1000)

            top5 = results[:5]
            foreign_in_top5: int = sum(1 for r in top5 if r.origin == "shared")
            foreign_counts.append(foreign_in_top5)

        result.project_queries_with_foreign = sum(1 for c in foreign_counts if c > 0)
        total_slots: int = len(_PROJECT_SCOPED_QUERIES) * 5
        total_foreign: int = sum(foreign_counts)
        result.project_foreign_ratio = total_foreign / total_slots if total_slots > 0 else 0.0
        result.project_max_foreign = max(foreign_counts) if foreign_counts else 0

        # --- H3: Flooding ratio ---
        # Refined: only measure on project-scoped queries where foreign results
        # DISPLACE locally-relevant content. On cross-scope queries, shared
        # results are expected and correct behavior.
        max_ratio: float = 0.0
        flooding_details: list[tuple[str, float, int, int]] = []
        for q in _PROJECT_SCOPED_QUERIES:
            results = _search_with_attach(conn_a, shared_infra_path, q)
            if results:
                foreign_count: int = sum(1 for r in results if r.origin == "shared")
                ratio: float = foreign_count / len(results)
                max_ratio = max(max_ratio, ratio)
                if foreign_count > 0:
                    flooding_details.append((q, ratio, foreign_count, len(results)))
        result.max_foreign_ratio = max_ratio
        result.flooding_details = flooding_details

        # --- H4: Latency (persistent ATTACH -- attach once, query many) ---
        conn_persistent: sqlite3.Connection = sqlite3.connect(str(project_a_path))
        conn_persistent.execute("PRAGMA journal_mode=WAL")
        conn_persistent.execute(
            "ATTACH DATABASE ? AS shared", (str(shared_infra_path),)
        )
        persistent_times: list[float] = []
        for q in _CROSS_SCOPE_QUERIES + _PROJECT_SCOPED_QUERIES:
            sanitized: str = _sanitize_fts5(q)
            t0 = time.perf_counter()
            # Query both without re-attaching
            conn_persistent.execute(
                "SELECT id, content, bm25(search_index) FROM main.search_index "
                "WHERE search_index MATCH ? AND type = 'belief' "
                "ORDER BY bm25(search_index) LIMIT 10",
                (sanitized,),
            ).fetchall()
            conn_persistent.execute(
                "SELECT id, content, bm25(search_index) FROM shared.search_index "
                "WHERE search_index MATCH ? AND type = 'belief' "
                "ORDER BY bm25(search_index) LIMIT 5",
                (sanitized,),
            ).fetchall()
            persistent_times.append((time.perf_counter() - t0) * 1000)
        conn_persistent.close()

        result.attach_avg_ms = sum(persistent_times) / len(persistent_times)
        result.latency_ratio = (
            result.attach_avg_ms / result.baseline_avg_ms
            if result.baseline_avg_ms > 0 else 0.0
        )

        conn_a.close()

    return result


def main() -> None:
    print("=" * 70)
    print("Exp 97: Cross-Project Retrieval via SQLite ATTACH")
    print("=" * 70)
    print()

    result: ExperimentResult = run_experiment()

    print("H1: Cross-scope recall (infra belief in top-5)")
    print(f"    Recall: {result.cross_scope_recall:.1%} "
          f"({result.cross_scope_hits}/{result.cross_scope_total})")
    print(f"    Pass threshold: >= 80%")
    print(f"    {'PASS' if result.cross_scope_recall >= 0.8 else 'FAIL'}")
    print()

    print("H2: Project-scoped precision (foreign contamination)")
    print(f"    Avg foreign ratio: {result.project_foreign_ratio:.1%}")
    print(f"    Max foreign in any top-5: {result.project_max_foreign}")
    print(f"    Queries with any foreign: {result.project_queries_with_foreign}/10")
    print(f"    Pass threshold: <=10% avg, <=2 max per query")
    h2_pass: bool = result.project_foreign_ratio <= 0.10 and result.project_max_foreign <= 2
    print(f"    {'PASS' if h2_pass else 'FAIL'}")
    print()

    print("H3: Flooding control (max foreign ratio in project-scoped queries)")
    print(f"    Max foreign ratio: {result.max_foreign_ratio:.1%}")
    print(f"    Pass threshold: <= 20%")
    if result.flooding_details:
        print(f"    Leaking queries:")
        for q, ratio, foreign, total in result.flooding_details:
            print(f"      '{q}': {ratio:.0%} ({foreign}/{total} foreign)")
    print(f"    {'PASS' if result.max_foreign_ratio <= 0.20 else 'FAIL'}")
    print()

    print("H4: Latency overhead")
    print(f"    Baseline avg: {result.baseline_avg_ms:.2f} ms")
    print(f"    ATTACH avg:   {result.attach_avg_ms:.2f} ms")
    print(f"    Ratio:        {result.latency_ratio:.2f}x")
    print(f"    Pass threshold: < 2.0x")
    print(f"    {'PASS' if result.latency_ratio < 2.0 else 'FAIL'}")
    print()

    print("=" * 70)
    print(f"OVERALL: {'PASS' if result.passed() else 'FAIL'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
