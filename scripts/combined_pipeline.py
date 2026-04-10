"""
combined_pipeline.py -- C1: End-to-end retrieval pipeline (FTS5 + HRR + BFS).

Tests the full architecture:
  1. FTS5: keyword search on node content
  2. HRR: typed traversal for vocabulary-bridge queries
  3. BFS: expand from FTS5/HRR hits to related nodes
  4. Merge + rank

Compares: combined recall vs each method alone vs pairs.

Usage:
    PYTHONPATH=scripts python scripts/combined_pipeline.py /path/to/repo /path/to/extracted_dir

Reads: extracted/{git_edges,import_edges,structural_edges,sentences}/<repo>.json + repo files
Writes: extracted/combined/<repo>.json
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from hrr_encoder import Edge, HRRGraph, load_edges


SKIP_DIRS: set[str] = {
    ".git", "node_modules", "target", ".venv", "venv", "__pycache__",
    ".mypy_cache", ".ruff_cache", "dist", "build", ".tox", "vendor",
}

STOP_WORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must", "to", "of",
    "in", "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "and", "but", "or", "if", "not", "no", "this", "that", "it", "its",
}


# --- FTS5 ---

class FTS5Index:
    """SQLite FTS5 index for file content retrieval."""

    def __init__(self) -> None:
        self.db: sqlite3.Connection = sqlite3.connect(":memory:")
        self.db.execute("CREATE VIRTUAL TABLE fts USING fts5(path, content, tokenize='porter')")
        self._count: int = 0

    def add(self, path: str, content: str) -> None:
        self.db.execute("INSERT INTO fts VALUES (?, ?)", (path, content))
        self._count += 1

    def commit(self) -> None:
        self.db.commit()

    def search(self, query: str, limit: int = 10) -> list[str]:
        """Return file paths matching query."""
        terms: list[str] = [
            t for t in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", query)
            if t.lower() not in STOP_WORDS and len(t) > 2
        ]
        if not terms:
            return []
        fts_query: str = " OR ".join(terms[:20])
        try:
            rows: list[tuple[str]] = self.db.execute(
                "SELECT path FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, limit),
            ).fetchall()
            return [r[0] for r in rows]
        except sqlite3.OperationalError:
            return []

    def size(self) -> int:
        return self._count


def build_fts5(repo_path: Path) -> FTS5Index:
    """Build FTS5 index from repo files."""
    index: FTS5Index = FTS5Index()
    text_exts: set[str] = {
        ".py", ".rs", ".go", ".ts", ".tsx", ".js", ".jsx",
        ".c", ".h", ".cpp", ".cc", ".hpp", ".md", ".txt",
        ".yml", ".yaml", ".toml", ".json", ".sh", ".sql",
    }
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath: Path = Path(root) / f
            if fpath.suffix.lower() not in text_exts:
                continue
            try:
                content: str = fpath.read_text(errors="ignore")[:8192]
                rel: str = str(fpath.relative_to(repo_path))
                index.add(rel, content)
            except OSError:
                continue
    index.commit()
    return index


# --- BFS ---

class GraphAdjacency:
    """Simple adjacency list for BFS traversal."""

    def __init__(self) -> None:
        self.adj: dict[str, set[str]] = defaultdict(set)
        self.typed_adj: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    def add_edge(self, source: str, target: str, edge_type: str) -> None:
        self.adj[source].add(target)
        self.adj[target].add(source)
        self.typed_adj[source][edge_type].add(target)
        self.typed_adj[target][edge_type].add(source)

    def bfs(self, start_nodes: set[str], max_depth: int = 2, max_results: int = 20) -> set[str]:
        """BFS from start nodes, return all reachable within max_depth."""
        visited: set[str] = set(start_nodes)
        frontier: set[str] = set(start_nodes)

        for _depth in range(max_depth):
            next_frontier: set[str] = set()
            for node in frontier:
                for neighbor in self.adj.get(node, set()):
                    if neighbor not in visited:
                        next_frontier.add(neighbor)
                        visited.add(neighbor)
                        if len(visited) >= max_results + len(start_nodes):
                            return visited
            frontier = next_frontier
            if not frontier:
                break

        return visited

    def neighbors(self, node: str) -> set[str]:
        return self.adj.get(node, set())


def build_adjacency(edges: list[Edge]) -> GraphAdjacency:
    """Build adjacency from edge list."""
    graph: GraphAdjacency = GraphAdjacency()
    for e in edges:
        graph.add_edge(e.source, e.target, e.edge_type)
    return graph


# --- Combined Pipeline ---

class CombinedPipeline:
    """FTS5 + HRR + BFS combined retrieval."""

    def __init__(
        self,
        fts5: FTS5Index,
        hrr: HRRGraph,
        bfs_graph: GraphAdjacency,
    ) -> None:
        self.fts5: FTS5Index = fts5
        self.hrr: HRRGraph = hrr
        self.bfs_graph: GraphAdjacency = bfs_graph

    def retrieve_fts5_only(self, query_content: str, limit: int = 10) -> set[str]:
        """FTS5 keyword search."""
        return set(self.fts5.search(query_content, limit=limit))

    def retrieve_hrr_only(self, source: str, edge_type: str, limit: int = 10) -> set[str]:
        """HRR typed traversal."""
        results: list[tuple[str, float]] = self.hrr.query_forward(source, edge_type, top_k=limit)
        return {r[0] for r in results}

    def retrieve_bfs_only(self, start_nodes: set[str], max_depth: int = 2) -> set[str]:
        """BFS expansion from given nodes."""
        return self.bfs_graph.bfs(start_nodes, max_depth=max_depth) - start_nodes

    def retrieve_combined(
        self,
        query_content: str,
        source: str | None = None,
        edge_type: str | None = None,
        fts_limit: int = 10,
        hrr_limit: int = 10,
        bfs_depth: int = 1,
    ) -> dict[str, set[str]]:
        """Full pipeline: FTS5 + HRR + BFS."""
        # Step 1: FTS5
        fts_hits: set[str] = self.retrieve_fts5_only(query_content, limit=fts_limit)

        # Step 2: HRR (if source and edge_type provided)
        hrr_hits: set[str] = set()
        if source and edge_type:
            hrr_hits = self.retrieve_hrr_only(source, edge_type, limit=hrr_limit)

        # Step 3: BFS from union of FTS5 + HRR hits
        seed_nodes: set[str] = fts_hits | hrr_hits
        bfs_hits: set[str] = set()
        if seed_nodes and bfs_depth > 0:
            bfs_hits = self.retrieve_bfs_only(seed_nodes, max_depth=bfs_depth)

        combined: set[str] = fts_hits | hrr_hits | bfs_hits

        return {
            "fts5": fts_hits,
            "hrr": hrr_hits,
            "bfs_expansion": bfs_hits,
            "combined": combined,
        }


# --- Evaluation ---

def evaluate_combined(
    pipeline: CombinedPipeline,
    edges: list[Edge],
    repo_path: Path,
    num_queries: int = 50,
    seed: int = 123,
) -> dict[str, Any]:
    """Evaluate combined pipeline against ground truth edges."""
    rng: np.random.Generator = np.random.default_rng(seed)

    # Build ground truth
    gt: dict[tuple[str, str], set[str]] = defaultdict(set)
    for e in edges:
        gt[(e.source, e.edge_type)].add(e.target)

    query_keys: list[tuple[str, str]] = [k for k, v in gt.items() if len(v) >= 1]
    if len(query_keys) > num_queries:
        indices: NDArray[np.intp] = rng.choice(len(query_keys), size=num_queries, replace=False)
        query_keys = [query_keys[int(i)] for i in indices]

    # Per-method hit tracking
    method_hits: dict[str, int] = {"fts5": 0, "hrr": 0, "bfs": 0, "combined": 0}
    method_only: dict[str, int] = {"fts5_only": 0, "hrr_only": 0, "bfs_only": 0}
    total_targets: int = 0
    neither_count: int = 0

    for source, edge_type in query_keys:
        targets: set[str] = gt[(source, edge_type)]
        total_targets += len(targets)

        # Get source file content for FTS5 query
        source_content: str = ""
        source_path: Path = repo_path / source
        if source_path.exists():
            try:
                source_content = source_path.read_text(errors="ignore")[:2000]
            except OSError:
                pass

        # Run combined pipeline
        results: dict[str, set[str]] = pipeline.retrieve_combined(
            query_content=source_content,
            source=source,
            edge_type=edge_type,
            bfs_depth=1,
        )

        fts_found: set[str] = results["fts5"] & targets
        hrr_found: set[str] = results["hrr"] & targets
        bfs_found: set[str] = results["bfs_expansion"] & targets
        combined_found: set[str] = results["combined"] & targets

        method_hits["fts5"] += len(fts_found)
        method_hits["hrr"] += len(hrr_found)
        method_hits["bfs"] += len(bfs_found)
        method_hits["combined"] += len(combined_found)

        # Unique contributions
        for t in targets:
            in_fts: bool = t in results["fts5"]
            in_hrr: bool = t in results["hrr"]
            in_bfs: bool = t in results["bfs_expansion"]

            if in_fts and not in_hrr and not in_bfs:
                method_only["fts5_only"] += 1
            if in_hrr and not in_fts and not in_bfs:
                method_only["hrr_only"] += 1
            if in_bfs and not in_fts and not in_hrr:
                method_only["bfs_only"] += 1
            if not in_fts and not in_hrr and not in_bfs:
                neither_count += 1

    # Compute recalls
    recalls: dict[str, float] = {}
    for method, hits in method_hits.items():
        recalls[f"{method}_recall"] = round(hits / max(total_targets, 1), 4)

    return {
        "queries": len(query_keys),
        "total_targets": total_targets,
        "recalls": recalls,
        "unique_contributions": method_only,
        "neither_found": neither_count,
        "neither_pct": round(neither_count / max(total_targets, 1) * 100, 1),
    }


def main() -> None:
    if len(sys.argv) < 3:
        print(f"Usage: PYTHONPATH=scripts {sys.argv[0]} /path/to/repo /path/to/extracted_dir")
        sys.exit(1)

    repo_path: Path = Path(sys.argv[1]).resolve()
    extracted_dir: Path = Path(sys.argv[2])
    repo_name: str = repo_path.name
    dim: int = 2048

    print(f"[combined] {repo_name}", file=sys.stderr)

    # Load edges
    edges: list[Edge] = load_edges(extracted_dir, repo_name)
    print(f"  {len(edges)} edges", file=sys.stderr)

    if not edges:
        print("  no edges", file=sys.stderr)
        return

    # Build FTS5
    print(f"  building FTS5...", file=sys.stderr)
    fts5: FTS5Index = build_fts5(repo_path)
    print(f"  FTS5: {fts5.size()} files indexed", file=sys.stderr)

    # Build HRR
    print(f"  building HRR (DIM={dim})...", file=sys.stderr)
    hrr: HRRGraph = HRRGraph(dim=dim)
    hrr.routing = "routed"
    hrr.encode(edges)
    print(f"  HRR: {len(hrr.node_vectors)} nodes, {len(hrr.partitions)} partitions", file=sys.stderr)

    # Build BFS adjacency
    print(f"  building BFS adjacency...", file=sys.stderr)
    bfs_graph: GraphAdjacency = build_adjacency(edges)

    # Combined pipeline
    pipeline: CombinedPipeline = CombinedPipeline(fts5, hrr, bfs_graph)

    # Evaluate
    print(f"\n  evaluating (50 queries)...", file=sys.stderr)
    results: dict[str, Any] = evaluate_combined(pipeline, edges, repo_path)

    print(f"\n  Results:", file=sys.stderr)
    print(f"  {'Method':<15} {'Recall':>8}", file=sys.stderr)
    print(f"  {'-'*25}", file=sys.stderr)
    for method, recall in sorted(results["recalls"].items()):
        print(f"  {method:<15} {recall:>8.3f}", file=sys.stderr)

    print(f"\n  Unique contributions:", file=sys.stderr)
    for method, count in sorted(results["unique_contributions"].items()):
        print(f"    {method}: {count}", file=sys.stderr)
    print(f"    neither: {results['neither_found']} ({results['neither_pct']}%)", file=sys.stderr)

    # Write
    output_dir: Path = extracted_dir / "combined"
    output_dir.mkdir(exist_ok=True)
    output_path: Path = output_dir / f"{repo_name}.json"
    output_path.write_text(json.dumps(results, indent=2))
    print(f"\n  written to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
