"""Tests that the ingest pipeline respects the use_llm configuration toggle.

Verifies that when ingest.use_llm=True, the LLM classifier is called,
and when ingest.use_llm=False, the offline classifier is used instead.
Uses mocking to avoid requiring an API key.
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agentmemory.store import MemoryStore
import agentmemory.server as server_mod
from agentmemory.server import ingest


@pytest.fixture(autouse=True)
def isolated_store(tmp_path: Path) -> Generator[None, None, None]:
    """Replace the module-level store with a fresh tmp store for each test."""
    db_path: Path = tmp_path / "test_memory.db"
    store: MemoryStore = MemoryStore(db_path)
    server_mod._set_store(store)  # pyright: ignore[reportPrivateUsage]
    yield
    store.close()
    server_mod._set_store(None)  # type: ignore[arg-type]  # pyright: ignore[reportPrivateUsage]


class TestUseLLMConfig:
    """Verify the ingest tool dispatches to the correct classifier based on config."""

    def test_use_llm_false_calls_offline_classifier(self) -> None:
        """When ingest.use_llm=False, ingest_turn should use classify_sentences_offline."""
        with (
            patch("agentmemory.server.get_bool_setting", return_value=False) as mock_setting,
            patch("agentmemory.ingest.classify_sentences_offline", wraps=__import__(
                "agentmemory.classification", fromlist=["classify_sentences_offline"]
            ).classify_sentences_offline) as mock_offline,
            patch("agentmemory.ingest.classify_sentences") as mock_llm,
        ):
            result: str = ingest("All code must use strict typing.", source="user")

            # Verify config was checked
            mock_setting.assert_called_with("ingest", "use_llm")

            # Verify offline was called, LLM was not
            mock_offline.assert_called_once()
            mock_llm.assert_not_called()

            # Verify output says "offline"
            assert "offline" in result

    def test_use_llm_true_but_no_api_key_falls_back_to_offline(self) -> None:
        """When use_llm=True but ANTHROPIC_API_KEY is not set, should fall back to offline."""
        with (
            patch("agentmemory.server.get_bool_setting", return_value=True),
            patch.dict("os.environ", {}, clear=False),
            patch("agentmemory.ingest.classify_sentences_offline", wraps=__import__(
                "agentmemory.classification", fromlist=["classify_sentences_offline"]
            ).classify_sentences_offline) as mock_offline,
            patch("agentmemory.ingest.classify_sentences") as mock_llm,
        ):
            # Remove ANTHROPIC_API_KEY if present
            import os
            env_backup: str | None = os.environ.pop("ANTHROPIC_API_KEY", None)
            try:
                result: str = ingest("Testing fallback behavior.", source="user")
                # Should use offline since no API key
                assert "offline" in result
                mock_offline.assert_called_once()
                mock_llm.assert_not_called()
            finally:
                if env_backup is not None:
                    os.environ["ANTHROPIC_API_KEY"] = env_backup

    def test_use_llm_true_with_api_key_calls_llm_classifier(self) -> None:
        """When use_llm=True and ANTHROPIC_API_KEY is set, should use LLM classifier."""
        import json

        # Build a mock LLM response
        mock_response_items: list[dict[str, str | int]] = [
            {"id": 1, "persist": "PERSIST", "type": "REQUIREMENT"},
        ]
        mock_response_text: str = json.dumps(mock_response_items)

        mock_block: MagicMock = MagicMock()
        mock_block.type = "text"
        mock_block.text = mock_response_text

        mock_anthropic_instance: MagicMock = MagicMock()
        mock_anthropic_instance.messages.create.return_value.content = [mock_block]

        with (
            patch("agentmemory.server.get_bool_setting", return_value=True),
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"}),
            patch("agentmemory.ingest.classify_sentences") as mock_llm,
            patch("agentmemory.ingest.classify_sentences_offline") as mock_offline,
        ):
            # Make mock_llm return a valid ClassifiedSentence list
            from agentmemory.classification import ClassifiedSentence
            mock_llm.return_value = [
                ClassifiedSentence(
                    text="All code must use strict typing.",
                    source="user",
                    persist=True,
                    sentence_type="REQUIREMENT",
                    alpha=9.0,
                    beta_param=1.0,
                ),
            ]

            result: str = ingest("All code must use strict typing.", source="user")

            # Verify LLM classifier was called, offline was not
            mock_llm.assert_called_once()
            mock_offline.assert_not_called()

            # Verify output says "haiku"
            assert "haiku" in result
