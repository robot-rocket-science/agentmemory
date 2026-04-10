"""
Experiment 7: Variable-Relevance Thompson Sampling Test

Prior experiments (Exp 2, 5, 5b) used relevance=1.0 for all beliefs -- as if
every belief is equally relevant to every query. In practice, a database belief
is relevant to database queries and irrelevant to CSS queries.

This test: does Thompson sampling still produce good ranking when beliefs have
context-dependent relevance?

Setup:
- 200 beliefs across 4 domains (database, frontend, deployment, strategy)
- 5 query contexts, each making one domain highly relevant and others low
- Thompson sampling ranks by sample * relevance
- Measure: ECE, exploration, and a new metric -- domain precision (do
  high-relevance beliefs rank above low-relevance ones?)
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
from scipy.stats import spearmanr  # type: ignore[import-untyped]

from experiments.exp2_bayesian_calibration import (
    Belief, compute_calibration,
)


@dataclass
class DomainBelief(Belief):
    domain: str = ""


DOMAINS: list[str] = ["database", "frontend", "deployment", "strategy"]

# Relevance matrix: query_context x domain -> relevance score
# Each row sums to ~2.0 to keep total relevance comparable across contexts
RELEVANCE_MATRIX: dict[str, dict[str, float]] = {
    "database_task":    {"database": 0.9, "frontend": 0.1, "deployment": 0.3, "strategy": 0.1},
    "frontend_task":    {"database": 0.1, "frontend": 0.9, "deployment": 0.1, "strategy": 0.1},
    "deployment_task":  {"database": 0.2, "frontend": 0.1, "deployment": 0.9, "strategy": 0.2},
    "strategy_task":    {"database": 0.1, "frontend": 0.1, "deployment": 0.1, "strategy": 0.9},
    "cross_cutting":    {"database": 0.5, "frontend": 0.5, "deployment": 0.5, "strategy": 0.5},
}

TRUE_RATES: dict[str, float] = {"database": 0.75, "frontend": 0.65, "deployment": 0.55, "strategy": 0.80}


def create_domain_beliefs(n_per_domain: int = 50) -> list[DomainBelief]:
    beliefs: list[DomainBelief] = []
    bid: int = 0
    for domain in DOMAINS:
        for _ in range(n_per_domain):
            beliefs.append(DomainBelief(
                id=bid,
                source_type=domain,
                true_usefulness_rate=TRUE_RATES[domain],
                alpha=0.5,        # Jeffreys prior
                beta_param=0.5,
                domain=domain,
            ))
            bid += 1
    return beliefs


def run_trial(n_sessions: int, rng: np.random.Generator) -> dict[str, Any]:
    beliefs: list[DomainBelief] = create_domain_beliefs()
    n_retrievals: int = 10
    n_retrieve_k: int = 5

    # Cycle through query contexts
    contexts: list[str] = list(RELEVANCE_MATRIX.keys())
    exploration_count: int = 0
    total_count: int = 0
    domain_precision_scores: list[float] = []

    for session in range(n_sessions):
        # Pick a query context for this session
        ctx: str = contexts[session % len(contexts)]
        relevance_map: dict[str, float] = RELEVANCE_MATRIX[ctx]

        entropies: list[float] = [b.entropy for b in beliefs]
        median_ent: float = float(np.median(entropies)) if entropies else 0

        for _ in range(n_retrievals):
            # Thompson sampling with relevance weighting
            samples: list[tuple[DomainBelief, float, float]] = []
            for b in beliefs:
                s: float = float(rng.beta(max(b.alpha, 0.01), max(b.beta_param, 0.01)))
                relevance: float = relevance_map[b.domain]
                score: float = s * relevance
                samples.append((b, score, relevance))

            samples.sort(key=lambda x: x[1], reverse=True)
            retrieved: list[tuple[DomainBelief, float]] = [(b, rel) for b, _, rel in samples[:n_retrieve_k]]

            # Domain precision: what fraction of retrieved beliefs are from
            # the high-relevance domain?
            high_rel_domain: str = max(relevance_map, key=lambda k: relevance_map[k])
            from_target: int = sum(1 for b, _ in retrieved if b.domain == high_rel_domain)
            domain_precision_scores.append(from_target / n_retrieve_k)

            for b, _rel in retrieved:
                total_count += 1
                if b.entropy > median_ent:
                    exploration_count += 1

                b.retrieval_count += 1
                # Outcome depends on BOTH true rate and relevance
                # A correct belief that's irrelevant to the current task
                # should still count as "used" if retrieved -- the belief
                # itself is correct, relevance is a retrieval quality issue
                if rng.random() < 0.30:
                    b.update("ignored")
                elif rng.random() < b.true_usefulness_rate:
                    b.update("used")
                else:
                    b.update("harmful")

    cal: dict[str, Any] = compute_calibration(cast(list[Belief], beliefs))
    rank: float = 0.0
    tested: list[DomainBelief] = [b for b in beliefs if b.retrieval_count > 0]
    if len(tested) > 2:
        confs: list[float] = [b.confidence for b in tested]
        trues: list[float] = [b.true_usefulness_rate for b in tested]
        if len(set(trues)) > 1:
            rho_val: float = float(cast(Any, spearmanr(confs, trues)).statistic)
            rank = rho_val if not np.isnan(rho_val) else 0.0

    return {
        "ece": cal["ece"],
        "exploration": round(exploration_count / total_count, 4) if total_count else 0,
        "rank_correlation": round(rank, 4),
        "domain_precision": round(float(np.mean(domain_precision_scores)), 4),
        "beliefs_tested": len(tested),
        "beliefs_total": len(beliefs),
    }


def main() -> None:
    rng_base: np.random.Generator = np.random.default_rng(42)
    n_trials: int = 100
    n_sessions: int = 50

    print("=" * 60, file=sys.stderr)
    print("Experiment 7: Variable-Relevance Thompson Sampling", file=sys.stderr)
    print(f"  200 beliefs, 4 domains, 5 query contexts, {n_sessions} sessions, "
          f"{n_trials} trials", file=sys.stderr)
    print(f"  Jeffreys prior Beta(0.5, 0.5)", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    trial_results: list[dict[str, Any]] = []
    for trial in range(n_trials):
        seed: int = int(cast(int, rng_base.integers(0, 2**32)))
        rng: np.random.Generator = np.random.default_rng(seed)
        result: dict[str, Any] = run_trial(n_sessions, rng)
        trial_results.append(result)
        if (trial + 1) % 25 == 0:
            print(f"  Trial {trial + 1}/{n_trials}", file=sys.stderr)

    eces: list[float] = [float(r["ece"]) for r in trial_results]
    expls: list[float] = [float(r["exploration"]) for r in trial_results]
    ranks: list[float] = [float(r["rank_correlation"]) for r in trial_results]
    dom_precs: list[float] = [float(r["domain_precision"]) for r in trial_results]
    tested: list[float] = [float(r["beliefs_tested"]) for r in trial_results]

    print(f"\n{'='*60}", file=sys.stderr)
    print("RESULTS", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"  ECE:              {np.mean(eces):.4f} +/- {np.std(eces):.4f} "
          f"(90%: {np.percentile(eces,5):.4f} - {np.percentile(eces,95):.4f})", file=sys.stderr)
    print(f"  Exploration:      {np.mean(expls):.4f} +/- {np.std(expls):.4f}", file=sys.stderr)
    print(f"  Rank correlation: {np.mean(ranks):.4f} +/- {np.std(ranks):.4f}", file=sys.stderr)
    print(f"  Domain precision: {np.mean(dom_precs):.4f} +/- {np.std(dom_precs):.4f}", file=sys.stderr)
    print(f"  Beliefs tested:   {np.mean(tested):.0f}/{trial_results[0]['beliefs_total']}", file=sys.stderr)

    # Compare to Exp 5b (uniform relevance)
    print(f"\n  Comparison to Exp 5b (uniform relevance):", file=sys.stderr)
    print(f"  {'Metric':<20} {'Exp 5b (uniform)':>18} {'Exp 7 (variable)':>18}", file=sys.stderr)
    print(f"  {'ECE':<20} {'0.0658':>18} {np.mean(eces):>18.4f}", file=sys.stderr)
    print(f"  {'Exploration':<20} {'0.1943':>18} {np.mean(expls):>18.4f}", file=sys.stderr)
    print(f"  {'Rank correlation':<20} {'N/A':>18} {np.mean(ranks):>18.4f}", file=sys.stderr)
    print(f"  {'Domain precision':<20} {'N/A':>18} {np.mean(dom_precs):>18.4f}", file=sys.stderr)

    # Requirement checks
    ece_pass: bool = float(np.mean(eces)) < 0.10
    expl_pass: bool = 0.15 <= float(np.mean(expls)) <= 0.50
    print(f"\n  REQ-009 (ECE < 0.10): {'PASS' if ece_pass else 'FAIL'} ({np.mean(eces):.4f})", file=sys.stderr)
    print(f"  REQ-010 (exploration 0.15-0.50): {'PASS' if expl_pass else 'FAIL'} ({np.mean(expls):.4f})", file=sys.stderr)

    summary: dict[str, Any] = {
        "ece_mean": round(float(np.mean(eces)), 4),
        "ece_std": round(float(np.std(eces)), 4),
        "exploration_mean": round(float(np.mean(expls)), 4),
        "rank_correlation_mean": round(float(np.mean(ranks)), 4),
        "domain_precision_mean": round(float(np.mean(dom_precs)), 4),
        "beliefs_tested_mean": round(float(np.mean(tested)), 1),
        "req009_pass": ece_pass,
        "req010_pass": expl_pass,
    }

    Path("experiments/exp7_results.json").write_text(json.dumps(summary, indent=2))
    print(f"\nOutput: experiments/exp7_results.json", file=sys.stderr)


if __name__ == "__main__":
    main()
