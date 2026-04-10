"""
Experiment 15: Scaling Behavior of Thompson Sampling Feedback Loop

Tests: does Thompson + Jeffreys degrade at larger scales?
- 200 beliefs (baseline, from Exp 5b/7)
- 1,000 beliefs
- 5,000 beliefs
- 10,000 beliefs

For each scale: 50 sessions, measure ECE, exploration, domain precision.
Also measure: wall-clock time per retrieval (does it get slow?).
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from experiments.exp2_bayesian_calibration import (
    Belief, compute_calibration, _digamma,
)


SCALES = [200, 1_000, 5_000, 10_000]
N_SESSIONS = 50
N_TRIALS = 10  # fewer trials for larger scales (speed)
DOMAINS = ["database", "frontend", "deployment", "strategy", "testing",
           "security", "performance", "documentation", "devops", "research"]
TRUE_RATES = {d: 0.4 + 0.05 * i for i, d in enumerate(DOMAINS)}  # 0.40 to 0.85


def create_beliefs(n: int) -> list[Belief]:
    beliefs = []
    for i in range(n):
        domain = DOMAINS[i % len(DOMAINS)]
        beliefs.append(Belief(
            id=i,
            source_type=domain,
            true_usefulness_rate=TRUE_RATES[domain],
            alpha=0.5,
            beta_param=0.5,
        ))
    return beliefs


def run_trial(n_beliefs: int, rng: np.random.Generator) -> dict:
    beliefs = create_beliefs(n_beliefs)

    t_start = time.perf_counter()
    total_retrievals = 0

    for session in range(N_SESSIONS):
        for _ in range(10):  # 10 retrievals per session
            # Thompson sampling
            samples = np.array([
                rng.beta(max(b.alpha, 0.01), max(b.beta_param, 0.01))
                for b in beliefs
            ])
            top_k_idx = np.argpartition(samples, -5)[-5:]
            top_k_idx = top_k_idx[np.argsort(samples[top_k_idx])[::-1]]

            for idx in top_k_idx:
                b = beliefs[idx]
                b.retrieval_count += 1
                total_retrievals += 1

                if rng.random() < 0.30:
                    b.update("ignored")
                elif rng.random() < b.true_usefulness_rate:
                    b.update("used")
                else:
                    b.update("harmful")

    t_elapsed = time.perf_counter() - t_start

    cal = compute_calibration(beliefs)
    tested = sum(1 for b in beliefs if b.retrieval_count > 0)
    converged = sum(1 for b in beliefs
                    if b.retrieval_count > 0
                    and abs(b.confidence - b.true_usefulness_rate) <= 0.15)

    return {
        "ece": cal["ece"],
        "beliefs_tested": tested,
        "beliefs_total": n_beliefs,
        "test_coverage": round(tested / n_beliefs, 4),
        "convergence_rate": round(converged / tested, 4) if tested else 0,
        "wall_seconds": round(t_elapsed, 3),
        "retrievals_per_second": round(total_retrievals / t_elapsed, 0),
    }


def main():
    rng_base = np.random.default_rng(42)

    print("=" * 60, file=sys.stderr)
    print("Experiment 15: Scaling Behavior", file=sys.stderr)
    print(f"  Scales: {SCALES}", file=sys.stderr)
    print(f"  {N_SESSIONS} sessions, {N_TRIALS} trials per scale", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    results = {}

    for n in SCALES:
        print(f"\n  Scale: {n:,} beliefs...", file=sys.stderr)
        trial_results = []

        for trial in range(N_TRIALS):
            seed = rng_base.integers(0, 2**32)
            rng = np.random.default_rng(seed)
            r = run_trial(n, rng)
            trial_results.append(r)

        eces = [r["ece"] for r in trial_results]
        coverages = [r["test_coverage"] for r in trial_results]
        conv_rates = [r["convergence_rate"] for r in trial_results]
        wall_times = [r["wall_seconds"] for r in trial_results]
        ret_rates = [r["retrievals_per_second"] for r in trial_results]

        summary = {
            "n_beliefs": n,
            "ece_mean": round(float(np.mean(eces)), 4),
            "ece_std": round(float(np.std(eces)), 4),
            "test_coverage_mean": round(float(np.mean(coverages)), 4),
            "convergence_rate_mean": round(float(np.mean(conv_rates)), 4),
            "wall_seconds_mean": round(float(np.mean(wall_times)), 3),
            "retrievals_per_second": round(float(np.mean(ret_rates)), 0),
        }
        results[n] = summary

        print(f"    ECE: {summary['ece_mean']:.4f}, "
              f"coverage: {summary['test_coverage_mean']:.0%}, "
              f"convergence: {summary['convergence_rate_mean']:.0%}, "
              f"time: {summary['wall_seconds_mean']:.1f}s, "
              f"ret/s: {summary['retrievals_per_second']:.0f}", file=sys.stderr)

    # Summary table
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"{'Scale':>10} {'ECE':>8} {'Tested':>8} {'Conv':>8} {'Time':>8} {'Ret/s':>10}", file=sys.stderr)
    print("-" * 55, file=sys.stderr)
    for n, s in results.items():
        print(f"{n:>10,} {s['ece_mean']:>8.4f} {s['test_coverage_mean']:>8.0%} "
              f"{s['convergence_rate_mean']:>8.0%} {s['wall_seconds_mean']:>7.1f}s "
              f"{s['retrievals_per_second']:>10,.0f}", file=sys.stderr)

    # Key question: does ECE degrade with scale?
    ece_vals = [str(round(results[n]["ece_mean"], 4)) for n in SCALES]
    cov_vals = [f'{results[n]["test_coverage_mean"]:.0%}' for n in SCALES]
    print(f"\n  ECE trend: {' -> '.join(ece_vals)}", file=sys.stderr)
    print(f"  Coverage trend: {' -> '.join(cov_vals)}", file=sys.stderr)

    Path("experiments/exp15_results.json").write_text(json.dumps(results, indent=2, default=str))
    print(f"\nOutput: experiments/exp15_results.json", file=sys.stderr)


if __name__ == "__main__":
    main()
