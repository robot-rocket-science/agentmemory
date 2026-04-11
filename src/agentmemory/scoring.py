"""Temporal and confidence-aware scoring functions for belief retrieval.

Validated in Exp 57-60. Content-type decay half-lives from Exp 58c.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timezone

from agentmemory.models import Belief

# Content type to decay half-life in hours (from Exp 58c).
# None means the belief never decays (stays at 1.0 regardless of age).
DECAY_HALF_LIVES: dict[str, float | None] = {
    "factual": 336.0,        # 14 days
    "preference": None,       # never decays (usually locked)
    "correction": None,       # never decays (always locked)
    "requirement": None,      # never decays
    "procedural": 504.0,      # 21 days
    "causal": 720.0,          # 30 days
    "relational": 336.0,      # 14 days
}


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp. Returns a timezone-aware datetime."""
    dt: datetime = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def decay_factor(belief: Belief, current_time_iso: str) -> float:
    """Content-aware exponential decay.

    Locked beliefs return 1.0.
    Superseded beliefs (valid_to is set) return 0.01.
    Beliefs whose type has no half-life (None) return 1.0.
    All other beliefs decay as: 0.5 ^ (age_hours / half_life_hours).
    """
    if belief.superseded_by is not None or belief.valid_to is not None:
        return 0.01

    if belief.locked:
        return 1.0

    half_life: float | None = DECAY_HALF_LIVES.get(belief.belief_type)
    if half_life is None:
        return 1.0

    current: datetime = _parse_iso(current_time_iso)
    created: datetime = _parse_iso(belief.created_at)
    age_hours: float = (current - created).total_seconds() / 3600.0

    if age_hours <= 0.0:
        return 1.0

    return math.pow(0.5, age_hours / half_life)


def lock_boost_typed(belief: Belief, query_terms: list[str], boost: float = 2.0) -> float:
    """Boost locked beliefs that are topically relevant to the query.

    Relevance is determined by checking whether any query term appears in the
    belief content (case-insensitive substring match).

    Returns boost + decay_factor for relevant locked beliefs.
    Returns decay_factor for non-locked beliefs (boost is not applied).
    """
    # Superseded beliefs get no boost regardless of lock status.
    if belief.superseded_by is not None or belief.valid_to is not None:
        return 0.01

    if not belief.locked:
        return 1.0

    content_lower: str = belief.content.lower()
    is_relevant: bool = any(term.lower() in content_lower for term in query_terms if term)

    if is_relevant:
        return boost + 1.0  # boost applied on top of base 1.0
    return 1.0


def thompson_sample(alpha: float, beta_param: float) -> float:
    """Sample from Beta(alpha, beta_param) for Thompson sampling ranking."""
    return random.betavariate(alpha, beta_param)


# Core ranking weights (from CORE_RANKING.md, validated by Exp 38/61 research).
_TYPE_WEIGHTS: dict[str, float] = {
    "requirement": 2.5,
    "correction": 2.0,
    "preference": 1.8,
    "factual": 1.0,
    "procedural": 1.2,
    "causal": 1.3,
    "relational": 1.0,
}

_SOURCE_WEIGHTS: dict[str, float] = {
    "user_corrected": 1.5,
    "user_stated": 1.3,
    "document_recent": 1.0,
    "document_old": 0.8,
    "agent_inferred": 1.0,
}


def _length_multiplier(content: str) -> float:
    """Content length multiplier: penalize fragments, boost dense beliefs."""
    n: int = len(content)
    if n < 30:
        return 0.5
    if n < 100:
        return 1.0
    if n < 200:
        return 1.3
    return 1.6


def core_score(belief: Belief, current_time_iso: str | None = None) -> float:
    """Composite ranking score for /mem:core.

    Tier 1: type * source * length (works on flat data)
    Tier 2: decay factor from source dates (when available)
    Score range: ~0 (old superseded fragment) to ~6+ (recent long user-corrected requirement).
    """
    if belief.superseded_by is not None or belief.valid_to is not None:
        return 0.0

    type_w: float = _TYPE_WEIGHTS.get(belief.belief_type, 1.0)
    source_w: float = _SOURCE_WEIGHTS.get(belief.source_type, 1.0)
    length_w: float = _length_multiplier(belief.content)
    lock_w: float = 2.0 if belief.locked else 1.0

    # Tier 2: temporal decay (when timestamps have variance)
    decay_w: float = 1.0
    if current_time_iso is not None:
        decay_w = decay_factor(belief, current_time_iso)

    return type_w * source_w * length_w * lock_w * decay_w


def recency_boost(belief: Belief, current_time_iso: str, half_life_hours: float = 24.0) -> float:
    """Boost recently created beliefs so new information can surface.

    Exp 63 showed new beliefs cannot penetrate existing top-k at uniform
    confidence. This gives a multiplicative bonus to beliefs created within
    the last half_life_hours, tapering to 1.0 for older beliefs.

    Returns a value in [1.0, 2.0]: 2.0 for brand-new, 1.0 at +inf age.
    """
    current: datetime = _parse_iso(current_time_iso)
    created: datetime = _parse_iso(belief.created_at)
    age_hours: float = max(0.0, (current - created).total_seconds() / 3600.0)
    return 1.0 + math.pow(0.5, age_hours / half_life_hours)


def score_belief(belief: Belief, query: str, current_time_iso: str) -> float:
    """Combined scoring: type weight * source weight * decay * recency * lock boost * Thompson.

    Superseded beliefs always score 0.01.
    Locked beliefs: score = lock_boost_typed * thompson_sample (always elevated).
    Normal beliefs: score = type_w * source_w * recency * thompson_sample * decay.

    Incorporates type and source weights (previously only used by core_score)
    so that requirements/corrections rank above factual in retrieval, not just
    in the /mem:core display. Per Exp 62-64 findings.
    """
    if belief.superseded_by is not None or belief.valid_to is not None:
        return 0.01

    query_terms: list[str] = query.split()
    decay: float = decay_factor(belief, current_time_iso)
    boost: float = lock_boost_typed(belief, query_terms)
    sample: float = thompson_sample(belief.alpha, belief.beta_param)
    type_w: float = _TYPE_WEIGHTS.get(belief.belief_type, 1.0)
    source_w: float = _SOURCE_WEIGHTS.get(belief.source_type, 1.0)
    recency: float = recency_boost(belief, current_time_iso)

    if belief.locked:
        return boost * sample * type_w

    return sample * decay * type_w * source_w * recency
