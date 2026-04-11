"""Full retrieval pipeline: store -> scoring -> compression -> ranked results.

Connects MemoryStore, scoring, and compression into a single callable that
returns a token-budget-aware ranked list of beliefs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from agentmemory.compression import compress_belief, estimate_tokens, pack_beliefs
from agentmemory.models import Belief
from agentmemory.scoring import score_belief
from agentmemory.store import MemoryStore


def _now_iso() -> str:
    """Current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RetrievalResult:
    """Output of a single retrieve() call."""

    beliefs: list[Belief]
    scores: dict[str, float]   # belief_id -> score
    total_tokens: int
    budget_remaining: int


def retrieve(
    store: MemoryStore,
    query: str,
    budget: int = 2000,
    top_k: int = 30,
    include_locked: bool = True,
    max_locked: int = 100,
) -> RetrievalResult:
    """Full retrieval pipeline.

    Steps:
    1. Collect all locked beliefs (L0 -- always included when include_locked=True).
    2. FTS5 full-text search for query-relevant beliefs (L2).
    3. Merge candidate sets, deduplicate by belief ID.
    4. Score all candidates (decay + lock_boost + thompson).
    5. Sort by score descending.
    6. Compress and pack into token budget.
    7. Return RetrievalResult with beliefs, scores, and budget accounting.
    """
    current_time: str = _now_iso()

    # Step 1: locked beliefs (L0), capped to prevent blowup.
    locked_beliefs: list[Belief] = store.get_locked_beliefs() if include_locked else []
    if len(locked_beliefs) > max_locked:
        locked_beliefs = locked_beliefs[:max_locked]

    # Step 2: FTS5 search (L2). May overlap with locked set.
    fts_beliefs: list[Belief] = []
    query_stripped: str = query.strip()
    if query_stripped:
        fts_beliefs = store.search(query_stripped, top_k=top_k)

    # Step 3: merge and deduplicate, locked beliefs take precedence.
    seen_ids: set[str] = set()
    candidates: list[Belief] = []

    for belief in locked_beliefs:
        if belief.id not in seen_ids:
            seen_ids.add(belief.id)
            candidates.append(belief)

    for belief in fts_beliefs:
        if belief.id not in seen_ids:
            # Exclude locked beliefs from FTS results when include_locked=False
            if not include_locked and belief.locked:
                continue
            seen_ids.add(belief.id)
            candidates.append(belief)

    # Step 4: score every candidate.
    scores: dict[str, float] = {}
    for belief in candidates:
        scores[belief.id] = score_belief(belief, query_stripped, current_time)

    # Step 5: sort by score descending.
    candidates.sort(key=lambda b: scores[b.id], reverse=True)

    # Step 6: compress and pack into budget.
    packed: list[Belief] = pack_beliefs(candidates, budget_tokens=budget)

    # Step 7: compute token accounting.
    total_tokens: int = sum(
        estimate_tokens(compress_belief(b)) for b in packed
    )
    budget_remaining: int = budget - total_tokens

    # Return only the beliefs that were packed, with their scores.
    packed_scores: dict[str, float] = {b.id: scores[b.id] for b in packed}

    return RetrievalResult(
        beliefs=packed,
        scores=packed_scores,
        total_tokens=total_tokens,
        budget_remaining=budget_remaining,
    )
