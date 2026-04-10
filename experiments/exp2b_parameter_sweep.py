from __future__ import annotations

"""
Experiment 2b: Parameter sweep to find working Bayesian configuration.

Exp 2 showed: source-informed priors are too strong (ECE=0.37), exploration
weight too low (0% exploration). This sweep tests ranges of prior strengths
and exploration weights to find configurations that pass REQ-009 and REQ-010.
"""

import json
import sys
from typing import Any

import numpy as np

from experiments.exp2_bayesian_calibration import (
    ExperimentConfig,
    compute_calibration,
    compute_convergence,
    compute_exploration,
    compute_rank_correlation,
    Belief,
)


def create_beliefs_with_params(
    config: ExperimentConfig,
    prior_strength: float,
) -> list[Belief]:
    """Create beliefs where source priors have given total strength (alpha+beta)."""
    beliefs: list[Belief] = []
    bid = 0

    # Source configs: (type, count, true_rate, confidence_ratio)
    # confidence_ratio is what fraction of prior_strength goes to alpha
    sources: list[tuple[str, int, float, float]] = [
        ("user_stated", config.n_user_stated, config.true_rate_user, 0.9),
        ("document", config.n_document, config.true_rate_document, 0.7),
        ("agent_inferred", config.n_agent_inferred, config.true_rate_agent, 0.5),
        ("cross_reference", config.n_cross_reference, config.true_rate_cross_ref, 0.6),
    ]

    for source_type, count, true_rate, conf_ratio in sources:
        alpha = prior_strength * conf_ratio
        beta = prior_strength * (1 - conf_ratio)
        # Ensure minimum of 0.5 for each parameter
        alpha = max(alpha, 0.5)
        beta = max(beta, 0.5)

        for _ in range(count):
            beliefs.append(Belief(
                id=bid,
                source_type=source_type,
                true_usefulness_rate=true_rate,
                alpha=alpha,
                beta_param=beta,
            ))
            bid += 1

    return beliefs


def run_sweep_trial(
    config: ExperimentConfig,
    prior_strength: float,
    exploration_weight: float,
    rng: np.random.Generator,
) -> dict[str, float]:
    """Run a single trial with given parameters."""
    beliefs = create_beliefs_with_params(config, prior_strength)
    session_records: list[dict[str, Any]] = []

    sweep_config = ExperimentConfig(
        n_beliefs=config.n_beliefs,
        n_sessions=config.n_sessions,
        n_retrievals_per_session=config.n_retrievals_per_session,
        n_beliefs_per_retrieval=config.n_beliefs_per_retrieval,
        n_trials=config.n_trials,
        exploration_weight=exploration_weight,
        failure_cost_weight=config.failure_cost_weight,
        seed=config.seed,
        n_user_stated=config.n_user_stated,
        n_document=config.n_document,
        n_agent_inferred=config.n_agent_inferred,
        n_cross_reference=config.n_cross_reference,
        true_rate_user=config.true_rate_user,
        true_rate_document=config.true_rate_document,
        true_rate_agent=config.true_rate_agent,
        true_rate_cross_ref=config.true_rate_cross_ref,
    )

    for session in range(config.n_sessions):
        retrievals: list[dict[str, Any]] = []
        session_data: dict[str, Any] = {"session": session, "retrievals": retrievals}

        for _ in range(config.n_retrievals_per_session):
            scores: list[tuple[Belief, float]] = [(b, b.expected_utility(1.0, sweep_config)) for b in beliefs]
            scores.sort(key=lambda x: x[1], reverse=True)
            retrieved: list[Belief] = [b for b, _ in scores[:config.n_beliefs_per_retrieval]]

            for belief in retrieved:
                belief.retrieval_count += 1

                if rng.random() < belief.true_usefulness_rate:
                    outcome = "used"
                else:
                    outcome = "harmful"

                if rng.random() < 0.30:
                    outcome = "ignored"

                retrievals.append({
                    "belief_id": belief.id,
                    "entropy": belief.entropy,
                })

                belief.update(outcome)

        session_records.append(session_data)

    cal = compute_calibration(beliefs)
    conv = compute_convergence(beliefs)
    expl = compute_exploration(session_records, beliefs)
    rank = compute_rank_correlation(beliefs)

    return {
        "ece": float(cal["ece"]),
        "convergence_rate": float(conv["convergence_rate"]),
        "exploration_fraction": float(expl["exploration_fraction"]),
        "rank_correlation": rank,
    }


def _rng_seed(rng: np.random.Generator) -> int:
    raw: Any = rng.integers(0, 2**32)
    return int(raw)


def main() -> None:
    base_config = ExperimentConfig(n_trials=20)  # fewer trials per point for speed
    rng_base = np.random.default_rng(base_config.seed)

    prior_strengths: list[float] = [1.0, 2.0, 3.0, 5.0, 8.0, 10.0]
    exploration_weights: list[float] = [0.0, 0.05, 0.10, 0.20, 0.30, 0.50, 1.0]

    print(f"Sweeping {len(prior_strengths)} prior strengths x "
          f"{len(exploration_weights)} exploration weights x "
          f"{base_config.n_trials} trials", file=sys.stderr)

    results: list[dict[str, Any]] = []

    for ps in prior_strengths:
        for ew in exploration_weights:
            eces: list[float] = []
            explores: list[float] = []
            convs: list[float] = []
            ranks: list[float] = []

            for _trial in range(base_config.n_trials):
                seed: int = _rng_seed(rng_base)
                rng = np.random.default_rng(seed)
                r = run_sweep_trial(base_config, ps, ew, rng)
                eces.append(r["ece"])
                explores.append(r["exploration_fraction"])
                convs.append(r["convergence_rate"])
                ranks.append(r["rank_correlation"])

            result: dict[str, Any] = {
                "prior_strength": ps,
                "exploration_weight": ew,
                "ece_mean": round(float(np.mean(eces)), 4),
                "ece_std": round(float(np.std(eces)), 4),
                "exploration_mean": round(float(np.mean(explores)), 4),
                "convergence_mean": round(float(np.mean(convs)), 4),
                "rank_corr_mean": round(float(np.nanmean(ranks)), 4),
                "req009_pass": float(np.mean(eces)) < 0.10,
                "req010_pass": 0.15 <= float(np.mean(explores)) <= 0.50,
                "both_pass": float(np.mean(eces)) < 0.10 and 0.15 <= float(np.mean(explores)) <= 0.50,
            }
            results.append(result)

            status = "PASS" if result["both_pass"] else "----"
            print(f"  ps={ps:4.1f} ew={ew:4.2f} -> ECE={result['ece_mean']:.4f} "
                  f"expl={result['exploration_mean']:.4f} "
                  f"conv={result['convergence_mean']:.4f} [{status}]", file=sys.stderr)

    # Find best configurations
    passing: list[dict[str, Any]] = [r for r in results if r["both_pass"]]
    best_by_ece: list[dict[str, Any]] = sorted(passing, key=lambda r: float(r["ece_mean"]))[:5] if passing else []

    output: dict[str, Any] = {
        "sweep_results": results,
        "passing_configs": len(passing),
        "total_configs": len(results),
        "best_by_ece": best_by_ece,
    }

    print(f"\n--- {len(passing)}/{len(results)} configurations pass both requirements ---",
          file=sys.stderr)
    if best_by_ece:
        print("Top 5 by ECE:", file=sys.stderr)
        for r in best_by_ece:
            print(f"  ps={r['prior_strength']:.1f} ew={r['exploration_weight']:.2f} "
                  f"ECE={r['ece_mean']:.4f} expl={r['exploration_mean']:.4f}", file=sys.stderr)
    else:
        print("No configurations pass both. Closest:", file=sys.stderr)
        closest: list[dict[str, Any]] = sorted(
            results, key=lambda r: float(r["ece_mean"]) + abs(0.25 - float(r["exploration_mean"]))
        )[:5]
        for r in closest:
            print(f"  ps={r['prior_strength']:.1f} ew={r['exploration_weight']:.2f} "
                  f"ECE={r['ece_mean']:.4f} expl={r['exploration_mean']:.4f}", file=sys.stderr)

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
