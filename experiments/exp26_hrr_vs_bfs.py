"""
Experiment 26: Real HRR vs BFS Comparison

Unlike exp24 (which was bag-of-words cosine similarity, not HRR), this experiment
uses actual HRR binding on the real project-a typed graph:

  - Each node gets a random hypervector
  - Each edge is encoded as: convolve(node_A, edge_type_vec, node_B)
  - All edges are superposed into a global graph HRR vector S
  - Queries use successive convolution for multi-hop traversal
  - Results are compared against BFS ground truth from the database

Query types tested:
  1. Single-hop forward:  given A, find B where A -[edge]-> B
  2. Single-hop reverse:  given B, find A where A -[edge]-> B
  3. Two-hop:             given A, find C where A -[e1]-> B -[e2]-> C

Metrics: precision@k and recall@k vs BFS ground truth.

Run with: uv run python experiments/exp26_hrr_vs_bfs.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import TypedDict

import numpy as np
import numpy.typing as npt


project-a_DB: Path = Path(
    "/home/user/projects/.gsd/workflows/spikes/"
    "260406-1-associative-memory-for-gsd-please-explor/"
    "sandbox/project-a.db"
)


class NodeInfo(TypedDict):
    content: str
    category: str


EdgeInfo = TypedDict("EdgeInfo", {"from": str, "to": str, "type": str})

# 8192-dim: capacity ~910 bindings, covers our 775 edges with headroom
DIM = 8192
SEP = "=" * 65


# ---------------------------------------------------------------------------
# Core HRR ops
# ---------------------------------------------------------------------------


def make_vector(rng: np.random.Generator) -> npt.NDArray[np.float64]:
    v: npt.NDArray[np.float64] = rng.standard_normal(DIM)
    v /= np.linalg.norm(v)
    return v


def convolve(
    a: npt.NDArray[np.float64], b: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    result: npt.NDArray[np.float64] = np.real(
        np.fft.irfft(np.fft.rfft(a) * np.fft.rfft(b), n=DIM)
    )
    return result


def correlate(
    a: npt.NDArray[np.float64], b: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    result: npt.NDArray[np.float64] = np.real(
        np.fft.irfft(np.conj(np.fft.rfft(a)) * np.fft.rfft(b), n=DIM)
    )
    return result


def cos_sim(a: npt.NDArray[np.float64], b: npt.NDArray[np.float64]) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def top_k(
    query_vec: npt.NDArray[np.float64],
    node_vecs: dict[str, npt.NDArray[np.float64]],
    k: int,
) -> list[tuple[str, float]]:
    sims: list[tuple[str, float]] = [
        (nid, cos_sim(query_vec, v)) for nid, v in node_vecs.items()
    ]
    sims.sort(key=lambda x: x[1], reverse=True)
    return sims[:k]


# ---------------------------------------------------------------------------
# Load graph from SQLite
# ---------------------------------------------------------------------------


def load_graph(db_path: Path) -> tuple[dict[str, NodeInfo], list[EdgeInfo]]:
    db: sqlite3.Connection = sqlite3.connect(str(db_path))
    nodes: dict[str, NodeInfo] = {}
    for row in db.execute(
        "SELECT id, content, category FROM mem_nodes WHERE superseded_by IS NULL"
    ):
        nodes[str(row[0])] = NodeInfo(content=str(row[1]), category=str(row[2]))

    edges: list[EdgeInfo] = []
    for row in db.execute("SELECT from_id, to_id, edge_type FROM mem_edges"):
        # Only include edges where both endpoints are in nodes
        if str(row[0]) in nodes and str(row[1]) in nodes:
            edges.append(
                EdgeInfo(
                    **{"from": str(row[0]), "to": str(row[1]), "type": str(row[2])}
                )
            )

    db.close()
    return nodes, edges


# ---------------------------------------------------------------------------
# BFS ground truth
# ---------------------------------------------------------------------------


def bfs_one_hop(edges: list[EdgeInfo], source: str, edge_type: str) -> set[str]:
    return {e["to"] for e in edges if e["from"] == source and e["type"] == edge_type}


def bfs_one_hop_reverse(edges: list[EdgeInfo], target: str, edge_type: str) -> set[str]:
    return {e["from"] for e in edges if e["to"] == target and e["type"] == edge_type}


def bfs_two_hop(edges: list[EdgeInfo], source: str, e1: str, e2: str) -> set[str]:
    mid = bfs_one_hop(edges, source, e1)
    result: set[str] = set()
    for m in mid:
        result |= bfs_one_hop(edges, m, e2)
    result.discard(source)
    return result


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def precision_recall_at_k(
    retrieved: list[str], relevant: set[str], k: int
) -> tuple[float, float]:
    if not relevant:
        return 0.0, 0.0
    retrieved_k = retrieved[:k]
    hits = sum(1 for r in retrieved_k if r in relevant)
    precision = hits / k
    recall = hits / len(relevant)
    return precision, recall


# ---------------------------------------------------------------------------
# Encode graph as HRR
# ---------------------------------------------------------------------------


def build_hrr_graph(
    nodes: dict[str, NodeInfo],
    edges: list[EdgeInfo],
    rng: np.random.Generator,
) -> tuple[
    dict[str, npt.NDArray[np.float64]],
    dict[str, npt.NDArray[np.float64]],
    npt.NDArray[np.float64],
]:
    """
    Assign random vectors to nodes and edge types.
    Encode each edge as convolve(node_A, edge_type, node_B).
    Superpose all edge vectors into a global graph HRR S.

    Returns: node_vecs, edge_type_vecs, S
    """
    # Assign random vectors to every node
    node_vecs: dict[str, npt.NDArray[np.float64]] = {
        nid: make_vector(rng) for nid in nodes
    }

    # Assign random vectors to each unique edge type
    edge_types: list[str] = list({e["type"] for e in edges})
    edge_type_vecs: dict[str, npt.NDArray[np.float64]] = {
        et: make_vector(rng) for et in edge_types
    }

    # Encode each edge as a bound triple and superpose
    graph_s: npt.NDArray[np.float64] = np.zeros(DIM)
    for e in edges:
        # Triple binding: from_node * edge_type * to_node
        bound: npt.NDArray[np.float64] = convolve(
            convolve(node_vecs[e["from"]], edge_type_vecs[e["type"]]),
            node_vecs[e["to"]],
        )
        graph_s += bound

    # Normalize to unit length for stable cosine similarity
    s_norm = float(np.linalg.norm(graph_s))
    if s_norm > 0:
        graph_s /= s_norm

    return node_vecs, edge_type_vecs, graph_s


# ---------------------------------------------------------------------------
# HRR query functions
# ---------------------------------------------------------------------------


def hrr_one_hop_forward(
    source: str,
    edge_type: str,
    node_vecs: dict[str, npt.NDArray[np.float64]],
    edge_type_vecs: dict[str, npt.NDArray[np.float64]],
    graph_s: npt.NDArray[np.float64],
    k: int,
) -> list[tuple[str, float]]:
    """
    Query: source -[edge_type]-> ?
    Encode query as convolve(node_source, edge_type_vec),
    then correlate against S, find nearest neighbors.

    Unbinding triple (A * E * B):
      Given A and E, recover B:
      correlate(A, correlate(E, S)) or correlate(convolve(A, E), S)
    """
    q: npt.NDArray[np.float64] = convolve(node_vecs[source], edge_type_vecs[edge_type])
    recovered: npt.NDArray[np.float64] = correlate(q, graph_s)
    return top_k(recovered, node_vecs, k)


def hrr_one_hop_reverse(
    target: str,
    edge_type: str,
    node_vecs: dict[str, npt.NDArray[np.float64]],
    edge_type_vecs: dict[str, npt.NDArray[np.float64]],
    graph_s: npt.NDArray[np.float64],
    k: int,
) -> list[tuple[str, float]]:
    """
    Query: ? -[edge_type]-> target
    For triple (A * E * B), to recover A given E and B:
    correlate(convolve(edge_type_vec, node_target), S)
    """
    q: npt.NDArray[np.float64] = convolve(edge_type_vecs[edge_type], node_vecs[target])
    recovered: npt.NDArray[np.float64] = correlate(q, graph_s)
    return top_k(recovered, node_vecs, k)


def hrr_two_hop(
    source: str,
    e1: str,
    e2: str,
    node_vecs: dict[str, npt.NDArray[np.float64]],
    edge_type_vecs: dict[str, npt.NDArray[np.float64]],
    graph_s: npt.NDArray[np.float64],
    k: int,
) -> list[tuple[str, float]]:
    """
    Query: source -[e1]-> ? -[e2]-> ?
    Two-hop: compose query as convolve(node_source, e1_vec, e2_vec)
    then correlate against S^2 (self-convolution of S approximates 2-hop reachability).

    S^2 = convolve(S, S) encodes all 2-hop paths: if A->B->C are in S,
    then (A*E1*B) * (B*E2*C) = A * E1 * (B*B) * E2 * C
    Since B*B ≈ delta (autocorrelation peak), this ≈ A * E1 * E2 * C.
    """
    s2: npt.NDArray[np.float64] = convolve(graph_s, graph_s)
    s2_norm = float(np.linalg.norm(s2))
    if s2_norm > 0:
        s2 /= s2_norm

    q: npt.NDArray[np.float64] = convolve(
        convolve(node_vecs[source], edge_type_vecs[e1]), edge_type_vecs[e2]
    )
    recovered: npt.NDArray[np.float64] = correlate(q, s2)
    return top_k(recovered, node_vecs, k)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _avg_metric(records: list[dict[str, float]], key: str) -> float:
    return sum(r[key] for r in records) / len(records)


def main() -> None:
    rng: np.random.Generator = np.random.default_rng(42)

    print(SEP)
    print(f"Experiment 26: Real HRR vs BFS  (n={DIM})")
    print(SEP)

    # Load graph
    nodes: dict[str, NodeInfo]
    edges: list[EdgeInfo]
    nodes, edges = load_graph(project-a_DB)
    print(f"\nGraph: {len(nodes)} nodes, {len(edges)} edges", file=sys.stderr)
    edge_type_counts: defaultdict[str, int] = defaultdict(int)
    for e in edges:
        edge_type_counts[e["type"]] += 1
    for et, n in sorted(edge_type_counts.items(), key=lambda x: -x[1]):
        print(f"  {et}: {n} edges", file=sys.stderr)

    # Build HRR
    print("\nBuilding HRR graph encoding...", file=sys.stderr)
    node_vecs: dict[str, npt.NDArray[np.float64]]
    edge_type_vecs: dict[str, npt.NDArray[np.float64]]
    graph_s: npt.NDArray[np.float64]
    node_vecs, edge_type_vecs, graph_s = build_hrr_graph(nodes, edges, rng)
    print(
        f"  Graph superposition built. Capacity headroom: {DIM // 9} max bindings, {len(edges)} used",
        file=sys.stderr,
    )

    # Build outgoing-edge index for selecting good test cases
    out_edges: dict[str, dict[str, set[str]]] = {}
    for e in edges:
        out_edges.setdefault(e["from"], {}).setdefault(e["type"], set()).add(e["to"])

    results: dict[str, list[dict[str, float]]] = {
        "single_hop_forward": [],
        "single_hop_reverse": [],
        "two_hop": [],
    }

    # -----------------------------------------------------------------------
    # Test 1: Single-hop forward  A -[CITES]-> ?
    # -----------------------------------------------------------------------
    print(f"\n{SEP}")
    print("TEST 1: Single-Hop Forward  A -[CITES]-> ?")
    print(SEP)
    print(
        f"\n  {'Source':>8}  {'BFS hits':>9}  {'P@5':>6}  {'R@5':>6}  {'P@10':>6}  {'R@10':>6}  HRR top-3"
    )

    # Pick sources with at least 1 and at most 6 CITES targets (manageable ground truth)
    test_sources_cites: list[str] = [
        nid for nid in out_edges if 1 <= len(out_edges[nid].get("CITES", set())) <= 6
    ][:12]

    for source in test_sources_cites:
        gt: set[str] = bfs_one_hop(edges, source, "CITES")
        hrr_results: list[tuple[str, float]] = hrr_one_hop_forward(
            source, "CITES", node_vecs, edge_type_vecs, graph_s, k=10
        )
        hrr_ids: list[str] = [r[0] for r in hrr_results]

        p5, r5 = precision_recall_at_k(hrr_ids, gt, 5)
        p10, r10 = precision_recall_at_k(hrr_ids, gt, 10)
        top3: str = ", ".join(
            f"{r[0]}({'Y' if r[0] in gt else 'n'})" for r in hrr_results[:3]
        )

        print(
            f"  {source:>8}  {len(gt):>9}  {p5:>6.2f}  {r5:>6.2f}  {p10:>6.2f}  {r10:>6.2f}  {top3}"
        )
        results["single_hop_forward"].append(
            {"p5": p5, "r5": r5, "p10": p10, "r10": r10}
        )

    fwd: list[dict[str, float]] = results["single_hop_forward"]
    print(
        f"\n  Mean:  P@5={_avg_metric(fwd, 'p5'):.3f}  R@5={_avg_metric(fwd, 'r5'):.3f}  P@10={_avg_metric(fwd, 'p10'):.3f}  R@10={_avg_metric(fwd, 'r10'):.3f}"
    )

    # -----------------------------------------------------------------------
    # Test 2: Single-hop reverse  ? -[CITES]-> B
    # -----------------------------------------------------------------------
    print(f"\n{SEP}")
    print("TEST 2: Single-Hop Reverse  ? -[CITES]-> B")
    print(SEP)
    print(
        f"\n  {'Target':>8}  {'BFS hits':>9}  {'P@5':>6}  {'R@5':>6}  {'P@10':>6}  {'R@10':>6}  HRR top-3"
    )

    # Pick targets that have 1-5 incoming CITES edges
    in_edges_map: dict[str, dict[str, set[str]]] = {}
    for e in edges:
        in_edges_map.setdefault(e["to"], {}).setdefault(e["type"], set()).add(e["from"])

    test_targets_cites: list[str] = [
        nid
        for nid in in_edges_map
        if 1 <= len(in_edges_map[nid].get("CITES", set())) <= 5
    ][:12]

    for target in test_targets_cites:
        gt = bfs_one_hop_reverse(edges, target, "CITES")
        hrr_results = hrr_one_hop_reverse(
            target, "CITES", node_vecs, edge_type_vecs, graph_s, k=10
        )
        hrr_ids = [r[0] for r in hrr_results]

        p5, r5 = precision_recall_at_k(hrr_ids, gt, 5)
        p10, r10 = precision_recall_at_k(hrr_ids, gt, 10)
        top3 = ", ".join(
            f"{r[0]}({'Y' if r[0] in gt else 'n'})" for r in hrr_results[:3]
        )

        print(
            f"  {target:>8}  {len(gt):>9}  {p5:>6.2f}  {r5:>6.2f}  {p10:>6.2f}  {r10:>6.2f}  {top3}"
        )
        results["single_hop_reverse"].append(
            {"p5": p5, "r5": r5, "p10": p10, "r10": r10}
        )

    rev: list[dict[str, float]] = results["single_hop_reverse"]
    print(
        f"\n  Mean:  P@5={_avg_metric(rev, 'p5'):.3f}  R@5={_avg_metric(rev, 'r5'):.3f}  P@10={_avg_metric(rev, 'p10'):.3f}  R@10={_avg_metric(rev, 'r10'):.3f}"
    )

    # -----------------------------------------------------------------------
    # Test 3: Two-hop  A -[CITES]-> B -[DECIDED_IN]-> M
    # -----------------------------------------------------------------------
    print(f"\n{SEP}")
    print("TEST 3: Two-Hop  A -[CITES]-> B -[DECIDED_IN]-> M")
    print(SEP)
    print(
        f"\n  {'Source':>8}  {'BFS hits':>9}  {'P@5':>6}  {'R@5':>6}  {'P@10':>6}  {'R@10':>6}  HRR top-3"
    )

    # Sources that have CITES edges leading to nodes with DECIDED_IN edges
    test_sources_2hop: list[str] = []
    for nid in out_edges:
        gt = bfs_two_hop(edges, nid, "CITES", "DECIDED_IN")
        if 1 <= len(gt) <= 8:
            test_sources_2hop.append(nid)
    test_sources_2hop = test_sources_2hop[:12]

    for source in test_sources_2hop:
        gt = bfs_two_hop(edges, source, "CITES", "DECIDED_IN")
        hrr_results = hrr_two_hop(
            source, "CITES", "DECIDED_IN", node_vecs, edge_type_vecs, graph_s, k=10
        )
        hrr_ids = [r[0] for r in hrr_results]

        p5, r5 = precision_recall_at_k(hrr_ids, gt, 5)
        p10, r10 = precision_recall_at_k(hrr_ids, gt, 10)
        top3 = ", ".join(
            f"{r[0]}({'Y' if r[0] in gt else 'n'})" for r in hrr_results[:3]
        )

        print(
            f"  {source:>8}  {len(gt):>9}  {p5:>6.2f}  {r5:>6.2f}  {p10:>6.2f}  {r10:>6.2f}  {top3}"
        )
        results["two_hop"].append({"p5": p5, "r5": r5, "p10": p10, "r10": r10})

    two: list[dict[str, float]] = results["two_hop"]
    print(
        f"\n  Mean:  P@5={_avg_metric(two, 'p5'):.3f}  R@5={_avg_metric(two, 'r5'):.3f}  P@10={_avg_metric(two, 'p10'):.3f}  R@10={_avg_metric(two, 'r10'):.3f}"
    )

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print(f"\n{SEP}")
    print("SUMMARY")
    print(SEP)

    def mean_results(key: str) -> dict[str, float]:
        r: list[dict[str, float]] = results[key]
        return {k: sum(x[k] for x in r) / len(r) for k in ["p5", "r5", "p10", "r10"]}

    for label, key in [
        ("Single-hop forward (CITES)", "single_hop_forward"),
        ("Single-hop reverse (CITES)", "single_hop_reverse"),
        ("Two-hop (CITES->DECIDED_IN)", "two_hop"),
    ]:
        m: dict[str, float] = mean_results(key)
        print(f"\n  {label}:")
        print(
            f"    P@5={m['p5']:.3f}  R@5={m['r5']:.3f}  P@10={m['p10']:.3f}  R@10={m['r10']:.3f}"
        )

    print(f"""
  Notes:
  - Ground truth: BFS on SQLite graph (exact)
  - HRR: bound triples convolve(node_A, edge_type, node_B), superposed into S
  - Two-hop: uses S^2 = convolve(S, S); query = convolve(node_A, e1_vec, e2_vec)
  - n={DIM}, {len(edges)} edges superposed, capacity headroom ≈ {DIM // 9 - len(edges)} bindings
  - Unlike exp24, this uses actual binding/unbinding -- no bag-of-words cosine similarity
""")

    # Save results
    out: Path = Path(__file__).parent / "exp26_results.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Results saved to {out.name}")


if __name__ == "__main__":
    main()
