"""Full retrieval pipeline: store -> scoring -> compression -> ranked results.

Connects MemoryStore, scoring, and compression into a single callable that
returns a token-budget-aware ranked list of beliefs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from agentmemory.compression import compress_belief, estimate_tokens, pack_beliefs
from agentmemory.hrr import HRRGraph
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


# Module-level HRR graph cache (built lazily on first retrieval with HRR)
_hrr_graph: HRRGraph | None = None
_hrr_edge_count: int = 0


def _get_hrr_graph(store: MemoryStore) -> HRRGraph | None:
    """Build or return cached HRR graph from store edges.

    Returns None if the store has no edges (HRR adds no value without edges).
    Rebuilds if edge count has changed.
    """
    global _hrr_graph, _hrr_edge_count
    triples: list[tuple[str, str, str]] = store.get_all_edge_triples()
    if not triples:
        return None
    if _hrr_graph is not None and len(triples) == _hrr_edge_count:
        return _hrr_graph
    # Build new graph
    graph: HRRGraph = HRRGraph()
    graph.encode(triples)
    _hrr_graph = graph
    _hrr_edge_count = len(triples)
    return graph


def _hrr_expand(
    store: MemoryStore,
    hrr: HRRGraph,
    seed_ids: list[str],
    top_k: int = 5,
) -> list[Belief]:
    """Use HRR single-hop to find structurally connected beliefs from seeds.

    This is the vocabulary-bridge step: finds beliefs connected via typed edges
    that FTS5 keyword matching would miss.
    """
    found_ids: set[str] = set()
    for seed_id in seed_ids:
        # Try each edge type the seed participates in
        for edge_type in hrr.edge_types():
            results: list[tuple[str, float]] = hrr.query_forward(
                seed_id, edge_type, top_k=3,
            )
            for label, _sim in results:
                found_ids.add(label)
            # Also reverse
            results = hrr.query_reverse(seed_id, edge_type, top_k=3)
            for label, _sim in results:
                found_ids.add(label)

    # Look up actual beliefs for found IDs
    beliefs: list[Belief] = []
    for belief_id in found_ids:
        belief: Belief | None = store.get_belief(belief_id)
        if belief is not None and belief.valid_to is None:
            beliefs.append(belief)
        if len(beliefs) >= top_k:
            break

    return beliefs


def retrieve(
    store: MemoryStore,
    query: str,
    budget: int = 2000,
    top_k: int = 50,
    include_locked: bool = True,
    max_locked: int = 100,
    use_hrr: bool = True,
) -> RetrievalResult:
    """Full retrieval pipeline: FTS5 + HRR + scoring + compression.

    Steps:
    1. Collect locked beliefs (L0).
    2. FTS5 full-text search (L2).
    3. HRR vocabulary-bridge expansion from FTS5 hits (L3).
    4. Merge all candidate sets, deduplicate.
    5. Score, sort, compress, pack into budget.
    """
    current_time: str = _now_iso()

    # Step 1: locked beliefs (L0), capped.
    locked_beliefs: list[Belief] = store.get_locked_beliefs() if include_locked else []
    if len(locked_beliefs) > max_locked:
        locked_beliefs = locked_beliefs[:max_locked]

    # Step 2: FTS5 search (L2).
    fts_beliefs: list[Belief] = []
    query_stripped: str = query.strip()
    if query_stripped:
        fts_beliefs = store.search(query_stripped, top_k=top_k)

    # Step 3: HRR vocabulary-bridge expansion (L3).
    hrr_beliefs: list[Belief] = []
    if use_hrr and fts_beliefs:
        hrr: HRRGraph | None = _get_hrr_graph(store)
        if hrr is not None:
            seed_ids: list[str] = [b.id for b in fts_beliefs[:5]]
            hrr_beliefs = _hrr_expand(store, hrr, seed_ids, top_k=5)

    # Step 4: merge and deduplicate.
    seen_ids: set[str] = set()
    candidates: list[Belief] = []

    for belief in locked_beliefs:
        if belief.id not in seen_ids:
            seen_ids.add(belief.id)
            candidates.append(belief)

    for belief in fts_beliefs:
        if belief.id not in seen_ids:
            if not include_locked and belief.locked:
                continue
            seen_ids.add(belief.id)
            candidates.append(belief)

    for belief in hrr_beliefs:
        if belief.id not in seen_ids:
            seen_ids.add(belief.id)
            candidates.append(belief)

    # Step 5: score every candidate.
    scores: dict[str, float] = {}
    for belief in candidates:
        scores[belief.id] = score_belief(belief, query_stripped, current_time)

    # Step 6: sort by score descending.
    candidates.sort(key=lambda b: scores[b.id], reverse=True)

    # Step 7: compress and pack into budget.
    packed: list[Belief] = pack_beliefs(candidates, budget_tokens=budget)

    # Step 8: compute token accounting.
    total_tokens: int = sum(
        estimate_tokens(compress_belief(b)) for b in packed
    )
    budget_remaining: int = budget - total_tokens

    packed_scores: dict[str, float] = {b.id: scores[b.id] for b in packed}

    return RetrievalResult(
        beliefs=packed,
        scores=packed_scores,
        total_tokens=total_tokens,
        budget_remaining=budget_remaining,
    )
