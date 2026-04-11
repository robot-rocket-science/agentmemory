"""Tests for MemoryStore: schema, CRUD, dedup, locking, FTS5, sessions, benchmarks."""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Generator
from pathlib import Path

import pytest

from agentmemory.models import (
    BELIEF_FACTUAL,
    BELIEF_PREFERENCE,
    BSRC_AGENT_INFERRED,
    BSRC_USER_STATED,
    OBS_TYPE_DECISION,
    OBS_TYPE_USER_STATEMENT,
    OUTCOME_HARMFUL,
    OUTCOME_USED,
    SRC_AGENT,
    SRC_USER,
)
from agentmemory.store import MemoryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    s: MemoryStore = MemoryStore(tmp_path / "test.db")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# 1. Database creation and schema
# ---------------------------------------------------------------------------


def test_schema_tables_exist(store: MemoryStore) -> None:
    """All expected tables must be present after init."""
    rows: list[sqlite3.Row] = store.query(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables: list[str] = [row[0] for row in rows]
    for expected in [
        "observations",
        "beliefs",
        "evidence",
        "edges",
        "sessions",
        "checkpoints",
        "tests",
        "audit_log",
    ]:
        assert expected in tables, f"Missing table: {expected}"


def test_fts5_virtual_table_exists(store: MemoryStore) -> None:
    """FTS5 search_index virtual table must exist."""
    rows: list[sqlite3.Row] = store.query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='search_index'"
    )
    vtables: list[str] = [row[0] for row in rows]
    assert "search_index" in vtables


def test_wal_mode(store: MemoryStore) -> None:
    """Database must be in WAL journal mode."""
    rows: list[sqlite3.Row] = store.query("PRAGMA journal_mode")
    assert rows[0][0] == "wal"


# ---------------------------------------------------------------------------
# 2. Observation insert + dedup
# ---------------------------------------------------------------------------


def test_observation_insert(store: MemoryStore) -> None:
    obs = store.insert_observation(
        content="User wants strict typing everywhere",
        observation_type=OBS_TYPE_USER_STATEMENT,
        source_type=SRC_USER,
    )
    assert obs.id
    assert obs.content == "User wants strict typing everywhere"
    assert obs.content_hash
    assert obs.created_at


def test_observation_dedup_same_content(store: MemoryStore) -> None:
    """Inserting identical content twice returns the same observation ID."""
    content: str = "The build system is uv"
    obs1 = store.insert_observation(content, OBS_TYPE_USER_STATEMENT, SRC_USER)
    obs2 = store.insert_observation(content, OBS_TYPE_USER_STATEMENT, SRC_USER)
    assert obs1.id == obs2.id


def test_observation_different_content_different_id(store: MemoryStore) -> None:
    obs1 = store.insert_observation("content A", OBS_TYPE_DECISION, SRC_AGENT)
    obs2 = store.insert_observation("content B", OBS_TYPE_DECISION, SRC_AGENT)
    assert obs1.id != obs2.id


def test_observation_appears_in_search_index(store: MemoryStore) -> None:
    store.insert_observation(
        content="agent crashed due to memory overflow",
        observation_type=OBS_TYPE_DECISION,
        source_type=SRC_AGENT,
    )
    rows: list[sqlite3.Row] = store.query(
        "SELECT type FROM search_index WHERE type='observation' LIMIT 1"
    )
    assert len(rows) > 0
    assert rows[0][0] == "observation"


# ---------------------------------------------------------------------------
# 3. Observation immutability
# ---------------------------------------------------------------------------


def test_observation_no_update_path(store: MemoryStore) -> None:
    """There is no public API to modify an observation after insertion."""
    obs = store.insert_observation("immutable fact", OBS_TYPE_USER_STATEMENT, SRC_USER)
    # Confirm no method named update_observation or delete_observation exists
    assert not hasattr(store, "update_observation")
    assert not hasattr(store, "delete_observation")
    # The stored content must be unchanged
    rows: list[sqlite3.Row] = store.query(
        "SELECT content FROM observations WHERE id = ?", (obs.id,)
    )
    assert len(rows) == 1
    assert rows[0][0] == "immutable fact"


# ---------------------------------------------------------------------------
# 4. Belief insert + dedup
# ---------------------------------------------------------------------------


def test_belief_insert(store: MemoryStore) -> None:
    belief = store.insert_belief(
        content="User prefers dataclasses over Pydantic",
        belief_type=BELIEF_PREFERENCE,
        source_type=BSRC_USER_STATED,
    )
    assert belief.id
    assert abs(belief.confidence - 0.5) < 1e-9
    assert belief.locked is False
    assert belief.valid_to is None
    assert belief.superseded_by is None


def test_belief_dedup_same_content(store: MemoryStore) -> None:
    """Same content returns the same belief ID."""
    content: str = "Python version is 3.12"
    b1 = store.insert_belief(content, BELIEF_FACTUAL, BSRC_USER_STATED)
    b2 = store.insert_belief(content, BELIEF_FACTUAL, BSRC_USER_STATED)
    assert b1.id == b2.id


def test_belief_with_observation_evidence(store: MemoryStore) -> None:
    obs = store.insert_observation("user said pyright strict", OBS_TYPE_USER_STATEMENT, SRC_USER)
    belief = store.insert_belief(
        content="Pyright strict mode is required",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        observation_id=obs.id,
    )
    rows: list[sqlite3.Row] = store.query(
        "SELECT observation_id, relationship FROM evidence WHERE belief_id = ?",
        (belief.id,),
    )
    assert len(rows) == 1
    assert rows[0]["observation_id"] == obs.id
    assert rows[0]["relationship"] == "supports"


def test_belief_appears_in_search_index(store: MemoryStore) -> None:
    store.insert_belief(
        content="Always use uv package manager",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
    )
    rows: list[sqlite3.Row] = store.query(
        "SELECT type FROM search_index WHERE type='belief' LIMIT 1"
    )
    assert len(rows) > 0
    assert rows[0][0] == "belief"


# ---------------------------------------------------------------------------
# 5. Belief locking
# ---------------------------------------------------------------------------


def test_lock_belief(store: MemoryStore) -> None:
    belief = store.insert_belief("strict typing always", BELIEF_FACTUAL, BSRC_USER_STATED)
    store.lock_belief(belief.id)
    updated = store.get_belief(belief.id)
    assert updated is not None
    assert updated.locked is True


def test_locked_belief_confidence_cannot_decrease(store: MemoryStore) -> None:
    """Applying 'harmful' outcome to a locked belief must not reduce confidence."""
    belief = store.insert_belief(
        "use uv always", BELIEF_FACTUAL, BSRC_USER_STATED,
        alpha=10.0, beta_param=1.0
    )
    store.lock_belief(belief.id)
    original_beta: float = belief.beta_param

    store.update_confidence(belief.id, OUTCOME_HARMFUL, weight=5.0)

    updated = store.get_belief(belief.id)
    assert updated is not None
    assert abs(updated.beta_param - original_beta) < 1e-9, (
        "Locked belief beta_param must not increase on harmful outcome"
    )


def test_unlocked_belief_confidence_decreases_on_harmful(store: MemoryStore) -> None:
    belief = store.insert_belief(
        "agent should cache results", BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        alpha=5.0, beta_param=1.0
    )
    store.update_confidence(belief.id, OUTCOME_HARMFUL, weight=2.0)
    updated = store.get_belief(belief.id)
    assert updated is not None
    assert abs(updated.beta_param - 3.0) < 1e-9


def test_used_outcome_increases_alpha(store: MemoryStore) -> None:
    belief = store.insert_belief(
        "use pytest for tests", BELIEF_FACTUAL, BSRC_USER_STATED,
        alpha=2.0, beta_param=1.0
    )
    store.update_confidence(belief.id, OUTCOME_USED, weight=1.0)
    updated = store.get_belief(belief.id)
    assert updated is not None
    assert abs(updated.alpha - 3.0) < 1e-9


# ---------------------------------------------------------------------------
# 6. Belief supersession
# ---------------------------------------------------------------------------


def test_supersede_belief(store: MemoryStore) -> None:
    old = store.insert_belief("Python 3.11 is required", BELIEF_FACTUAL, BSRC_USER_STATED)
    new = store.insert_belief("Python 3.12 is required", BELIEF_FACTUAL, BSRC_USER_STATED)

    store.supersede_belief(old.id, new.id, "version requirement updated")

    old_updated = store.get_belief(old.id)
    assert old_updated is not None
    assert old_updated.valid_to is not None, "Old belief must have valid_to set"
    assert old_updated.superseded_by == new.id


def test_supersede_creates_edge(store: MemoryStore) -> None:
    old = store.insert_belief("SQLite WAL off", BELIEF_FACTUAL, BSRC_USER_STATED)
    new = store.insert_belief("SQLite WAL on", BELIEF_FACTUAL, BSRC_USER_STATED)
    store.supersede_belief(old.id, new.id, "WAL enabled by design")

    rows: list[sqlite3.Row] = store.query(
        "SELECT id FROM edges WHERE from_id = ? AND to_id = ? AND edge_type = 'SUPERSEDES'",
        (new.id, old.id),
    )
    assert len(rows) > 0


def test_superseded_beliefs_excluded_from_search(store: MemoryStore) -> None:
    old = store.insert_belief(
        "project requires PostgreSQL", BELIEF_FACTUAL, BSRC_USER_STATED
    )
    new = store.insert_belief(
        "project requires SQLite", BELIEF_FACTUAL, BSRC_USER_STATED
    )
    store.supersede_belief(old.id, new.id, "switched to SQLite")

    results = store.search("project requires")
    result_ids = [b.id for b in results]
    assert old.id not in result_ids, "Superseded belief must not appear in search"
    assert new.id in result_ids, "Active belief must appear in search"


# ---------------------------------------------------------------------------
# 7. FTS5 search
# ---------------------------------------------------------------------------


def test_fts5_search_returns_ranked_results(store: MemoryStore) -> None:
    """Insert 10 beliefs, search, verify relevant results are returned."""
    topics: list[tuple[str, str]] = [
        ("user prefers strict type annotations in all Python code", BSRC_USER_STATED),
        ("use dataclasses not Pydantic for data models", BSRC_USER_STATED),
        ("always use uv package manager for Python projects", BSRC_USER_STATED),
        ("pyright strict mode must be enabled", BSRC_USER_STATED),
        ("SQLite WAL mode for crash safety", BSRC_USER_STATED),
        ("FTS5 search index for text retrieval", BSRC_AGENT_INFERRED),
        ("Bayesian confidence update on belief feedback", BSRC_AGENT_INFERRED),
        ("session checkpoints are synchronous writes", BSRC_USER_STATED),
        ("content hash deduplication prevents duplicate storage", BSRC_AGENT_INFERRED),
        ("Beta distribution models belief confidence", BSRC_AGENT_INFERRED),
    ]
    for content, src in topics:
        store.insert_belief(content, BELIEF_FACTUAL, src)

    results = store.search("Python type annotations strict", top_k=5)
    assert len(results) > 0
    top_contents = [b.content for b in results]
    assert any("type" in c or "strict" in c for c in top_contents)


def test_fts5_search_excludes_superseded(store: MemoryStore) -> None:
    old = store.insert_belief("project uses pip", BELIEF_FACTUAL, BSRC_USER_STATED)
    new = store.insert_belief("project uses uv", BELIEF_FACTUAL, BSRC_USER_STATED)
    store.supersede_belief(old.id, new.id, "switched to uv")

    results = store.search("project uses")
    ids = [b.id for b in results]
    assert old.id not in ids


def test_search_observations(store: MemoryStore) -> None:
    store.insert_observation("agent crashed with OOM error", OBS_TYPE_DECISION, SRC_AGENT)
    store.insert_observation("user approved the plan", OBS_TYPE_USER_STATEMENT, SRC_USER)
    results = store.search_observations("crashed OOM", top_k=5)
    assert len(results) > 0
    assert any("crash" in r.content or "OOM" in r.content for r in results)


def test_get_locked_beliefs(store: MemoryStore) -> None:
    b1 = store.insert_belief("locked rule 1", BELIEF_FACTUAL, BSRC_USER_STATED)
    b2 = store.insert_belief("unlocked belief", BELIEF_FACTUAL, BSRC_AGENT_INFERRED)
    store.lock_belief(b1.id)

    locked = store.get_locked_beliefs()
    ids = [b.id for b in locked]
    assert b1.id in ids
    assert b2.id not in ids


# ---------------------------------------------------------------------------
# 8. Session lifecycle
# ---------------------------------------------------------------------------


def test_create_session(store: MemoryStore) -> None:
    session = store.create_session(model="claude-sonnet-4-6", project_context="agentmemory")
    assert session.id
    assert session.started_at
    assert session.completed_at is None
    assert session.model == "claude-sonnet-4-6"


def test_checkpoint_write(store: MemoryStore) -> None:
    session = store.create_session()
    ckpt = store.checkpoint(
        session.id,
        checkpoint_type="decision",
        content="Decided to use SQLite for storage",
        references=["abc123", "def456"],
    )
    assert ckpt.id > 0
    assert ckpt.session_id == session.id
    refs = json.loads(ckpt.references)
    assert refs == ["abc123", "def456"]


def test_complete_session(store: MemoryStore) -> None:
    session = store.create_session()
    store.complete_session(session.id, summary="Completed phase 1")
    rows: list[sqlite3.Row] = store.query(
        "SELECT completed_at, summary FROM sessions WHERE id = ?", (session.id,)
    )
    assert len(rows) == 1
    assert rows[0]["completed_at"] is not None
    assert rows[0]["summary"] == "Completed phase 1"


def test_get_session_checkpoints(store: MemoryStore) -> None:
    session = store.create_session()
    store.checkpoint(session.id, "goal", "Implement SQLite store")
    store.checkpoint(session.id, "decision", "Use WAL mode")
    store.checkpoint(session.id, "file_change", "Created store.py")

    checkpoints = store.get_session_checkpoints(session.id)
    assert len(checkpoints) == 3
    assert checkpoints[0].checkpoint_type == "goal"
    assert checkpoints[2].checkpoint_type == "file_change"


# ---------------------------------------------------------------------------
# 9. Incomplete session detection
# ---------------------------------------------------------------------------


def test_find_incomplete_sessions(store: MemoryStore) -> None:
    s1 = store.create_session(model="claude-a")
    s2 = store.create_session(model="claude-b")
    store.complete_session(s2.id, "done")

    incomplete = store.find_incomplete_sessions()
    ids = [s.id for s in incomplete]
    assert s1.id in ids
    assert s2.id not in ids


def test_no_incomplete_sessions_when_all_complete(store: MemoryStore) -> None:
    s = store.create_session()
    store.complete_session(s.id)
    assert store.find_incomplete_sessions() == []


# ---------------------------------------------------------------------------
# 10. Checkpoint write latency benchmark
# ---------------------------------------------------------------------------


def test_checkpoint_write_latency_p95(store: MemoryStore) -> None:
    """100 checkpoint writes: p95 latency must be under 50ms."""
    session = store.create_session()
    latencies: list[float] = []

    for i in range(100):
        start: float = time.perf_counter()
        store.checkpoint(
            session.id,
            checkpoint_type="task_state",
            content=f"Checkpoint number {i}: processing step {i * 2}",
            references=[f"ref{i}"],
        )
        end: float = time.perf_counter()
        latencies.append((end - start) * 1000)  # ms

    latencies.sort()
    p95_ms: float = latencies[94]  # 95th percentile (0-indexed: index 94)
    assert p95_ms < 50.0, f"p95 checkpoint latency {p95_ms:.2f}ms exceeds 50ms limit"


# ---------------------------------------------------------------------------
# 11. Status counts
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 11a. Temporal date passthrough
# ---------------------------------------------------------------------------


def test_belief_created_at_passthrough(store: MemoryStore) -> None:
    """Inserting a belief with a historical created_at should preserve that timestamp."""
    historical_ts: str = "2024-01-15T10:30:00+00:00"
    belief = store.insert_belief(
        content="Project started with SQLite",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        created_at=historical_ts,
    )
    assert belief.created_at == historical_ts

    # Verify via raw SQL too
    rows: list[sqlite3.Row] = store.query(
        "SELECT created_at FROM beliefs WHERE id = ?", (belief.id,)
    )
    assert len(rows) == 1
    assert rows[0][0] == historical_ts


def test_decay_factor_old_factual_belief(store: MemoryStore) -> None:
    """An old factual belief should have decay_factor < 1.0."""
    from agentmemory.scoring import decay_factor

    historical_ts: str = "2024-01-01T00:00:00+00:00"
    belief = store.insert_belief(
        content="Old factual belief for decay test",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        created_at=historical_ts,
    )
    # Current time is ~2 years after creation; factual half-life is 336h (14 days)
    current_ts: str = "2026-04-11T00:00:00+00:00"
    d: float = decay_factor(belief, current_ts)
    assert d < 1.0, f"Expected decay < 1.0 for old factual belief, got {d}"
    # After 2 years the decay should be extremely small
    assert d < 0.01, f"Expected near-zero decay for 2-year-old factual belief, got {d}"


def test_decay_factor_locked_belief_always_one(store: MemoryStore) -> None:
    """A locked belief should always return decay_factor 1.0 regardless of age."""
    from agentmemory.scoring import decay_factor

    historical_ts: str = "2020-01-01T00:00:00+00:00"
    belief = store.insert_belief(
        content="Locked belief should not decay",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        locked=True,
        created_at=historical_ts,
    )
    current_ts: str = "2026-04-11T00:00:00+00:00"
    d: float = decay_factor(belief, current_ts)
    assert d == 1.0, f"Expected decay=1.0 for locked belief, got {d}"


# ---------------------------------------------------------------------------
# 11b. Session metrics increment
# ---------------------------------------------------------------------------


def test_increment_session_metrics(store: MemoryStore) -> None:
    """increment_session_metrics should add to existing counters, not replace."""
    session = store.create_session(model="test-model")

    store.increment_session_metrics(
        session.id,
        retrieval_tokens=100,
        classification_tokens=50,
        beliefs_created=3,
        corrections_detected=1,
        searches_performed=2,
        feedback_given=1,
    )

    s1 = store.get_session(session.id)
    assert s1 is not None
    assert s1.retrieval_tokens == 100
    assert s1.classification_tokens == 50
    assert s1.beliefs_created == 3
    assert s1.corrections_detected == 1
    assert s1.searches_performed == 2
    assert s1.feedback_given == 1

    # Increment again -- values should accumulate
    store.increment_session_metrics(
        session.id,
        retrieval_tokens=200,
        classification_tokens=75,
        beliefs_created=2,
        corrections_detected=0,
        searches_performed=1,
        feedback_given=3,
    )

    s2 = store.get_session(session.id)
    assert s2 is not None
    assert s2.retrieval_tokens == 300
    assert s2.classification_tokens == 125
    assert s2.beliefs_created == 5
    assert s2.corrections_detected == 1
    assert s2.searches_performed == 3
    assert s2.feedback_given == 4


def test_increment_session_metrics_partial(store: MemoryStore) -> None:
    """Incrementing only some counters should leave others at zero."""
    session = store.create_session()

    store.increment_session_metrics(session.id, beliefs_created=7)

    s = store.get_session(session.id)
    assert s is not None
    assert s.beliefs_created == 7
    assert s.retrieval_tokens == 0
    assert s.classification_tokens == 0
    assert s.corrections_detected == 0
    assert s.searches_performed == 0
    assert s.feedback_given == 0


# ---------------------------------------------------------------------------
# 12. Status counts
# ---------------------------------------------------------------------------


def test_status_counts(store: MemoryStore) -> None:
    store.insert_observation("obs1", OBS_TYPE_USER_STATEMENT, SRC_USER)
    store.insert_observation("obs2", OBS_TYPE_DECISION, SRC_AGENT)
    b1 = store.insert_belief("belief1", BELIEF_FACTUAL, BSRC_USER_STATED)
    store.insert_belief("belief2", BELIEF_PREFERENCE, BSRC_AGENT_INFERRED)
    store.lock_belief(b1.id)
    store.create_session()

    stats = store.status()
    assert stats["observations"] == 2
    assert stats["beliefs"] == 2
    assert stats["locked"] == 1
    assert stats["superseded"] == 0
    assert stats["sessions"] == 1
