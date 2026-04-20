"""REQ-006: Checkpoint write overhead < 50ms p95.

Pass criterion: p95 latency for writing a checkpoint must be < 50ms.
p99 must be < 100ms.
1,000 checkpoints with payload sizes from 100 bytes to 10KB.
"""

from __future__ import annotations

import statistics
import time

from agentmemory.models import (
    CKPT_DECISION,
    CKPT_FILE_CHANGE,
    CKPT_TASK_STATE,
    Session,
)
from agentmemory.store import MemoryStore

_NUM_CHECKPOINTS: int = 1_000
_P95_LIMIT_MS: float = 50.0
_P99_LIMIT_MS: float = 100.0


def _make_payload(size_bytes: int) -> str:
    """Return a string payload of approximately size_bytes bytes."""
    unit: str = "x"
    return unit * size_bytes


def test_req006_checkpoint_latency(store: MemoryStore) -> None:
    """Write 1,000 checkpoints, measure latency, assert p95 < 50ms and p99 < 100ms."""
    session: Session = store.create_session(
        model="claude", project_context="latency-test"
    )

    checkpoint_types: list[str] = [CKPT_DECISION, CKPT_FILE_CHANGE, CKPT_TASK_STATE]
    latencies_ms: list[float] = []

    for i in range(_NUM_CHECKPOINTS):
        # Vary payload size: 100 bytes up to ~10KB in a sawtooth pattern.
        size_bytes: int = 100 + (i % 100) * 100  # 100, 200, ..., 10000, 100, ...
        payload: str = _make_payload(size_bytes)
        ctype: str = checkpoint_types[i % len(checkpoint_types)]

        t0: float = time.perf_counter()
        store.checkpoint(
            session_id=session.id,
            checkpoint_type=ctype,
            content=payload,
            references=[f"ref_{i}"],
        )
        t1: float = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000.0)

    latencies_ms.sort()
    p50: float = statistics.median(latencies_ms)
    p95_idx: int = int(len(latencies_ms) * 0.95)
    p99_idx: int = int(len(latencies_ms) * 0.99)
    p95: float = latencies_ms[p95_idx]
    p99: float = latencies_ms[p99_idx]

    assert p95 < _P95_LIMIT_MS, (
        f"REQ-006 FAILED: p95 latency {p95:.2f}ms >= {_P95_LIMIT_MS}ms. "
        f"p50={p50:.2f}ms p99={p99:.2f}ms"
    )
    assert p99 < _P99_LIMIT_MS, (
        f"REQ-006 FAILED: p99 latency {p99:.2f}ms >= {_P99_LIMIT_MS}ms. "
        f"p50={p50:.2f}ms p95={p95:.2f}ms"
    )
