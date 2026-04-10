from __future__ import annotations

"""
Experiment 25: Combined Retrieval Pipeline

Tests whether combining FTS5 + HRR + BFS improves retrieval over any single method.
(SimHash omitted -- research showed brute-force Hamming is equivalent to HRR cosine
similarity at this scale, so it would be redundant.)

Ground truth: 6 critical belief topics from Exp 4/6, 3 query variants each.

Fusion method: Reciprocal Rank Fusion (RRF) -- standard IR technique.
  RRF_score(doc) = sum(1 / (k + rank_in_method)) for each method that returns doc
  k = 60 (standard constant)
"""

import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from collections.abc import Callable
from typing import Any

import numpy as np
import numpy.typing as npt

ALPHA_SEEK_DB = Path("/Users/thelorax/projects/.gsd/workflows/spikes/"
                     "260406-1-associative-memory-for-gsd-please-explor/"
                     "sandbox/alpha-seek.db")

CRITICAL: dict[str, dict[str, Any]] = {
    "dispatch_gate": {
        "queries": ["dispatch gate deploy protocol", "follow deploy gate verification", "dispatch runbook GCP"],
        "needed": {"D089", "D106", "D137"},
    },
    "calls_puts": {
        "queries": ["calls puts equal citizens", "put call strategy direction", "options both directions"],
        "needed": {"D073", "D096", "D100"},
    },
    "capital_5k": {
        "queries": ["starting capital bankroll", "initial investment amount", "how much money USD"],
        "needed": {"D099"},
    },
    "agent_behavior": {
        "queries": ["agent behavior instructions", "dont elaborate pontificate", "execute precisely return control"],
        "needed": {"D157", "D188"},
    },
    "strict_typing": {
        "queries": ["typing pyright strict", "type annotations python", "static type checking"],
        "needed": {"D071", "D113"},
    },
    "gcp_primary": {
        "queries": ["GCP primary compute platform", "archon overflow only", "cloud compute infrastructure"],
        "needed": {"D078", "D120"},
    },
}

DIM = 512
RRF_K = 60

NDArr = npt.NDArray[np.floating[Any]]
AdjDict = defaultdict[str, list[tuple[str, str, float]]]


def load_data() -> tuple[dict[str, str], AdjDict]:
    db = sqlite3.connect(str(ALPHA_SEEK_DB))
    nodes: dict[str, str] = {}
    for row in db.execute("SELECT id, content FROM mem_nodes WHERE superseded_by IS NULL"):
        nodes[str(row[0])] = str(row[1])

    adj: AdjDict = defaultdict(list)
    for row in db.execute("SELECT from_id, to_id, edge_type, weight FROM mem_edges"):
        from_id = str(row[0])
        to_id = str(row[1])
        edge_type = str(row[2])
        weight = float(row[3]) if row[3] else 1.0
        adj[from_id].append((to_id, edge_type, weight))
        adj[to_id].append((from_id, edge_type, weight))

    db.close()
    return nodes, adj


def build_fts(nodes: dict[str, str]) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE fts USING fts5(id, content, tokenize='porter')")
    for nid, content in nodes.items():
        db.execute("INSERT INTO fts VALUES (?, ?)", (nid, content))
    db.commit()
    return db


def search_fts(query: str, fts_db: sqlite3.Connection, top_k: int = 20) -> list[str]:
    terms: list[str] = [t for t in query.split() if len(t) > 2]
    if not terms:
        return []
    q = " OR ".join(terms)
    try:
        return [str(r[0]) for r in fts_db.execute(
            "SELECT id FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT ?", (q, top_k)
        ).fetchall()]
    except Exception:
        return []


def build_hrr(nodes: dict[str, str], rng: np.random.Generator) -> tuple[dict[str, NDArr], dict[str, NDArr]]:
    stopwords: set[str] = {"the", "a", "an", "is", "are", "was", "were", "it", "this", "that",
                 "to", "of", "in", "for", "on", "with", "at", "by", "from", "and",
                 "or", "but", "not", "be", "has", "have", "had"}
    vocab: set[str] = set()
    for content in nodes.values():
        words: list[str] = re.findall(r'[a-z0-9]+', content.lower())
        vocab.update(w for w in words if w not in stopwords and len(w) > 2)

    word_vecs: dict[str, NDArr] = {w: rng.standard_normal(DIM) / np.sqrt(DIM) for w in vocab}

    node_vecs: dict[str, NDArr] = {}
    for nid, content in nodes.items():
        words_set: set[str] = set(re.findall(r'[a-z0-9]+', content.lower())) - stopwords
        vec: NDArr = np.zeros(DIM)
        for w in words_set:
            if w in word_vecs:
                vec = vec + word_vecs[w]
        norm = float(np.linalg.norm(vec))
        node_vecs[nid] = vec / norm if norm > 0 else vec

    return node_vecs, word_vecs


def search_hrr(query: str, node_vecs: dict[str, NDArr], word_vecs: dict[str, NDArr], top_k: int = 20) -> list[str]:
    stopwords: set[str] = {"the", "a", "an", "is", "are", "was", "were", "it", "this", "that",
                 "to", "of", "in", "for", "on", "with", "at", "by", "from", "and",
                 "or", "but", "not", "be", "has", "have", "had"}
    words: set[str] = set(re.findall(r'[a-z0-9]+', query.lower())) - stopwords
    qvec: NDArr = np.zeros(DIM)
    for w in words:
        if w in word_vecs:
            qvec = qvec + word_vecs[w]
    norm = float(np.linalg.norm(qvec))
    if norm == 0:
        return []
    qvec = qvec / norm

    sims: list[tuple[str, float]] = [(nid, float(np.dot(qvec, vec))) for nid, vec in node_vecs.items()]
    sims.sort(key=lambda x: x[1], reverse=True)
    return [nid for nid, _ in sims[:top_k]]


def search_bfs(query: str, fts_db: sqlite3.Connection, adj: AdjDict, nodes: dict[str, str], top_k: int = 20) -> list[str]:
    seeds: list[str] = search_fts(query, fts_db, top_k=3)
    if not seeds:
        return []

    visited: dict[str, float] = {}
    queue: list[tuple[str, int, float]] = [(s, 0, 1.0) for s in seeds if s in nodes]

    while queue:
        nid, depth, score = queue.pop(0)
        if nid in visited:
            visited[nid] = max(visited[nid], score)
            continue
        visited[nid] = score
        if depth >= 2:
            continue

        for neighbor, _etype, weight in adj.get(nid, []):
            if neighbor not in nodes:
                continue
            ndeg = len(adj.get(neighbor, []))
            damping = 0.5 if ndeg > 30 else 1.0
            queue.append((neighbor, depth + 1, score * weight * damping * 0.7))

    ranked: list[tuple[str, float]] = sorted(visited.items(), key=lambda x: x[1], reverse=True)
    return [nid for nid, _ in ranked[:top_k]]


def reciprocal_rank_fusion(ranked_lists: list[list[str]], k: int = RRF_K) -> list[str]:
    scores: defaultdict[str, float] = defaultdict(float)
    for rlist in ranked_lists:
        for rank, nid in enumerate(rlist):
            scores[nid] += 1.0 / (k + rank + 1)
    return [nid for nid, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]


def main() -> None:
    rng = np.random.default_rng(42)

    print("=" * 60, file=sys.stderr)
    print("Experiment 25: Combined Retrieval Pipeline", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    nodes, adj = load_data()
    fts_db = build_fts(nodes)
    node_vecs, word_vecs = build_hrr(nodes, rng)
    print(f"  {len(nodes)} nodes, {sum(len(v) for v in adj.values())//2} edges", file=sys.stderr)

    methods: dict[str, Callable[[str], list[str]]] = {
        "fts": lambda q: search_fts(q, fts_db),
        "hrr": lambda q: search_hrr(q, node_vecs, word_vecs),
        "bfs": lambda q: search_bfs(q, fts_db, adj, nodes),
        "fused": lambda q: reciprocal_rank_fusion([
            search_fts(q, fts_db),
            search_hrr(q, node_vecs, word_vecs),
            search_bfs(q, fts_db, adj, nodes),
        ]),
    }

    results: dict[str, dict[str, dict[str, Any]]] = {}
    for topic_id, topic in CRITICAL.items():
        needed: set[str] = topic["needed"]
        topic_results: dict[str, dict[str, Any]] = {}

        for method_name, search_fn in methods.items():
            found: set[str] = set()
            total_retrieved: set[str] = set()
            for query in topic["queries"]:
                results_list: list[str] = search_fn(query)
                total_retrieved.update(results_list)
                found.update(needed & set(results_list))

            topic_results[method_name] = {
                "found": list(found),
                "missed": list(needed - found),
                "coverage": len(found) / len(needed) if needed else 0,
                "total_retrieved": len(total_retrieved),
            }

        results[topic_id] = topic_results

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"{'Topic':<18} {'FTS5':>6} {'HRR':>6} {'BFS':>6} {'Fused':>6}", file=sys.stderr)
    print("-" * 45, file=sys.stderr)

    method_totals: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"found": 0, "needed": 0})
    for topic_id, topic_results in results.items():
        needed_count = len(CRITICAL[topic_id]["needed"])
        row = f"{topic_id:<18}"
        for method in ["fts", "hrr", "bfs", "fused"]:
            cov: float = topic_results[method]["coverage"]
            row += f" {cov:>5.0%} "
            method_totals[method]["found"] += int(cov * needed_count)
            method_totals[method]["needed"] += needed_count
        print(row, file=sys.stderr)

    print("-" * 45, file=sys.stderr)
    row = f"{'OVERALL':<18}"
    for method in ["fts", "hrr", "bfs", "fused"]:
        t = method_totals[method]
        row += f" {t['found']/t['needed']:>5.0%} "
    print(row, file=sys.stderr)

    # Unique contributions
    print(f"\n  Unique contributions (found by this method but NOT by others):", file=sys.stderr)
    for topic_id, topic_results in results.items():
        for method in ["fts", "hrr", "bfs"]:
            found_by_method: set[str] = set(topic_results[method]["found"])
            found_by_others: set[str] = set()
            for other in ["fts", "hrr", "bfs"]:
                if other != method:
                    found_by_others.update(topic_results[other]["found"])
            unique: set[str] = found_by_method - found_by_others
            if unique:
                print(f"    {topic_id}/{method}: {unique}", file=sys.stderr)

    # Is any method fully redundant?
    print(f"\n  Redundancy check:", file=sys.stderr)
    for method in ["fts", "hrr", "bfs"]:
        total_unique = 0
        for topic_id, topic_results in results.items():
            found_by_method_r: set[str] = set(topic_results[method]["found"])
            found_by_others_r: set[str] = set()
            for other in ["fts", "hrr", "bfs"]:
                if other != method:
                    found_by_others_r.update(topic_results[other]["found"])
            total_unique += len(found_by_method_r - found_by_others_r)
        print(f"    {method}: {total_unique} unique finds across all topics "
              f"({'REDUNDANT' if total_unique == 0 else 'CONTRIBUTES'})", file=sys.stderr)

    Path("experiments/exp25_results.json").write_text(json.dumps(results, indent=2))
    print(f"\nOutput: experiments/exp25_results.json", file=sys.stderr)


if __name__ == "__main__":
    main()
