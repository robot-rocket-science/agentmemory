"""REQ-001: Cross-session decision retention -- real conversation log replay.

Replays real conversation logs from turns.jsonl through the ingestion
pipeline, then verifies that decisions made in early sessions are
retrievable in later sessions without re-stating them.

Acceptance threshold: >= 80% of early-session decisions correctly
retrievable after 5+ sessions of additional content.

This test uses production data. If turns.jsonl doesn't exist or has
insufficient data, the test is skipped.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import pytest

from agentmemory.ingest import ingest_turn
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore


_LOGS_DIR: Path = Path.home() / ".claude" / "conversation-logs"
_JSONL_PATH: Path = _LOGS_DIR / "turns.jsonl"
_ARCHIVE_DIR: Path = _LOGS_DIR / "archive"

# Patterns that indicate a user decision, directive, or correction.
_DECISION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(always use|we use|switch to|prefer|use uv)\b", re.IGNORECASE),
    re.compile(
        r"\b(never|don'?t|do not|stop doing|avoid)\b.*\b\w{4,}\b", re.IGNORECASE
    ),
    re.compile(r"\b(the rule is|decision:|we decided)\b", re.IGNORECASE),
    re.compile(r"\b(LLM classification should)\b", re.IGNORECASE),
    re.compile(r"\b(commit the|never commit)\b", re.IGNORECASE),
]

# Minimum text length to be a meaningful decision
_MIN_TEXT_LEN: int = 30
# Skip turns that are mostly XML/task-notification noise
_NOISE_PATTERN: re.Pattern[str] = re.compile(
    r"<(task-notification|tool-use-id|output-file)"
)


def _is_decision_turn(text: str) -> bool:
    """Check if a user turn contains a decision-like statement."""
    if len(text) < _MIN_TEXT_LEN:
        return False
    if _NOISE_PATTERN.search(text):
        return False
    return any(p.search(text) for p in _DECISION_PATTERNS)


def _extract_decision_query(text: str) -> str:
    """Extract key terms from a decision to use as a retrieval query."""
    # Take the first 200 chars, strip noise, extract key words
    snippet: str = text[:200]
    words: list[str] = re.findall(r"[a-zA-Z]{3,}", snippet)
    stopwords: set[str] = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "have",
        "has",
        "are",
        "was",
        "were",
        "been",
        "will",
        "would",
        "should",
        "could",
        "not",
        "but",
        "can",
        "all",
        "also",
        "just",
        "like",
        "use",
        "you",
        "don",
        "please",
        "need",
        "want",
        "let",
        "its",
        "our",
        "your",
    }
    key_words: list[str] = [w for w in words if w.lower() not in stopwords][:8]
    return " ".join(key_words)


def _load_jsonl_into(
    path: Path,
    sessions: dict[str, list[dict[str, str]]],
) -> None:
    """Parse a single JSONL file and append turns into sessions dict."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line_raw in fh:
            line_raw = line_raw.strip()
            if not line_raw:
                continue
            try:
                record: dict[str, object] = json.loads(line_raw)
            except json.JSONDecodeError:
                continue
            event: object = record.get("event")
            text: object = record.get("text")
            sid: object = record.get("session_id")
            ts: object = record.get("timestamp")
            if not isinstance(event, str) or not isinstance(text, str):
                continue
            if not isinstance(sid, str) or not isinstance(ts, str):
                continue
            sessions[sid].append(
                {
                    "event": event,
                    "text": text,
                    "timestamp": ts,
                }
            )


def _load_sessions() -> dict[str, list[dict[str, str]]]:
    """Load all JSONL logs (current + archive) grouped by session_id."""
    sessions: dict[str, list[dict[str, str]]] = defaultdict(list)

    # Current log
    _load_jsonl_into(_JSONL_PATH, sessions)

    # Archived logs
    if _ARCHIVE_DIR.is_dir():
        for archive_file in sorted(_ARCHIVE_DIR.glob("*.jsonl")):
            _load_jsonl_into(archive_file, sessions)

    # Sort each session's turns by timestamp
    for turns in sessions.values():
        turns.sort(key=lambda t: t["timestamp"])
    return dict(sessions)


@pytest.fixture()
def replay_store(tmp_path: Path) -> MemoryStore:
    """Fresh store for replay test."""
    return MemoryStore(tmp_path / "replay.db")


def _has_logs() -> bool:
    """Check if any conversation logs exist (current or archive)."""
    if _JSONL_PATH.exists():
        return True
    if _ARCHIVE_DIR.is_dir() and any(_ARCHIVE_DIR.glob("*.jsonl")):
        return True
    return False


@pytest.mark.skipif(
    not _has_logs(),
    reason="No conversation logs at ~/.claude/conversation-logs/",
)
def test_req001_decisions_persist_across_sessions(replay_store: MemoryStore) -> None:
    """Decisions from early sessions must be retrievable after later sessions.

    1. Load real conversation logs (current + archive), group by session.
    2. Order sessions chronologically.
    3. Ingest first 5 sessions. Extract decision-like turns.
    4. Ingest remaining sessions (additional noise/context).
    5. Verify >= 80% of early decisions are retrievable.
    """
    sessions: dict[str, list[dict[str, str]]] = _load_sessions()

    # Order sessions by earliest timestamp
    session_order: list[str] = sorted(
        sessions.keys(),
        key=lambda sid: sessions[sid][0]["timestamp"] if sessions[sid] else "z",
    )

    # Need at least 10 sessions for a meaningful test
    if len(session_order) < 10:
        pytest.skip(f"Only {len(session_order)} sessions, need >= 10")

    # Phase 1: Ingest first 5 sessions, collect decisions
    early_decisions: list[tuple[str, str]] = []  # (original_text, query)
    for sid in session_order[:5]:
        for turn in sessions[sid]:
            if turn["event"] == "user" and _is_decision_turn(turn["text"]):
                query: str = _extract_decision_query(turn["text"])
                if query:
                    early_decisions.append((turn["text"][:150], query))

            # Ingest all turns (user + assistant)
            ingest_turn(
                store=replay_store,
                text=turn["text"],
                source=turn["event"],
            )

    if len(early_decisions) < 5:
        pytest.skip(f"Only {len(early_decisions)} decisions found in first 5 sessions")

    # Phase 2: Ingest remaining sessions (noise + new context)
    for sid in session_order[5:]:
        for turn in sessions[sid]:
            ingest_turn(
                store=replay_store,
                text=turn["text"],
                source=turn["event"],
            )

    # Phase 3: Verify early decisions are still retrievable
    # Use at most 10 decisions to keep test time reasonable
    test_decisions: list[tuple[str, str]] = early_decisions[:10]
    retrieved_count: int = 0

    for original_text, query in test_decisions:
        result: RetrievalResult = retrieve(
            replay_store,
            query,
            budget=2000,
            include_locked=False,
        )
        # Check if any retrieved belief overlaps with the original decision
        # Use 3+ word overlap as a relevance signal
        original_words: set[str] = {
            w.lower() for w in re.findall(r"[a-zA-Z]{4,}", original_text)
        }
        for belief in result.beliefs:
            belief_words: set[str] = {
                w.lower() for w in re.findall(r"[a-zA-Z]{4,}", belief.content)
            }
            overlap: int = len(original_words & belief_words)
            if overlap >= 3:
                retrieved_count += 1
                break

    retention_rate: float = retrieved_count / len(test_decisions)

    assert retention_rate >= 0.80, (
        f"REQ-001 FAILED: {retrieved_count}/{len(test_decisions)} early decisions "
        f"retrievable after {len(session_order)} sessions ({retention_rate:.0%} < 80%). "
        f"Decisions tested: {[q for _, q in test_decisions]}"
    )
