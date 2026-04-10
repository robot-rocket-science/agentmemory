from __future__ import annotations

"""
Experiment 5: Exploration-Exploitation Strategy Comparison

Tests four strategies for balancing calibration (ECE) and exploration:
  A. Phased exploration (annealing)
  B. Decoupled exploration (separate channels)
  C. Thompson sampling (posterior sampling)
  D. Static baseline (best from Exp 2b: ew=0.50)

Depends on: Exp 2 findings (calibration metric fix, uniform priors)
Blocks: Exp 3 (retrieval quality), Exp 4 (token budget)

Protocol: EXPERIMENTS.md, Experiment 5
"""

import json
import sys
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from experiments.exp2_bayesian_calibration import (
    ExperimentConfig,
    Belief,
    compute_calibration,
    compute_rank_correlation,
)


@dataclass
class StrategyResult:
    ece: float
    exploration_fraction: float
    rank_correlation: float
    convergence_rate: float
    total_retrievals: int


def create_beliefs(config: ExperimentConfig) -> list[Belief]:
    """All beliefs start with uniform priors (Exp 2 showed source-informed are harmful)."""
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
                alpha=1.0, beta_param=1.0,
            ))
            bid += 1
    return beliefs


def simulate_outcome(belief: Belief, rng: np.random.Generator) -> Literal["used", "harmful", "ignored"]:
    if rng.random() < 0.30:
        return "ignored"
    elif rng.random() < belief.true_usefulness_rate:
        return "used"
    else:
        return "harmful"


def apply_outcome(belief: Belief, outcome: Literal["used", "harmful", "ignored"]) -> None:
    belief.retrieval_count += 1
    belief.update(outcome)


def compute_metrics(beliefs: list[Belief], exploration_retrievals: int,
                    total_retrievals: int) -> StrategyResult:
    cal = compute_calibration(beliefs)
    rank = compute_rank_correlation(beliefs)

    tested = [b for b in beliefs if b.retrieval_count > 0]
    converged = [b for b in tested if abs(b.confidence - b.true_usefulness_rate) <= 0.10]
    conv_rate = len(converged) / len(tested) if tested else 0

    expl_frac = exploration_retrievals / total_retrievals if total_retrievals > 0 else 0

    ece_val: float = cal["ece"]
    return StrategyResult(
        ece=ece_val,
        exploration_fraction=round(expl_frac, 4),
        rank_correlation=rank,
        convergence_rate=round(conv_rate, 4),
        total_retrievals=total_retrievals,
    )


# --- Strategy A: Phased Exploration (Annealing) ---

def run_phased(config: ExperimentConfig, rng: np.random.Generator) -> StrategyResult:
    beliefs = create_beliefs(config)
    exploration_count = 0
    total_count = 0

    for _session in range(config.n_sessions):
        # Decay exploration weight: 0.50 -> 0.05 over 30 sessions
        ew = max(0.05, 0.50 * (1.0 - _session / 30.0))
        phase_config = ExperimentConfig(exploration_weight=ew, failure_cost_weight=0.3)

        # Track median entropy for exploration measurement
        entropies: list[float] = [b.entropy for b in beliefs]
        median_ent = float(np.median(entropies)) if entropies else 0

        for _ in range(config.n_retrievals_per_session):
            scores: list[tuple[Belief, float]] = [(b, b.expected_utility(1.0, phase_config)) for b in beliefs]
            scores.sort(key=lambda x: x[1], reverse=True)
            retrieved: list[Belief] = [b for b, _ in scores[:config.n_beliefs_per_retrieval]]

            for b in retrieved:
                total_count += 1
                if b.entropy > median_ent:
                    exploration_count += 1
                apply_outcome(b, simulate_outcome(b, rng))

    return compute_metrics(beliefs, exploration_count, total_count)


# --- Strategy B: Decoupled Exploration ---

def run_decoupled(config: ExperimentConfig, rng: np.random.Generator) -> StrategyResult:
    beliefs = create_beliefs(config)
    exploration_count = 0
    total_count = 0

    exploit_config = ExperimentConfig(exploration_weight=0.05, failure_cost_weight=0.3)

    for _session in range(config.n_sessions):
        entropies: list[float] = [b.entropy for b in beliefs]
        median_ent = float(np.median(entropies)) if entropies else 0

        # Task channel: 10 retrievals, low exploration
        for _ in range(config.n_retrievals_per_session):
            scores: list[tuple[Belief, float]] = [(b, b.expected_utility(1.0, exploit_config)) for b in beliefs]
            scores.sort(key=lambda x: x[1], reverse=True)
            retrieved: list[Belief] = [b for b, _ in scores[:config.n_beliefs_per_retrieval]]

            for b in retrieved:
                total_count += 1
                if b.entropy > median_ent:
                    exploration_count += 1
                apply_outcome(b, simulate_outcome(b, rng))

        # Exploration channel: 5 retrievals, highest entropy
        explore_candidates = sorted(beliefs, key=lambda b: b.entropy, reverse=True)
        explore_retrieved = explore_candidates[:5]

        for b in explore_retrieved:
            total_count += 1
            exploration_count += 1  # all exploration channel retrievals count
            apply_outcome(b, simulate_outcome(b, rng))

    return compute_metrics(beliefs, exploration_count, total_count)


# --- Strategy C: Thompson Sampling ---

def run_thompson(config: ExperimentConfig, rng: np.random.Generator) -> StrategyResult:
    beliefs = create_beliefs(config)
    exploration_count = 0
    total_count = 0

    for _session in range(config.n_sessions):
        entropies: list[float] = [b.entropy for b in beliefs]
        median_ent = float(np.median(entropies)) if entropies else 0

        for _ in range(config.n_retrievals_per_session):
            # Sample from each belief's Beta distribution
            samples: list[tuple[Belief, float]] = []
            for b in beliefs:
                s = float(rng.beta(b.alpha, b.beta_param))
                samples.append((b, s))

            samples.sort(key=lambda x: x[1], reverse=True)
            retrieved: list[Belief] = [b for b, _ in samples[:config.n_beliefs_per_retrieval]]

            for b in retrieved:
                total_count += 1
                if b.entropy > median_ent:
                    exploration_count += 1
                apply_outcome(b, simulate_outcome(b, rng))

    return compute_metrics(beliefs, exploration_count, total_count)


# --- Strategy D: Static Baseline ---

def run_static(config: ExperimentConfig, rng: np.random.Generator) -> StrategyResult:
    beliefs = create_beliefs(config)
    exploration_count = 0
    total_count = 0

    static_config = ExperimentConfig(exploration_weight=0.50, failure_cost_weight=0.3)

    for _session in range(config.n_sessions):
        entropies: list[float] = [b.entropy for b in beliefs]
        median_ent = float(np.median(entropies)) if entropies else 0

        for _ in range(config.n_retrievals_per_session):
            scores: list[tuple[Belief, float]] = [(b, b.expected_utility(1.0, static_config)) for b in beliefs]
            scores.sort(key=lambda x: x[1], reverse=True)
            retrieved: list[Belief] = [b for b, _ in scores[:config.n_beliefs_per_retrieval]]

            for b in retrieved:
                total_count += 1
                if b.entropy > median_ent:
                    exploration_count += 1
                apply_outcome(b, simulate_outcome(b, rng))

    return compute_metrics(beliefs, exploration_count, total_count)


# --- Main ---

StrategyFn = type[None]  # placeholder, real type below

STRATEGIES: dict[str, Any] = {
    "A_phased": run_phased,
    "B_decoupled": run_decoupled,
    "C_thompson": run_thompson,
    "D_static": run_static,
}


def _rng_seed(rng: np.random.Generator) -> int:
    raw: Any = rng.integers(0, 2**32)
    return int(raw)


def main() -> None:
    config = ExperimentConfig(n_trials=100)
    rng_base = np.random.default_rng(config.seed)

    print("=" * 60, file=sys.stderr)
    print("Experiment 5: Exploration-Exploitation Strategies", file=sys.stderr)
    print(f"  {config.n_beliefs} beliefs, {config.n_sessions} sessions, "
          f"{config.n_trials} trials per strategy", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    all_results: dict[str, dict[str, Any]] = {}

    for name, strategy_fn in STRATEGIES.items():
        print(f"\nRunning {name}...", file=sys.stderr)

        trial_results: list[dict[str, Any]] = []
        for trial in range(config.n_trials):
            seed: int = _rng_seed(rng_base)
            rng = np.random.default_rng(seed)
            result: StrategyResult = strategy_fn(config, rng)
            trial_results.append({
                "ece": result.ece,
                "exploration": result.exploration_fraction,
                "rank_corr": result.rank_correlation,
                "convergence": result.convergence_rate,
                "total_retrievals": result.total_retrievals,
            })
            if (trial + 1) % 25 == 0:
                print(f"  Trial {trial + 1}/{config.n_trials}", file=sys.stderr)

        eces: list[float] = [r["ece"] for r in trial_results]
        expls: list[float] = [r["exploration"] for r in trial_results]
        convs: list[float] = [r["convergence"] for r in trial_results]
        ranks: list[float] = [r["rank_corr"] for r in trial_results]
        retrievals: int = trial_results[0]["total_retrievals"]

        summary: dict[str, Any] = {
            "ece_mean": round(float(np.mean(eces)), 4),
            "ece_std": round(float(np.std(eces)), 4),
            "ece_p5": round(float(np.percentile(eces, 5)), 4),
            "ece_p95": round(float(np.percentile(eces, 95)), 4),
            "exploration_mean": round(float(np.mean(expls)), 4),
            "exploration_std": round(float(np.std(expls)), 4),
            "convergence_mean": round(float(np.mean(convs)), 4),
            "rank_corr_mean": round(float(np.nanmean(ranks)), 4),
            "retrievals_per_session": retrievals // config.n_sessions,
            "req009_pass": float(np.mean(eces)) < 0.10,
            "req010_pass": 0.15 <= float(np.mean(expls)) <= 0.50,
            "both_pass": float(np.mean(eces)) < 0.10 and 0.15 <= float(np.mean(expls)) <= 0.50,
        }

        all_results[name] = summary

        status = "PASS BOTH" if summary["both_pass"] else (
            "pass ECE only" if summary["req009_pass"] else (
                "pass expl only" if summary["req010_pass"] else "FAIL BOTH"
            )
        )
        print(f"  {name}: ECE={summary['ece_mean']:.4f} "
              f"(90%: {summary['ece_p5']:.4f}-{summary['ece_p95']:.4f}) "
              f"expl={summary['exploration_mean']:.4f} "
              f"conv={summary['convergence_mean']:.4f} "
              f"rank={summary['rank_corr_mean']:.4f} "
              f"[{status}]", file=sys.stderr)

    # Summary table
    print("\n" + "=" * 60, file=sys.stderr)
    print("RESULTS SUMMARY", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"{'Strategy':<15} {'ECE':>8} {'Expl':>8} {'Conv':>8} {'Rank':>8} {'Ret/Ses':>8} {'Status':<12}",
          file=sys.stderr)
    print("-" * 75, file=sys.stderr)

    for name, s in all_results.items():
        status = "PASS BOTH" if s["both_pass"] else (
            "ECE only" if s["req009_pass"] else (
                "Expl only" if s["req010_pass"] else "FAIL"
            )
        )
        print(f"{name:<15} {s['ece_mean']:>8.4f} {s['exploration_mean']:>8.4f} "
              f"{s['convergence_mean']:>8.4f} {s['rank_corr_mean']:>8.4f} "
              f"{s['retrievals_per_session']:>8d} {status:<12}", file=sys.stderr)

    print("\n--- REQUIREMENT CHECKS ---", file=sys.stderr)
    for name, s in all_results.items():
        print(f"  {name}:", file=sys.stderr)
        print(f"    REQ-009 (ECE < 0.10):           {'PASS' if s['req009_pass'] else 'FAIL'} "
              f"({s['ece_mean']:.4f})", file=sys.stderr)
        print(f"    REQ-010 (0.15 <= expl <= 0.50): {'PASS' if s['req010_pass'] else 'FAIL'} "
              f"({s['exploration_mean']:.4f})", file=sys.stderr)

    # Winner selection
    passing: dict[str, dict[str, Any]] = {k: v for k, v in all_results.items() if v["both_pass"]}
    if passing:
        winner = min(passing.items(), key=lambda x: float(x[1]["ece_mean"]))
        print(f"\nWINNER: {winner[0]} (lowest ECE among passing strategies)", file=sys.stderr)
    else:
        closest = min(all_results.items(),
                      key=lambda x: float(x[1]["ece_mean"]) + abs(0.25 - float(x[1]["exploration_mean"])))
        print(f"\nNo strategy passes both. Closest: {closest[0]}", file=sys.stderr)

    print(json.dumps(all_results, indent=2))


if __name__ == "__main__":
    main()
