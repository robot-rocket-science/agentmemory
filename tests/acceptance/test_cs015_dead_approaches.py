"""CS-015: Dead Approaches Re-Proposed.

Pass criterion: Superseded beliefs are excluded from search results.
Only the latest version in a supersession chain should be returned.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_CORRECTED,
    Belief,
)
from agentmemory.store import MemoryStore


def test_cs015_superseded_excluded_from_search(store: MemoryStore) -> None:
    """Insert belief A (old approach) and belief B (replacement). Supersede A
    with B. Search for the old approach topic.

    A must NOT appear (valid_to is set). B should appear. This prevents the
    agent from re-proposing dead approaches.
    """
    belief_a: Belief = store.insert_belief(
        content="Use price filters for signal quality improvement.",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=3.0,
        beta_param=1.0,
    )

    belief_b: Belief = store.insert_belief(
        content="No-filter approach works better for price signal quality (D183).",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_CORRECTED,
        alpha=6.0,
        beta_param=0.5,
    )

    store.supersede_belief(
        old_id=belief_a.id, new_id=belief_b.id, reason="D183 results"
    )

    # Search for the topic. Superseded belief A must be excluded.
    results: list[Belief] = store.search("price filter signal quality")
    result_ids: list[str] = [r.id for r in results]

    assert belief_a.id not in result_ids, (
        f"Superseded belief A ({belief_a.id}) must NOT appear in search results. "
        f"Got IDs: {result_ids}"
    )
    assert belief_b.id in result_ids, (
        f"Replacement belief B ({belief_b.id}) must appear in search results. "
        f"Got IDs: {result_ids}"
    )


def test_cs015_supersession_chain(store: MemoryStore) -> None:
    """Insert A, B, C where A is superseded by B, B is superseded by C.

    Search should only return C (the final version in the chain).
    """
    belief_a: Belief = store.insert_belief(
        content="Use moving average crossover for trend detection.",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=2.0,
        beta_param=1.0,
    )

    belief_b: Belief = store.insert_belief(
        content="Use exponential moving average crossover for trend detection.",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=4.0,
        beta_param=0.5,
    )

    belief_c: Belief = store.insert_belief(
        content="Use adaptive moving average crossover for trend detection.",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_CORRECTED,
        alpha=7.0,
        beta_param=0.5,
    )

    # Chain: A -> B -> C
    store.supersede_belief(old_id=belief_a.id, new_id=belief_b.id, reason="EMA better")
    store.supersede_belief(
        old_id=belief_b.id, new_id=belief_c.id, reason="Adaptive best"
    )

    # Only C should survive in search results.
    results: list[Belief] = store.search("moving average crossover trend detection")
    result_ids: list[str] = [r.id for r in results]

    assert belief_a.id not in result_ids, (
        f"Belief A ({belief_a.id}) is superseded and must not appear in results."
    )
    assert belief_b.id not in result_ids, (
        f"Belief B ({belief_b.id}) is superseded and must not appear in results."
    )
    assert belief_c.id in result_ids, (
        f"Belief C ({belief_c.id}) is the final version and must appear in results. "
        f"Got IDs: {result_ids}"
    )
