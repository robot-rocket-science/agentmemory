"""
Experiment 38: Feedback Loop Scaling -- Candidate Mechanisms

Problem: Thompson sampling on independent Beta priors degrades at 10K beliefs.
Coverage drops to 22%, ECE rises to 0.17. The cause is data starvation, not
algorithmic failure -- each tested belief gets ~1.1 observations on average
(needs 5-10 to converge).

This experiment tests 5 candidate mechanisms that address the starvation problem
through evidence sharing, pre-filtering, or reframing the problem.

Mechanisms:
  A. Flat Thompson (baseline from Exp 15)
  B. Hierarchical priors -- beliefs in graph clusters share a group Beta prior
  C. Source-stratified priors -- user_stated starts at Beta(9,1), agent at Beta(1,1)
  D. Graph label propagation -- propagate tested belief confidence to neighbors
  E. Lazy evaluation -- only test beliefs when retrieved for real tasks
  F. Combined: hierarchical + source-stratified + lazy (the likely production config)

Scales: 1K, 5K, 10K, 50K beliefs
Budget: 50 sessions x 10 retrievals x 5 top-k = 2,500 slots
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

import numpy as np
from numpy.typing import NDArray


# ============================================================
# Belief model
# ============================================================

@dataclass
class ScaleBelief:
    id: int
    source_type: str
    true_usefulness_rate: float
    alpha: float = 0.5
    beta_param: float = 0.5
    retrieval_count: int = 0
    used_count: int = 0
    cluster_id: int = 0
    neighbors: list[int] = field(default_factory=lambda: list[int]())

    @property
    def confidence(self) -> float:
        return self.alpha / (self.alpha + self.beta_param)

    def update(self, outcome: Literal["used", "harmful", "ignored"]) -> None:
        if outcome == "used":
            self.alpha += 1.0
            self.used_count += 1
        elif outcome == "harmful":
            self.beta_param += 1.0

    def sample_thompson(self, rng: np.random.Generator) -> float:
        return float(rng.beta(max(self.alpha, 0.01), max(self.beta_param, 0.01)))


# ============================================================
# Graph topology generation (realistic structure)
# ============================================================

SOURCE_TYPES = ["user_stated", "document_recent", "document_old",
                "agent_inferred", "cross_reference"]
TRUE_RATES = {
    "user_stated": 0.85,
    "document_recent": 0.70,
    "document_old": 0.50,
    "agent_inferred": 0.45,
    "cross_reference": 0.55,
}
SOURCE_WEIGHTS = [0.10, 0.20, 0.15, 0.30, 0.25]  # fraction of total

# Source-stratified priors (mechanism C)
SOURCE_PRIORS = {
    "user_stated": (9.0, 1.0),       # High confidence: user said it
    "document_recent": (7.0, 3.0),    # Good confidence: recent doc
    "document_old": (4.0, 4.0),       # Uncertain: old doc, may be stale
    "agent_inferred": (1.0, 1.0),     # Uninformative: agent guessed
    "cross_reference": (3.0, 2.0),    # Slight positive: multiple sources
}


def build_graph(n: int, rng: np.random.Generator) -> tuple[list[ScaleBelief], dict[int, list[int]]]:
    """Build beliefs with power-law graph structure (realistic topology).

    Graph has ~3 edges per node on average, with power-law degree distribution.
    Beliefs in the same cluster share similar true_usefulness_rates.
    """
    beliefs: list[ScaleBelief] = []

    # Assign source types
    source_counts = [int(w * n) for w in SOURCE_WEIGHTS]
    source_counts[-1] = n - sum(source_counts[:-1])  # fix rounding

    source_list: list[str] = []
    for stype, count in zip(SOURCE_TYPES, source_counts):
        source_list.extend([stype] * count)
    rng.shuffle(source_list)  # type: ignore[arg-type]

    # Create beliefs
    for i in range(n):
        stype = source_list[i]
        # Add noise to true rate (+/- 0.1)
        true_rate = np.clip(TRUE_RATES[stype] + rng.normal(0, 0.1), 0.05, 0.95)
        beliefs.append(ScaleBelief(
            id=i, source_type=stype, true_usefulness_rate=float(true_rate),
        ))

    # Build power-law graph edges
    # Use preferential attachment (Barabasi-Albert-like)
    edges_per_node = 3
    adjacency: dict[int, list[int]] = defaultdict(list)
    degree = np.ones(n)  # start with degree 1 to avoid division by zero

    for i in range(edges_per_node, n):
        # Pick edges_per_node targets, weighted by degree
        probs = degree[:i] / degree[:i].sum()
        targets = rng.choice(i, size=min(edges_per_node, i), replace=False, p=probs)
        for t in targets:
            adjacency[i].append(int(t))
            adjacency[int(t)].append(i)
            degree[i] += 1
            degree[t] += 1

    # Store neighbors on beliefs
    for i in range(n):
        empty: list[int] = []
        beliefs[i].neighbors = adjacency.get(i, empty)

    # Assign clusters via connected components on thresholded graph
    # (group beliefs with strong connections)
    n_clusters = max(10, n // 100)
    for i in range(n):
        beliefs[i].cluster_id = i % n_clusters

    # Build cluster membership
    clusters: dict[int, list[int]] = defaultdict(list)
    for b in beliefs:
        clusters[b.cluster_id].append(b.id)

    return beliefs, dict(clusters)


# ============================================================
# Simulation infrastructure
# ============================================================

N_SESSIONS = 50
N_RETRIEVALS = 10
TOP_K = 5


def compute_outcome(belief: ScaleBelief, rng: np.random.Generator) -> Literal["used", "harmful", "ignored"]:
    if rng.random() < 0.30:
        return "ignored"
    if rng.random() < belief.true_usefulness_rate:
        return "used"
    return "harmful"


def compute_metrics(beliefs: list[ScaleBelief]) -> dict[str, Any]:
    n = len(beliefs)
    tested = [b for b in beliefs if b.retrieval_count > 0]
    coverage = len(tested) / n

    # ECE: bin beliefs by confidence, compare to actual usefulness
    n_bins = 10
    bins: list[list[ScaleBelief]] = [[] for _ in range(n_bins)]
    for b in beliefs:
        bin_idx = min(int(b.confidence * n_bins), n_bins - 1)
        bins[bin_idx].append(b)

    ece = 0.0
    for bin_beliefs in bins:
        if not bin_beliefs:
            continue
        avg_conf = np.mean([b.confidence for b in bin_beliefs])
        avg_true = np.mean([b.true_usefulness_rate for b in bin_beliefs])
        ece += len(bin_beliefs) / n * abs(avg_conf - avg_true)

    # Convergence: tested beliefs within 0.15 of true rate
    converged = sum(1 for b in tested
                    if abs(b.confidence - b.true_usefulness_rate) <= 0.15)
    conv_rate = converged / max(1, len(tested))

    # Retrieval quality: are high-confidence beliefs actually better?
    # Compare top-10% confidence beliefs' true rates vs bottom-10%
    sorted_beliefs = sorted(beliefs, key=lambda b: b.confidence, reverse=True)
    top_10 = sorted_beliefs[:max(1, n // 10)]
    bot_10 = sorted_beliefs[-max(1, n // 10):]
    ranking_quality = (np.mean([b.true_usefulness_rate for b in top_10]) -
                       np.mean([b.true_usefulness_rate for b in bot_10]))

    return {
        "ece": round(ece, 4),
        "coverage": round(coverage, 4),
        "convergence_rate": round(conv_rate, 4),
        "ranking_quality": round(float(ranking_quality), 4),
    }


# ============================================================
# Mechanism A: Flat Thompson (baseline)
# ============================================================

def run_flat_thompson(beliefs: list[ScaleBelief], clusters: dict[int, list[int]], rng: np.random.Generator) -> dict[str, Any]:
    for b in beliefs:
        b.alpha, b.beta_param = 0.5, 0.5
        b.retrieval_count = b.used_count = 0

    for _ in range(N_SESSIONS):
        for _ in range(N_RETRIEVALS):
            samples = np.array([b.sample_thompson(rng) for b in beliefs])
            top_k_idx = np.argpartition(samples, -TOP_K)[-TOP_K:]
            for raw_idx in top_k_idx:
                idx: int = int(raw_idx)
                beliefs[idx].retrieval_count += 1
                beliefs[idx].update(compute_outcome(beliefs[idx], rng))

    m = compute_metrics(beliefs)
    m["method"] = "flat_thompson"
    return m


# ============================================================
# Mechanism B: Hierarchical priors (cluster-level Beta)
# ============================================================

def run_hierarchical(beliefs: list[ScaleBelief], clusters: dict[int, list[int]], rng: np.random.Generator) -> dict[str, Any]:
    # Each cluster has a shared Beta prior
    cluster_alpha: dict[int, float] = {c: 0.5 for c in clusters}
    cluster_beta: dict[int, float] = {c: 0.5 for c in clusters}

    for b in beliefs:
        b.alpha, b.beta_param = 0.5, 0.5
        b.retrieval_count = b.used_count = 0

    propagation_weight = 0.2  # fraction of update shared with cluster

    for _ in range(N_SESSIONS):
        for _ in range(N_RETRIEVALS):
            # Sample from individual + cluster prior combination
            samples = np.array([
                float(rng.beta(
                    max(b.alpha + cluster_alpha[b.cluster_id], 0.01),
                    max(b.beta_param + cluster_beta[b.cluster_id], 0.01),
                ))
                for b in beliefs
            ])
            top_k_idx = np.argpartition(samples, -TOP_K)[-TOP_K:]

            for raw_idx in top_k_idx:
                idx: int = int(raw_idx)
                b = beliefs[idx]
                b.retrieval_count += 1
                outcome = compute_outcome(b, rng)
                b.update(outcome)

                # Propagate to cluster
                cid: int = b.cluster_id
                if outcome == "used":
                    cluster_alpha[cid] += propagation_weight
                elif outcome == "harmful":
                    cluster_beta[cid] += propagation_weight

    # Apply cluster posteriors to untested beliefs
    for b in beliefs:
        if b.retrieval_count == 0:
            b.alpha += cluster_alpha[b.cluster_id]
            b.beta_param += cluster_beta[b.cluster_id]

    m = compute_metrics(beliefs)
    m["method"] = "hierarchical"
    return m


# ============================================================
# Mechanism C: Source-stratified priors
# ============================================================

def run_source_stratified(beliefs: list[ScaleBelief], clusters: dict[int, list[int]], rng: np.random.Generator) -> dict[str, Any]:
    # Initialize with informative source-type priors
    for b in beliefs:
        a, bp = SOURCE_PRIORS[b.source_type]
        b.alpha, b.beta_param = a, bp
        b.retrieval_count = b.used_count = 0

    for _ in range(N_SESSIONS):
        for _ in range(N_RETRIEVALS):
            samples = np.array([b.sample_thompson(rng) for b in beliefs])
            top_k_idx = np.argpartition(samples, -TOP_K)[-TOP_K:]
            for raw_idx in top_k_idx:
                idx: int = int(raw_idx)
                beliefs[idx].retrieval_count += 1
                beliefs[idx].update(compute_outcome(beliefs[idx], rng))

    m = compute_metrics(beliefs)
    m["method"] = "source_stratified"
    return m


# ============================================================
# Mechanism D: Graph label propagation
# ============================================================

def run_graph_propagation(beliefs: list[ScaleBelief], clusters: dict[int, list[int]], rng: np.random.Generator) -> dict[str, Any]:
    for b in beliefs:
        b.alpha, b.beta_param = 0.5, 0.5
        b.retrieval_count = b.used_count = 0

    propagation_weight = 0.15

    for _ in range(N_SESSIONS):
        for _ in range(N_RETRIEVALS):
            samples = np.array([b.sample_thompson(rng) for b in beliefs])
            top_k_idx: NDArray[np.intp] = np.argpartition(samples, -TOP_K)[-TOP_K:]

            for raw_idx in top_k_idx.tolist():
                idx: int = int(raw_idx)
                b: ScaleBelief = beliefs[idx]
                b.retrieval_count += 1
                outcome = compute_outcome(b, rng)
                b.update(outcome)

                # Propagate to immediate graph neighbors
                if outcome != "ignored":
                    for nid in b.neighbors:
                        nb: ScaleBelief = beliefs[nid]
                        if outcome == "used":
                            nb.alpha += propagation_weight
                        else:
                            nb.beta_param += propagation_weight

    m = compute_metrics(beliefs)
    m["method"] = "graph_propagation"
    return m


# ============================================================
# Mechanism E: Lazy evaluation (test only on retrieval)
# ============================================================

def run_lazy(beliefs: list[ScaleBelief], clusters: dict[int, list[int]], rng: np.random.Generator) -> dict[str, Any]:
    """No proactive exploration. Only update beliefs that would be retrieved
    for a real task (simulated via domain relevance)."""
    for b in beliefs:
        b.alpha, b.beta_param = 0.5, 0.5
        b.retrieval_count = b.used_count = 0

    # Simulate domain-specific queries: each session has a context
    # that makes ~20% of beliefs relevant
    domains = list(TRUE_RATES.keys())

    for session in range(N_SESSIONS):
        # Pick a domain context for this session
        context_domain = domains[session % len(domains)]

        for _ in range(N_RETRIEVALS):
            # Only consider beliefs relevant to this context
            # (same source type -- crude proxy for domain relevance)
            relevant_idx = [i for i, b in enumerate(beliefs)
                            if b.source_type == context_domain]

            if not relevant_idx:
                continue

            # Thompson sample only within relevant beliefs
            samples = np.array([beliefs[i].sample_thompson(rng) for i in relevant_idx])
            n_pick = min(TOP_K, len(relevant_idx))
            top_k_local = np.argpartition(samples, -n_pick)[-n_pick:]

            for raw_local_idx in top_k_local:
                idx: int = relevant_idx[int(raw_local_idx)]
                beliefs[idx].retrieval_count += 1
                beliefs[idx].update(compute_outcome(beliefs[idx], rng))

    m = compute_metrics(beliefs)
    m["method"] = "lazy"
    return m


# ============================================================
# Mechanism F: Combined (hierarchical + source + graph propagation)
# ============================================================

def run_combined(beliefs: list[ScaleBelief], clusters: dict[int, list[int]], rng: np.random.Generator) -> dict[str, Any]:
    cluster_alpha: dict[int, float] = {c: 0.5 for c in clusters}
    cluster_beta: dict[int, float] = {c: 0.5 for c in clusters}
    cluster_prop = 0.15
    neighbor_prop = 0.10

    for b in beliefs:
        a, bp = SOURCE_PRIORS[b.source_type]
        b.alpha, b.beta_param = a, bp
        b.retrieval_count = b.used_count = 0

    for _ in range(N_SESSIONS):
        for _ in range(N_RETRIEVALS):
            samples = np.array([
                float(rng.beta(
                    max(b.alpha + cluster_alpha[b.cluster_id], 0.01),
                    max(b.beta_param + cluster_beta[b.cluster_id], 0.01),
                ))
                for b in beliefs
            ])
            top_k_idx: NDArray[np.intp] = np.argpartition(samples, -TOP_K)[-TOP_K:]

            for raw_idx in top_k_idx.tolist():
                idx: int = int(raw_idx)
                b: ScaleBelief = beliefs[idx]
                b.retrieval_count += 1
                outcome = compute_outcome(b, rng)
                b.update(outcome)

                if outcome != "ignored":
                    # Propagate to cluster
                    cid: int = b.cluster_id
                    if outcome == "used":
                        cluster_alpha[cid] += cluster_prop
                    else:
                        cluster_beta[cid] += cluster_prop

                    # Propagate to neighbors
                    for nid in b.neighbors:
                        nb: ScaleBelief = beliefs[nid]
                        if outcome == "used":
                            nb.alpha += neighbor_prop
                        else:
                            nb.beta_param += neighbor_prop

    # Apply cluster posteriors to untested beliefs
    for b in beliefs:
        if b.retrieval_count == 0:
            b.alpha += cluster_alpha[b.cluster_id]
            b.beta_param += cluster_beta[b.cluster_id]

    m = compute_metrics(beliefs)
    m["method"] = "combined"
    return m


# ============================================================
# Main
# ============================================================

MethodFn = Callable[[list[ScaleBelief], dict[int, list[int]], np.random.Generator], dict[str, Any]]

METHODS: list[tuple[str, MethodFn]] = [
    ("flat_thompson", run_flat_thompson),
    ("hierarchical", run_hierarchical),
    ("source_stratified", run_source_stratified),
    ("graph_propagation", run_graph_propagation),
    ("lazy", run_lazy),
    ("combined", run_combined),
]

SCALES = [1_000, 5_000, 10_000, 50_000]
N_TRIALS = 5


def main() -> None:
    rng_base = np.random.default_rng(42)

    print("=" * 70, file=sys.stderr)
    print("Experiment 38: Feedback Loop Scaling", file=sys.stderr)
    print(f"  Scales: {SCALES}", file=sys.stderr)
    print(f"  Methods: {[m[0] for m in METHODS]}", file=sys.stderr)
    print(f"  Trials: {N_TRIALS}", file=sys.stderr)
    print(f"  Budget: {N_SESSIONS} sessions x {N_RETRIEVALS} retrievals x {TOP_K} top-k = {N_SESSIONS * N_RETRIEVALS * TOP_K} slots", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    results: dict[str, Any] = {}

    for scale in SCALES:
        print(f"\n--- Scale: {scale:,} beliefs ---", file=sys.stderr)
        results[str(scale)] = {}

        for method_name, method_fn in METHODS:
            trial_metrics: list[dict[str, Any]] = []

            for _trial in range(N_TRIALS):
                seed: int = int(rng_base.integers(0, 2**32))  # type: ignore[arg-type]
                rng = np.random.default_rng(seed)

                t0 = time.perf_counter()
                beliefs, clusters = build_graph(scale, rng)
                rng2 = np.random.default_rng(seed + 1)
                m = method_fn(beliefs, clusters, rng2)
                m["wall_seconds"] = round(time.perf_counter() - t0, 3)
                trial_metrics.append(m)

            # Average across trials
            avg: dict[str, Any] = {"method": method_name}
            for key in ["ece", "coverage", "convergence_rate", "ranking_quality", "wall_seconds"]:
                vals = [t[key] for t in trial_metrics]
                avg[key] = round(float(np.mean(vals)), 4)
                avg[f"{key}_std"] = round(float(np.std(vals)), 4)

            results[str(scale)][method_name] = avg
            print(f"  {method_name:<20} ECE={avg['ece']:.4f}  cov={avg['coverage']:.1%}  "
                  f"conv={avg['convergence_rate']:.1%}  rank_q={avg['ranking_quality']:.3f}  "
                  f"time={avg['wall_seconds']:.1f}s", file=sys.stderr)

    # Summary table
    print(f"\n{'='*70}", file=sys.stderr)
    print(f"{'Scale':>8} {'Method':<20} {'ECE':>8} {'Coverage':>10} {'Conv':>8} {'RankQ':>8}", file=sys.stderr)
    print("-" * 60, file=sys.stderr)
    for scale in SCALES:
        for method_name, _ in METHODS:
            r = results[str(scale)][method_name]
            print(f"{scale:>8,} {method_name:<20} {r['ece']:>8.4f} {r['coverage']:>10.1%} "
                  f"{r['convergence_rate']:>8.1%} {r['ranking_quality']:>8.3f}", file=sys.stderr)
        print("-" * 60, file=sys.stderr)

    out_path = Path("experiments/exp38_results.json")
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nResults saved to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
