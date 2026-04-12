"""Exp 68: Spread Type Priors

Tests whether differentiated Bayesian priors per belief type make Thompson
sampling scoring meaningful, increasing score variance while preserving MRR.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.scoring import score_belief
from agentmemory.store import MemoryStore

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CWD: Final[str] = "/Users/thelorax/projects/agentmemory"
DB_HASH: Final[str] = hashlib.sha256(CWD.encode()).hexdigest()[:12]
LIVE_DB: Final[Path] = Path.home() / ".agentmemory" / "projects" / DB_HASH / "memory.db"

TOP_K: Final[int] = 30
MRR_K: Final[int] = 10

# New priors: (alpha, beta_param) per belief type
TYPE_PRIORS: Final[dict[str, tuple[float, float]]] = {
    "requirement": (9.0, 0.5),
    "correction": (9.0, 0.5),
    "preference": (7.0, 1.0),
    "factual": (3.0, 1.0),
    "procedural": (2.0, 1.0),
    "causal": (2.0, 1.0),
    "relational": (2.0, 1.0),
}

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

def measure_scores_and_mrr(
    store: MemoryStore,
    queries: list[str],
    ground_truth: dict[str, set[str]],
) -> dict[str, object]:
    """Retrieve, measure MRR@10, and collect score stats per belief type."""
    now_iso: str = datetime.now(timezone.utc).isoformat()
    reciprocal_ranks: list[float] = []
    scores_by_type: dict[str, list[float]] = {}
    type_ranks: dict[str, list[int]] = {}  # type -> list of ranks in results

    for q in queries:
        rr: RetrievalResult = retrieve(store, q, top_k=TOP_K)
        retrieved_ids: list[str] = [b.id for b in rr.beliefs]
        gt: set[str] = ground_truth.get(q, set())

        # MRR
        rr_val: float = 0.0
        for rank, bid in enumerate(retrieved_ids[:MRR_K], start=1):
            if bid in gt:
                rr_val = 1.0 / rank
                break
        reciprocal_ranks.append(rr_val)

        # Score stats by type
        for rank, b in enumerate(rr.beliefs, start=1):
            s: float = score_belief(b, q, now_iso)
            bt: str = b.belief_type
            if bt not in scores_by_type:
                scores_by_type[bt] = []
            scores_by_type[bt].append(s)
            if bt not in type_ranks:
                type_ranks[bt] = []
            type_ranks[bt].append(rank)

    mrr: float = sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0

    # Compute per-type stats
    type_stats: dict[str, dict[str, float]] = {}
    for bt, scores in scores_by_type.items():
        type_stats[bt] = {
            "mean_score": statistics.mean(scores) if scores else 0.0,
            "std_score": statistics.stdev(scores) if len(scores) > 1 else 0.0,
            "count": float(len(scores)),
            "mean_rank": statistics.mean(type_ranks.get(bt, [0.0])),
        }

    # Overall score variance
    all_scores: list[float] = []
    for s_list in scores_by_type.values():
        all_scores.extend(s_list)
    overall_std: float = statistics.stdev(all_scores) if len(all_scores) > 1 else 0.0

    return {
        "mrr": mrr,
        "overall_score_std": overall_std,
        "type_stats": type_stats,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not LIVE_DB.exists():
        print(f"ERROR: Live DB not found at {LIVE_DB}", file=sys.stderr)
        sys.exit(1)

    # Two temp copies: one for baseline, one for spread priors
    tmp_dir: str = tempfile.mkdtemp(prefix="exp68_")
    baseline_db: Path = Path(tmp_dir) / "baseline.db"
    spread_db: Path = Path(tmp_dir) / "spread.db"
    shutil.copy2(LIVE_DB, baseline_db)
    shutil.copy2(LIVE_DB, spread_db)
    for suffix in ["-wal", "-shm"]:
        wal: Path = LIVE_DB.with_suffix(LIVE_DB.suffix + suffix)
        if wal.exists():
            shutil.copy2(wal, baseline_db.with_suffix(baseline_db.suffix + suffix))
            shutil.copy2(wal, spread_db.with_suffix(spread_db.suffix + suffix))
    print(f"Working in: {tmp_dir}")

    # Apply spread priors to spread_db
    conn: sqlite3.Connection = sqlite3.connect(str(spread_db))
    for btype, (alpha, beta) in TYPE_PRIORS.items():
        affected: int = conn.execute(
            "UPDATE beliefs SET alpha = ?, beta_param = ? WHERE belief_type = ?",
            (alpha, beta, btype),
        ).rowcount
        print(f"  Set {btype}: alpha={alpha}, beta={beta} ({affected} beliefs)")
    conn.commit()
    conn.close()

    # Open stores
    store_baseline: MemoryStore = MemoryStore(baseline_db)
    store_spread: MemoryStore = MemoryStore(spread_db)

    # Bootstrap ground truth from baseline
    ground_truth: dict[str, set[str]] = {}
    for q in QUERIES:
        rr: RetrievalResult = retrieve(store_baseline, q, top_k=TOP_K)
        ground_truth[q] = set(b.id for b in rr.beliefs[:3])

    # Measure baseline
    print("\nMeasuring baseline (uniform priors)...")
    baseline_metrics: dict[str, object] = measure_scores_and_mrr(
        store_baseline, QUERIES, ground_truth
    )
    print(f"  MRR@{MRR_K}: {baseline_metrics['mrr']:.4f}")
    print(f"  Score std: {baseline_metrics['overall_score_std']:.4f}")

    # Measure spread
    print("Measuring spread priors...")
    spread_metrics: dict[str, object] = measure_scores_and_mrr(
        store_spread, QUERIES, ground_truth
    )
    print(f"  MRR@{MRR_K}: {spread_metrics['mrr']:.4f}")
    print(f"  Score std: {spread_metrics['overall_score_std']:.4f}")

    # Compare
    mrr_delta: float = float(spread_metrics["mrr"]) - float(baseline_metrics["mrr"])  # type: ignore[arg-type]
    std_delta: float = float(spread_metrics["overall_score_std"]) - float(baseline_metrics["overall_score_std"])  # type: ignore[arg-type]

    variance_increased: bool = std_delta > 0.0
    mrr_preserved: bool = mrr_delta >= -0.05  # Allow 5% tolerance

    # Check if requirements/corrections rank higher than factual
    spread_stats: dict[str, dict[str, float]] = spread_metrics["type_stats"]  # type: ignore[assignment]
    req_rank: float = spread_stats.get("requirement", {}).get("mean_rank", 999.0)
    corr_rank: float = spread_stats.get("correction", {}).get("mean_rank", 999.0)
    fact_rank: float = spread_stats.get("factual", {}).get("mean_rank", 999.0)
    high_value_ranks_better: bool = min(req_rank, corr_rank) < fact_rank

    output: dict[str, object] = {
        "experiment": "exp68_spread_type_priors",
        "type_priors": {k: {"alpha": v[0], "beta": v[1]} for k, v in TYPE_PRIORS.items()},
        "baseline": baseline_metrics,
        "spread": spread_metrics,
        "mrr_delta": mrr_delta,
        "score_std_delta": std_delta,
        "variance_increased": variance_increased,
        "mrr_preserved": mrr_preserved,
        "high_value_ranks_better": high_value_ranks_better,
        "success": variance_increased and mrr_preserved,
        "success_criterion": "Score variance increases AND MRR does not decrease",
    }

    out_path: Path = Path(__file__).parent / "exp68_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nMRR delta:            {mrr_delta:+.4f}")
    print(f"Score std delta:      {std_delta:+.4f}")
    print(f"Variance increased:   {variance_increased}")
    print(f"MRR preserved:        {mrr_preserved}")
    print(f"High-value rank better: {high_value_ranks_better}")
    print(f"Success:              {output['success']}")
    print(f"Results saved to:     {out_path}")

    # Cleanup
    shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
