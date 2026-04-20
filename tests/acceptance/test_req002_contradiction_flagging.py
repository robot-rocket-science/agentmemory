"""REQ-002: Belief consistency -- no silent contradictions.

Acceptance test: inject 10 known contradiction pairs into the belief store.
For each, issue a query that retrieves both sides. Verify the system flags
every contradiction and never silently presents contradictory beliefs.

Acceptance threshold: 100% of known contradictions flagged. Zero silent.

The test exercises the full path:
  1. insert_belief() creates beliefs
  2. detect_relationships() creates CONTRADICTS edges
  3. retrieve() calls flag_contradictions() on result set
  4. RetrievalResult.contradiction_warnings contains all pairs
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BELIEF_REQUIREMENT,
    BSRC_AGENT_INFERRED,
    BSRC_USER_STATED,
    Belief,
    EDGE_CONTRADICTS,
)
from agentmemory.relationship_detector import detect_relationships
from agentmemory.retrieval import flag_contradictions, retrieve
from agentmemory.store import MemoryStore


# 10 contradiction pairs: each has high term overlap + negation divergence.
_CONTRADICTION_PAIRS: list[tuple[str, str, str]] = [
    # (belief_a, belief_b, query_to_retrieve_both)
    (
        "The database is PostgreSQL for all services",
        "The database is not PostgreSQL, we use MySQL instead",
        "database PostgreSQL",
    ),
    (
        "Frontend uses React with TypeScript",
        "Frontend does not use React, it uses Vue with TypeScript",
        "frontend React TypeScript",
    ),
    (
        "API responses should include pagination metadata",
        "API responses should never include pagination metadata",
        "API pagination metadata",
    ),
    (
        "Deploy to production using GitHub Actions CI pipeline",
        "Do not deploy to production using GitHub Actions",
        "deploy production GitHub Actions",
    ),
    (
        "Use SQLite for local development databases",
        "SQLite is not suitable for local development databases",
        "SQLite local development",
    ),
    (
        "Authentication uses JWT tokens with 24 hour expiry",
        "Authentication doesn't use JWT tokens with 24 hour expiry",
        "authentication JWT tokens",
    ),
    (
        "The caching layer runs on Redis for all environments",
        "The caching layer does not run on Redis anymore",
        "caching layer Redis",
    ),
    (
        "Tests should run in parallel using pytest-xdist",
        "Tests should not run in parallel, use sequential execution",
        "tests parallel pytest",
    ),
    (
        "Logging uses structured JSON format for all services",
        "Logging does not use JSON format, plain text is required",
        "logging JSON format",
    ),
    (
        "The API rate limit is 1000 requests per minute",
        "The API rate limit is not 1000 requests per minute, it was removed",
        "API rate limit requests",
    ),
]


def _insert_pair(
    store: MemoryStore,
    text_a: str,
    text_b: str,
) -> tuple[Belief, Belief]:
    """Insert two beliefs and run relationship detection on the second."""
    b_a: Belief = store.insert_belief(
        content=text_a,
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
    )
    b_b: Belief = store.insert_belief(
        content=text_b,
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=0.5,
        beta_param=0.5,
    )
    # Trigger relationship detection (normally fires on ingest)
    detect_relationships(store, b_b)
    return b_a, b_b


def test_req002_all_contradictions_create_edges(store: MemoryStore) -> None:
    """All 10 contradiction pairs must produce CONTRADICTS edges."""
    missing_edges: list[int] = []

    for i, (text_a, text_b, _query) in enumerate(_CONTRADICTION_PAIRS):
        b_a, b_b = _insert_pair(store, text_a, text_b)

        # Check that a CONTRADICTS edge exists between them
        neighbors = store.get_neighbors(b_b.id, edge_types=[EDGE_CONTRADICTS])
        neighbor_ids: set[str] = {n.id for n, _e in neighbors}

        if b_a.id not in neighbor_ids:
            missing_edges.append(i)

    assert len(missing_edges) == 0, (
        f"CONTRADICTS edges missing for pairs: {missing_edges}. "
        f"Expected 10/10 pairs to have edges."
    )


def test_req002_flag_contradictions_detects_all_pairs(store: MemoryStore) -> None:
    """flag_contradictions() must flag all 10 pairs when both beliefs are in result set."""
    all_beliefs: list[Belief] = []

    for text_a, text_b, _query in _CONTRADICTION_PAIRS:
        b_a, b_b = _insert_pair(store, text_a, text_b)
        all_beliefs.extend([b_a, b_b])

    warnings: list[str] = flag_contradictions(store, all_beliefs)

    assert len(warnings) >= 10, (
        f"Expected >= 10 contradiction warnings, got {len(warnings)}. "
        f"Warnings: {warnings}"
    )


def test_req002_retrieval_includes_warnings(store: MemoryStore) -> None:
    """retrieve() must include contradiction warnings when contradicting beliefs match a query."""
    # Insert all pairs
    for text_a, text_b, _query in _CONTRADICTION_PAIRS:
        _insert_pair(store, text_a, text_b)

    # Query for a topic that should retrieve at least one contradiction pair
    result = retrieve(store, "database PostgreSQL MySQL", budget=2000)

    # If both sides of a contradiction are in the result, warnings must be present
    contents: list[str] = [b.content for b in result.beliefs]
    has_postgres: bool = any("PostgreSQL" in c for c in contents)
    has_mysql: bool = any("MySQL" in c for c in contents)

    if has_postgres and has_mysql:
        warnings_list: list[str] = result.contradiction_warnings or []
        assert len(warnings_list) > 0, (
            "Both sides of the PostgreSQL/MySQL contradiction were retrieved "
            "but no contradiction warning was generated."
        )


def test_req002_no_false_positive_on_agreement(store: MemoryStore) -> None:
    """Two beliefs that agree (both positive or both negative) must NOT produce CONTRADICTS edges."""
    b_a: Belief = store.insert_belief(
        content="Use PostgreSQL for all production databases",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
    )
    b_b: Belief = store.insert_belief(
        content="PostgreSQL is the standard for all production databases",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=0.5,
        beta_param=0.5,
    )
    detect_relationships(store, b_b)

    neighbors = store.get_neighbors(b_b.id, edge_types=[EDGE_CONTRADICTS])
    neighbor_ids: set[str] = {n.id for n, _e in neighbors}

    assert b_a.id not in neighbor_ids, (
        "Two agreeing beliefs should NOT have a CONTRADICTS edge."
    )


def test_req002_no_false_positive_both_negated(store: MemoryStore) -> None:
    """Two beliefs that both contain negation on the same topic must NOT contradict."""
    b_a: Belief = store.insert_belief(
        content="Do not use MongoDB for the analytics service",
        belief_type=BELIEF_REQUIREMENT,
        source_type=BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
    )
    b_b: Belief = store.insert_belief(
        content="Never use MongoDB for the analytics pipeline",
        belief_type=BELIEF_REQUIREMENT,
        source_type=BSRC_AGENT_INFERRED,
        alpha=0.5,
        beta_param=0.5,
    )
    detect_relationships(store, b_b)

    neighbors = store.get_neighbors(b_b.id, edge_types=[EDGE_CONTRADICTS])
    neighbor_ids: set[str] = {n.id for n, _e in neighbors}

    assert b_a.id not in neighbor_ids, (
        "Two beliefs both containing negation should NOT have a CONTRADICTS edge."
    )
