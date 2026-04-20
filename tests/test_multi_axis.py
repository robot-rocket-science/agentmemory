"""Unit tests for multi-axis confidence scoring (Exp 91)."""
# pyright: reportUnknownMemberType=false

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agentmemory.models import Belief
from agentmemory.multi_axis import (
    AXIS_ACCURACY,
    AXIS_FRESHNESS,
    AXIS_RELEVANCE,
    ConfidenceAxes,
)
from agentmemory.scoring import score_belief_multi_axis
from agentmemory.uncertainty import BetaAxis


# ---------------------------------------------------------------------------
# ConfidenceAxes unit tests
# ---------------------------------------------------------------------------


class TestConfidenceAxes:
    """Tests for the ConfidenceAxes dataclass."""

    def test_default_uninformative(self) -> None:
        axes = ConfidenceAxes()
        assert axes.accuracy.mean == pytest.approx(0.5)
        assert axes.relevance.mean == pytest.approx(0.5)
        assert axes.freshness.mean == pytest.approx(0.5)

    def test_from_single_prior_maps_to_relevance(self) -> None:
        axes = ConfidenceAxes.from_single_prior(9.0, 0.5)
        # Relevance should carry the original prior
        assert axes.relevance.alpha == pytest.approx(9.0)
        assert axes.relevance.beta_param == pytest.approx(0.5)
        # Accuracy and freshness should be uninformative
        assert axes.accuracy.alpha == pytest.approx(1.0)
        assert axes.freshness.alpha == pytest.approx(1.0)

    def test_json_roundtrip(self) -> None:
        axes = ConfidenceAxes(
            accuracy=BetaAxis(3.0, 1.0),
            relevance=BetaAxis(5.0, 2.0),
            freshness=BetaAxis(1.0, 4.0),
        )
        restored = ConfidenceAxes.from_json(axes.to_json())
        assert restored.accuracy.alpha == pytest.approx(3.0)
        assert restored.relevance.alpha == pytest.approx(5.0)
        assert restored.freshness.beta_param == pytest.approx(4.0)

    def test_json_pads_short_vectors(self) -> None:
        # Only 2 axes in JSON -- should pad to 3
        axes = ConfidenceAxes.from_json("[[2.0, 1.0], [3.0, 1.0]]")
        assert axes.freshness.alpha == pytest.approx(1.0)

    def test_axis_index_access(self) -> None:
        axes = ConfidenceAxes(
            accuracy=BetaAxis(2.0, 1.0),
            relevance=BetaAxis(3.0, 1.0),
            freshness=BetaAxis(4.0, 1.0),
        )
        assert axes.axis(AXIS_ACCURACY).alpha == pytest.approx(2.0)
        assert axes.axis(AXIS_RELEVANCE).alpha == pytest.approx(3.0)
        assert axes.axis(AXIS_FRESHNESS).alpha == pytest.approx(4.0)

    def test_axis_invalid_index_raises(self) -> None:
        axes = ConfidenceAxes()
        with pytest.raises(ValueError, match="Invalid axis index"):
            axes.axis(99)


# ---------------------------------------------------------------------------
# Outcome routing tests
# ---------------------------------------------------------------------------


class TestOutcomeRouting:
    """Tests for feedback signal routing to axes."""

    def test_used_routes_to_relevance(self) -> None:
        axes = ConfidenceAxes()
        old_rel_alpha = axes.relevance.alpha
        old_acc_alpha = axes.accuracy.alpha
        axes.update("used", weight=1.0)
        assert axes.relevance.alpha > old_rel_alpha
        assert axes.accuracy.alpha == pytest.approx(old_acc_alpha)

    def test_harmful_routes_to_accuracy(self) -> None:
        axes = ConfidenceAxes()
        old_acc_beta = axes.accuracy.beta_param
        old_rel_beta = axes.relevance.beta_param
        axes.update("harmful", weight=1.0)
        assert axes.accuracy.beta_param > old_acc_beta
        assert axes.relevance.beta_param == pytest.approx(old_rel_beta)

    def test_confirmed_routes_to_both(self) -> None:
        axes = ConfidenceAxes()
        old_acc_alpha = axes.accuracy.alpha
        old_rel_alpha = axes.relevance.alpha
        axes.update("confirmed", weight=1.0)
        assert axes.accuracy.alpha > old_acc_alpha
        assert axes.relevance.alpha > old_rel_alpha

    def test_ignored_routes_weak_relevance_negative(self) -> None:
        axes = ConfidenceAxes()
        old_rel_beta = axes.relevance.beta_param
        axes.update("ignored", weight=1.0)
        assert axes.relevance.beta_param > old_rel_beta
        # Should be a weak signal (0.1 multiplier)
        assert axes.relevance.beta_param == pytest.approx(old_rel_beta + 0.1)

    def test_contradicted_routes_to_accuracy_negative(self) -> None:
        axes = ConfidenceAxes()
        old_acc_beta = axes.accuracy.beta_param
        axes.update("contradicted", weight=1.0)
        assert axes.accuracy.beta_param > old_acc_beta

    def test_unknown_outcome_no_change(self) -> None:
        axes = ConfidenceAxes()
        before = axes.to_json()
        axes.update("nonexistent_outcome", weight=1.0)
        assert axes.to_json() == before


# ---------------------------------------------------------------------------
# Composite scoring tests
# ---------------------------------------------------------------------------


class TestCompositeScoring:
    """Tests for composite_mean and composite_sample."""

    def test_composite_mean_all_uninformative(self) -> None:
        axes = ConfidenceAxes()
        # All axes at Beta(1,1) -> mean 0.5 each -> product 0.125
        assert axes.composite_mean() == pytest.approx(0.125)

    def test_composite_mean_strong_accuracy_weak_relevance(self) -> None:
        axes = ConfidenceAxes(
            accuracy=BetaAxis(9.0, 1.0),  # mean ~0.9
            relevance=BetaAxis(1.0, 9.0),  # mean ~0.1
            freshness=BetaAxis(1.0, 1.0),  # mean 0.5
        )
        # 0.9 * 0.1 * 0.5 = 0.045
        assert axes.composite_mean() == pytest.approx(0.045, rel=0.01)

    def test_accurate_and_relevant_beats_accurate_only(self) -> None:
        # This is the core experiment hypothesis
        both = ConfidenceAxes(
            accuracy=BetaAxis(9.0, 1.0),
            relevance=BetaAxis(9.0, 1.0),
            freshness=BetaAxis(1.0, 1.0),
        )
        acc_only = ConfidenceAxes(
            accuracy=BetaAxis(9.0, 1.0),
            relevance=BetaAxis(1.0, 1.0),
            freshness=BetaAxis(1.0, 1.0),
        )
        assert both.composite_mean() > acc_only.composite_mean()

    def test_legacy_confidence_in_unit_range(self) -> None:
        axes = ConfidenceAxes(
            accuracy=BetaAxis(9.0, 1.0),
            relevance=BetaAxis(5.0, 2.0),
            freshness=BetaAxis(3.0, 1.0),
        )
        lc = axes.legacy_confidence
        assert 0.0 <= lc <= 1.0

    def test_composite_sample_returns_positive(self) -> None:
        axes = ConfidenceAxes(
            accuracy=BetaAxis(5.0, 1.0),
            relevance=BetaAxis(5.0, 1.0),
            freshness=BetaAxis(5.0, 1.0),
        )
        for _ in range(50):
            assert axes.composite_sample() > 0.0


# ---------------------------------------------------------------------------
# score_belief_multi_axis integration tests
# ---------------------------------------------------------------------------


def _make_belief(
    *,
    belief_type: str = "factual",
    source_type: str = "user_stated",
    content: str = "test belief content for unit tests",
    locked: bool = False,
    alpha: float = 3.0,
    beta_param: float = 1.0,
    uncertainty_vector: str | None = None,
    superseded_by: str | None = None,
    valid_to: str | None = None,
) -> Belief:
    """Build a minimal Belief for testing."""
    now_iso: str = datetime.now(timezone.utc).isoformat()
    return Belief(
        id="aabbccddee01",
        content_hash="hash12345678",
        content=content,
        belief_type=belief_type,
        alpha=alpha,
        beta_param=beta_param,
        confidence=alpha / (alpha + beta_param),
        source_type=source_type,
        locked=locked,
        valid_from=None,
        valid_to=valid_to,
        superseded_by=superseded_by,
        created_at=now_iso,
        updated_at=now_iso,
        uncertainty_vector=uncertainty_vector,
    )


class TestScoreBeliefMultiAxis:
    """Tests for score_belief_multi_axis."""

    def test_falls_back_without_vector(self) -> None:
        """Without uncertainty_vector, should produce a valid score."""
        b = _make_belief(uncertainty_vector=None)
        now = datetime.now(timezone.utc)
        score = score_belief_multi_axis(b, "test query", now)
        assert score > 0.0

    def test_superseded_scores_low(self) -> None:
        b = _make_belief(superseded_by="other_id")
        now = datetime.now(timezone.utc)
        assert score_belief_multi_axis(b, "test", now) == pytest.approx(0.01)

    def test_high_accuracy_high_relevance_scores_higher(self) -> None:
        """Beliefs strong on both axes should consistently outscore
        beliefs strong on only one axis."""
        both_strong = ConfidenceAxes(
            accuracy=BetaAxis(9.0, 1.0),
            relevance=BetaAxis(9.0, 1.0),
            freshness=BetaAxis(1.0, 1.0),
        )
        acc_only = ConfidenceAxes(
            accuracy=BetaAxis(9.0, 1.0),
            relevance=BetaAxis(1.0, 9.0),
            freshness=BetaAxis(1.0, 1.0),
        )
        b_both = _make_belief(uncertainty_vector=both_strong.to_json())
        b_acc = _make_belief(uncertainty_vector=acc_only.to_json())
        now = datetime.now(timezone.utc)

        # Run multiple samples to check statistical dominance
        both_wins = 0
        trials = 200
        for _ in range(trials):
            s_both = score_belief_multi_axis(b_both, "test query", now)
            s_acc = score_belief_multi_axis(b_acc, "test query", now)
            if s_both > s_acc:
                both_wins += 1

        # Both-strong should win at least 80% of the time
        assert both_wins / trials > 0.80

    def test_locked_belief_uses_composite(self) -> None:
        axes = ConfidenceAxes(
            accuracy=BetaAxis(9.0, 1.0),
            relevance=BetaAxis(9.0, 1.0),
            freshness=BetaAxis(1.0, 1.0),
        )
        b = _make_belief(
            locked=True,
            content="test query related content",
            uncertainty_vector=axes.to_json(),
        )
        now = datetime.now(timezone.utc)
        score = score_belief_multi_axis(b, "test query", now)
        assert score > 0.0


# ---------------------------------------------------------------------------
# Summary output test
# ---------------------------------------------------------------------------


class TestSummary:
    """Tests for human-readable summary output."""

    def test_summary_has_all_axes(self) -> None:
        axes = ConfidenceAxes()
        s = axes.summary()
        assert "accuracy" in s
        assert "relevance" in s
        assert "freshness" in s
        for name in s:
            assert "mean" in s[name]
            assert "alpha" in s[name]
            assert "beta" in s[name]
            assert "variance" in s[name]
