from __future__ import annotations

"""
Experiment 42: Information Bottleneck Compression -- Empirical Validation

Tests the type-aware compression heuristic proposed in Exp 20:
  - constraints: 1.0x (full preservation)
  - evidence: 0.6x (truncate to core claim)
  - context: 0.3x (aggressive truncation)
  - rationale: 0.4x
  - supersession: pointer-only (~8 tokens)
  - implementation: 0.3x

Method:
  1. Decompose 173 decisions into sentence nodes (replicating Exp 16)
  2. Build FTS5 indexes on full and compressed sentence nodes
  3. Measure retrieval coverage on 6 critical topics (ground truth from Exp 9)
  4. Compute token savings by type and overall
  5. Measure within-type compression variance (does full IB add value?)
  6. Test keyword-only compression for retrieval-aware comparison

Zero-LLM. Uses only FTS5 + standard library + numpy.
"""

import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

NDArr = npt.NDArray[np.floating[Any]]

ALPHA_SEEK_DB = Path(
    "/home/user/projects/.gsd/workflows/spikes/"
    "260406-1-associative-memory-for-gsd-please-explor/"
    "sandbox/project-a.db"
)

# Ground truth from Exp 9: 6 critical topics, 13 decisions total
CRITICAL_BELIEFS: dict[str, dict[str, list[str] | str]] = {
    "dispatch_gate": {
        "queries": [
            "dispatch gate deploy protocol",
            "follow deploy gate verification",
            "dispatch runbook GCP",
        ],
        "needed": ["D089", "D106", "D137"],
    },
    "calls_puts": {
        "queries": [
            "calls puts equal citizens",
            "put call strategy direction",
            "options both directions",
        ],
        "needed": ["D073", "D096", "D100"],
    },
    "capital_5k": {
        "queries": [
            "starting capital bankroll",
            "initial investment amount",
            "how much money USD",
        ],
        "needed": ["D099"],
    },
    "agent_behavior": {
        "queries": [
            "agent behavior instructions",
            "dont elaborate pontificate",
            "execute precisely return control",
        ],
        "needed": ["D157", "D188"],
    },
    "strict_typing": {
        "queries": [
            "typing pyright strict",
            "type annotations python",
            "static type checking",
        ],
        "needed": ["D071", "D113"],
    },
    "gcp_primary": {
        "queries": [
            "GCP primary compute platform",
            "server-a overflow only",
            "cloud compute infrastructure",
        ],
        "needed": ["D078", "D120"],
    },
}

# Type-aware compression ratios from Exp 20
COMPRESSION_RATIOS: dict[str, float] = {
    "constraint": 1.0,
    "evidence": 0.6,
    "context": 0.3,
    "rationale": 0.4,
    "supersession": 0.0,  # special: compress to pointer
    "implementation": 0.3,
}

SUPERSESSION_TARGET_TOKENS: int = 8  # "D097 supersedes D045" format

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
# Sentence decomposition (from Exp 16)
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
    if any(
        w in s for w in ["because", "rationale", "reason", "driven by", "root cause"]
    ):
        return "rationale"
    if any(w in s for w in ["supersede", "replace", "retire", "override"]):
        return "supersession"
    if any(w in s for w in ["must", "always", "never", "mandatory", "require", "rule"]):
        return "constraint"
    if any(
        w in s for w in ["data", "showed", "result", "found", "measured", "%", "x "]
    ):
        return "evidence"
    if any(w in s for w in ["script", "implement", "code", ".py", "function"]):
        return "implementation"
    return "context"


def count_tokens(text: str) -> int:
    """Approximate token count (chars / 4)."""
    return max(1, len(text) // 4)


# ============================================================
# Compression strategies
# ============================================================


def compress_truncate(text: str, target_tokens: int) -> str:
    """Compress by truncating to target token count (word-boundary)."""
    if count_tokens(text) <= target_tokens:
        return text
    target_chars: int = target_tokens * 4
    if target_chars >= len(text):
        return text
    # Find word boundary near target
    truncated: str = text[:target_chars]
    last_space: int = truncated.rfind(" ")
    if last_space > target_chars // 2:
        truncated = truncated[:last_space]
    return truncated.rstrip(".,;:- ")


def compress_to_pointer(text: str) -> str:
    """Compress supersession node to pointer format."""
    refs: list[str] = re.findall(r"\b[DM]\d{2,3}\b", text)
    if len(refs) >= 2:
        return f"{refs[0]} supersedes {refs[1]}"
    if len(refs) == 1:
        return f"{refs[0]} superseded"
    # No refs found, truncate hard
    return compress_truncate(text, SUPERSESSION_TARGET_TOKENS)


def extract_keywords(text: str) -> str:
    """Extract non-stopword tokens for keyword-only representation."""
    words: list[str] = re.findall(r"[a-zA-Z0-9_.%-]+", text)
    keywords: list[str] = [
        w for w in words if w.lower() not in STOPWORDS and len(w) >= 2
    ]
    return " ".join(keywords)


SentenceNode = dict[str, Any]


def apply_type_compression(node: SentenceNode) -> str:
    """Apply type-aware compression to a sentence node."""
    content: str = str(node["content"])
    stype: str = str(node["type"])
    original_tokens: int = count_tokens(content)

    if stype == "supersession":
        return compress_to_pointer(content)

    ratio: float = COMPRESSION_RATIOS.get(stype, 0.5)
    target_tokens: int = max(3, int(original_tokens * ratio))
    return compress_truncate(content, target_tokens)


# ============================================================
# FTS5 search
# ============================================================


def build_fts_index(
    nodes: list[SentenceNode],
    use_content_key: str = "content",
) -> sqlite3.Connection:
    """Build an in-memory FTS5 index from sentence nodes."""
    db: sqlite3.Connection = sqlite3.connect(":memory:")
    db.execute(
        "CREATE VIRTUAL TABLE fts USING fts5("
        "node_id, parent_decision, content, tokenize='porter')"
    )
    for node in nodes:
        db.execute(
            "INSERT INTO fts VALUES (?, ?, ?)",
            (str(node["id"]), str(node["parent_decision"]), str(node[use_content_key])),
        )
    return db


def fts_search(db: sqlite3.Connection, query: str) -> list[str]:
    """Search FTS5 and return parent decision IDs (deduplicated, ranked)."""
    # Use OR query for broader coverage
    terms: list[str] = query.split()
    fts_query: str = " OR ".join(terms)
    try:
        rows: list[tuple[str, ...]] = db.execute(
            "SELECT parent_decision, rank FROM fts WHERE fts MATCH ? "
            "ORDER BY rank LIMIT 100",
            (fts_query,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    seen: set[str] = set()
    results: list[str] = []
    for row in rows:
        did: str = str(row[0])
        if did not in seen:
            seen.add(did)
            results.append(did)
    return results


def evaluate_coverage(
    db: sqlite3.Connection,
    label: str,
) -> dict[str, Any]:
    """Evaluate retrieval coverage on 6 critical topics."""
    results: dict[str, Any] = {
        "method": label,
        "per_topic": {},
        "total_needed": 0,
        "total_found": 0,
    }
    for topic, spec in CRITICAL_BELIEFS.items():
        queries: list[str] = list(spec["queries"])  # type: ignore[arg-type]
        needed: list[str] = list(spec["needed"])  # type: ignore[arg-type]
        results["total_needed"] += len(needed)

        # Union of results across all queries for this topic
        found_decisions: set[str] = set()
        for q in queries:
            hits: list[str] = fts_search(db, q)
            for h in hits:
                found_decisions.add(h)

        found: list[str] = [d for d in needed if d in found_decisions]
        missed: list[str] = [d for d in needed if d not in found_decisions]
        results["total_found"] += len(found)

        results["per_topic"][topic] = {
            "needed": needed,
            "found": found,
            "missed": missed,
            "coverage": len(found) / len(needed) if needed else 1.0,
        }

    total_needed: int = int(results["total_needed"])
    total_found: int = int(results["total_found"])
    results["overall_coverage"] = (
        total_found / total_needed if total_needed > 0 else 1.0
    )
    return results


# ============================================================
# Within-type variance analysis
# ============================================================


def compute_type_variance(
    nodes: list[SentenceNode],
) -> dict[str, dict[str, float]]:
    """Compute token count stats per type to assess IB value.

    If within-type variance is low, the heuristic is near-optimal.
    If variance is high, per-node IB optimization could help.
    """
    type_tokens: dict[str, list[int]] = defaultdict(list)
    for node in nodes:
        stype: str = str(node["type"])
        tokens: int = count_tokens(str(node["content"]))
        type_tokens[stype].append(tokens)

    stats: dict[str, dict[str, float]] = {}
    for stype, token_list in sorted(type_tokens.items()):
        arr: NDArr = np.array(token_list, dtype=np.float64)
        mean_val: float = float(np.mean(arr))
        std_val: float = float(np.std(arr))
        cv: float = std_val / mean_val if mean_val > 0 else 0.0
        stats[stype] = {
            "count": float(len(token_list)),
            "mean_tokens": round(mean_val, 1),
            "std_tokens": round(std_val, 1),
            "cv": round(cv, 3),  # coefficient of variation
            "min_tokens": float(min(token_list)),
            "max_tokens": float(max(token_list)),
            "p25_tokens": round(float(np.percentile(arr, 25)), 1),
            "p75_tokens": round(float(np.percentile(arr, 75)), 1),
        }
    return stats


# ============================================================
# IB-to-HRR dimension mapping (Question 4)
# ============================================================


def ib_to_hrr_dimension(
    type_stats: dict[str, dict[str, float]],
    compression_ratios: dict[str, float],
    snr_target: float = 5.0,
    num_edges_per_node: float = 25.0,
) -> dict[str, dict[str, float]]:
    """Estimate minimum HRR dimension from IB-optimal representation size.

    Theory: If a belief's IB-optimal representation is K bits,
    HRR dimension D must satisfy:
        SNR = sqrt(D / num_edges) >= snr_target
    => D >= snr_target^2 * num_edges

    But K (the IB rate) tells us how many EFFECTIVE bits we need.
    If K < log2(D), HRR has spare capacity. If K > log2(D), some
    beliefs will alias (false similarity).

    For text-based nodes, K ~ compressed_tokens * bits_per_token.
    We use ~4 bits per token as a rough entropy estimate (English
    text has ~1-4 bits per character, tokens are ~4 chars).
    """
    bits_per_token: float = 16.0  # ~4 bits/char * 4 chars/token
    results: dict[str, dict[str, float]] = {}

    for stype, stats in type_stats.items():
        ratio: float = compression_ratios.get(stype, 0.5)
        compressed_mean: float = stats["mean_tokens"] * ratio
        ib_bits: float = compressed_mean * bits_per_token

        # Minimum HRR dim from SNR requirement
        min_dim_snr: float = snr_target**2 * num_edges_per_node

        # Minimum HRR dim from information capacity
        # HRR at dimension D can faithfully store ~D/2 independent bits
        # per superposition slot (Johnson-Lindenstrauss bound)
        min_dim_info: float = 2.0 * ib_bits

        results[stype] = {
            "compressed_mean_tokens": round(compressed_mean, 1),
            "ib_bits": round(ib_bits, 0),
            "min_dim_snr": round(min_dim_snr, 0),
            "min_dim_info": round(min_dim_info, 0),
            "binding_dim": round(max(min_dim_snr, min_dim_info), 0),
        }

    return results


# ============================================================
# Main experiment
# ============================================================


def main() -> None:
    db: sqlite3.Connection = sqlite3.connect(str(ALPHA_SEEK_DB))

    decisions: list[tuple[str, ...]] = db.execute(
        "SELECT id, decision, choice, rationale FROM decisions ORDER BY seq"
    ).fetchall()
    db.close()

    print(f"Loading {len(decisions)} decisions...", file=sys.stderr)

    # Step 1: Decompose into sentence nodes
    all_nodes: list[SentenceNode] = []
    for row in decisions:
        did: str = str(row[0])
        full_text: str = f"{row[1]}: {row[2]}"
        if row[3]:
            full_text += f" | {row[3]}"

        sentences: list[str] = split_into_sentences(full_text)
        for i, sent in enumerate(sentences):
            node: SentenceNode = {
                "id": f"{did}_s{i}",
                "parent_decision": did,
                "sentence_index": i,
                "content": sent,
                "tokens": count_tokens(sent),
                "type": classify_sentence(sent),
            }
            all_nodes.append(node)

    print(f"  {len(all_nodes)} sentence nodes", file=sys.stderr)

    # Step 2: Apply compression strategies
    # Strategy A: Full (no compression)
    # Strategy B: Type-aware truncation
    # Strategy C: Keyword-only (retrieval-optimized)
    for node in all_nodes:
        content: str = str(node["content"])
        node["compressed"] = apply_type_compression(node)
        node["keywords"] = extract_keywords(content)
        node["compressed_tokens"] = count_tokens(str(node["compressed"]))
        node["keyword_tokens"] = count_tokens(str(node["keywords"]))

    # Step 3: Build FTS5 indexes
    print("Building FTS5 indexes...", file=sys.stderr)
    fts_full: sqlite3.Connection = build_fts_index(all_nodes, "content")
    fts_compressed: sqlite3.Connection = build_fts_index(all_nodes, "compressed")
    fts_keywords: sqlite3.Connection = build_fts_index(all_nodes, "keywords")

    # Step 4: Evaluate retrieval coverage
    print("Evaluating retrieval coverage...", file=sys.stderr)
    cov_full: dict[str, Any] = evaluate_coverage(fts_full, "full")
    cov_compressed: dict[str, Any] = evaluate_coverage(
        fts_compressed, "type_compressed"
    )
    cov_keywords: dict[str, Any] = evaluate_coverage(fts_keywords, "keyword_only")

    # Step 5: Token analysis
    type_tokens_full: dict[str, int] = defaultdict(int)
    type_tokens_compressed: dict[str, int] = defaultdict(int)
    type_tokens_keywords: dict[str, int] = defaultdict(int)
    type_counts: dict[str, int] = defaultdict(int)

    for node in all_nodes:
        stype: str = str(node["type"])
        type_counts[stype] += 1
        type_tokens_full[stype] += int(node["tokens"])
        type_tokens_compressed[stype] += int(node["compressed_tokens"])
        type_tokens_keywords[stype] += int(node["keyword_tokens"])

    total_full: int = sum(type_tokens_full.values())
    total_compressed: int = sum(type_tokens_compressed.values())
    total_keywords: int = sum(type_tokens_keywords.values())

    # Step 6: Within-type variance
    type_variance: dict[str, dict[str, float]] = compute_type_variance(all_nodes)

    # Step 7: IB-to-HRR dimension mapping
    hrr_dims: dict[str, dict[str, float]] = ib_to_hrr_dimension(
        type_variance, COMPRESSION_RATIOS
    )

    # Step 8: Retrieval-aware compression analysis
    # Test: which nodes lose retrievability under compression?
    retrieval_loss_nodes: list[dict[str, str]] = []
    for topic, spec in CRITICAL_BELIEFS.items():
        queries_list: list[str] = list(spec["queries"])  # type: ignore[arg-type]
        needed_list: list[str] = list(spec["needed"])  # type: ignore[arg-type]

        full_found: set[str] = set()
        compressed_found: set[str] = set()
        keyword_found: set[str] = set()
        for q in queries_list:
            for h in fts_search(fts_full, q):
                full_found.add(h)
            for h in fts_search(fts_compressed, q):
                compressed_found.add(h)
            for h in fts_search(fts_keywords, q):
                keyword_found.add(h)

        for d in needed_list:
            if d in full_found and d not in compressed_found:
                retrieval_loss_nodes.append(
                    {
                        "topic": topic,
                        "decision": d,
                        "lost_in": "compressed",
                    }
                )
            if d in full_found and d not in keyword_found:
                retrieval_loss_nodes.append(
                    {
                        "topic": topic,
                        "decision": d,
                        "lost_in": "keywords",
                    }
                )

    # ============================================================
    # Print results
    # ============================================================

    print(f"\n{'=' * 70}", file=sys.stderr)
    print("EXPERIMENT 42: IB COMPRESSION RESULTS", file=sys.stderr)
    print(f"{'=' * 70}", file=sys.stderr)

    # Q1: Retrieval coverage
    print("\n--- Q1: Retrieval Coverage ---", file=sys.stderr)
    print(
        f"  Full nodes:       {cov_full['overall_coverage']:.0%} "
        f"({cov_full['total_found']}/{cov_full['total_needed']})",
        file=sys.stderr,
    )
    print(
        f"  Type-compressed:  {cov_compressed['overall_coverage']:.0%} "
        f"({cov_compressed['total_found']}/{cov_compressed['total_needed']})",
        file=sys.stderr,
    )
    print(
        f"  Keyword-only:     {cov_keywords['overall_coverage']:.0%} "
        f"({cov_keywords['total_found']}/{cov_keywords['total_needed']})",
        file=sys.stderr,
    )

    print("\n  Per-topic detail:", file=sys.stderr)
    for topic in CRITICAL_BELIEFS:
        fc: float = float(cov_full["per_topic"][topic]["coverage"])
        cc: float = float(cov_compressed["per_topic"][topic]["coverage"])
        kc: float = float(cov_keywords["per_topic"][topic]["coverage"])
        cm: list[str] = list(cov_compressed["per_topic"][topic]["missed"])
        km: list[str] = list(cov_keywords["per_topic"][topic]["missed"])
        print(
            f"    {topic:20s}  full={fc:.0%}  compressed={cc:.0%}  keywords={kc:.0%}",
            file=sys.stderr,
        )
        if cm:
            print(f"      compressed missed: {cm}", file=sys.stderr)
        if km:
            print(f"      keywords missed: {km}", file=sys.stderr)

    # Q2: Token savings
    print("\n--- Q2: Token Savings ---", file=sys.stderr)
    print(
        f"  {'Type':<16s} {'Count':>6s} {'Full':>8s} {'Compressed':>11s} "
        f"{'Keywords':>9s} {'Ratio':>7s}",
        file=sys.stderr,
    )
    print(
        f"  {'-' * 16} {'-' * 6} {'-' * 8} {'-' * 11} {'-' * 9} {'-' * 7}",
        file=sys.stderr,
    )
    for stype in sorted(type_counts.keys()):
        count: int = type_counts[stype]
        tf: int = type_tokens_full[stype]
        tc: int = type_tokens_compressed[stype]
        tk: int = type_tokens_keywords[stype]
        actual_ratio: float = tc / tf if tf > 0 else 0.0
        print(
            f"  {stype:<16s} {count:>6d} {tf:>8,d} {tc:>11,d} "
            f"{tk:>9,d} {actual_ratio:>7.2f}",
            file=sys.stderr,
        )

    print(
        f"  {'TOTAL':<16s} {sum(type_counts.values()):>6d} {total_full:>8,d} "
        f"{total_compressed:>11,d} {total_keywords:>9,d} "
        f"{total_compressed / total_full:>7.2f}",
        file=sys.stderr,
    )
    print(
        f"\n  Savings: {total_full - total_compressed:,d} tokens "
        f"({(1 - total_compressed / total_full):.0%} reduction)",
        file=sys.stderr,
    )
    print("  REQ-003 budget: 2,000 tokens", file=sys.stderr)
    print(
        f"  Compressed corpus: {total_compressed:,d} tokens "
        f"({'EXCEEDS' if total_compressed > 2000 else 'WITHIN'} budget)",
        file=sys.stderr,
    )
    print(
        "  Note: REQ-003 applies to retrieval RESULT, not full corpus.", file=sys.stderr
    )
    print(f"  At retrieval: top-k nodes, not all {len(all_nodes):,d}", file=sys.stderr)

    # Estimate typical retrieval payload
    avg_compressed_per_node: float = total_compressed / len(all_nodes)
    nodes_in_budget: int = (
        int(2000 / avg_compressed_per_node) if avg_compressed_per_node > 0 else 0
    )
    print(
        f"  Avg compressed tokens/node: {avg_compressed_per_node:.1f}", file=sys.stderr
    )
    print(f"  Nodes fitting in 2K budget: ~{nodes_in_budget}", file=sys.stderr)

    # Q3: Within-type variance (does full IB add value?)
    print("\n--- Q3: Within-Type Variance ---", file=sys.stderr)
    print(
        f"  {'Type':<16s} {'Count':>6s} {'Mean':>6s} {'Std':>6s} "
        f"{'CV':>6s} {'Min':>5s} {'Max':>5s} {'IQR':>10s}",
        file=sys.stderr,
    )
    print(
        f"  {'-' * 16} {'-' * 6} {'-' * 6} {'-' * 6} {'-' * 6} "
        f"{'-' * 5} {'-' * 5} {'-' * 10}",
        file=sys.stderr,
    )
    for stype in sorted(type_variance.keys()):
        tv: dict[str, float] = type_variance[stype]
        iqr_str: str = f"{tv['p25_tokens']:.0f}-{tv['p75_tokens']:.0f}"
        print(
            f"  {stype:<16s} {tv['count']:>6.0f} {tv['mean_tokens']:>6.1f} "
            f"{tv['std_tokens']:>6.1f} {tv['cv']:>6.3f} "
            f"{tv['min_tokens']:>5.0f} {tv['max_tokens']:>5.0f} "
            f"{iqr_str:>10s}",
            file=sys.stderr,
        )

    # Interpret CV
    high_var_types: list[str] = [t for t, s in type_variance.items() if s["cv"] > 0.5]
    low_var_types: list[str] = [t for t, s in type_variance.items() if s["cv"] <= 0.5]
    print(
        f"\n  Low variance (CV <= 0.5, heuristic near-optimal): {low_var_types}",
        file=sys.stderr,
    )
    print(
        f"  High variance (CV > 0.5, IB could help): {high_var_types}", file=sys.stderr
    )

    # Q4: IB-to-HRR dimension
    print("\n--- Q4: IB-to-HRR Dimension Mapping ---", file=sys.stderr)
    print(
        "  Assumptions: SNR target=5.0, edges/node=25, ~16 bits/token", file=sys.stderr
    )
    print(
        f"  {'Type':<16s} {'Comp.Tok':>9s} {'IB Bits':>8s} "
        f"{'MinDim(SNR)':>12s} {'MinDim(Info)':>13s} {'Binding':>8s}",
        file=sys.stderr,
    )
    print(
        f"  {'-' * 16} {'-' * 9} {'-' * 8} {'-' * 12} {'-' * 13} {'-' * 8}",
        file=sys.stderr,
    )
    for stype in sorted(hrr_dims.keys()):
        hd: dict[str, float] = hrr_dims[stype]
        print(
            f"  {stype:<16s} {hd['compressed_mean_tokens']:>9.1f} "
            f"{hd['ib_bits']:>8.0f} {hd['min_dim_snr']:>12.0f} "
            f"{hd['min_dim_info']:>13.0f} {hd['binding_dim']:>8.0f}",
            file=sys.stderr,
        )

    # Q5: Retrieval-aware compression
    print("\n--- Q5: Retrieval-Aware Compression ---", file=sys.stderr)
    if retrieval_loss_nodes:
        print(f"  Retrieval losses: {len(retrieval_loss_nodes)}", file=sys.stderr)
        for loss in retrieval_loss_nodes:
            print(
                f"    {loss['topic']}/{loss['decision']}: lost in {loss['lost_in']}",
                file=sys.stderr,
            )
    else:
        print("  No retrieval losses detected.", file=sys.stderr)

    # Show sample compressions
    print("\n  Sample compressions (first of each type):", file=sys.stderr)
    shown_types: set[str] = set()
    for node in all_nodes:
        stype_str: str = str(node["type"])
        if stype_str in shown_types:
            continue
        shown_types.add(stype_str)
        original: str = str(node["content"])
        compressed_text: str = str(node["compressed"])
        keyword_text: str = str(node["keywords"])
        print(
            f"\n    [{stype_str}] original ({node['tokens']}t): {original[:80]}...",
            file=sys.stderr,
        )
        print(
            f"    [{stype_str}] compressed ({node['compressed_tokens']}t): "
            f"{compressed_text[:80]}...",
            file=sys.stderr,
        )
        print(
            f"    [{stype_str}] keywords ({node['keyword_tokens']}t): "
            f"{keyword_text[:80]}...",
            file=sys.stderr,
        )
        if len(shown_types) >= 6:
            break

    # ============================================================
    # Save results
    # ============================================================

    output: dict[str, Any] = {
        "experiment": "exp42_ib_compression",
        "date": "2026-04-10",
        "input": {
            "decisions": len(decisions),
            "sentence_nodes": len(all_nodes),
        },
        "coverage": {
            "full": cov_full,
            "type_compressed": cov_compressed,
            "keyword_only": cov_keywords,
        },
        "tokens": {
            "full_total": total_full,
            "compressed_total": total_compressed,
            "keyword_total": total_keywords,
            "savings_tokens": total_full - total_compressed,
            "savings_pct": round((1 - total_compressed / total_full) * 100, 1),
            "avg_compressed_per_node": round(avg_compressed_per_node, 1),
            "nodes_in_2k_budget": nodes_in_budget,
            "per_type": {
                stype: {
                    "count": type_counts[stype],
                    "full_tokens": type_tokens_full[stype],
                    "compressed_tokens": type_tokens_compressed[stype],
                    "keyword_tokens": type_tokens_keywords[stype],
                    "actual_ratio": round(
                        type_tokens_compressed[stype] / type_tokens_full[stype], 3
                    )
                    if type_tokens_full[stype] > 0
                    else 0.0,
                }
                for stype in sorted(type_counts.keys())
            },
        },
        "within_type_variance": type_variance,
        "hrr_dimension_mapping": hrr_dims,
        "retrieval_losses": retrieval_loss_nodes,
        "compression_ratios_used": COMPRESSION_RATIOS,
    }

    out_path: Path = Path("experiments/exp42_ib_results.json")
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults saved to {out_path}", file=sys.stderr)

    fts_full.close()
    fts_compressed.close()
    fts_keywords.close()


if __name__ == "__main__":
    main()
