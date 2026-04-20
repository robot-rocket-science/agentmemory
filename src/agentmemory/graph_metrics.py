"""Graph-theoretic metrics for the belief network.

Computes structural importance (degree centrality, PageRank) from the
belief edge graph. These metrics feed into retrieval scoring as a
"structural boost" for hub beliefs.
"""

from __future__ import annotations

from typing import Final

from agentmemory.store import MemoryStore

_DEFAULT_DAMPING: Final[float] = 0.85
_DEFAULT_ITERATIONS: Final[int] = 50
_DEFAULT_TOLERANCE: Final[float] = 1e-6


def compute_degree_centrality(store: MemoryStore) -> dict[str, int]:
    """Compute degree (edge count) for all beliefs with edges.

    Returns dict of belief_id -> degree. Beliefs with no edges are
    not included (implicitly degree 0).
    """
    rows = store.query(
        """SELECT belief_id, COUNT(*) as degree FROM (
            SELECT from_id as belief_id FROM edges WHERE pruned_at IS NULL
            UNION ALL
            SELECT to_id as belief_id FROM edges WHERE pruned_at IS NULL
        ) GROUP BY belief_id"""
    )
    return {str(r[0]): int(r[1]) for r in rows}


def compute_pagerank(
    store: MemoryStore,
    damping: float = _DEFAULT_DAMPING,
    iterations: int = _DEFAULT_ITERATIONS,
    tolerance: float = _DEFAULT_TOLERANCE,
) -> dict[str, float]:
    """Compute PageRank over the belief edge graph.

    Uses the iterative power method. Directed edges transfer rank
    in the forward direction (from_id -> to_id).

    Returns dict of belief_id -> pagerank score (sums to ~1.0).
    Only includes beliefs that participate in at least one edge.
    """
    # Build adjacency: out_edges[node] = list of target nodes
    edge_rows = store.query("SELECT from_id, to_id FROM edges WHERE pruned_at IS NULL")

    out_edges: dict[str, list[str]] = {}
    all_nodes: set[str] = set()
    for row in edge_rows:
        src: str = str(row[0])
        dst: str = str(row[1])
        all_nodes.add(src)
        all_nodes.add(dst)
        out_edges.setdefault(src, []).append(dst)

    n: int = len(all_nodes)
    if n == 0:
        return {}

    # Initialize uniform
    rank: dict[str, float] = {node: 1.0 / n for node in all_nodes}
    teleport: float = (1.0 - damping) / n

    # Identify dangling nodes (no outgoing edges) once
    dangling_nodes: list[str] = [n for n in all_nodes if n not in out_edges]

    for _ in range(iterations):
        # Batch dangling node rank: sum their rank, distribute uniformly
        dangling_sum: float = sum(rank[dn] for dn in dangling_nodes)
        dangling_share: float = damping * dangling_sum / n

        new_rank: dict[str, float] = {
            node: teleport + dangling_share for node in all_nodes
        }

        # Distribute rank along edges
        for node, targets in out_edges.items():
            share: float = damping * rank[node] / len(targets)
            for t in targets:
                new_rank[t] += share

        # Check convergence
        diff: float = sum(abs(new_rank[node] - rank[node]) for node in all_nodes)
        rank = new_rank
        if diff < tolerance:
            break

    return rank


def compute_structural_importance(
    store: MemoryStore,
    damping: float = _DEFAULT_DAMPING,
) -> dict[str, float]:
    """Combined structural score: 0.7 * normalized_pagerank + 0.3 * normalized_degree.

    Returns dict of belief_id -> importance in [0.0, 1.0] range.
    """
    pr: dict[str, float] = compute_pagerank(store, damping=damping)
    degrees: dict[str, int] = compute_degree_centrality(store)

    if not pr:
        return {}

    # Normalize PageRank to [0, 1]
    max_pr: float = max(pr.values()) if pr else 1.0
    if max_pr == 0.0:
        max_pr = 1.0

    # Normalize degree to [0, 1]
    max_deg: float = float(max(degrees.values())) if degrees else 1.0
    if max_deg == 0.0:
        max_deg = 1.0

    all_ids: set[str] = set(pr.keys()) | set(degrees.keys())
    result: dict[str, float] = {}
    for bid in all_ids:
        norm_pr: float = pr.get(bid, 0.0) / max_pr
        norm_deg: float = degrees.get(bid, 0) / max_deg
        result[bid] = 0.7 * norm_pr + 0.3 * norm_deg

    return result


def structural_boost(
    belief_id: str,
    importance_cache: dict[str, float],
) -> float:
    """Boost factor from graph structure for use in scoring.

    Returns a multiplier in [1.0, 2.0].
    Top 5% of beliefs get up to 2.0x boost.
    Beliefs with no edges get 1.0x (no penalty).
    """
    importance: float = importance_cache.get(belief_id, 0.0)
    if importance <= 0.0:
        return 1.0
    # Scale: importance 0->1 maps to boost 1.0->2.0
    return 1.0 + importance
