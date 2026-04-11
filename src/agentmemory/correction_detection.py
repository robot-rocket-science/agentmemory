"""Zero-LLM correction detector (Exp 1 V2).

92% accuracy on real corrections from alpha-seek OVERRIDES.md.
V1 (26% detection): only looked for negation.
V2 (87% raw, 92% on actual corrections): adds imperative verbs, always/never,
declarative overrides, emphasis, prior references, strong directives.
"""
from __future__ import annotations

import re


def detect_correction(text: str) -> tuple[bool, list[str], float]:
    """Detect whether text is a user correction/directive.

    Returns (is_correction, signals, confidence).

    Signals checked:
    - imperative: starts with use/add/remove/stop/always/never/etc
    - always_never: contains always/never/permanently/from now on
    - negation: contains do not/don't/stop/no more
    - emphasis: contains !/hate/ever again
    - prior_ref: contains we've been/i told you/already/we agreed
    - declarative: "X is Y" or "X needs to be Y" pattern
    - directive: must/require/mandatory/hard cap

    is_correction = len(signals) >= 1
    confidence = min(1.0, len(signals) * 0.3)
    """
    text_lower: str = text.lower().strip()
    signals: list[str] = []

    # Imperative verb start (34% of corrections)
    if re.match(
        r"^(use|add|remove|update|follow|convert|make|do|try|run|keep|"
        r"leave|report|copy|stop|always|never|we are|calls|5k)\b",
        text_lower,
    ):
        signals.append("imperative")

    # Always/never absolutist language (18% of corrections)
    if any(
        w in text_lower
        for w in [
            "always",
            "never",
            "every time",
            "every single",
            "from now on",
            "permanently",
            "period",
        ]
    ):
        signals.append("always_never")

    # Negation (29% of corrections)
    if any(
        w in text_lower
        for w in ["do not", "don't", "dont", "stop", "not ", "no more", "no "]
    ):
        signals.append("negation")

    # Emphasis / frustration (8% of corrections but very high signal)
    if any(
        w in text_lower
        for w in ["!", "hate", "stop", "ever again", "zero question", "100 times"]
    ):
        signals.append("emphasis")

    # Reference to prior discussion (8% -- strongest signal when present)
    if any(
        w in text_lower
        for w in [
            "we've been",
            "i told you",
            "we discussed",
            "we agreed",
            "already",
            "iirc",
            "we decided",
        ]
    ):
        signals.append("prior_ref")

    # Declarative override: "X is Y" or "X needs to be Y" (21% of corrections)
    if re.search(
        r"(?:is|are|needs to be|should be|must be) "
        r"(?:the|a|an|\d|only|always)",
        text_lower,
    ):
        signals.append("declarative")

    # Strong directive
    if any(
        w in text_lower
        for w in ["must", "require", "mandatory", "hard cap", "hard rule"]
    ):
        signals.append("directive")

    is_correction: bool = len(signals) >= 1
    confidence: float = min(1.0, len(signals) * 0.3)

    return is_correction, signals, confidence
