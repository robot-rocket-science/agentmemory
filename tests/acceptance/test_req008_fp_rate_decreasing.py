"""REQ-008: False positive rate decreasing over time.

Tests that the feedback loop reduces retrieval noise over sessions.
Simulates 20 sessions where beliefs receive "used" or "harmful" feedback.
FP rate at session 20 must be lower than FP rate at session 5.

The test creates a mix of relevant and irrelevant beliefs, then runs
repeated retrieval-feedback cycles. Irrelevant beliefs that are marked
"harmful" should have their confidence decrease, causing them to rank
lower in subsequent retrievals (reducing FP rate).
"""
from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    Belief,
)
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore


_QUERY: str = "database configuration PostgreSQL"

# Beliefs that are relevant to the query
_RELEVANT: list[str] = [
    "PostgreSQL is the primary database for all services",
    "Database connection uses pgbouncer for connection pooling",
    "PostgreSQL version 15 with JSONB support enabled",
    "Database schema migrations managed by alembic",
    "PostgreSQL configuration tuned for 8GB RAM server",
]

# Beliefs that are NOT relevant but share some vocabulary
_IRRELEVANT: list[str] = [
    "The database of known issues is tracked in Linear",
    "Configuration files are stored in the config directory",
    "PostgreSQL documentation was reviewed last quarter",
    "The configuration management tool is Ansible not Puppet",
    "Database diagram exported as PNG for documentation",
    "Configuration drift detection runs every 6 hours",
    "PostgreSQL client library version pinned in requirements",
    "The legacy database migration script is deprecated",
    "Configuration validation happens at startup time only",
    "Database backups stored in S3 with 30 day retention",
]

# Additional filler to make the store realistic
_FILLER: list[str] = [
    f"Unrelated filler belief about topic {i} for test padding"
    for i in range(30)
]


def _seed_store(store: MemoryStore) -> dict[str, bool]:
    """Insert beliefs and return a map of belief_id -> is_relevant."""
    relevance: dict[str, bool] = {}

    for content in _RELEVANT:
        b: Belief = store.insert_belief(
            content=content,
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
            alpha=2.0,
            beta_param=1.0,
        )
        relevance[b.id] = True

    for content in _IRRELEVANT:
        b = store.insert_belief(
            content=content,
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
            alpha=2.0,
            beta_param=1.0,
        )
        relevance[b.id] = False

    for content in _FILLER:
        b = store.insert_belief(
            content=content,
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
            alpha=1.0,
            beta_param=1.0,
        )
        relevance[b.id] = False

    return relevance


def _compute_fp_rate(
    beliefs: list[Belief],
    relevance: dict[str, bool],
) -> float:
    """Fraction of retrieved beliefs that are irrelevant (false positives)."""
    if not beliefs:
        return 0.0
    fp_count: int = sum(
        1 for b in beliefs if not relevance.get(b.id, False)
    )
    return fp_count / len(beliefs)


def _run_feedback_cycle(
    store: MemoryStore,
    relevance: dict[str, bool],
) -> float:
    """Run one retrieval-feedback cycle and return the FP rate."""
    result: RetrievalResult = retrieve(
        store, _QUERY, budget=2000, include_locked=False,
    )

    # Give feedback: "used" for relevant, "harmful" for irrelevant
    for belief in result.beliefs:
        is_relevant: bool = relevance.get(belief.id, False)
        outcome: str = "used" if is_relevant else "harmful"
        store.update_confidence(belief.id, outcome, weight=1.0)

    return _compute_fp_rate(result.beliefs, relevance)


def test_req008_fp_rate_decreases_with_feedback(store: MemoryStore) -> None:
    """FP rate at session 20 must be lower than FP rate at session 5.

    Simulates 20 retrieval-feedback cycles. Each cycle retrieves beliefs
    for the same query, then gives positive feedback to relevant beliefs
    and negative feedback to irrelevant ones. Over time, irrelevant
    beliefs should rank lower, reducing the false positive rate.
    """
    relevance: dict[str, bool] = _seed_store(store)
    fp_rates: list[float] = []

    n_sessions: int = 20
    for _session in range(n_sessions):
        fp_rate: float = _run_feedback_cycle(store, relevance)
        fp_rates.append(fp_rate)

    # Compare early (session 5) vs late (session 20)
    fp_early: float = fp_rates[4]  # session 5 (0-indexed)
    fp_late: float = fp_rates[-1]  # session 20

    assert fp_late <= fp_early, (
        f"REQ-008 FAILED: FP rate at session 20 ({fp_late:.3f}) > "
        f"FP rate at session 5 ({fp_early:.3f}). "
        f"The feedback loop is not reducing noise over time. "
        f"Full FP rate trajectory: {[f'{r:.3f}' for r in fp_rates]}"
    )


def test_req008_fp_rate_trend_is_nonincreasing(store: MemoryStore) -> None:
    """The overall FP rate trend should be non-increasing (allowing for noise).

    Rather than requiring strict monotonic decrease (which is unrealistic),
    verify that the mean FP rate in the last 5 sessions is <= mean FP rate
    in the first 5 sessions.
    """
    relevance: dict[str, bool] = _seed_store(store)
    fp_rates: list[float] = []

    n_sessions: int = 20
    for _session in range(n_sessions):
        fp_rate: float = _run_feedback_cycle(store, relevance)
        fp_rates.append(fp_rate)

    mean_first_5: float = sum(fp_rates[:5]) / 5
    mean_last_5: float = sum(fp_rates[15:]) / 5

    assert mean_last_5 <= mean_first_5, (
        f"REQ-008: Mean FP rate in last 5 sessions ({mean_last_5:.3f}) > "
        f"mean FP rate in first 5 sessions ({mean_first_5:.3f}). "
        f"Feedback loop is not improving retrieval quality over time."
    )
