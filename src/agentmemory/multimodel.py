"""Multi-model Bayesian scoring for beliefs with feedback history.

Adapted from Exp 93/93b (archaeology-style Bayesian inference). Assigns each
belief with feedback to one of four generative models (SIGNAL, NOISE, STALE,
CONTESTED) based on multi-dimensional evidence. Returns a quality multiplier
for use in the scoring pipeline.

Only applied to beliefs that have at least one feedback event. Beliefs without
feedback return a neutral multiplier (1.0) -- the posterior would be prior-
dominated and uninformative (Exp 93 finding).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class _ModelSpec:
    """Likelihood parameters for one generative model."""

    name: str
    label: str
    # (mu, kappa) for Beta likelihood on each evidence dimension
    feedback_ratio: tuple[float, float]
    harmful_ratio: tuple[float, float]
    age_decay: tuple[float, float]
    source_quality: tuple[float, float]
    prior: float


_MODELS: tuple[_ModelSpec, ...] = (
    _ModelSpec(
        "M1",
        "SIGNAL",
        feedback_ratio=(0.8, 10.0),
        harmful_ratio=(0.05, 20.0),
        age_decay=(0.5, 5.0),
        source_quality=(0.6, 5.0),
        prior=0.30,
    ),
    _ModelSpec(
        "M2",
        "NOISE",
        feedback_ratio=(0.15, 10.0),
        harmful_ratio=(0.1, 10.0),
        age_decay=(0.5, 3.0),
        source_quality=(0.3, 8.0),
        prior=0.40,
    ),
    _ModelSpec(
        "M3",
        "STALE",
        feedback_ratio=(0.4, 5.0),
        harmful_ratio=(0.15, 8.0),
        age_decay=(0.85, 10.0),
        source_quality=(0.5, 3.0),
        prior=0.15,
    ),
    _ModelSpec(
        "M4",
        "CONTESTED",
        feedback_ratio=(0.5, 3.0),
        harmful_ratio=(0.35, 8.0),
        age_decay=(0.3, 3.0),
        source_quality=(0.5, 3.0),
        prior=0.15,
    ),
)

# Scoring multiplier per model. SIGNAL beliefs get boosted, NOISE gets penalized.
# These are multiplicative on top of the existing score_belief() output.
_MODEL_MULTIPLIER: dict[str, float] = {
    "M1": 1.3,  # SIGNAL: boost by 30%
    "M2": 0.6,  # NOISE: penalize by 40%
    "M3": 0.8,  # STALE: mild penalty
    "M4": 1.0,  # CONTESTED: neutral (needs more evidence)
}

_SOURCE_QUALITY: dict[str, float] = {
    "user_corrected": 1.0,
    "user_stated": 0.8,
    "document_recent": 0.5,
    "document_old": 0.3,
    "agent_inferred": 0.3,
}


def _beta_log_likelihood(x: float, mu: float, kappa: float) -> float:
    """Log-likelihood of x under Beta(mu*kappa, (1-mu)*kappa)."""
    a: float = max(0.01, mu * kappa)
    b: float = max(0.01, (1.0 - mu) * kappa)
    x_safe: float = max(0.001, min(0.999, x))
    log_p: float = (a - 1.0) * math.log(x_safe) + (b - 1.0) * math.log(1.0 - x_safe)
    log_beta: float = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    return log_p - log_beta


def multimodel_multiplier(
    used_count: int,
    ignored_count: int,
    harmful_count: int,
    age_normalized: float,
    source_type: str,
) -> float:
    """Compute a scoring multiplier from multi-model Bayesian classification.

    Only meaningful when total feedback > 0. Returns 1.0 (neutral) when
    there is no feedback data.

    Args:
        used_count: Number of "used" or "confirmed" feedback events.
        ignored_count: Number of "ignored" feedback events.
        harmful_count: Number of "harmful" feedback events.
        age_normalized: Belief age normalized to [0, 1] (0=newest, 1=oldest).
        source_type: Belief source type string.

    Returns:
        Multiplier in [0.6, 1.3] based on MAP model classification.
    """
    total: int = used_count + ignored_count + harmful_count
    if total == 0:
        return 1.0

    # Evidence dimensions
    feedback_ratio: float = used_count / total
    harmful_ratio: float = harmful_count / total
    source_quality: float = _SOURCE_QUALITY.get(source_type, 0.5)

    # Compute log-posterior for each model
    log_posteriors: dict[str, float] = {}
    for m in _MODELS:
        ll: float = 0.0
        ll += _beta_log_likelihood(feedback_ratio, *m.feedback_ratio)
        ll += _beta_log_likelihood(harmful_ratio, *m.harmful_ratio)
        ll += _beta_log_likelihood(age_normalized, *m.age_decay)
        ll += _beta_log_likelihood(source_quality, *m.source_quality)
        log_posteriors[m.name] = ll + math.log(max(1e-10, m.prior))

    # MAP model
    map_model: str = max(log_posteriors, key=lambda k: log_posteriors[k])
    return _MODEL_MULTIPLIER.get(map_model, 1.0)
