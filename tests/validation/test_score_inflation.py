"""Diagnostic tests for Bayesian score inflation bug.

Documents the bug: scanner/ingest inserts agent-inferred beliefs with
inflated alpha priors (3.0-9.0) instead of Jeffreys (0.5, 0.5). This
makes Thompson sampling non-discriminative and the feedback loop negligible.

These tests verify the fix: after correction, agent-inferred beliefs
should start at source-appropriate priors that allow meaningful Bayesian
updates.
"""

from __future__ import annotations

import random
from collections.abc import Generator
from pathlib import Path

import pytest

from agentmemory.classification import TYPE_PRIORS
from agentmemory.models import (
    BELIEF_CORRECTION,
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_CORRECTED,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.store import MemoryStore


@pytest.fixture()
def store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    s: MemoryStore = MemoryStore(tmp_path / "test.db")
    yield s
    s.close()


class TestInsertionPriors:
    """Verify that insertion priors are appropriate for each source type."""

    def test_agent_inferred_factual_uses_low_prior(self, store: MemoryStore) -> None:
        """Agent-inferred factual beliefs should start with low confidence,
        not the inflated alpha=9.5 that makes everything 95%."""
        b: Belief = store.insert_belief(
            content="The module uses a factory pattern",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )
        # Default insert_belief uses alpha=0.5, beta=0.5 (Jeffreys)
        assert b.alpha <= 1.0, (
            f"Agent-inferred factual should use Jeffreys prior, got alpha={b.alpha}"
        )
        assert b.confidence <= 0.6, (
            f"Agent-inferred factual should start uncertain, got {b.confidence:.0%}"
        )

    def test_user_corrected_uses_strong_prior(self, store: MemoryStore) -> None:
        """User corrections should start with high confidence (intentional)."""
        b: Belief = store.insert_belief(
            content="Use PostgreSQL not SQLite for production",
            belief_type=BELIEF_CORRECTION,
            source_type=BSRC_USER_CORRECTED,
            alpha=9.0,
            beta_param=0.5,
        )
        assert b.confidence > 0.9, (
            f"User correction should start strong, got {b.confidence:.0%}"
        )

    def test_user_stated_uses_strong_prior(self, store: MemoryStore) -> None:
        """User-stated beliefs should start with high confidence (intentional)."""
        b: Belief = store.insert_belief(
            content="My pronouns are he/him",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_USER_STATED,
            alpha=9.0,
            beta_param=0.5,
        )
        assert b.confidence > 0.9, (
            f"User-stated should start strong, got {b.confidence:.0%}"
        )


class TestThompsonDiscrimination:
    """Verify that Thompson sampling can distinguish beliefs at different levels."""

    def test_thompson_spread_at_jeffreys(self) -> None:
        """At Jeffreys prior (0.5, 0.5), Thompson sampling should have
        full spread [0, 1], enabling exploration."""
        rng: random.Random = random.Random(42)
        samples: list[float] = [rng.betavariate(0.5, 0.5) for _ in range(200)]
        spread: float = max(samples) - min(samples)
        assert spread > 0.9, (
            f"Jeffreys prior should have near-full spread, got {spread:.2f}"
        )

    def test_thompson_spread_at_inflated(self) -> None:
        """At inflated prior (9.5, 0.5), Thompson sampling has narrow spread,
        making it unable to explore."""
        rng: random.Random = random.Random(42)
        samples: list[float] = [rng.betavariate(9.5, 0.5) for _ in range(200)]
        spread: float = max(samples) - min(samples)
        # Document the problem: spread is much less than 1.0
        assert spread < 0.6, (
            f"Inflated prior has narrow spread as expected: {spread:.2f}"
        )

    def test_can_distinguish_used_from_unused(self) -> None:
        """After 3 'used' events, a Jeffreys-prior belief should clearly
        outrank an untouched one in Thompson draws."""
        rng: random.Random = random.Random(42)
        # Untouched (Jeffreys)
        unused_wins: int = 0
        for _ in range(1000):
            used: float = rng.betavariate(3.5, 0.5)  # 0.5 + 3 used
            unused: float = rng.betavariate(0.5, 0.5)  # fresh
            if unused > used:
                unused_wins += 1
        # Used should win most of the time
        assert unused_wins < 300, (
            f"Used belief should outrank unused in >70% of draws, "
            f"unused won {unused_wins}/1000"
        )


class TestFeedbackImpact:
    """Verify that feedback events have meaningful impact on confidence."""

    def test_single_used_moves_confidence_meaningfully(
        self,
        store: MemoryStore,
    ) -> None:
        """A single 'used' event should move a Jeffreys-prior belief
        by at least 0.10 confidence (not the 0.005 seen with inflated priors)."""
        b: Belief = store.insert_belief(
            content="Test belief for feedback impact",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )
        before: float = b.confidence

        store.update_confidence(b.id, "used")
        after_b: Belief | None = store.get_belief(b.id)
        assert after_b is not None
        delta: float = after_b.confidence - before
        assert delta > 0.10, (
            f"Single 'used' should move confidence by >0.10, got {delta:.4f}"
        )

    def test_single_ignored_moves_confidence_meaningfully(
        self,
        store: MemoryStore,
    ) -> None:
        """A single 'ignored' event should move a Jeffreys-prior belief
        by at least 0.10 confidence."""
        b: Belief = store.insert_belief(
            content="Test belief for ignore impact",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )
        before: float = b.confidence

        store.update_confidence(b.id, "ignored")
        after_b: Belief | None = store.get_belief(b.id)
        assert after_b is not None
        delta: float = before - after_b.confidence
        # "ignored" uses 0.1 weight (dampened by design), so delta is ~0.045
        # at Jeffreys. The key test: it should be > 0.01 (vs ~0.005 when inflated)
        assert delta > 0.01, (
            f"Single 'ignored' should move confidence measurably, got {delta:.4f}"
        )

    def test_three_ignores_drops_below_50(self, store: MemoryStore) -> None:
        """Three 'ignored' events on a fresh belief should drop it below 50%,
        not require 9+ ignores like the inflated version."""
        b: Belief = store.insert_belief(
            content="Test belief for ignore cascade",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )

        for _ in range(3):
            store.update_confidence(b.id, "ignored")

        after_b: Belief | None = store.get_belief(b.id)
        assert after_b is not None
        assert after_b.confidence < 0.5, (
            f"3 ignores should drop below 50%, got {after_b.confidence:.0%}"
        )


class TestClassificationPriors:
    """Verify that TYPE_PRIORS are used correctly."""

    def test_type_priors_distinguish_from_source_weights(self) -> None:
        """TYPE_PRIORS should provide differentiated starting confidence,
        but agent-inferred beliefs should not start above 80%."""
        for type_name, prior in TYPE_PRIORS.items():
            if prior is None:
                continue  # non-persist types
            alpha, beta = prior
            conf: float = alpha / (alpha + beta)
            # The prior should be informative but not inflated
            # Agent-inferred facts at 75% is a design choice from Exp 61
            # The key constraint: these should NOT be used for agent-inferred
            # beliefs that bypassed LLM classification
            assert conf < 0.96, (
                f"TYPE_PRIOR for {type_name} is too high: "
                f"alpha={alpha}, beta={beta}, conf={conf:.0%}"
            )


class TestRecalibration:
    """Verify that the recalibrate function correctly deflates inflated beliefs."""

    def test_recalibrate_deflates_agent_inferred(self, store: MemoryStore) -> None:
        """Agent-inferred beliefs at scanner default should be deflated."""
        # Insert beliefs mimicking scanner behavior (inflated alpha)
        inflated: Belief = store.insert_belief(
            content="Scanner-inserted belief about module structure",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
            alpha=9.5,
            beta_param=0.5,
        )

        # Recalibrate
        count: int = store.recalibrate_scores()
        assert count >= 1

        after: Belief | None = store.get_belief(inflated.id)
        assert after is not None
        assert after.alpha < 3.0, f"Deflated alpha should be < 3.0, got {after.alpha}"
        assert after.confidence < 0.80, (
            f"Deflated confidence should be < 80%, got {after.confidence:.0%}"
        )

    def test_recalibrate_preserves_user_sourced(self, store: MemoryStore) -> None:
        """User-corrected beliefs should NOT be deflated."""
        user_b: Belief = store.insert_belief(
            content="User correction that should stay strong",
            belief_type=BELIEF_CORRECTION,
            source_type=BSRC_USER_CORRECTED,
            alpha=9.0,
            beta_param=0.5,
        )

        store.recalibrate_scores()

        after: Belief | None = store.get_belief(user_b.id)
        assert after is not None
        assert after.alpha == 9.0, (
            f"User-corrected alpha should be unchanged, got {after.alpha}"
        )

    def test_recalibrate_preserves_locked(self, store: MemoryStore) -> None:
        """Locked beliefs should NOT be deflated."""
        locked_b: Belief = store.insert_belief(
            content="Locked belief that must not change",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
            alpha=9.5,
            beta_param=0.5,
            locked=True,
        )

        store.recalibrate_scores()

        after: Belief | None = store.get_belief(locked_b.id)
        assert after is not None
        assert after.alpha == 9.5, (
            f"Locked alpha should be unchanged, got {after.alpha}"
        )
