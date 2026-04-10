"""
Experiment 46: SimHash Binary Encoding for Belief Corpus

Builds SimHash (random hyperplane projection on TF-IDF) for the 1,195
sentence-level belief nodes from Exp 16. Evaluates:

1. Encoding performance and storage
2. Hamming distance distribution
3. Semantic quality (related vs unrelated pairs)
4. Retrieval pre-filter (vs FTS5 on 6 critical topics)
5. Drift detection (isolated beliefs)
6. Comparison with HRR (content-based vs structure-based)

Zero-LLM. TF-IDF + random projection. numpy/scipy only.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

# Type aliases
FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
Uint8Array = NDArray[np.uint8]

ALPHA_SEEK_DB = Path(
    "/Users/thelorax/projects/.gsd/workflows/spikes/"
    "260406-1-associative-memory-for-gsd-please-explor/"
    "sandbox/alpha-seek.db"
)

STOPWORDS: frozenset[str] = frozenset({
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

# Ground truth from Exp 9 / Exp 39
CRITICAL_BELIEFS: dict[str, dict[str, Any]] = {
    "dispatch_gate": {
        "single_query": "dispatch gate deploy protocol",
        "needed": ["D089", "D106", "D137"],
    },
    "calls_puts": {
        "single_query": "calls puts equal citizens",
        "needed": ["D073", "D096", "D100"],
    },
    "capital_5k": {
        "single_query": "starting capital bankroll",
        "needed": ["D099"],
    },
    "agent_behavior": {
        "single_query": "agent behavior instructions",
        "needed": ["D157", "D188"],
    },
    "strict_typing": {
        "single_query": "typing pyright strict",
        "needed": ["D071", "D113"],
    },
    "gcp_primary": {
        "single_query": "GCP primary compute platform",
        "needed": ["D078", "D120"],
    },
}


# ============================================================
# Data loading (from Exp 16 approach)
# ============================================================

def split_into_sentences(text: str) -> list[str]:
    """Split text into sentences. Simple rule-based splitter."""
    parts: list[str] = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    sentences: list[str] = []
    for part in parts:
        subparts: list[str] = part.split(" | ")
        for sp in subparts:
            sp = sp.strip()
            if len(sp) > 10:
                sentences.append(sp)
    return sentences


def classify_sentence(sentence: str) -> str:
    """Classify a sentence by its role in a decision."""
    s: str = sentence.lower()
    if any(w in s for w in ["because", "rationale", "reason", "driven by", "root cause"]):
        return "rationale"
    if any(w in s for w in ["supersede", "replace", "retire", "override"]):
        return "supersession"
    if any(w in s for w in ["must", "always", "never", "mandatory", "require", "rule"]):
        return "constraint"
    if any(w in s for w in ["data", "showed", "result", "found", "measured", "%", "x "]):
        return "evidence"
    if any(w in s for w in ["script", "implement", "code", ".py", "function"]):
        return "implementation"
    if re.match(r"^[A-Z].*:", s):
        return "assertion"
    return "context"


def load_sentence_nodes() -> list[dict[str, Any]]:
    """Load all sentence nodes by decomposing decisions (Exp 16 method)."""
    db: sqlite3.Connection = sqlite3.connect(str(ALPHA_SEEK_DB))
    decisions: list[Any] = db.execute(
        "SELECT id, decision, choice, rationale FROM decisions ORDER BY seq"
    ).fetchall()
    db.close()

    all_nodes: list[dict[str, Any]] = []
    for row in decisions:
        did: str = str(row[0])
        full_text: str = f"{row[1]}: {row[2]}"
        if row[3]:
            full_text += f" | {row[3]}"

        sentences: list[str] = split_into_sentences(full_text)
        for i, sent in enumerate(sentences):
            stype: str = classify_sentence(sent)
            refs: list[str] = sorted(
                {m.group(1) for m in re.finditer(r"\b(D\d{2,3})\b", sent)}
                - {did}
            )
            node: dict[str, Any] = {
                "id": f"{did}_s{i}",
                "parent_decision": did,
                "sentence_index": i,
                "content": sent,
                "type": stype,
                "references": refs,
            }
            all_nodes.append(node)

    return all_nodes


# ============================================================
# Tokenizer and TF-IDF
# ============================================================

def tokenize(text: str) -> list[str]:
    """Lowercase, alphanumeric, no stopwords, min 2 chars."""
    words: list[str] = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) >= 2]


def build_tfidf(
    documents: list[str],
) -> tuple[FloatArray, list[str]]:
    """Build TF-IDF matrix from document list.

    Returns:
        tfidf_matrix: shape (n_docs, vocab_size), float64
        vocab: ordered list of terms
    """
    n_docs: int = len(documents)

    # Tokenize all documents
    doc_tokens: list[list[str]] = [tokenize(doc) for doc in documents]

    # Build vocabulary with document frequency
    df: Counter[str] = Counter()
    for tokens in doc_tokens:
        for t in set(tokens):
            df[t] += 1

    # Filter: appear in >= 2 docs and <= 80% of docs
    max_df: int = int(n_docs * 0.8)
    vocab: list[str] = sorted(
        w for w, count in df.items() if count >= 2 and count <= max_df
    )
    word_to_idx: dict[str, int] = {w: i for i, w in enumerate(vocab)}
    vocab_size: int = len(vocab)

    # Build TF-IDF matrix
    tfidf: FloatArray = np.zeros((n_docs, vocab_size), dtype=np.float64)
    idf: FloatArray = np.zeros(vocab_size, dtype=np.float64)

    for i, w in enumerate(vocab):
        idf[i] = math.log(n_docs / (1 + df[w]))

    for doc_idx, tokens in enumerate(doc_tokens):
        tf: Counter[str] = Counter(tokens)
        for word, count in tf.items():
            if word in word_to_idx:
                col: int = word_to_idx[word]
                # Log-normalized TF * IDF
                tfidf[doc_idx, col] = (1 + math.log(count)) * idf[col]

    # L2 normalize rows
    norms: FloatArray = np.linalg.norm(tfidf, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    tfidf = tfidf / norms

    return tfidf, vocab


# ============================================================
# SimHash encoding
# ============================================================

def simhash_encode(
    tfidf_matrix: FloatArray,
    n_bits: int = 128,
    seed: int = 42,
) -> tuple[Uint8Array, FloatArray]:
    """Encode TF-IDF vectors to n_bits binary codes via random hyperplane projection.

    Returns:
        codes: shape (n_docs, n_bits), uint8 (0 or 1)
        projections: shape (n_docs, n_bits), float64 (raw dot products before sign)
    """
    rng: np.random.Generator = np.random.default_rng(seed)
    vocab_size: int = tfidf_matrix.shape[1]

    # Random hyperplanes: each column is a random unit vector
    hyperplanes: FloatArray = rng.standard_normal((vocab_size, n_bits))
    # Normalize columns
    hp_norms: FloatArray = np.linalg.norm(hyperplanes, axis=0, keepdims=True)
    hyperplanes = hyperplanes / hp_norms

    # Project: (n_docs, vocab_size) @ (vocab_size, n_bits) -> (n_docs, n_bits)
    projections: FloatArray = tfidf_matrix @ hyperplanes

    # Threshold at 0
    codes: Uint8Array = (projections >= 0).astype(np.uint8)

    return codes, projections


def hamming_distance_matrix(codes: Uint8Array) -> Uint8Array:
    """Compute pairwise Hamming distances. Returns uint8 matrix."""
    n: int = codes.shape[0]
    # XOR and sum across bits
    dist: IntArray = np.zeros((n, n), dtype=np.int64)
    # Vectorized: for each pair, count differing bits
    # Use broadcasting: codes[i] XOR codes[j] then sum
    # Memory-efficient: process in chunks
    chunk_size: int = 200
    for i in range(0, n, chunk_size):
        i_end: int = min(i + chunk_size, n)
        # Shape: (chunk, 1, n_bits) XOR (1, n, n_bits) -> (chunk, n, n_bits)
        diff: IntArray = np.bitwise_xor(
            codes[i:i_end, np.newaxis, :].astype(np.int64),
            codes[np.newaxis, :, :].astype(np.int64),
        )
        dist[i:i_end, :] = diff.sum(axis=2)

    return dist.astype(np.uint8)


def hamming_distance_single(
    query_code: Uint8Array,
    codes: Uint8Array,
) -> Uint8Array:
    """Hamming distance from a single query code to all codes."""
    diff: IntArray = np.bitwise_xor(
        query_code.astype(np.int64),
        codes.astype(np.int64),
    )
    return diff.sum(axis=1).astype(np.uint8)


def encode_query(
    query: str,
    vocab: list[str],
    idf_vec: FloatArray,
    hyperplanes: FloatArray,
) -> Uint8Array:
    """Encode a query string to a SimHash code."""
    word_to_idx: dict[str, int] = {w: i for i, w in enumerate(vocab)}
    tokens: list[str] = tokenize(query)
    vec: FloatArray = np.zeros(len(vocab), dtype=np.float64)
    tf: Counter[str] = Counter(tokens)
    for word, count in tf.items():
        if word in word_to_idx:
            col: int = word_to_idx[word]
            vec[col] = (1 + math.log(count)) * idf_vec[col]
    # L2 normalize
    norm: float = float(np.linalg.norm(vec))
    if norm > 0:
        vec = vec / norm
    proj: FloatArray = vec @ hyperplanes
    code: Uint8Array = (proj >= 0).astype(np.uint8)
    return code


# ============================================================
# FTS5 for comparison
# ============================================================

def build_fts(nodes: list[dict[str, Any]]) -> sqlite3.Connection:
    """Build in-memory FTS5 index."""
    db: sqlite3.Connection = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE fts USING fts5(id, content, tokenize='porter')")
    for node in nodes:
        db.execute(
            "INSERT INTO fts VALUES (?, ?)", (node["id"], node["content"])
        )
    db.commit()
    return db


def search_fts(
    query: str, fts_db: sqlite3.Connection, top_k: int = 30
) -> list[str]:
    """FTS5 search with OR terms."""
    terms: list[str] = [t.strip() for t in query.split() if len(t.strip()) > 2]
    if not terms:
        return []
    fts_query: str = " OR ".join(terms)
    try:
        results: list[Any] = fts_db.execute(
            "SELECT id FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT ?",
            (fts_query, top_k),
        ).fetchall()
        return [str(r[0]) for r in results]
    except Exception:
        return []


# ============================================================
# Analysis functions
# ============================================================

def analyze_distribution(
    dist_matrix: Uint8Array,
) -> dict[str, Any]:
    """Analyze the Hamming distance distribution."""
    n: int = dist_matrix.shape[0]
    # Extract upper triangle (no diagonal)
    upper_tri: FloatArray = dist_matrix[np.triu_indices(n, k=1)].astype(np.float64)
    total_pairs: int = len(upper_tri)

    stats: dict[str, Any] = {
        "total_pairs": total_pairs,
        "mean": float(np.mean(upper_tri)),
        "median": float(np.median(upper_tri)),
        "std": float(np.std(upper_tri)),
        "min": int(np.min(upper_tri)),
        "max": int(np.max(upper_tri)),
        "p5": float(np.percentile(upper_tri, 5)),
        "p25": float(np.percentile(upper_tri, 25)),
        "p75": float(np.percentile(upper_tri, 75)),
        "p95": float(np.percentile(upper_tri, 95)),
    }

    # Fraction within various thresholds
    for k in [5, 10, 15, 20, 25, 30]:
        count: int = int(np.sum(upper_tri <= k))
        stats[f"frac_le_{k}"] = round(count / total_pairs, 6)
        stats[f"count_le_{k}"] = count

    # Histogram bins
    hist_counts: list[int] = []
    hist_edges: list[int] = list(range(0, 129, 4))
    for i in range(len(hist_edges) - 1):
        low: int = hist_edges[i]
        high: int = hist_edges[i + 1]
        count = int(np.sum((upper_tri >= low) & (upper_tri < high)))
        hist_counts.append(count)
    stats["histogram_bins"] = hist_edges
    stats["histogram_counts"] = hist_counts

    return stats


def find_related_pairs(
    nodes: list[dict[str, Any]],
) -> tuple[list[tuple[int, int, str]], list[tuple[int, int, str]]]:
    """Find related and unrelated belief pairs for validation.

    Related: same parent decision (siblings)
    Unrelated: different topics (far-apart decisions)
    """
    # Build index by parent decision
    by_decision: dict[str, list[int]] = defaultdict(list)
    for idx, node in enumerate(nodes):
        by_decision[node["parent_decision"]].append(idx)

    # Related pairs: siblings within the same decision
    related: list[tuple[int, int, str]] = []
    decisions_with_siblings: list[str] = [
        d for d, indices in by_decision.items() if len(indices) >= 2
    ]
    # Take pairs from diverse decisions
    sample_decisions: list[str] = decisions_with_siblings[:10]
    for did in sample_decisions:
        indices: list[int] = by_decision[did]
        if len(indices) >= 2:
            related.append((indices[0], indices[1], f"siblings in {did}"))
        if len(related) >= 15:
            break

    # Cross-reference pairs (nodes that reference the same other decision)
    ref_to_nodes: dict[str, list[int]] = defaultdict(list)
    for idx, node in enumerate(nodes):
        for ref in node["references"]:
            ref_to_nodes[ref].append(idx)

    for ref, indices in sorted(ref_to_nodes.items(), key=lambda x: -len(x[1])):
        if len(indices) >= 2:
            # Take two nodes from different decisions that cite the same thing
            for i in range(len(indices)):
                for j in range(i + 1, len(indices)):
                    if nodes[indices[i]]["parent_decision"] != nodes[indices[j]]["parent_decision"]:
                        related.append(
                            (indices[i], indices[j], f"both cite {ref}")
                        )
                        break
                if len(related) >= 20:
                    break
            if len(related) >= 20:
                break

    # Unrelated pairs: decisions from very different IDs (topically distant)
    unrelated: list[tuple[int, int, str]] = []
    all_dids: list[str] = sorted(by_decision.keys())
    # Pick pairs from opposite ends of the decision sequence
    early_dids: list[str] = all_dids[:10]
    late_dids: list[str] = all_dids[-10:]
    for e_did in early_dids:
        for l_did in late_dids:
            e_idx: int = by_decision[e_did][0]
            l_idx: int = by_decision[l_did][0]
            unrelated.append((e_idx, l_idx, f"{e_did} vs {l_did}"))
            if len(unrelated) >= 15:
                break
        if len(unrelated) >= 15:
            break

    return related[:15], unrelated[:15]


def evaluate_retrieval_prefilter(
    nodes: list[dict[str, Any]],
    codes: Uint8Array,
    vocab: list[str],
    idf_vec: FloatArray,
    hyperplanes: FloatArray,
    fts_db: sqlite3.Connection,
) -> dict[str, Any]:
    """Evaluate SimHash as retrieval pre-filter vs FTS5."""
    results: dict[str, Any] = {}

    for topic_name, topic_data in CRITICAL_BELIEFS.items():
        query: str = topic_data["single_query"]
        needed: set[str] = set(topic_data["needed"])

        # FTS5 results
        fts_results: list[str] = search_fts(query, fts_db, top_k=30)
        fts_decisions: set[str] = set()
        for nid in fts_results:
            match: re.Match[str] | None = re.match(r"(D\d{2,3})", nid)
            if match:
                fts_decisions.add(match.group(1))
        fts_coverage: set[str] = needed & fts_decisions

        # SimHash results at various K thresholds
        query_code: Uint8Array = encode_query(query, vocab, idf_vec, hyperplanes)
        dists: Uint8Array = hamming_distance_single(query_code, codes)

        simhash_by_k: dict[int, dict[str, Any]] = {}
        for k_thresh in [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]:
            mask: NDArray[np.bool_] = dists <= k_thresh
            candidate_indices: list[int] = [
                int(i) for i in np.where(mask)[0]
            ]
            candidate_decisions: set[str] = set()
            for idx in candidate_indices:
                did: str = nodes[idx]["parent_decision"]
                candidate_decisions.add(did)
            sh_coverage: set[str] = needed & candidate_decisions
            simhash_by_k[k_thresh] = {
                "candidates": len(candidate_indices),
                "decisions": len(candidate_decisions),
                "coverage": sorted(sh_coverage),
                "missed": sorted(needed - sh_coverage),
                "recall": len(sh_coverage) / len(needed) if needed else 1.0,
            }

        # Find minimum K that captures all needed decisions
        min_k_full: int | None = None
        for k_thresh in sorted(simhash_by_k.keys()):
            if not simhash_by_k[k_thresh]["missed"]:
                min_k_full = k_thresh
                break

        results[topic_name] = {
            "query": query,
            "needed": sorted(needed),
            "fts5_coverage": sorted(fts_coverage),
            "fts5_missed": sorted(needed - fts_coverage),
            "fts5_total": len(fts_results),
            "simhash_by_k": simhash_by_k,
            "min_k_full_coverage": min_k_full,
        }

    return results


def evaluate_drift_detection(
    nodes: list[dict[str, Any]],
    dist_matrix: Uint8Array,
) -> dict[str, Any]:
    """Test drift detection: do topically unique beliefs have high min Hamming distance?"""
    # Find beliefs from rare decisions (few references, few siblings)
    by_decision: dict[str, list[int]] = defaultdict(list)
    for idx, node in enumerate(nodes):
        by_decision[node["parent_decision"]].append(idx)

    # Count how many times each decision is referenced
    ref_counts: Counter[str] = Counter()
    for node in nodes:
        for ref in node["references"]:
            ref_counts[ref] += 1

    # Isolated decisions: zero incoming references, few sentences
    isolated: list[tuple[str, int]] = []
    for did, indices in by_decision.items():
        incoming: int = ref_counts.get(did, 0)
        if incoming == 0 and len(indices) <= 3:
            isolated.append((did, indices[0]))

    # Take first 10
    isolated = isolated[:10]

    results: dict[str, Any] = {"isolated_beliefs": []}
    n: int = dist_matrix.shape[0]

    for did, idx in isolated:
        # Min distance to any other node
        row: Uint8Array = dist_matrix[idx, :]
        # Exclude self
        row_copy: FloatArray = row.astype(np.float64).copy()
        row_copy[idx] = 999.0
        min_dist: float = float(np.min(row_copy))
        mean_dist: float = float(np.mean(row[row > 0]))
        # Find indices within min_dist + 5
        close_count: int = int(np.sum(row <= int(min_dist) + 5)) - 1  # exclude self

        results["isolated_beliefs"].append({
            "decision": did,
            "node_id": nodes[idx]["id"],
            "content_preview": nodes[idx]["content"][:80],
            "type": nodes[idx]["type"],
            "min_hamming_dist": int(min_dist),
            "mean_hamming_dist": round(mean_dist, 1),
            "close_neighbors": close_count,
        })

    # Also compute the overall distribution of min distances for all nodes
    all_min_dists: list[int] = []
    for i in range(n):
        row = dist_matrix[i, :]
        row_copy = row.astype(np.float64).copy()
        row_copy[i] = 999.0
        all_min_dists.append(int(np.min(row_copy)))

    min_dist_arr: FloatArray = np.array(all_min_dists, dtype=np.float64)
    results["global_min_dist_stats"] = {
        "mean": round(float(np.mean(min_dist_arr)), 2),
        "median": float(np.median(min_dist_arr)),
        "std": round(float(np.std(min_dist_arr)), 2),
        "min": int(np.min(min_dist_arr)),
        "max": int(np.max(min_dist_arr)),
        "p90": float(np.percentile(min_dist_arr, 90)),
        "p95": float(np.percentile(min_dist_arr, 95)),
    }

    # Isolated beliefs vs overall
    isolated_min_dists: list[int] = [
        b["min_hamming_dist"] for b in results["isolated_beliefs"]
    ]
    if isolated_min_dists:
        results["isolated_min_dist_mean"] = round(
            float(np.mean(isolated_min_dists)), 2
        )
        results["global_min_dist_mean"] = results["global_min_dist_stats"]["mean"]
        results["separation_ratio"] = round(
            float(np.mean(isolated_min_dists))
            / results["global_min_dist_stats"]["mean"],
            3,
        )

    return results


def compare_with_hrr(
    nodes: list[dict[str, Any]],
    dist_matrix: Uint8Array,
) -> dict[str, Any]:
    """Compare SimHash (content-based) with HRR (structure-based).

    Focus on vocabulary-gap cases from Exp 34 Test A:
    - D157 "ban async_bash" and D188 "don't elaborate" share AGENT_CONSTRAINT
    - D100 "never question calls/puts" and D073 "equal citizens" share AGENT_CONSTRAINT
    - These share minimal vocabulary but are structurally connected
    """
    # Find the relevant nodes
    behavior_dids: list[str] = ["D157", "D188", "D100", "D073"]
    # Also some content-similar pairs for contrast
    # Nodes about typing/pyright: D071, D113
    content_similar_dids: list[str] = ["D071", "D113"]

    # Build lookup
    did_to_indices: dict[str, list[int]] = defaultdict(list)
    for idx, node in enumerate(nodes):
        did_to_indices[node["parent_decision"]].append(idx)

    results: dict[str, Any] = {"vocabulary_gap_cases": [], "content_similar_cases": []}

    # Vocabulary-gap pairs: should have HIGH Hamming distance (SimHash fails)
    for i in range(len(behavior_dids)):
        for j in range(i + 1, len(behavior_dids)):
            d1: str = behavior_dids[i]
            d2: str = behavior_dids[j]
            if d1 not in did_to_indices or d2 not in did_to_indices:
                continue
            # Take first sentence of each
            idx1: int = did_to_indices[d1][0]
            idx2: int = did_to_indices[d2][0]
            h_dist: int = int(dist_matrix[idx1, idx2])

            # Compute token overlap
            tokens1: set[str] = set(tokenize(nodes[idx1]["content"]))
            tokens2: set[str] = set(tokenize(nodes[idx2]["content"]))
            overlap: set[str] = tokens1 & tokens2
            jaccard: float = (
                len(overlap) / len(tokens1 | tokens2)
                if (tokens1 | tokens2)
                else 0.0
            )

            results["vocabulary_gap_cases"].append({
                "pair": f"{d1} vs {d2}",
                "node1": nodes[idx1]["id"],
                "node2": nodes[idx2]["id"],
                "content1": nodes[idx1]["content"][:80],
                "content2": nodes[idx2]["content"][:80],
                "hamming_distance": h_dist,
                "token_overlap": sorted(overlap),
                "jaccard": round(jaccard, 3),
                "note": "AGENT_CONSTRAINT edge exists (HRR finds this at 184x separation)",
            })

    # Content-similar pairs: should have LOW Hamming distance (SimHash succeeds)
    for i in range(len(content_similar_dids)):
        for j in range(i + 1, len(content_similar_dids)):
            d1 = content_similar_dids[i]
            d2 = content_similar_dids[j]
            if d1 not in did_to_indices or d2 not in did_to_indices:
                continue
            idx1 = did_to_indices[d1][0]
            idx2 = did_to_indices[d2][0]
            h_dist = int(dist_matrix[idx1, idx2])
            tokens1 = set(tokenize(nodes[idx1]["content"]))
            tokens2 = set(tokenize(nodes[idx2]["content"]))
            overlap = tokens1 & tokens2
            jaccard = (
                len(overlap) / len(tokens1 | tokens2)
                if (tokens1 | tokens2)
                else 0.0
            )
            results["content_similar_cases"].append({
                "pair": f"{d1} vs {d2}",
                "node1": nodes[idx1]["id"],
                "node2": nodes[idx2]["id"],
                "content1": nodes[idx1]["content"][:80],
                "content2": nodes[idx2]["content"][:80],
                "hamming_distance": h_dist,
                "token_overlap": sorted(overlap),
                "jaccard": round(jaccard, 3),
            })

    # Explicit D157 vs D188 test
    d157_idx: int | None = None
    d188_idx: int | None = None
    for idx, node in enumerate(nodes):
        if node["parent_decision"] == "D157" and node["sentence_index"] == 0:
            d157_idx = idx
        if node["parent_decision"] == "D188" and node["sentence_index"] == 0:
            d188_idx = idx

    if d157_idx is not None and d188_idx is not None:
        h_dist = int(dist_matrix[d157_idx, d188_idx])
        t1: set[str] = set(tokenize(nodes[d157_idx]["content"]))
        t2: set[str] = set(tokenize(nodes[d188_idx]["content"]))
        overlap = t1 & t2
        results["d157_d188_explicit"] = {
            "d157_content": nodes[d157_idx]["content"],
            "d188_content": nodes[d188_idx]["content"],
            "hamming_distance": h_dist,
            "token_overlap": sorted(overlap),
            "jaccard": round(
                len(overlap) / len(t1 | t2) if (t1 | t2) else 0.0, 3
            ),
            "simhash_verdict": "FAIL" if h_dist > 40 else "PARTIAL" if h_dist > 25 else "PASS",
            "hrr_verdict": "PASS (184x separation via AGENT_CONSTRAINT edge, Exp 34)",
        }

    return results


# ============================================================
# Main
# ============================================================

def main() -> None:
    out: dict[str, Any] = {}
    print("=" * 60, file=sys.stderr)
    print("Experiment 46: SimHash Binary Encoding Prototype", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # ----------------------------------------------------------
    # Load data
    # ----------------------------------------------------------
    print("\n--- Loading sentence nodes ---", file=sys.stderr)
    nodes: list[dict[str, Any]] = load_sentence_nodes()
    print(f"  {len(nodes)} sentence nodes from "
          f"{len(set(n['parent_decision'] for n in nodes))} decisions", file=sys.stderr)
    out["corpus_size"] = len(nodes)
    out["n_decisions"] = len(set(n["parent_decision"] for n in nodes))

    documents: list[str] = [n["content"] for n in nodes]

    # ----------------------------------------------------------
    # Q1: Encoding performance and storage
    # ----------------------------------------------------------
    print("\n--- Q1: Building TF-IDF + SimHash ---", file=sys.stderr)

    t0: float = time.perf_counter()
    tfidf_matrix: FloatArray
    vocab: list[str]
    tfidf_matrix, vocab = build_tfidf(documents)
    t_tfidf: float = time.perf_counter() - t0

    print(f"  TF-IDF: {tfidf_matrix.shape[0]} docs x {tfidf_matrix.shape[1]} vocab "
          f"({t_tfidf:.3f}s)", file=sys.stderr)

    # Build IDF vector for query encoding
    n_docs: int = len(documents)
    doc_tokens_sets: list[set[str]] = [set(tokenize(d)) for d in documents]
    df: Counter[str] = Counter()
    for tok_set in doc_tokens_sets:
        for t in tok_set:
            df[t] += 1
    idf_vec: FloatArray = np.array(
        [math.log(n_docs / (1 + df.get(w, 0))) for w in vocab], dtype=np.float64
    )

    t0 = time.perf_counter()
    n_bits: int = 128
    codes: Uint8Array
    codes, _projections = simhash_encode(tfidf_matrix, n_bits=n_bits)
    t_simhash: float = time.perf_counter() - t0

    print(f"  SimHash: {codes.shape[0]} x {codes.shape[1]} bits ({t_simhash:.3f}s)",
          file=sys.stderr)

    # Reconstruct hyperplanes for query encoding (same seed)
    rng: np.random.Generator = np.random.default_rng(42)
    hyperplanes: FloatArray = rng.standard_normal((len(vocab), n_bits))
    hp_norms: FloatArray = np.linalg.norm(hyperplanes, axis=0, keepdims=True)
    hyperplanes = hyperplanes / hp_norms

    storage_codes_bytes: int = codes.nbytes
    storage_codes_bits: int = n_docs * n_bits

    out["q1_encoding"] = {
        "vocab_size": len(vocab),
        "n_bits": n_bits,
        "tfidf_time_s": round(t_tfidf, 4),
        "simhash_time_s": round(t_simhash, 4),
        "total_encoding_time_s": round(t_tfidf + t_simhash, 4),
        "storage_codes_bytes": storage_codes_bytes,
        "storage_codes_kb": round(storage_codes_bytes / 1024, 2),
        "storage_bits_total": storage_codes_bits,
        "storage_bits_per_node": n_bits,
        "tfidf_matrix_shape": list(tfidf_matrix.shape),
        "tfidf_nonzero_frac": round(
            float(np.count_nonzero(tfidf_matrix)) / tfidf_matrix.size, 4
        ),
    }

    print(f"  Storage: {storage_codes_bytes} bytes ({storage_codes_bytes/1024:.1f} KB) "
          f"for {n_docs} codes", file=sys.stderr)
    print(f"  Total encoding time: {t_tfidf + t_simhash:.3f}s", file=sys.stderr)

    # ----------------------------------------------------------
    # Q2: Hamming distance distribution
    # ----------------------------------------------------------
    print("\n--- Q2: Computing Hamming distance matrix ---", file=sys.stderr)
    t0 = time.perf_counter()
    dist_matrix: Uint8Array = hamming_distance_matrix(codes)
    t_dist: float = time.perf_counter() - t0
    print(f"  Distance matrix: {dist_matrix.shape} ({t_dist:.3f}s)", file=sys.stderr)

    dist_stats: dict[str, Any] = analyze_distribution(dist_matrix)
    out["q2_distribution"] = dist_stats
    out["q2_distribution"]["compute_time_s"] = round(t_dist, 4)

    print(f"  Mean: {dist_stats['mean']:.1f}, Median: {dist_stats['median']:.0f}, "
          f"Std: {dist_stats['std']:.1f}", file=sys.stderr)
    print(f"  Min: {dist_stats['min']}, Max: {dist_stats['max']}", file=sys.stderr)
    print(f"  P5-P95: {dist_stats['p5']:.0f} - {dist_stats['p95']:.0f}", file=sys.stderr)
    for k in [5, 10, 15, 20, 25, 30]:
        frac: float = dist_stats[f"frac_le_{k}"]
        count: int = dist_stats[f"count_le_{k}"]
        print(f"  Hamming <= {k:2d}: {frac:.4%} ({count:,} pairs)", file=sys.stderr)

    # ----------------------------------------------------------
    # Q3: Semantic quality validation
    # ----------------------------------------------------------
    print("\n--- Q3: Semantic quality (related vs unrelated pairs) ---", file=sys.stderr)
    related_pairs: list[tuple[int, int, str]]
    unrelated_pairs: list[tuple[int, int, str]]
    related_pairs, unrelated_pairs = find_related_pairs(nodes)

    related_dists: list[int] = []
    related_details: list[dict[str, Any]] = []
    for idx1, idx2, reason in related_pairs:
        h_dist: int = int(dist_matrix[idx1, idx2])
        related_dists.append(h_dist)
        related_details.append({
            "pair": f"{nodes[idx1]['id']} / {nodes[idx2]['id']}",
            "reason": reason,
            "hamming": h_dist,
            "content1": nodes[idx1]["content"][:60],
            "content2": nodes[idx2]["content"][:60],
        })
        print(f"  RELATED  H={h_dist:3d}  {reason:<25s}  "
              f"{nodes[idx1]['id']} / {nodes[idx2]['id']}", file=sys.stderr)

    unrelated_dists: list[int] = []
    unrelated_details: list[dict[str, Any]] = []
    for idx1, idx2, reason in unrelated_pairs:
        h_dist = int(dist_matrix[idx1, idx2])
        unrelated_dists.append(h_dist)
        unrelated_details.append({
            "pair": f"{nodes[idx1]['id']} / {nodes[idx2]['id']}",
            "reason": reason,
            "hamming": h_dist,
            "content1": nodes[idx1]["content"][:60],
            "content2": nodes[idx2]["content"][:60],
        })
        print(f"  UNREL    H={h_dist:3d}  {reason:<25s}  "
              f"{nodes[idx1]['id']} / {nodes[idx2]['id']}", file=sys.stderr)

    rel_arr: FloatArray = np.array(related_dists, dtype=np.float64)
    unrel_arr: FloatArray = np.array(unrelated_dists, dtype=np.float64)

    out["q3_semantic_quality"] = {
        "related_pairs": related_details,
        "unrelated_pairs": unrelated_details,
        "related_mean": round(float(np.mean(rel_arr)), 2),
        "related_median": float(np.median(rel_arr)),
        "related_std": round(float(np.std(rel_arr)), 2),
        "unrelated_mean": round(float(np.mean(unrel_arr)), 2),
        "unrelated_median": float(np.median(unrel_arr)),
        "unrelated_std": round(float(np.std(unrel_arr)), 2),
        "separation": round(
            float(np.mean(unrel_arr)) - float(np.mean(rel_arr)), 2
        ),
        "separation_ratio": round(
            float(np.mean(unrel_arr)) / float(np.mean(rel_arr))
            if float(np.mean(rel_arr)) > 0
            else 0.0,
            3,
        ),
    }

    print(f"\n  Related   mean={np.mean(rel_arr):.1f}  median={np.median(rel_arr):.0f}  "
          f"std={np.std(rel_arr):.1f}", file=sys.stderr)
    print(f"  Unrelated mean={np.mean(unrel_arr):.1f}  median={np.median(unrel_arr):.0f}  "
          f"std={np.std(unrel_arr):.1f}", file=sys.stderr)
    print(f"  Separation: {np.mean(unrel_arr) - np.mean(rel_arr):.1f} "
          f"(ratio {np.mean(unrel_arr)/np.mean(rel_arr):.2f}x)", file=sys.stderr)

    # ----------------------------------------------------------
    # Q4: Retrieval pre-filter evaluation
    # ----------------------------------------------------------
    print("\n--- Q4: Retrieval pre-filter vs FTS5 ---", file=sys.stderr)
    fts_db: sqlite3.Connection = build_fts(nodes)

    retrieval_results: dict[str, Any] = evaluate_retrieval_prefilter(
        nodes, codes, vocab, idf_vec, hyperplanes, fts_db
    )
    out["q4_retrieval"] = retrieval_results

    for topic_name, data in retrieval_results.items():
        fts_miss: list[str] = data["fts5_missed"]
        min_k: int | None = data["min_k_full_coverage"]
        print(f"\n  {topic_name}:", file=sys.stderr)
        print(f"    FTS5: {len(data['fts5_coverage'])}/{len(data['needed'])} "
              f"{'OK' if not fts_miss else f'MISSED: {fts_miss}'}", file=sys.stderr)
        print(f"    SimHash min K for 100%: {min_k}", file=sys.stderr)
        for k in [15, 25, 35, 45]:
            sk: dict[str, Any] = data["simhash_by_k"].get(k, {})
            if sk:
                missed_str: str = "OK" if not sk["missed"] else f"MISSED: {sk['missed']}"
                print(f"    K={k:2d}: {sk['candidates']:4d} candidates, "
                      f"recall={sk['recall']:.0%} {missed_str}", file=sys.stderr)

    # ----------------------------------------------------------
    # Q5: Drift detection
    # ----------------------------------------------------------
    print("\n--- Q5: Drift detection ---", file=sys.stderr)
    drift_results: dict[str, Any] = evaluate_drift_detection(nodes, dist_matrix)
    out["q5_drift"] = drift_results

    for belief in drift_results["isolated_beliefs"]:
        print(f"  {belief['decision']}: min_H={belief['min_hamming_dist']}, "
              f"mean_H={belief['mean_hamming_dist']}, "
              f"close={belief['close_neighbors']}  "
              f"({belief['content_preview'][:50]}...)", file=sys.stderr)

    gstats: dict[str, Any] = drift_results["global_min_dist_stats"]
    print(f"\n  Global min-dist: mean={gstats['mean']}, median={gstats['median']}, "
          f"P90={gstats['p90']}, P95={gstats['p95']}", file=sys.stderr)
    if "separation_ratio" in drift_results:
        print(f"  Isolated mean min-dist: {drift_results['isolated_min_dist_mean']} "
              f"(ratio to global: {drift_results['separation_ratio']}x)", file=sys.stderr)

    # ----------------------------------------------------------
    # Q6: SimHash vs HRR comparison
    # ----------------------------------------------------------
    print("\n--- Q6: SimHash vs HRR comparison ---", file=sys.stderr)
    hrr_comparison: dict[str, Any] = compare_with_hrr(nodes, dist_matrix)
    out["q6_hrr_comparison"] = hrr_comparison

    print("\n  Vocabulary-gap cases (SimHash should FAIL, HRR PASSES):", file=sys.stderr)
    for case in hrr_comparison["vocabulary_gap_cases"]:
        print(f"    {case['pair']}: H={case['hamming_distance']}, "
              f"Jaccard={case['jaccard']}, overlap={case['token_overlap']}",
              file=sys.stderr)

    if "d157_d188_explicit" in hrr_comparison:
        expl: dict[str, Any] = hrr_comparison["d157_d188_explicit"]
        print(f"\n  D157 vs D188 explicit:", file=sys.stderr)
        print(f"    D157: {expl['d157_content'][:80]}", file=sys.stderr)
        print(f"    D188: {expl['d188_content'][:80]}", file=sys.stderr)
        print(f"    Hamming: {expl['hamming_distance']}, Jaccard: {expl['jaccard']}",
              file=sys.stderr)
        print(f"    SimHash verdict: {expl['simhash_verdict']}", file=sys.stderr)
        print(f"    HRR verdict: {expl['hrr_verdict']}", file=sys.stderr)

    print("\n  Content-similar cases (SimHash should PASS):", file=sys.stderr)
    for case in hrr_comparison["content_similar_cases"]:
        print(f"    {case['pair']}: H={case['hamming_distance']}, "
              f"Jaccard={case['jaccard']}", file=sys.stderr)

    # ----------------------------------------------------------
    # Save results
    # ----------------------------------------------------------
    out_path: Path = Path("experiments/exp46_simhash_results.json")
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n\nResults saved to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
