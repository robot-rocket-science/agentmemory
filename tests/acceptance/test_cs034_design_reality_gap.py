"""CS-034: Design-Reality Gap Not Surfaced Until Explicitly Asked.

Pass criterion: When both a "designed" belief and a "not implemented" belief
exist about the same topic, the contradiction detector flags the gap.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    Belief,
)
from agentmemory.relationship_detector import detect_relationships
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore


def test_cs034_design_and_gap_both_retrievable(store: MemoryStore) -> None:
    """Both a design belief and a gap belief about the same feature
    should appear in retrieval results."""
    store.insert_belief(
        content="The feedback loop is designed to update alpha/beta on each retrieval",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    store.insert_belief(
        content="The feedback loop is not implemented yet, feedback_given column is missing",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    result: RetrievalResult = retrieve(store, "feedback loop implementation status")

    contents: list[str] = [b.content for b in result.beliefs]
    has_design: bool = any("designed" in c for c in contents)
    has_gap: bool = any("not implemented" in c for c in contents)

    assert has_design, "Design belief should be in results"
    assert has_gap, "Gap belief should be in results"


def test_cs034_contradiction_detected_between_design_and_gap(
    store: MemoryStore,
) -> None:
    """A gap belief should trigger contradiction detection against a design belief."""
    store.insert_belief(
        content="Hook patterns are active and wired in settings.json for all events",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    gap: Belief = store.insert_belief(
        content="Hook patterns are not active, they are proposed designs only, not wired",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    result = detect_relationships(store, gap)
    assert result.contradictions > 0, (
        f"Should detect contradiction between active and not-active hook beliefs. "
        f"Got: {result.details}"
    )
