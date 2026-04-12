"""Exp 70: FTS5 Top-K Scaling

Tests whether increasing FTS5 top_k from 30 to 50/75/100 improves retrieval
coverage, and identifies the point of diminishing returns.

Read-only against live DB. No writes.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Final

from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CWD: Final[str] = "/Users/thelorax/projects/agentmemory"
DB_HASH: Final[str] = hashlib.sha256(CWD.encode()).hexdigest()[:12]
LIVE_DB: Final[Path] = Path.home() / ".agentmemory" / "projects" / DB_HASH / "memory.db"

MRR_K: Final[int] = 10
TOP_K_VALUES: Final[list[int]] = [30, 50, 75, 100]
BUDGET: Final[int] = 2000
WARMUP_RUNS: Final[int] = 2
TIMED_RUNS: Final[int] = 5

QUERIES: Final[list[str]] = [
    "locked beliefs constraints",
    "FTS5 retrieval search",
    "correction detection pipeline",
    "belief type priors weights",
    "HRR vocabulary bridge",
    "scoring pipeline Thompson sampling",
    "recency boost new beliefs",
    "token budget compression",
    "session tracking tokens",
    "edge graph triples",
    "observation ingestion pipeline",
    "belief compression packing",
    "classification Haiku pipeline",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def measure_at_topk(
    store: MemoryStore,
    queries: list[str],
    ground_truth: dict[str, set[str]],
    top_k: int,
) -> dict[str, object]:
    """Retrieve at given top_k and measure coverage, MRR, tokens, latency."""
    total_hits: int = 0
    total_expected: int = 0
    reciprocal_ranks: list[float] = []
    total_tokens: int = 0
    all_belief_ids: set[str] = set()

    # Warmup
    for _ in range(WARMUP_RUNS):
        for q in queries:
            retrieve(store, q, top_k=top_k, budget=BUDGET)

    # Timed runs
    latencies_ms: list[float] = []
    for run_idx in range(TIMED_RUNS):
        t0: float = time.perf_counter()
        for q in queries:
            rr: RetrievalResult = retrieve(store, q, top_k=top_k, budget=BUDGET)

            # Only measure metrics on last timed run
            if run_idx == TIMED_RUNS - 1:
                retrieved_ids: list[str] = [b.id for b in rr.beliefs]
                all_belief_ids.update(retrieved_ids)
                gt: set[str] = ground_truth.get(q, set())

                # Coverage
                hits: int = len(gt & set(retrieved_ids))
                total_hits += hits
                total_expected += len(gt)

                # MRR
                rr_val: float = 0.0
                for rank, bid in enumerate(retrieved_ids[:MRR_K], start=1):
                    if bid in gt:
                        rr_val = 1.0 / rank
                        break
                reciprocal_ranks.append(rr_val)

                total_tokens += rr.total_tokens

        t1: float = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000.0)

    mrr: float = sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0
    coverage: float = total_hits / total_expected if total_expected > 0 else 0.0
    avg_latency_ms: float = sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0
    avg_tokens: float = total_tokens / len(queries) if queries else 0.0

    return {
        "top_k": top_k,
        "coverage": coverage,
        "mrr": mrr,
        "total_tokens": total_tokens,
        "avg_tokens_per_query": avg_tokens,
        "avg_latency_ms": avg_latency_ms,
        "unique_beliefs_retrieved": len(all_belief_ids),
        "within_budget": total_tokens <= BUDGET * len(queries),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not LIVE_DB.exists():
        print(f"ERROR: Live DB not found at {LIVE_DB}", file=sys.stderr)
        sys.exit(1)

    print(f"Using live DB (read-only): {LIVE_DB}")
    store: MemoryStore = MemoryStore(LIVE_DB)

    # Bootstrap ground truth from top_k=100 retrieval (top-3 per query)
    print("Bootstrapping ground truth from top_k=100...")
    ground_truth: dict[str, set[str]] = {}
    for q in QUERIES:
        rr: RetrievalResult = retrieve(store, q, top_k=100, budget=BUDGET)
        ground_truth[q] = set(b.id for b in rr.beliefs[:3])
    gt_size: int = sum(len(v) for v in ground_truth.values())
    print(f"Ground truth: {gt_size} beliefs across {len(QUERIES)} queries")

    # Measure at each top_k
    results_per_k: list[dict[str, object]] = []
    for top_k in TOP_K_VALUES:
        print(f"\nMeasuring top_k={top_k}...")
        metrics: dict[str, object] = measure_at_topk(store, QUERIES, ground_truth, top_k)
        results_per_k.append(metrics)
        print(f"  Coverage:  {metrics['coverage']:.4f}")
        print(f"  MRR@{MRR_K}:   {metrics['mrr']:.4f}")
        print(f"  Tokens:    {metrics['total_tokens']}")
        print(f"  Latency:   {metrics['avg_latency_ms']:.1f} ms")
        print(f"  Unique beliefs: {metrics['unique_beliefs_retrieved']}")

    # Marginal coverage analysis
    print("\n--- Marginal Coverage Analysis ---")
    marginal_gains: list[dict[str, object]] = []
    for i in range(1, len(results_per_k)):
        prev_cov: float = float(results_per_k[i - 1]["coverage"])  # type: ignore[arg-type]
        curr_cov: float = float(results_per_k[i]["coverage"])  # type: ignore[arg-type]
        prev_k: int = int(results_per_k[i - 1]["top_k"])  # type: ignore[arg-type]
        curr_k: int = int(results_per_k[i]["top_k"])  # type: ignore[arg-type]
        delta_cov: float = curr_cov - prev_cov
        delta_k: int = curr_k - prev_k
        marginal: float = delta_cov / delta_k if delta_k > 0 else 0.0
        marginal_gains.append({
            "from_k": prev_k,
            "to_k": curr_k,
            "coverage_delta": delta_cov,
            "marginal_per_k": marginal,
        })
        print(f"  {prev_k} -> {curr_k}: coverage delta = {delta_cov:+.4f}, marginal = {marginal:.6f}/k")

    # Find best top_k within budget
    best_within_budget: dict[str, object] | None = None
    for m in results_per_k:
        if m["within_budget"]:
            if best_within_budget is None or float(m["coverage"]) > float(best_within_budget["coverage"]):  # type: ignore[arg-type]
                best_within_budget = m

    output: dict[str, object] = {
        "experiment": "exp70_fts5_topk_scaling",
        "budget": BUDGET,
        "num_queries": len(QUERIES),
        "ground_truth_size": gt_size,
        "results_per_k": results_per_k,
        "marginal_gains": marginal_gains,
        "best_within_budget": best_within_budget,
        "success": (
            best_within_budget is not None
            and int(best_within_budget.get("top_k", 30)) > 30  # type: ignore[arg-type]
        ),
        "success_criterion": "Coverage improves at top_k=50 without exceeding token budget",
    }

    out_path: Path = Path(__file__).parent / "exp70_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nBest top_k within budget: {best_within_budget}")
    print(f"Success: {output['success']}")
    print(f"Results saved to: {out_path}")


if __name__ == "__main__":
    main()
