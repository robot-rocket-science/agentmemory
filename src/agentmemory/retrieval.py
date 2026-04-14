"""Full retrieval pipeline: store -> scoring -> compression -> ranked results.

Connects MemoryStore, scoring, and compression into a single callable that
returns a token-budget-aware ranked list of beliefs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from agentmemory.compression import pack_beliefs
from agentmemory.hrr import HRRGraph
from agentmemory.models import EDGE_CONTRADICTS, Belief
from agentmemory.scoring import score_belief
from agentmemory.store import MemoryStore



@dataclass
class RetrievalResult:
    """Output of a single retrieve() call."""

    beliefs: list[Belief]
    scores: dict[str, float]   # belief_id -> score
    total_tokens: int
    budget_remaining: int
    contradiction_warnings: list[str] | None = None


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


# Edge types worth querying via HRR. Semantic edges provide vocabulary
# bridging; structural edges (COMMIT_TOUCHES, CO_CHANGED, SENTENCE_IN_FILE,
# WITHIN_SECTION) add noise without improving retrieval quality.
_HRR_EDGE_TYPES: frozenset[str] = frozenset({
    "SUPERSEDES", "CONTRADICTS", "SUPPORTS", "CALLS", "CITES",
})


def _hrr_expand(
    store: MemoryStore,
    hrr: HRRGraph,
    seed_ids: list[str],
    top_k: int = 5,
) -> list[Belief]:
    """Use HRR single-hop to find structurally connected beliefs from seeds.

    This is the vocabulary-bridge step: finds beliefs connected via typed edges
    that FTS5 keyword matching would miss. Only queries semantic edge types
    to avoid O(seeds * edge_types * cleanup_size) blowup.
    """
    # Only query edge types that exist in the graph AND are semantic.
    active_types: list[str] = [
        et for et in hrr.edge_types() if et in _HRR_EDGE_TYPES
    ]

    found_ids: set[str] = set()
    for seed_id in seed_ids[:3]:  # Cap seeds to limit query count.
        for edge_type in active_types:
            results: list[tuple[str, float]] = hrr.query_forward(
                seed_id, edge_type, top_k=3,
            )
            for label, _sim in results:
                found_ids.add(label)
            results = hrr.query_reverse(seed_id, edge_type, top_k=3)
            for label, _sim in results:
                found_ids.add(label)

    # Batch lookup instead of N+1 get_belief calls.
    if not found_ids:
        return []
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
    current_time: datetime = datetime.now(timezone.utc)
    query_stripped: str = query.strip()

    # Step 1: locked beliefs (L0), relevance-filtered.
    # Split into relevant (query term overlap) and irrelevant.
    # Include all relevant locked beliefs, cap irrelevant ones to avoid noise.
    locked_beliefs: list[Belief] = []
    if include_locked:
        all_locked: list[Belief] = store.get_locked_beliefs()
        query_terms_lower: list[str] = [t.lower() for t in query_stripped.split() if len(t) >= 2]
        relevant_locked: list[Belief] = []
        irrelevant_locked: list[Belief] = []
        for belief in all_locked:
            content_lower: str = belief.content.lower()
            if any(term in content_lower for term in query_terms_lower):
                relevant_locked.append(belief)
            else:
                irrelevant_locked.append(belief)
        # All relevant locked beliefs are included.
        # Cap irrelevant ones to avoid budget waste (keep a small sample
        # so truly universal constraints still surface).
        max_irrelevant: int = min(10, max_locked - len(relevant_locked))
        locked_beliefs = relevant_locked + irrelevant_locked[:max(0, max_irrelevant)]

    # Step 2: FTS5 search (L2).
    fts_beliefs: list[Belief] = []
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
    packed: list[Belief]
    total_tokens: int
    packed, total_tokens = pack_beliefs(candidates, budget_tokens=budget)
    budget_remaining: int = budget - total_tokens

    packed_scores: dict[str, float] = {b.id: scores[b.id] for b in packed}

    # Step 9: flag contradictions in result set (REQ-002).
    contradiction_warnings: list[str] = flag_contradictions(store, packed)

    return RetrievalResult(
        beliefs=packed,
        scores=packed_scores,
        total_tokens=total_tokens,
        budget_remaining=budget_remaining,
        contradiction_warnings=contradiction_warnings,
    )


def flag_contradictions(
    store: MemoryStore,
    beliefs: list[Belief],
) -> list[str]:
    """Check if any beliefs in the result set have CONTRADICTS edges between them.

    Returns a list of warning strings for each contradicting pair found.
    This addresses REQ-002: never silently present contradictory beliefs.
    """
    if len(beliefs) < 2:
        return []

    result_ids: set[str] = {b.id for b in beliefs}
    warnings: list[str] = []
    checked: set[frozenset[str]] = set()

    for belief in beliefs:
        neighbors = store.get_neighbors(
            belief.id, edge_types=[EDGE_CONTRADICTS],
        )
        for neighbor, _edge in neighbors:
            if neighbor.id in result_ids:
                pair: frozenset[str] = frozenset({belief.id, neighbor.id})
                if pair not in checked:
                    checked.add(pair)
                    snippet_a: str = belief.content[:60].replace("\n", " ")
                    snippet_b: str = neighbor.content[:60].replace("\n", " ")
                    warnings.append(
                        f"CONTRADICTS: [{belief.id}] \"{snippet_a}\" "
                        f"vs [{neighbor.id}] \"{snippet_b}\""
                    )

    return warnings
