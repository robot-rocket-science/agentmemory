"""Search logic for the UserPromptSubmit hook.

Extracted from agentmemory-search-inject.sh so the scoring, entity
expansion, supersession following, and action-context detection can
be unit tested. The hook script calls search_for_prompt() and formats
the result.

All queries run against a raw sqlite3 connection (no MemoryStore) for
speed in the hook path (~50-100ms budget).
"""
from __future__ import annotations

import random
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HALF_LIVES: dict[str, float] = {
    "factual": 336.0, "procedural": 504.0,
    "causal": 720.0, "relational": 336.0,
    "preference": 2016.0, "correction": 1344.0,
    "requirement": 4032.0,
}

TYPE_WEIGHTS: dict[str, float] = {
    "requirement": 2.5, "correction": 2.0, "preference": 1.8,
    "factual": 1.0, "procedural": 1.2, "causal": 1.3, "relational": 1.0,
}

SOURCE_WEIGHTS: dict[str, float] = {
    "user_corrected": 1.5, "user_stated": 1.3,
    "document_recent": 1.0, "document_old": 0.8, "agent_inferred": 1.0,
}

# Action verbs that imply the user is about to operate on a target entity.
# Pattern -> group(1) captures the target.
ACTION_PATTERNS: list[tuple[str, str]] = [
    (r"\bpush\s+(?:to\s+)?(\w+)", "git remote"),
    (r"\bdeploy\s+(?:to\s+)?(\w+)", "deploy target"),
    (r"\binstall\s+(?:from\s+)?(\w+)", "install source"),
    (r"\bmerge\s+(?:into\s+)?(\w+)", "merge target"),
    (r"\bpublish\s+(?:to\s+)?(\w+)", "publish target"),
    (r"\bclone\s+(\w+)", "clone source"),
]

TOKEN_BUDGET_CHARS: int = 6000
CORRECTION_RECENCY_HOURS: float = 72.0
CORRECTION_BOOST: float = 5.0
LOCK_BOOST: float = 3.0
ACTIVATION_BOOST: float = 2.0

# ---------------------------------------------------------------------------
# Structural prompt analysis (Layer 0)
# ---------------------------------------------------------------------------

# Task-type verb taxonomy (validated in exp86: 90.5% accuracy)
_VERB_CLASSES: dict[str, list[str]] = {
    "planning": [
        "plan", "design", "architect", "roadmap", "outline", "scope",
        "milestone", "breakdown", "decompose", "strategize", "schedule",
    ],
    "deployment": [
        "deploy", "push", "ship", "release", "publish", "launch",
        "merge", "promote", "rollout", "stage",
    ],
    "debugging": [
        "fix", "debug", "diagnose", "troubleshoot", "bisect", "trace",
        "investigate", "reproduce", "isolate", "patch", "address",
    ],
    "implementation": [
        "build", "implement", "create", "add", "wire", "integrate",
        "configure", "setup", "scaffold", "bootstrap",
    ],
    "validation": [
        "test", "verify", "validate", "check", "audit", "review",
        "confirm", "assert", "benchmark", "measure", "pytest", "run",
    ],
    "research": [
        "research", "explore", "investigate", "analyze", "study",
        "compare", "evaluate", "wonder", "hypothesize", "survey",
    ],
}

_ALL_TASK_VERBS: set[str] = {v for vs in _VERB_CLASSES.values() for v in vs}

# Sequential markers suppress subagent detection
_SEQUENTIAL_MARKERS: list[str] = [
    "then", "after that", "next", "once that's done", "first.*then",
    "step by step", "carefully", "one at a time", "sequentially",
    "before we", "wait for", "depends on",
]

# Parallel markers (exp87: "also" removed -- 87.8% FP rate)
_PARALLEL_MARKERS: list[str] = [
    "in parallel", "at the same time", "meanwhile", "concurrently",
    "simultaneously", "spawn subagent", "use subagent", "use agent",
    "all at once", "at once",
]

# Planning phrases the user habitually uses
_PLANNING_PHRASES: list[str] = [
    "make a plan", "make a todo", "todo list", "follow the plan",
    "verify the steps", "stay on track", "execute the plan",
    "refer to the runbook", "check the docs", "best practices",
]

# Compound word splitting for verb detection
_COMPOUNDS: dict[str, str] = {
    "bugfix": "bug fix", "hotfix": "hot fix", "quickfix": "quick fix",
}


@dataclass
class StructuralAnalysis:
    """Result of structural prompt analysis."""

    task_types: list[str] = field(default_factory=lambda: list[str]())
    subagent_suitable: bool = False
    subagent_signals: list[str] = field(default_factory=lambda: list[str]())
    enumerated_items: int = 0
    unique_entities: int = 0
    word_count: int = 0
    has_sequential_markers: bool = False
    has_parallel_markers: bool = False
    planning_phrases_found: list[str] = field(default_factory=lambda: list[str]())


def _split_compounds(text: str) -> str:
    """Split compound words like 'bugfix' into 'bug fix'."""
    result: str = text
    for compound, split in _COMPOUNDS.items():
        result = re.sub(rf"\b{compound}\b", split, result, flags=re.IGNORECASE)
    result = re.sub(r"([a-z])([A-Z])", r"\1 \2", result)
    return result.replace("_", " ")


def analyze_prompt_structure(text: str) -> StructuralAnalysis:
    """Analyze prompt structure for task-type and subagent suitability.

    Zero-LLM structural analysis validated at 90.5% task-type accuracy
    and 92% subagent detection accuracy (exp86). Runs in <2ms.
    """
    result = StructuralAnalysis()
    words: list[str] = text.split()
    result.word_count = len(words)

    # Entity extraction (CamelCase, paths, dotted names, snake_case)
    entities: set[str] = set()
    entities.update(re.findall(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", text))
    entities.update(re.findall(r"[\w./]+\.(?:py|js|ts|md|json|yaml|yml|sh|sql)\b", text))
    entities.update(re.findall(r"\b\w+\.\w+(?:\.\w+)*\b", text))
    entities.update(
        w for w in re.findall(r"\b[a-z]+_[a-z_]+\b", text) if len(w) > 4
    )
    result.unique_entities = len(entities)

    # Enumerated items
    result.enumerated_items = (
        len(re.findall(r"^\s*\d+[\.\)]\s+", text, re.MULTILINE))
        + len(re.findall(r"^\s*[-*]\s+", text, re.MULTILINE))
        + len(re.findall(r"\b(?:first|second|third|fourth|fifth)\b", text, re.IGNORECASE))
    )

    # Verb class scoring
    expanded: str = _split_compounds(text).lower()
    expanded_words: list[str] = re.findall(r"\b\w+\b", expanded)
    verb_scores: dict[str, float] = {}
    for task_type, verbs in _VERB_CLASSES.items():
        hits: int = sum(1 for w in expanded_words if w in verbs)
        if hits > 0:
            verb_scores[task_type] = hits / max(len(expanded_words), 1) * 100

    # Sequential vs parallel markers
    text_lower: str = text.lower()
    for marker in _SEQUENTIAL_MARKERS:
        if re.search(marker, text_lower):
            result.has_sequential_markers = True
            break
    for marker in _PARALLEL_MARKERS:
        if marker in text_lower:
            result.has_parallel_markers = True
            break

    # Planning phrases
    for phrase in _PLANNING_PHRASES:
        if phrase in text_lower:
            result.planning_phrases_found.append(phrase)

    # Task type detection
    for task_type, score in sorted(verb_scores.items(), key=lambda x: x[1], reverse=True):
        if score > 0.5:
            result.task_types.append(task_type)
    if result.planning_phrases_found and "planning" not in result.task_types:
        result.task_types.insert(0, "planning")

    # Subagent suitability detection (100% precision, 62.5% recall in exp86)
    signals: list[str] = []
    if result.enumerated_items >= 3:
        signals.append(f"enumerated_items={result.enumerated_items}")
    if result.unique_entities >= 3 and not result.has_sequential_markers:
        signals.append(f"multi_entity={result.unique_entities}")
    if result.has_parallel_markers:
        signals.append("parallel_language")
    if result.word_count > 100 and result.unique_entities >= 2:
        signals.append("broad_scope")
    if "research" in result.task_types and result.word_count > 50:
        signals.append("research_breadth")
    # Multi-verb-phrase detection
    verb_phrases: list[str] = re.findall(
        r"\b(?:" + "|".join(_ALL_TASK_VERBS) + r")\s+\w+", text_lower,
    )
    if len(verb_phrases) >= 3 and not result.has_sequential_markers:
        signals.append(f"multi_verb_phrase={len(verb_phrases)}")

    result.subagent_signals = signals
    result.subagent_suitable = len(signals) >= 1 and not result.has_sequential_markers

    return result


@dataclass
class ScoredBelief:
    """A belief with computed relevance score."""
    id: str
    content: str
    belief_type: str
    source_type: str
    locked: bool
    confidence: float
    score: float
    age_days: float | None = None
    via: str = "fts5"  # how it was found: fts5, entity, supersession, action


@dataclass
class SearchResult:
    """Result of a hook search."""
    beliefs: list[ScoredBelief] = field(default_factory=lambda: [])
    source_docs: list[str] = field(default_factory=lambda: [])


def format_ba_injection(result: SearchResult) -> str:
    """Format search results as four-zone ba protocol injection.

    Zone 1 - OPERATIONAL STATE: recent corrections and state changes (< 72h)
    Zone 2 - STANDING CONSTRAINTS: locked beliefs as bare imperatives
    Zone 3 - ACTIVE HYPOTHESES: speculative beliefs under investigation
    Zone 4 - BACKGROUND: everything else, assume true unless Zone 1 overrides

    This replaces the flat scored list with structured context that mirrors
    high-context communication: deviations first, rules second, open questions
    third, assumptions last.
    """
    state_changes: list[ScoredBelief] = []
    constraints: list[ScoredBelief] = []
    hypotheses: list[ScoredBelief] = []
    background: list[ScoredBelief] = []

    for b in result.beliefs:
        is_recent_correction: bool = (
            b.belief_type in ("correction", "observation")
            and b.age_days is not None
            and b.age_days < 3.0
        )
        is_supersession: bool = b.via == "supersession"
        is_recent_observation: bool = b.via == "recent_observation"
        is_speculative: bool = b.belief_type == "speculative"

        if is_recent_correction or is_supersession or is_recent_observation:
            state_changes.append(b)
        elif b.locked:
            constraints.append(b)
        elif is_speculative:
            hypotheses.append(b)
        else:
            background.append(b)

    sections: list[str] = []

    if state_changes:
        lines: list[str] = ["== OPERATIONAL STATE =="]
        for b in state_changes:
            age_tag: str = ""
            if b.age_days is not None:
                if b.age_days < 1:
                    age_tag = f" (changed <1d ago)"
                else:
                    age_tag = f" (changed {b.age_days:.0f}d ago)"
            lines.append(f"[!] {b.content}{age_tag}")
        sections.append("\n".join(lines))

    if constraints:
        lines = ["== STANDING CONSTRAINTS =="]
        for b in constraints:
            # Bare imperative, no scores or metadata
            lines.append(f"- {b.content}")
        sections.append("\n".join(lines))

    if hypotheses:
        lines = ["== ACTIVE HYPOTHESES =="]
        for b in hypotheses:
            lines.append(f"[?] {b.content}")
        sections.append("\n".join(lines))

    if background:
        lines = ["== BACKGROUND =="]
        for b in background:
            lines.append(f"- {b.content}")
        sections.append("\n".join(lines))

    if not sections:
        return ""

    header: str = f"AGENTMEMORY: {len(result.beliefs)} belief(s) relevant to your prompt:"
    body: str = "\n\n".join(sections)
    footer: str = ""
    if result.source_docs:
        footer = "\n\nSource documents (read for deeper context):\n"
        footer += "\n".join(f"- {p}" for p in result.source_docs)

    return f"{header}\n{body}{footer}"


# ---------------------------------------------------------------------------
# Query construction
# ---------------------------------------------------------------------------

def extract_query_words(prompt: str) -> list[str]:
    """Extract searchable words from a user prompt."""
    words: list[str] = re.findall(r"[a-zA-Z0-9_]+", prompt)
    return [w for w in words if len(w) > 2][:15]


def extract_entity_candidates(words: list[str]) -> list[str]:
    """Extract likely entity names: longer words, mixed case, underscores."""
    entities: list[str] = []
    for w in words:
        # Likely entities: > 4 chars, or contain uppercase mid-word, or underscores
        if len(w) > 4 or "_" in w or (len(w) > 2 and any(c.isupper() for c in w[1:])):
            entities.append(w)
    return entities


def detect_action_targets(prompt: str) -> list[str]:
    """Detect action verbs and return their target entities."""
    targets: list[str] = []
    for pattern, _label in ACTION_PATTERNS:
        match: re.Match[str] | None = re.search(pattern, prompt, re.IGNORECASE)
        if match:
            target: str = match.group(1)
            if len(target) > 2:
                targets.append(target)
    return targets


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_belief(
    row: sqlite3.Row,
    query_words: list[str],
    now: datetime,
) -> ScoredBelief:
    """Score a single belief row."""
    alpha: float = float(row["alpha"])
    beta_p: float = float(row["beta_param"])
    locked: bool = bool(row["locked"])
    btype: str = row["belief_type"] or "factual"
    src: str = row["source_type"] or "agent_inferred"
    created: str = row["created_at"] or ""

    # Thompson sample from Beta distribution
    sample: float = random.betavariate(max(0.01, alpha), max(0.01, beta_p))

    # Temporal decay (locked beliefs don't decay)
    decay: float = 1.0
    age_h: float | None = None
    if created:
        try:
            ct: datetime = datetime.fromisoformat(created)
            if ct.tzinfo is None:
                ct = ct.replace(tzinfo=timezone.utc)
            age_h = max(0.0, (now - ct).total_seconds() / 3600.0)
            if not locked:
                hl: float | None = HALF_LIVES.get(btype)
                if hl:
                    decay = 0.5 ** (age_h / hl)
        except (ValueError, TypeError):
            pass

    # Lock boost (only if content matches query)
    boost: float = 1.0
    if locked:
        content_lower: str = (row["content"] or "").lower()
        if any(w.lower() in content_lower for w in query_words):
            boost = LOCK_BOOST

    # Correction recency boost: recent corrections about entities in the
    # prompt get a strong boost so they dominate retrieval
    correction_boost: float = 1.0
    if btype == "correction" and age_h is not None and age_h < CORRECTION_RECENCY_HOURS:
        content_lower_c: str = (row["content"] or "").lower()
        if any(w.lower() in content_lower_c for w in query_words):
            correction_boost = CORRECTION_BOOST

    # Type/source weights
    tw: float = TYPE_WEIGHTS.get(btype, 1.0)
    sw: float = SOURCE_WEIGHTS.get(src, 1.0)

    # Recency boost
    recency: float = 1.0
    if age_h is not None:
        recency = 1.0 + 0.5 ** (age_h / 24.0)

    # Final score
    if locked:
        final: float = boost * sample * correction_boost
    else:
        final = tw * sw * sample * decay * recency * correction_boost

    # Confidence
    conf: float = alpha / (alpha + beta_p) if (alpha + beta_p) > 0 else 0.5

    # Age in days
    age_days: float | None = None
    if age_h is not None:
        age_days = age_h / 24.0

    return ScoredBelief(
        id=row["id"],
        content=row["content"] or "",
        belief_type=btype,
        source_type=src,
        locked=locked,
        confidence=conf,
        score=final,
        age_days=age_days,
    )


# ---------------------------------------------------------------------------
# Supersession following
# ---------------------------------------------------------------------------

def follow_supersession(
    db: sqlite3.Connection,
    belief_ids: list[str],
) -> list[sqlite3.Row]:
    """For superseded beliefs, find their active replacements."""
    if not belief_ids:
        return []
    ph: str = ",".join("?" * len(belief_ids))
    # Find beliefs that supersede any of the given IDs
    rows: list[sqlite3.Row] = db.execute(
        f"""SELECT b.* FROM edges e
            JOIN beliefs b ON b.id = e.from_id
            WHERE e.to_id IN ({ph})
              AND e.edge_type = 'SUPERSEDES'
              AND b.valid_to IS NULL
            LIMIT 10""",
        belief_ids,
    ).fetchall()
    return rows


# ---------------------------------------------------------------------------
# Main search
# ---------------------------------------------------------------------------

def _process_pending_feedback(
    db: sqlite3.Connection,
    prompt: str,
    min_matches: int = 2,
) -> int:
    """Process pending feedback from the previous search against this prompt.

    Matches key terms from previously retrieved beliefs against the current
    prompt text. Beliefs whose terms appear in the prompt are marked 'used',
    others 'ignored'. This closes the feedback loop for hook-based retrieval.

    Returns the number of 'used' outcomes recorded.
    """
    try:
        pending: list[sqlite3.Row] = db.execute(
            "SELECT id, belief_id, belief_content FROM pending_feedback LIMIT 100"
        ).fetchall()
    except sqlite3.OperationalError:
        return 0

    if not pending:
        return 0

    prompt_lower: str = prompt.lower()
    prompt_terms: set[str] = set(re.findall(r"[a-zA-Z0-9_]+", prompt_lower))
    used_count: int = 0
    now_str: str = datetime.now(timezone.utc).isoformat()
    pending_ids: list[int] = []

    # Look up session_id for test recording (may be NULL for hook-only sessions)
    session_row: sqlite3.Row | None = db.execute(
        "SELECT id FROM sessions WHERE completed_at IS NULL "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    session_id: str = session_row["id"] if session_row else "hook"

    for row in pending:
        pending_ids.append(row["id"])
        belief_id: str = row["belief_id"]
        content: str = row["belief_content"] or ""

        # Extract key terms from belief content
        terms: list[str] = [
            w for w in re.findall(r"[a-zA-Z0-9_]+", content.lower())
            if len(w) >= 3
        ]
        if not terms:
            continue

        unique_terms: set[str] = set(terms)
        matched: int = len(unique_terms & prompt_terms)

        if matched >= min_matches:
            # "used" -- belief content overlaps with prompt
            db.execute(
                "UPDATE beliefs SET alpha = alpha + 0.3, updated_at = ? WHERE id = ?",
                (now_str, belief_id),
            )
            outcome: str = "used"
            used_count += 1
        else:
            # "ignored" -- weak evidence of irrelevance (0.1 beta increment)
            # Skip locked beliefs -- they represent user constraints
            db.execute(
                "UPDATE beliefs SET beta_param = beta_param + 0.1, updated_at = ? "
                "WHERE id = ? AND locked = 0",
                (now_str, belief_id),
            )
            outcome = "ignored"

        # Record in tests table for visibility and trend measurement
        detail: str = f"hook: {matched}/{len(unique_terms)} terms matched"
        db.execute(
            "INSERT INTO tests (belief_id, session_id, outcome, outcome_detail, "
            "detection_layer, evidence_weight, created_at) "
            "VALUES (?, ?, ?, ?, 'implicit', 1.0, ?)",
            (belief_id, session_id, outcome, detail, now_str),
        )

    # Clear processed entries
    if pending_ids:
        ph: str = ",".join("?" * len(pending_ids))
        db.execute(f"DELETE FROM pending_feedback WHERE id IN ({ph})", pending_ids)
        db.commit()

    return used_count


def _evaluate_activation_conditions(
    db: sqlite3.Connection,
    analysis: StructuralAnalysis,
    prompt_words: set[str],
) -> list[sqlite3.Row]:
    """Find beliefs whose activation_condition matches current prompt.

    Condition format (lines ORed, '+' ANDed within line):
        task_type:planning
        task_type:deployment+keyword_any:production,staging
        structural:enumerated_items>=3
        keyword_any:deploy,ship,push
        subagent:true
    """
    try:
        rows: list[sqlite3.Row] = db.execute(
            "SELECT * FROM beliefs WHERE activation_condition IS NOT NULL "
            "AND valid_to IS NULL AND activation_condition != ''"
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    matched: list[sqlite3.Row] = []
    for row in rows:
        condition: str = row["activation_condition"] or ""
        if _condition_matches(condition, analysis, prompt_words):
            matched.append(row)
    return matched


def _condition_matches(
    condition: str,
    analysis: StructuralAnalysis,
    prompt_words: set[str],
) -> bool:
    """Evaluate an activation condition string. Lines ORed, '+' ANDed."""
    for line in condition.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        predicates: list[str] = line.split("+")
        if all(_eval_predicate(p.strip(), analysis, prompt_words) for p in predicates):
            return True
    return False


def _eval_predicate(
    pred: str,
    analysis: StructuralAnalysis,
    prompt_words: set[str],
) -> bool:
    """Evaluate a single predicate like 'task_type:planning'."""
    if ":" not in pred:
        return False
    ptype: str
    pvalue: str
    ptype, pvalue = pred.split(":", 1)

    if ptype == "task_type":
        return pvalue in analysis.task_types
    elif ptype == "keyword_any":
        keywords: set[str] = {k.strip().lower() for k in pvalue.split(",")}
        return bool(keywords & prompt_words)
    elif ptype == "keyword_all":
        keywords = {k.strip().lower() for k in pvalue.split(",")}
        return keywords.issubset(prompt_words)
    elif ptype == "structural":
        return _eval_structural_predicate(pvalue, analysis)
    elif ptype == "subagent":
        return analysis.subagent_suitable
    return False


def _eval_structural_predicate(expr: str, analysis: StructuralAnalysis) -> bool:
    """Evaluate structural:enumerated_items>=3 style predicates."""
    m: re.Match[str] | None = re.match(r"(\w+)\s*(>=|<=|>|<|==)\s*(\d+)", expr)
    if not m:
        return False
    signal: str = m.group(1)
    op: str = m.group(2)
    threshold: int = int(m.group(3))

    value: int = 0
    if signal == "enumerated_items":
        value = analysis.enumerated_items
    elif signal == "unique_entities":
        value = analysis.unique_entities
    elif signal == "word_count":
        value = analysis.word_count
    else:
        return False

    if op == ">=":
        return value >= threshold
    elif op == "<=":
        return value <= threshold
    elif op == ">":
        return value > threshold
    elif op == "<":
        return value < threshold
    elif op == "==":
        return value == threshold
    return False


def search_for_prompt(
    db: sqlite3.Connection,
    prompt: str,
    budget_chars: int = TOKEN_BUDGET_CHARS,
) -> SearchResult:
    """Run the full search pipeline for a user prompt.

    0. Structural prompt analysis + activation_condition matching
    1. Process pending feedback from previous search (closes feedback loop)
    2. FTS5 keyword search
    3. Entity-aware secondary search (user corrections mentioning prompt entities)
    4. Action-context detection (search for beliefs about action targets)
    5. Supersession-chain following (surface replacements for superseded beliefs)
    6. Score, deduplicate, pack into budget
    7. Record new pending feedback for this search's results
    """
    # Process feedback from previous turn before running new search
    _process_pending_feedback(db, prompt)

    query_words: list[str] = extract_query_words(prompt)
    if not query_words:
        return SearchResult()

    now: datetime = datetime.now(timezone.utc)
    seen_ids: set[str] = set()
    all_scored: list[ScoredBelief] = []

    # --- Layer 0: Structural analysis + activation_condition matching ---
    analysis: StructuralAnalysis = analyze_prompt_structure(prompt)
    prompt_words_set: set[str] = {w.lower() for w in re.findall(r"\b\w+\b", prompt.lower())}
    activated_rows: list[sqlite3.Row] = _evaluate_activation_conditions(
        db, analysis, prompt_words_set,
    )
    for r in activated_rows:
        if r["id"] not in seen_ids:
            sb: ScoredBelief = score_belief(r, query_words, now)
            sb.via = "activation"
            sb.score *= ACTIVATION_BOOST
            all_scored.append(sb)
            seen_ids.add(r["id"])

    # --- Layer 1: FTS5 keyword search (existing behavior) ---
    fts_query: str = " OR ".join(f'"{w}"' for w in query_words)
    try:
        rows: list[sqlite3.Row] = db.execute(
            """SELECT b.*, bm25(search_index) AS bm25_score
               FROM search_index si
               JOIN beliefs b ON b.id = si.id
               WHERE search_index MATCH ?
                 AND si.type = 'belief'
                 AND b.valid_to IS NULL
               ORDER BY bm25(search_index)
               LIMIT 50""",
            (fts_query,),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []

    for r in rows:
        if r["id"] not in seen_ids:
            sb: ScoredBelief = score_belief(r, query_words, now)
            sb.via = "fts5"
            all_scored.append(sb)
            seen_ids.add(r["id"])

    # --- Layer 1.5: Edge-based vocabulary expansion (lightweight HRR proxy) ---
    # HRR runs in retrieval.py but is too heavy for the hook path (numpy, ~117ms).
    # Instead, traverse edges from FTS5 hits to find connected beliefs that FTS5
    # missed due to vocabulary gaps. This bridges ~31% of directive vocabulary
    # gaps (exp53) without numpy overhead. ~5-10ms for edge traversal.
    if seen_ids:
        fts_ids_list: list[str] = list(seen_ids)[:20]  # cap to avoid large queries
        ph_edge: str = ",".join("?" * len(fts_ids_list))
        try:
            edge_rows: list[sqlite3.Row] = db.execute(
                f"""SELECT DISTINCT b.* FROM edges e
                    JOIN beliefs b ON b.id = e.to_id
                    WHERE e.from_id IN ({ph_edge})
                      AND e.edge_type IN ('RELATES_TO', 'SUPPORTS', 'IMPLEMENTS')
                      AND b.valid_to IS NULL
                      AND b.id NOT IN ({ph_edge})
                    LIMIT 10""",
                fts_ids_list + fts_ids_list,
            ).fetchall()
        except sqlite3.OperationalError:
            edge_rows = []

        for r in edge_rows:
            if r["id"] not in seen_ids:
                sb = score_belief(r, query_words, now)
                sb.via = "edge_expansion"
                sb.score *= 0.8  # slight discount for indirect match
                all_scored.append(sb)
                seen_ids.add(r["id"])

    # --- Layer 2: Entity-aware search (corrections/user statements) ---
    entities: list[str] = extract_entity_candidates(query_words)
    action_targets: list[str] = detect_action_targets(prompt)
    # Merge action targets into entity list
    all_entities: list[str] = list(set(entities + action_targets))

    if all_entities:
        entity_fts: str = " OR ".join(f'"{e}"' for e in all_entities)
        try:
            entity_rows: list[sqlite3.Row] = db.execute(
                """SELECT b.*, bm25(search_index) AS bm25_score
                   FROM search_index si
                   JOIN beliefs b ON b.id = si.id
                   WHERE search_index MATCH ?
                     AND si.type = 'belief'
                     AND b.valid_to IS NULL
                     AND b.source_type IN ('user_corrected', 'user_stated')
                   ORDER BY b.created_at DESC
                   LIMIT 10""",
                (entity_fts,),
            ).fetchall()
        except sqlite3.OperationalError:
            entity_rows = []

        for r in entity_rows:
            if r["id"] not in seen_ids:
                sb = score_belief(r, all_entities, now)
                sb.via = "entity"
                # Boost entity-matched corrections
                sb.score *= 1.5
                all_scored.append(sb)
                seen_ids.add(r["id"])

    # --- Layer 3: Action-context search (broader, not limited to user sources) ---
    if action_targets:
        for target in action_targets:
            target_fts: str = f'"{target}"'
            try:
                target_rows: list[sqlite3.Row] = db.execute(
                    """SELECT b.*, bm25(search_index) AS bm25_score
                       FROM search_index si
                       JOIN beliefs b ON b.id = si.id
                       WHERE search_index MATCH ?
                         AND si.type = 'belief'
                         AND b.valid_to IS NULL
                       ORDER BY b.created_at DESC
                       LIMIT 5""",
                    (target_fts,),
                ).fetchall()
            except sqlite3.OperationalError:
                target_rows = []

            for r in target_rows:
                if r["id"] not in seen_ids:
                    sb = score_belief(r, [target], now)
                    sb.via = "action"
                    all_scored.append(sb)
                    seen_ids.add(r["id"])

    # --- Layer 4: Supersession following ---
    # Check if any FTS5 results point to beliefs that have been superseded
    # (shouldn't happen since we filter valid_to IS NULL, but check edges)
    fts_ids: list[str] = [sb.id for sb in all_scored]
    supersession_rows: list[sqlite3.Row] = follow_supersession(db, fts_ids)
    for r in supersession_rows:
        if r["id"] not in seen_ids:
            sb = score_belief(r, query_words, now)
            sb.via = "supersession"
            sb.score *= 2.0  # boost superseding beliefs
            all_scored.append(sb)
            seen_ids.add(r["id"])

    # --- Layer 5: Recent observations (unclassified discoveries) ---
    # The ingest pipeline creates observations immediately but beliefs only
    # after classification. This layer surfaces raw observations from the
    # last 24 hours that match prompt entities, catching agent discoveries
    # that haven't been classified into beliefs yet.
    if all_entities:
        try:
            # Check if observations are in the FTS index
            obs_rows: list[sqlite3.Row] = db.execute(
                """SELECT o.id, o.content, o.source_type, o.created_at
                   FROM observations o
                   WHERE o.created_at > datetime('now', '-24 hours')
                   ORDER BY o.created_at DESC
                   LIMIT 20""",
            ).fetchall()
            for r in obs_rows:
                obs_content: str = r["content"] or ""
                obs_id: str = r["id"]
                if obs_id in seen_ids:
                    continue
                # Check if any entity appears in the observation
                obs_lower: str = obs_content.lower()
                if any(e.lower() in obs_lower for e in all_entities):
                    # Score as a high-priority recent observation
                    age_h_obs: float = 0.0
                    created_obs: str = r["created_at"] or ""
                    if created_obs:
                        try:
                            ct_obs: datetime = datetime.fromisoformat(created_obs)
                            if ct_obs.tzinfo is None:
                                ct_obs = ct_obs.replace(tzinfo=timezone.utc)
                            age_h_obs = max(0.0, (now - ct_obs).total_seconds() / 3600.0)
                        except (ValueError, TypeError):
                            pass
                    recency_obs: float = 1.0 + 0.5 ** (age_h_obs / 6.0)  # 6h half-life for observations
                    obs_score: float = 1.5 * recency_obs  # base score with strong recency
                    all_scored.append(ScoredBelief(
                        id=obs_id,
                        content=obs_content[:300],  # truncate long observations
                        belief_type="observation",
                        source_type=r["source_type"] or "unknown",
                        locked=False,
                        confidence=0.5,  # unscored
                        score=obs_score,
                        age_days=age_h_obs / 24.0,
                        via="recent_observation",
                    ))
                    seen_ids.add(obs_id)
        except sqlite3.OperationalError:
            pass

    # --- Score, sort, pack ---
    all_scored.sort(key=lambda x: x.score, reverse=True)

    packed: list[ScoredBelief] = []
    used: int = 0
    for sb in all_scored:
        entry_len: int = len(sb.content) + 40
        if used + entry_len > budget_chars:
            break
        packed.append(sb)
        used += entry_len

    # --- Source document tracing ---
    source_docs: list[str] = []
    if packed:
        belief_ids: list[str] = [b.id for b in packed]
        ph: str = ",".join("?" * len(belief_ids))

        # Check if source_path column exists
        obs_cols: list[str] = [
            r[1] for r in db.execute("PRAGMA table_info(observations)").fetchall()
        ]
        if "source_path" in obs_cols:
            try:
                path_rows: list[sqlite3.Row] = db.execute(
                    f"""SELECT DISTINCT o.source_path
                        FROM evidence e
                        JOIN observations o ON o.id = e.observation_id
                        WHERE e.belief_id IN ({ph})
                          AND o.source_path != ''
                        LIMIT 10""",
                    belief_ids,
                ).fetchall()
                source_docs = [str(r[0]) for r in path_rows]
            except sqlite3.OperationalError:
                pass

        # Fallback: source_id
        if not source_docs:
            try:
                id_rows: list[sqlite3.Row] = db.execute(
                    f"""SELECT DISTINCT o.source_id
                        FROM evidence e
                        JOIN observations o ON o.id = e.observation_id
                        WHERE e.belief_id IN ({ph})
                          AND o.source_id != ''
                          AND o.observation_type = 'document'
                        LIMIT 10""",
                    belief_ids,
                ).fetchall()
                source_docs = [str(r[0]) for r in id_rows if r[0]]
            except sqlite3.OperationalError:
                pass

    # --- Record retrieval for feedback loop ---
    # Update last_retrieved_at and insert pending_feedback so the
    # auto-feedback path (commit-check hook) can close the loop.
    # This is the fix for onboarded beliefs never getting confidence
    # updates: hook_search previously did zero writes.
    if packed:
        now_str: str = now.isoformat()
        belief_ids_packed: list[str] = [b.id for b in packed]
        ph_upd: str = ",".join("?" * len(belief_ids_packed))
        try:
            db.execute(
                f"UPDATE beliefs SET last_retrieved_at = ? WHERE id IN ({ph_upd})",
                [now_str, *belief_ids_packed],
            )
            # Insert pending feedback (batch insert for speed)
            db.executemany(
                "INSERT INTO pending_feedback (belief_id, belief_content, session_id, created_at) "
                "VALUES (?, ?, NULL, ?)",
                [(b.id, b.content[:200], now_str) for b in packed],
            )
            db.commit()
        except sqlite3.OperationalError:
            pass  # readonly or missing table -- degrade silently

    return SearchResult(beliefs=packed, source_docs=source_docs[:5])
