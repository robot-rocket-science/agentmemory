"""Exp 90: Jacobian and Hamiltonian analysis of belief scoring dynamics.

Treats the belief scoring algorithm as a dynamical system:
  State: (alpha, beta) per belief
  Inputs: feedback events (used, ignored, harmful), decay, type priors
  Output: confidence = alpha / (alpha + beta)

Jacobian: sensitivity of confidence to each input parameter.
Hamiltonian: energy analysis of the belief population trajectory,
  conservation tests, and regime classification.

Methodology adapted from alpha-seek Jacobian/Hamiltonian diagnostic
skills (jacobian.md, hamiltonian.md).
"""
from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Jacobian: Sensitivity Analysis
# ---------------------------------------------------------------------------


@dataclass
class JacobianResult:
    """Partial derivatives of confidence w.r.t. system parameters."""

    # Operating point
    alpha: float
    beta: float
    confidence: float

    # Partial derivatives (analytical)
    dc_dalpha: float  # d(conf)/d(alpha) -- sensitivity to positive feedback
    dc_dbeta: float  # d(conf)/d(beta) -- sensitivity to negative feedback
    dc_dweight: float  # d(conf)/d(weight) for a "used" event

    # Cost per +0.1 confidence
    used_events_per_10pp: float  # how many "used" events to gain +0.1 conf
    ignored_events_per_10pp: float  # how many "ignored" events to lose -0.1 conf
    harmful_events_to_50pct: float  # events to drop to 0.5


def compute_jacobian(alpha: float, beta: float) -> JacobianResult:
    """Compute the Jacobian at an operating point (alpha, beta).

    Confidence = alpha / (alpha + beta)

    Partial derivatives:
      d(conf)/d(alpha) = beta / (alpha + beta)^2
      d(conf)/d(beta) = -alpha / (alpha + beta)^2

    For a "used" event with weight w:
      d(conf)/d(w) = d(conf)/d(alpha) * d(alpha)/d(w) = beta / (alpha + beta)^2

    For an "ignored" event (beta += 0.1*w):
      d(conf)/d(w) = d(conf)/d(beta) * 0.1 = -0.1 * alpha / (alpha + beta)^2
    """
    s: float = alpha + beta
    conf: float = alpha / s if s > 0 else 0.5

    dc_da: float = beta / (s * s) if s > 0 else 0.0
    dc_db: float = -alpha / (s * s) if s > 0 else 0.0

    # For "used" event: alpha += 1.0 (weight=1.0)
    dc_dw_used: float = dc_da  # d(conf)/d(weight) for used

    # Cost analysis: how many events to move confidence by 0.1?
    # After n "used" events: conf_new = (alpha + n) / (alpha + n + beta)
    # Solve: conf_new - conf = 0.1
    # (alpha + n) / (alpha + n + beta) - alpha/s = 0.1
    # n = 0.1 * s * (s + n) / beta ... iterative, use approximation
    # First-order: n ~= 0.1 / dc_da if dc_da > 0
    used_per_10pp: float = 0.1 / dc_da if dc_da > 0.001 else float("inf")

    # For "ignored": beta += 0.1 per event
    # n events: conf_new = alpha / (alpha + beta + 0.1*n)
    # Loss of 0.1: alpha/(s + 0.1n) = conf - 0.1
    # n = (alpha/(conf-0.1) - s) / 0.1
    if conf > 0.1:
        ignored_per_10pp: float = (alpha / (conf - 0.1) - s) / 0.1
    else:
        ignored_per_10pp = float("inf")

    # "harmful" events to reach 0.5: beta += weight until alpha/(alpha+beta_new) = 0.5
    # alpha = alpha + beta_new -> beta_new = alpha -> delta_beta = alpha - beta
    harmful_to_50: float = max(0.0, alpha - beta)

    return JacobianResult(
        alpha=alpha,
        beta=beta,
        confidence=conf,
        dc_dalpha=dc_da,
        dc_dbeta=dc_db,
        dc_dweight=dc_dw_used,
        used_events_per_10pp=used_per_10pp,
        ignored_events_per_10pp=ignored_per_10pp,
        harmful_events_to_50pct=harmful_to_50,
    )


# ---------------------------------------------------------------------------
# Hamiltonian: Energy and Regime Analysis
# ---------------------------------------------------------------------------


@dataclass
class BeliefTrajectory:
    """Time-series of a belief's confidence evolution."""

    belief_id: str
    belief_type: str
    timestamps: list[str]
    alphas: list[float]
    betas: list[float]
    confidences: list[float]


@dataclass
class HamiltonianResult:
    """Energy analysis of belief population."""

    # Population-level
    total_kinetic: float  # sum of |d(conf)/dt|^2 -- how fast things change
    total_potential: float  # sum of -conf -- accumulated confidence
    hamiltonian: float  # T + V
    regime: str  # MOMENTUM, ACCUMULATION, QUIESCENT, TRANSITION

    # Gini coefficient
    gini: float

    # Conservation test
    conservation: str  # DISSIPATIVE, INJECTING, CONSERVED

    # Per-tier breakdown
    tier_counts: dict[str, int]
    tier_avg_conf: dict[str, float]


def classify_regime(kinetic: float, potential: float) -> str:
    """Classify the belief population regime."""
    t_norm: float = kinetic / max(abs(potential), 0.001)
    if t_norm > 1.0:
        return "MOMENTUM"  # rapid changes dominate
    if t_norm < 0.1:
        return "ACCUMULATION"  # steady state, confidence built up
    if t_norm > 0.5 and abs(potential) > 1.0:
        return "TRANSITION"
    return "QUIESCENT"


def compute_hamiltonian(db_path: str) -> HamiltonianResult:
    """Compute Hamiltonian diagnostics on the belief population."""
    conn: sqlite3.Connection = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows: list[sqlite3.Row] = conn.execute(
        """SELECT confidence, belief_type, source_type, locked,
                  alpha, beta_param
           FROM beliefs WHERE superseded_by IS NULL"""
    ).fetchall()

    confs: list[float] = [float(r["confidence"]) for r in rows]
    n: int = len(confs)

    if n == 0:
        conn.close()
        return HamiltonianResult(
            total_kinetic=0,
            total_potential=0,
            hamiltonian=0,
            regime="QUIESCENT",
            gini=0,
            conservation="CONSERVED",
            tier_counts={},
            tier_avg_conf={},
        )

    # Potential energy: V = -sum(conf) (more confidence = lower potential)
    total_v: float = -sum(confs)

    # Kinetic energy: proxy from confidence variance
    # High variance = beliefs are moving apart = high kinetic energy
    mean_c: float = sum(confs) / n
    variance: float = sum((c - mean_c) ** 2 for c in confs) / n
    total_t: float = variance * n  # scale by population

    h: float = total_t + total_v
    regime: str = classify_regime(total_t, total_v)

    # Gini coefficient
    sorted_c: list[float] = sorted(confs)
    gini_num: float = sum(
        (2 * (i + 1) - n - 1) * sorted_c[i] for i in range(n)
    )
    gini: float = gini_num / (n * sum(sorted_c)) if sum(sorted_c) > 0 else 0

    # Conservation: is H stable? (would need time series, approximate from
    # feedback vs creation ratio)
    with_feedback: int = sum(
        1
        for r in rows
        if float(r["alpha"]) != 1.9
        and float(r["alpha"]) != 0.6
        and float(r["alpha"]) != 0.5
    )
    feedback_ratio: float = with_feedback / n if n > 0 else 0
    if feedback_ratio > 0.5:
        conservation = "DISSIPATIVE"  # feedback is reshaping distribution
    elif feedback_ratio < 0.1:
        conservation = "CONSERVED"  # nothing is changing
    else:
        conservation = "WEAKLY_DISSIPATIVE"

    # Tier breakdown
    tiers: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        c: float = float(r["confidence"])
        if c >= 0.9:
            tiers["locked/correction"].append(c)
        elif c >= 0.7:
            tiers["high"].append(c)
        elif c >= 0.5:
            tiers["medium"].append(c)
        elif c >= 0.3:
            tiers["low"].append(c)
        else:
            tiers["very_low"].append(c)

    tier_counts: dict[str, int] = {k: len(v) for k, v in tiers.items()}
    tier_avg: dict[str, float] = {
        k: sum(v) / len(v) if v else 0 for k, v in tiers.items()
    }

    conn.close()
    return HamiltonianResult(
        total_kinetic=total_t,
        total_potential=total_v,
        hamiltonian=h,
        regime=regime,
        gini=gini,
        conservation=conservation,
        tier_counts=tier_counts,
        tier_avg_conf=tier_avg,
    )


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------


def main() -> None:
    db_path: str = str(
        Path.home() / ".agentmemory" / "projects" / "2e7ed55e017a" / "memory.db"
    )

    print("=" * 70)
    print("Exp 90: Belief Scoring Dynamics (Jacobian + Hamiltonian)")
    print("=" * 70)

    # --- Jacobian at key operating points ---
    print("\n## JACOBIAN: Sensitivity Analysis")
    print()

    operating_points: list[tuple[str, float, float]] = [
        ("Agent FACT (current cluster)", 1.90, 1.00),
        ("Agent FACT (correct prior)", 0.60, 1.00),
        ("Agent FACT (after 5 used)", 5.60, 1.00),
        ("Agent FACT (after 5 ignored)", 0.60, 1.50),
        ("User correction", 9.00, 0.50),
        ("Agent requirement", 1.80, 0.50),
        ("Agent assumption", 0.50, 1.00),
    ]

    print(
        f"{'Operating Point':35s}  {'Conf':>5s}  {'dC/da':>6s}  "
        f"{'dC/db':>6s}  {'Used/10pp':>9s}  {'Ign/10pp':>8s}  {'Harm->50':>8s}"
    )
    print("-" * 95)

    for name, a, b in operating_points:
        j: JacobianResult = compute_jacobian(a, b)
        used_str: str = (
            f"{j.used_events_per_10pp:.1f}"
            if j.used_events_per_10pp < 1000
            else "inf"
        )
        ign_str: str = (
            f"{j.ignored_events_per_10pp:.1f}"
            if j.ignored_events_per_10pp < 1000
            else "inf"
        )
        print(
            f"{name:35s}  {j.confidence:5.3f}  {j.dc_dalpha:6.4f}  "
            f"{j.dc_dbeta:6.4f}  {used_str:>9s}  {ign_str:>8s}  {j.harmful_events_to_50pct:8.1f}"
        )

    # Key insight
    print()
    print("KEY INSIGHT:")
    j_cluster = compute_jacobian(1.90, 1.00)
    j_correct = compute_jacobian(0.60, 1.00)
    print(
        f"  At the 0.66 cluster: dC/dalpha = {j_cluster.dc_dalpha:.4f}"
    )
    print(
        f"  At the correct 0.375: dC/dalpha = {j_correct.dc_dalpha:.4f}"
    )
    print(
        f"  Sensitivity ratio: {j_correct.dc_dalpha / j_cluster.dc_dalpha:.1f}x"
    )
    print(
        f"  Beliefs at 0.375 are {j_correct.dc_dalpha / j_cluster.dc_dalpha:.1f}x "
        f"MORE responsive to feedback than beliefs at 0.66."
    )
    print(
        f"  Recalibrating to correct priors makes the feedback loop "
        f"{j_correct.dc_dalpha / j_cluster.dc_dalpha:.1f}x more effective."
    )

    # --- Hamiltonian ---
    print()
    print("## HAMILTONIAN: Population Energy Analysis")
    print()

    h: HamiltonianResult = compute_hamiltonian(db_path)

    print(f"  Kinetic energy (T):  {h.total_kinetic:.2f}")
    print(f"  Potential energy (V): {h.total_potential:.2f}")
    print(f"  Hamiltonian (H=T+V): {h.hamiltonian:.2f}")
    print(f"  Regime:              {h.regime}")
    print(f"  Conservation:        {h.conservation}")
    print(f"  Gini coefficient:    {h.gini:.4f}")
    print()
    print("  Tier breakdown:")
    for tier in ["locked/correction", "high", "medium", "low", "very_low"]:
        count: int = h.tier_counts.get(tier, 0)
        avg: float = h.tier_avg_conf.get(tier, 0)
        print(f"    {tier:20s}  {count:6d}  avg={avg:.3f}")

    # Diagnosis
    print()
    print("## DIAGNOSIS")
    print()
    if h.gini < 0.05:
        print("  CRITICAL: Gini < 0.05 -- near-zero diversity.")
        print("  The belief population is effectively uniform.")
        print("  Thompson sampling degenerates to random selection.")
    elif h.gini < 0.15:
        print("  WARNING: Gini < 0.15 -- low diversity.")
        print("  Most beliefs are indistinguishable from each other.")
    else:
        print("  OK: Gini >= 0.15 -- adequate diversity.")

    if h.regime == "QUIESCENT":
        print("  STAGNANT: Low kinetic energy -- beliefs are not moving.")
        print("  The feedback loop is not creating differentiation.")
    elif h.regime == "ACCUMULATION":
        print("  HEALTHY: Beliefs are accumulating confidence steadily.")

    if h.conservation == "CONSERVED":
        print("  FROZEN: H is approximately conserved -- no net change.")
        print("  The system is in equilibrium. Feedback isn't perturbing it.")

    # Recommendation
    print()
    print("## RECOMMENDED FIX")
    print()
    print("  1. Run recalibrate_scores() to reset alpha=1.9 cluster")
    print("     to type-specific priors (already committed)")
    print("  2. The recalibrated beliefs at alpha=0.6 will have")
    print(f"     {j_correct.dc_dalpha / j_cluster.dc_dalpha:.1f}x higher "
          f"sensitivity to feedback")
    print("  3. Existing feedback mechanism (weight=1.0 per used,")
    print("     0.1 per ignored) is adequate IF beliefs start at")
    print("     the correct lower prior where sensitivity is higher")
    print("  4. Monitor: re-run this analysis after recalibration")
    print("     to verify Gini improves and regime shifts from")
    print(f"     {h.regime} to ACCUMULATION or TRANSITION")


if __name__ == "__main__":
    main()
