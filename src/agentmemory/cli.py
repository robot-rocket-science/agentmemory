"""CLI entry point for agentmemory.

Provides direct commands that execute without LLM involvement:
  agentmemory setup              -- install commands, MCP config, commit hook
  agentmemory onboard <path>     -- scan and ingest a project
  agentmemory stats              -- detailed analytics
  agentmemory health             -- diagnostics
  agentmemory core [--top N]     -- top N beliefs by confidence
  agentmemory search <query>     -- search beliefs
  agentmemory locked             -- show locked beliefs
  agentmemory remember <text>    -- store a new belief
  agentmemory lock <text>        -- create a locked belief
  agentmemory delete <id> [...]   -- soft-delete beliefs by ID
  agentmemory timeline           -- beliefs ordered by time with filters
  agentmemory evolution          -- trace belief/topic evolution
  agentmemory diff <since>       -- show what changed since a time
  agentmemory commit-check       -- check time/changes since last commit
  agentmemory commit-config      -- view or update commit tracker settings
  agentmemory help               -- command reference
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any, cast

from agentmemory.config import (
    get_setting,
    load_config as load_mem_config,
    save_config as save_mem_config,
)
from agentmemory.commit_tracker import (
    CommitCheckResult,
    CommitTrackerConfig,
    check_commit_status,
    format_status,
    load_config as load_commit_config,
    save_config as save_commit_config,
)
from agentmemory.ingest import IngestResult, ingest_turn
from agentmemory.models import Belief, Edge
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.scoring import score_belief, uncertainty_score
from agentmemory.scanner import ScanResult, scan_project
from agentmemory.store import MemoryStore

_AGENTMEMORY_HOME: Path = Path.home() / ".agentmemory"
_COMMANDS_DIR: Path = Path.home() / ".claude" / "commands" / "mem"
_PACKAGE_ROOT: Path = Path(__file__).parent.parent.parent
_active_project: Path | None = None


def _project_db_path(project_dir: Path) -> Path:
    """Compute the isolated DB path for a project directory."""
    import hashlib
    abs_path: str = str(project_dir.resolve())
    path_hash: str = hashlib.sha256(abs_path.encode()).hexdigest()[:12]
    db_dir: Path = _AGENTMEMORY_HOME / "projects" / path_hash
    db_dir.mkdir(parents=True, exist_ok=True)
    # Breadcrumb to map hash -> project path
    meta_path: Path = db_dir / "project.txt"
    if not meta_path.exists():
        meta_path.write_text(abs_path + "\n", encoding="utf-8")
    return db_dir / "memory.db"


def _resolve_db_path() -> Path:
    """Resolve DB path: AGENTMEMORY_DB env > --project flag > cwd."""
    import os
    env_db: str | None = os.environ.get("AGENTMEMORY_DB")
    if env_db:
        p: Path = Path(env_db)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    if _active_project is not None:
        return _project_db_path(_active_project)
    return _project_db_path(Path.cwd())


def _get_store() -> MemoryStore:
    db_path: Path = _resolve_db_path()
    return MemoryStore(db_path)


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

_COMMAND_DEFS: dict[str, dict[str, str]] = {
    "onboard": {
        "description": "Scan a project directory and ingest it into agentmemory.",
        "argument_hint": "Path to project directory (e.g. . or ~/projects/myapp)",
        "tools": "Agent",
        "objective": "Onboard a project into agentmemory with LLM classification.",
        "process": (
            "1. Call MCP tool `mcp__agentmemory__onboard` with the project path.\n"
            "   This extracts observations and returns sentences as JSON (no beliefs created yet).\n"
            "2. Display the onboard summary (node counts, edge counts, timing).\n"
            "3. Parse sentences from the JSON between SENTENCES_JSON_START and SENTENCES_JSON_END markers.\n"
            "4. Batch sentences into groups of 20.\n"
            "5. For each batch, spawn a Haiku subagent (model=haiku) with this prompt:\n"
            '   "You are classifying sentences extracted from project files for a memory system.\n'
            "   For EACH sentence, classify on THREE dimensions:\n"
            "   1. persist: PERSIST (remember across sessions) or EPHEMERAL (discard)\n"
            "   2. type: REQUIREMENT, PREFERENCE, FACT, ASSUMPTION, DECISION, ANALYSIS, COORDINATION, QUESTION, or META\n"
            "      NOTE: Do NOT use CORRECTION. These are document extracts, not live conversation.\n"
            "      Statements like 'not X, but Y' are FACT or DECISION, not corrections.\n"
            "   3. author: USER (human-written: direct, terse, imperative), AGENT (AI-written: structured, hedged, analytical), or UNKNOWN\n"
            "   Be conservative: when in doubt, EPHEMERAL.\n"
            "   Sentences:\\n{numbered list}\\n\n"
            '   Respond as JSON array: [{id, persist, type, author}]"\n'
            "   Spawn up to 5 batches in parallel.\n"
            "6. Collect classification results from all subagents.\n"
            "7. Merge classification results back into the sentence objects (add type, persist, and author fields).\n"
            "8. Call `mcp__agentmemory__create_beliefs` with the classified JSON.\n"
            "9. Display the belief creation summary.\n"
        ),
    },
    "stats": {
        "description": "Show detailed agentmemory analytics: confidence distribution, beliefs by type, age.",
        "argument_hint": "",
        "tools": "Bash",
        "objective": "Show detailed memory system analytics.",
        "process": "Run: `uv run agentmemory stats`\nDisplay the output. Do not add commentary.",
    },
    "health": {
        "description": "Run agentmemory diagnostics.",
        "argument_hint": "",
        "tools": "Bash",
        "objective": "Run memory system diagnostics.",
        "process": "Run: `uv run agentmemory health`\nDisplay the output. Do not add commentary.",
    },
    "core": {
        "description": "Show the top N highest-confidence beliefs.",
        "argument_hint": "Optional: number of beliefs to show (default 10)",
        "tools": "Bash",
        "objective": "Show the most important beliefs the system holds.",
        "process": "Run: `uv run agentmemory core --top ${ARGUMENTS:-10}`\nDisplay the output. Do not add commentary.",
    },
    "search": {
        "description": "Search agentmemory beliefs for a query.",
        "argument_hint": "Search query",
        "tools": "Bash",
        "objective": "Search memory for relevant beliefs.",
        "process": "Run: `uv run agentmemory search $ARGUMENTS`\nDisplay the output. Do not add commentary.",
    },
    "locked": {
        "description": "Show all locked beliefs (non-negotiable constraints).",
        "argument_hint": "",
        "tools": "Bash",
        "objective": "Show all locked beliefs.",
        "process": "Run: `uv run agentmemory locked`\nDisplay the output. Do not add commentary.",
    },
    "new-belief": {
        "description": "Store a new belief in agentmemory.",
        "argument_hint": "The belief text to store",
        "tools": "Bash",
        "objective": "Store a new belief.",
        "process": "Run: `uv run agentmemory remember \"$ARGUMENTS\"`\nDisplay the output. Do not add commentary.",
    },
    "lock": {
        "description": "Create a locked belief (non-negotiable constraint).",
        "argument_hint": "The constraint text to lock",
        "tools": "Bash",
        "objective": "Create a locked belief.",
        "process": "Run: `uv run agentmemory lock \"$ARGUMENTS\"`\nDisplay the output. Do not add commentary.",
    },
    "delete": {
        "description": "Soft-delete beliefs by ID. Beliefs are excluded from search and retrieval but remain in the database.",
        "argument_hint": "One or more belief IDs (space-separated)",
        "tools": "Bash",
        "objective": "Remove beliefs that are duplicates, stale, or incorrect.",
        "process": "Run: `uv run agentmemory delete $ARGUMENTS`\nDisplay the output. Do not add commentary.",
    },
    "wonder": {
        "description": "Deep-dive research on a hypothesis, question, or topic using memory graph context.",
        "argument_hint": "A hypothesis, question, or research topic",
        "tools": "Bash, Read, WebSearch, Agent",
        "objective": "Gather all beliefs and associations connected to the query, then spawn parallel subagents for deep research.",
        "process": (
            "1. Run: `uv run agentmemory wonder \"$ARGUMENTS\"` to get belief context.\n"
            "2. Run: `uv run agentmemory settings` to read wonder.max_agents (default 4).\n"
            "3. Parse the belief context output into themes or angles.\n"
            "4. Spawn up to max_agents subagents in parallel using the Agent tool. "
            "Each subagent gets:\n"
            "   - The original wonder query\n"
            "   - The full belief context from step 1\n"
            "   - A specific research angle or theme to investigate\n"
            "   Suggested agent assignments:\n"
            "   - Agent 1: Search for prior art, related work, existing solutions\n"
            "   - Agent 2: Identify gaps, contradictions, or weak spots in current beliefs\n"
            "   - Agent 3: Generate hypotheses and propose experiments to test them\n"
            "   - Agent 4: Synthesize findings and map connections to the existing graph\n"
            "   Additional agents can explore domain-specific angles as needed.\n"
            "5. Collect results from all subagents.\n"
            "6. Present a structured analysis:\n"
            "   - What the memory system already knows (from beliefs)\n"
            "   - What was discovered (from research)\n"
            "   - Gaps and open questions\n"
            "   - Proposed next steps or experiments\n"
        ),
    },
    "settings": {
        "description": "View or update agentmemory settings.",
        "argument_hint": "Optional: --key value pairs to update",
        "tools": "Bash, AskUserQuestion",
        "objective": "View or interactively configure agentmemory settings.",
        "process": (
            "Run: `uv run agentmemory settings`\n"
            "Display the current settings.\n"
            "If the user wants to change something, use AskUserQuestion to present options, "
            "then run `agentmemory settings --<key> <value>` to update."
        ),
    },
    "reason": {
        "description": "Focused reasoning about a problem using graph-aware retrieval and uncertainty analysis.",
        "argument_hint": "A statement or topic to reason about",
        "tools": "Bash, Read, WebSearch, Agent",
        "objective": "Use multi-hop graph retrieval and uncertainty signals to reason deeply about the given topic.",
        "process": (
            "1. Run: `uv run agentmemory reason \"$ARGUMENTS\"` to get structured evidence context.\n"
            "2. Run: `uv run agentmemory settings` to read reason.max_agents and reason.depth.\n"
            "3. Analyze the structured output. It contains:\n"
            "   - DIRECT EVIDENCE: FTS5 matches with confidence scores\n"
            "   - CONNECTED EVIDENCE: Graph-expanded beliefs with edge types and hop distance\n"
            "   - HIGH-UNCERTAINTY BELIEFS: Beliefs where the system has insufficient evidence\n"
            "   - CONTRADICTIONS: Pairs of beliefs that contradict each other\n"
            "4. Build a reasoning chain:\n"
            "   - Start from the highest-confidence direct evidence\n"
            "   - Follow graph connections to build supporting arguments\n"
            "   - Note where the chain relies on high-uncertainty beliefs\n"
            "   - Note where contradictions block a clear conclusion\n"
            "5. If the reasoning chain has gaps or relies on uncertain beliefs, spawn up to "
            "max_agents subagents using the Agent tool. Each subagent gets:\n"
            "   - The original reason query\n"
            "   - ONE specific investigation task (not the full evidence dump)\n"
            "   - Assign roles based on need: Verifier (check uncertain belief), "
            "Gap-filler (research missing info), Contradiction-resolver (which is correct?)\n"
            "   If the evidence is sufficient, skip subagent dispatch entirely.\n"
            "6. Collect subagent results (if any).\n"
            "7. Present the reasoned analysis:\n"
            "   - ANSWER: Direct response based on evidence\n"
            "   - EVIDENCE CHAIN: Beliefs and connections supporting the answer\n"
            "   - CONFIDENCE: How confident the reasoning is, citing uncertain links\n"
            "   - OPEN QUESTIONS: Anything that could not be resolved\n"
            "   - SUGGESTED UPDATES: Beliefs whose confidence should change based on findings\n"
        ),
    },
    "disable": {
        "description": "Disable agentmemory for the rest of this session.",
        "argument_hint": "",
        "tools": "",
        "objective": "Disable all agentmemory MCP tool calls for this session.",
        "process": (
            "Acknowledge that agentmemory is disabled. "
            "Stop calling ALL mcp__agentmemory__* tools for the rest of this session. "
            "Do not search, observe, ingest, or call any agentmemory tools until /mem:enable is invoked."
        ),
    },
    "unlock": {
        "description": "Unlock least-relevant locked beliefs back to regular beliefs.",
        "argument_hint": "Optional: --count N (default 5)",
        "tools": "Bash",
        "objective": "Unlock the least-relevant locked beliefs.",
        "process": "Run: `uv run agentmemory unlock --count ${ARGUMENTS:-5}`\nDisplay the output. Do not add commentary.",
    },
    "enable": {
        "description": "Re-enable agentmemory after /mem:disable.",
        "argument_hint": "",
        "tools": "",
        "objective": "Re-enable agentmemory MCP tool calls.",
        "process": (
            "Acknowledge that agentmemory is re-enabled. "
            "Resume calling agentmemory MCP tools as normal per CLAUDE.md instructions."
        ),
    },
    "help": {
        "description": "Show available mem commands and usage guide.",
        "argument_hint": "",
        "tools": "",
        "objective": "Display the agentmemory command reference.",
        "process": (
            "Display this command reference:\n\n"
            "  /mem:onboard <path>     Scan and ingest a project\n"
            "  /mem:stats              Detailed analytics\n"
            "  /mem:health             Diagnostics\n"
            "  /mem:core [N]           Top N beliefs by confidence\n"
            "  /mem:search <query>     Search beliefs\n"
            "  /mem:locked             Show locked beliefs\n"
            "  /mem:new-belief <text>  Store a new belief\n"
            "  /mem:lock <text>        Create a locked belief\n"
            "  /mem:wonder <topic>     Deep research from graph context\n"
            "  /mem:settings           View or update settings\n"
            "  /mem:disable            Stop agentmemory for this session\n"
            "  /mem:enable             Resume agentmemory\n"
            "  /mem:help               This reference\n"
        ),
    },
}


def _render_command_md(name: str, defn: dict[str, str]) -> str:
    """Render a command .md file in GSD format."""
    lines: list[str] = ["---", f"name: mem:{name}"]
    lines.append(f"description: {defn['description']}")
    if defn.get("argument_hint"):
        lines.append(f"argument-hint: {defn['argument_hint']}")
    if defn.get("tools"):
        lines.append("allowed-tools:")
        for tool in defn["tools"].split(", "):
            lines.append(f"  - {tool}")
    lines.append("---")
    lines.append(f"<objective>")
    lines.append(defn["objective"])
    lines.append("</objective>")
    lines.append("")
    lines.append("<process>")
    lines.append(defn["process"])
    lines.append("</process>")
    return "\n".join(lines) + "\n"


def cmd_setup(args: argparse.Namespace) -> None:
    """Install agentmemory commands and MCP config."""
    print("Setting up agentmemory...")

    # Step 1: Create command .md files
    _COMMANDS_DIR.mkdir(parents=True, exist_ok=True)
    for name, defn in _COMMAND_DEFS.items():
        cmd_path: Path = _COMMANDS_DIR / f"{name}.md"
        cmd_path.write_text(_render_command_md(name, defn))
    print(f"  Created {len(_COMMAND_DEFS)} commands in {_COMMANDS_DIR}")

    # Step 2: Clean up old skill-based commands (legacy)
    old_skills_dir: Path = Path.home() / ".claude" / "skills"
    old_prefixes: list[str] = [
        "mem-correct", "mem-ingest", "mem-locked", "mem-observe",
        "mem-onboard", "mem-remember", "mem-search", "mem-status",
    ]
    cleaned: int = 0
    for prefix in old_prefixes:
        old_path: Path = old_skills_dir / prefix
        if old_path.is_dir():
            shutil.rmtree(old_path)
            cleaned += 1
    # Also clean old project-level commands
    old_project_cmds: Path = Path.cwd() / ".claude" / "commands"
    for old_file in ["onboard.md", "mem-status.md", "mem-search.md", "mem-locked.md"]:
        old_cmd: Path = old_project_cmds / old_file
        if old_cmd.exists():
            old_cmd.unlink()
            cleaned += 1
    if cleaned > 0:
        print(f"  Cleaned {cleaned} legacy skill/command files")

    # Step 3: Ensure agentmemory CLI is accessible
    agentmemory_bin: str | None = shutil.which("agentmemory")
    if agentmemory_bin is None:
        print("  Warning: 'agentmemory' not found on PATH.", file=sys.stderr)
        print("  Commands will use 'uv run agentmemory' as fallback.", file=sys.stderr)

    # Step 4: Verify DB is accessible
    db_path: Path = _resolve_db_path()
    store: MemoryStore = _get_store()
    counts: dict[str, int] = store.status()
    store.close()
    print(f"\n  Database: {db_path}")
    print(f"  Beliefs: {counts.get('beliefs', 0)}, Locked: {counts.get('locked', 0)}")

    # Step 5: Install commit tracker hook
    _install_commit_hook(agentmemory_bin)

    # Step 6: Smoke test
    print("\n  Smoke test...")
    import subprocess
    smoke: subprocess.CompletedProcess[str] = subprocess.run(
        ["uv", "run", "agentmemory", "stats"],
        capture_output=True, text=True, timeout=10,
    )
    if smoke.returncode == 0:
        print("  OK: CLI works")
    else:
        print(f"  FAIL: agentmemory stats returned exit code {smoke.returncode}", file=sys.stderr)
        if smoke.stderr:
            print(f"  {smoke.stderr[:200]}", file=sys.stderr)

    print(f"\nDone. Restart Claude Code, then run /mem:onboard . on your project.")


# ---------------------------------------------------------------------------
# onboard
# ---------------------------------------------------------------------------


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

    print("Ingesting into memory store...")
    store: MemoryStore = _get_store()
    aggregate: IngestResult = IngestResult()

    # Map scanner node IDs to belief IDs via content hash
    import hashlib as _hashlib
    node_to_belief: dict[str, str] = {}

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
            created_at=node.date,
            source_path=node.file or "",
            source_id=node.id,
            event_time=node.date,
        )
        aggregate.merge(turn_result)

        # Look up the belief created from this node's content
        content_hash: str = _hashlib.sha256(node.content.encode()).hexdigest()[:12]
        belief: Belief | None = store.get_belief_by_hash(content_hash)
        if belief is not None:
            node_to_belief[node.id] = belief.id

        ingested += 1
        if ingested % 500 == 0:
            print(f"  ...{ingested}/{total}")

    print(f"  Mapped {len(node_to_belief)} scanner nodes to belief IDs")

    # Store structural edges, translating scanner IDs to belief IDs where possible
    edge_count: int = 0
    for edge in scan.edges:
        # Use belief IDs if we have them, otherwise keep scanner IDs
        src: str = node_to_belief.get(edge.src, edge.src)
        tgt: str = node_to_belief.get(edge.tgt, edge.tgt)
        store.insert_graph_edge(
            from_id=src,
            to_id=tgt,
            edge_type=edge.edge_type,
            weight=edge.weight,
            reason="scanner",
        )
        edge_count += 1
    if edge_count > 0:
        print(f"  Stored {edge_count} structural edges")

    store.close()

    timing_parts: list[str] = [f"{k}={v:.2f}s" for k, v in scan.timings.items()]
    print(f"\nDone.")
    print(f"  Observations: {aggregate.observations_created}")
    print(f"  Beliefs: {aggregate.beliefs_created}")
    print(f"  Corrections: {aggregate.corrections_detected}")
    print(f"  Edges: {edge_count}")
    print(f"  Timing: {', '.join(timing_parts)}")


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


def cmd_stats(args: argparse.Namespace) -> None:
    """Show detailed analytics."""
    db_path: Path = _resolve_db_path()
    store: MemoryStore = _get_store()
    counts: dict[str, int] = store.status()

    # Belief type breakdown
    type_rows: list[sqlite3.Row] = store.query(
        "SELECT belief_type, COUNT(*) as cnt FROM beliefs "
        "WHERE valid_to IS NULL GROUP BY belief_type ORDER BY cnt DESC"
    )
    # Confidence distribution
    conf_rows: list[sqlite3.Row] = store.query(
        "SELECT confidence FROM beliefs WHERE valid_to IS NULL"
    )
    # Source breakdown
    src_rows: list[sqlite3.Row] = store.query(
        "SELECT source_type, COUNT(*) as cnt FROM beliefs "
        "WHERE valid_to IS NULL GROUP BY source_type ORDER BY cnt DESC"
    )
    store.close()

    print(f"Memory system stats ({db_path}):")
    print(f"  Observations: {counts.get('observations', 0)}")
    print(f"  Beliefs: {counts.get('beliefs', 0)}")
    print(f"  Locked: {counts.get('locked', 0)}")
    print(f"  Superseded: {counts.get('superseded', 0)}")
    print(f"  Edges: {counts.get('edges', 0)}")
    print(f"  Sessions: {counts.get('sessions', 0)}")

    if type_rows:
        print("\n  By type:")
        for row in type_rows:
            print(f"    {row['belief_type']}: {row['cnt']}")

    if src_rows:
        print("\n  By source:")
        for row in src_rows:
            print(f"    {row['source_type']}: {row['cnt']}")

    if conf_rows:
        confidences: list[float] = [float(str(r["confidence"])) for r in conf_rows]
        confidences.sort()
        n: int = len(confidences)
        print(f"\n  Confidence distribution (n={n}):")
        if n > 0:
            print(f"    min: {confidences[0]:.3f}")
            print(f"    p25: {confidences[n // 4]:.3f}")
            print(f"    p50: {confidences[n // 2]:.3f}")
            print(f"    p75: {confidences[3 * n // 4]:.3f}")
            print(f"    max: {confidences[-1]:.3f}")


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


def cmd_health(args: argparse.Namespace) -> None:
    """Run diagnostics."""
    # Show stats first
    cmd_stats(args)
    print("\n  Diagnostics:")
    print("    TODO: implement diagnostic checks")
    print("    - orphaned beliefs (no observation link)")
    print("    - graph connectivity issues")
    print("    - stale/incomplete sessions")
    print("    - FTS5 index integrity")


# ---------------------------------------------------------------------------
# core
# ---------------------------------------------------------------------------


def cmd_core(args: argparse.Namespace) -> None:
    """Show top N beliefs by composite core score."""
    from datetime import datetime as dt
    from datetime import timezone as tz

    from agentmemory.scoring import core_score

    top_n: int = args.top
    now_iso: str = dt.now(tz.utc).isoformat()
    store: MemoryStore = _get_store()

    # Fetch all active beliefs and score them
    rows: list[sqlite3.Row] = store.query(
        "SELECT * FROM beliefs WHERE valid_to IS NULL"
    )
    store.close()

    if not rows:
        print("No beliefs found.")
        return

    # Convert rows to Belief objects for scoring
    scored: list[tuple[Belief, float]] = []
    for row in rows:
        b: Belief = Belief(
            id=str(row["id"]),
            content_hash=str(row["content_hash"]),
            content=str(row["content"]),
            belief_type=str(row["belief_type"]),
            alpha=float(str(row["alpha"])),
            beta_param=float(str(row["beta_param"])),
            confidence=float(str(row["confidence"])),
            source_type=str(row["source_type"]),
            locked=bool(row["locked"]),
            valid_from=str(row["valid_from"]) if row["valid_from"] else None,
            valid_to=str(row["valid_to"]) if row["valid_to"] else None,
            superseded_by=str(row["superseded_by"]) if row["superseded_by"] else None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
        scored.append((b, core_score(b, now_iso)))

    scored.sort(key=lambda x: x[1], reverse=True)
    top: list[tuple[Belief, float]] = scored[:top_n]

    print(f"Top {top_n} core beliefs:")
    for i, (b, s) in enumerate(top, 1):
        locked_str: str = " [LOCKED]" if b.locked else ""
        print(f"  {i}. [score {s:.2f}]{locked_str} {b.content}")
        print(f"     type: {b.belief_type}, source: {b.source_type}, id: {b.id}")


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


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
        locked_str: str = " [LOCKED]" if belief.locked else ""
        print(f"  [{belief.confidence:.0%}]{locked_str} {belief.content} "
              f"(ID: {belief.id}, type: {belief.belief_type}{score_str})")


# ---------------------------------------------------------------------------
# locked
# ---------------------------------------------------------------------------


def cmd_locked(args: argparse.Namespace) -> None:
    """Show all locked beliefs."""
    store: MemoryStore = _get_store()
    beliefs: list[Belief] = store.get_locked_beliefs()
    store.close()

    if not beliefs:
        print("No locked beliefs.")
        return

    warn_at: int = get_setting("locked", "warn_at")
    max_cap: int = get_setting("locked", "max_cap")

    print(f"Locked beliefs ({len(beliefs)}):")
    for b in beliefs:
        print(f"  [{b.confidence:.0%}] {b.content} (ID: {b.id})")

    if len(beliefs) >= warn_at:
        print(f"\n  WARNING: {len(beliefs)} locked beliefs (warn threshold: {warn_at}, cap: {max_cap})")
        print("  Consider unlocking least-relevant locked beliefs.")
        print("  Run: agentmemory unlock [--count N] to unlock the N least-relevant.")


# ---------------------------------------------------------------------------
# remember (new-belief)
# ---------------------------------------------------------------------------


def cmd_remember(args: argparse.Namespace) -> None:
    """Store a new belief (high prior, NOT locked)."""
    text: str = " ".join(args.text)
    if not text.strip():
        print("Error: empty belief text", file=sys.stderr)
        sys.exit(1)

    store: MemoryStore = _get_store()
    belief: Belief = store.insert_belief(
        content=text,
        belief_type="factual",
        source_type="user_stated",
        alpha=9.0,
        beta_param=0.5,
        locked=False,
    )
    store.close()

    print(f"Stored belief (ID: {belief.id}): {belief.content}")
    print(f"  confidence: {belief.confidence:.0%}, locked: {belief.locked}")


# ---------------------------------------------------------------------------
# lock
# ---------------------------------------------------------------------------


def cmd_lock(args: argparse.Namespace) -> None:
    """Create a locked belief."""
    text: str = " ".join(args.text)
    if not text.strip():
        print("Error: empty belief text", file=sys.stderr)
        sys.exit(1)

    store: MemoryStore = _get_store()
    belief: Belief = store.insert_belief(
        content=text,
        belief_type="factual",
        source_type="user_stated",
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )
    store.close()

    print(f"Locked belief (ID: {belief.id}): {belief.content}")
    print(f"  confidence: {belief.confidence:.0%}, locked: {belief.locked}")


# ---------------------------------------------------------------------------
# wonder (stub)
# ---------------------------------------------------------------------------


def cmd_wonder(args: argparse.Namespace) -> None:
    """Gather graph context for deep research. Stub -- full implementation TODO."""
    query: str = " ".join(args.query)
    if not query.strip():
        print("Error: empty query", file=sys.stderr)
        sys.exit(1)

    store: MemoryStore = _get_store()
    result: RetrievalResult = retrieve(store, query, budget=4000)
    store.close()

    if not result.beliefs:
        print(f"No beliefs found for: {query}")
        print("The memory system has no context on this topic yet.")
        return

    print(f"Wonder: {query}")
    print(f"Found {len(result.beliefs)} related belief(s):\n")
    for belief in result.beliefs:
        locked_str: str = " [LOCKED]" if belief.locked else ""
        print(f"  [{belief.confidence:.0%}]{locked_str} {belief.content}")
    print("\n--- Graph context above. Deep research prompt template: TODO ---")


# ---------------------------------------------------------------------------
# reason
# ---------------------------------------------------------------------------


def cmd_reason(args: argparse.Namespace) -> None:
    """Graph-aware reasoning with uncertainty analysis.

    Retrieves beliefs via FTS5, expands along graph edges (BFS),
    computes uncertainty scores, detects contradictions, and outputs
    structured evidence for LLM reasoning.
    """
    query: str = " ".join(args.query)
    if not query.strip():
        print("Error: empty query", file=sys.stderr)
        sys.exit(1)

    depth: int = args.depth if args.depth is not None else int(
        get_setting("reason", "depth") or 2
    )
    budget: int = args.budget

    store: MemoryStore = _get_store()

    # Step 1: FTS5 retrieval
    result: RetrievalResult = retrieve(store, query, budget=budget)

    if not result.beliefs:
        print("No beliefs found matching your query.")
        store.close()
        return

    # Step 2: Graph expansion from top 10 seeds
    seed_ids: list[str] = [b.id for b in result.beliefs[:10]]
    expanded: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph(
        seed_ids, depth=depth,
    )

    # Step 3: Merge and deduplicate
    all_beliefs: dict[str, Belief] = {}
    belief_hops: dict[str, int] = {}  # belief_id -> min hop distance
    belief_edges: dict[str, str] = {}  # belief_id -> edge type that found it

    for b in result.beliefs:
        all_beliefs[b.id] = b
        belief_hops[b.id] = 0

    for _bid, exp_neighbors in expanded.items():
        for neighbor_belief, edge_type, hop in exp_neighbors:
            if neighbor_belief.id not in all_beliefs:
                all_beliefs[neighbor_belief.id] = neighbor_belief
            if neighbor_belief.id not in belief_hops or hop < belief_hops[neighbor_belief.id]:
                belief_hops[neighbor_belief.id] = hop
                belief_edges[neighbor_belief.id] = edge_type

    # Step 4: Compute uncertainty for each belief
    belief_uncertainty: dict[str, float] = {}
    for bid, b in all_beliefs.items():
        belief_uncertainty[bid] = uncertainty_score(b.alpha, b.beta_param)

    # Step 5: Detect contradictions
    contradictions: list[tuple[Belief, Belief]] = []
    result_ids: set[str] = set(all_beliefs.keys())
    for bid in result_ids:
        neighbors: list[tuple[Belief, Edge]] = store.get_neighbors(
            bid, edge_types=["CONTRADICTS"], direction="both",
        )
        for neighbor_belief, _edge in neighbors:
            if neighbor_belief.id in result_ids and neighbor_belief.id > bid:
                contradictions.append(
                    (all_beliefs[bid], neighbor_belief)
                )

    store.close()

    # Step 6: Format structured output
    direct: list[Belief] = [
        b for b in result.beliefs if belief_hops.get(b.id, 0) == 0
    ]
    connected: list[tuple[Belief, str, int]] = []
    for bid, b in all_beliefs.items():
        hop: int = belief_hops.get(bid, 0)
        if hop > 0:
            etype: str = belief_edges.get(bid, "RELATES_TO")
            connected.append((b, etype, hop))
    connected.sort(key=lambda x: (x[2], -x[0].confidence))

    high_uncertainty: list[tuple[Belief, float]] = [
        (b, belief_uncertainty[bid])
        for bid, b in all_beliefs.items()
        if belief_uncertainty[bid] > 0.7
    ]
    high_uncertainty.sort(key=lambda x: x[1], reverse=True)

    # Print
    print(f"QUERY: {query}")
    print(f"  Depth: {depth}, Direct hits: {len(direct)}, "
          f"Graph-expanded: {len(connected)}, "
          f"High-uncertainty: {len(high_uncertainty)}, "
          f"Contradictions: {len(contradictions)}")

    print(f"\nDIRECT EVIDENCE (Level 1 -- {len(direct)} beliefs):")
    for b in direct:
        locked_str: str = " [LOCKED]" if b.locked else ""
        unc: float = belief_uncertainty.get(b.id, 0.0)
        print(f"  [{b.confidence:.0%}]{locked_str} {b.content}")
        print(f"    type: {b.belief_type}, uncertainty: {unc:.2f}, id: {b.id}")

    if connected:
        print(f"\nCONNECTED EVIDENCE (Level 2-3 -- {len(connected)} beliefs):")
        for b, etype, hop in connected:
            locked_str = " [LOCKED]" if b.locked else ""
            print(f"  [hop {hop}] [{b.confidence:.0%}]{locked_str} {b.content}")
            print(f"    via {etype}, type: {b.belief_type}, id: {b.id}")

    if high_uncertainty:
        print(f"\nHIGH-UNCERTAINTY BELIEFS ({len(high_uncertainty)} beliefs):")
        for b, unc in high_uncertainty:
            hop = belief_hops.get(b.id, 0)
            print(f"  [{b.confidence:.0%}, uncertainty: {unc:.2f}] {b.content}")
            print(f"    alpha: {b.alpha}, beta: {b.beta_param}, hop: {hop}, id: {b.id}")

    if contradictions:
        print(f"\nCONTRADICTIONS ({len(contradictions)} pairs):")
        for a, b in contradictions:
            print(f"  \"{a.content[:80]}\"")
            print(f"    CONTRADICTS")
            print(f"  \"{b.content[:80]}\"")
            print()

    if not connected and not high_uncertainty and not contradictions:
        print("\n  (No graph edges, uncertainty flags, or contradictions found.)")
        print("  Reason output is equivalent to a standard search at this graph density.")


# ---------------------------------------------------------------------------
# unlock
# ---------------------------------------------------------------------------


def cmd_unlock(args: argparse.Namespace) -> None:
    """Unlock the least-relevant locked beliefs back to regular beliefs."""
    count: int = args.count
    store: MemoryStore = _get_store()
    beliefs: list[Belief] = store.get_locked_beliefs()

    if not beliefs:
        print("No locked beliefs to unlock.")
        store.close()
        return

    if len(beliefs) <= count:
        print(f"Only {len(beliefs)} locked beliefs exist. Nothing to unlock.")
        store.close()
        return

    # Score all locked beliefs and pick the lowest-scoring ones
    current_time: str = _now_iso()
    scored: list[tuple[Belief, float]] = []
    for b in beliefs:
        s: float = score_belief(b, "", current_time)
        scored.append((b, s))

    scored.sort(key=lambda x: x[1])
    to_unlock: list[tuple[Belief, float]] = scored[:count]

    print(f"Unlocking {len(to_unlock)} least-relevant locked beliefs:")
    for b, s in to_unlock:
        store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "UPDATE beliefs SET locked = 0, updated_at = ? WHERE id = ?",
            (current_time, b.id),
        )
        store._conn.commit()  # pyright: ignore[reportPrivateUsage]
        print(f"  Unlocked: [{b.confidence:.0%}] {b.content} (ID: {b.id}, score: {s:.3f})")

    store.close()
    print(f"\n{len(to_unlock)} beliefs unlocked.")


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def cmd_delete(args: argparse.Namespace) -> None:
    """Soft-delete beliefs by ID."""
    store: MemoryStore = _get_store()
    ids: list[str] = args.ids

    deleted: int = 0
    for belief_id in ids:
        belief: Belief | None = store.get_belief(belief_id)
        if belief is None:
            print(f"  Not found: {belief_id}")
            continue
        if belief.valid_to is not None:
            print(f"  Already deleted: {belief_id}")
            continue
        store.delete_belief(belief_id)
        print(f"  Deleted [{belief.confidence:.0%}] {belief.content[:80]} (ID: {belief_id})")
        deleted += 1

    store.close()
    print(f"\n{deleted} of {len(ids)} beliefs deleted.")


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _resolve_relative_time(time_str: str) -> str:
    """Resolve '-7d', '-24h', '-30m' to ISO 8601."""
    import re as _re
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    match: _re.Match[str] | None = _re.match(r"^-(\d+)([dhm])$", time_str)
    if match:
        value: int = int(match.group(1))
        unit: str = match.group(2)
        delta: _td
        if unit == "d":
            delta = _td(days=value)
        elif unit == "h":
            delta = _td(hours=value)
        else:
            delta = _td(minutes=value)
        return (_dt.now(_tz.utc) - delta).isoformat()
    return time_str


# ---------------------------------------------------------------------------
# temporal queries (Wave 2)
# ---------------------------------------------------------------------------


def cmd_timeline(args: argparse.Namespace) -> None:
    """Show beliefs ordered by time with optional filters."""
    store: MemoryStore = _get_store()
    start: str | None = _resolve_relative_time(args.since) if args.since else None
    end: str | None = _resolve_relative_time(args.until) if args.until else None
    beliefs: list[Belief] = store.timeline(
        topic=args.topic, start=start, end=end,
        session_id=args.session, limit=args.limit,
    )
    if not beliefs:
        print("No beliefs found.")
        store.close()
        return
    print(f"Timeline: {len(beliefs)} belief(s)\n")
    for b in beliefs:
        status: str = " [SUPERSEDED]" if b.valid_to else ""
        lock: str = " [LOCKED]" if b.locked else ""
        print(f"  [{b.created_at[:19]}] ({b.belief_type}){lock}{status}")
        print(f"    {b.content[:120]}")
    store.close()


def cmd_evolution(args: argparse.Namespace) -> None:
    """Trace belief or topic evolution over time."""
    store: MemoryStore = _get_store()
    beliefs: list[Belief] = store.evolution(
        belief_id=args.belief_id, topic=args.topic,
    )
    if not beliefs:
        print("No evolution chain found.")
        store.close()
        return
    print(f"Evolution: {len(beliefs)} belief(s)\n")
    for i, b in enumerate(beliefs):
        marker: str = " -> " if i > 0 else "    "
        status: str = "[SUPERSEDED]" if b.valid_to else "[CURRENT]   "
        lock: str = " [LOCKED]" if b.locked else ""
        print(f"  {marker}{status}{lock} ({b.id})")
        print(f"        [{b.created_at[:19]}] {b.content[:120]}")
    store.close()


def cmd_diff(args: argparse.Namespace) -> None:
    """Show what changed in the belief store over a time period."""
    store: MemoryStore = _get_store()
    since: str = _resolve_relative_time(args.since)
    until: str | None = _resolve_relative_time(args.until) if args.until else None
    changes: dict[str, list[Belief]] = store.diff(since=since, until=until)
    added: list[Belief] = changes["added"]
    removed: list[Belief] = changes["removed"]
    evolved: list[Belief] = changes["evolved"]

    print(f"Diff since {since[:19]}:\n")
    print(f"  ADDED: {len(added)}")
    for b in added[:10]:
        print(f"    + [{b.belief_type}] {b.content[:100]}")
    if len(added) > 10:
        print(f"    ... and {len(added) - 10} more")

    print(f"\n  REMOVED: {len(removed)}")
    for b in removed[:10]:
        print(f"    - [{b.belief_type}] {b.content[:100]}")
    if len(removed) > 10:
        print(f"    ... and {len(removed) - 10} more")

    print(f"\n  EVOLVED: {len(evolved)}")
    for b in evolved[:10]:
        print(f"    ~ [{b.belief_type}] {b.content[:100]}")
    if len(evolved) > 10:
        print(f"    ... and {len(evolved) - 10} more")
    store.close()


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------


def cmd_settings(args: argparse.Namespace) -> None:
    """View or update agentmemory settings."""
    config: dict[str, Any] = load_mem_config()

    changed: bool = False
    if args.wonder_max_agents is not None:
        wonder_section: dict[str, Any] = cast("dict[str, Any]", config.get("wonder", {}))
        wonder_section["max_agents"] = args.wonder_max_agents
        config["wonder"] = wonder_section
        changed = True
    if args.core_default_top is not None:
        core_section: dict[str, Any] = cast("dict[str, Any]", config.get("core", {}))
        core_section["default_top"] = args.core_default_top
        config["core"] = core_section
        changed = True
    if args.locked_max_cap is not None:
        locked_section: dict[str, Any] = cast("dict[str, Any]", config.get("locked", {}))
        locked_section["max_cap"] = args.locked_max_cap
        config["locked"] = locked_section
        changed = True
    if args.locked_warn_at is not None:
        locked_section2: dict[str, Any] = cast("dict[str, Any]", config.get("locked", {}))
        locked_section2["warn_at"] = args.locked_warn_at
        config["locked"] = locked_section2
        changed = True
    if args.reason_max_agents is not None:
        reason_section: dict[str, Any] = cast("dict[str, Any]", config.get("reason", {}))
        reason_section["max_agents"] = args.reason_max_agents
        config["reason"] = reason_section
        changed = True
    if args.reason_depth is not None:
        reason_section2: dict[str, Any] = cast("dict[str, Any]", config.get("reason", {}))
        reason_section2["depth"] = args.reason_depth
        config["reason"] = reason_section2
        changed = True

    if changed:
        cfg_path: Path = save_mem_config(config)
        print(f"Settings updated ({cfg_path}):")
    else:
        print("agentmemory settings:")

    w: dict[str, Any] = cast("dict[str, Any]", config.get("wonder", {}))
    r: dict[str, Any] = cast("dict[str, Any]", config.get("reason", {}))
    c: dict[str, Any] = cast("dict[str, Any]", config.get("core", {}))
    lk: dict[str, Any] = cast("dict[str, Any]", config.get("locked", {}))

    print(f"  wonder.max_agents:  {w.get('max_agents', 4)}")
    print(f"  reason.max_agents:  {r.get('max_agents', 3)}")
    print(f"  reason.depth:       {r.get('depth', 2)}")
    print(f"  core.default_top:   {c.get('default_top', 10)}")
    print(f"  locked.max_cap:     {lk.get('max_cap', 100)}")
    print(f"  locked.warn_at:     {lk.get('warn_at', 80)}")


# ---------------------------------------------------------------------------
# commit-check
# ---------------------------------------------------------------------------


def cmd_commit_check(args: argparse.Namespace) -> None:
    """Check time since last commit and uncommitted changes.

    Prints a nudge if thresholds exceeded, or a quiet status if not.
    Designed for use as a Claude Code hook target.
    Exit code is always 0 so hooks never block.
    """
    project_dir: Path = Path(args.project_dir).expanduser().resolve()
    result: CommitCheckResult = check_commit_status(project_dir)
    if args.nudge_only:
        if result.nudge:
            print(result.nudge)
    else:
        output: str = format_status(result)
        if output:
            print(output)


# ---------------------------------------------------------------------------
# commit-config
# ---------------------------------------------------------------------------


def cmd_commit_config(args: argparse.Namespace) -> None:
    """View or update commit tracker settings."""
    config: CommitTrackerConfig = load_commit_config()

    changed: bool = False
    if args.enable:
        config.enabled = True
        changed = True
    if args.disable:
        config.enabled = False
        changed = True
    if args.max_minutes is not None:
        config.max_seconds = args.max_minutes * 60
        changed = True
    if args.max_changes is not None:
        config.max_changes = args.max_changes
        changed = True

    if changed:
        path: Path = save_commit_config(config)
        print(f"Config updated: {path}")

    print("Commit tracker config:")
    print(f"  enabled: {config.enabled}")
    print(f"  max_minutes: {config.max_seconds // 60}")
    print(f"  max_changes: {config.max_changes}")


# ---------------------------------------------------------------------------
# hook installer
# ---------------------------------------------------------------------------

_HOOK_MATCHER: str = "agentmemory commit-check"

_SETTINGS_PATH: Path = Path.home() / ".claude" / "settings.json"


def _install_commit_hook(agentmemory_bin: str | None) -> None:
    """Add a PreToolUse hook to Claude Code settings.json.

    The hook calls `agentmemory commit-check` before each tool use.
    If the hook already exists, it is left as-is. Idempotent.
    """
    cmd: str = "agentmemory" if agentmemory_bin else "uv run agentmemory"

    hook_entry: dict[str, object] = {
        "hooks": {
            "PreToolUse": [
                {
                    "type": "command",
                    "command": f"{cmd} commit-check",
                }
            ]
        }
    }

    if not _SETTINGS_PATH.exists():
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_PATH.write_text(json.dumps(hook_entry, indent=2) + "\n")
        print(f"  Installed commit tracker hook in {_SETTINGS_PATH}")
        return

    try:
        settings: dict[str, Any] = json.loads(_SETTINGS_PATH.read_text())
    except (json.JSONDecodeError, ValueError):
        print(
            f"  Warning: could not parse {_SETTINGS_PATH}, skipping hook install",
            file=sys.stderr,
        )
        return

    hooks: dict[str, Any] = cast(
        dict[str, Any],
        settings.get("hooks") if isinstance(settings.get("hooks"), dict) else {},
    )

    pre_tool: list[Any] = cast(
        list[Any],
        hooks.get("PreToolUse") if isinstance(hooks.get("PreToolUse"), list) else [],
    )

    # Check if already installed
    for entry in pre_tool:
        if isinstance(entry, dict):
            cmd_val: str = str(cast(dict[str, Any], entry).get("command", ""))
            if _HOOK_MATCHER in cmd_val:
                print("  Commit tracker hook already installed")
                return

    pre_tool.append({
        "type": "command",
        "command": f"{cmd} commit-check",
    })
    hooks["PreToolUse"] = pre_tool
    settings["hooks"] = hooks
    _SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"  Installed commit tracker hook in {_SETTINGS_PATH}")


# ---------------------------------------------------------------------------
# mcp
# ---------------------------------------------------------------------------


def cmd_mcp(args: argparse.Namespace) -> None:
    """Start the MCP server (stdio transport)."""
    from agentmemory.server import mcp
    mcp.run()


# ---------------------------------------------------------------------------
# uninstall
# ---------------------------------------------------------------------------


def cmd_uninstall(args: argparse.Namespace) -> None:
    """Remove agentmemory commands and config."""
    print("Uninstalling agentmemory...")

    # Remove command .md files
    if _COMMANDS_DIR.is_dir():
        shutil.rmtree(_COMMANDS_DIR)
        print(f"  Removed {_COMMANDS_DIR}")

    # Remove old skills
    old_skills_dir: Path = Path.home() / ".claude" / "skills"
    for prefix in ["mem-correct", "mem-ingest", "mem-locked", "mem-observe",
                    "mem-onboard", "mem-remember", "mem-search", "mem-status"]:
        old_path: Path = old_skills_dir / prefix
        if old_path.is_dir():
            shutil.rmtree(old_path)

    print("  Removed legacy skills")
    print("\nDone. Data is preserved at ~/.agentmemory/. To delete data: rm -rf ~/.agentmemory/")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="agentmemory",
        description="Persistent memory for AI coding agents",
    )
    parser.add_argument(
        "--project", type=str, default=None,
        help="Project directory (default: cwd). Determines which isolated DB to use.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # setup
    p_setup: argparse.ArgumentParser = subparsers.add_parser(
        "setup", help="Install commands and MCP config"
    )
    p_setup.set_defaults(func=cmd_setup)

    # onboard
    p_onboard: argparse.ArgumentParser = subparsers.add_parser(
        "onboard", help="Scan and ingest a project directory"
    )
    p_onboard.add_argument("path", help="Project directory to onboard")
    p_onboard.set_defaults(func=cmd_onboard)

    # stats
    p_stats: argparse.ArgumentParser = subparsers.add_parser(
        "stats", help="Detailed analytics"
    )
    p_stats.set_defaults(func=cmd_stats)

    # health
    p_health: argparse.ArgumentParser = subparsers.add_parser(
        "health", help="Run diagnostics"
    )
    p_health.set_defaults(func=cmd_health)

    # core
    p_core: argparse.ArgumentParser = subparsers.add_parser(
        "core", help="Top N beliefs by confidence"
    )
    p_core.add_argument("--top", type=int, default=10, help="Number of beliefs")
    p_core.set_defaults(func=cmd_core)

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

    # remember (new-belief)
    p_remember: argparse.ArgumentParser = subparsers.add_parser(
        "remember", help="Store a new belief"
    )
    p_remember.add_argument("text", nargs="+", help="Belief text")
    p_remember.set_defaults(func=cmd_remember)

    # lock
    p_lock: argparse.ArgumentParser = subparsers.add_parser(
        "lock", help="Create a locked belief"
    )
    p_lock.add_argument("text", nargs="+", help="Belief text to lock")
    p_lock.set_defaults(func=cmd_lock)

    # wonder
    p_wonder: argparse.ArgumentParser = subparsers.add_parser(
        "wonder", help="Deep research from graph context"
    )
    p_wonder.add_argument("query", nargs="+", help="Research topic or question")
    p_wonder.set_defaults(func=cmd_wonder)

    # reason
    p_reason: argparse.ArgumentParser = subparsers.add_parser(
        "reason", help="Graph-aware reasoning with uncertainty analysis"
    )
    p_reason.add_argument("query", nargs="+", help="Statement or topic to reason about")
    p_reason.add_argument("--depth", type=int, default=None,
                          help="Graph expansion depth 1-3 (default: from config, usually 2)")
    p_reason.add_argument("--budget", type=int, default=4000,
                          help="Token budget for retrieval (default: 4000)")
    p_reason.set_defaults(func=cmd_reason)

    # unlock
    p_unlock: argparse.ArgumentParser = subparsers.add_parser(
        "unlock", help="Unlock least-relevant locked beliefs"
    )
    p_unlock.add_argument("--count", type=int, default=5,
                          help="Number of beliefs to unlock (default: 5)")
    p_unlock.set_defaults(func=cmd_unlock)

    # delete
    p_delete: argparse.ArgumentParser = subparsers.add_parser(
        "delete", help="Soft-delete beliefs by ID"
    )
    p_delete.add_argument("ids", nargs="+", help="One or more belief IDs to delete")
    p_delete.set_defaults(func=cmd_delete)

    # timeline
    p_timeline: argparse.ArgumentParser = subparsers.add_parser(
        "timeline", help="Show beliefs ordered by time"
    )
    p_timeline.add_argument("--topic", default=None, help="FTS5 topic filter")
    p_timeline.add_argument("--since", default=None, help="Start time (ISO 8601 or -7d/-24h)")
    p_timeline.add_argument("--until", default=None, help="End time (ISO 8601 or -7d/-24h)")
    p_timeline.add_argument("--session", default=None, help="Filter by session ID")
    p_timeline.add_argument("--limit", type=int, default=50, help="Max beliefs (default: 50)")
    p_timeline.set_defaults(func=cmd_timeline)

    # evolution
    p_evolution: argparse.ArgumentParser = subparsers.add_parser(
        "evolution", help="Trace belief or topic evolution"
    )
    p_evolution.add_argument("--belief-id", default=None, help="Follow SUPERSEDES chain for this belief")
    p_evolution.add_argument("--topic", default=None, help="Show all beliefs about topic chronologically")
    p_evolution.set_defaults(func=cmd_evolution)

    # diff
    p_diff: argparse.ArgumentParser = subparsers.add_parser(
        "diff", help="Show what changed over a time period"
    )
    p_diff.add_argument("since", help="Start time (ISO 8601 or -7d/-24h)")
    p_diff.add_argument("--until", default=None, help="End time (default: now)")
    p_diff.set_defaults(func=cmd_diff)

    # settings
    p_settings: argparse.ArgumentParser = subparsers.add_parser(
        "settings", help="View or update agentmemory settings"
    )
    p_settings.add_argument("--wonder-max-agents", type=int, default=None,
                            help="Max subagents for /mem:wonder (default: 4)")
    p_settings.add_argument("--core-default-top", type=int, default=None,
                            help="Default N for /mem:core (default: 10)")
    p_settings.add_argument("--locked-max-cap", type=int, default=None,
                            help="Max locked beliefs in retrieve (default: 100)")
    p_settings.add_argument("--locked-warn-at", type=int, default=None,
                            help="Warn when locked beliefs exceed this (default: 80)")
    p_settings.add_argument("--reason-max-agents", type=int, default=None,
                            help="Max subagents for /mem:reason (default: 3)")
    p_settings.add_argument("--reason-depth", type=int, default=None,
                            help="Graph expansion depth for /mem:reason (default: 2)")
    p_settings.set_defaults(func=cmd_settings)

    # commit-check
    p_commit_check: argparse.ArgumentParser = subparsers.add_parser(
        "commit-check", help="Check time/changes since last commit"
    )
    p_commit_check.add_argument(
        "--project-dir", default=".", help="Git repo to check (default: cwd)"
    )
    p_commit_check.add_argument(
        "--nudge-only", action="store_true", default=False,
        help="Only print output when a nudge threshold is exceeded"
    )
    p_commit_check.set_defaults(func=cmd_commit_check)

    # commit-config
    p_commit_config: argparse.ArgumentParser = subparsers.add_parser(
        "commit-config", help="View or update commit tracker settings"
    )
    p_commit_config.add_argument("--enable", action="store_true", help="Enable tracker")
    p_commit_config.add_argument("--disable", action="store_true", help="Disable tracker")
    p_commit_config.add_argument(
        "--max-minutes", type=int, default=None,
        help="Minutes before nudge (default: 15)",
    )
    p_commit_config.add_argument(
        "--max-changes", type=int, default=None,
        help="Uncommitted changes before nudge (default: 10)",
    )
    p_commit_config.set_defaults(func=cmd_commit_config)

    # mcp (start MCP server)
    p_mcp: argparse.ArgumentParser = subparsers.add_parser(
        "mcp", help="Start the MCP server (stdio transport)"
    )
    p_mcp.set_defaults(func=cmd_mcp)

    # uninstall
    p_uninstall: argparse.ArgumentParser = subparsers.add_parser(
        "uninstall", help="Remove agentmemory commands and config"
    )
    p_uninstall.set_defaults(func=cmd_uninstall)

    args: argparse.Namespace = parser.parse_args()

    # Set project isolation before dispatching
    global _active_project
    if args.project is not None:
        _active_project = Path(args.project).resolve()

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
