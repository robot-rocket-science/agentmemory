"""MAB FactConsolidation adapter with LLM-based entity extraction (Exp 5, Treatment B).

Identical to mab_entity_index_adapter.py EXCEPT the extraction step uses
Haiku LLM instead of regex. Same EntityIndex, same multi_hop_retrieve(),
same output format. Only the extraction method changes.

Usage:
    uv run python benchmarks/mab_llm_entity_adapter.py --retrieve-only /tmp/exp5_treatment_b.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Final

# Ensure benchmarks/ is importable when running as a script
_BENCH_DIR: str = str(Path(__file__).resolve().parent)
if _BENCH_DIR not in sys.path:
    sys.path.insert(0, _BENCH_DIR)

from datasets import load_dataset  # type: ignore[import-untyped]

from llm_entity_extraction import extract_triples_llm  # type: ignore[import-untyped]
from mab_entity_index_adapter import (  # type: ignore[import-untyped]
    EntityIndex,
    multi_hop_retrieve,
)
from agentmemory.triple_extraction import FactTriple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HF_DATASET: Final[str] = "ai-hyz/MemoryAgentBench"
DEFAULT_SOURCE: Final[str] = "factconsolidation_mh_262k"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Exp 5 Treatment B: LLM entity extraction for multi-hop",
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        help=f"MAB source (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--subset",
        type=int,
        default=None,
        help="Limit to first N questions",
    )
    parser.add_argument(
        "--retrieve-only",
        default=None,
        metavar="PATH",
        help="Write retrieval results (NO answers) to PATH",
    )
    parser.add_argument(
        "--audit-log",
        default=None,
        metavar="PATH",
        help="Write LLM extraction audit log to PATH",
    )
    args: argparse.Namespace = parser.parse_args()

    print("=== Exp 5 Treatment B: LLM Entity Extraction ===")
    print(f"Source: {args.source}")

    # Load data
    ds = load_dataset(HF_DATASET, split="Conflict_Resolution")  # type: ignore[no-untyped-call]
    context: str = ""
    questions: list[str] = []
    answers: list[list[str]] = []

    for raw_row in ds:  # type: ignore[union-attr]
        row: dict[str, object] = dict(raw_row)  # type: ignore[arg-type]
        metadata: dict[str, object] = row.get("metadata", {})  # type: ignore[assignment]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        if str(metadata.get("source", "")) != args.source:
            continue
        context = str(row["context"])
        questions = list(row["questions"])  # type: ignore[arg-type]
        answers = [list(a) for a in row["answers"]]  # type: ignore[union-attr]
        break

    if not context:
        print(f"No data for source: {args.source}")
        return

    if args.subset is not None:
        questions = questions[: args.subset]
        answers = answers[: args.subset]

    # Parse context into lines
    lines: list[str] = context.strip().split("\n")
    if lines and lines[0].startswith("Here is"):
        lines = lines[1:]

    total_lines: int = len(lines)
    print(f"Total fact lines: {total_lines}")

    # LLM extraction
    print("Running LLM extraction (Haiku)...")
    t0: float = time.monotonic()
    triples: list[FactTriple]
    audit_log: list[dict[str, object]]
    triples, audit_log = extract_triples_llm(lines, verbose=True)
    extract_time: float = time.monotonic() - t0
    print(
        f"LLM extraction: {len(triples)}/{total_lines} "
        f"({len(triples) / total_lines * 100:.1f}%) in {extract_time:.1f}s"
    )

    # Write audit log if requested
    if args.audit_log:
        audit_path: Path = Path(args.audit_log)
        with audit_path.open("w", encoding="utf-8") as f:
            json.dump(audit_log, f, indent=2)
        print(f"Audit log: {args.audit_log}")

    # Build entity index from LLM-extracted triples
    index: EntityIndex = EntityIndex()
    for triple in triples:
        index.add(triple)

    print(
        f"Index: {index.entity_count} entities, {index.fact_count} facts, "
        f"{index.conflict_count} conflicts"
    )

    # Run queries (identical to regex adapter)
    per_question: list[dict[str, object]] = []
    ground_truth: list[dict[str, object]] = []

    t1: float = time.monotonic()
    answer_in_ctx: int = 0
    for i, (question, answer_list) in enumerate(zip(questions, answers)):
        ctx: str = multi_hop_retrieve(index, question)
        per_question.append(
            {
                "id": i,
                "question": question,
                "context": ctx,
            }
        )
        ground_truth.append(
            {
                "id": i,
                "answers": answer_list,
            }
        )

        if answer_list[0].lower() in ctx.lower():
            answer_in_ctx += 1

    query_time: float = time.monotonic() - t1

    print(f"Queried {len(questions)} questions in {query_time:.2f}s")
    print(
        f"Answer in context: {answer_in_ctx}/{len(questions)} "
        f"= {answer_in_ctx / len(questions) * 100:.0f}%"
    )

    # Write output
    if args.retrieve_only:
        retrieve_path: Path = Path(args.retrieve_only)
        gt_path: Path = retrieve_path.with_name(
            retrieve_path.stem + "_gt" + retrieve_path.suffix,
        )
        with retrieve_path.open("w", encoding="utf-8") as f:
            json.dump(per_question, f, indent=2)
        with gt_path.open("w", encoding="utf-8") as f:
            json.dump(ground_truth, f, indent=2)
        print(f"Wrote to {args.retrieve_only}")
        print(f"Wrote GT to {gt_path}")
        print("ISOLATION: retrieval file contains NO ground truth")


if __name__ == "__main__":
    main()
