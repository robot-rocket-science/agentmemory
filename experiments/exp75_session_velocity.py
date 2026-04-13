"""Experiment 75: Session Velocity Measurement and Calibration.

Phase 1: Reconstruct session boundaries from belief timestamps via gap detection.
Phase 2: Velocity profile analysis per session.
Phase 3: Compare velocity-scaled decay vs flat decay on locked/unlocked beliefs.
Phase 4: Calibrate the multiplier function (step vs continuous vs log).

Success criteria:
  - Session reconstruction produces boundaries consistent with known 14 sessions (+/- 2)
  - Velocity-scaled decay achieves >2.0x score separation (locked vs sprint-origin)
  - Velocity-scaled decay does not degrade MRR for locked beliefs vs flat decay
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH: str = str(
    Path.home() / ".agentmemory" / "projects" / "2e7ed55e017a" / "memory.db"
)
GAP_THRESHOLDS_MINUTES: list[int] = [15, 30, 60, 120]
EXPECTED_SESSIONS: int = 14


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ReconstructedSession:
    index: int
    start: datetime
    end: datetime
    belief_count: int
    correction_count: int
    locked_count: int
    duration_hours: float
    velocity: float  # beliefs / hour
    tier: str


@dataclass
class ScoredBelief:
    belief_id: str
    content: str
    belief_type: str
    locked: bool
    superseded: bool
    created_at: datetime
    session_idx: int
    flat_score: float
    velocity_score: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_iso(ts: str) -> datetime:
    dt: datetime = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def velocity_scale_step(velocity: float) -> float:
    """Exp 58c 4-tier step function."""
    if velocity > 10.0:
        return 0.1
    if velocity >= 5.0:
        return 0.5
    if velocity >= 2.0:
        return 0.8
    return 1.0


def velocity_scale_continuous(velocity: float) -> float:
    """Smooth sigmoid-like curve."""
    return max(0.1, 1.0 / (1.0 + velocity / 5.0))


def velocity_scale_log(velocity: float) -> float:
    """Logarithmic compression."""
    return max(0.1, 1.0 - 0.3 * math.log2(1.0 + velocity))


DECAY_HALF_LIVES: dict[str, float | None] = {
    "factual": 336.0,
    "preference": None,
    "correction": None,
    "requirement": None,
    "procedural": 504.0,
    "causal": 720.0,
    "relational": 336.0,
}


def flat_decay(belief_type: str, age_hours: float, locked: bool, superseded: bool) -> float:
    if superseded:
        return 0.01
    if locked:
        return 1.0
    half_life: float | None = DECAY_HALF_LIVES.get(belief_type)
    if half_life is None:
        return 1.0
    if age_hours <= 0.0:
        return 1.0
    return math.pow(0.5, age_hours / half_life)


def velocity_decay(
    belief_type: str,
    age_hours: float,
    locked: bool,
    superseded: bool,
    session_velocity: float,
    scale_fn: object,
) -> float:
    if superseded:
        return 0.01
    if locked:
        return 1.0
    half_life: float | None = DECAY_HALF_LIVES.get(belief_type)
    if half_life is None:
        return 1.0
    if age_hours <= 0.0:
        return 1.0
    # Scale half-life by velocity: fast sessions -> shorter effective half-life
    assert callable(scale_fn)
    effective_hl: float = half_life * scale_fn(session_velocity)
    if effective_hl <= 0.0:
        return 0.01
    return math.pow(0.5, age_hours / effective_hl)


# ---------------------------------------------------------------------------
# Phase 1: Reconstruct sessions
# ---------------------------------------------------------------------------


def reconstruct_sessions(
    conn: sqlite3.Connection, gap_minutes: int
) -> list[ReconstructedSession]:
    rows: list[sqlite3.Row] = conn.execute(
        """SELECT id, created_at, belief_type, source_type, locked, valid_to, superseded_by
           FROM beliefs ORDER BY created_at ASC"""
    ).fetchall()

    if not rows:
        return []

    gap_threshold: timedelta = timedelta(minutes=gap_minutes)
    sessions: list[ReconstructedSession] = []
    current_beliefs: list[sqlite3.Row] = [rows[0]]

    for i in range(1, len(rows)):
        prev_ts: datetime = parse_iso(rows[i - 1]["created_at"])
        curr_ts: datetime = parse_iso(rows[i]["created_at"])
        if (curr_ts - prev_ts) > gap_threshold:
            # Boundary found, finalize current session
            sessions.append(_finalize_session(current_beliefs, len(sessions)))
            current_beliefs = []
        current_beliefs.append(rows[i])

    # Finalize last session
    if current_beliefs:
        sessions.append(_finalize_session(current_beliefs, len(sessions)))

    return sessions


def _finalize_session(
    beliefs: list[sqlite3.Row], index: int
) -> ReconstructedSession:
    start: datetime = parse_iso(beliefs[0]["created_at"])
    end: datetime = parse_iso(beliefs[-1]["created_at"])
    duration: float = max(0.5, (end - start).total_seconds() / 3600.0)
    count: int = len(beliefs)
    corrections: int = sum(1 for b in beliefs if b["source_type"] == "user_corrected")
    locked: int = sum(1 for b in beliefs if b["locked"])
    velocity: float = count / duration

    tier: str
    if velocity > 10.0:
        tier = "sprint"
    elif velocity >= 5.0:
        tier = "moderate"
    elif velocity >= 2.0:
        tier = "steady"
    else:
        tier = "deep"

    return ReconstructedSession(
        index=index, start=start, end=end,
        belief_count=count, correction_count=corrections, locked_count=locked,
        duration_hours=duration, velocity=velocity, tier=tier,
    )


# ---------------------------------------------------------------------------
# Phase 2: Velocity profile
# ---------------------------------------------------------------------------


def print_velocity_profile(sessions: list[ReconstructedSession]) -> None:
    print("\n=== Phase 2: Velocity Profile ===\n")
    print(f"{'Sess':>4} {'Start':>19} {'Dur(h)':>7} {'Beliefs':>8} {'Corr':>5} {'Lock':>5} {'Vel':>8} {'Tier':>10}")
    print("-" * 85)
    for s in sessions:
        print(
            f"{s.index:>4} {s.start.strftime('%Y-%m-%d %H:%M'):>19} "
            f"{s.duration_hours:>7.1f} {s.belief_count:>8} {s.correction_count:>5} "
            f"{s.locked_count:>5} {s.velocity:>8.1f} {s.tier:>10}"
        )

    # Summary
    tiers: dict[str, int] = {}
    for s in sessions:
        tiers[s.tier] = tiers.get(s.tier, 0) + 1
    print(f"\nTier distribution: {tiers}")
    total_beliefs: int = sum(s.belief_count for s in sessions)
    total_hours: float = sum(s.duration_hours for s in sessions)
    print(f"Overall: {total_beliefs} beliefs in {total_hours:.1f} hours ({total_beliefs/max(1,total_hours):.1f} beliefs/hr)")


# ---------------------------------------------------------------------------
# Phase 3: Score comparison
# ---------------------------------------------------------------------------


def score_comparison(
    conn: sqlite3.Connection,
    sessions: list[ReconstructedSession],
) -> dict[str, object]:
    now: datetime = datetime.now(timezone.utc)

    # Build session lookup: belief created_at -> session index
    session_lookup: list[tuple[datetime, datetime, int, float]] = [
        (s.start, s.end, s.index, s.velocity) for s in sessions
    ]

    rows: list[sqlite3.Row] = conn.execute(
        "SELECT id, content, belief_type, source_type, locked, valid_to, superseded_by, created_at FROM beliefs"
    ).fetchall()

    scored: list[ScoredBelief] = []
    for row in rows:
        created: datetime = parse_iso(row["created_at"])
        age_hours: float = (now - created).total_seconds() / 3600.0
        locked: bool = bool(row["locked"])
        superseded: bool = row["superseded_by"] is not None or row["valid_to"] is not None
        belief_type: str = row["belief_type"]

        # Find session
        sess_idx: int = -1
        sess_vel: float = 0.0
        for s_start, s_end, s_idx, s_vel in session_lookup:
            if s_start <= created <= s_end + timedelta(seconds=1):
                sess_idx = s_idx
                sess_vel = s_vel
                break

        f_score: float = flat_decay(belief_type, age_hours, locked, superseded)
        v_score: float = velocity_decay(
            belief_type, age_hours, locked, superseded,
            sess_vel, velocity_scale_step,
        )

        scored.append(ScoredBelief(
            belief_id=row["id"], content=row["content"][:60],
            belief_type=belief_type, locked=locked, superseded=superseded,
            created_at=created, session_idx=sess_idx,
            flat_score=f_score, velocity_score=v_score,
        ))

    # Compute metrics
    locked_flat: list[float] = [s.flat_score for s in scored if s.locked and not s.superseded]
    locked_vel: list[float] = [s.velocity_score for s in scored if s.locked and not s.superseded]

    # Sprint-origin unlocked beliefs
    sprint_sessions: set[int] = {s.index for s in sessions if s.tier == "sprint"}
    sprint_unlocked_flat: list[float] = [
        s.flat_score for s in scored
        if s.session_idx in sprint_sessions and not s.locked and not s.superseded
    ]
    sprint_unlocked_vel: list[float] = [
        s.velocity_score for s in scored
        if s.session_idx in sprint_sessions and not s.locked and not s.superseded
    ]

    def mean(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    mean_locked_flat: float = mean(locked_flat)
    mean_locked_vel: float = mean(locked_vel)
    mean_sprint_flat: float = mean(sprint_unlocked_flat)
    mean_sprint_vel: float = mean(sprint_unlocked_vel)

    sep_flat: float = mean_locked_flat / mean_sprint_flat if mean_sprint_flat > 0 else float("inf")
    sep_vel: float = mean_locked_vel / mean_sprint_vel if mean_sprint_vel > 0 else float("inf")

    print("\n=== Phase 3: Score Comparison ===\n")
    print(f"Locked beliefs:  n={len(locked_flat)}")
    print(f"  Flat decay mean:     {mean_locked_flat:.4f}")
    print(f"  Velocity decay mean: {mean_locked_vel:.4f}")
    print(f"\nSprint-origin unlocked: n={len(sprint_unlocked_flat)}")
    print(f"  Flat decay mean:     {mean_sprint_flat:.4f}")
    print(f"  Velocity decay mean: {mean_sprint_vel:.4f}")
    print(f"\nSeparation ratio (locked / sprint-unlocked):")
    print(f"  Flat:     {sep_flat:.3f}x")
    print(f"  Velocity: {sep_vel:.3f}x")
    print(f"  Target: >2.0x")
    print(f"  PASS: {sep_vel > 2.0}")

    return {
        "locked_count": len(locked_flat),
        "sprint_unlocked_count": len(sprint_unlocked_flat),
        "mean_locked_flat": mean_locked_flat,
        "mean_locked_velocity": mean_locked_vel,
        "mean_sprint_flat": mean_sprint_flat,
        "mean_sprint_velocity": mean_sprint_vel,
        "separation_flat": sep_flat,
        "separation_velocity": sep_vel,
        "pass": sep_vel > 2.0,
    }


# ---------------------------------------------------------------------------
# Phase 4: Calibrate multiplier
# ---------------------------------------------------------------------------


def calibrate_multiplier(
    conn: sqlite3.Connection,
    sessions: list[ReconstructedSession],
) -> dict[str, float]:
    now: datetime = datetime.now(timezone.utc)
    session_lookup: list[tuple[datetime, datetime, float]] = [
        (s.start, s.end, s.velocity) for s in sessions
    ]
    sprint_sessions: set[int] = {s.index for s in sessions if s.tier == "sprint"}

    rows: list[sqlite3.Row] = conn.execute(
        "SELECT belief_type, locked, valid_to, superseded_by, created_at FROM beliefs"
    ).fetchall()

    scale_fns: dict[str, object] = {
        "step": velocity_scale_step,
        "continuous": velocity_scale_continuous,
        "log": velocity_scale_log,
    }
    results: dict[str, float] = {}

    for name, fn in scale_fns.items():
        locked_scores: list[float] = []
        sprint_scores: list[float] = []
        for row in rows:
            created: datetime = parse_iso(row["created_at"])
            age_hours: float = (now - created).total_seconds() / 3600.0
            locked: bool = bool(row["locked"])
            superseded: bool = row["superseded_by"] is not None or row["valid_to"] is not None

            sess_vel: float = 0.0
            sess_idx: int = -1
            for i, (s_start, s_end, s_vel) in enumerate(session_lookup):
                if s_start <= created <= s_end + timedelta(seconds=1):
                    sess_vel = s_vel
                    sess_idx = i
                    break

            score: float = velocity_decay(
                row["belief_type"], age_hours, locked, superseded, sess_vel, fn,
            )
            if locked and not superseded:
                locked_scores.append(score)
            elif sess_idx in sprint_sessions and not locked and not superseded:
                sprint_scores.append(score)

        mean_l: float = sum(locked_scores) / len(locked_scores) if locked_scores else 0.0
        mean_s: float = sum(sprint_scores) / len(sprint_scores) if sprint_scores else 0.0
        sep: float = mean_l / mean_s if mean_s > 0 else float("inf")
        results[name] = sep

    print("\n=== Phase 4: Multiplier Calibration ===\n")
    print(f"{'Function':>12} {'Separation':>12}")
    print("-" * 26)
    for name, sep in sorted(results.items(), key=lambda x: -x[1]):
        print(f"{name:>12} {sep:>12.3f}x")
    best: str = max(results, key=lambda k: results[k])
    print(f"\nBest: {best} ({results[best]:.3f}x)")
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    conn: sqlite3.Connection = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Phase 1: Reconstruct sessions at different gap thresholds
    print("=== Phase 1: Session Boundary Reconstruction ===\n")
    best_sessions: list[ReconstructedSession] = []
    best_gap: int = 30
    for gap in GAP_THRESHOLDS_MINUTES:
        sessions: list[ReconstructedSession] = reconstruct_sessions(conn, gap)
        diff: int = abs(len(sessions) - EXPECTED_SESSIONS)
        print(f"  Gap={gap:>3}min -> {len(sessions)} sessions (diff from expected: {diff})")
        if not best_sessions or diff < abs(len(best_sessions) - EXPECTED_SESSIONS):
            best_sessions = sessions
            best_gap = gap

    print(f"\nBest gap: {best_gap} minutes ({len(best_sessions)} sessions)")

    # Phase 2
    print_velocity_profile(best_sessions)

    # Phase 3
    metrics: dict[str, object] = score_comparison(conn, best_sessions)

    # Phase 4
    calibration: dict[str, float] = calibrate_multiplier(conn, best_sessions)

    # Save results
    results: dict[str, object] = {
        "gap_threshold_minutes": best_gap,
        "session_count": len(best_sessions),
        "sessions": [
            {
                "index": s.index,
                "start": s.start.isoformat(),
                "end": s.end.isoformat(),
                "belief_count": s.belief_count,
                "correction_count": s.correction_count,
                "locked_count": s.locked_count,
                "duration_hours": s.duration_hours,
                "velocity": s.velocity,
                "tier": s.tier,
            }
            for s in best_sessions
        ],
        "score_comparison": metrics,
        "calibration": calibration,
    }

    out_path: Path = Path(__file__).parent / "exp75_session_velocity_results.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nResults saved to {out_path}")

    conn.close()


if __name__ == "__main__":
    main()
