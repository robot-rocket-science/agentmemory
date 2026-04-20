"""CS-014: Research-Execution Divergence.

Pass criterion: Beliefs from a research phase are retrievable during execution,
and IMPLEMENTS edges link execution artifacts to research requirements.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.store import MemoryStore


def test_cs014_research_finding_retrievable(store: MemoryStore) -> None:
    """A locked research finding is surfaced when searching for related
    configuration terms in a later execution context."""
    research: Belief = store.insert_belief(
        content="Maximize N requires --delta-lo 0.10 flag.",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        locked=True,
        alpha=9.0,
        beta_param=0.5,
    )

    results: list[Belief] = store.search("delta parameter configuration")
    result_ids: list[str] = [r.id for r in results]
    assert research.id in result_ids, (
        "Research finding about --delta-lo must be retrievable during execution. "
        f"Got IDs: {result_ids}"
    )


def test_cs014_implements_edge_links_phases(store: MemoryStore) -> None:
    """An IMPLEMENTS edge from an execution file to a research requirement
    is queryable via graph_edges."""
    store.insert_graph_edge(
        from_id="file:run_backtest.py",
        to_id="req:RESEARCH-001",
        edge_type="IMPLEMENTS",
    )

    conn = store._conn  # pyright: ignore[reportPrivateUsage]
    rows = conn.execute(
        "SELECT from_id, to_id FROM graph_edges WHERE edge_type = 'IMPLEMENTS'"
    ).fetchall()
    edges: list[tuple[str, str]] = [(r["from_id"], r["to_id"]) for r in rows]

    assert ("file:run_backtest.py", "req:RESEARCH-001") in edges, (
        f"IMPLEMENTS edge not found. Edges: {edges}"
    )
