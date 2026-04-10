"""
Experiment 26: Real HRR vs BFS Comparison

Unlike exp24 (which was bag-of-words cosine similarity, not HRR), this experiment
uses actual HRR binding on the real alpha-seek typed graph:

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

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np


ALPHA_SEEK_DB = Path("/Users/thelorax/projects/.gsd/workflows/spikes/"
                     "260406-1-associative-memory-for-gsd-please-explor/"
                     "sandbox/alpha-seek.db")

# 8192-dim: capacity ~910 bindings, covers our 775 edges with headroom
DIM = 8192
SEP = "=" * 65


# ---------------------------------------------------------------------------
# Core HRR ops
# ---------------------------------------------------------------------------

def make_vector(rng: np.random.Generator) -> np.ndarray:
    v = rng.standard_normal(DIM)
    v /= np.linalg.norm(v)
    return v


def convolve(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.real(np.fft.irfft(np.fft.rfft(a) * np.fft.rfft(b), n=DIM))


def correlate(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.real(np.fft.irfft(np.conj(np.fft.rfft(a)) * np.fft.rfft(b), n=DIM))


def cos_sim(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def top_k(query_vec: np.ndarray, node_vecs: dict[str, np.ndarray], k: int) -> list[tuple[str, float]]:
    """Return top-k (node_id, similarity) pairs."""
    sims = [(nid, cos_sim(query_vec, v)) for nid, v in node_vecs.items()]
    sims.sort(key=lambda x: x[1], reverse=True)
    return sims[:k]


# ---------------------------------------------------------------------------
# Load graph from SQLite
# ---------------------------------------------------------------------------

def load_graph(db_path: Path) -> tuple[dict, list]:
    db = sqlite3.connect(str(db_path))
    nodes = {}
    for row in db.execute(
        "SELECT id, content, category FROM mem_nodes WHERE superseded_by IS NULL"
    ):
        nodes[row[0]] = {"content": row[1], "category": row[2]}

    edges = []
    for row in db.execute(
        "SELECT from_id, to_id, edge_type FROM mem_edges"
    ):
        # Only include edges where both endpoints are in nodes
        if row[0] in nodes and row[1] in nodes:
            edges.append({"from": row[0], "to": row[1], "type": row[2]})

    db.close()
    return nodes, edges


# ---------------------------------------------------------------------------
# BFS ground truth
# ---------------------------------------------------------------------------

def bfs_one_hop(edges: list, source: str, edge_type: str) -> set[str]:
    return {e["to"] for e in edges if e["from"] == source and e["type"] == edge_type}


def bfs_one_hop_reverse(edges: list, target: str, edge_type: str) -> set[str]:
    return {e["from"] for e in edges if e["to"] == target and e["type"] == edge_type}


def bfs_two_hop(edges: list, source: str, e1: str, e2: str) -> set[str]:
    mid = bfs_one_hop(edges, source, e1)
    result = set()
    for m in mid:
        result |= bfs_one_hop(edges, m, e2)
    result.discard(source)
    return result


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def precision_recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> tuple[float, float]:
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
    nodes: dict,
    edges: list,
    rng: np.random.Generator
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], np.ndarray]:
    """
    Assign random vectors to nodes and edge types.
    Encode each edge as convolve(node_A, edge_type, node_B).
    Superpose all edge vectors into a global graph HRR S.

    Returns: node_vecs, edge_type_vecs, S
    """
    # Assign random vectors to every node
    node_vecs = {nid: make_vector(rng) for nid in nodes}

    # Assign random vectors to each unique edge type
    edge_types = list({e["type"] for e in edges})
    edge_type_vecs = {et: make_vector(rng) for et in edge_types}

    # Encode each edge as a bound triple and superpose
    S = np.zeros(DIM)
    for e in edges:
        # Triple binding: from_node * edge_type * to_node
        bound = convolve(convolve(node_vecs[e["from"]], edge_type_vecs[e["type"]]),
                         node_vecs[e["to"]])
        S += bound

    # Normalize S to unit length for stable cosine similarity
    s_norm = np.linalg.norm(S)
    if s_norm > 0:
        S /= s_norm

    return node_vecs, edge_type_vecs, S


# ---------------------------------------------------------------------------
# HRR query functions
# ---------------------------------------------------------------------------

def hrr_one_hop_forward(
    source: str,
    edge_type: str,
    node_vecs: dict[str, np.ndarray],
    edge_type_vecs: dict[str, np.ndarray],
    S: np.ndarray,
    k: int
) -> list[tuple[str, float]]:
    """
    Query: source -[edge_type]-> ?
    Encode query as convolve(node_source, edge_type_vec),
    then correlate against S, find nearest neighbors.

    Unbinding triple (A * E * B):
      Given A and E, recover B:
      correlate(A, correlate(E, S)) or correlate(convolve(A, E), S)
    """
    q = convolve(node_vecs[source], edge_type_vecs[edge_type])
    recovered = correlate(q, S)
    return top_k(recovered, node_vecs, k)


def hrr_one_hop_reverse(
    target: str,
    edge_type: str,
    node_vecs: dict[str, np.ndarray],
    edge_type_vecs: dict[str, np.ndarray],
    S: np.ndarray,
    k: int
) -> list[tuple[str, float]]:
    """
    Query: ? -[edge_type]-> target
    For triple (A * E * B), to recover A given E and B:
    correlate(convolve(edge_type_vec, node_target), S)
    """
    q = convolve(edge_type_vecs[edge_type], node_vecs[target])
    recovered = correlate(q, S)
    return top_k(recovered, node_vecs, k)


def hrr_two_hop(
    source: str,
    e1: str,
    e2: str,
    node_vecs: dict[str, np.ndarray],
    edge_type_vecs: dict[str, np.ndarray],
    S: np.ndarray,
    k: int
) -> list[tuple[str, float]]:
    """
    Query: source -[e1]-> ? -[e2]-> ?
    Two-hop: compose query as convolve(node_source, e1_vec, e2_vec)
    then correlate against S^2 (self-convolution of S approximates 2-hop reachability).

    S^2 = convolve(S, S) encodes all 2-hop paths: if A->B->C are in S,
    then (A*E1*B) * (B*E2*C) = A * E1 * (B*B) * E2 * C
    Since B*B ≈ delta (autocorrelation peak), this ≈ A * E1 * E2 * C.
    """
    S2 = convolve(S, S)
    s2_norm = np.linalg.norm(S2)
    if s2_norm > 0:
        S2 /= s2_norm

    q = convolve(convolve(node_vecs[source], edge_type_vecs[e1]), edge_type_vecs[e2])
    recovered = correlate(q, S2)
    return top_k(recovered, node_vecs, k)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    rng = np.random.default_rng(42)

    print(SEP)
    print(f"Experiment 26: Real HRR vs BFS  (n={DIM})")
    print(SEP)

    # Load graph
    nodes, edges = load_graph(ALPHA_SEEK_DB)
    print(f"\nGraph: {len(nodes)} nodes, {len(edges)} edges", file=sys.stderr)
    edge_type_counts = defaultdict(int)
    for e in edges:
        edge_type_counts[e["type"]] += 1
    for et, n in sorted(edge_type_counts.items(), key=lambda x: -x[1]):
        print(f"  {et}: {n} edges", file=sys.stderr)

    # Build HRR
    print(f"\nBuilding HRR graph encoding...", file=sys.stderr)
    node_vecs, edge_type_vecs, S = build_hrr_graph(nodes, edges, rng)
    print(f"  Graph superposition built. Capacity headroom: {DIM//9} max bindings, {len(edges)} used",
          file=sys.stderr)

    # Build outgoing-edge index for selecting good test cases
    out_edges = defaultdict(lambda: defaultdict(set))  # out_edges[from][type] = {to, ...}
    for e in edges:
        out_edges[e["from"]][e["type"]].add(e["to"])

    results = {"single_hop_forward": [], "single_hop_reverse": [], "two_hop": []}

    # -----------------------------------------------------------------------
    # Test 1: Single-hop forward  A -[CITES]-> ?
    # -----------------------------------------------------------------------
    print(f"\n{SEP}")
    print("TEST 1: Single-Hop Forward  A -[CITES]-> ?")
    print(SEP)
    print(f"\n  {'Source':>8}  {'BFS hits':>9}  {'P@5':>6}  {'R@5':>6}  {'P@10':>6}  {'R@10':>6}  HRR top-3")

    # Pick sources with at least 1 and at most 6 CITES targets (manageable ground truth)
    test_sources_cites = [
        nid for nid in out_edges
        if 1 <= len(out_edges[nid].get("CITES", set())) <= 6
    ][:12]

    for source in test_sources_cites:
        gt = bfs_one_hop(edges, source, "CITES")
        hrr_results = hrr_one_hop_forward(source, "CITES", node_vecs, edge_type_vecs, S, k=10)
        hrr_ids = [r[0] for r in hrr_results]

        p5, r5 = precision_recall_at_k(hrr_ids, gt, 5)
        p10, r10 = precision_recall_at_k(hrr_ids, gt, 10)
        top3 = ", ".join(f"{r[0]}({'Y' if r[0] in gt else 'n'})" for r in hrr_results[:3])

        print(f"  {source:>8}  {len(gt):>9}  {p5:>6.2f}  {r5:>6.2f}  {p10:>6.2f}  {r10:>6.2f}  {top3}")
        results["single_hop_forward"].append({"p5": p5, "r5": r5, "p10": p10, "r10": r10})

    avg = lambda key: sum(r[key] for r in results["single_hop_forward"]) / len(results["single_hop_forward"])
    print(f"\n  Mean:  P@5={avg('p5'):.3f}  R@5={avg('r5'):.3f}  P@10={avg('p10'):.3f}  R@10={avg('r10'):.3f}")

    # -----------------------------------------------------------------------
    # Test 2: Single-hop reverse  ? -[CITES]-> B
    # -----------------------------------------------------------------------
    print(f"\n{SEP}")
    print("TEST 2: Single-Hop Reverse  ? -[CITES]-> B")
    print(SEP)
    print(f"\n  {'Target':>8}  {'BFS hits':>9}  {'P@5':>6}  {'R@5':>6}  {'P@10':>6}  {'R@10':>6}  HRR top-3")

    # Pick targets that have 1-5 incoming CITES edges
    in_edges = defaultdict(lambda: defaultdict(set))
    for e in edges:
        in_edges[e["to"]][e["type"]].add(e["from"])

    test_targets_cites = [
        nid for nid in in_edges
        if 1 <= len(in_edges[nid].get("CITES", set())) <= 5
    ][:12]

    for target in test_targets_cites:
        gt = bfs_one_hop_reverse(edges, target, "CITES")
        hrr_results = hrr_one_hop_reverse(target, "CITES", node_vecs, edge_type_vecs, S, k=10)
        hrr_ids = [r[0] for r in hrr_results]

        p5, r5 = precision_recall_at_k(hrr_ids, gt, 5)
        p10, r10 = precision_recall_at_k(hrr_ids, gt, 10)
        top3 = ", ".join(f"{r[0]}({'Y' if r[0] in gt else 'n'})" for r in hrr_results[:3])

        print(f"  {target:>8}  {len(gt):>9}  {p5:>6.2f}  {r5:>6.2f}  {p10:>6.2f}  {r10:>6.2f}  {top3}")
        results["single_hop_reverse"].append({"p5": p5, "r5": r5, "p10": p10, "r10": r10})

    avg = lambda key: sum(r[key] for r in results["single_hop_reverse"]) / len(results["single_hop_reverse"])
    print(f"\n  Mean:  P@5={avg('p5'):.3f}  R@5={avg('r5'):.3f}  P@10={avg('p10'):.3f}  R@10={avg('r10'):.3f}")

    # -----------------------------------------------------------------------
    # Test 3: Two-hop  A -[CITES]-> B -[DECIDED_IN]-> M
    # -----------------------------------------------------------------------
    print(f"\n{SEP}")
    print("TEST 3: Two-Hop  A -[CITES]-> B -[DECIDED_IN]-> M")
    print(SEP)
    print(f"\n  {'Source':>8}  {'BFS hits':>9}  {'P@5':>6}  {'R@5':>6}  {'P@10':>6}  {'R@10':>6}  HRR top-3")

    # Sources that have CITES edges leading to nodes with DECIDED_IN edges
    test_sources_2hop = []
    for nid in out_edges:
        gt = bfs_two_hop(edges, nid, "CITES", "DECIDED_IN")
        if 1 <= len(gt) <= 8:
            test_sources_2hop.append(nid)
    test_sources_2hop = test_sources_2hop[:12]

    for source in test_sources_2hop:
        gt = bfs_two_hop(edges, source, "CITES", "DECIDED_IN")
        hrr_results = hrr_two_hop(source, "CITES", "DECIDED_IN", node_vecs, edge_type_vecs, S, k=10)
        hrr_ids = [r[0] for r in hrr_results]

        p5, r5 = precision_recall_at_k(hrr_ids, gt, 5)
        p10, r10 = precision_recall_at_k(hrr_ids, gt, 10)
        top3 = ", ".join(f"{r[0]}({'Y' if r[0] in gt else 'n'})" for r in hrr_results[:3])

        print(f"  {source:>8}  {len(gt):>9}  {p5:>6.2f}  {r5:>6.2f}  {p10:>6.2f}  {r10:>6.2f}  {top3}")
        results["two_hop"].append({"p5": p5, "r5": r5, "p10": p10, "r10": r10})

    avg = lambda key: sum(r[key] for r in results["two_hop"]) / len(results["two_hop"])
    print(f"\n  Mean:  P@5={avg('p5'):.3f}  R@5={avg('r5'):.3f}  P@10={avg('p10'):.3f}  R@10={avg('r10'):.3f}")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print(f"\n{SEP}")
    print("SUMMARY")
    print(SEP)

    def mean_results(key):
        r = results[key]
        return {k: sum(x[k] for x in r) / len(r) for k in ["p5", "r5", "p10", "r10"]}

    for label, key in [
        ("Single-hop forward (CITES)", "single_hop_forward"),
        ("Single-hop reverse (CITES)", "single_hop_reverse"),
        ("Two-hop (CITES->DECIDED_IN)", "two_hop"),
    ]:
        m = mean_results(key)
        print(f"\n  {label}:")
        print(f"    P@5={m['p5']:.3f}  R@5={m['r5']:.3f}  P@10={m['p10']:.3f}  R@10={m['r10']:.3f}")

    print(f"""
  Notes:
  - Ground truth: BFS on SQLite graph (exact)
  - HRR: bound triples convolve(node_A, edge_type, node_B), superposed into S
  - Two-hop: uses S^2 = convolve(S, S); query = convolve(node_A, e1_vec, e2_vec)
  - n={DIM}, {len(edges)} edges superposed, capacity headroom ≈ {DIM//9 - len(edges)} bindings
  - Unlike exp24, this uses actual binding/unbinding -- no bag-of-words cosine similarity
""")

    # Save results
    out = Path(__file__).parent / "exp26_results.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Results saved to {out.name}")


if __name__ == "__main__":
    main()
