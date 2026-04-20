"""CS-020: Ignoring Task ID Present in the Instruction.

Pass criterion: Beliefs containing specific task IDs are retrievable by
searching for those IDs, and ID collisions are detectable.
"""
from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.store import MemoryStore


def test_cs020_task_id_retrievable(store: MemoryStore) -> None:
    """A belief referencing task #41 is found when searching for that ID."""
    task_belief: Belief = store.insert_belief(
        content="Current task is #41 (requirements traceability extraction)",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
    )

    results: list[Belief] = store.search("task 41 traceability")
    result_ids: list[str] = [r.id for r in results]
    assert task_belief.id in result_ids, (
        "Belief referencing task #41 must be retrievable by ID search. "
        f"Got IDs: {result_ids}"
    )


def test_cs020_id_collision_detectable(store: MemoryStore) -> None:
    """Two beliefs both referencing 'Exp 40' are both returned, allowing
    collision detection."""
    belief_a: Belief = store.insert_belief(
        content="Exp 40 tested BM25 retrieval with 500 queries",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
    )
    belief_b: Belief = store.insert_belief(
        content="Exp 40 measured insertion throughput under concurrent load",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
    )

    results: list[Belief] = store.search("Exp 40")
    result_ids: list[str] = [r.id for r in results]
    assert belief_a.id in result_ids, (
        f"First Exp 40 belief must be in results. Got: {result_ids}"
    )
    assert belief_b.id in result_ids, (
        f"Second Exp 40 belief must be in results. Got: {result_ids}"
    )
    # Both appearing means the agent can detect the collision.
    assert len([rid for rid in result_ids if rid in {belief_a.id, belief_b.id}]) == 2
