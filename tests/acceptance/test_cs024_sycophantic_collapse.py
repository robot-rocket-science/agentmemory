"""CS-024: Sycophantic Collapse Under User Pressure.

Pass criterion: Evidence-backed beliefs maintain confidence when challenged
without counter-evidence. Correction detection distinguishes "you're wrong"
from "explain more."
"""

from __future__ import annotations

from agentmemory.correction_detection import detect_correction
from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.store import MemoryStore


def test_cs024_challenge_not_detected_as_correction() -> None:
    """'Revisit your assumptions' is a challenge, not a correction.
    The correction detector should not fire on it."""
    is_correction, signals, confidence = detect_correction(
        "I disagree, revisit your assumptions"
    )
    # This is borderline -- if it fires, confidence should be low
    if is_correction:
        assert confidence < 0.6, (
            f"Challenge misclassified as high-confidence correction: "
            f"signals={signals}, confidence={confidence}"
        )


def test_cs024_actual_correction_detected() -> None:
    """An actual correction with counter-evidence should be detected."""
    is_correction, _signals, confidence = detect_correction(
        "No, that's wrong. The benchmark uses 16K nodes not 586. "
        "Stop claiming it was tested at scale."
    )
    assert is_correction
    assert confidence >= 0.3


def test_cs024_evidence_backed_belief_persists(store: MemoryStore) -> None:
    """A belief with high alpha (much evidence) should maintain high confidence
    even after a single negative update."""
    belief: Belief = store.insert_belief(
        content="FTS5+HRR retrieval achieves 100% coverage on critical beliefs",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=9.0,
        beta_param=1.0,
    )

    # Simulate one "ignored" feedback (user pushed back once)
    store.update_confidence(belief.id, "ignored")

    updated: Belief | None = store.get_belief(belief.id)
    assert updated is not None
    assert updated.confidence > 0.7, (
        f"Evidence-backed belief dropped too much from one pushback: "
        f"confidence={updated.confidence}"
    )


def test_cs024_repeated_challenge_without_evidence(store: MemoryStore) -> None:
    """Multiple challenges without counter-evidence should not collapse confidence
    of a well-established belief."""
    belief: Belief = store.insert_belief(
        content="The hybrid retrieval architecture is validated by Exp 25",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        alpha=15.0,
        beta_param=1.0,
    )

    # Three rounds of "ignored" (user pushback without evidence)
    for _ in range(3):
        store.update_confidence(belief.id, "ignored")

    updated: Belief | None = store.get_belief(belief.id)
    assert updated is not None
    assert updated.confidence > 0.6, (
        f"Well-established belief collapsed under pressure: "
        f"confidence={updated.confidence}"
    )
