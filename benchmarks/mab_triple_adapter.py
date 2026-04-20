"""MAB FactConsolidation adapter with structured triple extraction.

Extends mab_adapter.py with:
1. Per-line fact parsing into (entity, property, value, serial) triples
2. SUPERSEDES edge creation between conflicting triples
3. Entity-level graph edges for BFS multi-hop traversal

Supports experimental controls:
  --no-supersedes  : Ingest triples but skip SUPERSEDES edges (Control A)
  --no-bfs         : Use FTS5 only, no BFS expansion (Control B)
  --treatment      : Full pipeline with SUPERSEDES + BFS (default)

Usage:
    uv run python benchmarks/mab_triple_adapter.py --retrieve-only /tmp/exp3_treatment.json
    uv run python benchmarks/mab_triple_adapter.py --no-supersedes --retrieve-only /tmp/exp3_ctrl_a.json
    uv run python benchmarks/mab_triple_adapter.py --no-bfs --retrieve-only /tmp/exp3_ctrl_b.json
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from datasets import load_dataset  # type: ignore[import-untyped]

from agentmemory.ingest import ingest_turn
from agentmemory.retrieval import retrieve
from agentmemory.store import MemoryStore
from agentmemory.triple_extraction import FactTriple, extract_triple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HF_DATASET: Final[str] = "ai-hyz/MemoryAgentBench"
DEFAULT_SOURCE: Final[str] = "factconsolidation_mh_262k"

EDGE_ABOUT_ENTITY: Final[str] = "ABOUT_ENTITY"

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TripleIngestStats:
    """Statistics from triple-aware ingestion."""

    total_lines: int = 0
    triples_extracted: int = 0
    supersedes_created: int = 0
    entity_edges_created: int = 0
    beliefs_created: int = 0


@dataclass
class ExpResult:
    """Results for one experimental condition."""

    condition: str = ""
    total_questions: int = 0
    ingest_stats: TripleIngestStats = field(default_factory=TripleIngestStats)
    ingest_time_s: float = 0.0
    query_time_s: float = 0.0
    per_question: list[dict[str, object]] = field(
        default_factory=lambda: list[dict[str, object]](),
    )
    ground_truth: list[dict[str, object]] = field(
        default_factory=lambda: list[dict[str, object]](),
    )


# ---------------------------------------------------------------------------
# Triple-aware ingestion
# ---------------------------------------------------------------------------


def _synthetic_timestamp(serial: int, total_lines: int) -> str:
    """Generate synthetic timestamp from serial number.

    Maps serial 0 to 365 days ago, serial N to now.
    This gives temporal decay a gradient to work with.
    """
    from datetime import datetime, timedelta, timezone

    now: datetime = datetime.now(timezone.utc)
    if total_lines <= 1:
        return now.isoformat()
    fraction: float = serial / (total_lines - 1)
    days_ago: float = (1.0 - fraction) * 365.0
    dt: datetime = now - timedelta(days=days_ago)
    return dt.isoformat()


def ingest_with_triples(
    store: MemoryStore,
    context: str,
    source_name: str,
    create_supersedes: bool = True,
) -> TripleIngestStats:
    """Ingest FactConsolidation context with triple extraction.

    For each line:
    1. Extract (entity, property, value, serial) triple
    2. Create belief with synthetic timestamp based on serial
    3. If create_supersedes: check for conflicting triples on same
       (entity, property), create SUPERSEDES edge (newer supersedes older)
    4. Create ABOUT_ENTITY edge from belief to entity string
    """
    stats: TripleIngestStats = TripleIngestStats()

    lines: list[str] = context.strip().split("\n")
    if lines and lines[0].startswith("Here is"):
        lines = lines[1:]  # Skip header

    total_lines: int = len(lines)
    stats.total_lines = total_lines

    session = store.create_session(
        model="mab-triple-benchmark",
        project_context=f"FactConsolidation {source_name}",
    )

    # Track triples by (entity_lower, property) for conflict detection
    triple_beliefs: dict[tuple[str, str], list[tuple[FactTriple, str]]] = {}

    for line in lines:
        triple: FactTriple | None = extract_triple(line)

        if triple is not None:
            stats.triples_extracted += 1

            # Create belief with serial-based timestamp
            ts: str = _synthetic_timestamp(
                triple.serial if triple.serial is not None else 0,
                total_lines,
            )

            ingest_result = ingest_turn(
                store=store,
                text=triple.source_text,
                source="mab-triple",
                session_id=session.id,
                source_id=f"fact_{triple.serial}",
                created_at=ts,
            )
            stats.beliefs_created += ingest_result.beliefs_created

            if ingest_result.beliefs_created == 0:
                continue

            # Find the belief we just created by searching for its text
            from agentmemory.models import Belief

            found_beliefs: list[Belief] = store.search(triple.source_text[:50], top_k=1)
            if not found_beliefs:
                continue
            belief_id: str = found_beliefs[0].id

            # Track for conflict detection
            key: tuple[str, str] = (triple.entity.lower(), triple.property_name)
            if key not in triple_beliefs:
                triple_beliefs[key] = []

            # Check for conflicts and create SUPERSEDES edges
            if create_supersedes and key in triple_beliefs:
                for existing_triple, existing_id in triple_beliefs[key]:
                    if existing_triple.value.lower() != triple.value.lower():
                        # Determine which is newer
                        new_serial: int = (
                            triple.serial if triple.serial is not None else 0
                        )
                        old_serial: int = (
                            existing_triple.serial
                            if existing_triple.serial is not None
                            else 0
                        )

                        if new_serial > old_serial:
                            store.supersede_belief(
                                old_id=existing_id,
                                new_id=belief_id,
                                reason=f"serial {new_serial} > {old_serial}",
                            )
                            stats.supersedes_created += 1
                        elif old_serial > new_serial:
                            store.supersede_belief(
                                old_id=belief_id,
                                new_id=existing_id,
                                reason=f"serial {old_serial} > {new_serial}",
                            )
                            stats.supersedes_created += 1

            triple_beliefs[key].append((triple, belief_id))

        else:
            # No triple extracted: ingest as plain text (no regression)
            ts = _synthetic_timestamp(0, total_lines)
            line_match: re.Match[str] | None = re.match(r"(\d+)\.", line)
            serial_num: int = int(line_match.group(1)) if line_match else 0
            ts = _synthetic_timestamp(serial_num, total_lines)

            plain_result = ingest_turn(
                store=store,
                text=line,
                source="mab-triple",
                session_id=session.id,
                source_id=f"line_{serial_num}",
                created_at=ts,
            )
            stats.beliefs_created += plain_result.beliefs_created

    store.complete_session(session.id)
    return stats


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


def query_agentmemory(
    store: MemoryStore,
    question: str,
    budget: int = 2000,
    use_bfs: bool = True,
) -> str:
    """Query with temporal sort (newest beliefs first)."""
    result = retrieve(
        store=store,
        query=question,
        budget=budget,
        include_locked=False,
        use_hrr=True,
        use_bfs=use_bfs,
        temporal_sort=True,
    )
    parts: list[str] = [b.content for b in result.beliefs]
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_condition(
    context: str,
    questions: list[str],
    answers: list[list[str]],
    source_name: str,
    condition: str,
    create_supersedes: bool = True,
    use_bfs: bool = True,
    budget: int = 2000,
) -> ExpResult:
    """Run one experimental condition with full isolation."""
    result: ExpResult = ExpResult(condition=condition)

    with tempfile.TemporaryDirectory(prefix=f"exp3_{condition}_") as tmpdir:
        db_path: str = f"{tmpdir}/exp3.db"
        store: MemoryStore = MemoryStore(db_path)

        # Ingest
        t0: float = time.monotonic()
        result.ingest_stats = ingest_with_triples(
            store,
            context,
            source_name,
            create_supersedes=create_supersedes,
        )
        result.ingest_time_s = time.monotonic() - t0

        print(
            f"  Ingested: {result.ingest_stats.beliefs_created} beliefs, "
            f"{result.ingest_stats.triples_extracted} triples, "
            f"{result.ingest_stats.supersedes_created} SUPERSEDES edges "
            f"in {result.ingest_time_s:.1f}s"
        )

        # Query
        t1: float = time.monotonic()
        for q_idx, (question, answer_list) in enumerate(zip(questions, answers)):
            ctx: str = query_agentmemory(
                store, question, budget=budget, use_bfs=use_bfs
            )

            result.total_questions += 1
            result.per_question.append(
                {
                    "id": q_idx,
                    "question": question,
                    "context": ctx,
                }
            )
            result.ground_truth.append(
                {
                    "id": q_idx,
                    "answers": answer_list,
                }
            )

        result.query_time_s = time.monotonic() - t1

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Exp 3: Structured triple extraction for FactConsolidation",
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        help=f"MAB source filter (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--no-supersedes",
        action="store_true",
        help="Control A: ingest triples but skip SUPERSEDES edges",
    )
    parser.add_argument(
        "--no-bfs",
        action="store_true",
        help="Control B: skip BFS expansion in retrieval",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=2000,
        help="Retrieval token budget (default: 2000)",
    )
    parser.add_argument(
        "--subset",
        type=int,
        default=None,
        help="Limit to first N questions (for debugging)",
    )
    parser.add_argument(
        "--retrieve-only",
        default=None,
        metavar="PATH",
        help="Write retrieval results (NO answers) to PATH",
    )
    args: argparse.Namespace = parser.parse_args()

    # Determine condition name
    if args.no_supersedes:
        condition: str = "control_a_no_supersedes"
    elif args.no_bfs:
        condition = "control_b_no_bfs"
    else:
        condition = "treatment"

    print(f"=== Exp 3: {condition} ===")
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
        print(f"No data found for source: {args.source}")
        return

    if args.subset is not None:
        questions = questions[: args.subset]
        answers = answers[: args.subset]

    print(f"Context: {len(context)} chars, {len(questions)} questions")

    # Run condition
    result: ExpResult = run_condition(
        context=context,
        questions=questions,
        answers=answers,
        source_name=args.source,
        condition=condition,
        create_supersedes=not args.no_supersedes,
        use_bfs=not args.no_bfs,
        budget=args.budget,
    )

    print(f"  Queried {result.total_questions} questions in {result.query_time_s:.1f}s")

    # Write output
    if args.retrieve_only:
        retrieve_path: Path = Path(args.retrieve_only)
        gt_path: Path = retrieve_path.with_name(
            retrieve_path.stem + "_gt" + retrieve_path.suffix,
        )
        with retrieve_path.open("w", encoding="utf-8") as f:
            json.dump(result.per_question, f, indent=2)
        with gt_path.open("w", encoding="utf-8") as f:
            json.dump(result.ground_truth, f, indent=2)
        print(
            f"Wrote {result.total_questions} retrieval results to {args.retrieve_only}"
        )
        print(f"Wrote {result.total_questions} ground truth to {gt_path}")
        print("ISOLATION: retrieval file contains NO ground truth")


if __name__ == "__main__":
    main()
