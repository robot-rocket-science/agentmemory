"""Exp 93b: Multi-model scoring applied ONLY to beliefs with feedback.

Hypotheses:
  H1a: Feedback subset Gini > 0.25 (vs 0.15 full population)
  H1b: >50% of feedback subset confidently classified (entropy < 0.5)

Rationale: beliefs without feedback have uninformative evidence vectors
(feedback_ratio defaults to 0.5), making the posterior prior-dominated.
By restricting to beliefs with actual feedback, the archaeology-style
updating should produce real differentiation.

Usage:
    uv run python experiments/exp93b_feedback_only.py
"""

from __future__ import annotations

import math
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# --- Reuse model definitions from exp93 ---

@dataclass
class GenerativeModel:
    name: str
    label: str
    expected_feedback_ratio: tuple[float, float]
    expected_harmful_ratio: tuple[float, float]
    expected_age_decay: tuple[float, float]
    expected_source_quality: tuple[float, float]
    prior: float = 0.25


MODELS: list[GenerativeModel] = [
    GenerativeModel("M1", "SIGNAL",
                    expected_feedback_ratio=(0.8, 10.0),
                    expected_harmful_ratio=(0.05, 20.0),
                    expected_age_decay=(0.5, 5.0),
                    expected_source_quality=(0.6, 5.0),
                    prior=0.30),
    GenerativeModel("M2", "NOISE",
                    expected_feedback_ratio=(0.15, 10.0),
                    expected_harmful_ratio=(0.1, 10.0),
                    expected_age_decay=(0.5, 3.0),
                    expected_source_quality=(0.3, 8.0),
                    prior=0.40),
    GenerativeModel("M3", "STALE",
                    expected_feedback_ratio=(0.4, 5.0),
                    expected_harmful_ratio=(0.15, 8.0),
                    expected_age_decay=(0.85, 10.0),
                    expected_source_quality=(0.5, 3.0),
                    prior=0.15),
    GenerativeModel("M4", "CONTESTED",
                    expected_feedback_ratio=(0.5, 3.0),
                    expected_harmful_ratio=(0.35, 8.0),
                    expected_age_decay=(0.3, 3.0),
                    expected_source_quality=(0.5, 3.0),
                    prior=0.15),
]

MODEL_CONFIDENCE: dict[str, float] = {
    "M1": 0.85, "M2": 0.25, "M3": 0.35, "M4": 0.55,
}

SOURCE_QUALITY_MAP: dict[str, float] = {
    "user_corrected": 1.0, "user_stated": 0.8,
    "document_recent": 0.5, "document_old": 0.3, "agent_inferred": 0.3,
}


@dataclass
class BeliefEvidence:
    belief_id: str
    belief_type: str
    source_type: str
    locked: bool
    confidence_current: float
    alpha: float
    beta: float
    feedback_ratio: float
    harmful_ratio: float
    age_normalized: float
    source_quality: float
    total_feedback: int


def parse_ts(ts: str) -> datetime:
    dt: datetime = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def beta_log_likelihood(x: float, mu: float, kappa: float) -> float:
    a: float = max(0.01, mu * kappa)
    b: float = max(0.01, (1.0 - mu) * kappa)
    x_safe: float = max(0.001, min(0.999, x))
    log_p: float = (a - 1.0) * math.log(x_safe) + (b - 1.0) * math.log(1.0 - x_safe)
    log_beta: float = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    return log_p - log_beta


@dataclass
class ModelPosterior:
    belief_id: str
    posteriors: dict[str, float] = field(default_factory=dict)
    map_model: str = ""
    map_probability: float = 0.0
    entropy: float = 0.0


def compute_posterior(ev: BeliefEvidence) -> ModelPosterior:
    log_posteriors: dict[str, float] = {}
    for m in MODELS:
        ll: float = 0.0
        ll += beta_log_likelihood(ev.feedback_ratio, *m.expected_feedback_ratio)
        ll += beta_log_likelihood(ev.harmful_ratio, *m.expected_harmful_ratio)
        ll += beta_log_likelihood(ev.age_normalized, *m.expected_age_decay)
        ll += beta_log_likelihood(ev.source_quality, *m.expected_source_quality)
        log_posteriors[m.name] = ll + math.log(max(1e-10, m.prior))

    max_lp: float = max(log_posteriors.values())
    log_norm: float = max_lp + math.log(
        sum(math.exp(lp - max_lp) for lp in log_posteriors.values())
    )
    posteriors: dict[str, float] = {
        name: math.exp(lp - log_norm) for name, lp in log_posteriors.items()
    }
    map_name: str = max(posteriors, key=lambda k: posteriors[k])
    h: float = -sum(p * math.log2(p) for p in posteriors.values() if p > 1e-10)

    return ModelPosterior(
        belief_id=ev.belief_id, posteriors=posteriors,
        map_model=map_name, map_probability=posteriors[map_name], entropy=h,
    )


def gini(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_v: list[float] = sorted(values)
    n: int = len(sorted_v)
    total: float = sum(sorted_v)
    if total == 0:
        return 0.0
    numer: float = sum((2 * (i + 1) - n - 1) * sorted_v[i] for i in range(n))
    return numer / (n * total)


def main() -> None:
    db_path: str = str(
        Path.home() / ".agentmemory" / "projects" / "2e7ed55e017a" / "memory.db"
    )
    conn: sqlite3.Connection = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows: list[sqlite3.Row] = conn.execute(
        """SELECT b.id, b.alpha, b.beta_param, b.confidence,
                  b.belief_type, b.source_type, b.locked, b.created_at,
                  COALESCE(t.used_count, 0) as used_count,
                  COALESCE(t.ignored_count, 0) as ignored_count,
                  COALESCE(t.harmful_count, 0) as harmful_count,
                  COALESCE(t.total_tests, 0) as total_tests
           FROM beliefs b
           LEFT JOIN (
               SELECT belief_id,
                      SUM(CASE WHEN outcome='used' OR outcome='confirmed' THEN 1 ELSE 0 END) as used_count,
                      SUM(CASE WHEN outcome='ignored' THEN 1 ELSE 0 END) as ignored_count,
                      SUM(CASE WHEN outcome='harmful' THEN 1 ELSE 0 END) as harmful_count,
                      COUNT(*) as total_tests
               FROM tests GROUP BY belief_id
           ) t ON b.id = t.belief_id
           WHERE b.superseded_by IS NULL"""
    ).fetchall()

    age_bounds: sqlite3.Row = conn.execute(
        "SELECT MIN(created_at) as oldest, MAX(created_at) as newest FROM beliefs WHERE superseded_by IS NULL"
    ).fetchone()
    oldest_dt: datetime = parse_ts(str(age_bounds["oldest"]))
    newest_dt: datetime = parse_ts(str(age_bounds["newest"]))
    max_age_hours: float = max(1.0, (newest_dt - oldest_dt).total_seconds() / 3600.0)
    conn.close()

    # Split into feedback vs no-feedback
    with_feedback: list[BeliefEvidence] = []
    without_feedback: list[BeliefEvidence] = []

    for r in rows:
        total: int = int(r["total_tests"])
        used: int = int(r["used_count"])
        harmful: int = int(r["harmful_count"])
        created_dt: datetime = parse_ts(str(r["created_at"]))
        age_norm: float = (newest_dt - created_dt).total_seconds() / 3600.0 / max_age_hours

        ev = BeliefEvidence(
            belief_id=str(r["id"]),
            belief_type=str(r["belief_type"]),
            source_type=str(r["source_type"]),
            locked=bool(r["locked"]),
            confidence_current=float(r["confidence"]),
            alpha=float(r["alpha"]),
            beta=float(r["beta_param"]),
            feedback_ratio=used / total if total > 0 else 0.5,
            harmful_ratio=harmful / total if total > 0 else 0.0,
            age_normalized=age_norm,
            source_quality=SOURCE_QUALITY_MAP.get(str(r["source_type"]), 0.5),
            total_feedback=total,
        )
        if total > 0:
            with_feedback.append(ev)
        else:
            without_feedback.append(ev)

    print("=" * 70)
    print("Exp 93b: Multi-Model on Feedback Subset Only")
    print("=" * 70)
    print(f"Total beliefs: {len(rows)}")
    print(f"With feedback: {len(with_feedback)} ({len(with_feedback)/len(rows)*100:.1f}%)")
    print(f"Without feedback: {len(without_feedback)} ({len(without_feedback)/len(rows)*100:.1f}%)")
    print()

    # --- Feedback subset analysis ---
    fb_posteriors: list[ModelPosterior] = [compute_posterior(e) for e in with_feedback]
    fb_scores: list[float] = [
        sum(p * MODEL_CONFIDENCE.get(m, 0.5) for m, p in post.posteriors.items())
        for post in fb_posteriors
    ]
    fb_current: list[float] = [e.confidence_current for e in with_feedback]

    fb_gini_current: float = gini(fb_current)
    fb_gini_new: float = gini(fb_scores)

    print("## FEEDBACK SUBSET RESULTS")
    print(f"  Current Gini (subset): {fb_gini_current:.4f}")
    print(f"  Multi-model Gini:      {fb_gini_new:.4f} ({fb_gini_new - fb_gini_current:+.4f})")
    print()

    # H1a test
    h1a_pass: bool = fb_gini_new > 0.25
    print(f"  H1a (Gini > 0.25): {'PASS' if h1a_pass else 'FAIL'} (got {fb_gini_new:.4f})")

    # H1b test
    confident: int = sum(1 for p in fb_posteriors if p.entropy < 0.5)
    confident_pct: float = confident / len(fb_posteriors) * 100
    h1b_pass: bool = confident_pct > 50.0
    print(f"  H1b (>50% confident): {'PASS' if h1b_pass else 'FAIL'} (got {confident_pct:.1f}%)")
    print()

    # MAP distribution
    fb_map: Counter[str] = Counter(p.map_model for p in fb_posteriors)
    labels: dict[str, str] = {m.name: m.label for m in MODELS}
    print("  MAP distribution (feedback subset):")
    for name in ["M1", "M2", "M3", "M4"]:
        c: int = fb_map.get(name, 0)
        print(f"    {name} ({labels[name]:>10s}): {c:>5d} ({c/len(fb_posteriors)*100:>5.1f}%)")
    print()

    # Score distribution
    print("  Score distribution (feedback subset):")
    buckets: Counter[str] = Counter()
    for s in fb_scores:
        if s >= 0.7:
            buckets["0.7-1.0"] += 1
        elif s >= 0.5:
            buckets["0.5-0.7"] += 1
        elif s >= 0.3:
            buckets["0.3-0.5"] += 1
        else:
            buckets["0.0-0.3"] += 1

    for b in ["0.0-0.3", "0.3-0.5", "0.5-0.7", "0.7-1.0"]:
        c = buckets.get(b, 0)
        print(f"    {b}: {c:>5d} ({c/len(fb_scores)*100:>5.1f}%)")
    print()

    # Feedback-count breakdown: does more feedback = more confident classification?
    print("  Classification confidence by feedback count:")
    fb_bins: list[tuple[str, int, int]] = [
        ("1-2 events", 1, 2), ("3-5 events", 3, 5),
        ("6-10 events", 6, 10), ("11+ events", 11, 9999),
    ]
    for label, lo, hi in fb_bins:
        subset: list[ModelPosterior] = [
            p for e, p in zip(with_feedback, fb_posteriors)
            if lo <= e.total_feedback <= hi
        ]
        if not subset:
            continue
        avg_h: float = sum(p.entropy for p in subset) / len(subset)
        conf_n: int = sum(1 for p in subset if p.entropy < 0.5)
        print(f"    {label:>12s}: n={len(subset):>4d}  avg_entropy={avg_h:.3f}  "
              f"confident={conf_n/len(subset)*100:.0f}%")
    print()

    # --- Compare no-feedback subset ---
    nf_posteriors: list[ModelPosterior] = [compute_posterior(e) for e in without_feedback]
    nf_avg_entropy: float = sum(p.entropy for p in nf_posteriors) / len(nf_posteriors)
    fb_avg_entropy: float = sum(p.entropy for p in fb_posteriors) / len(fb_posteriors)

    print("## FEEDBACK vs NO-FEEDBACK COMPARISON")
    print(f"  Avg entropy (with feedback):    {fb_avg_entropy:.3f}")
    print(f"  Avg entropy (without feedback): {nf_avg_entropy:.3f}")
    print(f"  Delta: {fb_avg_entropy - nf_avg_entropy:+.3f}")
    print()
    if fb_avg_entropy < nf_avg_entropy:
        print("  CONFIRMED: Feedback evidence reduces posterior uncertainty.")
        print(f"  Beliefs with feedback are {nf_avg_entropy/max(fb_avg_entropy,0.001):.1f}x more classifiable.")
    else:
        print("  UNEXPECTED: Feedback does not reduce entropy.")
        print("  The evidence dimensions may not be well-calibrated.")


if __name__ == "__main__":
    main()
