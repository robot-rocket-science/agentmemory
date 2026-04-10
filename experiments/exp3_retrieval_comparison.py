from __future__ import annotations

"""
Experiment 3: BFS vs FTS5 vs Hybrid Retrieval Quality

Compares three retrieval methods on real alpha-seek graph data:
  A. FTS5 only (BM25 text search)
  B. BFS only (graph traversal with hub damping)
  C. Hybrid (FTS5 seeding + BFS traversal)

The experiment requires human evaluation: the user writes queries and labels
results blind (without knowing which method produced which result).

Verifies: REQ-007 (retrieval precision >= 0.50)
Protocol: EXPERIMENTS.md, Experiment 3
Depends on: Exp 5b (retrieval ranking strategy -- Thompson sampling adopted)
"""

import json
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


ALPHA_SEEK_DB = Path("/Users/thelorax/projects/.gsd/workflows/spikes/"
                     "260406-1-associative-memory-for-gsd-please-explor/"
                     "sandbox/alpha-seek.db")


# --- Data Loading ---

@dataclass
class Node:
    id: str
    content: str
    category: str
    source_type: str
    confidence: float


@dataclass
class Edge:
    from_id: str
    to_id: str
    edge_type: str
    weight: float
    reason: str


def load_graph(db_path: Path) -> tuple[dict[str, Node], dict[str, list[tuple[str, str, float]]]]:
    """Load nodes and adjacency list from alpha-seek database."""
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row

    nodes: dict[str, Node] = {}
    for row in db.execute("SELECT id, content, category, source_type, confidence FROM mem_nodes WHERE superseded_by IS NULL"):
        nodes[row["id"]] = Node(
            id=row["id"],
            content=row["content"],
            category=row["category"] or "",
            source_type=row["source_type"] or "",
            confidence=row["confidence"] or 0.5,
        )

    adj: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for row in db.execute("SELECT from_id, to_id, edge_type, weight FROM mem_edges"):
        adj[row["from_id"]].append((row["to_id"], row["edge_type"], row["weight"] or 1.0))
        adj[row["to_id"]].append((row["from_id"], row["edge_type"], row["weight"] or 1.0))

    db.close()
    print(f"Loaded {len(nodes)} nodes, {sum(len(v) for v in adj.values()) // 2} edges", file=sys.stderr)
    return nodes, dict(adj)


def build_fts_index(nodes: dict[str, Node]) -> sqlite3.Connection:
    """Build an in-memory FTS5 index for text search."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE node_fts USING fts5(id, content, category, tokenize='porter')")
    for node in nodes.values():
        db.execute("INSERT INTO node_fts VALUES (?, ?, ?)",
                   (node.id, node.content, node.category))
    db.commit()
    return db


# --- Retrieval Methods ---

def retrieve_fts(query: str, fts_db: sqlite3.Connection, top_k: int = 15) -> list[tuple[str, float]]:
    """FTS5 BM25 text search. Returns (node_id, score) pairs."""
    # Convert space-separated query to OR query for broader matching
    # FTS5 default is AND (all terms must match), which is too strict
    terms = [t.strip() for t in query.split() if len(t.strip()) > 2]
    if not terms:
        return []
    fts_query = " OR ".join(terms)

    try:
        results = fts_db.execute(
            "SELECT id, rank FROM node_fts WHERE node_fts MATCH ? ORDER BY rank LIMIT ?",
            (fts_query, top_k)
        ).fetchall()
        # FTS5 rank is negative (lower = better), so we negate for sorting
        return [(row[0], -row[1]) for row in results]
    except Exception:
        return []


def retrieve_bfs(
    seed_ids: list[str],
    adj: dict[str, list[tuple[str, str, float]]],
    nodes: dict[str, Node],
    max_hops: int = 2,
    top_k: int = 15,
    hub_damping_threshold: int = 30,
    hub_damping_factor: float = 0.5,
) -> list[tuple[str, float]]:
    """BFS traversal with hub damping. Returns (node_id, score) pairs."""
    visited: dict[str, float] = {}
    queue: list[tuple[str, int, float]] = [(sid, 0, 1.0) for sid in seed_ids if sid in nodes]

    while queue:
        node_id, depth, score = queue.pop(0)

        if node_id in visited:
            visited[node_id] = max(visited[node_id], score)
            continue
        visited[node_id] = score

        if depth >= max_hops:
            continue

        neighbors = adj.get(node_id, [])
        _degree = len(neighbors)

        for neighbor_id, _edge_type, weight in neighbors:
            if neighbor_id not in nodes:
                continue

            # Hub damping
            neighbor_degree = len(adj.get(neighbor_id, []))
            damping = hub_damping_factor if neighbor_degree > hub_damping_threshold else 1.0

            next_score = score * weight * damping * (0.7 ** (depth + 1))
            queue.append((neighbor_id, depth + 1, next_score))

    # Sort by score, return top_k
    ranked: list[tuple[str, float]] = sorted(visited.items(), key=lambda x: x[1], reverse=True)
    return ranked[:top_k]


def retrieve_hybrid(
    query: str,
    fts_db: sqlite3.Connection,
    adj: dict[str, list[tuple[str, str, float]]],
    nodes: dict[str, Node],
    fts_seed_count: int = 5,
    top_k: int = 15,
) -> list[tuple[str, float]]:
    """FTS5 seeding + BFS traversal. Returns (node_id, score) pairs."""
    # Get FTS seeds
    fts_results = retrieve_fts(query, fts_db, top_k=fts_seed_count)
    seed_ids = [nid for nid, _ in fts_results]

    if not seed_ids:
        return retrieve_fts(query, fts_db, top_k=top_k)

    # BFS from seeds
    bfs_results = retrieve_bfs(seed_ids, adj, nodes, top_k=top_k * 2)

    # Combine: FTS score + BFS score (normalized)
    fts_scores = dict(fts_results)
    bfs_scores = dict(bfs_results)

    all_ids = set(fts_scores.keys()) | set(bfs_scores.keys())
    max_fts = max(fts_scores.values()) if fts_scores else 1.0
    max_bfs = max(bfs_scores.values()) if bfs_scores else 1.0

    combined: dict[str, float] = {}
    for nid in all_ids:
        fts_norm = fts_scores.get(nid, 0) / max_fts if max_fts > 0 else 0
        bfs_norm = bfs_scores.get(nid, 0) / max_bfs if max_bfs > 0 else 0
        combined[nid] = 0.5 * fts_norm + 0.5 * bfs_norm

    ranked: list[tuple[str, float]] = sorted(combined.items(), key=lambda x: x[1], reverse=True)
    return ranked[:top_k]


# --- Evaluation Harness ---

def prepare_blind_evaluation(
    query: str,
    query_id: str,
    nodes: dict[str, Node],
    fts_db: sqlite3.Connection,
    adj: dict[str, list[tuple[str, str, float]]],
) -> dict[str, Any]:
    """Run all three methods and prepare a blind evaluation sheet."""
    fts_results = retrieve_fts(query, fts_db, top_k=15)
    bfs_seeds = [nid for nid, _ in retrieve_fts(query, fts_db, top_k=3)]
    bfs_results = retrieve_bfs(bfs_seeds, adj, nodes, top_k=15)
    hybrid_results = retrieve_hybrid(query, fts_db, adj, nodes, top_k=15)

    # Collect all unique results
    all_ids: set[str] = set()
    method_map: dict[str, set[str]] = {}  # node_id -> set of methods that returned it

    for method_name, results in [("fts", fts_results), ("bfs", bfs_results), ("hybrid", hybrid_results)]:
        for nid, _score in results:
            all_ids.add(nid)
            if nid not in method_map:
                method_map[nid] = set()
            method_map[nid].add(method_name)

    # Shuffle for blind evaluation
    shuffled_ids = list(all_ids)
    rng = np.random.default_rng(hash(query_id) % (2**32))
    rng.shuffle(shuffled_ids)

    # Build evaluation sheet (method attribution hidden)
    eval_items: list[dict[str, Any]] = []
    for i, nid in enumerate(shuffled_ids):
        node = nodes.get(nid)
        if not node:
            continue
        eval_items.append({
            "eval_id": f"{query_id}_item_{i:03d}",
            "node_id": nid,  # hidden during eval, revealed after
            "content": node.content,
            "category": node.category,
            "source_type": node.source_type,
            # Relevance label to be filled by human evaluator:
            # "relevant", "partially_relevant", "not_relevant"
            "relevance": None,
        })

    # Store the method attribution separately (for scoring after labeling)
    attribution: dict[str, list[str]] = {
        nid: list(methods) for nid, methods in method_map.items()
    }

    return {
        "query_id": query_id,
        "query": query,
        "n_unique_results": len(all_ids),
        "n_fts": len(fts_results),
        "n_bfs": len(bfs_results),
        "n_hybrid": len(hybrid_results),
        "eval_items": eval_items,
        "_attribution": attribution,  # hidden during eval
    }


# --- Main ---

def main() -> None:
    if not ALPHA_SEEK_DB.exists():
        print(f"ERROR: Alpha-seek database not found at {ALPHA_SEEK_DB}", file=sys.stderr)
        sys.exit(1)

    nodes, adj = load_graph(ALPHA_SEEK_DB)
    fts_db = build_fts_index(nodes)

    # Compute graph stats
    degrees = [len(adj.get(nid, [])) for nid in nodes]
    orphans = sum(1 for d in degrees if d == 0)
    max_degree_id = max(nodes.keys(), key=lambda nid: len(adj.get(nid, [])))
    max_degree = len(adj.get(max_degree_id, []))

    print(f"\nGraph stats:", file=sys.stderr)
    print(f"  Nodes: {len(nodes)}", file=sys.stderr)
    print(f"  Edges: {sum(len(v) for v in adj.values()) // 2}", file=sys.stderr)
    print(f"  Orphans: {orphans} ({orphans/len(nodes):.0%})", file=sys.stderr)
    print(f"  Max degree: {max_degree_id} ({max_degree} edges)", file=sys.stderr)
    print(f"  Mean degree: {np.mean(degrees):.1f}", file=sys.stderr)

    # Demo queries -- these should be replaced by user-written queries for real experiment
    demo_queries = [
        ("q01", "exit rules position sizing"),
        ("q02", "walk forward evaluation protocol methodology"),
        ("q03", "paper trading deployment production"),
        ("q04", "capital sizing risk management"),
        ("q05", "N starvation trade volume"),
    ]

    print(f"\nRunning {len(demo_queries)} demo queries...\n", file=sys.stderr)

    all_evals: list[dict[str, Any]] = []
    for qid, query in demo_queries:
        eval_sheet = prepare_blind_evaluation(query, qid, nodes, fts_db, adj)
        all_evals.append(eval_sheet)
        print(f"  {qid}: '{query}' -> {eval_sheet['n_unique_results']} unique results "
              f"(fts={eval_sheet['n_fts']}, bfs={eval_sheet['n_bfs']}, "
              f"hybrid={eval_sheet['n_hybrid']})", file=sys.stderr)

    print(f"\nTotal items to label: {sum(e['n_unique_results'] for e in all_evals)}", file=sys.stderr)
    print(f"\nTo run the actual experiment:", file=sys.stderr)
    print(f"  1. Write 20 queries (you, not the system)", file=sys.stderr)
    print(f"  2. Run this script with your queries", file=sys.stderr)
    print(f"  3. Label each item as relevant/partially_relevant/not_relevant", file=sys.stderr)
    print(f"  4. Run scoring script to compute P@15, R@15, nDCG@15 per method", file=sys.stderr)

    print(json.dumps(all_evals, indent=2))


if __name__ == "__main__":
    main()
