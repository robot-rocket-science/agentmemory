"""CS-017: Configuration Drift from Implicit Defaults.

Pass criterion: CO_CHANGED edges surface coupled files, and beliefs about
configuration defaults are retrievable alongside the coupling data.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.store import MemoryStore


def test_cs017_cochanged_files_surfaced(store: MemoryStore) -> None:
    """CO_CHANGED edges between config.py and its dependents are queryable,
    and a belief about the default capital value is retrievable by search."""
    # Insert CO_CHANGED edges.
    store.insert_graph_edge(
        from_id="file:config.py",
        to_id="file:dispatch.py",
        edge_type="CO_CHANGED",
        weight=5.0,
    )
    store.insert_graph_edge(
        from_id="file:config.py",
        to_id="file:runner.py",
        edge_type="CO_CHANGED",
        weight=3.0,
    )

    # Insert a belief about the implicit default.
    capital_belief: Belief = store.insert_belief(
        content="Default capital is $5000 in config.py.",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
    )

    # Search for the belief.
    results: list[Belief] = store.search("capital configuration")
    result_ids: list[str] = [r.id for r in results]
    assert capital_belief.id in result_ids, (
        f"Belief about default capital must be retrievable. Got IDs: {result_ids}"
    )

    # Verify CO_CHANGED edges exist.
    conn = store._conn  # pyright: ignore[reportPrivateUsage]
    rows = conn.execute(
        "SELECT from_id, to_id, weight FROM graph_edges WHERE edge_type = 'CO_CHANGED'"
    ).fetchall()
    edges: dict[tuple[str, str], float] = {
        (r["from_id"], r["to_id"]): r["weight"] for r in rows
    }

    assert ("file:config.py", "file:dispatch.py") in edges, (
        f"Missing CO_CHANGED edge to dispatch.py. Edges: {list(edges)}"
    )
    assert ("file:config.py", "file:runner.py") in edges, (
        f"Missing CO_CHANGED edge to runner.py. Edges: {list(edges)}"
    )
    assert edges[("file:config.py", "file:dispatch.py")] == 5.0
    assert edges[("file:config.py", "file:runner.py")] == 3.0
