"""Exp 93: Multi-model Bayesian scoring with archaeology-style evidence.

Adapts the Wikipedia Bayesian inference archaeology example to belief scoring.
Instead of estimating a century from pottery fragments, we estimate a belief's
"true quality model" from multi-dimensional feedback evidence.

Key insight: the archaeology example uses MULTIPLE observable dimensions
(glazed, decorated) to update a posterior over a CONTINUOUS hidden variable.
Our current system uses ONE dimension (used/ignored) to update a per-belief
alpha/beta. This experiment tests whether multi-dimensional evidence with
model selection produces better population differentiation.

Competing generative models for each belief:
  M1: SIGNAL    -- genuinely useful (expects: high used rate, low harmful)
  M2: NOISE     -- low quality (expects: high ignored rate)
  M3: STALE     -- was useful, now outdated (expects: used early, ignored late)
  M4: CONTESTED -- controversial (expects: both used AND harmful)

Observable dimensions per belief (analogous to glazed/decorated):
  D1: feedback_ratio  = used_count / (used_count + ignored_count + harmful_count)
  D2: harmful_ratio   = harmful_count / total_feedback
  D3: age_normalized  = hours_since_creation / max_age_hours
  D4: retrieval_rank  = avg_rank_when_retrieved / total_beliefs (0=top, 1=bottom)
  D5: source_quality  = {user_corrected: 1.0, user_stated: 0.8, agent_inferred: 0.3}

Each model defines likelihood functions over these dimensions, analogous to
pG(c) and pD(c) in the archaeology example. The posterior over models is
updated as evidence accumulates, and the MAP model determines scoring behavior.

Bayesian model selection: P(M|evidence) proportional to P(evidence|M) * P(M)
Bayes factor between models: BF = P(evidence|M1) / P(evidence|M2)

Usage:
    uv run python experiments/exp93_multimodel_bayesian.py
"""

from __future__ import annotations

import math
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Model definitions
# ---------------------------------------------------------------------------

# Each model specifies the expected value of each observable dimension.
# Likelihoods are modeled as Beta distributions around these expected values,
# following the archaeology pattern where pG(c) varies linearly with the
# hidden variable.


@dataclass
class GenerativeModel:
    """A candidate generative model for belief quality."""

    name: str
    label: str

    # Expected values for each observable dimension under this model.
    # Each is (mu, concentration) for a Beta likelihood.
    # Higher concentration = model is more "sure" about its prediction.
    expected_feedback_ratio: tuple[float, float]  # (mu, kappa)
    expected_harmful_ratio: tuple[float, float]
    expected_age_decay: tuple[float, float]  # how confidence should change with age
    expected_source_quality: tuple[float, float]

    # Prior probability P(M)
    prior: float = 0.25


# The four competing models
MODELS: list[GenerativeModel] = [
    GenerativeModel(
        name="M1",
        label="SIGNAL",
        expected_feedback_ratio=(0.8, 10.0),   # high used rate
        expected_harmful_ratio=(0.05, 20.0),    # very low harmful
        expected_age_decay=(0.5, 5.0),          # moderate age sensitivity
        expected_source_quality=(0.6, 5.0),     # any source
        prior=0.30,
    ),
    GenerativeModel(
        name="M2",
        label="NOISE",
        expected_feedback_ratio=(0.15, 10.0),   # low used rate
        expected_harmful_ratio=(0.1, 10.0),     # some harmful
        expected_age_decay=(0.5, 3.0),          # doesn't matter
        expected_source_quality=(0.3, 8.0),     # likely agent-inferred
        prior=0.40,  # most beliefs are noise -- honest prior
    ),
    GenerativeModel(
        name="M3",
        label="STALE",
        expected_feedback_ratio=(0.4, 5.0),     # was used sometimes
        expected_harmful_ratio=(0.15, 8.0),     # moderate harmful (outdated info)
        expected_age_decay=(0.85, 10.0),        # HIGH age = key signal for staleness
        expected_source_quality=(0.5, 3.0),     # any source
        prior=0.15,
    ),
    GenerativeModel(
        name="M4",
        label="CONTESTED",
        expected_feedback_ratio=(0.5, 3.0),     # mixed -- low concentration = high variance
        expected_harmful_ratio=(0.35, 8.0),     # notable harmful rate
        expected_age_decay=(0.3, 3.0),          # age-independent
        expected_source_quality=(0.5, 3.0),     # any source
        prior=0.15,
    ),
]


# ---------------------------------------------------------------------------
# Evidence extraction
# ---------------------------------------------------------------------------

@dataclass
class BeliefEvidence:
    """Multi-dimensional evidence vector for one belief."""

    belief_id: str
    belief_type: str
    source_type: str
    locked: bool
    confidence_current: float
    alpha: float
    beta: float

    # Observable dimensions (all normalized to [0, 1])
    feedback_ratio: float       # D1: used / total_feedback
    harmful_ratio: float        # D2: harmful / total_feedback
    age_normalized: float       # D3: age / max_age
    source_quality: float       # D5: source type quality


SOURCE_QUALITY_MAP: dict[str, float] = {
    "user_corrected": 1.0,
    "user_stated": 0.8,
    "document_recent": 0.5,
    "document_old": 0.3,
    "agent_inferred": 0.3,
}


def load_evidence(db_path: str) -> list[BeliefEvidence]:
    """Extract multi-dimensional evidence for all active beliefs."""
    conn: sqlite3.Connection = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get beliefs with their feedback history
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
                      SUM(CASE WHEN outcome = 'used' OR outcome = 'confirmed' THEN 1 ELSE 0 END) as used_count,
                      SUM(CASE WHEN outcome = 'ignored' THEN 1 ELSE 0 END) as ignored_count,
                      SUM(CASE WHEN outcome = 'harmful' THEN 1 ELSE 0 END) as harmful_count,
                      COUNT(*) as total_tests
               FROM tests GROUP BY belief_id
           ) t ON b.id = t.belief_id
           WHERE b.superseded_by IS NULL"""
    ).fetchall()

    # Compute max age for normalization
    ages: list[float] = []
    for r in rows:
        created: str = str(r["created_at"])
        # Simple hour estimate from ISO timestamp
        ages.append(len(created))  # placeholder, compute below

    # Get actual age range
    age_rows: list[sqlite3.Row] = conn.execute(
        """SELECT MIN(created_at) as oldest, MAX(created_at) as newest
           FROM beliefs WHERE superseded_by IS NULL"""
    ).fetchall()

    from datetime import datetime, timezone

    oldest_str: str = str(age_rows[0]["oldest"])
    newest_str: str = str(age_rows[0]["newest"])

    def parse_ts(ts: str) -> datetime:
        dt: datetime = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    oldest_dt: datetime = parse_ts(oldest_str)
    newest_dt: datetime = parse_ts(newest_str)
    max_age_hours: float = max(1.0, (newest_dt - oldest_dt).total_seconds() / 3600.0)

    evidence: list[BeliefEvidence] = []
    for r in rows:
        total: int = int(r["total_tests"])
        used: int = int(r["used_count"])
        ignored: int = int(r["ignored_count"])
        harmful: int = int(r["harmful_count"])

        # D1: feedback ratio (default 0.5 if no feedback -- uninformative)
        fb_ratio: float = used / total if total > 0 else 0.5

        # D2: harmful ratio
        harm_ratio: float = harmful / total if total > 0 else 0.0

        # D3: age normalized to [0, 1]
        created_dt: datetime = parse_ts(str(r["created_at"]))
        age_hours: float = (newest_dt - created_dt).total_seconds() / 3600.0
        age_norm: float = age_hours / max_age_hours

        # D5: source quality
        src_q: float = SOURCE_QUALITY_MAP.get(str(r["source_type"]), 0.5)

        evidence.append(BeliefEvidence(
            belief_id=str(r["id"]),
            belief_type=str(r["belief_type"]),
            source_type=str(r["source_type"]),
            locked=bool(r["locked"]),
            confidence_current=float(r["confidence"]),
            alpha=float(r["alpha"]),
            beta=float(r["beta_param"]),
            feedback_ratio=fb_ratio,
            harmful_ratio=harm_ratio,
            age_normalized=age_norm,
            source_quality=src_q,
        ))

    conn.close()
    return evidence


# ---------------------------------------------------------------------------
# Likelihood computation (archaeology-style)
# ---------------------------------------------------------------------------

def beta_log_likelihood(x: float, mu: float, kappa: float) -> float:
    """Log-likelihood of observing x under Beta(mu*kappa, (1-mu)*kappa).

    This is the archaeology-style approach: the model predicts an expected
    value mu for the observable, with concentration kappa controlling how
    "sure" the model is. Higher kappa = narrower distribution = more
    discriminative.

    Uses the Beta PDF: p(x; a, b) = x^(a-1) * (1-x)^(b-1) / B(a, b)
    """
    a: float = max(0.01, mu * kappa)
    b: float = max(0.01, (1.0 - mu) * kappa)
    x_safe: float = max(0.001, min(0.999, x))

    # Log Beta PDF (unnormalized is fine since we compare across models)
    log_p: float = (a - 1.0) * math.log(x_safe) + (b - 1.0) * math.log(1.0 - x_safe)
    # Normalize with log Beta function
    log_beta: float = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    return log_p - log_beta


def model_log_likelihood(ev: BeliefEvidence, model: GenerativeModel) -> float:
    """Joint log-likelihood of all evidence dimensions under one model.

    Assumes conditional independence of dimensions given the model
    (same assumption as the archaeology example: P(GD|C) = pG(c) * pD(c)).
    """
    ll: float = 0.0
    ll += beta_log_likelihood(ev.feedback_ratio, *model.expected_feedback_ratio)
    ll += beta_log_likelihood(ev.harmful_ratio, *model.expected_harmful_ratio)
    ll += beta_log_likelihood(ev.age_normalized, *model.expected_age_decay)
    ll += beta_log_likelihood(ev.source_quality, *model.expected_source_quality)
    return ll


# ---------------------------------------------------------------------------
# Posterior computation and model selection
# ---------------------------------------------------------------------------

@dataclass
class ModelPosterior:
    """Posterior probability of each model for one belief."""

    belief_id: str
    posteriors: dict[str, float] = field(default_factory=dict)
    map_model: str = ""
    map_probability: float = 0.0
    bayes_factor_signal_vs_noise: float = 0.0
    entropy: float = 0.0  # Shannon entropy of posterior -- low = confident classification


def compute_posterior(ev: BeliefEvidence) -> ModelPosterior:
    """Compute posterior P(M|evidence) for all models.

    P(M|E) = P(E|M) * P(M) / sum_j(P(E|Mj) * P(Mj))

    This is the direct analogue of the archaeology formula:
    f_C(c|E=e) = P(E=e|C=c) / integral(P(E=e|C=c) * f_C(c) dc) * f_C(c)
    """
    # Compute log-posterior (unnormalized) for each model
    log_posteriors: dict[str, float] = {}
    for m in MODELS:
        ll: float = model_log_likelihood(ev, m)
        log_prior: float = math.log(max(1e-10, m.prior))
        log_posteriors[m.name] = ll + log_prior

    # Normalize via log-sum-exp
    max_lp: float = max(log_posteriors.values())
    log_norm: float = max_lp + math.log(
        sum(math.exp(lp - max_lp) for lp in log_posteriors.values())
    )

    posteriors: dict[str, float] = {}
    for name, lp in log_posteriors.items():
        posteriors[name] = math.exp(lp - log_norm)

    # MAP model
    map_name: str = max(posteriors, key=lambda k: posteriors[k])
    map_prob: float = posteriors[map_name]

    # Bayes factor: M1 (SIGNAL) vs M2 (NOISE)
    bf: float = 0.0
    if posteriors.get("M2", 0) > 1e-10:
        bf = posteriors.get("M1", 0) / posteriors["M2"]

    # Shannon entropy of posterior
    h: float = 0.0
    for p in posteriors.values():
        if p > 1e-10:
            h -= p * math.log2(p)

    return ModelPosterior(
        belief_id=ev.belief_id,
        posteriors=posteriors,
        map_model=map_name,
        map_probability=map_prob,
        bayes_factor_signal_vs_noise=bf,
        entropy=h,
    )


# ---------------------------------------------------------------------------
# Scoring: convert model posterior to a single confidence score
# ---------------------------------------------------------------------------

# Model-specific confidence mappings.
# A belief classified as SIGNAL gets high confidence.
# A belief classified as NOISE gets low confidence.
# STALE gets moderate-to-low. CONTESTED gets moderate.
MODEL_CONFIDENCE: dict[str, float] = {
    "M1": 0.85,   # SIGNAL -> high confidence
    "M2": 0.25,   # NOISE -> low confidence
    "M3": 0.35,   # STALE -> low-moderate
    "M4": 0.55,   # CONTESTED -> moderate (needs more evidence)
}


def multimodel_score(posterior: ModelPosterior) -> float:
    """Compute a single confidence score from the model posterior.

    This is a weighted average of model-specific confidence values,
    weighted by posterior probability. Analogous to the archaeology
    example's point estimate: E[C|evidence] = integral(c * f_C(c|E) dc).
    """
    score: float = 0.0
    for model_name, prob in posterior.posteriors.items():
        score += prob * MODEL_CONFIDENCE.get(model_name, 0.5)
    return score


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def gini(values: list[float]) -> float:
    """Gini coefficient."""
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

    print("=" * 78)
    print("Exp 93: Multi-Model Bayesian Scoring (Archaeology-Style)")
    print("=" * 78)

    # Load evidence
    evidence: list[BeliefEvidence] = load_evidence(db_path)
    print(f"Population: {len(evidence)} active beliefs")
    print()

    # Current system scores
    current_confs: list[float] = [e.confidence_current for e in evidence]
    current_gini: float = gini(current_confs)

    # Compute posteriors for all beliefs
    posteriors: list[ModelPosterior] = [compute_posterior(e) for e in evidence]
    new_scores: list[float] = [multimodel_score(p) for p in posteriors]
    new_gini: float = gini(new_scores)

    # --- Summary ---
    print("## POPULATION COMPARISON")
    print(f"  Current Gini:     {current_gini:.4f}")
    print(f"  Multi-model Gini: {new_gini:.4f} ({new_gini - current_gini:+.4f})")
    print()

    # Current confidence distribution
    current_buckets: Counter[str] = Counter()
    for c in current_confs:
        if c >= 0.8:
            current_buckets["0.8-1.0"] += 1
        elif c >= 0.6:
            current_buckets["0.6-0.8"] += 1
        elif c >= 0.4:
            current_buckets["0.4-0.6"] += 1
        elif c >= 0.2:
            current_buckets["0.2-0.4"] += 1
        else:
            current_buckets["0.0-0.2"] += 1

    new_buckets: Counter[str] = Counter()
    for s in new_scores:
        if s >= 0.8:
            new_buckets["0.8-1.0"] += 1
        elif s >= 0.6:
            new_buckets["0.6-0.8"] += 1
        elif s >= 0.4:
            new_buckets["0.4-0.6"] += 1
        elif s >= 0.2:
            new_buckets["0.2-0.4"] += 1
        else:
            new_buckets["0.0-0.2"] += 1

    print("  Confidence distribution:")
    print(f"  {'Bucket':>8s}  {'Current':>8s}  {'%':>5s}  {'Multi-M':>8s}  {'%':>5s}")
    for bucket in ["0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]:
        c_count: int = current_buckets.get(bucket, 0)
        n_count: int = new_buckets.get(bucket, 0)
        c_pct: float = c_count / len(evidence) * 100
        n_pct: float = n_count / len(evidence) * 100
        print(f"  {bucket:>8s}  {c_count:>8d}  {c_pct:>4.1f}%  {n_count:>8d}  {n_pct:>4.1f}%")
    print()

    # --- MAP model distribution ---
    print("## MAP MODEL DISTRIBUTION")
    map_counts: Counter[str] = Counter(p.map_model for p in posteriors)
    model_labels: dict[str, str] = {m.name: m.label for m in MODELS}
    for name in ["M1", "M2", "M3", "M4"]:
        count: int = map_counts.get(name, 0)
        pct: float = count / len(posteriors) * 100
        print(f"  {name} ({model_labels[name]:>10s}): {count:>6d} ({pct:>5.1f}%)")
    print()

    # --- Posterior entropy (confidence in classification) ---
    entropies: list[float] = [p.entropy for p in posteriors]
    avg_entropy: float = sum(entropies) / len(entropies)
    low_entropy: int = sum(1 for e in entropies if e < 0.5)
    high_entropy: int = sum(1 for e in entropies if e > 1.5)
    print("## CLASSIFICATION CONFIDENCE")
    print(f"  Avg posterior entropy: {avg_entropy:.3f} bits (max = 2.0 for 4 models)")
    print(f"  Confident (H < 0.5):  {low_entropy:>6d} ({low_entropy / len(posteriors) * 100:.1f}%)")
    print(f"  Uncertain (H > 1.5):  {high_entropy:>6d} ({high_entropy / len(posteriors) * 100:.1f}%)")
    print()

    # --- Bayes factor analysis ---
    bf_values: list[float] = [p.bayes_factor_signal_vs_noise for p in posteriors]
    strong_signal: int = sum(1 for bf in bf_values if bf > 3.0)
    strong_noise: int = sum(1 for bf in bf_values if bf < 1.0 / 3.0)
    equivocal: int = len(bf_values) - strong_signal - strong_noise
    print("## BAYES FACTORS (SIGNAL vs NOISE)")
    print(f"  Strong evidence for SIGNAL (BF > 3):  {strong_signal:>6d} ({strong_signal / len(posteriors) * 100:.1f}%)")
    print(f"  Strong evidence for NOISE (BF < 1/3): {strong_noise:>6d} ({strong_noise / len(posteriors) * 100:.1f}%)")
    print(f"  Equivocal (1/3 < BF < 3):            {equivocal:>6d} ({equivocal / len(posteriors) * 100:.1f}%)")
    print()

    # --- Cross-reference: how do model assignments correlate with belief type? ---
    print("## MODEL x BELIEF TYPE CROSS-TABULATION")
    type_model: dict[str, Counter[str]] = {}
    for ev, post in zip(evidence, posteriors):
        if ev.belief_type not in type_model:
            type_model[ev.belief_type] = Counter()
        type_model[ev.belief_type][post.map_model] += 1

    header: str = f"  {'Type':>15s}"
    for name in ["M1", "M2", "M3", "M4"]:
        header += f"  {model_labels[name]:>10s}"
    header += "  {'Total':>6s}"
    print(f"  {'Type':>15s}  {'SIGNAL':>10s}  {'NOISE':>10s}  {'STALE':>10s}  {'CONTESTED':>10s}  {'Total':>6s}")
    for bt in sorted(type_model.keys()):
        counts: Counter[str] = type_model[bt]
        total: int = sum(counts.values())
        parts: list[str] = [f"  {bt:>15s}"]
        for name in ["M1", "M2", "M3", "M4"]:
            c: int = counts.get(name, 0)
            parts.append(f"{c:>10d}")
        parts.append(f"{total:>6d}")
        print("  ".join(parts))
    print()

    # --- Cross-reference: model assignments vs source type ---
    print("## MODEL x SOURCE TYPE CROSS-TABULATION")
    source_model: dict[str, Counter[str]] = {}
    for ev, post in zip(evidence, posteriors):
        if ev.source_type not in source_model:
            source_model[ev.source_type] = Counter()
        source_model[ev.source_type][post.map_model] += 1

    print(f"  {'Source':>17s}  {'SIGNAL':>10s}  {'NOISE':>10s}  {'STALE':>10s}  {'CONTESTED':>10s}  {'Total':>6s}")
    for st in sorted(source_model.keys()):
        counts = source_model[st]
        total = sum(counts.values())
        parts = [f"  {st:>17s}"]
        for name in ["M1", "M2", "M3", "M4"]:
            c = counts.get(name, 0)
            parts.append(f"{c:>10d}")
        parts.append(f"{total:>6d}")
        print("  ".join(parts))
    print()

    # --- Locked beliefs: what model are they? ---
    print("## LOCKED BELIEF MODEL ASSIGNMENTS")
    locked_posts: list[ModelPosterior] = [
        p for e, p in zip(evidence, posteriors) if e.locked
    ]
    if locked_posts:
        locked_map: Counter[str] = Counter(p.map_model for p in locked_posts)
        for name in ["M1", "M2", "M3", "M4"]:
            c = locked_map.get(name, 0)
            print(f"  {name} ({model_labels[name]:>10s}): {c}")
        locked_avg_entropy: float = sum(p.entropy for p in locked_posts) / len(locked_posts)
        print(f"  Avg entropy: {locked_avg_entropy:.3f} (should be low -- locked beliefs should be classifiable)")
    print()

    # --- Rank disruption: how much would rankings change? ---
    print("## RANK DISRUPTION ANALYSIS")
    # Sort by current confidence, get ranks
    current_ranked: list[tuple[str, float]] = sorted(
        [(e.belief_id, e.confidence_current) for e in evidence],
        key=lambda x: x[1],
        reverse=True,
    )
    current_rank: dict[str, int] = {bid: i for i, (bid, _) in enumerate(current_ranked)}

    # Sort by new scores, get ranks
    new_ranked: list[tuple[str, float]] = sorted(
        [(p.belief_id, multimodel_score(p)) for p in posteriors],
        key=lambda x: x[1],
        reverse=True,
    )
    new_rank: dict[str, int] = {bid: i for i, (bid, _) in enumerate(new_ranked)}

    # Compute rank displacement
    displacements: list[int] = []
    for bid in current_rank:
        old_r: int = current_rank[bid]
        new_r: int = new_rank.get(bid, old_r)
        displacements.append(abs(old_r - new_r))

    avg_disp: float = sum(displacements) / len(displacements) if displacements else 0
    max_disp: int = max(displacements) if displacements else 0
    moved_100: int = sum(1 for d in displacements if d > 100)
    moved_1000: int = sum(1 for d in displacements if d > 1000)

    print(f"  Avg rank displacement: {avg_disp:.0f}")
    print(f"  Max rank displacement: {max_disp}")
    print(f"  Beliefs moving >100 ranks:  {moved_100} ({moved_100 / len(evidence) * 100:.1f}%)")
    print(f"  Beliefs moving >1000 ranks: {moved_1000} ({moved_1000 / len(evidence) * 100:.1f}%)")
    print()

    # --- Top 20 beliefs that gain most / lose most ---
    print("## BIGGEST RANK CHANGES (top 10 winners, top 10 losers)")
    rank_changes: list[tuple[str, int, int, float, float]] = []
    ev_map: dict[str, BeliefEvidence] = {e.belief_id: e for e in evidence}
    post_map: dict[str, ModelPosterior] = {p.belief_id: p for p in posteriors}

    for bid in current_rank:
        old_r = current_rank[bid]
        new_r = new_rank.get(bid, old_r)
        old_conf: float = ev_map[bid].confidence_current
        new_conf: float = multimodel_score(post_map[bid])
        rank_changes.append((bid, old_r, new_r, old_conf, new_conf))

    # Biggest winners (moved up = old_r - new_r > 0)
    winners: list[tuple[str, int, int, float, float]] = sorted(
        rank_changes, key=lambda x: x[1] - x[2], reverse=True
    )[:10]
    print("  Winners (promoted):")
    print(f"    {'ID':>12s}  {'Old Rank':>8s}  {'New Rank':>8s}  {'Delta':>6s}  {'Old Conf':>8s}  {'New Score':>9s}  {'MAP Model':>10s}")
    for bid, old_r, new_r, old_c, new_c in winners:
        delta: int = old_r - new_r
        map_m: str = post_map[bid].map_model
        print(f"    {bid:>12s}  {old_r:>8d}  {new_r:>8d}  {delta:>+6d}  {old_c:>8.3f}  {new_c:>9.3f}  {map_m} ({model_labels[map_m]})")

    losers: list[tuple[str, int, int, float, float]] = sorted(
        rank_changes, key=lambda x: x[1] - x[2]
    )[:10]
    print("  Losers (demoted):")
    print(f"    {'ID':>12s}  {'Old Rank':>8s}  {'New Rank':>8s}  {'Delta':>6s}  {'Old Conf':>8s}  {'New Score':>9s}  {'MAP Model':>10s}")
    for bid, old_r, new_r, old_c, new_c in losers:
        delta = old_r - new_r
        map_m = post_map[bid].map_model
        print(f"    {bid:>12s}  {old_r:>8d}  {new_r:>8d}  {delta:>+6d}  {old_c:>8.3f}  {new_c:>9.3f}  {map_m} ({model_labels[map_m]})")
    print()

    # --- Diagnosis ---
    print("=" * 78)
    print("## DIAGNOSIS")
    print("=" * 78)
    print()

    if new_gini > current_gini + 0.05:
        print("  POSITIVE: Multi-model scoring increases Gini by "
              f"{new_gini - current_gini:+.4f}")
        print("  The archaeology-style multi-dimensional evidence creates")
        print("  meaningful population differentiation.")
    elif new_gini > current_gini:
        print("  MARGINAL: Gini increase is small "
              f"({new_gini - current_gini:+.4f})")
        print("  Multi-model scoring provides some differentiation but")
        print("  may not justify the added complexity.")
    else:
        print("  NEGATIVE: Multi-model scoring does not improve Gini.")
        print("  The evidence dimensions may not be discriminative enough,")
        print("  or the model priors need calibration.")

    print()
    noise_pct: float = map_counts.get("M2", 0) / len(posteriors) * 100
    signal_pct: float = map_counts.get("M1", 0) / len(posteriors) * 100
    if noise_pct > 70:
        print(f"  WARNING: {noise_pct:.0f}% of beliefs classified as NOISE.")
        print("  This may indicate:")
        print("    1. The feedback loop is too sparse (most beliefs have zero feedback)")
        print("    2. The M2 prior (0.40) is too aggressive")
        print("    3. The NOISE model's likelihood is too broad (catches everything)")
    elif noise_pct > 50:
        print(f"  PLAUSIBLE: {noise_pct:.0f}% NOISE is expected for an agent-inferred-heavy corpus")
    else:
        print(f"  INTERESTING: Only {noise_pct:.0f}% NOISE -- more signal than expected")

    print()
    print("  Bernstein-von Mises applicability:")
    print("  The archaeology example converges after ~50 fragments because the")
    print("  evidence space is finite ({GD, GD_, G_D, G_D_}).")
    with_feedback: int = sum(1 for e in evidence if e.feedback_ratio != 0.5)
    print(f"  In our system, {with_feedback}/{len(evidence)} beliefs have any feedback.")
    if with_feedback < len(evidence) * 0.1:
        print("  SPARSE: <10% of beliefs have feedback evidence.")
        print("  The posterior is dominated by the prior for most beliefs.")
        print("  Convergence requires more feedback events, not better models.")
    else:
        print(f"  ADEQUATE: {with_feedback / len(evidence) * 100:.0f}% have evidence.")
        print("  Posterior should be partially converged for these beliefs.")


if __name__ == "__main__":
    main()
