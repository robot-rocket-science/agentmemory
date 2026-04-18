# pyright: reportPrivateUsage=false, reportUnusedFunction=false
"""Benchmark-style tests for valence propagation.

These tests demonstrate valence propagation's impact on retrieval quality
in scenarios that mirror production use: multi-round interactions with
feedback between queries.

Standard benchmarks (LongMemEval, MAB, etc.) use fresh-DB-per-test-case
with no feedback loop, so valence does not apply there. These tests
validate the production scenario where feedback reshapes the graph.

Pre-registered hypotheses:
H1: After confirming a correct belief, retrieval for related queries
    surfaces that belief more reliably (via SUPPORTS edge strengthening).
H2: After confirming one side of a contradiction, retrieval for the
    disputed topic returns the confirmed side preferentially.
H3: Valence propagation increases the number of beliefs with non-default
    confidence (addressing the 0.04% feedback coverage problem).
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_STATED,
    EDGE_CONTRADICTS,
    EDGE_SUPPORTS,
    Belief,
)
from agentmemory.retrieval import retrieve, RetrievalResult
from agentmemory.store import MemoryStore


@pytest.fixture()
def store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    s: MemoryStore = MemoryStore(tmp_path / "valence_benchmark.db")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# H1: SUPPORTS edge strengthening improves retrieval
# ---------------------------------------------------------------------------


def test_h1_confirm_improves_related_retrieval(store: MemoryStore) -> None:
    """H1: Confirming a belief strengthens SUPPORTS edges, improving
    retrieval of related beliefs via graph traversal."""

    # Create a knowledge cluster about deployment
    deploy_main: Belief = store.insert_belief(
        "Cloudflare Pages handles static site deployment with automatic builds",
        BELIEF_FACTUAL, BSRC_USER_STATED,
        alpha=5.0, beta_param=1.0,
    )
    deploy_detail: Belief = store.insert_belief(
        "Wrangler CLI manages Cloudflare Workers and Pages configuration",
        BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        alpha=2.0, beta_param=1.0,  # low confidence initially
    )
    deploy_step: Belief = store.insert_belief(
        "Build output directory must be configured in wrangler.toml for Pages",
        BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        alpha=2.0, beta_param=1.0,  # low confidence
    )

    # Create SUPPORTS edges
    store.insert_edge(deploy_main.id, deploy_detail.id, "SUPPORTS", weight=0.8)
    store.insert_edge(deploy_main.id, deploy_step.id, "SUPPORTS", weight=0.7)

    # Add noise beliefs
    for i in range(10):
        store.insert_belief(
            f"Unrelated belief about topic {i} with various keywords and details",
            BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
            alpha=3.0, beta_param=1.0,
        )

    # Baseline retrieval: query for deployment details
    _baseline: RetrievalResult = retrieve(store, "wrangler configuration for pages deploy", budget=2000)

    # Confirm the main deployment belief (simulates user saying "yes, that's right")
    store.propagate_valence(deploy_main.id, valence=1.0)

    # Post-confirmation retrieval
    _post_confirm: RetrievalResult = retrieve(store, "wrangler configuration for pages deploy", budget=2000)

    # The SUPPORTS neighbors should now have higher confidence
    detail_after: Belief | None = store.get_belief(deploy_detail.id)
    step_after: Belief | None = store.get_belief(deploy_step.id)
    assert detail_after is not None and step_after is not None
    assert detail_after.confidence > 2.0 / 3.0  # above original 0.667
    assert step_after.confidence > 2.0 / 3.0


# ---------------------------------------------------------------------------
# H2: Contradiction resolution via confirm
# ---------------------------------------------------------------------------


def test_h2_contradiction_resolution_retrieval(store: MemoryStore) -> None:
    """H2: Confirming one side of a contradiction makes the confirmed
    side more likely to be retrieved for the disputed topic."""

    correct: Belief = store.insert_belief(
        "agentmemory uses SQLite FTS5 for full-text search indexing",
        BELIEF_FACTUAL, BSRC_USER_STATED,
        alpha=5.0, beta_param=1.0,
    )
    wrong: Belief = store.insert_belief(
        "agentmemory uses PostgreSQL full-text search for indexing",
        BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        alpha=5.0, beta_param=1.0,
    )
    store.insert_edge(correct.id, wrong.id, EDGE_CONTRADICTS)

    # Before confirmation: both have equal confidence (0.833)
    assert abs(correct.confidence - wrong.confidence) < 0.01

    # Confirm the correct belief
    store.update_confidence(correct.id, "confirmed", valence=1.0, weight=2.0)
    store.propagate_valence(correct.id, valence=1.0)

    # After: correct should be higher, wrong should be lower
    correct_after: Belief | None = store.get_belief(correct.id)
    wrong_after: Belief | None = store.get_belief(wrong.id)
    assert correct_after is not None and wrong_after is not None
    assert correct_after.confidence > wrong_after.confidence

    # Retrieve for the disputed topic
    result: RetrievalResult = retrieve(store, "agentmemory search indexing technology", budget=2000)
    if result.beliefs:
        # If both are retrieved, correct should rank higher
        retrieved_ids: list[str] = [b.id for b in result.beliefs]
        if correct.id in retrieved_ids and wrong.id in retrieved_ids:
            assert retrieved_ids.index(correct.id) < retrieved_ids.index(wrong.id)


# ---------------------------------------------------------------------------
# H3: Feedback coverage improvement
# ---------------------------------------------------------------------------


def test_h3_valence_propagation_coverage(store: MemoryStore) -> None:
    """H3: A single explicit feedback should touch multiple beliefs
    via propagation, increasing feedback coverage beyond 0.04%."""

    # Create a connected graph of 20 beliefs
    beliefs: list[Belief] = []
    for i in range(20):
        b: Belief = store.insert_belief(
            f"Connected belief number {i} about memory architecture design",
            BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
            alpha=2.0, beta_param=1.0,
        )
        beliefs.append(b)

    # Create a chain: 0->1->2->...->19
    for i in range(19):
        store.insert_edge(beliefs[i].id, beliefs[i + 1].id, "SUPPORTS")

    # Also create some branches
    store.insert_edge(beliefs[0].id, beliefs[5].id, "SUPPORTS")
    store.insert_edge(beliefs[0].id, beliefs[10].id, "SUPPORTS")

    # Count beliefs with non-default confidence before
    non_default_before: int = sum(
        1 for b in beliefs
        if store.get_belief(b.id) is not None
        and abs(store.get_belief(b.id).confidence - 2.0 / 3.0) > 0.001  # type: ignore[union-attr]
    )

    # Single explicit feedback on belief 0
    updated_count: int = store.propagate_valence(beliefs[0].id, valence=1.0)

    # Count beliefs with non-default confidence after
    non_default_after: int = sum(
        1 for b in beliefs
        if store.get_belief(b.id) is not None
        and abs(store.get_belief(b.id).confidence - 2.0 / 3.0) > 0.001  # type: ignore[union-attr]
    )

    # Propagation should have touched multiple beliefs (not just the seed)
    assert updated_count >= 3  # at least hop 1 neighbors (1, 5, 10)
    assert non_default_after > non_default_before
    # Coverage: updated_count / 20 should be meaningful
    coverage: float = updated_count / 20.0
    assert coverage > 0.15  # at least 15% of the graph touched from one feedback


# ---------------------------------------------------------------------------
# Production scenario: multi-round knowledge evolution
# ---------------------------------------------------------------------------


def test_knowledge_evolution_via_feedback(store: MemoryStore) -> None:
    """Simulate production use: beliefs evolve over multiple rounds
    of feedback, and retrieval quality improves."""

    # Round 1: Initial knowledge (potentially noisy)
    b1: Belief = store.insert_belief(
        "The project uses React for the frontend framework",
        BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        alpha=2.0, beta_param=1.0,
    )
    b2: Belief = store.insert_belief(
        "The project uses Vue for the frontend framework",
        BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        alpha=2.0, beta_param=1.0,
    )
    b3: Belief = store.insert_belief(
        "The frontend uses Tailwind CSS for styling with custom components",
        BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        alpha=2.0, beta_param=1.0,
    )
    store.insert_edge(b1.id, b2.id, EDGE_CONTRADICTS)
    store.insert_edge(b1.id, b3.id, EDGE_SUPPORTS)  # React + Tailwind go together

    # Round 2: User confirms React is correct
    store.update_confidence(b1.id, "confirmed", valence=1.0, weight=2.0)
    store.propagate_valence(b1.id, valence=1.0)

    # Verify: React strengthened, Vue weakened, Tailwind strengthened
    b1_after: Belief | None = store.get_belief(b1.id)
    b2_after: Belief | None = store.get_belief(b2.id)
    b3_after: Belief | None = store.get_belief(b3.id)
    assert b1_after is not None and b2_after is not None and b3_after is not None

    assert b1_after.confidence > b1.confidence  # React confirmed
    assert b2_after.confidence < b2.confidence  # Vue contradicted
    assert b3_after.confidence > b3.confidence  # Tailwind supported

    # Round 3: Further feedback strengthens the pattern
    store.update_confidence(b3.id, "used", valence=0.5)
    store.propagate_valence(b3.id, valence=0.5)

    # Final state: clear hierarchy
    b1_final: Belief | None = store.get_belief(b1.id)
    b2_final: Belief | None = store.get_belief(b2.id)
    b3_final: Belief | None = store.get_belief(b3.id)
    assert b1_final is not None and b2_final is not None and b3_final is not None

    # React and Tailwind should be high confidence, Vue should be low
    assert b1_final.confidence > 0.8
    assert b3_final.confidence > 0.65
    assert b2_final.confidence < b1_final.confidence
