"""CS-028: Locked Correction Retrieved, Injected, and Ignored.

Pass criterion: A locked correction about using subagents (not direct API)
is retrievable, top-ranked, and flagged when the prohibited action is queried.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_CORRECTION,
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_CORRECTED,
    Belief,
)
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore


def test_cs028_locked_correction_top_ranked(store: MemoryStore) -> None:
    """A locked correction about API usage must rank in top 5 for related queries."""
    store.insert_belief(
        content=(
            "LLM classification uses Claude Code subagents via Agent tool, "
            "not direct Anthropic API calls. No ANTHROPIC_API_KEY needed."
        ),
        belief_type=BELIEF_CORRECTION,
        source_type=BSRC_USER_CORRECTED,
        locked=True,
        alpha=10.0,
        beta_param=0.5,
    )

    # Add noise beliefs
    for i in range(20):
        store.insert_belief(
            content=f"Implementation detail about module configuration item {i}",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )

    result: RetrievalResult = retrieve(store, "API key Anthropic classification")
    top_5: list[Belief] = result.beliefs[:5]
    assert any(
        "subagent" in b.content.lower() or "Agent tool" in b.content for b in top_5
    ), "Locked correction about subagents must appear in top 5 results"


def test_cs028_locked_belief_resists_ignored_feedback(store: MemoryStore) -> None:
    """Locked beliefs should resist confidence drops from 'ignored' feedback.
    This is by design: locked = non-negotiable."""
    belief: Belief = store.insert_belief(
        content="Use subagents not direct API calls for LLM classification",
        belief_type=BELIEF_CORRECTION,
        source_type=BSRC_USER_CORRECTED,
        locked=True,
        alpha=10.0,
        beta_param=0.5,
    )

    # Simulate 5 violations (belief retrieved but ignored)
    for _ in range(5):
        store.update_confidence(belief.id, "ignored")

    updated: Belief | None = store.get_belief(belief.id)
    assert updated is not None
    # Locked beliefs resist confidence drops -- confidence should stay high
    assert updated.confidence > 0.9, (
        f"Locked belief should resist ignored feedback, confidence={updated.confidence}"
    )
