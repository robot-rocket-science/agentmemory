from __future__ import annotations

"""
Experiment 22: Hierarchical Confidence as Scaling Solution

Exp 15 showed Thompson sampling degrades at 10K beliefs (ECE 0.06->0.17,
coverage 100%->22%). The feedback loop can't test every belief individually.

Hypothesis: instead of Bayesian confidence on individual beliefs, assign
confidence to SUBGRAPHS rooted at anchor nodes. When an anchor is retrieved
and used successfully, all beliefs in its subgraph get a partial confidence
boost. This propagates feedback through the graph structure.

Compare:
  A. Flat Thompson (baseline from Exp 15): individual belief confidence
  B. Hierarchical: anchor confidence propagates to subgraph members
  C. Temporal decay + flat Thompson: stale beliefs have lower scores

Test at 1K, 5K, 10K beliefs.
"""

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from experiments.exp2_bayesian_calibration import Belief, compute_calibration


N_SESSIONS = 50
N_TRIALS = 10
SCALES = [1_000, 5_000, 10_000]
DOMAINS = ["database", "frontend", "deployment", "strategy", "testing",
           "security", "performance", "documentation", "devops", "research"]
TRUE_RATES: dict[str, float] = {d: 0.4 + 0.05 * i for i, d in enumerate(DOMAINS)}


def create_beliefs_with_anchors(n: int) -> tuple[list[Belief], dict[int, list[int]]]:
    """Create beliefs organized into subgraphs around anchor nodes."""
    beliefs: list[Belief] = []
    # Every 50th belief is an anchor; the surrounding 49 are its subgraph
    anchor_subgraph: dict[int, list[int]] = {}  # anchor_idx -> [member_indices]

    for i in range(n):
        domain = DOMAINS[i % len(DOMAINS)]
        beliefs.append(Belief(
            id=i,
            source_type=domain,
            true_usefulness_rate=TRUE_RATES[domain],
            alpha=0.5,
            beta_param=0.5,
        ))

        if i % 50 == 0:
            anchor_subgraph[i] = []
        else:
            anchor_idx = (i // 50) * 50
            if anchor_idx in anchor_subgraph:
                anchor_subgraph[anchor_idx].append(i)

    return beliefs, anchor_subgraph


def run_flat(n: int, rng: np.random.Generator) -> dict[str, Any]:
    """Baseline: flat Thompson sampling (from Exp 15)."""
    beliefs, _ = create_beliefs_with_anchors(n)

    for _ in range(N_SESSIONS):
        for _ in range(10):
            samples = np.array([rng.beta(max(b.alpha, 0.01), max(b.beta_param, 0.01)) for b in beliefs])
            top_k = np.argpartition(samples, -5)[-5:]
            for idx_np in top_k:
                idx = int(idx_np)
                beliefs[idx].retrieval_count += 1
                if rng.random() < 0.30:
                    beliefs[idx].update("ignored")
                elif rng.random() < beliefs[idx].true_usefulness_rate:
                    beliefs[idx].update("used")
                else:
                    beliefs[idx].update("harmful")

    cal: dict[str, Any] = compute_calibration(beliefs)
    tested = sum(1 for b in beliefs if b.retrieval_count > 0)
    return {"ece": cal["ece"], "coverage": round(tested / n, 4), "method": "flat"}


def run_hierarchical(n: int, rng: np.random.Generator) -> dict[str, Any]:
    """Hierarchical: anchor confidence propagates to subgraph."""
    beliefs, anchor_subgraph = create_beliefs_with_anchors(n)
    propagation_weight = 0.3  # subgraph members get 30% of anchor's update

    for _ in range(N_SESSIONS):
        for _ in range(10):
            # Thompson sample on all beliefs
            samples = np.array([rng.beta(max(b.alpha, 0.01), max(b.beta_param, 0.01)) for b in beliefs])
            top_k = np.argpartition(samples, -5)[-5:]

            for idx_np in top_k:
                idx = int(idx_np)
                b = beliefs[idx]
                b.retrieval_count += 1

                if rng.random() < 0.30:
                    outcome = "ignored"
                elif rng.random() < b.true_usefulness_rate:
                    outcome = "used"
                else:
                    outcome = "harmful"

                b.update(outcome)

                # Propagate to subgraph if this is an anchor
                if idx in anchor_subgraph and outcome != "ignored":
                    for member_idx in anchor_subgraph[idx]:
                        member = beliefs[member_idx]
                        if outcome == "used":
                            member.alpha += propagation_weight
                        else:
                            member.beta_param += propagation_weight
                        member.retrieval_count += 1  # count as indirectly tested

    cal: dict[str, Any] = compute_calibration(beliefs)
    tested = sum(1 for b in beliefs if b.retrieval_count > 0)
    return {"ece": cal["ece"], "coverage": round(tested / n, 4), "method": "hierarchical"}


def run_temporal_decay(n: int, rng: np.random.Generator) -> dict[str, Any]:
    """Temporal decay: older beliefs score lower, reducing effective pool."""
    beliefs, _ = create_beliefs_with_anchors(n)
    creation_session = np.zeros(n)  # when each belief was "created"
    # Simulate staggered creation: older beliefs created earlier
    for i in range(n):
        creation_session[i] = (i / n) * N_SESSIONS * 0.5  # spread across first half

    for session in range(N_SESSIONS):
        for _ in range(10):
            # Thompson sample with temporal decay
            samples_list: list[float] = []
            for i, b in enumerate(beliefs):
                s = rng.beta(max(b.alpha, 0.01), max(b.beta_param, 0.01))
                age = session - creation_session[i]
                decay = float(np.exp(-0.02 * max(0, age)))  # half-life ~35 sessions
                samples_list.append(float(s) * decay)

            samples = np.array(samples_list)
            top_k = np.argpartition(samples, -5)[-5:]

            for idx_np in top_k:
                idx = int(idx_np)
                beliefs[idx].retrieval_count += 1
                if rng.random() < 0.30:
                    beliefs[idx].update("ignored")
                elif rng.random() < beliefs[idx].true_usefulness_rate:
                    beliefs[idx].update("used")
                else:
                    beliefs[idx].update("harmful")

    cal: dict[str, Any] = compute_calibration(beliefs)
    tested = sum(1 for b in beliefs if b.retrieval_count > 0)
    return {"ece": cal["ece"], "coverage": round(tested / n, 4), "method": "temporal_decay"}


def main() -> None:
    rng_base = np.random.default_rng(42)

    print("=" * 60, file=sys.stderr)
    print("Experiment 22: Hierarchical Confidence at Scale", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    results: dict[int, dict[str, dict[str, float]]] = {}
    methods: list[tuple[str, Callable[[int, np.random.Generator], dict[str, Any]]]] = [
        ("flat", run_flat), ("hierarchical", run_hierarchical), ("temporal_decay", run_temporal_decay),
    ]

    for scale in SCALES:
        results[scale] = {}
        for method_name, method_fn in methods:
            eces: list[float] = []
            coverages: list[float] = []
            for _ in range(N_TRIALS):
                seed = int(rng_base.integers(0, 2**32))  # type: ignore[reportUnknownArgumentType]
                r: dict[str, Any] = method_fn(scale, np.random.default_rng(seed))
                eces.append(r["ece"])
                coverages.append(r["coverage"])

            results[scale][method_name] = {
                "ece_mean": round(float(np.mean(eces)), 4),
                "coverage_mean": round(float(np.mean(coverages)), 4),
            }
            print(f"  {scale:>6,} {method_name:<15} ECE={np.mean(eces):.4f} "
                  f"coverage={np.mean(coverages):.0%}", file=sys.stderr)

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"{'Scale':>8} {'Method':<15} {'ECE':>8} {'Coverage':>10}", file=sys.stderr)
    print("-" * 45, file=sys.stderr)
    for scale in SCALES:
        for method in ["flat", "hierarchical", "temporal_decay"]:
            r2 = results[scale][method]
            print(f"{scale:>8,} {method:<15} {r2['ece_mean']:>8.4f} {r2['coverage_mean']:>10.0%}", file=sys.stderr)
        print(file=sys.stderr)

    Path("experiments/exp22_results.json").write_text(json.dumps(results, indent=2, default=str))
    print(f"Output: experiments/exp22_results.json", file=sys.stderr)


if __name__ == "__main__":
    main()
