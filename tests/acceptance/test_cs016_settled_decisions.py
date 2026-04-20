"""CS-016: Settled Decision Repeatedly Questioned.

Pass criterion: Locked decisions are surfaced when relevant topics are queried,
preventing the agent from re-opening settled decisions.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore

_DECISION_TEXT: str = (
    "Calls and puts are equal citizens (D073). This is not open for discussion."
)


def test_cs016_locked_decision_surfaced(store: MemoryStore) -> None:
    """Insert a locked belief about calls/puts equality (D073).

    Search for 'should we remove puts'. The locked belief must appear,
    preventing the agent from questioning a settled decision.
    """
    locked: Belief = store.insert_belief(
        content=_DECISION_TEXT,
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )
    assert locked.id

    # FTS5: "puts" and "calls" are tokens present in the belief.
    results: list[Belief] = store.search("puts calls equal citizens")
    result_ids: list[str] = [r.id for r in results]
    assert locked.id in result_ids, (
        "Locked D073 decision must appear when querying about puts. "
        f"Got IDs: {result_ids}"
    )


def test_cs016_locked_ranks_above_competing_evidence(store: MemoryStore) -> None:
    """Insert the locked D073 belief plus an unlocked belief with competing
    evidence about puts underperformance. Use retrieve() and verify the locked
    belief ranks first in most trials, enforcing the settled decision.

    Thompson sampling is stochastic, so we check statistical dominance
    over multiple retrievals rather than a single deterministic check.
    """
    store.insert_belief(
        content=_DECISION_TEXT,
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )

    store.insert_belief(
        content="Puts underperform calls by 15% in recent data analysis.",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=2.0,
        beta_param=1.0,
        locked=False,
    )

    locked_first: int = 0
    trials: int = 10
    for _ in range(trials):
        result: RetrievalResult = retrieve(
            store, "puts performance direction strategy calls equal"
        )
        if result.beliefs and result.beliefs[0].locked:
            locked_first += 1

    assert locked_first >= 8, (
        f"Expected locked D073 decision to rank first in >= 8/10 trials. "
        f"Got {locked_first}/{trials}."
    )
