"""CS-033: Cold Start -- First Session Has No Memory.

Pass criterion: When querying a topic with zero relevant beliefs,
the system must return few or no results rather than flooding with
irrelevant beliefs from other topics.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    Belief,
)
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore


def test_cs033_empty_store_returns_no_results(store: MemoryStore) -> None:
    """An empty store should return zero results for any query."""
    result: RetrievalResult = retrieve(store, "slash command architecture")
    assert len(result.beliefs) == 0


def test_cs033_unrelated_beliefs_not_returned(store: MemoryStore) -> None:
    """When the store has beliefs about topic A only, querying topic B
    should not return topic A beliefs as if they were relevant."""
    # Fill with agentmemory-specific beliefs
    for i in range(20):
        store.insert_belief(
            content=f"FTS5 retrieval pipeline processes belief index entry {i}",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )

    # Query about a completely unrelated topic
    result: RetrievalResult = retrieve(
        store, "Kubernetes pod restart CrashLoopBackOff", budget=2000
    )

    # Should return zero or very few results (FTS5 won't match)
    assert len(result.beliefs) <= 2, (
        f"Query about Kubernetes should not return {len(result.beliefs)} "
        f"beliefs about FTS5 retrieval"
    )


def test_cs033_first_session_beliefs_retrievable_in_second(
    store: MemoryStore,
) -> None:
    """Beliefs created during the first session should be retrievable
    in subsequent queries (simulating session 2)."""
    # First session learns about slash commands
    store.insert_belief(
        content="Claude Code slash commands are defined in .claude/commands/ directory",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    store.insert_belief(
        content="Slash command system is always LLM-mediated, not direct execution",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    # Second session queries the same topic
    results: list[Belief] = store.search("slash command architecture")
    assert len(results) >= 1
    assert any("slash" in r.content.lower() for r in results)
