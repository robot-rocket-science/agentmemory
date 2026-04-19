"""REQ-023: Provenance metadata.

Beliefs must carry rigor_tier, method, sample_size, data_source, and
independently_validated fields. These must be settable at creation, updatable
after the fact, and preserved through search/retrieval round-trips.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.store import MemoryStore


def test_provenance_fields_settable_at_creation(store: MemoryStore) -> None:
    """Insert a belief with all provenance fields and verify they persist."""
    b: Belief = store.insert_belief(
        content="Retrieval latency p95 is under 200ms",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        rigor_tier="empirically_tested",
        method="benchmark_suite",
        sample_size=1000,
        data_source="latency_logs",
        independently_validated=True,
    )

    fetched: Belief | None = store.get_belief(b.id)
    assert fetched is not None
    assert fetched.rigor_tier == "empirically_tested"
    assert fetched.method == "benchmark_suite"
    assert fetched.sample_size == 1000
    assert fetched.data_source == "latency_logs"
    assert fetched.independently_validated is True


def test_provenance_defaults(store: MemoryStore) -> None:
    """Beliefs created without explicit provenance get safe defaults."""
    b: Belief = store.insert_belief(
        content="Default provenance belief",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    fetched: Belief | None = store.get_belief(b.id)
    assert fetched is not None
    assert fetched.rigor_tier == "hypothesis"
    assert fetched.method is None
    assert fetched.sample_size is None
    assert fetched.data_source == ""
    assert fetched.independently_validated is False


def test_provenance_update_persists(store: MemoryStore) -> None:
    """Updating provenance fields via SQL persists across reads."""
    b: Belief = store.insert_belief(
        content="Compression ratio averages 55 percent",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        rigor_tier="hypothesis",
    )

    # Update provenance via direct SQL (no dedicated method exists yet)
    store.connection.execute(
        """UPDATE beliefs
           SET rigor_tier = ?, method = ?, sample_size = ?,
               data_source = ?, independently_validated = ?
           WHERE id = ?""",
        ("simulated", "exp_042", 50, "compression_bench", 1, b.id),
    )
    store.connection.commit()

    fetched: Belief | None = store.get_belief(b.id)
    assert fetched is not None
    assert fetched.rigor_tier == "simulated"
    assert fetched.method == "exp_042"
    assert fetched.sample_size == 50
    assert fetched.data_source == "compression_bench"
    assert fetched.independently_validated is True


def test_search_results_include_provenance(store: MemoryStore) -> None:
    """Beliefs returned by search carry provenance metadata intact."""
    store.insert_belief(
        content="HRR graph encode takes 1.2 seconds on 4K edges",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        rigor_tier="empirically_tested",
        method="profiler",
        sample_size=200,
        data_source="perf_trace",
        independently_validated=False,
    )

    results: list[Belief] = store.search("HRR graph encode", top_k=5)
    assert len(results) >= 1
    hit: Belief = results[0]
    assert hit.rigor_tier == "empirically_tested"
    assert hit.method == "profiler"
    assert hit.sample_size == 200
    assert hit.data_source == "perf_trace"
    assert hit.independently_validated is False
