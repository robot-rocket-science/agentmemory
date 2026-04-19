"""Benchmark protocol enforcement fixtures.

Codifies docs/BENCHMARK_PROTOCOL.md as pytest fixtures and assertions.
Every protocol step is an enforceable contract. Contamination = test failure.

References:
    - docs/BENCHMARK_PROTOCOL.md (internal protocol)
    - github.com/lhl/agentic-memory/benchmarks (Lin methodology checklist)
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTPUT_DIR: Final[Path] = Path(
    os.environ.get(
        "BENCHMARK_OUTPUT_DIR",
        "/tmp/benchmark_v2",
    )
)

BENCHMARK_IDS: Final[list[str]] = [
    "mab_sh_262k",
    "mab_mh_262k",
    "locomo",
    "structmemeval",
    "longmemeval",
]

# Protocol: keys that MUST NOT appear in retrieval files
BANNED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "answer",
        "answers",
        "answer_raw",
        "reference_answer",
        "ground_truth",
        "gt",
        "gold",
        "target",
        "expected",
        "solution",
        "correct",
        "correct_answer",
        "label",
        "score",
        "f1",
        "exact_match",
        "substring_exact_match",
        "accuracy",
        "rouge",
        "bleu",
        "is_correct",
        "judgment",
        "eval_score",
    }
)

# Keys known to be safe in retrieval files
SAFE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "id",
        "question",
        "context",
        "retrieved_context",
        "question_id",
        "question_type",
        "question_date",
        "source",
        "row_idx",
        "q_idx",
        "case_id",
        "task",
        "domain",
        "task_type",
        "episode_id",
        "qa_type",
        "qa_type_name",
        "question_uuid",
        "category",
        "category_name",
        "num_beliefs",
        "retrieval_latency_ms",
        "option_a",
        "option_b",  # forced-choice (no correct indicator)
    }
)

# LoCoMo mathematical ceiling per locomo-audit (6.4% corrupted GT)
LOCOMO_CEILING: Final[float] = 93.57

# Lin methodology checklist: required metadata fields
METHODOLOGY_REQUIRED: Final[list[str]] = [
    "benchmark_name",
    "benchmark_version",
    "metric_type",
    "reader_model",
    "judge_model",
    "retrieval_method",
    "token_budget",
    "prompt_template_hash",
    "run_count",
    "git_commit",
    "timestamp",
    "code_link",
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkPaths:
    """Standard file paths for a benchmark run per protocol naming convention."""

    name: str
    output_dir: Path = OUTPUT_DIR

    @property
    def retrieval(self) -> Path:
        return self.output_dir / f"benchmark_{self.name}.json"

    @property
    def gt(self) -> Path:
        return self.output_dir / f"benchmark_{self.name}_gt.json"

    @property
    def preds(self) -> Path:
        return self.output_dir / f"benchmark_{self.name}_preds.json"

    @property
    def scores(self) -> Path:
        return self.output_dir / f"benchmark_{self.name}_scores.json"

    @property
    def audit(self) -> Path:
        return self.output_dir / f"benchmark_{self.name}_audit.json"

    @property
    def methodology(self) -> Path:
        return self.output_dir / f"benchmark_{self.name}_methodology.json"


@dataclass
class AuditRecord:
    """Structured audit trail per protocol Step 5."""

    benchmark: str = ""
    git_commit: str = ""
    timestamp: str = ""
    adapter_script: str = ""
    reader_model: str = ""
    contamination_status: str = ""
    retrieval_file: str = ""
    gt_file: str = ""
    predictions_file: str = ""
    metric: str = ""
    score: float = 0.0
    n: int = 0
    published_baseline: str = ""
    retrieval_elapsed_s: float = 0.0
    prediction_token_count: int = 0
    notes: str = ""
    errors: list[str] = field(default_factory=lambda: list[str]())

    def to_dict(self) -> dict[str, object]:
        return {k: v for k, v in self.__dict__.items()}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def output_dir() -> Path:
    """Create and return the benchmark output directory."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


@pytest.fixture(scope="session")
def git_commit() -> str:
    """Capture the current git commit hash for audit trail."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture(scope="session")
def git_is_clean() -> bool:
    """Check if git working tree is clean."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip() == ""


@pytest.fixture(scope="session")
def run_timestamp() -> str:
    """ISO 8601 timestamp for this benchmark run."""
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture(params=BENCHMARK_IDS)
def benchmark_id(request: pytest.FixtureRequest) -> str:
    """Parametrize across all benchmark IDs."""
    return str(request.param)


@pytest.fixture
def paths(benchmark_id: str, output_dir: Path) -> BenchmarkPaths:
    """Standard paths for a given benchmark."""
    return BenchmarkPaths(name=benchmark_id, output_dir=output_dir)


# ---------------------------------------------------------------------------
# Protocol enforcement helpers
# ---------------------------------------------------------------------------


def load_json_file(path: Path) -> list[dict[str, object]]:
    """Load a JSON array file, raising clear errors."""
    if not path.exists():
        msg: str = f"File does not exist: {path}"
        raise FileNotFoundError(msg)
    with path.open("r", encoding="utf-8") as f:
        raw: object = json.load(f)
    if not isinstance(raw, list):
        msg = f"Expected JSON array, got {type(raw).__name__}: {path}"
        raise TypeError(msg)
    data: list[dict[str, object]] = raw  # type: ignore[assignment]
    return data


def extract_all_keys(data: list[dict[str, object]]) -> set[str]:
    """Extract the union of all keys across all items."""
    keys: set[str] = set()
    for item in data:
        keys.update(item.keys())
    return keys


def check_contamination(data: list[dict[str, object]]) -> set[str]:
    """Return set of banned keys found in data. Empty = clean."""
    all_keys: set[str] = extract_all_keys(data)
    return all_keys & BANNED_KEYS


def check_unknown_keys(data: list[dict[str, object]]) -> set[str]:
    """Return keys that are neither banned nor known-safe. Need manual review."""
    all_keys: set[str] = extract_all_keys(data)
    return all_keys - SAFE_KEYS - BANNED_KEYS


def write_audit_record(record: AuditRecord, path: Path) -> None:
    """Write audit trail to JSON file."""
    with path.open("w", encoding="utf-8") as f:
        json.dump(record.to_dict(), f, indent=2)
