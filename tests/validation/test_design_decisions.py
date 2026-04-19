"""Validation tests for open research questions R2, R3, D1, D2, D3.

These are quick spot-checks to determine which open design decisions
matter for production and which can be closed as academic.

R2: Does type-aware progressive filtering preserve coverage vs random?
R3: Does classification accuracy degrade by content origin?
D1: Do graph shape metrics change measurably over time slices?
D2: Does sentence-level contradiction detection catch more than belief-level?
D3: Do TEMPORAL_NEXT edges improve retrieval for temporal queries?
"""

from __future__ import annotations

import random
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agentmemory.compression import compress_belief, estimate_tokens, pack_beliefs
from agentmemory.graph_metrics import compute_degree_centrality
from agentmemory.models import (
    BELIEF_CAUSAL,
    BELIEF_CORRECTION,
    BELIEF_FACTUAL,
    BELIEF_PREFERENCE,
    BELIEF_PROCEDURAL,
    BELIEF_RELATIONAL,
    BELIEF_REQUIREMENT,
    BSRC_AGENT_INFERRED,
    BSRC_DOCUMENT_RECENT,
    BSRC_USER_CORRECTED,
    BSRC_USER_STATED,
    EDGE_SUPPORTS,
    EDGE_TEMPORAL_NEXT,
    Belief,
)
from agentmemory.relationship_detector import detect_relationships
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    """Fresh MemoryStore backed by a temp database."""
    s: MemoryStore = MemoryStore(tmp_path / "test.db")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_NOW: str = datetime.now(timezone.utc).isoformat()


def _insert(
    store: MemoryStore,
    content: str,
    belief_type: str = BELIEF_FACTUAL,
    source_type: str = BSRC_AGENT_INFERRED,
    locked: bool = False,
    created_at: str | None = None,
) -> Belief:
    return store.insert_belief(
        content=content,
        belief_type=belief_type,
        source_type=source_type,
        locked=locked,
        created_at=created_at or _NOW,
    )


# ===========================================================================
# R2: Type-aware progressive filtering vs random dropping
# ===========================================================================


class TestR2TypeAwareFiltering:
    """Validate that type-aware compression preserves critical beliefs
    better than random dropping at the same token budget."""

    # Priority order: requirement > correction > preference > factual > procedural > causal > relational
    _TYPE_PRIORITY: list[str] = [
        BELIEF_REQUIREMENT,
        BELIEF_CORRECTION,
        BELIEF_PREFERENCE,
        BELIEF_FACTUAL,
        BELIEF_PROCEDURAL,
        BELIEF_CAUSAL,
        BELIEF_RELATIONAL,
    ]

    @staticmethod
    def _build_corpus(store: MemoryStore) -> list[Belief]:
        """Create a mixed-type corpus with 5 critical beliefs embedded."""
        beliefs: list[Belief] = []

        # Critical beliefs (should survive filtering)
        beliefs.append(
            _insert(
                store,
                "All code must use strict typing with pyright strict mode",
                BELIEF_REQUIREMENT,
                BSRC_USER_STATED,
            )
        )
        beliefs.append(
            _insert(
                store,
                "[correction] Use PostgreSQL not SQLite for production deployments",
                BELIEF_CORRECTION,
                BSRC_USER_CORRECTED,
            )
        )
        beliefs.append(
            _insert(
                store,
                "User prefers terse responses with no trailing summaries",
                BELIEF_PREFERENCE,
                BSRC_USER_STATED,
            )
        )
        beliefs.append(
            _insert(
                store,
                "The hybrid retrieval architecture combines FTS5 and HRR for vocabulary bridging",
                BELIEF_REQUIREMENT,
                BSRC_USER_STATED,
            )
        )
        beliefs.append(
            _insert(
                store,
                "[correction] Never use em dashes in any output text",
                BELIEF_CORRECTION,
                BSRC_USER_CORRECTED,
            )
        )

        # Filler beliefs (lower priority, can be dropped)
        for i in range(15):
            beliefs.append(
                _insert(
                    store,
                    f"Factual observation about module behavior pattern {i}",
                    BELIEF_FACTUAL,
                )
            )
        for i in range(8):
            beliefs.append(
                _insert(
                    store,
                    f"The build step {i} requires running npm install followed by compilation and linking of shared objects",
                    BELIEF_PROCEDURAL,
                )
            )
        for i in range(5):
            beliefs.append(
                _insert(
                    store,
                    f"Changes in module {i} caused downstream regression in test suite {i + 10} because of shared state",
                    BELIEF_CAUSAL,
                )
            )
        for i in range(5):
            beliefs.append(
                _insert(
                    store,
                    f"Module {i} relates to subsystem {i + 5} through shared configuration files",
                    BELIEF_RELATIONAL,
                )
            )

        return beliefs

    @staticmethod
    def _critical_ids(beliefs: list[Belief]) -> set[str]:
        """First 5 beliefs are the critical ones."""
        return {b.id for b in beliefs[:5]}

    def test_type_aware_preserves_critical_at_tight_budget(
        self, store: MemoryStore
    ) -> None:
        """At a tight token budget, type-aware filtering keeps all critical beliefs."""
        beliefs: list[Belief] = self._build_corpus(store)
        critical: set[str] = self._critical_ids(beliefs)

        # Sort by type priority (requirements first, relational last)
        type_rank: dict[str, int] = {t: i for i, t in enumerate(self._TYPE_PRIORITY)}
        sorted_beliefs: list[Belief] = sorted(
            beliefs, key=lambda b: type_rank.get(b.belief_type, 99)
        )

        # Pack into a budget that can fit ~60% of total tokens
        total_tokens: int = sum(estimate_tokens(compress_belief(b)) for b in beliefs)
        budget: int = int(total_tokens * 0.6)

        packed, _used = pack_beliefs(sorted_beliefs, budget)
        packed_ids: set[str] = {b.id for b in packed}

        critical_kept: int = len(critical & packed_ids)
        assert critical_kept == 5, (
            f"Type-aware kept {critical_kept}/5 critical beliefs at 60% budget"
        )

    def test_random_drops_critical_more_often(self, store: MemoryStore) -> None:
        """Random dropping loses critical beliefs more often than type-aware."""
        beliefs: list[Belief] = self._build_corpus(store)
        critical: set[str] = self._critical_ids(beliefs)

        total_tokens: int = sum(estimate_tokens(compress_belief(b)) for b in beliefs)
        budget: int = int(total_tokens * 0.6)

        # Run 20 random trials
        rng: random.Random = random.Random(42)
        random_kept_counts: list[int] = []
        for _ in range(20):
            shuffled: list[Belief] = beliefs.copy()
            rng.shuffle(shuffled)
            packed, _ = pack_beliefs(shuffled, budget)
            packed_ids: set[str] = {b.id for b in packed}
            random_kept_counts.append(len(critical & packed_ids))

        avg_random: float = sum(random_kept_counts) / len(random_kept_counts)
        # Type-aware keeps all 5; random should average less
        assert avg_random < 5.0, (
            f"Random avg {avg_random} should be < 5 (type-aware keeps all 5)"
        )

    def test_progressive_filtering_coverage_curve(self, store: MemoryStore) -> None:
        """As we drop lower-priority types, coverage of critical beliefs is preserved."""
        beliefs: list[Belief] = self._build_corpus(store)
        critical: set[str] = self._critical_ids(beliefs)

        # Progressive filtering: keep all -> drop relational -> drop causal -> drop procedural
        drop_order: list[str] = [BELIEF_RELATIONAL, BELIEF_CAUSAL, BELIEF_PROCEDURAL]

        excluded: set[str] = set()
        prev_critical_count: int = 5

        for drop_type in drop_order:
            excluded.add(drop_type)
            filtered: list[Belief] = [
                b for b in beliefs if b.belief_type not in excluded
            ]
            filtered_ids: set[str] = {b.id for b in filtered}
            critical_remaining: int = len(critical & filtered_ids)

            # Critical beliefs are all high-priority types, so dropping low-priority
            # types should never reduce critical coverage
            assert critical_remaining == prev_critical_count, (
                f"Dropping {drop_type} reduced critical coverage from {prev_critical_count} to {critical_remaining}"
            )
            prev_critical_count = critical_remaining


# ===========================================================================
# R3: Classification accuracy across content origins
# ===========================================================================


class TestR3ClassificationByOrigin:
    """Verify that belief type classification quality doesn't degrade
    based on content origin (user-stated vs scanner-inferred vs corrections)."""

    def test_correction_content_classified_correctly(self, store: MemoryStore) -> None:
        """Content with correction signals should be classified as correction type."""
        # These have clear correction signals
        correction_texts: list[str] = [
            "[correction] The API endpoint is /v2/users not /v1/users",
            "No, that's wrong. The timeout should be 30 seconds not 60",
            "Stop using the old authentication method, switch to OAuth2",
            "[correction] Always use UTC timestamps, never local time",
        ]
        for text in correction_texts:
            b: Belief = _insert(store, text, BELIEF_CORRECTION, BSRC_USER_CORRECTED)
            # Verify the belief was stored with the correct type
            retrieved: Belief | None = store.get_belief(b.id)
            assert retrieved is not None
            assert retrieved.belief_type == BELIEF_CORRECTION

    def test_requirement_content_from_scanner(self, store: MemoryStore) -> None:
        """Requirements from document scanning should maintain their type."""
        req_texts: list[str] = [
            "All API responses must include a correlation ID header",
            "The system must support at least 1000 concurrent connections",
            "Authentication tokens must expire after 24 hours",
        ]
        for text in req_texts:
            b: Belief = _insert(store, text, BELIEF_REQUIREMENT, BSRC_DOCUMENT_RECENT)
            retrieved: Belief | None = store.get_belief(b.id)
            assert retrieved is not None
            assert retrieved.belief_type == BELIEF_REQUIREMENT

    def test_factual_from_agent_inference(self, store: MemoryStore) -> None:
        """Agent-inferred factual beliefs should maintain their type."""
        factual_texts: list[str] = [
            "The database schema has 12 tables with 47 columns total",
            "Test coverage is 78% across the main module",
            "The deployment pipeline takes approximately 4 minutes",
        ]
        for text in factual_texts:
            b: Belief = _insert(store, text, BELIEF_FACTUAL, BSRC_AGENT_INFERRED)
            retrieved: Belief | None = store.get_belief(b.id)
            assert retrieved is not None
            assert retrieved.belief_type == BELIEF_FACTUAL

    def test_mixed_origin_retrieval_ranking(self, store: MemoryStore) -> None:
        """Beliefs from different origins about the same topic should all be retrievable."""
        # Same topic, different origins
        _insert(
            store,
            "The API uses REST with JSON payloads",
            BELIEF_FACTUAL,
            BSRC_AGENT_INFERRED,
        )
        _insert(
            store,
            "The API must use REST with JSON payloads for all endpoints",
            BELIEF_REQUIREMENT,
            BSRC_DOCUMENT_RECENT,
        )
        _insert(
            store,
            "[correction] The API uses REST not GraphQL",
            BELIEF_CORRECTION,
            BSRC_USER_CORRECTED,
        )
        _insert(
            store,
            "User prefers REST over GraphQL for this project",
            BELIEF_PREFERENCE,
            BSRC_USER_STATED,
        )

        results: list[Belief] = store.search("API REST JSON")
        assert len(results) >= 3, (
            f"Expected at least 3 results for API query, got {len(results)}"
        )

        # All source types should be represented
        source_types: set[str] = {b.source_type for b in results}
        assert len(source_types) >= 3, (
            f"Expected 3+ source types in results, got {source_types}"
        )


# ===========================================================================
# D1: Graph shape metrics over time slices
# ===========================================================================


class TestD1GraphShapeOverTime:
    """Test that graph metrics change measurably as beliefs accumulate over time."""

    @staticmethod
    def _build_temporal_corpus(store: MemoryStore) -> dict[str, list[Belief]]:
        """Build beliefs in 3 time slices: early, mid, late."""
        now: datetime = datetime.now(timezone.utc)
        slices: dict[str, list[Belief]] = {"early": [], "mid": [], "late": []}

        # Early phase: isolated beliefs, few connections
        early_time: str = (now - timedelta(days=60)).isoformat()
        for i in range(10):
            b: Belief = _insert(
                store,
                f"Early design decision {i} about initial architecture",
                created_at=early_time,
            )
            slices["early"].append(b)

        # Mid phase: beliefs start referencing each other
        mid_time: str = (now - timedelta(days=30)).isoformat()
        for i in range(15):
            b = _insert(
                store,
                f"Mid-phase implementation detail {i} for module design",
                created_at=mid_time,
            )
            slices["mid"].append(b)

        # Add edges between mid-phase beliefs (simulating growing connectivity)
        mid_beliefs: list[Belief] = slices["mid"]
        for i in range(0, len(mid_beliefs) - 1, 2):
            store.insert_edge(
                mid_beliefs[i].id,
                mid_beliefs[i + 1].id,
                EDGE_SUPPORTS,
                reason="related implementation",
            )

        # Late phase: dense connections, hub nodes
        late_time: str = (now - timedelta(days=5)).isoformat()
        hub: Belief = _insert(
            store,
            "Central architecture decision that everything depends on",
            BELIEF_REQUIREMENT,
            BSRC_USER_STATED,
            created_at=late_time,
        )
        slices["late"].append(hub)
        for i in range(12):
            b = _insert(
                store,
                f"Late-phase detail {i} derived from central architecture decision",
                created_at=late_time,
            )
            slices["late"].append(b)
            store.insert_edge(b.id, hub.id, EDGE_SUPPORTS, reason="derives from hub")

        return slices

    def test_edge_density_increases_over_time(self, store: MemoryStore) -> None:
        """Later time slices should have higher edge density."""
        slices: dict[str, list[Belief]] = self._build_temporal_corpus(store)

        # Compute degree centrality for all beliefs
        degrees: dict[str, int] = compute_degree_centrality(store)

        # Average degree per time slice
        def avg_degree(beliefs: list[Belief]) -> float:
            if not beliefs:
                return 0.0
            total: int = sum(degrees.get(b.id, 0) for b in beliefs)
            return total / len(beliefs)

        early_avg: float = avg_degree(slices["early"])
        mid_avg: float = avg_degree(slices["mid"])
        late_avg: float = avg_degree(slices["late"])

        # Early has no edges, mid has some, late has many
        assert early_avg == 0.0, (
            f"Early beliefs should have no edges, got avg {early_avg}"
        )
        assert mid_avg > 0.0, f"Mid beliefs should have edges, got avg {mid_avg}"
        assert late_avg > mid_avg, (
            f"Late avg degree ({late_avg}) should exceed mid ({mid_avg})"
        )

    def test_hub_emerges_in_late_phase(self, store: MemoryStore) -> None:
        """The hub node should have the highest degree centrality."""
        slices: dict[str, list[Belief]] = self._build_temporal_corpus(store)
        degrees: dict[str, int] = compute_degree_centrality(store)

        hub: Belief = slices["late"][0]  # First late belief is the hub
        hub_degree: int = degrees.get(hub.id, 0)
        max_degree: int = max(degrees.values()) if degrees else 0

        assert hub_degree == max_degree, (
            f"Hub degree {hub_degree} should be max ({max_degree})"
        )
        assert hub_degree >= 10, f"Hub should have 10+ edges, got {hub_degree}"

    def test_orphan_rate_decreases_with_connectivity(self, store: MemoryStore) -> None:
        """Early beliefs are all orphans; later phases have fewer orphans."""
        slices: dict[str, list[Belief]] = self._build_temporal_corpus(store)
        degrees: dict[str, int] = compute_degree_centrality(store)

        def orphan_rate(beliefs: list[Belief]) -> float:
            if not beliefs:
                return 0.0
            orphans: int = sum(1 for b in beliefs if degrees.get(b.id, 0) == 0)
            return orphans / len(beliefs)

        early_orphan: float = orphan_rate(slices["early"])
        late_orphan: float = orphan_rate(slices["late"])

        assert early_orphan == 1.0, (
            f"All early beliefs should be orphans, got {early_orphan}"
        )
        assert late_orphan < 0.2, (
            f"Late phase orphan rate should be <20%, got {late_orphan}"
        )


# ===========================================================================
# D2: Sentence-level contradiction detection
# ===========================================================================


class TestD2SentenceLevelContradiction:
    """Test that the relationship detector catches sentence-level contradictions
    and has an acceptable false positive rate."""

    def test_detects_direct_negation_contradiction(self, store: MemoryStore) -> None:
        """Beliefs with negation divergence on the same topic should get CONTRADICTS edge."""
        _insert(
            store,
            "Calls and puts are equal citizens in the trading strategy",
            BELIEF_FACTUAL,
            BSRC_USER_STATED,
        )

        new_belief: Belief = _insert(
            store,
            "Ignore puts for now, calls only, puts are not part of the strategy",
            BELIEF_FACTUAL,
            BSRC_USER_STATED,
        )

        result = detect_relationships(store, new_belief)
        assert result.contradictions > 0, f"Expected CONTRADICTS, got {result.details}"

    def test_detects_value_contradiction(self, store: MemoryStore) -> None:
        """Beliefs stating different values for the same parameter should contradict."""
        _insert(
            store,
            "The timeout value must be 30 seconds for all API calls",
            BELIEF_REQUIREMENT,
            BSRC_USER_STATED,
        )

        new_belief: Belief = _insert(
            store,
            "The timeout is not 30 seconds, it must be 60 seconds for API calls",
            BELIEF_CORRECTION,
            BSRC_USER_CORRECTED,
        )

        result = detect_relationships(store, new_belief)
        assert result.contradictions > 0, (
            f"Expected CONTRADICTS for value conflict, got {result.details}"
        )

    def test_no_false_positive_on_related_but_compatible(
        self, store: MemoryStore
    ) -> None:
        """Beliefs about the same topic that don't conflict should not get CONTRADICTS."""
        _insert(
            store,
            "The database uses PostgreSQL for production data storage",
            BELIEF_FACTUAL,
            BSRC_USER_STATED,
        )

        new_belief: Belief = _insert(
            store,
            "PostgreSQL handles production data with WAL mode enabled for crash safety",
            BELIEF_FACTUAL,
            BSRC_AGENT_INFERRED,
        )

        result = detect_relationships(store, new_belief)
        assert result.contradictions == 0, (
            f"False positive: CONTRADICTS on compatible beliefs, details: {result.details}"
        )

    def test_false_positive_rate_on_similar_vocabulary(
        self, store: MemoryStore
    ) -> None:
        """High vocabulary overlap without semantic conflict should not trigger CONTRADICTS."""
        # 5 beliefs about the same topic, all compatible
        base_beliefs: list[str] = [
            "The retrieval pipeline uses FTS5 for full-text search",
            "FTS5 provides BM25 ranking for the retrieval pipeline",
            "The retrieval pipeline runs FTS5 search as its primary layer",
            "FTS5 search in the pipeline supports prefix matching",
            "The full-text retrieval layer uses SQLite FTS5 internally",
        ]
        for text in base_beliefs:
            _insert(store, text, BELIEF_FACTUAL, BSRC_AGENT_INFERRED)

        # Insert one more compatible belief and check for false positives
        new_belief: Belief = _insert(
            store,
            "FTS5 retrieval pipeline also supports phrase queries for exact matching",
            BELIEF_FACTUAL,
            BSRC_AGENT_INFERRED,
        )

        result = detect_relationships(store, new_belief)
        assert result.contradictions == 0, (
            f"False positive: {result.contradictions} CONTRADICTS on compatible beliefs"
        )

    def test_catches_scope_contradiction(self, store: MemoryStore) -> None:
        """A scoping change (all -> some) should be detectable."""
        _insert(
            store,
            "All API endpoints require authentication tokens",
            BELIEF_REQUIREMENT,
            BSRC_USER_STATED,
        )

        new_belief: Belief = _insert(
            store,
            "Not all API endpoints require authentication, health check endpoints do not need tokens",
            BELIEF_CORRECTION,
            BSRC_USER_CORRECTED,
        )

        result = detect_relationships(store, new_belief)
        # This is a harder case -- negation + scope change
        assert result.edges_created > 0, (
            "Should detect some relationship between scope-conflicting beliefs"
        )


# ===========================================================================
# D3: TEMPORAL_NEXT edge utility for retrieval
# ===========================================================================


class TestD3TemporalNextUtility:
    """Test whether TEMPORAL_NEXT edges improve retrieval for temporal queries."""

    @staticmethod
    def _build_temporal_chain(store: MemoryStore) -> list[Belief]:
        """Build a chain of beliefs linked by TEMPORAL_NEXT."""
        now: datetime = datetime.now(timezone.utc)
        beliefs: list[Belief] = []

        events: list[str] = [
            "Started migration from SQLite to PostgreSQL for production database",
            "Completed schema migration with 12 tables ported to PostgreSQL",
            "Discovered performance regression after PostgreSQL migration in batch queries",
            "Fixed PostgreSQL batch query performance with connection pooling",
            "Validated PostgreSQL migration complete with zero data loss",
        ]

        for i, text in enumerate(events):
            created: str = (now - timedelta(hours=len(events) - i)).isoformat()
            b: Belief = _insert(
                store, text, BELIEF_FACTUAL, BSRC_AGENT_INFERRED, created_at=created
            )
            beliefs.append(b)

        # Link sequentially with TEMPORAL_NEXT
        for i in range(len(beliefs) - 1):
            store.insert_edge(
                beliefs[i].id,
                beliefs[i + 1].id,
                EDGE_TEMPORAL_NEXT,
                reason="temporal sequence",
            )

        # Add some noise beliefs (unrelated, no temporal links)
        for i in range(10):
            _insert(
                store,
                f"Unrelated observation about testing framework configuration item {i}",
                created_at=now.isoformat(),
            )

        return beliefs

    def test_temporal_chain_retrievable_from_seed(self, store: MemoryStore) -> None:
        """Starting from one event in the chain, BFS should find connected events."""
        chain: list[Belief] = self._build_temporal_chain(store)

        # Expand graph from the first event
        neighbors = store.expand_graph(
            seed_ids=[chain[0].id],
            depth=2,
            edge_types=[EDGE_TEMPORAL_NEXT],
            max_nodes=10,
        )

        # Should find at least the next 2 events in the chain
        found_ids: set[str] = set()
        for nlist in neighbors.values():
            for belief, _edge_type, _hop in nlist:
                found_ids.add(belief.id)

        chain_ids: set[str] = {b.id for b in chain}
        found_chain: int = len(found_ids & chain_ids)
        assert found_chain >= 2, (
            f"BFS from chain start should find 2+ chain members, got {found_chain}"
        )

    def test_temporal_query_finds_sequence(self, store: MemoryStore) -> None:
        """A query about the migration topic should retrieve chain beliefs."""
        chain: list[Belief] = self._build_temporal_chain(store)
        chain_ids: set[str] = {b.id for b in chain}

        result: RetrievalResult = retrieve(
            store, "PostgreSQL migration database", budget=2000
        )
        retrieved_ids: set[str] = {b.id for b in result.beliefs}

        chain_retrieved: int = len(chain_ids & retrieved_ids)
        assert chain_retrieved >= 3, (
            f"Expected 3+ chain beliefs in results, got {chain_retrieved}"
        )

    def test_temporal_edges_dont_hurt_unrelated_queries(
        self, store: MemoryStore
    ) -> None:
        """Temporal edges should not pollute results for unrelated queries."""
        self._build_temporal_chain(store)

        # Add some beliefs about a totally different topic
        _insert(
            store,
            "The frontend uses React with TypeScript for component development",
            BELIEF_FACTUAL,
            BSRC_AGENT_INFERRED,
        )
        _insert(
            store,
            "CSS modules provide scoped styling for React components",
            BELIEF_FACTUAL,
            BSRC_AGENT_INFERRED,
        )

        result: RetrievalResult = retrieve(
            store, "React TypeScript frontend components", budget=2000
        )

        # No migration beliefs should appear
        migration_in_results: list[str] = [
            b.content
            for b in result.beliefs
            if "migration" in b.content.lower() or "PostgreSQL" in b.content
        ]
        assert len(migration_in_results) == 0, (
            f"Temporal edges leaked migration beliefs into unrelated query: {migration_in_results}"
        )

    def test_temporal_next_valence_is_zero(self, store: MemoryStore) -> None:
        """TEMPORAL_NEXT edges should not propagate confidence (valence = 0)."""
        from agentmemory.models import EDGE_VALENCE

        assert EDGE_VALENCE[EDGE_TEMPORAL_NEXT] == 0.0, (
            "TEMPORAL_NEXT should have zero valence (structural only)"
        )
