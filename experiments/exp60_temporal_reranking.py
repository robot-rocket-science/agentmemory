"""Exp 60: Temporal Re-ranking Integration with FTS5+HRR

Tests whether adding temporal re-ranking as a post-retrieval step improves or
degrades the Exp 56 pipeline (FTS5 K=30 + HRR DIM=2048, 100% coverage).

Re-ranking strategies tested:
  A. NO_RERANK   -- Exp 56 results as-is (baseline)
  B. DECAY_RERANK -- position score * content-aware decay factor
  C. LOCK_BOOST   -- locked/behavioral beliefs boosted above non-locked
  D. LOCK_BOOST_TYPED -- lock boost + type weight for scope-matching decisions

Key questions:
  1. Does re-ranking change coverage? (Should NOT decrease from 100%)
  2. Does lock boosting improve MRR for behavioral beliefs?
  3. Does decay demote stale irrelevant results, improving precision?

Evaluated at K=15 and K=30.

Data: alpha-seek.db
  - Decision timestamps derived from DECIDED_IN -> milestone.created_at
  - Content type classified from decisions.scope
  - Locked status from decisions.revisable
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from math import exp, log
from pathlib import Path
from typing import Any, Final

import numpy as np

# ============================================================
# Config
# ============================================================

ALPHA_SEEK_DB: Final[Path] = Path(
    "/Users/thelorax/projects/.gsd/workflows/spikes/"
    "260406-1-associative-memory-for-gsd-please-explor/"
    "sandbox/alpha-seek.db"
)

HRR_DIM: Final[int] = 2048
FTS_K: Final[int] = 30
FINAL_K: Final[int] = 50
EVAL_K_VALUES: Final[list[int]] = [15, 30]
HRR_THRESHOLD: Final[float] = 0.08

RNG: np.random.Generator = np.random.default_rng(42)

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

KNOWN_BEHAVIORAL: Final[list[str]] = ["D157", "D188", "D100", "D073"]

STOPWORDS: Final[frozenset[str]] = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "can", "could", "must", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "but",
    "and", "or", "nor", "not", "no", "so", "if", "then", "than",
    "too", "very", "just", "about", "up", "out", "off", "over",
    "under", "again", "further", "once", "here", "there", "when",
    "where", "why", "how", "all", "each", "every", "both", "few",
    "more", "most", "other", "some", "such", "only", "own", "same",
    "that", "this", "these", "those", "what", "which", "who", "whom",
    "it", "its", "he", "she", "they", "them", "his", "her", "their",
    "we", "us", "our", "you", "your", "i", "me", "my",
})

DIRECTIVE_PATTERNS: Final[list[re.Pattern[str]]] = [
    re.compile(r"\bBANNED\b"),
    re.compile(r"\bNever\s+use\b", re.IGNORECASE),
    re.compile(r"\bNever\s+\w+\b"),
    re.compile(r"\balways\s+\w+\b", re.IGNORECASE),
    re.compile(r"\bmust\s+not\b", re.IGNORECASE),
    re.compile(r"\bdo\s+not\b", re.IGNORECASE),
    re.compile(r"\bdon't\b", re.IGNORECASE),
]

# Content-aware decay half-lives in days (None = never decays)
DECAY_HALF_LIVES: Final[dict[str, float | None]] = {
    "constraint": None,
    "evidence": 14.0,
    "context": 3.0,
    "rationale": 30.0,
    "procedure": 21.0,
}

# Scope -> content type mapping
SCOPE_TO_CONTENT_TYPE: Final[dict[str, str]] = {
    "architecture": "constraint",
    "agent behavior": "constraint",
    "operations": "procedure",
    "code-quality": "constraint",
    "infrastructure": "constraint",
    "tooling": "constraint",
    "configuration": "constraint",
    "methodology": "constraint",
    "strategy": "rationale",
    "signal-model": "evidence",
    "backtesting": "evidence",
    "validation": "evidence",
    "evaluation": "evidence",
    "data": "evidence",
    "hypothesis": "evidence",
    "algorithm": "evidence",
    "generative-model": "evidence",
    "backtest": "evidence",
    "fill-model": "evidence",
    "exit-algorithm": "evidence",
    "milestone": "context",
    "bugfix": "context",
    "reporting": "context",
    "documentation": "context",
    "naming": "context",
    "strategy framing": "rationale",
    "data-source": "evidence",
    "execution": "procedure",
}

# Topic scope keywords for type-aware re-ranking
TOPIC_SCOPE_KEYWORDS: Final[dict[str, list[str]]] = {
    "dispatch_gate": ["operations", "procedure"],
    "calls_puts": ["strategy"],
    "capital_5k": ["strategy", "constraint"],
    "agent_behavior": ["agent behavior", "tooling"],
    "strict_typing": ["code-quality"],
    "gcp_primary": ["infrastructure"],
}


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class DecisionMeta:
    """Temporal and classification metadata for a decision."""
    decision_id: str
    scope: str
    content_type: str
    revisable: bool
    locked: bool          # revisable=False means locked
    timestamp_iso: str | None
    age_days: float       # age relative to current_time


@dataclass
class RankedResult:
    """A single result in the pipeline output, with re-ranking metadata."""
    node_id: str
    decision_id: str | None
    retrieval_score: float
    position: int            # 1-based rank from pipeline output
    position_score: float    # 1.0 at rank 1, decaying to 0.5 at rank N
    content_type: str
    age_days: float
    decay: float
    locked: bool
    rerank_score: float = field(default=0.0)


# ============================================================
# Data loading
# ============================================================

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


def _parse_iso_to_epoch(iso: str) -> float:
    """Parse ISO 8601 UTC string to Unix timestamp (seconds)."""
    import datetime
    # Remove trailing Z, parse
    cleaned: str = iso.rstrip("Z").replace("T", " ")
    dt: datetime.datetime = datetime.datetime.fromisoformat(cleaned)
    return dt.replace(tzinfo=datetime.timezone.utc).timestamp()


def load_decision_metadata(current_time_epoch: float) -> dict[str, DecisionMeta]:
    """Load scope, revisable, and derived timestamp for all decisions.

    Timestamp is derived from the EARLIEST DECIDED_IN milestone's created_at.
    Decisions without a DECIDED_IN edge get no timestamp (age = 0).
    """
    db: sqlite3.Connection = sqlite3.connect(str(ALPHA_SEEK_DB))

    # Load decisions: id, scope, revisable
    decisions_raw: dict[str, tuple[str, str]] = {}
    for row in db.execute("SELECT id, scope, revisable FROM decisions"):
        did: str = str(row[0])
        scope: str = str(row[1]) if row[1] else ""
        revisable_str: str = str(row[2]) if row[2] else "Yes"
        decisions_raw[did] = (scope, revisable_str)

    # Load DECIDED_IN -> milestone.created_at for all decisions
    # Milestone IDs in mem_edges use prefix '_M###', milestones table uses 'M###-suffix'
    # We join on: milestone.id LIKE substr(edge.to_id, 2) || '%'
    decision_timestamps: dict[str, float] = {}
    for row in db.execute(
        """
        SELECT e.from_id, MIN(m.created_at)
        FROM mem_edges e
        JOIN milestones m ON m.id LIKE (SUBSTR(e.to_id, 2) || '%')
        WHERE e.edge_type = 'DECIDED_IN'
          AND e.from_id LIKE 'D%'
        GROUP BY e.from_id
        """
    ):
        did = str(row[0])
        if row[1] is not None:
            decision_timestamps[did] = _parse_iso_to_epoch(str(row[1]))

    db.close()

    SECS_PER_DAY: float = 86400.0
    result: dict[str, DecisionMeta] = {}

    for did, (scope, revisable_str) in decisions_raw.items():
        content_type: str = SCOPE_TO_CONTENT_TYPE.get(scope, "rationale")

        # revisable=No or contains "No" means locked
        locked: bool = revisable_str.strip().lower().startswith("no")

        ts_epoch: float | None = decision_timestamps.get(did)
        if ts_epoch is not None:
            age_days: float = (current_time_epoch - ts_epoch) / SECS_PER_DAY
            age_days = max(0.0, age_days)
            timestamp_iso: str | None = (
                None  # not needed for output; could compute from ts_epoch
            )
        else:
            age_days = 0.0
            timestamp_iso = None

        result[did] = DecisionMeta(
            decision_id=did,
            scope=scope,
            content_type=content_type,
            revisable=not locked,
            locked=locked,
            timestamp_iso=timestamp_iso,
            age_days=age_days,
        )

    return result


def get_current_time_epoch() -> float:
    """Return Unix epoch for latest milestone + 1 day (simulated 'now')."""
    db: sqlite3.Connection = sqlite3.connect(str(ALPHA_SEEK_DB))
    row: Any = db.execute(
        "SELECT MAX(created_at) FROM milestones"
    ).fetchone()
    db.close()
    latest_iso: str = str(row[0])
    latest_epoch: float = _parse_iso_to_epoch(latest_iso)
    return latest_epoch + 86400.0  # +1 day


# ============================================================
# Utility: extract decision ID from node ID
# ============================================================

def extract_decision_id(node_id: str) -> str | None:
    """Extract D### from a node ID like D097_s3."""
    m: re.Match[str] | None = re.match(r"(D\d{3})", node_id)
    return m.group(1) if m else None


def estimate_tokens(text: str) -> int:
    """Rough token estimate: chars / 4."""
    return max(1, len(text) // 4)


# ============================================================
# Behavioral belief detection
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


# ============================================================
# FTS5
# ============================================================

def build_fts(nodes: dict[str, str]) -> sqlite3.Connection:
    """Build in-memory FTS5 index with porter stemming."""
    db: sqlite3.Connection = sqlite3.connect(":memory:")
    db.execute(
        "CREATE VIRTUAL TABLE fts USING fts5(id, content, tokenize='porter')"
    )
    for nid, content in nodes.items():
        db.execute("INSERT INTO fts VALUES (?, ?)", (nid, content))
    db.commit()
    return db


def search_fts(
    query: str,
    fts_db: sqlite3.Connection,
    top_k: int,
) -> list[tuple[str, float]]:
    """FTS5 search with OR terms."""
    terms: list[str] = [t.strip() for t in query.split() if len(t.strip()) > 2]
    if not terms:
        return []
    fts_query: str = " OR ".join(terms)
    results: list[tuple[str, float]] = [
        (str(r[0]), float(r[1]))
        for r in fts_db.execute(
            "SELECT id, bm25(fts) FROM fts WHERE fts MATCH ? "
            "ORDER BY bm25(fts) LIMIT ?",
            (fts_query, top_k),
        ).fetchall()
    ]
    return results


# ============================================================
# Graph construction
# ============================================================

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
        nid for nid in nodes
        if extract_decision_id(nid) in behavioral_ids
    ]
    edges: list[tuple[str, str]] = []
    for i, a in enumerate(behavioral_nodes):
        for b in behavioral_nodes[i + 1 :]:
            edges.append((a, b))
            edges.append((b, a))
    return edges


# ============================================================
# HRR engine (from exp56_corrected_baseline.py)
# ============================================================

def make_vector(dim: int) -> np.ndarray[Any, np.dtype[np.floating[Any]]]:
    """Random unit vector."""
    v: np.ndarray[Any, np.dtype[np.floating[Any]]] = RNG.standard_normal(dim)
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

    def _get_edge_type_vec(self, etype: str) -> np.ndarray[Any, np.dtype[np.floating[Any]]]:
        if etype not in self.edge_type_vecs:
            self.edge_type_vecs[etype] = make_vector(self.dim)
        return self.edge_type_vecs[etype]

    def encode_partition(
        self,
        partition_id: str,
        edges: list[tuple[str, str, str]],
    ) -> dict[str, Any]:
        """Encode edges into partition(s), auto-splitting if over capacity."""
        if len(edges) <= self.capacity:
            return self._encode_single_partition(partition_id, edges)

        n_parts: int = math.ceil(len(edges) / self.capacity)
        chunk_size: int = math.ceil(len(edges) / n_parts)
        total_encoded: int = 0

        for i in range(n_parts):
            chunk: list[tuple[str, str, str]] = edges[i * chunk_size : (i + 1) * chunk_size]
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
            src_vec: np.ndarray[Any, np.dtype[np.floating[Any]]] = self._get_node_vec(src)
            tgt_vec: np.ndarray[Any, np.dtype[np.floating[Any]]] = self._get_node_vec(tgt)
            etype_vec: np.ndarray[Any, np.dtype[np.floating[Any]]] = self._get_edge_type_vec(etype)
            _ = src_vec  # registered via _get_node_vec
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

        etype_vec: np.ndarray[Any, np.dtype[np.floating[Any]]] = self.edge_type_vecs[edge_type]
        best_scores: dict[str, float] = {}

        for part_id in self.node_to_partitions[node_id]:
            superpos: np.ndarray[Any, np.dtype[np.floating[Any]]] = self.partitions[part_id]
            result: np.ndarray[Any, np.dtype[np.floating[Any]]] = unbind(superpos, etype_vec)

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
# Hybrid pipeline (identical to Exp 56 FTS K=30 + HRR DIM=2048)
# ============================================================

def search_fts_hrr(
    query: str,
    fts_db: sqlite3.Connection,
    nodes: dict[str, str],
    hrr_graph: HRRGraph,
    edge_types: list[str],
    fts_k: int = FTS_K,
    final_k: int = FINAL_K,
    hrr_threshold: float = HRR_THRESHOLD,
) -> list[tuple[str, float]]:
    """FTS5 -> HRR walk -> union pipeline (Exp 56 method G/F)."""
    fts_results: list[tuple[str, float]] = search_fts(query, fts_db, top_k=fts_k)
    fts_ids: set[str] = {nid for nid, _ in fts_results}

    hrr_additions: list[tuple[str, float]] = []
    for seed_id, _ in fts_results:
        for etype in edge_types:
            neighbors: list[tuple[str, float]] = hrr_graph.query_neighbors(
                seed_id, etype, threshold=hrr_threshold
            )
            for neighbor_id, sim in neighbors:
                if neighbor_id not in fts_ids:
                    hrr_additions.append((neighbor_id, sim))

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
# Temporal scoring
# ============================================================

def compute_decay_factor(
    content_type: str,
    age_days: float,
    locked: bool,
) -> float:
    """Content-aware exponential decay (Exp 57 Model 2)."""
    if locked:
        return 1.0
    half_life: float | None = DECAY_HALF_LIVES.get(content_type)
    if half_life is None:
        return 1.0
    if age_days <= 0.0:
        return 1.0
    return exp(-log(2) / half_life * age_days)


def annotate_results(
    pipeline_results: list[tuple[str, float]],
    decision_meta: dict[str, DecisionMeta],
    behavioral_ids: set[str],
) -> list[RankedResult]:
    """Attach temporal metadata to pipeline results."""
    n: int = len(pipeline_results)
    annotated: list[RankedResult] = []

    for position, (nid, score) in enumerate(pipeline_results, start=1):
        did: str | None = extract_decision_id(nid)
        position_score: float = 1.0 - 0.5 * (position - 1) / max(n - 1, 1)

        if did and did in decision_meta:
            meta: DecisionMeta = decision_meta[did]
            content_type: str = meta.content_type
            age_days: float = meta.age_days
            locked: bool = meta.locked or (did in behavioral_ids)
        else:
            content_type = "rationale"
            age_days = 0.0
            locked = False

        decay: float = compute_decay_factor(content_type, age_days, locked)

        annotated.append(RankedResult(
            node_id=nid,
            decision_id=did,
            retrieval_score=score,
            position=position,
            position_score=position_score,
            content_type=content_type,
            age_days=age_days,
            decay=decay,
            locked=locked,
            rerank_score=0.0,
        ))

    return annotated


# ============================================================
# Re-ranking strategies
# ============================================================

def rerank_no_rerank(annotated: list[RankedResult]) -> list[RankedResult]:
    """Strategy A: identity -- preserve pipeline order."""
    result: list[RankedResult] = list(annotated)
    for item in result:
        item.rerank_score = item.position_score
    return result


def rerank_decay(annotated: list[RankedResult]) -> list[RankedResult]:
    """Strategy B: position_score * decay_factor."""
    result: list[RankedResult] = list(annotated)
    for item in result:
        item.rerank_score = item.position_score * item.decay
    result.sort(key=lambda x: x.rerank_score, reverse=True)
    return result


def rerank_lock_boost(annotated: list[RankedResult]) -> list[RankedResult]:
    """Strategy C: locked/behavioral beliefs boosted to score >= 2.0."""
    result: list[RankedResult] = list(annotated)
    for item in result:
        if item.locked:
            item.rerank_score = 2.0 + item.decay
        else:
            item.rerank_score = item.position_score * item.decay
    result.sort(key=lambda x: x.rerank_score, reverse=True)
    return result


def rerank_lock_boost_typed(
    annotated: list[RankedResult],
    topic_name: str,
    decision_meta: dict[str, DecisionMeta],
) -> list[RankedResult]:
    """Strategy D: lock boost + 1.5x weight for scope-matching decisions."""
    scope_keywords: list[str] = TOPIC_SCOPE_KEYWORDS.get(topic_name, [])
    result: list[RankedResult] = list(annotated)

    for item in result:
        # Determine type weight
        type_weight: float = 1.0
        if item.decision_id and item.decision_id in decision_meta:
            scope: str = decision_meta[item.decision_id].scope
            if scope in scope_keywords:
                type_weight = 1.5

        if item.locked:
            item.rerank_score = (2.0 + item.decay) * type_weight
        else:
            item.rerank_score = item.position_score * item.decay * type_weight

    result.sort(key=lambda x: x.rerank_score, reverse=True)
    return result


# ============================================================
# Evaluation
# ============================================================

@dataclass
class TopicEval:
    """Evaluation result for one topic at one K."""
    topic: str
    strategy: str
    k: int
    coverage: float
    mrr: float
    precision_at_k: float
    tokens: int
    found: list[str]
    missed: list[str]
    behavioral_mrr: float    # MRR restricted to KNOWN_BEHAVIORAL decisions


def evaluate_at_k(
    topic_name: str,
    strategy_name: str,
    ranked: list[RankedResult],
    needed_decisions: list[str],
    nodes: dict[str, str],
    k: int,
) -> TopicEval:
    """Evaluate ranked results at cutoff K."""
    needed: set[str] = set(needed_decisions)
    behavioral_needed: set[str] = {d for d in needed if d in KNOWN_BEHAVIORAL}

    cutoff: list[RankedResult] = ranked[:k]

    found_decisions: set[str] = set()
    first_relevant_rank: int | None = None
    first_behavioral_rank: int | None = None
    total_tokens: int = 0
    relevant_count: int = 0

    for rank, item in enumerate(cutoff, start=1):
        content: str = nodes.get(item.node_id, "")
        total_tokens += estimate_tokens(content)
        did: str | None = item.decision_id
        if did and did in needed:
            found_decisions.add(did)
            relevant_count += 1
            if first_relevant_rank is None:
                first_relevant_rank = rank
        if did and did in behavioral_needed and first_behavioral_rank is None:
            first_behavioral_rank = rank

    coverage: float = len(found_decisions) / len(needed) if needed else 0.0
    precision_at_k: float = relevant_count / k if k > 0 else 0.0
    mrr: float = 1.0 / first_relevant_rank if first_relevant_rank else 0.0
    behavioral_mrr: float = (
        1.0 / first_behavioral_rank if first_behavioral_rank else 0.0
    )

    return TopicEval(
        topic=topic_name,
        strategy=strategy_name,
        k=k,
        coverage=round(coverage, 3),
        mrr=round(mrr, 3),
        precision_at_k=round(precision_at_k, 3),
        tokens=total_tokens,
        found=sorted(found_decisions),
        missed=sorted(needed - found_decisions),
        behavioral_mrr=round(behavioral_mrr, 3),
    )


# ============================================================
# Aggregate
# ============================================================

def aggregate_evals(
    evals: list[TopicEval],
    strategy_name: str,
    k: int,
) -> dict[str, Any]:
    """Compute aggregate metrics across all topics for one strategy/K."""
    topic_evals: list[TopicEval] = [
        e for e in evals if e.strategy == strategy_name and e.k == k
    ]
    total_needed: int = sum(
        len(TOPICS[e.topic]["needed"]) for e in topic_evals
    )
    total_found: int = sum(len(e.found) for e in topic_evals)
    all_missed: list[str] = sorted({d for e in topic_evals for d in e.missed})
    mean_mrr: float = sum(e.mrr for e in topic_evals) / len(topic_evals)
    mean_prec: float = sum(e.precision_at_k for e in topic_evals) / len(topic_evals)
    mean_tokens: float = sum(e.tokens for e in topic_evals) / len(topic_evals)
    mean_beh_mrr: float = (
        sum(e.behavioral_mrr for e in topic_evals) / len(topic_evals)
    )

    return {
        "strategy": strategy_name,
        "k": k,
        "micro_coverage": round(total_found / total_needed, 3) if total_needed else 0.0,
        "macro_coverage": round(
            sum(e.coverage for e in topic_evals) / len(topic_evals), 3
        ),
        "total_found": total_found,
        "total_needed": total_needed,
        "mean_mrr": round(mean_mrr, 3),
        "mean_precision_at_k": round(mean_prec, 3),
        "mean_tokens": round(mean_tokens, 1),
        "mean_behavioral_mrr": round(mean_beh_mrr, 3),
        "missed": all_missed,
        "topic_details": [
            {
                "topic": e.topic,
                "coverage": e.coverage,
                "mrr": e.mrr,
                "precision_at_k": e.precision_at_k,
                "tokens": e.tokens,
                "found": e.found,
                "missed": e.missed,
                "behavioral_mrr": e.behavioral_mrr,
            }
            for e in topic_evals
        ],
    }


# ============================================================
# Main
# ============================================================

def main() -> None:
    t_start: float = time.monotonic()
    print("=" * 70, file=sys.stderr)
    print("Experiment 60: Temporal Re-ranking Integration with FTS5+HRR", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    # --- Load data ---
    print("\n--- Loading data ---", file=sys.stderr)
    sentence_nodes: dict[str, str] = load_sentence_nodes()
    print(f"  Sentence nodes: {len(sentence_nodes)}", file=sys.stderr)

    current_time_epoch: float = get_current_time_epoch()

    import datetime
    current_time_dt: datetime.datetime = datetime.datetime.fromtimestamp(
        current_time_epoch, tz=datetime.timezone.utc
    )
    print(
        f"  Simulated current_time: {current_time_dt.isoformat()} "
        f"(latest milestone + 1 day)",
        file=sys.stderr,
    )

    decision_meta: dict[str, DecisionMeta] = load_decision_metadata(current_time_epoch)
    print(f"  Decisions with metadata: {len(decision_meta)}", file=sys.stderr)

    decisions_with_ts: int = sum(
        1 for m in decision_meta.values() if m.age_days > 0.0
    )
    locked_count: int = sum(1 for m in decision_meta.values() if m.locked)
    print(
        f"  Decisions with timestamp: {decisions_with_ts}, locked: {locked_count}",
        file=sys.stderr,
    )

    # Print temporal metadata for ground truth decisions
    print("\n  Ground truth decision metadata:", file=sys.stderr)
    gt_decisions: list[str] = sorted({
        d for t in TOPICS.values() for d in t["needed"]
    })
    for did in gt_decisions:
        if did in decision_meta:
            m: DecisionMeta = decision_meta[did]
            print(
                f"    {did}: scope={m.scope!r:20s} "
                f"type={m.content_type:12s} "
                f"locked={m.locked} "
                f"age={m.age_days:.1f}d",
                file=sys.stderr,
            )
        else:
            print(f"    {did}: NO METADATA", file=sys.stderr)

    # --- Behavioral beliefs ---
    behavioral_ids: set[str] = scan_behavioral_beliefs(sentence_nodes)
    behavioral_node_ids: list[str] = [
        nid for nid in sentence_nodes
        if extract_decision_id(nid) in behavioral_ids
    ]
    print(
        f"\n  Behavioral decisions: {len(behavioral_ids)}, "
        f"nodes: {len(behavioral_node_ids)}",
        file=sys.stderr,
    )

    # --- Build FTS5 index ---
    print("\n--- Building FTS5 index ---", file=sys.stderr)
    fts_db: sqlite3.Connection = build_fts(sentence_nodes)

    # --- Build HRR graph (DIM=2048, same as Exp 56 method G) ---
    print(f"\n--- Building HRR graph (DIM={HRR_DIM}) ---", file=sys.stderr)
    global RNG
    RNG = np.random.default_rng(42)
    hrr_graph: HRRGraph = HRRGraph(dim=HRR_DIM)

    constraint_edges: list[tuple[str, str]] = build_agent_constraint_edges(
        sentence_nodes, behavioral_ids
    )
    cites_edges: list[tuple[str, str]] = extract_cites_edges(sentence_nodes)

    ac_typed: list[tuple[str, str, str]] = [
        (s, t, "AGENT_CONSTRAINT") for s, t in constraint_edges
    ]
    ci_typed: list[tuple[str, str, str]] = [
        (s, t, "CITES") for s, t in cites_edges
    ]

    ac_meta: dict[str, Any] = hrr_graph.encode_partition("behavioral", ac_typed)
    ci_meta: dict[str, Any] = hrr_graph.encode_partition("cites", ci_typed)

    print(
        f"  AGENT_CONSTRAINT: {len(ac_typed)} edges, "
        f"sub_partitions={ac_meta['sub_partitions']}",
        file=sys.stderr,
    )
    print(
        f"  CITES: {len(ci_typed)} edges, "
        f"sub_partitions={ci_meta['sub_partitions']}",
        file=sys.stderr,
    )

    # --- Run pipeline on all topics ---
    print("\n" + "=" * 70, file=sys.stderr)
    print("RUNNING PIPELINE + RE-RANKING", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    STRATEGIES: list[str] = [
        "NO_RERANK",
        "DECAY_RERANK",
        "LOCK_BOOST",
        "LOCK_BOOST_TYPED",
    ]

    all_evals: list[TopicEval] = []
    # Also keep raw pipeline results per topic for diagnostics
    pipeline_results_by_topic: dict[str, list[tuple[str, float]]] = {}

    for topic_name, topic_data in TOPICS.items():
        query: str = topic_data["query"]
        needed: list[str] = topic_data["needed"]
        print(f'\n--- {topic_name}: "{query}" ---', file=sys.stderr)

        # Run Exp 56 pipeline once per topic
        pipeline_out: list[tuple[str, float]] = search_fts_hrr(
            query,
            fts_db,
            sentence_nodes,
            hrr_graph,
            ["AGENT_CONSTRAINT", "CITES"],
            fts_k=FTS_K,
            final_k=FINAL_K,
        )
        pipeline_results_by_topic[topic_name] = pipeline_out

        # Annotate with temporal metadata
        annotated: list[RankedResult] = annotate_results(
            pipeline_out, decision_meta, behavioral_ids
        )

        # Apply each re-ranking strategy
        strategy_results: dict[str, list[RankedResult]] = {
            "NO_RERANK": rerank_no_rerank(list(annotated)),
            "DECAY_RERANK": rerank_decay(list(annotated)),
            "LOCK_BOOST": rerank_lock_boost(list(annotated)),
            "LOCK_BOOST_TYPED": rerank_lock_boost_typed(
                list(annotated), topic_name, decision_meta
            ),
        }

        for strategy_name, ranked in strategy_results.items():
            for k in EVAL_K_VALUES:
                ev: TopicEval = evaluate_at_k(
                    topic_name,
                    strategy_name,
                    ranked,
                    needed,
                    sentence_nodes,
                    k,
                )
                all_evals.append(ev)

        # Print summary for K=15
        for strategy_name, ranked in strategy_results.items():
            k15: list[RankedResult] = ranked[:15]
            found_15: set[str] = {
                item.decision_id
                for item in k15
                if item.decision_id and item.decision_id in set(needed)
            }
            missed_15: set[str] = set(needed) - found_15
            print(
                f"  {strategy_name:20s} K=15: "
                f"found={sorted(found_15)} "
                f"missed={sorted(missed_15)}",
                file=sys.stderr,
            )

    # --- Aggregate results ---
    print("\n" + "=" * 70, file=sys.stderr)
    print("AGGREGATE RESULTS", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    aggregates: dict[str, dict[str, Any]] = {}

    for strategy_name in STRATEGIES:
        for k in EVAL_K_VALUES:
            agg: dict[str, Any] = aggregate_evals(all_evals, strategy_name, k)
            key: str = f"{strategy_name}_K{k}"
            aggregates[key] = agg
            print(
                f"  {strategy_name:20s} K={k:2d}: "
                f"cov={agg['micro_coverage']:.0%} ({agg['total_found']}/{agg['total_needed']}) "
                f"mrr={agg['mean_mrr']:.3f} "
                f"beh_mrr={agg['mean_behavioral_mrr']:.3f} "
                f"prec={agg['mean_precision_at_k']:.0%} "
                f"tok={agg['mean_tokens']:7.1f} "
                f"missed={agg['missed']}",
                file=sys.stderr,
            )

    # --- Behavioral MRR comparison (key question 2) ---
    print("\n" + "=" * 70, file=sys.stderr)
    print("BEHAVIORAL MRR COMPARISON (D157, D188, D100, D073)", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    behavioral_topic_map: dict[str, str] = {
        "D157": "agent_behavior",
        "D188": "agent_behavior",
        "D100": "calls_puts",
        "D073": "calls_puts",
    }

    for strategy_name in STRATEGIES:
        beh_ranks: list[int] = []
        for did, topic_name in behavioral_topic_map.items():
            ev_k15: list[TopicEval] = [
                e for e in all_evals
                if e.strategy == strategy_name and e.k == 15 and e.topic == topic_name
            ]
            if not ev_k15:
                continue
            ev: TopicEval = ev_k15[0]
            # Check if this did appears in found
            if did in ev.found:
                # Find rank in the ranked list
                ranked_strat: list[RankedResult] = []
                topic_data_raw: dict[str, Any] = TOPICS[topic_name]
                pipeline_out2: list[tuple[str, float]] = pipeline_results_by_topic[topic_name]
                annotated2: list[RankedResult] = annotate_results(
                    pipeline_out2, decision_meta, behavioral_ids
                )
                if strategy_name == "NO_RERANK":
                    ranked_strat = rerank_no_rerank(annotated2)
                elif strategy_name == "DECAY_RERANK":
                    ranked_strat = rerank_decay(annotated2)
                elif strategy_name == "LOCK_BOOST":
                    ranked_strat = rerank_lock_boost(annotated2)
                elif strategy_name == "LOCK_BOOST_TYPED":
                    ranked_strat = rerank_lock_boost_typed(
                        annotated2, topic_name, decision_meta
                    )

                for rank, item in enumerate(ranked_strat[:15], start=1):
                    if item.decision_id == did:
                        beh_ranks.append(rank)
                        break

        print(
            f"  {strategy_name:20s}: behavioral ranks in K=15: {beh_ranks}",
            file=sys.stderr,
        )

    # --- Precision comparison (key question 3) ---
    print("\n" + "=" * 70, file=sys.stderr)
    print("PRECISION@15 vs PRECISION@30 BY STRATEGY", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    for strategy_name in STRATEGIES:
        p15: float = aggregates[f"{strategy_name}_K15"]["mean_precision_at_k"]
        p30: float = aggregates[f"{strategy_name}_K30"]["mean_precision_at_k"]
        delta: float = p15 - aggregates["NO_RERANK_K15"]["mean_precision_at_k"]
        print(
            f"  {strategy_name:20s}: P@15={p15:.3f} P@30={p30:.3f} "
            f"delta_vs_baseline_P15={delta:+.3f}",
            file=sys.stderr,
        )

    # --- Save results ---
    elapsed: float = time.monotonic() - t_start

    output: dict[str, Any] = {
        "experiment": "exp60_temporal_reranking",
        "date": "2026-04-10",
        "elapsed_seconds": round(elapsed, 2),
        "config": {
            "hrr_dim": HRR_DIM,
            "fts_k": FTS_K,
            "final_k": FINAL_K,
            "hrr_threshold": HRR_THRESHOLD,
            "eval_k_values": EVAL_K_VALUES,
            "sentence_nodes": len(sentence_nodes),
            "behavioral_decisions": len(behavioral_ids),
            "behavioral_nodes": len(behavioral_node_ids),
            "agent_constraint_edges": len(constraint_edges),
            "cites_edges": len(cites_edges),
            "hrr_capacity": hrr_graph.capacity,
            "hrr_ac_sub_partitions": ac_meta["sub_partitions"],
            "hrr_ci_sub_partitions": ci_meta["sub_partitions"],
            "current_time_iso": current_time_dt.isoformat(),
        },
        "strategies": STRATEGIES,
        "topics": {
            t: {"query": v["query"], "needed": v["needed"]}
            for t, v in TOPICS.items()
        },
        "ground_truth_metadata": {
            did: {
                "scope": decision_meta[did].scope,
                "content_type": decision_meta[did].content_type,
                "locked": decision_meta[did].locked,
                "age_days": round(decision_meta[did].age_days, 2),
            }
            for did in gt_decisions
            if did in decision_meta
        },
        "aggregates": aggregates,
        "topic_evals": [
            {
                "topic": e.topic,
                "strategy": e.strategy,
                "k": e.k,
                "coverage": e.coverage,
                "mrr": e.mrr,
                "precision_at_k": e.precision_at_k,
                "tokens": e.tokens,
                "found": e.found,
                "missed": e.missed,
                "behavioral_mrr": e.behavioral_mrr,
            }
            for e in all_evals
        ],
    }

    out_path: Path = Path(__file__).parent / "exp60_results.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults saved to {out_path}", file=sys.stderr)
    print(f"Elapsed: {elapsed:.2f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
