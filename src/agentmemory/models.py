"""Domain model dataclasses for agentmemory.

All fields map 1:1 to SQLite schema columns. No Pydantic, no validation logic here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# Observation types
OBS_TYPE_CONVERSATION: Final[str] = "conversation"
OBS_TYPE_FILE_CHANGE: Final[str] = "file_change"
OBS_TYPE_ERROR: Final[str] = "error"
OBS_TYPE_DECISION: Final[str] = "decision"
OBS_TYPE_USER_STATEMENT: Final[str] = "user_statement"
OBS_TYPE_DOCUMENT: Final[str] = "document"

# Source types (observation)
SRC_USER: Final[str] = "user"
SRC_AGENT: Final[str] = "agent"
SRC_SYSTEM: Final[str] = "system"
SRC_DOCUMENT: Final[str] = "document"

# Belief types
BELIEF_FACTUAL: Final[str] = "factual"
BELIEF_PREFERENCE: Final[str] = "preference"
BELIEF_RELATIONAL: Final[str] = "relational"
BELIEF_PROCEDURAL: Final[str] = "procedural"
BELIEF_CAUSAL: Final[str] = "causal"
BELIEF_CORRECTION: Final[str] = "correction"
BELIEF_REQUIREMENT: Final[str] = "requirement"

# Belief source types
BSRC_USER_STATED: Final[str] = "user_stated"
BSRC_USER_CORRECTED: Final[str] = "user_corrected"
BSRC_DOCUMENT_RECENT: Final[str] = "document_recent"
BSRC_DOCUMENT_OLD: Final[str] = "document_old"
BSRC_AGENT_INFERRED: Final[str] = "agent_inferred"

# Evidence relationships
REL_SUPPORTS: Final[str] = "supports"
REL_WEAKENS: Final[str] = "weakens"
REL_CONTRADICTS: Final[str] = "contradicts"

# Edge types
EDGE_CITES: Final[str] = "CITES"
EDGE_RELATES_TO: Final[str] = "RELATES_TO"
EDGE_SUPERSEDES: Final[str] = "SUPERSEDES"
EDGE_CONTRADICTS: Final[str] = "CONTRADICTS"
EDGE_SUPPORTS: Final[str] = "SUPPORTS"
EDGE_TESTS: Final[str] = "TESTS"
EDGE_IMPLEMENTS: Final[str] = "IMPLEMENTS"
EDGE_TEMPORAL_NEXT: Final[str] = "TEMPORAL_NEXT"

# Speculative edge types (forward-looking beliefs)
EDGE_SPECULATES: Final[str] = "SPECULATES"  # current state -> possible future
EDGE_DEPENDS_ON: Final[str] = "DEPENDS_ON"  # speculative node -> condition required
EDGE_RESOLVES: Final[str] = "RESOLVES"  # evidence/experiment -> speculative node
EDGE_HIBERNATED: Final[str] = "HIBERNATED"  # soft-closed branch marker

# Edge-type valence multipliers for propagation.
# Positive = propagate in same direction, negative = invert valence.
EDGE_VALENCE: dict[str, float] = {
    "SUPPORTS": 1.0,
    "DEPENDS_ON": 0.8,
    "IMPLEMENTS": 0.7,
    "CITES": 0.5,
    "TESTS": 0.5,
    "RESOLVES": 0.5,
    "RELATES_TO": 0.3,
    "SPECULATES": 0.3,
    "CONTRADICTS": -0.5,  # inverts the valence sign
    "SUPERSEDES": 0.0,  # historical, no propagation
    "TEMPORAL_NEXT": 0.0,  # structural, no propagation
    "HIBERNATED": 0.0,  # inactive, no propagation
}

# Valence propagation parameters
VALENCE_DECAY: Final[float] = 0.5  # attenuation per hop
VALENCE_MAX_HOPS: Final[int] = 3  # maximum propagation depth
VALENCE_MIN_THRESHOLD: Final[float] = 0.05  # stop below this
CONFIRM_WEIGHT: Final[float] = 2.0  # weight for explicit confirm()
SESSION_HUB_BOOST: Final[float] = 2.0  # extra weight for hub beliefs

# Lock levels (3-tier lock system)
LOCK_NONE: Final[str] = "none"  # Normal belief, full Bayesian updates
LOCK_PROMOTED: Final[str] = (
    "promoted"  # System-promoted, resists noise but evidence can demote
)
LOCK_USER: Final[str] = "user"  # User-locked, only explicit user action changes

# Temporal directions
TEMPORAL_BACKWARD: Final[str] = "backward"
TEMPORAL_FORWARD: Final[str] = "forward"

# Test outcomes
OUTCOME_USED: Final[str] = "used"
OUTCOME_IGNORED: Final[str] = "ignored"
OUTCOME_CONTRADICTED: Final[str] = "contradicted"
OUTCOME_HARMFUL: Final[str] = "harmful"
OUTCOME_CONFIRMED: Final[str] = "confirmed"
OUTCOME_WEAK: Final[str] = "weak"

# Valence map: string outcome -> continuous score [-1.0, +1.0]
# Positive = alpha boost, negative = beta boost, zero = no change.
VALENCE_MAP: dict[str, float] = {
    "confirmed": +1.0,
    "used": +0.5,
    "ignored": 0.0,
    "contradicted": 0.0,
    "weak": -0.3,
    "harmful": -1.0,
}

# Detection layers
LAYER_EXPLICIT: Final[str] = "explicit"
LAYER_IMPLICIT: Final[str] = "implicit"
LAYER_CHECKPOINT: Final[str] = "checkpoint"
LAYER_FN_SCAN: Final[str] = "fn_scan"

# Checkpoint types
CKPT_DECISION: Final[str] = "decision"
CKPT_FILE_CHANGE: Final[str] = "file_change"
CKPT_TASK_STATE: Final[str] = "task_state"
CKPT_CONTEXT_SUMMARY: Final[str] = "context_summary"
CKPT_ERROR: Final[str] = "error"
CKPT_GOAL: Final[str] = "goal"


@dataclass
class Observation:
    id: str  # UUID hex, 12 chars
    content_hash: str  # SHA-256 hex, 12 chars (for dedup)
    content: str
    observation_type: (
        str  # conversation, file_change, error, decision, user_statement, document
    )
    source_type: str  # user, agent, system, document
    source_id: str  # unique identifier for source (file path, commit SHA, turn ID -- NOT the type string)
    source_path: str = ""  # file path the content was extracted from (for doc tracing)
    session_id: str | None = None
    created_at: str = ""  # ISO 8601


@dataclass
class Belief:
    id: str  # UUID hex, 12 chars
    content_hash: str  # SHA-256 hex, 12 chars (for dedup)
    content: str
    belief_type: str  # factual, preference, relational, procedural, causal, correction, requirement
    alpha: float  # Beta distribution success count (Jeffreys prior: starts at 0.5)
    beta_param: float  # Beta distribution failure count (Jeffreys prior: starts at 0.5)
    confidence: float  # alpha / (alpha + beta_param), computed field
    source_type: str  # user_stated, user_corrected, document_recent, document_old, agent_inferred
    locked: bool  # Cannot be downgraded by feedback (legacy: use lock_level)
    valid_from: str | None  # ISO 8601
    valid_to: str | None  # ISO 8601, NULL = still current
    superseded_by: str | None  # Points to replacement belief ID
    created_at: str
    updated_at: str
    event_time: str | None = (
        None  # Bitemporal: when fact occurred (vs created_at = ingestion time)
    )
    session_id: str | None = None  # Session that created this belief
    classified_by: str = (
        "offline"  # "offline" or "llm" -- which classifier produced this belief
    )
    rigor_tier: str = "hypothesis"  # hypothesis / simulated / empirically_tested / validated (REQ-025)
    method: str | None = None  # How this belief was produced (REQ-023)
    sample_size: int | None = None  # Number of samples in evidence (REQ-023)
    last_retrieved_at: str | None = None  # ISO 8601 timestamp of last retrieval
    data_source: str = (
        ""  # Where belief came from (REQ-023: e.g. "documentation", "git_log")
    )
    independently_validated: bool = False  # Has external verification (REQ-023)
    temporal_direction: str = (
        "backward"  # "backward" (factual) or "forward" (speculative)
    )
    uncertainty_vector: str | None = (
        None  # JSON array of [alpha,beta] pairs per uncertainty dimension
    )
    hibernation_score: float | None = None  # Soft-close score for speculative branches
    activation_condition: str | None = (
        None  # Event-based trigger for prospective beliefs
    )
    lock_level: str = "none"  # "none", "promoted", "user" -- 3-tier lock system


@dataclass
class Evidence:
    id: int
    belief_id: str
    observation_id: str
    source_weight: float  # 1.0 for user, 0.5 for agent
    relationship: str  # supports, weakens, contradicts
    created_at: str


@dataclass
class Edge:
    id: int
    from_id: str
    to_id: str
    edge_type: (
        str  # CITES, RELATES_TO, SUPERSEDES, CONTRADICTS, SUPPORTS, TEMPORAL_NEXT
    )
    weight: float
    reason: str
    created_at: str
    alpha: float = 1.0
    beta_param: float = 1.0
    traversal_count: int = 0
    last_traversed_at: str | None = None
    pruned_at: str | None = None


@dataclass
class Session:
    id: str
    started_at: str
    completed_at: str | None
    model: str | None
    project_context: str | None
    summary: str | None
    # Token and correction burden tracking (REQ-024, amortization hypothesis)
    retrieval_tokens: int = 0  # tokens injected via search/retrieve
    classification_tokens: int = 0  # tokens consumed by Haiku classification
    beliefs_created: int = 0  # beliefs stored this session
    corrections_detected: int = 0  # user corrections detected this session
    searches_performed: int = 0  # search/retrieve calls this session
    feedback_given: int = 0  # feedback events (auto + explicit) this session
    # Velocity tracking (Wave 1D, Exp 58c)
    velocity_items_per_hour: float | None = None
    velocity_tier: str | None = None  # sprint, moderate, steady, deep
    topics_json: str | None = None  # JSON array of top topic keywords


@dataclass
class Checkpoint:
    id: int
    session_id: str
    checkpoint_type: (
        str  # decision, file_change, task_state, context_summary, error, goal
    )
    content: str
    references: str  # JSON array of related IDs
    created_at: str


@dataclass
class TestResult:
    id: int
    belief_id: str
    session_id: str
    retrieval_context: str | None
    outcome: str  # used, ignored, contradicted, harmful
    outcome_detail: str | None
    detection_layer: str  # explicit, implicit, checkpoint, fn_scan
    evidence_weight: float
    created_at: str
