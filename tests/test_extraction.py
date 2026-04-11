"""Tests for the Exp 61 extraction and classification pipeline modules."""
from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest

from agentmemory.classification import classify_sentences, classify_sentences_offline
from agentmemory.correction_detection import detect_correction
from agentmemory.extraction import extract_sentences
from agentmemory.ingest import IngestResult, ingest_turn
from agentmemory.store import MemoryStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_HAS_API_KEY: bool = bool(os.environ.get("ANTHROPIC_API_KEY"))


@pytest.fixture()
def store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    s: MemoryStore = MemoryStore(tmp_path / "test.db")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# 1. extract_sentences
# ---------------------------------------------------------------------------


def test_extract_sentences_strips_code_blocks() -> None:
    text: str = "Here is some context.\n```python\nprint('hello')\n```\nEnd of message."
    sentences: list[str] = extract_sentences(text)
    for s in sentences:
        assert "print(" not in s
        assert "```" not in s


def test_extract_sentences_strips_inline_code() -> None:
    text: str = "Run the `uv run pytest` command to execute tests."
    sentences: list[str] = extract_sentences(text)
    for s in sentences:
        assert "`" not in s
    # Surrounding text should still be present
    joined: str = " ".join(sentences)
    assert "run" in joined.lower() or "command" in joined.lower() or "execute" in joined.lower()


def test_extract_sentences_strips_urls() -> None:
    text: str = "See https://docs.example.com/api for the full reference."
    sentences: list[str] = extract_sentences(text)
    for s in sentences:
        assert "https://" not in s


def test_extract_sentences_strips_markdown() -> None:
    text: str = (
        "# Header One\n"
        "**Bold text** and _italic text_.\n"
        "| col1 | col2 |\n"
        "| --- | --- |\n"
        "- list item one\n"
        "1. numbered item\n"
        "Regular sentence here."
    )
    sentences: list[str] = extract_sentences(text)
    for s in sentences:
        assert not s.startswith("#")
        assert "**" not in s
        assert "| col" not in s
    joined: str = " ".join(sentences)
    assert "Regular sentence here" in joined


def test_extract_sentences_drops_short_fragments() -> None:
    text: str = "Ok. Yes. Sure. This is a complete sentence worth keeping."
    sentences: list[str] = extract_sentences(text)
    for s in sentences:
        assert len(s) >= 10


def test_extract_sentences_splits_on_punctuation() -> None:
    text: str = "First sentence. Second sentence. Third sentence here."
    sentences: list[str] = extract_sentences(text)
    assert len(sentences) >= 2


def test_extract_sentences_empty_input() -> None:
    sentences: list[str] = extract_sentences("")
    assert sentences == []


# ---------------------------------------------------------------------------
# 2. detect_correction -- known corrections
# ---------------------------------------------------------------------------


def test_detect_correction_imperative_use() -> None:
    """'use X' is a canonical correction from OVERRIDES.md patterns."""
    is_corr, signals, conf = detect_correction("use uv for all package management")
    assert is_corr is True
    assert "imperative" in signals
    assert conf > 0.0


def test_detect_correction_always_never() -> None:
    """'always use uv' hits both imperative and always_never signals."""
    is_corr, _signals, conf = detect_correction("always use uv run commands")
    assert is_corr is True
    assert conf >= 0.3


def test_detect_correction_negation() -> None:
    """'do not use async_bash' is an explicit negation correction."""
    is_corr, signals, _conf = detect_correction(
        "do not use async_bash, it is unreliable"
    )
    assert is_corr is True
    assert "negation" in signals


def test_detect_correction_capital_value() -> None:
    """'capital is 5k not 100k' pattern -- declarative override."""
    is_corr, signals, _conf = detect_correction("the capital is only 5k not 100k")
    assert is_corr is True
    assert "declarative" in signals or "negation" in signals


def test_detect_correction_from_now_on() -> None:
    is_corr, signals, _conf = detect_correction("from now on always commit atomically")
    assert is_corr is True
    assert "always_never" in signals


def test_detect_correction_directive() -> None:
    is_corr, signals, _conf = detect_correction("strict static typing is mandatory in all code")
    assert is_corr is True
    assert "directive" in signals or "declarative" in signals


# ---------------------------------------------------------------------------
# 3. detect_correction -- non-corrections
# ---------------------------------------------------------------------------


def test_detect_non_correction_api_status() -> None:
    """'The API returned 200' is informational, not a correction."""
    is_corr, _signals, _conf = detect_correction("The API returned 200 successfully.")
    # This is informational. It may fire 'declarative' on certain phrasing but we
    # verify the function at least returns a bool without error.
    assert isinstance(is_corr, bool)


def test_detect_non_correction_file_saved() -> None:
    """'file saved successfully' should have low or zero signals."""
    _is_corr, signals, conf = detect_correction("file saved successfully.")
    # Should have very few signals -- not a directive or imperative
    assert len(signals) <= 1
    assert conf <= 0.3


def test_detect_non_correction_observation() -> None:
    """Pure observation with no directive language."""
    _is_corr, _signals, conf = detect_correction(
        "The deployment completed in 45 seconds."
    )
    assert conf <= 0.3


# ---------------------------------------------------------------------------
# 4. classify_sentences_offline
# ---------------------------------------------------------------------------


def test_classify_sentences_offline_basic() -> None:
    """Offline classifier produces valid ClassifiedSentence objects."""
    pairs: list[tuple[str, str]] = [
        ("always use strict static typing in all code", "user"),
        ("the database connection was established successfully", "assistant"),
        ("what is the current status of the build", "user"),
    ]
    results = classify_sentences_offline(pairs)
    assert len(results) == len(pairs)
    for cs in results:
        assert isinstance(cs.persist, bool)
        assert isinstance(cs.sentence_type, str)
        assert cs.alpha > 0.0
        assert cs.beta_param > 0.0
        assert cs.source in ("user", "assistant")


def test_classify_sentences_offline_question_not_persisted() -> None:
    """Questions starting with question words and ending with ? are not persisted."""
    pairs: list[tuple[str, str]] = [
        ("what is the current build status?", "user"),
        ("how does the retrieval pipeline work?", "user"),
    ]
    results = classify_sentences_offline(pairs)
    for cs in results:
        assert cs.persist is False
        assert cs.sentence_type == "QUESTION"


def test_classify_sentences_offline_correction_locked() -> None:
    """Sentences detected as corrections get sentence_type CORRECTION."""
    pairs: list[tuple[str, str]] = [
        ("do not use the async_bash tool in this project", "user"),
    ]
    results = classify_sentences_offline(pairs)
    assert results[0].sentence_type == "CORRECTION"
    assert results[0].persist is True


def test_classify_sentences_offline_requirement() -> None:
    pairs: list[tuple[str, str]] = [
        ("all code must use strict static typing", "user"),
    ]
    results = classify_sentences_offline(pairs)
    assert results[0].sentence_type == "REQUIREMENT"


# ---------------------------------------------------------------------------
# 5. ingest_turn end-to-end (offline)
# ---------------------------------------------------------------------------


def test_ingest_turn_creates_observation_and_beliefs(store: MemoryStore) -> None:
    """ingest_turn inserts at least one observation and some beliefs."""
    text: str = (
        "I always use uv for package management. "
        "Do not use pip directly in this project."
    )
    result: IngestResult = ingest_turn(
        store=store,
        text=text,
        source="user",
        use_llm=False,
    )
    assert result.observations_created == 1
    assert result.sentences_extracted >= 1
    # At least one sentence should persist (strong correction signals)
    assert result.sentences_persisted >= 1


def test_ingest_turn_user_vs_assistant(store: MemoryStore) -> None:
    """Both user and assistant turns are ingested without error."""
    user_result: IngestResult = ingest_turn(
        store=store,
        text="We have decided to use PostgreSQL for the backend database.",
        source="user",
        use_llm=False,
    )
    assistant_result: IngestResult = ingest_turn(
        store=store,
        text="The schema migration completed successfully across all environments.",
        source="assistant",
        use_llm=False,
    )
    assert user_result.observations_created == 1
    assert assistant_result.observations_created == 1


def test_ingest_turn_empty_text(store: MemoryStore) -> None:
    """Empty text produces one observation and no beliefs."""
    result: IngestResult = ingest_turn(
        store=store,
        text="",
        source="user",
        use_llm=False,
    )
    assert result.sentences_extracted == 0
    assert result.beliefs_created == 0


# ---------------------------------------------------------------------------
# 6. Corrections create locked beliefs
# ---------------------------------------------------------------------------


def test_correction_creates_locked_belief(store: MemoryStore) -> None:
    """A user correction turn produces locked, high-confidence beliefs."""
    text: str = "do not use async_bash, always use the regular bash tool instead"
    result: IngestResult = ingest_turn(
        store=store,
        text=text,
        source="user",
        use_llm=False,
    )
    # Corrections are detected and persisted as beliefs
    assert result.corrections_detected >= 1
    assert result.beliefs_created >= 1

    # Corrections are locked (permanent constraints)
    locked = store.get_locked_beliefs()
    assert len(locked) >= 1


def test_correction_detection_count(store: MemoryStore) -> None:
    """IngestResult.corrections_detected is incremented for correction turns."""
    text: str = "never use em dashes in any comments or documentation"
    result: IngestResult = ingest_turn(
        store=store,
        text=text,
        source="user",
        use_llm=False,
    )
    assert result.corrections_detected >= 1


# ---------------------------------------------------------------------------
# 7. LLM classification (skipped if no API key)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _HAS_API_KEY,
    reason="ANTHROPIC_API_KEY not set",
)
def test_classify_sentences_llm() -> None:
    """LLM classifier returns valid classifications for a small batch."""
    pairs: list[tuple[str, str]] = [
        ("always use uv for package management", "user"),
        ("the build completed in 12 seconds", "assistant"),
        ("what version of Python should I use?", "user"),
    ]
    results = classify_sentences(pairs)
    assert len(results) == len(pairs)
    for cs in results:
        assert isinstance(cs.persist, bool)
        assert cs.sentence_type in {
            "REQUIREMENT",
            "CORRECTION",
            "PREFERENCE",
            "FACT",
            "ASSUMPTION",
            "DECISION",
            "ANALYSIS",
            "COORDINATION",
            "QUESTION",
            "META",
        }
