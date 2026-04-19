from __future__ import annotations

"""
Experiment 1: Zero-LLM Belief Extraction Pipeline

This is the extraction pipeline under test. It takes raw conversation text
and extracts beliefs using only regex patterns, keyword scoring, and
content classification. No LLM calls.

The experiment measures: what fraction of beliefs a human annotator would
extract does this pipeline actually catch?

Verifies: REQ-014 (recall >= 0.40, precision >= 0.50)
Protocol: EXPERIMENTS.md, Experiment 1
"""

import json
import re
import sys
from dataclasses import dataclass
from typing import Any


# --- Extracted Belief ---


@dataclass
class ExtractedBelief:
    content: str  # the claim
    belief_type: str  # factual, preference, procedural, causal, relational
    confidence: float  # extraction confidence [0, 1]
    source_pattern: str  # which pattern matched
    source_span: tuple[int, int] = (0, 0)  # character offsets in original text


# --- Classification Patterns ---

# --- Correction Detection (V2, tested on OVERRIDES.md: 92% on actual corrections) ---


def detect_correction(text: str) -> tuple[bool, list[str], float]:
    """Detect whether text is a user correction/directive.

    Returns (is_correction, signals, confidence).

    V1 (26% detection): only looked for negation.
    V2 (87% raw, 92% on actual corrections): adds imperative verbs, always/never,
    declarative overrides, emphasis, prior references, strong directives.

    Tested on 38 real overrides from project-a OVERRIDES.md.
    2 of 5 "misses" were actually not corrections (informational statements).
    """
    text_lower = text.lower().strip()
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

    is_correction = len(signals) >= 1
    confidence = min(1.0, len(signals) * 0.3)

    return is_correction, signals, confidence


DECISION_PATTERNS: list[tuple[str, str]] = [
    (
        r"(?:I|we|they|he|she)\s+(?:decided|chose|picked|selected|went with|settled on|switched to)\s+(.{5,80})",
        "factual",
    ),
    (
        r"(?:going to|will|shall)\s+(?:use|adopt|implement|switch to|go with)\s+(.{5,80})",
        "factual",
    ),
    (r"(?:let's|lets)\s+(?:use|go with|try|switch to)\s+(.{5,80})", "factual"),
    (r"(?:the decision is|we agreed)\s+(.{5,80})", "factual"),
]

PREFERENCE_PATTERNS: list[tuple[str, str]] = [
    (
        r"(?:I|we|they|he|she)\s+(?:prefer|like|want|love|always use|never use|hate)\s+(.{5,80})",
        "preference",
    ),
    (r"(?:I'd rather|I would rather)\s+(.{5,80})", "preference"),
    (
        r"(?:don't|do not|doesn't|does not)\s+(?:like|want|use|prefer)\s+(.{5,80})",
        "preference",
    ),
]

FACT_PATTERNS: list[tuple[str, str]] = [
    (
        r"(\w+(?:\s+\w+)?)\s+(?:is|are|was|were)\s+(?:a|an|the)?\s*(\w+(?:\s+\w+){0,5})",
        "factual",
    ),
    (
        r"(\w+(?:\s+\w+)?)\s+(?:uses?|runs? on|built with|depends on|requires?)\s+(.{5,60})",
        "relational",
    ),
    (
        r"(\w+(?:\s+\w+)?)\s+(?:works? at|lives? in|manages?|owns?|leads?)\s+(.{5,60})",
        "factual",
    ),
    (r"(?:the|our)\s+(\w+(?:\s+\w+)?)\s+(?:is|are)\s+(.{5,80})", "factual"),
]

ERROR_PATTERNS: list[tuple[str, str]] = [
    (
        r"(.{5,40})\s+(?:failed|errored|crashed|broke|doesn't work|didn't work|isn't working)",
        "procedural",
    ),
    (r"(?:error|bug|issue|problem)(?:\s+\w+){0,3}:\s*(.{5,80})", "procedural"),
    (r"(?:can't|cannot|couldn't|unable to)\s+(.{5,60})", "procedural"),
    (r"(.{5,40})\s+(?:because|due to|caused by)\s+(.{5,60})", "causal"),
]

PROCEDURE_PATTERNS: list[tuple[str, str]] = [
    (
        r"(?:to|in order to)\s+(\w+(?:\s+\w+){1,5}),?\s+(?:you need to|first|run|execute|install)\s+(.{5,80})",
        "procedural",
    ),
    (r"(?:step \d|first|then|next|finally|after that),?\s+(.{5,80})", "procedural"),
    (r"(?:make sure|ensure|remember to|don't forget to)\s+(.{5,80})", "procedural"),
    (
        r"(?:the way to|how to|the process for)\s+(\w+(?:\s+\w+){1,3})\s+(?:is|involves)\s+(.{5,80})",
        "procedural",
    ),
]


# --- Keyword Scoring for Classification ---

DECISION_KEYWORDS = {
    "decided",
    "chose",
    "picked",
    "selected",
    "settled",
    "agreed",
    "going with",
    "switched to",
    "will use",
    "adopted",
}
PREFERENCE_KEYWORDS = {
    "prefer",
    "like",
    "want",
    "love",
    "hate",
    "rather",
    "always",
    "never",
    "favorite",
    "don't like",
}
FACT_KEYWORDS = {
    "is",
    "are",
    "was",
    "uses",
    "runs",
    "built",
    "works",
    "has",
    "located",
    "version",
}
ERROR_KEYWORDS = {
    "error",
    "failed",
    "crash",
    "bug",
    "broken",
    "issue",
    "exception",
    "traceback",
    "doesn't work",
    "can't",
}
PROCEDURE_KEYWORDS = {
    "first",
    "then",
    "next",
    "step",
    "run",
    "install",
    "execute",
    "configure",
    "deploy",
    "make sure",
}


def classify_text(text: str) -> tuple[str, float]:
    """Classify text into a belief type via keyword scoring."""
    text_lower = text.lower()

    scores: dict[str, int] = {
        "decision": sum(1 for kw in DECISION_KEYWORDS if kw in text_lower),
        "preference": sum(1 for kw in PREFERENCE_KEYWORDS if kw in text_lower),
        "factual": sum(1 for kw in FACT_KEYWORDS if kw in text_lower),
        "error": sum(1 for kw in ERROR_KEYWORDS if kw in text_lower),
        "procedural": sum(1 for kw in PROCEDURE_KEYWORDS if kw in text_lower),
    }

    total = sum(scores.values())
    if total == 0:
        return "unstructured", 0.0

    best = max(scores, key=lambda k: scores[k])
    confidence = scores[best] / max(total, 1)

    # Map decision/error to belief types
    type_map: dict[str, str] = {"decision": "factual", "error": "procedural"}
    belief_type = type_map.get(best, best)

    return belief_type, confidence


# --- Extraction Pipeline ---


def extract_beliefs(text: str) -> list[ExtractedBelief]:
    """Extract beliefs from a single conversation turn."""
    beliefs: list[ExtractedBelief] = []
    seen_contents: set[str] = set()  # dedup within a single turn

    all_patterns: list[tuple[str, str]] = (
        DECISION_PATTERNS
        + PREFERENCE_PATTERNS
        + FACT_PATTERNS
        + ERROR_PATTERNS
        + PROCEDURE_PATTERNS
    )

    for pattern, belief_type in all_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            # Build the belief content from capture groups
            groups = [g for g in match.groups() if g]
            if not groups:
                continue

            content = " ".join(groups).strip()

            # Clean up
            content = re.sub(r"\s+", " ", content)
            content = content.rstrip(".,;:!?")

            # Skip very short or very long extractions
            if len(content) < 10 or len(content) > 200:
                continue

            # Skip if too generic (just common words)
            words = content.lower().split()
            stopwords = {
                "the",
                "a",
                "an",
                "is",
                "are",
                "was",
                "were",
                "it",
                "this",
                "that",
                "to",
                "for",
                "of",
                "in",
                "on",
                "with",
            }
            meaningful_words = [w for w in words if w not in stopwords and len(w) > 2]
            if len(meaningful_words) < 2:
                continue

            # Dedup
            content_key = content.lower()
            if content_key in seen_contents:
                continue
            seen_contents.add(content_key)

            # Compute confidence from classification score
            _, class_conf = classify_text(match.group(0))
            confidence = max(
                0.3, min(1.0, class_conf + 0.2)
            )  # floor at 0.3, boost by 0.2

            beliefs.append(
                ExtractedBelief(
                    content=content,
                    belief_type=belief_type,
                    confidence=confidence,
                    source_pattern=pattern[:50] + "..."
                    if len(pattern) > 50
                    else pattern,
                    source_span=(match.start(), match.end()),
                )
            )

    # Also try sentence-level classification for sentences not caught by patterns
    sentences = re.split(r"[.!?\n]+", text)
    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 15 or len(sent) > 300:
            continue

        btype, conf = classify_text(sent)
        if btype == "unstructured" or conf < 0.4:
            continue

        # Check if this sentence overlaps with an already-extracted belief
        sent_lower = sent.lower()
        already_covered = any(
            b.content.lower() in sent_lower or sent_lower in b.content.lower()
            for b in beliefs
        )
        if already_covered:
            continue

        content_key = sent.lower()
        if content_key in seen_contents:
            continue
        seen_contents.add(content_key)

        beliefs.append(
            ExtractedBelief(
                content=sent,
                belief_type=btype,
                confidence=conf,
                source_pattern="sentence_classification",
            )
        )

    return beliefs


# --- Sample Data for Testing ---

SAMPLE_TURNS: list[dict[str, str]] = [
    {
        "id": "turn_001",
        "speaker": "user",
        "text": "I decided to use PostgreSQL for the backend database because of its JSON support and we've been using it for years. Also, don't use MySQL -- I had terrible experiences with it at my last company.",
    },
    {
        "id": "turn_002",
        "speaker": "assistant",
        "text": "The deployment failed because the Docker image was built for arm64 but the server runs x86_64. To fix this, first rebuild with --platform linux/amd64, then push to the registry, and finally redeploy.",
    },
    {
        "id": "turn_003",
        "speaker": "user",
        "text": "We're going with React for the frontend. The team prefers TypeScript over JavaScript. Make sure all new components use functional style, not class components.",
    },
    {
        "id": "turn_004",
        "speaker": "user",
        "text": "John works at Anthropic on the API team. He manages the rate limiting service. The current rate limit is 1000 requests per minute for the pro tier.",
    },
    {
        "id": "turn_005",
        "speaker": "assistant",
        "text": "The test suite crashed with a segfault in the native module. This is likely caused by a memory corruption bug in the FFI bindings. I'd recommend switching to the pure Python implementation until we can debug the native code.",
    },
    {
        "id": "turn_006",
        "speaker": "user",
        "text": "Let's settle this -- we're using uv for package management, not pip or poetry. It's faster and I prefer the lockfile format. Also we always pin exact versions in production.",
    },
    {
        "id": "turn_007",
        "speaker": "user",
        "text": "Can you check on the PR? I think Sarah submitted it yesterday. The build pipeline uses GitHub Actions and deploys to AWS ECS. Oh and remember that staging uses a different database than production.",
    },
    {
        "id": "turn_008",
        "speaker": "assistant",
        "text": "I noticed the API response times have degraded since we added the caching layer. The p95 went from 120ms to 450ms. This might be because Redis is running on the same instance as the application server.",
    },
    {
        "id": "turn_009",
        "speaker": "user",
        "text": "For the new feature, I want the agent to remember conversations across sessions. The memory should persist even if the CLI crashes. Performance is important -- retrieval should take less than 500ms.",
    },
    {
        "id": "turn_010",
        "speaker": "user",
        "text": "Good morning. What were we working on yesterday? I think we were debugging the authentication flow but I'm not sure where we left off.",
    },
]


def run_on_samples() -> None:
    """Run extraction on sample data and print results for review."""
    print(f"Running extraction on {len(SAMPLE_TURNS)} sample turns\n", file=sys.stderr)

    all_results: list[dict[str, Any]] = []

    for turn in SAMPLE_TURNS:
        beliefs = extract_beliefs(turn["text"])
        result: dict[str, Any] = {
            "turn_id": turn["id"],
            "speaker": turn["speaker"],
            "text": turn["text"],
            "extracted_beliefs": [
                {
                    "content": b.content,
                    "type": b.belief_type,
                    "confidence": round(b.confidence, 2),
                    "pattern": b.source_pattern,
                }
                for b in beliefs
            ],
            "count": len(beliefs),
        }
        all_results.append(result)

        print(f"--- {turn['id']} ({turn['speaker']}) ---", file=sys.stderr)
        print(f"  Text: {turn['text'][:100]}...", file=sys.stderr)
        print(f"  Extracted {len(beliefs)} beliefs:", file=sys.stderr)
        for b in beliefs:
            print(
                f"    [{b.belief_type}] {b.content} (conf={b.confidence:.2f})",
                file=sys.stderr,
            )
        print(file=sys.stderr)

    # Summary stats
    total_beliefs = sum(r["count"] for r in all_results)
    turns_with_beliefs = sum(1 for r in all_results if r["count"] > 0)
    print(
        f"SUMMARY: {total_beliefs} beliefs from {len(all_results)} turns "
        f"({turns_with_beliefs} turns had extractions)",
        file=sys.stderr,
    )
    print(
        f"Average: {total_beliefs / len(all_results):.1f} beliefs per turn",
        file=sys.stderr,
    )

    print(json.dumps(all_results, indent=2))


if __name__ == "__main__":
    run_on_samples()
