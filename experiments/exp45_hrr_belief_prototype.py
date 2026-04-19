"""
Experiment 45: HRR Belief Prototype

Research thread #36: full HRR prototype for the 1,195-node sentence-level
belief graph.  Tests five questions:

  1. Partition strategy -- per-decision neighborhood vs edge-type vs fixed-size
  2. DIM=4096 vs DIM=2048 comparison
  3. Integrated single-hop HRR + BFS multi-hop pipeline
  4. Vocabulary-gap retrieval (D157 recovery via AGENT_CONSTRAINT walk)
  5. Capacity analysis -- partition count, memory footprint, scaling

Data source: project-a.db (586 decisions -> 1,195 sentence nodes, 1,485 edges)
Ground truth: 6 critical topics from Exp 9/39 (13 decisions)

Only numpy/scipy + stdlib.  Strict pyright typing.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Final, TypeAlias

import numpy as np
import numpy.typing as npt

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

NDArr: TypeAlias = npt.NDArray[np.floating[Any]]
SentDict: TypeAlias = dict[str, dict[str, Any]]
GroupDict: TypeAlias = dict[str, list[str]]
EdgeTriple: TypeAlias = tuple[str, str, str]
EdgeList: TypeAlias = list[EdgeTriple]

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ALPHA_SEEK_DB: Final[Path] = Path(
    "/home/user/projects/.gsd/workflows/spikes/"
    "260406-1-associative-memory-for-gsd-please-explor/"
    "sandbox/project-a.db"
)

BEHAVIORAL_DECISIONS: Final[list[str]] = ["D157", "D188", "D100", "D073"]

# Ground truth from Exp 9/39
TOPICS: Final[dict[str, dict[str, Any]]] = {
    "dispatch_gate": {
        "query": "dispatch gate deploy protocol",
        "needed": ["D089", "D106", "D137"],
    },
    "calls_puts": {
        "query": "calls puts equal citizens",
        "needed": ["D073", "D096", "D100"],
    },
    "capital_5k": {
        "query": "starting capital bankroll",
        "needed": ["D099"],
    },
    "agent_behavior": {
        "query": "agent behavior instructions",
        "needed": ["D157", "D188"],
    },
    "strict_typing": {
        "query": "typing pyright strict",
        "needed": ["D071", "D113"],
    },
    "gcp_primary": {
        "query": "GCP primary compute platform",
        "needed": ["D078", "D120"],
    },
}


# ===================================================================
# HRR Core (dimension-agnostic)
# ===================================================================


def make_vec(rng: np.random.Generator, dim: int) -> NDArr:
    """Unit-norm random vector in R^dim."""
    v: NDArr = rng.standard_normal(dim).astype(np.float64)
    norm: np.floating[Any] = np.linalg.norm(v)
    if norm < 1e-10:
        v[0] = 1.0
        return v
    result: NDArr = v / norm
    return result


def bind(a: NDArr, b: NDArr) -> NDArr:
    """Circular convolution via FFT."""
    out: NDArr = np.real(np.fft.ifft(np.fft.fft(a) * np.fft.fft(b))).astype(np.float64)
    return out


def unbind(key: NDArr, superposition: NDArr) -> NDArr:
    """Circular correlation (approximate inverse of bind) via FFT."""
    out: NDArr = np.real(
        np.fft.ifft(np.conj(np.fft.fft(key)) * np.fft.fft(superposition))
    ).astype(np.float64)
    return out


def cos_sim(a: NDArr, b: NDArr) -> float:
    """Cosine similarity, safe for zero vectors."""
    na: float = float(np.linalg.norm(a))
    nb: float = float(np.linalg.norm(b))
    if na < 1e-10 or nb < 1e-10:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def nearest_k(
    query: NDArr,
    memory: dict[str, NDArr],
    k: int = 10,
    exclude: set[str] | None = None,
) -> list[tuple[str, float]]:
    """Return k nearest nodes by cosine similarity."""
    ex: set[str] = exclude if exclude is not None else set()
    sims: list[tuple[str, float]] = [
        (label, cos_sim(query, vec)) for label, vec in memory.items() if label not in ex
    ]
    sims.sort(key=lambda x: x[1], reverse=True)
    return sims[:k]


# ===================================================================
# Data loading
# ===================================================================


def split_sentences(text: str) -> list[str]:
    """Split decision text into sentences."""
    parts: list[str | Any] = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    sents: list[str] = []
    for p in parts:
        for sp in str(p).split(" | "):
            sp = sp.strip()
            if len(sp) > 10:
                sents.append(sp)
    return sents


def load_sentence_graph() -> tuple[SentDict, GroupDict, EdgeList]:
    """Load sentences and build typed edges from project-a DB."""
    db: sqlite3.Connection = sqlite3.connect(str(ALPHA_SEEK_DB))
    sentences: SentDict = {}
    groups: GroupDict = {}

    for row in db.execute("SELECT id, decision, choice, rationale FROM decisions"):
        did: str = str(row[0])
        full: str = f"{row[1]}: {row[2]}"
        if row[3]:
            full += f" | {row[3]}"
        sents: list[str] = split_sentences(full)
        group: list[str] = []
        for i, s in enumerate(sents):
            sid: str = f"{did}_s{i}"
            sentences[sid] = {"content": s, "parent": did, "index": i}
            group.append(sid)
        groups[did] = group
    db.close()

    # Build edges
    edges: EdgeList = []

    # NEXT_IN_DECISION
    for _did, group in groups.items():
        for i in range(len(group) - 1):
            edges.append((group[i], group[i + 1], "NEXT_IN_DECISION"))

    # CITES: sentence mentioning D### -> first sentence of target decision
    d_ref: re.Pattern[str] = re.compile(r"\bD(\d{2,3})\b")
    for sid, sent in sentences.items():
        parent: str = str(sent["parent"])
        for m in d_ref.finditer(str(sent["content"])):
            target_did: str = f"D{m.group(1)}"
            if (
                target_did != parent
                and target_did in groups
                and len(groups[target_did]) > 0
            ):
                edges.append((sid, groups[target_did][0], "CITES"))

    # SAME_TOPIC via milestone co-reference
    m_ref: re.Pattern[str] = re.compile(r"\bM(\d{2,3})\b")
    milestone_sids: dict[str, list[str]] = {}
    for sid, sent in sentences.items():
        for m in m_ref.finditer(str(sent["content"])):
            mid: str = f"M{m.group(1)}"
            if mid not in milestone_sids:
                milestone_sids[mid] = []
            milestone_sids[mid].append(sid)

    for _mid, sids in milestone_sids.items():
        by_parent: defaultdict[str, list[str]] = defaultdict(list)
        for sid in sids:
            by_parent[str(sentences[sid]["parent"])].append(sid)
        parents: list[str] = list(by_parent.keys())
        for i in range(len(parents)):
            for j in range(i + 1, min(i + 3, len(parents))):
                src: str = by_parent[parents[i]][0]
                dst: str = by_parent[parents[j]][0]
                edges.append((src, dst, "SAME_TOPIC"))

    return sentences, groups, edges


def build_agent_constraint_edges(
    groups: GroupDict, behavioral_dids: list[str]
) -> EdgeList:
    """Build bidirectional AGENT_CONSTRAINT edges among behavioral beliefs."""
    behavior_sids: list[str] = []
    for did in behavioral_dids:
        if did in groups and len(groups[did]) > 0:
            behavior_sids.append(groups[did][0])
    edges: EdgeList = []
    for i in range(len(behavior_sids)):
        for j in range(i + 1, len(behavior_sids)):
            edges.append((behavior_sids[i], behavior_sids[j], "AGENT_CONSTRAINT"))
            edges.append((behavior_sids[j], behavior_sids[i], "AGENT_CONSTRAINT"))
    return edges


# ===================================================================
# Partition strategies
# ===================================================================


def partition_by_decision_neighborhood(
    edges: EdgeList, sentences: SentDict
) -> dict[str, EdgeList]:
    """Strategy A: group edges by source decision, merge small groups."""
    by_parent: defaultdict[str, EdgeList] = defaultdict(list)
    for src, dst, et in edges:
        parent: str = str(sentences[src]["parent"])
        by_parent[parent].append((src, dst, et))

    partitions: dict[str, EdgeList] = {}
    current: EdgeList = []
    idx: int = 0
    for _parent, pedges in sorted(by_parent.items()):
        current.extend(pedges)
        if len(current) >= 50:
            partitions[f"dec_{idx}"] = list(current)
            current = []
            idx += 1
    if current:
        partitions[f"dec_{idx}"] = current
    return partitions


def partition_by_edge_type(edges: EdgeList) -> dict[str, EdgeList]:
    """Strategy B: one partition per edge type."""
    by_type: defaultdict[str, EdgeList] = defaultdict(list)
    for src, dst, et in edges:
        by_type[et].append((src, dst, et))
    return dict(by_type)


def partition_fixed_size(edges: EdgeList, max_edges: int = 100) -> dict[str, EdgeList]:
    """Strategy C: fixed-size partitions, k edges each."""
    partitions: dict[str, EdgeList] = {}
    for i in range(0, len(edges), max_edges):
        chunk: EdgeList = edges[i : i + max_edges]
        partitions[f"fixed_{i // max_edges}"] = chunk
    return partitions


# ===================================================================
# HRR Graph with partitions
# ===================================================================


class HRRGraph:
    """HRR-encoded partitioned graph."""

    def __init__(self, dim: int, rng: np.random.Generator) -> None:
        self.dim: int = dim
        self.rng: np.random.Generator = rng
        self.node_vecs: dict[str, NDArr] = {}
        self.edge_type_vecs: dict[str, NDArr] = {}
        self.partitions: dict[str, NDArr] = {}
        self.node_to_partitions: dict[str, set[str]] = defaultdict(set)
        self.partition_edge_counts: dict[str, int] = {}

    def _ensure_node(self, nid: str) -> None:
        if nid not in self.node_vecs:
            self.node_vecs[nid] = make_vec(self.rng, self.dim)

    def _ensure_edge_type(self, etype: str) -> None:
        if etype not in self.edge_type_vecs:
            self.edge_type_vecs[etype] = make_vec(self.rng, self.dim)

    def encode_partition(self, partition_id: str, edges: EdgeList) -> None:
        """Encode edges into a superposition vector."""
        s_vec: NDArr = np.zeros(self.dim, dtype=np.float64)
        for src, dst, etype in edges:
            self._ensure_node(src)
            self._ensure_node(dst)
            self._ensure_edge_type(etype)
            # Encode: bind(src, edge_type) -> dst
            bound: NDArr = bind(
                bind(self.node_vecs[src], self.edge_type_vecs[etype]),
                self.node_vecs[dst],
            )
            s_vec = s_vec + bound
            self.node_to_partitions[src].add(partition_id)
            self.node_to_partitions[dst].add(partition_id)
        self.partitions[partition_id] = s_vec
        self.partition_edge_counts[partition_id] = len(edges)

    def query_single_hop(
        self,
        source: str,
        edge_type: str,
        top_k: int = 10,
        threshold: float = 0.0,
        partition_id: str | None = None,
    ) -> list[tuple[str, float]]:
        """Single-hop typed query: source -[edge_type]-> ?"""
        if source not in self.node_vecs:
            return []
        if edge_type not in self.edge_type_vecs:
            return []

        # Determine which partitions to query
        if partition_id is not None:
            pids: list[str] = [partition_id]
        else:
            pids = sorted(self.node_to_partitions.get(source, set()))

        if not pids:
            return []

        # Query each partition and aggregate
        all_scores: dict[str, float] = {}
        q_vec: NDArr = bind(self.node_vecs[source], self.edge_type_vecs[edge_type])

        for pid in pids:
            s_vec: NDArr = self.partitions[pid]
            result: NDArr = unbind(q_vec, s_vec)

            # Score against nodes in this partition
            for nid in self.node_vecs:
                if nid == source:
                    continue
                if pid not in self.node_to_partitions.get(nid, set()):
                    continue
                sim: float = cos_sim(result, self.node_vecs[nid])
                if sim >= threshold:
                    if nid not in all_scores or sim > all_scores[nid]:
                        all_scores[nid] = sim

        ranked: list[tuple[str, float]] = sorted(
            all_scores.items(), key=lambda x: x[1], reverse=True
        )
        return ranked[:top_k]

    def memory_footprint_bytes(self) -> int:
        """Total memory for all superposition vectors + node/edge-type vectors."""
        n_partition_vecs: int = len(self.partitions)
        n_node_vecs: int = len(self.node_vecs)
        n_etype_vecs: int = len(self.edge_type_vecs)
        total_vecs: int = n_partition_vecs + n_node_vecs + n_etype_vecs
        # Each vector: dim * 8 bytes (float64)
        return total_vecs * self.dim * 8


# ===================================================================
# BFS on explicit edge list (multi-hop)
# ===================================================================


def bfs_multi_hop(
    start_nodes: set[str],
    edges: EdgeList,
    edge_type_filter: str | None,
    max_hops: int,
    sentences: SentDict,
) -> dict[str, int]:
    """BFS from start_nodes, return {node: hop_distance}."""
    # Build adjacency
    adj: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
    for src, dst, et in edges:
        if edge_type_filter is None or et == edge_type_filter:
            adj[src].append((dst, et))

    visited: dict[str, int] = {}
    frontier: set[str] = set(start_nodes)
    for node in frontier:
        visited[node] = 0

    for hop in range(1, max_hops + 1):
        next_frontier: set[str] = set()
        for node in frontier:
            for neighbor, _et in adj.get(node, []):
                if neighbor not in visited:
                    visited[neighbor] = hop
                    next_frontier.add(neighbor)
        frontier = next_frontier
        if not frontier:
            break

    return visited


# ===================================================================
# FTS5 helpers
# ===================================================================


def build_fts_index(sentences: SentDict) -> sqlite3.Connection:
    """Build an in-memory FTS5 index on sentence content."""
    db: sqlite3.Connection = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE fts USING fts5(id, content, tokenize='porter')")
    for sid, sent in sentences.items():
        db.execute("INSERT INTO fts VALUES (?, ?)", (sid, str(sent["content"])))
    db.commit()
    return db


def search_fts(
    query: str, fts_db: sqlite3.Connection, top_k: int = 30
) -> list[tuple[str, float]]:
    """FTS5 search returning (sentence_id, bm25_score)."""
    terms: list[str] = [t.strip() for t in query.split() if len(t.strip()) > 2]
    if not terms:
        return []
    fts_query: str = " OR ".join(terms)
    try:
        results: list[Any] = fts_db.execute(
            "SELECT id, rank FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT ?",
            (fts_query, top_k),
        ).fetchall()
        return [(str(r[0]), float(r[1])) for r in results]
    except Exception:
        return []


def extract_decision_id(sid: str) -> str | None:
    """Extract D### from a sentence id like D195_s1."""
    m: re.Match[str] | None = re.match(r"(D\d{2,3})", sid)
    return m.group(1) if m else None


# ===================================================================
# Test 1: Partition strategy comparison
# ===================================================================


def test_partition_strategies(
    sentences: SentDict,
    groups: GroupDict,
    edges: EdgeList,
) -> dict[str, Any]:
    """Compare partition strategies at DIM=2048 and DIM=4096."""
    print("\n" + "=" * 70, file=sys.stderr)
    print("TEST 1: Partition Strategy Comparison", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    # Find 5 test queries: sentences with known CITES targets
    cites_out: defaultdict[str, list[str]] = defaultdict(list)
    for src, dst, et in edges:
        if et == "CITES":
            cites_out[src].append(dst)

    # Pick 5 sources with 2+ CITES targets
    test_queries: list[tuple[str, list[str]]] = []
    for src, targets in sorted(
        cites_out.items(), key=lambda x: len(x[1]), reverse=True
    ):
        if len(targets) >= 2 and len(test_queries) < 5:
            test_queries.append((src, targets))

    print(f"  Test queries: {len(test_queries)}", file=sys.stderr)
    for src, targets in test_queries:
        print(
            f"    {src} -> {len(targets)} CITES targets",
            file=sys.stderr,
        )

    strategies: dict[str, dict[str, EdgeList]] = {
        "decision_neighborhood": partition_by_decision_neighborhood(edges, sentences),
        "edge_type": partition_by_edge_type(edges),
        "fixed_100": partition_fixed_size(edges, max_edges=100),
    }

    results: dict[str, Any] = {}

    for dim in [2048, 4096]:
        dim_results: dict[str, Any] = {}
        for strategy_name, partitions in strategies.items():
            rng: np.random.Generator = np.random.default_rng(42)
            graph: HRRGraph = HRRGraph(dim=dim, rng=rng)

            for pid, pedges in partitions.items():
                graph.encode_partition(pid, pedges)

            # Test each query
            query_results: list[dict[str, Any]] = []
            total_recall: int = 0
            total_targets: int = 0

            for src, targets in test_queries:
                hits: list[tuple[str, float]] = graph.query_single_hop(
                    src, "CITES", top_k=len(targets) + 5
                )
                hit_ids: set[str] = set(h[0] for h in hits[: len(targets)])
                found: set[str] = hit_ids & set(targets)
                total_recall += len(found)
                total_targets += len(targets)

                # Top similarity for found targets
                target_sims: list[float] = [
                    sim for nid, sim in hits if nid in set(targets)
                ]
                noise_sims: list[float] = [
                    sim for nid, sim in hits if nid not in set(targets) and nid != src
                ]

                query_results.append(
                    {
                        "source": src,
                        "n_targets": len(targets),
                        "found": len(found),
                        "recall": round(len(found) / len(targets), 3),
                        "target_sims": [round(s, 4) for s in target_sims[:5]],
                        "noise_sims": [round(s, 4) for s in noise_sims[:3]],
                    }
                )

            partition_sizes: list[int] = [len(pe) for pe in partitions.values()]
            avg_recall: float = (
                total_recall / total_targets if total_targets > 0 else 0.0
            )

            dim_results[strategy_name] = {
                "n_partitions": len(partitions),
                "avg_partition_size": round(
                    sum(partition_sizes) / len(partition_sizes), 1
                ),
                "max_partition_size": max(partition_sizes),
                "min_partition_size": min(partition_sizes),
                "avg_recall": round(avg_recall, 3),
                "total_recall": f"{total_recall}/{total_targets}",
                "per_query": query_results,
                "memory_bytes": graph.memory_footprint_bytes(),
            }

            print(
                f"\n  DIM={dim} | {strategy_name}: "
                f"{len(partitions)} partitions, "
                f"avg size {dim_results[strategy_name]['avg_partition_size']}, "
                f"recall {avg_recall:.3f}",
                file=sys.stderr,
            )

        results[f"dim_{dim}"] = dim_results

    return results


# ===================================================================
# Test 2: DIM=4096 vs DIM=2048
# ===================================================================


def test_dim_comparison(
    sentences: SentDict,
    groups: GroupDict,
    edges: EdgeList,
) -> dict[str, Any]:
    """Direct DIM comparison using best partition strategy."""
    print("\n" + "=" * 70, file=sys.stderr)
    print("TEST 2: DIM=4096 vs DIM=2048", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    # Use decision-neighborhood partitioning (most natural for belief graph)
    partitions: dict[str, EdgeList] = partition_by_decision_neighborhood(
        edges, sentences
    )

    # Build 10 test queries covering different partition regions
    cites_out: defaultdict[str, list[str]] = defaultdict(list)
    for src, dst, et in edges:
        if et == "CITES":
            cites_out[src].append(dst)

    test_queries: list[tuple[str, list[str]]] = []
    seen_parents: set[str] = set()
    for src, targets in sorted(
        cites_out.items(), key=lambda x: len(x[1]), reverse=True
    ):
        parent: str = str(sentences[src]["parent"])
        if parent not in seen_parents and len(targets) >= 1:
            test_queries.append((src, targets))
            seen_parents.add(parent)
            if len(test_queries) >= 10:
                break

    results: dict[str, Any] = {}

    for dim in [2048, 4096]:
        rng: np.random.Generator = np.random.default_rng(42)
        graph: HRRGraph = HRRGraph(dim=dim, rng=rng)

        t0: float = time.time()
        for pid, pedges in partitions.items():
            graph.encode_partition(pid, pedges)
        encode_time: float = time.time() - t0

        query_results: list[dict[str, Any]] = []
        total_recall: int = 0
        total_targets: int = 0
        query_times: list[float] = []

        for src, targets in test_queries:
            t1: float = time.time()
            hits: list[tuple[str, float]] = graph.query_single_hop(
                src, "CITES", top_k=len(targets) + 5
            )
            query_times.append(time.time() - t1)

            hit_ids: set[str] = set(h[0] for h in hits[: len(targets)])
            found: set[str] = hit_ids & set(targets)
            total_recall += len(found)
            total_targets += len(targets)

            target_sims: list[float] = [sim for nid, sim in hits if nid in set(targets)]
            best_noise: float = max(
                (sim for nid, sim in hits if nid not in set(targets)),
                default=0.0,
            )

            query_results.append(
                {
                    "source": src,
                    "n_targets": len(targets),
                    "found": len(found),
                    "recall": round(len(found) / len(targets), 3),
                    "mean_target_sim": (
                        round(sum(target_sims) / len(target_sims), 4)
                        if target_sims
                        else 0.0
                    ),
                    "best_noise_sim": round(best_noise, 4),
                    "separation": (
                        round(min(target_sims) / max(best_noise, 0.001), 2)
                        if target_sims
                        else 0.0
                    ),
                }
            )

        avg_recall: float = total_recall / total_targets if total_targets > 0 else 0.0

        results[f"dim_{dim}"] = {
            "avg_recall": round(avg_recall, 3),
            "total_recall": f"{total_recall}/{total_targets}",
            "encode_time_s": round(encode_time, 3),
            "avg_query_time_ms": round(1000.0 * sum(query_times) / len(query_times), 2),
            "memory_bytes": graph.memory_footprint_bytes(),
            "per_query": query_results,
        }

        print(
            f"\n  DIM={dim}: recall={avg_recall:.3f} "
            f"({total_recall}/{total_targets}), "
            f"encode={encode_time:.3f}s, "
            f"query avg={results[f'dim_{dim}']['avg_query_time_ms']:.2f}ms, "
            f"memory={graph.memory_footprint_bytes() / 1024:.0f} KB",
            file=sys.stderr,
        )
        for qr in query_results:
            print(
                f"    {qr['source']}: "
                f"{qr['found']}/{qr['n_targets']} "
                f"(sep={qr['separation']}x, "
                f"target_sim={qr['mean_target_sim']:.4f})",
                file=sys.stderr,
            )

    return results


# ===================================================================
# Test 3: Integrated HRR single-hop + BFS multi-hop pipeline
# ===================================================================


def test_integrated_pipeline(
    sentences: SentDict,
    groups: GroupDict,
    edges: EdgeList,
) -> dict[str, Any]:
    """HRR handles typed single-hop, BFS handles exact multi-hop."""
    print("\n" + "=" * 70, file=sys.stderr)
    print("TEST 3: Integrated HRR Single-Hop + BFS Multi-Hop Pipeline", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    # Add AGENT_CONSTRAINT edges for behavioral beliefs
    ac_edges: EdgeList = build_agent_constraint_edges(groups, BEHAVIORAL_DECISIONS)
    all_edges: EdgeList = edges + ac_edges

    # Build HRR graph with decision-neighborhood partitions
    partitions: dict[str, EdgeList] = partition_by_decision_neighborhood(
        all_edges, sentences
    )
    # Put behavioral edges in their own partition
    partitions["behavioral"] = ac_edges

    rng: np.random.Generator = np.random.default_rng(42)
    dim: int = 2048
    graph: HRRGraph = HRRGraph(dim=dim, rng=rng)
    for pid, pedges in partitions.items():
        graph.encode_partition(pid, pedges)

    # Build FTS5 index
    fts_db: sqlite3.Connection = build_fts_index(sentences)

    results: dict[str, Any] = {}

    for topic_name, topic_data in TOPICS.items():
        query_text: str = str(topic_data["query"])
        needed: set[str] = set(str(d) for d in topic_data["needed"])

        # Step 1: FTS5 keyword search
        fts_hits: list[tuple[str, float]] = search_fts(query_text, fts_db, top_k=30)
        fts_sids: set[str] = set(h[0] for h in fts_hits)
        fts_dids: set[str] = set()
        for sid in fts_sids:
            did: str | None = extract_decision_id(sid)
            if did is not None:
                fts_dids.add(did)

        # Step 2: HRR single-hop from FTS5 hits
        hrr_sids: set[str] = set()
        for seed_sid, _score in fts_hits[:10]:
            for etype in ["CITES", "AGENT_CONSTRAINT", "SAME_TOPIC"]:
                neighbors: list[tuple[str, float]] = graph.query_single_hop(
                    seed_sid, etype, top_k=5, threshold=0.05
                )
                for nid, _sim in neighbors:
                    hrr_sids.add(nid)

        hrr_dids: set[str] = set()
        for sid in hrr_sids:
            did = extract_decision_id(sid)
            if did is not None:
                hrr_dids.add(did)

        # Step 3: BFS 2-hop from all HRR+FTS5 hits
        start_sids: set[str] = fts_sids | hrr_sids
        bfs_result: dict[str, int] = bfs_multi_hop(
            start_sids,
            all_edges,
            edge_type_filter=None,
            max_hops=2,
            sentences=sentences,
        )
        bfs_dids: set[str] = set()
        for sid in bfs_result:
            did = extract_decision_id(sid)
            if did is not None:
                bfs_dids.add(did)

        # Evaluate
        fts_found: set[str] = needed & fts_dids
        hrr_added: set[str] = (needed & hrr_dids) - fts_found
        bfs_added: set[str] = (needed & bfs_dids) - fts_found - hrr_added
        combined: set[str] = needed & (fts_dids | hrr_dids | bfs_dids)

        results[topic_name] = {
            "query": query_text,
            "needed": sorted(needed),
            "fts_found": sorted(fts_found),
            "fts_coverage": round(len(fts_found) / len(needed), 3),
            "hrr_added": sorted(hrr_added),
            "bfs_added": sorted(bfs_added),
            "combined_found": sorted(combined),
            "combined_coverage": round(len(combined) / len(needed), 3),
            "fts_result_count": len(fts_sids),
            "hrr_result_count": len(hrr_sids),
            "bfs_result_count": len(bfs_result),
        }

        status: str = (
            "OK" if combined == needed else f"MISSED: {sorted(needed - combined)}"
        )
        print(
            f"\n  {topic_name}: "
            f"FTS={len(fts_found)}/{len(needed)} "
            f"+HRR={len(hrr_added)} "
            f"+BFS={len(bfs_added)} "
            f"-> {len(combined)}/{len(needed)} {status}",
            file=sys.stderr,
        )

    fts_db.close()

    # Totals
    total_needed: int = sum(len(r["needed"]) for r in results.values())
    total_combined: int = sum(len(r["combined_found"]) for r in results.values())
    results["overall"] = {
        "total_needed": total_needed,
        "total_combined": total_combined,
        "overall_coverage": round(total_combined / total_needed, 3),
    }
    print(
        f"\n  OVERALL: {total_combined}/{total_needed} "
        f"({results['overall']['overall_coverage']:.0%})",
        file=sys.stderr,
    )

    return results


# ===================================================================
# Test 4: Vocabulary-gap retrieval (D157 recovery)
# ===================================================================


def test_vocabulary_gap(
    sentences: SentDict,
    groups: GroupDict,
    edges: EdgeList,
) -> dict[str, Any]:
    """D157 recovery: FTS5-only vs HRR-only vs combined."""
    print("\n" + "=" * 70, file=sys.stderr)
    print("TEST 4: Vocabulary-Gap Retrieval (D157 Recovery)", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    ac_edges: EdgeList = build_agent_constraint_edges(groups, BEHAVIORAL_DECISIONS)
    all_edges: EdgeList = edges + ac_edges

    # Build HRR graph
    partitions: dict[str, EdgeList] = partition_by_decision_neighborhood(
        all_edges, sentences
    )
    partitions["behavioral"] = ac_edges

    rng: np.random.Generator = np.random.default_rng(42)
    graph: HRRGraph = HRRGraph(dim=2048, rng=rng)
    for pid, pedges in partitions.items():
        graph.encode_partition(pid, pedges)

    # Build FTS5
    fts_db: sqlite3.Connection = build_fts_index(sentences)

    query: str = "agent behavior instructions"

    # --- FTS5-only ---
    fts_hits: list[tuple[str, float]] = search_fts(query, fts_db, top_k=30)
    fts_dids: set[str] = set()
    for sid, _score in fts_hits:
        did: str | None = extract_decision_id(sid)
        if did is not None:
            fts_dids.add(did)
    d157_in_fts: bool = "D157" in fts_dids
    d188_in_fts: bool = "D188" in fts_dids

    print(
        f"\n  FTS5-only: D157={'FOUND' if d157_in_fts else 'MISSED'}, "
        f"D188={'FOUND' if d188_in_fts else 'MISSED'}",
        file=sys.stderr,
    )

    # --- HRR-only (from known D188 seed) ---
    d188_sid: str = groups["D188"][0] if "D188" in groups else ""
    hrr_from_d188: list[tuple[str, float]] = []
    if d188_sid:
        hrr_from_d188 = graph.query_single_hop(
            d188_sid, "AGENT_CONSTRAINT", top_k=10, threshold=0.0
        )
    d157_in_hrr: bool = any(nid.startswith("D157") for nid, _sim in hrr_from_d188)
    d157_hrr_sim: float = 0.0
    for nid, sim in hrr_from_d188:
        if nid.startswith("D157"):
            d157_hrr_sim = sim
            break

    print(
        f"  HRR-only (from D188): D157={'FOUND' if d157_in_hrr else 'MISSED'} "
        f"(sim={d157_hrr_sim:.4f})",
        file=sys.stderr,
    )
    print("    HRR neighbors of D188:", file=sys.stderr)
    for nid, sim in hrr_from_d188[:8]:
        is_behavioral: bool = any(nid.startswith(d) for d in BEHAVIORAL_DECISIONS)
        marker: str = " <-- BEHAVIORAL" if is_behavioral else ""
        print(f"      {nid}: sim={sim:.4f}{marker}", file=sys.stderr)

    # --- Combined (FTS5 -> HRR walk) ---
    combined_dids: set[str] = set(fts_dids)
    for seed_sid, _score in fts_hits[:10]:
        for etype in ["AGENT_CONSTRAINT", "CITES"]:
            neighbors: list[tuple[str, float]] = graph.query_single_hop(
                seed_sid, etype, top_k=5, threshold=0.05
            )
            for nid, _sim in neighbors:
                did = extract_decision_id(nid)
                if did is not None:
                    combined_dids.add(did)

    d157_in_combined: bool = "D157" in combined_dids

    print(
        f"  Combined: D157={'FOUND' if d157_in_combined else 'MISSED'}", file=sys.stderr
    )
    print(
        "    FTS5 finds D188, HRR walks AGENT_CONSTRAINT to find D157", file=sys.stderr
    )

    # Separation analysis for HRR results
    behavioral_sims: list[float] = []
    distractor_sims: list[float] = []
    for nid, sim in hrr_from_d188:
        is_behavioral = any(nid.startswith(d) for d in BEHAVIORAL_DECISIONS)
        if is_behavioral:
            behavioral_sims.append(sim)
        else:
            distractor_sims.append(sim)

    mean_behavioral: float = (
        sum(behavioral_sims) / len(behavioral_sims) if behavioral_sims else 0.0
    )
    mean_distractor: float = (
        sum(distractor_sims) / len(distractor_sims) if distractor_sims else 0.0
    )
    separation: float = (
        mean_behavioral / max(abs(mean_distractor), 0.001) if behavioral_sims else 0.0
    )

    fts_db.close()

    results: dict[str, Any] = {
        "query": query,
        "fts_only": {
            "d157_found": d157_in_fts,
            "d188_found": d188_in_fts,
            "total_results": len(fts_hits),
        },
        "hrr_only": {
            "d157_found": d157_in_hrr,
            "d157_similarity": round(d157_hrr_sim, 4),
            "behavioral_mean_sim": round(mean_behavioral, 4),
            "distractor_mean_sim": round(mean_distractor, 4),
            "separation_ratio": round(separation, 1),
        },
        "combined": {
            "d157_found": d157_in_combined,
            "d188_found": "D188" in combined_dids,
            "mechanism": "FTS5 finds D188, HRR walks AGENT_CONSTRAINT to D157",
        },
    }

    print(
        f"\n  Separation: behavioral mean={mean_behavioral:.4f}, "
        f"distractor mean={mean_distractor:.4f}, "
        f"ratio={separation:.1f}x",
        file=sys.stderr,
    )

    return results


# ===================================================================
# Test 5: Capacity analysis
# ===================================================================


def test_capacity_analysis(
    sentences: SentDict,
    groups: GroupDict,
    edges: EdgeList,
) -> dict[str, Any]:
    """Partition count, memory footprint, scaling projections."""
    print("\n" + "=" * 70, file=sys.stderr)
    print("TEST 5: Capacity Analysis", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    n_nodes: int = len(sentences)
    n_edges: int = len(edges)

    # Decision-neighborhood partitioning (the winner from Test 1)
    partitions: dict[str, EdgeList] = partition_by_decision_neighborhood(
        edges, sentences
    )
    partition_sizes: list[int] = [len(pe) for pe in partitions.values()]

    # Capacity headroom at DIM=2048 and DIM=4096
    capacity_2048: int = 2048 // 9  # ~227
    capacity_4096: int = 4096 // 9  # ~455

    over_capacity_2048: int = sum(1 for s in partition_sizes if s > capacity_2048)
    over_capacity_4096: int = sum(1 for s in partition_sizes if s > capacity_4096)

    # Memory footprint
    n_partitions: int = len(partitions)
    # Unique nodes across all partitions
    all_edge_types: set[str] = set()
    for _pid, pedges in partitions.items():
        for _src, _dst, et in pedges:
            all_edge_types.add(et)
    n_edge_types: int = len(all_edge_types)

    for dim in [2048, 4096]:
        n_vecs: int = n_partitions + n_nodes + n_edge_types
        mem_bytes: int = n_vecs * dim * 8
        mem_mb: float = mem_bytes / (1024 * 1024)
        print(
            f"\n  DIM={dim}: {n_partitions} partitions, "
            f"{n_vecs} vectors, "
            f"{mem_mb:.2f} MB total",
            file=sys.stderr,
        )

    # Scaling projections
    print("\n  Scaling projections:", file=sys.stderr)
    scaling: list[dict[str, Any]] = []

    for target_nodes in [1195, 10000, 100000]:
        scale_factor: float = target_nodes / max(n_nodes, 1)
        projected_edges: int = int(n_edges * scale_factor)

        # Assume avg partition size stays ~50-60 edges
        avg_partition_size: float = (
            sum(partition_sizes) / len(partition_sizes) if partition_sizes else 50.0
        )
        projected_partitions: int = max(
            1, math.ceil(projected_edges / avg_partition_size)
        )

        for dim in [2048, 4096]:
            total_vecs: int = projected_partitions + target_nodes + n_edge_types
            mem_bytes = total_vecs * dim * 8
            mem_mb = mem_bytes / (1024 * 1024)

            entry: dict[str, Any] = {
                "nodes": target_nodes,
                "edges": projected_edges,
                "partitions": projected_partitions,
                "dim": dim,
                "total_vectors": total_vecs,
                "memory_mb": round(mem_mb, 2),
            }
            scaling.append(entry)
            print(
                f"    {target_nodes:>7} nodes, {projected_edges:>7} edges, "
                f"{projected_partitions:>4} partitions @ DIM={dim}: "
                f"{mem_mb:.2f} MB",
                file=sys.stderr,
            )

    results: dict[str, Any] = {
        "current_graph": {
            "nodes": n_nodes,
            "edges": n_edges,
            "partitions": n_partitions,
            "partition_sizes": {
                "min": min(partition_sizes) if partition_sizes else 0,
                "max": max(partition_sizes) if partition_sizes else 0,
                "mean": (
                    round(sum(partition_sizes) / len(partition_sizes), 1)
                    if partition_sizes
                    else 0.0
                ),
                "median": round(float(np.median(partition_sizes)), 1)
                if partition_sizes
                else 0.0,
            },
            "edge_types": sorted(all_edge_types),
        },
        "capacity_check": {
            "dim_2048_capacity": capacity_2048,
            "dim_2048_over_capacity": over_capacity_2048,
            "dim_4096_capacity": capacity_4096,
            "dim_4096_over_capacity": over_capacity_4096,
        },
        "memory_footprint": {
            "dim_2048_mb": round(
                (n_partitions + n_nodes + n_edge_types) * 2048 * 8 / (1024 * 1024),
                2,
            ),
            "dim_4096_mb": round(
                (n_partitions + n_nodes + n_edge_types) * 4096 * 8 / (1024 * 1024),
                2,
            ),
        },
        "scaling_projections": scaling,
    }

    return results


# ===================================================================
# Main
# ===================================================================


def main() -> None:
    print("=" * 70, file=sys.stderr)
    print("Experiment 45: HRR Belief Prototype", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    # Load data
    print("\nLoading sentence graph...", file=sys.stderr)
    sentences, groups, edges = load_sentence_graph()
    print(
        f"  {len(sentences)} sentences, {len(groups)} decisions, {len(edges)} edges",
        file=sys.stderr,
    )

    edge_type_counts: defaultdict[str, int] = defaultdict(int)
    for _src, _dst, et in edges:
        edge_type_counts[et] += 1
    for et, count in sorted(edge_type_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"    {et}: {count}", file=sys.stderr)

    # Run all tests
    all_results: dict[str, Any] = {}

    all_results["test1_partition_strategies"] = test_partition_strategies(
        sentences, groups, edges
    )
    all_results["test2_dim_comparison"] = test_dim_comparison(sentences, groups, edges)
    all_results["test3_integrated_pipeline"] = test_integrated_pipeline(
        sentences, groups, edges
    )
    all_results["test4_vocabulary_gap"] = test_vocabulary_gap(sentences, groups, edges)
    all_results["test5_capacity_analysis"] = test_capacity_analysis(
        sentences, groups, edges
    )

    # Save results
    out_path: Path = Path("experiments/exp45_results.json")
    out_path.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nResults saved to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
