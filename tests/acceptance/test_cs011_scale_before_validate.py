"""CS-011: Scale Before Validate.

Pass criterion: A locked behavioral constraint about validating before scaling
is surfaced by search and ranked above unlocked action beliefs by retrieve().
"""
from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BELIEF_REQUIREMENT,
    BSRC_AGENT_INFERRED,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore

_CONSTRAINT: str = (
    "Before dispatching any multi-run sweep, always run one config "
    "end-to-end locally first."
)


def test_cs011_validate_first_belief_surfaced(store: MemoryStore) -> None:
    """A locked behavioral requirement about validation-before-dispatch is
    returned when searching for 'dispatch parameter sweep'."""
    locked: Belief = store.insert_belief(
        content=_CONSTRAINT,
        belief_type=BELIEF_REQUIREMENT,
        source_type=BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )

    results: list[Belief] = store.search("dispatch sweep run config locally")
    result_ids: list[str] = [b.id for b in results]
    assert locked.id in result_ids, (
        f"Locked validation constraint must be surfaced by search. "
        f"Got IDs: {result_ids}"
    )


def test_cs011_constraint_ranks_above_action(store: MemoryStore) -> None:
    """The locked constraint must rank above an unlocked action belief when
    retrieve() is used with a query about dispatching a sweep."""
    store.insert_belief(
        content=_CONSTRAINT,
        belief_type=BELIEF_REQUIREMENT,
        source_type=BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )
    store.insert_belief(
        content="Ready to dispatch 16 GCP VMs for parameter sweep.",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=0.5,
        beta_param=0.5,
        locked=False,
    )

    result: RetrievalResult = retrieve(store, "dispatch sweep run configs")
    assert result.beliefs, "Expected results from retrieve()"

    top: Belief = result.beliefs[0]
    assert top.locked is True, (
        f"Locked validation constraint must rank first. "
        f"Top belief: '{top.content}' locked={top.locked}"
    )
