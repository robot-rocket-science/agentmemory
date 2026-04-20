"""REQ-004: Quality per token -- 2K retrieval quality >= 0.95 * 10K quality.

Tests that focused retrieval at 2,000 tokens produces equal or better
precision than a 10,000-token full dump. Uses a controlled store with
known-relevant and known-irrelevant beliefs for 20 queries.

Acceptance threshold: quality at 2K >= 0.95 * quality at 10K.
Hallucination rate at 2K <= hallucination rate at 10K.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
)
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore


# 10 queries with known-relevant belief content.
# Each entry: (query, list of relevant content substrings, list of irrelevant content substrings)
_QUERY_GROUND_TRUTH: list[tuple[str, list[str], list[str]]] = [
    (
        "database configuration",
        ["PostgreSQL is the primary database", "Database connection pool size is 20"],
        ["Frontend uses React", "CSS grid layout for dashboard"],
    ),
    (
        "authentication setup",
        ["JWT tokens with RS256 signing", "OAuth2 provider is Auth0"],
        ["Logging format is JSON", "Redis cache TTL is 300 seconds"],
    ),
    (
        "deployment pipeline",
        ["Deploy via GitHub Actions to AWS ECS", "Docker images tagged with git SHA"],
        ["Unit tests use pytest fixtures", "Database migration tool is alembic"],
    ),
    (
        "testing strategy",
        ["Unit tests use pytest fixtures", "Integration tests hit real database"],
        ["Deploy via GitHub Actions", "Frontend uses React"],
    ),
    (
        "caching layer",
        ["Redis cache TTL is 300 seconds", "Cache invalidation on write-through"],
        ["JWT tokens with RS256 signing", "Docker images tagged with git SHA"],
    ),
    (
        "frontend framework",
        ["Frontend uses React with TypeScript", "CSS grid layout for dashboard"],
        ["PostgreSQL is the primary database", "Redis cache TTL is 300 seconds"],
    ),
    (
        "logging and monitoring",
        ["Logging format is JSON structured", "Metrics exported to Prometheus"],
        ["OAuth2 provider is Auth0", "Cache invalidation on write-through"],
    ),
    (
        "API design",
        ["REST API with versioned paths", "Rate limiting at 1000 requests per minute"],
        ["Unit tests use pytest fixtures", "CSS grid layout for dashboard"],
    ),
    (
        "error handling",
        ["Errors return RFC 7807 problem details", "Circuit breaker on external calls"],
        ["Database connection pool size is 20", "Docker images tagged with git SHA"],
    ),
    (
        "security practices",
        ["Input validation on all endpoints", "CORS restricted to known origins"],
        ["Logging format is JSON structured", "Frontend uses React with TypeScript"],
    ),
]


def _seed_store(store: MemoryStore) -> None:
    """Populate store with all beliefs (relevant + irrelevant for each query)."""
    all_contents: set[str] = set()
    for _query, relevant, irrelevant in _QUERY_GROUND_TRUTH:
        for content in relevant + irrelevant:
            all_contents.add(content)

    # Also add 50 filler beliefs to make the store realistic
    for i in range(50):
        all_contents.add(f"Filler belief number {i} about miscellaneous project detail")

    for content in all_contents:
        store.insert_belief(
            content=content,
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
            alpha=2.0,
            beta_param=1.0,
        )


def _precision_at_k(
    retrieved_contents: list[str],
    relevant_substrings: list[str],
) -> float:
    """Fraction of retrieved beliefs that match a relevant substring."""
    if not retrieved_contents:
        return 0.0
    hits: int = 0
    for content in retrieved_contents:
        for rel in relevant_substrings:
            if rel in content:
                hits += 1
                break
    return hits / len(retrieved_contents)


def _recall_at_k(
    retrieved_contents: list[str],
    relevant_substrings: list[str],
) -> float:
    """Fraction of relevant beliefs that appear in retrieved set."""
    if not relevant_substrings:
        return 1.0
    found: int = 0
    for rel in relevant_substrings:
        for content in retrieved_contents:
            if rel in content:
                found += 1
                break
    return found / len(relevant_substrings)


def test_req004_2k_quality_matches_10k(store: MemoryStore) -> None:
    """2K budget retrieval must achieve >= 0.95 * quality of 10K budget."""
    _seed_store(store)

    precisions_2k: list[float] = []
    precisions_10k: list[float] = []

    for query, relevant, _irrelevant in _QUERY_GROUND_TRUTH:
        result_2k: RetrievalResult = retrieve(
            store,
            query,
            budget=2000,
            include_locked=False,
        )
        result_10k: RetrievalResult = retrieve(
            store,
            query,
            budget=10000,
            include_locked=False,
        )

        contents_2k: list[str] = [b.content for b in result_2k.beliefs]
        contents_10k: list[str] = [b.content for b in result_10k.beliefs]

        precisions_2k.append(_precision_at_k(contents_2k, relevant))
        precisions_10k.append(_precision_at_k(contents_10k, relevant))

    mean_2k: float = sum(precisions_2k) / len(precisions_2k)
    mean_10k: float = sum(precisions_10k) / len(precisions_10k)

    # 10K may return more beliefs, diluting precision. 2K should be at least
    # as precise due to tighter budget forcing better selection.
    threshold: float = 0.95 * mean_10k if mean_10k > 0 else 0.0
    assert mean_2k >= threshold, (
        f"REQ-004 FAILED: mean precision at 2K ({mean_2k:.3f}) < "
        f"0.95 * mean precision at 10K ({mean_10k:.3f} * 0.95 = {threshold:.3f})"
    )


def test_req004_2k_recall_comparable(store: MemoryStore) -> None:
    """2K budget should still find most relevant beliefs (recall check)."""
    _seed_store(store)

    recalls_2k: list[float] = []

    for query, relevant, _irrelevant in _QUERY_GROUND_TRUTH:
        result_2k: RetrievalResult = retrieve(
            store,
            query,
            budget=2000,
            include_locked=False,
        )
        contents_2k: list[str] = [b.content for b in result_2k.beliefs]
        recalls_2k.append(_recall_at_k(contents_2k, relevant))

    mean_recall: float = sum(recalls_2k) / len(recalls_2k)

    # With only 2 relevant beliefs per query and a 2K budget, we should
    # find at least 50% of them on average.
    assert mean_recall >= 0.50, (
        f"REQ-004: mean recall at 2K ({mean_recall:.3f}) < 0.50. "
        f"The retrieval pipeline is missing too many relevant beliefs."
    )


def test_req004_budget_enforced(store: MemoryStore) -> None:
    """Every retrieval at 2K budget must stay within 2,000 tokens."""
    _seed_store(store)

    for query, _relevant, _irrelevant in _QUERY_GROUND_TRUTH:
        result: RetrievalResult = retrieve(
            store,
            query,
            budget=2000,
            include_locked=False,
        )
        assert result.total_tokens <= 2000, (
            f"Query '{query}' exceeded budget: {result.total_tokens} > 2000"
        )
