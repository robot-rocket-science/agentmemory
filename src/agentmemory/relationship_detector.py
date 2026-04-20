"""Relationship detector for agentmemory.

After a new belief is persisted, searches for related existing beliefs
and creates CONTRADICTS or SUPPORTS edges based on term overlap and
negation signals.

Runs alongside temporal supersession detection in the ingest pipeline.
Addresses REQ-002: contradiction detection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from agentmemory.models import (
    EDGE_CONTRADICTS,
    EDGE_IMPLEMENTS,
    EDGE_RELATES_TO,
    EDGE_SUPPORTS,
    Belief,
)
from agentmemory.store import MemoryStore
from agentmemory.supersession import extract_terms, jaccard_similarity

# Minimum Jaccard similarity for CONTRADICTS detection.
# Lower than supersession (0.4) to catch more relationships.
_MIN_JACCARD_CONTRADICTS: Final[float] = 0.3

# Minimum Jaccard similarity for SUPPORTS detection.
# Higher bar -- we want genuine topical agreement, not just shared vocabulary.
_MIN_JACCARD_SUPPORTS: Final[float] = 0.5

# Minimum Jaccard for RELATES_TO: lower bar than SUPPORTS, catches
# beliefs about the same topic with different vocabulary.
_MIN_JACCARD_RELATES: Final[float] = 0.25

# Maximum candidates to check from FTS5 search.
_MAX_CANDIDATES: Final[int] = 10

# Maximum edges to create per new belief (avoid quadratic blowup).
_MAX_EDGES_PER_BELIEF: Final[int] = 3

# Minimum significant terms for eligibility.
_MIN_TERMS: Final[int] = 3

# Negation signals that suggest contradiction.
_NEGATION_PATTERNS: Final[list[re.Pattern[str]]] = [
    re.compile(r"\bnot\b", re.IGNORECASE),
    re.compile(r"\bno longer\b", re.IGNORECASE),
    re.compile(r"\binstead of\b", re.IGNORECASE),
    re.compile(r"\bdon'?t\b", re.IGNORECASE),
    re.compile(r"\bremoved\b", re.IGNORECASE),
    re.compile(r"\breplaced\b", re.IGNORECASE),
    re.compile(r"\bwrong\b", re.IGNORECASE),
    re.compile(r"\bincorrect\b", re.IGNORECASE),
    re.compile(r"\bnever\b", re.IGNORECASE),
    re.compile(r"\bshould not\b", re.IGNORECASE),
    re.compile(r"\bcannot\b", re.IGNORECASE),
    re.compile(r"\bwon'?t\b", re.IGNORECASE),
    re.compile(r"\bisn'?t\b", re.IGNORECASE),
    re.compile(r"\baren'?t\b", re.IGNORECASE),
    re.compile(r"\bwasn'?t\b", re.IGNORECASE),
    re.compile(r"\bweren'?t\b", re.IGNORECASE),
    re.compile(r"\bdoesn'?t\b", re.IGNORECASE),
    re.compile(r"\bdidn'?t\b", re.IGNORECASE),
]


@dataclass
class RelationshipResult:
    """Result of relationship detection for a single belief."""

    checked: bool = False
    edges_created: int = 0
    contradictions: int = 0
    supports: int = 0
    relates: int = 0
    details: list[str] = field(default_factory=lambda: list[str]())


def has_negation_signal(text: str) -> bool:
    """Check if text contains negation signals."""
    for pattern in _NEGATION_PATTERNS:
        if pattern.search(text):
            return True
    return False


def negation_divergence(text_a: str, text_b: str) -> bool:
    """Check if exactly one of two texts contains negation signals.

    If both have negation or neither has negation, they likely agree.
    If exactly one has negation on the same topic, they likely contradict.
    """
    neg_a: bool = has_negation_signal(text_a)
    neg_b: bool = has_negation_signal(text_b)
    return neg_a != neg_b


def detect_relationships(
    store: MemoryStore,
    new_belief: Belief,
    min_jaccard_contradicts: float = _MIN_JACCARD_CONTRADICTS,
    min_jaccard_supports: float = _MIN_JACCARD_SUPPORTS,
) -> RelationshipResult:
    """Detect CONTRADICTS and SUPPORTS relationships for a new belief.

    Searches for existing beliefs with high term overlap, then uses
    negation signals to distinguish contradiction from support.

    Does NOT create edges to/from locked beliefs (they are authoritative).

    Returns a RelationshipResult describing what edges were created.
    """
    result = RelationshipResult(checked=True)

    new_terms: set[str] = extract_terms(new_belief.content)
    if len(new_terms) < _MIN_TERMS:
        result.details.append("new belief too short for relationship check")
        return result

    # Search for candidates using the new belief's content as query
    candidates: list[Belief] = store.search(
        new_belief.content,
        top_k=_MAX_CANDIDATES,
    )

    for candidate in candidates:
        if result.edges_created >= _MAX_EDGES_PER_BELIEF:
            break

        # Skip self
        if candidate.id == new_belief.id:
            continue

        # Skip superseded
        if candidate.valid_to is not None or candidate.superseded_by is not None:
            continue

        # Skip locked beliefs -- they are authoritative, not contradictable
        if candidate.locked:
            continue

        # Check term overlap
        candidate_terms: set[str] = extract_terms(candidate.content)
        if len(candidate_terms) < _MIN_TERMS:
            continue

        jaccard: float = jaccard_similarity(new_terms, candidate_terms)

        # Check for contradiction: high overlap + negation divergence
        if jaccard >= min_jaccard_contradicts:
            if negation_divergence(new_belief.content, candidate.content):
                store.insert_edge(
                    from_id=new_belief.id,
                    to_id=candidate.id,
                    edge_type=EDGE_CONTRADICTS,
                    weight=jaccard,
                    reason=f"negation_divergence (jaccard={jaccard:.2f})",
                )
                result.edges_created += 1
                result.contradictions += 1
                result.details.append(
                    f"CONTRADICTS {candidate.id} (jaccard={jaccard:.2f})"
                )
                continue

        # Check for support: higher overlap + same type + no negation divergence
        if jaccard >= min_jaccard_supports:
            if candidate.belief_type == new_belief.belief_type:
                store.insert_edge(
                    from_id=new_belief.id,
                    to_id=candidate.id,
                    edge_type=EDGE_SUPPORTS,
                    weight=jaccard,
                    reason=f"topical_agreement (jaccard={jaccard:.2f})",
                )
                result.edges_created += 1
                result.supports += 1
                result.details.append(
                    f"SUPPORTS {candidate.id} (jaccard={jaccard:.2f})"
                )
                continue

        # Check for RELATES_TO: lower bar, cross-type allowed.
        # This creates the vocabulary bridges that HRR traverses.
        if jaccard >= _MIN_JACCARD_RELATES:
            store.insert_edge(
                from_id=new_belief.id,
                to_id=candidate.id,
                edge_type=EDGE_RELATES_TO,
                weight=jaccard,
                reason=f"entity_overlap (jaccard={jaccard:.2f})",
            )
            result.edges_created += 1
            result.relates += 1
            result.details.append(f"RELATES_TO {candidate.id} (jaccard={jaccard:.2f})")

    if result.edges_created == 0:
        result.details.append("no relationships detected")

    return result


# ---------------------------------------------------------------------------
# Gap closure detection: implementation events supersede gap beliefs
# ---------------------------------------------------------------------------

# Signals that a belief describes something as implemented/shipped/done.
_IMPLEMENTATION_PATTERNS: Final[list[re.Pattern[str]]] = [
    re.compile(r"\bimplemented\b", re.IGNORECASE),
    re.compile(r"\bshipped\b", re.IGNORECASE),
    re.compile(r"\bwired\b", re.IGNORECASE),
    re.compile(r"\bconfigured\b", re.IGNORECASE),
    re.compile(r"\bdeployed\b", re.IGNORECASE),
    re.compile(r"\bactive\b", re.IGNORECASE),
    re.compile(r"\brunning\b", re.IGNORECASE),
    re.compile(r"\bcomplete\b", re.IGNORECASE),
    re.compile(r"\bFEATURE IMPLEMENTED\b"),
    re.compile(r"\bcommit [0-9a-f]{7}", re.IGNORECASE),
]

# Signals that a belief describes a gap (something missing/not built).
_GAP_PATTERNS: Final[list[re.Pattern[str]]] = [
    re.compile(r"\bnot implemented\b", re.IGNORECASE),
    re.compile(r"\bnot built\b", re.IGNORECASE),
    re.compile(r"\bnot configured\b", re.IGNORECASE),
    re.compile(r"\bnot wired\b", re.IGNORECASE),
    re.compile(r"\bnot in settings\b", re.IGNORECASE),
    re.compile(r"\bno .{0,30}hook", re.IGNORECASE),
    re.compile(r"\bno .{0,30}configured\b", re.IGNORECASE),
    re.compile(r"\bno .{0,20}exists?\b", re.IGNORECASE),
    re.compile(r"\bnot yet built\b", re.IGNORECASE),
    re.compile(r"\bNOT YET BUILT\b"),
    re.compile(r"\bdoes not (?:exist|have|support)\b", re.IGNORECASE),
    re.compile(r"\bnothing (?:reads|ingests|processes)\b", re.IGNORECASE),
    re.compile(r"\bno (?:log rotation|awareness)\b", re.IGNORECASE),
    re.compile(r"\bnever runs\b", re.IGNORECASE),
]

# Minimum containment ratio for gap closure. Uses directional containment
# (what fraction of the gap belief's terms appear in the implementation
# belief) instead of Jaccard, because gap beliefs are short ("no hooks
# configured" = 2 topic terms) while implementation beliefs are long.
# Jaccard penalizes this asymmetry; containment does not.
_MIN_CONTAINMENT_GAP_CLOSURE: Final[float] = 0.5


def _has_implementation_signal(text: str) -> bool:
    """Check if text describes something as implemented/shipped."""
    count: int = 0
    for pattern in _IMPLEMENTATION_PATTERNS:
        if pattern.search(text):
            count += 1
            if count >= 2:
                return True
    return False


def _has_gap_signal(text: str) -> bool:
    """Check if text describes a gap (something missing/not built)."""
    for pattern in _GAP_PATTERNS:
        if pattern.search(text):
            return True
    return False


@dataclass
class GapClosureResult:
    """Result of gap closure detection."""

    checked: bool = False
    gaps_closed: int = 0
    details: list[str] = field(default_factory=lambda: list[str]())


def _containment(small: set[str], large: set[str]) -> float:
    """Fraction of small's terms that appear in large."""
    if not small:
        return 0.0
    return len(small & large) / len(small)


def detect_gap_closure(
    store: MemoryStore,
    new_belief: Belief,
    min_containment: float = _MIN_CONTAINMENT_GAP_CLOSURE,
) -> GapClosureResult:
    """Detect when a new implementation belief supersedes a stale gap belief.

    When a belief says "feature X is implemented" and an existing belief
    says "feature X is not implemented", the gap belief is superseded and
    an IMPLEMENTS edge is created.

    Uses directional containment (gap terms contained in impl terms)
    instead of Jaccard, because gap beliefs are typically short while
    implementation beliefs are detailed. A short gap belief like
    "no hooks configured" (2 topic terms) has Jaccard=0.12 against a
    long impl belief, but containment=1.0 since both topic terms appear.

    This prevents stale gap beliefs from misleading future sessions (CS-035).
    """
    result = GapClosureResult(checked=True)

    if not _has_implementation_signal(new_belief.content):
        result.details.append("new belief has no implementation signal")
        return result

    new_terms: set[str] = extract_terms(new_belief.content)
    if len(new_terms) < _MIN_TERMS:
        result.details.append("new belief too short for gap closure check")
        return result

    candidates: list[Belief] = store.search(
        new_belief.content,
        top_k=_MAX_CANDIDATES,
    )

    for candidate in candidates:
        if candidate.id == new_belief.id:
            continue
        if candidate.valid_to is not None or candidate.superseded_by is not None:
            continue
        if not _has_gap_signal(candidate.content):
            continue

        candidate_terms: set[str] = extract_terms(candidate.content)
        if len(candidate_terms) < _MIN_TERMS:
            continue

        # Directional: what fraction of the gap belief's terms appear
        # in the implementation belief?
        cont: float = _containment(candidate_terms, new_terms)
        if cont < min_containment:
            continue

        # Gap belief found with topic overlap -- supersede it
        store.supersede_belief(
            old_id=candidate.id,
            new_id=new_belief.id,
            reason="gap_closure",
        )
        store.insert_edge(
            from_id=new_belief.id,
            to_id=candidate.id,
            edge_type=EDGE_IMPLEMENTS,
            weight=cont,
            reason=f"gap_closure (containment={cont:.2f})",
        )
        result.gaps_closed += 1
        result.details.append(
            f"CLOSES_GAP {candidate.id} (containment={cont:.2f}): "
            f"{candidate.content[:80]}"
        )

    if result.gaps_closed == 0:
        result.details.append("no gap beliefs found to close")

    return result
