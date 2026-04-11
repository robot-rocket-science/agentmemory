"""MCP server for agentmemory, exposing memory tools via FastMCP.

Provides search, remember, correct, observe, status, and get_locked tools.
Uses a single lazily-initialized MemoryStore backed by ~/.agentmemory/memory.db.
"""
from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP

from agentmemory.commit_tracker import (
    CommitCheckResult,
    CommitTrackerConfig,
    check_commit_status,
    format_status,
    load_config as load_commit_config,
    save_config as save_commit_config,
)
from agentmemory.ingest import IngestResult, ingest_turn
from agentmemory.scanner import ScanResult, scan_project
from agentmemory.models import (
    BSRC_USER_CORRECTED,
    BSRC_USER_STATED,
    BELIEF_FACTUAL,
    BELIEF_CORRECTION,
    OBS_TYPE_USER_STATEMENT,
    Belief,
    Observation,
)
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore

# ---------------------------------------------------------------------------
# Store singleton
# ---------------------------------------------------------------------------

_store: MemoryStore | None = None

_DEFAULT_DB_PATH: Path = Path.home() / ".agentmemory" / "memory.db"


def _get_store() -> MemoryStore:
    """Return the module-level MemoryStore, creating it on first call."""
    global _store
    if _store is None:
        _DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _store = MemoryStore(_DEFAULT_DB_PATH)
    return _store


def _set_store(store: MemoryStore) -> None:  # pyright: ignore[reportUnusedFunction]
    """Override the module-level store. Used by tests."""
    global _store
    _store = store


# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp: FastMCP = FastMCP(name="agentmemory")


def _format_belief(belief: Belief, score: float | None = None) -> str:
    """Format a single belief for display."""
    score_part: str = f", score: {score:.3f}" if score is not None else ""
    return (
        f"[{belief.confidence:.0%}] {belief.content} "
        f"(ID: {belief.id}, type: {belief.belief_type}{score_part})"
    )


@mcp.tool
def search(query: str, budget: int = 2000) -> str:
    """Search for beliefs relevant to the query.

    Returns formatted text of matching beliefs with confidence scores.
    Uses the retrieval pipeline (FTS5 + scoring + packing).
    """
    store: MemoryStore = _get_store()
    result: RetrievalResult = retrieve(store, query, budget=budget)

    if not result.beliefs:
        return "No beliefs found matching your query."

    lines: list[str] = [
        f"Found {len(result.beliefs)} belief(s) ({result.total_tokens} tokens, "
        f"{result.budget_remaining} remaining):"
    ]
    for belief in result.beliefs:
        score: float | None = result.scores.get(belief.id)
        lines.append(_format_belief(belief, score))

    return "\n".join(lines)


@mcp.tool
def remember(text: str) -> str:
    """Create a high-confidence belief from a user statement.

    Sets source_type='user_stated', alpha=9.0, beta_param=0.5.
    NOT locked -- only /mem:lock creates locked beliefs.
    Returns confirmation with belief ID.
    """
    store: MemoryStore = _get_store()
    belief: Belief = store.insert_belief(
        content=text,
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
        locked=False,
    )
    return (
        f"Remembered (ID: {belief.id}): {belief.content} "
        f"[confidence: {belief.confidence:.0%}, locked: {belief.locked}]"
    )


@mcp.tool
def correct(text: str, replaces: str | None = None) -> str:
    """Record a user correction.

    Creates a high-confidence belief with source_type='user_corrected'.
    NOT locked -- only /mem:lock creates locked beliefs.
    If replaces is provided (a search query), finds the best matching
    existing belief and supersedes it.
    """
    store: MemoryStore = _get_store()
    belief: Belief = store.insert_belief(
        content=text,
        belief_type=BELIEF_CORRECTION,
        source_type=BSRC_USER_CORRECTED,
        alpha=9.0,
        beta_param=0.5,
        locked=False,
    )

    superseded_msg: str = ""
    if replaces is not None and replaces.strip():
        candidates: list[Belief] = store.search(replaces.strip(), top_k=5)
        for candidate in candidates:
            if candidate.id == belief.id:
                continue
            if candidate.valid_to is not None:
                continue
            if candidate.superseded_by is not None:
                continue
            store.supersede_belief(
                old_id=candidate.id,
                new_id=belief.id,
                reason="user_corrected",
            )
            superseded_msg = f" Superseded belief ID: {candidate.id}."
            break

    return (
        f"Correction recorded (ID: {belief.id}): {belief.content} "
        f"[confidence: {belief.confidence:.0%}, locked: {belief.locked}]."
        f"{superseded_msg}"
    )


@mcp.tool
def observe(text: str, source: str = "user") -> str:
    """Record a raw observation without creating a belief.

    Returns the observation ID.
    """
    store: MemoryStore = _get_store()
    obs: Observation = store.insert_observation(
        content=text,
        observation_type=OBS_TYPE_USER_STATEMENT,
        source_type=source,
        source_id=source,
    )
    return f"Observation recorded (ID: {obs.id}): {obs.content}"


@mcp.tool
def status() -> str:
    """Return memory system status.

    Reports counts of observations, beliefs, locked beliefs, superseded
    beliefs, edges, and sessions.
    """
    store: MemoryStore = _get_store()
    counts: dict[str, int] = store.status()
    lines: list[str] = ["Memory system status:"]
    for key, value in counts.items():
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)


@mcp.tool
def get_locked() -> str:
    """Return all locked beliefs formatted for context injection.

    This is what the SessionStart hook calls to load persistent beliefs
    into the agent's active context.
    """
    store: MemoryStore = _get_store()
    beliefs: list[Belief] = store.get_locked_beliefs()

    if not beliefs:
        return "No locked beliefs found."

    lines: list[str] = [f"Locked beliefs ({len(beliefs)}):"]
    for belief in beliefs:
        lines.append(_format_belief(belief))
    return "\n".join(lines)


@mcp.tool
def onboard(project_path: str) -> str:
    """Onboard a project by scanning its directory for signals.

    Detects available signals (git history, docs, source code, directives,
    citations) and extracts content into observations and beliefs.

    Point this at a project root directory to populate the memory store
    with the project's knowledge graph. No LLM cost -- uses offline
    classification for bulk ingestion.
    """
    path: Path = Path(project_path).expanduser().resolve()
    if not path.is_dir():
        return f"Not a directory: {path}"

    # Scan the project
    scan: ScanResult = scan_project(path)

    # Feed extracted nodes through the ingest pipeline
    store: MemoryStore = _get_store()
    aggregate: IngestResult = IngestResult()

    for node in scan.nodes:
        # Skip file nodes (structural only, not meaningful text)
        if node.node_type == "file":
            continue

        # Determine source type from node type
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

    # Build summary
    node_types: dict[str, int] = {}
    for n in scan.nodes:
        node_types[n.node_type] = node_types.get(n.node_type, 0) + 1

    edge_types: dict[str, int] = {}
    for e in scan.edges:
        edge_types[e.edge_type] = edge_types.get(e.edge_type, 0) + 1

    lines: list[str] = [
        f"Onboarded project: {scan.manifest.name}",
        f"  Signals: git={scan.manifest.has_git}, "
        f"docs={scan.manifest.doc_count}, "
        f"languages={scan.manifest.languages}",
        f"  Nodes extracted: {len(scan.nodes)}",
    ]
    for ntype, count in sorted(node_types.items()):
        lines.append(f"    {ntype}: {count}")
    lines.append(f"  Edges extracted: {len(scan.edges)}")
    for etype, count in sorted(edge_types.items()):
        lines.append(f"    {etype}: {count}")
    lines.append(f"  Observations created: {aggregate.observations_created}")
    lines.append(f"  Beliefs created: {aggregate.beliefs_created}")
    lines.append(f"  Corrections detected: {aggregate.corrections_detected}")

    timing_parts: list[str] = [
        f"{k}={v:.2f}s" for k, v in scan.timings.items()
    ]
    lines.append(f"  Timing: {', '.join(timing_parts)}")

    return "\n".join(lines)


@mcp.tool
def ingest(text: str, source: str = "user") -> str:
    """Ingest a conversation turn through the full pipeline.

    Extracts sentences, detects corrections, classifies content types,
    and creates observations + beliefs with appropriate Bayesian priors.
    Corrections become locked beliefs automatically.

    Use source='user' for user messages, source='assistant' for agent messages.
    """
    store: MemoryStore = _get_store()
    result: IngestResult = ingest_turn(store, text, source, use_llm=False)

    return (
        f"Ingested {source} turn:\n"
        f"  Observations: {result.observations_created}\n"
        f"  Beliefs: {result.beliefs_created}\n"
        f"  Corrections: {result.corrections_detected}\n"
        f"  Sentences: {result.sentences_extracted} extracted, "
        f"{result.sentences_persisted} persisted"
    )


@mcp.tool
def commit_check(project_dir: str = ".") -> str:
    """Check time since last git commit and number of uncommitted changes.

    Returns a nudge message if either threshold is exceeded, or a quiet
    status summary if everything is within bounds. Deterministic -- no LLM
    involved in the check logic.

    Configure thresholds with commit_config tool.
    """
    result: CommitCheckResult = check_commit_status(Path(project_dir))
    return format_status(result)


@mcp.tool
def commit_config(
    enabled: bool | None = None,
    max_minutes: int | None = None,
    max_changes: int | None = None,
) -> str:
    """View or update commit tracker configuration.

    Call with no arguments to view current config.
    Pass any combination of parameters to update.

    Args:
        enabled: Turn commit tracking on or off.
        max_minutes: Minutes before nudging to commit (default 15).
        max_changes: Number of uncommitted changes before nudging (default 10).
    """
    config: CommitTrackerConfig = load_commit_config()

    if enabled is None and max_minutes is None and max_changes is None:
        return (
            f"Commit tracker config:\n"
            f"  enabled: {config.enabled}\n"
            f"  max_minutes: {config.max_seconds // 60}\n"
            f"  max_changes: {config.max_changes}\n"
            f"  config file: {Path.home() / '.agentmemory' / 'commit_tracker.json'}"
        )

    if enabled is not None:
        config.enabled = enabled
    if max_minutes is not None:
        config.max_seconds = max_minutes * 60
    if max_changes is not None:
        config.max_changes = max_changes

    path: Path = save_commit_config(config)
    return (
        f"Commit tracker config updated ({path}):\n"
        f"  enabled: {config.enabled}\n"
        f"  max_minutes: {config.max_seconds // 60}\n"
        f"  max_changes: {config.max_changes}"
    )


if __name__ == "__main__":
    mcp.run()
