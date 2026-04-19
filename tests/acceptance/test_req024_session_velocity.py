"""REQ-024: Session velocity tracking.

Sessions must track velocity_items_per_hour and velocity_tier. The tier
maps to: sprint (>10), moderate (>=5), steady (>=2), deep (<2).
"""

from __future__ import annotations

from agentmemory.models import Session
from agentmemory.store import MemoryStore


def test_velocity_computed_on_complete(store: MemoryStore) -> None:
    """Creating a session, adding items, and completing it produces velocity."""
    session: Session = store.create_session(model="claude", project_context="test")

    # Simulate work: add beliefs_created and corrections_detected
    store.increment_session_metrics(
        session.id,
        beliefs_created=12,
        corrections_detected=3,
    )

    store.complete_session(session.id, summary="velocity test")

    updated: Session | None = store.get_session(session.id)
    assert updated is not None
    assert updated.completed_at is not None
    assert updated.velocity_items_per_hour is not None, (
        "velocity_items_per_hour should be computed on session completion"
    )
    assert updated.velocity_tier is not None, (
        "velocity_tier should be set on session completion"
    )
    # 15 items in < 1 second elapsed -> clamped to 0.5h min -> 30 items/h -> sprint
    assert updated.velocity_items_per_hour > 0.0


def test_velocity_tier_sprint(store: MemoryStore) -> None:
    """High item count in short session yields 'sprint' tier."""
    session: Session = store.create_session(model="claude", project_context="test")
    store.increment_session_metrics(session.id, beliefs_created=20)
    store.complete_session(session.id, summary="sprint session")

    updated: Session | None = store.get_session(session.id)
    assert updated is not None
    # 20 items / 0.5h (minimum clamp) = 40 items/h -> sprint
    assert updated.velocity_tier == "sprint"


def test_velocity_tier_deep(store: MemoryStore) -> None:
    """Zero items produces 'deep' tier (velocity ~ 0)."""
    session: Session = store.create_session(model="claude", project_context="test")
    # No metrics incremented -- 0 items
    store.complete_session(session.id, summary="deep session")

    updated: Session | None = store.get_session(session.id)
    assert updated is not None
    assert updated.velocity_tier == "deep"
    assert updated.velocity_items_per_hour is not None
    assert updated.velocity_items_per_hour < 2.0


def test_velocity_tier_labels_are_valid(store: MemoryStore) -> None:
    """All velocity tiers must be one of the four defined labels."""
    valid_tiers: set[str] = {"sprint", "moderate", "steady", "deep"}

    # Create sessions with varying item counts to hit different tiers
    item_counts: list[int] = [0, 1, 3, 6, 15, 50]
    for count in item_counts:
        session: Session = store.create_session(model="claude", project_context="test")
        if count > 0:
            store.increment_session_metrics(session.id, beliefs_created=count)
        store.complete_session(session.id, summary=f"tier test count={count}")

        updated: Session | None = store.get_session(session.id)
        assert updated is not None
        assert updated.velocity_tier in valid_tiers, (
            f"velocity_tier '{updated.velocity_tier}' not in {valid_tiers} "
            f"for item count {count}"
        )
