"""Experiment: Do LLMs reason better about time with Julian dates vs ISO strings vs relative format?

Hypothesis: Julian dates (monotonic floats) are easier for LLMs to compare than ISO strings.
Design: 20 temporal reasoning tasks x 3 conditions (ISO, JULIAN, RELATIVE).
Model: claude-haiku-4-5-20251001
"""

from __future__ import annotations

import json
import random
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

TaskType = Literal["ORDERING", "RECENCY", "GAP", "SEQUENCE", "WINDOW"]
Condition = Literal["ISO", "JULIAN", "RELATIVE"]

TASK_TYPES: list[TaskType] = ["ORDERING", "RECENCY", "GAP", "SEQUENCE", "WINDOW"]
CONDITIONS: list[Condition] = ["ISO", "JULIAN", "RELATIVE"]
TASKS_PER_TYPE = 4
MODEL = "claude-haiku-4-5-20251001"
MAX_CONCURRENT = 5
DB_PATH = Path.home() / ".agentmemory" / "memory.db"
RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

# J2000 epoch for Julian date conversion
J2000_EPOCH = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
J2000_JD = 2451545.0


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Belief:
    id: str
    content: str
    created_at: datetime


@dataclass
class TaskResult:
    task_id: int
    task_type: TaskType
    condition: Condition
    correct: bool
    expected: str
    got: str
    latency_s: float
    raw_response: str


@dataclass
class Task:
    task_id: int
    task_type: TaskType
    beliefs: list[Belief]
    ground_truth: str  # canonical answer
    results: list[TaskResult] = field(default_factory=lambda: list[TaskResult]())


# ---------------------------------------------------------------------------
# Timestamp conversions
# ---------------------------------------------------------------------------


def to_julian(dt: datetime) -> float:
    """Convert datetime to Julian Date using J2000 offset method."""
    delta = dt - J2000_EPOCH
    return J2000_JD + delta.total_seconds() / 86400.0


def to_relative(dt: datetime, now: datetime) -> str:
    """Convert datetime to human-readable relative string like '3 days 2 hours ago'."""
    diff = now - dt
    total_seconds = int(diff.total_seconds())
    if total_seconds < 0:
        return "in the future"

    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    parts: list[str] = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0 and days == 0:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if seconds > 0 and days == 0 and hours == 0:
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
    if not parts:
        return "just now"
    return " ".join(parts) + " ago"


def format_timestamp(dt: datetime, condition: Condition, now: datetime) -> str:
    """Format a datetime according to the experimental condition."""
    if condition == "ISO":
        return dt.isoformat()
    elif condition == "JULIAN":
        return f"{to_julian(dt):.6f}"
    else:
        return to_relative(dt, now)


# ---------------------------------------------------------------------------
# Database access
# ---------------------------------------------------------------------------


def load_beliefs() -> list[Belief]:
    """Load beliefs from the agentmemory database. If fewer than 20 beliefs exist,
    generate synthetic time offsets to create enough spread for the experiment."""
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT id, content, created_at FROM beliefs ORDER BY created_at"
    ).fetchall()
    conn.close()

    raw_beliefs: list[Belief] = []
    for row in rows:
        bid: str = row[0]
        content: str = row[1]
        ts_str: str = row[2]
        dt = datetime.fromisoformat(ts_str)
        raw_beliefs.append(Belief(id=bid, content=content, created_at=dt))

    if not raw_beliefs:
        print("ERROR: No beliefs found in database. Cannot run experiment.", file=sys.stderr)
        sys.exit(1)

    # We need enough beliefs with meaningful time spread.
    # If the DB has < 30 beliefs or tight clustering, generate synthetic offsets.
    min_needed = 30
    if len(raw_beliefs) >= min_needed:
        # Check time spread
        span = (raw_beliefs[-1].created_at - raw_beliefs[0].created_at).total_seconds()
        if span > 3600:  # at least 1 hour spread
            return raw_beliefs

    # Generate synthetic beliefs with realistic time spread
    print(f"  Database has {len(raw_beliefs)} beliefs with narrow time spread.")
    print("  Generating synthetic time offsets for experimental variety.")
    base_time = raw_beliefs[0].created_at
    synthetic: list[Belief] = []
    rng = random.Random(42)  # deterministic

    # Create 40 beliefs spread over ~30 days
    for i in range(40):
        offset_hours = rng.uniform(0, 30 * 24)  # 0 to 30 days in hours
        dt = base_time + timedelta(hours=offset_hours)
        src = raw_beliefs[i % len(raw_beliefs)]
        label = f"[syn-{i:02d}]"
        synthetic.append(Belief(
            id=f"syn_{i:04d}",
            content=f"{label} {src.content}",
            created_at=dt,
        ))

    synthetic.sort(key=lambda b: b.created_at)
    return synthetic


# ---------------------------------------------------------------------------
# Task generation
# ---------------------------------------------------------------------------


def generate_tasks(beliefs: list[Belief]) -> list[Task]:
    """Generate 20 tasks: 4 per task type."""
    rng = random.Random(42)
    tasks: list[Task] = []
    task_id = 0

    for task_type in TASK_TYPES:
        for _ in range(TASKS_PER_TYPE):
            task = _make_task(task_id, task_type, beliefs, rng)
            tasks.append(task)
            task_id += 1

    return tasks


def _make_task(
    task_id: int, task_type: TaskType, beliefs: list[Belief], rng: random.Random
) -> Task:
    """Create a single task with ground truth."""
    if task_type == "ORDERING":
        pair = rng.sample(beliefs, 2)
        older = min(pair, key=lambda b: b.created_at)
        return Task(
            task_id=task_id, task_type=task_type, beliefs=pair,
            ground_truth=older.id,
        )

    elif task_type == "RECENCY":
        group = rng.sample(beliefs, 5)
        newest = max(group, key=lambda b: b.created_at)
        return Task(
            task_id=task_id, task_type=task_type, beliefs=group,
            ground_truth=newest.id,
        )

    elif task_type == "GAP":
        pair = rng.sample(beliefs, 2)
        pair.sort(key=lambda b: b.created_at)
        diff = pair[1].created_at - pair[0].created_at
        total_hours = diff.total_seconds() / 3600.0
        if total_hours >= 48:
            gap_str = f"{total_hours / 24:.1f} days"
        else:
            gap_str = f"{total_hours:.1f} hours"
        return Task(
            task_id=task_id, task_type=task_type, beliefs=pair,
            ground_truth=gap_str,
        )

    elif task_type == "SEQUENCE":
        group = rng.sample(beliefs, 3)
        ordered = sorted(group, key=lambda b: b.created_at)
        order_str = ",".join(b.id for b in ordered)
        return Task(
            task_id=task_id, task_type=task_type, beliefs=group,
            ground_truth=order_str,
        )

    else:  # WINDOW
        anchor = rng.choice(beliefs)
        candidates = [b for b in beliefs if b.id != anchor.id]
        picked = rng.sample(candidates, min(4, len(candidates)))
        window_hrs = 24.0
        within: list[str] = []
        for b in picked:
            gap = abs((b.created_at - anchor.created_at).total_seconds()) / 3600.0
            if gap <= window_hrs:
                within.append(b.id)
        within.sort()
        truth = ",".join(within) if within else "none"
        all_beliefs = [anchor] + picked
        return Task(
            task_id=task_id, task_type=task_type, beliefs=all_beliefs,
            ground_truth=truth,
        )


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_prompt(task: Task, condition: Condition, now: datetime) -> str:
    """Build the LLM prompt for a given task and condition."""
    beliefs = task.beliefs

    def fmt(b: Belief) -> str:
        ts = format_timestamp(b.created_at, condition, now)
        return f'  ID: {b.id}\n  Timestamp: {ts}\n  Content: "{b.content[:80]}"'

    if task.task_type == "ORDERING":
        belief_block = "\n\n".join(fmt(b) for b in beliefs)
        return (
            "Below are two beliefs with timestamps. "
            "Which belief was created first? "
            "Reply with ONLY the ID of the older belief, nothing else.\n\n"
            f"{belief_block}"
        )

    elif task.task_type == "RECENCY":
        belief_block = "\n\n".join(fmt(b) for b in beliefs)
        return (
            "Below are five beliefs with timestamps. "
            "Which belief is the most recent (newest)? "
            "Reply with ONLY the ID of the most recent belief, nothing else.\n\n"
            f"{belief_block}"
        )

    elif task.task_type == "GAP":
        belief_block = "\n\n".join(fmt(b) for b in beliefs)
        return (
            "Below are two beliefs with timestamps. "
            "How much time passed between them? "
            "If 48 hours or more, reply in the format 'X.X days'. "
            "If less than 48 hours, reply in the format 'X.X hours'. "
            "Reply with ONLY the number and unit, nothing else.\n\n"
            f"{belief_block}"
        )

    elif task.task_type == "SEQUENCE":
        belief_block = "\n\n".join(fmt(b) for b in beliefs)
        return (
            "Below are three beliefs with timestamps. "
            "Put them in chronological order (oldest first). "
            "Reply with ONLY the IDs separated by commas, nothing else. "
            "Example format: id1,id2,id3\n\n"
            f"{belief_block}"
        )

    else:  # WINDOW
        anchor = beliefs[0]
        candidates = beliefs[1:]
        anchor_block = fmt(anchor)
        cand_block = "\n\n".join(fmt(b) for b in candidates)
        return (
            "Below is an anchor belief and four candidate beliefs, each with timestamps. "
            "Which candidates were created within 24 hours of the anchor? "
            "Reply with ONLY the IDs of matching candidates separated by commas. "
            "If none match, reply 'none'.\n\n"
            f"ANCHOR:\n{anchor_block}\n\n"
            f"CANDIDATES:\n{cand_block}"
        )


# ---------------------------------------------------------------------------
# API calling
# ---------------------------------------------------------------------------


def call_llm(prompt: str) -> tuple[str, float]:
    """Call Claude via CLI subagent and return (response_text, latency_seconds)."""
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            [
                "claude",
                "-p", prompt,
                "--model", MODEL,
                "--max-turns", "1",
                "--output-format", "text",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        latency = time.monotonic() - t0
        return result.stdout.strip(), latency
    except subprocess.TimeoutExpired:
        latency = time.monotonic() - t0
        return "[TIMEOUT]", latency


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_response(task: Task, response: str) -> tuple[bool, str]:
    """Score an LLM response against ground truth. Returns (correct, parsed_answer)."""
    cleaned = response.strip().strip('"').strip("'").strip()

    if task.task_type in ("ORDERING", "RECENCY"):
        return cleaned == task.ground_truth, cleaned

    elif task.task_type == "GAP":
        # Parse numeric value and compare within tolerance
        expected = task.ground_truth  # e.g. "12.3 hours" or "5.2 days"
        try:
            exp_parts = expected.split()
            exp_val = float(exp_parts[0])
            exp_unit = exp_parts[1]

            resp_parts = cleaned.split()
            resp_val = float(resp_parts[0])
            resp_unit = resp_parts[1].rstrip("s").rstrip(".")

            # Normalize to hours
            exp_hours = exp_val * 24.0 if "day" in exp_unit else exp_val
            resp_hours = resp_val * 24.0 if "day" in resp_unit else resp_val

            # 10% tolerance
            if exp_hours > 0:
                rel_err = abs(resp_hours - exp_hours) / exp_hours
                return rel_err < 0.10, cleaned
            return abs(resp_hours - exp_hours) < 0.5, cleaned
        except (ValueError, IndexError):
            return False, cleaned

    elif task.task_type == "SEQUENCE":
        # Compare comma-separated ID sequences
        expected_ids = task.ground_truth.split(",")
        got_ids = [s.strip() for s in cleaned.split(",")]
        return expected_ids == got_ids, cleaned

    else:  # WINDOW
        expected_set: set[str] = set(task.ground_truth.split(",")) if task.ground_truth != "none" else set()
        if cleaned.lower() == "none":
            got_set: set[str] = set()
        else:
            got_set = {s.strip() for s in cleaned.split(",")}
        return expected_set == got_set, cleaned


# ---------------------------------------------------------------------------
# Main experiment loop
# ---------------------------------------------------------------------------


def run_experiment() -> dict[str, Any]:
    """Run the full experiment and return results."""
    print("=" * 60)
    print("Experiment: Temporal Format Reasoning (ISO vs Julian vs Relative)")
    print("=" * 60)

    # Load beliefs
    print("\n[1/4] Loading beliefs from database...")
    beliefs = load_beliefs()
    print(f"  Loaded {len(beliefs)} beliefs.")

    # Generate tasks
    print("\n[2/4] Generating 20 tasks (4 per type)...")
    tasks = generate_tasks(beliefs)
    for t in tasks:
        print(f"  Task {t.task_id:2d}: {t.task_type:<10s} ({len(t.beliefs)} beliefs)")

    # Run LLM calls
    total = len(tasks) * len(CONDITIONS)
    print(f"\n[3/4] Running {total} LLM calls ({MODEL})...")
    now = datetime.now(timezone.utc)

    completed = 0
    all_results: list[TaskResult] = []

    for task_obj in tasks:
        for cond in CONDITIONS:
            prompt = build_prompt(task_obj, cond, now)
            response_text, latency = call_llm(prompt)
            correct, parsed = score_response(task_obj, response_text)
            result = TaskResult(
                task_id=task_obj.task_id,
                task_type=task_obj.task_type,
                condition=cond,
                correct=correct,
                expected=task_obj.ground_truth,
                got=parsed,
                latency_s=latency,
                raw_response=response_text,
            )
            task_obj.results.append(result)
            all_results.append(result)
            completed += 1
            status = "OK" if correct else "WRONG"
            print(f"  [{completed:2d}/{total}] Task {task_obj.task_id:2d} {cond:<8s} {status:<5s} ({latency:.2f}s)")

    # Compute report
    print("\n[4/4] Computing results...\n")
    report = compute_report(all_results)
    print_report(report)

    # Save detailed results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"exp_temporal_format_{ts_str}.json"
    serializable: dict[str, Any] = {
        "metadata": {
            "model": MODEL,
            "num_tasks": len(tasks),
            "conditions": list(CONDITIONS),
            "task_types": list(TASK_TYPES),
            "run_at": datetime.now(timezone.utc).isoformat(),
            "num_beliefs_used": len(beliefs),
        },
        "report": report,
        "results": [asdict(r) for r in all_results],
    }
    out_path.write_text(json.dumps(serializable, indent=2))
    print(f"\nDetailed results saved to: {out_path}")

    return report


def compute_report(results: list[TaskResult]) -> dict[str, Any]:
    """Aggregate results into a summary report."""
    report: dict[str, Any] = {}

    # Per-condition accuracy
    cond_stats: dict[str, dict[str, float]] = {}
    for cond in CONDITIONS:
        cond_results = [r for r in results if r.condition == cond]
        n = len(cond_results)
        correct = sum(1 for r in cond_results if r.correct)
        avg_lat = sum(r.latency_s for r in cond_results) / n if n > 0 else 0.0
        cond_stats[cond] = {
            "accuracy_pct": (correct / n * 100) if n > 0 else 0.0,
            "correct": float(correct),
            "total": float(n),
            "avg_latency_s": round(avg_lat, 3),
        }
    report["per_condition"] = cond_stats

    # Per-task-type accuracy breakdown by condition
    type_stats: dict[str, dict[str, dict[str, float]]] = {}
    for tt in TASK_TYPES:
        type_stats[tt] = {}
        for cond in CONDITIONS:
            subset = [r for r in results if r.task_type == tt and r.condition == cond]
            n = len(subset)
            correct = sum(1 for r in subset if r.correct)
            type_stats[tt][cond] = {
                "accuracy_pct": (correct / n * 100) if n > 0 else 0.0,
                "correct": float(correct),
                "total": float(n),
            }
    report["per_task_type"] = type_stats

    # Winner
    best_cond = max(CONDITIONS, key=lambda c: cond_stats[c]["accuracy_pct"])
    report["winner"] = best_cond
    report["summary"] = (
        f"{best_cond} format had the highest overall accuracy at "
        f"{cond_stats[best_cond]['accuracy_pct']:.1f}%."
    )

    return report


def print_report(report: dict[str, Any]) -> None:
    """Print a human-readable report to stdout."""
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)

    print("\nOverall Accuracy by Condition:")
    print(f"  {'Condition':<12s} {'Accuracy':>10s} {'Correct':>10s} {'Latency':>10s}")
    print(f"  {'-'*12} {'-'*10} {'-'*10} {'-'*10}")
    per_cond: dict[str, Any] = report["per_condition"]
    for cond in CONDITIONS:
        stats: dict[str, float] = per_cond[cond]
        print(
            f"  {cond:<12s} {stats['accuracy_pct']:>9.1f}% "
            f"{int(stats['correct']):>5d}/{int(stats['total']):<4d} "
            f"{stats['avg_latency_s']:>9.3f}s"
        )

    print("\nAccuracy by Task Type and Condition:")
    per_type: dict[str, Any] = report["per_task_type"]
    for tt in TASK_TYPES:
        print(f"\n  {tt}:")
        for cond in CONDITIONS:
            s: dict[str, float] = per_type[tt][cond]
            print(f"    {cond:<10s} {s['accuracy_pct']:>6.1f}%  ({int(s['correct'])}/{int(s['total'])})")

    print(f"\nWinner: {report['winner']}")
    print(f"Summary: {report['summary']}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    run_experiment()


if __name__ == "__main__":
    main()
