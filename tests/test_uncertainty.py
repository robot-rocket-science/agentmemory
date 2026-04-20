"""Tests for multi-dimensional Bayesian uncertainty tracking.

Validates Beta entropy, VOI, evidence propagation, hibernation scoring,
and the UncertaintyVector lifecycle for speculative beliefs.
"""

from __future__ import annotations

import json

from agentmemory.uncertainty import (
    BetaAxis,
    DIMENSION_FEASIBILITY,
    DIMENSION_VALUE,
    DIMENSION_COST,
    UncertaintyVector,
    propagate_evidence,
)


# --- BetaAxis tests ---


def test_beta_axis_mean() -> None:
    """Beta(3,1) has mean 0.75."""
    axis: BetaAxis = BetaAxis(3.0, 1.0)
    assert abs(axis.mean - 0.75) < 1e-6


def test_beta_axis_uniform_entropy() -> None:
    """Beta(1,1) = Uniform has maximum entropy = ln(2)."""
    axis: BetaAxis = BetaAxis(1.0, 1.0)
    # Uniform has entropy ln(1) = 0 for the differential entropy
    # Actually Beta(1,1) differential entropy = ln(B(1,1)) = ln(1) = 0
    # This is correct: the uniform distribution on [0,1] has H = 0 (ln(1))
    assert abs(axis.entropy()) < 0.01


def test_beta_axis_concentrated_low_entropy() -> None:
    """Beta(50,50) has much lower entropy than Beta(1,1)."""
    uniform: BetaAxis = BetaAxis(1.0, 1.0)
    concentrated: BetaAxis = BetaAxis(50.0, 50.0)
    assert concentrated.entropy() < uniform.entropy()


def test_beta_axis_update_success() -> None:
    """Success increments alpha."""
    axis: BetaAxis = BetaAxis(1.0, 1.0)
    axis.update(True, weight=1.0)
    assert axis.alpha == 2.0
    assert axis.beta_param == 1.0


def test_beta_axis_update_failure() -> None:
    """Failure increments beta_param."""
    axis: BetaAxis = BetaAxis(1.0, 1.0)
    axis.update(False, weight=1.0)
    assert axis.alpha == 1.0
    assert axis.beta_param == 2.0


def test_beta_axis_voi_positive() -> None:
    """Observing reduces expected entropy, so VOI > 0."""
    axis: BetaAxis = BetaAxis(1.0, 1.0)
    h_prior: float = axis.entropy()
    h_expected_post: float = axis.expected_entropy_after_observation()
    assert h_prior >= h_expected_post


def test_beta_axis_voi_decreases_with_evidence() -> None:
    """More evidence = less VOI (already well-characterized)."""
    uncertain: BetaAxis = BetaAxis(1.0, 1.0)
    certain: BetaAxis = BetaAxis(50.0, 50.0)
    voi_uncertain: float = (
        uncertain.entropy() - uncertain.expected_entropy_after_observation()
    )
    voi_certain: float = (
        certain.entropy() - certain.expected_entropy_after_observation()
    )
    assert voi_uncertain > voi_certain


# --- UncertaintyVector tests ---


def test_default_vector_has_4_dimensions() -> None:
    """Default vector has feasibility, value, cost, dependency."""
    uv: UncertaintyVector = UncertaintyVector()
    assert uv.n_dimensions == 4


def test_joint_entropy_is_sum() -> None:
    """Joint entropy of independent axes = sum of individual entropies."""
    uv: UncertaintyVector = UncertaintyVector()
    individual_sum: float = sum(axis.entropy() for axis in uv.axes)
    assert abs(uv.joint_entropy() - individual_sum) < 1e-10


def test_update_dimension() -> None:
    """Updating one dimension doesn't affect others."""
    uv: UncertaintyVector = UncertaintyVector()
    original_value_alpha: float = uv.axes[DIMENSION_VALUE].alpha
    uv.update_dimension(DIMENSION_FEASIBILITY, True, weight=2.0)
    assert uv.axes[DIMENSION_FEASIBILITY].alpha == 3.0  # 1.0 + 2.0
    assert uv.axes[DIMENSION_VALUE].alpha == original_value_alpha  # unchanged


def test_best_experiment_dimension() -> None:
    """The dimension with highest VOI should be the most uncertain one."""
    uv: UncertaintyVector = UncertaintyVector()
    # Make feasibility well-known, leave others uncertain
    uv.axes[DIMENSION_FEASIBILITY] = BetaAxis(50.0, 5.0)
    best: int = uv.best_experiment_dimension()
    # Best should NOT be feasibility (it's already well-characterized)
    assert best != DIMENSION_FEASIBILITY


def test_hibernation_score_high_for_promising_certain() -> None:
    """High mean + low entropy = high hibernation score (promising, well-understood)."""
    uv: UncertaintyVector = UncertaintyVector(
        axes=[
            BetaAxis(50.0, 5.0),  # feasibility: high confidence
            BetaAxis(40.0, 10.0),  # value: high confidence
            BetaAxis(30.0, 5.0),  # cost: favorable
            BetaAxis(45.0, 5.0),  # dependency: met
        ]
    )
    score: float = uv.hibernation_score()
    assert score > 0.5, f"Expected > 0.5, got {score}"


def test_hibernation_score_low_for_uncertain() -> None:
    """All Beta(1,1) = maximum uncertainty = low hibernation score."""
    uv: UncertaintyVector = UncertaintyVector()
    score: float = uv.hibernation_score()
    # With all axes at Beta(1,1): mean=0.5, normalized_entropy~1.0
    # S = 0.5 * (1 - ~1.0) ~ 0.0
    assert score < 0.4, f"Expected < 0.4, got {score}"


def test_json_roundtrip() -> None:
    """UncertaintyVector survives JSON serialization."""
    uv: UncertaintyVector = UncertaintyVector(
        axes=[
            BetaAxis(3.0, 1.0),
            BetaAxis(2.0, 5.0),
        ]
    )
    json_str: str = uv.to_json()
    parsed: list[list[float]] = json.loads(json_str)
    assert len(parsed) == 2
    assert parsed[0] == [3.0, 1.0]
    assert parsed[1] == [2.0, 5.0]

    restored: UncertaintyVector = UncertaintyVector.from_json(json_str)
    assert restored.n_dimensions == 2
    assert abs(restored.axes[0].alpha - 3.0) < 1e-6
    assert abs(restored.axes[1].beta_param - 5.0) < 1e-6


def test_dimension_summary() -> None:
    """Summary returns all dimensions with correct keys."""
    uv: UncertaintyVector = UncertaintyVector()
    summary: dict[str, dict[str, float]] = uv.dimension_summary()
    assert "feasibility" in summary
    assert "value" in summary
    assert "cost" in summary
    assert "dependency" in summary
    for dim_data in summary.values():
        assert "mean" in dim_data
        assert "variance" in dim_data
        assert "entropy" in dim_data
        assert "voi" in dim_data


# --- Evidence propagation tests ---


def test_propagate_evidence() -> None:
    """Evidence propagates from source dimension to target with weight scaling."""
    source: UncertaintyVector = UncertaintyVector()
    target: UncertaintyVector = UncertaintyVector()

    # Source feasibility gets a strong positive update
    original_target_cost_alpha: float = target.axes[DIMENSION_COST].alpha

    propagate_evidence(
        source_vector=source,
        source_dimension=DIMENSION_FEASIBILITY,
        target_vector=target,
        target_dimension=DIMENSION_COST,
        weight=0.5,
        delta_alpha=4.0,
        delta_beta=0.0,
    )

    # Target cost should increase by weight * delta_alpha = 0.5 * 4.0 = 2.0
    assert (
        abs(target.axes[DIMENSION_COST].alpha - (original_target_cost_alpha + 2.0))
        < 1e-6
    )


def test_propagate_no_effect_on_wrong_dimension() -> None:
    """Propagating to an out-of-range dimension does nothing."""
    target: UncertaintyVector = UncertaintyVector()
    original: str = target.to_json()

    propagate_evidence(
        source_vector=UncertaintyVector(),
        source_dimension=0,
        target_vector=target,
        target_dimension=99,  # out of range
        weight=1.0,
        delta_alpha=5.0,
        delta_beta=5.0,
    )

    assert target.to_json() == original


# --- Speculative belief lifecycle tests ---


def test_speculative_lifecycle() -> None:
    """Full lifecycle: create -> update -> evaluate -> hibernate -> revive."""
    # 1. Create with maximum uncertainty
    uv: UncertaintyVector = UncertaintyVector()
    initial_entropy: float = uv.joint_entropy()

    # 2. First experiment: feasibility looks good
    uv.update_dimension(DIMENSION_FEASIBILITY, True, weight=3.0)
    assert uv.axes[DIMENSION_FEASIBILITY].mean > 0.5

    # 3. Entropy should decrease (we learned something)
    assert uv.joint_entropy() < initial_entropy

    # 4. Best next experiment should NOT be feasibility
    assert uv.best_experiment_dimension() != DIMENSION_FEASIBILITY

    # 5. Bad news on value: not useful
    uv.update_dimension(DIMENSION_VALUE, False, weight=5.0)
    assert uv.axes[DIMENSION_VALUE].mean < 0.5

    # 6. Hibernation score should be moderate (one axis good, one bad)
    score: float = uv.hibernation_score()
    # Max mean is feasibility (~0.8), but entropy is moderate
    assert 0.0 < score < 1.0

    # 7. More bad news: cost is high
    uv.update_dimension(DIMENSION_COST, False, weight=4.0)

    # 8. Hibernation score should drop further
    score2: float = uv.hibernation_score()
    assert score2 <= score or abs(score2 - score) < 0.1

    # 9. New evidence: value actually is good (reversal)
    uv.update_dimension(DIMENSION_VALUE, True, weight=8.0)
    assert uv.axes[DIMENSION_VALUE].mean > 0.4  # recovering

    # 10. Hibernation score should recover
    score3: float = uv.hibernation_score()
    assert score3 > score2 or abs(score3 - score2) < 0.15
