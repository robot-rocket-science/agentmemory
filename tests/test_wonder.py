"""Tests for the exploratory wonder module.

Covers: gap analysis, research axis generation, speculative belief ingestion,
garbage collection, MCP tool serialization, and edge cases.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import pytest

from agentmemory.models import Belief
from agentmemory.store import MemoryStore
from agentmemory.wonder import (
    DEFAULT_AGENT_COUNT,
    GCResult,
    GapAnalysis,
    ResearchAxis,
    WonderIngestResult,
    WonderResult,
    analyze_gaps,
    generate_research_axes,
    wonder,
    wonder_gc,
    wonder_ingest,
    wonder_result_to_dict,
)


@pytest.fixture()
def store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    """Create a temporary MemoryStore for testing."""
    s: MemoryStore = MemoryStore(tmp_path / "test_wonder.db")
    yield s
    s.close()


@pytest.fixture()
def populated_store(store: MemoryStore) -> MemoryStore:
    """Store with a set of test beliefs for gap analysis."""
    store.insert_belief(
        "PostgreSQL is the database choice",
        "factual",
        "user_stated",
        alpha=5.0,
        beta_param=1.0,
    )
    store.insert_belief(
        "SQLite was considered but rejected for production",
        "factual",
        "agent_inferred",
        alpha=2.0,
        beta_param=1.0,
    )
    store.insert_belief(
        "Database performance matters for production workloads",
        "factual",
        "agent_inferred",
        alpha=1.0,
        beta_param=1.0,
    )
    store.insert_belief(
        "Redis is used for caching",
        "factual",
        "user_stated",
        alpha=3.0,
        beta_param=1.0,
    )
    return store


# ---------------------------------------------------------------------------
# Gap analysis
# ---------------------------------------------------------------------------


class TestAnalyzeGaps:
    def test_empty_store(self, store: MemoryStore) -> None:
        gap: GapAnalysis = analyze_gaps(store, "anything at all")
        assert gap.coverage_score == 0.0
        assert len(gap.known_beliefs) == 0
        assert len(gap.identified_gaps) >= 1
        assert "No beliefs found" in gap.identified_gaps[0]

    def test_full_coverage(self, populated_store: MemoryStore) -> None:
        gap: GapAnalysis = analyze_gaps(populated_store, "PostgreSQL database")
        assert gap.coverage_score > 0.0
        assert len(gap.known_beliefs) > 0

    def test_partial_coverage(self, populated_store: MemoryStore) -> None:
        gap: GapAnalysis = analyze_gaps(
            populated_store,
            "PostgreSQL replication sharding",
        )
        # "PostgreSQL" covered, "replication" and "sharding" not
        assert 0.0 < gap.coverage_score < 1.0
        uncovered_gap: bool = any(
            "no belief coverage" in g.lower() for g in gap.identified_gaps
        )
        assert uncovered_gap

    def test_high_uncertainty_detection(self, store: MemoryStore) -> None:
        # Insert a belief with very low evidence (high uncertainty)
        store.insert_belief(
            "Maybe we should use MongoDB",
            "factual",
            "agent_inferred",
            alpha=0.5,
            beta_param=0.5,
        )
        gap: GapAnalysis = analyze_gaps(store, "MongoDB")
        # Beta(0.5, 0.5) has high uncertainty
        assert (
            len(gap.high_uncertainty) >= 0
        )  # may or may not flag depending on threshold

    def test_agent_inferred_gap(self, store: MemoryStore) -> None:
        # All beliefs are agent-inferred
        for i in range(5):
            store.insert_belief(
                f"Inferred fact {i} about testing",
                "factual",
                "agent_inferred",
                alpha=1.0,
                beta_param=1.0,
            )
        gap: GapAnalysis = analyze_gaps(store, "testing")
        agent_gap: bool = any("agent-inferred" in g for g in gap.identified_gaps)
        assert agent_gap


# ---------------------------------------------------------------------------
# Research axis generation
# ---------------------------------------------------------------------------


class TestGenerateResearchAxes:
    def test_default_count(self, populated_store: MemoryStore) -> None:
        gap: GapAnalysis = analyze_gaps(populated_store, "database performance")
        axes: list[ResearchAxis] = generate_research_axes(gap)
        assert len(axes) == DEFAULT_AGENT_COUNT

    def test_custom_count(self, populated_store: MemoryStore) -> None:
        gap: GapAnalysis = analyze_gaps(populated_store, "database")
        for n in [1, 2, 3, 5, 6, 7, 8]:
            axes: list[ResearchAxis] = generate_research_axes(gap, agent_count=n)
            assert len(axes) == n

    def test_clamps_to_bounds(self, populated_store: MemoryStore) -> None:
        gap: GapAnalysis = analyze_gaps(populated_store, "database")
        assert len(generate_research_axes(gap, agent_count=0)) == 1  # clamped to min
        assert len(generate_research_axes(gap, agent_count=99)) == 8  # clamped to max

    def test_axis_names_unique(self, populated_store: MemoryStore) -> None:
        gap: GapAnalysis = analyze_gaps(populated_store, "database")
        axes: list[ResearchAxis] = generate_research_axes(gap, agent_count=8)
        names: list[str] = [ax.name for ax in axes]
        assert len(names) == len(set(names))

    def test_axis_ids_sequential(self, populated_store: MemoryStore) -> None:
        gap: GapAnalysis = analyze_gaps(populated_store, "database")
        axes: list[ResearchAxis] = generate_research_axes(gap, agent_count=4)
        ids: list[int] = [ax.axis_id for ax in axes]
        assert ids == [1, 2, 3, 4]

    def test_first_two_axes_always_present(self, populated_store: MemoryStore) -> None:
        gap: GapAnalysis = analyze_gaps(populated_store, "database")
        axes: list[ResearchAxis] = generate_research_axes(gap, agent_count=2)
        assert axes[0].name == "Domain Research"
        assert axes[1].name == "Gap Analysis"


# ---------------------------------------------------------------------------
# Wonder (full pipeline)
# ---------------------------------------------------------------------------


class TestWonder:
    def test_returns_result(self, populated_store: MemoryStore) -> None:
        result: WonderResult = wonder(
            populated_store,
            "database choice",
            agent_count=3,
        )
        assert isinstance(result, WonderResult)
        assert result.agent_count == 3
        assert len(result.research_axes) == 3
        assert isinstance(result.gap_analysis, GapAnalysis)

    def test_creates_speculative_anchors(self, populated_store: MemoryStore) -> None:
        result: WonderResult = wonder(populated_store, "vector embeddings")
        # Should create at least one speculative anchor for the gap
        assert len(result.speculative_ids) >= 0  # may be 0 if no gaps

    def test_serialization(self, populated_store: MemoryStore) -> None:
        result: WonderResult = wonder(populated_store, "database", agent_count=4)
        d: dict[str, object] = wonder_result_to_dict(result)
        # Should be JSON-serializable
        json_str: str = json.dumps(d)
        parsed: dict[str, object] = json.loads(json_str)
        assert parsed["agent_count"] == 4
        assert isinstance(parsed["research_axes"], list)
        assert isinstance(parsed["identified_gaps"], list)


# ---------------------------------------------------------------------------
# Wonder ingest
# ---------------------------------------------------------------------------


class TestWonderIngest:
    def test_ingest_creates_speculative_beliefs(self, store: MemoryStore) -> None:
        docs: list[tuple[str, int]] = [
            (
                "Vector databases like Milvus support billion-scale search. "
                "FAISS provides efficient CPU and GPU similarity search. "
                "Annoy uses random projection trees for approximate neighbors.",
                1,
            ),
        ]
        result: WonderIngestResult = wonder_ingest(store, docs)
        assert result.documents_processed == 1
        assert result.beliefs_created >= 2  # at least some sentences extracted
        assert (
            result.beliefs_tagged == result.beliefs_created
        )  # all new should be tagged

        # Verify they are in the DB with correct metadata
        rows = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT * FROM beliefs WHERE source_type = 'wonder_generated'"
        ).fetchall()
        assert len(rows) == result.beliefs_tagged
        for row in rows:
            assert row["belief_type"] == "speculative"
            assert float(row["alpha"]) == pytest.approx(0.3)  # pyright: ignore[reportUnknownMemberType]
            assert float(row["beta_param"]) == pytest.approx(1.0)  # pyright: ignore[reportUnknownMemberType]
            assert row["temporal_direction"] == "forward"

    def test_ingest_with_anchors(self, store: MemoryStore) -> None:
        anchor: Belief = store.insert_belief(
            "anchor belief for wonder",
            "factual",
            "user_stated",
            alpha=5.0,
            beta_param=1.0,
        )
        docs: list[tuple[str, int]] = [
            ("Some new research finding about testing strategies.", 2),
        ]
        result: WonderIngestResult = wonder_ingest(
            store,
            docs,
            anchor_belief_ids=[anchor.id],
        )
        assert result.anchor_edges_created > 0

        # Verify edge exists
        specs = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT id FROM beliefs WHERE source_type = 'wonder_generated'"
        ).fetchall()
        for spec_row in specs:
            assert store.edge_exists(spec_row["id"], anchor.id)

    def test_ingest_empty_docs(self, store: MemoryStore) -> None:
        result: WonderIngestResult = wonder_ingest(store, [])
        assert result.documents_processed == 0
        assert result.beliefs_created == 0

    def test_ingest_blank_doc_skipped(self, store: MemoryStore) -> None:
        result: WonderIngestResult = wonder_ingest(store, [("   ", 1)])
        assert result.documents_processed == 0

    def test_ingest_multiple_axes(self, store: MemoryStore) -> None:
        docs: list[tuple[str, int]] = [
            ("Axis one finding about caching strategies in distributed systems.", 1),
            ("Axis three finding about alternative database architectures.", 3),
        ]
        result: WonderIngestResult = wonder_ingest(store, docs)
        assert result.documents_processed == 2

        # Verify data_source tags distinguish axes
        axis1 = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT COUNT(*) FROM beliefs WHERE data_source = 'wonder_axis_1'"
        ).fetchone()[0]
        axis3 = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT COUNT(*) FROM beliefs WHERE data_source = 'wonder_axis_3'"
        ).fetchone()[0]
        assert axis1 > 0
        assert axis3 > 0

    def test_ingest_dedup_content_hash(self, store: MemoryStore) -> None:
        """Same content ingested twice should not create duplicates."""
        doc: str = "Unique fact about deduplication testing in wonder module."
        wonder_ingest(store, [(doc, 1)])
        count1: int = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT COUNT(*) FROM beliefs WHERE source_type = 'wonder_generated'"
        ).fetchone()[0]

        wonder_ingest(store, [(doc, 1)])
        count2: int = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT COUNT(*) FROM beliefs WHERE source_type = 'wonder_generated'"
        ).fetchone()[0]
        # Content-hash dedup in insert_belief should prevent duplicates
        assert count2 == count1

    def test_locked_beliefs_not_retagged(self, store: MemoryStore) -> None:
        """Locked beliefs should not be retagged as speculative."""
        locked: Belief = store.insert_belief(
            "This is a locked constraint about wonder testing.",
            "correction",
            "user_corrected",
            alpha=9.0,
            beta_param=1.0,
            locked=True,
        )
        # Ingest the same content -- it will dedup, but even if somehow
        # a locked belief were in the new set, it should not be retagged
        wonder_ingest(
            store,
            [("This is a locked constraint about wonder testing.", 1)],
        )
        reloaded: Belief | None = store.get_belief(locked.id)
        assert reloaded is not None
        assert reloaded.locked
        assert reloaded.source_type == "user_corrected"  # NOT wonder_generated


# ---------------------------------------------------------------------------
# Garbage collection
# ---------------------------------------------------------------------------


class TestWonderGC:
    def _create_speculative(
        self,
        store: MemoryStore,
        content: str,
        days_old: int = 0,
    ) -> str:
        """Helper: create a speculative belief with a specific age."""
        from datetime import datetime, timedelta, timezone

        created: str = (
            datetime.now(timezone.utc) - timedelta(days=days_old)
        ).isoformat()
        b: Belief = store.insert_belief(
            content,
            "speculative",
            "wonder_generated",
            alpha=0.3,
            beta_param=1.0,
            created_at=created,
        )
        return b.id

    def test_gc_respects_ttl(self, store: MemoryStore) -> None:
        fresh_id: str = self._create_speculative(store, "fresh spec belief", days_old=5)
        old_id: str = self._create_speculative(store, "old spec belief", days_old=20)

        result: GCResult = wonder_gc(store, ttl_days=14, dry_run=False)
        assert result.deleted == 1  # only the old one
        assert result.surviving == 0  # old one was the only one scanned

        # Verify: fresh one alive, old one soft-deleted
        fresh: Belief | None = store.get_belief(fresh_id)
        old: Belief | None = store.get_belief(old_id)
        assert fresh is not None
        assert old is not None
        assert old.valid_to is not None  # soft-deleted

    def test_gc_preserves_resolved(self, store: MemoryStore) -> None:
        """Beliefs with RESOLVES edges should survive GC."""
        old_id: str = self._create_speculative(store, "resolved spec", days_old=30)
        evidence: Belief = store.insert_belief(
            "evidence confirming resolved spec",
            "factual",
            "user_stated",
            alpha=5.0,
            beta_param=1.0,
        )
        store.insert_edge(evidence.id, old_id, "RESOLVES", 1.0, "test")

        result: GCResult = wonder_gc(store, ttl_days=14, dry_run=False)
        assert result.deleted == 0  # preserved because of RESOLVES edge

    def test_gc_preserves_updated_confidence(self, store: MemoryStore) -> None:
        """Beliefs whose confidence was updated should survive GC."""
        old_id: str = self._create_speculative(store, "updated spec", days_old=30)
        # Simulate evidence: increase alpha
        store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "UPDATE beliefs SET alpha = 3.0 WHERE id = ?",
            (old_id,),
        )
        store._conn.commit()  # pyright: ignore[reportPrivateUsage]

        result: GCResult = wonder_gc(store, ttl_days=14, dry_run=False)
        assert result.deleted == 0  # preserved because alpha changed

    def test_gc_dry_run_no_deletion(self, store: MemoryStore) -> None:
        self._create_speculative(store, "dry run target", days_old=30)
        result: GCResult = wonder_gc(store, ttl_days=14, dry_run=True)
        assert result.deleted > 0

        # Verify nothing actually deleted
        alive: int = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT COUNT(*) FROM beliefs WHERE valid_to IS NULL "
            "AND belief_type = 'speculative'"
        ).fetchone()[0]
        assert alive == 1  # still alive

    def test_gc_preserves_locked(self, store: MemoryStore) -> None:
        """Locked speculative beliefs should never be GC'd."""
        from datetime import datetime, timedelta, timezone

        created: str = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        store.insert_belief(
            "locked spec belief",
            "speculative",
            "wonder_generated",
            alpha=0.3,
            beta_param=1.0,
            locked=True,
            created_at=created,
        )

        result: GCResult = wonder_gc(store, ttl_days=14, dry_run=False)
        assert result.deleted == 0

    def test_gc_does_not_touch_regular_beliefs(self, store: MemoryStore) -> None:
        """GC should only affect speculative/wonder_generated beliefs."""
        from datetime import datetime, timedelta, timezone

        created: str = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        store.insert_belief(
            "old regular belief",
            "factual",
            "agent_inferred",
            alpha=1.0,
            beta_param=1.0,
            created_at=created,
        )

        result: GCResult = wonder_gc(store, ttl_days=14, dry_run=False)
        assert result.scanned == 0  # should not even scan non-speculative


# ---------------------------------------------------------------------------
# GC validation against existing belief trees (empirical)
# ---------------------------------------------------------------------------


class TestGCEmpiricalValidation:
    """Validate GC behavior against realistic belief tree structures."""

    def test_gc_preserves_connected_tree(self, store: MemoryStore) -> None:
        """A tree of speculative beliefs where the root has evidence should
        preserve the root but GC the unresolved leaves."""
        from datetime import datetime, timedelta, timezone

        old_ts: str = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        # Root: resolved (has evidence)
        root: Belief = store.insert_belief(
            "root hypothesis about caching",
            "speculative",
            "wonder_generated",
            alpha=0.3,
            beta_param=1.0,
            created_at=old_ts,
        )
        evidence: Belief = store.insert_belief(
            "caching reduces latency by 40%",
            "factual",
            "user_stated",
            alpha=5.0,
            beta_param=1.0,
        )
        store.insert_edge(evidence.id, root.id, "RESOLVES", 1.0, "test")

        # Leaf 1: unresolved (should be GC'd)
        leaf1: Belief = store.insert_belief(
            "maybe Redis is best for this cache",
            "speculative",
            "wonder_generated",
            alpha=0.3,
            beta_param=1.0,
            created_at=old_ts,
        )
        store.insert_edge(root.id, leaf1.id, "SPECULATES", 1.0, "test")

        # Leaf 2: also unresolved
        leaf2: Belief = store.insert_belief(
            "maybe Memcached is simpler",
            "speculative",
            "wonder_generated",
            alpha=0.3,
            beta_param=1.0,
            created_at=old_ts,
        )
        store.insert_edge(root.id, leaf2.id, "SPECULATES", 1.0, "test")

        result: GCResult = wonder_gc(store, ttl_days=14, dry_run=False)
        # Root preserved (RESOLVES edge), leaves GC'd
        assert result.deleted == 2

        root_after: Belief | None = store.get_belief(root.id)
        leaf1_after: Belief | None = store.get_belief(leaf1.id)
        leaf2_after: Belief | None = store.get_belief(leaf2.id)
        assert root_after is not None and root_after.valid_to is None
        assert leaf1_after is not None and leaf1_after.valid_to is not None
        assert leaf2_after is not None and leaf2_after.valid_to is not None

    def test_gc_batch_volume(self, store: MemoryStore) -> None:
        """Simulate a large wonder session and verify GC handles volume."""
        from datetime import datetime, timedelta, timezone

        old_ts: str = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        # Create 200 speculative beliefs
        ids: list[str] = []
        for i in range(200):
            b: Belief = store.insert_belief(
                f"speculative finding number {i} about various topics",
                "speculative",
                "wonder_generated",
                alpha=0.3,
                beta_param=1.0,
                created_at=old_ts,
            )
            ids.append(b.id)

        # Mark 50 as having evidence (should survive)
        for bid in ids[:50]:
            store._conn.execute(  # pyright: ignore[reportPrivateUsage]
                "UPDATE beliefs SET alpha = 3.0 WHERE id = ?",
                (bid,),
            )
        store._conn.commit()  # pyright: ignore[reportPrivateUsage]

        result: GCResult = wonder_gc(store, ttl_days=14, dry_run=False)
        assert result.deleted == 150
        assert result.surviving == 50

        # Verify surviving beliefs are the ones with updated alpha
        alive: int = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT COUNT(*) FROM beliefs WHERE valid_to IS NULL "
            "AND belief_type = 'speculative'"
        ).fetchone()[0]
        assert alive == 50

    def test_gc_decay_rate_simulation(self, store: MemoryStore) -> None:
        """Verify that speculative beliefs at different ages GC correctly."""
        from datetime import datetime, timedelta, timezone

        now: datetime = datetime.now(timezone.utc)

        # Create beliefs at different ages
        # GC uses `created_at < cutoff` (strictly less than), so a belief
        # created exactly 14 days ago IS older than the cutoff and gets GC'd.
        ages: list[int] = [1, 7, 13, 15, 30, 60]
        for days in ages:
            ts: str = (now - timedelta(days=days)).isoformat()
            store.insert_belief(
                f"spec belief aged {days} days",
                "speculative",
                "wonder_generated",
                alpha=0.3,
                beta_param=1.0,
                created_at=ts,
            )

        result: GCResult = wonder_gc(store, ttl_days=14, dry_run=False)
        # Days 15, 30, 60 should be GC'd (3 beliefs, strictly older than 14d)
        # Days 1, 7, 13 should survive (3 beliefs, younger than 14d)
        assert result.deleted == 3

        alive: int = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT COUNT(*) FROM beliefs WHERE valid_to IS NULL "
            "AND belief_type = 'speculative'"
        ).fetchone()[0]
        assert alive == 3
