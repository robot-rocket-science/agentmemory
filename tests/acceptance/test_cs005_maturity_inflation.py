"""CS-005: Project Maturity Inflation.

Pass criterion: Provenance/rigor metadata columns (rigor_tier, method,
sample_size) exist and round-trip correctly. Session velocity tracking
computes and stores velocity_items_per_hour and velocity_tier.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    Belief,
    Session,
)
from agentmemory.store import MemoryStore


def test_cs005_rigor_tier_stored(store: MemoryStore) -> None:
    """Insert a belief with rigor_tier, method, and sample_size.

    Retrieve it and verify all three fields are stored and returned correctly,
    ensuring provenance metadata survives the round-trip.
    """
    belief: Belief = store.insert_belief(
        content="Signal quality improves with 30-minute lookback window",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=3.0,
        beta_param=1.0,
        rigor_tier="simulated",
        method="synthetic_data",
        sample_size=38,
    )
    assert belief.id

    retrieved: Belief | None = store.get_belief(belief.id)
    assert retrieved is not None

    assert retrieved.rigor_tier == "simulated", (
        f"Expected rigor_tier='simulated', got '{retrieved.rigor_tier}'"
    )
    assert retrieved.method == "synthetic_data", (
        f"Expected method='synthetic_data', got '{retrieved.method}'"
    )
    assert retrieved.sample_size == 38, (
        f"Expected sample_size=38, got {retrieved.sample_size}"
    )


def test_cs005_velocity_tracking(store: MemoryStore) -> None:
    """Create a session, add some beliefs to generate metrics, complete it.

    Verify velocity_items_per_hour and velocity_tier are computed and stored.
    """
    session: Session = store.create_session(
        model="test-model",
        project_context="agentmemory",
    )
    assert session.id

    # Increment session metrics so velocity has something to compute.
    store.increment_session_metrics(
        session.id,
        beliefs_created=10,
        corrections_detected=2,
    )

    store.complete_session(session.id, summary="velocity tracking test")

    completed: Session | None = store.get_session(session.id)
    assert completed is not None
    assert completed.completed_at is not None, "Session must be marked complete"

    assert completed.velocity_items_per_hour is not None, (
        "velocity_items_per_hour must be computed on session completion"
    )
    assert completed.velocity_items_per_hour > 0, (
        f"Expected positive velocity, got {completed.velocity_items_per_hour}"
    )

    assert completed.velocity_tier is not None, (
        "velocity_tier must be assigned on session completion"
    )
    assert completed.velocity_tier in {"sprint", "moderate", "steady", "deep"}, (
        f"Expected valid velocity_tier, got '{completed.velocity_tier}'"
    )
