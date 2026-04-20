"""Exp 94b: Intention-space clustering of belief graph.

Clusters beliefs by "intention" -- what question does this belief answer? --
rather than by vocabulary. Uses graph structure (edges) and belief metadata
to define an intention embedding, then clusters to find natural groupings.

Approach:
  1. Build a feature vector per belief from:
     - belief_type (one-hot)
     - source_type (one-hot)
     - edge connectivity pattern (which edge types connect to it)
     - graph neighborhood (types of connected beliefs)
  2. Cluster using simple k-means on these features
  3. Analyze: do clusters correspond to "intention categories"?
     (e.g., "architecture decisions", "user preferences", "debug context")
  4. Check if beliefs in the same cluster but with no shared vocabulary
     would benefit from cross-retrieval

Usage:
    uv run python experiments/exp94b_intention_clustering.py
"""

from __future__ import annotations

import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

BELIEF_TYPES: list[str] = [
    "factual", "requirement", "correction", "preference",
    "assumption", "decision", "analysis", "speculative",
]
SOURCE_TYPES: list[str] = [
    "agent_inferred", "user_corrected", "user_stated",
    "document_recent", "document_old", "wonder_generated",
]
EDGE_TYPES: list[str] = [
    "RELATES_TO", "SUPPORTS", "CONTRADICTS", "CITES",
    "SUPERSEDES", "TEMPORAL_NEXT",
]


@dataclass
class BeliefFeatures:
    """Feature vector for intention clustering."""

    belief_id: str
    content: str
    belief_type: str
    source_type: str
    features: list[float]  # concatenated feature vector

    # Cluster assignment (set during clustering)
    cluster: int = -1


def extract_features(db_path: str) -> list[BeliefFeatures]:
    """Build feature vectors from belief metadata and graph structure."""
    conn: sqlite3.Connection = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Load beliefs
    belief_rows: list[sqlite3.Row] = conn.execute(
        """SELECT id, content, belief_type, source_type, locked,
                  confidence, alpha, beta_param
           FROM beliefs WHERE superseded_by IS NULL"""
    ).fetchall()

    # Load edges
    edge_rows: list[sqlite3.Row] = conn.execute(
        "SELECT from_id, to_id, edge_type FROM edges"
    ).fetchall()
    conn.close()

    # Build adjacency info
    outgoing: dict[str, Counter[str]] = defaultdict(Counter)
    incoming: dict[str, Counter[str]] = defaultdict(Counter)
    neighbor_types: dict[str, Counter[str]] = defaultdict(Counter)

    belief_type_map: dict[str, str] = {
        str(r["id"]): str(r["belief_type"]) for r in belief_rows
    }

    for e in edge_rows:
        from_id: str = str(e["from_id"])
        to_id: str = str(e["to_id"])
        etype: str = str(e["edge_type"])
        outgoing[from_id][etype] += 1
        incoming[to_id][etype] += 1
        # Track neighbor belief types
        if to_id in belief_type_map:
            neighbor_types[from_id][belief_type_map[to_id]] += 1
        if from_id in belief_type_map:
            neighbor_types[to_id][belief_type_map[from_id]] += 1

    # Build feature vectors
    results: list[BeliefFeatures] = []
    for r in belief_rows:
        bid: str = str(r["id"])
        bt: str = str(r["belief_type"])
        st: str = str(r["source_type"])

        features: list[float] = []

        # One-hot belief type (8 dims)
        for t in BELIEF_TYPES:
            features.append(1.0 if bt == t else 0.0)

        # One-hot source type (6 dims)
        for t in SOURCE_TYPES:
            features.append(1.0 if st == t else 0.0)

        # Edge connectivity (12 dims: 6 outgoing + 6 incoming, log-scaled)
        for et in EDGE_TYPES:
            features.append(math.log1p(outgoing[bid].get(et, 0)))
        for et in EDGE_TYPES:
            features.append(math.log1p(incoming[bid].get(et, 0)))

        # Neighbor type distribution (8 dims, normalized)
        total_neighbors: int = sum(neighbor_types[bid].values())
        for t in BELIEF_TYPES:
            if total_neighbors > 0:
                features.append(neighbor_types[bid].get(t, 0) / total_neighbors)
            else:
                features.append(0.0)

        # Scalar features (3 dims)
        features.append(float(r["locked"]))
        features.append(float(r["confidence"]))
        features.append(math.log1p(len(str(r["content"]))))

        results.append(BeliefFeatures(
            belief_id=bid,
            content=str(r["content"]),
            belief_type=bt,
            source_type=st,
            features=features,
        ))

    return results


# ---------------------------------------------------------------------------
# K-means clustering (no sklearn dependency)
# ---------------------------------------------------------------------------

def kmeans(
    data: list[list[float]], k: int, max_iter: int = 50, seed: int = 42
) -> list[int]:
    """Vectorized k-means using numpy. Returns cluster assignments."""
    import numpy as np

    rng: np.random.Generator = np.random.default_rng(seed)
    arr: np.ndarray[tuple[int, int], np.dtype[np.float64]] = np.array(data, dtype=np.float64)
    n: int = arr.shape[0]

    # Initialize centroids (k-means++)
    first_idx: int = int(rng.integers(0, n))
    centroids: np.ndarray[tuple[int, int], np.dtype[np.float64]] = arr[first_idx : first_idx + 1].copy()
    for _ in range(1, k):
        dists: np.ndarray[tuple[int], np.dtype[np.float64]] = np.min(
            np.sum((arr[:, None, :] - centroids[None, :, :]) ** 2, axis=2), axis=1
        )
        total_d: float = float(np.sum(dists))
        if total_d == 0:
            idx: int = int(rng.integers(0, n))
            centroids = np.vstack([centroids, arr[idx]])
            continue
        probs: np.ndarray[tuple[int], np.dtype[np.float64]] = dists / total_d
        idx = int(rng.choice(n, p=probs))
        centroids = np.vstack([centroids, arr[idx]])

    assignments: np.ndarray[tuple[int], np.dtype[np.intp]] = np.zeros(n, dtype=np.intp)

    for _iteration in range(max_iter):
        # Vectorized assignment: compute all distances at once
        # (n, 1, dim) - (1, k, dim) -> (n, k, dim) -> sum -> (n, k)
        dist_matrix: np.ndarray[tuple[int, int], np.dtype[np.float64]] = np.sum(
            (arr[:, None, :] - centroids[None, :, :]) ** 2, axis=2
        )
        new_assignments: np.ndarray[tuple[int], np.dtype[np.intp]] = np.argmin(dist_matrix, axis=1)

        if np.array_equal(new_assignments, assignments):
            break
        assignments = new_assignments

        # Update centroids
        for c in range(k):
            mask: np.ndarray[tuple[int], np.dtype[np.bool_]] = assignments == c
            if np.any(mask):
                centroids[c] = np.mean(arr[mask], axis=0)

    return assignments.tolist()


# ---------------------------------------------------------------------------
# Vocabulary overlap analysis
# ---------------------------------------------------------------------------

def word_set(text: str) -> set[str]:
    """Extract lowered words (3+ chars) from text."""
    return {w.lower() for w in text.split() if len(w) >= 3}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    db_path: str = str(
        Path.home() / ".agentmemory" / "projects" / "2e7ed55e017a" / "memory.db"
    )

    print("=" * 70)
    print("Exp 94b: Intention-Space Clustering")
    print("=" * 70)
    print()

    beliefs: list[BeliefFeatures] = extract_features(db_path)
    print(f"Population: {len(beliefs)} beliefs")
    print(f"Feature dim: {len(beliefs[0].features)}")
    print()

    # Normalize features (z-score per dimension)
    dim: int = len(beliefs[0].features)
    means: list[float] = [0.0] * dim
    for b in beliefs:
        for d in range(dim):
            means[d] += b.features[d]
    means = [m / len(beliefs) for m in means]

    stds: list[float] = [0.0] * dim
    for b in beliefs:
        for d in range(dim):
            stds[d] += (b.features[d] - means[d]) ** 2
    stds = [math.sqrt(s / len(beliefs)) for s in stds]

    normalized: list[list[float]] = []
    for b in beliefs:
        norm: list[float] = []
        for d in range(dim):
            if stds[d] > 1e-10:
                norm.append((b.features[d] - means[d]) / stds[d])
            else:
                norm.append(0.0)
        normalized.append(norm)

    # Try multiple k values
    import numpy as np
    arr: np.ndarray[tuple[int, int], np.dtype[np.float64]] = np.array(normalized, dtype=np.float64)

    print("## ELBOW ANALYSIS")
    for k in [3, 5, 8, 12, 16, 20]:
        assignments: list[int] = kmeans(normalized, k)
        assign_arr: np.ndarray[tuple[int], np.dtype[np.intp]] = np.array(assignments, dtype=np.intp)

        # Vectorized WCSS
        wcss: float = 0.0
        for c in range(k):
            mask: np.ndarray[tuple[int], np.dtype[np.bool_]] = assign_arr == c
            if not np.any(mask):
                continue
            members: np.ndarray[tuple[int, int], np.dtype[np.float64]] = arr[mask]
            centroid: np.ndarray[tuple[int], np.dtype[np.float64]] = np.mean(members, axis=0)
            wcss += float(np.sum((members - centroid) ** 2))

        cluster_sizes: Counter[int] = Counter(assignments)
        min_size: int = min(cluster_sizes.values())
        max_size: int = max(cluster_sizes.values())
        print(f"  k={k:>2d}: WCSS={wcss:>12.1f}  sizes=[{min_size}..{max_size}]  "
              f"biggest={max_size/len(beliefs)*100:.0f}%")

    # Detailed analysis at k=8
    print()
    print("## DETAILED CLUSTERING (k=8)")
    k: int = 8
    assignments = kmeans(normalized, k)
    for i, b in enumerate(beliefs):
        b.cluster = assignments[i]

    # Cluster profiles
    for c in range(k):
        members: list[BeliefFeatures] = [b for b in beliefs if b.cluster == c]
        if not members:
            continue

        # Dominant belief type
        bt_counts: Counter[str] = Counter(m.belief_type for m in members)
        top_bt: str = bt_counts.most_common(1)[0][0]
        top_bt_pct: float = bt_counts.most_common(1)[0][1] / len(members) * 100

        # Dominant source type
        st_counts: Counter[str] = Counter(m.source_type for m in members)
        top_st: str = st_counts.most_common(1)[0][0]
        top_st_pct: float = st_counts.most_common(1)[0][1] / len(members) * 100

        # Sample content
        samples: list[str] = [m.content[:80] for m in members[:3]]

        print(f"\n  Cluster {c}: {len(members)} beliefs ({len(members)/len(beliefs)*100:.1f}%)")
        print(f"    Dominant type:   {top_bt} ({top_bt_pct:.0f}%)")
        print(f"    Dominant source: {top_st} ({top_st_pct:.0f}%)")
        print(f"    Type dist: {dict(bt_counts.most_common(3))}")
        print(f"    Samples:")
        for s in samples:
            print(f"      - {s}")

    # --- VOCABULARY GAP ANALYSIS ---
    # Find pairs within the same cluster that have LOW vocabulary overlap
    # These are the beliefs that share intention but not vocabulary
    print()
    print("## VOCABULARY GAP ANALYSIS (same cluster, low vocab overlap)")
    print("  These are beliefs that an intention layer would connect")
    print("  but FTS5 keyword search cannot.")
    print()

    total_pairs: int = 0
    low_overlap_pairs: int = 0
    gap_examples: list[tuple[str, str, int, float]] = []

    for c in range(k):
        members = [b for b in beliefs if b.cluster == c]
        # Sample pairs (cap at 500 to keep it fast)
        import random
        random.seed(42)
        sample: list[BeliefFeatures] = random.sample(members, min(100, len(members)))

        for i in range(len(sample)):
            for j in range(i + 1, min(i + 10, len(sample))):
                ws_i: set[str] = word_set(sample[i].content)
                ws_j: set[str] = word_set(sample[j].content)
                jac: float = jaccard(ws_i, ws_j)
                total_pairs += 1
                if jac < 0.1:
                    low_overlap_pairs += 1
                    if len(gap_examples) < 5:
                        gap_examples.append((
                            sample[i].content[:60],
                            sample[j].content[:60],
                            c, jac,
                        ))

    gap_rate: float = low_overlap_pairs / max(1, total_pairs) * 100
    print(f"  Total pairs sampled: {total_pairs}")
    print(f"  Low overlap (Jaccard < 0.1): {low_overlap_pairs} ({gap_rate:.1f}%)")
    print()

    if gap_examples:
        print("  Examples of same-cluster, different-vocabulary beliefs:")
        for content_a, content_b, cluster, jac in gap_examples:
            print(f"    Cluster {cluster} (Jaccard={jac:.3f}):")
            print(f"      A: {content_a}")
            print(f"      B: {content_b}")
            print()

    # --- CROSS-CLUSTER VOCABULARY ---
    # High vocab overlap across clusters = noise; the clustering is capturing
    # something beyond vocabulary
    print("## CROSS-CLUSTER OVERLAP (high vocab overlap, different clusters)")
    cross_examples: list[tuple[str, str, int, int, float]] = []
    random.seed(43)
    all_sample: list[BeliefFeatures] = random.sample(beliefs, min(200, len(beliefs)))
    cross_total: int = 0
    cross_high: int = 0

    for i in range(len(all_sample)):
        for j in range(i + 1, min(i + 5, len(all_sample))):
            if all_sample[i].cluster == all_sample[j].cluster:
                continue
            ws_i = word_set(all_sample[i].content)
            ws_j = word_set(all_sample[j].content)
            jac = jaccard(ws_i, ws_j)
            cross_total += 1
            if jac > 0.3:
                cross_high += 1
                if len(cross_examples) < 3:
                    cross_examples.append((
                        all_sample[i].content[:60],
                        all_sample[j].content[:60],
                        all_sample[i].cluster,
                        all_sample[j].cluster,
                        jac,
                    ))

    if cross_total > 0:
        print(f"  Cross-cluster pairs: {cross_total}")
        print(f"  High overlap (Jaccard > 0.3): {cross_high} ({cross_high/cross_total*100:.1f}%)")
        if cross_examples:
            print("  Examples:")
            for ca, cb, cl_a, cl_b, jac in cross_examples:
                print(f"    Cluster {cl_a} vs {cl_b} (Jaccard={jac:.3f}):")
                print(f"      A: {ca}")
                print(f"      B: {cb}")
                print()

    # --- VERDICT ---
    print("=" * 70)
    print("## VERDICT")
    print("=" * 70)
    print()
    if gap_rate > 30:
        print(f"  STRONG SIGNAL: {gap_rate:.0f}% of same-cluster pairs have <10% vocab overlap.")
        print("  An intention layer would bridge vocabulary gaps that FTS5 cannot.")
        print("  These clusters define natural 'intention categories' for retrieval.")
    elif gap_rate > 15:
        print(f"  MODERATE SIGNAL: {gap_rate:.0f}% vocab-gap pairs in same clusters.")
        print("  There's structure beyond vocabulary, but not dominant.")
    else:
        print(f"  WEAK SIGNAL: Only {gap_rate:.0f}% vocab-gap pairs.")
        print("  Vocabulary and intention are highly correlated in this corpus.")
        print("  An intention layer may not add much over FTS5.")


if __name__ == "__main__":
    main()
