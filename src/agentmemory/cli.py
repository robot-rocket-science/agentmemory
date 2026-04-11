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
from agentmemory.models import Belief
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.scanner import ScanResult, scan_project
from agentmemory.store import MemoryStore

_DEFAULT_DB_PATH: Path = Path.home() / ".agentmemory" / "memory.db"
_COMMANDS_DIR: Path = Path.home() / ".claude" / "commands" / "mem"
_PACKAGE_ROOT: Path = Path(__file__).parent.parent.parent


def _get_store() -> MemoryStore:
    _DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return MemoryStore(_DEFAULT_DB_PATH)


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

_COMMAND_DEFS: dict[str, dict[str, str]] = {
    "onboard": {
        "description": "Scan a project directory and ingest it into agentmemory.",
        "argument_hint": "Path to project directory (e.g. . or ~/projects/myapp)",
        "tools": "Bash",
        "objective": "Onboard a project into agentmemory by scanning its directory.",
        "process": "Run: `agentmemory onboard $ARGUMENTS`\nDisplay the output. Do not add commentary.",
    },
    "stats": {
        "description": "Show detailed agentmemory analytics: confidence distribution, beliefs by type, age.",
        "argument_hint": "",
        "tools": "Bash",
        "objective": "Show detailed memory system analytics.",
        "process": "Run: `agentmemory stats`\nDisplay the output. Do not add commentary.",
    },
    "health": {
        "description": "Run agentmemory diagnostics.",
        "argument_hint": "",
        "tools": "Bash",
        "objective": "Run memory system diagnostics.",
        "process": "Run: `agentmemory health`\nDisplay the output. Do not add commentary.",
    },
    "core": {
        "description": "Show the top N highest-confidence beliefs.",
        "argument_hint": "Optional: number of beliefs to show (default 10)",
        "tools": "Bash",
        "objective": "Show the most important beliefs the system holds.",
        "process": "Run: `agentmemory core --top ${ARGUMENTS:-10}`\nDisplay the output. Do not add commentary.",
    },
    "search": {
        "description": "Search agentmemory beliefs for a query.",
        "argument_hint": "Search query",
        "tools": "Bash",
        "objective": "Search memory for relevant beliefs.",
        "process": "Run: `agentmemory search $ARGUMENTS`\nDisplay the output. Do not add commentary.",
    },
    "locked": {
        "description": "Show all locked beliefs (non-negotiable constraints).",
        "argument_hint": "",
        "tools": "Bash",
        "objective": "Show all locked beliefs.",
        "process": "Run: `agentmemory locked`\nDisplay the output. Do not add commentary.",
    },
    "new-belief": {
        "description": "Store a new belief in agentmemory.",
        "argument_hint": "The belief text to store",
        "tools": "Bash",
        "objective": "Store a new belief.",
        "process": "Run: `agentmemory remember \"$ARGUMENTS\"`\nDisplay the output. Do not add commentary.",
    },
    "lock": {
        "description": "Create a locked belief (non-negotiable constraint).",
        "argument_hint": "The constraint text to lock",
        "tools": "Bash",
        "objective": "Create a locked belief.",
        "process": "Run: `agentmemory lock \"$ARGUMENTS\"`\nDisplay the output. Do not add commentary.",
    },
    "wonder": {
        "description": "Deep-dive research on a hypothesis, question, or topic using memory graph context.",
        "argument_hint": "A hypothesis, question, or research topic",
        "tools": "Bash, Read, WebSearch",
        "objective": "Gather all beliefs and associations connected to the query, then do deep research and hypothesizing.",
        "process": (
            "Run: `agentmemory wonder \"$ARGUMENTS\"`\n"
            "This will output relevant beliefs and graph context.\n"
            "Then use that context to research the topic deeply: "
            "form hypotheses, identify gaps, suggest experiments, "
            "and synthesize what the memory system knows with what can be found.\n"
            "Present findings as a structured analysis."
        ),
    },
    "settings": {
        "description": "View or update agentmemory settings.",
        "argument_hint": "Optional: --key value pairs to update",
        "tools": "Bash, AskUserQuestion",
        "objective": "View or interactively configure agentmemory settings.",
        "process": (
            "Run: `agentmemory settings`\n"
            "Display the current settings.\n"
            "If the user wants to change something, use AskUserQuestion to present options, "
            "then run `agentmemory settings --<key> <value>` to update."
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

    # Step 2: Ensure agentmemory CLI is accessible
    agentmemory_bin: str | None = shutil.which("agentmemory")
    if agentmemory_bin is None:
        print("  Warning: 'agentmemory' not found on PATH.", file=sys.stderr)
        print("  Commands will try 'uv run agentmemory' as fallback.", file=sys.stderr)

    # Step 3: Write MCP config hint
    mcp_config: dict[str, object] = {
        "mcpServers": {
            "agentmemory": {
                "type": "stdio",
                "command": "agentmemory" if agentmemory_bin else "uv",
                "args": ["mcp"] if agentmemory_bin else [
                    "tool", "run", "agentmemory", "mcp",
                ],
            }
        }
    }
    print(f"\n  MCP server config (add to your project's .mcp.json):")
    print(f"  {json.dumps(mcp_config, indent=2)}")

    # Step 4: Verify DB is accessible
    _DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    store: MemoryStore = _get_store()
    counts: dict[str, int] = store.status()
    store.close()
    print(f"\n  Database: {_DEFAULT_DB_PATH}")
    print(f"  Beliefs: {counts.get('beliefs', 0)}, Locked: {counts.get('locked', 0)}")

    # Step 5: Install commit tracker hook
    _install_commit_hook(agentmemory_bin)

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


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


def cmd_stats(args: argparse.Namespace) -> None:
    """Show detailed analytics."""
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

    print("Memory system stats:")
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
    """Show top N beliefs by confidence."""
    top_n: int = args.top
    store: MemoryStore = _get_store()
    rows: list[sqlite3.Row] = store.query(
        "SELECT * FROM beliefs WHERE valid_to IS NULL "
        "ORDER BY confidence DESC LIMIT ?",
        (top_n,),
    )
    store.close()

    if not rows:
        print("No beliefs found.")
        return

    print(f"Top {top_n} core beliefs:")
    for i, row in enumerate(rows, 1):
        locked_str: str = " [LOCKED]" if row["locked"] else ""
        print(f"  {i}. [{row['confidence']:.0%}]{locked_str} {row['content']}")
        print(f"     type: {row['belief_type']}, source: {row['source_type']}, id: {row['id']}")


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

    print(f"Locked beliefs ({len(beliefs)}):")
    for b in beliefs:
        print(f"  [{b.confidence:.0%}] {b.content} (ID: {b.id})")


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

    if changed:
        cfg_path: Path = save_mem_config(config)
        print(f"Settings updated ({cfg_path}):")
    else:
        print("agentmemory settings:")

    w: dict[str, Any] = cast("dict[str, Any]", config.get("wonder", {}))
    c: dict[str, Any] = cast("dict[str, Any]", config.get("core", {}))
    lk: dict[str, Any] = cast("dict[str, Any]", config.get("locked", {}))

    print(f"  wonder.max_agents:  {w.get('max_agents', 4)}")
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
# main
# ---------------------------------------------------------------------------


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="agentmemory",
        description="Persistent memory for AI coding agents",
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
    p_settings.set_defaults(func=cmd_settings)

    # commit-check
    p_commit_check: argparse.ArgumentParser = subparsers.add_parser(
        "commit-check", help="Check time/changes since last commit"
    )
    p_commit_check.add_argument(
        "--project-dir", default=".", help="Git repo to check (default: cwd)"
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

    # help (just use argparse default)

    args: argparse.Namespace = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
