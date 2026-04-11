"""Type-aware belief compression for context injection.

Token savings validated at ~55% in Exp 42. Dense types (factual, correction,
requirement, preference) are kept in full. Procedural beliefs are trimmed to
the first sentence plus key terms. Causal and relational beliefs are trimmed
to the first sentence.
"""
from __future__ import annotations

from agentmemory.models import Belief

# Types that are kept verbatim because their density makes truncation lossy.
_FULL_TEXT_TYPES: frozenset[str] = frozenset(
    {"factual", "requirement", "correction", "preference"}
)

# Types compressed to the first sentence only.
_FIRST_SENTENCE_TYPES: frozenset[str] = frozenset({"causal", "relational"})


def estimate_tokens(text: str) -> int:
    """Rough token estimate: len(text) // 4."""
    return len(text) // 4


def _first_sentence(text: str) -> str:
    """Return text up to and including the first sentence-ending punctuation."""
    for i, ch in enumerate(text):
        if ch in ".!?":
            return text[: i + 1].strip()
    # No sentence boundary found; return the whole text.
    return text.strip()


def _extract_key_terms(text: str) -> str:
    """Extract capitalized words and quoted phrases as rough key terms."""
    words: list[str] = text.split()
    key_terms: list[str] = [
        w.strip("\"',;:()[]") for w in words
        if w and (w[0].isupper() or w.startswith('"') or len(w) > 8)
    ]
    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for term in key_terms:
        if term and term not in seen:
            seen.add(term)
            unique.append(term)
    return " ".join(unique[:10])  # cap at 10 key terms


def compress_belief(belief: Belief) -> str:
    """Type-aware compression for context injection.

    - factual / requirement / correction / preference: full text
    - procedural: first sentence + key terms from the remainder
    - causal / relational: first sentence only
    """
    content: str = belief.content.strip()

    if belief.belief_type in _FULL_TEXT_TYPES:
        return content

    if belief.belief_type in _FIRST_SENTENCE_TYPES:
        return _first_sentence(content)

    if belief.belief_type == "procedural":
        sentence: str = _first_sentence(content)
        remainder: str = content[len(sentence):].strip()
        if remainder:
            key_terms: str = _extract_key_terms(remainder)
            if key_terms:
                return f"{sentence} [{key_terms}]"
        return sentence

    # Unknown type: return full text to avoid silent data loss.
    return content


def pack_beliefs(beliefs: list[Belief], budget_tokens: int = 2000) -> list[Belief]:
    """Pack beliefs into a token budget.

    Takes a pre-scored, pre-sorted list of beliefs. Adds beliefs in order until
    the budget is exhausted. Returns the subset that fits within budget_tokens.
    """
    packed: list[Belief] = []
    remaining: int = budget_tokens

    for belief in beliefs:
        compressed: str = compress_belief(belief)
        cost: int = estimate_tokens(compressed)
        if cost > remaining:
            break
        packed.append(belief)
        remaining -= cost

    return packed
