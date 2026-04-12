"""LLM-based sentence classification for the agentmemory pipeline.

Implements the Exp 61 classification process: batch sentences to Haiku,
assign type-based Bayesian priors, return ClassifiedSentence objects.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from anthropic import Anthropic

from agentmemory.correction_detection import detect_correction

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Haiku model identifier (cheapest available, 99% accuracy per Exp 47/50)
_HAIKU_MODEL: str = "claude-haiku-4-5-20251001"

# Batch size for LLM classification calls
_BATCH_SIZE: int = 20

# Type-to-prior mapping from Exp 61.
# None means "don't store" (Coordination, Question, Meta).
TYPE_PRIORS: dict[str, tuple[float, float] | None] = {
    "REQUIREMENT":  (9.0, 0.5),   # 94.7% -- hard constraints
    "CORRECTION":   (9.0, 0.5),   # 94.7% -- user corrections
    "PREFERENCE":   (7.0, 1.0),   # 87.5% -- user preferences
    "FACT":         (3.0, 1.0),   # 75.0% -- stated facts
    "ASSUMPTION":   (2.0, 1.0),   # 66.7% -- taken as true without evidence
    "DECISION":     (5.0, 1.0),   # 83.3% -- choices made
    "ANALYSIS":     (2.0, 1.0),   # 66.7% -- derived conclusions
    "COORDINATION": None,
    "QUESTION":     None,
    "META":         None,
}

# Prompt template from Exp 61 Step 3.
_CLASSIFICATION_PROMPT: str = """You are classifying conversation sentences for a memory system.

For EACH sentence, classify on two dimensions:

1. persist: Should this be remembered across sessions?
   - PERSIST: Contains a decision, preference, correction, fact, or
     requirement that would be useful in a future session
   - EPHEMERAL: Only useful in the current moment (greetings, status
     updates, meta-commentary, coordination, questions, announcements)

2. type: What kind of information?
   - DECISION: A choice was made
   - PREFERENCE: A stated like/dislike/style preference
   - CORRECTION: Fixing something previously stated or done wrong
   - FACT: A stated truth about the project or world
   - REQUIREMENT: A constraint or rule that must be followed
   - ASSUMPTION: Something taken as true without firm evidence
   - ANALYSIS: Reasoning, explanation, or derived conclusion
   - QUESTION: Asking for information
   - COORDINATION: Control flow ("ok", "proceed", "next")
   - META: About the conversation process itself

Be conservative with PERSIST. When in doubt, mark EPHEMERAL.

Sentences:
{sentences}

Respond as JSON array: [{{"id": 1, "persist": "...", "type": "..."}}]"""

# Question prefixes for offline classification heuristic.
_QUESTION_PREFIXES: tuple[str, ...] = (
    "what ",
    "how ",
    "why ",
    "when ",
    "where ",
    "can ",
    "does ",
    "is there",
)


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class ClassifiedSentence:
    text: str
    source: str          # "user" or "assistant"
    persist: bool        # should this be stored?
    sentence_type: str   # REQUIREMENT, CORRECTION, FACT, etc.
    alpha: float         # Beta prior alpha
    beta_param: float    # Beta prior beta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_sentence_block(batch: list[tuple[str, str]]) -> str:
    """Format a batch of (text, source) tuples into the numbered prompt block."""
    lines: list[str] = []
    for i, (text, source) in enumerate(batch, start=1):
        lines.append(f'{i}. [{source}] "{text}"')
    return "\n".join(lines)


def _parse_llm_response(
    raw: str,
    batch: list[tuple[str, str]],
) -> list[ClassifiedSentence]:
    """Parse the JSON array from the LLM response into ClassifiedSentence objects."""
    # Extract JSON array from response (may have surrounding text)
    match: re.Match[str] | None = re.search(r"\[[\s\S]*\]", raw)
    if match is None:
        # Fallback: mark entire batch as EPHEMERAL ANALYSIS
        return _fallback_batch(batch)

    items: list[dict[str, str]] = json.loads(match.group())
    results: list[ClassifiedSentence] = []

    for item in items:
        idx: int = int(item.get("id", 0)) - 1
        if idx < 0 or idx >= len(batch):
            continue
        text, source = batch[idx]
        persist_label: str = item.get("persist", "EPHEMERAL")
        sentence_type: str = item.get("type", "ANALYSIS").upper()

        prior: tuple[float, float] | None = TYPE_PRIORS.get(sentence_type)
        should_persist: bool = persist_label == "PERSIST" and prior is not None
        alpha: float
        beta_val: float
        if prior is not None:
            alpha, beta_val = prior
        else:
            alpha, beta_val = 2.0, 1.0

        results.append(
            ClassifiedSentence(
                text=text,
                source=source,
                persist=should_persist,
                sentence_type=sentence_type,
                alpha=alpha,
                beta_param=beta_val,
            )
        )

    return results


def _fallback_batch(batch: list[tuple[str, str]]) -> list[ClassifiedSentence]:
    """Return EPHEMERAL ANALYSIS for every sentence in the batch."""
    results: list[ClassifiedSentence] = []
    for text, source in batch:
        results.append(
            ClassifiedSentence(
                text=text,
                source=source,
                persist=False,
                sentence_type="ANALYSIS",
                alpha=2.0,
                beta_param=1.0,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_sentences(
    sentences: list[tuple[str, str]],
    client: Anthropic | None = None,
) -> list[ClassifiedSentence]:
    """Classify sentences using Haiku in batches of 20.

    Each sentence is a (text, source) tuple where source is 'user' or 'assistant'.

    Uses the prompt template from Exp 61:
    - Classify each sentence on persist (PERSIST/EPHEMERAL) and type
    - Conservative: when in doubt, EPHEMERAL

    Returns ClassifiedSentence with prior assigned from TYPE_PRIORS.
    Sentences classified as COORDINATION/QUESTION/META get persist=False.

    If client is None, creates one. Uses claude-haiku-4-5-20251001 model.
    """
    if client is None:
        client = Anthropic()

    results: list[ClassifiedSentence] = []

    for batch_start in range(0, len(sentences), _BATCH_SIZE):
        batch: list[tuple[str, str]] = sentences[batch_start : batch_start + _BATCH_SIZE]
        sentence_block: str = _build_sentence_block(batch)
        prompt: str = _CLASSIFICATION_PROMPT.format(sentences=sentence_block)

        response = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        raw: str = ""
        for block in response.content:
            if block.type == "text":
                raw = block.text
                break

        batch_results: list[ClassifiedSentence] = _parse_llm_response(raw, batch)
        results.extend(batch_results)

    return results


def classify_sentences_offline(
    sentences: list[tuple[str, str]],
) -> list[ClassifiedSentence]:
    """Zero-LLM fallback classification using the correction detector + keyword heuristics.

    Lower accuracy (36% vs 99% LLM) but works offline.
    Uses detect_correction for corrections, keyword scoring for other types.
    All classified sentences get persist=True (conservative, let feedback sort later)
    except obvious questions (starts with 'what/how/why/when/where/can/does/is there').
    """
    results: list[ClassifiedSentence] = []

    for text, source in sentences:
        text_lower: str = text.lower().strip()

        # Questions: obvious non-persist
        if text_lower.startswith(_QUESTION_PREFIXES) and text_lower.endswith("?"):
            results.append(
                ClassifiedSentence(
                    text=text,
                    source=source,
                    persist=False,
                    sentence_type="QUESTION",
                    alpha=2.0,
                    beta_param=1.0,
                )
            )
            continue

        # Keyword heuristics take priority over the correction detector so that
        # sentences like "all code must use strict typing" are REQUIREMENT, not
        # CORRECTION (the correction detector fires on "must" via directive signal).
        sentence_type: str
        alpha: float
        beta_val: float

        if any(
            kw in text_lower
            for kw in [
                "must",
                "require",
                "mandatory",
                "hard cap",
                "constraint",
                "hard rule",
            ]
        ):
            sentence_type = "REQUIREMENT"
            _req_prior = TYPE_PRIORS["REQUIREMENT"]
            assert _req_prior is not None
            alpha, beta_val = _req_prior
            results.append(
                ClassifiedSentence(
                    text=text,
                    source=source,
                    persist=True,
                    sentence_type=sentence_type,
                    alpha=alpha,
                    beta_param=beta_val,
                )
            )
            continue

        # Correction detector (runs after requirement check to avoid false positives
        # from directive keywords like "must" that also appear in requirements)
        is_correction, _signals, _conf = detect_correction(text)
        if is_correction:
            _cor_prior = TYPE_PRIORS["CORRECTION"]
            assert _cor_prior is not None
            results.append(
                ClassifiedSentence(
                    text=text,
                    source=source,
                    persist=True,
                    sentence_type="CORRECTION",
                    alpha=_cor_prior[0],
                    beta_param=_cor_prior[1],
                )
            )
            continue

        # Keyword heuristics for remaining types
        if any(
            kw in text_lower
            for kw in [
                "prefer",
                "like",
                "want",
                "hate",
                "always use",
                "never use",
                "favorite",
            ]
        ):
            sentence_type = "PREFERENCE"
            _pref_prior = TYPE_PRIORS["PREFERENCE"]
            assert _pref_prior is not None
            alpha, beta_val = _pref_prior
        elif any(
            kw in text_lower
            for kw in [
                "decided",
                "chose",
                "picked",
                "selected",
                "going with",
                "switched to",
                "will use",
            ]
        ):
            sentence_type = "DECISION"
            _dec_prior = TYPE_PRIORS["DECISION"]
            assert _dec_prior is not None
            alpha, beta_val = _dec_prior
        elif any(
            kw in text_lower
            for kw in ["assume", "assuming", "i think", "probably", "likely"]
        ):
            sentence_type = "ASSUMPTION"
            _asm_prior = TYPE_PRIORS["ASSUMPTION"]
            assert _asm_prior is not None
            alpha, beta_val = _asm_prior
        elif any(
            kw in text_lower
            for kw in ["because", "therefore", "causes", "results in", "analysis"]
        ):
            sentence_type = "ANALYSIS"
            _ana_prior = TYPE_PRIORS["ANALYSIS"]
            assert _ana_prior is not None
            alpha, beta_val = _ana_prior
        else:
            # Default: FACT
            sentence_type = "FACT"
            _fact_prior = TYPE_PRIORS["FACT"]
            assert _fact_prior is not None
            alpha, beta_val = _fact_prior

        results.append(
            ClassifiedSentence(
                text=text,
                source=source,
                persist=True,
                sentence_type=sentence_type,
                alpha=alpha,
                beta_param=beta_val,
            )
        )

    return results
