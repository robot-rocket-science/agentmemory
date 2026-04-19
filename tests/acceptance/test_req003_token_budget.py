"""REQ-003: Token budget packing.

The retrieval pipeline must respect a token budget when packing beliefs.
Locked beliefs are included even when the budget is tight.
"""

from __future__ import annotations

from agentmemory.compression import pack_beliefs
from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.retrieval import retrieve, RetrievalResult
from agentmemory.store import MemoryStore


def _make_beliefs(store: MemoryStore, count: int, locked: bool = False) -> list[Belief]:
    """Insert *count* distinct beliefs and return them."""
    beliefs: list[Belief] = []
    for i in range(count):
        b: Belief = store.insert_belief(
            content=f"Belief number {i}: this is filler content to consume tokens for testing purposes.",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
            locked=locked,
        )
        beliefs.append(b)
    return beliefs


def test_budget_500_respected(store: MemoryStore) -> None:
    """Create 20+ beliefs, retrieve with budget=500. Total tokens in result <= 500."""
    _make_beliefs(store, 25)
    packed: list[Belief]
    total_tokens: int
    packed, total_tokens = pack_beliefs(
        store.search("belief filler content", top_k=50),
        budget_tokens=500,
    )
    assert total_tokens <= 500, f"Total tokens {total_tokens} exceeds budget 500"
    assert len(packed) > 0, "Expected at least one belief in result"


def test_larger_budget_returns_more(store: MemoryStore) -> None:
    """Budget=2000 should return more beliefs than budget=500."""
    _make_beliefs(store, 25)
    all_candidates: list[Belief] = store.search("belief filler content", top_k=50)

    packed_small: list[Belief]
    tokens_small: int
    packed_small, tokens_small = pack_beliefs(all_candidates, budget_tokens=500)

    packed_large: list[Belief]
    tokens_large: int
    packed_large, tokens_large = pack_beliefs(all_candidates, budget_tokens=2000)

    assert tokens_small <= 500
    assert tokens_large <= 2000
    assert len(packed_large) > len(packed_small), (
        f"budget=2000 returned {len(packed_large)} beliefs, "
        f"budget=500 returned {len(packed_small)}; expected more with larger budget"
    )


def test_locked_beliefs_included_under_tight_budget(store: MemoryStore) -> None:
    """Locked beliefs should appear in retrieval results even with a tight budget."""
    # Insert a locked belief with distinctive content
    locked_belief: Belief = store.insert_belief(
        content="Always use uv for Python package management",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        locked=True,
    )
    # Fill with unlocked beliefs to compete for budget
    _make_beliefs(store, 20, locked=False)

    result: RetrievalResult = retrieve(
        store,
        query="uv Python package management",
        budget=200,
        include_locked=True,
    )

    packed_ids: set[str] = {b.id for b in result.beliefs}
    assert locked_belief.id in packed_ids, (
        "Locked belief was not included in retrieval despite include_locked=True"
    )
    assert result.total_tokens <= 200, (
        f"Total tokens {result.total_tokens} exceeds budget 200"
    )


def test_retrieve_pipeline_respects_budget(store: MemoryStore) -> None:
    """End-to-end: retrieve() total_tokens <= budget."""
    _make_beliefs(store, 25)
    result: RetrievalResult = retrieve(
        store,
        query="belief filler content tokens testing",
        budget=500,
    )
    assert result.total_tokens <= 500
    assert result.budget_remaining >= 0
    assert result.total_tokens + result.budget_remaining == 500
