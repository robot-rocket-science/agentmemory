"""CS-035: Triple Self-Contradiction on Implemented Features.

Pass criterion: When a feature-existence belief and a feature-absence belief
coexist, the system detects the contradiction and surfaces it.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_CORRECTION,
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_CORRECTED,
    EDGE_CONTRADICTS,
    Belief,
)
from agentmemory.relationship_detector import detect_relationships
from agentmemory.retrieval import flag_contradictions, retrieve
from agentmemory.store import MemoryStore


def test_cs035_feature_existence_contradiction_detected(
    store: MemoryStore,
) -> None:
    """Contradicting beliefs about whether a feature exists should be detected."""
    store.insert_belief(
        content="Temporal decay is implemented in the scoring system with type-specific half-lives for belief aging",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    denial: Belief = store.insert_belief(
        content="Temporal decay is not implemented in the scoring system, belief aging does not exist",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    result = detect_relationships(store, denial)
    assert result.contradictions > 0, (
        f"Should detect contradiction about decay existence. Got: {result.details}"
    )


def test_cs035_correction_supersedes_wrong_claim(store: MemoryStore) -> None:
    """A correction should supersede a wrong claim about missing features."""
    wrong: Belief = store.insert_belief(
        content="No compaction or pruning is built into the system",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    correction: Belief = store.insert_belief(
        content=(
            "[correction] Compaction IS implemented. PreCompact/PostCompact hooks "
            "are wired in settings.json, log rotation works, archived segments "
            "are auto-ingested."
        ),
        belief_type=BELIEF_CORRECTION,
        source_type=BSRC_USER_CORRECTED,
        locked=True,
    )

    # Supersede the wrong claim
    store.supersede_belief(old_id=wrong.id, new_id=correction.id, reason="was wrong")

    # The wrong claim should be superseded
    old: Belief | None = store.get_belief(wrong.id)
    assert old is not None
    assert old.superseded_by == correction.id

    # Searching should return the correction, not the wrong claim
    results = retrieve(store, "compaction pruning system")
    result_ids: set[str] = {b.id for b in results.beliefs}
    assert correction.id in result_ids, "Correction should be in results"
    assert wrong.id not in result_ids, "Superseded wrong claim should not appear"


def test_cs035_contradiction_warning_in_retrieval(store: MemoryStore) -> None:
    """If contradicting beliefs both appear in results, a warning should be raised."""
    b1: Belief = store.insert_belief(
        content="Hooks are configured and active in settings.json",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    b2: Belief = store.insert_belief(
        content="Hooks are not configured, they are proposed designs only",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    # Create CONTRADICTS edge
    store.insert_edge(b1.id, b2.id, EDGE_CONTRADICTS, reason="existence conflict")

    # flag_contradictions should detect this
    warnings: list[str] = flag_contradictions(store, [b1, b2])
    assert len(warnings) >= 1, "Should flag contradiction between hook beliefs"
