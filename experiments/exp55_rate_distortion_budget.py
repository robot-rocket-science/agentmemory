from __future__ import annotations

"""
Experiment 55: Rate-Distortion Theory for Token Budget Allocation

Tests whether query-dependent rate-distortion allocation of token budget
across retrieved beliefs outperforms fixed-ratio type-aware compression.

Method:
  1. For each query, retrieve FTS5 top-30 candidates
  2. Apply 3 allocation strategies within token budget:
     a. Fixed-ratio (Exp 42 type-aware compression)
     b. RD-optimal (relevance-weighted reverse water-filling)
     c. Top-k full text (greedy, no compression)
  3. Compare NDCG@budget, precision@budget, token efficiency
  4. Sensitivity analysis across 5 budget levels
  5. Wilcoxon test on per-query NDCG

Zero-LLM. Uses numpy + scipy only.
"""

import json
import math
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats as scipy_stats
from scipy.optimize import minimize as scipy_minimize

ALPHA_SEEK_DB = Path(
    "/Users/thelorax/projects/.gsd/workflows/spikes/"
    "260406-1-associative-memory-for-gsd-please-explor/"
    "sandbox/alpha-seek.db"
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
            "archon overflow only",
            "cloud compute infrastructure",
        ],
        "needed": ["D078", "D120"],
    },
}

COMPRESSION_RATIOS: dict[str, float] = {
    "constraint": 1.0,
    "evidence": 0.6,
    "context": 0.3,
    "rationale": 0.4,
    "supersession": 0.0,  # pointer
    "implementation": 0.3,
}

SUPERSESSION_TARGET_TOKENS: int = 8
BUDGET_LEVELS: list[int] = [500, 1000, 1500, 2000, 3000]

STOPWORDS: set[str] = {
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
# Sentence decomposition (from Exp 42)
# ============================================================

SentenceNode = dict[str, Any]


def split_into_sentences(text: str) -> list[str]:
    parts: list[str] = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    sentences: list[str] = []
    for part in parts:
        subparts: list[str] = part.split(' | ')
        for sp in subparts:
            sp = sp.strip()
            if len(sp) > 10:
                sentences.append(sp)
    return sentences


def classify_sentence(sentence: str) -> str:
    s: str = sentence.lower()
    if any(w in s for w in ['because', 'rationale', 'reason', 'driven by', 'root cause']):
        return 'rationale'
    if any(w in s for w in ['supersede', 'replace', 'retire', 'override']):
        return 'supersession'
    if any(w in s for w in ['must', 'always', 'never', 'mandatory', 'require', 'rule']):
        return 'constraint'
    if any(w in s for w in ['data', 'showed', 'result', 'found', 'measured', '%', 'x ']):
        return 'evidence'
    if any(w in s for w in ['script', 'implement', 'code', '.py', 'function']):
        return 'implementation'
    return 'context'


def count_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def compress_truncate(text: str, target_tokens: int) -> str:
    if count_tokens(text) <= target_tokens:
        return text
    target_chars: int = target_tokens * 4
    if target_chars >= len(text):
        return text
    truncated: str = text[:target_chars]
    last_space: int = truncated.rfind(' ')
    if last_space > target_chars // 2:
        truncated = truncated[:last_space]
    return truncated.rstrip('.,;:- ')


# ============================================================
# Fidelity functions
# ============================================================

def fidelity_power(c: float, exponent: float) -> float:
    """Power-law fidelity: f(c) = c^exponent.

    exponent < 1 = front-loaded info (first words carry most value).
    exponent = 1 = linear (info uniformly distributed).
    exponent > 1 = back-loaded info (rare, but possible for context).
    """
    return max(0.0, min(1.0, c)) ** exponent


def fidelity_log(c: float) -> float:
    """Logarithmic fidelity: f(c) = log(1 + c) / log(2).

    Strongly concave -- diminishing returns from including more text.
    """
    return math.log(1.0 + max(0.0, min(1.0, c))) / math.log(2.0)


# Type-specific fidelity exponents (estimated from Exp 42)
FIDELITY_EXPONENTS: dict[str, float] = {
    "constraint": 0.3,       # very front-loaded
    "evidence": 0.5,         # moderate
    "context": 0.7,          # more linear
    "rationale": 0.5,        # moderate
    "supersession": 0.2,     # pointer: all or nothing
    "implementation": 0.7,   # more linear
}


# ============================================================
# FTS5 search
# ============================================================

def build_fts_index(nodes: list[SentenceNode]) -> sqlite3.Connection:
    db: sqlite3.Connection = sqlite3.connect(":memory:")
    db.execute(
        "CREATE VIRTUAL TABLE fts USING fts5("
        "node_id, parent_decision, stype, content, tokenize='porter')"
    )
    for node in nodes:
        db.execute(
            "INSERT INTO fts VALUES (?, ?, ?, ?)",
            (str(node["id"]), str(node["parent_decision"]),
             str(node["type"]), str(node["content"])),
        )
    return db


def fts_search_ranked(
    db: sqlite3.Connection,
    query: str,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Return sentence-level results with BM25 scores."""
    terms: list[str] = query.split()
    fts_query: str = " OR ".join(terms)
    try:
        rows: list[tuple[Any, ...]] = db.execute(
            "SELECT node_id, parent_decision, stype, rank "
            "FROM fts WHERE fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (fts_query, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    results: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        results.append({
            "node_id": str(row[0]),
            "parent_decision": str(row[1]),
            "stype": str(row[2]),
            "bm25_score": float(row[3]),
            "bm25_rank": i,
        })
    return results


# ============================================================
# Allocation strategies
# ============================================================

def strategy_fixed_ratio(
    candidates: list[dict[str, Any]],
    budget: int,
) -> list[dict[str, Any]]:
    """Fixed-ratio type-aware compression (Exp 42 baseline).

    Compress each belief by its type ratio, include as many as fit.
    """
    allocated: list[dict[str, Any]] = []
    tokens_used: int = 0

    for c in candidates:
        stype: str = c["stype"]
        full_tokens: int = c["tokens"]
        ratio: float = COMPRESSION_RATIOS.get(stype, 0.5)

        if stype == "supersession":
            compressed_tokens: int = SUPERSESSION_TARGET_TOKENS
        else:
            compressed_tokens = max(3, int(full_tokens * ratio))

        if tokens_used + compressed_tokens > budget:
            continue

        tokens_used += compressed_tokens
        allocated.append({
            **c,
            "allocated_tokens": compressed_tokens,
            "compression_ratio": compressed_tokens / full_tokens if full_tokens > 0 else 0.0,
            "fidelity": fidelity_power(
                compressed_tokens / full_tokens if full_tokens > 0 else 0.0,
                FIDELITY_EXPONENTS.get(stype, 0.5),
            ),
        })

    return allocated


def strategy_topk_full(
    candidates: list[dict[str, Any]],
    budget: int,
) -> list[dict[str, Any]]:
    """Top-k full text: include at full fidelity until budget exhausted."""
    allocated: list[dict[str, Any]] = []
    tokens_used: int = 0

    for c in candidates:
        full_tokens: int = c["tokens"]
        if tokens_used + full_tokens > budget:
            continue
        tokens_used += full_tokens
        allocated.append({
            **c,
            "allocated_tokens": full_tokens,
            "compression_ratio": 1.0,
            "fidelity": 1.0,
        })

    return allocated


def strategy_rd_optimal(
    candidates: list[dict[str, Any]],
    budget: int,
) -> list[dict[str, Any]]:
    """Rate-distortion optimal allocation via reverse water-filling.

    maximize sum_i r_i * f(c_i)
    subject to sum_i c_i * l_i <= B, 0 <= c_i <= 1

    Solved analytically for power-law fidelity f(c) = c^alpha:
    Optimal: c_i* = (lambda * l_i / (r_i * alpha))^(1/(alpha-1))
    where lambda is the Lagrange multiplier found by bisection.
    """
    n: int = len(candidates)
    if n == 0:
        return []

    relevances: np.ndarray = np.zeros(n, dtype=np.float64)
    lengths: np.ndarray = np.zeros(n, dtype=np.float64)
    alphas: np.ndarray = np.zeros(n, dtype=np.float64)

    for i, c in enumerate(candidates):
        # Relevance = -bm25_score (FTS5 rank is negative, lower = better)
        # Normalize to [0, 1] range
        relevances[i] = -c["bm25_score"]
        lengths[i] = float(c["tokens"])
        alphas[i] = FIDELITY_EXPONENTS.get(c["stype"], 0.5)

    # Shift relevances to positive
    r_min: float = float(np.min(relevances))
    if r_min <= 0:
        relevances = relevances - r_min + 0.01

    # Check if everything fits at full
    total_full: float = float(np.sum(lengths))
    if total_full <= budget:
        # Everything fits -- allocate fully
        allocated: list[dict[str, Any]] = []
        for i, c in enumerate(candidates):
            allocated.append({
                **c,
                "allocated_tokens": c["tokens"],
                "compression_ratio": 1.0,
                "fidelity": 1.0,
            })
        return allocated

    # Solve via scipy SLSQP
    def neg_objective(c_vec: np.ndarray) -> float:
        total: float = 0.0
        for i in range(n):
            ci: float = float(c_vec[i])
            fi: float = fidelity_power(ci, float(alphas[i]))
            total += float(relevances[i]) * fi
        return -total

    def budget_constraint(c_vec: np.ndarray) -> float:
        return float(budget) - float(np.sum(c_vec * lengths))

    # Initial guess: uniform compression
    uniform_c: float = min(1.0, budget / total_full)
    x0: np.ndarray = np.full(n, uniform_c, dtype=np.float64)

    bounds: list[tuple[float, float]] = [(0.05, 1.0)] * n
    constraints: list[dict[str, Any]] = [
        {"type": "ineq", "fun": budget_constraint},
    ]

    result = scipy_minimize(
        neg_objective,
        x0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 200, "ftol": 1e-8},
    )

    c_optimal: np.ndarray = result.x

    # Build allocated list
    allocated = []
    tokens_used: int = 0
    for i, c in enumerate(candidates):
        ci: float = float(np.clip(c_optimal[i], 0.05, 1.0))
        alloc_tokens: int = max(3, int(ci * lengths[i]))

        if tokens_used + alloc_tokens > budget:
            # Ran out of budget (rounding); skip remaining
            continue

        tokens_used += alloc_tokens
        allocated.append({
            **c,
            "allocated_tokens": alloc_tokens,
            "compression_ratio": round(ci, 3),
            "fidelity": fidelity_power(ci, float(alphas[i])),
        })

    return allocated


# ============================================================
# Ranking quality metrics (at token-budget level, not k-level)
# ============================================================

def ndcg_budget(
    allocated: list[dict[str, Any]],
    relevant: set[str],
) -> float:
    """NDCG of allocated beliefs.

    Rank position is determined by allocation order.
    Relevance is binary (in ground truth or not).
    """
    if not relevant or not allocated:
        return 0.0

    # DCG
    dcg: float = 0.0
    for i, a in enumerate(allocated):
        if a["parent_decision"] in relevant:
            dcg += 1.0 / math.log2(i + 2)

    # IDCG: all relevant at top
    n_rel: int = sum(1 for a in allocated if a["parent_decision"] in relevant)
    idcg: float = sum(1.0 / math.log2(i + 2) for i in range(max(n_rel, 1)))

    return dcg / idcg if idcg > 0 else 0.0


def precision_budget(
    allocated: list[dict[str, Any]],
    relevant: set[str],
) -> float:
    """Fraction of allocated beliefs that are ground-truth relevant."""
    if not allocated:
        return 0.0
    hits: int = sum(1 for a in allocated if a["parent_decision"] in relevant)
    return hits / len(allocated)


def token_efficiency(
    allocated: list[dict[str, Any]],
    relevant: set[str],
) -> float:
    """Fraction of token budget going to relevant beliefs."""
    total: int = sum(a["allocated_tokens"] for a in allocated)
    if total == 0:
        return 0.0
    relevant_tokens: int = sum(
        a["allocated_tokens"] for a in allocated
        if a["parent_decision"] in relevant
    )
    return relevant_tokens / total


def mean_fidelity(allocated: list[dict[str, Any]]) -> float:
    """Mean information fidelity across allocated beliefs."""
    if not allocated:
        return 0.0
    return float(np.mean([a["fidelity"] for a in allocated]))


def recall_budget(
    allocated: list[dict[str, Any]],
    relevant: set[str],
) -> float:
    """Fraction of relevant decisions included in allocation."""
    if not relevant:
        return 1.0
    found: set[str] = {a["parent_decision"] for a in allocated if a["parent_decision"] in relevant}
    return len(found) / len(relevant)


# ============================================================
# Main experiment
# ============================================================

def main() -> None:
    # Load and decompose
    db: sqlite3.Connection = sqlite3.connect(str(ALPHA_SEEK_DB))
    decisions: list[tuple[str, ...]] = db.execute(
        "SELECT id, decision, choice, rationale FROM decisions ORDER BY seq"
    ).fetchall()
    db.close()

    print(f"Loaded {len(decisions)} decisions", file=sys.stderr)

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

    # Build FTS5 index
    print("Building FTS5 index...", file=sys.stderr)
    fts_db: sqlite3.Connection = build_fts_index(all_nodes)

    # Node lookup by id
    node_by_id: dict[str, SentenceNode] = {str(n["id"]): n for n in all_nodes}

    # Run comparison across all budgets and queries
    print("\nRunning allocation comparison...", file=sys.stderr)

    all_results: dict[str, Any] = {
        "experiment": "exp55_rate_distortion_budget",
        "date": "2026-04-10",
        "input": {
            "decisions": len(decisions),
            "sentence_nodes": len(all_nodes),
        },
        "budget_levels": BUDGET_LEVELS,
        "fidelity_exponents": FIDELITY_EXPONENTS,
        "compression_ratios": COMPRESSION_RATIOS,
        "per_budget": {},
    }

    for budget in BUDGET_LEVELS:
        print(f"\n--- Budget: {budget} tokens ---", file=sys.stderr)

        budget_queries: list[dict[str, Any]] = []
        fixed_ndcgs: list[float] = []
        rd_ndcgs: list[float] = []
        topk_ndcgs: list[float] = []

        for topic, spec in CRITICAL_BELIEFS.items():
            queries: list[str] = list(spec["queries"])  # type: ignore[arg-type]
            needed: list[str] = list(spec["needed"])  # type: ignore[arg-type]
            relevant: set[str] = set(needed)

            for query in queries:
                # Get FTS5 candidates (sentence level)
                fts_results: list[dict[str, Any]] = fts_search_ranked(
                    fts_db, query, limit=30
                )

                if not fts_results:
                    empty_metrics: dict[str, float] = {
                        "ndcg": 0.0, "precision": 0.0,
                        "token_efficiency": 0.0, "recall": 0.0,
                        "mean_fidelity": 0.0, "beliefs_included": 0,
                        "tokens_used": 0,
                    }
                    budget_queries.append({
                        "topic": topic, "query": query,
                        "fixed_ratio": empty_metrics,
                        "rd_optimal": empty_metrics,
                        "topk_full": empty_metrics,
                    })
                    fixed_ndcgs.append(0.0)
                    rd_ndcgs.append(0.0)
                    topk_ndcgs.append(0.0)
                    continue

                # Enrich candidates with node data
                candidates: list[dict[str, Any]] = []
                for r in fts_results:
                    node: SentenceNode | None = node_by_id.get(r["node_id"])
                    if node is None:
                        continue
                    candidates.append({
                        **r,
                        "tokens": int(node["tokens"]),
                        "stype": str(node["type"]),
                    })

                # Apply three strategies
                fixed: list[dict[str, Any]] = strategy_fixed_ratio(candidates, budget)
                rd: list[dict[str, Any]] = strategy_rd_optimal(candidates, budget)
                topk: list[dict[str, Any]] = strategy_topk_full(candidates, budget)

                def compute_metrics(
                    allocated: list[dict[str, Any]],
                    rel: set[str],
                ) -> dict[str, Any]:
                    return {
                        "ndcg": round(ndcg_budget(allocated, rel), 4),
                        "precision": round(precision_budget(allocated, rel), 4),
                        "token_efficiency": round(token_efficiency(allocated, rel), 4),
                        "recall": round(recall_budget(allocated, rel), 4),
                        "mean_fidelity": round(mean_fidelity(allocated), 4),
                        "beliefs_included": len(allocated),
                        "tokens_used": sum(a["allocated_tokens"] for a in allocated),
                    }

                fixed_m: dict[str, Any] = compute_metrics(fixed, relevant)
                rd_m: dict[str, Any] = compute_metrics(rd, relevant)
                topk_m: dict[str, Any] = compute_metrics(topk, relevant)

                fixed_ndcgs.append(fixed_m["ndcg"])
                rd_ndcgs.append(rd_m["ndcg"])
                topk_ndcgs.append(topk_m["ndcg"])

                budget_queries.append({
                    "topic": topic,
                    "query": query,
                    "candidates": len(candidates),
                    "fixed_ratio": fixed_m,
                    "rd_optimal": rd_m,
                    "topk_full": topk_m,
                })

        # Aggregate for this budget level
        f_arr: np.ndarray = np.array(fixed_ndcgs)
        r_arr: np.ndarray = np.array(rd_ndcgs)
        t_arr: np.ndarray = np.array(topk_ndcgs)

        f_mean: float = float(np.mean(f_arr))
        r_mean: float = float(np.mean(r_arr))
        t_mean: float = float(np.mean(t_arr))

        improvement: float = (r_mean - f_mean) / f_mean * 100 if f_mean > 0 else 0.0

        # Wilcoxon: fixed vs RD
        stat_result: dict[str, Any] = {"test": "wilcoxon"}
        diffs: np.ndarray = r_arr - f_arr
        nonzero: np.ndarray = diffs[diffs != 0]
        if len(nonzero) >= 5:
            w, p = scipy_stats.wilcoxon(nonzero)
            stat_result.update({
                "W": float(w), "p": round(float(p), 4),
                "n_nonzero": int(len(nonzero)),
            })
        else:
            stat_result["note"] = f"Too few nonzero diffs ({len(nonzero)})"

        # Print summary
        metric_names: list[str] = ["ndcg", "precision", "token_efficiency",
                                    "recall", "mean_fidelity", "beliefs_included",
                                    "tokens_used"]
        print(f"\n  {'Metric':<20s} {'Fixed':>8s} {'RD':>8s} {'Top-k':>8s}",
              file=sys.stderr)
        print(f"  {'-'*20} {'-'*8} {'-'*8} {'-'*8}", file=sys.stderr)
        for m in metric_names:
            f_vals: list[float] = [q["fixed_ratio"][m] for q in budget_queries]
            r_vals: list[float] = [q["rd_optimal"][m] for q in budget_queries]
            t_vals: list[float] = [q["topk_full"][m] for q in budget_queries]
            print(f"  {m:<20s} {np.mean(f_vals):>8.3f} "
                  f"{np.mean(r_vals):>8.3f} {np.mean(t_vals):>8.3f}",
                  file=sys.stderr)

        print(f"\n  NDCG improvement (RD vs fixed): {improvement:+.1f}%",
              file=sys.stderr)
        if "p" in stat_result:
            print(f"  Wilcoxon: p={stat_result['p']:.4f}", file=sys.stderr)

        all_results["per_budget"][str(budget)] = {
            "aggregate": {
                "fixed_ndcg_mean": round(f_mean, 4),
                "rd_ndcg_mean": round(r_mean, 4),
                "topk_ndcg_mean": round(t_mean, 4),
                "rd_vs_fixed_improvement_pct": round(improvement, 1),
            },
            "statistical_test": stat_result,
            "per_query": budget_queries,
        }

    # ============================================================
    # Overall decision
    # ============================================================

    print(f"\n{'='*70}", file=sys.stderr)
    print("EXPERIMENT 55: RATE-DISTORTION RESULTS SUMMARY", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)

    print(f"\n  {'Budget':>6s} {'Fixed NDCG':>11s} {'RD NDCG':>9s} "
          f"{'Improvement':>12s}", file=sys.stderr)
    print(f"  {'-'*6} {'-'*11} {'-'*9} {'-'*12}", file=sys.stderr)

    for budget in BUDGET_LEVELS:
        bdata: dict[str, Any] = all_results["per_budget"][str(budget)]["aggregate"]
        print(f"  {budget:>6d} {bdata['fixed_ndcg_mean']:>11.3f} "
              f"{bdata['rd_ndcg_mean']:>9.3f} "
              f"{bdata['rd_vs_fixed_improvement_pct']:>+11.1f}%", file=sys.stderr)

    # H3 check: at generous budget, RD should degenerate to fixed
    generous: dict[str, Any] = all_results["per_budget"]["3000"]["aggregate"]
    tight: dict[str, Any] = all_results["per_budget"]["500"]["aggregate"]

    print(f"\n  H3 check (budget=3000 degenerates): "
          f"RD improvement = {generous['rd_vs_fixed_improvement_pct']:+.1f}%",
          file=sys.stderr)
    print(f"  Tight budget advantage (500): "
          f"{tight['rd_vs_fixed_improvement_pct']:+.1f}%", file=sys.stderr)

    # Decision
    at_2k: dict[str, Any] = all_results["per_budget"]["2000"]["aggregate"]
    imp_2k: float = at_2k["rd_vs_fixed_improvement_pct"]

    print(f"\n--- Decision (at REQ-003 budget = 2000) ---", file=sys.stderr)
    if imp_2k >= 10.0:
        print(f"  ADOPT: RD allocation ({imp_2k:+.1f}% NDCG improvement)",
              file=sys.stderr)
    elif imp_2k >= 5.0:
        print(f"  MARGINAL: {imp_2k:+.1f}% improvement. Adopt for tight "
              f"budgets only.", file=sys.stderr)
    elif imp_2k > -5.0:
        print(f"  REJECT: {imp_2k:+.1f}% improvement. Fixed-ratio heuristic "
              f"is near-optimal.", file=sys.stderr)
    else:
        print(f"  REJECT: RD DECREASES quality ({imp_2k:+.1f}%).",
              file=sys.stderr)

    # Save
    out_path: Path = Path("experiments/exp55_results.json")
    out_path.write_text(json.dumps(all_results, indent=2))
    print(f"\nResults saved to {out_path}", file=sys.stderr)

    fts_db.close()


if __name__ == "__main__":
    main()
