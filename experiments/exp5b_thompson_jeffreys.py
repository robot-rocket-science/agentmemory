from __future__ import annotations

"""
Experiment 5b: Thompson Sampling with Jeffreys Prior and Fixed Entropy Threshold

Tests two refinements to the Exp 5 Thompson sampling result:
1. Jeffreys prior Beta(0.5, 0.5) vs uniform Beta(1, 1) -- wider prior = more exploration
2. Fixed entropy threshold (0.69 nats) vs median-relative -- stable measurement

Also proposes an alternative to REQ-010: convergence criterion instead of
exploration fraction.

Protocol: EXPERIMENTS.md, Experiment 5b
"""

import json
import sys
from typing import Any

import numpy as np
from scipy.stats import beta as beta_dist  # type: ignore[import-untyped]

from experiments.exp2_bayesian_calibration import (
    ExperimentConfig,
    Belief,
    compute_calibration,
    compute_rank_correlation,
)


def compute_beta_entropy_scipy(a: float, b: float) -> float:
    """Use scipy for the reference values (our _digamma approximation has edge cases at small a,b)."""
    result: Any = beta_dist.entropy(a, b)  # type: ignore[no-untyped-call]
    return float(result)


# Compute the actual threshold values using scipy (accurate)
ENTROPY_BETA_1_1: float = compute_beta_entropy_scipy(1.0, 1.0)
ENTROPY_BETA_05_05: float = compute_beta_entropy_scipy(0.5, 0.5)


def create_beliefs(config: ExperimentConfig, alpha_init: float, beta_init: float) -> list[Belief]:
    beliefs: list[Belief] = []
    bid = 0
    sources: list[tuple[str, int, float]] = [
        ("user_stated", config.n_user_stated, config.true_rate_user),
        ("document", config.n_document, config.true_rate_document),
        ("agent_inferred", config.n_agent_inferred, config.true_rate_agent),
        ("cross_reference", config.n_cross_reference, config.true_rate_cross_ref),
    ]
    for source_type, count, true_rate in sources:
        for _ in range(count):
            beliefs.append(Belief(
                id=bid, source_type=source_type,
                true_usefulness_rate=true_rate,
                alpha=alpha_init, beta_param=beta_init,
            ))
            bid += 1
    return beliefs


def run_thompson_trial(
    config: ExperimentConfig,
    alpha_init: float,
    beta_init: float,
    entropy_threshold: float | None,  # None = median-relative, float = fixed
    rng: np.random.Generator,
) -> dict[str, Any]:
    beliefs = create_beliefs(config, alpha_init, beta_init)

    exploration_count = 0
    total_count = 0
    # Track per-session metrics for convergence-over-time analysis
    session_snapshots: list[dict[str, int | float]] = []

    for session in range(config.n_sessions):
        if entropy_threshold is None:
            # Median-relative (original, flawed)
            current_threshold = float(np.median([b.entropy for b in beliefs]))
        else:
            current_threshold = entropy_threshold

        for _ in range(config.n_retrievals_per_session):
            samples: list[tuple[Belief, float]] = []
            for b in beliefs:
                s = float(rng.beta(max(b.alpha, 0.01), max(b.beta_param, 0.01)))
                samples.append((b, s))

            samples.sort(key=lambda x: x[1], reverse=True)
            retrieved: list[Belief] = [b for b, _ in samples[:config.n_beliefs_per_retrieval]]

            for b in retrieved:
                total_count += 1
                if b.entropy > current_threshold:
                    exploration_count += 1

                b.retrieval_count += 1
                if rng.random() < 0.30:
                    b.update("ignored")
                elif rng.random() < b.true_usefulness_rate:
                    b.update("used")
                else:
                    b.update("harmful")

        # Snapshot at certain sessions
        if session + 1 in [5, 10, 20, 50]:
            tested = [b for b in beliefs if b.retrieval_count > 0]
            converged_010 = sum(1 for b in tested if abs(b.confidence - b.true_usefulness_rate) <= 0.10)
            converged_015 = sum(1 for b in tested if abs(b.confidence - b.true_usefulness_rate) <= 0.15)
            session_snapshots.append({
                "session": session + 1,
                "tested": len(tested),
                "converged_010": converged_010,
                "converged_015": converged_015,
                "convergence_rate_010": round(converged_010 / len(tested), 4) if tested else 0,
                "convergence_rate_015": round(converged_015 / len(tested), 4) if tested else 0,
            })

    cal = compute_calibration(beliefs)
    rank = compute_rank_correlation(beliefs)
    tested = [b for b in beliefs if b.retrieval_count > 0]
    unique_tested = len(tested)

    return {
        "ece": cal["ece"],
        "exploration_fraction": round(exploration_count / total_count, 4) if total_count > 0 else 0,
        "rank_correlation": rank,
        "beliefs_tested": unique_tested,
        "convergence_snapshots": session_snapshots,
    }


def main() -> None:
    config = ExperimentConfig(n_trials=100)
    rng_base = np.random.default_rng(config.seed)

    print("=" * 60, file=sys.stderr)
    print("Experiment 5b: Thompson + Jeffreys + Fixed Entropy", file=sys.stderr)
    print(f"  Entropy of Beta(1,1):   {ENTROPY_BETA_1_1:.4f} nats", file=sys.stderr)
    print(f"  Entropy of Beta(0.5,0.5): {ENTROPY_BETA_05_05:.4f} nats", file=sys.stderr)
    print(f"  {config.n_trials} trials per condition", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    conditions: dict[str, tuple[float, float, float | None]] = {
        "thompson_uniform_median": (1.0, 1.0, None),          # Exp 5 original
        "thompson_uniform_fixed": (1.0, 1.0, ENTROPY_BETA_1_1),  # Fix metric only
        "thompson_jeffreys_median": (0.5, 0.5, None),         # Fix prior only
        "thompson_jeffreys_fixed": (0.5, 0.5, ENTROPY_BETA_1_1), # Fix both
    }

    all_results: dict[str, dict[str, Any]] = {}

    for cond_name, (alpha, beta_val, threshold) in conditions.items():
        print(f"\nRunning {cond_name} (a={alpha}, b={beta_val}, "
              f"thresh={'median' if threshold is None else f'{threshold:.4f}'})...",
              file=sys.stderr)

        trial_data: list[dict[str, Any]] = []
        for trial in range(config.n_trials):
            seed: int = int(cast_int(rng_base.integers(0, 2**32)))
            rng = np.random.default_rng(seed)
            result = run_thompson_trial(config, alpha, beta_val, threshold, rng)
            trial_data.append(result)

            if (trial + 1) % 25 == 0:
                print(f"  Trial {trial + 1}/{config.n_trials}", file=sys.stderr)

        eces: list[float] = [t["ece"] for t in trial_data]
        expls: list[float] = [t["exploration_fraction"] for t in trial_data]
        ranks: list[float] = [t["rank_correlation"] for t in trial_data if not np.isnan(t.get("rank_correlation", float("nan")))]
        tested: list[int] = [t["beliefs_tested"] for t in trial_data]

        # Convergence at session 50
        conv_010_50: list[float] = [t["convergence_snapshots"][-1]["convergence_rate_010"]
                       for t in trial_data if t["convergence_snapshots"]]
        conv_015_50: list[float] = [t["convergence_snapshots"][-1]["convergence_rate_015"]
                       for t in trial_data if t["convergence_snapshots"]]

        # Convergence at session 10 (early)
        conv_015_10: list[float] = [t["convergence_snapshots"][1]["convergence_rate_015"]
                       for t in trial_data
                       if len(t["convergence_snapshots"]) > 1]

        summary: dict[str, Any] = {
            "ece_mean": round(float(np.mean(eces)), 4),
            "ece_std": round(float(np.std(eces)), 4),
            "ece_p5": round(float(np.percentile(eces, 5)), 4),
            "ece_p95": round(float(np.percentile(eces, 95)), 4),
            "exploration_mean": round(float(np.mean(expls)), 4),
            "exploration_std": round(float(np.std(expls)), 4),
            "rank_corr_mean": round(float(np.nanmean(ranks)), 4) if ranks else float("nan"),
            "beliefs_tested_mean": round(float(np.mean(tested)), 1),
            "convergence_010_session50": round(float(np.mean(conv_010_50)), 4) if conv_010_50 else None,
            "convergence_015_session50": round(float(np.mean(conv_015_50)), 4) if conv_015_50 else None,
            "convergence_015_session10": round(float(np.mean(conv_015_10)), 4) if conv_015_10 else None,
            "req009_pass": float(np.mean(eces)) < 0.10,
            "req010_pass": 0.15 <= float(np.mean(expls)) <= 0.50,
            "both_pass": float(np.mean(eces)) < 0.10 and 0.15 <= float(np.mean(expls)) <= 0.50,
        }

        all_results[cond_name] = summary

        status = "PASS BOTH" if summary["both_pass"] else (
            "ECE only" if summary["req009_pass"] else (
                "Expl only" if summary["req010_pass"] else "FAIL"
            )
        )
        print(f"  {cond_name}: ECE={summary['ece_mean']:.4f} "
              f"expl={summary['exploration_mean']:.4f} "
              f"conv@50(0.15)={summary['convergence_015_session50']} "
              f"tested={summary['beliefs_tested_mean']:.0f} "
              f"[{status}]", file=sys.stderr)

    # Summary
    print("\n" + "=" * 60, file=sys.stderr)
    print("RESULTS", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"{'Condition':<30} {'ECE':>7} {'Expl':>7} {'Conv@50':>8} {'Tested':>7} {'Status':<12}",
          file=sys.stderr)
    print("-" * 80, file=sys.stderr)

    for name, s in all_results.items():
        status = "PASS BOTH" if s["both_pass"] else (
            "ECE only" if s["req009_pass"] else (
                "Expl only" if s["req010_pass"] else "FAIL"
            )
        )
        conv_val: float = s['convergence_015_session50'] if s['convergence_015_session50'] is not None else 0.0
        print(f"{name:<30} {s['ece_mean']:>7.4f} {s['exploration_mean']:>7.4f} "
              f"{conv_val:>8.4f} "
              f"{s['beliefs_tested_mean']:>7.0f} {status:<12}", file=sys.stderr)

    # Proposed REQ-010 revision analysis
    print("\n--- PROPOSED REQ-010 REVISION ---", file=sys.stderr)
    print("Current: exploration fraction >= 0.15", file=sys.stderr)
    print("Proposed: convergence rate (within 0.15 of true rate) >= 0.60 by session 50", file=sys.stderr)
    for name, s in all_results.items():
        conv: float = s["convergence_015_session50"] if s["convergence_015_session50"] is not None else 0.0
        passes = conv >= 0.60
        print(f"  {name}: convergence={conv:.4f} -> {'PASS' if passes else 'FAIL'}", file=sys.stderr)

    print(json.dumps(all_results, indent=2))


def cast_int(val: Any) -> int:
    return int(val)


if __name__ == "__main__":
    main()
