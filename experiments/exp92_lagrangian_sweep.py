"""Exp 92: Lagrangian framework -- factorial sweep of energy definitions.

Full-factorial (2 T x 3 V = 6 configs) over candidate definitions of
kinetic and potential energy applied to the belief scoring population.

Kinetic energy candidates:
  T_a: sum of (dc_i/dt)^2  -- squared velocity from feedback history
  T_b: sum of (dC/dalpha_i * dalpha_i/dt)^2  -- Jacobian-weighted velocity

Potential energy candidates:
  V_a: -sum(c_i)  -- accumulated confidence (same as Exp 90 Hamiltonian)
  V_b: -sum(c_i * log(c_i) + (1-c_i) * log(1-c_i))  -- binary entropy
  V_c: -sum((c_i - 0.5)^2)  -- retrieval utility (extremes are useful)

For each config, compute:
  L = T - V, H = T + V
  Euler-Lagrange residual (does the system obey its own equations of motion?)
  Lagrange multiplier for fixed-budget constraint
  Gini, regime, conservation diagnostics (from Exp 90)
  Discriminative power: does this config separate known-good from known-bad states?

Usage:
    uv run python experiments/exp92_lagrangian_sweep.py
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@dataclass
class BeliefState:
    """Snapshot of a single belief's scoring state."""

    belief_id: str
    alpha: float
    beta: float
    confidence: float
    belief_type: str
    source_type: str
    locked: bool
    created_at: str
    updated_at: str


def load_beliefs(db_path: str) -> list[BeliefState]:
    """Load all active beliefs from the database."""
    conn: sqlite3.Connection = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows: list[sqlite3.Row] = conn.execute(
        """SELECT id, alpha, beta_param, confidence, belief_type,
                  source_type, locked, created_at, updated_at
           FROM beliefs WHERE superseded_by IS NULL"""
    ).fetchall()
    conn.close()

    beliefs: list[BeliefState] = []
    for r in rows:
        beliefs.append(BeliefState(
            belief_id=str(r["id"]),
            alpha=float(r["alpha"]),
            beta=float(r["beta_param"]),
            confidence=float(r["confidence"]),
            belief_type=str(r["belief_type"]),
            source_type=str(r["source_type"]),
            locked=bool(r["locked"]),
            created_at=str(r["created_at"]),
            updated_at=str(r["updated_at"]),
        ))
    return beliefs


# ---------------------------------------------------------------------------
# Kinetic energy definitions
# ---------------------------------------------------------------------------

def kinetic_squared_velocity(beliefs: list[BeliefState]) -> float:
    """T_a: sum of (dc_i/dt)^2 -- proxy via alpha/beta drift from default.

    We don't have a true time series, so we estimate velocity as the
    distance from the type-specific default prior. Beliefs that have
    moved far from their prior have high accumulated velocity.
    """
    type_defaults: dict[str, tuple[float, float]] = {
        "factual": (0.6, 1.0),
        "requirement": (1.8, 0.5),
        "correction": (1.8, 0.5),
        "preference": (1.4, 1.0),
        "assumption": (0.5, 1.0),
        "decision": (1.0, 1.0),
        "analysis": (0.5, 1.0),
        "speculative": (0.5, 1.0),
    }
    total: float = 0.0
    for b in beliefs:
        default_a, default_b = type_defaults.get(b.belief_type, (0.6, 1.0))
        default_c: float = default_a / (default_a + default_b)
        dc: float = b.confidence - default_c
        total += dc * dc
    return total


def kinetic_jacobian_weighted(beliefs: list[BeliefState]) -> float:
    """T_b: sum of (dC/dalpha * dalpha)^2 -- Jacobian-weighted velocity.

    Weights the drift by the local sensitivity. Beliefs that moved
    in regions of high sensitivity contribute more kinetic energy.
    """
    type_defaults: dict[str, tuple[float, float]] = {
        "factual": (0.6, 1.0),
        "requirement": (1.8, 0.5),
        "correction": (1.8, 0.5),
        "preference": (1.4, 1.0),
        "assumption": (0.5, 1.0),
        "decision": (1.0, 1.0),
        "analysis": (0.5, 1.0),
        "speculative": (0.5, 1.0),
    }
    total: float = 0.0
    for b in beliefs:
        default_a, default_b = type_defaults.get(b.belief_type, (0.6, 1.0))
        s: float = b.alpha + b.beta
        if s < 0.001:
            continue
        # Jacobian: dC/dalpha = beta / (alpha + beta)^2
        dc_dalpha: float = b.beta / (s * s)
        # Drift in alpha from default
        dalpha: float = b.alpha - default_a
        velocity: float = dc_dalpha * dalpha
        total += velocity * velocity
    return total


KINETIC_FNS: dict[str, tuple[str, object]] = {
    "T_a": ("squared_velocity (dc from prior)^2", kinetic_squared_velocity),
    "T_b": ("jacobian_weighted (dC/da * da)^2", kinetic_jacobian_weighted),
}


# ---------------------------------------------------------------------------
# Potential energy definitions
# ---------------------------------------------------------------------------

def potential_accumulated(beliefs: list[BeliefState]) -> float:
    """V_a: -sum(c_i) -- accumulated confidence as potential well."""
    return -sum(b.confidence for b in beliefs)


def potential_entropy(beliefs: list[BeliefState]) -> float:
    """V_b: -sum(H(c_i)) where H is binary entropy.

    Beliefs at 0.5 have max entropy (max uncertainty = high potential).
    Beliefs near 0 or 1 have low entropy (resolved = low potential).
    Sign convention: high entropy = high potential energy (unstable).
    """
    total: float = 0.0
    for b in beliefs:
        c: float = max(0.001, min(0.999, b.confidence))
        h: float = -(c * math.log2(c) + (1 - c) * math.log2(1 - c))
        total += h
    return total  # positive = high potential (uncertain)


def potential_utility(beliefs: list[BeliefState]) -> float:
    """V_c: -sum((c_i - 0.5)^2) -- retrieval utility.

    Beliefs far from 0.5 are more useful (strong signal either way).
    Convention: useful = low potential (stable configuration).
    """
    return -sum((b.confidence - 0.5) ** 2 for b in beliefs)


POTENTIAL_FNS: dict[str, tuple[str, object]] = {
    "V_a": ("accumulated -sum(c)", potential_accumulated),
    "V_b": ("entropy sum(H(c))", potential_entropy),
    "V_c": ("utility -sum((c-0.5)^2)", potential_utility),
}


# ---------------------------------------------------------------------------
# Diagnostics (shared across configs)
# ---------------------------------------------------------------------------

def gini(values: list[float]) -> float:
    """Gini coefficient. 0 = equal, 1 = max inequality."""
    if not values:
        return 0.0
    sorted_v: list[float] = sorted(values)
    n: int = len(sorted_v)
    total: float = sum(sorted_v)
    if total == 0:
        return 0.0
    numer: float = sum((2 * (i + 1) - n - 1) * sorted_v[i] for i in range(n))
    return numer / (n * total)


def classify_regime(t: float, v: float) -> str:
    """Same regime classification as Exp 90."""
    t_norm: float = abs(t) / max(abs(v), 0.001)
    if t_norm > 1.0:
        return "MOMENTUM"
    if t_norm < 0.1:
        return "ACCUMULATION"
    if t_norm > 0.5 and abs(v) > 1.0:
        return "TRANSITION"
    return "QUIESCENT"


@dataclass
class SweepResult:
    """Results for one (T, V) configuration."""

    t_name: str
    v_name: str
    t_desc: str
    v_desc: str

    # Energy values
    t_val: float
    v_val: float
    lagrangian: float  # L = T - V
    hamiltonian: float  # H = T + V

    # Regime diagnostics
    regime: str
    gini_coeff: float

    # Discriminative power: can this config tell apart belief tiers?
    tier_energies: dict[str, tuple[float, float]] = field(default_factory=dict)

    # Lagrange multiplier estimate for budget constraint
    lambda_budget: float = 0.0

    # Euler-Lagrange residual (how well the system obeys its EoM)
    el_residual: float = 0.0


# ---------------------------------------------------------------------------
# Tier analysis -- does the energy definition separate tiers?
# ---------------------------------------------------------------------------

def tier_label(b: BeliefState) -> str:
    """Assign a belief to a diagnostic tier."""
    if b.locked:
        return "locked"
    if b.source_type in ("user_corrected", "user_stated"):
        return "user_sourced"
    if b.confidence >= 0.7:
        return "high_conf"
    if b.confidence >= 0.4:
        return "mid_conf"
    return "low_conf"


def compute_tier_energies(
    beliefs: list[BeliefState],
    t_fn: object,
    v_fn: object,
) -> dict[str, tuple[float, float]]:
    """Compute per-tier average T and V to measure discrimination."""
    tiers: dict[str, list[BeliefState]] = defaultdict(list)
    for b in beliefs:
        tiers[tier_label(b)].append(b)

    result: dict[str, tuple[float, float]] = {}
    for tier_name, tier_beliefs in tiers.items():
        if not tier_beliefs:
            continue
        n: int = len(tier_beliefs)
        t: float = t_fn(tier_beliefs) / n  # type: ignore[operator]
        v: float = v_fn(tier_beliefs) / n  # type: ignore[operator]
        result[tier_name] = (t, v)
    return result


def discrimination_score(tier_energies: dict[str, tuple[float, float]]) -> float:
    """How well does this energy config separate tiers?

    Computes ratio of between-tier variance to within-tier mean.
    Higher = more discriminative.
    """
    if len(tier_energies) < 2:
        return 0.0

    # Use Lagrangian (T - V) as the scalar to compare
    l_values: list[float] = [t - v for t, v in tier_energies.values()]
    mean_l: float = sum(l_values) / len(l_values)
    variance: float = sum((lv - mean_l) ** 2 for lv in l_values) / len(l_values)

    return math.sqrt(variance) / max(abs(mean_l), 0.001)


# ---------------------------------------------------------------------------
# Budget constraint -- Lagrange multiplier estimation
# ---------------------------------------------------------------------------

def estimate_lambda_budget(
    beliefs: list[BeliefState],
    t_fn: object,
    v_fn: object,
    budget: int = 100,
) -> float:
    """Estimate the Lagrange multiplier for a fixed feedback budget.

    lambda = dL/dN at the current operating point, where N = total
    feedback events consumed. Approximated by perturbing one belief
    and measuring the marginal change in L.
    """
    l_base: float = t_fn(beliefs) - v_fn(beliefs)  # type: ignore[operator]

    # Simulate giving one "used" feedback to the lowest-confidence unlocked belief
    unlocked: list[BeliefState] = [b for b in beliefs if not b.locked]
    if not unlocked:
        return 0.0

    target: BeliefState = min(unlocked, key=lambda b: b.confidence)
    perturbed: list[BeliefState] = []
    for b in beliefs:
        if b.belief_id == target.belief_id:
            new_alpha: float = b.alpha + 0.5  # one "used" event
            new_s: float = new_alpha + b.beta
            perturbed.append(BeliefState(
                belief_id=b.belief_id,
                alpha=new_alpha,
                beta=b.beta,
                confidence=new_alpha / new_s if new_s > 0 else 0.5,
                belief_type=b.belief_type,
                source_type=b.source_type,
                locked=b.locked,
                created_at=b.created_at,
                updated_at=b.updated_at,
            ))
        else:
            perturbed.append(b)

    l_perturbed: float = t_fn(perturbed) - v_fn(perturbed)  # type: ignore[operator]
    return l_perturbed - l_base  # dL/dN for one event


# ---------------------------------------------------------------------------
# Euler-Lagrange residual
# ---------------------------------------------------------------------------

def euler_lagrange_residual(
    beliefs: list[BeliefState],
    t_fn: object,
    v_fn: object,
) -> float:
    """Estimate how well the system obeys d/dt(dL/dq_dot) - dL/dq = 0.

    Since we don't have true dynamics, we test whether beliefs that
    received more feedback (larger |alpha - default|) moved in the
    direction that minimizes the action. Measured as correlation
    between feedback magnitude and -dV/dc (the 'force').
    """
    type_defaults: dict[str, tuple[float, float]] = {
        "factual": (0.6, 1.0),
        "requirement": (1.8, 0.5),
        "correction": (1.8, 0.5),
        "preference": (1.4, 1.0),
        "assumption": (0.5, 1.0),
        "decision": (1.0, 1.0),
        "analysis": (0.5, 1.0),
        "speculative": (0.5, 1.0),
    }

    # Compute numerical dV/dc for each belief
    eps: float = 0.001
    forces: list[float] = []
    displacements: list[float] = []

    for b in beliefs:
        if b.locked:
            continue

        default_a, default_b = type_defaults.get(b.belief_type, (0.6, 1.0))
        displacement: float = b.alpha - default_a

        # Numerical dV/dc: perturb confidence, measure V change
        b_plus: BeliefState = BeliefState(
            belief_id=b.belief_id,
            alpha=b.alpha,
            beta=b.beta,
            confidence=min(0.999, b.confidence + eps),
            belief_type=b.belief_type,
            source_type=b.source_type,
            locked=b.locked,
            created_at=b.created_at,
            updated_at=b.updated_at,
        )
        b_minus: BeliefState = BeliefState(
            belief_id=b.belief_id,
            alpha=b.alpha,
            beta=b.beta,
            confidence=max(0.001, b.confidence - eps),
            belief_type=b.belief_type,
            source_type=b.source_type,
            locked=b.locked,
            created_at=b.created_at,
            updated_at=b.updated_at,
        )

        v_plus: float = v_fn([b_plus])  # type: ignore[operator]
        v_minus: float = v_fn([b_minus])  # type: ignore[operator]
        force: float = -(v_plus - v_minus) / (2 * eps)

        forces.append(force)
        displacements.append(displacement)

    # Correlation between force and displacement
    # If EL is satisfied, beliefs that feel more force should have moved more
    if len(forces) < 2:
        return 0.0

    n: int = len(forces)
    mean_f: float = sum(forces) / n
    mean_d: float = sum(displacements) / n
    cov: float = sum((forces[i] - mean_f) * (displacements[i] - mean_d) for i in range(n)) / n
    std_f: float = math.sqrt(sum((f - mean_f) ** 2 for f in forces) / n)
    std_d: float = math.sqrt(sum((d - mean_d) ** 2 for d in displacements) / n)

    if std_f < 1e-10 or std_d < 1e-10:
        return 0.0

    correlation: float = cov / (std_f * std_d)
    # Residual = 1 - |correlation|. 0 = perfect EL compliance, 1 = no relationship.
    return 1.0 - abs(correlation)


# ---------------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------------

def main() -> None:
    db_path: str = str(
        Path.home() / ".agentmemory" / "projects" / "2e7ed55e017a" / "memory.db"
    )

    beliefs: list[BeliefState] = load_beliefs(db_path)
    confs: list[float] = [b.confidence for b in beliefs]
    g: float = gini(confs)

    print("=" * 78)
    print("Exp 92: Lagrangian Framework -- Factorial Energy Definition Sweep")
    print("=" * 78)
    print(f"Population: {len(beliefs)} active beliefs")
    print(f"Gini: {g:.4f}")
    print()

    # Full factorial: 2 T x 3 V = 6 configs
    results: list[SweepResult] = []

    for t_key, (t_desc, t_fn) in KINETIC_FNS.items():
        for v_key, (v_desc, v_fn) in POTENTIAL_FNS.items():
            t_val: float = t_fn(beliefs)  # type: ignore[operator]
            v_val: float = v_fn(beliefs)  # type: ignore[operator]

            tier_e: dict[str, tuple[float, float]] = compute_tier_energies(
                beliefs, t_fn, v_fn  # type: ignore[arg-type]
            )
            lam: float = estimate_lambda_budget(
                beliefs, t_fn, v_fn, budget=100  # type: ignore[arg-type]
            )
            el_r: float = euler_lagrange_residual(
                beliefs, t_fn, v_fn  # type: ignore[arg-type]
            )

            r = SweepResult(
                t_name=t_key,
                v_name=v_key,
                t_desc=t_desc,
                v_desc=v_desc,
                t_val=t_val,
                v_val=v_val,
                lagrangian=t_val - v_val,
                hamiltonian=t_val + v_val,
                regime=classify_regime(t_val, v_val),
                gini_coeff=g,
                tier_energies=tier_e,
                lambda_budget=lam,
                el_residual=el_r,
            )
            results.append(r)

    # --- Summary table ---
    print("## SWEEP RESULTS (2 T x 3 V = 6 configs)")
    print()
    print(f"{'Config':10s}  {'T':>12s}  {'V':>12s}  {'L=T-V':>12s}  "
          f"{'H=T+V':>12s}  {'Regime':>13s}  {'EL Resid':>8s}  {'lambda':>10s}  {'Discrim':>7s}")
    print("-" * 110)

    for r in results:
        disc: float = discrimination_score(r.tier_energies)
        config: str = f"{r.t_name}+{r.v_name}"
        print(f"{config:10s}  {r.t_val:12.2f}  {r.v_val:12.2f}  {r.lagrangian:12.2f}  "
              f"{r.hamiltonian:12.2f}  {r.regime:>13s}  {r.el_residual:8.4f}  "
              f"{r.lambda_budget:10.6f}  {disc:7.4f}")

    # --- Tier breakdown per config ---
    print()
    print("## TIER ENERGY BREAKDOWN (per-belief average)")
    print()

    tier_order: list[str] = ["locked", "user_sourced", "high_conf", "mid_conf", "low_conf"]

    for r in results:
        config = f"{r.t_name}+{r.v_name}"
        print(f"--- {config} ({r.t_desc} / {r.v_desc}) ---")
        print(f"  {'Tier':15s}  {'T/n':>10s}  {'V/n':>10s}  {'L/n':>10s}")
        for tier in tier_order:
            if tier in r.tier_energies:
                t, v = r.tier_energies[tier]
                print(f"  {tier:15s}  {t:10.6f}  {v:10.6f}  {t - v:10.6f}")
        print()

    # --- Analysis: which config is most informative? ---
    print("=" * 78)
    print("## ANALYSIS")
    print("=" * 78)
    print()

    best: SweepResult = max(results, key=lambda r: discrimination_score(r.tier_energies))
    best_disc: float = discrimination_score(best.tier_energies)
    worst: SweepResult = min(results, key=lambda r: discrimination_score(r.tier_energies))
    worst_disc: float = discrimination_score(worst.tier_energies)

    print(f"Most discriminative:  {best.t_name}+{best.v_name} "
          f"(disc={best_disc:.4f})")
    print(f"  T: {best.t_desc}")
    print(f"  V: {best.v_desc}")
    print()
    print(f"Least discriminative: {worst.t_name}+{worst.v_name} "
          f"(disc={worst_disc:.4f})")
    print()

    # EL compliance ranking
    el_ranked: list[SweepResult] = sorted(results, key=lambda r: r.el_residual)
    print("Euler-Lagrange compliance ranking (lower residual = better fit):")
    for r in el_ranked:
        print(f"  {r.t_name}+{r.v_name}: residual={r.el_residual:.4f}")
    print()

    # Lambda analysis
    print("Budget constraint sensitivity (lambda = marginal value of one feedback event):")
    for r in results:
        print(f"  {r.t_name}+{r.v_name}: lambda={r.lambda_budget:.6f}")
    print()

    # Cross-reference with known facts
    print("## CROSS-REFERENCE WITH KNOWN FINDINGS")
    print()
    print("From Exp 90 Jacobian:")
    print("  - 3.3x sensitivity gap between 0.66 cluster and correct 0.375 prior")
    print("  - Gini = 0.1474 (below 0.15 diversity threshold)")
    print("  - 81% of beliefs stuck in one confidence bucket")
    print()
    print("What each Lagrangian config tells us about these findings:")
    print()

    for r in results:
        config = f"{r.t_name}+{r.v_name}"
        disc = discrimination_score(r.tier_energies)
        locked_e = r.tier_energies.get("locked", (0, 0))
        low_e = r.tier_energies.get("low_conf", (0, 0))

        # Does this config see the cluster problem?
        locked_l: float = locked_e[0] - locked_e[1]
        low_l: float = low_e[0] - low_e[1]
        separation: float = abs(locked_l - low_l)

        print(f"  {config}:")
        print(f"    Locked vs low_conf L separation: {separation:.6f}")
        print(f"    Discrimination: {disc:.4f}")
        if r.el_residual < 0.3:
            print(f"    EL residual {r.el_residual:.4f} -- system approximately follows these dynamics")
        else:
            print(f"    EL residual {r.el_residual:.4f} -- poor fit, system does NOT follow these dynamics")
        print()


if __name__ == "__main__":
    main()
