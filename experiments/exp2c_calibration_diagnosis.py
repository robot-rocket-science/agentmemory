"""
Experiment 2c: Diagnose why calibration (ECE) is stuck at 0.16-0.21.

Hypotheses for poor calibration:
  H1: 30% IGNORED rate adds noise that prevents convergence
  H2: Selection bias -- top-k retrieval means most beliefs never get tested
  H3: ECE binning artifacts from clustered true rates (0.45, 0.55, 0.65, 0.85)
  H4: 50 sessions is insufficient for convergence
  H5: The model is actually working but our ECE threshold is unrealistic

This script runs targeted diagnostics for each hypothesis.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import numpy as np

from experiments.exp2_bayesian_calibration import (
    ExperimentConfig,
    Belief,
    compute_calibration,
)


def create_beliefs_uniform(config: ExperimentConfig) -> list[Belief]:
    beliefs: list[Belief] = []
    bid: int = 0
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


def diagnosis_h1_ignored_rate(rng: np.random.Generator) -> dict[str, dict[str, float]]:
    """H1: Does removing IGNORED outcomes fix calibration?"""
    print("  H1: Testing effect of IGNORED rate...", file=sys.stderr)
    results: dict[str, dict[str, float]] = {}

    for ignored_rate in [0.0, 0.10, 0.20, 0.30, 0.50]:
        eces: list[float] = []
        for _ in range(20):
            config = ExperimentConfig()
            beliefs = create_beliefs_uniform(config)

            for _ in range(config.n_sessions):
                for _ in range(config.n_retrievals_per_session):
                    # Random retrieval (not top-k) to eliminate selection bias
                    idxs = rng.choice(len(beliefs), size=config.n_beliefs_per_retrieval, replace=False)
                    for idx in idxs:
                        b: Belief = beliefs[int(idx)]
                        b.retrieval_count += 1

                        if rng.random() < ignored_rate:
                            b.update("ignored")
                        elif rng.random() < b.true_usefulness_rate:
                            b.update("used")
                        else:
                            b.update("harmful")

            cal: dict[str, Any] = compute_calibration(beliefs)
            eces.append(float(cal["ece"]))

        results[f"ignored_{ignored_rate:.2f}"] = {
            "ece_mean": round(float(np.mean(eces)), 4),
            "ece_std": round(float(np.std(eces)), 4),
        }
        print(f"    ignored_rate={ignored_rate:.2f} -> ECE={np.mean(eces):.4f}", file=sys.stderr)

    return results


def diagnosis_h2_selection_bias(rng: np.random.Generator) -> dict[str, dict[str, float]]:
    """H2: Does random retrieval (instead of top-k) fix calibration?"""
    print("  H2: Testing random vs top-k retrieval...", file=sys.stderr)
    results: dict[str, dict[str, float]] = {}

    for mode in ["random", "topk"]:
        eces: list[float] = []
        tested_fracs: list[float] = []

        for _ in range(20):
            config = ExperimentConfig()
            beliefs = create_beliefs_uniform(config)

            for _ in range(config.n_sessions):
                for _ in range(config.n_retrievals_per_session):
                    retrieved: list[Belief]
                    if mode == "random":
                        idxs = rng.choice(len(beliefs), size=config.n_beliefs_per_retrieval, replace=False)
                        retrieved = [beliefs[int(i)] for i in idxs]
                    else:
                        eu_config: ExperimentConfig = ExperimentConfig(exploration_weight=0.30)
                        scores: list[tuple[Belief, float]] = [(b, b.expected_utility(1.0, eu_config)) for b in beliefs]
                        scores.sort(key=lambda x: x[1], reverse=True)
                        retrieved = [b for b, _ in scores[:config.n_beliefs_per_retrieval]]

                    for b in retrieved:
                        b.retrieval_count += 1
                        if rng.random() < 0.30:
                            b.update("ignored")
                        elif rng.random() < b.true_usefulness_rate:
                            b.update("used")
                        else:
                            b.update("harmful")

            tested: int = sum(1 for b in beliefs if b.retrieval_count > 0)
            tested_fracs.append(tested / len(beliefs))
            cal: dict[str, Any] = compute_calibration(beliefs)
            eces.append(float(cal["ece"]))

        results[mode] = {
            "ece_mean": round(float(np.mean(eces)), 4),
            "ece_std": round(float(np.std(eces)), 4),
            "beliefs_tested_frac": round(float(np.mean(tested_fracs)), 4),
        }
        print(f"    {mode}: ECE={np.mean(eces):.4f}, "
              f"beliefs tested={np.mean(tested_fracs):.2%}", file=sys.stderr)

    return results


def diagnosis_h3_binning(rng: np.random.Generator) -> dict[str, Any]:
    """H3: Is ECE inflated by binning artifacts from clustered true rates?"""
    print("  H3: Testing ECE with different bin counts and per-source breakdown...", file=sys.stderr)

    config: ExperimentConfig = ExperimentConfig()
    beliefs: list[Belief] = create_beliefs_uniform(config)

    # Run with random retrieval and no ignored to isolate binning effects
    for _ in range(config.n_sessions * 2):  # extra sessions for more data
        for _ in range(config.n_retrievals_per_session):
            idxs = rng.choice(len(beliefs), size=config.n_beliefs_per_retrieval, replace=False)
            for idx in idxs:
                b: Belief = beliefs[int(idx)]
                b.retrieval_count += 1
                if rng.random() < b.true_usefulness_rate:
                    b.update("used")
                else:
                    b.update("harmful")

    results: dict[str, Any] = {}

    # ECE with different bin counts
    for n_bins in [5, 10, 20, 50]:
        cal: dict[str, Any] = compute_calibration(beliefs, n_bins=n_bins)
        results[f"bins_{n_bins}"] = cal["ece"]
        print(f"    {n_bins} bins: ECE={cal['ece']:.4f}", file=sys.stderr)

    # Per-source calibration
    for source in ["user_stated", "document", "agent_inferred", "cross_reference"]:
        source_beliefs: list[Belief] = [b for b in beliefs if b.source_type == source]
        cal = compute_calibration(source_beliefs)
        actual_rates: list[float] = []
        for b in source_beliefs:
            if b.retrieval_count > 0:
                actual_rates.append(b.used_count / b.retrieval_count)
        confs: list[float] = [b.confidence for b in source_beliefs]
        results[f"source_{source}"] = {
            "ece": cal["ece"],
            "mean_confidence": round(float(np.mean(confs)), 4),
            "mean_actual_use_rate": round(float(np.mean(actual_rates)), 4) if actual_rates else None,
            "true_rate": source_beliefs[0].true_usefulness_rate,
        }
        print(f"    {source}: ECE={cal['ece']:.4f}, "
              f"conf={np.mean(confs):.4f}, "
              f"actual={np.mean(actual_rates):.4f}, "
              f"true={source_beliefs[0].true_usefulness_rate}", file=sys.stderr)

    return results


def diagnosis_h4_convergence_over_time(rng: np.random.Generator) -> dict[str, dict[str, Any]]:
    """H4: How does ECE project-j over sessions? Is 50 enough?"""
    print("  H4: ECE over time (up to 200 sessions)...", file=sys.stderr)

    config: ExperimentConfig = ExperimentConfig()
    beliefs: list[Belief] = create_beliefs_uniform(config)
    results: dict[str, dict[str, Any]] = {}

    checkpoints: list[int] = [5, 10, 20, 50, 100, 200]
    session: int = 0

    for target in checkpoints:
        while session < target:
            for _ in range(config.n_retrievals_per_session):
                idxs = rng.choice(len(beliefs), size=config.n_beliefs_per_retrieval, replace=False)
                for idx in idxs:
                    b: Belief = beliefs[int(idx)]
                    b.retrieval_count += 1
                    if rng.random() < 0.30:
                        b.update("ignored")
                    elif rng.random() < b.true_usefulness_rate:
                        b.update("used")
                    else:
                        b.update("harmful")
            session += 1

        cal: dict[str, Any] = compute_calibration(beliefs)
        tested: int = sum(1 for b in beliefs if b.retrieval_count > 0)

        # Per-belief diagnosis: how close is each belief's confidence to its true rate?
        errors: list[float] = []
        for b in beliefs:
            if b.retrieval_count > 0:
                errors.append(abs(b.confidence - b.true_usefulness_rate))

        retrieval_counts: list[int] = [b.retrieval_count for b in beliefs if b.retrieval_count > 0]
        results[f"session_{target}"] = {
            "ece": cal["ece"],
            "beliefs_tested": tested,
            "mean_abs_error_per_belief": round(float(np.mean(errors)), 4) if errors else None,
            "median_abs_error_per_belief": round(float(np.median(errors)), 4) if errors else None,
            "median_retrievals_per_belief": round(float(np.median(retrieval_counts)), 1),
        }
        print(f"    session {target:3d}: ECE={cal['ece']:.4f}, "
              f"tested={tested}, "
              f"mean_err={np.mean(errors):.4f}, "
              f"med_retrievals={np.median(retrieval_counts):.0f}",
              file=sys.stderr)

    return results


def diagnosis_h5_theoretical_floor(rng: np.random.Generator) -> dict[str, float]:
    """H5: What ECE does a perfect oracle achieve with same noise structure?"""
    print("  H5: Oracle ECE (beliefs know their true rate, only noise is sampling)...", file=sys.stderr)

    config: ExperimentConfig = ExperimentConfig()

    eces: list[float] = []
    for _ in range(50):
        beliefs: list[Belief] = create_beliefs_uniform(config)
        # Give each belief many samples from its true rate
        for b in beliefs:
            n_samples: int = 100
            successes: int = int(rng.binomial(n_samples, b.true_usefulness_rate))
            b.alpha = 1.0 + successes
            b.beta_param = 1.0 + (n_samples - successes)
            b.retrieval_count = n_samples
            b.used_count = successes

        cal: dict[str, Any] = compute_calibration(beliefs)
        eces.append(float(cal["ece"]))

    result: dict[str, float] = {
        "oracle_ece_100_samples": round(float(np.mean(eces)), 4),
        "oracle_ece_std": round(float(np.std(eces)), 4),
    }
    print(f"    Oracle (100 samples each): ECE={np.mean(eces):.4f} +/- {np.std(eces):.4f}",
          file=sys.stderr)

    # Now with the IGNORED noise
    eces_noisy: list[float] = []
    for _ in range(50):
        beliefs = create_beliefs_uniform(config)
        for b in beliefs:
            n_samples = 100
            for _ in range(n_samples):
                b.retrieval_count += 1
                if rng.random() < 0.30:  # IGNORED
                    b.update("ignored")
                elif rng.random() < b.true_usefulness_rate:
                    b.update("used")
                else:
                    b.update("harmful")

        cal = compute_calibration(beliefs)
        eces_noisy.append(float(cal["ece"]))

    result["oracle_with_ignored_ece"] = round(float(np.mean(eces_noisy)), 4)
    result["oracle_with_ignored_std"] = round(float(np.std(eces_noisy)), 4)
    print(f"    Oracle (100 samples, 30% ignored): ECE={np.mean(eces_noisy):.4f} +/- "
          f"{np.std(eces_noisy):.4f}", file=sys.stderr)

    return result


def main() -> None:
    print("=" * 60, file=sys.stderr)
    print("Experiment 2c: Calibration Diagnosis", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    results: dict[str, Any] = {}
    results["h1_ignored_rate"] = diagnosis_h1_ignored_rate(np.random.default_rng(42))
    results["h2_selection_bias"] = diagnosis_h2_selection_bias(np.random.default_rng(43))
    results["h3_binning"] = diagnosis_h3_binning(np.random.default_rng(44))
    results["h4_convergence"] = diagnosis_h4_convergence_over_time(np.random.default_rng(45))
    results["h5_theoretical_floor"] = diagnosis_h5_theoretical_floor(np.random.default_rng(46))

    print("\n" + "=" * 60, file=sys.stderr)
    print("DIAGNOSIS SUMMARY", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # H1
    h1: dict[str, dict[str, float]] = results["h1_ignored_rate"]
    print(f"\nH1 (IGNORED rate effect):", file=sys.stderr)
    print(f"  0% ignored: ECE={h1['ignored_0.00']['ece_mean']:.4f}", file=sys.stderr)
    print(f"  30% ignored: ECE={h1['ignored_0.30']['ece_mean']:.4f}", file=sys.stderr)
    h1_verdict: str = "CONFIRMED" if h1['ignored_0.00']['ece_mean'] < h1['ignored_0.30']['ece_mean'] - 0.03 else "NOT SIGNIFICANT"
    print(f"  Verdict: {h1_verdict}", file=sys.stderr)

    # H2
    h2: dict[str, dict[str, float]] = results["h2_selection_bias"]
    print(f"\nH2 (Selection bias):", file=sys.stderr)
    print(f"  Random retrieval: ECE={h2['random']['ece_mean']:.4f}, "
          f"tested={h2['random']['beliefs_tested_frac']:.0%}", file=sys.stderr)
    print(f"  Top-k retrieval:  ECE={h2['topk']['ece_mean']:.4f}, "
          f"tested={h2['topk']['beliefs_tested_frac']:.0%}", file=sys.stderr)
    h2_verdict: str = "CONFIRMED" if h2['random']['ece_mean'] < h2['topk']['ece_mean'] - 0.03 else "NOT SIGNIFICANT"
    print(f"  Verdict: {h2_verdict}", file=sys.stderr)

    # H4
    h4: dict[str, dict[str, Any]] = results["h4_convergence"]
    print(f"\nH4 (Convergence over time):", file=sys.stderr)
    print(f"  Session 5:   ECE={h4['session_5']['ece']:.4f}", file=sys.stderr)
    print(f"  Session 50:  ECE={h4['session_50']['ece']:.4f}", file=sys.stderr)
    print(f"  Session 200: ECE={h4['session_200']['ece']:.4f}", file=sys.stderr)

    # H5
    h5: dict[str, float] = results["h5_theoretical_floor"]
    print(f"\nH5 (Theoretical floor):", file=sys.stderr)
    print(f"  Oracle (no noise):     ECE={h5['oracle_ece_100_samples']:.4f}", file=sys.stderr)
    print(f"  Oracle (30% ignored):  ECE={h5['oracle_with_ignored_ece']:.4f}", file=sys.stderr)
    print(f"  -> Minimum achievable ECE with this setup: ~{h5['oracle_ece_100_samples']:.4f}", file=sys.stderr)

    if h5['oracle_ece_100_samples'] > 0.05:
        print(f"  -> REQ-009 threshold of 0.10 may need revision!", file=sys.stderr)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
