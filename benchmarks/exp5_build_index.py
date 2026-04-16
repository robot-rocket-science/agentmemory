"""Exp 5 Phase 2: Build entity index from LLM-extracted triples and run queries.

Reads LLM extraction results (JSON) and the original dataset export.
Builds an EntityIndex, runs multi-hop queries, writes retrieval + GT files.

Usage:
    uv run python benchmarks/exp5_build_index.py \
        /tmp/exp5_lines.json /tmp/exp5_llm_triples.json \
        --retrieve-only /tmp/exp5_treatment_b.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_BENCH_DIR: str = str(Path(__file__).resolve().parent)
if _BENCH_DIR not in sys.path:
    sys.path.insert(0, _BENCH_DIR)

from mab_entity_index_adapter import (  # type: ignore[import-untyped]
    EntityIndex,
    multi_hop_retrieve,
)
from agentmemory.triple_extraction import FactTriple


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Exp 5 Phase 2: Build index from LLM triples",
    )
    parser.add_argument("lines_file", help="Path to exp5_lines.json (from Phase 1)")
    parser.add_argument("triples_file", help="Path to LLM-extracted triples JSON")
    parser.add_argument(
        "--retrieve-only", default=None, metavar="PATH",
        help="Write retrieval results (NO answers) to PATH",
    )
    args: argparse.Namespace = parser.parse_args()

    # Load original data
    with Path(args.lines_file).open("r", encoding="utf-8") as f:
        data: dict[str, object] = json.load(f)

    questions: list[str] = list(data["questions"])  # type: ignore[arg-type]
    answers: list[list[str]] = [list(a) for a in data["answers"]]  # type: ignore[union-attr]
    total_lines: int = int(data["total_lines"])  # type: ignore[arg-type]

    # Load LLM-extracted triples
    with Path(args.triples_file).open("r", encoding="utf-8") as f:
        raw_triples: list[dict[str, object]] = json.load(f)

    # Convert to FactTriple objects
    triples: list[FactTriple] = []
    for rt in raw_triples:
        entity: str = str(rt.get("entity", "")).strip()
        prop: str = str(rt.get("property", "")).strip()
        value: str = str(rt.get("value", "")).strip()
        raw_serial: object = rt.get("serial")
        serial: int | None = int(raw_serial) if isinstance(raw_serial, (int, float)) else None

        if entity and prop and value:
            triples.append(FactTriple(
                entity=entity,
                property_name=prop,
                value=value,
                serial=serial,
                source_text=str(rt.get("source_text", "")),
            ))

    print(f"Loaded {len(triples)} LLM-extracted triples from {total_lines} lines "
          f"({len(triples)/total_lines*100:.1f}%)")

    # Build entity index
    index: EntityIndex = EntityIndex()
    for triple in triples:
        index.add(triple)

    print(f"Index: {index.entity_count} entities, {index.fact_count} facts, "
          f"{index.conflict_count} conflicts")

    # Run queries
    per_question: list[dict[str, object]] = []
    ground_truth: list[dict[str, object]] = []

    t0: float = time.monotonic()
    answer_in_ctx: int = 0
    for i, (question, answer_list) in enumerate(zip(questions, answers)):
        ctx: str = multi_hop_retrieve(index, question)
        per_question.append({
            "id": i,
            "question": question,
            "context": ctx,
        })
        ground_truth.append({
            "id": i,
            "answers": answer_list,
        })

        if answer_list[0].lower() in ctx.lower():
            answer_in_ctx += 1

    query_time: float = time.monotonic() - t0

    print(f"Queried {len(questions)} questions in {query_time:.2f}s")
    print(f"Answer in context: {answer_in_ctx}/{len(questions)} "
          f"= {answer_in_ctx/len(questions)*100:.0f}%")

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
