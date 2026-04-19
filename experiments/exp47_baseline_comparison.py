"""Exp 47: Baseline Comparison -- Can We Beat Grep?

Compares 5 retrieval methods on the 6-topic project-a ground truth:
  A. Grep on decision-level nodes (173 decisions)
  B. Grep on sentence-level nodes (1,195 sentences)
  C. FTS5 (BM25 + porter stemming)
  D. FTS5 + PRF (pseudo-relevance feedback, 2-pass)
  E. FTS5 + HRR (hybrid pipeline from Exp 40)

Metrics: coverage@15, tokens@15, precision@15, MRR.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

# ============================================================
# Config
# ============================================================

ALPHA_SEEK_DB: Path = Path(
    "/home/user/projects/.gsd/workflows/spikes/"
    "260406-1-associative-memory-for-gsd-please-explor/"
    "sandbox/project-a.db"
)

TOP_K: int = 15
DIM: int = 2048
HRR_THRESHOLD: float = 0.08
RNG: np.random.Generator = np.random.default_rng(42)

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

BEHAVIORAL_BELIEFS: list[str] = ["D157", "D188", "D100", "D073"]

STOPWORDS: set[str] = {
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


# ============================================================
# Data loading
# ============================================================


def load_decision_nodes() -> dict[str, str]:
    """Load decision-level nodes (173 decisions, not sentence-split)."""
    db: sqlite3.Connection = sqlite3.connect(str(ALPHA_SEEK_DB))
    nodes: dict[str, str] = {}
    for row in db.execute(
        "SELECT id, content FROM mem_nodes WHERE superseded_by IS NULL"
    ):
        nid: str = str(row[0])
        # Only decision-level: no _s suffix
        if re.match(r"^D\d{3}$", nid):
            nodes[nid] = str(row[1])
    db.close()
    return nodes


def load_sentence_nodes() -> dict[str, str]:
    """Load all sentence-level nodes (1,195 sentences)."""
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
    """Simple tokenizer: lowercase, alphanumeric, no stopwords, min 2 chars."""
    words: list[str] = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) >= 2]


def estimate_tokens(text: str) -> int:
    """Rough token estimate: chars / 4."""
    return max(1, len(text) // 4)


# ============================================================
# Method A & B: Grep baseline
# ============================================================


def grep_search(
    query: str,
    nodes: dict[str, str],
    top_k: int = TOP_K,
) -> list[tuple[str, float]]:
    """Case-insensitive grep: rank by count of query terms matched.

    Returns (node_id, match_count) pairs sorted by match count descending.
    """
    query_terms: list[str] = [t.lower() for t in query.split() if len(t) >= 2]
    scores: list[tuple[str, float]] = []

    for nid, content in nodes.items():
        content_lower: str = content.lower()
        match_count: int = 0
        for term in query_terms:
            match_count += len(re.findall(re.escape(term), content_lower))
        if match_count > 0:
            scores.append((nid, float(match_count)))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_k]


# ============================================================
# Method C: FTS5
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
    """FTS5 search with OR terms. Returns (node_id, bm25_score)."""
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
# Method D: FTS5 + PRF
# ============================================================


def search_fts_prf(
    query: str,
    fts_db: sqlite3.Connection,
    nodes: dict[str, str],
    top_k: int = TOP_K,
) -> list[tuple[str, float]]:
    """Two-pass FTS5: first pass gets top-5, extract TF-IDF terms, second pass."""
    # Pass 1
    pass1: list[tuple[str, float]] = search_fts(query, fts_db, top_k=5)
    if not pass1:
        return search_fts(query, fts_db, top_k)

    # Extract distinctive terms from pass 1 results
    all_tokens: list[str] = tokenize(query)
    query_term_set: set[str] = set(all_tokens)

    # TF in pass 1 results
    tf: Counter[str] = Counter()
    for nid, _ in pass1:
        content: str = nodes.get(nid, "")
        for token in tokenize(content):
            if token not in query_term_set:
                tf[token] += 1

    # DF across full corpus (approximate with node count)
    df: Counter[str] = Counter()
    for content in nodes.values():
        seen: set[str] = set()
        for token in tokenize(content):
            if token not in seen:
                df[token] += 1
                seen.add(token)

    n_docs: int = len(nodes)
    # TF-IDF score for expansion terms
    expansion: list[tuple[str, float]] = []
    for term, freq in tf.items():
        idf: float = np.log(n_docs / max(1, df.get(term, 1)))
        expansion.append((term, freq * idf))

    expansion.sort(key=lambda x: x[1], reverse=True)
    new_terms: list[str] = [t for t, _ in expansion[:5]]

    # Pass 2: expanded query
    expanded: str = query + " " + " ".join(new_terms)
    return search_fts(expanded, fts_db, top_k)


# ============================================================
# Method E: FTS5 + HRR
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
    result: np.ndarray[Any, np.dtype[np.complexfloating[Any, Any]]] = np.fft.ifft(
        np.fft.fft(a) * np.fft.fft(b)
    )
    return np.real(result)


def unbind(
    bound: np.ndarray[Any, np.dtype[np.floating[Any]]],
    key: np.ndarray[Any, np.dtype[np.floating[Any]]],
) -> np.ndarray[Any, np.dtype[np.floating[Any]]]:
    """Circular correlation via FFT."""
    result: np.ndarray[Any, np.dtype[np.complexfloating[Any, Any]]] = np.fft.ifft(
        np.fft.fft(bound) * np.conj(np.fft.fft(key))
    )
    return np.real(result)


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


def build_hrr_graph(
    nodes: dict[str, str],
) -> tuple[
    dict[str, np.ndarray[Any, np.dtype[np.floating[Any]]]],
    dict[str, np.ndarray[Any, np.dtype[np.floating[Any]]]],
    np.ndarray[Any, np.dtype[np.floating[Any]]],
    list[str],
]:
    """Build HRR graph with AGENT_CONSTRAINT edges for behavioral beliefs.

    Returns (node_vecs, edge_type_vecs, superposition, behavioral_node_ids).
    """
    # Scan for behavioral beliefs
    directive_patterns: list[re.Pattern[str]] = [
        re.compile(r"\bBANNED\b"),
        re.compile(r"\bNever\s+use\b", re.IGNORECASE),
        re.compile(r"\bNever\s+\w+\b"),
        re.compile(r"\balways\s+\w+\b", re.IGNORECASE),
        re.compile(r"\bmust\s+not\b", re.IGNORECASE),
        re.compile(r"\bdo\s+not\b", re.IGNORECASE),
        re.compile(r"\bdon't\b", re.IGNORECASE),
    ]

    known_behavioral: set[str] = set(BEHAVIORAL_BELIEFS)
    for nid, content in nodes.items():
        did: str | None = extract_decision_id(nid)
        if did and did not in known_behavioral:
            for pattern in directive_patterns:
                if pattern.search(content):
                    known_behavioral.add(did)
                    break

    # Collect behavioral node IDs
    behavioral_nodes: list[str] = []
    for nid in nodes:
        did = extract_decision_id(nid)
        if did and did in known_behavioral:
            behavioral_nodes.append(nid)

    # Build edges (fully connected behavioral clique)
    edges: list[tuple[str, str]] = []
    for i, a in enumerate(behavioral_nodes):
        for b in behavioral_nodes[i + 1 :]:
            edges.append((a, b))
            edges.append((b, a))

    # Encode in HRR
    node_vecs: dict[str, np.ndarray[Any, np.dtype[np.floating[Any]]]] = {}
    for nid in nodes:
        node_vecs[nid] = make_vector(DIM)

    etype_vec: np.ndarray[Any, np.dtype[np.floating[Any]]] = make_vector(DIM)
    edge_type_vecs: dict[str, np.ndarray[Any, np.dtype[np.floating[Any]]]] = {
        "AGENT_CONSTRAINT": etype_vec,
    }

    superposition: np.ndarray[Any, np.dtype[np.floating[Any]]] = np.zeros(DIM)
    for _src, tgt in edges:
        superposition += bind(node_vecs[tgt], etype_vec)

    return node_vecs, edge_type_vecs, superposition, behavioral_nodes


def hrr_query_neighbors(
    node_id: str,
    superposition: np.ndarray[Any, np.dtype[np.floating[Any]]],
    edge_type_vec: np.ndarray[Any, np.dtype[np.floating[Any]]],
    node_vecs: dict[str, np.ndarray[Any, np.dtype[np.floating[Any]]]],
    behavioral_nodes: list[str],
    threshold: float = HRR_THRESHOLD,
) -> list[tuple[str, float]]:
    """Find HRR neighbors of a node via edge type."""
    if node_id not in node_vecs:
        return []

    result: np.ndarray[Any, np.dtype[np.floating[Any]]] = unbind(
        superposition, edge_type_vec
    )

    scores: list[tuple[str, float]] = []
    for nid in behavioral_nodes:
        if nid == node_id:
            continue
        sim: float = cos_sim(result, node_vecs[nid])
        if sim >= threshold:
            scores.append((nid, sim))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores


def search_fts_hrr(
    query: str,
    fts_db: sqlite3.Connection,
    nodes: dict[str, str],
    node_vecs: dict[str, np.ndarray[Any, np.dtype[np.floating[Any]]]],
    edge_type_vecs: dict[str, np.ndarray[Any, np.dtype[np.floating[Any]]]],
    superposition: np.ndarray[Any, np.dtype[np.floating[Any]]],
    behavioral_nodes: list[str],
    top_k: int = TOP_K,
) -> list[tuple[str, float]]:
    """FTS5 -> HRR walk -> union pipeline."""
    # FTS5 pass
    fts_results: list[tuple[str, float]] = search_fts(query, fts_db, top_k=30)
    fts_ids: set[str] = {nid for nid, _ in fts_results}

    # HRR walk from each FTS5 hit
    hrr_additions: list[tuple[str, float]] = []
    etype_vec: np.ndarray[Any, np.dtype[np.floating[Any]]] = edge_type_vecs[
        "AGENT_CONSTRAINT"
    ]

    for seed_id, _ in fts_results:
        neighbors: list[tuple[str, float]] = hrr_query_neighbors(
            seed_id, superposition, etype_vec, node_vecs, behavioral_nodes
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

    return combined[:top_k]


# ============================================================
# Evaluation
# ============================================================


def evaluate_method(
    method_name: str,
    results: list[tuple[str, float]],
    needed_decisions: list[str],
    nodes: dict[str, str],
) -> dict[str, Any]:
    """Evaluate a single method's results against ground truth."""
    needed: set[str] = set(needed_decisions)

    # Decisions found in results
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
    print("=" * 60, file=sys.stderr)
    print("Experiment 47: Baseline Comparison -- Can We Beat Grep?", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Load data
    print("\n--- Loading data ---", file=sys.stderr)
    decision_nodes: dict[str, str] = load_decision_nodes()
    sentence_nodes: dict[str, str] = load_sentence_nodes()
    print(
        f"  Decision nodes: {len(decision_nodes)}, "
        f"Sentence nodes: {len(sentence_nodes)}",
        file=sys.stderr,
    )

    # Build indexes
    print("\n--- Building indexes ---", file=sys.stderr)
    fts_sentence: sqlite3.Connection = build_fts(sentence_nodes)
    print("  FTS5 (sentence): built", file=sys.stderr)

    node_vecs, edge_type_vecs, superposition, behavioral_nodes = build_hrr_graph(
        sentence_nodes
    )
    print(
        f"  HRR: {len(behavioral_nodes)} behavioral nodes, DIM={DIM}",
        file=sys.stderr,
    )

    # Run all methods on all topics
    all_results: dict[str, dict[str, dict[str, Any]]] = {}

    for topic_name, topic_data in TOPICS.items():
        query: str = topic_data["query"]
        needed: list[str] = topic_data["needed"]
        print(f'\n--- {topic_name}: "{query}" ---', file=sys.stderr)

        topic_results: dict[str, dict[str, Any]] = {}

        # Method A: Grep on decisions
        grep_dec: list[tuple[str, float]] = grep_search(query, decision_nodes)
        topic_results["A_grep_decision"] = evaluate_method(
            "A_grep_decision", grep_dec, needed, decision_nodes
        )

        # Method B: Grep on sentences
        grep_sent: list[tuple[str, float]] = grep_search(query, sentence_nodes)
        topic_results["B_grep_sentence"] = evaluate_method(
            "B_grep_sentence", grep_sent, needed, sentence_nodes
        )

        # Method C: FTS5
        fts_res: list[tuple[str, float]] = search_fts(query, fts_sentence)
        topic_results["C_fts5"] = evaluate_method(
            "C_fts5", fts_res, needed, sentence_nodes
        )

        # Method D: FTS5 + PRF
        prf_res: list[tuple[str, float]] = search_fts_prf(
            query, fts_sentence, sentence_nodes
        )
        topic_results["D_fts5_prf"] = evaluate_method(
            "D_fts5_prf", prf_res, needed, sentence_nodes
        )

        # Method E: FTS5 + HRR
        hrr_res: list[tuple[str, float]] = search_fts_hrr(
            query,
            fts_sentence,
            sentence_nodes,
            node_vecs,
            edge_type_vecs,
            superposition,
            behavioral_nodes,
        )
        topic_results["E_fts5_hrr"] = evaluate_method(
            "E_fts5_hrr", hrr_res, needed, sentence_nodes
        )

        all_results[topic_name] = topic_results

        # Print per-topic summary
        for method, res in topic_results.items():
            status: str = "OK" if not res["missed"] else f"MISSED: {res['missed']}"
            print(
                f"  {method:20s}: cov={res['coverage']:.0%} "
                f"tok={res['tokens']:5d} "
                f"prec={res['precision']:.0%} "
                f"mrr={res['mrr']:.3f} "
                f"{status}",
                file=sys.stderr,
            )

    # Aggregate across topics
    print("\n" + "=" * 60, file=sys.stderr)
    print("AGGREGATE RESULTS", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    methods: list[str] = [
        "A_grep_decision",
        "B_grep_sentence",
        "C_fts5",
        "D_fts5_prf",
        "E_fts5_hrr",
    ]
    aggregates: dict[str, dict[str, float]] = {}

    for method in methods:
        coverages: list[float] = []
        tokens_list: list[int] = []
        precisions: list[float] = []
        mrrs: list[float] = []
        total_needed: int = 0
        total_found: int = 0

        for topic_name in TOPICS:
            res: dict[str, Any] = all_results[topic_name][method]
            coverages.append(res["coverage"])
            tokens_list.append(res["tokens"])
            precisions.append(res["precision"])
            mrrs.append(res["mrr"])
            total_needed += len(TOPICS[topic_name]["needed"])
            total_found += len(res["found"])

        macro_coverage: float = sum(coverages) / len(coverages)
        micro_coverage: float = total_found / total_needed if total_needed else 0.0
        mean_tokens: float = sum(tokens_list) / len(tokens_list)
        mean_precision: float = sum(precisions) / len(precisions)
        mean_mrr: float = sum(mrrs) / len(mrrs)

        aggregates[method] = {
            "macro_coverage": round(macro_coverage, 3),
            "micro_coverage": round(micro_coverage, 3),
            "mean_tokens": round(mean_tokens, 1),
            "mean_precision": round(mean_precision, 3),
            "mean_mrr": round(mean_mrr, 3),
            "total_found": total_found,
            "total_needed": total_needed,
        }

        print(
            f"  {method:20s}: "
            f"cov={micro_coverage:.0%} "
            f"tok={mean_tokens:7.1f} "
            f"prec={mean_precision:.0%} "
            f"mrr={mean_mrr:.3f} "
            f"({total_found}/{total_needed})",
            file=sys.stderr,
        )

    # Save results
    output: dict[str, Any] = {
        "config": {
            "top_k": TOP_K,
            "dim": DIM,
            "hrr_threshold": HRR_THRESHOLD,
            "decision_nodes": len(decision_nodes),
            "sentence_nodes": len(sentence_nodes),
            "behavioral_nodes": len(behavioral_nodes),
        },
        "per_topic": all_results,
        "aggregates": aggregates,
    }

    results_path: Path = Path(__file__).parent / "exp47_results.json"
    results_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\nResults saved to {results_path.name}", file=sys.stderr)


if __name__ == "__main__":
    main()
