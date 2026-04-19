"""REQ-025: Rigor tier classification.

Pass criteria:
- Beliefs have a rigor_tier field with 4-tier classification.
- Valid tiers: hypothesis, simulated, empirically_tested, validated.
- Default rigor_tier for new beliefs is "hypothesis".
- rigor_tier persists across insert/retrieve round-trip.
- rigor_tier can be updated via SQL and the change persists.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BELIEF_PROCEDURAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.store import MemoryStore

VALID_TIERS: list[str] = ["hypothesis", "simulated", "empirically_tested", "validated"]


def test_req025_each_rigor_tier_persists(store: MemoryStore) -> None:
    """Create a belief at each rigor tier and verify persistence."""
    for tier in VALID_TIERS:
        belief: Belief = store.insert_belief(
            content=f"Test belief at tier {tier}",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
            rigor_tier=tier,
        )
        retrieved: Belief | None = store.get_belief(belief.id)
        assert retrieved is not None, f"Belief at tier {tier} not found after insert"
        assert retrieved.rigor_tier == tier, (
            f"Expected rigor_tier='{tier}', got '{retrieved.rigor_tier}'"
        )


def test_req025_default_rigor_tier_is_hypothesis(store: MemoryStore) -> None:
    """New beliefs without explicit rigor_tier default to 'hypothesis'."""
    belief: Belief = store.insert_belief(
        content="Belief with default rigor tier",
        belief_type=BELIEF_PROCEDURAL,
        source_type=BSRC_USER_STATED,
    )
    assert belief.rigor_tier == "hypothesis", (
        f"Expected default rigor_tier='hypothesis', got '{belief.rigor_tier}'"
    )

    retrieved: Belief | None = store.get_belief(belief.id)
    assert retrieved is not None
    assert retrieved.rigor_tier == "hypothesis", (
        f"Expected persisted default 'hypothesis', got '{retrieved.rigor_tier}'"
    )


def test_req025_update_rigor_tier(store: MemoryStore) -> None:
    """Update rigor_tier on an existing belief and verify the change persists."""
    belief: Belief = store.insert_belief(
        content="Belief to promote through rigor tiers",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        rigor_tier="hypothesis",
    )
    assert belief.rigor_tier == "hypothesis"

    # Update via direct SQL (no dedicated method exists yet)
    store.connection.execute(
        "UPDATE beliefs SET rigor_tier = ?, updated_at = datetime('now') WHERE id = ?",
        ("empirically_tested", belief.id),
    )
    store.connection.commit()

    updated: Belief | None = store.get_belief(belief.id)
    assert updated is not None
    assert updated.rigor_tier == "empirically_tested", (
        f"Expected rigor_tier='empirically_tested' after update, "
        f"got '{updated.rigor_tier}'"
    )
