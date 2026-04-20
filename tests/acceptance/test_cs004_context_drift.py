"""CS-004: Loss of Established Context Within Session.

Pass criterion: Locked beliefs survive and remain ranked highly even when
many unlocked beliefs are inserted, preventing context drift within a session.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore

_LOCKED_TEXT: str = "This is a planning project, not implementation."


def test_cs004_locked_survives_noise(store: MemoryStore) -> None:
    """Insert a locked belief, then 20 unlocked noise beliefs about implementation.

    Use retrieve() and verify the locked belief still appears in results,
    proving it is not drowned out by volume of unlocked beliefs.
    """
    locked: Belief = store.insert_belief(
        content=_LOCKED_TEXT,
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )

    # Insert 20 unlocked noise beliefs about various implementation topics.
    noise_topics: list[str] = [
        "Implement the database migration script",
        "Build the REST API endpoint for users",
        "Create the frontend dashboard component",
        "Set up CI/CD pipeline for deployment",
        "Write integration tests for the auth module",
        "Implement rate limiting middleware",
        "Build the notification service",
        "Create the data export feature",
        "Implement search indexing with Elasticsearch",
        "Build the admin panel for user management",
        "Set up monitoring and alerting with Grafana",
        "Implement caching layer with Redis",
        "Build the file upload service",
        "Create the reporting module",
        "Implement webhook handlers for third-party integrations",
        "Build the user onboarding flow",
        "Create the billing and subscription module",
        "Implement the audit logging system",
        "Build the API documentation generator",
        "Create the performance benchmarking suite",
    ]
    for topic in noise_topics:
        store.insert_belief(
            content=topic,
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
            alpha=0.5,
            beta_param=0.5,
            locked=False,
        )

    result: RetrievalResult = retrieve(store, "what phase are we in planning project")
    assert result.beliefs, "Expected results from retrieve()"

    locked_in_results: list[Belief] = [b for b in result.beliefs if b.id == locked.id]
    assert locked_in_results, (
        "Locked belief must survive noise and appear in retrieve() results. "
        f"Got {len(result.beliefs)} results, none matching locked belief ID {locked.id}."
    )


def test_cs004_correction_confidence_stable(store: MemoryStore) -> None:
    """Insert a locked correction belief, then run update_confidence with
    outcome='ignored' 10 times. Confidence must not decrease.

    Locked beliefs have a confidence floor that resists downgrade attempts.
    """
    locked: Belief = store.insert_belief(
        content="Do not refactor the scoring module mid-experiment.",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )
    original_confidence: float = locked.confidence
    original_beta: float = locked.beta_param

    # Attempt to erode confidence 10 times via 'ignored' outcomes.
    for _ in range(10):
        store.update_confidence(locked.id, outcome="ignored", weight=1.0)

    updated: Belief | None = store.get_belief(locked.id)
    assert updated is not None
    assert updated.beta_param == original_beta, (
        f"Locked belief beta_param must not increase on 'ignored' outcomes. "
        f"Before: {original_beta}, after: {updated.beta_param}"
    )
    assert updated.confidence >= original_confidence, (
        f"Locked belief confidence must not decrease after repeated 'ignored' outcomes. "
        f"Before: {original_confidence:.4f}, after: {updated.confidence:.4f}"
    )
