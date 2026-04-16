"""Exp 5 Phase 1: Export fact lines from MAB dataset for LLM extraction.

Writes raw fact lines (with serial numbers) to a JSON file.
The orchestrator then sends these to Haiku subagents for entity extraction.
Results are fed to exp5_build_index.py for Phase 2.

Usage:
    uv run python benchmarks/exp5_export_lines.py /tmp/exp5_lines.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Final

from datasets import load_dataset  # type: ignore[import-untyped]

HF_DATASET: Final[str] = "ai-hyz/MemoryAgentBench"
DEFAULT_SOURCE: Final[str] = "factconsolidation_mh_262k"
SERIAL_RE: Final[re.Pattern[str]] = re.compile(r"^(\d+)\.\s+(.+)$")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: exp5_export_lines.py <output.json>")
        sys.exit(1)

    out_path: Path = Path(sys.argv[1])

    ds = load_dataset(HF_DATASET, split="Conflict_Resolution")  # type: ignore[no-untyped-call]
    context: str = ""
    questions: list[str] = []
    answers: list[list[str]] = []

    for raw_row in ds:  # type: ignore[union-attr]
        row: dict[str, object] = dict(raw_row)  # type: ignore[arg-type]
        metadata: dict[str, object] = row.get("metadata", {})  # type: ignore[assignment]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        if str(metadata.get("source", "")) != DEFAULT_SOURCE:
            continue
        context = str(row["context"])
        questions = list(row["questions"])  # type: ignore[arg-type]
        answers = [list(a) for a in row["answers"]]  # type: ignore[union-attr]
        break

    lines: list[str] = context.strip().split("\n")
    if lines and lines[0].startswith("Here is"):
        lines = lines[1:]

    # Parse serial numbers
    parsed: list[dict[str, object]] = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        m: re.Match[str] | None = SERIAL_RE.match(line)
        if m:
            parsed.append({"serial": int(m.group(1)), "text": m.group(2).strip()})
        else:
            parsed.append({"serial": i + 1, "text": line})

    output: dict[str, object] = {
        "total_lines": len(parsed),
        "lines": parsed,
        "questions": questions,
        "answers": answers,
    }

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"Exported {len(parsed)} lines, {len(questions)} questions to {out_path}")


if __name__ == "__main__":
    main()
