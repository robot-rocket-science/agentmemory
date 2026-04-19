"""CS-012: Duplicate Code Corruption by Auto-Mode Agent.

Pass criterion: A behavioral belief about post-edit validation is storable,
retrievable, and ranked highly for edit-related queries.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_PROCEDURAL,
    BELIEF_REQUIREMENT,
    BSRC_USER_CORRECTED,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.store import MemoryStore


def test_cs012_post_edit_validation_belief_retrievable(store: MemoryStore) -> None:
    """A behavioral belief about verifying Python files after edit should be
    retrievable when querying about file editing."""
    store.insert_belief(
        content="After editing any Python file, verify it parses without SyntaxError",
        belief_type=BELIEF_PROCEDURAL,
        source_type=BSRC_USER_STATED,
        locked=True,
    )

    results: list[Belief] = store.search("editing Python file syntax check")
    assert len(results) >= 1
    assert any("SyntaxError" in r.content for r in results)


def test_cs012_auto_mode_corruption_flag(store: MemoryStore) -> None:
    """A belief flagging auto-mode edits as needing review should be retrievable."""
    store.insert_belief(
        content="Files last edited by auto-mode have not been human-reviewed",
        belief_type=BELIEF_REQUIREMENT,
        source_type=BSRC_USER_CORRECTED,
        locked=True,
    )

    results: list[Belief] = store.search("auto-mode edited file review")
    assert len(results) >= 1
    assert any("auto-mode" in r.content for r in results)
