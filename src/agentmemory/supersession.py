"""Temporal supersession detector for agentmemory.

After a new belief is persisted, searches for older active beliefs with
high term overlap. If a match is found and the time gap exceeds the
threshold, the older belief is superseded by the newer one.

The core insight: when two beliefs share the same topic, the newer one
almost always reflects current understanding. Time is the strongest
signal for contradiction detection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

from agentmemory.models import Belief
from agentmemory.store import MemoryStore

# Minimum Jaccard similarity on significant terms to consider two beliefs
# as covering the same topic. Tuned to avoid false positives from shared
# domain vocabulary while catching genuine same-topic pairs.
_MIN_JACCARD: Final[float] = 0.4

# Minimum age gap in seconds between old and new belief for supersession.
# Prevents superseding beliefs created in the same burst of ingestion.
_MIN_AGE_GAP_SECONDS: Final[int] = 3600  # 1 hour

# Maximum candidates to check from FTS5 search.
_MAX_CANDIDATES: Final[int] = 10

# Minimum significant terms in a belief to be eligible for supersession.
# Very short beliefs (e.g., "def build_fts") are too ambiguous.
_MIN_TERMS: Final[int] = 3

_STOPWORDS: Final[frozenset[str]] = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "of", "in", "to",
    "for", "with", "on", "at", "by", "from", "as", "into", "through",
    "that", "this", "these", "those", "it", "its", "not", "no", "all",
    "and", "or", "but", "if", "then", "than", "so", "just", "also",
    "about", "up", "out", "when", "where", "how", "what", "which",
    "who", "whom", "there", "here", "each", "every", "both", "few",
    "more", "most", "other", "some", "such", "only", "own", "same",
    "very", "too", "any", "new", "one", "two", "we", "you", "they",
    "my", "your", "our", "his", "her", "me", "us", "them", "he", "she",
})


@dataclass
class SupersessionResult:
    """Result of a temporal supersession check."""

    checked: bool = False
    superseded_id: str = ""
    superseded_content: str = ""
    jaccard: float = 0.0
    age_gap_hours: float = 0.0
    reason: str = ""


def extract_terms(text: str) -> set[str]:
    """Extract significant terms from text, filtering stopwords."""
    words: list[str] = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) >= 2}


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two term sets."""
    if not a or not b:
        return 0.0
    intersection: int = len(a & b)
    union: int = len(a | b)
    if union == 0:
        return 0.0
    return intersection / union


def _parse_iso(iso_str: str) -> datetime:
    """Parse an ISO 8601 timestamp to a timezone-aware datetime."""
    dt: datetime = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def check_temporal_supersession(
    store: MemoryStore,
    new_belief: Belief,
    min_jaccard: float = _MIN_JACCARD,
    min_age_gap_seconds: int = _MIN_AGE_GAP_SECONDS,
) -> SupersessionResult:
    """Check if a newly persisted belief should supersede an older one.

    Searches for active beliefs with high term overlap. If found and the
    time gap is sufficient, supersedes the oldest matching belief.

    Does NOT supersede locked beliefs.

    Returns a SupersessionResult describing what happened.
    """
    result = SupersessionResult(checked=True)

    new_terms: set[str] = extract_terms(new_belief.content)
    if len(new_terms) < _MIN_TERMS:
        result.reason = "new belief too short for supersession check"
        return result

    # Search for candidates using the new belief's content as query
    candidates: list[Belief] = store.search(
        new_belief.content, top_k=_MAX_CANDIDATES,
    )

    new_dt: datetime = _parse_iso(new_belief.created_at)

    best_match: Belief | None = None
    best_jaccard: float = 0.0
    best_age_gap: float = 0.0

    for candidate in candidates:
        # Skip self
        if candidate.id == new_belief.id:
            continue

        # Skip already-superseded
        if candidate.valid_to is not None or candidate.superseded_by is not None:
            continue

        # Never supersede locked beliefs
        if candidate.locked:
            continue

        # Check time gap: candidate must be older than new belief
        candidate_dt: datetime = _parse_iso(candidate.created_at)
        age_gap_seconds: float = (new_dt - candidate_dt).total_seconds()
        if age_gap_seconds < min_age_gap_seconds:
            continue

        # Check term overlap
        candidate_terms: set[str] = extract_terms(candidate.content)
        if len(candidate_terms) < _MIN_TERMS:
            continue

        jaccard: float = jaccard_similarity(new_terms, candidate_terms)
        if jaccard < min_jaccard:
            continue

        # Pick the highest-overlap match (most likely to be same topic)
        if jaccard > best_jaccard:
            best_match = candidate
            best_jaccard = jaccard
            best_age_gap = age_gap_seconds / 3600.0

    if best_match is None:
        result.reason = "no overlapping older beliefs found"
        return result

    # Supersede the best match
    store.supersede_belief(
        old_id=best_match.id,
        new_id=new_belief.id,
        reason="temporal_supersession",
    )

    result.superseded_id = best_match.id
    result.superseded_content = best_match.content
    result.jaccard = best_jaccard
    result.age_gap_hours = best_age_gap
    result.reason = (
        f"superseded (jaccard={best_jaccard:.2f}, "
        f"age={best_age_gap:.1f}h)"
    )
    return result
