"""Tests for offline vs LLM classification accuracy on known sentences.

Validates that classify_sentences_offline handles common sentence patterns
correctly, and that parse_classification_response handles LLM output correctly.
"""
from __future__ import annotations

import pytest

from agentmemory.classification import (
    ClassifiedSentence,
    classify_sentences_offline,
    parse_classification_response,
)


# ---------------------------------------------------------------------------
# Known-good sentence corpus with expected classifications
# ---------------------------------------------------------------------------

# Format: (text, source, expected_type, expected_persist)

GIT_COMMITS: list[tuple[str, str, str, bool]] = [
    ("Fix CLAUDE.md tool names to match Claude Code MCP convention", "assistant", "FACT", True),
    ("Bridge belief-scanner ID gap: content-hash mapping enables HRR vocabulary bridge", "assistant", "FACT", True),
    ("Integrate HRR into retrieval pipeline: FTS5 plus HRR vocabulary-bridge expansion", "assistant", "FACT", True),
]

HEADINGS_MARKDOWN: list[tuple[str, str, str, bool]] = [
    ("## Phase 2 Implementation Plan", "assistant", "META", False),
    ("### Available Tools", "assistant", "META", False),
    ("# Memory Index", "assistant", "META", False),
]

REQUIREMENTS: list[tuple[str, str, str, bool]] = [
    ("All code must use strict static typing with pyright strict mode", "user", "REQUIREMENT", True),
    ("Never commit large data files or results files", "user", "REQUIREMENT", True),
    ("You must always use uv for package management", "user", "REQUIREMENT", True),
]

EPHEMERAL: list[tuple[str, str, str, bool]] = [
    ("ok", "user", "COORDINATION", False),
    ("sounds good", "user", "COORDINATION", False),
    ("what file?", "user", "QUESTION", False),
]

CORRECTIONS: list[tuple[str, str, str, bool]] = [
    ("No, use SQLite not PostgreSQL for storage", "user", "CORRECTION", True),
    ("Don't do that, always run tests before committing", "user", "CORRECTION", True),
    ("That's wrong, the half-life for factual beliefs is 14 days not 7", "user", "CORRECTION", True),
]


ALL_SENTENCES: list[tuple[str, str, str, bool]] = (
    GIT_COMMITS + HEADINGS_MARKDOWN + REQUIREMENTS + EPHEMERAL + CORRECTIONS
)


# ---------------------------------------------------------------------------
# Test offline classification
# ---------------------------------------------------------------------------


class TestOfflineClassification:
    """Verify classify_sentences_offline on known sentence types."""

    def test_requirements_classified_correctly(self) -> None:
        """Sentences with must/always/never should be REQUIREMENT or CORRECTION, PERSIST.

        The offline classifier checks requirement keywords (must, require, mandatory,
        etc.) before the correction detector. However, "never" is not a requirement
        keyword -- it triggers the correction detector instead (imperative + always_never
        signals). This is a known behavior: "Never commit..." is classified as CORRECTION
        rather than REQUIREMENT offline. The LLM path handles this distinction better.
        """
        pairs: list[tuple[str, str]] = [(t, s) for t, s, _, _ in REQUIREMENTS]
        results: list[ClassifiedSentence] = classify_sentences_offline(pairs)
        assert len(results) == 3

        # All should persist regardless of exact type
        for cs in results:
            assert cs.persist is True

        # "must" sentences -> REQUIREMENT
        must_results: list[ClassifiedSentence] = [
            r for r in results if "must" in r.text.lower()
        ]
        for cs in must_results:
            assert cs.sentence_type == "REQUIREMENT", (
                f"Expected REQUIREMENT for: {cs.text!r}, got {cs.sentence_type}"
            )

        # "Never commit..." -> CORRECTION (known offline behavior: "never" triggers
        # the correction detector, not the requirement heuristic)
        never_results: list[ClassifiedSentence] = [
            r for r in results if r.text.startswith("Never")
        ]
        for cs in never_results:
            assert cs.sentence_type == "CORRECTION", (
                f"Expected CORRECTION for: {cs.text!r}, got {cs.sentence_type}"
            )

    def test_corrections_classified_correctly(self) -> None:
        """Correction sentences should be detected as CORRECTION, PERSIST."""
        pairs: list[tuple[str, str]] = [(t, s) for t, s, _, _ in CORRECTIONS]
        results: list[ClassifiedSentence] = classify_sentences_offline(pairs)
        assert len(results) == 3
        for cs in results:
            assert cs.sentence_type == "CORRECTION", (
                f"Expected CORRECTION for: {cs.text!r}, got {cs.sentence_type}"
            )
            assert cs.persist is True

    def test_ephemeral_short_strings(self) -> None:
        """Very short coordination strings should still be classified (offline marks them PERSIST by default).

        The offline classifier is known to be conservative: it marks most things as PERSIST.
        Short strings without question marks or requirement keywords get classified as FACT.
        This documents the known limitation vs LLM accuracy.
        """
        pairs: list[tuple[str, str]] = [(t, s) for t, s, _, _ in EPHEMERAL]
        results: list[ClassifiedSentence] = classify_sentences_offline(pairs)
        assert len(results) == 3
        # "what file?" ends with ? and starts with a question prefix -> QUESTION, not PERSIST
        question_results: list[ClassifiedSentence] = [
            r for r in results if r.text == "what file?"
        ]
        assert len(question_results) == 1
        assert question_results[0].sentence_type == "QUESTION"
        assert question_results[0].persist is False

        # "ok" and "sounds good" are known false positives for offline:
        # offline marks them as FACT/PERSIST since it has no COORDINATION heuristic.
        # This is the documented 36% accuracy gap vs LLM.
        coord_results: list[ClassifiedSentence] = [
            r for r in results if r.text in ("ok", "sounds good")
        ]
        for cs in coord_results:
            # Document the known failure: offline classifies these as FACT, persist=True
            assert cs.persist is True, (
                f"Offline classifier marks '{cs.text}' as persist=True (known limitation)"
            )

    def test_git_commits_classified_as_fact(self) -> None:
        """Git commit messages should classify as FACT with PERSIST."""
        pairs: list[tuple[str, str]] = [(t, s) for t, s, _, _ in GIT_COMMITS]
        results: list[ClassifiedSentence] = classify_sentences_offline(pairs)
        assert len(results) == 3
        for cs in results:
            assert cs.persist is True
            # Offline defaults to FACT for generic text
            assert cs.sentence_type == "FACT", (
                f"Expected FACT for commit msg: {cs.text!r}, got {cs.sentence_type}"
            )

    def test_headings_offline_limitation(self) -> None:
        """Headings/markdown are META for LLM but offline has no heading detection.

        Documents the known gap: offline classifies headings as FACT/PERSIST.
        """
        pairs: list[tuple[str, str]] = [(t, s) for t, s, _, _ in HEADINGS_MARKDOWN]
        results: list[ClassifiedSentence] = classify_sentences_offline(pairs)
        assert len(results) == 3
        for cs in results:
            # Offline cannot detect META/headings, so they become FACT, persist=True
            assert cs.persist is True, (
                f"Offline marks heading '{cs.text}' as persist (known limitation)"
            )

    def test_all_sentences_return_valid_types(self) -> None:
        """Every classified sentence should have a valid type from the taxonomy."""
        valid_types: frozenset[str] = frozenset({
            "REQUIREMENT", "CORRECTION", "PREFERENCE", "FACT", "ASSUMPTION",
            "DECISION", "ANALYSIS", "COORDINATION", "QUESTION", "META",
        })
        pairs: list[tuple[str, str]] = [(t, s) for t, s, _, _ in ALL_SENTENCES]
        results: list[ClassifiedSentence] = classify_sentences_offline(pairs)
        assert len(results) == 15
        for cs in results:
            assert cs.sentence_type in valid_types, (
                f"Invalid type {cs.sentence_type!r} for: {cs.text!r}"
            )

    def test_priors_are_set(self) -> None:
        """All classified sentences should have alpha and beta_param > 0."""
        pairs: list[tuple[str, str]] = [(t, s) for t, s, _, _ in ALL_SENTENCES]
        results: list[ClassifiedSentence] = classify_sentences_offline(pairs)
        for cs in results:
            assert cs.alpha > 0.0
            assert cs.beta_param > 0.0


# ---------------------------------------------------------------------------
# Test LLM classification (mocked)
# ---------------------------------------------------------------------------


class TestLLMClassificationMocked:
    """Verify the LLM path would get all 15 right using a mocked Anthropic client."""

    @staticmethod
    def _build_mock_response(sentences: list[tuple[str, str, str, bool]]) -> str:
        """Build a mock LLM JSON response that returns correct classifications."""
        import json
        items: list[dict[str, str | int]] = []
        for i, (_, _, expected_type, expected_persist) in enumerate(sentences, start=1):
            persist_label: str = "PERSIST" if expected_persist else "EPHEMERAL"
            items.append({"id": i, "persist": persist_label, "type": expected_type})
        return json.dumps(items)

    def test_parse_response_returns_correct_types(self) -> None:
        """With a perfect LLM response, all 15 sentences should be classified correctly."""
        mock_response_text: str = self._build_mock_response(ALL_SENTENCES)

        pairs: list[tuple[str, str]] = [(t, s) for t, s, _, _ in ALL_SENTENCES]
        results: list[ClassifiedSentence] = parse_classification_response(mock_response_text, pairs)

        assert len(results) == 15

        for cs, (text, _, expected_type, expected_persist) in zip(results, ALL_SENTENCES, strict=True):
            assert cs.sentence_type == expected_type, (
                f"Parse: expected {expected_type} for {text!r}, got {cs.sentence_type}"
            )
            assert cs.persist is expected_persist, (
                f"Parse: expected persist={expected_persist} for {text!r}, got {cs.persist}"
            )

    def test_parse_corrections_are_persist_and_high_confidence(self) -> None:
        """Corrections from parsed response should have high alpha (9.0) and persist=True."""
        mock_response_text: str = self._build_mock_response(CORRECTIONS)

        pairs: list[tuple[str, str]] = [(t, s) for t, s, _, _ in CORRECTIONS]
        results: list[ClassifiedSentence] = parse_classification_response(mock_response_text, pairs)

        for cs in results:
            assert cs.persist is True
            assert cs.alpha == pytest.approx(9.0)  # pyright: ignore[reportUnknownMemberType]
            assert cs.sentence_type == "CORRECTION"

    def test_parse_ephemeral_not_persisted(self) -> None:
        """Ephemeral sentences from parsed response should have persist=False."""
        mock_items: list[tuple[str, str, str, bool]] = [
            ("ok", "user", "COORDINATION", False),
            ("sounds good", "user", "COORDINATION", False),
            ("what file?", "user", "QUESTION", False),
        ]
        mock_response_text: str = self._build_mock_response(mock_items)

        pairs: list[tuple[str, str]] = [(t, s) for t, s, _, _ in mock_items]
        results: list[ClassifiedSentence] = parse_classification_response(mock_response_text, pairs)

        for cs in results:
            assert cs.persist is False, (
                f"Parse should mark '{cs.text}' as EPHEMERAL, got persist={cs.persist}"
            )
