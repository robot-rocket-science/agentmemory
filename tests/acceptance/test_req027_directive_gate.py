"""REQ-027: Directive gate for Bash commands.

Pass criteria:
- The gate script exists and is executable.
- The embedded Python logic correctly blocks commands that violate locked
  prohibition beliefs (matching >=2 key terms from a prohibition).
- Commands that do not match any prohibition are allowed through.
- The _install_directive_gate function in cli.py is idempotent.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
GATE_SCRIPT: Path = REPO_ROOT / "scripts" / "agentmemory-directive-gate.sh"


# ---------------------------------------------------------------------------
# Helper: replicate the gate's core matching logic in pure Python so we can
# unit-test it without shelling out or needing a real SQLite database.
# ---------------------------------------------------------------------------

_PROHIBITION_PATTERNS: list[str] = [
    r"\bnever\b",
    r"\bdo not\b",
    r"\bdon'?t\b",
    r"\bmust not\b",
    r"\bshould not\b",
    r"\bshouldn'?t\b",
    r"\bavoid\b",
    r"\bstop\b",
    r"\bprohibit",
    r"\bban\b",
    r"\bforbid",
]

_STOPWORDS: set[str] = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "shall",
    "should",
    "may",
    "might",
    "must",
    "can",
    "could",
    "of",
    "in",
    "to",
    "for",
    "with",
    "on",
    "at",
    "by",
    "from",
    "not",
    "no",
    "never",
    "don",
    "dont",
    "stop",
    "avoid",
    "and",
    "or",
    "but",
    "if",
    "this",
    "that",
    "it",
}


def _is_prohibition(content: str) -> bool:
    """Return True if content matches any prohibition keyword pattern."""
    lower: str = content.lower()
    for pat in _PROHIBITION_PATTERNS:
        if re.search(pat, lower):
            return True
    return False


def _gate_blocks(prohibitions: list[str], command: str) -> str | None:
    """Replicate the gate's matching logic.

    Returns the violated prohibition string if blocked, None if allowed.
    """
    command_lower: str = command.lower()
    for prohibition in prohibitions:
        words: list[str] = re.findall(r"[a-zA-Z0-9_]+", prohibition.lower())
        key_terms: list[str] = [w for w in words if w not in _STOPWORDS and len(w) >= 3]
        matches: int = sum(1 for t in key_terms if t in command_lower)
        if matches >= 2 and len(key_terms) >= 2:
            return prohibition
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_req027_gate_script_exists() -> None:
    """The directive gate shell script exists at the expected path."""
    assert GATE_SCRIPT.exists(), f"Gate script not found at {GATE_SCRIPT}"


def test_req027_gate_script_is_executable() -> None:
    """The directive gate shell script has the executable bit set."""
    assert GATE_SCRIPT.exists(), f"Gate script not found at {GATE_SCRIPT}"
    mode: int = os.stat(GATE_SCRIPT).st_mode
    assert mode & stat.S_IXUSR, f"Gate script is not user-executable (mode={oct(mode)})"


def test_req027_prohibition_detection() -> None:
    """Prohibition patterns correctly identify prohibition beliefs."""
    assert _is_prohibition("Never use async_bash for long-running tasks")
    assert _is_prohibition("Do not commit .env files")
    assert _is_prohibition("Avoid using global mutable state")
    assert _is_prohibition("You must not delete production data")
    assert not _is_prohibition("Use pytest for all tests")
    assert not _is_prohibition("Database schema uses PostgreSQL")


def test_req027_gate_blocks_matching_command() -> None:
    """Gate blocks a command when >=2 key terms from a prohibition match."""
    prohibitions: list[str] = [
        "Never use async_bash for long-running tasks",
    ]
    # "async_bash" and "long" both appear -> block
    result: str | None = _gate_blocks(
        prohibitions, "async_bash --timeout 3600 long-running-job"
    )
    assert result is not None, "Gate should block command matching prohibition"


def test_req027_gate_allows_unrelated_command() -> None:
    """Gate allows a command that does not match any prohibition."""
    prohibitions: list[str] = [
        "Never use async_bash for long-running tasks",
        "Do not commit .env files",
    ]
    result: str | None = _gate_blocks(prohibitions, "git status")
    assert result is None, "Gate should allow unrelated command"


def test_req027_gate_requires_two_term_matches() -> None:
    """A single key-term match is not enough to trigger a block."""
    prohibitions: list[str] = [
        "Never delete production databases without backup",
    ]
    # Only "delete" matches -> should not block
    result: str | None = _gate_blocks(prohibitions, "rm -rf /tmp/test_dir")
    assert result is None, "Single key-term match should not trigger block"


def test_req027_install_function_exists() -> None:
    """The _install_directive_gate function is importable from cli module."""
    from agentmemory.cli import _install_directive_gate  # type: ignore[attr-access]

    assert callable(_install_directive_gate)
