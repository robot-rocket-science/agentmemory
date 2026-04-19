from __future__ import annotations

"""
Experiment 54: Mutual Information Scoring for Retrieval Ranking

Tests whether PMI/NMI-based re-ranking of FTS5 results improves ranking
quality over BM25 alone on the 6-topic ground truth.

Method:
  1. Build term statistics from 1,195 sentence-level nodes
  2. For each query, retrieve FTS5 top-30 (BM25-ranked)
  3. Re-rank those 30 by pointwise mutual information
  4. Compare BM25 vs MI on MRR, P@5, P@10, P@15, NDCG@15, Recall@15
  5. Wilcoxon signed-rank test on per-query MRR

Zero-LLM. Uses only FTS5 + standard library + numpy + scipy.
"""

import json
import math
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats as scipy_stats  # type: ignore[import-untyped]

ALPHA_SEEK_DB = Path(
    "/home/user/projects/.gsd/workflows/spikes/"
    "260406-1-associative-memory-for-gsd-please-explor/"
    "sandbox/project-a.db"
)

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
# Sentence decomposition (from Exp 42)
# ============================================================

SentenceNode = dict[str, Any]


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
# Simple Porter-like stemmer (matches FTS5 porter tokenizer)
# ============================================================


def stem(word: str) -> str:
    """Minimal suffix stripping to approximate FTS5 porter stemmer."""
    w: str = word.lower()
    if len(w) <= 3:
        return w
    for suffix in [
        "ation",
        "ment",
        "ness",
        "ing",
        "tion",
        "sion",
        "ies",
        "ied",
        "ous",
        "ive",
        "ful",
        "able",
        "ly",
        "ed",
        "er",
        "es",
        "s",
    ]:
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            return w[: -len(suffix)]
    return w


def tokenize(text: str) -> list[str]:
    """Tokenize and stem, removing stopwords."""
    words: list[str] = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return [stem(w) for w in words if w not in STOPWORDS and len(w) >= 2]


# ============================================================
# Term statistics and MI computation
# ============================================================


class CorpusStats:
    """Precomputed term statistics for MI scoring."""

    def __init__(self, nodes: list[SentenceNode]) -> None:
        self.n_docs: int = len(nodes)
        # Document frequency: how many docs contain each term
        self.df: Counter[str] = Counter()
        # Per-document term frequencies
        self.doc_terms: list[Counter[str]] = []
        # Map node index -> parent decision
        self.doc_decisions: list[str] = []
        # Map node index -> node id
        self.doc_ids: list[str] = []

        for node in nodes:
            terms: list[str] = tokenize(str(node["content"]))
            tf: Counter[str] = Counter(terms)
            self.doc_terms.append(tf)
            self.doc_decisions.append(str(node["parent_decision"]))
            self.doc_ids.append(str(node["id"]))
            for term in set(terms):
                self.df[term] += 1

        # Corpus term probability: p(t) = df(t) / N
        # Laplace smoothing: add 1 to all counts, V to denominator
        self.vocab_size: int = len(self.df)
        self.total_smoothed: float = float(self.n_docs + self.vocab_size)

    def p_term(self, term: str) -> float:
        """Corpus-level probability of a term (Laplace smoothed)."""
        return (self.df.get(term, 0) + 1.0) / self.total_smoothed

    def p_term_given_doc(self, term: str, doc_idx: int) -> float:
        """P(term | document) based on term frequency, Laplace smoothed."""
        tf: Counter[str] = self.doc_terms[doc_idx]
        total_terms: int = sum(tf.values())
        if total_terms == 0:
            return 1.0 / (self.vocab_size + 1)
        return (tf.get(term, 0) + 1.0) / (total_terms + self.vocab_size)

    def pmi_score(self, query_terms: list[str], doc_idx: int) -> float:
        """Pointwise mutual information between query and document.

        PMI(q, d) = sum over shared terms t of:
            log2( p(t|d) / p(t) )

        This measures how much more likely each query term is in this
        document compared to the corpus baseline.
        """
        score: float = 0.0
        for term in query_terms:
            p_t: float = self.p_term(term)
            p_t_d: float = self.p_term_given_doc(term, doc_idx)
            if p_t > 0 and p_t_d > 0:
                score += math.log2(p_t_d / p_t)
        return score

    def nmi_score(self, query_terms: list[str], doc_idx: int) -> float:
        """Normalized mutual information score in [0, 1].

        Normalizes PMI by the joint entropy to make scores comparable
        across queries of different lengths.
        """
        pmi: float = self.pmi_score(query_terms, doc_idx)
        # Joint entropy approximation: H(q) + H(d)
        # H(q) = -sum p(t|q) log p(t|q)
        q_tf: Counter[str] = Counter(query_terms)
        q_total: int = len(query_terms)
        h_q: float = 0.0
        for _term, count in q_tf.items():
            p: float = count / q_total
            if p > 0:
                h_q -= p * math.log2(p)

        # H(d) = -sum p(t|d) log p(t|d)
        d_tf: Counter[str] = self.doc_terms[doc_idx]
        d_total: int = sum(d_tf.values())
        h_d: float = 0.0
        if d_total > 0:
            for count in d_tf.values():
                p_val: float = count / d_total
                if p_val > 0:
                    h_d -= p_val * math.log2(p_val)

        joint_h: float = h_q + h_d
        if joint_h <= 0:
            return 0.0
        # Clamp to [0, 1]
        return max(0.0, min(1.0, pmi / joint_h))


# ============================================================
# FTS5 search with score access
# ============================================================


def build_fts_index(nodes: list[SentenceNode]) -> sqlite3.Connection:
    """Build an in-memory FTS5 index from sentence nodes."""
    db: sqlite3.Connection = sqlite3.connect(":memory:")
    db.execute(
        "CREATE VIRTUAL TABLE fts USING fts5("
        "node_id, parent_decision, content, tokenize='porter')"
    )
    for node in nodes:
        db.execute(
            "INSERT INTO fts VALUES (?, ?, ?)",
            (str(node["id"]), str(node["parent_decision"]), str(node["content"])),
        )
    return db


def fts_search_ranked(
    db: sqlite3.Connection,
    query: str,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Search FTS5 and return ranked results with BM25 scores.

    Returns list of {node_id, parent_decision, bm25_score, rank}.
    Results are at the sentence level (not deduplicated by decision).
    """
    terms: list[str] = query.split()
    fts_query: str = " OR ".join(terms)
    try:
        rows: list[tuple[Any, ...]] = db.execute(
            "SELECT node_id, parent_decision, rank "
            "FROM fts WHERE fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (fts_query, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    results: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        results.append(
            {
                "node_id": str(row[0]),
                "parent_decision": str(row[1]),
                "bm25_score": float(row[2]),  # FTS5 rank (lower = better)
                "bm25_rank": i,
            }
        )
    return results


# ============================================================
# Ranking quality metrics
# ============================================================


def reciprocal_rank(
    ranked_decisions: list[str],
    relevant: set[str],
) -> float:
    """Reciprocal rank of first relevant result."""
    for i, d in enumerate(ranked_decisions):
        if d in relevant:
            return 1.0 / (i + 1)
    return 0.0


def precision_at_k(
    ranked_decisions: list[str],
    relevant: set[str],
    k: int,
) -> float:
    """Precision at rank k."""
    if k == 0:
        return 0.0
    top_k: list[str] = ranked_decisions[:k]
    hits: int = sum(1 for d in top_k if d in relevant)
    return hits / k


def recall_at_k(
    ranked_decisions: list[str],
    relevant: set[str],
    k: int,
) -> float:
    """Recall at rank k."""
    if not relevant:
        return 1.0
    top_k: list[str] = ranked_decisions[:k]
    hits: int = sum(1 for d in top_k if d in relevant)
    return hits / len(relevant)


def ndcg_at_k(
    ranked_decisions: list[str],
    relevant: set[str],
    k: int,
) -> float:
    """Normalized discounted cumulative gain at k.

    Binary relevance: 1 if in relevant set, 0 otherwise.
    """
    if not relevant:
        return 1.0

    # DCG
    dcg: float = 0.0
    for i, d in enumerate(ranked_decisions[:k]):
        if d in relevant:
            dcg += 1.0 / math.log2(i + 2)  # +2 because rank is 1-indexed

    # Ideal DCG: all relevant docs at top
    ideal_count: int = min(len(relevant), k)
    idcg: float = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))

    if idcg <= 0:
        return 0.0
    return dcg / idcg


def deduplicate_by_decision(
    results: list[dict[str, Any]],
) -> list[str]:
    """Deduplicate ranked results by parent decision, keeping best rank."""
    seen: set[str] = set()
    deduped: list[str] = []
    for r in results:
        d: str = r["parent_decision"]
        if d not in seen:
            seen.add(d)
            deduped.append(d)
    return deduped


# ============================================================
# Main experiment
# ============================================================


def main() -> None:
    # Load decisions from project-a DB
    db: sqlite3.Connection = sqlite3.connect(str(ALPHA_SEEK_DB))
    decisions: list[tuple[str, ...]] = db.execute(
        "SELECT id, decision, choice, rationale FROM decisions ORDER BY seq"
    ).fetchall()
    db.close()

    print(f"Loaded {len(decisions)} decisions", file=sys.stderr)

    # Decompose into sentence nodes (same as Exp 42)
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

    # Build corpus statistics for MI scoring
    print("Building corpus statistics...", file=sys.stderr)
    corpus: CorpusStats = CorpusStats(all_nodes)
    print(f"  Vocabulary: {corpus.vocab_size} stemmed terms", file=sys.stderr)

    # Build FTS5 index
    print("Building FTS5 index...", file=sys.stderr)
    fts_db: sqlite3.Connection = build_fts_index(all_nodes)

    # Build node_id -> index mapping for MI lookup
    id_to_idx: dict[str, int] = {str(n["id"]): i for i, n in enumerate(all_nodes)}

    # Run comparison on all 18 queries
    print("\nRunning retrieval comparison...", file=sys.stderr)
    per_query_results: list[dict[str, Any]] = []
    bm25_mrrs: list[float] = []
    mi_mrrs: list[float] = []
    nmi_mrrs: list[float] = []

    for topic, spec in CRITICAL_BELIEFS.items():
        queries: list[str] = list(spec["queries"])  # type: ignore[arg-type]
        needed: list[str] = list(spec["needed"])  # type: ignore[arg-type]
        relevant: set[str] = set(needed)

        for query in queries:
            # Step 1: FTS5 retrieval (BM25 ranked, sentence level)
            fts_results: list[dict[str, Any]] = fts_search_ranked(
                fts_db, query, limit=30
            )

            if not fts_results:
                per_query_results.append(
                    {
                        "topic": topic,
                        "query": query,
                        "fts_hits": 0,
                        "bm25": {
                            "mrr": 0.0,
                            "p5": 0.0,
                            "p10": 0.0,
                            "p15": 0.0,
                            "r15": 0.0,
                            "ndcg15": 0.0,
                        },
                        "pmi": {
                            "mrr": 0.0,
                            "p5": 0.0,
                            "p10": 0.0,
                            "p15": 0.0,
                            "r15": 0.0,
                            "ndcg15": 0.0,
                        },
                        "nmi": {
                            "mrr": 0.0,
                            "p5": 0.0,
                            "p10": 0.0,
                            "p15": 0.0,
                            "r15": 0.0,
                            "ndcg15": 0.0,
                        },
                    }
                )
                bm25_mrrs.append(0.0)
                mi_mrrs.append(0.0)
                nmi_mrrs.append(0.0)
                continue

            # Tokenize query for MI scoring
            q_terms: list[str] = tokenize(query)

            # Step 2: Score each FTS5 result by PMI and NMI
            for r in fts_results:
                node_id: str = r["node_id"]
                idx: int = id_to_idx.get(node_id, -1)
                if idx >= 0:
                    r["pmi_score"] = corpus.pmi_score(q_terms, idx)
                    r["nmi_score"] = corpus.nmi_score(q_terms, idx)
                else:
                    r["pmi_score"] = -999.0
                    r["nmi_score"] = 0.0

            # Step 3: Create three rankings
            # BM25: already sorted by FTS5 rank (lower = better)
            bm25_ranked: list[dict[str, Any]] = sorted(
                fts_results, key=lambda x: x["bm25_score"]
            )
            # PMI: higher = better
            pmi_ranked: list[dict[str, Any]] = sorted(
                fts_results, key=lambda x: -x["pmi_score"]
            )
            # NMI: higher = better
            nmi_ranked: list[dict[str, Any]] = sorted(
                fts_results, key=lambda x: -x["nmi_score"]
            )

            # Deduplicate by decision for metric computation
            bm25_decisions: list[str] = deduplicate_by_decision(bm25_ranked)
            pmi_decisions: list[str] = deduplicate_by_decision(pmi_ranked)
            nmi_decisions: list[str] = deduplicate_by_decision(nmi_ranked)

            # Step 4: Compute metrics
            bm25_metrics: dict[str, float] = {
                "mrr": reciprocal_rank(bm25_decisions, relevant),
                "p5": precision_at_k(bm25_decisions, relevant, 5),
                "p10": precision_at_k(bm25_decisions, relevant, 10),
                "p15": precision_at_k(bm25_decisions, relevant, 15),
                "r15": recall_at_k(bm25_decisions, relevant, 15),
                "ndcg15": ndcg_at_k(bm25_decisions, relevant, 15),
            }
            pmi_metrics: dict[str, float] = {
                "mrr": reciprocal_rank(pmi_decisions, relevant),
                "p5": precision_at_k(pmi_decisions, relevant, 5),
                "p10": precision_at_k(pmi_decisions, relevant, 10),
                "p15": precision_at_k(pmi_decisions, relevant, 15),
                "r15": recall_at_k(pmi_decisions, relevant, 15),
                "ndcg15": ndcg_at_k(pmi_decisions, relevant, 15),
            }
            nmi_metrics: dict[str, float] = {
                "mrr": reciprocal_rank(nmi_decisions, relevant),
                "p5": precision_at_k(nmi_decisions, relevant, 5),
                "p10": precision_at_k(nmi_decisions, relevant, 10),
                "p15": precision_at_k(nmi_decisions, relevant, 15),
                "r15": recall_at_k(nmi_decisions, relevant, 15),
                "ndcg15": ndcg_at_k(nmi_decisions, relevant, 15),
            }

            bm25_mrrs.append(bm25_metrics["mrr"])
            mi_mrrs.append(pmi_metrics["mrr"])
            nmi_mrrs.append(nmi_metrics["mrr"])

            per_query_results.append(
                {
                    "topic": topic,
                    "query": query,
                    "fts_hits": len(fts_results),
                    "unique_decisions": len(bm25_decisions),
                    "bm25": bm25_metrics,
                    "pmi": pmi_metrics,
                    "nmi": nmi_metrics,
                    "bm25_top5": bm25_decisions[:5],
                    "pmi_top5": pmi_decisions[:5],
                    "nmi_top5": nmi_decisions[:5],
                }
            )

    # ============================================================
    # Statistical tests
    # ============================================================

    print("\n" + "=" * 70, file=sys.stderr)
    print("EXPERIMENT 54: MI SCORING RESULTS", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    # Aggregate metrics
    n_queries: int = len(per_query_results)
    bm25_arr: np.ndarray = np.array(bm25_mrrs)
    pmi_arr: np.ndarray = np.array(mi_mrrs)
    nmi_arr: np.ndarray = np.array(nmi_mrrs)

    print(f"\nN queries: {n_queries}", file=sys.stderr)
    print("\nMean MRR:", file=sys.stderr)
    print(
        f"  BM25: {np.mean(bm25_arr):.3f} (std {np.std(bm25_arr):.3f})", file=sys.stderr
    )
    print(
        f"  PMI:  {np.mean(pmi_arr):.3f} (std {np.std(pmi_arr):.3f})", file=sys.stderr
    )
    print(
        f"  NMI:  {np.mean(nmi_arr):.3f} (std {np.std(nmi_arr):.3f})", file=sys.stderr
    )

    # MRR improvement
    bm25_mean: float = float(np.mean(bm25_arr))
    pmi_mean: float = float(np.mean(pmi_arr))
    nmi_mean: float = float(np.mean(nmi_arr))
    pmi_improvement: float = (
        (pmi_mean - bm25_mean) / bm25_mean * 100 if bm25_mean > 0 else 0.0
    )
    nmi_improvement: float = (
        (nmi_mean - bm25_mean) / bm25_mean * 100 if bm25_mean > 0 else 0.0
    )

    print("\nMRR improvement over BM25:", file=sys.stderr)
    print(f"  PMI: {pmi_improvement:+.1f}%", file=sys.stderr)
    print(f"  NMI: {nmi_improvement:+.1f}%", file=sys.stderr)

    # Wilcoxon signed-rank test (BM25 vs PMI, BM25 vs NMI)
    # Only on pairs where at least one value is non-zero
    pmi_stat_result: dict[str, Any] = {"test": "wilcoxon", "note": ""}
    nmi_stat_result: dict[str, Any] = {"test": "wilcoxon", "note": ""}

    diffs_pmi: np.ndarray = pmi_arr - bm25_arr
    diffs_nmi: np.ndarray = nmi_arr - bm25_arr

    nonzero_pmi: np.ndarray = diffs_pmi[diffs_pmi != 0]
    nonzero_nmi: np.ndarray = diffs_nmi[diffs_nmi != 0]

    if len(nonzero_pmi) >= 5:
        pmi_wres: Any = scipy_stats.wilcoxon(nonzero_pmi)  # pyright: ignore[reportUnknownMemberType]
        w_pmi: float = float(pmi_wres.statistic)
        p_pmi: float = float(pmi_wres.pvalue)
        r_pmi: float = w_pmi / math.sqrt(len(nonzero_pmi))
        pmi_stat_result.update(
            {
                "W": w_pmi,
                "p": p_pmi,
                "r_effect": round(r_pmi, 3),
                "n_nonzero_pairs": int(len(nonzero_pmi)),
            }
        )
        print(
            f"\nWilcoxon BM25 vs PMI: W={w_pmi:.0f}, p={p_pmi:.4f}, "
            f"r={r_pmi:.3f}, n={len(nonzero_pmi)}",
            file=sys.stderr,
        )
    else:
        pmi_stat_result["note"] = f"Too few nonzero differences ({len(nonzero_pmi)})"
        print(
            f"\nWilcoxon BM25 vs PMI: insufficient data "
            f"({len(nonzero_pmi)} nonzero diffs)",
            file=sys.stderr,
        )

    if len(nonzero_nmi) >= 5:
        nmi_wres: Any = scipy_stats.wilcoxon(nonzero_nmi)  # pyright: ignore[reportUnknownMemberType]
        w_nmi: float = float(nmi_wres.statistic)
        p_nmi: float = float(nmi_wres.pvalue)
        r_nmi: float = w_nmi / math.sqrt(len(nonzero_nmi))
        nmi_stat_result.update(
            {
                "W": w_nmi,
                "p": p_nmi,
                "r_effect": round(r_nmi, 3),
                "n_nonzero_pairs": int(len(nonzero_nmi)),
            }
        )
        print(
            f"Wilcoxon BM25 vs NMI: W={w_nmi:.0f}, p={p_nmi:.4f}, "
            f"r={r_nmi:.3f}, n={len(nonzero_nmi)}",
            file=sys.stderr,
        )
    else:
        nmi_stat_result["note"] = f"Too few nonzero differences ({len(nonzero_nmi)})"
        print(
            f"Wilcoxon BM25 vs NMI: insufficient data "
            f"({len(nonzero_nmi)} nonzero diffs)",
            file=sys.stderr,
        )

    # Per-query detail table
    print(
        f"\n{'Query':<40s} {'BM25':>6s} {'PMI':>6s} {'NMI':>6s} "
        f"{'B-P5':>5s} {'P-P5':>5s} {'N-P5':>5s}",
        file=sys.stderr,
    )
    print("-" * 80, file=sys.stderr)
    for r in per_query_results:
        q_short: str = r["query"][:38]
        print(
            f"  {q_short:<38s} "
            f"{r['bm25']['mrr']:>6.3f} {r['pmi']['mrr']:>6.3f} "
            f"{r['nmi']['mrr']:>6.3f} "
            f"{r['bm25']['p5']:>5.2f} {r['pmi']['p5']:>5.2f} "
            f"{r['nmi']['p5']:>5.2f}",
            file=sys.stderr,
        )

    # Aggregate P@5, NDCG@15, R@15
    metrics_names: list[str] = ["p5", "p10", "p15", "r15", "ndcg15"]
    print(f"\n{'Metric':<12s} {'BM25':>8s} {'PMI':>8s} {'NMI':>8s}", file=sys.stderr)
    print("-" * 40, file=sys.stderr)
    aggregate: dict[str, dict[str, float]] = {"bm25": {}, "pmi": {}, "nmi": {}}
    for m in metrics_names:
        bm25_vals: list[float] = [r["bm25"][m] for r in per_query_results]
        pmi_vals: list[float] = [r["pmi"][m] for r in per_query_results]
        nmi_vals: list[float] = [r["nmi"][m] for r in per_query_results]
        bm: float = float(np.mean(bm25_vals))
        pm: float = float(np.mean(pmi_vals))
        nm: float = float(np.mean(nmi_vals))
        aggregate["bm25"][m] = round(bm, 4)
        aggregate["pmi"][m] = round(pm, 4)
        aggregate["nmi"][m] = round(nm, 4)
        print(f"  {m:<10s} {bm:>8.3f} {pm:>8.3f} {nm:>8.3f}", file=sys.stderr)

    # Decision against criteria
    print("\n--- Decision ---", file=sys.stderr)
    best_method: str = "pmi" if pmi_mean >= nmi_mean else "nmi"
    best_improvement: float = max(pmi_improvement, nmi_improvement)
    if best_improvement >= 10.0:
        print(
            f"  ADOPT: {best_method.upper()} scoring as re-ranker "
            f"({best_improvement:+.1f}% MRR improvement)",
            file=sys.stderr,
        )
    elif best_improvement >= 5.0:
        print(
            f"  MARGINAL: {best_method.upper()} shows {best_improvement:+.1f}% "
            f"improvement. Test on other datasets for confirmation.",
            file=sys.stderr,
        )
    elif best_improvement > -5.0:
        print(
            f"  REJECT: MI scoring adds < 5% improvement "
            f"({best_improvement:+.1f}%). BM25 sufficient.",
            file=sys.stderr,
        )
    else:
        print(
            f"  REJECT: MI scoring DECREASES ranking quality "
            f"({best_improvement:+.1f}%).",
            file=sys.stderr,
        )

    # ============================================================
    # Save results
    # ============================================================

    output: dict[str, Any] = {
        "experiment": "exp54_mutual_information_scoring",
        "date": "2026-04-10",
        "input": {
            "decisions": len(decisions),
            "sentence_nodes": len(all_nodes),
            "vocabulary_size": corpus.vocab_size,
            "queries": n_queries,
        },
        "aggregate_metrics": aggregate,
        "mrr_summary": {
            "bm25_mean": round(bm25_mean, 4),
            "pmi_mean": round(pmi_mean, 4),
            "nmi_mean": round(nmi_mean, 4),
            "pmi_improvement_pct": round(pmi_improvement, 1),
            "nmi_improvement_pct": round(nmi_improvement, 1),
        },
        "statistical_tests": {
            "bm25_vs_pmi": pmi_stat_result,
            "bm25_vs_nmi": nmi_stat_result,
        },
        "per_query": per_query_results,
    }

    out_path: Path = Path("experiments/exp54_results.json")
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults saved to {out_path}", file=sys.stderr)

    fts_db.close()


if __name__ == "__main__":
    main()
