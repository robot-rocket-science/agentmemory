from __future__ import annotations

"""
Experiment 2: Bayesian Confidence Calibration Simulation

Tests whether Beta-Bernoulli confidence model produces calibrated scores.
Pure simulation -- no LLM calls, no human interaction.

Verifies: REQ-009 (calibration ECE < 0.10), REQ-010 (exploration 15-50%)

Protocol: EXPERIMENTS.md, Experiment 2
"""

import json
import sys
from dataclasses import dataclass
from math import log, lgamma
from typing import Any, Literal

import numpy as np


def _digamma(x: float) -> float:
    """Stirling approximation of digamma, accurate to ~1e-8 for x >= 6."""
    result = 0.0
    while x < 6.0:
        result -= 1.0 / x
        x += 1.0
    result += log(x) - 1.0 / (2.0 * x)
    x2 = 1.0 / (x * x)
    result -= x2 * (1.0/12.0 - x2 * (1.0/120.0 - x2 / 252.0))
    return result


# --- Configuration ---

@dataclass
class ExperimentConfig:
    n_beliefs: int = 200
    n_sessions: int = 50
    n_retrievals_per_session: int = 10
    n_beliefs_per_retrieval: int = 5
    n_trials: int = 100
    exploration_weight: float = 0.05
    failure_cost_weight: float = 0.3
    seed: int = 42

    # Source distribution: how many beliefs of each type
    n_user_stated: int = 50
    n_document: int = 50
    n_agent_inferred: int = 50
    n_cross_reference: int = 50

    # True usefulness rates (hidden from the model)
    true_rate_user: float = 0.85
    true_rate_document: float = 0.65
    true_rate_agent: float = 0.45
    true_rate_cross_ref: float = 0.55


# --- Belief Model ---

@dataclass
class Belief:
    id: int
    source_type: str
    true_usefulness_rate: float  # ground truth, hidden from model
    alpha: float = 1.0
    beta_param: float = 1.0
    retrieval_count: int = 0
    used_count: int = 0
    harmful_count: int = 0
    ignored_count: int = 0
    nid: str = ""

    @property
    def confidence(self) -> float:
        return self.alpha / (self.alpha + self.beta_param)

    @property
    def uncertainty(self) -> float:
        total = self.alpha + self.beta_param
        return (self.alpha * self.beta_param) / (total * total * (total + 1))

    @property
    def entropy(self) -> float:
        """Beta distribution entropy via lgamma (avoids scipy overhead in tight loop)."""
        a, b = self.alpha, self.beta_param
        log_beta = lgamma(a) + lgamma(b) - lgamma(a + b)
        psi_ab = _digamma(a + b)
        return log_beta - (a - 1) * _digamma(a) - (b - 1) * _digamma(b) + (a + b - 2) * psi_ab

    def expected_utility(self, relevance: float, config: ExperimentConfig) -> float:
        posterior_mean = self.confidence
        reward = relevance * posterior_mean
        risk = relevance * (1 - posterior_mean) * config.failure_cost_weight
        exploration = config.exploration_weight * self.entropy
        return reward - risk + exploration

    def update(self, outcome: Literal["used", "harmful", "ignored"]) -> None:
        if outcome == "used":
            self.alpha += 1.0
            self.used_count += 1
        elif outcome == "harmful":
            self.beta_param += 1.0
            self.harmful_count += 1
        elif outcome == "ignored":
            self.ignored_count += 1


def create_beliefs(config: ExperimentConfig, use_source_priors: bool) -> list[Belief]:
    beliefs: list[Belief] = []
    bid = 0

    sources: list[tuple[str, int, float, float, float]] = [
        ("user_stated", config.n_user_stated, config.true_rate_user, 9.0, 1.0),
        ("document", config.n_document, config.true_rate_document, 7.0, 3.0),
        ("agent_inferred", config.n_agent_inferred, config.true_rate_agent, 1.0, 1.0),
        ("cross_reference", config.n_cross_reference, config.true_rate_cross_ref, 3.0, 2.0),
    ]

    for source_type, count, true_rate, alpha_prior, beta_prior in sources:
        for _ in range(count):
            if use_source_priors:
                a, b = alpha_prior, beta_prior
            else:
                a, b = 1.0, 1.0  # uniform prior (control group)
            beliefs.append(Belief(
                id=bid,
                source_type=source_type,
                true_usefulness_rate=true_rate,
                alpha=a,
                beta_param=b,
            ))
            bid += 1

    return beliefs


# --- Simulation ---

def _rng_seed(rng: np.random.Generator) -> int:
    raw: Any = rng.integers(0, 2**32)
    return int(raw)


def run_single_trial(
    config: ExperimentConfig,
    use_source_priors: bool,
    rng: np.random.Generator,
) -> dict[str, Any]:
    beliefs = create_beliefs(config, use_source_priors)
    session_records: list[dict[str, Any]] = []

    for session in range(config.n_sessions):
        retrievals: list[dict[str, Any]] = []
        session_data: dict[str, Any] = {"session": session, "retrievals": retrievals}

        for _ in range(config.n_retrievals_per_session):
            # Score all beliefs by expected utility (relevance = 1.0 for all)
            scores: list[tuple[Belief, float]] = [(b, b.expected_utility(1.0, config)) for b in beliefs]
            scores.sort(key=lambda x: x[1], reverse=True)

            # Retrieve top-k
            retrieved: list[Belief] = [b for b, _ in scores[:config.n_beliefs_per_retrieval]]

            for belief in retrieved:
                belief.retrieval_count += 1

                # Simulate outcome: Bernoulli draw from true usefulness rate
                outcome: Literal["used", "harmful", "ignored"]
                if rng.random() < belief.true_usefulness_rate:
                    outcome = "used"
                else:
                    outcome = "harmful"

                # 30% chance of IGNORED (belief was retrieved but task didn't need it)
                if rng.random() < 0.30:
                    outcome = "ignored"

                confidence_before = belief.confidence
                belief.update(outcome)
                confidence_after = belief.confidence

                retrievals.append({
                    "belief_id": belief.id,
                    "source_type": belief.source_type,
                    "true_rate": belief.true_usefulness_rate,
                    "confidence_before": confidence_before,
                    "confidence_after": confidence_after,
                    "outcome": outcome,
                    "entropy": belief.entropy,
                })

        session_records.append(session_data)

    return {
        "beliefs": beliefs,
        "sessions": session_records,
    }


# --- Metrics ---

def compute_calibration(beliefs: list[Belief], n_bins: int = 10) -> dict[str, Any]:
    """Expected Calibration Error and per-bin calibration."""
    # Only include beliefs that have been tested at least once
    tested = [b for b in beliefs if b.retrieval_count > 0]
    if not tested:
        return {"ece": 1.0, "bins": [], "n_tested": 0}

    bins: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for b in tested:
        bin_idx = min(int(b.confidence * n_bins), n_bins - 1)
        # Exclude IGNORED from denominator: Beta only tracks used/harmful,
        # so calibration must compare against the same population.
        # Bug found in Exp 2c: using retrieval_count (includes IGNORED) inflated
        # the denominator, making actual_use_rate systematically lower than confidence.
        decisive_count = b.used_count + b.harmful_count
        actual_use_rate = b.used_count / decisive_count if decisive_count > 0 else 0.5
        bins[bin_idx].append((b.confidence, actual_use_rate))

    ece = 0.0
    bin_data: list[dict[str, Any]] = []
    total = len(tested)

    for i, bin_contents in enumerate(bins):
        if not bin_contents:
            bin_data.append({
                "bin_range": f"{i/n_bins:.1f}-{(i+1)/n_bins:.1f}",
                "count": 0,
                "mean_confidence": None,
                "mean_actual_rate": None,
                "calibration_error": None,
            })
            continue

        confs: list[float] = [c for c, _ in bin_contents]
        actuals: list[float] = [a for _, a in bin_contents]
        mean_conf = float(np.mean(confs))
        mean_actual = float(np.mean(actuals))
        error = abs(mean_conf - mean_actual)
        ece += (len(bin_contents) / total) * error

        bin_data.append({
            "bin_range": f"{i/n_bins:.1f}-{(i+1)/n_bins:.1f}",
            "count": len(bin_contents),
            "mean_confidence": round(float(mean_conf), 4),
            "mean_actual_rate": round(float(mean_actual), 4),
            "calibration_error": round(float(error), 4),
        })

    return {"ece": round(float(ece), 4), "bins": bin_data, "n_tested": len(tested)}


def compute_convergence(beliefs: list[Belief], threshold: float = 0.10) -> dict[str, Any]:
    """How many beliefs converged to within threshold of their true rate."""
    tested = [b for b in beliefs if b.retrieval_count > 0]
    converged = [b for b in tested if abs(b.confidence - b.true_usefulness_rate) <= threshold]
    return {
        "n_tested": len(tested),
        "n_converged": len(converged),
        "convergence_rate": round(len(converged) / len(tested), 4) if tested else 0,
    }


def compute_exploration(session_records: list[dict[str, Any]], beliefs: list[Belief]) -> dict[str, Any]:
    """What fraction of retrievals targeted uncertain beliefs."""
    # Compute median entropy across all beliefs
    entropies: list[float] = [b.entropy for b in beliefs]
    median_entropy = float(np.median(entropies))

    total_retrievals = 0
    exploration_retrievals = 0

    for session in session_records:
        retrieval_list: list[dict[str, Any]] = session["retrievals"]
        for ret in retrieval_list:
            total_retrievals += 1
            entropy_val: float = ret["entropy"]
            if entropy_val > median_entropy:
                exploration_retrievals += 1

    return {
        "total_retrievals": total_retrievals,
        "exploration_retrievals": exploration_retrievals,
        "exploration_fraction": round(exploration_retrievals / total_retrievals, 4) if total_retrievals > 0 else 0,
        "median_entropy": round(median_entropy, 4),
    }


def compute_rank_correlation(beliefs: list[Belief]) -> float:
    """Spearman rho between confidence ranking and true usefulness ranking."""
    tested = [b for b in beliefs if b.retrieval_count > 0]
    if len(tested) < 3:
        return 0.0

    from scipy.stats import spearmanr  # type: ignore[import-untyped]
    confs: list[float] = [b.confidence for b in tested]
    trues: list[float] = [b.true_usefulness_rate for b in tested]
    result: Any = spearmanr(confs, trues)
    rho: float = float(result.statistic)
    return round(rho, 4)


# --- Main ---

def run_experiment(config: ExperimentConfig) -> dict[str, Any]:
    rng_base = np.random.default_rng(config.seed)

    source_informed_list: list[dict[str, Any]] = []
    uniform_prior_list: list[dict[str, Any]] = []

    for trial in range(config.n_trials):
        seed: int = _rng_seed(rng_base)

        # Source-informed priors
        rng = np.random.default_rng(seed)
        trial_result = run_single_trial(config, use_source_priors=True, rng=rng)
        beliefs_list: list[Belief] = trial_result["beliefs"]
        sessions_list: list[dict[str, Any]] = trial_result["sessions"]
        calibration = compute_calibration(beliefs_list)
        convergence = compute_convergence(beliefs_list)
        exploration = compute_exploration(sessions_list, beliefs_list)
        rank_corr = compute_rank_correlation(beliefs_list)

        source_informed_list.append({
            "trial": trial,
            "ece": calibration["ece"],
            "convergence_rate": convergence["convergence_rate"],
            "exploration_fraction": exploration["exploration_fraction"],
            "rank_correlation": rank_corr,
            "n_tested": calibration["n_tested"],
            "calibration_bins": calibration["bins"],
        })

        # Uniform priors (control)
        rng = np.random.default_rng(seed)  # same seed for fair comparison
        trial_result = run_single_trial(config, use_source_priors=False, rng=rng)
        beliefs_list = trial_result["beliefs"]
        sessions_list = trial_result["sessions"]
        calibration = compute_calibration(beliefs_list)
        convergence = compute_convergence(beliefs_list)
        exploration = compute_exploration(sessions_list, beliefs_list)
        rank_corr = compute_rank_correlation(beliefs_list)

        uniform_prior_list.append({
            "trial": trial,
            "ece": calibration["ece"],
            "convergence_rate": convergence["convergence_rate"],
            "exploration_fraction": exploration["exploration_fraction"],
            "rank_correlation": rank_corr,
            "n_tested": calibration["n_tested"],
            "calibration_bins": calibration["bins"],
        })

        if (trial + 1) % 10 == 0:
            print(f"  Trial {trial + 1}/{config.n_trials} complete", file=sys.stderr)

    results: dict[str, Any] = {
        "config": config.__dict__,
        "source_informed": source_informed_list,
        "uniform_prior": uniform_prior_list,
    }
    return results


def summarize(results: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}

    for group_name in ["source_informed", "uniform_prior"]:
        trials: list[dict[str, Any]] = results[group_name]
        eces: list[float] = [float(t["ece"]) for t in trials]
        conv_rates: list[float] = [float(t["convergence_rate"]) for t in trials]
        explore_fracs: list[float] = [float(t["exploration_fraction"]) for t in trials]
        rank_corrs: list[float] = [float(t["rank_correlation"]) for t in trials]

        summary[group_name] = {
            "ece": {
                "mean": round(float(np.mean(eces)), 4),
                "std": round(float(np.std(eces)), 4),
                "p5": round(float(np.percentile(eces, 5)), 4),
                "p95": round(float(np.percentile(eces, 95)), 4),
            },
            "convergence_rate": {
                "mean": round(float(np.mean(conv_rates)), 4),
                "std": round(float(np.std(conv_rates)), 4),
            },
            "exploration_fraction": {
                "mean": round(float(np.mean(explore_fracs)), 4),
                "std": round(float(np.std(explore_fracs)), 4),
            },
            "rank_correlation": {
                "mean": round(float(np.mean(rank_corrs)), 4),
                "std": round(float(np.std(rank_corrs)), 4),
            },
        }

    # Requirement checks
    si: dict[str, Any] = summary["source_informed"]
    summary["requirement_checks"] = {
        "REQ-009_calibration": {
            "threshold": "ECE < 0.10",
            "result": si["ece"]["mean"],
            "pass": si["ece"]["mean"] < 0.10,
        },
        "REQ-010_exploration": {
            "threshold": "0.15 <= exploration <= 0.50",
            "result": si["exploration_fraction"]["mean"],
            "pass": 0.15 <= si["exploration_fraction"]["mean"] <= 0.50,
        },
    }

    return summary


def main() -> None:
    config = ExperimentConfig()

    print("=" * 60, file=sys.stderr)
    print("Experiment 2: Bayesian Confidence Calibration Simulation", file=sys.stderr)
    print(f"  {config.n_beliefs} beliefs, {config.n_sessions} sessions, "
          f"{config.n_trials} trials", file=sys.stderr)
    print(f"  Exploration weight: {config.exploration_weight}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    results = run_experiment(config)
    summary = summarize(results)

    # Print summary to stderr for human reading
    print("\n--- SUMMARY ---", file=sys.stderr)
    for group in ["source_informed", "uniform_prior"]:
        g: dict[str, Any] = summary[group]
        print(f"\n{group}:", file=sys.stderr)
        print(f"  ECE:          {g['ece']['mean']:.4f} +/- {g['ece']['std']:.4f} "
              f"(90% CI: {g['ece']['p5']:.4f} - {g['ece']['p95']:.4f})", file=sys.stderr)
        print(f"  Convergence:  {g['convergence_rate']['mean']:.4f} +/- "
              f"{g['convergence_rate']['std']:.4f}", file=sys.stderr)
        print(f"  Exploration:  {g['exploration_fraction']['mean']:.4f} +/- "
              f"{g['exploration_fraction']['std']:.4f}", file=sys.stderr)
        print(f"  Rank corr:    {g['rank_correlation']['mean']:.4f} +/- "
              f"{g['rank_correlation']['std']:.4f}", file=sys.stderr)

    print("\n--- REQUIREMENT CHECKS ---", file=sys.stderr)
    req_checks: dict[str, Any] = summary["requirement_checks"]
    for req_id, check in req_checks.items():
        status: str = "PASS" if check["pass"] else "FAIL"
        print(f"  {req_id}: {status} (threshold: {check['threshold']}, "
              f"result: {check['result']:.4f})", file=sys.stderr)

    # Write full results to stdout as JSON
    output: dict[str, Any] = {"summary": summary, "config": config.__dict__}
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
