"""Holographic Reduced Representations for belief graph encoding.

Implements circular convolution binding, partitioned superposition encoding,
and routed single-hop queries for vocabulary-bridge retrieval.

Based on Plate (1995) and validated in Exp 24-34. The real value is
fuzzy-start typed traversal, not multi-hop (Exp 26 finding).

Architecture: FTS5 (92% keyword) + HRR single-hop (8% vocabulary bridge).
"""

from __future__ import annotations

from typing import Final

import numpy as np
import numpy.typing as npt

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Vector = npt.NDArray[np.float64]

# Default dimensionality. Capacity = dim // 9 edges per partition.
DEFAULT_DIM: Final[int] = 2048


# ---------------------------------------------------------------------------
# Core HRR operations
# ---------------------------------------------------------------------------


def random_vector(dim: int, rng: np.random.Generator) -> Vector:
    """Generate a random unit vector from N(0, 1/sqrt(n))."""
    v: Vector = rng.normal(0, 1.0 / np.sqrt(dim), size=dim).astype(np.float64)
    norm: float = float(np.linalg.norm(v))
    if norm > 0:
        v = (v / norm).astype(np.float64)
    return v


def bind(a: Vector, b: Vector) -> Vector:
    """Circular convolution (binding) via FFT."""
    result: Vector = np.real(np.fft.ifft(np.fft.fft(a) * np.fft.fft(b))).astype(
        np.float64
    )
    return result


def unbind(key: Vector, composite: Vector) -> Vector:
    """Circular correlation (unbinding) via FFT."""
    result: Vector = np.real(
        np.fft.ifft(np.conj(np.fft.fft(key)) * np.fft.fft(composite))
    ).astype(np.float64)
    return result


def superpose(vectors: list[Vector]) -> Vector:
    """Bundle vectors via addition."""
    result: Vector = np.sum(np.array(vectors), axis=0).astype(np.float64)
    return result


def cosine_similarity(a: Vector, b: Vector) -> float:
    """Cosine similarity between two vectors."""
    na: float = float(np.linalg.norm(a))
    nb: float = float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# ---------------------------------------------------------------------------
# Cleanup memory (nearest-neighbor recovery)
# ---------------------------------------------------------------------------


class CleanupMemory:
    """Stores labeled vectors for approximate recovery via cosine similarity."""

    def __init__(self) -> None:
        self._labels: list[str] = []
        self._vectors: list[Vector] = []
        self._matrix: Vector | None = None

    def add(self, label: str, vector: Vector) -> None:
        """Add a labeled vector."""
        self._labels.append(label)
        self._vectors.append(vector)
        self._matrix = None  # invalidate cache

    def query(self, probe: Vector, top_k: int = 10) -> list[tuple[str, float]]:
        """Return top-k nearest neighbors by cosine similarity."""
        if not self._labels:
            return []
        if self._matrix is None:
            self._matrix = np.array(self._vectors, dtype=np.float64)
        # Batch cosine similarity
        norms: Vector = np.linalg.norm(self._matrix, axis=1).astype(np.float64)
        norms = np.where(norms > 0, norms, 1.0).astype(np.float64)
        normalized: Vector = (self._matrix / norms[:, np.newaxis]).astype(np.float64)
        probe_norm: float = float(np.linalg.norm(probe))
        if probe_norm == 0:
            return []
        probe_normalized: Vector = (probe / probe_norm).astype(np.float64)
        sims: Vector = (normalized @ probe_normalized).astype(np.float64)
        # Top-k indices
        k: int = min(top_k, len(self._labels))
        top_indices: npt.NDArray[np.intp] = np.argpartition(sims, -k)[-k:]
        top_indices = top_indices[np.argsort(sims[top_indices])[::-1]]
        return [(self._labels[int(i)], float(sims[int(i)])) for i in top_indices]

    def size(self) -> int:
        return len(self._labels)


# ---------------------------------------------------------------------------
# HRR Graph
# ---------------------------------------------------------------------------


class HRRGraph:
    """Partitioned HRR graph with routed queries.

    Encodes typed edges as superpositions of bound triples:
        triple = bind(bind(source, edge_type), target)
        partition_vector = superpose(all triples in partition)

    Queries unbind the probe from relevant partitions and recover
    targets via cleanup memory.
    """

    def __init__(self, dim: int = DEFAULT_DIM, seed: int = 42) -> None:
        self.dim: int = dim
        self.capacity: int = dim // 9  # reliable retrieval threshold
        self._rng: np.random.Generator = np.random.default_rng(seed)
        self._node_vecs: dict[str, Vector] = {}
        self._edge_type_vecs: dict[str, Vector] = {}
        self._cleanup: CleanupMemory = CleanupMemory()
        self._partitions: list[dict[str, object]] = []
        self._node_to_partitions: dict[str, set[int]] = {}

    def _get_node_vec(self, node_id: str) -> Vector:
        """Get or create a random vector for a node."""
        if node_id not in self._node_vecs:
            v: Vector = random_vector(self.dim, self._rng)
            self._node_vecs[node_id] = v
            self._cleanup.add(node_id, v)
        return self._node_vecs[node_id]

    def _get_edge_type_vec(self, edge_type: str) -> Vector:
        """Get or create a random vector for an edge type."""
        if edge_type not in self._edge_type_vecs:
            self._edge_type_vecs[edge_type] = random_vector(self.dim, self._rng)
        return self._edge_type_vecs[edge_type]

    def encode(self, edges: list[tuple[str, str, str]]) -> None:
        """Encode a list of (source, target, edge_type) triples.

        Partitions edges by edge type, then chunks large types at capacity.
        Each partition becomes a superposition vector.
        """
        # Group by edge type
        by_type: dict[str, list[tuple[str, str, str]]] = {}
        for src, tgt, etype in edges:
            by_type.setdefault(etype, []).append((src, tgt, etype))

        # Partition: one per edge type, chunk at capacity
        partitions: list[list[tuple[str, str, str]]] = []
        for etype, type_edges in by_type.items():
            for i in range(0, len(type_edges), self.capacity):
                partitions.append(type_edges[i : i + self.capacity])

        # Encode each partition
        for part_edges in partitions:
            triples: list[Vector] = []
            nodes_in_part: set[str] = set()
            edge_types_in_part: set[str] = set()

            for src, tgt, etype in part_edges:
                s_vec: Vector = self._get_node_vec(src)
                t_vec: Vector = self._get_node_vec(tgt)
                e_vec: Vector = self._get_edge_type_vec(etype)
                triple: Vector = bind(bind(s_vec, e_vec), t_vec)
                triples.append(triple)
                nodes_in_part.add(src)
                nodes_in_part.add(tgt)
                edge_types_in_part.add(etype)

            if not triples:
                continue

            superposition: Vector = superpose(triples)
            part_idx: int = len(self._partitions)

            self._partitions.append(
                {
                    "vector": superposition,
                    "edge_count": len(triples),
                    "edge_types": edge_types_in_part,
                    "nodes": nodes_in_part,
                }
            )

            # Update routing index
            for node in nodes_in_part:
                if node not in self._node_to_partitions:
                    self._node_to_partitions[node] = set()
                self._node_to_partitions[node].add(part_idx)

    def _relevant_partitions(self, node_id: str) -> list[int]:
        """Get partition indices containing this node."""
        return sorted(
            self._node_to_partitions.get(node_id, range(len(self._partitions)))
        )

    def query_forward(
        self,
        source: str,
        edge_type: str,
        top_k: int = 10,
        threshold: float = 0.05,
    ) -> list[tuple[str, float]]:
        """Query: what does source connect to via edge_type?

        Returns (target_id, similarity) pairs sorted by similarity.
        """
        if source not in self._node_vecs or edge_type not in self._edge_type_vecs:
            return []

        s_vec: Vector = self._node_vecs[source]
        e_vec: Vector = self._edge_type_vecs[edge_type]
        query_vec: Vector = bind(s_vec, e_vec)

        # Unbind from relevant partitions and aggregate
        aggregated: Vector = np.zeros(self.dim)
        for idx in self._relevant_partitions(source):
            part: dict[str, object] = self._partitions[idx]
            part_vec: Vector = part["vector"]  # type: ignore[assignment]
            unbound: Vector = unbind(query_vec, part_vec)
            aggregated = aggregated + unbound

        # Recover targets from cleanup memory
        results: list[tuple[str, float]] = self._cleanup.query(
            aggregated, top_k=top_k + 1
        )

        # Filter out self and below threshold
        filtered: list[tuple[str, float]] = [
            (label, sim)
            for label, sim in results
            if label != source and sim >= threshold
        ]
        return filtered[:top_k]

    def query_reverse(
        self,
        target: str,
        edge_type: str,
        top_k: int = 10,
        threshold: float = 0.05,
    ) -> list[tuple[str, float]]:
        """Query: what connects to target via edge_type?

        Returns (source_id, similarity) pairs sorted by similarity.
        """
        if target not in self._node_vecs or edge_type not in self._edge_type_vecs:
            return []

        t_vec: Vector = self._node_vecs[target]
        e_vec: Vector = self._edge_type_vecs[edge_type]

        aggregated: Vector = np.zeros(self.dim)
        for idx in self._relevant_partitions(target):
            part: dict[str, object] = self._partitions[idx]
            part_vec: Vector = part["vector"]  # type: ignore[assignment]
            # For reverse: unbind target from partition, then unbind edge type
            unbound: Vector = unbind(t_vec, part_vec)
            unbound = unbind(e_vec, unbound)
            aggregated = aggregated + unbound

        results: list[tuple[str, float]] = self._cleanup.query(
            aggregated, top_k=top_k + 1
        )
        filtered: list[tuple[str, float]] = [
            (label, sim)
            for label, sim in results
            if label != target and sim >= threshold
        ]
        return filtered[:top_k]

    def node_count(self) -> int:
        return len(self._node_vecs)

    def edge_types(self) -> list[str]:
        """Return all encoded edge types."""
        return sorted(self._edge_type_vecs.keys())

    def edge_type_count(self) -> int:
        return len(self._edge_type_vecs)

    def partition_count(self) -> int:
        return len(self._partitions)

    def summary(self) -> dict[str, object]:
        """Return graph encoding summary."""
        return {
            "dim": self.dim,
            "capacity": self.capacity,
            "nodes": self.node_count(),
            "edge_types": sorted(self._edge_type_vecs.keys()),
            "partitions": self.partition_count(),
            "total_edges": sum(int(str(p["edge_count"])) for p in self._partitions),
        }
