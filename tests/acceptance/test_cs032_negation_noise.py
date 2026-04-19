"""CS-032: Negation Pattern Noise in Retrieval.

Pass criterion: Queries containing negation words must not be flooded
with correction beliefs that share only the negation word. The retrieve
pipeline's negation noise filter must deprioritize these.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_CORRECTION,
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_CORRECTED,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore


def test_cs032_negation_corrections_dont_dominate(store: MemoryStore) -> None:
    """Correction beliefs sharing only 'not' with the query should not
    completely exclude the topical target from results."""
    # Target belief -- give it user_stated source for higher weight
    target: Belief = store.insert_belief(
        content="Paper trading agents are not firing in the morning on archon server",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
    )

    # 50 correction beliefs with "not" about unrelated topics
    for i in range(50):
        store.insert_belief(
            content=f"Module {i} is not compatible with the new API version {i + 10}",
            belief_type=BELIEF_CORRECTION,
            source_type=BSRC_USER_CORRECTED,
        )

    result: RetrievalResult = retrieve(
        store, "paper trading agents not firing", budget=2000
    )

    # The target belief should at least be in results (not excluded entirely)
    result_ids: set[str] = {b.id for b in result.beliefs}
    assert target.id in result_ids, (
        "Target belief about paper trading must be in results"
    )


def test_cs032_topical_match_beats_negation_match(store: MemoryStore) -> None:
    """A belief matching on topic words should outrank one matching only on 'not'."""
    topical: Belief = store.insert_belief(
        content="The cron service is not running on the production server",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    negation_only: Belief = store.insert_belief(
        content="The test framework is not compatible with Python 3.8",
        belief_type=BELIEF_CORRECTION,
        source_type=BSRC_USER_CORRECTED,
    )

    results: list[Belief] = store.search("cron service not running server")
    result_ids: list[str] = [r.id for r in results]

    if topical.id in result_ids and negation_only.id in result_ids:
        topical_rank: int = result_ids.index(topical.id)
        negation_rank: int = result_ids.index(negation_only.id)
        assert topical_rank < negation_rank, (
            f"Topical match (rank {topical_rank}) should outrank "
            f"negation-only match (rank {negation_rank})"
        )
