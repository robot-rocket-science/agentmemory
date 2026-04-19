"""Benchmark protocol enforcement test suite.

Codifies docs/BENCHMARK_PROTOCOL.md + Lin methodology checklist as
executable pytest contracts. Every protocol violation is a test failure.

Run modes:
    # Validate existing output files (fast)
    uv run pytest benchmarks/test_benchmark_suite.py -v

    # Run retrieval + validate (slow, produces new data)
    uv run pytest benchmarks/test_benchmark_suite.py -v -m retrieval --run-retrieval

    # Run scoring on existing predictions
    uv run pytest benchmarks/test_benchmark_suite.py -v -m scoring

    # Full pipeline (retrieval + contamination + scoring)
    uv run pytest benchmarks/test_benchmark_suite.py -v --run-retrieval

Marks:
    retrieval: tests that run the slow adapter step
    contamination: contamination verification tests
    scoring: tests that score predictions
    protocol: protocol metadata enforcement
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Final

import pytest

from benchmarks.conftest import (
    BENCHMARK_IDS,
    LOCOMO_CEILING,
    METHODOLOGY_REQUIRED,
    BenchmarkPaths,
    check_contamination,
    check_unknown_keys,
    extract_all_keys,
    load_json_file,
)


# ---------------------------------------------------------------------------
# Custom pytest options
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-retrieval",
        action="store_true",
        default=False,
        help="Run the slow retrieval adapters (default: skip, validate existing files)",
    )


# ---------------------------------------------------------------------------
# Adapter commands per benchmark
# ---------------------------------------------------------------------------

ADAPTER_COMMANDS: Final[dict[str, list[str]]] = {
    "mab_sh_262k": [
        "uv",
        "run",
        "python",
        "benchmarks/mab_adapter.py",
        "--split",
        "Conflict_Resolution",
        "--source",
        "factconsolidation_sh_262k",
    ],
    "mab_mh_262k": [
        "uv",
        "run",
        "python",
        "benchmarks/mab_entity_index_adapter.py",
    ],
    "locomo": [
        "uv",
        "run",
        "python",
        "benchmarks/locomo_adapter.py",
    ],
    "structmemeval": [
        "uv",
        "run",
        "python",
        "benchmarks/structmemeval_adapter.py",
        "--task",
        "location",
        "--bench",
        "small",
    ],
    "longmemeval": [
        "uv",
        "run",
        "python",
        "benchmarks/longmemeval_adapter.py",
    ],
}

# Expected item counts per published papers
EXPECTED_COUNTS: Final[dict[str, dict[str, int]]] = {
    "mab_sh_262k": {"min_items": 90, "max_items": 110},
    "mab_mh_262k": {"min_items": 90, "max_items": 110},
    "locomo": {"min_items": 1900, "max_items": 2000},
    "structmemeval": {"min_items": 10, "max_items": 20},
    "longmemeval": {"min_items": 490, "max_items": 510},
}

# Published baselines for comparison
PUBLISHED_BASELINES: Final[dict[str, dict[str, object]]] = {
    "mab_sh_262k": {
        "metric": "SEM",
        "paper_best": 88.0,
        "paper_best_label": "GPT-4o",
        "prior_v1.2.1": 90.0,
    },
    "mab_mh_262k": {
        "metric": "SEM",
        "paper_ceiling": 7.0,
        "paper_ceiling_label": "all methods",
        "prior_v1.2.1": 60.0,
    },
    "locomo": {
        "metric": "F1",
        "paper_best": 51.6,
        "paper_best_label": "GPT-4-turbo",
        "prior_v1.2.1": 66.1,
    },
    "structmemeval": {
        "metric": "Accuracy",
        "prior_v1.2.1": 100.0,
    },
    "longmemeval": {
        "metric": "Accuracy (Opus judge)",
        "paper_best": 60.6,
        "paper_best_label": "GPT-4o",
        "prior_v1.2.1": 59.0,
    },
}


# =====================================================================
# STEP 0: Environment Verification
# =====================================================================


class TestEnvironment:
    """Protocol Step 0: verify clean environment for benchmarking."""

    def test_git_commit_recorded(self, git_commit: str) -> None:
        """Audit trail requires a recorded git commit hash."""
        assert len(git_commit) == 40, f"Invalid git hash: {git_commit}"

    def test_output_dir_exists(self, output_dir: Path) -> None:
        """Output directory must exist."""
        assert output_dir.exists()
        assert output_dir.is_dir()


# =====================================================================
# STEP 2: Retrieval (Adapter Run) -- only with --run-retrieval flag
# =====================================================================


class TestRetrieval:
    """Protocol Steps 1-2: data acquisition and retrieval.

    These tests are SLOW (minutes per benchmark). Only run with --run-retrieval.
    They produce the retrieval + GT files that subsequent tests validate.
    """

    @pytest.mark.retrieval
    @pytest.mark.parametrize("benchmark_id", BENCHMARK_IDS)
    def test_adapter_produces_output(
        self,
        benchmark_id: str,
        output_dir: Path,
        request: pytest.FixtureRequest,
    ) -> None:
        """Run adapter in --retrieve-only mode and verify output files."""
        if not request.config.getoption("--run-retrieval"):
            pytest.skip("Retrieval tests require --run-retrieval flag")

        paths: BenchmarkPaths = BenchmarkPaths(name=benchmark_id, output_dir=output_dir)
        cmd: list[str] = ADAPTER_COMMANDS[benchmark_id] + [
            "--retrieve-only",
            str(paths.retrieval),
        ]

        t0: float = time.monotonic()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,
        )
        elapsed: float = time.monotonic() - t0

        # Contract: adapter must exit 0
        assert result.returncode == 0, (
            f"Adapter failed for {benchmark_id} (exit {result.returncode}):\n"
            f"{result.stderr[:1000]}"
        )

        # Contract: retrieval file must exist
        assert paths.retrieval.exists(), (
            f"Adapter did not produce retrieval file: {paths.retrieval}"
        )

        # Contract: GT file must exist (separate from retrieval)
        assert paths.gt.exists(), (
            f"Adapter did not produce GT file: {paths.gt}\n"
            f"This is a protocol violation: GT must be in a separate file."
        )

        # Contract: item count within expected range
        data: list[dict[str, object]] = load_json_file(paths.retrieval)
        expected: dict[str, int] = EXPECTED_COUNTS[benchmark_id]
        assert expected["min_items"] <= len(data) <= expected["max_items"], (
            f"{benchmark_id}: got {len(data)} items, "
            f"expected {expected['min_items']}-{expected['max_items']}"
        )

        # Record timing for audit
        timing_path: Path = output_dir / f"benchmark_{benchmark_id}_timing.json"
        with timing_path.open("w", encoding="utf-8") as f:
            json.dump({"elapsed_s": round(elapsed, 2), "n_items": len(data)}, f)


# =====================================================================
# CONTAMINATION CHECK (Mandatory -- Protocol Step 2 post-condition)
# =====================================================================


class TestContamination:
    """Mandatory contamination verification.

    Any contamination = automatic 0% and test FAILURE.
    This is the single most important test in the suite.
    """

    @pytest.mark.contamination
    @pytest.mark.parametrize("benchmark_id", BENCHMARK_IDS)
    def test_retrieval_file_has_no_banned_keys(
        self,
        benchmark_id: str,
        output_dir: Path,
    ) -> None:
        """Protocol: retrieval file MUST NOT contain any answer/score keys."""
        paths: BenchmarkPaths = BenchmarkPaths(name=benchmark_id, output_dir=output_dir)
        if not paths.retrieval.exists():
            pytest.skip(f"No retrieval file for {benchmark_id}")

        data: list[dict[str, object]] = load_json_file(paths.retrieval)
        leaked: set[str] = check_contamination(data)

        assert not leaked, (
            f"CONTAMINATION in {benchmark_id}!\n"
            f"Banned keys found: {sorted(leaked)}\n"
            f"All keys: {sorted(extract_all_keys(data))}\n"
            f"VERDICT: INVALID. Results are automatically 0%.\n"
            f"Fix the adapter and re-run from Step 2."
        )

    @pytest.mark.contamination
    @pytest.mark.parametrize("benchmark_id", BENCHMARK_IDS)
    def test_retrieval_file_keys_reviewed(
        self,
        benchmark_id: str,
        output_dir: Path,
    ) -> None:
        """All keys in retrieval file must be either safe or explicitly reviewed."""
        paths: BenchmarkPaths = BenchmarkPaths(name=benchmark_id, output_dir=output_dir)
        if not paths.retrieval.exists():
            pytest.skip(f"No retrieval file for {benchmark_id}")

        data: list[dict[str, object]] = load_json_file(paths.retrieval)
        unknown: set[str] = check_unknown_keys(data)

        # Unknown keys are a WARNING, not a failure, but they must be empty
        # for the strict protocol. Add new safe keys to SAFE_KEYS in conftest.py.
        assert not unknown, (
            f"Unknown keys in {benchmark_id} retrieval file: {sorted(unknown)}\n"
            f"Review these keys for potential answer leakage.\n"
            f"If safe, add them to SAFE_KEYS in conftest.py."
        )

    @pytest.mark.contamination
    @pytest.mark.parametrize("benchmark_id", BENCHMARK_IDS)
    def test_gt_file_is_separate(
        self,
        benchmark_id: str,
        output_dir: Path,
    ) -> None:
        """Protocol: ground truth must be in a SEPARATE file from retrieval."""
        paths: BenchmarkPaths = BenchmarkPaths(name=benchmark_id, output_dir=output_dir)
        if not paths.retrieval.exists():
            pytest.skip(f"No retrieval file for {benchmark_id}")

        assert paths.gt.exists(), (
            f"No GT file for {benchmark_id}. "
            f"Protocol requires ground truth in a separate _gt.json file."
        )

        # Verify GT file actually contains answer data
        gt: list[dict[str, object]] = load_json_file(paths.gt)
        gt_keys: set[str] = extract_all_keys(gt)
        has_answers: bool = bool(gt_keys & {"answer", "answers", "reference_answer"})
        has_cat5: bool = "cat5_correct" in gt_keys  # LoCoMo forced-choice

        assert has_answers or has_cat5, (
            f"GT file for {benchmark_id} has no answer fields.\n"
            f"Keys found: {sorted(gt_keys)}\n"
            f"GT file must contain answer data for scoring."
        )

    @pytest.mark.contamination
    @pytest.mark.parametrize("benchmark_id", BENCHMARK_IDS)
    def test_predictions_file_has_no_gt(
        self,
        benchmark_id: str,
        output_dir: Path,
    ) -> None:
        """Predictions file must not contain GT keys (Mode 2 prevention)."""
        paths: BenchmarkPaths = BenchmarkPaths(name=benchmark_id, output_dir=output_dir)
        if not paths.preds.exists():
            pytest.skip(f"No predictions file for {benchmark_id}")

        data: list[dict[str, object]] = load_json_file(paths.preds)
        all_keys: set[str] = extract_all_keys(data)

        # Predictions should only have: id/question_id, llm_prediction, verdict
        gt_keys: set[str] = all_keys & {
            "answer",
            "answers",
            "reference_answer",
            "ground_truth",
            "gt",
            "gold",
            "expected",
            "target",
        }
        assert not gt_keys, (
            f"GT leakage in predictions file for {benchmark_id}: {sorted(gt_keys)}"
        )

    @pytest.mark.contamination
    @pytest.mark.parametrize("benchmark_id", BENCHMARK_IDS)
    def test_verify_clean_script_agrees(
        self,
        benchmark_id: str,
        output_dir: Path,
    ) -> None:
        """Cross-check: run the standalone verify_clean.py script."""
        paths: BenchmarkPaths = BenchmarkPaths(name=benchmark_id, output_dir=output_dir)
        if not paths.retrieval.exists():
            pytest.skip(f"No retrieval file for {benchmark_id}")

        result = subprocess.run(
            ["uv", "run", "python", "benchmarks/verify_clean.py", str(paths.retrieval)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"verify_clean.py FAILED for {benchmark_id}:\n{result.stdout}\n{result.stderr}"
        )


# =====================================================================
# DATASET INTEGRITY
# =====================================================================


class TestDatasetIntegrity:
    """Verify datasets match published specifications."""

    @pytest.mark.parametrize("benchmark_id", BENCHMARK_IDS)
    def test_item_count_matches_paper(
        self,
        benchmark_id: str,
        output_dir: Path,
    ) -> None:
        """Item count must match published dataset size."""
        paths: BenchmarkPaths = BenchmarkPaths(name=benchmark_id, output_dir=output_dir)
        if not paths.retrieval.exists():
            pytest.skip(f"No retrieval file for {benchmark_id}")

        data: list[dict[str, object]] = load_json_file(paths.retrieval)
        expected: dict[str, int] = EXPECTED_COUNTS[benchmark_id]

        assert expected["min_items"] <= len(data) <= expected["max_items"], (
            f"{benchmark_id}: {len(data)} items outside expected range "
            f"[{expected['min_items']}, {expected['max_items']}]"
        )

    @pytest.mark.parametrize("benchmark_id", BENCHMARK_IDS)
    def test_retrieval_gt_count_match(
        self,
        benchmark_id: str,
        output_dir: Path,
    ) -> None:
        """Retrieval and GT files must have the same number of items."""
        paths: BenchmarkPaths = BenchmarkPaths(name=benchmark_id, output_dir=output_dir)
        if not paths.retrieval.exists() or not paths.gt.exists():
            pytest.skip(f"Missing files for {benchmark_id}")

        retrieval: list[dict[str, object]] = load_json_file(paths.retrieval)
        gt: list[dict[str, object]] = load_json_file(paths.gt)

        assert len(retrieval) == len(gt), (
            f"{benchmark_id}: retrieval has {len(retrieval)} items but "
            f"GT has {len(gt)} items. Counts must match."
        )


# =====================================================================
# SCORING (Protocol Step 4)
# =====================================================================


class TestScoring:
    """Score predictions and validate results."""

    @pytest.mark.scoring
    def test_mab_sh_scoring(self, output_dir: Path) -> None:
        """Score MAB SH 262K using substring_exact_match."""
        paths: BenchmarkPaths = BenchmarkPaths(
            name="mab_sh_262k", output_dir=output_dir
        )
        if not paths.preds.exists() or not paths.gt.exists():
            pytest.skip("MAB SH predictions or GT not available")

        from benchmarks.mab_adapter import score_multi_answer

        preds: list[dict[str, object]] = load_json_file(paths.preds)
        gt: list[dict[str, object]] = load_json_file(paths.gt)

        correct: int = 0
        total: int = 0
        for i, pred in enumerate(preds):
            prediction: str = str(pred.get("llm_prediction", ""))
            gt_answers: list[str] = [str(a) for a in gt[i].get("answers", [])]  # type: ignore[union-attr]
            if not gt_answers:
                continue
            scores: dict[str, float] = score_multi_answer(prediction, gt_answers)
            if scores.get("substring_exact_match", 0.0) > 0:
                correct += 1
            total += 1

        sem: float = correct / total * 100 if total > 0 else 0.0

        # Write scores
        result: dict[str, object] = {
            "benchmark": "mab_sh_262k",
            "metric": "SEM",
            "score_pct": round(sem, 1),
            "correct": correct,
            "total": total,
        }
        with paths.scores.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        # Sanity: should not be 0% (retrieval is known to work)
        assert sem > 0, "MAB SH 262K scored 0% -- likely a pipeline error"

    @pytest.mark.scoring
    def test_mab_mh_scoring(self, output_dir: Path) -> None:
        """Score MAB MH 262K using substring_exact_match."""
        paths: BenchmarkPaths = BenchmarkPaths(
            name="mab_mh_262k", output_dir=output_dir
        )
        if not paths.preds.exists() or not paths.gt.exists():
            pytest.skip("MAB MH predictions or GT not available")

        from benchmarks.mab_adapter import score_multi_answer

        preds: list[dict[str, object]] = load_json_file(paths.preds)
        gt: list[dict[str, object]] = load_json_file(paths.gt)

        correct: int = 0
        total: int = 0
        for i, pred in enumerate(preds):
            prediction: str = str(pred.get("llm_prediction", ""))
            gt_answers: list[str] = [str(a) for a in gt[i].get("answers", [])]  # type: ignore[union-attr]
            if not gt_answers:
                continue
            scores: dict[str, float] = score_multi_answer(prediction, gt_answers)
            if scores.get("substring_exact_match", 0.0) > 0:
                correct += 1
            total += 1

        sem: float = correct / total * 100 if total > 0 else 0.0

        result: dict[str, object] = {
            "benchmark": "mab_mh_262k",
            "metric": "SEM",
            "score_pct": round(sem, 1),
            "correct": correct,
            "total": total,
        }
        with paths.scores.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        assert sem > 0, "MAB MH 262K scored 0% -- likely a pipeline error"

    @pytest.mark.scoring
    def test_locomo_scoring(self, output_dir: Path) -> None:
        """Score LoCoMo predictions using protocol-correct F1."""
        paths: BenchmarkPaths = BenchmarkPaths(name="locomo", output_dir=output_dir)
        if not paths.preds.exists() or not paths.gt.exists():
            pytest.skip("LoCoMo predictions or GT not available")

        result = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "benchmarks/locomo_score_protocol.py",
                str(paths.preds),
                str(paths.gt),
                "--output",
                str(paths.scores),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"LoCoMo scoring failed:\n{result.stderr}"

        scores: dict[str, object] = {}
        if paths.scores.exists():
            with paths.scores.open("r", encoding="utf-8") as f:
                scores = json.load(f)

        overall_f1: float = float(scores.get("overall_f1", 0)) * 100  # type: ignore[arg-type]
        assert overall_f1 > 0, "LoCoMo scored 0% F1 -- likely a pipeline error"

    @pytest.mark.scoring
    def test_locomo_below_ceiling(self, output_dir: Path) -> None:
        """LoCoMo has 6.4% corrupted GT; scores above 93.57% are suspicious."""
        paths: BenchmarkPaths = BenchmarkPaths(name="locomo", output_dir=output_dir)
        if not paths.scores.exists():
            pytest.skip("LoCoMo scores not available")

        with paths.scores.open("r", encoding="utf-8") as f:
            scores: dict[str, object] = json.load(f)

        overall_f1: float = float(scores.get("overall_f1", 0)) * 100  # type: ignore[arg-type]

        assert overall_f1 <= LOCOMO_CEILING, (
            f"LoCoMo F1 = {overall_f1:.1f}% exceeds mathematical ceiling "
            f"of {LOCOMO_CEILING}% (6.4% corrupted GT per locomo-audit). "
            f"This indicates contamination or a scoring bug."
        )

    @pytest.mark.scoring
    def test_structmemeval_scoring(self, output_dir: Path) -> None:
        """Score StructMemEval using LLM judge verdicts."""
        paths: BenchmarkPaths = BenchmarkPaths(
            name="structmemeval", output_dir=output_dir
        )
        if not paths.preds.exists():
            pytest.skip("StructMemEval predictions not available")

        preds: list[dict[str, object]] = load_json_file(paths.preds)
        correct: int = sum(
            1
            for p in preds
            if str(p.get("verdict", "")).lower() in ("correct", "yes", "true", "1")
        )
        total: int = len(preds)
        accuracy: float = correct / total * 100 if total > 0 else 0.0

        result: dict[str, object] = {
            "benchmark": "structmemeval",
            "metric": "Accuracy",
            "score_pct": round(accuracy, 1),
            "correct": correct,
            "total": total,
        }
        with paths.scores.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

    @pytest.mark.scoring
    def test_longmemeval_scoring(self, output_dir: Path) -> None:
        """Score LongMemEval using LLM judge verdicts per category."""
        paths: BenchmarkPaths = BenchmarkPaths(
            name="longmemeval", output_dir=output_dir
        )
        if not paths.preds.exists() or not paths.gt.exists():
            pytest.skip("LongMemEval predictions or GT not available")

        preds: list[dict[str, object]] = load_json_file(paths.preds)
        gt: list[dict[str, object]] = load_json_file(paths.gt)
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

        result: dict[str, object] = {
            "benchmark": "longmemeval",
            "metric": "Accuracy (Opus binary judge)",
            "score_pct": round(overall, 1),
            "correct": total_correct,
            "total": total_count,
            "per_category": {
                qtype: {
                    "correct": correct_by_type.get(qtype, 0),
                    "total": total_by_type[qtype],
                    "accuracy_pct": round(
                        correct_by_type.get(qtype, 0) / total_by_type[qtype] * 100,
                        1,
                    ),
                }
                for qtype in sorted(total_by_type.keys())
            },
        }
        with paths.scores.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)


# =====================================================================
# PROTOCOL METADATA (Lin Methodology Checklist)
# =====================================================================


class TestMethodology:
    """Enforce Lin methodology checklist completeness."""

    @pytest.mark.protocol
    @pytest.mark.parametrize("benchmark_id", BENCHMARK_IDS)
    def test_methodology_file_exists(
        self,
        benchmark_id: str,
        output_dir: Path,
    ) -> None:
        """Each benchmark must have a methodology metadata file."""
        paths: BenchmarkPaths = BenchmarkPaths(name=benchmark_id, output_dir=output_dir)
        if not paths.retrieval.exists():
            pytest.skip(f"No retrieval output for {benchmark_id}")

        assert paths.methodology.exists(), (
            f"No methodology file for {benchmark_id}.\n"
            f"Create {paths.methodology} with the required fields:\n"
            f"{METHODOLOGY_REQUIRED}"
        )

    @pytest.mark.protocol
    @pytest.mark.parametrize("benchmark_id", BENCHMARK_IDS)
    def test_methodology_complete(
        self,
        benchmark_id: str,
        output_dir: Path,
    ) -> None:
        """All Lin methodology checklist fields must be populated."""
        paths: BenchmarkPaths = BenchmarkPaths(name=benchmark_id, output_dir=output_dir)
        if not paths.methodology.exists():
            pytest.skip(f"No methodology file for {benchmark_id}")

        with paths.methodology.open("r", encoding="utf-8") as f:
            meta: dict[str, object] = json.load(f)

        missing: list[str] = [
            field
            for field in METHODOLOGY_REQUIRED
            if field not in meta or meta[field] in (None, "", "unknown")
        ]
        assert not missing, (
            f"Methodology metadata incomplete for {benchmark_id}.\n"
            f"Missing fields: {missing}\n"
            f"This violates the Lin methodology checklist."
        )

    @pytest.mark.protocol
    @pytest.mark.parametrize("benchmark_id", BENCHMARK_IDS)
    def test_audit_trail_exists(
        self,
        benchmark_id: str,
        output_dir: Path,
    ) -> None:
        """Each scored benchmark must have an audit trail file."""
        paths: BenchmarkPaths = BenchmarkPaths(name=benchmark_id, output_dir=output_dir)
        if not paths.scores.exists():
            pytest.skip(f"No scores for {benchmark_id}")

        assert paths.audit.exists(), (
            f"No audit trail for {benchmark_id}.\n"
            f"Protocol Step 5 requires a complete audit record."
        )


# =====================================================================
# STRUCTURAL CHECKS (Lin "landmines")
# =====================================================================


class TestLandmines:
    """Detect common benchmarking landmines (Lin quick reference)."""

    @pytest.mark.protocol
    def test_metric_types_not_mixed(self, output_dir: Path) -> None:
        """Never compare R@k with QA accuracy across benchmarks."""
        scores_files: list[Path] = list(output_dir.glob("benchmark_*_scores.json"))
        if not scores_files:
            pytest.skip("No scores files")

        metrics: dict[str, str] = {}
        for sf in scores_files:
            with sf.open("r", encoding="utf-8") as f:
                data: dict[str, object] = json.load(f)
            name: str = str(data.get("benchmark", sf.stem))
            metric: str = str(data.get("metric", "unknown"))
            metrics[name] = metric

        # This is informational -- different benchmarks use different metrics
        # The contract is that each benchmark explicitly labels its metric type
        for name, metric in metrics.items():
            assert metric != "unknown", (
                f"Benchmark {name} has no explicit metric type label. "
                f"Lin checklist requires metric_type in every result."
            )

    @pytest.mark.protocol
    def test_no_single_run_without_variance_note(self, output_dir: Path) -> None:
        """Single-run results must note that variance is not quantified.

        Lin recommends 5-10 runs. If run_count < 5, the methodology file
        must document why (e.g., deterministic retrieval).
        """
        for bench_id in BENCHMARK_IDS:
            paths: BenchmarkPaths = BenchmarkPaths(name=bench_id, output_dir=output_dir)
            if not paths.methodology.exists():
                continue

            with paths.methodology.open("r", encoding="utf-8") as f:
                meta: dict[str, object] = json.load(f)

            run_count: int = int(meta.get("run_count", 1))  # type: ignore[arg-type]
            if run_count < 5:
                variance_note: str = str(meta.get("variance_justification", ""))
                assert variance_note, (
                    f"{bench_id}: run_count={run_count} < 5 but no "
                    f"variance_justification in methodology file. "
                    f"Lin checklist requires justification for single-run reporting."
                )
