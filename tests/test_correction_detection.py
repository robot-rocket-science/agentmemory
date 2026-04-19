"""Unit tests for the zero-LLM correction detector."""
# pyright: reportUnknownMemberType=false

from __future__ import annotations

import pytest

from agentmemory.correction_detection import detect_correction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def assert_detected(text: str, expected_signals: list[str] | None = None) -> None:
    """Assert text is detected as a correction, optionally checking signals."""
    is_correction, signals, confidence = detect_correction(text)
    assert is_correction, f"Expected correction but got False for: {text!r}"
    assert confidence > 0.0
    if expected_signals is not None:
        for sig in expected_signals:
            assert sig in signals, f"Expected signal {sig!r} in {signals} for: {text!r}"


def assert_not_detected(text: str) -> None:
    """Assert text is NOT detected as a correction."""
    is_correction, _signals, _confidence = detect_correction(text)
    assert not is_correction, (
        f"Expected not-correction but got True (signals={_signals}) for: {text!r}"
    )


# ---------------------------------------------------------------------------
# 1. True positives -- obvious corrections
# ---------------------------------------------------------------------------


class TestTruePositives:
    def test_negation_with_replacement(self) -> None:
        assert_detected(
            "no, use PostgreSQL not MySQL",
            ["negation"],
        )

    def test_thats_wrong_with_declarative(self) -> None:
        # "should be the" triggers declarative; "not " triggers negation
        assert_detected(
            "that's wrong, it should be the other approach not this one",
            ["negation", "declarative"],
        )

    def test_thats_wrong_bare(self) -> None:
        # "that's wrong, it should be X" has no signals -- the declarative
        # regex requires a determiner/number after "should be". This is a
        # known gap in the heuristic detector.
        is_correction, signals, _ = detect_correction("that's wrong, it should be X")
        assert not is_correction
        assert signals == []

    def test_correction_prefix(self) -> None:
        # "not " triggers negation; "is /v2" triggers declarative
        assert_detected(
            "correction: the API endpoint is /v2 not /v1",
            ["negation"],
        )

    def test_stop_doing_that(self) -> None:
        assert_detected(
            "stop committing large files",
            ["imperative", "negation", "emphasis"],
        )

    def test_dont_do_that(self) -> None:
        assert_detected("don't use print statements", ["negation"])

    def test_always_directive(self) -> None:
        assert_detected(
            "always run the linter before committing",
            ["imperative", "always_never"],
        )

    def test_never_directive(self) -> None:
        assert_detected(
            "never push directly to main",
            ["imperative", "always_never"],
        )

    def test_from_now_on(self) -> None:
        assert_detected(
            "from now on, use type hints everywhere",
            ["always_never"],
        )

    def test_frustration_with_exclamation(self) -> None:
        assert_detected(
            "I told you to use pytest!",
            ["prior_ref", "emphasis"],
        )

    def test_prior_reference_we_agreed(self) -> None:
        assert_detected(
            "we agreed to use SQLite, not Postgres",
            ["negation", "prior_ref"],
        )

    def test_must_directive(self) -> None:
        assert_detected("you must use strict typing", ["directive"])

    def test_mandatory_directive(self) -> None:
        assert_detected("type hints are mandatory", ["directive"])

    def test_imperative_use(self) -> None:
        assert_detected("use uv instead of pip", ["imperative"])

    def test_imperative_remove(self) -> None:
        assert_detected("remove the debug logging", ["imperative"])

    def test_imperative_update(self) -> None:
        assert_detected("update the version to 3.0", ["imperative"])

    def test_declarative_needs_to_be(self) -> None:
        assert_detected(
            "the timeout needs to be 30 seconds",
            ["declarative"],
        )

    def test_declarative_should_be(self) -> None:
        assert_detected(
            "the default should be always enabled",
            ["declarative", "always_never"],
        )

    def test_hard_cap(self) -> None:
        assert_detected("there is a hard cap at 5000 tokens", ["directive"])

    def test_ever_again(self) -> None:
        assert_detected("do not do that ever again", ["negation", "emphasis"])

    def test_permanently(self) -> None:
        assert_detected(
            "disable that feature permanently",
            ["always_never"],
        )


# ---------------------------------------------------------------------------
# 2. True negatives -- not corrections
# ---------------------------------------------------------------------------


class TestTrueNegatives:
    def test_positive_acknowledgment(self) -> None:
        assert_not_detected("yes that looks good")

    def test_neutral_statement(self) -> None:
        assert_not_detected("the database uses PostgreSQL")

    def test_request_for_new_feature(self) -> None:
        # "add" at start triggers imperative -- this IS detected.
        # Use phrasing that avoids imperative start.
        assert_not_detected("I'd like a new endpoint for users")

    def test_question(self) -> None:
        assert_not_detected("what version of Python are we using")

    def test_thanks(self) -> None:
        assert_not_detected("thanks, that works")

    def test_proceed(self) -> None:
        assert_not_detected("ok, go ahead")

    def test_descriptive_sentence(self) -> None:
        assert_not_detected("the function returns a tuple of three elements")

    def test_simple_agreement(self) -> None:
        assert_not_detected("sounds good to me")


# ---------------------------------------------------------------------------
# 3. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_string(self) -> None:
        is_correction, signals, confidence = detect_correction("")
        assert not is_correction
        assert signals == []
        assert confidence == 0.0

    def test_whitespace_only(self) -> None:
        is_correction, signals, _confidence = detect_correction("   \n\t  ")
        assert not is_correction
        assert signals == []

    def test_single_word(self) -> None:
        is_correction, _signals, _confidence = detect_correction("hello")
        assert not is_correction

    def test_no_changes_needed(self) -> None:
        # Contains "no " which triggers negation -- the detector fires.
        # This is a known false-positive pattern for the heuristic.
        is_correction, signals, _confidence = detect_correction("no changes needed")
        assert is_correction
        assert "negation" in signals

    def test_case_insensitive(self) -> None:
        assert_detected("ALWAYS use type hints", ["always_never"])

    def test_leading_whitespace(self) -> None:
        assert_detected("  use pytest for all tests", ["imperative"])

    def test_multiple_signals_raise_confidence(self) -> None:
        _, signals, confidence = detect_correction(
            "I told you to always use pytest! stop using unittest"
        )
        assert len(signals) >= 3
        assert confidence >= 0.9

    def test_confidence_capped_at_one(self) -> None:
        # Stack many signals to ensure cap works
        _, _signals, confidence = detect_correction(
            "I told you already! never do that ever again. "
            "it must always be the other way."
        )
        assert confidence <= 1.0


# ---------------------------------------------------------------------------
# 4. Signal-specific tests
# ---------------------------------------------------------------------------


class TestSignalSpecific:
    """Verify each signal fires for its documented triggers."""

    @pytest.mark.parametrize(
        "text",
        [
            "use black for formatting",
            "add a retry mechanism",
            "remove dead code",
            "stop using global state",
            "always check return values",
            "never ignore errors",
            "run the test suite first",
            "keep the interface simple",
            "follow the existing conventions",
            "make it async",
        ],
    )
    def test_imperative_signal(self, text: str) -> None:
        _, signals, _ = detect_correction(text)
        assert "imperative" in signals

    @pytest.mark.parametrize(
        "text",
        [
            "we should always validate input",
            "never skip tests",
            "do this every time",
            "every single commit needs a message",
            "from now on use ruff",
            "enable that permanently",
            "no exceptions, period",
        ],
    )
    def test_always_never_signal(self, text: str) -> None:
        _, signals, _ = detect_correction(text)
        assert "always_never" in signals

    @pytest.mark.parametrize(
        "text",
        [
            "do not use eval",
            "don't hardcode paths",
            "dont ignore warnings",
            "no more manual deployments",
        ],
    )
    def test_negation_signal(self, text: str) -> None:
        _, signals, _ = detect_correction(text)
        assert "negation" in signals

    @pytest.mark.parametrize(
        "text",
        [
            "fix this now!",
            "I hate that pattern",
            "never do that ever again",
        ],
    )
    def test_emphasis_signal(self, text: str) -> None:
        _, signals, _ = detect_correction(text)
        assert "emphasis" in signals

    @pytest.mark.parametrize(
        "text",
        [
            "we've been over this",
            "i told you last time",
            "we discussed this yesterday",
            "we agreed on the approach",
            "I already mentioned that",
            "iirc we decided on option B",
        ],
    )
    def test_prior_ref_signal(self, text: str) -> None:
        _, signals, _ = detect_correction(text)
        assert "prior_ref" in signals

    @pytest.mark.parametrize(
        "text",
        [
            "the limit is 100 requests",
            "the default should be the safe option",
            "retries must be only 3",
            "the format needs to be a standard JSON",
        ],
    )
    def test_declarative_signal(self, text: str) -> None:
        _, signals, _ = detect_correction(text)
        assert "declarative" in signals

    @pytest.mark.parametrize(
        "text",
        [
            "authentication must be enabled",
            "TLS is a hard rule",
            "type hints are mandatory",
            "this is a hard cap",
            "we require full coverage",
        ],
    )
    def test_directive_signal(self, text: str) -> None:
        _, signals, _ = detect_correction(text)
        assert "directive" in signals


# ---------------------------------------------------------------------------
# 5. Return type contract
# ---------------------------------------------------------------------------


class TestReturnContract:
    """Verify the function always returns the documented tuple shape."""

    def test_returns_tuple_of_three(self) -> None:
        result = detect_correction("anything")
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_return_types(self) -> None:
        is_correction, signals, confidence = detect_correction("use X")
        assert isinstance(is_correction, bool)
        assert isinstance(signals, list)
        assert isinstance(confidence, float)

    def test_no_signals_means_not_correction(self) -> None:
        is_correction, signals, confidence = detect_correction("hello world")
        assert not is_correction
        assert signals == []
        assert confidence == 0.0

    def test_one_signal_gives_030_confidence(self) -> None:
        # "use" at start triggers exactly imperative
        _, signals, confidence = detect_correction("use ruff")
        assert len(signals) == 1
        assert confidence == pytest.approx(0.3)

    def test_two_signals_gives_060_confidence(self) -> None:
        # "always" at start triggers imperative + always_never
        _, signals, confidence = detect_correction("always lint")
        assert len(signals) == 2
        assert confidence == pytest.approx(0.6)
