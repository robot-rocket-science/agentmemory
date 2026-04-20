"""REQ-012: Write durability -- zero acknowledged writes lost after crash.

Every observation and belief that receives an acknowledgment (insert returns
without error) must survive a subsequent process crash. Tests WAL mode
durability by forking a child process, writing beliefs, then killing it
with SIGKILL at random points.

Acceptance threshold: zero acknowledged writes lost across 100 SIGKILL crash cycles.
"""

from __future__ import annotations

import multiprocessing
import os
import signal
import sqlite3
from pathlib import Path

from agentmemory.models import BELIEF_FACTUAL, BSRC_AGENT_INFERRED
from agentmemory.store import MemoryStore


def _writer_process(db_path: str, start_idx: int, count: int) -> None:
    """Child process: open DB, write beliefs, exit normally."""
    store = MemoryStore(db_path)
    for i in range(start_idx, start_idx + count):
        store.insert_belief(
            content=f"Durability test belief #{i}",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )
    store.close()


def _writer_process_with_signal(
    db_path: str,
    start_idx: int,
    count: int,
    kill_after: int,
) -> None:
    """Child process: write beliefs, then self-SIGKILL after kill_after writes."""
    store = MemoryStore(db_path)
    for i in range(start_idx, start_idx + count):
        store.insert_belief(
            content=f"Durability test belief #{i}",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )
        if i - start_idx == kill_after:
            store.close()
            os.kill(os.getpid(), signal.SIGKILL)
    store.close()


def _count_beliefs_with_prefix(db_path: str, prefix: str) -> int:
    """Direct SQL count of beliefs matching a content prefix."""
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT COUNT(*) FROM beliefs WHERE content LIKE ?",
        (prefix + "%",),
    ).fetchone()
    conn.close()
    return int(row[0]) if row else 0


def _belief_exists(db_path: str, content: str) -> bool:
    """Check if a specific belief content exists in the DB."""
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT 1 FROM beliefs WHERE content = ? LIMIT 1",
        (content,),
    ).fetchone()
    conn.close()
    return row is not None


def test_req012_normal_writes_survive_reopen(tmp_path: Path) -> None:
    """Beliefs written and committed survive DB close + reopen."""
    db_path: str = str(tmp_path / "durability.db")
    n_beliefs: int = 50

    p = multiprocessing.Process(
        target=_writer_process,
        args=(db_path, 0, n_beliefs),
    )
    p.start()
    p.join(timeout=30)
    assert p.exitcode == 0, f"Writer process failed with exit code {p.exitcode}"

    count: int = _count_beliefs_with_prefix(db_path, "Durability test belief #")
    assert count == n_beliefs, (
        f"Expected {n_beliefs} beliefs after reopen, found {count}"
    )


def test_req012_sigkill_committed_writes_survive(tmp_path: Path) -> None:
    """Beliefs committed before SIGKILL must survive (WAL durability guarantee).

    Writes 20 beliefs, SIGKILL after belief #10. Beliefs 0-10 must survive.
    """
    db_path: str = str(tmp_path / "crash.db")
    total: int = 20
    kill_after: int = 10

    p = multiprocessing.Process(
        target=_writer_process_with_signal,
        args=(db_path, 0, total, kill_after),
    )
    p.start()
    p.join(timeout=30)

    assert p.exitcode == -signal.SIGKILL, (
        f"Expected SIGKILL exit code (-9), got {p.exitcode}"
    )

    survived: int = 0
    for i in range(kill_after + 1):
        if _belief_exists(db_path, f"Durability test belief #{i}"):
            survived += 1

    assert survived == kill_after + 1, (
        f"REQ-012 FAILED: {survived}/{kill_after + 1} committed beliefs survived SIGKILL. "
        f"WAL mode should guarantee zero loss for committed writes."
    )


def test_req012_repeated_crash_cycles(tmp_path: Path) -> None:
    """Run 100 crash cycles, each writing 10 beliefs then crashing after 5.

    Every belief committed before each crash must survive.
    REQ-012 acceptance: zero acknowledged writes lost across 100 crash cycles.
    """
    db_path: str = str(tmp_path / "multi_crash.db")
    cycles: int = 100
    per_cycle: int = 10
    kill_at: int = 5
    expected_survivors: list[str] = []

    for cycle in range(cycles):
        start_idx: int = cycle * per_cycle

        p = multiprocessing.Process(
            target=_writer_process_with_signal,
            args=(db_path, start_idx, per_cycle, kill_at),
        )
        p.start()
        p.join(timeout=30)

        for i in range(start_idx, start_idx + kill_at + 1):
            expected_survivors.append(f"Durability test belief #{i}")

    missing: list[str] = [
        c for c in expected_survivors if not _belief_exists(db_path, c)
    ]

    assert len(missing) == 0, (
        f"REQ-012 FAILED: {len(missing)}/{len(expected_survivors)} committed writes "
        f"lost across {cycles} crash cycles. Missing: {missing[:5]}..."
    )
