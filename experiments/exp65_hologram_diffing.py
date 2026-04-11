"""Exp 65: Belief Graph Diffing and Drift Detection.

Tests whether diffing two snapshots of the belief graph can detect
meaningful changes vs noise. Operates on the full graph.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentmemory.store import MemoryStore

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class BeliefSnapshot:
    """Immutable snapshot of belief state."""
    belief_id: str
    content_hash: str
    confidence: float
    belief_type: str
    locked: bool


@dataclass
class SnapshotDiff:
    """Result of diffing two belief snapshots."""
    added: list[BeliefSnapshot] = field(default_factory=lambda: list[BeliefSnapshot]())
    removed: list[BeliefSnapshot] = field(default_factory=lambda: list[BeliefSnapshot]())
    confidence_changed: list[tuple[BeliefSnapshot, BeliefSnapshot]] = field(
        default_factory=lambda: list[tuple[BeliefSnapshot, BeliefSnapshot]](),
    )
    type_changed: list[tuple[BeliefSnapshot, BeliefSnapshot]] = field(
        default_factory=lambda: list[tuple[BeliefSnapshot, BeliefSnapshot]](),
    )
    lock_changed: list[tuple[BeliefSnapshot, BeliefSnapshot]] = field(
        default_factory=lambda: list[tuple[BeliefSnapshot, BeliefSnapshot]](),
    )
    top_k_turnover: float = 0.0  # Jaccard distance of top-100


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


def take_snapshot(store: MemoryStore) -> list[BeliefSnapshot]:
    """Take a snapshot of all active beliefs."""
    rows = store.query("SELECT * FROM beliefs WHERE valid_to IS NULL")
    result: list[BeliefSnapshot] = []
    for r in rows:
        alpha = float(r["alpha"])
        beta_p = float(r["beta_param"])
        conf = alpha / (alpha + beta_p) if (alpha + beta_p) > 0 else 0.0
        result.append(BeliefSnapshot(
            belief_id=r["id"],
            content_hash=r["content_hash"],
            confidence=conf,
            belief_type=r["belief_type"],
            locked=bool(r["locked"]),
        ))
    return result


def _top_k_ids(snap: list[BeliefSnapshot], k: int = 100) -> set[str]:
    """Return the top-k belief IDs by confidence (descending)."""
    sorted_snap = sorted(snap, key=lambda b: b.confidence, reverse=True)
    return {b.belief_id for b in sorted_snap[:k]}


def diff_snapshots(
    a: list[BeliefSnapshot],
    b: list[BeliefSnapshot],
) -> SnapshotDiff:
    """Diff two snapshots and return structured changes."""
    a_by_hash: dict[str, BeliefSnapshot] = {s.content_hash: s for s in a}
    b_by_hash: dict[str, BeliefSnapshot] = {s.content_hash: s for s in b}

    a_hashes = set(a_by_hash.keys())
    b_hashes = set(b_by_hash.keys())

    diff = SnapshotDiff()

    # Added / removed
    for h in sorted(b_hashes - a_hashes):
        diff.added.append(b_by_hash[h])
    for h in sorted(a_hashes - b_hashes):
        diff.removed.append(a_by_hash[h])

    # Changed (same content_hash in both)
    for h in sorted(a_hashes & b_hashes):
        sa = a_by_hash[h]
        sb = b_by_hash[h]
        if abs(sa.confidence - sb.confidence) > 1e-9:
            diff.confidence_changed.append((sa, sb))
        if sa.belief_type != sb.belief_type:
            diff.type_changed.append((sa, sb))
        if sa.locked != sb.locked:
            diff.lock_changed.append((sa, sb))

    # Top-100 turnover (Jaccard distance)
    top_a = _top_k_ids(a)
    top_b = _top_k_ids(b)
    union = top_a | top_b
    intersection = top_a & top_b
    if union:
        diff.top_k_turnover = 1.0 - (len(intersection) / len(union))
    else:
        diff.top_k_turnover = 0.0

    return diff


def diff_summary(label: str, d: SnapshotDiff, contents: str = "") -> str:
    """Format a human-readable diff summary."""
    lines: list[str] = [f"Diff: {label}"]
    lines.append(f"  Added: {len(d.added)} belief(s)")
    for b in d.added:
        lock_tag = " [LOCKED]" if b.locked else ""
        desc = contents if contents else b.content_hash
        lines.append(
            f"    [{b.confidence:.1%}]{lock_tag} {desc} ({b.belief_type})"
        )
    lines.append(f"  Removed: {len(d.removed)}")
    lines.append(f"  Confidence changed: {len(d.confidence_changed)}")
    lines.append(f"  Top-100 turnover: {d.top_k_turnover:.4f}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 1: Diff computation and performance
# ---------------------------------------------------------------------------


def phase1(store: MemoryStore) -> dict[str, Any]:
    """Benchmark diff performance."""
    log("=== Phase 1: Diff computation and performance ===")

    snap = take_snapshot(store)
    log(f"Snapshot size: {len(snap)} active beliefs")

    # Self-diff (should be empty)
    self_diff = diff_snapshots(snap, snap)
    assert len(self_diff.added) == 0, "Self-diff should have no additions"
    assert len(self_diff.removed) == 0, "Self-diff should have no removals"
    assert len(self_diff.confidence_changed) == 0, "Self-diff: no conf changes"
    assert self_diff.top_k_turnover == 0.0, "Self-diff: zero turnover"
    log("Self-diff: PASS (empty as expected)")

    # Modified copy: change confidence of first 10 beliefs
    modified: list[BeliefSnapshot] = []
    for i, b in enumerate(snap):
        modified.append(BeliefSnapshot(
            belief_id=b.belief_id,
            content_hash=b.content_hash,
            confidence=b.confidence + 0.01 if i < 10 else b.confidence,
            belief_type=b.belief_type,
            locked=b.locked,
        ))

    mod_diff = diff_snapshots(snap, modified)
    assert len(mod_diff.confidence_changed) == 10, (
        f"Expected 10 changes, got {len(mod_diff.confidence_changed)}"
    )
    log(f"Modified diff: {len(mod_diff.confidence_changed)} confidence changes (expected 10)")

    # Benchmark: 20 reps
    times_self: list[float] = []
    times_mod: list[float] = []
    for _ in range(20):
        t0 = time.perf_counter()
        diff_snapshots(snap, snap)
        times_self.append(time.perf_counter() - t0)

        t0 = time.perf_counter()
        diff_snapshots(snap, modified)
        times_mod.append(time.perf_counter() - t0)

    times_self.sort()
    times_mod.sort()

    results: dict[str, Any] = {
        "snapshot_size": len(snap),
        "self_diff_empty": True,
        "modified_diff_confidence_changes": len(mod_diff.confidence_changed),
        "bench_self_p50_ms": round(times_self[9] * 1000, 3),
        "bench_self_p95_ms": round(times_self[18] * 1000, 3),
        "bench_mod_p50_ms": round(times_mod[9] * 1000, 3),
        "bench_mod_p95_ms": round(times_mod[18] * 1000, 3),
    }
    log(f"Bench self-diff: p50={results['bench_self_p50_ms']}ms "
        f"p95={results['bench_self_p95_ms']}ms")
    log(f"Bench mod-diff:  p50={results['bench_mod_p50_ms']}ms "
        f"p95={results['bench_mod_p95_ms']}ms")
    return results


# ---------------------------------------------------------------------------
# Phase 2: Simulated drift
# ---------------------------------------------------------------------------

_DRIFT_CONFIGS: list[tuple[str, str, str]] = [
    ("the build system uses Hatch - observation {i}", "factual", "agent_inferred"),
    ("API rate limiting applies at 100 req/s - note {i}", "factual", "agent_inferred"),
    ("all functions must have docstrings - rule {i}", "requirement", "user_stated"),
    ("do not use global variables - correction {i}", "correction", "user_corrected"),
    ("prefer composition over inheritance - pref {i}", "preference", "user_stated"),
]


def phase2(
    prod_snap: list[BeliefSnapshot],
    tmp_db_path: Path,
) -> dict[str, Any]:
    """Simulate 50 turns of drift and measure snapshot changes."""
    log("\n=== Phase 2: Simulated drift ===")

    tmp_store = MemoryStore(tmp_db_path)
    checkpoints: list[dict[str, Any]] = []

    for turn in range(1, 51):
        bucket = (turn - 1) // 10  # 0..4
        template, btype, stype = _DRIFT_CONFIGS[bucket]
        content = template.format(i=turn)

        tmp_store.insert_belief(
            content=content,
            belief_type=btype,
            source_type=stype,
            alpha=0.9,
            beta_param=0.1,
        )

        if turn % 5 == 0:
            snap = take_snapshot(tmp_store)
            d = diff_snapshots(prod_snap, snap)
            cp: dict[str, Any] = {
                "turn": turn,
                "added_count": len(d.added),
                "removed_count": len(d.removed),
                "top_100_turnover": round(d.top_k_turnover, 4),
            }
            checkpoints.append(cp)
            log(f"  Turn {turn:2d}: added={cp['added_count']}, "
                f"top100_turnover={cp['top_100_turnover']:.4f}")

    return {"drift_checkpoints": checkpoints}


# ---------------------------------------------------------------------------
# Phase 3: Correction impact detection
# ---------------------------------------------------------------------------

_CORRECTIONS: list[tuple[str, str]] = [
    ("C1", "HRR is only useful for fuzzy-start retrieval, not multi-hop"),
    ("C2", "The token budget must be 3000, not 2000"),
    ("C3", "Temporal edges add zero signal"),
]


def phase3(tmp_db_path: Path) -> dict[str, Any]:
    """Insert corrections and verify they appear cleanly in diffs."""
    log("\n=== Phase 3: Correction impact detection ===")

    tmp_store = MemoryStore(tmp_db_path)
    pre_snap = take_snapshot(tmp_store)
    log(f"Pre-correction snapshot: {len(pre_snap)} beliefs")

    results: list[dict[str, Any]] = []

    log("\n--- Correction Diff Summaries ---")

    for label, content in _CORRECTIONS:
        tmp_store.insert_belief(
            content=content,
            belief_type="correction",
            source_type="user_corrected",
            alpha=9.0,
            beta_param=0.5,
            locked=True,
        )

        post_snap = take_snapshot(tmp_store)
        d = diff_snapshots(pre_snap, post_snap)

        # Check: correction is the ONLY added belief
        is_clean = len(d.added) == 1

        # Check: correction appears in top-100 by confidence
        top_100 = _top_k_ids(post_snap)
        correction_in_top100 = any(
            b.belief_id in top_100 for b in d.added
        )

        expected_conf = 9.0 / (9.0 + 0.5)

        cr: dict[str, Any] = {
            "label": label,
            "content": content,
            "clean_signal": is_clean,
            "added_count": len(d.added),
            "in_top_100": correction_in_top100,
            "expected_confidence": round(expected_conf, 4),
            "top_100_turnover": round(d.top_k_turnover, 4),
        }
        results.append(cr)

        # Print formatted summary
        summary = diff_summary(
            f"pre-correction -> post-{label}", d, contents=content,
        )
        log(summary)

        log(f"  Clean signal: {is_clean}, In top-100: {correction_in_top100}")
        log("")

        # Update pre_snap for next correction
        pre_snap = post_snap

    return {"corrections": results}


# ---------------------------------------------------------------------------
# Phase 4: Noise floor measurement
# ---------------------------------------------------------------------------


def phase4(tmp_db_path: Path) -> dict[str, Any]:
    """Two snapshots 0.1s apart with no changes. Expect zero diff."""
    log("=== Phase 4: Noise floor measurement ===")

    tmp_store = MemoryStore(tmp_db_path)
    snap_a = take_snapshot(tmp_store)
    time.sleep(0.1)
    snap_b = take_snapshot(tmp_store)

    d = diff_snapshots(snap_a, snap_b)
    total_diffs = (
        len(d.added) + len(d.removed)
        + len(d.confidence_changed) + len(d.type_changed)
        + len(d.lock_changed)
    )

    result: dict[str, Any] = {
        "total_diffs": total_diffs,
        "added": len(d.added),
        "removed": len(d.removed),
        "confidence_changed": len(d.confidence_changed),
        "type_changed": len(d.type_changed),
        "lock_changed": len(d.lock_changed),
        "top_100_turnover": round(d.top_k_turnover, 4),
        "is_zero_noise": total_diffs == 0,
    }
    log(f"Noise floor: {total_diffs} total diffs (expected 0)")
    log(f"  Top-100 turnover: {result['top_100_turnover']}")
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    """Print to stderr."""
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    prod_db = Path.home() / ".agentmemory" / "memory.db"
    if not prod_db.exists():
        log(f"ERROR: Production DB not found at {prod_db}")
        sys.exit(1)

    # Open production store (read-only usage)
    prod_store = MemoryStore(prod_db)
    prod_snap = take_snapshot(prod_store)
    log(f"Production DB: {len(prod_snap)} active beliefs\n")

    # Phase 1: performance benchmarks on production data
    p1 = phase1(prod_store)

    # Create temp DB for phases 2-4
    tmp_dir = tempfile.mkdtemp(prefix="exp65_")
    tmp_db = Path(tmp_dir) / "memory.db"
    shutil.copy2(str(prod_db), str(tmp_db))
    # Copy WAL/SHM if they exist
    for suffix in ("-wal", "-shm"):
        extra = prod_db.parent / (prod_db.name + suffix)
        if extra.exists():
            shutil.copy2(str(extra), str(tmp_dir))

    try:
        # Phase 2: simulated drift
        p2 = phase2(prod_snap, tmp_db)

        # Phase 3: correction impact
        p3 = phase3(tmp_db)

        # Phase 4: noise floor
        p4 = phase4(tmp_db)

        # Assemble and write results
        all_results: dict[str, Any] = {
            "experiment": "exp65_hologram_diffing",
            "description": "Belief graph diffing and drift detection",
            "production_beliefs": len(prod_snap),
            "phase1_performance": p1,
            "phase2_drift": p2,
            "phase3_corrections": p3,
            "phase4_noise_floor": p4,
        }

        results_path = Path(__file__).parent / "exp65_results.json"
        with open(results_path, "w") as f:
            json.dump(all_results, f, indent=2)
        log(f"\nResults written to {results_path}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        log(f"Cleaned up temp dir: {tmp_dir}")


if __name__ == "__main__":
    main()
