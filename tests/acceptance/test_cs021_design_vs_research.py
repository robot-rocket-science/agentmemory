"""CS-021: Design Spec Disguised as Research.

Pass criterion: rigor_tier distinguishes design hypotheses from empirically
tested findings, so consumers do not conflate speculation with evidence.
"""
from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    Belief,
)
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore


def test_cs021_hypothesis_vs_empirical(store: MemoryStore) -> None:
    """Insert a hypothesis belief and an empirically-tested belief about the
    same topic. Both must be retrievable and distinguishable by rigor_tier."""
    hypothesis: Belief = store.insert_belief(
        content="Proposed architecture uses event sourcing for belief history",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        rigor_tier="hypothesis",
    )
    empirical: Belief = store.insert_belief(
        content="Event sourcing tested on 1000 events, 50ms p95 latency",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        rigor_tier="empirically_tested",
    )

    result: RetrievalResult = retrieve(store, "event sourcing architecture belief history")
    returned: dict[str, Belief] = {b.id: b for b in result.beliefs}

    assert hypothesis.id in returned, (
        f"Hypothesis belief {hypothesis.id} not returned by retrieve()"
    )
    assert empirical.id in returned, (
        f"Empirical belief {empirical.id} not returned by retrieve()"
    )

    assert returned[hypothesis.id].rigor_tier == "hypothesis", (
        f"Expected hypothesis tier, got {returned[hypothesis.id].rigor_tier}"
    )
    assert returned[empirical.id].rigor_tier == "empirically_tested", (
        f"Expected empirically_tested tier, got {returned[empirical.id].rigor_tier}"
    )
