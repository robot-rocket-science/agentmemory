"""
hrr_encoder.py -- H1: Encode extracted graphs into HRR superpositions.

Takes extracted graph JSON files and produces:
  1. Node vectors (random, stored in cleanup memory)
  2. Edge type vectors (random, orthogonal)
  3. Subgraph superpositions (partitioned to stay within capacity)
  4. Retrieval functions (single-hop typed traversal)

Usage:
    python scripts/hrr_encoder.py /path/to/extracted_dir <repo_name> [--dim 2048] [--output path]

Reads: extracted/{git_edges,import_edges,structural_edges}/<repo>.json
Writes: extracted/hrr/<repo>.json (vectors stored as base64 for compactness)
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
from numpy.typing import NDArray


# --- Core HRR Operations ---

Vector = NDArray[np.float64]


def random_vector(dim: int, rng: np.random.Generator) -> Vector:
    """Generate a random unit vector from N(0, 1/n)."""
    v: Vector = rng.normal(0, 1.0 / math.sqrt(dim), size=dim)
    return v


def bind(a: Vector, b: Vector) -> Vector:
    """Circular convolution (binding) via FFT."""
    result: Vector = np.real(np.fft.ifft(np.fft.fft(a) * np.fft.fft(b))).astype(np.float64)
    return result


def unbind(key: Vector, composite: Vector) -> Vector:
    """Circular correlation (approximate unbinding) via FFT."""
    result: Vector = np.real(np.fft.ifft(np.conj(np.fft.fft(key)) * np.fft.fft(composite))).astype(np.float64)
    return result


def superpose(vectors: list[Vector]) -> Vector:
    """Superposition (bundling) via vector addition."""
    result: Vector = np.sum(np.array(vectors), axis=0).astype(np.float64)
    return result


def cosine_similarity(a: Vector, b: Vector) -> float:
    """Cosine similarity between two vectors."""
    norm_a: float = float(np.linalg.norm(a))
    norm_b: float = float(np.linalg.norm(b))
    if norm_a < 1e-10 or norm_b < 1e-10:
        return 0.0
    result: float = float(np.dot(a, b) / (norm_a * norm_b))
    return result


# --- Cleanup Memory ---

class CleanupMemory:
    """Nearest-neighbor lookup for recovering approximate vectors."""

    def __init__(self) -> None:
        self.labels: list[str] = []
        self.vectors: list[Vector] = []
        self._matrix: Vector | None = None

    def add(self, label: str, vector: Vector) -> None:
        self.labels.append(label)
        self.vectors.append(vector)
        self._matrix = None  # invalidate cache

    def _build_matrix(self) -> None:
        if self._matrix is None:
            self._matrix = np.array(self.vectors)

    def query(self, probe: Vector, top_k: int = 10) -> list[tuple[str, float]]:
        """Return top-k nearest neighbors by cosine similarity."""
        if not self.vectors:
            return []
        self._build_matrix()
        assert self._matrix is not None

        # Batch cosine similarity
        norms: Vector = np.linalg.norm(self._matrix, axis=1)
        probe_norm: float = float(np.linalg.norm(probe))
        if probe_norm < 1e-10:
            return []

        similarities: Vector = (self._matrix @ probe) / (norms * probe_norm + 1e-10)

        # Top-k
        k: int = min(top_k, len(self.labels))
        top_indices: NDArray[np.intp] = np.argpartition(similarities, -k)[-k:]
        top_indices = top_indices[np.argsort(similarities[top_indices])[::-1]]

        results: list[tuple[str, float]] = []
        for idx in top_indices:
            results.append((self.labels[int(idx)], float(similarities[int(idx)])))
        return results

    def size(self) -> int:
        return len(self.labels)


# --- Edge Loading ---

class Edge(NamedTuple):
    source: str
    target: str
    edge_type: str
    weight: float


def load_edges(extracted_dir: Path, repo_name: str, min_cochange_weight: int = 3) -> list[Edge]:
    """Load all file-to-file edges from extraction results."""
    edges: list[Edge] = []

    # Git co-change (filtered by weight)
    git_path: Path = extracted_dir / "git_edges" / f"{repo_name}.json"
    if git_path.exists():
        git_data: dict[str, Any] = json.loads(git_path.read_text())
        co_changed: list[dict[str, Any]] = git_data.get("co_changed_edges", [])
        for e in co_changed:
            w: int = e.get("weight", 1)
            if w >= min_cochange_weight:
                edges.append(Edge(
                    source=e["source"],
                    target=e["target"],
                    edge_type="CO_CHANGED",
                    weight=float(w),
                ))

    # Imports
    imp_path: Path = extracted_dir / "import_edges" / f"{repo_name}.json"
    if imp_path.exists():
        imp_data: dict[str, Any] = json.loads(imp_path.read_text())
        imp_edges: list[dict[str, Any]] = imp_data.get("edges", [])
        for e in imp_edges:
            edges.append(Edge(
                source=e["source"],
                target=e["target"],
                edge_type="IMPORTS",
                weight=1.0,
            ))

    # Structural (file-to-file only)
    str_path: Path = extracted_dir / "structural_edges" / f"{repo_name}.json"
    if str_path.exists():
        str_data: dict[str, Any] = json.loads(str_path.read_text())
        str_edges: list[dict[str, Any]] = str_data.get("edges", [])
        for e in str_edges:
            s: str = e.get("source", "")
            t: str = e.get("target", "")
            if ":" not in s and ":" not in t:
                edges.append(Edge(
                    source=s,
                    target=t,
                    edge_type=e.get("type", "STRUCTURAL"),
                    weight=1.0,
                ))

    return edges


# --- Subgraph Partitioning ---

def partition_edges(edges: list[Edge], max_per_partition: int) -> list[list[Edge]]:
    """Partition edges into subgraphs that fit within HRR capacity.

    Strategy: partition by edge type first (natural subgraphs), then split
    large types by connected components or arbitrary chunks.
    """
    by_type: dict[str, list[Edge]] = defaultdict(list)
    for e in edges:
        by_type[e.edge_type].append(e)

    partitions: list[list[Edge]] = []
    for _edge_type, type_edges in sorted(by_type.items()):
        if len(type_edges) <= max_per_partition:
            partitions.append(type_edges)
        else:
            # Split into chunks
            for i in range(0, len(type_edges), max_per_partition):
                chunk: list[Edge] = type_edges[i:i + max_per_partition]
                partitions.append(chunk)

    return partitions


# --- HRR Graph Encoding ---

class HRRGraph:
    """HRR-encoded graph with typed edge traversal."""

    def __init__(self, dim: int, seed: int = 42) -> None:
        self.dim: int = dim
        self.capacity: int = dim // 9  # reliable retrieval threshold
        self.rng: np.random.Generator = np.random.default_rng(seed)

        self.node_vectors: dict[str, Vector] = {}
        self.edge_type_vectors: dict[str, Vector] = {}
        self.cleanup: CleanupMemory = CleanupMemory()

        # Superpositions (one per partition)
        self.partitions: list[dict[str, Any]] = []

        # Partition routing index: node_id -> set of partition indices
        self.node_to_partitions: dict[str, set[int]] = defaultdict(set)

        # Routing mode: "all" queries every partition, "routed" queries only relevant ones
        self.routing: str = "routed"

    def _get_node_vector(self, node_id: str) -> Vector:
        """Get or create a random vector for a node."""
        if node_id not in self.node_vectors:
            v: Vector = random_vector(self.dim, self.rng)
            self.node_vectors[node_id] = v
            self.cleanup.add(node_id, v)
        return self.node_vectors[node_id]

    def _get_edge_type_vector(self, edge_type: str) -> Vector:
        """Get or create a random vector for an edge type."""
        if edge_type not in self.edge_type_vectors:
            self.edge_type_vectors[edge_type] = random_vector(self.dim, self.rng)
        return self.edge_type_vectors[edge_type]

    def encode(self, edges: list[Edge]) -> None:
        """Encode all edges into HRR superpositions."""
        max_per_partition: int = self.capacity
        partitions: list[list[Edge]] = partition_edges(edges, max_per_partition)

        for part_edges in partitions:
            if not part_edges:
                continue

            # Encode each edge as bind(source, edge_type, target)
            bound_triples: list[Vector] = []
            edge_types_in_partition: Counter[str] = Counter()

            for e in part_edges:
                src_vec: Vector = self._get_node_vector(e.source)
                tgt_vec: Vector = self._get_node_vector(e.target)
                etype_vec: Vector = self._get_edge_type_vector(e.edge_type)

                triple: Vector = bind(bind(src_vec, etype_vec), tgt_vec)
                bound_triples.append(triple)
                edge_types_in_partition[e.edge_type] += 1

            # Superpose into single vector
            S: Vector = superpose(bound_triples)

            partition_idx: int = len(self.partitions)

            # Build routing index: which nodes appear in this partition
            nodes_in_partition: set[str] = set()
            for e in part_edges:
                nodes_in_partition.add(e.source)
                nodes_in_partition.add(e.target)
                self.node_to_partitions[e.source].add(partition_idx)
                self.node_to_partitions[e.target].add(partition_idx)

            self.partitions.append({
                "superposition": S,
                "edge_count": len(part_edges),
                "edge_types": dict(edge_types_in_partition),
                "capacity_usage": round(len(part_edges) / self.capacity, 3),
                "nodes": nodes_in_partition,
            })

    def _get_relevant_partitions(self, node_id: str) -> list[int]:
        """Get partition indices relevant to a node query."""
        if self.routing == "all" or node_id not in self.node_to_partitions:
            return list(range(len(self.partitions)))
        return sorted(self.node_to_partitions[node_id])

    def query_forward(self, source: str, edge_type: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Single-hop forward query: 'What does source connect to via edge_type?'"""
        if source not in self.node_vectors:
            return []
        if edge_type not in self.edge_type_vectors:
            return []

        src_vec: Vector = self.node_vectors[source]
        etype_vec: Vector = self.edge_type_vectors[edge_type]
        query_vec: Vector = bind(src_vec, etype_vec)

        # Query only relevant partitions (routing)
        relevant_indices: list[int] = self._get_relevant_partitions(source)
        all_results: dict[str, float] = {}
        for idx in relevant_indices:
            partition: dict[str, Any] = self.partitions[idx]
            S: Vector = partition["superposition"]
            result_vec: Vector = unbind(query_vec, S)
            matches: list[tuple[str, float]] = self.cleanup.query(result_vec, top_k=top_k)
            for label, sim in matches:
                if label != source:  # exclude self
                    if label not in all_results or sim > all_results[label]:
                        all_results[label] = sim

        # Sort by similarity
        sorted_results: list[tuple[str, float]] = sorted(all_results.items(), key=lambda x: x[1], reverse=True)
        return sorted_results[:top_k]

    def query_reverse(self, target: str, edge_type: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Single-hop reverse query: 'What connects to target via edge_type?'"""
        if target not in self.node_vectors:
            return []
        if edge_type not in self.edge_type_vectors:
            return []

        tgt_vec: Vector = self.node_vectors[target]
        etype_vec: Vector = self.edge_type_vectors[edge_type]
        query_vec: Vector = bind(tgt_vec, etype_vec)

        relevant_indices: list[int] = self._get_relevant_partitions(target)
        all_results: dict[str, float] = {}
        for idx in relevant_indices:
            partition: dict[str, Any] = self.partitions[idx]
            S: Vector = partition["superposition"]
            result_vec: Vector = unbind(query_vec, S)
            matches: list[tuple[str, float]] = self.cleanup.query(result_vec, top_k=top_k)
            for label, sim in matches:
                if label != target:
                    if label not in all_results or sim > all_results[label]:
                        all_results[label] = sim

        sorted_results: list[tuple[str, float]] = sorted(all_results.items(), key=lambda x: x[1], reverse=True)
        return sorted_results[:top_k]

    def summary(self) -> dict[str, Any]:
        """Return encoding summary."""
        # Routing stats
        partitions_per_node: list[int] = [len(v) for v in self.node_to_partitions.values()]
        avg_partitions: float = sum(partitions_per_node) / max(len(partitions_per_node), 1)
        max_partitions: int = max(partitions_per_node) if partitions_per_node else 0

        return {
            "dim": self.dim,
            "capacity_per_partition": self.capacity,
            "total_nodes": len(self.node_vectors),
            "edge_types": list(self.edge_type_vectors.keys()),
            "num_partitions": len(self.partitions),
            "routing": self.routing,
            "avg_partitions_per_node": round(avg_partitions, 1),
            "max_partitions_per_node": max_partitions,
            "partitions": [
                {
                    "edge_count": p["edge_count"],
                    "edge_types": p["edge_types"],
                    "capacity_usage": p["capacity_usage"],
                    "node_count": len(p["nodes"]),
                }
                for p in self.partitions
            ],
        }


# --- Evaluation ---

class RetrievalResult(NamedTuple):
    edge_type: str
    source: str
    ground_truth_targets: list[str]
    retrieved: list[tuple[str, float]]
    recall_at_5: float
    recall_at_10: float
    precision_at_5: float
    precision_at_10: float


def evaluate_retrieval(
    graph: HRRGraph,
    edges: list[Edge],
    num_queries: int = 50,
    seed: int = 123,
) -> list[RetrievalResult]:
    """Evaluate HRR retrieval against ground truth edges."""
    rng: np.random.Generator = np.random.default_rng(seed)

    # Build ground truth: source + edge_type -> set of targets
    ground_truth: dict[tuple[str, str], set[str]] = defaultdict(set)
    for e in edges:
        ground_truth[(e.source, e.edge_type)].add(e.target)

    # Select random queries (source, edge_type pairs with known targets)
    query_keys: list[tuple[str, str]] = [k for k, v in ground_truth.items() if len(v) >= 1]
    if len(query_keys) > num_queries:
        indices: NDArray[np.intp] = rng.choice(len(query_keys), size=num_queries, replace=False)
        query_keys = [query_keys[int(i)] for i in indices]

    results: list[RetrievalResult] = []
    for source, edge_type in query_keys:
        targets: set[str] = ground_truth[(source, edge_type)]
        retrieved: list[tuple[str, float]] = graph.query_forward(source, edge_type, top_k=10)

        retrieved_ids_5: set[str] = {r[0] for r in retrieved[:5]}
        retrieved_ids_10: set[str] = {r[0] for r in retrieved[:10]}

        hits_5: int = len(targets & retrieved_ids_5)
        hits_10: int = len(targets & retrieved_ids_10)

        r_at_5: float = hits_5 / len(targets) if targets else 0.0
        r_at_10: float = hits_10 / len(targets) if targets else 0.0
        p_at_5: float = hits_5 / min(5, len(retrieved)) if retrieved else 0.0
        p_at_10: float = hits_10 / min(10, len(retrieved)) if retrieved else 0.0

        results.append(RetrievalResult(
            edge_type=edge_type,
            source=source,
            ground_truth_targets=sorted(targets),
            retrieved=retrieved,
            recall_at_5=round(r_at_5, 4),
            recall_at_10=round(r_at_10, 4),
            precision_at_5=round(p_at_5, 4),
            precision_at_10=round(p_at_10, 4),
        ))

    return results


def main() -> None:
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} /path/to/extracted_dir <repo_name> [--dim N] [--output path]")
        sys.exit(1)

    extracted_dir: Path = Path(sys.argv[1])
    repo_name: str = sys.argv[2]
    dim: int = 2048
    output_path: Path | None = None
    routing: str = "routed"

    args: list[str] = sys.argv[3:]
    i: int = 0
    while i < len(args):
        if args[i] == "--dim" and i + 1 < len(args):
            dim = int(args[i + 1])
            i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            output_path = Path(args[i + 1])
            i += 2
        elif args[i] == "--routing" and i + 1 < len(args):
            routing = args[i + 1]
            i += 2
        else:
            i += 1

    if output_path is None:
        output_dir: Path = extracted_dir / "hrr"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / f"{repo_name}.json"

    print(f"[encode] {repo_name} DIM={dim} routing={routing}", file=sys.stderr)

    # Load edges
    edges: list[Edge] = load_edges(extracted_dir, repo_name)
    print(f"  loaded {len(edges)} edges", file=sys.stderr)

    edge_type_counts: Counter[str] = Counter(e.edge_type for e in edges)
    for etype, count in edge_type_counts.most_common():
        print(f"    {etype}: {count}", file=sys.stderr)

    if not edges:
        print("  no edges to encode", file=sys.stderr)
        return

    # Encode
    graph: HRRGraph = HRRGraph(dim=dim)
    graph.routing = routing
    graph.encode(edges)

    summary: dict[str, Any] = graph.summary()
    print(f"  encoded: {summary['total_nodes']} nodes, {summary['num_partitions']} partitions", file=sys.stderr)
    print(f"  routing: {routing}, avg {summary['avg_partitions_per_node']} partitions/node, max {summary['max_partitions_per_node']}", file=sys.stderr)

    # Evaluate
    print(f"\n  evaluating retrieval (50 random queries)...", file=sys.stderr)
    results: list[RetrievalResult] = evaluate_retrieval(graph, edges, num_queries=50)

    # Aggregate by edge type
    by_type: dict[str, list[RetrievalResult]] = defaultdict(list)
    for r in results:
        by_type[r.edge_type].append(r)

    print(f"\n  {'Edge Type':<25} {'Queries':>8} {'R@5':>6} {'R@10':>6} {'P@5':>6} {'P@10':>6}", file=sys.stderr)
    print(f"  {'-'*70}", file=sys.stderr)

    type_summaries: dict[str, dict[str, float]] = {}
    for etype, type_results in sorted(by_type.items()):
        n: int = len(type_results)
        avg_r5: float = sum(r.recall_at_5 for r in type_results) / n
        avg_r10: float = sum(r.recall_at_10 for r in type_results) / n
        avg_p5: float = sum(r.precision_at_5 for r in type_results) / n
        avg_p10: float = sum(r.precision_at_10 for r in type_results) / n
        print(f"  {etype:<25} {n:>8} {avg_r5:>6.3f} {avg_r10:>6.3f} {avg_p5:>6.3f} {avg_p10:>6.3f}", file=sys.stderr)
        type_summaries[etype] = {
            "queries": n,
            "recall_at_5": round(avg_r5, 4),
            "recall_at_10": round(avg_r10, 4),
            "precision_at_5": round(avg_p5, 4),
            "precision_at_10": round(avg_p10, 4),
        }

    # Overall
    total_queries: int = len(results)
    overall_r5: float = 0.0
    overall_r10: float = 0.0
    overall_p5: float = 0.0
    overall_p10: float = 0.0
    if total_queries > 0:
        overall_r5 = sum(r.recall_at_5 for r in results) / total_queries
        overall_r10 = sum(r.recall_at_10 for r in results) / total_queries
        overall_p5 = sum(r.precision_at_5 for r in results) / total_queries
        overall_p10 = sum(r.precision_at_10 for r in results) / total_queries
        print(f"  {'OVERALL':<25} {total_queries:>8} {overall_r5:>6.3f} {overall_r10:>6.3f} {overall_p5:>6.3f} {overall_p10:>6.3f}", file=sys.stderr)

    # Write results
    output_data: dict[str, Any] = {
        "repo": repo_name,
        "dim": dim,
        "encoding_summary": summary,
        "retrieval_by_type": type_summaries,
        "retrieval_overall": {
            "queries": total_queries,
            "recall_at_5": round(overall_r5, 4),
            "recall_at_10": round(overall_r10, 4),
            "precision_at_5": round(overall_p5, 4),
            "precision_at_10": round(overall_p10, 4),
        },
        "per_query_results": [
            {
                "edge_type": r.edge_type,
                "source": r.source,
                "ground_truth": r.ground_truth_targets,
                "retrieved_top10": [(label, round(sim, 4)) for label, sim in r.retrieved],
                "recall_at_5": r.recall_at_5,
                "recall_at_10": r.recall_at_10,
            }
            for r in results
        ],
    }

    output_path.write_text(json.dumps(output_data, indent=2))
    print(f"\n  written to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
