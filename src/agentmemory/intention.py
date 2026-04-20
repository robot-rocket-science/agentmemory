"""Intention-space clustering for vocabulary-gap bridging.

Assigns beliefs to intention clusters based on metadata and graph structure,
not vocabulary. Exp 94b showed 98% of same-cluster pairs have <10% vocab
overlap -- these clusters capture "what question does this belief answer?"
rather than "what words does it use."

The hook search path uses cluster assignments to expand FTS5 results:
when FTS5 returns beliefs from cluster X, also pull top beliefs from
cluster X that FTS5 missed due to vocabulary mismatch.

Cluster assignments are stored in the belief_clusters table and rebuilt
when the edge graph changes (same trigger as HRR precompute).
"""

from __future__ import annotations

import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone

import numpy as np
import numpy.typing as npt

# Feature dimensions
BELIEF_TYPES: list[str] = [
    "factual",
    "requirement",
    "correction",
    "preference",
    "assumption",
    "decision",
    "analysis",
    "speculative",
]
SOURCE_TYPES: list[str] = [
    "agent_inferred",
    "user_corrected",
    "user_stated",
    "document_recent",
    "document_old",
    "wonder_generated",
]
EDGE_TYPES: list[str] = [
    "RELATES_TO",
    "SUPPORTS",
    "CONTRADICTS",
    "CITES",
    "SUPERSEDES",
    "TEMPORAL_NEXT",
]

# Total feature dim: 8 + 6 + 12 + 8 + 3 = 37
FEATURE_DIM: int = (
    len(BELIEF_TYPES) + len(SOURCE_TYPES) + 2 * len(EDGE_TYPES) + len(BELIEF_TYPES) + 3
)

# Default cluster count. Exp 96 showed k=40 drops the largest cluster
# from 81% to 29%, making expansion queries discriminative. k=8 produced
# a single 12,764-belief mega-cluster that was useless for expansion.
DEFAULT_K: int = 40


def build_features(
    conn: sqlite3.Connection,
) -> tuple[list[str], npt.NDArray[np.float64]]:
    """Extract feature vectors for all active beliefs.

    Returns (belief_ids, feature_matrix) where feature_matrix is (n, FEATURE_DIM).
    """
    conn.row_factory = sqlite3.Row

    rows: list[sqlite3.Row] = conn.execute(
        """SELECT id, belief_type, source_type, locked, confidence
           FROM beliefs WHERE superseded_by IS NULL AND valid_to IS NULL"""
    ).fetchall()

    if not rows:
        return [], np.zeros((0, FEATURE_DIM), dtype=np.float64)

    # Build adjacency info
    edge_rows: list[sqlite3.Row] = conn.execute(
        "SELECT from_id, to_id, edge_type FROM edges"
    ).fetchall()

    outgoing: dict[str, Counter[str]] = defaultdict(Counter)
    incoming: dict[str, Counter[str]] = defaultdict(Counter)
    neighbor_types: dict[str, Counter[str]] = defaultdict(Counter)

    bt_map: dict[str, str] = {str(r["id"]): str(r["belief_type"]) for r in rows}

    for e in edge_rows:
        fid: str = str(e["from_id"])
        tid: str = str(e["to_id"])
        etype: str = str(e["edge_type"])
        outgoing[fid][etype] += 1
        incoming[tid][etype] += 1
        if tid in bt_map:
            neighbor_types[fid][bt_map[tid]] += 1
        if fid in bt_map:
            neighbor_types[tid][bt_map[fid]] += 1

    ids: list[str] = []
    features: list[list[float]] = []

    for r in rows:
        bid: str = str(r["id"])
        bt: str = str(r["belief_type"])
        st: str = str(r["source_type"])
        ids.append(bid)

        feat: list[float] = []

        # One-hot belief type
        for t in BELIEF_TYPES:
            feat.append(1.0 if bt == t else 0.0)

        # One-hot source type
        for t in SOURCE_TYPES:
            feat.append(1.0 if st == t else 0.0)

        # Edge connectivity (log-scaled)
        for et in EDGE_TYPES:
            feat.append(math.log1p(outgoing[bid].get(et, 0)))
        for et in EDGE_TYPES:
            feat.append(math.log1p(incoming[bid].get(et, 0)))

        # Neighbor type distribution
        total_neighbors: int = sum(neighbor_types[bid].values())
        for t in BELIEF_TYPES:
            if total_neighbors > 0:
                feat.append(neighbor_types[bid].get(t, 0) / total_neighbors)
            else:
                feat.append(0.0)

        # Scalar features
        feat.append(float(r["locked"]))
        feat.append(float(r["confidence"]))
        feat.append(math.log1p(len(str(r["id"]))))  # placeholder for content length

        features.append(feat)

    arr: npt.NDArray[np.float64] = np.array(features, dtype=np.float64)
    return ids, arr


def cluster_beliefs(
    ids: list[str],
    features: npt.NDArray[np.float64],
    k: int = DEFAULT_K,
    max_iter: int = 50,
    seed: int = 42,
) -> list[int]:
    """K-means clustering on normalized features. Returns cluster assignments."""
    if len(ids) == 0:
        return []

    n: int = features.shape[0]
    if n <= k:
        return list(range(n))

    # Z-score normalize
    means: npt.NDArray[np.float64] = np.mean(features, axis=0)
    stds: npt.NDArray[np.float64] = np.std(features, axis=0)
    stds = np.where(stds > 1e-10, stds, 1.0).astype(np.float64)
    normalized: npt.NDArray[np.float64] = ((features - means) / stds).astype(np.float64)

    # K-means++ init
    rng: np.random.Generator = np.random.default_rng(seed)
    first_idx: int = int(rng.integers(0, n))
    centroids: npt.NDArray[np.float64] = normalized[first_idx : first_idx + 1].copy()

    for _ in range(1, k):
        dists: npt.NDArray[np.float64] = np.min(
            np.sum((normalized[:, None, :] - centroids[None, :, :]) ** 2, axis=2),
            axis=1,
        )
        total_d: float = float(np.sum(dists))
        if total_d == 0:
            idx: int = int(rng.integers(0, n))
        else:
            probs: npt.NDArray[np.float64] = dists / total_d
            idx = int(rng.choice(n, p=probs))
        centroids = np.vstack([centroids, normalized[idx]])

    assignments: npt.NDArray[np.intp] = np.zeros(n, dtype=np.intp)

    for _ in range(max_iter):
        dist_matrix: npt.NDArray[np.float64] = np.sum(
            (normalized[:, None, :] - centroids[None, :, :]) ** 2, axis=2
        )
        new_assignments: npt.NDArray[np.intp] = np.argmin(dist_matrix, axis=1)

        if np.array_equal(new_assignments, assignments):
            break
        assignments = new_assignments

        for c in range(k):
            mask: npt.NDArray[np.bool_] = assignments == c
            if np.any(mask):
                centroids[c] = np.mean(normalized[mask], axis=0)

    return assignments.tolist()


def build_cluster_table(conn: sqlite3.Connection, k: int = DEFAULT_K) -> int:
    """Build or rebuild the belief_clusters table.

    Returns the number of beliefs clustered.
    """
    ids: list[str]
    features: npt.NDArray[np.float64]
    ids, features = build_features(conn)
    if not ids:
        return 0

    assignments: list[int] = cluster_beliefs(ids, features, k=k)
    now_iso: str = datetime.now(timezone.utc).isoformat()

    try:
        conn.execute("DELETE FROM belief_clusters")
    except Exception:
        return 0

    batch: list[tuple[str, int, str]] = [
        (ids[i], assignments[i], now_iso) for i in range(len(ids))
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO belief_clusters (belief_id, cluster_id, created_at) VALUES (?, ?, ?)",
        batch,
    )
    conn.commit()
    return len(ids)
