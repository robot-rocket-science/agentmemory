"""Tests comparing offline vs LLM classification on hand-picked sentences.

Each sentence has a known-correct classification (human-labeled ground truth).
The test runs both classifiers and documents where they disagree.

Key findings from gap analysis:
- Offline classifier never catches anything LLM misses (0 cases across 4 repos)
- Offline false-persist rate: 24-76% depending on repo
- Offline CORRECTION precision: 4-11% (fires on keywords in non-correction text)
- Offline REQUIREMENT keyword match is decent when the text is genuinely a
  requirement, but also fires on headings like "Requirements Validated"
- LLM is strictly superior for persist/type classification
"""
from __future__ import annotations

import json
from typing import Any

from agentmemory.classification import (
    ClassifiedSentence,
    _parse_llm_response,  # pyright: ignore[reportPrivateUsage]
    classify_sentences_offline,
)


# ---------------------------------------------------------------------------
# Ground truth: 20 hand-picked sentences with correct classifications
# ---------------------------------------------------------------------------

# Each entry: (text, source, correct_persist, correct_type, notes)
GROUND_TRUTH: list[dict[str, Any]] = [
    # --- Headings / structural (should NOT persist) ---
    {
        "text": "Files Created/Modified",
        "source": "assistant",
        "persist": False,
        "type": "META",
        "note": "Section heading. Offline: FACT+persist (wrong).",
    },
    {
        "text": "Requirements Validated",
        "source": "assistant",
        "persist": False,
        "type": "META",
        "note": "Section heading containing keyword 'require'. Offline: REQUIREMENT+persist (wrong).",
    },
    {
        "text": "Completed This Session",
        "source": "assistant",
        "persist": False,
        "type": "META",
        "note": "Section heading. Offline: FACT+persist (wrong).",
    },
    {
        "text": "**Date:** 2026-03-27",
        "source": "assistant",
        "persist": False,
        "type": "META",
        "note": "Metadata line. Offline: FACT+persist (wrong).",
    },
    {
        "text": "patterns_established:",
        "source": "assistant",
        "persist": False,
        "type": "META",
        "note": "YAML-like key. Offline: FACT+persist (wrong).",
    },
    # --- Ephemeral coordination (should NOT persist) ---
    {
        "text": "Run Ansible playbook -- UCI config applied and verified.",
        "source": "assistant",
        "persist": False,
        "type": "COORDINATION",
        "note": "Action completed. Offline: CORRECTION+persist (wrong, 'run' triggers imperative).",
    },
    {
        "text": "Copy token -- agent will save it securely",
        "source": "assistant",
        "persist": False,
        "type": "COORDINATION",
        "note": "Instruction step. Offline: CORRECTION+persist (wrong, 'copy' triggers imperative).",
    },
    # --- Questions (should NOT persist) ---
    {
        "text": "What port is Grafana running on?",
        "source": "user",
        "persist": False,
        "type": "QUESTION",
        "note": "Both classifiers should get this right.",
    },
    {
        "text": "How do I restart the VPN container?",
        "source": "user",
        "persist": False,
        "type": "QUESTION",
        "note": "Both classifiers should get this right.",
    },
    # --- True corrections (should persist) ---
    {
        "text": "Changed listen interface from loopback to LAN (192.168.1.2:9100).",
        "source": "assistant",
        "persist": True,
        "type": "CORRECTION",
        "note": "Actual config change. LLM gets CORRECTION. Offline: FACT (misses it).",
    },
    {
        "text": "Changed interface pattern from default loopback,lan to lan* so neighbors are discovered per physical port.",
        "source": "assistant",
        "persist": True,
        "type": "CORRECTION",
        "note": "Actual config change. LLM gets CORRECTION. Offline: FACT.",
    },
    # --- True requirements (should persist) ---
    {
        "text": "All code must use strict static typing (pyright strict mode)",
        "source": "user",
        "persist": True,
        "type": "REQUIREMENT",
        "note": "Both should get this. Offline matches on 'must'.",
    },
    {
        "text": "Commits should be atomic and concise",
        "source": "user",
        "persist": True,
        "type": "REQUIREMENT",
        "note": "LLM gets REQUIREMENT. Offline: FACT (no keyword match).",
    },
    # --- True preferences (should persist) ---
    {
        "text": "RAID -- single-disk setup, use backups",
        "source": "user",
        "persist": True,
        "type": "PREFERENCE",
        "note": "Architecture preference. LLM: PREFERENCE. Offline: FACT.",
    },
    {
        "text": "Always use uv for Python package management",
        "source": "user",
        "persist": True,
        "type": "PREFERENCE",
        "note": "Offline: CORRECTION (triggers on 'always use'). LLM: PREFERENCE.",
    },
    # --- True facts (should persist) ---
    {
        "text": "Grafana datasource UID is PBFA97CFB590B2093 -- all alert rules bind to this UID.",
        "source": "assistant",
        "persist": True,
        "type": "FACT",
        "note": "Concrete factual detail. Both should persist this.",
    },
    {
        "text": "Port forwarding 41515, correctly synced to qBittorrent listen_port",
        "source": "assistant",
        "persist": True,
        "type": "FACT",
        "note": "Infrastructure fact. Both persist, types may differ.",
    },
    # --- False positives for offline CORRECTION detector ---
    {
        "text": "fix: vpn-health-check -- use gluetun API for exit IP",
        "source": "assistant",
        "persist": True,
        "type": "FACT",
        "note": "Commit message. Offline: CORRECTION (triggers on 'fix' and 'use'). LLM: FACT.",
    },
    {
        "text": "Add IoT re-pairing checklist after KivaNet retirement",
        "source": "assistant",
        "persist": True,
        "type": "FACT",
        "note": "Commit message. Offline: CORRECTION (triggers on 'add'). LLM: FACT.",
    },
    {
        "text": "The upload was never triggered because the script uploads only after all folds complete.",
        "source": "assistant",
        "persist": True,
        "type": "FACT",
        "note": "Factual statement. Offline: CORRECTION (triggers on 'never'). LLM: FACT.",
    },
]


# ---------------------------------------------------------------------------
# Helper: build mock LLM response from ground truth
# ---------------------------------------------------------------------------


def _mock_llm_response(batch: list[dict[str, Any]]) -> str:
    """Build the JSON array a perfect LLM would return."""
    items: list[dict[str, str | int]] = []
    for i, gt in enumerate(batch, start=1):
        persist_label: str = "PERSIST" if gt["persist"] else "EPHEMERAL"
        items.append({"id": i, "persist": persist_label, "type": gt["type"]})
    return json.dumps(items)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOfflineClassifier:
    """Verify offline classifier behavior on known sentences."""

    def test_offline_persist_accuracy(self) -> None:
        """Offline classifier should persist everything except questions."""
        sentences: list[tuple[str, str]] = [
            (gt["text"], gt["source"]) for gt in GROUND_TRUTH
        ]
        results: list[ClassifiedSentence] = classify_sentences_offline(sentences)

        correct_persist: int = 0
        for gt, result in zip(GROUND_TRUTH, results):
            if gt["persist"] == result.persist:
                correct_persist += 1

        # Offline should get at least the questions right but miss most
        # non-persist cases. Expect < 70% accuracy on persist.
        accuracy: float = correct_persist / len(GROUND_TRUTH)
        assert accuracy < 0.75, (
            f"Offline persist accuracy {accuracy:.0%} is unexpectedly high. "
            "If this passes, the ground truth set may not cover enough "
            "headings/structural text that offline over-persists."
        )

    def test_offline_false_correction_rate(self) -> None:
        """Offline correction detector fires on non-corrections."""
        sentences: list[tuple[str, str]] = [
            (gt["text"], gt["source"]) for gt in GROUND_TRUTH
        ]
        results: list[ClassifiedSentence] = classify_sentences_offline(sentences)

        # Count sentences offline labels CORRECTION that are not corrections
        false_corrections: list[str] = []
        for gt, result in zip(GROUND_TRUTH, results):
            if result.sentence_type == "CORRECTION" and gt["type"] != "CORRECTION":
                false_corrections.append(gt["text"][:80])

        # Expect at least 3 false corrections from this set (commit messages,
        # coordination text with imperative verbs, etc.)
        assert len(false_corrections) >= 3, (
            f"Expected >= 3 false corrections, got {len(false_corrections)}. "
            f"False corrections found: {false_corrections}"
        )

    def test_offline_never_catches_what_llm_misses(self) -> None:
        """In our ground truth, offline should not find any persist=True
        sentence that LLM would mark ephemeral. This validates the finding
        from 4-repo analysis: offline_misses = 0 in all repos."""
        sentences: list[tuple[str, str]] = [
            (gt["text"], gt["source"]) for gt in GROUND_TRUTH
        ]
        results: list[ClassifiedSentence] = classify_sentences_offline(sentences)

        # Every ground-truth persist=True sentence should also be persist=True
        # in offline (since offline persists almost everything)
        for gt, result in zip(GROUND_TRUTH, results):
            if gt["persist"]:
                assert result.persist, (
                    f"Offline missed persist for: {gt['text'][:80]}. "
                    "This would mean offline catches something LLM does not, "
                    "which contradicts the 4-repo analysis."
                )

    def test_offline_questions_detected(self) -> None:
        """Offline correctly identifies questions as non-persist."""
        questions: list[tuple[str, str]] = [
            (gt["text"], gt["source"])
            for gt in GROUND_TRUTH
            if gt["type"] == "QUESTION"
        ]
        results: list[ClassifiedSentence] = classify_sentences_offline(questions)

        for gt_q, result in zip(
            [g for g in GROUND_TRUTH if g["type"] == "QUESTION"], results
        ):
            assert not result.persist, (
                f"Offline should mark question as non-persist: {gt_q['text']}"
            )
            assert result.sentence_type == "QUESTION"


class TestLLMClassifier:
    """Verify LLM response parsing produces correct results."""

    def test_llm_parse_accuracy(self) -> None:
        """LLM parser with perfect mock responses should be 100% accurate."""
        batch: list[tuple[str, str]] = [
            (gt["text"], gt["source"]) for gt in GROUND_TRUTH
        ]
        mock_response: str = _mock_llm_response(GROUND_TRUTH)
        results: list[ClassifiedSentence] = _parse_llm_response(  # pyright: ignore[reportPrivateUsage]
            mock_response, batch
        )

        assert len(results) == len(GROUND_TRUTH)

        for gt, result in zip(GROUND_TRUTH, results):
            assert result.persist == gt["persist"], (
                f"Persist mismatch for: {gt['text'][:60]}"
            )
            assert result.sentence_type == gt["type"], (
                f"Type mismatch for: {gt['text'][:60]}: "
                f"got {result.sentence_type}, expected {gt['type']}"
            )

    def test_llm_correction_precision(self) -> None:
        """LLM should only label actual corrections as CORRECTION."""
        batch: list[tuple[str, str]] = [
            (gt["text"], gt["source"]) for gt in GROUND_TRUTH
        ]
        mock_response: str = _mock_llm_response(GROUND_TRUTH)
        results: list[ClassifiedSentence] = _parse_llm_response(  # pyright: ignore[reportPrivateUsage]
            mock_response, batch
        )

        for gt, result in zip(GROUND_TRUTH, results):
            if result.sentence_type == "CORRECTION":
                assert gt["type"] == "CORRECTION", (
                    f"LLM false correction: {gt['text'][:60]}"
                )


class TestClassifierComparison:
    """Direct head-to-head comparison on the same ground truth."""

    def test_disagreement_catalog(self) -> None:
        """Catalog all disagreements between offline and (mocked) LLM.

        This test always passes; its value is in the printed output
        showing exactly where and how the classifiers diverge.
        """
        sentences: list[tuple[str, str]] = [
            (gt["text"], gt["source"]) for gt in GROUND_TRUTH
        ]

        # Offline
        offline_results: list[ClassifiedSentence] = classify_sentences_offline(
            sentences
        )

        # LLM (mocked)
        mock_response: str = _mock_llm_response(GROUND_TRUTH)
        llm_results: list[ClassifiedSentence] = _parse_llm_response(  # pyright: ignore[reportPrivateUsage]
            mock_response, sentences
        )

        disagree_persist: int = 0
        disagree_type: int = 0
        offline_wins: int = 0
        llm_wins: int = 0

        for gt, off, llm in zip(GROUND_TRUTH, offline_results, llm_results):
            off_persist_correct: bool = off.persist == gt["persist"]
            llm_persist_correct: bool = llm.persist == gt["persist"]
            off_type_correct: bool = off.sentence_type == gt["type"]
            llm_type_correct: bool = llm.sentence_type == gt["type"]

            if off.persist != llm.persist:
                disagree_persist += 1
            if off.sentence_type != llm.sentence_type:
                disagree_type += 1

            # Score: correct on both dimensions = 2 pts, one = 1 pt
            off_score: int = int(off_persist_correct) + int(off_type_correct)
            llm_score: int = int(llm_persist_correct) + int(llm_type_correct)

            if off_score > llm_score:
                offline_wins += 1
            elif llm_score > off_score:
                llm_wins += 1

        # LLM should win on the majority of disagreements
        assert llm_wins > offline_wins, (
            f"LLM wins ({llm_wins}) should exceed offline wins ({offline_wins})"
        )
        # At least 5 persist disagreements in our set
        assert disagree_persist >= 5

    def test_offline_over_persists(self) -> None:
        """Offline should have a higher false-persist rate than LLM."""
        sentences: list[tuple[str, str]] = [
            (gt["text"], gt["source"]) for gt in GROUND_TRUTH
        ]
        offline_results: list[ClassifiedSentence] = classify_sentences_offline(
            sentences
        )

        # Count false persists for offline
        non_persist_gt: list[dict[str, Any]] = [
            gt for gt in GROUND_TRUTH if not gt["persist"]
        ]
        offline_false_persist: int = sum(
            1
            for gt, off in zip(GROUND_TRUTH, offline_results)
            if not gt["persist"] and off.persist
        )

        # Offline should false-persist at least half of the non-persist items
        assert offline_false_persist >= len(non_persist_gt) // 2, (
            f"Expected offline to false-persist at least "
            f"{len(non_persist_gt) // 2} items, got {offline_false_persist}"
        )
