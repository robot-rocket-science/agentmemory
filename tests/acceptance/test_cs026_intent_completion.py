"""CS-026: Implicit Intent Completion Gated by Permission Posture.

Pass criterion: Permission-gated behavioral beliefs are storable and
retrievable with their gate conditions intact.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_PREFERENCE,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.store import MemoryStore


def test_cs026_intent_belief_with_condition_retrievable(store: MemoryStore) -> None:
    """A behavioral belief with permission gate conditions should be retrievable."""
    store.insert_belief(
        content=(
            "When user says 'make a todo list', they mean 'make and execute'. "
            "Safe only when running with skip-permissions or autonomous mode."
        ),
        belief_type=BELIEF_PREFERENCE,
        source_type=BSRC_USER_STATED,
        locked=True,
    )

    results: list[Belief] = store.search("make a todo list execute")
    assert len(results) >= 1
    # The retrieved belief must include the gate condition
    matched: list[Belief] = [r for r in results if "todo list" in r.content]
    assert len(matched) >= 1
    assert any(
        "autonomous" in r.content or "skip-permissions" in r.content for r in matched
    ), "Retrieved intent belief must include permission gate condition"


def test_cs026_unconditional_vs_conditional_beliefs(store: MemoryStore) -> None:
    """The system should store both conditional and unconditional preferences."""
    store.insert_belief(
        content="User prefers terse responses with no trailing summaries",
        belief_type=BELIEF_PREFERENCE,
        source_type=BSRC_USER_STATED,
        locked=True,
    )
    store.insert_belief(
        content=(
            "User means 'execute immediately' when saying 'make a plan'. "
            "Only safe in autonomous mode."
        ),
        belief_type=BELIEF_PREFERENCE,
        source_type=BSRC_USER_STATED,
        locked=True,
    )

    # Both should be retrievable for different queries
    terse: list[Belief] = store.search("response style summary")
    assert any("terse" in r.content for r in terse)

    intent: list[Belief] = store.search("make a plan execute autonomous")
    assert any("execute immediately" in r.content for r in intent)
