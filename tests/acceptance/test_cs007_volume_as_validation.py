"""CS-007: Volume and Distinctness Presented as Validation.

Pass criterion: The store tracks rigor metadata on beliefs and can distinguish
validated from unvalidated findings via the rigor_tier field.
"""
from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    Belief,
)
from agentmemory.store import MemoryStore


def test_cs007_rigor_tier_distinguishes_findings(store: MemoryStore) -> None:
    """Three beliefs with distinct rigor tiers are stored and retrievable
    with the correct tier on each."""
    b_hyp: Belief = store.insert_belief(
        content="Retrieval latency is roughly 50ms under load",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        rigor_tier="hypothesis",
    )
    b_sim: Belief = store.insert_belief(
        content="Retrieval latency averages 48ms in simulation with 1000 queries",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        rigor_tier="simulated",
    )
    b_emp: Belief = store.insert_belief(
        content="Retrieval latency is 52ms p95 measured over 30 days in production",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        rigor_tier="empirically_tested",
    )

    results: list[Belief] = store.search("retrieval latency")
    result_map: dict[str, Belief] = {r.id: r for r in results}

    assert b_hyp.id in result_map, f"Hypothesis belief missing from results: {list(result_map)}"
    assert b_sim.id in result_map, f"Simulated belief missing from results: {list(result_map)}"
    assert b_emp.id in result_map, f"Empirical belief missing from results: {list(result_map)}"

    assert result_map[b_hyp.id].rigor_tier == "hypothesis"
    assert result_map[b_sim.id].rigor_tier == "simulated"
    assert result_map[b_emp.id].rigor_tier == "empirically_tested"


def test_cs007_unvalidated_beliefs_identifiable(store: MemoryStore) -> None:
    """Of 10 beliefs (8 hypothesis, 2 empirically tested), filtering by
    rigor_tier correctly isolates the 8 unvalidated ones."""
    hyp_ids: list[str] = []
    for i in range(8):
        b: Belief = store.insert_belief(
            content=f"Unvalidated finding number {i} about caching behavior",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
            rigor_tier="hypothesis",
        )
        hyp_ids.append(b.id)

    emp_ids: list[str] = []
    for i in range(2):
        b = store.insert_belief(
            content=f"Validated finding number {i} about caching measured in prod",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
            rigor_tier="empirically_tested",
        )
        emp_ids.append(b.id)

    # Query all active beliefs and filter to hypothesis tier.
    conn = store._conn  # pyright: ignore[reportPrivateUsage]
    rows = conn.execute(
        "SELECT id, rigor_tier FROM beliefs WHERE valid_to IS NULL"
    ).fetchall()
    unvalidated: list[str] = [r["id"] for r in rows if r["rigor_tier"] == "hypothesis"]

    assert len(unvalidated) == 8, f"Expected 8 unvalidated beliefs, got {len(unvalidated)}"
    assert set(unvalidated) == set(hyp_ids)
