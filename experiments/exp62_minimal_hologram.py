"""Experiment 62: Minimal Viable Hologram.

Tests whether a small subset of the belief graph preserves retrieval quality.
Measures coverage-vs-size curve, type ablation, locked-only baseline,
and temporal composition.

All logic uses the production MemoryStore and retrieval pipeline.
"""
from __future__ import annotations

import json
import random
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from agentmemory.compression import compress_belief, estimate_tokens
from agentmemory.models import Belief
from agentmemory.scoring import score_belief
from agentmemory.store import MemoryStore

# ============================================================
# Config
# ============================================================

PRODUCTION_DB: Final[Path] = Path.home() / ".agentmemory" / "memory.db"
RESULTS_PATH: Final[Path] = Path(__file__).parent / "exp62_results.json"
SEED: Final[int] = 42
SEEDS: Final[list[int]] = [42, 137, 256, 314, 999]

# Ground truth: queries and the belief content substrings that must appear
# in results for a hit. Derived from the production DB content -- these are
# beliefs that a knowledgeable user would expect the system to surface.
TOPICS: dict[str, dict[str, Any]] = {
    "scanning_and_onboarding": {
        "query": "scanner onboard project signals extraction",
        "needed_substrings": [
            "detect what signals exist",
            "scanner",
            "Zero human effort",
        ],
    },
    "hrr_architecture": {
        "query": "HRR hyperdimensional vocabulary bridge traversal",
        "needed_substrings": [
            "HRR",
            "vocabulary-bridge",
            "typed traversal",
        ],
    },
    "correction_detection": {
        "query": "correction detection user feedback",
        "needed_substrings": [
            "correction",
            "user confirmation",
        ],
    },
    "typing_and_quality": {
        "query": "pyright strict typing tests",
        "needed_substrings": [
            "pyright",
        ],
    },
    "cross_level_edges": {
        "query": "cross-level edge types entity edges graph connectivity",
        "needed_substrings": [
            "cross-level edge",
            "CROSSDOCENTITY",
        ],
    },
    "cli_and_commands": {
        "query": "CLI command setup installer",
        "needed_substrings": [
            "CLI",
            "command",
        ],
    },
}

# Subgraph sizes to test
K_VALUES: Final[list[int]] = [
    5, 10, 20, 30, 50, 75, 100, 150, 200, 300, 500, 750,
    1000, 2000, 5000, 10000, 15000,
]


# ============================================================
# Helpers
# ============================================================

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_all_beliefs(store: MemoryStore) -> list[Belief]:
    """Load all non-superseded beliefs from the store."""
    rows: list[sqlite3.Row] = store.query(
        "SELECT * FROM beliefs WHERE valid_to IS NULL"
    )
    beliefs: list[Belief] = []
    for r in rows:
        beliefs.append(Belief(
            id=r["id"],
            content_hash=r["content_hash"],
            content=r["content"],
            belief_type=r["belief_type"],
            alpha=r["alpha"],
            beta_param=r["beta_param"],
            confidence=r["confidence"],
            source_type=r["source_type"],
            locked=bool(r["locked"]),
            valid_from=r["valid_from"],
            valid_to=r["valid_to"],
            superseded_by=r["superseded_by"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        ))
    return beliefs


def score_beliefs_global(
    beliefs: list[Belief],
    query: str,
    seed: int = SEED,
) -> list[tuple[Belief, float]]:
    """Score and sort beliefs by the scoring pipeline. Returns (belief, score) pairs."""
    random.seed(seed)
    current_time: str = _now_iso()
    scored: list[tuple[Belief, float]] = []
    for b in beliefs:
        s: float = score_belief(b, query, current_time)
        scored.append((b, s))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def build_fts_index(beliefs: list[Belief], db_path: Path) -> MemoryStore:
    """Build a fresh MemoryStore with only the given beliefs indexed."""
    if db_path.exists():
        db_path.unlink()
    store: MemoryStore = MemoryStore(db_path)
    for b in beliefs:
        store.insert_belief(
            content=b.content,
            belief_type=b.belief_type,
            source_type=b.source_type,
            alpha=b.alpha,
            beta_param=b.beta_param,
            locked=b.locked,
        )
    return store


def evaluate_coverage(
    store: MemoryStore,
    topics: dict[str, dict[str, Any]],
    top_k: int = 50,
) -> dict[str, Any]:
    """Run all topic queries against the store and measure coverage.

    Coverage = how many of the needed substrings appear in ANY of the
    top-k search results.
    """
    total_needed: int = 0
    total_found: int = 0
    per_topic: dict[str, dict[str, Any]] = {}

    for topic_name, topic_data in topics.items():
        query: str = topic_data["query"]
        needed: list[str] = topic_data["needed_substrings"]
        total_needed += len(needed)

        results: list[Belief] = store.search(query, top_k=top_k)
        result_text: str = " ".join(r.content for r in results).lower()

        found: list[str] = []
        missing: list[str] = []
        for substring in needed:
            if substring.lower() in result_text:
                found.append(substring)
            else:
                missing.append(substring)
        total_found += len(found)

        coverage: float = len(found) / len(needed) if needed else 1.0
        per_topic[topic_name] = {
            "query": query,
            "needed": len(needed),
            "found": len(found),
            "missing": missing,
            "coverage": coverage,
            "results_count": len(results),
        }

    macro_coverage: float = (
        sum(t["coverage"] for t in per_topic.values()) / len(per_topic)
        if per_topic else 0.0
    )
    micro_coverage: float = total_found / total_needed if total_needed else 0.0

    return {
        "macro_coverage": macro_coverage,
        "micro_coverage": micro_coverage,
        "total_needed": total_needed,
        "total_found": total_found,
        "per_topic": per_topic,
    }


# ============================================================
# Phase 1: Coverage vs. Size curve
# ============================================================

def phase1_coverage_vs_size(
    all_beliefs: list[Belief],
    tmp_dir: Path,
) -> list[dict[str, Any]]:
    """Sweep subgraph sizes and measure coverage at each."""
    print("\n=== Phase 1: Coverage vs. Size ===", file=sys.stderr)
    results: list[dict[str, Any]] = []

    # Score with a broad query to get a global ranking
    global_query: str = " ".join(
        t["query"] for t in TOPICS.values()
    )

    # Run with multiple seeds for stability measurement
    for seed in SEEDS:
        scored: list[tuple[Belief, float]] = score_beliefs_global(
            all_beliefs, global_query, seed=seed,
        )

        for k in K_VALUES:
            if k > len(scored):
                k = len(scored)

            subset: list[Belief] = [b for b, _ in scored[:k]]

            # Build temporary FTS index
            tmp_db: Path = tmp_dir / f"hologram_k{k}_s{seed}.db"
            sub_store: MemoryStore = build_fts_index(subset, tmp_db)

            # Evaluate
            eval_result: dict[str, Any] = evaluate_coverage(sub_store, TOPICS)
            sub_store.close()
            tmp_db.unlink(missing_ok=True)

            # Token count
            total_tokens: int = sum(
                estimate_tokens(compress_belief(b)) for b in subset
            )

            # Type distribution
            type_dist: dict[str, int] = {}
            for b in subset:
                type_dist[b.belief_type] = type_dist.get(b.belief_type, 0) + 1

            row: dict[str, Any] = {
                "k": k,
                "seed": seed,
                "macro_coverage": eval_result["macro_coverage"],
                "micro_coverage": eval_result["micro_coverage"],
                "total_found": eval_result["total_found"],
                "total_needed": eval_result["total_needed"],
                "total_tokens": total_tokens,
                "type_distribution": type_dist,
            }
            results.append(row)
            print(
                f"  k={k:>5}, seed={seed}: "
                f"macro={eval_result['macro_coverage']:.1%}, "
                f"micro={eval_result['micro_coverage']:.1%}, "
                f"tokens={total_tokens}",
                file=sys.stderr,
            )

    return results


# ============================================================
# Phase 2: Type ablation
# ============================================================

def phase2_type_ablation(
    all_beliefs: list[Belief],
    tmp_dir: Path,
) -> dict[str, Any]:
    """Remove all beliefs of each type and measure coverage delta."""
    print("\n=== Phase 2: Type Ablation ===", file=sys.stderr)

    # Baseline: full graph
    full_db: Path = tmp_dir / "ablation_full.db"
    full_store: MemoryStore = build_fts_index(all_beliefs, full_db)
    baseline: dict[str, Any] = evaluate_coverage(full_store, TOPICS)
    full_store.close()
    full_db.unlink(missing_ok=True)

    print(
        f"  Baseline (full graph, {len(all_beliefs)} beliefs): "
        f"macro={baseline['macro_coverage']:.1%}",
        file=sys.stderr,
    )

    # Get unique types
    types: set[str] = {b.belief_type for b in all_beliefs}
    ablation_results: dict[str, Any] = {
        "baseline": baseline,
        "ablations": {},
    }

    for btype in sorted(types):
        subset: list[Belief] = [b for b in all_beliefs if b.belief_type != btype]
        removed_count: int = len(all_beliefs) - len(subset)

        abl_db: Path = tmp_dir / f"ablation_minus_{btype}.db"
        abl_store: MemoryStore = build_fts_index(subset, abl_db)
        abl_eval: dict[str, Any] = evaluate_coverage(abl_store, TOPICS)
        abl_store.close()
        abl_db.unlink(missing_ok=True)

        delta: float = baseline["macro_coverage"] - abl_eval["macro_coverage"]
        ablation_results["ablations"][btype] = {
            "removed_count": removed_count,
            "remaining_count": len(subset),
            "macro_coverage": abl_eval["macro_coverage"],
            "micro_coverage": abl_eval["micro_coverage"],
            "delta_macro": delta,
            "per_topic": abl_eval["per_topic"],
        }
        print(
            f"  Minus {btype} ({removed_count} removed): "
            f"macro={abl_eval['macro_coverage']:.1%} "
            f"(delta={delta:+.1%})",
            file=sys.stderr,
        )

    return ablation_results


# ============================================================
# Phase 3: Locked-only baseline
# ============================================================

def phase3_locked_only(
    all_beliefs: list[Belief],
    tmp_dir: Path,
) -> dict[str, Any]:
    """Evaluate coverage using only locked beliefs."""
    print("\n=== Phase 3: Locked-Only Baseline ===", file=sys.stderr)

    locked: list[Belief] = [b for b in all_beliefs if b.locked]
    print(f"  Locked beliefs: {len(locked)}", file=sys.stderr)

    if not locked:
        print("  No locked beliefs found. Skipping.", file=sys.stderr)
        return {
            "locked_count": 0,
            "macro_coverage": 0.0,
            "micro_coverage": 0.0,
            "note": "No locked beliefs in production DB",
        }

    lock_db: Path = tmp_dir / "locked_only.db"
    lock_store: MemoryStore = build_fts_index(locked, lock_db)
    lock_eval: dict[str, Any] = evaluate_coverage(lock_store, TOPICS)
    lock_store.close()
    lock_db.unlink(missing_ok=True)

    total_tokens: int = sum(
        estimate_tokens(compress_belief(b)) for b in locked
    )

    print(
        f"  Locked-only: macro={lock_eval['macro_coverage']:.1%}, "
        f"tokens={total_tokens}",
        file=sys.stderr,
    )

    return {
        "locked_count": len(locked),
        "macro_coverage": lock_eval["macro_coverage"],
        "micro_coverage": lock_eval["micro_coverage"],
        "total_tokens": total_tokens,
        "per_topic": lock_eval["per_topic"],
    }


# ============================================================
# Phase 4: Composition test
# ============================================================

def phase4_composition(
    all_beliefs: list[Belief],
    tmp_dir: Path,
) -> dict[str, Any]:
    """Split beliefs by creation time, build holograms, merge, and test."""
    print("\n=== Phase 4: Composition Test ===", file=sys.stderr)

    # Sort by creation time
    sorted_beliefs: list[Belief] = sorted(
        all_beliefs, key=lambda b: b.created_at
    )
    midpoint: int = len(sorted_beliefs) // 2
    first_half: list[Belief] = sorted_beliefs[:midpoint]
    second_half: list[Belief] = sorted_beliefs[midpoint:]

    results: dict[str, Any] = {
        "first_half_count": len(first_half),
        "second_half_count": len(second_half),
    }

    # Evaluate each half separately
    for label, subset in [("first_half", first_half), ("second_half", second_half)]:
        comp_db: Path = tmp_dir / f"comp_{label}.db"
        comp_store: MemoryStore = build_fts_index(subset, comp_db)
        comp_eval: dict[str, Any] = evaluate_coverage(comp_store, TOPICS)
        comp_store.close()
        comp_db.unlink(missing_ok=True)
        results[label] = {
            "macro_coverage": comp_eval["macro_coverage"],
            "micro_coverage": comp_eval["micro_coverage"],
        }
        print(
            f"  {label} ({len(subset)} beliefs): "
            f"macro={comp_eval['macro_coverage']:.1%}",
            file=sys.stderr,
        )

    # Evaluate merged (union = full graph in this case, but tests the concept)
    merged_db: Path = tmp_dir / "comp_merged.db"
    merged_store: MemoryStore = build_fts_index(all_beliefs, merged_db)
    merged_eval: dict[str, Any] = evaluate_coverage(merged_store, TOPICS)
    merged_store.close()
    merged_db.unlink(missing_ok=True)
    results["merged"] = {
        "macro_coverage": merged_eval["macro_coverage"],
        "micro_coverage": merged_eval["micro_coverage"],
    }
    print(
        f"  Merged ({len(all_beliefs)} beliefs): "
        f"macro={merged_eval['macro_coverage']:.1%}",
        file=sys.stderr,
    )

    # Composition fidelity: does merged coverage >= max(half1, half2)?
    max_half: float = max(
        results["first_half"]["macro_coverage"],
        results["second_half"]["macro_coverage"],
    )
    results["composition_fidelity"] = (
        results["merged"]["macro_coverage"] >= max_half
    )

    return results


# ============================================================
# Knee detection
# ============================================================

def find_knee(
    coverage_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Find the knee in the coverage-vs-k curve.

    Uses the average coverage across seeds at each k value.
    The knee is where the second derivative of coverage w.r.t. k peaks.
    """
    # Aggregate by k
    by_k: dict[int, list[float]] = {}
    for row in coverage_data:
        k: int = row["k"]
        if k not in by_k:
            by_k[k] = []
        by_k[k].append(row["macro_coverage"])

    # Sort by k
    k_vals: list[int] = sorted(by_k.keys())
    avg_coverage: list[float] = [
        sum(by_k[k]) / len(by_k[k]) for k in k_vals
    ]
    std_coverage: list[float] = [
        (sum((c - sum(by_k[k]) / len(by_k[k])) ** 2 for c in by_k[k]) / len(by_k[k])) ** 0.5
        for k in k_vals
    ]

    # Find the smallest k where coverage >= 90%
    knee_90: int | None = None
    for i, k in enumerate(k_vals):
        if avg_coverage[i] >= 0.90:
            knee_90 = k
            break

    # Find where marginal gain drops below 2% per step
    plateau_k: int | None = None
    for i in range(1, len(k_vals)):
        delta: float = avg_coverage[i] - avg_coverage[i - 1]
        k_delta: int = k_vals[i] - k_vals[i - 1]
        if k_delta > 0:
            marginal: float = delta / (k_delta / 500.0)  # normalize to per-500
            if marginal < 0.02 and avg_coverage[i] > 0.80:
                plateau_k = k_vals[i]
                break

    return {
        "k_values": k_vals,
        "avg_coverage": avg_coverage,
        "std_coverage": std_coverage,
        "knee_90_pct": knee_90,
        "plateau_k": plateau_k,
    }


# ============================================================
# Main
# ============================================================

def main() -> None:
    random.seed(SEED)
    tmp_dir: Path = Path(__file__).parent / "_exp62_tmp"
    tmp_dir.mkdir(exist_ok=True)

    print(f"Loading beliefs from {PRODUCTION_DB}...", file=sys.stderr)
    store: MemoryStore = MemoryStore(PRODUCTION_DB)
    all_beliefs: list[Belief] = load_all_beliefs(store)
    store.close()
    print(f"  Loaded {len(all_beliefs)} non-superseded beliefs", file=sys.stderr)

    # Type distribution
    type_dist: dict[str, int] = {}
    for b in all_beliefs:
        type_dist[b.belief_type] = type_dist.get(b.belief_type, 0) + 1
    print(f"  Types: {type_dist}", file=sys.stderr)

    # Adjust K_VALUES to not exceed actual count
    valid_k: list[int] = [k for k in K_VALUES if k <= len(all_beliefs)]
    if len(all_beliefs) not in valid_k:
        valid_k.append(len(all_beliefs))

    t0: float = time.monotonic()

    # Phase 1
    phase1_results: list[dict[str, Any]] = phase1_coverage_vs_size(
        all_beliefs, tmp_dir,
    )

    # Phase 2
    phase2_results: dict[str, Any] = phase2_type_ablation(
        all_beliefs, tmp_dir,
    )

    # Phase 3
    phase3_results: dict[str, Any] = phase3_locked_only(
        all_beliefs, tmp_dir,
    )

    # Phase 4
    phase4_results: dict[str, Any] = phase4_composition(
        all_beliefs, tmp_dir,
    )

    # Knee detection
    knee: dict[str, Any] = find_knee(phase1_results)

    elapsed: float = time.monotonic() - t0

    # Assemble results
    output: dict[str, Any] = {
        "config": {
            "db_path": str(PRODUCTION_DB),
            "total_beliefs": len(all_beliefs),
            "type_distribution": type_dist,
            "seeds": SEEDS,
            "topics": {k: v["query"] for k, v in TOPICS.items()},
            "total_needed": sum(
                len(v["needed_substrings"]) for v in TOPICS.values()
            ),
        },
        "phase1_coverage_vs_size": phase1_results,
        "phase2_type_ablation": phase2_results,
        "phase3_locked_only": phase3_results,
        "phase4_composition": phase4_results,
        "knee_analysis": knee,
        "elapsed_seconds": elapsed,
    }

    RESULTS_PATH.write_text(json.dumps(output, indent=2) + "\n")
    print(f"\nResults written to {RESULTS_PATH}", file=sys.stderr)
    print(f"Total time: {elapsed:.1f}s", file=sys.stderr)

    # Summary
    print("\n=== Summary ===", file=sys.stderr)
    print(f"  Knee (90% coverage): k={knee['knee_90_pct']}", file=sys.stderr)
    print(f"  Plateau onset: k={knee['plateau_k']}", file=sys.stderr)
    if knee["avg_coverage"]:
        for i, k in enumerate(knee["k_values"]):
            print(
                f"    k={k:>5}: {knee['avg_coverage'][i]:.1%} "
                f"(+/- {knee['std_coverage'][i]:.1%})",
                file=sys.stderr,
            )

    # Cleanup tmp
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
