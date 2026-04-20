"""Tests for anonymous telemetry snapshot collection.

Verifies that:
1. Snapshots contain only content-free metrics (no PII)
2. Session metrics are correctly extracted
3. Rolling windows aggregate properly
4. JSONL output format is correct
5. Telemetry can be disabled via config
6. Send-telemetry offset tracking and payload construction
"""
from __future__ import annotations

import json
from pathlib import Path

from agentmemory.models import BELIEF_FACTUAL, BSRC_AGENT_INFERRED, BSRC_USER_STATED, Belief
from agentmemory.store import MemoryStore
from agentmemory.telemetry import (
    collect_belief_metrics,
    collect_feedback_metrics,
    collect_graph_metrics,
    collect_rolling_window,
    collect_session_metrics,
    collect_snapshot,
    get_unsent_lines,
    mark_sent,
    write_snapshot,
)


def _setup_store(tmp_path: Path) -> tuple[MemoryStore, str]:
    """Create a store with a session and some beliefs for testing."""
    db: Path = tmp_path / "test.db"
    store: MemoryStore = MemoryStore(db)
    session = store.create_session()

    # Create beliefs of different types
    store.insert_belief(
        content="test factual belief",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        session_id=session.id,
    )
    store.insert_belief(
        content="test user belief",
        belief_type="preference",
        source_type=BSRC_USER_STATED,
        session_id=session.id,
    )

    # Record some metrics
    store.increment_session_metrics(
        session.id,
        retrieval_tokens=500,
        classification_tokens=100,
        beliefs_created=2,
        searches_performed=3,
        feedback_given=2,
    )

    # Record test results (feedback)
    b1: Belief = store.search("factual")[0]
    store.record_test_result(
        belief_id=b1.id,
        session_id=session.id,
        outcome="used",
        detection_layer="explicit",
    )
    store.record_test_result(
        belief_id=b1.id,
        session_id=session.id,
        outcome="ignored",
        detection_layer="auto_inferred",
    )

    return store, session.id


def test_session_metrics(tmp_path: Path) -> None:
    """Session counters are extracted correctly."""
    store, sid = _setup_store(tmp_path)
    metrics = collect_session_metrics(store, sid)

    assert metrics.retrieval_tokens == 500
    assert metrics.classification_tokens == 100
    assert metrics.beliefs_created == 2
    assert metrics.searches_performed == 3
    assert metrics.feedback_given == 2
    store.close()


def test_feedback_metrics(tmp_path: Path) -> None:
    """Feedback outcomes are aggregated correctly."""
    store, sid = _setup_store(tmp_path)
    metrics = collect_feedback_metrics(store, sid)

    assert metrics.outcome_counts.get("used") == 1
    assert metrics.outcome_counts.get("ignored") == 1
    assert metrics.detection_layer_counts.get("explicit") == 1
    assert metrics.detection_layer_counts.get("auto_inferred") == 1
    assert metrics.feedback_rate > 0
    store.close()


def test_belief_metrics(tmp_path: Path) -> None:
    """Belief lifecycle metrics are collected correctly."""
    store, _ = _setup_store(tmp_path)
    metrics = collect_belief_metrics(store)

    assert metrics.total_active == 2
    assert metrics.total_superseded == 0
    assert metrics.total_locked == 0
    assert sum(metrics.confidence_distribution.values()) == 2
    assert "factual" in metrics.type_distribution
    assert "preference" in metrics.type_distribution
    assert BSRC_AGENT_INFERRED in metrics.source_distribution
    store.close()


def test_graph_metrics(tmp_path: Path) -> None:
    """Graph metrics are collected correctly."""
    store, _ = _setup_store(tmp_path)

    # Add an edge
    beliefs: list[Belief] = store.search("test")
    if len(beliefs) >= 2:
        store.insert_edge(beliefs[0].id, beliefs[1].id, "RELATED", 1.0, "test")

    metrics = collect_graph_metrics(store)
    assert metrics.total_edges >= 0
    assert isinstance(metrics.avg_edges_per_belief, float)
    store.close()


def test_rolling_window_empty(tmp_path: Path) -> None:
    """Rolling window with no completed sessions returns zero count."""
    db: Path = tmp_path / "empty.db"
    store: MemoryStore = MemoryStore(db)
    window = collect_rolling_window(store, 7)
    assert window["sessions_in_window"] == 0
    store.close()


def test_rolling_window_with_sessions(tmp_path: Path) -> None:
    """Rolling window aggregates completed sessions."""
    db: Path = tmp_path / "rolling.db"
    store: MemoryStore = MemoryStore(db)

    # Create and complete 3 sessions
    for i in range(3):
        s = store.create_session()
        store.increment_session_metrics(
            s.id,
            beliefs_created=i + 1,
            searches_performed=2,
            feedback_given=1,
        )
        store.complete_session(s.id)

    window = collect_rolling_window(store, 7)
    assert window["sessions_in_window"] == 3
    assert window["totals"]["beliefs_created"] == 6  # 1+2+3
    assert window["totals"]["searches_performed"] == 6  # 2*3
    assert window["feedback_rate"] > 0
    store.close()


def test_full_snapshot(tmp_path: Path) -> None:
    """Full snapshot has all sections populated."""
    store, sid = _setup_store(tmp_path)
    store.complete_session(sid)
    snapshot = collect_snapshot(store, sid)

    assert snapshot.v == 1
    assert snapshot.ts != ""
    assert snapshot.session.retrieval_tokens == 500
    assert snapshot.feedback.outcome_counts.get("used") == 1
    assert snapshot.beliefs.total_active == 2
    assert isinstance(snapshot.graph.total_edges, int)
    assert "sessions_in_window" in snapshot.window_7
    assert "sessions_in_window" in snapshot.window_30
    store.close()


def test_write_snapshot_jsonl(tmp_path: Path) -> None:
    """Snapshot is written as valid JSONL."""
    store, sid = _setup_store(tmp_path)
    store.complete_session(sid)
    snapshot = collect_snapshot(store, sid)

    out: Path = tmp_path / "telemetry.jsonl"
    write_snapshot(snapshot, out)

    lines: list[str] = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    data: dict[str, object] = json.loads(lines[0])
    assert data["v"] == 1
    assert "session" in data
    assert "feedback" in data
    assert "beliefs" in data
    assert "graph" in data
    assert "window_7" in data
    assert "window_30" in data
    store.close()


def test_no_pii_in_snapshot(tmp_path: Path) -> None:
    """Snapshot must contain zero content strings, paths, or IDs."""
    store, sid = _setup_store(tmp_path)
    store.complete_session(sid)
    snapshot = collect_snapshot(store, sid)

    out: Path = tmp_path / "telemetry.jsonl"
    write_snapshot(snapshot, out)

    raw: str = out.read_text(encoding="utf-8")

    # Must not contain any belief content
    assert "test factual belief" not in raw
    assert "test user belief" not in raw

    # Must not contain any file paths
    assert str(tmp_path) not in raw
    assert "/Users/" not in raw
    assert "/home/" not in raw

    # Must not contain session IDs (12-char hex)
    assert sid not in raw

    # Must not contain belief IDs
    beliefs: list[Belief] = store.search("test")
    for b in beliefs:
        assert b.id not in raw

    store.close()


def test_multiple_snapshots_append(tmp_path: Path) -> None:
    """Multiple snapshots append to the same file."""
    db: Path = tmp_path / "multi.db"
    store: MemoryStore = MemoryStore(db)
    out: Path = tmp_path / "telemetry.jsonl"

    for _ in range(3):
        s = store.create_session()
        store.complete_session(s.id)
        snapshot = collect_snapshot(store, s.id)
        write_snapshot(snapshot, out)

    lines: list[str] = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3

    # Each line is valid JSON
    for line in lines:
        data: dict[str, object] = json.loads(line)
        assert data["v"] == 1

    store.close()


def test_emit_telemetry_respects_disabled(tmp_path: Path) -> None:
    """When telemetry is disabled in config, _emit_telemetry writes nothing."""
    import pytest

    db: Path = tmp_path / "disabled.db"
    store: MemoryStore = MemoryStore(db)
    s = store.create_session()
    store.complete_session(s.id)

    # Override config to disable telemetry
    from agentmemory import config as _cfg
    mp = pytest.MonkeyPatch()
    mp.setattr(_cfg, "_CONFIG_PATH", tmp_path / "config.json")
    (tmp_path / "config.json").write_text(
        '{"telemetry": {"enabled": false}}', encoding="utf-8"
    )

    # Override telemetry output path
    out: Path = tmp_path / "telemetry.jsonl"
    from agentmemory import telemetry as _tel
    mp.setattr(_tel, "_default_path", lambda: out)

    from agentmemory import server as _srv
    _srv._emit_telemetry(store, s.id)  # pyright: ignore[reportPrivateUsage]

    # File should not exist (telemetry disabled)
    assert not out.exists()

    store.close()
    mp.undo()


def test_emit_telemetry_writes_when_enabled(tmp_path: Path) -> None:
    """When telemetry is enabled, _emit_telemetry writes a snapshot."""
    import pytest

    db: Path = tmp_path / "enabled.db"
    store: MemoryStore = MemoryStore(db)
    s = store.create_session()
    store.increment_session_metrics(s.id, searches_performed=1)
    store.complete_session(s.id)

    # Override config to enable telemetry
    from agentmemory import config as _cfg
    mp = pytest.MonkeyPatch()
    mp.setattr(_cfg, "_CONFIG_PATH", tmp_path / "config.json")
    (tmp_path / "config.json").write_text(
        '{"telemetry": {"enabled": true}}', encoding="utf-8"
    )

    # Override default telemetry path
    from agentmemory import telemetry as _tel
    out: Path = tmp_path / "telemetry.jsonl"
    mp.setattr(_tel, "_default_path", lambda: out)

    from agentmemory import server as _srv
    _srv._emit_telemetry(store, s.id)  # pyright: ignore[reportPrivateUsage]

    # File should exist with one line
    assert out.exists()
    lines: list[str] = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    data: dict[str, object] = json.loads(lines[0])
    assert data["v"] == 1

    store.close()
    mp.undo()


def test_get_unsent_lines_no_file(tmp_path: Path) -> None:
    """Returns empty list when telemetry file does not exist."""
    import pytest
    from agentmemory import config as _cfg, telemetry as _tel

    mp = pytest.MonkeyPatch()
    mp.setattr(_tel, "_default_path", lambda: tmp_path / "nope.jsonl")
    mp.setattr(_cfg, "_CONFIG_PATH", tmp_path / "config.json")
    (tmp_path / "config.json").write_text(
        '{"telemetry": {"enabled": true, "sent_lines": 0}}', encoding="utf-8"
    )

    lines, offset = get_unsent_lines()
    assert lines == []
    assert offset == 0
    mp.undo()


def test_get_unsent_lines_with_offset(tmp_path: Path) -> None:
    """Only returns lines after the sent_lines offset."""
    import pytest
    from agentmemory import config as _cfg, telemetry as _tel

    mp = pytest.MonkeyPatch()
    out: Path = tmp_path / "telemetry.jsonl"
    out.write_text(
        '{"v":1,"ts":"a"}\n{"v":1,"ts":"b"}\n{"v":1,"ts":"c"}\n',
        encoding="utf-8",
    )
    mp.setattr(_tel, "_default_path", lambda: out)
    mp.setattr(_cfg, "_CONFIG_PATH", tmp_path / "config.json")
    (tmp_path / "config.json").write_text(
        '{"telemetry": {"enabled": true, "sent_lines": 1}}', encoding="utf-8"
    )

    lines, offset = get_unsent_lines()
    assert offset == 1
    assert len(lines) == 2
    assert '"ts":"b"' in lines[0]
    assert '"ts":"c"' in lines[1]
    mp.undo()


def test_mark_sent_updates_config(tmp_path: Path) -> None:
    """mark_sent persists the new offset to config."""
    import pytest
    from agentmemory import config as _cfg

    mp = pytest.MonkeyPatch()
    cfg_path: Path = tmp_path / "config.json"
    cfg_path.write_text(
        '{"telemetry": {"enabled": true, "sent_lines": 0}}', encoding="utf-8"
    )
    mp.setattr(_cfg, "_CONFIG_PATH", cfg_path)

    mark_sent(5)

    data: dict[str, object] = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert data["telemetry"]["sent_lines"] == 5  # type: ignore[index]
    mp.undo()


def test_get_unsent_after_mark_sent(tmp_path: Path) -> None:
    """After mark_sent, get_unsent_lines returns nothing for already-sent data."""
    import pytest
    from agentmemory import config as _cfg, telemetry as _tel

    mp = pytest.MonkeyPatch()
    out: Path = tmp_path / "telemetry.jsonl"
    out.write_text('{"v":1,"ts":"a"}\n{"v":1,"ts":"b"}\n', encoding="utf-8")
    mp.setattr(_tel, "_default_path", lambda: out)

    cfg_path: Path = tmp_path / "config.json"
    cfg_path.write_text(
        '{"telemetry": {"enabled": true, "sent_lines": 0}}', encoding="utf-8"
    )
    mp.setattr(_cfg, "_CONFIG_PATH", cfg_path)

    # First call: 2 unsent
    lines, offset = get_unsent_lines()
    assert len(lines) == 2

    # Mark both as sent
    mark_sent(offset + len(lines))

    # Second call: 0 unsent
    lines2, offset2 = get_unsent_lines()
    assert len(lines2) == 0
    assert offset2 == 2
    mp.undo()
