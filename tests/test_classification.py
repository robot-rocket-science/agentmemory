"""Unit tests for agentmemory.classification module."""

from __future__ import annotations

import pytest

from agentmemory.classification import (
    BATCH_SIZE,
    TYPE_PRIORS,
    ClassifiedSentence,
    classify_sentences_offline,
)


# ---------------------------------------------------------------------------
# ClassifiedSentence dataclass
# ---------------------------------------------------------------------------


class TestClassifiedSentenceFields:
    """ClassifiedSentence has expected fields with correct defaults."""

    def test_required_fields(self) -> None:
        cs = ClassifiedSentence(
            text="hello",
            source="user",
            persist=True,
            sentence_type="FACT",
            alpha=3.0,
            beta_param=1.0,
        )
        assert cs.text == "hello"
        assert cs.source == "user"
        assert cs.persist is True
        assert cs.sentence_type == "FACT"
        assert cs.alpha == 3.0
        assert cs.beta_param == 1.0

    def test_author_defaults_empty(self) -> None:
        cs = ClassifiedSentence(
            text="x",
            source="user",
            persist=False,
            sentence_type="ANALYSIS",
            alpha=2.0,
            beta_param=1.0,
        )
        assert cs.author == ""

    def test_author_can_be_set(self) -> None:
        cs = ClassifiedSentence(
            text="x",
            source="user",
            persist=False,
            sentence_type="ANALYSIS",
            alpha=2.0,
            beta_param=1.0,
            author="USER",
        )
        assert cs.author == "USER"


# ---------------------------------------------------------------------------
# TYPE_PRIORS validation
# ---------------------------------------------------------------------------


class TestTypePriors:
    """TYPE_PRIORS values are reasonable."""

    def test_requirement_higher_than_assumption(self) -> None:
        req = TYPE_PRIORS["REQUIREMENT"]
        asm = TYPE_PRIORS["ASSUMPTION"]
        assert req is not None
        assert asm is not None
        # Requirement alpha should be higher (stronger prior).
        assert req[0] > asm[0]

    def test_correction_higher_than_assumption(self) -> None:
        cor = TYPE_PRIORS["CORRECTION"]
        asm = TYPE_PRIORS["ASSUMPTION"]
        assert cor is not None
        assert asm is not None
        assert cor[0] > asm[0]

    def test_ephemeral_types_are_none(self) -> None:
        for key in ("COORDINATION", "QUESTION", "META"):
            assert TYPE_PRIORS[key] is None

    def test_all_persist_types_have_positive_priors(self) -> None:
        for key, val in TYPE_PRIORS.items():
            if val is not None:
                alpha, beta_val = val
                assert alpha > 0, f"{key} alpha must be positive"
                assert beta_val > 0, f"{key} beta must be positive"

    def test_batch_size_is_positive(self) -> None:
        assert BATCH_SIZE > 0


# ---------------------------------------------------------------------------
# classify_sentences_offline -- requirements
# ---------------------------------------------------------------------------


class TestClassifyRequirements:
    """Requirements with directive keywords are classified correctly."""

    @pytest.mark.parametrize(
        "text",
        [
            "All code must use strict typing",
            "This is a mandatory requirement for deployment",
            "There is a hard cap on memory usage",
            "This constraint applies to all modules",
        ],
    )
    def test_user_requirement_keywords(self, text: str) -> None:
        results = classify_sentences_offline([(text, "user")])
        assert len(results) == 1
        r = results[0]
        assert r.sentence_type == "REQUIREMENT"
        assert r.persist is True
        req_prior = TYPE_PRIORS["REQUIREMENT"]
        assert req_prior is not None
        assert r.alpha == req_prior[0]
        assert r.beta_param == req_prior[1]

    def test_directive_source_also_triggers_requirement(self) -> None:
        results = classify_sentences_offline(
            [("All tests must pass before merge", "directive")]
        )
        assert results[0].sentence_type == "REQUIREMENT"

    def test_non_user_source_skips_requirement_keywords(self) -> None:
        """Document text with 'must' should NOT be classified as REQUIREMENT."""
        results = classify_sentences_offline(
            [("The system must handle errors gracefully", "document")]
        )
        assert results[0].sentence_type != "REQUIREMENT"


# ---------------------------------------------------------------------------
# classify_sentences_offline -- corrections
# ---------------------------------------------------------------------------


class TestClassifyCorrections:
    """Correction detection works for user source."""

    @pytest.mark.parametrize(
        "text",
        [
            "no, use X not Y",
            "don't do that ever again",
            "stop using the old API",
        ],
    )
    def test_user_corrections(self, text: str) -> None:
        results = classify_sentences_offline([(text, "user")])
        assert len(results) == 1
        r = results[0]
        assert r.sentence_type == "CORRECTION"
        assert r.persist is True

    def test_correction_not_triggered_for_non_user_source(self) -> None:
        """Non-user sources should skip the correction detector."""
        results = classify_sentences_offline([("no, use X not Y", "document")])
        # Should fall through to keyword heuristics, not CORRECTION.
        assert results[0].sentence_type != "CORRECTION"


# ---------------------------------------------------------------------------
# classify_sentences_offline -- factual statements
# ---------------------------------------------------------------------------


class TestClassifyFacts:
    """Statements without special keywords default to FACT."""

    @pytest.mark.parametrize(
        "text",
        [
            "The database runs on PostgreSQL",
            "We deployed to AWS last Tuesday",
            "The server listens on port 8080",
        ],
    )
    def test_plain_statements_are_fact(self, text: str) -> None:
        results = classify_sentences_offline([(text, "user")])
        assert len(results) == 1
        r = results[0]
        assert r.sentence_type == "FACT"
        assert r.persist is True
        fact_prior = TYPE_PRIORS["FACT"]
        assert fact_prior is not None
        assert r.alpha == fact_prior[0]
        assert r.beta_param == fact_prior[1]


# ---------------------------------------------------------------------------
# classify_sentences_offline -- questions (ephemeral)
# ---------------------------------------------------------------------------


class TestClassifyQuestions:
    """Questions starting with known prefixes and ending with ? are QUESTION."""

    @pytest.mark.parametrize(
        "text",
        [
            "What is the deployment target?",
            "How does the pipeline work?",
            "Why did the tests fail?",
            "Where is the config file?",
            "Can we use Redis instead?",
            "Does this support Python 3.11?",
            "Is there a migration guide?",
        ],
    )
    def test_questions_are_ephemeral(self, text: str) -> None:
        results = classify_sentences_offline([(text, "user")])
        assert len(results) == 1
        r = results[0]
        assert r.sentence_type == "QUESTION"
        assert r.persist is False

    def test_question_prefix_without_question_mark_is_not_question(self) -> None:
        """A sentence starting with 'what' but no '?' is not classified as QUESTION."""
        results = classify_sentences_offline(
            [("What we need is a better pipeline", "user")]
        )
        assert results[0].sentence_type != "QUESTION"


# ---------------------------------------------------------------------------
# classify_sentences_offline -- other keyword types
# ---------------------------------------------------------------------------


class TestClassifyKeywordTypes:
    """Keyword heuristics for preference, decision, assumption, analysis."""

    def test_preference_keywords(self) -> None:
        results = classify_sentences_offline([("I prefer tabs over spaces", "user")])
        assert results[0].sentence_type == "PREFERENCE"
        assert results[0].persist is True

    def test_decision_keywords(self) -> None:
        results = classify_sentences_offline(
            [("The team chose FastAPI for this", "user")]
        )
        assert results[0].sentence_type == "DECISION"
        assert results[0].persist is True

    def test_assumption_keywords(self) -> None:
        results = classify_sentences_offline(
            [("I think the latency is under 100ms", "user")]
        )
        assert results[0].sentence_type == "ASSUMPTION"
        assert results[0].persist is True

    def test_analysis_keywords(self) -> None:
        results = classify_sentences_offline(
            [("The crash happens because of a race condition", "user")]
        )
        assert results[0].sentence_type == "ANALYSIS"
        assert results[0].persist is True


# ---------------------------------------------------------------------------
# classify_sentences_offline -- batch behavior
# ---------------------------------------------------------------------------


class TestClassifyBatch:
    """classify_sentences_offline handles multiple sentences in one call."""

    def test_mixed_batch(self) -> None:
        sentences: list[tuple[str, str]] = [
            ("All code must use strict typing", "user"),
            ("What is the deploy target?", "user"),
            ("The server runs on port 443", "user"),
        ]
        results = classify_sentences_offline(sentences)
        assert len(results) == 3
        assert results[0].sentence_type == "REQUIREMENT"
        assert results[1].sentence_type == "QUESTION"
        assert results[2].sentence_type == "FACT"

    def test_empty_input(self) -> None:
        results = classify_sentences_offline([])
        assert results == []

    def test_source_preserved(self) -> None:
        results = classify_sentences_offline([("something factual", "assistant")])
        assert results[0].source == "assistant"

    def test_text_preserved(self) -> None:
        text = "All code must use strict typing"
        results = classify_sentences_offline([(text, "user")])
        assert results[0].text == text
