"""CLI entry point for agentmemory.

Provides direct commands that execute without LLM involvement:
  agentmemory setup              -- install commands, MCP config, commit hook
  agentmemory onboard <path>     -- scan and ingest a project
  agentmemory ingest <jsonl>     -- ingest a JSONL conversation log
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
from agentmemory.ingest import IngestResult, ingest_jsonl, ingest_turn
from agentmemory.models import Belief, Edge, Session
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
    """Create store. Uses VaultStore if obsidian.vault_path is configured."""
    db_path: Path = _resolve_db_path()
    from agentmemory.config import get_str_setting

    vault_str: str = get_str_setting("obsidian", "vault_path")
    if vault_str:
        vault_path: Path = Path(vault_str)
        if vault_path.exists():
            from agentmemory.vault_store import VaultStore

            return VaultStore(vault_path, db_path)  # type: ignore[return-value]
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
        "process": 'Run: `uv run agentmemory remember "$ARGUMENTS"`\nDisplay the output. Do not add commentary.',
    },
    "lock": {
        "description": "Create a locked belief (non-negotiable constraint).",
        "argument_hint": "The constraint text to lock",
        "tools": "Bash",
        "objective": "Create a locked belief.",
        "process": 'Run: `uv run agentmemory lock "$ARGUMENTS"`\nDisplay the output. Do not add commentary.',
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
            '1. Run: `uv run agentmemory wonder "$ARGUMENTS"` to get belief context.\n'
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
        "description": "Consequence-path reasoning about a decision, problem, or hypothesis using branching evidence trees.",
        "argument_hint": "A decision point, problem to debug, or hypothesis to test",
        "tools": "Bash, Read, WebSearch, Agent",
        "objective": "Simulate branching consequence paths from memory to support decision-making, debugging, or planning.",
        "process": (
            '1. Run: `uv run agentmemory reason "$ARGUMENTS"` to get structured consequence-path output.\n'
            "2. Run: `uv run agentmemory settings` to read reason.max_agents and reason.depth.\n"
            "3. Analyze the structured output. It contains:\n"
            "   - VERDICT: SUFFICIENT / INSUFFICIENT / CONTRADICTORY / UNCERTAIN / PARTIAL\n"
            "   - SEED EVIDENCE: FTS5 matches with confidence and uncertainty scores\n"
            "   - CONSEQUENCE PATHS: Branching belief chains with compound confidence decay.\n"
            "     Each path shows: root belief -> edge_type -> next belief -> ...\n"
            "     Compound confidence decays multiplicatively at each hop.\n"
            "     WEAKEST LINK is marked in each path.\n"
            "     CONTRADICTS edges create forks (alternative consequence branches).\n"
            "   - IMPASSES: Reasoning blockers detected in the evidence:\n"
            "     * TIE: Contradicting beliefs with similar confidence (fork needs resolution)\n"
            "     * GAP: Path ends at high-uncertainty belief (evidence insufficient)\n"
            "     * CONSTRAINT_FAILURE: Evidence conflicts with a LOCKED belief (path BLOCKED)\n"
            "     * NO_CHANGE: All evidence is low-confidence (nothing actionable)\n"
            "4. Use the VERDICT to decide next steps:\n"
            "   - SUFFICIENT: Present the answer based on the strongest consequence path.\n"
            "   - INSUFFICIENT: Spawn subagents to fill gaps (see step 5).\n"
            "   - CONTRADICTORY: A LOCKED constraint blocks a path. DO NOT take the blocked path.\n"
            "     Present the unblocked path(s) instead. If ALL paths are blocked, escalate to user.\n"
            "   - UNCERTAIN: Present the fork to the user for resolution.\n"
            "   - PARTIAL: Present what is known, flag gaps explicitly.\n"
            "5. If the VERDICT is INSUFFICIENT or UNCERTAIN, spawn up to "
            "max_agents subagents using the Agent tool. Each subagent gets:\n"
            "   - The original reason query\n"
            "   - ONE specific impasse to resolve (from the IMPASSES section)\n"
            "   - Assign roles: Verifier (check uncertain leaf), "
            "Gap-filler (research missing evidence), Fork-resolver (which branch is correct?)\n"
            "   If VERDICT is SUFFICIENT, skip subagent dispatch entirely.\n"
            "6. Collect subagent results (if any).\n"
            "7. Present the reasoned analysis:\n"
            "   - ANSWER: Direct response with consequence path supporting it\n"
            "   - BLOCKED PATHS: Any paths forbidden by locked constraints\n"
            "   - WEAKEST LINKS: Beliefs where confidence is lowest in the chain\n"
            "   - OPEN QUESTIONS: Impasses that could not be resolved\n"
            "   - SUGGESTED UPDATES: Beliefs whose confidence should change based on findings\n"
            "     (call mcp__agentmemory__feedback for beliefs that were used/rejected)\n"
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
    "enable-telemetry": {
        "description": "Enable anonymous telemetry logging.",
        "argument_hint": "",
        "tools": "Bash",
        "objective": "Enable anonymous telemetry and confirm to the user.",
        "process": (
            "1. Run: `uv run agentmemory enable-telemetry`\n"
            "2. Display the output to the user.\n"
            "3. Confirm that only content-free metrics are collected (token spend,\n"
            "   correction rates, feedback health) and data stays local at\n"
            "   ~/.agentmemory/telemetry.jsonl.\n"
        ),
    },
    "disable-telemetry": {
        "description": "Disable anonymous telemetry logging.",
        "argument_hint": "",
        "tools": "Bash",
        "objective": "Disable anonymous telemetry and confirm to the user.",
        "process": (
            "1. Run: `uv run agentmemory disable-telemetry`\n"
            "2. Display the output to the user.\n"
            "3. Confirm telemetry is now disabled. No further data will be written\n"
            "   to ~/.agentmemory/telemetry.jsonl until re-enabled.\n"
        ),
    },
    "send-telemetry": {
        "description": "Send unsent telemetry snapshots to help improve agentmemory.",
        "argument_hint": "",
        "tools": "Bash",
        "objective": "Show the user their unsent telemetry data and send it with explicit confirmation.",
        "process": (
            "1. Run: `uv run agentmemory send-telemetry`\n"
            "2. The command will show a preview of what will be sent and ask for confirmation.\n"
            "3. Display the result to the user.\n"
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
            "  /mem:enable-telemetry   Enable anonymous performance logging\n"
            "  /mem:disable-telemetry  Disable anonymous performance logging\n"
            "  /mem:send-telemetry     Send unsent snapshots (shows data, asks first)\n"
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
    lines.append("<objective>")
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
        "mem-correct",
        "mem-ingest",
        "mem-locked",
        "mem-observe",
        "mem-onboard",
        "mem-remember",
        "mem-search",
        "mem-status",
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

    # Step 2b: Create .mcp.json if missing
    mcp_json_path: Path = Path.cwd() / ".mcp.json"
    if not mcp_json_path.exists():
        import json as _json

        mcp_config: dict[str, object] = {
            "mcpServers": {
                "agentmemory": {
                    "type": "stdio",
                    "command": "uv",
                    "args": [
                        "run",
                        "--project",
                        ".",
                        "python",
                        "-m",
                        "agentmemory.server",
                    ],
                    "env": {},
                }
            }
        }
        mcp_json_path.write_text(_json.dumps(mcp_config, indent=2) + "\n")
        print(f"  Created {mcp_json_path}")
    else:
        print(f"  .mcp.json already exists at {mcp_json_path}")

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

    # Step 5b: Install directive gate hook
    _install_directive_gate()

    # Step 6: Smoke test
    print("\n  Smoke test...")
    import subprocess

    smoke: subprocess.CompletedProcess[str] = subprocess.run(
        ["uv", "run", "agentmemory", "stats"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if smoke.returncode == 0:
        print("  OK: CLI works")
    else:
        print(
            f"  FAIL: agentmemory stats returned exit code {smoke.returncode}",
            file=sys.stderr,
        )
        if smoke.stderr:
            print(f"  {smoke.stderr[:200]}", file=sys.stderr)

    # Step 7: Obsidian vault setup
    _setup_obsidian_vault()

    # Step 8: Telemetry opt-in
    _setup_telemetry()

    print("\nDone. Restart Claude Code, then run /mem:onboard . on your project.")


def _setup_obsidian_vault() -> None:
    """Detect or configure Obsidian vault integration."""
    from agentmemory.config import get_str_setting, load_config, save_config

    print("\n  Obsidian vault integration...")

    # Check if already configured
    existing: str = get_str_setting("obsidian", "vault_path")
    if existing and Path(existing).exists():
        print(f"  Vault already configured: {existing}")
        return

    # Auto-detect: look for .obsidian/ in cwd or parent dirs
    vault_path: Path | None = None
    check: Path = Path.cwd()
    for _ in range(5):  # up to 5 levels
        if (check / ".obsidian").is_dir():
            vault_path = check
            break
        parent: Path = check.parent
        if parent == check:
            break
        check = parent

    if vault_path is None:
        # Create vault in project root
        vault_path = Path.cwd()
        obsidian_dir: Path = vault_path / ".obsidian"
        obsidian_dir.mkdir(exist_ok=True)
        # Write minimal config
        (obsidian_dir / "core-plugins.json").write_text(
            '{\n  "file-explorer": true,\n  "global-search": true,\n'
            '  "graph": true,\n  "backlink": true,\n  "outgoing-link": true,\n'
            '  "tag-pane": true,\n  "properties": true,\n  "daily-notes": true\n}\n',
            encoding="utf-8",
        )
        print(f"  Created Obsidian vault config at {obsidian_dir}")

    # Save vault_path to config
    config: dict[str, object] = load_config()
    obs_config: dict[str, object] = {
        "vault_path": str(vault_path),
        "beliefs_subfolder": "beliefs",
        "auto_sync": False,
    }
    config["obsidian"] = obs_config
    save_config(config)  # type: ignore[arg-type]
    print(f"  Vault path saved: {vault_path}")

    # Create vault directories
    for subdir in ("beliefs", "_index", "_dashboards", "_docs", "_canvas"):
        (vault_path / subdir).mkdir(exist_ok=True)
    print("  Created vault directories (beliefs, _index, _dashboards, _docs, _canvas)")

    # Add to .gitignore if not already present
    gitignore: Path = vault_path / ".gitignore"
    entries: list[str] = [
        "beliefs/",
        "_index/",
        "_dashboards/",
        "_docs/",
        "_canvas/",
        ".agentmemory_sync.json",
    ]
    if gitignore.exists():
        existing_text: str = gitignore.read_text(encoding="utf-8")
        missing: list[str] = [e for e in entries if e not in existing_text]
        if missing:
            with open(gitignore, "a", encoding="utf-8") as f:
                f.write("\n# Obsidian vault export (generated, not source)\n")
                for entry in missing:
                    f.write(entry + "\n")
            print(f"  Added {len(missing)} entries to .gitignore")

    # Check if Obsidian app is installed
    obsidian_app: Path = Path("/Applications/Obsidian.app")
    if not obsidian_app.exists():
        print("  Note: Obsidian app not found at /Applications/Obsidian.app")
        print("  Install from https://obsidian.md to use graph view and dashboards")


def _setup_telemetry() -> None:
    """Prompt user to opt in to anonymous telemetry during setup."""
    from agentmemory.config import get_bool_setting, load_config, save_config

    telem_path: str = str(Path.home() / ".agentmemory" / "telemetry.jsonl")

    print("\n  Anonymous telemetry...")
    print("  agentmemory can collect anonymous performance metrics to help")
    print("  improve the system. Here is exactly what we collect:\n")
    print("    Per session:")
    print("      - token counts (retrieval, classification)")
    print("      - beliefs created, corrections detected")
    print("      - searches performed, feedback given")
    print("      - session duration, velocity tier")
    print("    Aggregate:")
    print("      - belief counts by type/source/confidence bucket")
    print("      - active/superseded/locked totals, churn rate, orphan count")
    print("      - graph edge counts by type, avg edges per belief")
    print("      - feedback outcome distribution, feedback rate")
    print("      - rolling 7-session and 30-session averages\n")
    print("    NOT collected (ever):")
    print("      - belief content, project paths, file paths")
    print("      - session IDs, user names, identifying information\n")
    print(f"  Data file: {telem_path}")
    print("  Inspect it anytime. It is plain JSONL, one snapshot per line.")
    print("  Nothing is sent without your explicit permission (send-telemetry).")
    print("  Disable collection anytime with /mem:disable-telemetry\n")

    current: bool = get_bool_setting("telemetry", "enabled")
    if current:
        print("  Telemetry is currently: ENABLED")
    else:
        print("  Telemetry is currently: DISABLED")

    answer: str = input("  Enable anonymous telemetry? [y/N]: ").strip().lower()
    enabled: bool = answer in ("y", "yes")

    config: dict[str, object] = load_config()
    telem_config: dict[str, object] = {"enabled": enabled}
    config["telemetry"] = telem_config
    save_config(config)  # type: ignore[arg-type]

    status: str = "ENABLED" if enabled else "DISABLED"
    print(
        f"  Telemetry {status}. Change anytime with /mem:enable-telemetry or /mem:disable-telemetry"
    )


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------


def cmd_metrics(args: argparse.Namespace) -> None:
    """Analyze session data from conversation logs.

    Parses conversation logs to compute correction rates, search usage,
    memory utility, and session quality metrics. Compares memory-on vs
    memory-off sessions when sufficient data exists.

    This is the primary tool for validating agentmemory's real-world
    impact beyond benchmark scores.
    """
    import re as _re
    from collections import defaultdict

    log_dir: Path = Path.home() / ".claude" / "conversation-logs"
    if not log_dir.exists():
        print("No conversation logs found at ~/.claude/conversation-logs/")
        return

    # Load all turns
    all_turns: list[dict[str, str]] = []
    for jsonl_file in sorted(log_dir.glob("**/*.jsonl")):
        with jsonl_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    all_turns.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    all_turns.sort(key=lambda t: t.get("timestamp", ""))

    if not all_turns:
        print("No conversation turns found.")
        return

    # Group by session
    by_session: dict[str, list[dict[str, str]]] = defaultdict(list)
    for turn in all_turns:
        sid: str = turn.get("session_id", "")
        if sid:
            by_session[sid].append(turn)

    # Date range
    timestamps: list[str] = [
        t.get("timestamp", "") for t in all_turns if t.get("timestamp")
    ]
    timestamps.sort()

    print("=" * 60)
    print("agentmemory Session Metrics Report")
    print("=" * 60)
    print(f"  Date range:     {timestamps[0][:10]} to {timestamps[-1][:10]}")
    print(f"  Total turns:    {len(all_turns)}")
    print(f"  Total sessions: {len(by_session)}")
    print()

    # Correction patterns
    correction_pats: list[_re.Pattern[str]] = [
        _re.compile(r"\bno[,.]?\s+(that'?s|it'?s)\s+(wrong|not|incorrect)", _re.I),
        _re.compile(r"\bactually[,.]?\s+(it'?s|we|I|the)", _re.I),
        _re.compile(r"\bthat'?s\s+not\s+(right|correct|what)", _re.I),
        _re.compile(r"\bI\s+said\s+.+\s+not\s+", _re.I),
        _re.compile(r"\bstop\s+(doing|adding|using|saying)", _re.I),
        _re.compile(r"\bdon'?t\s+(do|add|use|say|mock|skip|commit)", _re.I),
        _re.compile(r"\bnot\s+what\s+I\s+(asked|meant|said|wanted)", _re.I),
    ]

    # Per-session analysis
    total_user: int = 0
    total_corrections: int = 0
    memory_on_sessions: list[dict[str, object]] = []
    memory_off_sessions: list[dict[str, object]] = []

    for sid, turns in by_session.items():
        user_turns: list[dict[str, str]] = [
            t for t in turns if t.get("event") == "user"
        ]
        assistant_turns: list[dict[str, str]] = [
            t for t in turns if t.get("event") == "assistant"
        ]

        if len(user_turns) < 2:
            continue  # skip trivial sessions

        # Count corrections
        corrections: int = 0
        for t in user_turns:
            text: str = t.get("text", "")
            for pat in correction_pats:
                if pat.search(text):
                    corrections += 1
                    break

        # Check for agentmemory usage
        has_memory: bool = any(
            "mcp__agentmemory" in t.get("text", "") for t in assistant_turns
        )

        total_user += len(user_turns)
        total_corrections += corrections

        session_data: dict[str, object] = {
            "user_turns": len(user_turns),
            "corrections": corrections,
            "correction_rate": round(corrections / len(user_turns), 4)
            if user_turns
            else 0.0,
            "has_memory": has_memory,
        }

        if has_memory:
            memory_on_sessions.append(session_data)
        elif len(user_turns) >= 3:
            memory_off_sessions.append(session_data)

    # Overall stats
    overall_rate: float = total_corrections / total_user if total_user > 0 else 0.0
    print("## Correction Analysis")
    print(f"  User turns analyzed: {total_user}")
    print(f"  Corrections found:  {total_corrections}")
    print(f"  Overall rate:       {overall_rate:.2%}")
    print()

    # Memory comparison
    on_rate: float = 0.0
    off_rate: float = 0.0
    if memory_on_sessions and memory_off_sessions:
        on_rate = sum(
            float(s.get("correction_rate", 0))  # type: ignore[arg-type]
            for s in memory_on_sessions
        ) / len(memory_on_sessions)
        off_rate = sum(
            float(s.get("correction_rate", 0))  # type: ignore[arg-type]
            for s in memory_off_sessions
        ) / len(memory_off_sessions)

        print("## Memory Impact")
        print(f"  Memory-ON sessions:  {len(memory_on_sessions)}")
        print(f"    Correction rate:   {on_rate:.2%}")
        print(f"  Memory-OFF sessions: {len(memory_off_sessions)}")
        print(f"    Correction rate:   {off_rate:.2%}")
        if off_rate > 0:
            delta: float = (off_rate - on_rate) / off_rate
            direction: str = "reduction" if delta > 0 else "increase"
            print(f"  Correction {direction}: {abs(delta):.1%}")
        print()
        print("  CAVEAT: Memory-ON sessions may differ in complexity")
        print("  from Memory-OFF sessions. This is observational, not")
        print("  a controlled experiment.")
    else:
        print("## Memory Impact")
        print(f"  Memory-ON sessions:  {len(memory_on_sessions)}")
        print(f"  Memory-OFF sessions: {len(memory_off_sessions)}")
        print("  Insufficient data for comparison (need both)")
    print()

    # Agentmemory DB stats
    store: MemoryStore = _get_store()
    sessions_in_db: list[Session] = store.find_incomplete_sessions()
    all_db_sessions: list[sqlite3.Row] = store.query(
        "SELECT COUNT(*) as c, "
        "SUM(CASE WHEN feedback_given > 0 THEN 1 ELSE 0 END) as with_fb, "
        "SUM(beliefs_created) as beliefs, "
        "SUM(corrections_detected) as corrections, "
        "SUM(searches_performed) as searches, "
        "AVG(quality_score) as avg_quality "
        "FROM sessions"
    )
    if all_db_sessions:
        row = all_db_sessions[0]
        print("## agentmemory DB Stats")
        print(f"  Sessions:         {row['c']}")
        print(f"  With feedback:    {row['with_fb']}")
        print(f"  Beliefs created:  {row['beliefs']}")
        print(f"  Corrections:      {row['corrections']}")
        print(f"  Searches:         {row['searches']}")
        quality: object = row["avg_quality"]
        if quality is not None:
            print(f"  Avg quality:      {float(quality):.3f}")  # type: ignore[arg-type]
        else:
            print("  Avg quality:      N/A (never computed)")
        print(f"  Incomplete:       {len(sessions_in_db)}")
    print()

    # Output JSON if requested
    if args.output:
        report: dict[str, object] = {
            "date_range": f"{timestamps[0]} to {timestamps[-1]}",
            "total_turns": len(all_turns),
            "total_sessions": len(by_session),
            "total_user_turns": total_user,
            "total_corrections": total_corrections,
            "overall_correction_rate": round(overall_rate, 4),
            "memory_on_sessions": len(memory_on_sessions),
            "memory_off_sessions": len(memory_off_sessions),
        }
        if memory_on_sessions and memory_off_sessions:
            report["memory_on_correction_rate"] = round(on_rate, 4)
            report["memory_off_correction_rate"] = round(off_rate, 4)
        out_path: Path = Path(args.output)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Report written to {args.output}")

    print("=" * 60)


# ---------------------------------------------------------------------------
# session-complete
# ---------------------------------------------------------------------------


def cmd_session_complete(args: argparse.Namespace) -> None:
    """Complete the active session, compute velocity and quality score.

    Intended for use by session-end hooks. Finds the most recent
    incomplete session, optionally ingests conversation turns from
    the log file, computes velocity and quality score, and marks
    the session as complete.

    Exit code is always 0 so hooks never block.
    """
    store: MemoryStore = _get_store()

    # Find incomplete session
    incomplete: list[Session] = store.find_incomplete_sessions()
    if not incomplete:
        return

    session: Session = incomplete[0]
    session_id: str = session.id

    # Optionally ingest conversation turns
    log_path: Path = (
        Path(args.log)
        if args.log
        else (Path.home() / ".claude" / "conversation-logs" / "turns.jsonl")
    )
    ingested: int = 0
    if log_path.exists() and not args.skip_ingest:
        try:
            with log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry: dict[str, str] = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    entry_session: str = entry.get("session_id", "")
                    if entry_session and entry_session != session_id:
                        continue

                    event_type: str = entry.get("event", "")
                    text: str = entry.get("text", "")
                    if not text or len(text.strip()) < 10:
                        continue
                    if event_type not in ("user", "assistant"):
                        continue

                    ts: str = entry.get("timestamp", "")
                    if ts and session.started_at and ts < session.started_at:
                        continue

                    source: str = "user" if event_type == "user" else "assistant"
                    try:
                        ingest_turn(store, text, source, session_id=session_id)
                        ingested += 1
                    except Exception:
                        pass
        except Exception:
            pass

    # Complete session (computes velocity)
    store.complete_session(session_id)

    # Auto-compute quality score
    try:
        rows: list[sqlite3.Row] = store.query(
            "SELECT searches_performed, feedback_given, corrections_detected, "
            "beliefs_created FROM sessions WHERE id = ?",
            (session_id,),
        )

        if rows:
            row = rows[0]
            searches: int = int(row[0] or 0)
            feedback: int = int(row[1] or 0)
            corrections: int = int(row[2] or 0)
            beliefs: int = int(row[3] or 0)

            quality: float = 0.0
            if searches > 0:
                feedback_rate: float = min(feedback / searches, 1.0)
                quality += feedback_rate * 0.5
            if beliefs > 0:
                correction_density: float = corrections / beliefs
                quality -= min(correction_density, 1.0) * 0.3
                quality += 0.2
            quality = max(-1.0, min(1.0, quality))

            store.query(
                "UPDATE sessions SET quality_score = ? WHERE id = ?",
                (round(quality, 4), session_id),
            )
    except Exception:
        pass

    if not args.quiet:
        print(f"Session {session_id[:12]} completed: {ingested} turns ingested")


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------


def cmd_ingest(args: argparse.Namespace) -> None:
    """Ingest a JSONL conversation log into agentmemory."""
    jsonl_path: Path = Path(args.path).expanduser().resolve()
    if not jsonl_path.is_file():
        print(f"File not found: {jsonl_path}", file=sys.stderr)
        sys.exit(1)

    store: MemoryStore = _get_store()
    print(f"Ingesting {jsonl_path.name} ...")
    result: IngestResult = ingest_jsonl(store, jsonl_path)
    print(
        f"Done: {result.observations_created} observations, "
        f"{result.beliefs_created} beliefs, "
        f"{result.corrections_detected} corrections"
    )


# ---------------------------------------------------------------------------
# onboard
# ---------------------------------------------------------------------------


def cmd_onboard(args: argparse.Namespace) -> None:
    """Scan a project directory and ingest into memory."""
    import time as _time

    project_path: Path = Path(args.path).expanduser().resolve()
    if not project_path.is_dir():
        print(f"Error: not a directory: {project_path}", file=sys.stderr)
        sys.exit(1)

    t_start: float = _time.perf_counter()
    print(f"Scanning {project_path.name}...")
    scan: ScanResult = scan_project(project_path)
    t_scan: float = _time.perf_counter()

    print(
        f"  Signals: git={scan.manifest.has_git}, "
        f"docs={scan.manifest.doc_count}, "
        f"languages={scan.manifest.languages}"
    )

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
    with store.transaction():
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
                bulk=True,
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

    t_ingest: float = _time.perf_counter()
    print(f"  Mapped {len(node_to_belief)} scanner nodes to belief IDs")

    # Store structural edges, translating scanner IDs to belief IDs where possible
    edge_batch: list[tuple[str, str, str, float, str]] = []
    for edge in scan.edges:
        src: str = node_to_belief.get(edge.src, edge.src)
        tgt: str = node_to_belief.get(edge.tgt, edge.tgt)
        edge_batch.append((src, tgt, edge.edge_type, edge.weight, "scanner"))
    edge_count: int = store.batch_insert_graph_edges(edge_batch)
    t_edges: float = _time.perf_counter()
    if edge_count > 0:
        print(f"  Stored {edge_count} structural edges")

    # --- Semantic linking pass (Haiku LLM) ---
    # Batch active beliefs and ask Haiku to identify same-concept pairs.
    # Creates RELATES_TO edges that HRR can traverse without manual citations.
    # Only runs with --link flag (costs ~$0.01-0.05 per onboard).
    link_edges: int = 0
    if getattr(args, "link", False):
        from agentmemory.semantic_linker import (
            LINK_BATCH_SIZE,
            apply_links,
            build_link_prompt,
            parse_link_response,
        )

        print("\nSemantic linking (Haiku)...")
        active_rows: list[sqlite3.Row] = store.query(
            "SELECT id, content FROM beliefs "
            "WHERE valid_to IS NULL AND superseded_by IS NULL "
            "ORDER BY created_at DESC LIMIT 500"
        )
        belief_pairs: list[tuple[str, str]] = [
            (r["id"], r["content"]) for r in active_rows
        ]

        for batch_start in range(0, len(belief_pairs), LINK_BATCH_SIZE):
            batch: list[tuple[str, str]] = belief_pairs[
                batch_start : batch_start + LINK_BATCH_SIZE
            ]
            prompt: str = build_link_prompt(batch)

            try:
                import anthropic

                client: anthropic.Anthropic = anthropic.Anthropic()
                response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=2048,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw_text: str = str(
                    getattr(response.content[0], "text", response.content[0])
                )
                links: list[tuple[str, str, str]] = parse_link_response(raw_text)
                created: int = apply_links(store, links)
                link_edges += created
                batch_num: int = batch_start // LINK_BATCH_SIZE + 1
                total_batches: int = (
                    len(belief_pairs) + LINK_BATCH_SIZE - 1
                ) // LINK_BATCH_SIZE
                print(
                    f"  Batch {batch_num}/{total_batches}: "
                    f"{len(links)} links found, {created} edges created"
                )
            except ImportError:
                print(
                    "  Warning: anthropic SDK not installed. "
                    "Install with: uv pip install anthropic"
                )
                break
            except Exception as e:
                print(f"  Error in batch: {e}")
                continue

        if link_edges > 0:
            print(f"  Total semantic edges: {link_edges}")

    # --- Obsidian vault sync ---
    # If vault is configured, sync beliefs + link documents
    from agentmemory.config import get_str_setting

    vault_str: str = get_str_setting("obsidian", "vault_path")
    vault_sync_count: int = 0
    doc_link_count: int = 0
    if vault_str and Path(vault_str).exists():
        print("\nSyncing to Obsidian vault...")
        from agentmemory.obsidian import ObsidianConfig, SyncResult, sync_vault

        obs_config: ObsidianConfig = ObsidianConfig(vault_path=Path(vault_str))
        sync_result: SyncResult = sync_vault(store, obs_config, full=True)
        vault_sync_count = sync_result.beliefs_written
        print(f"  Beliefs synced: {sync_result.beliefs_written}")
        print(f"  Index notes: {sync_result.index_notes_written}")

        print("Linking project documents...")
        from agentmemory.doc_linker import LinkResult, link_documents

        link_result: LinkResult = link_documents(store, project_path, Path(vault_str))
        doc_link_count = link_result.docs_exported
        print(f"  Documents: {link_result.docs_exported}")
        print(f"  Cross-references: {link_result.refs_linked}")
        print(f"  Belief links: {link_result.belief_refs_added}")

    store.close()
    t_end: float = _time.perf_counter()

    scan_parts: list[str] = [f"{k}={v:.2f}s" for k, v in scan.timings.items()]
    phase_parts: list[str] = [
        f"scan={t_scan - t_start:.2f}s",
        f"ingest={t_ingest - t_scan:.2f}s",
        f"edges={t_edges - t_ingest:.2f}s",
    ]
    if vault_sync_count > 0:
        phase_parts.append(f"vault={t_end - t_edges:.2f}s")
    phase_parts.append(f"total={t_end - t_start:.2f}s")

    print("\nDone.")
    print(f"  Observations: {aggregate.observations_created}")
    print(f"  Beliefs: {aggregate.beliefs_created}")
    print(f"  Corrections: {aggregate.corrections_detected}")
    print(f"  Edges: {edge_count} structural + {link_edges} semantic")
    if vault_sync_count > 0:
        print(f"  Vault: {vault_sync_count} beliefs + {doc_link_count} docs")
    print(f"  Timing (scan): {', '.join(scan_parts)}")
    print(f"  Timing (pipeline): {', '.join(phase_parts)}")


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

    store = _get_store()
    metrics: dict[str, object] = store.get_health_metrics()
    edge_health: dict[str, object] = store.get_edge_health()
    store.close()

    active: int = int(str(metrics["active_beliefs"]))

    print("\n  Belief diagnostics:")
    print(
        f"    Credal gap: {metrics['credal_gap_count']} / {active}"
        f" ({metrics['credal_gap_pct']}%) beliefs at type prior (untested)"
    )
    print(
        f"    Orphans: {metrics['orphan_count']}"
        f" ({metrics['orphan_pct']}%) beliefs with no edges"
    )
    print(
        f"    Edges: {metrics['contradicts_edges']} CONTRADICTS,"
        f" {metrics['supports_edges']} SUPPORTS,"
        f" {metrics['supersedes_edges']} SUPERSEDES"
    )
    print(
        f"    Feedback coverage: {metrics['feedback_coverage_count']}"
        f" ({metrics['feedback_coverage_pct']}%) beliefs with test results"
    )
    print(f"    Avg confidence: {metrics['avg_confidence']}")
    print(f"    Stale sessions: {metrics['stale_sessions']} incomplete")

    print("\n  Edge diagnostics:")
    print(
        f"    Active: {edge_health['active_edges']}"
        f" (pruned: {edge_health['pruned_edges']})"
    )
    print(
        f"    Traversed: {edge_health['traversed_edges']}"
        f" (never: {edge_health['never_traversed_edges']})"
    )
    print(f"    Avg edge confidence: {edge_health['avg_edge_confidence']}")
    print(f"    Avg traversal count: {edge_health['avg_traversal_count']}")
    print(
        f"    Edge credal gap: {edge_health['edge_credal_gap']}"
        f" ({edge_health['edge_credal_gap_pct']}%) at default prior"
    )


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

    # Fetch all active, non-superseded beliefs and score them
    rows: list[sqlite3.Row] = store.query(
        "SELECT * FROM beliefs WHERE valid_to IS NULL AND superseded_by IS NULL"
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
        # Show belief age
        age_str: str = ""
        try:
            created: dt = dt.fromisoformat(b.created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=tz.utc)
            age_days: float = (dt.now(tz.utc) - created).total_seconds() / 86400.0
            if age_days < 1:
                age_str = " <1d"
            elif age_days < 7:
                age_str = f" {age_days:.0f}d"
            elif age_days < 30:
                age_str = f" {age_days / 7:.0f}w"
            else:
                age_str = f" {age_days / 30:.0f}mo"
        except Exception:
            pass
        print(f"  {i}. [score {s:.2f}{age_str}]{locked_str} {b.content}")
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

    print(
        f"Found {len(result.beliefs)} belief(s) "
        f"({result.total_tokens} tokens, {result.budget_remaining} remaining):"
    )
    from datetime import datetime as dt
    from datetime import timezone as tz

    for belief in result.beliefs:
        score: float | None = result.scores.get(belief.id)
        score_str: str = f", score: {score:.3f}" if score is not None else ""
        locked_str: str = " [LOCKED]" if belief.locked else ""
        age_str: str = ""
        try:
            created: dt = dt.fromisoformat(belief.created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=tz.utc)
            age_days: float = (dt.now(tz.utc) - created).total_seconds() / 86400.0
            if age_days < 1:
                age_str = " <1d"
            elif age_days < 7:
                age_str = f" {age_days:.0f}d"
            elif age_days < 30:
                age_str = f" {age_days / 7:.0f}w"
            else:
                age_str = f" {age_days / 30:.0f}mo"
        except Exception:
            pass
        print(
            f"  [{belief.confidence:.0%}{age_str}]{locked_str} {belief.content} "
            f"(ID: {belief.id}, type: {belief.belief_type}{score_str})"
        )


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
        print(
            f"\n  WARNING: {len(beliefs)} locked beliefs (warn threshold: {warn_at}, cap: {max_cap})"
        )
        print("  Consider unlocking least-relevant locked beliefs.")
        print("  Run: agentmemory unlock [--count N] to unlock the N least-relevant.")


# ---------------------------------------------------------------------------
# stale
# ---------------------------------------------------------------------------


def cmd_stale(args: argparse.Namespace) -> None:
    """Show beliefs not retrieved recently (stale)."""
    store: MemoryStore = _get_store()
    beliefs: list[Belief] = store.get_stale_beliefs(
        days_threshold=args.days,
        limit=args.limit,
    )
    store.close()

    if not beliefs:
        print(f"No stale beliefs (threshold: {args.days} days).")
        return

    print(f"Stale beliefs ({len(beliefs)}, threshold: {args.days} days):")
    for b in beliefs:
        last: str = b.last_retrieved_at if b.last_retrieved_at else "never"
        print(f"  [{b.confidence:.0%}] ({b.belief_type}) last retrieved: {last}")
        print(f"    {b.content}")
        print(f"    ID: {b.id}")


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
# wonder
# ---------------------------------------------------------------------------


def cmd_wonder(args: argparse.Namespace) -> None:
    """Deep research context gathering with graph expansion.

    Retrieves beliefs via FTS5, expands along graph edges (BFS),
    computes uncertainty scores, detects contradictions, and outputs
    structured context formatted for LLM consumption.
    """
    query: str = " ".join(args.query)
    if not query.strip():
        print("Error: empty query", file=sys.stderr)
        sys.exit(1)

    depth: int = (
        args.depth
        if args.depth is not None
        else int(get_setting("wonder", "depth") or 2)
    )
    budget: int = args.budget

    store: MemoryStore = _get_store()

    # Step 1: FTS5 retrieval
    result: RetrievalResult = retrieve(store, query, budget=budget)

    if not result.beliefs:
        print(f"No beliefs found for: {query}")
        print("The memory system has no context on this topic yet.")
        store.close()
        return

    # Step 2: Graph expansion from top 10 seeds
    seed_ids: list[str] = [b.id for b in result.beliefs[:10]]
    expanded: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph(
        seed_ids,
        depth=depth,
    )

    # Step 3: Merge and deduplicate
    all_beliefs: dict[str, Belief] = {}
    belief_hops: dict[str, int] = {}
    belief_edges: dict[str, str] = {}

    for b in result.beliefs:
        all_beliefs[b.id] = b
        belief_hops[b.id] = 0

    for _bid, exp_neighbors in expanded.items():
        for neighbor_belief, edge_type, hop in exp_neighbors:
            if neighbor_belief.id not in all_beliefs:
                all_beliefs[neighbor_belief.id] = neighbor_belief
            if (
                neighbor_belief.id not in belief_hops
                or hop < belief_hops[neighbor_belief.id]
            ):
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
            bid,
            edge_types=["CONTRADICTS"],
            direction="both",
        )
        for neighbor_belief, _edge in neighbors:
            if neighbor_belief.id in result_ids and neighbor_belief.id > bid:
                contradictions.append((all_beliefs[bid], neighbor_belief))

    store.close()

    # Step 6: Categorize
    direct: list[Belief] = [b for b in result.beliefs if belief_hops.get(b.id, 0) == 0]
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

    # Step 7: Output as structured context block (for LLM consumption)
    print(f"WONDER: {query}")
    print(
        f"depth={depth}, direct={len(direct)}, "
        f"graph={len(connected)}, uncertain={len(high_uncertainty)}, "
        f"contradictions={len(contradictions)}"
    )

    print("\n## Known Facts")
    for b in direct:
        locked_tag: str = " [LOCKED]" if b.locked else ""
        unc: float = belief_uncertainty.get(b.id, 0.0)
        unc_tag: str = f" [uncertain:{unc:.2f}]" if unc > 0.5 else ""
        print(f"- [{b.confidence:.0%}]{locked_tag}{unc_tag} {b.content}")

    if connected:
        print("\n## Connected Evidence")
        for b, etype, hop in connected:
            locked_tag = " [LOCKED]" if b.locked else ""
            print(f"- [hop {hop}, via {etype}]{locked_tag} {b.content}")

    if high_uncertainty:
        print("\n## Open Questions (high-uncertainty beliefs)")
        for b, unc in high_uncertainty:
            print(f"- [uncertainty:{unc:.2f}, conf:{b.confidence:.0%}] {b.content}")

    if contradictions:
        print("\n## Contradictions")
        for a, b in contradictions:
            print(f'- "{a.content[:100]}"')
            print(f'  CONTRADICTS "{b.content[:100]}"')

    if not connected and not high_uncertainty and not contradictions:
        print("\n(No graph connections, uncertainty flags, or contradictions found.)")

    # Step 8: Create speculative belief nodes
    # Sources: high-uncertainty beliefs, contradictions, and the query itself
    store = _get_store()
    from agentmemory.uncertainty import UncertaintyVector

    speculative_created: int = 0
    spec_ids: list[str] = []

    # Source belief: use the highest-confidence direct result as the anchor
    anchor_id: str | None = direct[0].id if direct else None

    # 8a: From high-uncertainty beliefs (if any)
    for b, unc in high_uncertainty[:3]:
        uv: UncertaintyVector = UncertaintyVector()
        spec: Belief = store.insert_speculative_belief(
            content=f"[hypothesis] {b.content}",
            uncertainty_vector_json=uv.to_json(),
            source_belief_id=anchor_id,
            session_id=None,
        )
        spec_ids.append(spec.id)
        speculative_created += 1

    # 8b: From contradictions (each contradiction is a fork point)
    for a, b in contradictions[:2]:
        uv = UncertaintyVector()
        spec = store.insert_speculative_belief(
            content=f'[fork] resolve: "{a.content[:80]}" vs "{b.content[:80]}"',
            uncertainty_vector_json=uv.to_json(),
            source_belief_id=a.id,
            session_id=None,
        )
        spec_ids.append(spec.id)
        speculative_created += 1

    # 8c: From the query itself (always create at least one speculative node
    # representing the open question, so there's something to reason about)
    if speculative_created == 0 and direct:
        uv = UncertaintyVector()
        spec = store.insert_speculative_belief(
            content=f"[open question] {query}",
            uncertainty_vector_json=uv.to_json(),
            source_belief_id=anchor_id,
            session_id=None,
        )
        spec_ids.append(spec.id)
        speculative_created += 1

    if speculative_created > 0:
        print(f"\n## Speculative Nodes Created: {speculative_created}")
        print("Use /mem:reason on these to test hypotheses and update uncertainty:")
        for sid in spec_ids:
            b_spec: Belief | None = store.get_belief(sid)
            label: str = b_spec.content[:80] if b_spec else sid
            print(f"  - {sid}: {label}")

    store.close()


# ---------------------------------------------------------------------------
# reason
# ---------------------------------------------------------------------------


def cmd_reason(args: argparse.Namespace) -> None:
    """Consequence-path reasoning with impasse detection.

    Retrieves beliefs via FTS5, builds branching consequence paths with
    compound confidence decay, detects reasoning impasses (ties, gaps,
    constraint failures), and outputs a structured decision-support tree.
    """
    query: str = " ".join(args.query)
    if not query.strip():
        print("Error: empty query", file=sys.stderr)
        sys.exit(1)

    depth: int = (
        args.depth
        if args.depth is not None
        else int(get_setting("reason", "depth") or 2)
    )
    budget: int = args.budget

    store: MemoryStore = _get_store()

    # Step 1: FTS5 retrieval for seed beliefs
    result: RetrievalResult = retrieve(store, query, budget=budget)

    if not result.beliefs:
        print("REASON: No relevant beliefs found for this query.")
        print("VERDICT: INSUFFICIENT -- no evidence in memory.")
        store.close()
        return

    # Step 1.5: Relevance floor check (CS-033)
    # Use content-word overlap between query and top-5 beliefs.
    # Require min 3-char words and exclude common stopwords.
    import re as _re

    _stop_words: frozenset[str] = frozenset(
        {
            "not",
            "don",
            "dont",
            "never",
            "cannot",
            "can",
            "isn",
            "doesn",
            "didn",
            "without",
            "none",
            "nor",
            "the",
            "and",
            "for",
            "are",
            "but",
            "with",
            "this",
            "that",
            "from",
            "have",
            "has",
            "was",
            "were",
            "been",
            "being",
            "will",
            "would",
            "could",
            "should",
            "about",
            "into",
            "what",
            "when",
            "where",
            "which",
            "while",
            "how",
            "who",
            "does",
            "did",
            "our",
            "your",
            "their",
            "its",
            "than",
            "then",
            "also",
            "just",
            "only",
            "very",
            "some",
            "any",
            "each",
            "every",
            "all",
            "both",
            "such",
            "more",
            "most",
            "other",
            "using",
            "used",
            "use",
            "may",
            "need",
            "way",
        }
    )
    query_content: set[str] = {
        t.lower() for t in _re.split(r"\W+", query) if len(t) >= 3
    } - _stop_words
    if query_content:
        topical_hits: int = 0
        for b in result.beliefs[:5]:
            b_terms: set[str] = {
                t.lower() for t in _re.split(r"\W+", b.content) if len(t) >= 3
            } - _stop_words
            overlap: int = len(query_content & b_terms)
            # Require at least 1 shared content word
            if overlap >= 1:
                topical_hits += 1
        if topical_hits == 0:
            print(f"REASON: {query}")
            print("VERDICT: INSUFFICIENT -- no topically relevant beliefs found.")
            print(
                f"  (Returned {len(result.beliefs)} beliefs but none share "
                f"content words with the query.)"
            )
            print(
                "  This topic may not be in memory. Consider using /mem:search "
                "with different keywords."
            )
            store.close()
            return

    # Step 2: Build consequence paths from top 10 seeds
    seed_ids: list[str] = [b.id for b in result.beliefs[:10]]
    paths: list[list[tuple[Belief, str, float]]] = store.find_consequence_paths(
        root_ids=seed_ids,
        max_depth=depth,
        confidence_floor=0.3,
        max_branches=20,
    )

    # Step 3: Collect all beliefs involved (seeds + path members)
    all_beliefs: dict[str, Belief] = {}
    for b in result.beliefs:
        all_beliefs[b.id] = b
    for path in paths:
        for b, _etype, _conf in path:
            all_beliefs[b.id] = b

    # Step 4: Load locked beliefs for constraint checking
    locked_rows: list[Belief] = store.get_locked_beliefs()
    # Filter to topically relevant locked beliefs (in all_beliefs or connected)
    relevant_locked: list[Belief] = [lb for lb in locked_rows if lb.id in all_beliefs]

    # Step 5: Detect impasses
    impasses: list[MemoryStore.Impasse] = store.detect_impasses(
        beliefs=all_beliefs,
        paths=paths,
        locked_beliefs=relevant_locked,
    )

    store.close()

    # Step 6: Compute sufficiency verdict
    has_high_conf: bool = any(b.confidence > 0.7 for b in result.beliefs[:5])
    has_paths: bool = len(paths) > 0
    has_constraint_failure: bool = any(
        imp.impasse_type == "constraint_failure" for imp in impasses
    )
    has_ties: bool = any(imp.impasse_type == "tie" for imp in impasses)

    if has_constraint_failure:
        verdict: str = "CONTRADICTORY -- evidence conflicts with locked constraints"
    elif not has_high_conf and not has_paths:
        verdict = "INSUFFICIENT -- no high-confidence evidence or consequence paths"
    elif has_ties:
        verdict = "UNCERTAIN -- contradicting beliefs with similar confidence"
    elif has_paths and has_high_conf:
        verdict = "SUFFICIENT -- evidence supports reasoning"
    else:
        verdict = "PARTIAL -- some evidence found, gaps remain"

    # Step 7: Format output
    print(f"REASON: {query}")
    print(
        f"  depth={depth}, seeds={len(seed_ids)}, "
        f"paths={len(paths)}, impasses={len(impasses)}"
    )
    print(f"VERDICT: {verdict}")

    # Direct evidence (top 10 seed beliefs)
    if result.beliefs:
        print(f"\nSEED EVIDENCE ({min(len(result.beliefs), 10)} beliefs):")
        for b in result.beliefs[:10]:
            locked_str: str = " [LOCKED]" if b.locked else ""
            unc: float = uncertainty_score(b.alpha, b.beta_param)
            print(f"  [{b.confidence:.0%}]{locked_str} {b.content}")
            print(f"    type={b.belief_type}, uncertainty={unc:.2f}, id={b.id}")

    # Consequence paths
    if paths:
        print(f"\nCONSEQUENCE PATHS ({len(paths)} paths):")
        for i, path in enumerate(paths):
            if not path:
                continue
            leaf_conf: float = path[-1][2]
            # Find weakest link
            weakest_idx: int = 0
            weakest_conf: float = path[0][2]
            for j, (_, _, cc) in enumerate(path):
                if cc < weakest_conf:
                    weakest_conf = cc
                    weakest_idx = j

            print(
                f"\n  PATH {i + 1} (length={len(path)}, "
                f"leaf_confidence={leaf_conf:.0%}):"
            )
            for j, (b, etype, cc) in enumerate(path):
                indent: str = "    " + "  " * j
                locked_str = " [LOCKED]" if b.locked else ""
                arrow: str = f"--{etype}-->" if etype != "ROOT" else "[root]"
                weak_marker: str = (
                    " *** WEAKEST LINK ***"
                    if j == weakest_idx and len(path) > 1
                    else ""
                )
                print(
                    f"{indent}{arrow} [{cc:.0%}]{locked_str} {b.content[:100]}{weak_marker}"
                )

    # Impasses
    if impasses:
        print(f"\nIMPASSES ({len(impasses)} detected):")
        for imp in impasses:
            severity_bar: str = "#" * int(imp.severity * 10)
            print(
                f"  [{imp.impasse_type.upper()}] (severity={imp.severity:.1f}) "
                f"[{severity_bar}]"
            )
            print(f"    {imp.description}")
            if imp.impasse_type == "constraint_failure":
                print("    ACTION: This path is BLOCKED by a locked constraint.")
            elif imp.impasse_type == "tie":
                print("    ACTION: Fork -- resolve which belief is correct.")
            elif imp.impasse_type == "gap":
                print("    ACTION: Evidence insufficient at this point in the chain.")

    if not paths and not impasses:
        print(
            "\n(No consequence paths or impasses found -- "
            "graph may be too sparse for path-based reasoning.)"
        )
        print("Reason output is equivalent to a standard search at this graph density.")

    # Step 8: Update speculative beliefs if any are in the result set
    from agentmemory.uncertainty import (
        UncertaintyVector,
        DIMENSION_FEASIBILITY,
        DIMENSION_VALUE,
    )

    store = _get_store()
    speculative_updated: int = 0

    for b in result.beliefs:
        if b.temporal_direction != "forward" or b.uncertainty_vector is None:
            continue

        uv: UncertaintyVector = UncertaintyVector.from_json(b.uncertainty_vector)

        # Evidence from consequence paths: if this belief appears in paths
        # with high compound confidence, increase feasibility
        in_path: bool = any(any(pb.id == b.id for pb, _, _ in path) for path in paths)
        if in_path and has_high_conf:
            uv.update_dimension(DIMENSION_FEASIBILITY, True, weight=2.0)

        # Evidence from impasses: constraint failures reduce value
        belief_in_impasse: bool = any(
            b.id in (imp.description or "") for imp in impasses
        )
        if has_constraint_failure or belief_in_impasse:
            uv.update_dimension(DIMENSION_VALUE, False, weight=2.0)

        # Supporting evidence: if high-confidence beliefs support this topic
        if has_high_conf and not has_constraint_failure:
            uv.update_dimension(DIMENSION_VALUE, True, weight=1.0)

        # Update in DB
        h_score: float = uv.hibernation_score()
        store.update_uncertainty(b.id, uv.to_json(), h_score)
        speculative_updated += 1

        # Create RESOLVES edge from seed beliefs to this speculative belief
        for seed in result.beliefs[:3]:
            if seed.id != b.id:
                store.insert_edge(
                    seed.id,
                    b.id,
                    "RESOLVES",
                    1.0,
                    f"reason:{verdict.split(' -- ')[0].lower()}",
                )

    if speculative_updated > 0:
        print(f"\nSPECULATIVE UPDATES: {speculative_updated} belief(s) updated")
        print(f"  Verdict applied: {verdict.split(' -- ')[0]}")
        # Show updated uncertainty summaries
        for b in result.beliefs:
            if b.temporal_direction != "forward" or b.uncertainty_vector is None:
                continue
            updated_b: Belief | None = store.get_belief(b.id)
            if updated_b is not None and updated_b.uncertainty_vector is not None:
                uv_updated: UncertaintyVector = UncertaintyVector.from_json(
                    updated_b.uncertainty_vector
                )
                summary: dict[str, dict[str, float]] = uv_updated.dimension_summary()
                h: float = (
                    updated_b.hibernation_score
                    if updated_b.hibernation_score is not None
                    else 0.0
                )
                print(f"  {b.id}: hibernation={h:.3f}")
                for dim_name, dim_data in summary.items():
                    print(
                        f"    {dim_name}: mean={dim_data['mean']:.3f}, "
                        f"voi={dim_data['voi']:.4f}"
                    )

    store.close()


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
        print(
            f"  Unlocked: [{b.confidence:.0%}] {b.content} (ID: {b.id}, score: {s:.3f})"
        )

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
        print(
            f"  Deleted [{belief.confidence:.0%}] {belief.content[:80]} (ID: {belief_id})"
        )
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
        topic=args.topic,
        start=start,
        end=end,
        session_id=args.session,
        limit=args.limit,
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
        belief_id=args.belief_id,
        topic=args.topic,
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
        wonder_section: dict[str, Any] = cast(
            "dict[str, Any]", config.get("wonder", {})
        )
        wonder_section["max_agents"] = args.wonder_max_agents
        config["wonder"] = wonder_section
        changed = True
    if args.core_default_top is not None:
        core_section: dict[str, Any] = cast("dict[str, Any]", config.get("core", {}))
        core_section["default_top"] = args.core_default_top
        config["core"] = core_section
        changed = True
    if args.locked_max_cap is not None:
        locked_section: dict[str, Any] = cast(
            "dict[str, Any]", config.get("locked", {})
        )
        locked_section["max_cap"] = args.locked_max_cap
        config["locked"] = locked_section
        changed = True
    if args.locked_warn_at is not None:
        locked_section2: dict[str, Any] = cast(
            "dict[str, Any]", config.get("locked", {})
        )
        locked_section2["warn_at"] = args.locked_warn_at
        config["locked"] = locked_section2
        changed = True
    if args.reason_max_agents is not None:
        reason_section: dict[str, Any] = cast(
            "dict[str, Any]", config.get("reason", {})
        )
        reason_section["max_agents"] = args.reason_max_agents
        config["reason"] = reason_section
        changed = True
    if args.reason_depth is not None:
        reason_section2: dict[str, Any] = cast(
            "dict[str, Any]", config.get("reason", {})
        )
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
_DIRECTIVE_GATE_MATCHER: str = "agentmemory-directive-gate"

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

    pre_tool.append(
        {
            "type": "command",
            "command": f"{cmd} commit-check",
        }
    )
    hooks["PreToolUse"] = pre_tool
    settings["hooks"] = hooks
    _SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"  Installed commit tracker hook in {_SETTINGS_PATH}")


def _install_directive_gate() -> None:
    """Add the directive-gate PreToolUse hook to Claude Code settings.json.

    The hook runs ``scripts/agentmemory-directive-gate.sh`` before write-like
    tools, surfacing locked behavioral directives as context reminders.
    Idempotent -- skips if already present.
    """
    # Try CWD first (cloned repo), then fall back to __file__ traversal (editable install)
    gate_script: Path = Path.cwd() / "scripts" / "agentmemory-directive-gate.sh"
    if not gate_script.exists():
        gate_script = (
            Path(__file__).resolve().parents[2]
            / "scripts"
            / "agentmemory-directive-gate.sh"
        )
    if not gate_script.exists():
        print(
            "  Warning: directive gate script not found, skipping hook install",
            file=sys.stderr,
        )
        return
    gate_command: str = f"bash {gate_script}"

    hook_entry: dict[str, object] = {
        "hooks": {
            "PreToolUse": [
                {
                    "type": "command",
                    "matcher": "Edit|Write|Bash|NotebookEdit",
                    "command": gate_command,
                }
            ]
        }
    }

    if not _SETTINGS_PATH.exists():
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_PATH.write_text(json.dumps(hook_entry, indent=2) + "\n")
        print(f"  Installed directive gate hook in {_SETTINGS_PATH}")
        return

    try:
        settings: dict[str, Any] = json.loads(_SETTINGS_PATH.read_text())
    except (json.JSONDecodeError, ValueError):
        print(
            f"  Warning: could not parse {_SETTINGS_PATH}, skipping directive gate install",
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
            if _DIRECTIVE_GATE_MATCHER in cmd_val:
                print("  Directive gate hook already installed")
                return

    pre_tool.append(
        {
            "type": "command",
            "matcher": "Edit|Write|Bash|NotebookEdit",
            "command": gate_command,
        }
    )
    hooks["PreToolUse"] = pre_tool
    settings["hooks"] = hooks
    _SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"  Installed directive gate hook in {_SETTINGS_PATH}")


# ---------------------------------------------------------------------------
# feedback-flush
# ---------------------------------------------------------------------------

_FEEDBACK_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "must",
        "can",
        "could",
        "of",
        "in",
        "to",
        "for",
        "with",
        "on",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "not",
        "no",
        "all",
        "and",
        "or",
        "but",
        "if",
        "then",
        "than",
        "when",
        "where",
        "how",
        "what",
        "which",
        "who",
        "whom",
        "use",
        "using",
        "used",
    }
)

_FEEDBACK_MIN_MATCHES: int = 2


def _extract_feedback_key_terms(text: str) -> list[str]:
    """Extract meaningful terms from text, filtering stopwords."""
    import re as _re

    words: list[str] = _re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return [w for w in words if w not in _FEEDBACK_STOPWORDS and len(w) >= 2]


def cmd_feedback_flush(args: argparse.Namespace) -> None:
    """Process pending feedback entries against recently ingested text."""
    from agentmemory.models import (
        LAYER_IMPLICIT,
        OUTCOME_IGNORED,
        OUTCOME_USED,
    )

    store: MemoryStore = _get_store()
    session_filter: str | None = getattr(args, "session", None)
    entries: list[dict[str, str]] = store.get_pending_feedback(
        session_id=session_filter if session_filter else None,
    )

    if not entries:
        print("No pending feedback entries to process.")
        return

    # Gather recently ingested text: observations from the same session(s)
    session_ids: set[str] = {e["session_id"] for e in entries if e["session_id"]}
    combined_text: str = ""
    for sid in session_ids:
        texts: list[str] = store.get_session_observation_texts(sid)
        combined_text += " ".join(texts) + " "
    combined_lower: str = combined_text.lower()

    matches: int = 0
    for entry in entries:
        belief_id: str = entry["belief_id"]
        belief_content: str = entry["belief_content"]
        sid_val: str = entry["session_id"]

        terms: list[str] = _extract_feedback_key_terms(belief_content)
        if not terms:
            continue

        unique_terms: set[str] = set(terms)
        unique_matches: int = sum(1 for t in unique_terms if t in combined_lower)

        outcome: str = (
            OUTCOME_USED if unique_matches >= _FEEDBACK_MIN_MATCHES else OUTCOME_IGNORED
        )
        detail: str = f"flush: {unique_matches}/{len(unique_terms)} key terms matched"

        store.record_test_result(
            belief_id=belief_id,
            session_id=sid_val if sid_val else "unknown",
            outcome=outcome,
            detection_layer=LAYER_IMPLICIT,
            outcome_detail=detail,
        )
        if outcome == OUTCOME_USED:
            matches += 1

    cleared: int = store.clear_pending_feedback(
        session_id=session_filter if session_filter else None,
    )
    print(f"Processed {cleared} pending feedback entries, {matches} matches found")


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
    for prefix in [
        "mem-correct",
        "mem-ingest",
        "mem-locked",
        "mem-observe",
        "mem-onboard",
        "mem-remember",
        "mem-search",
        "mem-status",
    ]:
        old_path: Path = old_skills_dir / prefix
        if old_path.is_dir():
            shutil.rmtree(old_path)

    print("  Removed legacy skills")
    print(
        "\nDone. Data is preserved at ~/.agentmemory/. To delete data: rm -rf ~/.agentmemory/"
    )


# ---------------------------------------------------------------------------
# rebuild-edges
# ---------------------------------------------------------------------------


def cmd_rebuild_edges(args: argparse.Namespace) -> None:
    """Rebuild SUPPORTS/CONTRADICTS edges across all active beliefs."""
    from agentmemory.relationship_detector import (
        RelationshipResult,
        detect_relationships,
    )

    store: MemoryStore = _get_store()
    only_orphans: bool = bool(args.only_orphans)

    all_ids: list[str] = store.get_active_belief_ids()
    total: int = len(all_ids)

    if only_orphans:
        orphan_ids: list[str] = [
            bid for bid in all_ids if store.count_edges_for(bid) == 0
        ]
        target_ids: list[str] = orphan_ids
        print(f"Targeting {len(orphan_ids)} orphan beliefs (of {total} active)")
    else:
        target_ids = all_ids
        print(f"Targeting all {total} active beliefs")

    edges_created: int = 0
    contradictions: int = 0
    supports: int = 0
    processed: int = 0
    skipped: int = 0

    for i, belief_id in enumerate(target_ids):
        belief: Belief | None = store.get_belief(belief_id)
        if belief is None or belief.valid_to is not None:
            skipped += 1
            continue

        result: RelationshipResult = detect_relationships(store, belief)
        edges_created += result.edges_created
        contradictions += result.contradictions
        supports += result.supports
        processed += 1

        if (i + 1) % 500 == 0:
            pct: float = (i + 1) / len(target_ids) * 100
            print(
                f"  [{pct:5.1f}%] {i + 1}/{len(target_ids)}"
                f" -- {edges_created} edges so far"
                f" ({supports} SUPPORTS, {contradictions} CONTRADICTS)"
            )

    store.close()

    print(f"\nDone. Processed {processed} beliefs (skipped {skipped}).")
    print(f"  Edges created: {edges_created}")
    print(f"    SUPPORTS: {supports}")
    print(f"    CONTRADICTS: {contradictions}")


# ---------------------------------------------------------------------------
# batch-feedback
# ---------------------------------------------------------------------------


def cmd_batch_feedback(args: argparse.Namespace) -> None:
    """Apply bulk feedback to beliefs matching criteria."""
    store: MemoryStore = _get_store()
    outcome: str = args.outcome
    weight: float = float(args.weight)

    if args.source_type:
        rows: list[sqlite3.Row] = store.query(
            "SELECT id FROM beliefs WHERE valid_to IS NULL AND source_type = ?",
            (args.source_type,),
        )
        target_ids: list[str] = [str(r["id"]) for r in rows]
        print(
            f"Targeting {len(target_ids)} beliefs with source_type={args.source_type}"
        )
    elif args.belief_type:
        rows = store.query(
            "SELECT id FROM beliefs WHERE valid_to IS NULL AND belief_type = ?",
            (args.belief_type,),
        )
        target_ids = [str(r["id"]) for r in rows]
        print(
            f"Targeting {len(target_ids)} beliefs with belief_type={args.belief_type}"
        )
    elif args.classified_by:
        rows = store.query(
            "SELECT id FROM beliefs WHERE valid_to IS NULL AND classified_by = ?",
            (args.classified_by,),
        )
        target_ids = [str(r["id"]) for r in rows]
        print(f"Targeting {len(target_ids)} beliefs classified_by={args.classified_by}")
    else:
        rows = store.query("SELECT id FROM beliefs WHERE valid_to IS NULL")
        target_ids = [str(r["id"]) for r in rows]
        print(f"Targeting all {len(target_ids)} active beliefs")

    print(f"Applying outcome={outcome}, weight={weight}")

    updated: int = store.bulk_update_confidence(target_ids, outcome, weight)
    store.close()

    print(f"Updated {updated} beliefs.")


def cmd_recalibrate(args: argparse.Namespace) -> None:
    """Deflate inflated Bayesian scores on agent-inferred beliefs."""
    store: MemoryStore = _get_store()
    factor: float = getattr(args, "factor", 0.2)
    count: int = store.recalibrate_scores(factor)
    store.close()
    print(f"Recalibrated {count} agent-inferred beliefs (factor={factor}).")
    print("User-sourced and locked beliefs were not touched.")


def cmd_sync_obsidian(args: argparse.Namespace) -> None:
    """Export beliefs to an Obsidian vault as markdown files."""
    from agentmemory.obsidian import (
        ObsidianConfig,
        SyncResult,
        load_obsidian_config,
        sync_vault,
    )

    store: MemoryStore = _get_store()

    vault_path: str | None = getattr(args, "vault", None)
    full: bool = getattr(args, "full", False)
    tier: str = getattr(args, "tier", "full")
    max_beliefs: int | None = getattr(args, "max_beliefs", None)

    config: ObsidianConfig | None = load_obsidian_config(vault_path)
    if config is None:
        print(
            "Error: no vault path configured. Use --vault or set "
            "obsidian.vault_path in ~/.agentmemory/config.json"
        )
        sys.exit(1)
    if not config.vault_path.exists():
        print(f"Error: vault path does not exist: {config.vault_path}")
        sys.exit(1)

    label: str = f"tier={tier}" if max_beliefs is None else f"max={max_beliefs}"
    print(f"Syncing to {config.vault_path} ({label}) ...")
    result: SyncResult = sync_vault(
        store,
        config,
        full=full,
        tier=tier,
        max_beliefs=max_beliefs,
    )
    store.close()

    print(f"Done in {result.elapsed_seconds}s:")
    print(f"  Written:   {result.beliefs_written}")
    print(f"  Unchanged: {result.beliefs_unchanged}")
    print(f"  Archived:  {result.beliefs_archived}")
    print(f"  Index:     {result.index_notes_written} notes")


def cmd_import_obsidian(args: argparse.Namespace) -> None:
    """Import changes from Obsidian vault back into agentmemory."""
    from agentmemory.obsidian import (
        ImportResult,
        ObsidianConfig,
        VaultChange,
        detect_vault_changes,
        import_vault_changes,
        load_obsidian_config,
    )

    store: MemoryStore = _get_store()

    vault_path: str | None = getattr(args, "vault", None)
    dry_run: bool = not getattr(args, "apply", False)

    config: ObsidianConfig | None = load_obsidian_config(vault_path)
    if config is None:
        print(
            "Error: no vault path configured. Use --vault or set "
            "obsidian.vault_path in ~/.agentmemory/config.json"
        )
        sys.exit(1)
    if not config.vault_path.exists():
        print(f"Error: vault path does not exist: {config.vault_path}")
        sys.exit(1)

    changes: list[VaultChange] = detect_vault_changes(config)
    if not changes:
        print("No changes detected in vault since last sync.")
        store.close()
        return

    if dry_run:
        print(f"Detected {len(changes)} change(s) (dry run):")
        for c in changes:
            preview: str = (c.new_text or "")[:60]
            print(f"  [{c.change_type}] {c.belief_id}: {preview}")
        print("\nRe-run with --apply to import changes.")
    else:
        result: ImportResult = import_vault_changes(store, changes)
        print("Import complete:")
        print(f"  Modified: {result.modified}")
        print(f"  New:      {result.new_beliefs}")
        print(f"  Deleted:  {result.deleted}")
        if result.errors:
            print("  Errors:")
            for e in result.errors:
                print(f"    - {e}")

    store.close()


def cmd_link_docs(args: argparse.Namespace) -> None:
    """Export project documents to Obsidian vault with cross-references."""
    from agentmemory.doc_linker import LinkResult, link_documents
    from agentmemory.obsidian import ObsidianConfig, load_obsidian_config

    store: MemoryStore = _get_store()
    vault_path: str | None = getattr(args, "vault", None)
    project: str | None = getattr(args, "project_dir", None)

    config: ObsidianConfig | None = load_obsidian_config(vault_path)
    if config is None:
        print(
            "Error: no vault path configured. Use --vault or set "
            "obsidian.vault_path in ~/.agentmemory/config.json"
        )
        sys.exit(1)

    proj_path: Path = Path(project).resolve() if project else Path.cwd()
    print(f"Linking docs from {proj_path} to {config.vault_path}/docs/ ...")

    result: LinkResult = link_documents(store, proj_path, config.vault_path)
    store.close()

    print(f"Done in {result.elapsed_seconds}s:")
    print(f"  Documents:    {result.docs_exported}")
    print(f"  References:   {result.refs_linked}")
    print(f"  Belief links: {result.belief_refs_added}")


def cmd_rebuild_index(args: argparse.Namespace) -> None:
    """Rebuild SQLite index from vault .md files."""
    from agentmemory.vault_store import RebuildResult, VaultStore

    vault_path: str | None = getattr(args, "vault", None)
    if vault_path is None:
        from agentmemory.config import get_str_setting

        vault_path = get_str_setting("obsidian", "vault_path")
    if not vault_path:
        print("Error: no vault path. Use --vault or set obsidian.vault_path")
        sys.exit(1)

    vp: Path = Path(vault_path)
    if not vp.exists():
        print(f"Error: vault path does not exist: {vp}")
        sys.exit(1)

    db_path: Path = _resolve_db_path()
    print(f"Rebuilding index from {vp}/beliefs/ -> {db_path} ...")

    vs: VaultStore = VaultStore(vp, db_path)
    result: RebuildResult = vs.rebuild_index()
    vs.close()

    print(f"Done in {result.elapsed_seconds}s:")
    print(f"  Beliefs indexed: {result.beliefs_indexed}")
    print(f"  Edges created:   {result.edges_created}")
    if result.errors:
        print(f"  Errors: {len(result.errors)}")
        for e in result.errors[:10]:
            print(f"    - {e}")


# ---------------------------------------------------------------------------
# telemetry toggle
# ---------------------------------------------------------------------------


def cmd_enable_telemetry(args: argparse.Namespace) -> None:
    """Enable anonymous telemetry."""
    from agentmemory.config import load_config, save_config

    config: dict[str, object] = load_config()
    telem: dict[str, object] = {"enabled": True}
    config["telemetry"] = telem
    save_config(config)  # type: ignore[arg-type]
    print("Telemetry ENABLED.")
    print(
        "Content-free performance metrics will be appended to ~/.agentmemory/telemetry.jsonl"
    )
    print("Disable anytime: agentmemory disable-telemetry (or /mem:disable-telemetry)")


def cmd_disable_telemetry(args: argparse.Namespace) -> None:
    """Disable anonymous telemetry."""
    from agentmemory.config import load_config, save_config

    config: dict[str, object] = load_config()
    telem: dict[str, object] = {"enabled": False}
    config["telemetry"] = telem
    save_config(config)  # type: ignore[arg-type]
    print("Telemetry DISABLED.")
    print("No further data will be written to ~/.agentmemory/telemetry.jsonl")
    print("Re-enable anytime: agentmemory enable-telemetry (or /mem:enable-telemetry)")


def cmd_send_telemetry(args: argparse.Namespace) -> None:
    """Send unsent telemetry snapshots to the project maintainers."""
    import json as _json

    from agentmemory.config import get_setting, get_str_setting
    from agentmemory.telemetry import get_unsent_lines, mark_sent, send_telemetry

    enabled: bool = bool(get_setting("telemetry", "enabled"))
    if not enabled:
        print(
            "Telemetry is disabled. Enable it first with: agentmemory enable-telemetry"
        )
        sys.exit(1)

    unsent, offset = get_unsent_lines()
    if not unsent:
        print("No unsent telemetry snapshots.")
        return

    endpoint: str = get_str_setting("telemetry", "endpoint")
    if not endpoint:
        print("Error: no telemetry endpoint configured.", file=sys.stderr)
        sys.exit(1)

    print(f"  {len(unsent)} unsent snapshot(s) to send to:")
    print(f"  {endpoint}\n")
    print("  Payload preview (each line is one session snapshot):")
    print("  " + "-" * 60)
    for i, line in enumerate(unsent):
        try:
            obj: dict[str, object] = _json.loads(line)
            ts: object = obj.get("ts", "?")
            session_raw: object = obj.get("session")
            beliefs_raw: object = obj.get("beliefs")
            s_created: object = 0
            b_active: object = 0
            if isinstance(session_raw, dict):
                sd: dict[str, object] = session_raw  # type: ignore[assignment]
                s_created = sd.get("beliefs_created", 0)
            if isinstance(beliefs_raw, dict):
                bd: dict[str, object] = beliefs_raw  # type: ignore[assignment]
                b_active = bd.get("total_active", 0)
            print(
                f"  [{i + 1}] ts={ts}  beliefs_created={s_created}  total_active={b_active}"
            )
        except (ValueError, AttributeError):
            print(f"  [{i + 1}] (unparseable line)")
    print("  " + "-" * 60)
    print(f"\n  Data file: {Path.home() / '.agentmemory' / 'telemetry.jsonl'}")
    print("  Open the file to inspect the full payload before sending.\n")

    answer: str = input("  Send this data? [y/N]: ").strip().lower()
    if answer not in ("y", "yes"):
        print("  Cancelled. Nothing was sent.")
        return

    try:
        result: dict[str, object] = send_telemetry(endpoint, unsent)
        accepted: object = result.get("accepted", 0)
        rejected: object = result.get("rejected", 0)
        print(f"\n  Sent. Accepted: {accepted}, Rejected: {rejected}")
        if isinstance(accepted, int) and accepted > 0:
            mark_sent(offset + len(unsent))
            print("  Offset updated. These snapshots won't be sent again.")
    except Exception as exc:
        print(f"\n  Send failed: {exc}", file=sys.stderr)
        print("  Your data is still local. Try again later.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="agentmemory",
        description="Persistent memory for AI coding agents",
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
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
    p_onboard.add_argument(
        "--link",
        action="store_true",
        default=False,
        help="Run Haiku semantic linking after ingestion (~$0.01-0.05)",
    )
    p_onboard.set_defaults(func=cmd_onboard)

    # ingest
    p_ingest: argparse.ArgumentParser = subparsers.add_parser(
        "ingest", help="Ingest a JSONL conversation log"
    )
    p_ingest.add_argument("path", help="Path to JSONL file")
    p_ingest.set_defaults(func=cmd_ingest)

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

    # metrics
    p_metrics: argparse.ArgumentParser = subparsers.add_parser(
        "metrics", help="Session metrics from conversation logs"
    )
    p_metrics.add_argument(
        "--output", default=None, help="Write JSON report to this path"
    )
    p_metrics.set_defaults(func=cmd_metrics)

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

    # stale
    p_stale: argparse.ArgumentParser = subparsers.add_parser(
        "stale", help="Show stale beliefs (not retrieved recently)"
    )
    p_stale.add_argument(
        "--days",
        type=int,
        default=30,
        help="Days threshold for staleness (default: 30)",
    )
    p_stale.add_argument(
        "--limit", type=int, default=20, help="Max beliefs to show (default: 20)"
    )
    p_stale.set_defaults(func=cmd_stale)

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
    p_wonder.add_argument(
        "--depth",
        type=int,
        default=None,
        help="Graph expansion depth 1-3 (default: from config, usually 2)",
    )
    p_wonder.add_argument(
        "--budget",
        type=int,
        default=4000,
        help="Token budget for retrieval (default: 4000)",
    )
    p_wonder.set_defaults(func=cmd_wonder)

    # reason
    p_reason: argparse.ArgumentParser = subparsers.add_parser(
        "reason", help="Graph-aware reasoning with uncertainty analysis"
    )
    p_reason.add_argument("query", nargs="+", help="Statement or topic to reason about")
    p_reason.add_argument(
        "--depth",
        type=int,
        default=None,
        help="Graph expansion depth 1-3 (default: from config, usually 2)",
    )
    p_reason.add_argument(
        "--budget",
        type=int,
        default=4000,
        help="Token budget for retrieval (default: 4000)",
    )
    p_reason.set_defaults(func=cmd_reason)

    # unlock
    p_unlock: argparse.ArgumentParser = subparsers.add_parser(
        "unlock", help="Unlock least-relevant locked beliefs"
    )
    p_unlock.add_argument(
        "--count", type=int, default=5, help="Number of beliefs to unlock (default: 5)"
    )
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
    p_timeline.add_argument(
        "--since", default=None, help="Start time (ISO 8601 or -7d/-24h)"
    )
    p_timeline.add_argument(
        "--until", default=None, help="End time (ISO 8601 or -7d/-24h)"
    )
    p_timeline.add_argument("--session", default=None, help="Filter by session ID")
    p_timeline.add_argument(
        "--limit", type=int, default=50, help="Max beliefs (default: 50)"
    )
    p_timeline.set_defaults(func=cmd_timeline)

    # evolution
    p_evolution: argparse.ArgumentParser = subparsers.add_parser(
        "evolution", help="Trace belief or topic evolution"
    )
    p_evolution.add_argument(
        "--belief-id", default=None, help="Follow SUPERSEDES chain for this belief"
    )
    p_evolution.add_argument(
        "--topic", default=None, help="Show all beliefs about topic chronologically"
    )
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
    p_settings.add_argument(
        "--wonder-max-agents",
        type=int,
        default=None,
        help="Max subagents for /mem:wonder (default: 4)",
    )
    p_settings.add_argument(
        "--core-default-top",
        type=int,
        default=None,
        help="Default N for /mem:core (default: 10)",
    )
    p_settings.add_argument(
        "--locked-max-cap",
        type=int,
        default=None,
        help="Max locked beliefs in retrieve (default: 100)",
    )
    p_settings.add_argument(
        "--locked-warn-at",
        type=int,
        default=None,
        help="Warn when locked beliefs exceed this (default: 80)",
    )
    p_settings.add_argument(
        "--reason-max-agents",
        type=int,
        default=None,
        help="Max subagents for /mem:reason (default: 3)",
    )
    p_settings.add_argument(
        "--reason-depth",
        type=int,
        default=None,
        help="Graph expansion depth for /mem:reason (default: 2)",
    )
    p_settings.set_defaults(func=cmd_settings)

    # commit-check
    p_commit_check: argparse.ArgumentParser = subparsers.add_parser(
        "commit-check", help="Check time/changes since last commit"
    )
    p_commit_check.add_argument(
        "--project-dir", default=".", help="Git repo to check (default: cwd)"
    )
    p_commit_check.add_argument(
        "--nudge-only",
        action="store_true",
        default=False,
        help="Only print output when a nudge threshold is exceeded",
    )
    p_commit_check.set_defaults(func=cmd_commit_check)

    # commit-config
    p_commit_config: argparse.ArgumentParser = subparsers.add_parser(
        "commit-config", help="View or update commit tracker settings"
    )
    p_commit_config.add_argument("--enable", action="store_true", help="Enable tracker")
    p_commit_config.add_argument(
        "--disable", action="store_true", help="Disable tracker"
    )
    p_commit_config.add_argument(
        "--max-minutes",
        type=int,
        default=None,
        help="Minutes before nudge (default: 15)",
    )
    p_commit_config.add_argument(
        "--max-changes",
        type=int,
        default=None,
        help="Uncommitted changes before nudge (default: 10)",
    )
    p_commit_config.set_defaults(func=cmd_commit_config)

    # session-complete
    p_session_complete: argparse.ArgumentParser = subparsers.add_parser(
        "session-complete",
        help="Complete active session (for session-end hooks)",
    )
    p_session_complete.add_argument(
        "--log", default=None, help="Path to turns.jsonl (default: auto-detect)"
    )
    p_session_complete.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Skip conversation turn ingestion",
    )
    p_session_complete.add_argument(
        "--quiet", "-q", action="store_true", help="Suppress output"
    )
    p_session_complete.set_defaults(func=cmd_session_complete)

    # feedback-flush
    p_feedback_flush: argparse.ArgumentParser = subparsers.add_parser(
        "feedback-flush", help="Process pending feedback entries from DB"
    )
    p_feedback_flush.add_argument(
        "--session", default=None, help="Filter by session ID"
    )
    p_feedback_flush.set_defaults(func=cmd_feedback_flush)

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

    # rebuild-edges
    p_rebuild: argparse.ArgumentParser = subparsers.add_parser(
        "rebuild-edges", help="Rebuild SUPPORTS/CONTRADICTS edges across all beliefs"
    )
    p_rebuild.add_argument(
        "--only-orphans",
        action="store_true",
        help="Only process beliefs with no existing SUPPORTS/CONTRADICTS edges",
    )
    p_rebuild.set_defaults(func=cmd_rebuild_edges)

    # batch-feedback
    p_batch: argparse.ArgumentParser = subparsers.add_parser(
        "batch-feedback", help="Apply bulk feedback to beliefs matching criteria"
    )
    p_batch.add_argument(
        "--outcome",
        choices=["used", "harmful"],
        default="used",
        help="Feedback outcome (default: used)",
    )
    p_batch.add_argument(
        "--weight",
        type=float,
        default=0.5,
        help="Update weight (default: 0.5)",
    )
    p_batch.add_argument("--source-type", default=None, help="Filter by source_type")
    p_batch.add_argument("--belief-type", default=None, help="Filter by belief_type")
    p_batch.add_argument(
        "--classified-by", default=None, help="Filter by classified_by"
    )
    p_batch.set_defaults(func=cmd_batch_feedback)

    # sync-obsidian
    p_sync_obs: argparse.ArgumentParser = subparsers.add_parser(
        "sync-obsidian", help="Export beliefs to Obsidian vault"
    )
    p_sync_obs.add_argument(
        "--vault", default=None, help="Obsidian vault path (default: from config)"
    )
    p_sync_obs.add_argument(
        "--full",
        action="store_true",
        default=False,
        help="Rewrite all files unconditionally",
    )
    p_sync_obs.add_argument(
        "--tier",
        default="full",
        choices=["core", "connected", "full"],
        help="Filter tier: core (~2000), connected (non-orphans), full (all)",
    )
    p_sync_obs.add_argument(
        "--max-beliefs",
        type=int,
        default=None,
        dest="max_beliefs",
        help="Export only top N beliefs by priority (overrides --tier)",
    )
    p_sync_obs.set_defaults(func=cmd_sync_obsidian)

    # import-obsidian
    p_import_obs: argparse.ArgumentParser = subparsers.add_parser(
        "import-obsidian", help="Import vault edits back into agentmemory"
    )
    p_import_obs.add_argument(
        "--vault", default=None, help="Obsidian vault path (default: from config)"
    )
    p_import_obs.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Apply changes (default: dry run)",
    )
    p_import_obs.set_defaults(func=cmd_import_obsidian)

    # link-docs
    p_link_docs: argparse.ArgumentParser = subparsers.add_parser(
        "link-docs",
        help="Export project documents to Obsidian vault with cross-references",
    )
    p_link_docs.add_argument(
        "--vault", default=None, help="Obsidian vault path (default: from config)"
    )
    p_link_docs.add_argument(
        "--project-dir", default=None, help="Project directory to scan (default: cwd)"
    )
    p_link_docs.set_defaults(func=cmd_link_docs)

    # rebuild-index
    p_rebuild_idx: argparse.ArgumentParser = subparsers.add_parser(
        "rebuild-index", help="Rebuild SQLite index from vault .md files"
    )
    p_rebuild_idx.add_argument(
        "--vault", default=None, help="Obsidian vault path (default: from config)"
    )
    p_rebuild_idx.set_defaults(func=cmd_rebuild_index)

    p_enable_telem: argparse.ArgumentParser = subparsers.add_parser(
        "enable-telemetry", help="Enable anonymous telemetry logging"
    )
    p_enable_telem.set_defaults(func=cmd_enable_telemetry)

    p_disable_telem: argparse.ArgumentParser = subparsers.add_parser(
        "disable-telemetry", help="Disable anonymous telemetry logging"
    )
    p_disable_telem.set_defaults(func=cmd_disable_telemetry)

    p_send_telem: argparse.ArgumentParser = subparsers.add_parser(
        "send-telemetry", help="Send unsent telemetry snapshots (with confirmation)"
    )
    p_send_telem.set_defaults(func=cmd_send_telemetry)

    # recalibrate
    p_recal: argparse.ArgumentParser = subparsers.add_parser(
        "recalibrate", help="Deflate inflated Bayesian scores on agent-inferred beliefs"
    )
    p_recal.add_argument(
        "--factor",
        type=float,
        default=0.2,
        help="Deflation factor for alpha (default: 0.2)",
    )
    p_recal.set_defaults(func=cmd_recalibrate)

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
