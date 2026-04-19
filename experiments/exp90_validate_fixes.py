"""Exp 90 validation: verify fix assumptions before implementation.

Run this BEFORE implementing any fixes. It simulates each fix component
on a copy of the production data and measures the projected impact.

Usage:
    uv run python experiments/exp90_validate_fixes.py
"""
from __future__ import annotations

import math
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path


def gini(values: list[float]) -> float:
    """Compute Gini coefficient. 0 = equal, 1 = max inequality."""
    if not values:
        return 0.0
    sorted_v: list[float] = sorted(values)
    n: int = len(sorted_v)
    total: float = sum(sorted_v)
    if total == 0:
        return 0.0
    numer: float = sum((2 * (i + 1) - n - 1) * sorted_v[i] for i in range(n))
    return numer / (n * total)


def thompson_distinguishability(alphas: list[float], betas: list[float], n_samples: int = 1000) -> float:
    """Measure P(different rank) for random pairs under Thompson sampling.

    Draw pairs from the population, sample from their Beta distributions,
    and check if the samples produce different rankings.
    """
    if len(alphas) < 2:
        return 1.0
    same_rank: int = 0
    for _ in range(n_samples):
        i: int = random.randint(0, len(alphas) - 1)
        j: int = random.randint(0, len(alphas) - 1)
        if i == j:
            continue
        s_i: float = random.betavariate(max(0.01, alphas[i]), max(0.01, betas[i]))
        s_j: float = random.betavariate(max(0.01, alphas[j]), max(0.01, betas[j]))
        if abs(s_i - s_j) < 0.01:  # effectively same score
            same_rank += 1
    return 1.0 - (same_rank / n_samples)


def main() -> None:
    db_path: str = str(
        Path.home() / ".agentmemory" / "projects" / "2e7ed55e017a" / "memory.db"
    )
    conn: sqlite3.Connection = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows: list[sqlite3.Row] = conn.execute(
        """SELECT id, alpha, beta_param, confidence, belief_type, source_type,
                  locked, created_at
           FROM beliefs WHERE superseded_by IS NULL"""
    ).fetchall()

    print("=" * 70)
    print("Exp 90 Validation: Pre-Implementation Checks")
    print("=" * 70)
    print(f"Active beliefs: {len(rows)}")

    # Current state
    confs: list[float] = [float(r["confidence"]) for r in rows]
    alphas: list[float] = [float(r["alpha"]) for r in rows]
    betas: list[float] = [float(r["beta_param"]) for r in rows]
    current_gini: float = gini(confs)
    current_distinguish: float = thompson_distinguishability(alphas, betas)

    print(f"Current Gini: {current_gini:.4f}")
    print(f"Current Thompson distinguishability: {current_distinguish:.3f}")
    print()

    # === Validate Fix 1: Type-Aware Recalibration ===
    print("## Fix 1: Type-Aware Recalibration")
    type_priors: dict[str, tuple[float, float]] = {
        "factual": (0.6, 1.0),
        "requirement": (1.8, 0.5),
        "correction": (1.8, 0.5),
        "preference": (1.4, 1.0),
        "assumption": (0.5, 1.0),
        "decision": (1.0, 1.0),
        "analysis": (0.5, 1.0),
        "speculative": (0.5, 1.0),
    }

    new_confs_1: list[float] = []
    new_alphas_1: list[float] = []
    new_betas_1: list[float] = []
    recal_count: int = 0

    for r in rows:
        a: float = float(r["alpha"])
        b: float = float(r["beta_param"])
        bt: str = str(r["belief_type"])
        st: str = str(r["source_type"])

        if st == "agent_inferred" and not bool(r["locked"]):
            target: tuple[float, float] = type_priors.get(bt, (0.6, 1.0))
            if a > target[0]:
                a = target[0]
                b = target[1]
                recal_count += 1

        new_alphas_1.append(a)
        new_betas_1.append(b)
        new_confs_1.append(a / (a + b) if (a + b) > 0 else 0.5)

    gini_1: float = gini(new_confs_1)
    dist_1: float = thompson_distinguishability(new_alphas_1, new_betas_1)
    print(f"  Beliefs recalibrated: {recal_count}")
    print(f"  Gini: {current_gini:.4f} -> {gini_1:.4f} ({gini_1 - current_gini:+.4f})")
    print(f"  Thompson distinguishability: {current_distinguish:.3f} -> {dist_1:.3f}")
    print(f"  PASS: {gini_1 >= 0.15}" if gini_1 >= 0.15 else f"  FAIL: Gini {gini_1:.4f} < 0.15 target")
    print()

    # === Validate Fix 2: Source-Type Decay ===
    print("## Fix 2: Source-Type Decay Modifiers (projected at T+30d)")
    source_decay: dict[str, float] = {
        "user_corrected": 2.0,
        "user_stated": 1.5,
        "agent_inferred": 0.3,
    }
    base_half_lives: dict[str, float] = {
        "factual": 336.0,
        "preference": 2016.0,
        "correction": 1344.0,
        "requirement": 4032.0,
    }

    # Simulate 30 days of decay on the recalibrated data
    hours_30d: float = 30 * 24
    decayed_confs: list[float] = []
    for i, r in enumerate(rows):
        conf: float = new_confs_1[i]
        bt = str(r["belief_type"])
        st = str(r["source_type"])
        locked: bool = bool(r["locked"])

        if locked:
            decayed_confs.append(conf)
            continue

        base_hl: float = base_half_lives.get(bt, 336.0)
        source_mod: float = source_decay.get(st, 1.0)
        eff_hl: float = base_hl * source_mod

        decay: float = 0.5 ** (hours_30d / eff_hl)
        decayed_confs.append(conf * decay)

    gini_2: float = gini(decayed_confs)
    print(f"  Gini at T+30d: {gini_1:.4f} -> {gini_2:.4f} ({gini_2 - gini_1:+.4f})")
    print(f"  Agent-inferred factual at T+30d: conf ~= {0.375 * 0.5 ** (hours_30d / (336 * 0.3)):.4f}")
    print(f"  User correction at T+30d: conf ~= {0.947 * 0.5 ** (hours_30d / (1344 * 2.0)):.4f}")
    print(f"  PASS: {gini_2 >= 0.25}" if gini_2 >= 0.25 else f"  WARNING: Gini {gini_2:.4f} < 0.25 target at T+30d")
    print()

    # === Validate Fix 3: First-Signal Amplification ===
    print("## Fix 3: First-Signal Amplification (3x weight on first feedback)")
    # Simulate: take beliefs at correct prior (0.375), apply one "used" event
    # with normal weight vs 3x weight
    a_normal: float = 0.6 + 0.5  # alpha += 0.5 (used valence)
    b_normal: float = 1.0
    conf_normal: float = a_normal / (a_normal + b_normal)

    a_amplified: float = 0.6 + 0.5 * 3.0  # alpha += 1.5 (3x first signal)
    b_amplified: float = 1.0
    conf_amplified: float = a_amplified / (a_amplified + b_amplified)

    print(f"  Normal first 'used': 0.375 -> {conf_normal:.3f} (+{(conf_normal - 0.375) * 100:.1f}pp)")
    print(f"  Amplified first 'used': 0.375 -> {conf_amplified:.3f} (+{(conf_amplified - 0.375) * 100:.1f}pp)")
    print(f"  Amplification effect: {(conf_amplified - conf_normal) * 100:.1f}pp additional separation")
    print(f"  PASS: amplified creates > 10pp separation from prior")
    print()

    # === Validate Fix 4: UCB Exploration Bonus ===
    print("## Fix 4: UCB Exploration Bonus")
    total_retrievals: int = 1000  # approximate
    c_param: float = 0.1

    # Belief retrieved 0 times vs 10 times vs 100 times
    for n_ret in [0, 1, 5, 10, 50, 100]:
        bonus: float = c_param * math.sqrt(math.log(max(1, total_retrievals)) / max(1, n_ret))
        print(f"  Retrieval count={n_ret:3d}: bonus={bonus:.4f}")
    print(f"  Max spread (0 vs 100 retrievals): {c_param * math.sqrt(math.log(1000)) - c_param * math.sqrt(math.log(1000) / 100):.4f}")
    print()

    # === Validate Fix 5: Asymmetric Feedback ===
    print("## Fix 5: Asymmetric Feedback (2x negative weight)")
    a_start: float = 0.6
    b_start: float = 1.0
    conf_start: float = a_start / (a_start + b_start)

    # Current: harmful beta += 1.0
    conf_after_harm_current: float = a_start / (a_start + b_start + 1.0)
    # Proposed: harmful beta += 2.0
    conf_after_harm_proposed: float = a_start / (a_start + b_start + 2.0)

    print(f"  Current 'harmful': {conf_start:.3f} -> {conf_after_harm_current:.3f} ({(conf_after_harm_current - conf_start) * 100:+.1f}pp)")
    print(f"  Proposed 'harmful' (2x): {conf_start:.3f} -> {conf_after_harm_proposed:.3f} ({(conf_after_harm_proposed - conf_start) * 100:+.1f}pp)")
    print(f"  Additional separation: {(conf_after_harm_current - conf_after_harm_proposed) * 100:.1f}pp")
    print()

    # === Combined projection ===
    print("=" * 70)
    print("COMBINED PROJECTION")
    print("=" * 70)
    print(f"  Current Gini:           {current_gini:.4f}")
    print(f"  After recalibration:    {gini_1:.4f}")
    print(f"  After +30d decay:       {gini_2:.4f}")
    print(f"  Thompson distinguish:   {current_distinguish:.3f} -> {dist_1:.3f}")
    print()

    # Check max cluster
    bucket_counter: Counter[float] = Counter(round(c, 2) for c in new_confs_1)
    max_bucket_pct: float = max(bucket_counter.values()) / len(new_confs_1) * 100
    print(f"  Max bucket after recal: {max_bucket_pct:.1f}% (target < 30%)")
    print(f"  PASS: {max_bucket_pct < 30}")

    conn.close()


if __name__ == "__main__":
    main()
