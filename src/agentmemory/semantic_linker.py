"""LLM-powered semantic linking for onboarding.

After beliefs are ingested, batches them and asks Haiku to identify
which beliefs discuss the same concept, decision, or topic -- even
when the vocabulary differs. Creates RELATES_TO edges that enable
HRR vocabulary bridging without requiring manual citations.

This runs as a post-onboarding pass: all beliefs exist in the DB,
and we're adding edges between them.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from agentmemory.models import EDGE_RELATES_TO

if TYPE_CHECKING:
    from agentmemory.store import MemoryStore

_HAIKU_MODEL: Final[str] = "claude-haiku-4-5-20251001"

# How many beliefs to send per Haiku batch.
LINK_BATCH_SIZE: Final[int] = 30

# Prompt template: given N beliefs, identify pairs that discuss the same topic.
_LINK_PROMPT: Final[str] = """You are linking beliefs in a memory system. Below are {count} beliefs extracted from a project.

Identify pairs that discuss the SAME concept, decision, or topic -- even if they use different words. Focus on semantic meaning, not surface vocabulary.

Examples of links:
- "The fill model rejects 90% of events" and "slippage is the binding constraint" (same concept: fill model limits volume)
- "D097 requires walk-forward evaluation" and "per-year breakdown is mandatory for backtests" (same requirement)

Do NOT link beliefs that merely share a word but discuss different things.

Beliefs:
{beliefs}

Return a JSON array of pairs: [{{"a": <id_a>, "b": <id_b>, "reason": "<short reason>"}}]
Only include confident links. Return [] if no strong links exist."""


@dataclass
class LinkResult:
    """Result of a semantic linking pass."""

    batches_sent: int = 0
    edges_created: int = 0
    errors: int = 0


def build_link_prompt(beliefs: list[tuple[str, str]]) -> str:
    """Build a semantic linking prompt for a batch of (id, content) tuples.

    Returns the full prompt string ready for a Haiku call.
    This is the public API -- the caller handles the LLM invocation
    (either via subprocess, API, or subagent).
    """
    lines: list[str] = []
    for belief_id, content in beliefs[:LINK_BATCH_SIZE]:
        # Truncate long beliefs to keep prompt compact
        truncated: str = content[:200] + "..." if len(content) > 200 else content
        lines.append(f'  {belief_id}: "{truncated}"')
    belief_block: str = "\n".join(lines)
    return _LINK_PROMPT.format(count=len(beliefs), beliefs=belief_block)


def parse_link_response(raw: str) -> list[tuple[str, str, str]]:
    """Parse Haiku's JSON response into (id_a, id_b, reason) tuples.

    Tolerant of malformed responses -- returns empty list on failure.
    """
    match: re.Match[str] | None = re.search(r"\[[\s\S]*\]", raw)
    if match is None:
        return []

    try:
        items: list[dict[str, str]] = json.loads(match.group())
    except (json.JSONDecodeError, ValueError):
        return []

    links: list[tuple[str, str, str]] = []
    for item in items:
        id_a: str = str(item.get("a", ""))
        id_b: str = str(item.get("b", ""))
        reason: str = str(item.get("reason", "semantic"))
        if id_a and id_b and id_a != id_b:
            links.append((id_a, id_b, reason))
    return links


def apply_links(
    store: MemoryStore,
    links: list[tuple[str, str, str]],
) -> int:
    """Insert RELATES_TO edges for parsed links. Returns count of edges created.

    Skips links where either belief doesn't exist or is superseded.
    Avoids duplicate edges.
    """
    created: int = 0
    for id_a, id_b, reason in links:
        # Verify both beliefs exist and are active
        rows_a: list[sqlite3.Row] = store.query(
            "SELECT id FROM beliefs WHERE id = ? AND valid_to IS NULL", (id_a,)
        )
        rows_b: list[sqlite3.Row] = store.query(
            "SELECT id FROM beliefs WHERE id = ? AND valid_to IS NULL", (id_b,)
        )
        if not rows_a or not rows_b:
            continue

        # Check for existing edge in either direction
        existing: list[sqlite3.Row] = store.query(
            "SELECT 1 FROM edges WHERE "
            "((from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?)) "
            "AND edge_type = ?",
            (id_a, id_b, id_b, id_a, EDGE_RELATES_TO),
        )
        if existing:
            continue

        store.insert_edge(
            from_id=id_a,
            to_id=id_b,
            edge_type=EDGE_RELATES_TO,
            weight=0.8,  # LLM-assessed links get high weight
            reason=f"llm_semantic: {reason}",
        )
        created += 1

    return created
