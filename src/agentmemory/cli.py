"""CLI entry point for agentmemory.

Provides direct commands that execute without LLM involvement:
  agentmemory onboard <path>   -- scan and ingest a project
  agentmemory status           -- show memory system health
  agentmemory search <query>   -- search beliefs
  agentmemory locked           -- show locked beliefs
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agentmemory.ingest import IngestResult, ingest_turn
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.scanner import ScanResult, scan_project
from agentmemory.store import MemoryStore

_DEFAULT_DB_PATH: Path = Path.home() / ".agentmemory" / "memory.db"


def _get_store() -> MemoryStore:
    _DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return MemoryStore(_DEFAULT_DB_PATH)


def cmd_onboard(args: argparse.Namespace) -> None:
    """Scan a project directory and ingest into memory."""
    project_path: Path = Path(args.path).expanduser().resolve()
    if not project_path.is_dir():
        print(f"Error: not a directory: {project_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {project_path.name}...")
    scan: ScanResult = scan_project(project_path)

    print(f"  Signals: git={scan.manifest.has_git}, "
          f"docs={scan.manifest.doc_count}, "
          f"languages={scan.manifest.languages}")

    # Node type counts
    node_types: dict[str, int] = {}
    for n in scan.nodes:
        node_types[n.node_type] = node_types.get(n.node_type, 0) + 1

    edge_types: dict[str, int] = {}
    for e in scan.edges:
        edge_types[e.edge_type] = edge_types.get(e.edge_type, 0) + 1

    print(f"  Nodes: {len(scan.nodes)}")
    for ntype, count in sorted(node_types.items()):
        print(f"    {ntype}: {count}")
    print(f"  Edges: {len(scan.edges)}")
    for etype, count in sorted(edge_types.items()):
        print(f"    {etype}: {count}")

    # Ingest
    print("Ingesting into memory store...")
    store: MemoryStore = _get_store()
    aggregate: IngestResult = IngestResult()

    ingested: int = 0
    total: int = sum(1 for n in scan.nodes if n.node_type != "file")
    for node in scan.nodes:
        if node.node_type == "file":
            continue

        source: str = "document"
        if node.node_type == "commit_belief":
            source = "git"
        elif node.node_type == "behavioral_belief":
            source = "directive"
        elif node.node_type == "callable":
            source = "code"

        turn_result: IngestResult = ingest_turn(
            store=store,
            text=node.content,
            source=source,
            session_id=None,
            use_llm=False,
        )
        aggregate.merge(turn_result)
        ingested += 1
        if ingested % 500 == 0:
            print(f"  ...{ingested}/{total}")

    store.close()

    timing_parts: list[str] = [f"{k}={v:.2f}s" for k, v in scan.timings.items()]
    print(f"\nDone.")
    print(f"  Observations: {aggregate.observations_created}")
    print(f"  Beliefs: {aggregate.beliefs_created}")
    print(f"  Corrections: {aggregate.corrections_detected}")
    print(f"  Timing: {', '.join(timing_parts)}")


def cmd_status(args: argparse.Namespace) -> None:
    """Show memory system status."""
    store: MemoryStore = _get_store()
    counts: dict[str, int] = store.status()
    store.close()

    print("Memory system status:")
    for key, value in counts.items():
        print(f"  {key}: {value}")


def cmd_search(args: argparse.Namespace) -> None:
    """Search for beliefs matching a query."""
    query: str = " ".join(args.query)
    if not query.strip():
        print("Error: empty query", file=sys.stderr)
        sys.exit(1)

    store: MemoryStore = _get_store()
    result: RetrievalResult = retrieve(store, query, budget=args.budget)
    store.close()

    if not result.beliefs:
        print("No beliefs found.")
        return

    print(f"Found {len(result.beliefs)} belief(s) "
          f"({result.total_tokens} tokens, {result.budget_remaining} remaining):")
    for belief in result.beliefs:
        score: float | None = result.scores.get(belief.id)
        score_str: str = f", score: {score:.3f}" if score is not None else ""
        print(f"  [{belief.confidence:.0%}] {belief.content} "
              f"(ID: {belief.id}, type: {belief.belief_type}{score_str})")


def cmd_locked(args: argparse.Namespace) -> None:
    """Show all locked beliefs."""
    store: MemoryStore = _get_store()
    from agentmemory.models import Belief
    beliefs: list[Belief] = store.get_locked_beliefs()
    store.close()

    if not beliefs:
        print("No locked beliefs.")
        return

    print(f"Locked beliefs ({len(beliefs)}):")
    for b in beliefs:
        print(f"  [{b.confidence:.0%}] {b.content} (ID: {b.id})")


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="agentmemory",
        description="Persistent memory for AI coding agents",
    )
    subparsers = parser.add_subparsers(dest="command")

    # onboard
    p_onboard: argparse.ArgumentParser = subparsers.add_parser(
        "onboard", help="Scan and ingest a project directory"
    )
    p_onboard.add_argument("path", help="Project directory to onboard")
    p_onboard.set_defaults(func=cmd_onboard)

    # status
    p_status: argparse.ArgumentParser = subparsers.add_parser(
        "status", help="Show memory system status"
    )
    p_status.set_defaults(func=cmd_status)

    # search
    p_search: argparse.ArgumentParser = subparsers.add_parser(
        "search", help="Search beliefs"
    )
    p_search.add_argument("query", nargs="+", help="Search query")
    p_search.add_argument("--budget", type=int, default=2000, help="Token budget")
    p_search.set_defaults(func=cmd_search)

    # locked
    p_locked: argparse.ArgumentParser = subparsers.add_parser(
        "locked", help="Show locked beliefs"
    )
    p_locked.set_defaults(func=cmd_locked)

    args: argparse.Namespace = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
