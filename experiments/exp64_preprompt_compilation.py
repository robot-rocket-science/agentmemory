"""Experiment 64: Query-Aware Pre-Prompt Compilation.

Tests whether running a set of broad project-level queries at session start
and packing the merged results into a token budget produces useful compiled
context. Measures coverage vs budget, compares against random and type-filtered
baselines, detects the compiled-vs-on-demand cage, and profiles latency.

Hypothesis: Query-aware compilation at 2000 tokens covers >60% of ground-truth
topics, outperforming random selection and matching type-filtered baselines.
"""
from __future__ import annotations

import json
import random
import sqlite3
import sys
import time
from collections import Counter
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
RESULTS_PATH: Final[Path] = Path(__file__).parent / "exp64_results.json"
SEED: Final[int] = 42

COMPILATION_QUERIES: Final[list[str]] = [
    "project requirements constraints rules",
    "architecture design decisions",
    "corrections mistakes what not to do",
    "tools libraries dependencies",
    "testing quality standards",
]

BUDGETS: Final[list[int]] = [250, 500, 750, 1000, 1500, 2000, 3000, 4000, 6000]

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

# Cage detection budgets
CAGE_COMPILED_BUDGETS: Final[list[int]] = [0, 500, 1000, 1500, 2000, 2500, 3000]
CAGE_TOTAL_BUDGET: Final[int] = 4000

# Latency config
LATENCY_BUDGET: Final[int] = 2000
LATENCY_REPS: Final[int] = 20

RANDOM_TRIALS: Final[int] = 10


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


def compile_context(
    store: MemoryStore,
    queries: list[str],
    budget_tokens: int,
    seed: int = SEED,
) -> list[tuple[Belief, str, float]]:
    """Run compilation queries, merge, score, compress, pack into budget.

    Returns list of (belief, compressed_text, score) packed within budget.
    """
    random.seed(seed)
    current_time: str = _now_iso()

    # Step 1-2: Run queries, merge, deduplicate
    seen_ids: set[str] = set()
    merged: list[Belief] = []
    for q in queries:
        results: list[Belief] = store.search(q, top_k=30)
        for b in results:
            if b.id not in seen_ids:
                seen_ids.add(b.id)
                merged.append(b)

    # Step 3: Score with combined query
    combined_query: str = " ".join(queries)
    scored: list[tuple[Belief, float]] = []
    for b in merged:
        s: float = score_belief(b, combined_query, current_time)
        scored.append((b, s))
    scored.sort(key=lambda x: x[1], reverse=True)

    # Step 4-5: Compress and greedily pack
    packed: list[tuple[Belief, str, float]] = []
    tokens_used: int = 0
    for b, s in scored:
        compressed: str = compress_belief(b)
        t: int = estimate_tokens(compressed)
        if tokens_used + t > budget_tokens:
            continue
        packed.append((b, compressed, s))
        tokens_used += t

    return packed


def coverage_from_texts(
    texts: list[str],
    topics: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Measure ground-truth substring coverage from a list of text strings."""
    combined: str = " ".join(texts).lower()
    total_needed: int = 0
    total_found: int = 0
    per_topic: dict[str, dict[str, Any]] = {}

    for topic_name, topic_data in topics.items():
        needed: list[str] = topic_data["needed_substrings"]
        total_needed += len(needed)

        found: list[str] = []
        missing: list[str] = []
        for sub in needed:
            if sub.lower() in combined:
                found.append(sub)
                total_found += 1
            else:
                missing.append(sub)

        per_topic[topic_name] = {
            "needed": len(needed),
            "found": len(found),
            "found_substrings": found,
            "missing_substrings": missing,
        }

    coverage_pct: float = (total_found / total_needed * 100.0) if total_needed > 0 else 0.0
    return {
        "total_needed": total_needed,
        "total_found": total_found,
        "coverage_pct": round(coverage_pct, 1),
        "per_topic": per_topic,
    }


def type_distribution(beliefs: list[Belief]) -> dict[str, int]:
    """Count beliefs by type."""
    counts: Counter[str] = Counter()
    for b in beliefs:
        counts[b.belief_type] += 1
    return dict(counts)


# ============================================================
# Phase 2 & 3: Compilation pipeline + Coverage evaluation
# ============================================================

def run_compilation_sweep(store: MemoryStore) -> list[dict[str, Any]]:
    """Run compilation at each budget level and measure coverage."""
    results: list[dict[str, Any]] = []
    for budget in BUDGETS:
        packed: list[tuple[Belief, str, float]] = compile_context(
            store, COMPILATION_QUERIES, budget
        )
        beliefs_packed: list[Belief] = [p[0] for p in packed]
        texts: list[str] = [p[1] for p in packed]
        total_tokens: int = sum(estimate_tokens(t) for t in texts)
        cov: dict[str, Any] = coverage_from_texts(texts, TOPICS)

        results.append({
            "budget": budget,
            "belief_count": len(packed),
            "total_tokens": total_tokens,
            "type_distribution": type_distribution(beliefs_packed),
            "coverage": cov,
        })
        print(
            f"  budget={budget:>5}  beliefs={len(packed):>4}  "
            f"tokens={total_tokens:>5}  coverage={cov['coverage_pct']}%",
            file=sys.stderr,
        )
    return results


# ============================================================
# Phase 4: Baseline comparison
# ============================================================

def run_random_baseline(
    all_beliefs: list[Belief],
    target_count: int,
    trials: int = RANDOM_TRIALS,
) -> dict[str, Any]:
    """Random-k baseline: randomly select target_count beliefs, measure coverage."""
    coverages: list[float] = []
    for trial in range(trials):
        random.seed(SEED + trial)
        sample: list[Belief] = random.sample(
            all_beliefs, min(target_count, len(all_beliefs))
        )
        texts: list[str] = [compress_belief(b) for b in sample]
        cov: dict[str, Any] = coverage_from_texts(texts, TOPICS)
        coverages.append(cov["coverage_pct"])

    mean_cov: float = sum(coverages) / len(coverages)
    variance: float = sum((c - mean_cov) ** 2 for c in coverages) / len(coverages)
    std_cov: float = variance ** 0.5
    return {
        "mean_coverage_pct": round(mean_cov, 1),
        "std_coverage_pct": round(std_cov, 1),
        "trials": trials,
        "target_count": target_count,
        "all_coverages": [round(c, 1) for c in coverages],
    }


def run_type_filtered_baseline(
    all_beliefs: list[Belief],
    budget_tokens: int,
) -> dict[str, Any]:
    """Type-filtered baseline: only requirement + correction, scored and packed."""
    random.seed(SEED)
    current_time: str = _now_iso()
    filtered: list[Belief] = [
        b for b in all_beliefs
        if b.belief_type in ("requirement", "correction")
    ]
    combined_query: str = " ".join(COMPILATION_QUERIES)
    scored: list[tuple[Belief, float]] = []
    for b in filtered:
        s: float = score_belief(b, combined_query, current_time)
        scored.append((b, s))
    scored.sort(key=lambda x: x[1], reverse=True)

    packed_texts: list[str] = []
    packed_beliefs: list[Belief] = []
    tokens_used: int = 0
    for b, _s in scored:
        compressed: str = compress_belief(b)
        t: int = estimate_tokens(compressed)
        if tokens_used + t > budget_tokens:
            continue
        packed_texts.append(compressed)
        packed_beliefs.append(b)
        tokens_used += t

    cov: dict[str, Any] = coverage_from_texts(packed_texts, TOPICS)
    return {
        "budget": budget_tokens,
        "belief_count": len(packed_beliefs),
        "total_tokens": tokens_used,
        "type_distribution": type_distribution(packed_beliefs),
        "coverage": cov,
    }


def run_baselines(
    store: MemoryStore,
    all_beliefs: list[Belief],
    compilation_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Run random and type-filtered baselines at each budget level."""
    baseline_results: list[dict[str, Any]] = []
    for comp in compilation_results:
        budget: int = comp["budget"]
        belief_count: int = comp["belief_count"]

        random_bl: dict[str, Any] = run_random_baseline(all_beliefs, belief_count)
        type_bl: dict[str, Any] = run_type_filtered_baseline(all_beliefs, budget)

        baseline_results.append({
            "budget": budget,
            "compiled_coverage_pct": comp["coverage"]["coverage_pct"],
            "random_baseline": random_bl,
            "type_filtered_baseline": type_bl,
        })
        print(
            f"  budget={budget:>5}  compiled={comp['coverage']['coverage_pct']:>5}%  "
            f"random={random_bl['mean_coverage_pct']:>5}%+-{random_bl['std_coverage_pct']:.1f}  "
            f"type_filtered={type_bl['coverage']['coverage_pct']:>5}%",
            file=sys.stderr,
        )
    return baseline_results


# ============================================================
# Phase 5: Cage detection
# ============================================================

def run_cage_detection(store: MemoryStore) -> list[dict[str, Any]]:
    """Detect whether compiled context crowds out on-demand retrieval."""
    cage_results: list[dict[str, Any]] = []

    for compiled_budget in CAGE_COMPILED_BUDGETS:
        ondemand_budget: int = CAGE_TOTAL_BUDGET - compiled_budget

        # Compile context
        if compiled_budget > 0:
            packed: list[tuple[Belief, str, float]] = compile_context(
                store, COMPILATION_QUERIES, compiled_budget
            )
            compiled_texts: list[str] = [p[1] for p in packed]
            compiled_ids: set[str] = {p[0].id for p in packed}
        else:
            compiled_texts = []
            compiled_ids = set()

        # On-demand retrieval per topic
        ondemand_texts: list[str] = []
        for _topic_name, topic_data in TOPICS.items():
            query: str = topic_data["query"]
            results: list[Belief] = store.search(query, top_k=30)
            # Pack on-demand results into remaining budget
            tokens_left: int = ondemand_budget
            for b in results:
                if b.id in compiled_ids:
                    continue  # already in compiled context
                compressed: str = compress_belief(b)
                t: int = estimate_tokens(compressed)
                if tokens_left - t < 0:
                    break
                ondemand_texts.append(compressed)
                tokens_left -= t

        # Union coverage
        all_texts: list[str] = compiled_texts + ondemand_texts
        union_cov: dict[str, Any] = coverage_from_texts(all_texts, TOPICS)
        compiled_cov: dict[str, Any] = coverage_from_texts(compiled_texts, TOPICS)
        ondemand_cov: dict[str, Any] = coverage_from_texts(ondemand_texts, TOPICS)

        cage_results.append({
            "compiled_budget": compiled_budget,
            "ondemand_budget": ondemand_budget,
            "compiled_coverage_pct": compiled_cov["coverage_pct"],
            "ondemand_coverage_pct": ondemand_cov["coverage_pct"],
            "union_coverage_pct": union_cov["coverage_pct"],
        })
        print(
            f"  compiled_b={compiled_budget:>5}  ondemand_b={ondemand_budget:>5}  "
            f"union={union_cov['coverage_pct']:>5}%  "
            f"compiled={compiled_cov['coverage_pct']:>5}%  "
            f"ondemand={ondemand_cov['coverage_pct']:>5}%",
            file=sys.stderr,
        )

    return cage_results


# ============================================================
# Phase 6: Compilation latency
# ============================================================

def run_latency_benchmark(store: MemoryStore) -> dict[str, Any]:
    """Measure compilation latency at budget=2000 over 20 reps."""
    times_ms: list[float] = []
    for _ in range(LATENCY_REPS):
        t0: float = time.perf_counter()
        _packed: list[tuple[Belief, str, float]] = compile_context(
            store, COMPILATION_QUERIES, LATENCY_BUDGET
        )
        elapsed_ms: float = (time.perf_counter() - t0) * 1000.0
        times_ms.append(elapsed_ms)

    times_ms.sort()
    p50_idx: int = len(times_ms) // 2
    p95_idx: int = int(len(times_ms) * 0.95)

    return {
        "budget": LATENCY_BUDGET,
        "reps": LATENCY_REPS,
        "p50_ms": round(times_ms[p50_idx], 1),
        "p95_ms": round(times_ms[min(p95_idx, len(times_ms) - 1)], 1),
        "min_ms": round(times_ms[0], 1),
        "max_ms": round(times_ms[-1], 1),
        "mean_ms": round(sum(times_ms) / len(times_ms), 1),
    }


# ============================================================
# Main
# ============================================================

def main() -> None:
    print("Exp 64: Query-Aware Pre-Prompt Compilation", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    store: MemoryStore = MemoryStore(PRODUCTION_DB)
    all_beliefs: list[Belief] = load_all_beliefs(store)
    print(f"Loaded {len(all_beliefs)} active beliefs", file=sys.stderr)

    type_dist: dict[str, int] = type_distribution(all_beliefs)
    print(f"Type distribution: {type_dist}", file=sys.stderr)

    # Phase 2 & 3: Compilation + coverage
    print("\n--- Phase 2-3: Compilation sweep ---", file=sys.stderr)
    compilation: list[dict[str, Any]] = run_compilation_sweep(store)

    # Phase 4: Baselines
    print("\n--- Phase 4: Baseline comparison ---", file=sys.stderr)
    baselines: list[dict[str, Any]] = run_baselines(store, all_beliefs, compilation)

    # Phase 5: Cage detection
    print("\n--- Phase 5: Cage detection ---", file=sys.stderr)
    cage: list[dict[str, Any]] = run_cage_detection(store)

    # Phase 6: Latency
    print("\n--- Phase 6: Compilation latency ---", file=sys.stderr)
    latency: dict[str, Any] = run_latency_benchmark(store)
    print(
        f"  p50={latency['p50_ms']:.1f}ms  p95={latency['p95_ms']:.1f}ms  "
        f"mean={latency['mean_ms']:.1f}ms",
        file=sys.stderr,
    )

    # Summary
    print("\n--- Summary ---", file=sys.stderr)
    for comp in compilation:
        budget: int = comp["budget"]
        cov: float = comp["coverage"]["coverage_pct"]
        bl: dict[str, Any] | None = None
        for b in baselines:
            if b["budget"] == budget:
                bl = b
                break
        rand_str: str = ""
        type_str: str = ""
        if bl is not None:
            rand_str = f"  random={bl['random_baseline']['mean_coverage_pct']}%"
            type_str = f"  type_filt={bl['type_filtered_baseline']['coverage']['coverage_pct']}%"
        print(
            f"  budget={budget:>5}  compiled={cov:>5}%{rand_str}{type_str}",
            file=sys.stderr,
        )

    cage_drop: bool = False
    if len(cage) >= 2:
        max_union: float = max(c["union_coverage_pct"] for c in cage)
        for c in cage:
            if c["union_coverage_pct"] < max_union - 5.0:
                cage_drop = True
                break
    print(f"\n  Cage detected: {cage_drop}", file=sys.stderr)

    # Write results
    results: dict[str, Any] = {
        "experiment": "exp64_preprompt_compilation",
        "timestamp": _now_iso(),
        "total_beliefs": len(all_beliefs),
        "type_distribution": type_dist,
        "compilation_sweep": compilation,
        "baselines": baselines,
        "cage_detection": cage,
        "cage_detected": cage_drop,
        "latency": latency,
    }

    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to {RESULTS_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
