"""Backfill session metrics from conversation logs.

Parses ~/.claude/conversation-logs/ (turns.jsonl + archives) to
retroactively compute correction rates, search patterns, and
session quality for historical sessions.

This fills the gap where session-end hooks failed silently due to
import path bugs. After running, the sessions table will have
accurate metrics for all sessions with matching conversation data.

Usage:
    uv run python scripts/backfill_session_metrics.py
    uv run python scripts/backfill_session_metrics.py --dry-run
    uv run python scripts/backfill_session_metrics.py --project-hash 2e7ed55e017a
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_DIR: Final[Path] = Path.home() / ".claude" / "conversation-logs"
DB_DIR: Final[Path] = Path.home() / ".agentmemory" / "projects"

# Patterns that indicate a user correction
CORRECTION_PATTERNS: Final[list[re.Pattern[str]]] = [
    re.compile(r"\bno[,.]?\s+(that'?s|it'?s)\s+(wrong|not|incorrect)", re.I),
    re.compile(r"\bactually[,.]?\s+(it'?s|we|I|the)", re.I),
    re.compile(r"\bthat'?s\s+not\s+(right|correct|what)", re.I),
    re.compile(r"\bI\s+said\s+.+\s+not\s+", re.I),
    re.compile(r"\bno[,.]?\s+I\s+(meant|said|want)", re.I),
    re.compile(r"\bstop\s+(doing|adding|using|saying)", re.I),
    re.compile(r"\bdon'?t\s+(do|add|use|say|mock|skip|commit)", re.I),
    re.compile(r"\bwrong\b.{0,20}\b(should|use|it'?s)\b", re.I),
    re.compile(r"\bnot\s+what\s+I\s+(asked|meant|said|wanted)", re.I),
]

# Patterns that indicate a repeat question (user re-asking for info already discussed)
REPEAT_PATTERNS: Final[list[re.Pattern[str]]] = [
    re.compile(r"\bI\s+already\s+(told|said|mentioned)", re.I),
    re.compile(r"\bwe\s+(already|just)\s+(discussed|decided|talked)", re.I),
    re.compile(r"\bremember\s+when\s+(we|I|you)", re.I),
    re.compile(r"\blike\s+I\s+said\s+(before|earlier)", re.I),
    re.compile(r"\bas\s+I\s+(mentioned|said)\s+(before|earlier)", re.I),
]


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------


def load_all_turns() -> list[dict[str, str]]:
    """Load all conversation turns from current + archived logs."""
    all_turns: list[dict[str, str]] = []

    # Current log
    current: Path = LOG_DIR / "turns.jsonl"
    if current.exists():
        all_turns.extend(_parse_jsonl(current))

    # Archives
    archive_dir: Path = LOG_DIR / "archive"
    if archive_dir.exists():
        for f in sorted(archive_dir.glob("*.jsonl")):
            all_turns.extend(_parse_jsonl(f))

    # Sort by timestamp
    all_turns.sort(key=lambda t: t.get("timestamp", ""))
    return all_turns


def _parse_jsonl(path: Path) -> list[dict[str, str]]:
    """Parse a JSONL file into a list of dicts."""
    turns: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                turns.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return turns


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


def compute_session_metrics(
    turns: list[dict[str, str]],
) -> dict[str, dict[str, object]]:
    """Compute per-session metrics from conversation turns.

    Returns a dict keyed by session_id with computed metrics.
    """
    # Group turns by session
    by_session: dict[str, list[dict[str, str]]] = defaultdict(list)
    for turn in turns:
        sid: str = turn.get("session_id", "")
        if sid:
            by_session[sid].append(turn)

    results: dict[str, dict[str, object]] = {}
    for sid, session_turns in by_session.items():
        user_turns: list[dict[str, str]] = [
            t for t in session_turns if t.get("event") == "user"
        ]
        assistant_turns: list[dict[str, str]] = [
            t for t in session_turns if t.get("event") == "assistant"
        ]

        # Count corrections
        corrections: int = 0
        for t in user_turns:
            text: str = t.get("text", "")
            for pattern in CORRECTION_PATTERNS:
                if pattern.search(text):
                    corrections += 1
                    break

        # Count repeat questions
        repeats: int = 0
        for t in user_turns:
            text = t.get("text", "")
            for pattern in REPEAT_PATTERNS:
                if pattern.search(text):
                    repeats += 1
                    break

        # Count MCP tool calls (search, remember, correct, etc.)
        searches: int = 0
        remembers: int = 0
        corrects: int = 0
        feedbacks: int = 0
        for t in assistant_turns:
            text = t.get("text", "")
            if "mcp__agentmemory__search" in text:
                searches += 1
            if "mcp__agentmemory__remember" in text:
                remembers += 1
            if "mcp__agentmemory__correct" in text:
                corrects += 1
            if "mcp__agentmemory__feedback" in text:
                feedbacks += 1

        # Timestamps
        timestamps: list[str] = [
            t.get("timestamp", "") for t in session_turns if t.get("timestamp")
        ]
        timestamps.sort()
        started: str = timestamps[0] if timestamps else ""
        ended: str = timestamps[-1] if timestamps else ""

        # Duration in hours
        duration_hours: float = 0.0
        if started and ended:
            try:
                t0: datetime = datetime.fromisoformat(started.replace("Z", "+00:00"))
                t1: datetime = datetime.fromisoformat(ended.replace("Z", "+00:00"))
                duration_hours = (t1 - t0).total_seconds() / 3600.0
            except (ValueError, TypeError):
                pass

        # Correction rate (corrections per user turn)
        correction_rate: float = corrections / len(user_turns) if user_turns else 0.0

        # Repeat rate
        repeat_rate: float = repeats / len(user_turns) if user_turns else 0.0

        results[sid] = {
            "total_turns": len(session_turns),
            "user_turns": len(user_turns),
            "assistant_turns": len(assistant_turns),
            "corrections_detected": corrections,
            "correction_rate": round(correction_rate, 4),
            "repeat_questions": repeats,
            "repeat_rate": round(repeat_rate, 4),
            "searches_performed": searches,
            "remembers": remembers,
            "corrects": corrects,
            "feedbacks": feedbacks,
            "duration_hours": round(duration_hours, 2),
            "started_at": started,
            "ended_at": ended,
        }

    return results


# ---------------------------------------------------------------------------
# DB backfill
# ---------------------------------------------------------------------------


def backfill_project(
    project_hash: str,
    session_metrics: dict[str, dict[str, object]],
    dry_run: bool = False,
) -> dict[str, int]:
    """Backfill metrics for a single project database."""
    db_path: Path = DB_DIR / project_hash / "memory.db"
    if not db_path.exists():
        return {"skipped": 1}

    conn: sqlite3.Connection = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Get existing sessions
    rows = conn.execute("SELECT id, started_at, completed_at FROM sessions").fetchall()
    if not rows:
        conn.close()
        return {"no_sessions": 1}

    updated: int = 0
    created: int = 0

    for row in rows:
        sid: str = row["id"]
        if sid not in session_metrics:
            continue

        metrics: dict[str, object] = session_metrics[sid]

        if dry_run:
            print(f"  Would update {sid[:12]}: {metrics}")
            updated += 1
            continue

        # Update session with backfilled metrics
        conn.execute(
            """UPDATE sessions SET
                corrections_detected = MAX(COALESCE(corrections_detected, 0), ?),
                searches_performed = MAX(COALESCE(searches_performed, 0), ?),
                feedback_given = MAX(COALESCE(feedback_given, 0), ?),
                completed_at = COALESCE(completed_at, ?)
            WHERE id = ?""",
            (
                int(metrics.get("corrections_detected", 0)),  # type: ignore[arg-type]
                int(metrics.get("searches_performed", 0)),  # type: ignore[arg-type]
                int(metrics.get("feedbacks", 0)),  # type: ignore[arg-type]
                str(metrics.get("ended_at", "")),
                sid,
            ),
        )
        updated += 1

    conn.commit()
    conn.close()
    return {"updated": updated, "created": created}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Backfill session metrics from conversation logs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without writing",
    )
    parser.add_argument(
        "--project-hash",
        default=None,
        help="Only backfill a specific project (default: all)",
    )
    args: argparse.Namespace = parser.parse_args()

    print("Loading conversation logs...")
    turns: list[dict[str, str]] = load_all_turns()
    print(
        f"  {len(turns)} turns across {len(set(t.get('session_id', '') for t in turns))} sessions"
    )

    # Compute date range
    timestamps: list[str] = [
        t.get("timestamp", "") for t in turns if t.get("timestamp")
    ]
    timestamps.sort()
    if timestamps:
        print(f"  Date range: {timestamps[0]} to {timestamps[-1]}")

    print("\nComputing session metrics...")
    metrics: dict[str, dict[str, object]] = compute_session_metrics(turns)

    # Summary stats -- helper to avoid type: ignore on every line
    def _int(val: object) -> int:
        return int(val) if val is not None else 0  # type: ignore[arg-type]

    def _float(val: object) -> float:
        return float(val) if val is not None else 0.0  # type: ignore[arg-type]

    total_corrections: int = sum(
        _int(m.get("corrections_detected", 0)) for m in metrics.values()
    )
    total_searches: int = sum(
        _int(m.get("searches_performed", 0)) for m in metrics.values()
    )
    total_user_turns: int = sum(_int(m.get("user_turns", 0)) for m in metrics.values())
    sessions_with_corrections: int = sum(
        1 for m in metrics.values() if _int(m.get("corrections_detected", 0)) > 0
    )
    sessions_with_searches: int = sum(
        1 for m in metrics.values() if _int(m.get("searches_performed", 0)) > 0
    )

    print(f"  {len(metrics)} sessions analyzed")
    print(f"  {total_user_turns} user turns total")
    print(
        f"  {total_corrections} corrections detected ({sessions_with_corrections} sessions)"
    )
    print(
        f"  {total_searches} agentmemory searches ({sessions_with_searches} sessions)"
    )
    overall_correction_rate: float = (
        total_corrections / total_user_turns if total_user_turns > 0 else 0.0
    )
    print(f"  Overall correction rate: {overall_correction_rate:.2%}")

    # Memory-on vs memory-off comparison
    memory_on: list[dict[str, object]] = [
        m for m in metrics.values() if _int(m.get("searches_performed", 0)) > 0
    ]
    memory_off: list[dict[str, object]] = [
        m
        for m in metrics.values()
        if _int(m.get("searches_performed", 0)) == 0
        and _int(m.get("user_turns", 0)) >= 3
    ]

    if memory_on and memory_off:
        on_corr_rate: float = sum(
            _float(m.get("correction_rate", 0)) for m in memory_on
        ) / len(memory_on)
        off_corr_rate: float = sum(
            _float(m.get("correction_rate", 0)) for m in memory_off
        ) / len(memory_off)
        print(
            f"\n  Memory-ON correction rate:  {on_corr_rate:.2%} (n={len(memory_on)} sessions)"
        )
        print(
            f"  Memory-OFF correction rate: {off_corr_rate:.2%} (n={len(memory_off)} sessions)"
        )
        if off_corr_rate > 0:
            reduction: float = (off_corr_rate - on_corr_rate) / off_corr_rate
            print(f"  Correction reduction: {reduction:.1%}")

    # Backfill databases
    print(f"\n{'Dry run: ' if args.dry_run else ''}Backfilling databases...")
    if args.project_hash:
        hashes: list[str] = [args.project_hash]
    else:
        hashes = [d.name for d in DB_DIR.iterdir() if d.is_dir()]

    total_updated: int = 0
    for ph in sorted(hashes):
        result: dict[str, int] = backfill_project(ph, metrics, dry_run=args.dry_run)
        u: int = result.get("updated", 0)
        if u > 0:
            print(f"  {ph}: {u} sessions updated")
            total_updated += u

    print(f"\nTotal: {total_updated} sessions updated across {len(hashes)} projects")
    if args.dry_run:
        print("(dry run -- no changes written)")


if __name__ == "__main__":
    main()
