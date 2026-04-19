"""Validation tests for end-to-end onboarding.

Verifies that onboard() creates beliefs directly without requiring
LLM orchestration. One call should scan, classify, and persist.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture()
def sample_project(tmp_path: Path) -> Path:
    """Create a minimal project directory with scannable content."""
    proj: Path = tmp_path / "test-project"
    proj.mkdir()

    # A Python file
    (proj / "main.py").write_text(
        '"""Main module for the test project."""\n'
        "def hello() -> str:\n"
        '    return "world"\n'
    )

    # A markdown doc
    (proj / "README.md").write_text(
        "# Test Project\n\n"
        "This project demonstrates agentmemory onboarding.\n\n"
        "## Requirements\n\n"
        "All code must use strict typing.\n"
        "Never commit large data files.\n"
    )

    # Initialize git so scanner can find it
    os.system(f"cd {proj} && git init -q && git add . && git commit -q -m 'init'")

    return proj


def test_onboard_creates_beliefs_without_llm(sample_project: Path) -> None:
    """onboard() should create beliefs end-to-end, not return raw JSON."""
    # Use the MCP tool function directly
    from agentmemory.server import onboard

    result: str = onboard(str(sample_project))

    # Should NOT contain SENTENCES_JSON_START (old behavior)
    assert "SENTENCES_JSON_START" not in result, (
        "onboard should not dump raw JSON for LLM classification"
    )

    # Should contain belief creation summary
    assert "Beliefs created:" in result, (
        f"onboard should report beliefs created. Got:\n{result}"
    )

    # Should have created at least some beliefs
    lines: list[str] = result.split("\n")
    for line in lines:
        if "Beliefs created:" in line:
            count_str: str = line.split(":")[1].strip()
            count: int = int(count_str)
            assert count > 0, "Should create at least 1 belief from README content"
            break


def test_onboard_returns_concise_summary(sample_project: Path) -> None:
    """onboard() result should be a concise summary, not 600K of JSON."""
    from agentmemory.server import onboard

    result: str = onboard(str(sample_project))

    # Result should be under 5K characters (was 600K before)
    assert len(result) < 5000, (
        f"onboard result should be concise summary, got {len(result)} chars"
    )


def test_onboard_includes_type_breakdown(sample_project: Path) -> None:
    """onboard() should report belief type breakdown."""
    from agentmemory.server import onboard

    result: str = onboard(str(sample_project))

    # Should show at least one belief type
    has_type: bool = any(
        t in result for t in ["factual:", "requirement:", "correction:", "preference:"]
    )
    assert has_type, f"Should include type breakdown. Got:\n{result}"
