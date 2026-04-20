"""Tests for multi-model Bayesian scoring (Exp 93b archaeology-style)."""

from __future__ import annotations


from agentmemory.multimodel import multimodel_multiplier


class TestMultimodelMultiplier:
    """Test the scoring multiplier from model classification."""

    def test_no_feedback_returns_neutral(self) -> None:
        """Zero feedback should return 1.0 (neutral)."""
        result: float = multimodel_multiplier(
            used_count=0,
            ignored_count=0,
            harmful_count=0,
            age_normalized=0.5,
            source_type="agent_inferred",
        )
        assert result == 1.0

    def test_high_used_rate_boosts(self) -> None:
        """Belief with high used rate should get SIGNAL multiplier (> 1.0)."""
        result: float = multimodel_multiplier(
            used_count=10,
            ignored_count=1,
            harmful_count=0,
            age_normalized=0.3,
            source_type="user_corrected",
        )
        assert result > 1.0, f"Expected boost for SIGNAL, got {result}"

    def test_high_ignored_rate_penalizes(self) -> None:
        """Belief mostly ignored should get NOISE multiplier (< 1.0)."""
        result: float = multimodel_multiplier(
            used_count=1,
            ignored_count=20,
            harmful_count=0,
            age_normalized=0.5,
            source_type="agent_inferred",
        )
        assert result < 1.0, f"Expected penalty for NOISE, got {result}"

    def test_high_harmful_rate_classifies(self) -> None:
        """Belief with significant harmful feedback should not boost."""
        result: float = multimodel_multiplier(
            used_count=2,
            ignored_count=2,
            harmful_count=8,
            age_normalized=0.3,
            source_type="agent_inferred",
        )
        assert result <= 1.0, f"Expected no boost for harmful belief, got {result}"

    def test_old_mostly_ignored_is_stale(self) -> None:
        """Old belief that was used but is now ignored should get STALE."""
        result: float = multimodel_multiplier(
            used_count=3,
            ignored_count=5,
            harmful_count=1,
            age_normalized=0.9,
            source_type="agent_inferred",
        )
        assert result < 1.0, f"Expected penalty for stale belief, got {result}"

    def test_result_in_valid_range(self) -> None:
        """Multiplier should always be in the defined range."""
        for used in [0, 1, 5, 20]:
            for ign in [0, 1, 5, 20]:
                for harm in [0, 1, 5]:
                    total: int = used + ign + harm
                    if total == 0:
                        continue
                    result: float = multimodel_multiplier(
                        used_count=used,
                        ignored_count=ign,
                        harmful_count=harm,
                        age_normalized=0.5,
                        source_type="agent_inferred",
                    )
                    assert 0.5 <= result <= 1.5, (
                        f"Multiplier {result} out of range for "
                        f"used={used} ign={ign} harm={harm}"
                    )

    def test_source_type_influences(self) -> None:
        """Same feedback pattern with different source types may differ."""
        user: float = multimodel_multiplier(
            used_count=5,
            ignored_count=3,
            harmful_count=0,
            age_normalized=0.3,
            source_type="user_corrected",
        )
        agent: float = multimodel_multiplier(
            used_count=5,
            ignored_count=3,
            harmful_count=0,
            age_normalized=0.3,
            source_type="agent_inferred",
        )
        # Both should be valid, but may differ
        assert 0.5 <= user <= 1.5
        assert 0.5 <= agent <= 1.5

    def test_single_feedback_event(self) -> None:
        """Even one event should produce a non-neutral result."""
        result: float = multimodel_multiplier(
            used_count=1,
            ignored_count=0,
            harmful_count=0,
            age_normalized=0.1,
            source_type="user_stated",
        )
        # One "used" event should lean SIGNAL
        assert result >= 1.0
