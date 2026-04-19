from __future__ import annotations

"""
Experiment 4 (retrieval-only): Token Budget vs Critical Belief Coverage

Instead of the full LLM + human evaluation protocol, this uses the Exp 6
failure data as ground truth: at each token budget, how many of the beliefs
that would have prevented historical failures appear in retrieved context?

This answers: "is our token budget large enough to include the critical stuff?"

Full Exp 4 (with LLM generation + human eval) can follow if needed.
"""

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import numpy as np


project-a_DB = Path(
    "/home/user/projects/.gsd/workflows/spikes/"
    "260406-1-associative-memory-for-gsd-please-explor/"
    "sandbox/project-a.db"
)

# Critical beliefs derived from Exp 6 Phase D failure analysis
# These are the beliefs that SHOULD have been in context to prevent the observed failures
CRITICAL_BELIEFS: dict[str, dict[str, Any]] = {
    "dispatch_gate": {
        "query": "dispatch gate deploy protocol GCP verification",
        "needed_decisions": ["D089", "D106", "D137"],
        "description": "Dispatch gate protocol -- 13 user corrections over 5 days",
    },
    "calls_puts": {
        "query": "calls puts equal citizens strategy direction",
        "needed_decisions": ["D073", "D096", "D100"],
        "description": "Calls and puts are equal citizens -- 4 corrections over 11 days",
    },
    "capital_5k": {
        "query": "starting capital bankroll amount USD",
        "needed_decisions": ["D099"],
        # NOTE: D209 also covers this topic but doesn't exist in the spike DB
        # (snapshot from Apr 6 predates D209). Only D099 is testable here.
        "description": "Capital is $5K -- 3 corrections over 10 days",
    },
    "agent_behavior": {
        "query": "agent behavior execute instructions elaboration",
        "needed_decisions": ["D157", "D188"],
        "description": "Execute precisely, no elaboration -- 3 corrections over 2 days",
    },
    "strict_typing": {
        "query": "typing pyright strict typed python",
        "needed_decisions": ["D071", "D113"],
        "description": "Use strict static typing -- 4 corrections over 4 days",
    },
    "gcp_primary": {
        "query": "GCP primary compute server-a overflow platform",
        "needed_decisions": ["D078", "D120"],
        "description": "GCP is primary, server-a overflow only -- 3 corrections over 7 days",
    },
}

TOKEN_BUDGETS = [100, 250, 500, 1000, 1500, 2000, 3000, 5000]


def load_nodes_and_fts() -> tuple[dict[str, dict[str, Any]], sqlite3.Connection]:
    db = sqlite3.connect(str(project-a_DB))
    db.row_factory = sqlite3.Row

    nodes: dict[str, dict[str, Any]] = {}
    for row in db.execute(
        "SELECT id, content, category, confidence FROM mem_nodes WHERE superseded_by IS NULL"
    ):
        # Estimate token count as chars / 4
        token_est = len(row["content"]) // 4
        nodes[row["id"]] = {
            "id": row["id"],
            "content": row["content"],
            "tokens": max(token_est, 5),
            "confidence": row["confidence"] or 0.5,
        }

    db.close()

    # Build in-memory FTS
    fts_db = sqlite3.connect(":memory:")
    fts_db.execute(
        "CREATE VIRTUAL TABLE fts USING fts5(id, content, tokenize='porter')"
    )
    for nid, node in nodes.items():
        fts_db.execute("INSERT INTO fts VALUES (?, ?)", (nid, node["content"]))
    fts_db.commit()

    return nodes, fts_db


def retrieve_at_budget(
    query: str,
    nodes: dict[str, dict[str, Any]],
    fts_db: sqlite3.Connection,
    budget: int,
) -> list[str]:
    """Retrieve beliefs up to token budget using FTS5 + OR query."""
    terms = [t.strip() for t in query.split() if len(t.strip()) > 2]
    if not terms:
        return []
    fts_query = " OR ".join(terms)

    try:
        results = fts_db.execute(
            "SELECT id, rank FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT 50",
            (fts_query,),
        ).fetchall()
    except Exception:
        return []

    retrieved: list[str] = []
    tokens_used = 0
    for row in results:
        nid: str = row[0]
        node = nodes.get(nid)
        if not node:
            continue
        node_tokens: int = node["tokens"]
        if tokens_used + node_tokens > budget:
            continue
        retrieved.append(nid)
        tokens_used += node_tokens

    return retrieved


def main() -> None:
    print("=" * 60, file=sys.stderr)
    print(
        "Experiment 4 (retrieval-only): Token Budget vs Critical Belief Coverage",
        file=sys.stderr,
    )
    print("=" * 60, file=sys.stderr)

    nodes, fts_db = load_nodes_and_fts()
    print(f"  Loaded {len(nodes)} nodes", file=sys.stderr)

    results: dict[int, dict[str, Any]] = {}

    for budget in TOKEN_BUDGETS:
        budget_results: dict[str, dict[str, Any]] = {}
        total_needed = 0
        total_found = 0

        for topic_id, topic in CRITICAL_BELIEFS.items():
            query: str = topic["query"]
            retrieved = retrieve_at_budget(query, nodes, fts_db, budget)
            needed: set[str] = set(topic["needed_decisions"])
            found = needed & set(retrieved)

            total_needed += len(needed)
            total_found += len(found)

            budget_results[topic_id] = {
                "needed": list(needed),
                "found": list(found),
                "missed": list(needed - set(retrieved)),
                "coverage": len(found) / len(needed) if needed else 0,
                "retrieved_count": len(retrieved),
            }

        overall_coverage = total_found / total_needed if total_needed > 0 else 0
        results[budget] = {
            "token_budget": budget,
            "overall_coverage": round(overall_coverage, 4),
            "total_needed": total_needed,
            "total_found": total_found,
            "per_topic": budget_results,
        }

        print(
            f"\n  Budget: {budget:,} tokens -> {overall_coverage:.0%} critical belief coverage "
            f"({total_found}/{total_needed})",
            file=sys.stderr,
        )
        for topic_id2, tr in budget_results.items():
            status = "FOUND" if tr["coverage"] == 1.0 else f"MISSING {tr['missed']}"
            print(
                f"    {topic_id2}: {tr['coverage']:.0%} ({tr['retrieved_count']} beliefs retrieved) "
                f"[{status}]",
                file=sys.stderr,
            )

    # Summary table
    print(f"\n{'=' * 60}", file=sys.stderr)
    print("TOKEN BUDGET vs CRITICAL BELIEF COVERAGE", file=sys.stderr)
    print(f"{'=' * 60}", file=sys.stderr)
    print(
        f"{'Budget':>8} {'Coverage':>10} {'Found':>6} {'Needed':>7} {'Beliefs Retrieved':>18}",
        file=sys.stderr,
    )
    print("-" * 55, file=sys.stderr)

    for budget in TOKEN_BUDGETS:
        r: dict[str, Any] = results[budget]
        per_topic_vals: dict[str, dict[str, Any]] = r["per_topic"]
        avg_retrieved = float(
            np.mean([t["retrieved_count"] for t in per_topic_vals.values()])
        )
        print(
            f"{budget:>8,} {r['overall_coverage']:>10.0%} {r['total_found']:>6} "
            f"{r['total_needed']:>7} {avg_retrieved:>18.1f}",
            file=sys.stderr,
        )

    # Find minimum budget for 100% coverage
    full_coverage_budget: int | None = None
    for budget in TOKEN_BUDGETS:
        if results[budget]["overall_coverage"] >= 1.0:
            full_coverage_budget = budget
            break

    print(
        f"\nMinimum budget for 100% critical coverage: "
        f"{full_coverage_budget if full_coverage_budget else 'NOT ACHIEVED'}",
        file=sys.stderr,
    )

    # REQ-003 check
    req003_coverage: float = results[2000]["overall_coverage"]
    print(
        f"Coverage at REQ-003 budget (2,000 tokens): {req003_coverage:.0%}",
        file=sys.stderr,
    )
    print(
        f"REQ-003 status: {'SUFFICIENT' if req003_coverage >= 0.90 else 'INSUFFICIENT'} "
        f"(need >= 90% of critical beliefs at 2K budget)",
        file=sys.stderr,
    )

    output_path = Path("experiments/exp4_results.json")
    output_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nOutput: {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
