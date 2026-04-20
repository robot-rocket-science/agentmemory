"""Exp 96: Hierarchical intention clustering.

Problem: k=8 produces one 77% mega-cluster (12,765 agent-inferred factual).
Tests two approaches:
  H3: Two-level clustering (type/source first, then k-means within) -> no cluster >20%.
  H4: k=40 flat clustering -> better Gini + MRR on vocab-gap pairs.

Usage:
    uv run python experiments/exp96_hierarchical_clustering.py
"""

from __future__ import annotations

import math
import random
import sqlite3
from collections import Counter
from pathlib import Path

import numpy as np
import numpy.typing as npt

from agentmemory.intention import build_features, cluster_beliefs


def word_set(text: str) -> set[str]:
    return {w.lower() for w in text.split() if len(w) >= 3}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def two_level_cluster(
    conn: sqlite3.Connection,
    ids: list[str],
    features: npt.NDArray[np.float64],
    k_per_group: int = 8,
) -> list[int]:
    """Two-level: group by type+source, then k-means within each group."""
    conn.row_factory = sqlite3.Row
    rows: list[sqlite3.Row] = conn.execute(
        "SELECT id, belief_type, source_type FROM beliefs WHERE id IN ({})".format(
            ",".join("?" * len(ids))
        ),
        ids,
    ).fetchall()

    type_source: dict[str, str] = {}
    for r in rows:
        type_source[str(r["id"])] = f"{r['belief_type']}_{r['source_type']}"

    # Group IDs by type+source
    groups: dict[str, list[int]] = {}
    for i, bid in enumerate(ids):
        key: str = type_source.get(bid, "unknown")
        if key not in groups:
            groups[key] = []
        groups[key].append(i)

    assignments: list[int] = [0] * len(ids)
    cluster_offset: int = 0

    for group_key in sorted(groups.keys()):
        indices: list[int] = groups[group_key]
        if len(indices) <= k_per_group:
            # Small group: each belief gets its own cluster
            for j, idx in enumerate(indices):
                assignments[idx] = cluster_offset + j
            cluster_offset += len(indices)
        else:
            # Large group: k-means within
            group_ids: list[str] = [ids[i] for i in indices]
            group_features: npt.NDArray[np.float64] = features[indices]
            sub_assignments: list[int] = cluster_beliefs(
                group_ids, group_features, k=k_per_group
            )
            for j, idx in enumerate(indices):
                assignments[idx] = cluster_offset + sub_assignments[j]
            cluster_offset += k_per_group

    return assignments


def analyze_clusters(
    ids: list[str],
    assignments: list[int],
    conn: sqlite3.Connection,
    label: str,
) -> dict[str, float]:
    """Analyze cluster quality."""
    n: int = len(ids)
    cluster_sizes: Counter[int] = Counter(assignments)
    k: int = len(cluster_sizes)
    max_size: int = max(cluster_sizes.values())
    max_pct: float = max_size / n * 100

    # Gini of cluster sizes
    sizes: list[float] = [float(c) for c in sorted(cluster_sizes.values())]
    n_c: int = len(sizes)
    total_s: float = sum(sizes)
    gini: float = 0.0
    if total_s > 0 and n_c > 1:
        numer: float = sum((2 * (i + 1) - n_c - 1) * sizes[i] for i in range(n_c))
        gini = numer / (n_c * total_s)

    # Vocab gap analysis: sample pairs within same cluster
    conn.row_factory = sqlite3.Row
    content_map: dict[str, str] = {}
    content_rows = conn.execute(
        "SELECT id, content FROM beliefs WHERE id IN ({})".format(
            ",".join("?" * len(ids))
        ),
        ids,
    ).fetchall()
    for r in content_rows:
        content_map[str(r["id"])] = str(r["content"])

    # Group by cluster
    cluster_members: dict[int, list[str]] = {}
    for i, bid in enumerate(ids):
        c: int = assignments[i]
        if c not in cluster_members:
            cluster_members[c] = []
        cluster_members[c].append(bid)

    random.seed(42)
    total_pairs: int = 0
    low_overlap: int = 0
    for c_id, members in cluster_members.items():
        sample = random.sample(members, min(50, len(members)))
        for i in range(len(sample)):
            for j in range(i + 1, min(i + 5, len(sample))):
                ws_i: set[str] = word_set(content_map.get(sample[i], ""))
                ws_j: set[str] = word_set(content_map.get(sample[j], ""))
                jac: float = jaccard(ws_i, ws_j)
                total_pairs += 1
                if jac < 0.1:
                    low_overlap += 1

    vocab_gap_rate: float = low_overlap / max(1, total_pairs) * 100

    print(f"\n  {label}:")
    print(f"    Clusters: {k}")
    print(f"    Largest cluster: {max_size} ({max_pct:.1f}%)")
    print(f"    Gini of cluster sizes: {gini:.4f}")
    print(f"    Vocab gap rate: {vocab_gap_rate:.1f}% (same-cluster, Jaccard<0.1)")
    print(f"    Top 5 sizes: {[c for _, c in cluster_sizes.most_common(5)]}")

    return {
        "k": float(k),
        "max_pct": max_pct,
        "gini": gini,
        "vocab_gap": vocab_gap_rate,
    }


def main() -> None:
    db_path: str = str(
        Path.home() / ".agentmemory" / "projects" / "2e7ed55e017a" / "memory.db"
    )
    conn: sqlite3.Connection = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    print("=" * 70)
    print("Exp 96: Hierarchical Intention Clustering")
    print("=" * 70)

    ids: list[str]
    features: npt.NDArray[np.float64]
    ids, features = build_features(conn)
    print(f"Population: {len(ids)} beliefs, {features.shape[1]} features")

    results: dict[str, dict[str, float]] = {}

    # Baseline: k=8
    a8: list[int] = cluster_beliefs(ids, features, k=8)
    results["k=8 (baseline)"] = analyze_clusters(ids, a8, conn, "k=8 (baseline)")

    # H4: k=40 flat
    a40: list[int] = cluster_beliefs(ids, features, k=40)
    results["k=40 (flat)"] = analyze_clusters(ids, a40, conn, "k=40 (flat)")

    # H4 variant: k=20
    a20: list[int] = cluster_beliefs(ids, features, k=20)
    results["k=20 (flat)"] = analyze_clusters(ids, a20, conn, "k=20 (flat)")

    # H3: two-level (type+source, then k=5 within)
    a_2level_5: list[int] = two_level_cluster(conn, ids, features, k_per_group=5)
    results["two-level (k=5/group)"] = analyze_clusters(
        ids, a_2level_5, conn, "two-level (k=5/group)"
    )

    # H3 variant: two-level k=8 within
    a_2level_8: list[int] = two_level_cluster(conn, ids, features, k_per_group=8)
    results["two-level (k=8/group)"] = analyze_clusters(
        ids, a_2level_8, conn, "two-level (k=8/group)"
    )

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(
        f"{'Config':>25s}  {'Clusters':>8s}  {'Max%':>6s}  {'Gini':>6s}  {'VocGap%':>7s}"
    )
    print("-" * 60)
    for name, r in results.items():
        print(
            f"{name:>25s}  {r['k']:>8.0f}  {r['max_pct']:>5.1f}%  "
            f"{r['gini']:>6.4f}  {r['vocab_gap']:>6.1f}%"
        )

    # Hypothesis tests
    print()
    h3_pass: bool = results["two-level (k=5/group)"]["max_pct"] < 20.0
    h4_pass: bool = (
        results["k=40 (flat)"]["gini"] > results["k=8 (baseline)"]["gini"]
    )
    print(
        f"H3 (two-level, no cluster >20%): "
        f"{'PASS' if h3_pass else 'FAIL'} "
        f"(max={results['two-level (k=5/group)']['max_pct']:.1f}%)"
    )
    print(
        f"H4 (k=40 Gini > k=8 Gini): "
        f"{'PASS' if h4_pass else 'FAIL'} "
        f"({results['k=40 (flat)']['gini']:.4f} vs {results['k=8 (baseline)']['gini']:.4f})"
    )

    conn.close()


if __name__ == "__main__":
    main()
