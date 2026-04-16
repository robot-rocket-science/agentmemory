"""Full retrieval pipeline: store -> scoring -> compression -> ranked results.

Connects MemoryStore, scoring, and compression into a single callable that
returns a token-budget-aware ranked list of beliefs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import re

from agentmemory.compression import pack_beliefs
from agentmemory.hrr import HRRGraph
from agentmemory.models import EDGE_CONTRADICTS, Belief
from agentmemory.scoring import score_belief
from agentmemory.store import MemoryStore

# Words that appear structurally in correction beliefs but carry no topical
# signal. When the query contains these, deprioritize beliefs that match ONLY
# on these words (CS-032: negation pattern noise).
_NEGATION_STOP_WORDS: frozenset[str] = frozenset({
    "not", "no", "dont", "don't", "never", "cannot", "can't",
    "isn't", "aren't", "wasn't", "weren't", "doesn't", "didn't",
    "without", "none", "nor",
})


def _filter_negation_noise(
    query: str,
    beliefs: list[Belief],
    keep_top: int = 50,
) -> list[Belief]:
    """Deprioritize beliefs that match a query only on negation/stop words.

    When a query like "service not starting" is run through FTS5, beliefs
    containing "not" in their correction text flood the results even though
    they share no topical terms with the query.

    This filter splits query terms into topical vs negation, then pushes
    beliefs with zero topical overlap to the end of the list.
    """
    query_terms: set[str] = {
        t.lower() for t in re.split(r'\W+', query) if len(t) >= 2
    }
    topical_terms: set[str] = query_terms - _NEGATION_STOP_WORDS
    if not topical_terms:
        return beliefs  # Query is all negation words -- can't filter

    signal: list[Belief] = []
    noise: list[Belief] = []
    for b in beliefs:
        belief_terms: set[str] = {
            t.lower() for t in re.split(r'\W+', b.content) if len(t) >= 2
        }
        # Check if belief shares any topical term with the query
        if topical_terms & belief_terms:
            signal.append(b)
        else:
            noise.append(b)

    # Return signal first, then noise (preserving original order within each)
    result: list[Belief] = signal + noise
    return result[:keep_top]



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
    """Build or return cached HRR graph from semantic edges only.

    Filters out structural edges (SENTENCE_IN_FILE, WITHIN_SECTION, etc.)
    at build time, not just query time. This reduces cleanup memory from
    21K to ~4K labels and cuts encode from 10s to ~1s, query from 720ms to 117ms.

    Returns None if the store has no semantic edges.
    Rebuilds if edge count has changed.
    """
    global _hrr_graph, _hrr_edge_count
    all_triples: list[tuple[str, str, str]] = store.get_all_edge_triples()
    if not all_triples:
        return None
    # Filter to semantic edge types at build time (not just query time).
    triples: list[tuple[str, str, str]] = [
        t for t in all_triples if t[2] in _HRR_EDGE_TYPES
    ]
    if not triples:
        return None
    if _hrr_graph is not None and len(triples) == _hrr_edge_count:
        return _hrr_graph
    # Build new graph from semantic edges only
    graph: HRRGraph = HRRGraph()
    graph.encode(triples)
    _hrr_graph = graph
    _hrr_edge_count = len(triples)
    return graph


# Edge types worth querying via HRR. Semantic edges provide vocabulary
# bridging; structural edges (COMMIT_TOUCHES, CO_CHANGED, SENTENCE_IN_FILE,
# WITHIN_SECTION) add noise without improving retrieval quality.
_HRR_EDGE_TYPES: frozenset[str] = frozenset({
    "SUPERSEDES", "CONTRADICTS", "SUPPORTS", "CALLS", "CITES", "TESTS", "IMPLEMENTS",
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
    use_bfs: bool = True,
    temporal_sort: bool = False,
) -> RetrievalResult:
    """Full retrieval pipeline: L0 + L1 + FTS5 + HRR + BFS + scoring + compression.

    Steps:
    1. Collect locked beliefs (L0).
    1.5. Collect behavioral beliefs (L1).
    2. FTS5 full-text search (L2).
    3. HRR vocabulary-bridge expansion (L3).
    3.5. BFS multi-hop from FTS5+HRR hits (L3).
    4. Merge all candidate sets, deduplicate.
    5. Score, sort, compress, pack into budget.

    If temporal_sort is True, the final packed beliefs are re-sorted
    chronologically (newest-first) after packing. This preserves the
    relevance-based selection (score determines what fits in budget)
    but presents results in temporal order for state-tracking queries.
    """
    current_time: datetime = datetime.now(timezone.utc)
    query_stripped: str = query.strip()

    # Step 1: locked beliefs (L0), relevance-filtered.
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
        max_irrelevant: int = min(10, max_locked - len(relevant_locked))
        locked_beliefs = relevant_locked + irrelevant_locked[:max(0, max_irrelevant)]

    # Step 1.5: behavioral beliefs (L1) -- unlocked directives always included.
    behavioral_beliefs: list[Belief] = store.get_behavioral_beliefs(limit=10)

    # Step 2: FTS5 search (L2).
    fts_beliefs: list[Belief] = []
    if query_stripped:
        fts_beliefs = store.search(query_stripped, top_k=top_k)
        # CS-032: deprioritize beliefs matching only on negation words
        fts_beliefs = _filter_negation_noise(query_stripped, fts_beliefs, keep_top=top_k)

    # Step 3: HRR vocabulary-bridge expansion (L3).
    hrr_beliefs: list[Belief] = []
    if use_hrr and fts_beliefs:
        hrr: HRRGraph | None = _get_hrr_graph(store)
        if hrr is not None:
            seed_ids: list[str] = [b.id for b in fts_beliefs[:5]]
            hrr_beliefs = _hrr_expand(store, hrr, seed_ids, top_k=5)

    # Step 3.5: BFS multi-hop from FTS5+HRR hits (L3).
    bfs_beliefs: list[Belief] = []
    if use_bfs and (fts_beliefs or hrr_beliefs):
        bfs_seed_ids: list[str] = [b.id for b in fts_beliefs[:5] + hrr_beliefs[:3]]
        if bfs_seed_ids:
            expanded: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph(
                seed_ids=bfs_seed_ids, depth=2, max_nodes=20,
            )
            for entries in expanded.values():
                for belief, _edge_type, _hop in entries:
                    bfs_beliefs.append(belief)

    # Step 4: merge and deduplicate.
    seen_ids: set[str] = set()
    candidates: list[Belief] = []

    for belief in locked_beliefs:
        if belief.id not in seen_ids:
            seen_ids.add(belief.id)
            candidates.append(belief)

    for belief in behavioral_beliefs:
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

    for belief in bfs_beliefs:
        if belief.id not in seen_ids:
            seen_ids.add(belief.id)
            candidates.append(belief)

    # Step 4.5: batch-query retrieval stats for frequency boost.
    candidate_ids: list[str] = [b.id for b in candidates]
    stats_batch: dict[str, dict[str, int]] = store.get_retrieval_stats_batch(candidate_ids)

    # Step 5: score every candidate.
    scores: dict[str, float] = {}
    for belief in candidates:
        stats: dict[str, int] = stats_batch.get(belief.id, {})
        scores[belief.id] = score_belief(
            belief,
            query_stripped,
            current_time,
            retrieval_count=stats.get("retrieval_count", 0),
            used_count=stats.get("used", 0),
        )

    # Step 6: sort by score descending.
    candidates.sort(key=lambda b: scores[b.id], reverse=True)

    # Step 7: compress and pack into budget.
    packed: list[Belief]
    total_tokens: int
    packed, total_tokens = pack_beliefs(candidates, budget_tokens=budget)
    budget_remaining: int = budget - total_tokens

    packed_scores: dict[str, float] = {b.id: scores[b.id] for b in packed}

    # Step 8: temporal re-sort (newest-first) if requested.
    # Selection is still relevance-based (score determines budget inclusion),
    # but presentation order becomes chronological for state-tracking queries.
    if temporal_sort:
        packed.sort(key=lambda b: b.created_at, reverse=True)

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
