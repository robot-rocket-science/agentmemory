"""MCP server for agentmemory, exposing memory tools via FastMCP.

Provides search, remember, correct, observe, status, and get_locked tools.
Uses a single lazily-initialized MemoryStore backed by ~/.agentmemory/memory.db.
"""
from __future__ import annotations

from pathlib import Path

import os

from fastmcp import FastMCP

from agentmemory.config import get_bool_setting
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
    Session,
)
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore

# ---------------------------------------------------------------------------
# Store singleton + session tracking
# ---------------------------------------------------------------------------

_store: MemoryStore | None = None
_session_id: str | None = None


def _resolve_server_db() -> Path:
    """Resolve DB path for the MCP server: AGENTMEMORY_DB env > cwd-based isolation."""
    import hashlib
    import os
    env_db: str | None = os.environ.get("AGENTMEMORY_DB")
    if env_db:
        p: Path = Path(env_db)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    # Per-project: hash of cwd
    home: Path = Path.home() / ".agentmemory"
    abs_path: str = str(Path.cwd().resolve())
    path_hash: str = hashlib.sha256(abs_path.encode()).hexdigest()[:12]
    db_dir: Path = home / "projects" / path_hash
    db_dir.mkdir(parents=True, exist_ok=True)
    meta_path: Path = db_dir / "project.txt"
    if not meta_path.exists():
        meta_path.write_text(abs_path + "\n", encoding="utf-8")
    return db_dir / "memory.db"


def _get_store() -> MemoryStore:
    """Return the module-level MemoryStore, creating it on first call."""
    global _store
    if _store is None:
        db_path: Path = _resolve_server_db()
        _store = MemoryStore(db_path)
    return _store


def _set_store(store: MemoryStore) -> None:  # pyright: ignore[reportUnusedFunction]
    """Override the module-level store. Used by tests."""
    global _store, _session_id
    _store = store
    _session_id = None


def _ensure_session() -> str:
    """Return the current session ID, creating a new session if needed."""
    global _session_id
    if _session_id is None:
        store: MemoryStore = _get_store()
        session: Session = store.create_session()
        _session_id = session.id
    return _session_id


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
    session_id: str = _ensure_session()
    result: RetrievalResult = retrieve(store, query, budget=budget)

    store.increment_session_metrics(
        session_id,
        retrieval_tokens=result.total_tokens,
        searches_performed=1,
    )

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
    """Create a locked, high-confidence belief from a user statement.

    Sets source_type='user_stated', alpha=9.0, beta_param=0.5, locked=True.
    User-stated beliefs are permanent constraints that persist across sessions.
    Returns confirmation with belief ID.
    """
    store: MemoryStore = _get_store()
    session_id: str = _ensure_session()
    belief: Belief = store.insert_belief(
        content=text,
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )
    store.checkpoint(session_id, "remember", belief.content, [belief.id])
    store.increment_session_metrics(session_id, beliefs_created=1)
    return (
        f"Remembered (ID: {belief.id}): {belief.content} "
        f"[confidence: {belief.confidence:.0%}, locked: {belief.locked}]"
    )


@mcp.tool
def correct(text: str, replaces: str | None = None) -> str:
    """Record a user correction as a locked belief.

    Creates a locked, high-confidence belief with source_type='user_corrected'.
    Corrections are permanent constraints that persist across sessions.
    If replaces is provided (a search query), finds the best matching
    existing belief and supersedes it.
    """
    store: MemoryStore = _get_store()
    session_id: str = _ensure_session()
    belief: Belief = store.insert_belief(
        content=text,
        belief_type=BELIEF_CORRECTION,
        source_type=BSRC_USER_CORRECTED,
        alpha=9.0,
        beta_param=0.5,
        locked=True,
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

    store.checkpoint(session_id, "correct", belief.content, [belief.id])
    store.increment_session_metrics(
        session_id, beliefs_created=1, corrections_detected=1,
    )
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
    session_id: str = _ensure_session()
    obs: Observation = store.insert_observation(
        content=text,
        observation_type=OBS_TYPE_USER_STATEMENT,
        source_type=source,
        source_id=source,
        session_id=session_id,
    )
    return f"Observation recorded (ID: {obs.id}): {obs.content}"


@mcp.tool
def status() -> str:
    """Return memory system status.

    Reports counts of observations, beliefs, locked beliefs, superseded
    beliefs, edges, and sessions. Includes current session token metrics.
    """
    store: MemoryStore = _get_store()
    counts: dict[str, int] = store.status()
    lines: list[str] = ["Memory system status:"]
    for key, value in counts.items():
        lines.append(f"  {key}: {value}")

    # Current session metrics
    if _session_id is not None:
        session: Session | None = store.get_session(_session_id)
        if session is not None:
            lines.append("Current session:")
            lines.append(f"  retrieval_tokens: {session.retrieval_tokens}")
            lines.append(f"  classification_tokens: {session.classification_tokens}")
            lines.append(f"  beliefs_created: {session.beliefs_created}")
            lines.append(f"  corrections_detected: {session.corrections_detected}")
            lines.append(f"  searches_performed: {session.searches_performed}")

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
            created_at=node.date,
        )
        aggregate.merge(turn_result)

    # Store structural edges for HRR graph encoding
    for edge in scan.edges:
        store.insert_graph_edge(
            from_id=edge.src,
            to_id=edge.tgt,
            edge_type=edge.edge_type,
            weight=edge.weight,
            reason="scanner",
        )

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
    session_id: str = _ensure_session()
    use_llm: bool = get_bool_setting("ingest", "use_llm")
    # LLM classification requires ANTHROPIC_API_KEY
    if use_llm and not os.environ.get("ANTHROPIC_API_KEY"):
        use_llm = False
    result: IngestResult = ingest_turn(store, text, source, session_id=session_id, use_llm=use_llm)

    # Estimate classification tokens: ~50 tokens/sentence for Haiku prompt+response
    est_classification_tokens: int = result.sentences_extracted * 50 if use_llm else 0
    store.increment_session_metrics(
        session_id,
        classification_tokens=est_classification_tokens,
        beliefs_created=result.beliefs_created,
        corrections_detected=result.corrections_detected,
    )

    classifier: str = "haiku" if use_llm else "offline"
    return (
        f"Ingested {source} turn ({classifier} classifier):\n"
        f"  Observations: {result.observations_created}\n"
        f"  Beliefs: {result.beliefs_created}\n"
        f"  Corrections: {result.corrections_detected}\n"
        f"  Sentences: {result.sentences_extracted} extracted, "
        f"{result.sentences_persisted} persisted"
    )


if __name__ == "__main__":
    mcp.run()
