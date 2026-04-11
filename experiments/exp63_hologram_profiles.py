"""Experiment 63: Type-Weight Profiles (Hologram Profiles).

Tests whether different type-weight profiles produce measurably different
retrieval results. A "profile" is a dict of belief_type -> weight multiplier
applied on top of score_belief().

Phase 1: Define profiles
Phase 2: Measure retrieval divergence (Jaccard) and ground-truth coverage
Phase 3: Serialization round-trip and load-time benchmarks
Phase 4: Dynamic shaping simulation (sensitivity to new beliefs)

Follows from Exp 62, which rejected global-ranked frozen subgraphs.
"""
from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from agentmemory.models import Belief
from agentmemory.scoring import score_belief
from agentmemory.store import MemoryStore

# ============================================================
# Config
# ============================================================

PRODUCTION_DB: Final[Path] = Path.home() / ".agentmemory" / "memory.db"
RESULTS_PATH: Final[Path] = Path(__file__).parent / "exp63_results.json"
SEED: Final[int] = 42
TOP_K: Final[int] = 30

# Ground truth topics (same as Exp 62)
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

# ============================================================
# Profile definitions
# ============================================================

Profile = dict[str, float]

PROFILES: dict[str, Profile] = {
    "strict_reviewer": {
        "correction": 3.0,
        "requirement": 3.0,
        "factual": 0.5,
        "preference": 1.0,
        "procedural": 0.5,
        "causal": 0.5,
        "relational": 0.5,
    },
    "explorer": {
        "factual": 2.0,
        "preference": 2.0,
        "correction": 0.5,
        "requirement": 0.5,
        "procedural": 2.0,
        "causal": 2.0,
        "relational": 2.0,
    },
    "balanced": {
        "factual": 1.0,
        "preference": 1.0,
        "correction": 1.0,
        "requirement": 1.0,
        "procedural": 1.0,
        "causal": 1.0,
        "relational": 1.0,
    },
}


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


def score_with_profile(
    beliefs: list[Belief],
    query: str,
    profile: Profile,
    current_time: str,
    seed: int = SEED,
) -> list[tuple[Belief, float]]:
    """Score beliefs using score_belief() multiplied by profile type weights.

    Returns sorted list of (belief, weighted_score) pairs, descending.
    """
    random.seed(seed)
    scored: list[tuple[Belief, float]] = []
    for b in beliefs:
        base_score: float = score_belief(b, query, current_time)
        type_weight: float = profile.get(b.belief_type, 1.0)
        scored.append((b, base_score * type_weight))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def top_k_ids(scored: list[tuple[Belief, float]], k: int = TOP_K) -> set[str]:
    """Extract the top-k belief IDs from a scored list."""
    return {b.id for b, _ in scored[:k]}


def jaccard_distance(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard distance = 1 - |intersection| / |union|."""
    if not set_a and not set_b:
        return 0.0
    union_size: int = len(set_a | set_b)
    if union_size == 0:
        return 0.0
    return 1.0 - len(set_a & set_b) / union_size


def measure_coverage(
    scored: list[tuple[Belief, float]],
    needed_substrings: list[str],
    k: int = TOP_K,
) -> dict[str, Any]:
    """Check how many needed substrings appear in the top-k results."""
    top_text: str = " ".join(b.content for b, _ in scored[:k]).lower()
    found: list[str] = []
    missing: list[str] = []
    for sub in needed_substrings:
        if sub.lower() in top_text:
            found.append(sub)
        else:
            missing.append(sub)
    coverage: float = len(found) / len(needed_substrings) if needed_substrings else 1.0
    return {
        "found": found,
        "missing": missing,
        "coverage": coverage,
    }


# ============================================================
# Phase 2: Retrieval divergence
# ============================================================

def phase2_retrieval_divergence(
    all_beliefs: list[Belief],
) -> dict[str, Any]:
    """Measure Jaccard distance and coverage for each profile x topic."""
    print("\n=== Phase 2: Retrieval Divergence ===", file=sys.stderr)
    current_time: str = _now_iso()

    profile_names: list[str] = sorted(PROFILES.keys())
    pairs: list[tuple[str, str]] = [
        (profile_names[i], profile_names[j])
        for i in range(len(profile_names))
        for j in range(i + 1, len(profile_names))
    ]

    # Per-topic results
    per_topic: dict[str, dict[str, Any]] = {}

    # Per-profile top-k sets keyed by (profile, topic)
    top_sets: dict[tuple[str, str], set[str]] = {}
    coverage_data: dict[tuple[str, str], dict[str, Any]] = {}

    for topic_name, topic_data in TOPICS.items():
        query: str = topic_data["query"]
        needed: list[str] = topic_data["needed_substrings"]

        topic_result: dict[str, Any] = {"query": query, "profiles": {}, "jaccard": {}}

        for pname in profile_names:
            scored: list[tuple[Belief, float]] = score_with_profile(
                all_beliefs, query, PROFILES[pname], current_time,
            )
            ids: set[str] = top_k_ids(scored)
            top_sets[(pname, topic_name)] = ids
            cov: dict[str, Any] = measure_coverage(scored, needed)
            coverage_data[(pname, topic_name)] = cov

            # Top-5 scores for diagnostics
            top5_scores: list[float] = [s for _, s in scored[:5]]

            topic_result["profiles"][pname] = {
                "coverage": cov["coverage"],
                "found": cov["found"],
                "missing": cov["missing"],
                "top5_scores": top5_scores,
            }

        # Jaccard distances between profile pairs
        for pa, pb in pairs:
            jd: float = jaccard_distance(
                top_sets[(pa, topic_name)],
                top_sets[(pb, topic_name)],
            )
            pair_key: str = f"{pa}_vs_{pb}"
            topic_result["jaccard"][pair_key] = round(jd, 4)

        per_topic[topic_name] = topic_result
        print(f"  {topic_name}:", file=sys.stderr)
        for pname in profile_names:
            cov_val: float = coverage_data[(pname, topic_name)]["coverage"]
            print(f"    {pname}: coverage={cov_val:.0%}", file=sys.stderr)
        for pa, pb in pairs:
            jd_val: float = topic_result["jaccard"][f"{pa}_vs_{pb}"]
            print(f"    Jaccard({pa} vs {pb})={jd_val:.3f}", file=sys.stderr)

    # Aggregate Jaccard across topics
    agg_jaccard: dict[str, dict[str, float]] = {}
    for pa, pb in pairs:
        pair_key = f"{pa}_vs_{pb}"
        vals: list[float] = [
            per_topic[t]["jaccard"][pair_key] for t in TOPICS
        ]
        agg_jaccard[pair_key] = {
            "mean": sum(vals) / len(vals),
            "min": min(vals),
            "max": max(vals),
        }

    # Aggregate coverage per profile
    agg_coverage: dict[str, dict[str, float]] = {}
    for pname in profile_names:
        covs: list[float] = [
            coverage_data[(pname, t)]["coverage"] for t in TOPICS
        ]
        agg_coverage[pname] = {
            "mean": sum(covs) / len(covs),
            "min": min(covs),
            "max": max(covs),
        }

    print("\n  Aggregate Jaccard distances:", file=sys.stderr)
    for pair_key, vals_dict in agg_jaccard.items():
        print(
            f"    {pair_key}: mean={vals_dict['mean']:.3f} "
            f"[{vals_dict['min']:.3f}, {vals_dict['max']:.3f}]",
            file=sys.stderr,
        )
    print("  Aggregate coverage:", file=sys.stderr)
    for pname, vals_dict in agg_coverage.items():
        print(
            f"    {pname}: mean={vals_dict['mean']:.1%} "
            f"[{vals_dict['min']:.0%}, {vals_dict['max']:.0%}]",
            file=sys.stderr,
        )

    return {
        "per_topic": per_topic,
        "aggregate_jaccard": agg_jaccard,
        "aggregate_coverage": agg_coverage,
    }


# ============================================================
# Phase 3: Serialization round-trip
# ============================================================

def phase3_serialization(
    all_beliefs: list[Belief],
) -> dict[str, Any]:
    """Serialize profiles to JSON, read back, verify identical retrieval."""
    print("\n=== Phase 3: Serialization Round-Trip ===", file=sys.stderr)
    current_time: str = _now_iso()
    tmp_file: Path = Path(__file__).parent / "_exp63_profile_tmp.json"

    results: dict[str, Any] = {}

    for pname, profile in PROFILES.items():
        # Serialize
        payload: dict[str, Any] = {
            "name": pname,
            "type_weights": profile,
        }
        tmp_file.write_text(json.dumps(payload, indent=2) + "\n")

        # Read back
        loaded: dict[str, Any] = json.loads(tmp_file.read_text())
        loaded_profile: Profile = loaded["type_weights"]

        # Verify identical retrieval on first topic
        test_query: str = list(TOPICS.values())[0]["query"]

        original_scored: list[tuple[Belief, float]] = score_with_profile(
            all_beliefs, test_query, profile, current_time,
        )
        loaded_scored: list[tuple[Belief, float]] = score_with_profile(
            all_beliefs, test_query, loaded_profile, current_time,
        )

        original_ids: set[str] = top_k_ids(original_scored)
        loaded_ids: set[str] = top_k_ids(loaded_scored)
        match: bool = original_ids == loaded_ids

        results[pname] = {
            "serialized_bytes": len(json.dumps(payload).encode()),
            "round_trip_match": match,
        }
        print(
            f"  {pname}: round-trip match={match}, "
            f"size={results[pname]['serialized_bytes']}B",
            file=sys.stderr,
        )

    # Load time benchmark (20 reps)
    reps: int = 20
    load_times: list[float] = []
    for _ in range(reps):
        t0: float = time.perf_counter()
        raw: str = tmp_file.read_text()
        parsed: dict[str, Any] = json.loads(raw)
        _ = parsed["type_weights"]  # type: ignore[assignment]
        elapsed: float = (time.perf_counter() - t0) * 1000.0  # ms
        load_times.append(elapsed)

    load_times.sort()
    p50_idx: int = len(load_times) // 2
    p95_idx: int = int(len(load_times) * 0.95)
    p50: float = load_times[p50_idx]
    p95: float = load_times[min(p95_idx, len(load_times) - 1)]

    results["load_time_ms"] = {
        "reps": reps,
        "p50": round(p50, 4),
        "p95": round(p95, 4),
    }
    print(
        f"  Load time ({reps} reps): p50={p50:.4f}ms, p95={p95:.4f}ms",
        file=sys.stderr,
    )

    # Cleanup
    tmp_file.unlink(missing_ok=True)

    return results


# ============================================================
# Phase 4: Dynamic shaping simulation
# ============================================================

def phase4_dynamic_shaping(
    all_beliefs: list[Belief],
) -> dict[str, Any]:
    """Simulate adding correction beliefs and measure top-30 drift under Profile A."""
    print("\n=== Phase 4: Dynamic Shaping Simulation ===", file=sys.stderr)
    current_time: str = _now_iso()
    profile_a: Profile = PROFILES["strict_reviewer"]
    test_query: str = list(TOPICS.values())[0]["query"]

    # Baseline top-30
    baseline_scored: list[tuple[Belief, float]] = score_with_profile(
        all_beliefs, test_query, profile_a, current_time,
    )
    baseline_ids: set[str] = top_k_ids(baseline_scored)

    # Add 20 synthetic correction beliefs one at a time
    drift_curve: list[dict[str, Any]] = []
    synthetic_beliefs: list[Belief] = []

    for i in range(20):
        content: str = (
            f"Correction #{i+1}: the scanner module should prefer "
            f"extraction variant {i+1} for signal detection in onboarding."
        )
        content_hash: str = hashlib.sha256(content.encode()).hexdigest()[:12]
        synth_id: str = f"synth_{i:04d}"
        b: Belief = Belief(
            id=synth_id,
            content_hash=content_hash,
            content=content,
            belief_type="correction",
            alpha=0.5,
            beta_param=0.5,
            confidence=0.5,
            source_type="user_corrected",
            locked=False,
            valid_from=current_time,
            valid_to=None,
            superseded_by=None,
            created_at=current_time,
            updated_at=current_time,
        )
        synthetic_beliefs.append(b)

        # Score with augmented belief list
        augmented: list[Belief] = all_beliefs + synthetic_beliefs
        scored: list[tuple[Belief, float]] = score_with_profile(
            augmented, test_query, profile_a, current_time,
        )
        new_ids: set[str] = top_k_ids(scored)

        jd: float = jaccard_distance(baseline_ids, new_ids)
        synth_in_top: int = sum(1 for sid in new_ids if sid.startswith("synth_"))

        drift_curve.append({
            "added": i + 1,
            "jaccard_from_baseline": round(jd, 4),
            "synthetic_in_top30": synth_in_top,
        })
        print(
            f"  +{i+1} corrections: Jaccard={jd:.3f}, "
            f"synthetic_in_top30={synth_in_top}",
            file=sys.stderr,
        )

    return {
        "profile": "strict_reviewer",
        "query": test_query,
        "baseline_top30_count": len(baseline_ids),
        "drift_curve": drift_curve,
    }


# ============================================================
# Main
# ============================================================

def main() -> None:
    random.seed(SEED)

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

    t0: float = time.monotonic()

    # Phase 1: profiles defined above (no runtime work)
    print("\n=== Phase 1: Profile Definitions ===", file=sys.stderr)
    for pname, profile in PROFILES.items():
        print(f"  {pname}: {profile}", file=sys.stderr)

    # Phase 2: retrieval divergence
    phase2_results: dict[str, Any] = phase2_retrieval_divergence(all_beliefs)

    # Phase 3: serialization
    phase3_results: dict[str, Any] = phase3_serialization(all_beliefs)

    # Phase 4: dynamic shaping
    phase4_results: dict[str, Any] = phase4_dynamic_shaping(all_beliefs)

    elapsed: float = time.monotonic() - t0

    # Assemble results
    output: dict[str, Any] = {
        "experiment": "exp63_hologram_profiles",
        "config": {
            "db_path": str(PRODUCTION_DB),
            "total_beliefs": len(all_beliefs),
            "type_distribution": type_dist,
            "seed": SEED,
            "top_k": TOP_K,
            "profiles": {k: v for k, v in PROFILES.items()},
            "topics": {k: v["query"] for k, v in TOPICS.items()},
        },
        "phase2_retrieval_divergence": phase2_results,
        "phase3_serialization": phase3_results,
        "phase4_dynamic_shaping": phase4_results,
        "elapsed_seconds": round(elapsed, 2),
    }

    RESULTS_PATH.write_text(json.dumps(output, indent=2) + "\n")
    print(f"\nResults written to {RESULTS_PATH}", file=sys.stderr)
    print(f"Total time: {elapsed:.1f}s", file=sys.stderr)

    # Summary
    print("\n=== SUMMARY ===", file=sys.stderr)
    print("Profile divergence (mean Jaccard across topics):", file=sys.stderr)
    for pair_key, vals in phase2_results["aggregate_jaccard"].items():
        print(f"  {pair_key}: {vals['mean']:.3f}", file=sys.stderr)
    print("Profile coverage (mean across topics):", file=sys.stderr)
    for pname, vals in phase2_results["aggregate_coverage"].items():
        print(f"  {pname}: {vals['mean']:.1%}", file=sys.stderr)
    print("Dynamic shaping (final state after +20 corrections):", file=sys.stderr)
    final: dict[str, Any] = phase4_results["drift_curve"][-1]
    print(
        f"  Jaccard from baseline: {final['jaccard_from_baseline']:.3f}",
        file=sys.stderr,
    )
    print(
        f"  Synthetic in top-30: {final['synthetic_in_top30']}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
