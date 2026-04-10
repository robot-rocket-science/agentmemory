"""
Experiment 39: Automatic Query Expansion Without LLM

Hypothesis: Corpus-derived PMI maps + pseudo-relevance feedback (PRF) can
automatically replicate the coverage of hand-crafted multi-query formulations
from Exp 9. Target: match or exceed 100% critical belief coverage on 6 topics,
using only a single initial query per topic.

Method:
  1. Build PMI co-occurrence map from alpha-seek belief corpus
  2. Implement PRF (two-pass FTS5 with TF-IDF term extraction)
  3. Compare: single-query baseline, PMI expansion, PRF, PMI+PRF combined
  4. Ground truth: 6 topics x 13 critical decisions from Exp 9

Zero-LLM. All techniques are statistical, deterministic, and sub-10ms per query.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

ALPHA_SEEK_DB = Path("/Users/thelorax/projects/.gsd/workflows/spikes/"
                     "260406-1-associative-memory-for-gsd-please-explor/"
                     "sandbox/alpha-seek.db")

# Ground truth from Exp 9
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

STOPWORDS = {
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
}


# ============================================================
# Data loading
# ============================================================

def load_nodes() -> dict[str, str]:
    """Load all active belief nodes from alpha-seek DB."""
    db = sqlite3.connect(str(ALPHA_SEEK_DB))
    nodes: dict[str, str] = {}
    for row in db.execute("SELECT id, content FROM mem_nodes WHERE superseded_by IS NULL"):
        nodes[str(row[0])] = str(row[1])
    db.close()
    return nodes


def tokenize(text: str) -> list[str]:
    """Simple tokenizer: lowercase, alpha-only, no stopwords, min 2 chars."""
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) >= 2]


def build_fts(nodes: dict[str, str]) -> sqlite3.Connection:
    """Build in-memory FTS5 index."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE fts USING fts5(id, content, tokenize='porter')")
    for nid, content in nodes.items():
        db.execute("INSERT INTO fts VALUES (?, ?)", (nid, content))
    db.commit()
    return db


def search_fts(query: str, fts_db: sqlite3.Connection, top_k: int = 30) -> list[str]:
    """FTS5 search with OR terms."""
    terms = [t.strip() for t in query.split() if len(t.strip()) > 2]
    if not terms:
        return []
    fts_query = " OR ".join(terms)
    try:
        results = fts_db.execute(
            "SELECT id FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT ?",
            (fts_query, top_k)
        ).fetchall()
        return [str(r[0]) for r in results]
    except Exception:
        return []


# ============================================================
# PMI Co-occurrence Map
# ============================================================

def build_pmi_map(nodes: dict[str, str], min_cooccur: int = 3, top_k: int = 5) -> dict[str, list[tuple[str, float]]]:
    """Build PMI co-occurrence map from belief corpus.

    Returns dict mapping each word to its top-k PMI associates.
    """
    # Tokenize all documents
    doc_tokens: list[set[str]] = []
    for content in nodes.values():
        tokens = set(tokenize(content))
        doc_tokens.append(tokens)

    n_docs = len(doc_tokens)

    # Document frequency for each word
    df: Counter[str] = Counter()
    for tokens in doc_tokens:
        for t in tokens:
            df[t] += 1

    # Filter: only words appearing in >= 3 docs and <= 50% of docs
    vocab = {w for w, count in df.items() if count >= min_cooccur and count <= n_docs * 0.5}

    # Co-occurrence frequency
    cooccur: Counter[tuple[str, str]] = Counter()
    for tokens in doc_tokens:
        filtered = sorted(tokens & vocab)
        for i, a in enumerate(filtered):
            for b in filtered[i+1:]:
                cooccur[(a, b)] += 1

    # Compute PMI
    pmi_scores: dict[str, list[tuple[str, float]]] = defaultdict(list)

    for (a, b), count in cooccur.items():
        if count < min_cooccur:
            continue
        p_ab = count / n_docs
        p_a = df[a] / n_docs
        p_b = df[b] / n_docs
        pmi = math.log2(p_ab / (p_a * p_b))
        if pmi > 0:
            pmi_scores[a].append((b, round(pmi, 3)))
            pmi_scores[b].append((a, round(pmi, 3)))

    # Keep top-k per word
    result: dict[str, list[tuple[str, float]]] = {}
    for word, associates in pmi_scores.items():
        associates.sort(key=lambda x: x[1], reverse=True)
        result[word] = associates[:top_k]

    return result


def expand_with_pmi(query: str, pmi_map: dict[str, list[tuple[str, float]]], max_expand: int = 10) -> str:
    """Expand query terms using PMI co-occurrence map."""
    original_terms = tokenize(query)
    expansion_terms: list[str] = []

    for term in original_terms:
        if term in pmi_map:
            for associate, _score in pmi_map[term][:3]:  # top-3 per query term
                if associate not in original_terms and associate not in expansion_terms:
                    expansion_terms.append(associate)

    expansion_terms = expansion_terms[:max_expand]
    all_terms = original_terms + expansion_terms
    return " ".join(all_terms)


# ============================================================
# Pseudo-Relevance Feedback (PRF)
# ============================================================

def prf_expand(query: str, fts_db: sqlite3.Connection, nodes: dict[str, str],
               initial_k: int = 5, expand_terms: int = 10) -> str:
    """Two-pass PRF: retrieve top-k, extract distinctive terms, re-query."""
    # First pass
    initial_results = search_fts(query, fts_db, top_k=initial_k)
    if not initial_results:
        return query

    # Collect terms from initial results
    result_terms: Counter[str] = Counter()
    for nid in initial_results:
        if nid in nodes:
            for t in tokenize(nodes[nid]):
                result_terms[t] += 1

    # Compute TF-IDF-like score for each result term
    # TF = frequency in results, IDF = inverse document frequency in full corpus
    n_docs = len(nodes)
    all_doc_tokens = [set(tokenize(c)) for c in nodes.values()]
    doc_freq: Counter[str] = Counter()
    for tokens in all_doc_tokens:
        for t in tokens:
            doc_freq[t] += 1

    term_scores: list[tuple[str, float]] = []
    original_terms = set(tokenize(query))

    for term, tf in result_terms.items():
        if term in original_terms:
            continue  # Skip terms already in query
        if term in STOPWORDS:
            continue
        df = doc_freq.get(term, 1)
        idf = math.log2(n_docs / df)
        score = tf * idf
        term_scores.append((term, score))

    # Sort by score, take top expansion terms
    term_scores.sort(key=lambda x: x[1], reverse=True)
    expansion = [t for t, _ in term_scores[:expand_terms]]

    all_terms = list(original_terms) + expansion
    return " ".join(all_terms)


# ============================================================
# Evaluation
# ============================================================

def evaluate_method(method_name: str, search_fn: Callable[[str], list[str]], topics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Evaluate a search method against ground truth topics."""
    results: dict[str, Any] = {"method": method_name, "per_topic": {}}
    total_needed = 0
    total_found = 0

    for topic_name, topic_data in topics.items():
        needed = set(topic_data["needed"])
        total_needed += len(needed)

        retrieved = search_fn(topic_data["single_query"])
        # Extract decision IDs from retrieved node IDs
        found_decisions: set[str] = set()
        for nid in retrieved:
            # Node IDs like "D089_s0" or just "D089"
            match = re.match(r"(D\d{3})", nid)
            if match:
                found_decisions.add(match.group(1))

        found = needed & found_decisions
        total_found += len(found)

        results["per_topic"][topic_name] = {
            "needed": sorted(needed),
            "found": sorted(found),
            "missed": sorted(needed - found),
            "coverage": round(len(found) / len(needed), 3) if needed else 1.0,
            "total_retrieved": len(retrieved),
        }

    results["overall_coverage"] = round(total_found / total_needed, 3) if total_needed else 1.0
    results["total_needed"] = total_needed
    results["total_found"] = total_found
    return results


# ============================================================
# Main
# ============================================================

def main() -> None:
    print("=== Experiment 39: Automatic Query Expansion ===", file=sys.stderr)

    # Load data
    print("Loading nodes...", file=sys.stderr)
    nodes = load_nodes()
    print(f"  {len(nodes)} belief nodes loaded", file=sys.stderr)

    print("Building FTS5 index...", file=sys.stderr)
    fts_db = build_fts(nodes)

    print("Building PMI co-occurrence map...", file=sys.stderr)
    pmi_map = build_pmi_map(nodes)
    print(f"  {len(pmi_map)} words in PMI map", file=sys.stderr)

    # Show sample PMI associations for key terms
    print("\n--- PMI Sample Associations ---", file=sys.stderr)
    for term in ["dispatch", "gate", "capital", "typing", "gcp", "agent", "deploy",
                 "puts", "calls", "archon", "pyright", "strict"]:
        if term in pmi_map:
            assoc = pmi_map[term][:5]
            assoc_str = ", ".join(f"{w}({s:.1f})" for w, s in assoc)
            print(f"  {term:>12} -> {assoc_str}", file=sys.stderr)
        else:
            print(f"  {term:>12} -> (not in PMI map)", file=sys.stderr)

    # Define search methods
    def search_baseline(query: str) -> list[str]:
        return search_fts(query, fts_db, top_k=30)

    def search_pmi(query: str) -> list[str]:
        expanded = expand_with_pmi(query, pmi_map)
        return search_fts(expanded, fts_db, top_k=30)

    def search_prf(query: str) -> list[str]:
        expanded = prf_expand(query, fts_db, nodes)
        return search_fts(expanded, fts_db, top_k=30)

    def search_combined(query: str) -> list[str]:
        # PMI expand first, then PRF on the expanded query
        pmi_expanded = expand_with_pmi(query, pmi_map)
        prf_expanded = prf_expand(pmi_expanded, fts_db, nodes)
        return search_fts(prf_expanded, fts_db, top_k=30)

    # Run evaluations
    methods = [
        ("baseline_single_query", search_baseline),
        ("pmi_expansion", search_pmi),
        ("pseudo_relevance_feedback", search_prf),
        ("pmi_plus_prf", search_combined),
    ]

    all_results: dict[str, Any] = {}
    print("\n--- Results ---", file=sys.stderr)

    for method_name, search_fn in methods:
        result = evaluate_method(method_name, search_fn, CRITICAL_BELIEFS)
        all_results[method_name] = result

        print(f"\n{method_name}: overall coverage = {result['overall_coverage']:.0%} "
              f"({result['total_found']}/{result['total_needed']})", file=sys.stderr)
        for topic, data in result["per_topic"].items():
            status = "OK" if not data["missed"] else f"MISSED: {data['missed']}"
            print(f"  {topic:<20} {data['coverage']:.0%}  {status}", file=sys.stderr)

    # Show expanded queries for debugging
    print("\n--- Expanded Queries ---", file=sys.stderr)
    for topic, data in CRITICAL_BELIEFS.items():
        q = data["single_query"]
        pmi_q = expand_with_pmi(q, pmi_map)
        prf_q = prf_expand(q, fts_db, nodes)
        combined_q = prf_expand(expand_with_pmi(q, pmi_map), fts_db, nodes)
        print(f"\n  {topic}:", file=sys.stderr)
        print(f"    original: {q}", file=sys.stderr)
        print(f"    PMI:      {pmi_q}", file=sys.stderr)
        print(f"    PRF:      {prf_q}", file=sys.stderr)
        print(f"    combined: {combined_q}", file=sys.stderr)

    # Summary table
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"{'Method':<30} {'Coverage':>10} {'Found':>8}", file=sys.stderr)
    print("-" * 50, file=sys.stderr)
    for method_name, result in all_results.items():
        print(f"{method_name:<30} {result['overall_coverage']:>10.0%} "
              f"{result['total_found']:>5}/{result['total_needed']}", file=sys.stderr)

    # Method 5: PMI-generated multi-query (auto-generate 3 queries per topic)
    def search_multi_pmi(query: str) -> list[str]:
        """Generate 3 query formulations using PMI associations, union results."""
        original_terms = tokenize(query)
        all_results_set: set[str] = set()

        # Query 1: original
        all_results_set.update(search_fts(query, fts_db, top_k=30))

        # Query 2: replace each term with its top PMI associate
        alt_terms: list[str] = []
        for term in original_terms:
            if term in pmi_map and pmi_map[term]:
                alt_terms.append(pmi_map[term][0][0])  # top-1 associate
            else:
                alt_terms.append(term)
        q2 = " ".join(alt_terms)
        all_results_set.update(search_fts(q2, fts_db, top_k=30))

        # Query 3: PRF on original
        q3 = prf_expand(query, fts_db, nodes)
        all_results_set.update(search_fts(q3, fts_db, top_k=30))

        return list(all_results_set)

    multi_result = evaluate_method("multi_pmi_3query", search_multi_pmi, CRITICAL_BELIEFS)
    all_results["multi_pmi_3query"] = multi_result
    print(f"\nmulti_pmi_3query: overall coverage = {multi_result['overall_coverage']:.0%} "
          f"({multi_result['total_found']}/{multi_result['total_needed']})", file=sys.stderr)
    for topic, data in multi_result["per_topic"].items():
        status = "OK" if not data["missed"] else f"MISSED: {data['missed']}"
        print(f"  {topic:<20} {data['coverage']:.0%}  {status}", file=sys.stderr)

    # Method 6: aggressive union -- all methods combined
    def search_union_all(query: str) -> list[str]:
        """Union of all expansion methods."""
        results: set[str] = set()
        results.update(search_fts(query, fts_db, top_k=30))
        results.update(search_fts(expand_with_pmi(query, pmi_map), fts_db, top_k=30))
        results.update(search_fts(prf_expand(query, fts_db, nodes), fts_db, top_k=30))
        results.update(search_fts(prf_expand(expand_with_pmi(query, pmi_map), fts_db, nodes), fts_db, top_k=30))
        return list(results)

    union_result = evaluate_method("union_all_methods", search_union_all, CRITICAL_BELIEFS)
    all_results["union_all_methods"] = union_result
    print(f"\nunion_all_methods: overall coverage = {union_result['overall_coverage']:.0%} "
          f"({union_result['total_found']}/{union_result['total_needed']})", file=sys.stderr)
    for topic, data in union_result["per_topic"].items():
        status = "OK" if not data["missed"] else f"MISSED: {data['missed']}"
        print(f"  {topic:<20} {data['coverage']:.0%}  {status}", file=sys.stderr)

    # Compare to Exp 9 hand-crafted 3-query (100% coverage)
    print(f"\n{'Exp 9 hand-crafted 3-query':<30} {'100%':>10} {'13':>5}/13", file=sys.stderr)

    # Save results
    out = Path("experiments/exp39_results.json")
    # Include PMI map sample for documentation
    pmi_sample: dict[str, list[tuple[str, float]]] = {}
    for term in ["dispatch", "gate", "capital", "typing", "gcp", "deploy", "calls", "puts"]:
        if term in pmi_map:
            pmi_sample[term] = pmi_map[term][:5]

    all_results["pmi_map_sample"] = pmi_sample
    all_results["pmi_map_size"] = len(pmi_map)
    all_results["corpus_size"] = len(nodes)

    out.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nResults saved to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
