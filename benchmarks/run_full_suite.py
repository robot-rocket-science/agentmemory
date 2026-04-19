"""Full benchmark suite runner for agentmemory.

Orchestrates all 5 benchmarks end-to-end following the contamination-proof
protocol in docs/BENCHMARK_PROTOCOL.md. This script handles Steps 0-2 and 4-5.
Step 3 (LLM reader predictions) is handled externally via Claude Code sub-agents.

Usage:
    uv run python benchmarks/run_full_suite.py --step retrieval
    uv run python benchmarks/run_full_suite.py --step verify
    uv run python benchmarks/run_full_suite.py --step score
    uv run python benchmarks/run_full_suite.py --step report
    uv run python benchmarks/run_full_suite.py --step all  # retrieval + verify only

Prediction generation (Step 3) must be done via sub-agents between
the 'verify' and 'score' steps.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTPUT_DIR: Final[str] = "/tmp/benchmark_v2"
BENCHMARKS: Final[list[str]] = [
    "mab_sh_262k",
    "mab_mh_262k",
    "locomo",
    "structmemeval",
    "longmemeval",
]


# File naming convention per protocol
def _paths(name: str) -> dict[str, Path]:
    d: Path = Path(OUTPUT_DIR)
    return {
        "retrieval": d / f"benchmark_{name}.json",
        "gt": d / f"benchmark_{name}_gt.json",
        "preds": d / f"benchmark_{name}_preds.json",
        "scores": d / f"benchmark_{name}_scores.json",
    }


# ---------------------------------------------------------------------------
# Step 0: Environment Verification
# ---------------------------------------------------------------------------


def verify_environment() -> dict[str, object]:
    """Verify git state and record audit info."""
    print("=" * 60)
    print("STEP 0: Environment Verification")
    print("=" * 60)

    # Git commit hash
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    commit: str = result.stdout.strip()
    print(f"  Git commit: {commit}")

    # Git status (should be clean for benchmarking)
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    status: str = result.stdout.strip()
    if status:
        print("  WARNING: Uncommitted changes detected:")
        for line in status.split("\n")[:10]:
            print(f"    {line}")
        print("  Results will note uncommitted changes in audit trail.")
    else:
        print("  Git status: clean")

    # Version from pyproject.toml
    result = subprocess.run(
        [
            "python",
            "-c",
            "import agentmemory; print(getattr(agentmemory, '__version__', 'unknown'))",
        ],
        capture_output=True,
        text=True,
    )
    version: str = result.stdout.strip() if result.returncode == 0 else "unknown"
    print(f"  agentmemory version: {version}")

    # Timestamp
    ts: str = datetime.now(timezone.utc).isoformat()
    print(f"  Timestamp: {ts}")

    # Create output directory
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    print(f"  Output dir: {OUTPUT_DIR}")
    print()

    return {
        "git_commit": commit,
        "git_dirty": bool(status),
        "version": version,
        "timestamp": ts,
    }


# ---------------------------------------------------------------------------
# Step 1-2: Data Acquisition + Retrieval
# ---------------------------------------------------------------------------


def run_retrieval(benchmark: str) -> dict[str, object]:
    """Run a single benchmark adapter in --retrieve-only mode."""
    paths: dict[str, Path] = _paths(benchmark)
    t0: float = time.monotonic()
    result: dict[str, object] = {"benchmark": benchmark, "status": "pending"}

    cmd: list[str]
    if benchmark == "mab_sh_262k":
        cmd = [
            "uv",
            "run",
            "python",
            "benchmarks/mab_adapter.py",
            "--split",
            "Conflict_Resolution",
            "--source",
            "factconsolidation_sh_262k",
            "--retrieve-only",
            str(paths["retrieval"]),
        ]
    elif benchmark == "mab_mh_262k":
        cmd = [
            "uv",
            "run",
            "python",
            "benchmarks/mab_entity_index_adapter.py",
            "--retrieve-only",
            str(paths["retrieval"]),
        ]
    elif benchmark == "locomo":
        cmd = [
            "uv",
            "run",
            "python",
            "benchmarks/locomo_adapter.py",
            "--retrieve-only",
            str(paths["retrieval"]),
        ]
    elif benchmark == "structmemeval":
        cmd = [
            "uv",
            "run",
            "python",
            "benchmarks/structmemeval_adapter.py",
            "--task",
            "location",
            "--bench",
            "small",
            "--retrieve-only",
            str(paths["retrieval"]),
        ]
    elif benchmark == "longmemeval":
        cmd = [
            "uv",
            "run",
            "python",
            "benchmarks/longmemeval_adapter.py",
            "--retrieve-only",
            str(paths["retrieval"]),
        ]
    else:
        print(f"  ERROR: Unknown benchmark '{benchmark}'")
        result["status"] = "error"
        result["error"] = f"Unknown benchmark: {benchmark}"
        return result

    print(f"  Running: {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    elapsed: float = time.monotonic() - t0

    if proc.returncode != 0:
        print(f"  FAILED (exit {proc.returncode})")
        print(f"  stderr: {proc.stderr[:500]}")
        result["status"] = "failed"
        result["error"] = proc.stderr[:500]
        result["elapsed_s"] = round(elapsed, 2)
        return result

    # Verify output files exist
    if not paths["retrieval"].exists():
        print(f"  ERROR: Retrieval file not created: {paths['retrieval']}")
        result["status"] = "failed"
        result["error"] = "Retrieval file not created"
        return result

    # Count items
    with paths["retrieval"].open("r", encoding="utf-8") as f:
        items: list[dict[str, object]] = json.load(f)
    n_items: int = len(items)

    # Check for GT file
    gt_exists: bool = paths["gt"].exists()
    n_gt: int = 0
    if gt_exists:
        with paths["gt"].open("r", encoding="utf-8") as f:
            gt: list[dict[str, object]] = json.load(f)
        n_gt = len(gt)

    print(f"  OK: {n_items} retrieval items, {n_gt} GT items, {elapsed:.1f}s")
    result["status"] = "ok"
    result["n_items"] = n_items
    result["n_gt"] = n_gt
    result["gt_file"] = gt_exists
    result["elapsed_s"] = round(elapsed, 2)
    result["stdout"] = proc.stdout[-500:]  # last 500 chars for audit
    return result


def run_all_retrievals() -> list[dict[str, object]]:
    """Run all benchmark adapters sequentially."""
    print("=" * 60)
    print("STEPS 1-2: Data Acquisition + Retrieval")
    print("=" * 60)

    results: list[dict[str, object]] = []
    for bench in BENCHMARKS:
        print(f"\n--- {bench} ---")
        r: dict[str, object] = run_retrieval(bench)
        results.append(r)

    # Summary
    print(f"\n{'=' * 60}")
    print("Retrieval Summary")
    print(f"{'=' * 60}")
    for r in results:
        status: str = str(r.get("status", "?"))
        name: str = str(r.get("benchmark", "?"))
        n: int = int(r.get("n_items", 0))  # type: ignore[arg-type]
        elapsed: float = float(r.get("elapsed_s", 0))  # type: ignore[arg-type]
        print(f"  {name:20s}  {status:6s}  n={n:5d}  {elapsed:7.1f}s")
    print()
    return results


# ---------------------------------------------------------------------------
# Step: Contamination Verification (MANDATORY)
# ---------------------------------------------------------------------------


def verify_contamination() -> dict[str, object]:
    """Run verify_clean.py on all retrieval files."""
    print("=" * 60)
    print("CONTAMINATION CHECK (mandatory)")
    print("=" * 60)

    all_clean: bool = True
    results: dict[str, str] = {}

    for bench in BENCHMARKS:
        paths: dict[str, Path] = _paths(bench)
        retrieval_path: Path = paths["retrieval"]

        if not retrieval_path.exists():
            print(f"  {bench}: SKIP (no retrieval file)")
            results[bench] = "skip"
            continue

        proc = subprocess.run(
            ["uv", "run", "python", "benchmarks/verify_clean.py", str(retrieval_path)],
            capture_output=True,
            text=True,
        )

        if proc.returncode == 0:
            print(f"  {bench}: CLEAN")
            results[bench] = "clean"
        else:
            print(f"  {bench}: CONTAMINATED")
            print(f"    {proc.stdout}")
            results[bench] = "contaminated"
            all_clean = False

    print()
    if all_clean:
        print("ALL FILES CLEAN - proceeding is safe")
    else:
        print(
            "CONTAMINATION FOUND - results from contaminated benchmarks are INVALID (0%)"
        )
        print("Fix the adapter(s) and re-run from Step 2 before proceeding.")

    return {"all_clean": all_clean, "per_benchmark": results}


# ---------------------------------------------------------------------------
# Step 4: Scoring
# ---------------------------------------------------------------------------


def score_mab(benchmark: str) -> dict[str, object]:
    """Score MAB SH or MH predictions using SEM metric."""
    paths: dict[str, Path] = _paths(benchmark)
    if not paths["preds"].exists():
        return {"benchmark": benchmark, "status": "no predictions file"}
    if not paths["gt"].exists():
        return {"benchmark": benchmark, "status": "no GT file"}

    with paths["preds"].open("r", encoding="utf-8") as f:
        preds: list[dict[str, object]] = json.load(f)
    with paths["gt"].open("r", encoding="utf-8") as f:
        gt: list[dict[str, object]] = json.load(f)

    # Import scoring function
    from benchmarks.mab_adapter import score_multi_answer

    correct: int = 0
    total: int = 0
    per_item: list[dict[str, object]] = []

    for i, pred in enumerate(preds):
        prediction: str = str(pred.get("llm_prediction", ""))
        gt_answers: list[str] = [str(a) for a in gt[i].get("answers", [])]  # type: ignore[union-attr]

        if not gt_answers:
            continue

        scores: dict[str, float] = score_multi_answer(prediction, gt_answers)
        sem: float = scores.get("substring_exact_match", 0.0)
        total += 1
        if sem > 0:
            correct += 1

        per_item.append(
            {
                "idx": i,
                "prediction": prediction[:200],
                "sem": sem,
            }
        )

    overall: float = correct / total * 100 if total > 0 else 0.0
    result: dict[str, object] = {
        "benchmark": benchmark,
        "metric": "substring_exact_match",
        "score_pct": round(overall, 1),
        "correct": correct,
        "total": total,
        "per_item": per_item,
    }

    # Write scores file
    with paths["scores"].open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result


def score_locomo() -> dict[str, object]:
    """Score LoCoMo predictions using F1 metric."""
    paths: dict[str, Path] = _paths("locomo")
    if not paths["preds"].exists():
        return {"benchmark": "locomo", "status": "no predictions file"}
    if not paths["gt"].exists():
        return {"benchmark": "locomo", "status": "no GT file"}

    # Use the protocol scoring script
    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "benchmarks/locomo_score_protocol.py",
            str(paths["preds"]),
            str(paths["gt"]),
            "--output",
            str(paths["scores"]),
        ],
        capture_output=True,
        text=True,
    )

    print(proc.stdout)
    if proc.returncode != 0:
        return {
            "benchmark": "locomo",
            "status": "scoring failed",
            "error": proc.stderr[:500],
        }

    if paths["scores"].exists():
        with paths["scores"].open("r", encoding="utf-8") as f:
            return json.load(f)

    return {"benchmark": "locomo", "status": "scored", "output": proc.stdout}


def score_structmemeval() -> dict[str, object]:
    """Score StructMemEval predictions using LLM judge accuracy."""
    paths: dict[str, Path] = _paths("structmemeval")
    if not paths["preds"].exists():
        return {"benchmark": "structmemeval", "status": "no predictions file"}
    if not paths["gt"].exists():
        return {"benchmark": "structmemeval", "status": "no GT file"}

    with paths["preds"].open("r", encoding="utf-8") as f:
        preds: list[dict[str, object]] = json.load(f)

    correct: int = 0
    total: int = len(preds)

    for pred in preds:
        verdict: str = str(pred.get("verdict", "")).lower()
        if verdict in ("correct", "yes", "true", "1"):
            correct += 1

    accuracy: float = correct / total * 100 if total > 0 else 0.0
    result: dict[str, object] = {
        "benchmark": "structmemeval",
        "metric": "accuracy",
        "score_pct": round(accuracy, 1),
        "correct": correct,
        "total": total,
    }

    with paths["scores"].open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result


def score_longmemeval() -> dict[str, object]:
    """Score LongMemEval predictions using LLM judge verdicts."""
    paths: dict[str, Path] = _paths("longmemeval")
    if not paths["preds"].exists():
        return {"benchmark": "longmemeval", "status": "no predictions file"}
    if not paths["gt"].exists():
        return {"benchmark": "longmemeval", "status": "no GT file"}

    # Preds file should include judge verdicts
    with paths["preds"].open("r", encoding="utf-8") as f:
        preds: list[dict[str, object]] = json.load(f)
    with paths["gt"].open("r", encoding="utf-8") as f:
        gt: list[dict[str, object]] = json.load(f)

    gt_by_id: dict[str, dict[str, object]] = {str(g["question_id"]): g for g in gt}

    correct_by_type: dict[str, int] = {}
    total_by_type: dict[str, int] = {}

    for pred in preds:
        qid: str = str(pred.get("question_id", ""))
        gt_entry: dict[str, object] | None = gt_by_id.get(qid)
        if gt_entry is None:
            continue

        qtype: str = str(gt_entry.get("question_type", "unknown"))
        verdict: str = str(pred.get("verdict", "incorrect")).lower()
        is_correct: bool = verdict in ("correct", "yes", "true", "1")

        total_by_type[qtype] = total_by_type.get(qtype, 0) + 1
        if is_correct:
            correct_by_type[qtype] = correct_by_type.get(qtype, 0) + 1

    total_correct: int = sum(correct_by_type.values())
    total_count: int = sum(total_by_type.values())
    overall: float = total_correct / total_count * 100 if total_count > 0 else 0.0

    category_results: dict[str, dict[str, object]] = {}
    for qtype in sorted(total_by_type.keys()):
        c: int = correct_by_type.get(qtype, 0)
        t: int = total_by_type[qtype]
        category_results[qtype] = {
            "correct": c,
            "total": t,
            "accuracy_pct": round(c / t * 100, 1) if t > 0 else 0.0,
        }

    result: dict[str, object] = {
        "benchmark": "longmemeval",
        "metric": "accuracy (Opus binary judge)",
        "score_pct": round(overall, 1),
        "correct": total_correct,
        "total": total_count,
        "per_category": category_results,
    }

    with paths["scores"].open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result


def run_all_scoring() -> list[dict[str, object]]:
    """Score all benchmarks."""
    print("=" * 60)
    print("STEP 4: Scoring")
    print("=" * 60)

    results: list[dict[str, object]] = []

    print("\n--- MAB SH 262K ---")
    results.append(score_mab("mab_sh_262k"))

    print("\n--- MAB MH 262K ---")
    results.append(score_mab("mab_mh_262k"))

    print("\n--- LoCoMo ---")
    results.append(score_locomo())

    print("\n--- StructMemEval ---")
    results.append(score_structmemeval())

    print("\n--- LongMemEval ---")
    results.append(score_longmemeval())

    # Summary
    print(f"\n{'=' * 60}")
    print("Scoring Summary")
    print(f"{'=' * 60}")
    for r in results:
        name: str = str(r.get("benchmark", "?"))
        metric: str = str(r.get("metric", "?"))
        score: float = float(r.get("score_pct", 0))  # type: ignore[arg-type]
        status: str = str(r.get("status", ""))
        if status:
            print(f"  {name:20s}  {status}")
        else:
            print(f"  {name:20s}  {metric}: {score:.1f}%")
    print()

    return results


# ---------------------------------------------------------------------------
# Step 5: Report
# ---------------------------------------------------------------------------

BASELINES: Final[dict[str, dict[str, str]]] = {
    "mab_sh_262k": {
        "metric": "SEM",
        "paper_best": "88% (GPT-4o)",
        "paper_mini": "45% (GPT-4o-mini)",
        "prior_v1.2.1": "90% (Opus)",
    },
    "mab_mh_262k": {
        "metric": "SEM",
        "paper_ceiling": "<=7% (all methods)",
        "prior_v1.2.1": "60% (Opus)",
    },
    "locomo": {
        "metric": "F1",
        "paper_best": "51.6% (GPT-4-turbo)",
        "prior_v1.2.1": "66.1% (Opus)",
    },
    "structmemeval": {
        "metric": "Accuracy",
        "paper_note": "vector stores fail",
        "prior_v1.2.1": "100% (14/14)",
    },
    "longmemeval": {
        "metric": "Accuracy (Opus judge)",
        "paper_best": "60.6% (GPT-4o)",
        "prior_v1.2.1": "59.0% (Opus)",
    },
}


def generate_report(
    env_info: dict[str, str],
    retrieval_results: list[dict[str, object]],
    contamination: dict[str, object],
    scoring_results: list[dict[str, object]],
    token_counts: dict[str, int] | None = None,
) -> str:
    """Generate the final benchmark report."""
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("BENCHMARK REPORT: agentmemory v2.2.2 Full Re-Run")
    lines.append("=" * 70)
    lines.append("")

    # Audit trail
    lines.append("## Audit Trail")
    lines.append(f"  Git commit:   {env_info.get('git_commit', 'unknown')}")
    lines.append(f"  Version:      {env_info.get('version', 'unknown')}")
    lines.append(f"  Timestamp:    {env_info.get('timestamp', 'unknown')}")
    lines.append(f"  Git dirty:    {env_info.get('git_dirty', 'unknown')}")
    lines.append("  Protocol:     docs/BENCHMARK_PROTOCOL.md")
    lines.append("  Reader model: Claude Opus 4.6 (sub-agent)")
    lines.append("")

    # Contamination status
    lines.append("## Contamination Check")
    all_clean: bool = bool(contamination.get("all_clean", False))
    lines.append(f"  Overall: {'ALL CLEAN' if all_clean else 'CONTAMINATION FOUND'}")
    per: dict[str, str] = contamination.get("per_benchmark", {})  # type: ignore[assignment]
    for bench, status in per.items():
        lines.append(f"  {bench:20s}  {status}")
    lines.append("")

    # Results table
    lines.append("## Results")
    lines.append("")
    lines.append(
        f"  {'Benchmark':20s}  {'Metric':8s}  {'Score':8s}  {'Prior v1.2.1':15s}  {'Paper Best':20s}"
    )
    lines.append(f"  {'-' * 20}  {'-' * 8}  {'-' * 8}  {'-' * 15}  {'-' * 20}")

    for sr in scoring_results:
        name: str = str(sr.get("benchmark", "?"))
        score: float = float(sr.get("score_pct", 0))  # type: ignore[arg-type]
        status: str = str(sr.get("status", ""))
        bl: dict[str, str] = BASELINES.get(name, {})
        metric: str = bl.get("metric", "?")
        prior: str = bl.get("prior_v1.2.1", "?")
        paper: str = bl.get(
            "paper_best", bl.get("paper_ceiling", bl.get("paper_note", "?"))
        )

        if status:
            lines.append(
                f"  {name:20s}  {metric:8s}  {'N/A':8s}  {prior:15s}  {paper:20s}  ({status})"
            )
        else:
            score_str: str = f"{score:.1f}%"
            lines.append(
                f"  {name:20s}  {metric:8s}  {score_str:8s}  {prior:15s}  {paper:20s}"
            )

    lines.append("")

    # Token counts
    if token_counts:
        lines.append("## Token Counts (sub-agent predictions)")
        for bench, count in token_counts.items():
            lines.append(f"  {bench:20s}  ~{count:,} tokens")
        lines.append("")

    # Retrieval timing
    lines.append("## Retrieval Timing")
    for rr in retrieval_results:
        name = str(rr.get("benchmark", "?"))
        elapsed: float = float(rr.get("elapsed_s", 0))  # type: ignore[arg-type]
        n: int = int(rr.get("n_items", 0))  # type: ignore[arg-type]
        lines.append(f"  {name:20s}  {elapsed:7.1f}s  n={n}")
    lines.append("")

    report: str = "\n".join(lines)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Run full agentmemory benchmark suite",
    )
    parser.add_argument(
        "--step",
        choices=["retrieval", "verify", "score", "report", "all"],
        required=True,
        help="Which step to run",
    )
    parser.add_argument(
        "--benchmark",
        choices=BENCHMARKS + ["all"],
        default="all",
        help="Which benchmark to run (default: all)",
    )
    args: argparse.Namespace = parser.parse_args()

    if args.step == "retrieval":
        verify_environment()
        if args.benchmark == "all":
            run_all_retrievals()
        else:
            run_retrieval(args.benchmark)
    elif args.step == "verify":
        verify_contamination()
    elif args.step == "score":
        run_all_scoring()
    elif args.step == "report":
        # Load saved state if available
        state_path: Path = Path(OUTPUT_DIR) / "suite_state.json"
        if state_path.exists():
            with state_path.open("r", encoding="utf-8") as f:
                state: dict[str, object] = json.load(f)
            report: str = generate_report(
                env_info=state.get("env", {}),  # type: ignore[arg-type]
                retrieval_results=state.get("retrieval", []),  # type: ignore[arg-type]
                contamination=state.get("contamination", {}),  # type: ignore[arg-type]
                scoring_results=state.get("scoring", []),  # type: ignore[arg-type]
                token_counts=state.get("token_counts"),  # type: ignore[arg-type]
            )
            print(report)
        else:
            print(f"No state file found at {state_path}")
            print("Run --step retrieval, --step verify, and --step score first.")
    elif args.step == "all":
        env: dict[str, object] = verify_environment()
        retrieval: list[dict[str, object]] = run_all_retrievals()
        contamination: dict[str, object] = verify_contamination()

        # Save state for later steps
        state: dict[str, object] = {
            "env": env,
            "retrieval": retrieval,
            "contamination": contamination,
        }
        state_path = Path(OUTPUT_DIR) / "suite_state.json"
        with state_path.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)
        print(f"State saved to {state_path}")
        print()
        print("Next: Generate predictions via sub-agents, then run --step score")


if __name__ == "__main__":
    main()
