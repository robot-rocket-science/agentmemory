"""Tests for the redesigned status report: inventory, retrieval, activity, maintenance."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentmemory.models import (
    BELIEF_CORRECTION,
    BELIEF_FACTUAL,
    BELIEF_PREFERENCE,
    BELIEF_REQUIREMENT,
    BSRC_AGENT_INFERRED,
    BSRC_USER_CORRECTED,
    BSRC_USER_STATED,
    OBS_TYPE_USER_STATEMENT,
    SRC_USER,
)
from agentmemory.store import MemoryStore


@pytest.fixture()
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path / "test_status.db")


def _populate(store: MemoryStore) -> None:
    """Seed a store with a realistic mix of beliefs."""
    # 3 factual agent-inferred
    for i in range(3):
        store.insert_belief(f"Factual {i}", BELIEF_FACTUAL, BSRC_AGENT_INFERRED)
    # 2 corrections from user
    for i in range(2):
        store.insert_belief(f"Correction {i}", BELIEF_CORRECTION, BSRC_USER_CORRECTED)
    # 1 requirement user-stated
    store.insert_belief("Must do X", BELIEF_REQUIREMENT, BSRC_USER_STATED)
    # 1 preference
    store.insert_belief("Prefer Y", BELIEF_PREFERENCE, BSRC_AGENT_INFERRED)
    # 1 locked correction
    b = store.insert_belief("Locked rule", BELIEF_CORRECTION, BSRC_USER_CORRECTED)
    store.lock_belief(b.id)
    # 1 observation
    store.insert_observation("user said something", OBS_TYPE_USER_STATEMENT, SRC_USER)
    # 1 session
    store.create_session()


class TestGetStatusReport:
    """Tests for MemoryStore.get_status_report()."""

    def test_returns_expected_sections(self, store: MemoryStore) -> None:
        _populate(store)
        report: dict[str, object] = store.get_status_report()
        assert "inventory" in report
        assert "retrieval" in report
        assert "activity" in report
        assert "maintenance" in report

    def test_inventory_counts(self, store: MemoryStore) -> None:
        _populate(store)
        report: dict[str, object] = store.get_status_report()
        inv: dict[str, object] = report["inventory"]  # type: ignore[assignment]
        assert inv["active"] == 8
        assert inv["superseded"] == 0
        assert inv["locked"] == 1

    def test_inventory_type_distribution(self, store: MemoryStore) -> None:
        _populate(store)
        report: dict[str, object] = store.get_status_report()
        inv: dict[str, object] = report["inventory"]  # type: ignore[assignment]
        by_type: dict[str, int] = inv["by_type"]  # type: ignore[assignment]
        assert by_type["factual"] == 3
        assert by_type["correction"] == 3  # 2 + 1 locked
        assert by_type["requirement"] == 1
        assert by_type["preference"] == 1

    def test_inventory_source_distribution(self, store: MemoryStore) -> None:
        _populate(store)
        report: dict[str, object] = store.get_status_report()
        inv: dict[str, object] = report["inventory"]  # type: ignore[assignment]
        by_source: dict[str, int] = inv["by_source"]  # type: ignore[assignment]
        assert by_source["agent_inferred"] == 4
        assert by_source["user_corrected"] == 3
        assert by_source["user_stated"] == 1

    def test_retrieval_section(self, store: MemoryStore) -> None:
        _populate(store)
        report: dict[str, object] = store.get_status_report()
        ret: dict[str, object] = report["retrieval"]  # type: ignore[assignment]
        assert "retrieved_once" in ret
        assert "total_active" in ret
        assert "pending_feedback" in ret
        assert isinstance(ret["scoring_features"], list)

    def test_activity_section(self, store: MemoryStore) -> None:
        _populate(store)
        report: dict[str, object] = store.get_status_report()
        act: dict[str, object] = report["activity"]  # type: ignore[assignment]
        assert act["sessions"] == 1
        assert "observations" in act

    def test_maintenance_section(self, store: MemoryStore) -> None:
        _populate(store)
        report: dict[str, object] = store.get_status_report()
        maint: dict[str, object] = report["maintenance"]  # type: ignore[assignment]
        assert "stale_count" in maint
        assert "orphan_count" in maint
        assert "orphan_pct" in maint
        assert "credal_gap_count" in maint

    def test_empty_db_returns_zeros(self, store: MemoryStore) -> None:
        report: dict[str, object] = store.get_status_report()
        inv: dict[str, object] = report["inventory"]  # type: ignore[assignment]
        assert inv["active"] == 0
        assert inv["by_type"] == {}
        assert inv["by_source"] == {}
        ret: dict[str, object] = report["retrieval"]  # type: ignore[assignment]
        assert ret["retrieved_once"] == 0
        assert ret["total_active"] == 0

    def test_locked_breakdown(self, store: MemoryStore) -> None:
        _populate(store)
        report: dict[str, object] = store.get_status_report()
        inv: dict[str, object] = report["inventory"]  # type: ignore[assignment]
        locked_by_type: dict[str, int] = inv["locked_by_type"]  # type: ignore[assignment]
        assert locked_by_type.get("correction", 0) == 1
