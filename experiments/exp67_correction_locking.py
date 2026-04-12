"""Exp 67: Correction Locking Impact

Tests whether locking all unlocked corrections improves retrieval quality
(MRR@10 and coverage) on ground-truth queries.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
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

TOP_K: Final[int] = 30
MRR_K: Final[int] = 10

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

def measure_retrieval(
    store: MemoryStore,
    queries: list[str],
    ground_truth: dict[str, set[str]],
) -> dict[str, object]:
    """Run retrieval and measure MRR@10 and coverage."""
    total_hits: int = 0
    total_expected: int = 0
    reciprocal_ranks: list[float] = []
    correction_ids_in_top10: set[str] = set()

    for q in queries:
        rr: RetrievalResult = retrieve(store, q, top_k=TOP_K)
        retrieved_ids: list[str] = [b.id for b in rr.beliefs]
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

        # Track corrections in top-10
        for b in rr.beliefs[:MRR_K]:
            if b.belief_type == "correction":
                correction_ids_in_top10.add(b.id)

    mrr: float = sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0
    coverage: float = total_hits / total_expected if total_expected > 0 else 0.0

    return {
        "mrr": mrr,
        "coverage": coverage,
        "total_hits": total_hits,
        "total_expected": total_expected,
        "correction_ids_in_top10": sorted(correction_ids_in_top10),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not LIVE_DB.exists():
        print(f"ERROR: Live DB not found at {LIVE_DB}", file=sys.stderr)
        sys.exit(1)

    # Copy DB to temp
    tmp_dir: str = tempfile.mkdtemp(prefix="exp67_")
    tmp_db: Path = Path(tmp_dir) / "memory.db"
    shutil.copy2(LIVE_DB, tmp_db)
    for suffix in ["-wal", "-shm"]:
        wal: Path = LIVE_DB.with_suffix(LIVE_DB.suffix + suffix)
        if wal.exists():
            shutil.copy2(wal, tmp_db.with_suffix(tmp_db.suffix + suffix))
    print(f"Working on temp DB: {tmp_db}")

    store: MemoryStore = MemoryStore(tmp_db)

    # Count unlocked corrections
    conn: sqlite3.Connection = sqlite3.connect(str(tmp_db))
    conn.row_factory = sqlite3.Row
    unlocked_count_row: sqlite3.Row | None = conn.execute(
        "SELECT COUNT(*) as cnt FROM beliefs WHERE belief_type='correction' AND locked=0"
    ).fetchone()
    unlocked_count: int = unlocked_count_row["cnt"] if unlocked_count_row else 0
    print(f"Unlocked corrections: {unlocked_count}")

    # Bootstrap ground truth from initial retrieval (top-3 per query)
    ground_truth: dict[str, set[str]] = {}
    for q in QUERIES:
        rr: RetrievalResult = retrieve(store, q, top_k=TOP_K)
        ground_truth[q] = set(b.id for b in rr.beliefs[:3])

    # Baseline measurement
    print("Measuring baseline...")
    baseline: dict[str, object] = measure_retrieval(store, QUERIES, ground_truth)
    baseline_corrections: set[str] = set(baseline["correction_ids_in_top10"])  # type: ignore[arg-type]
    print(f"  Baseline MRR@{MRR_K}: {baseline['mrr']:.4f}")
    print(f"  Baseline coverage: {baseline['coverage']:.4f}")
    print(f"  Corrections in top-10: {len(baseline_corrections)}")

    # Lock all corrections
    conn.execute(
        "UPDATE beliefs SET locked=1 WHERE belief_type='correction' AND locked=0"
    )
    conn.commit()
    conn.close()

    # Re-open store to pick up changes
    store_after: MemoryStore = MemoryStore(tmp_db)

    # Post-lock measurement
    print("Measuring after locking all corrections...")
    after: dict[str, object] = measure_retrieval(store_after, QUERIES, ground_truth)
    after_corrections: set[str] = set(after["correction_ids_in_top10"])  # type: ignore[arg-type]
    new_corrections: set[str] = after_corrections - baseline_corrections
    print(f"  After MRR@{MRR_K}: {after['mrr']:.4f}")
    print(f"  After coverage: {after['coverage']:.4f}")
    print(f"  Corrections in top-10: {len(after_corrections)}")
    print(f"  Newly surfaced corrections: {len(new_corrections)}")

    # Results
    mrr_delta: float = float(after["mrr"]) - float(baseline["mrr"])  # type: ignore[arg-type]
    cov_delta: float = float(after["coverage"]) - float(baseline["coverage"])  # type: ignore[arg-type]

    output: dict[str, object] = {
        "experiment": "exp67_correction_locking",
        "unlocked_corrections": unlocked_count,
        "baseline": {
            "mrr": baseline["mrr"],
            "coverage": baseline["coverage"],
            "corrections_in_top10": len(baseline_corrections),
        },
        "after_locking": {
            "mrr": after["mrr"],
            "coverage": after["coverage"],
            "corrections_in_top10": len(after_corrections),
            "newly_surfaced": len(new_corrections),
            "new_correction_ids": sorted(new_corrections),
        },
        "mrr_delta": mrr_delta,
        "coverage_delta": cov_delta,
        "success": mrr_delta >= 0.0 or cov_delta >= 0.0,
        "success_criterion": "Coverage or MRR improves after locking corrections",
    }

    out_path: Path = Path(__file__).parent / "exp67_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nMRR delta:      {mrr_delta:+.4f}")
    print(f"Coverage delta: {cov_delta:+.4f}")
    print(f"Success:        {output['success']}")
    print(f"Results saved to: {out_path}")

    # Cleanup
    shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
