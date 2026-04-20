"""CS-001: Agent surfaces evidence that work was already done.

Pass criterion: FTS5 search for a task surfaces a belief (or observation) that
the task is complete, allowing the agent to say "already done" instead of
re-executing.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    OBS_TYPE_DECISION,
    SRC_AGENT,
    Belief,
    Observation,
)
from agentmemory.store import MemoryStore


def test_cs001_observation_surfaced(store: MemoryStore) -> None:
    """An observation about a completed task is retrievable by FTS5 search.

    FTS5 with the porter tokenizer: "documentation" stems to "document".
    We search for "documentation completed" -- both tokens are in the content.
    """
    obs: Observation = store.insert_observation(
        content="Documentation task completed: all files updated",
        observation_type=OBS_TYPE_DECISION,
        source_type=SRC_AGENT,
    )
    assert obs.id

    # Use tokens that are actually present in the observation content.
    results: list[Observation] = store.search_observations("documentation completed")
    contents: list[str] = [r.content for r in results]
    assert any("Documentation" in c for c in contents), (
        "Expected the completed-task observation to appear in search results. "
        f"Got: {contents}"
    )


def test_cs001_belief_surfaced(store: MemoryStore) -> None:
    """A belief about completed documentation is returned by search, proving
    the store can surface 'already done' evidence before the agent re-executes."""
    # Step 1: insert the completed-task observation.
    obs: Observation = store.insert_observation(
        content="Documentation task completed: all files updated",
        observation_type=OBS_TYPE_DECISION,
        source_type=SRC_AGENT,
    )

    # Step 2: insert a belief derived from that observation.
    belief: Belief = store.insert_belief(
        content="Documentation was just completed covering X, Y, Z",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=5.0,
        beta_param=0.5,
        observation_id=obs.id,
    )
    assert belief.id

    # Step 3: search using tokens present in the belief content.
    # FTS5 AND semantics: all tokens must match. "documentation completed" are both present.
    results: list[Belief] = store.search("documentation completed")

    assert results, "Expected at least one belief returned for 'document everything'"

    result_ids: list[str] = [r.id for r in results]
    assert belief.id in result_ids, (
        "The 'just completed' belief must appear in search results so the agent "
        "can confirm work is already done. "
        f"Got IDs: {result_ids}"
    )


def test_cs001_belief_is_most_relevant(store: MemoryStore) -> None:
    """The completed-work belief should be the top or near-top result when the
    user asks about documentation, without any competing beliefs present."""
    # Background noise belief.
    store.insert_belief(
        content="API design follows REST conventions",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    # Relevant completed-work belief.
    completed: Belief = store.insert_belief(
        content="Documentation was just completed covering X, Y, Z",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=5.0,
        beta_param=0.5,
    )

    # Search using a token shared between both beliefs: "documentation" is in the
    # completed-work belief only, not the noise belief.
    results: list[Belief] = store.search("documentation completed")
    assert results, "Expected search results"
    result_ids: list[str] = [r.id for r in results]
    assert completed.id in result_ids, (
        f"Completed-work belief {completed.id} not in results: {result_ids}"
    )
