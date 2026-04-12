"""Exp 66: Feedback Loop Validation

Tests whether Bayesian feedback (alpha/beta updates via record_test_result)
improves MRR@10 over 50 simulated retrieval rounds on a copy of the live DB.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
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

NUM_ROUNDS: Final[int] = 50
TOP_K: Final[int] = 30
MRR_K: Final[int] = 10
SESSION_ID: Final[str] = "exp66_sim"

# Ground-truth queries: topic -> list of keyword queries.
# We discover relevant belief IDs dynamically from the DB on first retrieval
# and treat top-3 beliefs from round 0 as "ground truth" (self-bootstrapped).
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

def compute_mrr(
    results: dict[str, list[str]],
    ground_truth: dict[str, set[str]],
    k: int,
) -> float:
    """Mean Reciprocal Rank at k across all queries."""
    reciprocal_ranks: list[float] = []
    for query, retrieved_ids in results.items():
        gt: set[str] = ground_truth.get(query, set())
        if not gt:
            continue
        rr: float = 0.0
        for rank, bid in enumerate(retrieved_ids[:k], start=1):
            if bid in gt:
                rr = 1.0 / rank
                break
        reciprocal_ranks.append(rr)
    if not reciprocal_ranks:
        return 0.0
    return sum(reciprocal_ranks) / len(reciprocal_ranks)


def run_retrieval_round(
    store: MemoryStore,
    queries: list[str],
) -> dict[str, list[str]]:
    """Run retrieve() for each query, return query -> ordered belief IDs."""
    results: dict[str, list[str]] = {}
    for q in queries:
        rr: RetrievalResult = retrieve(store, q, top_k=TOP_K)
        results[q] = [b.id for b in rr.beliefs]
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not LIVE_DB.exists():
        print(f"ERROR: Live DB not found at {LIVE_DB}", file=sys.stderr)
        sys.exit(1)

    # Copy DB to temp
    tmp_dir: str = tempfile.mkdtemp(prefix="exp66_")
    tmp_db: Path = Path(tmp_dir) / "memory.db"
    shutil.copy2(LIVE_DB, tmp_db)
    # Also copy WAL/SHM if present
    for suffix in ["-wal", "-shm"]:
        wal: Path = LIVE_DB.with_suffix(LIVE_DB.suffix + suffix)
        if wal.exists():
            shutil.copy2(wal, tmp_db.with_suffix(tmp_db.suffix + suffix))
    print(f"Working on temp DB: {tmp_db}")

    store: MemoryStore = MemoryStore(tmp_db)

    # Bootstrap ground truth: first retrieval pass, top-3 per query are "relevant"
    initial_results: dict[str, list[str]] = run_retrieval_round(store, QUERIES)
    ground_truth: dict[str, set[str]] = {}
    for q, ids in initial_results.items():
        ground_truth[q] = set(ids[:3])

    print(f"Ground truth: {sum(len(v) for v in ground_truth.values())} beliefs across {len(QUERIES)} queries")

    # Run 50 rounds of retrieval + feedback
    mrr_per_round: list[float] = []
    for round_num in range(NUM_ROUNDS):
        results: dict[str, list[str]] = run_retrieval_round(store, QUERIES)

        # Record feedback
        for q, ids in results.items():
            gt: set[str] = ground_truth.get(q, set())
            for bid in ids[:MRR_K]:
                outcome: str = "used" if bid in gt else "ignored"
                store.record_test_result(
                    belief_id=bid,
                    session_id=SESSION_ID,
                    outcome=outcome,
                    detection_layer="checkpoint",
                )

        mrr: float = compute_mrr(results, ground_truth, MRR_K)
        mrr_per_round.append(mrr)

        if round_num % 10 == 0 or round_num == NUM_ROUNDS - 1:
            print(f"  Round {round_num + 1:3d}: MRR@{MRR_K} = {mrr:.4f}")

    # Results
    initial_mrr: float = mrr_per_round[0]
    final_mrr: float = mrr_per_round[-1]
    delta: float = final_mrr - initial_mrr
    pct_change: float = (delta / initial_mrr * 100.0) if initial_mrr > 0.0 else 0.0

    output: dict[str, object] = {
        "experiment": "exp66_feedback_loop",
        "num_rounds": NUM_ROUNDS,
        "num_queries": len(QUERIES),
        "ground_truth_size": sum(len(v) for v in ground_truth.values()),
        "mrr_per_round": mrr_per_round,
        "initial_mrr": initial_mrr,
        "final_mrr": final_mrr,
        "delta": delta,
        "pct_change": pct_change,
        "success": pct_change >= 10.0,
        "success_criterion": "MRR improves by >= 10% over 50 rounds",
    }

    out_path: Path = Path(__file__).parent / "exp66_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nInitial MRR@{MRR_K}: {initial_mrr:.4f}")
    print(f"Final MRR@{MRR_K}:   {final_mrr:.4f}")
    print(f"Delta:            {delta:+.4f} ({pct_change:+.1f}%)")
    print(f"Success:          {output['success']}")
    print(f"Results saved to: {out_path}")

    # Cleanup
    shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
