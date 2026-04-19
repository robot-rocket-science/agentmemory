"""Unit tests for agentmemory.scoring module."""
# pyright: reportUnknownMemberType=false

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agentmemory.models import Belief
from agentmemory.scoring import (
    core_score,
    decay_factor,
    get_exploration_stats,
    length_multiplier,
    lock_boost_typed,
    recency_boost,
    reset_exploration_stats,
    retrieval_frequency_boost,
    score_belief,
    thompson_sample,
    uncertainty_score,
    velocity_scale,
)


def _make_belief(
    *,
    belief_type: str = "factual",
    source_type: str = "user_stated",
    content: str = "test belief content for unit tests",
    locked: bool = False,
    alpha: float = 0.5,
    beta_param: float = 0.5,
    created_at: str | None = None,
    updated_at: str | None = None,
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
        confidence=alpha / (alpha + beta_param) if (alpha + beta_param) > 0 else 0.5,
        source_type=source_type,
        locked=locked,
        valid_from=None,
        valid_to=valid_to,
        superseded_by=superseded_by,
        created_at=created_at or now_iso,
        updated_at=updated_at or now_iso,
    )


# ---------------------------------------------------------------------------
# decay_factor tests
# ---------------------------------------------------------------------------


class TestDecayFactor:
    """Tests for decay_factor()."""

    def test_brand_new_belief_returns_one(self) -> None:
        """A belief created right now should have decay factor ~1.0."""
        now = datetime.now(timezone.utc)
        b = _make_belief(created_at=now.isoformat())
        assert decay_factor(b, now) == pytest.approx(1.0)

    def test_factual_half_life_14_days(self) -> None:
        """After 14 days (336 hours), a factual belief should decay to ~0.5."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=14)
        b = _make_belief(belief_type="factual", created_at=created.isoformat())
        result = decay_factor(b, now)
        assert result == pytest.approx(0.5, abs=0.01)

    def test_requirement_half_life_24_weeks(self) -> None:
        """After 24 weeks, a requirement belief should decay to ~0.5."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(weeks=24)
        b = _make_belief(belief_type="requirement", created_at=created.isoformat())
        result = decay_factor(b, now)
        assert result == pytest.approx(0.5, abs=0.01)

    def test_correction_half_life_8_weeks(self) -> None:
        """After 8 weeks, a correction belief should decay to ~0.5."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(weeks=8)
        b = _make_belief(belief_type="correction", created_at=created.isoformat())
        result = decay_factor(b, now)
        assert result == pytest.approx(0.5, abs=0.01)

    def test_preference_half_life_12_weeks(self) -> None:
        """After 12 weeks, a preference belief should decay to ~0.5."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(weeks=12)
        b = _make_belief(belief_type="preference", created_at=created.isoformat())
        result = decay_factor(b, now)
        assert result == pytest.approx(0.5, abs=0.01)

    def test_locked_belief_always_one(self) -> None:
        """Locked beliefs should return 1.0 regardless of age."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=365)
        b = _make_belief(locked=True, created_at=created.isoformat())
        assert decay_factor(b, now) == 1.0

    def test_superseded_belief_returns_001(self) -> None:
        """Superseded beliefs return 0.01."""
        now = datetime.now(timezone.utc)
        b = _make_belief(superseded_by="other_id_1234")
        assert decay_factor(b, now) == 0.01

    def test_valid_to_set_returns_001(self) -> None:
        """Beliefs with valid_to set return 0.01."""
        now = datetime.now(timezone.utc)
        b = _make_belief(valid_to=now.isoformat())
        assert decay_factor(b, now) == 0.01

    def test_unknown_type_returns_one(self) -> None:
        """A belief type not in DECAY_HALF_LIVES returns 1.0 (no decay)."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=100)
        b = _make_belief(belief_type="unknown_type", created_at=created.isoformat())
        assert decay_factor(b, now) == 1.0

    def test_accepts_iso_string(self) -> None:
        """current_time_iso can be a plain ISO string."""
        now = datetime.now(timezone.utc)
        b = _make_belief(created_at=now.isoformat())
        result = decay_factor(b, now.isoformat())
        assert result == pytest.approx(1.0)

    def test_future_created_at_returns_one(self) -> None:
        """If created_at is in the future (negative age), return 1.0."""
        now = datetime.now(timezone.utc)
        future = now + timedelta(hours=5)
        b = _make_belief(created_at=future.isoformat())
        assert decay_factor(b, now) == 1.0

    def test_two_half_lives_gives_quarter(self) -> None:
        """After 2 half-lives, decay should be ~0.25."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=28)  # 2x factual half-life (14d)
        b = _make_belief(belief_type="factual", created_at=created.isoformat())
        result = decay_factor(b, now)
        assert result == pytest.approx(0.25, abs=0.01)


# ---------------------------------------------------------------------------
# decay_factor with velocity scaling
# ---------------------------------------------------------------------------


class TestDecayFactorVelocity:
    """Tests for velocity-scaled decay."""

    def test_sprint_velocity_shortens_half_life(self) -> None:
        """Sprint velocity (>10) uses 0.1x half-life, so decay is much faster."""
        now = datetime.now(timezone.utc)
        # factual half-life = 336h. At velocity >10, effective = 336*0.1 = 33.6h
        created = now - timedelta(hours=33.6)
        b = _make_belief(belief_type="factual", created_at=created.isoformat())
        result = decay_factor(b, now, session_velocity=15.0)
        assert result == pytest.approx(0.5, abs=0.02)

    def test_deep_velocity_no_scaling(self) -> None:
        """Deep velocity (<2) gives 1.0x multiplier -- no scaling."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=14)
        b = _make_belief(belief_type="factual", created_at=created.isoformat())
        result_no_vel = decay_factor(b, now)
        result_deep = decay_factor(b, now, session_velocity=1.0)
        assert result_deep == pytest.approx(result_no_vel, abs=0.001)


# ---------------------------------------------------------------------------
# velocity_scale tests
# ---------------------------------------------------------------------------


class TestVelocityScale:
    def test_sprint(self) -> None:
        assert velocity_scale(15.0) == 0.1

    def test_fast(self) -> None:
        assert velocity_scale(7.0) == 0.5

    def test_moderate(self) -> None:
        assert velocity_scale(3.0) == 0.8

    def test_deep(self) -> None:
        assert velocity_scale(1.0) == 1.0

    def test_boundary_10(self) -> None:
        assert velocity_scale(10.0) == 0.5

    def test_boundary_5(self) -> None:
        assert velocity_scale(5.0) == 0.5

    def test_boundary_2(self) -> None:
        assert velocity_scale(2.0) == 0.8


# ---------------------------------------------------------------------------
# lock_boost_typed tests
# ---------------------------------------------------------------------------


class TestLockBoostTyped:
    def test_locked_relevant_gets_boost(self) -> None:
        b = _make_belief(locked=True, content="always use uv for Python")
        result = lock_boost_typed(b, ["uv", "Python"])
        assert result == 3.0  # default boost=2.0, so 2.0 + 1.0

    def test_locked_irrelevant_no_boost(self) -> None:
        b = _make_belief(locked=True, content="always use uv for Python")
        result = lock_boost_typed(b, ["docker", "kubernetes"])
        assert result == 1.0

    def test_unlocked_returns_one(self) -> None:
        b = _make_belief(locked=False, content="always use uv for Python")
        result = lock_boost_typed(b, ["uv", "Python"])
        assert result == 1.0

    def test_superseded_locked_returns_001(self) -> None:
        b = _make_belief(locked=True, superseded_by="other123")
        result = lock_boost_typed(b, ["anything"])
        assert result == 0.01

    def test_valid_to_returns_001(self) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        b = _make_belief(locked=True, valid_to=now_iso)
        result = lock_boost_typed(b, ["anything"])
        assert result == 0.01

    def test_custom_boost(self) -> None:
        b = _make_belief(locked=True, content="use pytest")
        result = lock_boost_typed(b, ["pytest"], boost=5.0)
        assert result == 6.0  # 5.0 + 1.0

    def test_empty_query_terms(self) -> None:
        b = _make_belief(locked=True, content="something")
        result = lock_boost_typed(b, [])
        assert result == 1.0

    def test_case_insensitive_match(self) -> None:
        b = _make_belief(locked=True, content="Always Use UV")
        result = lock_boost_typed(b, ["uv"])
        assert result == 3.0


# ---------------------------------------------------------------------------
# thompson_sample tests
# ---------------------------------------------------------------------------


class TestThompsonSample:
    def test_returns_between_zero_and_one(self) -> None:
        for _ in range(100):
            s = thompson_sample(1.0, 1.0)
            assert 0.0 <= s <= 1.0

    def test_zero_alpha_beta_does_not_crash(self) -> None:
        """Edge case: zero alpha/beta should not raise."""
        s = thompson_sample(0.0, 0.0)
        assert 0.0 <= s <= 1.0

    def test_negative_values_clamped(self) -> None:
        """Negative values get clamped to 1e-6."""
        s = thompson_sample(-1.0, -1.0)
        assert 0.0 <= s <= 1.0


# ---------------------------------------------------------------------------
# uncertainty_score tests
# ---------------------------------------------------------------------------


class TestUncertaintyScore:
    def test_jeffreys_prior_high_uncertainty(self) -> None:
        """Beta(0.5, 0.5) should give maximum uncertainty ~1.0."""
        result = uncertainty_score(0.5, 0.5)
        assert result == pytest.approx(1.0, abs=0.15)

    def test_confident_belief_low_uncertainty(self) -> None:
        """High alpha, low beta means confidence, low uncertainty."""
        result = uncertainty_score(100.0, 1.0)
        assert result < 0.05

    def test_zero_total_returns_one(self) -> None:
        assert uncertainty_score(0.0, 0.0) == 1.0

    def test_symmetric_moderate(self) -> None:
        """Beta(5, 5) should have moderate uncertainty."""
        result = uncertainty_score(5.0, 5.0)
        assert 0.0 < result < 1.0


# ---------------------------------------------------------------------------
# recency_boost tests
# ---------------------------------------------------------------------------


class TestRecencyBoost:
    def test_brand_new_belief_gets_two(self) -> None:
        """A belief created now should get recency_boost ~2.0."""
        now = datetime.now(timezone.utc)
        b = _make_belief(created_at=now.isoformat())
        result = recency_boost(b, now)
        assert result == pytest.approx(2.0, abs=0.01)

    def test_old_belief_approaches_one(self) -> None:
        """A very old belief should get recency_boost ~1.0."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=30)
        b = _make_belief(created_at=created.isoformat())
        result = recency_boost(b, now)
        assert result == pytest.approx(1.0, abs=0.01)

    def test_at_half_life_gives_1_5(self) -> None:
        """At exactly one half-life (default 24h), boost should be ~1.5."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(hours=24)
        b = _make_belief(created_at=created.isoformat())
        result = recency_boost(b, now, half_life_hours=24.0)
        assert result == pytest.approx(1.5, abs=0.01)

    def test_custom_half_life(self) -> None:
        """Custom half_life_hours should be respected."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(hours=48)
        b = _make_belief(created_at=created.isoformat())
        result = recency_boost(b, now, half_life_hours=48.0)
        assert result == pytest.approx(1.5, abs=0.01)

    def test_accepts_iso_string(self) -> None:
        now = datetime.now(timezone.utc)
        b = _make_belief(created_at=now.isoformat())
        result = recency_boost(b, now.isoformat())
        assert result == pytest.approx(2.0, abs=0.01)


# ---------------------------------------------------------------------------
# retrieval_frequency_boost tests
# ---------------------------------------------------------------------------


class TestRetrievalFrequencyBoost:
    def test_no_retrievals_returns_one(self) -> None:
        assert retrieval_frequency_boost(0, 0) == 1.0

    def test_high_retrieval_low_use_penalized(self) -> None:
        """>20 retrievals with <30% use rate should penalize."""
        result = retrieval_frequency_boost(30, 5)
        assert result == 0.5

    def test_high_retrieval_high_use_boosted(self) -> None:
        """>10 retrievals with >70% use rate should boost."""
        result = retrieval_frequency_boost(15, 12)
        assert result == 1.5

    def test_some_usage_mild_boost(self) -> None:
        """Some usage but not enough for strong boost."""
        result = retrieval_frequency_boost(5, 2)
        use_rate = 2 / 5
        expected = 1.0 + (use_rate * 0.3)
        assert result == pytest.approx(expected)

    def test_retrievals_no_usage_returns_one(self) -> None:
        """Retrieved but never used, not enough to penalize."""
        result = retrieval_frequency_boost(5, 0)
        assert result == 1.0


# ---------------------------------------------------------------------------
# core_score tests
# ---------------------------------------------------------------------------


class TestCoreScore:
    def test_superseded_returns_zero(self) -> None:
        b = _make_belief(superseded_by="other123")
        assert core_score(b) == 0.0

    def test_locked_doubles_score(self) -> None:
        b_locked = _make_belief(locked=True)
        b_unlocked = _make_belief(locked=False)
        # Without time-based decay, locked should be 2x unlocked
        assert core_score(b_locked) == pytest.approx(2.0 * core_score(b_unlocked))

    def test_type_weight_applied(self) -> None:
        b_req = _make_belief(belief_type="requirement")
        b_fact = _make_belief(belief_type="factual")
        # requirement weight = 2.5, factual = 1.0
        ratio = core_score(b_req) / core_score(b_fact)
        assert ratio == pytest.approx(2.5)

    def test_source_weight_applied(self) -> None:
        b_corrected = _make_belief(source_type="user_corrected")
        b_inferred = _make_belief(source_type="agent_inferred")
        ratio = core_score(b_corrected) / core_score(b_inferred)
        assert ratio == pytest.approx(1.5 / 1.0)

    def test_with_decay(self) -> None:
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=14)
        b = _make_belief(belief_type="factual", created_at=created.isoformat())
        score_no_time = core_score(b)
        score_with_time = core_score(b, current_time_iso=now.isoformat())
        # With 14-day-old factual, decay ~0.5, so score_with_time < score_no_time
        assert score_with_time < score_no_time


# ---------------------------------------------------------------------------
# length_multiplier tests
# ---------------------------------------------------------------------------


class TestLengthMultiplier:
    def test_short_fragment(self) -> None:
        assert length_multiplier("hi") == 0.5

    def test_normal(self) -> None:
        assert length_multiplier("a" * 50) == 1.0

    def test_medium(self) -> None:
        assert length_multiplier("a" * 150) == 1.3

    def test_long(self) -> None:
        assert length_multiplier("a" * 250) == 1.6


# ---------------------------------------------------------------------------
# score_belief tests
# ---------------------------------------------------------------------------


class TestScoreBelief:
    def test_superseded_returns_001(self) -> None:
        now = datetime.now(timezone.utc)
        b = _make_belief(superseded_by="other123")
        assert score_belief(b, "test query", now) == 0.01

    def test_locked_relevant_scores_higher(self) -> None:
        """Locked relevant belief should consistently score higher than unlocked."""
        now = datetime.now(timezone.utc)
        b_locked = _make_belief(
            locked=True,
            content="always use pytest for testing",
            alpha=10.0,
            beta_param=1.0,
        )
        b_unlocked = _make_belief(
            locked=False,
            content="always use pytest for testing",
            alpha=10.0,
            beta_param=1.0,
        )
        # Run multiple times to account for Thompson sampling variance
        locked_scores: list[float] = []
        unlocked_scores: list[float] = []
        for _ in range(200):
            locked_scores.append(score_belief(b_locked, "pytest testing", now))
            unlocked_scores.append(score_belief(b_unlocked, "pytest testing", now))
        # Locked mean should be higher due to lock_boost_typed
        avg_locked = sum(locked_scores) / len(locked_scores)
        avg_unlocked = sum(unlocked_scores) / len(unlocked_scores)
        assert avg_locked > avg_unlocked

    def test_type_weight_influences_score(self) -> None:
        """Requirements should score higher than factual on average."""
        now = datetime.now(timezone.utc)
        b_req = _make_belief(belief_type="requirement", alpha=5.0, beta_param=1.0)
        b_fact = _make_belief(belief_type="factual", alpha=5.0, beta_param=1.0)
        req_scores = [score_belief(b_req, "test", now) for _ in range(200)]
        fact_scores = [score_belief(b_fact, "test", now) for _ in range(200)]
        assert sum(req_scores) / len(req_scores) > sum(fact_scores) / len(fact_scores)

    def test_source_weight_influences_score(self) -> None:
        """user_corrected should score higher than agent_inferred on average."""
        now = datetime.now(timezone.utc)
        b_corrected = _make_belief(
            source_type="user_corrected", alpha=5.0, beta_param=1.0
        )
        b_inferred = _make_belief(
            source_type="agent_inferred", alpha=5.0, beta_param=1.0
        )
        corr_scores = [score_belief(b_corrected, "test", now) for _ in range(200)]
        inf_scores = [score_belief(b_inferred, "test", now) for _ in range(200)]
        assert sum(corr_scores) / len(corr_scores) > sum(inf_scores) / len(inf_scores)

    def test_old_belief_scores_lower(self) -> None:
        """Old beliefs should score lower due to decay and recency."""
        now = datetime.now(timezone.utc)
        b_new = _make_belief(created_at=now.isoformat(), alpha=5.0, beta_param=1.0)
        old_created = (now - timedelta(days=60)).isoformat()
        b_old = _make_belief(created_at=old_created, alpha=5.0, beta_param=1.0)
        new_scores = [score_belief(b_new, "test", now) for _ in range(200)]
        old_scores = [score_belief(b_old, "test", now) for _ in range(200)]
        assert sum(new_scores) / len(new_scores) > sum(old_scores) / len(old_scores)

    def test_accepts_iso_string_time(self) -> None:
        now = datetime.now(timezone.utc)
        b = _make_belief(alpha=5.0, beta_param=1.0)
        # Should not raise
        result = score_belief(b, "test", now.isoformat())
        assert result > 0


# ---------------------------------------------------------------------------
# Exploration stats tests
# ---------------------------------------------------------------------------


class TestExplorationStats:
    def test_reset_clears_counts(self) -> None:
        reset_exploration_stats()
        stats = get_exploration_stats()
        assert stats["exploration"] == 0
        assert stats["exploitation"] == 0
        assert stats["total"] == 0

    def test_score_belief_increments_counters(self) -> None:
        reset_exploration_stats()
        now = datetime.now(timezone.utc)
        b = _make_belief(alpha=5.0, beta_param=1.0)
        for _ in range(10):
            score_belief(b, "test", now)
        stats = get_exploration_stats()
        assert stats["total"] == 10
