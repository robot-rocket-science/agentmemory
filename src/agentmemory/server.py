"""MCP server for agentmemory, exposing memory tools via FastMCP.

Provides search, remember, correct, observe, status, and get_locked tools.
Uses a single lazily-initialized MemoryStore backed by ~/.agentmemory/memory.db.
"""
from __future__ import annotations

import atexit
import re
from datetime import datetime, timezone
from pathlib import Path

from fastmcp import FastMCP

from agentmemory.classification import (
    BATCH_SIZE,
    ClassifiedSentence,
    TYPE_PRIORS,
)
from agentmemory.ingest import (
    ExtractedTurn,
    IngestResult,
    create_beliefs_from_classified,
    extract_turn,
    ingest_turn,
)
from agentmemory.scanner import ScanResult, scan_project
from agentmemory.models import (
    BSRC_USER_CORRECTED,
    BSRC_USER_STATED,
    BELIEF_FACTUAL,
    BELIEF_CORRECTION,
    LAYER_EXPLICIT,
    LAYER_IMPLICIT,
    OBS_TYPE_USER_STATEMENT,
    OUTCOME_HARMFUL,
    OUTCOME_IGNORED,
    OUTCOME_USED,
    Belief,
    Observation,
    Session,
    TestResult,
)
from agentmemory.relationship_detector import detect_relationships
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore

# ---------------------------------------------------------------------------
# Store singleton + session tracking
# ---------------------------------------------------------------------------

_store: MemoryStore | None = None
_session_id: str | None = None

# Retrieval tracking: maps session_id -> list of (belief_id, timestamp) tuples.
# Populated by search(), consumed by feedback() and auto-feedback.
_retrieval_buffer: dict[str, list[tuple[str, str]]] = {}

# Ingest buffer: text ingested since the last auto-feedback processing.
# Populated by ingest(), consumed by _process_auto_feedback().
_ingest_buffer: list[str] = []

# Belief IDs that already received explicit feedback this session.
# Auto-feedback skips these (explicit always wins).
_explicit_feedback_ids: set[str] = set()

# TB-13: Count locked belief accesses for audit trail.
_locked_access_count: int = 0

# ---------------------------------------------------------------------------
# Auto-feedback: key-term extraction and matching
# ---------------------------------------------------------------------------

_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "of", "in", "to",
    "for", "with", "on", "at", "by", "from", "as", "into", "through",
    "that", "this", "these", "those", "it", "its", "not", "no", "all",
    "and", "or", "but", "if", "then", "than", "when", "where", "how",
    "what", "which", "who", "whom", "use", "using", "used",
})

# Minimum unique term matches to infer "used". From validation experiments:
# min_unique=2 gives 100% precision, 75% recall on realistic scenarios.
_AUTO_FEEDBACK_MIN_MATCHES: int = 2


def _extract_key_terms(text: str) -> list[str]:
    """Extract meaningful terms from text, filtering stopwords."""
    words: list[str] = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return [w for w in words if w not in _STOPWORDS and len(w) >= 2]


def _process_auto_feedback(session_id: str) -> int:
    """Process the previous retrieval batch: infer used/ignored from ingested text.

    Returns the number of auto-feedback events recorded.
    """
    global _ingest_buffer

    buffer: list[tuple[str, str]] | None = _retrieval_buffer.pop(session_id, None)
    if not buffer:
        return 0

    # Combine all ingested text since the retrieval
    combined_ingested: str = " ".join(_ingest_buffer).lower()
    _ingest_buffer = []

    if not combined_ingested.strip():
        # No ingested text -- everything is "ignored"
        store: MemoryStore = _get_store()
        count: int = 0
        for belief_id, _ts in buffer:
            if belief_id in _explicit_feedback_ids:
                continue
            store.record_test_result(
                belief_id=belief_id,
                session_id=session_id,
                outcome=OUTCOME_IGNORED,
                detection_layer=LAYER_IMPLICIT,
                outcome_detail="auto: no ingested text since retrieval",
            )
            count += 1
        if count > 0:
            store.increment_session_metrics(session_id, feedback_given=count)
        return count

    store = _get_store()
    count = 0
    for belief_id, _ts in buffer:
        if belief_id in _explicit_feedback_ids:
            continue

        belief: Belief | None = store.get_belief(belief_id)
        if belief is None:
            continue

        # Key-term overlap check
        terms: list[str] = _extract_key_terms(belief.content)
        if not terms:
            continue

        unique_terms: set[str] = set(terms)
        unique_matches: int = sum(1 for t in unique_terms if t in combined_ingested)

        outcome: str = OUTCOME_USED if unique_matches >= _AUTO_FEEDBACK_MIN_MATCHES else OUTCOME_IGNORED
        detail: str = (
            f"auto: {unique_matches}/{len(unique_terms)} key terms matched"
        )

        store.record_test_result(
            belief_id=belief_id,
            session_id=session_id,
            outcome=outcome,
            detection_layer=LAYER_IMPLICIT,
            outcome_detail=detail,
        )
        count += 1

    if count > 0:
        store.increment_session_metrics(session_id, feedback_given=count)
    return count


def _flush_feedback_on_exit() -> None:
    """Flush the last retrieval batch's auto-feedback when the server exits.

    Without this, the final search()'s retrieved beliefs never get feedback
    because no subsequent search() or ingest() triggers processing.
    """
    if _session_id is not None:
        _process_auto_feedback(_session_id)


atexit.register(_flush_feedback_on_exit)


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
    global _store, _session_id, _ingest_buffer
    _store = store
    _session_id = None
    _retrieval_buffer.clear()
    _ingest_buffer = []
    _explicit_feedback_ids.clear()


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

    # Process auto-feedback for the previous retrieval batch before this search
    _process_auto_feedback(session_id)

    result: RetrievalResult = retrieve(store, query, budget=budget)

    store.increment_session_metrics(
        session_id,
        retrieval_tokens=result.total_tokens,
        searches_performed=1,
    )

    if not result.beliefs:
        return (
            "No beliefs found matching your query. "
            "This may be a knowledge gap. Consider asking the user for context, "
            "or use observe() to record new information."
        )

    # Track which beliefs were retrieved for feedback loop
    ts: str = datetime.now(timezone.utc).isoformat()
    if session_id not in _retrieval_buffer:
        _retrieval_buffer[session_id] = []
    for belief in result.beliefs:
        _retrieval_buffer[session_id].append((belief.id, ts))
        # Persist to DB so feedback survives session crashes
        store.insert_pending_feedback(
            belief_id=belief.id,
            belief_content=belief.content,
            session_id=session_id,
        )

    lines: list[str] = [
        f"Found {len(result.beliefs)} belief(s) ({result.total_tokens} tokens, "
        f"{result.budget_remaining} remaining):"
    ]
    for belief in result.beliefs:
        score: float | None = result.scores.get(belief.id)
        lines.append(_format_belief(belief, score))

    # Append contradiction warnings if any (REQ-002)
    if result.contradiction_warnings:
        lines.append("")
        for warning in result.contradiction_warnings:
            lines.append(f"WARNING: {warning}")

    return "\n".join(lines)


@mcp.tool
def remember(text: str) -> str:
    """Create a high-confidence belief from a user statement.

    Sets source_type='user_stated', alpha=9.0, beta_param=0.5, locked=False.
    The belief is NOT locked until the user explicitly confirms via lock().
    Returns belief ID and prompts for user confirmation before locking.
    """
    store: MemoryStore = _get_store()
    session_id: str = _ensure_session()
    belief: Belief = store.insert_belief(
        content=text,
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
        locked=False,
        classified_by="user",
    )
    detect_relationships(store, belief)
    store.checkpoint(session_id, "remember", belief.content, [belief.id])
    store.increment_session_metrics(session_id, beliefs_created=1)
    return (
        f"Remembered (ID: {belief.id}): {belief.content} "
        f"[confidence: {belief.confidence:.0%}, locked: False] "
        f"Ask the user: 'Lock this as a permanent belief? "
        f"lock({belief.id})'"
    )


@mcp.tool
def correct(text: str, replaces: str | None = None) -> str:
    """Record a user correction as a high-confidence belief.

    Creates a high-confidence belief with source_type='user_corrected'.
    The belief is NOT locked until the user explicitly confirms via lock().
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
        locked=False,
        classified_by="user",
    )
    detect_relationships(store, belief)

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
        f"[confidence: {belief.confidence:.0%}, locked: False]."
        f"{superseded_msg} "
        f"Ask the user: 'Lock this as a permanent correction? "
        f"lock({belief.id})'"
    )


@mcp.tool
def lock(belief_id: str) -> str:
    """Lock a belief as a permanent constraint.

    Only call this AFTER the user has explicitly confirmed they want the
    belief locked. Locked beliefs persist across all sessions, cannot have
    their confidence reduced, and are injected into every session context.

    Returns confirmation or error if belief not found.
    """
    store: MemoryStore = _get_store()
    session_id: str = _ensure_session()
    belief: Belief | None = store.get_belief(belief_id)
    if belief is None:
        return f"Error: no belief found with ID {belief_id}"
    if belief.locked:
        return (
            f"Already locked (ID: {belief.id}): {belief.content} "
            f"[confidence: {belief.confidence:.0%}]"
        )
    store.lock_belief(belief_id)
    store.checkpoint(session_id, "lock", belief.content, [belief.id])
    return (
        f"Locked (ID: {belief.id}): {belief.content} "
        f"[confidence: {belief.confidence:.0%}, locked: True]"
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

    Reports inventory (counts by type/source/locked), retrieval pipeline
    status, activity metrics, and actionable maintenance items.
    """
    store: MemoryStore = _get_store()
    report: dict[str, object] = store.get_status_report()
    inv: dict[str, object] = report["inventory"]  # type: ignore[assignment]
    ret: dict[str, object] = report["retrieval"]  # type: ignore[assignment]
    act: dict[str, object] = report["activity"]  # type: ignore[assignment]
    maint: dict[str, object] = report["maintenance"]  # type: ignore[assignment]

    lines: list[str] = []

    # --- Inventory ---
    lines.append("Inventory:")
    lines.append(f"  {inv['active']} active beliefs ({inv['superseded']} superseded)")
    by_type: dict[str, int] = inv["by_type"]  # type: ignore[assignment]
    if by_type:
        type_parts: list[str] = [f"{c} {t}" for t, c in by_type.items()]
        lines.append(f"  By type: {', '.join(type_parts)}")
    by_source: dict[str, int] = inv["by_source"]  # type: ignore[assignment]
    if by_source:
        active_total: int = int(inv["active"])  # type: ignore[arg-type]
        src_parts: list[str] = []
        for src, cnt in by_source.items():
            pct: float = cnt / active_total * 100 if active_total > 0 else 0.0
            src_parts.append(f"{cnt} {src} ({pct:.0f}%)")
        lines.append(f"  By source: {', '.join(src_parts)}")
    locked_by_type: dict[str, int] = inv["locked_by_type"]  # type: ignore[assignment]
    if locked_by_type:
        lock_parts: list[str] = [f"{c} {t}" for t, c in locked_by_type.items()]
        lines.append(f"  Locked: {inv['locked']} ({', '.join(lock_parts)})")
    elif int(inv["locked"]) > 0:  # type: ignore[arg-type]
        lines.append(f"  Locked: {inv['locked']}")

    # --- Retrieval ---
    lines.append("Retrieval:")
    total_active: int = int(ret["total_active"])  # type: ignore[arg-type]
    retrieved: int = int(ret["retrieved_once"])  # type: ignore[arg-type]
    ret_pct: float = retrieved / total_active * 100 if total_active > 0 else 0.0
    lines.append(f"  {ret_pct:.0f}% retrieved at least once ({retrieved}/{total_active})")
    features: list[str] = ret["scoring_features"]  # type: ignore[assignment]
    lines.append(f"  Scoring: {' + '.join(features)}")
    pending: int = int(ret["pending_feedback"])  # type: ignore[arg-type]
    if pending > 0:
        lines.append(f"  Pending feedback: {pending}")

    # --- Current session ---
    if _session_id is not None:
        session: Session | None = store.get_session(_session_id)
        if session is not None:
            lines.append("Session:")
            lines.append(
                f"  beliefs: {session.beliefs_created}, "
                f"corrections: {session.corrections_detected}, "
                f"searches: {session.searches_performed}"
            )

    # --- Activity ---
    lines.append("Activity:")
    lines.append(f"  {act['sessions']} sessions, {act['observations']} observations")
    age_dist: dict[str, int] = act["age_distribution"]  # type: ignore[assignment]
    if age_dist:
        age_parts: list[str] = [f"{c} {bucket}" for bucket, c in age_dist.items()]
        lines.append(f"  Age: {', '.join(age_parts)}")
    last_velocity: Session | None = store.get_last_completed_session()
    if last_velocity is not None and last_velocity.velocity_tier is not None:
        lines.append(
            f"  Last session: {last_velocity.velocity_tier} "
            f"({last_velocity.velocity_items_per_hour:.1f} items/hr)"
        )

    # --- Rigor (REQ-026: calibrated status reporting) ---
    rigor_dist: dict[str, int] = store.get_rigor_distribution()
    if rigor_dist:
        active_total_r: int = sum(rigor_dist.values())
        lines.append("Rigor:")
        rigor_parts: list[str] = [
            f"{cnt} {tier} ({cnt / active_total_r * 100:.0f}%)"
            for tier, cnt in rigor_dist.items()
        ]
        lines.append(f"  {', '.join(rigor_parts)}")
        # Confidence caveat when most findings are below "validated" tier
        validated_count: int = rigor_dist.get("validated", 0)
        empirical_count: int = rigor_dist.get("empirically_tested", 0)
        strong_count: int = validated_count + empirical_count
        strong_pct: float = strong_count / active_total_r * 100 if active_total_r > 0 else 0.0
        if strong_pct < 20.0:
            lines.append(
                f"  Caveat: {strong_pct:.0f}% of beliefs are empirically tested or validated. "
                "Most findings are hypothesis-tier; treat with appropriate skepticism."
            )
        elif strong_pct < 50.0:
            lines.append(
                f"  Note: {strong_pct:.0f}% of beliefs are empirically tested or validated."
            )

    # --- Maintenance (actionable) ---
    stale: int = int(maint["stale_count"])  # type: ignore[arg-type]
    orphan: int = int(maint["orphan_count"])  # type: ignore[arg-type]
    credal: int = int(maint["credal_gap_count"])  # type: ignore[arg-type]
    if stale > 0 or orphan > 0 or credal > 0:
        lines.append("Maintenance:")
        if stale > 0:
            lines.append(f"  Stale (>30d unretrieved): {stale}")
        if orphan > 0:
            lines.append(f"  Orphans (no edges): {orphan} ({maint['orphan_pct']}%)")
        if credal > 0:
            lines.append(f"  Never updated (at type prior): {credal} ({maint['credal_gap_pct']}%)")

    return "\n".join(lines)


@mcp.tool
def get_locked() -> str:
    """Return all locked beliefs formatted for context injection.

    This is what the SessionStart hook calls to load persistent beliefs
    into the agent's active context.
    """
    global _locked_access_count
    _locked_access_count += 1

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

    Extracts content into observations and returns sentences for LLM
    classification. Does NOT create beliefs -- the calling agent should:
    1. Parse the returned sentences JSON
    2. Spawn Haiku subagents to classify batches of 20
    3. Call create_beliefs() with the classification results

    This separation ensures beliefs are created with LLM-quality types
    and priors from the start, rather than relying on offline heuristics.
    """
    import json as _json

    path: Path = Path(project_path).expanduser().resolve()
    if not path.is_dir():
        return f"Not a directory: {path}"

    # Check for incremental onboarding: use last onboard commit if available
    store_pre: MemoryStore = _get_store()
    last_run: dict[str, str] | None = store_pre.get_last_onboarding(str(path))
    since_commit: str | None = None
    if last_run is not None and last_run.get("commit_hash"):
        since_commit = last_run["commit_hash"]

    # Scan the project (incremental if since_commit is set)
    scan: ScanResult = scan_project(path, since_commit=since_commit)

    # Extract observations and sentences (no beliefs)
    store: MemoryStore = _get_store()
    observations_created: int = 0
    all_sentences: list[dict[str, str]] = []

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

        extracted: ExtractedTurn = extract_turn(
            store=store,
            text=node.content,
            source=source,
            session_id=None,
            created_at=node.date,
            source_path=node.file or "",
        )
        observations_created += 1

        for text, src in extracted.sentences:
            all_sentences.append({
                "text": text,
                "source": src,
                "observation_id": extracted.observation.id,
                "created_at": node.date or "",
                "is_correction": str(extracted.full_text_is_correction),
                "full_text": node.content,
            })

    # Store structural edges for HRR graph encoding
    for edge in scan.edges:
        store.insert_graph_edge(
            from_id=edge.src,
            to_id=edge.tgt,
            edge_type=edge.edge_type,
            weight=edge.weight,
            reason="scanner",
        )

    # Record onboarding provenance
    import subprocess
    commit_hash: str | None = None
    try:
        commit_hash = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(path),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        pass
    store.record_onboarding_run(
        project_path=str(path),
        commit_hash=commit_hash,
        nodes_extracted=len(scan.nodes),
        edges_extracted=len(scan.edges),
        beliefs_created=0,  # Beliefs created later via create_beliefs()
        observations_created=observations_created,
    )

    # Build summary
    node_types: dict[str, int] = {}
    for n in scan.nodes:
        node_types[n.node_type] = node_types.get(n.node_type, 0) + 1

    edge_types: dict[str, int] = {}
    for e in scan.edges:
        edge_types[e.edge_type] = edge_types.get(e.edge_type, 0) + 1

    mode: str = f"incremental (since {since_commit[:12]})" if since_commit else "full"
    lines: list[str] = [
        f"Onboarded project: {scan.manifest.name} [{mode}]",
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
    lines.append(f"  Observations created: {observations_created}")
    lines.append(f"  Sentences for classification: {len(all_sentences)}")

    timing_parts: list[str] = [
        f"{k}={v:.2f}s" for k, v in scan.timings.items()
    ]
    lines.append(f"  Timing: {', '.join(timing_parts)}")
    if commit_hash:
        lines.append(f"  Git HEAD at onboard: {commit_hash[:12]}")

    summary: str = "\n".join(lines)

    if not all_sentences:
        return summary + "\n\nNo sentences to classify."

    lines.append(f"\n  Batch size: {BATCH_SIZE} sentences per subagent")
    lines.append(f"  Estimated batches: {(len(all_sentences) + BATCH_SIZE - 1) // BATCH_SIZE}")
    lines.append("")
    lines.append("SENTENCES_JSON_START")
    lines.append(_json.dumps(all_sentences))
    lines.append("SENTENCES_JSON_END")

    return "\n".join(lines)


@mcp.tool
def create_beliefs(classified_json: str) -> str:
    """Create beliefs from LLM-classified sentences.

    Accepts a JSON string: [{"text": "...", "source": "user", "observation_id": "...",
    "type": "REQUIREMENT", "persist": "PERSIST", "created_at": "", "is_correction": "False",
    "full_text": "..."}]

    This is the second phase of the onboard pipeline:
    1. onboard() extracts observations and returns sentences
    2. The calling agent classifies via Haiku subagents
    3. create_beliefs() stores the results with correct types and priors

    Each item must have at minimum: text, source, observation_id, type, persist.
    Optional: author (USER/AGENT/UNKNOWN) -- agent-authored content gets lower priors.
    CORRECTION type is remapped to FACT (corrections are a live-conversation concept).
    """
    import json as _json

    store: MemoryStore = _get_store()
    items: list[dict[str, str]] = _json.loads(classified_json)

    total_created: int = 0
    total_skipped: int = 0

    # Group by observation_id for efficient processing
    by_obs: dict[str, list[dict[str, str]]] = {}
    for item in items:
        obs_id: str = item.get("observation_id", "")
        if obs_id not in by_obs:
            by_obs[obs_id] = []
        by_obs[obs_id].append(item)

    for obs_id, obs_items in by_obs.items():
        obs = store.get_observation(obs_id) if obs_id else None
        if obs is None:
            total_skipped += len(obs_items)
            continue

        classified: list[ClassifiedSentence] = []
        source: str = obs_items[0].get("source", "document")
        full_text: str = obs_items[0].get("full_text", "")
        created_at: str | None = obs_items[0].get("created_at") or None

        for item in obs_items:
            sentence_type: str = item.get("type", "FACT").upper()
            persist_label: str = item.get("persist", "PERSIST").upper()
            author: str = item.get("author", "UNKNOWN").upper()

            # Remap CORRECTION to FACT for onboard path
            if sentence_type == "CORRECTION":
                sentence_type = "FACT"

            prior: tuple[float, float] | None = TYPE_PRIORS.get(sentence_type)
            should_persist: bool = persist_label == "PERSIST" and prior is not None

            alpha: float = 2.0
            beta_val: float = 1.0
            if prior is not None:
                alpha, beta_val = prior

            # Agent-authored content gets lower priors
            if author == "AGENT" and should_persist:
                alpha = max(alpha * 0.5, 1.0)

            classified.append(ClassifiedSentence(
                text=item.get("text", ""),
                source=item.get("source", "document"),
                persist=should_persist,
                sentence_type=sentence_type,
                alpha=alpha,
                beta_param=beta_val,
                author=author,
            ))

        result: IngestResult = create_beliefs_from_classified(
            store=store,
            observation=obs,
            classified=classified,
            source=source,
            full_text_is_correction=False,
            full_text=full_text,
            created_at=created_at,
            classified_by="llm",
        )
        total_created += result.beliefs_created

    return (
        f"Created {total_created} belief(s) from {len(items)} classified sentence(s).\n"
        f"Skipped: {total_skipped} (missing observation)"
    )


@mcp.tool
def get_unclassified(limit: int = 200) -> str:
    """Return beliefs that were classified offline and may benefit from LLM reclassification.

    Returns belief IDs, content, current type, and source for beliefs created
    by the offline classifier. These can be batched and sent to Haiku subagents
    using build_classification_prompt(), then fed back via reclassify().

    The caller (a Claude Code skill) should:
    1. Call get_unclassified() to get the batch
    2. Group sentences into batches of 20
    3. Spawn Haiku subagents with the classification prompt for each batch
    4. Call reclassify() with the results
    """
    store: MemoryStore = _get_store()
    rows: list[dict[str, str]] = store.get_reclassifiable(limit)

    if not rows:
        return "No beliefs available for reclassification."

    lines: list[str] = [
        f"Found {len(rows)} belief(s) for reclassification.",
        f"Batch size: {BATCH_SIZE} sentences per subagent.",
        "",
    ]
    for r in rows:
        lines.append(f"[{r['id']}] ({r['type']}) {r['content']}")

    return "\n".join(lines)


@mcp.tool
def reclassify(mappings: str) -> str:
    """Apply LLM classification results to existing beliefs.

    Accepts a JSON string: [{"id": "belief_id", "type": "REQUIREMENT", "persist": "PERSIST"}, ...]

    For each mapping:
    - Updates belief_type based on the LLM classification
    - Updates alpha/beta priors from TYPE_PRIORS
    - Beliefs classified as EPHEMERAL (persist=false) are soft-deleted (valid_to set)

    This is the receiving end of subagent-based classification. The calling agent
    spawns Haiku subagents to classify batches, then feeds results here.
    """
    import json as _json

    store: MemoryStore = _get_store()
    items: list[dict[str, str]] = _json.loads(mappings)

    # Map from classification type to belief_type
    type_to_belief: dict[str, str] = {
        "REQUIREMENT": "requirement",
        "CORRECTION": "correction",
        "PREFERENCE": "preference",
        "FACT": "factual",
        "ASSUMPTION": "factual",
        "DECISION": "factual",
        "ANALYSIS": "factual",
        "COORDINATION": "factual",
        "QUESTION": "factual",
        "META": "factual",
    }

    updated: int = 0
    soft_deleted: int = 0
    skipped: int = 0

    for item in items:
        belief_id: str = item.get("id", "")
        sentence_type: str = item.get("type", "FACT").upper()
        persist_label: str = item.get("persist", "PERSIST").upper()

        belief: Belief | None = store.get_belief(belief_id)
        if belief is None:
            skipped += 1
            continue

        # Skip locked beliefs
        if belief.locked:
            skipped += 1
            continue

        prior: tuple[float, float] | None = TYPE_PRIORS.get(sentence_type)
        should_persist: bool = persist_label == "PERSIST" and prior is not None

        if not should_persist:
            store.soft_delete_belief(belief_id)
            soft_deleted += 1
        else:
            new_type: str = type_to_belief.get(sentence_type, "factual")
            alpha: float
            beta_val: float
            assert prior is not None  # guarded by should_persist check
            alpha, beta_val = prior
            store.update_belief_classification(
                belief_id, new_type, alpha, beta_val,
            )
            updated += 1

    return (
        f"Reclassification complete:\n"
        f"  Updated: {updated}\n"
        f"  Soft-deleted (EPHEMERAL): {soft_deleted}\n"
        f"  Skipped (locked/missing): {skipped}"
    )


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
    result: IngestResult = ingest_turn(store, text, source, session_id=session_id)

    # Feed ingested text into the auto-feedback buffer, then process.
    # Processing after append ensures the ingested text (agent's response to
    # previous search results) is included in the key-term matching.
    _ingest_buffer.append(text)
    auto_fb: int = _process_auto_feedback(session_id)

    store.increment_session_metrics(
        session_id,
        classification_tokens=0,
        beliefs_created=result.beliefs_created,
        corrections_detected=result.corrections_detected,
    )

    fb_msg: str = f"\n  Auto-feedback: {auto_fb} belief(s) scored" if auto_fb > 0 else ""
    reclass_msg: str = ""
    if result.beliefs_created > 0:
        reclass_msg = (
            f"\n  NOTE: {result.beliefs_created} belief(s) classified offline (36% accuracy). "
            f"Call get_unclassified() + reclassify() for LLM accuracy."
        )
    return (
        f"Ingested {source} turn (offline classifier):\n"
        f"  Observations: {result.observations_created}\n"
        f"  Beliefs: {result.beliefs_created}\n"
        f"  Corrections: {result.corrections_detected}\n"
        f"  Sentences: {result.sentences_extracted} extracted, "
        f"{result.sentences_persisted} persisted{fb_msg}{reclass_msg}"
    )


@mcp.tool
def timeline(
    topic: str | None = None,
    start: str | None = None,
    end: str | None = None,
    session_id: str | None = None,
    limit: int = 50,
) -> str:
    """Return beliefs ordered by time, filtered by topic and/or time range.

    Use cases:
      timeline(topic="deployment") -- all deployment beliefs chronologically
      timeline(start="-7d") -- everything from the last 7 days
      timeline(session_id="abc123") -- replay session abc123
      timeline(topic="capital", start="2026-03-25", end="2026-03-28")

    start/end accept ISO 8601 timestamps or relative offsets: "-7d", "-24h", "-30m".
    """
    store: MemoryStore = _get_store()
    resolved_start: str | None = _resolve_relative_time(start) if start else None
    resolved_end: str | None = _resolve_relative_time(end) if end else None
    beliefs: list[Belief] = store.timeline(
        topic=topic, start=resolved_start, end=resolved_end,
        session_id=session_id, limit=limit,
    )
    if not beliefs:
        return "No beliefs found for the given time/topic filter."
    lines: list[str] = [f"Timeline: {len(beliefs)} belief(s)"]
    for b in beliefs:
        status: str = " [SUPERSEDED]" if b.valid_to else ""
        lock: str = " [LOCKED]" if b.locked else ""
        lines.append(
            f"  [{b.created_at}] ({b.belief_type}){lock}{status} {b.content[:200]}"
        )
    return "\n".join(lines)


@mcp.tool
def evolution(
    belief_id: str | None = None,
    topic: str | None = None,
) -> str:
    """Trace how a belief or topic evolved over time.

    Two modes:
    1. belief_id: follow the SUPERSEDES chain in both directions.
       Shows: original -> correction 1 -> correction 2 -> current.
    2. topic: FTS5 search + time ordering. Shows all beliefs about
       the topic chronologically, marking which ones superseded others.

    Use cases:
      evolution(belief_id="a1b2c3d4e5f6") -- full chain for this belief
      evolution(topic="dispatch gate") -- how dispatch gate policy evolved
    """
    if not belief_id and not topic:
        return "Error: provide either belief_id or topic."
    store: MemoryStore = _get_store()
    beliefs: list[Belief] = store.evolution(belief_id=belief_id, topic=topic)
    if not beliefs:
        return "No evolution chain found."
    lines: list[str] = [f"Evolution: {len(beliefs)} belief(s)"]
    for i, b in enumerate(beliefs):
        marker: str = "->" if i > 0 else "  "
        status: str = " [SUPERSEDED]" if b.valid_to else " [CURRENT]"
        lock: str = " [LOCKED]" if b.locked else ""
        lines.append(
            f"  {marker} [{b.created_at}] (ID: {b.id}){lock}{status} {b.content[:200]}"
        )
    return "\n".join(lines)


@mcp.tool
def diff(
    since: str | None = None,
    until: str | None = None,
) -> str:
    """Show what changed in the belief store over a time period.

    Returns three sections: ADDED, REMOVED, EVOLVED.
    Accepts ISO 8601 timestamps or relative offsets: "-7d", "-24h", "-1h".

    Use cases:
      diff(since="-24h") -- what changed in the last 24 hours
      diff(since="-7d") -- weekly diff
      diff(since="2026-04-11T00:00:00") -- since a specific time
    """
    if not since:
        return "Error: 'since' is required."
    store: MemoryStore = _get_store()
    resolved_since: str = _resolve_relative_time(since)
    resolved_until: str | None = _resolve_relative_time(until) if until else None
    changes: dict[str, list[Belief]] = store.diff(
        since=resolved_since, until=resolved_until,
    )
    added: list[Belief] = changes["added"]
    removed: list[Belief] = changes["removed"]
    evolved: list[Belief] = changes["evolved"]

    lines: list[str] = [f"Diff since {resolved_since}:"]
    lines.append(f"\nADDED ({len(added)}):")
    for b in added[:20]:
        lines.append(f"  + [{b.belief_type}] {b.content[:150]}")
    if len(added) > 20:
        lines.append(f"  ... and {len(added) - 20} more")

    lines.append(f"\nREMOVED ({len(removed)}):")
    for b in removed[:20]:
        lines.append(f"  - [{b.belief_type}] {b.content[:150]}")
    if len(removed) > 20:
        lines.append(f"  ... and {len(removed) - 20} more")

    lines.append(f"\nEVOLVED ({len(evolved)}):")
    for b in evolved[:20]:
        lines.append(f"  ~ [{b.belief_type}] {b.content[:150]}")
    if len(evolved) > 20:
        lines.append(f"  ... and {len(evolved) - 20} more")

    return "\n".join(lines)


def _resolve_relative_time(time_str: str) -> str:
    """Resolve relative time strings like '-7d', '-24h', '-30m' to ISO 8601."""
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


@mcp.tool
def delete(belief_id: str) -> str:
    """Soft-delete a belief by setting valid_to = now.

    The belief is not hard-deleted -- it remains in the database but is
    excluded from all searches, retrieval, and locked belief injection.
    Use this to clean up duplicate, stale, or incorrect beliefs.

    Args:
        belief_id: The belief ID to delete (e.g. "a1b2c3d4e5f6").
    """
    store: MemoryStore = _get_store()
    belief: Belief | None = store.get_belief(belief_id)
    if belief is None:
        return f"Error: no belief found with ID {belief_id}"
    if belief.valid_to is not None:
        return f"Already deleted (ID: {belief.id}): {belief.content}"
    store.delete_belief(belief_id)
    return (
        f"Deleted (ID: {belief.id}): {belief.content} "
        f"[was: {belief.belief_type}, confidence: {belief.confidence:.0%}, "
        f"locked: {belief.locked}]"
    )


@mcp.tool
def bulk_delete(belief_ids: list[str]) -> str:
    """Soft-delete multiple beliefs at once.

    Use this for cleanup operations (e.g. removing duplicates identified
    by an audit). Each belief gets valid_to set to now.

    Args:
        belief_ids: List of belief IDs to delete.
    """
    store: MemoryStore = _get_store()
    deleted: int = store.bulk_delete_beliefs(belief_ids)
    skipped: int = len(belief_ids) - deleted
    result: str = f"Deleted {deleted} of {len(belief_ids)} beliefs."
    if skipped > 0:
        result += f" {skipped} were already deleted or not found."
    return result


_VALID_OUTCOMES: frozenset[str] = frozenset({OUTCOME_USED, OUTCOME_IGNORED, OUTCOME_HARMFUL})


@mcp.tool
def snapshot(
    at_time: str | None = None,
    topic: str | None = None,
    belief_type: str | None = None,
    limit: int = 50,
) -> str:
    """Return a snapshot of the belief state at a point in time.

    Shows what the agent believed at a given moment, grouped by type.
    If no at_time is given, returns the current belief state.
    If topic is given, filters by FTS5 keyword search.

    Args:
        at_time: ISO timestamp or relative ("-7d", "-24h"). Default: now.
        topic: Optional keyword filter (FTS5 search).
        belief_type: Optional type filter (factual, correction, requirement, preference).
        limit: Maximum beliefs to return (default 50).
    """
    store: MemoryStore = _get_store()

    resolved_time: str | None = None
    if at_time is not None:
        resolved_time = _resolve_relative_time(at_time)

    beliefs: list[Belief]
    if topic is not None:
        effective_time: str = resolved_time if resolved_time is not None else datetime.now(timezone.utc).isoformat()
        beliefs = store.search_at_time(topic, effective_time, top_k=limit)
        if belief_type is not None:
            beliefs = [b for b in beliefs if b.belief_type == belief_type]
    else:
        beliefs = store.get_snapshot(
            at_time=resolved_time,
            belief_type=belief_type,
            limit=limit,
        )

    if not beliefs:
        return "No beliefs found for the given criteria."

    # Group by type
    by_type: dict[str, list[Belief]] = {}
    for b in beliefs:
        by_type.setdefault(b.belief_type, []).append(b)

    total: int = len(beliefs)
    locked_count: int = sum(1 for b in beliefs if b.locked)
    avg_conf: float = sum(b.confidence for b in beliefs) / total

    lines: list[str] = [
        f"Belief snapshot ({total} beliefs, {locked_count} locked, avg_conf={avg_conf:.3f}):",
    ]
    if resolved_time is not None:
        lines[0] = f"Belief snapshot at {resolved_time} ({total} beliefs, {locked_count} locked, avg_conf={avg_conf:.3f}):"

    for bt, bt_beliefs in sorted(by_type.items(), key=lambda x: -len(x[1])):
        bt_locked: int = sum(1 for b in bt_beliefs if b.locked)
        bt_avg: float = sum(b.confidence for b in bt_beliefs) / len(bt_beliefs)
        lines.append(f"\n  {bt} ({len(bt_beliefs)}, {bt_locked} locked, avg={bt_avg:.3f}):")
        for b in bt_beliefs[:10]:
            lock_tag: str = " [LOCKED]" if b.locked else ""
            snippet: str = b.content[:80].replace("\n", " ")
            lines.append(f"    [{b.confidence:.0%}{lock_tag}] {snippet}")
        if len(bt_beliefs) > 10:
            lines.append(f"    ... and {len(bt_beliefs) - 10} more")

    return "\n".join(lines)


@mcp.tool
def feedback(belief_id: str, outcome: str, detail: str = "") -> str:
    """Record whether a retrieved belief was useful, ignored, or harmful.

    Call this after using (or deciding not to use) a belief from search results.
    This closes the feedback loop: beliefs that help get stronger, beliefs that
    hurt get weaker (unless locked).

    Args:
        belief_id: The belief ID from search results (e.g. "a1b2c3d4e5f6").
        outcome: One of "used", "ignored", or "harmful".
        detail: Optional context about why (e.g. "contradicted by user correction").
    """
    if outcome not in _VALID_OUTCOMES:
        return f"Invalid outcome '{outcome}'. Must be one of: {', '.join(sorted(_VALID_OUTCOMES))}"

    store: MemoryStore = _get_store()
    session_id: str = _ensure_session()

    belief: Belief | None = store.get_belief(belief_id)
    if belief is None:
        return f"Belief {belief_id} not found."

    test: TestResult = store.record_test_result(
        belief_id=belief_id,
        session_id=session_id,
        outcome=outcome,
        detection_layer=LAYER_EXPLICIT,
        outcome_detail=detail or None,
    )

    # Mark as explicitly rated so auto-feedback skips it
    _explicit_feedback_ids.add(belief_id)
    store.increment_session_metrics(session_id, feedback_given=1)

    # Re-read to get updated confidence
    updated: Belief | None = store.get_belief(belief_id)
    if updated is None:
        return f"Feedback recorded (test #{test.id}) but belief disappeared."

    lock_note: str = " (locked, beta unchanged)" if updated.locked and outcome == OUTCOME_HARMFUL else ""
    drop_warn: str = ""
    if belief.confidence >= 0.5 and updated.confidence < 0.5:
        snippet: str = updated.content[:80].replace("\n", " ")
        drop_warn = (
            f"\n  WARNING: Belief dropped below 50% confidence. "
            f'Review: "{snippet}"'
        )
    return (
        f"Feedback recorded for {belief_id}: {outcome}{lock_note}\n"
        f"  confidence: {belief.confidence:.3f} -> {updated.confidence:.3f}\n"
        f"  alpha: {belief.alpha} -> {updated.alpha}, "
        f"beta: {belief.beta_param} -> {updated.beta_param}{drop_warn}"
    )


@mcp.tool
def promote(belief_id: str) -> str:
    """Promote a belief to global scope (visible across all projects).

    Only call this AFTER the user has explicitly confirmed they want the
    belief promoted. Global beliefs are loaded in every project's context.
    Useful for behavioral rules like "always use pyright strict mode"
    that apply regardless of which project is active.

    Returns confirmation or error if belief not found.
    """
    store: MemoryStore = _get_store()
    belief: Belief | None = store.get_belief(belief_id)
    if belief is None:
        return f"Error: no belief found with ID {belief_id}"
    if belief.scope == "global":
        return f"Already global (ID: {belief.id}): {belief.content[:80]}"

    ok: bool = store.promote_to_global(belief_id)
    if not ok:
        return f"Error: could not promote belief {belief_id}"

    return (
        f"Promoted to global scope (ID: {belief.id}): {belief.content[:80]}\n"
        f"This belief will now be visible in all projects."
    )


if __name__ == "__main__":
    mcp.run()
