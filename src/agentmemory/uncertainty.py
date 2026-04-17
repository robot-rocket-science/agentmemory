"""Multi-dimensional Bayesian uncertainty tracking for speculative beliefs.

Each speculative belief carries a vector of independent Beta(alpha, beta)
distributions, one per uncertainty dimension. This module provides the
math for entropy calculation, evidence propagation, value of information,
and hibernation scoring.

References:
- Bishop (2006), Pattern Recognition and Machine Learning, Section 2.1-2.2
- Cover & Thomas (2006), Elements of Information Theory, Theorem 2.6.6
- Chaloner & Verdinelli (1995), Bayesian Experimental Design
- Pearl (1988), Probabilistic Reasoning in Intelligent Systems, Chapter 4
- Russo & Van Roy (2018), Learning to Optimize via Information-Directed Sampling
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field


# Default uncertainty dimensions for speculative beliefs
DIMENSION_FEASIBILITY: int = 0
DIMENSION_VALUE: int = 1
DIMENSION_COST: int = 2
DIMENSION_DEPENDENCY: int = 3

DIMENSION_NAMES: list[str] = ["feasibility", "value", "cost", "dependency"]

# Maximum entropy for one Beta distribution (Beta(1,1) = Uniform)
_MAX_SINGLE_ENTROPY: float = math.log(2.0)  # ln(2) ~ 0.693


def _digamma(x: float) -> float:
    """Digamma function approximation (psi(x)).

    Uses the asymptotic series for x >= 6 and recurrence relation for x < 6.
    Accurate to ~1e-8 for x > 0.
    """
    result: float = 0.0
    while x < 6.0:
        result -= 1.0 / x
        x += 1.0
    # Asymptotic expansion for large x
    result += math.log(x) - 0.5 / x
    x2: float = 1.0 / (x * x)
    result -= x2 * (1.0 / 12.0 - x2 * (1.0 / 120.0 - x2 / 252.0))
    return result


def _log_beta(a: float, b: float) -> float:
    """Log of the Beta function: ln(B(a,b)) = lgamma(a) + lgamma(b) - lgamma(a+b)."""
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


@dataclass
class BetaAxis:
    """A single uncertainty dimension with Beta distribution parameters."""
    alpha: float = 1.0  # success count (1.0 = uninformative prior)
    beta_param: float = 1.0  # failure count

    @property
    def mean(self) -> float:
        """Expected value: alpha / (alpha + beta_param)."""
        total: float = self.alpha + self.beta_param
        return self.alpha / total if total > 0 else 0.5

    @property
    def variance(self) -> float:
        """Variance of the Beta distribution."""
        a: float = self.alpha
        b: float = self.beta_param
        total: float = a + b
        if total <= 0:
            return 0.25
        return (a * b) / (total * total * (total + 1.0))

    def entropy(self) -> float:
        """Differential entropy of Beta(alpha, beta_param).

        H = ln(B(a,b)) - (a-1)*psi(a) - (b-1)*psi(b) + (a+b-2)*psi(a+b)
        """
        a: float = max(0.01, self.alpha)
        b: float = max(0.01, self.beta_param)
        return (
            _log_beta(a, b)
            - (a - 1.0) * _digamma(a)
            - (b - 1.0) * _digamma(b)
            + (a + b - 2.0) * _digamma(a + b)
        )

    def update(self, outcome: bool, weight: float = 1.0) -> None:
        """Bayesian update: success increments alpha, failure increments beta_param."""
        if outcome:
            self.alpha += weight
        else:
            self.beta_param += weight

    def expected_entropy_after_observation(self) -> float:
        """Expected entropy after observing one binary outcome.

        E[H_post] = P(success) * H(Beta(a+1, b)) + P(failure) * H(Beta(a, b+1))

        Used for Value of Information calculation.
        """
        p_success: float = self.mean
        h_success: float = BetaAxis(self.alpha + 1, self.beta_param).entropy()
        h_failure: float = BetaAxis(self.alpha, self.beta_param + 1).entropy()
        return p_success * h_success + (1.0 - p_success) * h_failure


@dataclass
class UncertaintyVector:
    """Multi-dimensional uncertainty for a speculative belief.

    Each dimension is an independent Beta distribution. Joint entropy
    is the sum of individual entropies (independence assumption).
    """
    axes: list[BetaAxis] = field(default_factory=lambda: [
        BetaAxis(1.0, 1.0),  # feasibility
        BetaAxis(1.0, 1.0),  # value
        BetaAxis(1.0, 1.0),  # cost
        BetaAxis(1.0, 1.0),  # dependency
    ])

    @staticmethod
    def from_json(s: str) -> UncertaintyVector:
        """Parse from JSON array of [alpha, beta] pairs."""
        pairs: list[list[float]] = json.loads(s)
        return UncertaintyVector(
            axes=[BetaAxis(alpha=p[0], beta_param=p[1]) for p in pairs]
        )

    def to_json(self) -> str:
        """Serialize to JSON array of [alpha, beta] pairs."""
        return json.dumps([[a.alpha, a.beta_param] for a in self.axes])

    @property
    def n_dimensions(self) -> int:
        return len(self.axes)

    def joint_entropy(self) -> float:
        """Sum of individual Beta entropies (independent axes)."""
        return sum(axis.entropy() for axis in self.axes)

    def max_entropy(self) -> float:
        """Maximum possible joint entropy (all axes at Beta(1,1))."""
        return self.n_dimensions * _MAX_SINGLE_ENTROPY

    def normalized_entropy(self) -> float:
        """Joint entropy as fraction of maximum [0, 1]."""
        h_max: float = self.max_entropy()
        if h_max <= 0:
            return 0.0
        return self.joint_entropy() / h_max

    def update_dimension(self, dimension: int, outcome: bool, weight: float = 1.0) -> None:
        """Update a single dimension with new evidence."""
        if 0 <= dimension < len(self.axes):
            self.axes[dimension].update(outcome, weight)

    def voi(self, dimension: int) -> float:
        """Value of Information: expected entropy reduction from one observation on this dimension.

        VOI = H_prior - E[H_posterior]
        """
        if dimension < 0 or dimension >= len(self.axes):
            return 0.0
        axis: BetaAxis = self.axes[dimension]
        h_prior: float = axis.entropy()
        h_expected_post: float = axis.expected_entropy_after_observation()
        return max(0.0, h_prior - h_expected_post)

    def best_experiment_dimension(self) -> int:
        """Which dimension has the highest VOI (most valuable to resolve)?"""
        voi_values: list[float] = [self.voi(i) for i in range(len(self.axes))]
        return max(range(len(voi_values)), key=lambda i: voi_values[i])

    def mean_variance(self) -> float:
        """Average variance across all dimensions. Lower = more certain."""
        if not self.axes:
            return 0.25
        return sum(axis.variance for axis in self.axes) / len(self.axes)

    def hibernation_score(self) -> float:
        """Score for soft-closing: high when promising and well-understood,
        low when unpromising or highly uncertain.

        S = max_mean * (1 - 4 * mean_variance)

        Uses variance (always in [0, 0.25] for Beta) instead of entropy
        to avoid issues with negative differential entropy. Factor of 4
        normalizes variance to [0, 1] range.

        Ranges from 0 (completely uncertain or all axes near 0) to ~1
        (high confidence on at least one axis, low overall uncertainty).
        """
        if not self.axes:
            return 0.0
        max_mean: float = max(axis.mean for axis in self.axes)
        norm_var: float = min(1.0, 4.0 * self.mean_variance())
        return max_mean * (1.0 - norm_var)

    def dimension_summary(self) -> dict[str, dict[str, float]]:
        """Human-readable summary of each dimension."""
        result: dict[str, dict[str, float]] = {}
        for i, axis in enumerate(self.axes):
            name: str = DIMENSION_NAMES[i] if i < len(DIMENSION_NAMES) else f"dim_{i}"
            result[name] = {
                "mean": round(axis.mean, 3),
                "variance": round(axis.variance, 4),
                "entropy": round(axis.entropy(), 4),
                "voi": round(self.voi(i), 4),
            }
        return result


def propagate_evidence(
    source_vector: UncertaintyVector,
    source_dimension: int,
    target_vector: UncertaintyVector,
    target_dimension: int,
    weight: float,
    delta_alpha: float,
    delta_beta: float,
) -> None:
    """Propagate evidence from one node's dimension to another's.

    Simplified Belief Propagation: the update to the source dimension
    is scaled by the edge weight and applied to the target dimension.
    """
    if target_dimension < 0 or target_dimension >= target_vector.n_dimensions:
        return
    target_vector.axes[target_dimension].alpha += weight * delta_alpha
    target_vector.axes[target_dimension].beta_param += weight * delta_beta
