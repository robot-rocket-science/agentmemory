"""Multi-axis confidence scoring for beliefs (Exp 91).

Replaces the single alpha/beta pair with three independent Beta priors:
  - accuracy:  is the content factually correct?
  - relevance: does it surface for the right queries?
  - freshness: is it still current?

Each axis receives different feedback signals. The composite score is the
product of Thompson samples from each axis, so a belief must be accurate
AND relevant to rank highly.

Reuses BetaAxis from uncertainty.py for the per-axis math.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field

from agentmemory.uncertainty import BetaAxis

# Axis indices
AXIS_ACCURACY: int = 0
AXIS_RELEVANCE: int = 1
AXIS_FRESHNESS: int = 2

AXIS_NAMES: list[str] = ["accuracy", "relevance", "freshness"]

# Outcome -> axis routing.
# Each outcome maps to (axis_index, is_positive, weight_multiplier).
# The weight_multiplier scales the base evidence weight.
OUTCOME_ROUTING: dict[str, list[tuple[int, bool, float]]] = {
    # "used" = agent acted on it -> relevance positive signal
    "used": [(AXIS_RELEVANCE, True, 0.5)],
    # "confirmed" = explicitly confirmed correct -> accuracy + relevance
    "confirmed": [
        (AXIS_ACCURACY, True, 1.0),
        (AXIS_RELEVANCE, True, 0.5),
    ],
    # "ignored" = retrieved but not acted on -> weak relevance negative
    "ignored": [(AXIS_RELEVANCE, False, 0.1)],
    # "harmful" = caused wrong behavior -> accuracy negative (strong)
    "harmful": [(AXIS_ACCURACY, False, 2.0)],
    # "contradicted" = directly contradicted by evidence -> accuracy negative
    "contradicted": [(AXIS_ACCURACY, False, 1.0)],
    # "weak" = low quality signal -> mild accuracy negative
    "weak": [(AXIS_ACCURACY, False, 0.6)],
}


@dataclass
class ConfidenceAxes:
    """Three independent Beta priors for belief confidence.

    Serializes to/from the existing uncertainty_vector JSON column
    as [[a,b], [a,b], [a,b]].
    """

    accuracy: BetaAxis = field(default_factory=lambda: BetaAxis(1.0, 1.0))
    relevance: BetaAxis = field(default_factory=lambda: BetaAxis(1.0, 1.0))
    freshness: BetaAxis = field(default_factory=lambda: BetaAxis(1.0, 1.0))

    def axis(self, index: int) -> BetaAxis:
        """Get axis by index."""
        if index == AXIS_ACCURACY:
            return self.accuracy
        if index == AXIS_RELEVANCE:
            return self.relevance
        if index == AXIS_FRESHNESS:
            return self.freshness
        msg = f"Invalid axis index: {index}"
        raise ValueError(msg)

    @staticmethod
    def from_json(s: str) -> ConfidenceAxes:
        """Parse from JSON array of [alpha, beta] pairs."""
        pairs: list[list[float]] = json.loads(s)
        if len(pairs) < 3:
            # Pad with uninformative priors if fewer than 3 axes
            while len(pairs) < 3:
                pairs.append([1.0, 1.0])
        return ConfidenceAxes(
            accuracy=BetaAxis(alpha=pairs[0][0], beta_param=pairs[0][1]),
            relevance=BetaAxis(alpha=pairs[1][0], beta_param=pairs[1][1]),
            freshness=BetaAxis(alpha=pairs[2][0], beta_param=pairs[2][1]),
        )

    @staticmethod
    def from_single_prior(alpha: float, beta_param: float) -> ConfidenceAxes:
        """Create from legacy single alpha/beta by mapping to relevance axis.

        Used for backfill migration: existing alpha/beta becomes the relevance
        prior (since most historical feedback was used/ignored). Accuracy and
        freshness start uninformative.
        """
        return ConfidenceAxes(
            accuracy=BetaAxis(1.0, 1.0),
            relevance=BetaAxis(alpha=alpha, beta_param=beta_param),
            freshness=BetaAxis(1.0, 1.0),
        )

    def to_json(self) -> str:
        """Serialize to JSON array of [alpha, beta] pairs."""
        return json.dumps(
            [
                [self.accuracy.alpha, self.accuracy.beta_param],
                [self.relevance.alpha, self.relevance.beta_param],
                [self.freshness.alpha, self.freshness.beta_param],
            ]
        )

    def update(self, outcome: str, weight: float = 1.0) -> None:
        """Route a feedback outcome to the appropriate axis/axes.

        Uses OUTCOME_ROUTING to determine which axis gets updated
        and in which direction.
        """
        routes: list[tuple[int, bool, float]] | None = OUTCOME_ROUTING.get(outcome)
        if routes is None:
            return
        for axis_idx, is_positive, multiplier in routes:
            ax: BetaAxis = self.axis(axis_idx)
            ax.update(is_positive, weight * multiplier)

    def composite_sample(self) -> float:
        """Product of Thompson samples from each axis.

        A belief must score well on ALL axes to rank highly.
        Returns a value in roughly [0, 1] (can exceed 1 if all axes
        have strong positive priors).
        """
        samples: list[float] = []
        for ax in [self.accuracy, self.relevance, self.freshness]:
            safe_a: float = max(ax.alpha, 1e-6)
            safe_b: float = max(ax.beta_param, 1e-6)
            samples.append(random.betavariate(safe_a, safe_b))
        return samples[0] * samples[1] * samples[2]

    def composite_mean(self) -> float:
        """Deterministic composite: product of axis means.

        For testing and debugging where Thompson sampling variance
        is undesirable.
        """
        return self.accuracy.mean * self.relevance.mean * self.freshness.mean

    def summary(self) -> dict[str, dict[str, float]]:
        """Human-readable axis summary."""
        result: dict[str, dict[str, float]] = {}
        for name, ax in zip(
            AXIS_NAMES, [self.accuracy, self.relevance, self.freshness], strict=True
        ):
            result[name] = {
                "mean": round(ax.mean, 3),
                "alpha": round(ax.alpha, 3),
                "beta": round(ax.beta_param, 3),
                "variance": round(ax.variance, 4),
            }
        return result

    @property
    def legacy_confidence(self) -> float:
        """Backward-compatible single confidence value.

        Geometric mean of axis means, which penalizes any weak axis
        while staying in [0, 1].
        """
        product: float = self.accuracy.mean * self.relevance.mean * self.freshness.mean
        return product ** (1.0 / 3.0)
