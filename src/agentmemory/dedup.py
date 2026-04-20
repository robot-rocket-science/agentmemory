"""Duplicate detection for belief deduplication.

Identifies exact duplicates (same content_hash) and near-duplicates
(high word-level Jaccard similarity). Provides merge functionality
that keeps the highest-confidence belief and supersedes the rest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agentmemory.models import Belief
from agentmemory.store import MemoryStore

_WORD_RE: re.Pattern[str] = re.compile(r"[a-zA-Z0-9]+")
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "must",
        "can",
        "could",
        "of",
        "in",
        "to",
        "for",
        "with",
        "on",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "not",
        "no",
        "all",
        "and",
        "or",
        "but",
        "if",
        "then",
        "than",
        "when",
        "where",
        "how",
    }
)


@dataclass
class DuplicateCluster:
    """A group of duplicate or near-duplicate beliefs."""

    canonical_id: str  # highest-confidence belief in the cluster
    duplicate_ids: list[str] = field(default_factory=lambda: [])
    similarity: float = 1.0  # 1.0 for exact, <1.0 for near-duplicates


@dataclass
class DeduplicationResult:
    """Result of a deduplication operation."""

    exact_clusters: list[DuplicateCluster]
    near_clusters: list[DuplicateCluster]
    total_duplicates: int
    merged: int  # only non-zero if merge was applied


def _tokenize(text: str) -> set[str]:
    """Tokenize text into a set of lowercase content words (no stopwords)."""
    words: list[str] = _WORD_RE.findall(text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two word sets."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    intersection: int = len(a & b)
    union: int = len(a | b)
    return intersection / union if union > 0 else 0.0


def find_exact_duplicates(store: MemoryStore) -> list[DuplicateCluster]:
    """Find beliefs with identical content_hash (exact duplicates).

    Groups by content_hash and returns clusters where the highest-confidence
    belief is the canonical.
    """
    rows = store.query(
        """SELECT content_hash, GROUP_CONCAT(id, ',') as ids
           FROM beliefs
           WHERE valid_to IS NULL
           GROUP BY content_hash
           HAVING COUNT(*) > 1
           ORDER BY COUNT(*) DESC"""
    )

    clusters: list[DuplicateCluster] = []
    for row in rows:
        ids: list[str] = str(row[1]).split(",")
        # Load beliefs to find highest confidence
        beliefs: list[Belief] = []
        for bid in ids:
            b: Belief | None = store.get_belief(bid)
            if b is not None:
                beliefs.append(b)
        if len(beliefs) < 2:
            continue
        beliefs.sort(key=lambda b: b.confidence, reverse=True)
        canonical: Belief = beliefs[0]
        dupes: list[str] = [b.id for b in beliefs[1:]]
        clusters.append(
            DuplicateCluster(
                canonical_id=canonical.id,
                duplicate_ids=dupes,
                similarity=1.0,
            )
        )

    return clusters


def find_near_duplicates(
    store: MemoryStore,
    threshold: float = 0.8,
    sample_size: int = 5000,
) -> list[DuplicateCluster]:
    """Find beliefs with high word-level Jaccard similarity.

    Samples up to sample_size beliefs and compares all pairs.
    Returns clusters where similarity >= threshold.
    """
    beliefs: list[Belief] = store.get_all_active_beliefs(limit=sample_size)

    # Pre-tokenize
    tokens: dict[str, set[str]] = {}
    for b in beliefs:
        tokens[b.id] = _tokenize(b.content)

    # Find pairs above threshold (skip very short content)
    clusters: list[DuplicateCluster] = []
    merged_ids: set[str] = set()  # avoid putting same belief in multiple clusters

    for i, b1 in enumerate(beliefs):
        if b1.id in merged_ids:
            continue
        t1: set[str] = tokens[b1.id]
        if len(t1) < 3:
            continue  # too short to compare meaningfully

        cluster_ids: list[str] = []
        for j in range(i + 1, len(beliefs)):
            b2: Belief = beliefs[j]
            if b2.id in merged_ids:
                continue
            t2: set[str] = tokens[b2.id]
            if len(t2) < 3:
                continue
            sim: float = _jaccard(t1, t2)
            if sim >= threshold:
                cluster_ids.append(b2.id)
                merged_ids.add(b2.id)

        if cluster_ids:
            merged_ids.add(b1.id)
            # Canonical = highest confidence
            all_in_cluster: list[Belief] = [b1]
            for cid in cluster_ids:
                cb: Belief | None = store.get_belief(cid)
                if cb is not None:
                    all_in_cluster.append(cb)
            all_in_cluster.sort(key=lambda b: b.confidence, reverse=True)
            canonical: Belief = all_in_cluster[0]
            dupes: list[str] = [b.id for b in all_in_cluster[1:]]
            min_sim: float = min(
                _jaccard(tokens[canonical.id], tokens[d]) for d in dupes
            )
            clusters.append(
                DuplicateCluster(
                    canonical_id=canonical.id,
                    duplicate_ids=dupes,
                    similarity=min_sim,
                )
            )

    return clusters


def merge_duplicates(
    store: MemoryStore,
    clusters: list[DuplicateCluster],
) -> int:
    """Merge duplicate clusters: supersede duplicates, keep canonical.

    Returns count of beliefs superseded.
    """
    merged: int = 0
    for cluster in clusters:
        for dup_id in cluster.duplicate_ids:
            store.soft_delete_belief(dup_id)
            merged += 1
    return merged


def find_and_report(
    store: MemoryStore,
    near_threshold: float = 0.8,
    near_sample: int = 5000,
) -> DeduplicationResult:
    """Run full dedup analysis and return results."""
    exact: list[DuplicateCluster] = find_exact_duplicates(store)
    near: list[DuplicateCluster] = find_near_duplicates(
        store, threshold=near_threshold, sample_size=near_sample
    )
    total: int = sum(len(c.duplicate_ids) for c in exact) + sum(
        len(c.duplicate_ids) for c in near
    )
    return DeduplicationResult(
        exact_clusters=exact,
        near_clusters=near,
        total_duplicates=total,
        merged=0,
    )
