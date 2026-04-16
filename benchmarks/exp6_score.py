"""Exp 6 scoring: temporal coherence experiment.

Compares baseline (latest-serial-only) vs temporal (all-historical-values)
retrieval on MAB MH 262K.

Usage:
    uv run python benchmarks/exp6_score.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BENCH_DIR: str = str(Path(__file__).resolve().parent)
if _BENCH_DIR not in sys.path:
    sys.path.insert(0, _BENCH_DIR)

from mab_adapter import score_multi_answer  # type: ignore[import-untyped]


CONDITIONS: list[str] = ["baseline", "temporal"]
READERS: list[str] = ["opus", "haiku"]


def score_condition_reader(condition: str, reader: str) -> dict[str, object] | None:
    """Score a single condition*reader combination."""
    pred_path: Path = Path(f"/tmp/exp6_{condition}_preds_{reader}.json")
    gt_path: Path = Path(f"/tmp/exp6_{condition}_gt.json")

    if not pred_path.exists():
        return None
    if not gt_path.exists():
        print(f"ERROR: GT file missing: {gt_path}")
        return None

    with pred_path.open("r", encoding="utf-8") as f:
        preds: list[dict[str, object]] = json.load(f)
    with gt_path.open("r", encoding="utf-8") as f:
        gt: list[dict[str, object]] = json.load(f)

    gt_by_id: dict[int, list[str]] = {}
    for entry in gt:
        entry_id: int = int(entry["id"])  # type: ignore[arg-type]
        answers: list[str] = [str(a) for a in entry["answers"]]  # type: ignore[union-attr]
        gt_by_id[entry_id] = answers

    sem_scores: list[float] = []
    f1_scores: list[float] = []
    per_question: list[dict[str, object]] = []

    for pred_entry in preds:
        pred_id: int = int(pred_entry["id"])  # type: ignore[arg-type]
        prediction: str = str(pred_entry.get("llm_prediction", "unknown"))
        answers: list[str] = gt_by_id.get(pred_id, [])

        if not answers:
            continue

        scores: dict[str, float] = score_multi_answer(prediction, answers)
        sem_scores.append(scores["substring_exact_match"])
        f1_scores.append(scores["f1"])

        per_question.append({
            "id": pred_id,
            "prediction": prediction,
            "gt_answers": answers,
            "sem": scores["substring_exact_match"],
            "f1": scores["f1"],
        })

    sem_pct: float = sum(sem_scores) / len(sem_scores) * 100 if sem_scores else 0.0
    f1_pct: float = sum(f1_scores) / len(f1_scores) * 100 if f1_scores else 0.0

    return {
        "condition": condition,
        "reader": reader,
        "n": len(sem_scores),
        "sem_pct": round(sem_pct, 1),
        "f1_pct": round(f1_pct, 1),
        "per_question": per_question,
    }


def main() -> None:
    print("=" * 60)
    print("Exp 6: Temporal Coherence Results")
    print("=" * 60)
    print()
    print("GT-reachable: baseline=62/100, temporal=96/100 (+34)")
    print()

    results: list[dict[str, object]] = []

    for condition in CONDITIONS:
        for reader in READERS:
            result: dict[str, object] | None = score_condition_reader(condition, reader)
            if result is None:
                print(f"  {condition:12s} / {reader:6s}: MISSING")
                continue
            results.append(result)
            print(f"  {condition:12s} / {reader:6s}: SEM={result['sem_pct']}%  F1={result['f1_pct']}%  (n={result['n']})")

    print()
    print("=" * 60)
    print("Summary Table (SEM %)")
    print("=" * 60)
    print(f"{'Condition':15s} {'Opus':>8s} {'Haiku':>8s}")
    print("-" * 35)

    for condition in CONDITIONS:
        opus_sem: str = "-"
        haiku_sem: str = "-"
        for r in results:
            if r["condition"] == condition and r["reader"] == "opus":
                opus_sem = f"{r['sem_pct']}%"
            if r["condition"] == condition and r["reader"] == "haiku":
                haiku_sem = f"{r['sem_pct']}%"
        print(f"{condition:15s} {opus_sem:>8s} {haiku_sem:>8s}")

    out_path: Path = Path("/tmp/exp6_scores.json")
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed results: {out_path}")


if __name__ == "__main__":
    main()
