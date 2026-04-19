"""CS-031: Decision Never Stored as Belief.

Pass criterion: Decisions are storable with execution state and retrievable
when the topic is queried. Unexecuted decisions are distinguishable.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.store import MemoryStore


def test_cs031_decision_stored_and_retrievable(store: MemoryStore) -> None:
    """A decision 'uninstall tool X' should be storable and retrievable."""
    store.insert_belief(
        content="Decision: uninstall MemPalace and use only agentmemory. Status: decided.",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        locked=True,
    )

    results: list[Belief] = store.search("uninstall MemPalace agentmemory")
    assert len(results) >= 1
    assert any("uninstall" in r.content and "MemPalace" in r.content for r in results)


def test_cs031_unexecuted_decision_distinguishable(store: MemoryStore) -> None:
    """A decided-but-not-executed decision should be distinguishable from a completed one."""
    store.insert_belief(
        content="Decision: migrate database to PostgreSQL. Status: decided, not executed.",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
    )
    store.insert_belief(
        content="Decision: add WAL mode to SQLite. Status: done, commit abc123.",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
    )

    results: list[Belief] = store.search("database decision migration")
    assert len(results) >= 1
    # Both should appear -- the consumer can distinguish by content
    contents: list[str] = [r.content for r in results]
    has_unexecuted: bool = any("not executed" in c for c in contents)
    assert has_unexecuted, "Unexecuted decision should be retrievable with status"
