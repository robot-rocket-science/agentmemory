"""
hrr_sentence_encoder.py -- S2: HRR encoding of sentence-level graphs.

Takes sentence decomposition output and encodes in HRR with file-local
partitioning: each file's sentences are one partition, cross-file edges
are separate partitions.

Usage:
    python scripts/hrr_sentence_encoder.py /path/to/extracted_dir <repo_name> [--dim 2048]

Reads: extracted/sentences/<repo>.json
Writes: extracted/hrr_sentences/<repo>.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

# Reuse core HRR ops from hrr_encoder
from hrr_encoder import (
    CleanupMemory,
    Vector,
    bind,
    random_vector,
    superpose,
    unbind,
)


class SentenceHRRGraph:
    """HRR-encoded sentence graph with file-local partitioning."""

    def __init__(self, dim: int, seed: int = 42) -> None:
        self.dim: int = dim
        self.capacity: int = dim // 9
        self.rng: np.random.Generator = np.random.default_rng(seed)

        self.node_vectors: dict[str, Vector] = {}
        self.edge_type_vectors: dict[str, Vector] = {}
        self.cleanup: CleanupMemory = CleanupMemory()

        self.partitions: list[dict[str, Any]] = []
        self.node_to_partitions: dict[str, set[int]] = defaultdict(set)

    def _get_node_vector(self, node_id: str) -> Vector:
        if node_id not in self.node_vectors:
            v: Vector = random_vector(self.dim, self.rng)
            self.node_vectors[node_id] = v
            self.cleanup.add(node_id, v)
        return self.node_vectors[node_id]

    def _get_edge_type_vector(self, edge_type: str) -> Vector:
        if edge_type not in self.edge_type_vectors:
            self.edge_type_vectors[edge_type] = random_vector(self.dim, self.rng)
        return self.edge_type_vectors[edge_type]

    def _encode_partition(self, edges: list[tuple[str, str, str]], label: str) -> None:
        """Encode a set of edges into one partition."""
        if not edges:
            return

        bound_triples: list[Vector] = []
        edge_types: Counter[str] = Counter()
        nodes_in_partition: set[str] = set()

        for src, tgt, etype in edges:
            src_vec: Vector = self._get_node_vector(src)
            tgt_vec: Vector = self._get_node_vector(tgt)
            etype_vec: Vector = self._get_edge_type_vector(etype)
            triple: Vector = bind(bind(src_vec, etype_vec), tgt_vec)
            bound_triples.append(triple)
            edge_types[etype] += 1
            nodes_in_partition.add(src)
            nodes_in_partition.add(tgt)

        S: Vector = superpose(bound_triples)
        partition_idx: int = len(self.partitions)

        for node_id in nodes_in_partition:
            self.node_to_partitions[node_id].add(partition_idx)

        self.partitions.append({
            "superposition": S,
            "edge_count": len(edges),
            "edge_types": dict(edge_types),
            "capacity_usage": round(len(edges) / self.capacity, 3),
            "label": label,
            "nodes": nodes_in_partition,
        })

    def encode_sentence_graph(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> None:
        """Encode sentence graph with file-local partitioning.

        Strategy:
        1. Group within-file edges by file -> one partition per file (if <= capacity)
        2. Cross-file edges -> separate partitions, chunked at capacity
        """
        # Classify edges as within-file or cross-file
        node_file: dict[str, str] = {}
        for n in nodes:
            node_file[n["id"]] = n.get("file", "")

        within_file: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        cross_file: list[tuple[str, str, str]] = []

        for e in edges:
            src: str = e["source"]
            tgt: str = e["target"]
            etype: str = e["type"]
            src_file: str = node_file.get(src, "")
            tgt_file: str = node_file.get(tgt, "")

            if src_file and tgt_file and src_file == tgt_file:
                within_file[src_file].append((src, tgt, etype))
            else:
                cross_file.append((src, tgt, etype))

        # Encode within-file partitions
        for file_path, file_edges in sorted(within_file.items()):
            if len(file_edges) <= self.capacity:
                self._encode_partition(file_edges, f"file:{file_path}")
            else:
                # Split large files into chunks
                for i in range(0, len(file_edges), self.capacity):
                    chunk: list[tuple[str, str, str]] = file_edges[i:i + self.capacity]
                    self._encode_partition(chunk, f"file:{file_path}:chunk{i // self.capacity}")

        # Encode cross-file edges
        if cross_file:
            # Group by edge type for better selectivity
            by_type: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
            for src, tgt, etype in cross_file:
                by_type[etype].append((src, tgt, etype))

            for etype, type_edges in sorted(by_type.items()):
                if len(type_edges) <= self.capacity:
                    self._encode_partition(type_edges, f"cross:{etype}")
                else:
                    for i in range(0, len(type_edges), self.capacity):
                        chunk = type_edges[i:i + self.capacity]
                        self._encode_partition(chunk, f"cross:{etype}:chunk{i // self.capacity}")

    def query_forward(self, source: str, edge_type: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Single-hop forward query with partition routing."""
        if source not in self.node_vectors or edge_type not in self.edge_type_vectors:
            return []

        src_vec: Vector = self.node_vectors[source]
        etype_vec: Vector = self.edge_type_vectors[edge_type]
        query_vec: Vector = bind(src_vec, etype_vec)

        relevant: list[int] = sorted(self.node_to_partitions.get(source, set()))
        if not relevant:
            relevant = list(range(len(self.partitions)))

        all_results: dict[str, float] = {}
        for idx in relevant:
            S: Vector = self.partitions[idx]["superposition"]
            result_vec: Vector = unbind(query_vec, S)
            matches: list[tuple[str, float]] = self.cleanup.query(result_vec, top_k=top_k)
            for label, sim in matches:
                if label != source:
                    if label not in all_results or sim > all_results[label]:
                        all_results[label] = sim

        sorted_results: list[tuple[str, float]] = sorted(
            all_results.items(), key=lambda x: x[1], reverse=True
        )
        return sorted_results[:top_k]

    def summary(self) -> dict[str, Any]:
        partitions_per_node: list[int] = [len(v) for v in self.node_to_partitions.values()]
        avg_ppn: float = sum(partitions_per_node) / max(len(partitions_per_node), 1)
        max_ppn: int = max(partitions_per_node) if partitions_per_node else 0

        within_count: int = sum(1 for p in self.partitions if p["label"].startswith("file:"))
        cross_count: int = sum(1 for p in self.partitions if p["label"].startswith("cross:"))

        return {
            "dim": self.dim,
            "capacity": self.capacity,
            "total_nodes": len(self.node_vectors),
            "num_partitions": len(self.partitions),
            "within_file_partitions": within_count,
            "cross_file_partitions": cross_count,
            "avg_partitions_per_node": round(avg_ppn, 1),
            "max_partitions_per_node": max_ppn,
            "edge_types": list(self.edge_type_vectors.keys()),
        }


# --- Evaluation ---

def evaluate_sentence_retrieval(
    graph: SentenceHRRGraph,
    edges: list[dict[str, Any]],
    num_queries: int = 50,
    seed: int = 123,
) -> list[dict[str, Any]]:
    """Evaluate HRR retrieval on sentence graph."""
    rng: np.random.Generator = np.random.default_rng(seed)

    # Build ground truth
    gt: dict[tuple[str, str], set[str]] = defaultdict(set)
    for e in edges:
        gt[(e["source"], e["type"])].add(e["target"])

    query_keys: list[tuple[str, str]] = [k for k, v in gt.items() if len(v) >= 1]
    if len(query_keys) > num_queries:
        indices: NDArray[np.intp] = rng.choice(len(query_keys), size=num_queries, replace=False)
        query_keys = [query_keys[int(i)] for i in indices]

    results: list[dict[str, Any]] = []
    for source, edge_type in query_keys:
        targets: set[str] = gt[(source, edge_type)]
        retrieved: list[tuple[str, float]] = graph.query_forward(source, edge_type, top_k=10)

        retrieved_5: set[str] = {r[0] for r in retrieved[:5]}
        retrieved_10: set[str] = {r[0] for r in retrieved[:10]}

        hits_5: int = len(targets & retrieved_5)
        hits_10: int = len(targets & retrieved_10)

        results.append({
            "edge_type": edge_type,
            "source": source,
            "n_targets": len(targets),
            "recall_at_5": round(hits_5 / len(targets), 4) if targets else 0.0,
            "recall_at_10": round(hits_10 / len(targets), 4) if targets else 0.0,
            "precision_at_5": round(hits_5 / min(5, len(retrieved)), 4) if retrieved else 0.0,
            "precision_at_10": round(hits_10 / min(10, len(retrieved)), 4) if retrieved else 0.0,
        })

    return results


def main() -> None:
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} /path/to/extracted_dir <repo_name> [--dim N]")
        sys.exit(1)

    extracted_dir: Path = Path(sys.argv[1])
    repo_name: str = sys.argv[2]
    dim: int = 2048

    args: list[str] = sys.argv[3:]
    i: int = 0
    while i < len(args):
        if args[i] == "--dim" and i + 1 < len(args):
            dim = int(args[i + 1])
            i += 2
        else:
            i += 1

    # Load sentence graph
    sent_path: Path = extracted_dir / "sentences" / f"{repo_name}.json"
    if not sent_path.exists():
        print(f"No sentence graph found at {sent_path}", file=sys.stderr)
        sys.exit(1)

    sent_data: dict[str, Any] = json.loads(sent_path.read_text())
    nodes: list[dict[str, Any]] = sent_data["nodes"]
    edges: list[dict[str, Any]] = sent_data["edges"]

    print(f"[sentence-hrr] {repo_name} DIM={dim}", file=sys.stderr)
    print(f"  {len(nodes)} sentence nodes, {len(edges)} edges", file=sys.stderr)

    # Encode
    graph: SentenceHRRGraph = SentenceHRRGraph(dim=dim)
    graph.encode_sentence_graph(nodes, edges)

    summary: dict[str, Any] = graph.summary()
    print(f"  encoded: {summary['total_nodes']} nodes, {summary['num_partitions']} partitions "
          f"({summary['within_file_partitions']} within-file, {summary['cross_file_partitions']} cross-file)",
          file=sys.stderr)
    print(f"  routing: avg {summary['avg_partitions_per_node']} partitions/node, max {summary['max_partitions_per_node']}",
          file=sys.stderr)

    # Evaluate
    print(f"\n  evaluating retrieval (50 queries)...", file=sys.stderr)
    results: list[dict[str, Any]] = evaluate_sentence_retrieval(graph, edges)

    # Aggregate by type
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        by_type[r["edge_type"]].append(r)

    print(f"\n  {'Edge Type':<25} {'Queries':>8} {'R@5':>6} {'R@10':>6} {'P@5':>6} {'P@10':>6}", file=sys.stderr)
    print(f"  {'-'*70}", file=sys.stderr)

    type_summaries: dict[str, dict[str, float | int]] = {}
    for etype, type_results in sorted(by_type.items()):
        n: int = len(type_results)
        avg_r5: float = sum(r["recall_at_5"] for r in type_results) / n
        avg_r10: float = sum(r["recall_at_10"] for r in type_results) / n
        avg_p5: float = sum(r["precision_at_5"] for r in type_results) / n
        avg_p10: float = sum(r["precision_at_10"] for r in type_results) / n
        print(f"  {etype:<25} {n:>8} {avg_r5:>6.3f} {avg_r10:>6.3f} {avg_p5:>6.3f} {avg_p10:>6.3f}", file=sys.stderr)
        type_summaries[etype] = {
            "queries": n, "recall_at_5": round(avg_r5, 4), "recall_at_10": round(avg_r10, 4),
            "precision_at_5": round(avg_p5, 4), "precision_at_10": round(avg_p10, 4),
        }

    # Overall
    total_q: int = len(results)
    overall_r5: float = sum(r["recall_at_5"] for r in results) / max(total_q, 1)
    overall_r10: float = sum(r["recall_at_10"] for r in results) / max(total_q, 1)
    overall_p5: float = sum(r["precision_at_5"] for r in results) / max(total_q, 1)
    overall_p10: float = sum(r["precision_at_10"] for r in results) / max(total_q, 1)
    print(f"  {'OVERALL':<25} {total_q:>8} {overall_r5:>6.3f} {overall_r10:>6.3f} {overall_p5:>6.3f} {overall_p10:>6.3f}", file=sys.stderr)

    # Write
    output_dir: Path = extracted_dir / "hrr_sentences"
    output_dir.mkdir(exist_ok=True)
    output_path: Path = output_dir / f"{repo_name}.json"

    output: dict[str, Any] = {
        "repo": repo_name,
        "dim": dim,
        "encoding_summary": summary,
        "retrieval_by_type": type_summaries,
        "retrieval_overall": {
            "queries": total_q,
            "recall_at_5": round(overall_r5, 4),
            "recall_at_10": round(overall_r10, 4),
            "precision_at_5": round(overall_p5, 4),
            "precision_at_10": round(overall_p10, 4),
        },
    }

    output_path.write_text(json.dumps(output, indent=2))
    print(f"\n  written to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
