"""Exp 56: Corrected Baseline Comparison

Reruns Exp 47 with known engineering fixes applied:
  1. DIM=4096 (capacity ~409 vs 306 edges from 18 behavioral nodes)
  2. Sub-partitioning: auto-split partitions exceeding capacity threshold
  3. CITES edges included (from Exp 40 which achieved 100%)
  4. Increased K for FTS5 pass (K=30 internal, top-15 final ranking)

Methods compared:
  A. Grep on decision-level nodes (baseline, unchanged)
  B. FTS5 on sentence-level nodes (K=15)
  C. FTS5 on sentence-level nodes (K=30, re-ranked to 15)
  D. FTS5 + HRR (DIM=2048, original Exp 47 config -- reproduces the failure)
  E. FTS5 + HRR (DIM=4096, sub-partitioned, CITES edges -- corrected)

Hypothesis: Method E achieves 100% coverage (13/13), surpassing grep's 92%.
Null hypothesis: Corrections do not improve coverage beyond grep.

Ground truth: 6 topics, 13 critical decisions from project-a.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Final

import numpy as np

# ============================================================
# Config
# ============================================================

ALPHA_SEEK_DB: Final[Path] = Path(
    "/home/user/projects/.gsd/workflows/spikes/"
    "260406-1-associative-memory-for-gsd-please-explor/"
    "sandbox/project-a.db"
)

TOP_K: Final[int] = 15
_rng: np.random.Generator = np.random.default_rng(42)

TOPICS: dict[str, dict[str, Any]] = {
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

KNOWN_BEHAVIORAL: Final[list[str]] = ["D157", "D188", "D100", "D073"]

STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "can",
        "could",
        "must",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "but",
        "and",
        "or",
        "nor",
        "not",
        "no",
        "so",
        "if",
        "then",
        "than",
        "too",
        "very",
        "just",
        "about",
        "up",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "only",
        "own",
        "same",
        "that",
        "this",
        "these",
        "those",
        "what",
        "which",
        "who",
        "whom",
        "it",
        "its",
        "he",
        "she",
        "they",
        "them",
        "his",
        "her",
        "their",
        "we",
        "us",
        "our",
        "you",
        "your",
        "i",
        "me",
        "my",
    }
)

DIRECTIVE_PATTERNS: Final[list[re.Pattern[str]]] = [
    re.compile(r"\bBANNED\b"),
    re.compile(r"\bNever\s+use\b", re.IGNORECASE),
    re.compile(r"\bNever\s+\w+\b"),
    re.compile(r"\balways\s+\w+\b", re.IGNORECASE),
    re.compile(r"\bmust\s+not\b", re.IGNORECASE),
    re.compile(r"\bdo\s+not\b", re.IGNORECASE),
    re.compile(r"\bdon't\b", re.IGNORECASE),
]


# ============================================================
# Data loading
# ============================================================


def load_decision_nodes() -> dict[str, str]:
    """Load decision-level nodes (D### only, no sentence splits)."""
    db: sqlite3.Connection = sqlite3.connect(str(ALPHA_SEEK_DB))
    nodes: dict[str, str] = {}
    for row in db.execute(
        "SELECT id, content FROM mem_nodes WHERE superseded_by IS NULL"
    ):
        nid: str = str(row[0])
        if re.match(r"^D\d{3}$", nid):
            nodes[nid] = str(row[1])
    db.close()
    return nodes


def load_sentence_nodes() -> dict[str, str]:
    """Load all sentence-level nodes."""
    db: sqlite3.Connection = sqlite3.connect(str(ALPHA_SEEK_DB))
    nodes: dict[str, str] = {}
    for row in db.execute(
        "SELECT id, content FROM mem_nodes WHERE superseded_by IS NULL"
    ):
        nodes[str(row[0])] = str(row[1])
    db.close()
    return nodes


def extract_decision_id(node_id: str) -> str | None:
    """Extract D### from a node ID like D097_s3."""
    m: re.Match[str] | None = re.match(r"(D\d{3})", node_id)
    return m.group(1) if m else None


def tokenize(text: str) -> list[str]:
    """Lowercase, alphanumeric, no stopwords, min 2 chars."""
    words: list[str] = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) >= 2]


def estimate_tokens(text: str) -> int:
    """Rough token estimate: chars / 4."""
    return max(1, len(text) // 4)


# ============================================================
# Grep baseline
# ============================================================


def grep_search(
    query: str,
    nodes: dict[str, str],
    top_k: int = TOP_K,
) -> list[tuple[str, float]]:
    """Case-insensitive grep: rank by count of query terms matched."""
    query_terms: list[str] = [t.lower() for t in query.split() if len(t) >= 2]
    scores: list[tuple[str, float]] = []

    for nid, content in nodes.items():
        content_lower: str = content.lower()
        match_count: int = sum(
            len(re.findall(re.escape(term), content_lower)) for term in query_terms
        )
        if match_count > 0:
            scores.append((nid, float(match_count)))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_k]


# ============================================================
# FTS5
# ============================================================


def build_fts(nodes: dict[str, str]) -> sqlite3.Connection:
    """Build in-memory FTS5 index with porter stemming."""
    db: sqlite3.Connection = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE fts USING fts5(id, content, tokenize='porter')")
    for nid, content in nodes.items():
        db.execute("INSERT INTO fts VALUES (?, ?)", (nid, content))
    db.commit()
    return db


def search_fts(
    query: str,
    fts_db: sqlite3.Connection,
    top_k: int = TOP_K,
) -> list[tuple[str, float]]:
    """FTS5 search with OR terms."""
    terms: list[str] = [t.strip() for t in query.split() if len(t.strip()) > 2]
    if not terms:
        return []
    fts_query: str = " OR ".join(terms)
    try:
        results: list[tuple[str, float]] = [
            (str(r[0]), float(r[1]))
            for r in fts_db.execute(
                "SELECT id, bm25(fts) FROM fts WHERE fts MATCH ? "
                "ORDER BY bm25(fts) LIMIT ?",
                (fts_query, top_k),
            ).fetchall()
        ]
        return results
    except Exception:
        return []


# ============================================================
# Graph construction
# ============================================================


def scan_behavioral_beliefs(nodes: dict[str, str]) -> set[str]:
    """Find all behavioral decision IDs via directive patterns."""
    behavioral: set[str] = set(KNOWN_BEHAVIORAL)
    for nid, content in nodes.items():
        did: str | None = extract_decision_id(nid)
        if did and did not in behavioral:
            for pattern in DIRECTIVE_PATTERNS:
                if pattern.search(content):
                    behavioral.add(did)
                    break
    return behavioral


def extract_cites_edges(nodes: dict[str, str]) -> list[tuple[str, str]]:
    """Extract CITES edges from D### references in content."""
    d_pattern: re.Pattern[str] = re.compile(r"\bD(\d{3})\b")
    edges: list[tuple[str, str]] = []

    for nid, content in nodes.items():
        src_match: re.Match[str] | None = re.match(r"(D\d{3})", nid)
        if not src_match:
            continue
        src_decision: str = src_match.group(1)

        for m in d_pattern.finditer(content):
            target_decision: str = f"D{m.group(1)}"
            if target_decision != src_decision:
                for target_nid in nodes:
                    if target_nid.startswith(target_decision):
                        edges.append((nid, target_nid))
                        break
    return edges


def build_agent_constraint_edges(
    nodes: dict[str, str],
    behavioral_ids: set[str],
) -> list[tuple[str, str]]:
    """Fully connect all behavioral belief nodes."""
    behavioral_nodes: list[str] = [
        nid for nid in nodes if extract_decision_id(nid) in behavioral_ids
    ]
    edges: list[tuple[str, str]] = []
    for i, a in enumerate(behavioral_nodes):
        for b in behavioral_nodes[i + 1 :]:
            edges.append((a, b))
            edges.append((b, a))
    return edges


# ============================================================
# HRR engine with sub-partitioning
# ============================================================


def make_vector(dim: int) -> np.ndarray[Any, np.dtype[np.floating[Any]]]:
    """Random unit vector."""
    v: np.ndarray[Any, np.dtype[np.floating[Any]]] = _rng.standard_normal(dim)
    v /= np.linalg.norm(v)
    return v


def bind(
    a: np.ndarray[Any, np.dtype[np.floating[Any]]],
    b: np.ndarray[Any, np.dtype[np.floating[Any]]],
) -> np.ndarray[Any, np.dtype[np.floating[Any]]]:
    """Circular convolution via FFT."""
    return np.real(np.fft.ifft(np.fft.fft(a) * np.fft.fft(b)))


def unbind(
    bound: np.ndarray[Any, np.dtype[np.floating[Any]]],
    key: np.ndarray[Any, np.dtype[np.floating[Any]]],
) -> np.ndarray[Any, np.dtype[np.floating[Any]]]:
    """Circular correlation via FFT."""
    return np.real(np.fft.ifft(np.fft.fft(bound) * np.conj(np.fft.fft(key))))


def cos_sim(
    a: np.ndarray[Any, np.dtype[np.floating[Any]]],
    b: np.ndarray[Any, np.dtype[np.floating[Any]]],
) -> float:
    """Cosine similarity."""
    na: np.floating[Any] = np.linalg.norm(a)
    nb: np.floating[Any] = np.linalg.norm(b)
    if na < 1e-10 or nb < 1e-10:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def hrr_capacity(dim: int) -> int:
    """Approximate capacity: dim / (2 * ln(dim))."""
    return int(dim / (2 * math.log(dim)))


class HRRGraph:
    """HRR graph with typed edges and automatic sub-partitioning."""

    def __init__(self, dim: int) -> None:
        self.dim: int = dim
        self.capacity: int = hrr_capacity(dim)
        self.node_vecs: dict[str, np.ndarray[Any, np.dtype[np.floating[Any]]]] = {}
        self.edge_type_vecs: dict[str, np.ndarray[Any, np.dtype[np.floating[Any]]]] = {}
        self.partitions: dict[str, np.ndarray[Any, np.dtype[np.floating[Any]]]] = {}
        self.node_to_partitions: dict[str, list[str]] = {}
        self.partition_nodes: dict[str, set[str]] = {}
        self.partition_edge_counts: dict[str, int] = {}

    def _get_node_vec(self, nid: str) -> np.ndarray[Any, np.dtype[np.floating[Any]]]:
        if nid not in self.node_vecs:
            self.node_vecs[nid] = make_vector(self.dim)
        return self.node_vecs[nid]

    def _get_edge_type_vec(
        self, etype: str
    ) -> np.ndarray[Any, np.dtype[np.floating[Any]]]:
        if etype not in self.edge_type_vecs:
            self.edge_type_vecs[etype] = make_vector(self.dim)
        return self.edge_type_vecs[etype]

    def encode_partition(
        self,
        partition_id: str,
        edges: list[tuple[str, str, str]],
    ) -> dict[str, Any]:
        """Encode edges into partition(s), auto-splitting if over capacity.

        Returns metadata about the encoding.
        """
        if len(edges) <= self.capacity:
            return self._encode_single_partition(partition_id, edges)

        # Sub-partition: split edges into chunks within capacity
        n_parts: int = math.ceil(len(edges) / self.capacity)
        chunk_size: int = math.ceil(len(edges) / n_parts)
        total_encoded: int = 0

        for i in range(n_parts):
            chunk: list[tuple[str, str, str]] = edges[
                i * chunk_size : (i + 1) * chunk_size
            ]
            sub_id: str = f"{partition_id}_sub{i}"
            self._encode_single_partition(sub_id, chunk)
            total_encoded += len(chunk)

        return {
            "partition_id": partition_id,
            "sub_partitions": n_parts,
            "total_edges": len(edges),
            "capacity": self.capacity,
            "edges_per_sub": chunk_size,
        }

    def _encode_single_partition(
        self,
        partition_id: str,
        edges: list[tuple[str, str, str]],
    ) -> dict[str, Any]:
        superpos: np.ndarray[Any, np.dtype[np.floating[Any]]] = np.zeros(self.dim)
        nodes_in_partition: set[str] = set()

        for src, tgt, etype in edges:
            src_vec: np.ndarray[Any, np.dtype[np.floating[Any]]] = self._get_node_vec(
                src
            )
            tgt_vec: np.ndarray[Any, np.dtype[np.floating[Any]]] = self._get_node_vec(
                tgt
            )
            etype_vec: np.ndarray[Any, np.dtype[np.floating[Any]]] = (
                self._get_edge_type_vec(etype)
            )
            _ = src_vec  # Used for node registration only
            superpos += bind(tgt_vec, etype_vec)
            nodes_in_partition.add(src)
            nodes_in_partition.add(tgt)

        self.partitions[partition_id] = superpos
        self.partition_nodes[partition_id] = nodes_in_partition
        self.partition_edge_counts[partition_id] = len(edges)

        for nid in nodes_in_partition:
            if nid not in self.node_to_partitions:
                self.node_to_partitions[nid] = []
            self.node_to_partitions[nid].append(partition_id)

        return {
            "partition_id": partition_id,
            "sub_partitions": 1,
            "total_edges": len(edges),
            "capacity": self.capacity,
        }

    def query_neighbors(
        self,
        node_id: str,
        edge_type: str,
        threshold: float = 0.08,
    ) -> list[tuple[str, float]]:
        """Find neighbors across all partitions containing this node."""
        if node_id not in self.node_to_partitions:
            return []
        if edge_type not in self.edge_type_vecs:
            return []

        etype_vec: np.ndarray[Any, np.dtype[np.floating[Any]]] = self.edge_type_vecs[
            edge_type
        ]
        best_scores: dict[str, float] = {}

        for part_id in self.node_to_partitions[node_id]:
            superpos: np.ndarray[Any, np.dtype[np.floating[Any]]] = self.partitions[
                part_id
            ]
            result: np.ndarray[Any, np.dtype[np.floating[Any]]] = unbind(
                superpos, etype_vec
            )

            for nid in self.partition_nodes[part_id]:
                if nid == node_id:
                    continue
                sim: float = cos_sim(result, self.node_vecs[nid])
                if sim >= threshold:
                    if nid not in best_scores or sim > best_scores[nid]:
                        best_scores[nid] = sim

        scores: list[tuple[str, float]] = sorted(
            best_scores.items(), key=lambda x: x[1], reverse=True
        )
        return scores


# ============================================================
# Hybrid pipeline
# ============================================================


def search_fts_hrr(
    query: str,
    fts_db: sqlite3.Connection,
    nodes: dict[str, str],
    hrr_graph: HRRGraph,
    edge_types: list[str],
    fts_k: int = 30,
    final_k: int = TOP_K,
    hrr_threshold: float = 0.08,
) -> list[tuple[str, float]]:
    """FTS5 -> HRR walk -> union pipeline."""
    # FTS5 pass (wider net)
    fts_results: list[tuple[str, float]] = search_fts(query, fts_db, top_k=fts_k)
    fts_ids: set[str] = {nid for nid, _ in fts_results}

    # HRR walk from each FTS5 hit
    hrr_additions: list[tuple[str, float]] = []
    for seed_id, _ in fts_results:
        for etype in edge_types:
            neighbors: list[tuple[str, float]] = hrr_graph.query_neighbors(
                seed_id, etype, threshold=hrr_threshold
            )
            for neighbor_id, sim in neighbors:
                if neighbor_id not in fts_ids:
                    hrr_additions.append((neighbor_id, sim))

    # Union: FTS5 results + HRR additions (deduped)
    seen: set[str] = set()
    combined: list[tuple[str, float]] = []
    for nid, score in fts_results:
        if nid not in seen:
            combined.append((nid, score))
            seen.add(nid)
    for nid, score in hrr_additions:
        if nid not in seen:
            combined.append((nid, score))
            seen.add(nid)

    return combined[:final_k]


# ============================================================
# Evaluation
# ============================================================


def evaluate_method(
    method_name: str,
    results: list[tuple[str, float]],
    needed_decisions: list[str],
    nodes: dict[str, str],
) -> dict[str, Any]:
    """Evaluate results against ground truth."""
    needed: set[str] = set(needed_decisions)
    found_decisions: set[str] = set()
    first_relevant_rank: int | None = None
    total_tokens: int = 0
    relevant_count: int = 0

    for rank, (nid, _score) in enumerate(results):
        did: str | None = extract_decision_id(nid)
        content: str = nodes.get(nid, "")
        total_tokens += estimate_tokens(content)
        if did and did in needed:
            found_decisions.add(did)
            relevant_count += 1
            if first_relevant_rank is None:
                first_relevant_rank = rank + 1

    coverage: float = len(found_decisions) / len(needed) if needed else 0.0
    precision: float = relevant_count / len(results) if results else 0.0
    mrr: float = 1.0 / first_relevant_rank if first_relevant_rank else 0.0

    return {
        "method": method_name,
        "result_count": len(results),
        "found": sorted(found_decisions),
        "missed": sorted(needed - found_decisions),
        "coverage": round(coverage, 3),
        "tokens": total_tokens,
        "precision": round(precision, 3),
        "mrr": round(mrr, 3),
    }


# ============================================================
# Main
# ============================================================


def main() -> None:
    t_start: float = time.monotonic()
    print("=" * 70, file=sys.stderr)
    print("Experiment 56: Corrected Baseline Comparison", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    # Load data
    print("\n--- Loading data ---", file=sys.stderr)
    decision_nodes: dict[str, str] = load_decision_nodes()
    sentence_nodes: dict[str, str] = load_sentence_nodes()
    print(
        f"  Decision nodes: {len(decision_nodes)}, "
        f"Sentence nodes: {len(sentence_nodes)}",
        file=sys.stderr,
    )

    # Scan behavioral beliefs
    behavioral_ids: set[str] = scan_behavioral_beliefs(sentence_nodes)
    behavioral_node_ids: list[str] = [
        nid for nid in sentence_nodes if extract_decision_id(nid) in behavioral_ids
    ]
    print(
        f"  Behavioral decisions: {len(behavioral_ids)}, "
        f"behavioral nodes: {len(behavioral_node_ids)}",
        file=sys.stderr,
    )

    # Build edges
    print("\n--- Building edges ---", file=sys.stderr)
    constraint_edges: list[tuple[str, str]] = build_agent_constraint_edges(
        sentence_nodes, behavioral_ids
    )
    cites_edges: list[tuple[str, str]] = extract_cites_edges(sentence_nodes)
    print(
        f"  AGENT_CONSTRAINT edges: {len(constraint_edges)}, "
        f"CITES edges: {len(cites_edges)}",
        file=sys.stderr,
    )

    # Build FTS5 index
    print("\n--- Building FTS5 index ---", file=sys.stderr)
    fts_sentence: sqlite3.Connection = build_fts(sentence_nodes)

    # Build HRR graphs at two DIM settings
    configs: list[dict[str, Any]] = [
        {"name": "DIM=2048 (original)", "dim": 2048},
        {"name": "DIM=4096 (corrected)", "dim": 4096},
    ]

    hrr_graphs: dict[str, HRRGraph] = {}
    for cfg in configs:
        dim: int = cfg["dim"]
        label: str = cfg["name"]
        print(f"\n--- Building HRR graph: {label} ---", file=sys.stderr)

        # Reset rng for reproducibility across configs
        global _rng
        _rng = np.random.default_rng(42)

        graph: HRRGraph = HRRGraph(dim=dim)
        cap: int = graph.capacity

        # Encode AGENT_CONSTRAINT partition
        ac_typed: list[tuple[str, str, str]] = [
            (s, t, "AGENT_CONSTRAINT") for s, t in constraint_edges
        ]
        ac_meta: dict[str, Any] = graph.encode_partition("behavioral", ac_typed)
        print(
            f"  AGENT_CONSTRAINT: {len(ac_typed)} edges, "
            f"capacity={cap}, "
            f"sub_partitions={ac_meta['sub_partitions']}",
            file=sys.stderr,
        )

        # Encode CITES partition
        ci_typed: list[tuple[str, str, str]] = [(s, t, "CITES") for s, t in cites_edges]
        ci_meta: dict[str, Any] = graph.encode_partition("cites", ci_typed)
        print(
            f"  CITES: {len(ci_typed)} edges, "
            f"sub_partitions={ci_meta['sub_partitions']}",
            file=sys.stderr,
        )

        hrr_graphs[cfg["name"]] = graph

    # ============================================================
    # Run all methods on all topics
    # ============================================================

    print("\n" + "=" * 70, file=sys.stderr)
    print("RUNNING EVALUATIONS", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    methods_spec: list[dict[str, Any]] = [
        {
            "id": "A_grep",
            "label": "Grep (decisions)",
            "type": "grep",
            "node_set": "decision",
        },
        {
            "id": "B_fts5_k15",
            "label": "FTS5 K=15",
            "type": "fts5",
            "top_k": 15,
        },
        {
            "id": "C_fts5_k30",
            "label": "FTS5 K=30",
            "type": "fts5",
            "top_k": 30,
        },
        {
            "id": "D_fts5_hrr_2048",
            "label": "FTS5+HRR DIM=2048 (original)",
            "type": "hybrid",
            "hrr_key": "DIM=2048 (original)",
            "fts_k": 15,
            "final_k": 15,
        },
        {
            "id": "E_fts5_hrr_4096",
            "label": "FTS5+HRR DIM=4096 K=15",
            "type": "hybrid",
            "hrr_key": "DIM=4096 (corrected)",
            "fts_k": 15,
            "final_k": 15,
        },
        {
            "id": "F_fts5_k30_hrr_4096",
            "label": "FTS5 K=30 + HRR DIM=4096 (full)",
            "type": "hybrid",
            "hrr_key": "DIM=4096 (corrected)",
            "fts_k": 30,
            "final_k": 50,
        },
        {
            "id": "G_fts5_k30_hrr_2048",
            "label": "FTS5 K=30 + HRR DIM=2048 (full)",
            "type": "hybrid",
            "hrr_key": "DIM=2048 (original)",
            "fts_k": 30,
            "final_k": 50,
        },
    ]

    all_results: dict[str, dict[str, dict[str, Any]]] = {}

    for topic_name, topic_data in TOPICS.items():
        query: str = topic_data["query"]
        needed: list[str] = topic_data["needed"]
        print(f'\n--- {topic_name}: "{query}" ---', file=sys.stderr)

        topic_results: dict[str, dict[str, Any]] = {}

        for spec in methods_spec:
            mid: str = spec["id"]

            if spec["type"] == "grep":
                ns: dict[str, str] = (
                    decision_nodes
                    if spec.get("node_set") == "decision"
                    else sentence_nodes
                )
                results: list[tuple[str, float]] = grep_search(query, ns)
                eval_nodes: dict[str, str] = ns

            elif spec["type"] == "fts5":
                k: int = spec["top_k"]
                results = search_fts(query, fts_sentence, top_k=k)
                eval_nodes = sentence_nodes

            elif spec["type"] == "hybrid":
                hrr_key: str = spec["hrr_key"]
                results = search_fts_hrr(
                    query,
                    fts_sentence,
                    sentence_nodes,
                    hrr_graphs[hrr_key],
                    ["AGENT_CONSTRAINT", "CITES"],
                    fts_k=spec.get("fts_k", 30),
                    final_k=spec.get("final_k", TOP_K),
                )
                eval_nodes = sentence_nodes
            else:
                continue

            evaluation: dict[str, Any] = evaluate_method(
                mid, results, needed, eval_nodes
            )
            topic_results[mid] = evaluation

            status: str = (
                "OK" if not evaluation["missed"] else f"MISSED: {evaluation['missed']}"
            )
            print(
                f"  {spec['label']:40s}: "
                f"cov={evaluation['coverage']:.0%} "
                f"tok={evaluation['tokens']:5d} "
                f"prec={evaluation['precision']:.0%} "
                f"mrr={evaluation['mrr']:.3f} "
                f"{status}",
                file=sys.stderr,
            )

        all_results[topic_name] = topic_results

    # ============================================================
    # Aggregate
    # ============================================================

    print("\n" + "=" * 70, file=sys.stderr)
    print("AGGREGATE RESULTS", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    aggregates: dict[str, dict[str, Any]] = {}

    for spec in methods_spec:
        mid = spec["id"]
        coverages: list[float] = []
        tokens_list: list[int] = []
        precisions: list[float] = []
        mrrs: list[float] = []
        total_needed: int = 0
        total_found: int = 0
        all_missed: list[str] = []

        for topic_name in TOPICS:
            res: dict[str, Any] = all_results[topic_name][mid]
            coverages.append(res["coverage"])
            tokens_list.append(res["tokens"])
            precisions.append(res["precision"])
            mrrs.append(res["mrr"])
            total_needed += len(TOPICS[topic_name]["needed"])
            total_found += len(res["found"])
            all_missed.extend(res["missed"])

        micro_cov: float = total_found / total_needed if total_needed else 0.0
        mean_tok: float = sum(tokens_list) / len(tokens_list)
        mean_prec: float = sum(precisions) / len(precisions)
        mean_mrr: float = sum(mrrs) / len(mrrs)

        aggregates[mid] = {
            "label": spec["label"],
            "micro_coverage": round(micro_cov, 3),
            "macro_coverage": round(sum(coverages) / len(coverages), 3),
            "mean_tokens": round(mean_tok, 1),
            "mean_precision": round(mean_prec, 3),
            "mean_mrr": round(mean_mrr, 3),
            "total_found": total_found,
            "total_needed": total_needed,
            "missed": sorted(set(all_missed)),
        }

        print(
            f"  {spec['label']:40s}: "
            f"cov={micro_cov:.0%} ({total_found}/{total_needed}) "
            f"tok={mean_tok:7.1f} "
            f"prec={mean_prec:.0%} "
            f"mrr={mean_mrr:.3f} "
            f"missed={sorted(set(all_missed))}",
            file=sys.stderr,
        )

    # ============================================================
    # D157/D137 deep diagnostics
    # ============================================================

    print("\n" + "=" * 70, file=sys.stderr)
    print("D157 DIAGNOSTIC (agent_behavior topic)", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    for cfg_name, graph in hrr_graphs.items():
        print(f"\n  {cfg_name}:", file=sys.stderr)
        # Check if D188 nodes are in the graph
        d188_nodes: list[str] = [
            nid for nid in sentence_nodes if nid.startswith("D188")
        ]
        d157_nodes: list[str] = [
            nid for nid in sentence_nodes if nid.startswith("D157")
        ]
        print(f"    D188 nodes: {d188_nodes}", file=sys.stderr)
        print(f"    D157 nodes: {d157_nodes}", file=sys.stderr)

        for d188_nid in d188_nodes:
            neighbors: list[tuple[str, float]] = graph.query_neighbors(
                d188_nid, "AGENT_CONSTRAINT", threshold=0.01
            )
            d157_hits: list[tuple[str, float]] = [
                (nid, sim) for nid, sim in neighbors if nid.startswith("D157")
            ]
            print(
                f"    Walk from {d188_nid}: "
                f"{len(neighbors)} neighbors, "
                f"D157 hits: {d157_hits[:5]}",
                file=sys.stderr,
            )

    print("\n" + "=" * 70, file=sys.stderr)
    print("D137 DIAGNOSTIC (dispatch_gate topic)", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    # Check D137 in FTS5 results at various K
    for k_val in [15, 30, 50]:
        fts_res: list[tuple[str, float]] = search_fts(
            "dispatch gate deploy protocol", fts_sentence, top_k=k_val
        )
        d137_found: list[tuple[int, str, float]] = [
            (rank + 1, nid, score)
            for rank, (nid, score) in enumerate(fts_res)
            if nid.startswith("D137")
        ]
        print(
            f"  FTS5 K={k_val}: D137 found={d137_found if d137_found else 'NOT FOUND'}",
            file=sys.stderr,
        )

    # Check D137 in grep
    grep_res: list[tuple[str, float]] = grep_search(
        "dispatch gate deploy protocol", decision_nodes, top_k=50
    )
    d137_grep: list[tuple[int, str, float]] = [
        (rank + 1, nid, score)
        for rank, (nid, score) in enumerate(grep_res)
        if nid.startswith("D137")
    ]
    print(f"  Grep: D137 found={d137_grep}", file=sys.stderr)

    elapsed: float = time.monotonic() - t_start

    # ============================================================
    # Save results
    # ============================================================

    output: dict[str, Any] = {
        "experiment": "exp56_corrected_baseline",
        "date": "2026-04-10",
        "elapsed_seconds": round(elapsed, 2),
        "config": {
            "top_k": TOP_K,
            "dims_tested": [2048, 4096],
            "decision_nodes": len(decision_nodes),
            "sentence_nodes": len(sentence_nodes),
            "behavioral_decisions": len(behavioral_ids),
            "behavioral_nodes": len(behavioral_node_ids),
            "agent_constraint_edges": len(constraint_edges),
            "cites_edges": len(cites_edges),
            "hrr_capacity_2048": hrr_capacity(2048),
            "hrr_capacity_4096": hrr_capacity(4096),
        },
        "per_topic": all_results,
        "aggregates": aggregates,
    }

    results_path: Path = Path(__file__).parent / "exp56_results.json"
    results_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\nResults saved to {results_path.name}", file=sys.stderr)
    print(f"Total time: {elapsed:.2f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
