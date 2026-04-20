"""Exp 95: Entity layer scoring calibration.

Measures the compound boost problem: correction type weight * source weight
* lock boost = 9.0x, drowning relevant unlocked content.

Tests two fixes:
  H1: Cap compound boost at 3.0x total. MRR of correct answers should improve >20%.
  H2: Query-relevance-gated boost. Noise reduction >50%.

Methodology: Run test queries against the live DB with original and modified
scoring, compare rank of known-correct beliefs.

Usage:
    uv run python experiments/exp95_entity_scoring_calibration.py
"""

from __future__ import annotations

import math
import random
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ScoredResult:
    belief_id: str
    content: str
    belief_type: str
    source_type: str
    locked: bool
    score: float
    via: str
    is_relevant: bool  # manually labeled


# Test queries with known-relevant content patterns
TEST_CASES: list[tuple[str, list[str]]] = [
    (
        "HRR hook path performance optimization",
        ["hrr", "hook", "performance", "cleanup memory", "cosine", "precompute"],
    ),
    (
        "what priors should agent-inferred factual beliefs use",
        ["prior", "alpha", "beta", "0.6", "0.375", "type_priors", "factual"],
    ),
    (
        "how does the feedback loop update confidence",
        ["feedback", "update_confidence", "alpha", "beta", "used", "ignored", "harmful"],
    ),
    (
        "retrieval scoring pipeline components",
        ["score_belief", "thompson", "decay", "recency", "ucb", "type_weight"],
    ),
    (
        "how are beliefs classified during ingestion",
        ["classification", "belief_type", "source_type", "offline", "extract"],
    ),
]


def score_belief_original(
    row: sqlite3.Row,
    query_words: list[str],
    now: datetime,
) -> float:
    """Original scoring: multiplicative compound boost."""
    type_weights: dict[str, float] = {
        "requirement": 2.5, "correction": 2.0, "preference": 1.8,
        "factual": 1.0, "procedural": 1.2, "causal": 1.3, "relational": 1.0,
    }
    source_weights: dict[str, float] = {
        "user_corrected": 1.5, "user_stated": 1.3, "document_recent": 1.0,
        "document_old": 0.8, "agent_inferred": 1.0,
    }
    half_lives: dict[str, float] = {
        "factual": 336.0, "correction": 1344.0, "requirement": 4032.0,
        "preference": 2016.0,
    }

    alpha: float = float(row["alpha"])
    beta: float = float(row["beta_param"])
    locked: bool = bool(row["locked"])
    bt: str = str(row["belief_type"])
    st: str = str(row["source_type"])
    content: str = str(row["content"])

    sample: float = random.betavariate(max(0.01, alpha), max(0.01, beta))
    tw: float = type_weights.get(bt, 1.0)
    sw: float = source_weights.get(st, 1.0)

    # Decay
    decay: float = 1.0
    if not locked:
        try:
            created: datetime = datetime.fromisoformat(str(row["created_at"]))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_h: float = max(0.0, (now - created).total_seconds() / 3600.0)
            hl: float | None = half_lives.get(bt)
            if hl:
                decay = 0.5 ** (age_h / hl)
        except Exception:
            pass

    # Lock boost
    boost: float = 1.0
    if locked:
        content_lower: str = content.lower()
        if any(w.lower() in content_lower for w in query_words):
            boost = 3.0

    # Recency
    recency: float = 1.0
    try:
        created = datetime.fromisoformat(str(row["created_at"]))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_h = max(0.0, (now - created).total_seconds() / 3600.0)
        recency = 1.0 + 0.5 ** (age_h / 24.0)
    except Exception:
        pass

    if locked:
        return boost * sample
    return tw * sw * sample * decay * recency


def score_belief_capped(
    row: sqlite3.Row,
    query_words: list[str],
    now: datetime,
    cap: float = 3.0,
) -> float:
    """H1: Same as original but cap the total compound multiplier."""
    type_weights: dict[str, float] = {
        "requirement": 2.5, "correction": 2.0, "preference": 1.8,
        "factual": 1.0, "procedural": 1.2, "causal": 1.3, "relational": 1.0,
    }
    source_weights: dict[str, float] = {
        "user_corrected": 1.5, "user_stated": 1.3, "document_recent": 1.0,
        "document_old": 0.8, "agent_inferred": 1.0,
    }
    half_lives: dict[str, float] = {
        "factual": 336.0, "correction": 1344.0, "requirement": 4032.0,
        "preference": 2016.0,
    }

    alpha = float(row["alpha"])
    beta = float(row["beta_param"])
    locked = bool(row["locked"])
    bt = str(row["belief_type"])
    st = str(row["source_type"])
    content = str(row["content"])

    sample = random.betavariate(max(0.01, alpha), max(0.01, beta))
    tw = type_weights.get(bt, 1.0)
    sw = source_weights.get(st, 1.0)

    decay: float = 1.0
    if not locked:
        try:
            created = datetime.fromisoformat(str(row["created_at"]))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_h = max(0.0, (now - created).total_seconds() / 3600.0)
            hl = half_lives.get(bt)
            if hl:
                decay = 0.5 ** (age_h / hl)
        except Exception:
            pass

    boost: float = 1.0
    if locked:
        content_lower = content.lower()
        if any(w.lower() in content_lower for w in query_words):
            boost = 3.0

    recency: float = 1.0
    try:
        created = datetime.fromisoformat(str(row["created_at"]))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_h = max(0.0, (now - created).total_seconds() / 3600.0)
        recency = 1.0 + 0.5 ** (age_h / 24.0)
    except Exception:
        pass

    if locked:
        return min(boost * sample, cap * sample)

    # Cap the type*source compound
    compound: float = min(tw * sw, cap)
    return compound * sample * decay * recency


def score_belief_relevance_gated(
    row: sqlite3.Row,
    query_words: list[str],
    now: datetime,
) -> float:
    """H2: Only boost corrections that are topically relevant to the query."""
    type_weights: dict[str, float] = {
        "requirement": 2.5, "correction": 2.0, "preference": 1.8,
        "factual": 1.0, "procedural": 1.2, "causal": 1.3, "relational": 1.0,
    }
    source_weights: dict[str, float] = {
        "user_corrected": 1.5, "user_stated": 1.3, "document_recent": 1.0,
        "document_old": 0.8, "agent_inferred": 1.0,
    }
    half_lives: dict[str, float] = {
        "factual": 336.0, "correction": 1344.0, "requirement": 4032.0,
        "preference": 2016.0,
    }

    alpha = float(row["alpha"])
    beta = float(row["beta_param"])
    locked = bool(row["locked"])
    bt = str(row["belief_type"])
    st = str(row["source_type"])
    content = str(row["content"])

    sample = random.betavariate(max(0.01, alpha), max(0.01, beta))

    # Relevance gate: count query word overlap with content
    content_lower = content.lower()
    overlap: int = sum(1 for w in query_words if w.lower() in content_lower)
    overlap_ratio: float = overlap / max(1, len(query_words))

    # Only apply type/source boost if content is relevant
    if overlap_ratio >= 0.3:  # at least 30% keyword overlap
        tw = type_weights.get(bt, 1.0)
        sw = source_weights.get(st, 1.0)
    else:
        tw = 1.0  # no type boost for irrelevant content
        sw = 1.0  # no source boost

    decay: float = 1.0
    if not locked:
        try:
            created = datetime.fromisoformat(str(row["created_at"]))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_h = max(0.0, (now - created).total_seconds() / 3600.0)
            hl = half_lives.get(bt)
            if hl:
                decay = 0.5 ** (age_h / hl)
        except Exception:
            pass

    boost: float = 1.0
    if locked:
        if overlap_ratio >= 0.3:
            boost = 3.0
        else:
            boost = 1.0  # no lock boost for irrelevant locked beliefs

    recency: float = 1.0
    try:
        created = datetime.fromisoformat(str(row["created_at"]))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_h = max(0.0, (now - created).total_seconds() / 3600.0)
        recency = 1.0 + 0.5 ** (age_h / 24.0)
    except Exception:
        pass

    if locked:
        return boost * sample
    return tw * sw * sample * decay * recency


def is_relevant(content: str, relevance_keywords: list[str]) -> bool:
    """Check if content contains any relevance keyword."""
    lower: str = content.lower()
    return any(kw.lower() in lower for kw in relevance_keywords)


def run_query(
    conn: sqlite3.Connection,
    query: str,
    relevance_keywords: list[str],
    score_fn: object,
    label: str,
    seed: int = 42,
) -> tuple[float, int, int]:
    """Run a query, return (MRR of relevant beliefs, relevant_in_top5, total_relevant)."""
    random.seed(seed)
    now: datetime = datetime.now(timezone.utc)
    words: list[str] = [w for w in query.split() if len(w) > 2]

    # FTS5 search
    fts_query: str = " OR ".join(f'"{w}"' for w in words[:10])
    rows: list[sqlite3.Row] = conn.execute(
        """SELECT b.* FROM search_index si
           JOIN beliefs b ON b.id = si.id
           WHERE search_index MATCH ?
             AND si.type = 'belief'
             AND b.valid_to IS NULL
           ORDER BY bm25(search_index) LIMIT 50""",
        (fts_query,),
    ).fetchall()

    # Score and rank
    scored: list[tuple[float, bool, str, str]] = []
    for r in rows:
        s: float = score_fn(r, words, now)  # type: ignore[operator]
        rel: bool = is_relevant(str(r["content"]), relevance_keywords)
        scored.append((s, rel, str(r["id"]), str(r["content"])[:60]))

    scored.sort(key=lambda x: x[0], reverse=True)

    # MRR: reciprocal rank of first relevant result
    mrr: float = 0.0
    relevant_in_top5: int = 0
    total_relevant: int = 0
    for rank, (s, rel, bid, content) in enumerate(scored, 1):
        if rel:
            total_relevant += 1
            if mrr == 0.0:
                mrr = 1.0 / rank
            if rank <= 5:
                relevant_in_top5 += 1

    return mrr, relevant_in_top5, total_relevant


def main() -> None:
    db_path: str = str(
        Path.home() / ".agentmemory" / "projects" / "2e7ed55e017a" / "memory.db"
    )
    conn: sqlite3.Connection = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    print("=" * 78)
    print("Exp 95: Entity Layer Scoring Calibration")
    print("=" * 78)
    print()

    configs: list[tuple[str, object]] = [
        ("Original (uncapped)", score_belief_original),
        ("H1: Capped at 3.0x", lambda r, q, n: score_belief_capped(r, q, n, cap=3.0)),
        ("H1: Capped at 2.0x", lambda r, q, n: score_belief_capped(r, q, n, cap=2.0)),
        ("H2: Relevance-gated", score_belief_relevance_gated),
    ]

    # Run each config across all test cases
    print(f"{'Config':>25s}  {'Query':>45s}  {'MRR':>5s}  {'Rel@5':>5s}  {'Total':>5s}")
    print("-" * 95)

    config_mrrs: dict[str, list[float]] = defaultdict(list)

    for config_name, score_fn in configs:
        for query, keywords in TEST_CASES:
            mrr, rel5, total = run_query(conn, query, keywords, score_fn, config_name)
            config_mrrs[config_name].append(mrr)
            q_short: str = query[:42]
            print(f"{config_name:>25s}  {q_short:>45s}  {mrr:5.3f}  {rel5:>5d}  {total:>5d}")

    # Summary
    print()
    print("## SUMMARY")
    print(f"{'Config':>25s}  {'Avg MRR':>8s}  {'Improvement':>12s}")
    print("-" * 50)
    baseline_mrr: float = sum(config_mrrs["Original (uncapped)"]) / len(config_mrrs["Original (uncapped)"])
    for config_name in ["Original (uncapped)", "H1: Capped at 3.0x", "H1: Capped at 2.0x", "H2: Relevance-gated"]:
        avg: float = sum(config_mrrs[config_name]) / len(config_mrrs[config_name])
        improvement: float = (avg - baseline_mrr) / max(baseline_mrr, 0.001) * 100
        print(f"{config_name:>25s}  {avg:8.3f}  {improvement:>+11.1f}%")

    # H1 test
    print()
    h1_pass: bool = sum(config_mrrs["H1: Capped at 3.0x"]) / len(config_mrrs["H1: Capped at 3.0x"]) > baseline_mrr * 1.2
    print(f"H1 (cap 3.0x, MRR +20%): {'PASS' if h1_pass else 'FAIL'}")

    # H2 test
    h2_mrr: float = sum(config_mrrs["H2: Relevance-gated"]) / len(config_mrrs["H2: Relevance-gated"])
    h2_pass: bool = h2_mrr > baseline_mrr * 1.5
    print(f"H2 (relevance-gated, noise -50%): {'PASS' if h2_pass else 'FAIL'}")

    conn.close()


if __name__ == "__main__":
    main()
