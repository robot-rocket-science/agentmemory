"""Exp 57: Time Architecture Evaluation Against Case Studies

Tests whether the adopted time architecture (Model 3: TEMPORAL_NEXT structural
edges + Model 2: content-aware decay) addresses the temporal failure modes in
the case studies.

For each case study, we ask:
  1. Does the time architecture provide the temporal signal needed to prevent this failure?
  2. What specific temporal mechanism (decay, supersession, recency, accumulation, velocity) is required?
  3. Does our architecture handle it, or is there a gap?
  4. Are there alternative temporal architectures that handle gaps better?

We test 5 temporal architectures:
  A. No time (baseline): all beliefs weighted equally regardless of age
  B. Model 2 only (decay): content-aware decay on node properties, no structural time
  C. Model 3 only (structural): TEMPORAL_NEXT edges, no decay
  D. Model 3 + Model 2 (adopted): structural edges + content-aware decay
  E. Event-sourced (alternative): append-only event log with materialized views,
     explicit supersession chains, session velocity metadata

We simulate temporal scenarios from the case studies using the alpha-seek timeline
and synthetic event sequences, then measure which architecture prevents each failure.

Hypotheses:
  H1: The adopted architecture (D) handles >= 80% of temporal failure modes.
  H2: At least one case study requires temporal signals that D cannot provide.
  H3: Event-sourced architecture (E) handles cases that D misses.
  H4: Content-aware decay prevents CS-005 (maturity inflation) and CS-015 (dead re-proposals).
  H5: SUPERSEDES chains are load-bearing for CS-009 and CS-015 (approach history).
"""

from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final

# ============================================================
# Temporal architecture definitions
# ============================================================

class ContentType(Enum):
    CONSTRAINT = "constraint"       # no decay (locked rules, axioms)
    EVIDENCE = "evidence"           # moderate decay (stale as new data arrives)
    CONTEXT = "context"             # fast decay (activities, debugging, WIP)
    RATIONALE = "rationale"         # slow decay (why decisions were made)
    PROCEDURE = "procedure"         # slow decay (how-to, protocols)
    SUPERSEDED = "superseded"       # no independent decay (pointer to replacement)


# Decay half-lives in days (for exponential decay)
DECAY_HALF_LIVES: Final[dict[ContentType, float | None]] = {
    ContentType.CONSTRAINT: None,    # never decays
    ContentType.EVIDENCE: 14.0,      # 2-week half-life
    ContentType.CONTEXT: 3.0,        # 3-day half-life
    ContentType.RATIONALE: 30.0,     # 1-month half-life
    ContentType.PROCEDURE: 21.0,     # 3-week half-life
    ContentType.SUPERSEDED: None,    # follows the node it points to
}


@dataclass
class Belief:
    """A belief node with temporal metadata."""
    id: str
    content: str
    content_type: ContentType
    created_at: float           # days since project start
    last_retrieved: float       # days since project start
    retrieval_count: int
    locked: bool
    superseded_by: str | None   # ID of the replacing belief
    session_id: int             # which session created this
    source: str                 # "user", "agent", "commit", "extraction"


@dataclass
class Session:
    """A session with velocity metadata."""
    id: int
    start_time: float           # days since project start
    duration_hours: float
    items_completed: int
    corrections_issued: int


@dataclass
class TemporalEvent:
    """An event in the append-only log (for event-sourced architecture)."""
    timestamp: float            # days since project start
    event_type: str             # "created", "retrieved", "superseded", "corrected", "locked"
    belief_id: str
    session_id: int
    metadata: dict[str, Any] = field(default_factory=dict)  # type: ignore[arg-type]


# ============================================================
# Architecture implementations
# ============================================================

def decay_factor(
    belief: Belief,
    current_time: float,
) -> float:
    """Content-aware exponential decay (Model 2)."""
    if belief.locked:
        return 1.0
    if belief.superseded_by is not None:
        return 0.01  # near-zero but not invisible for history queries

    half_life: float | None = DECAY_HALF_LIVES.get(belief.content_type)
    if half_life is None:
        return 1.0  # no decay

    age: float = current_time - belief.last_retrieved
    if age <= 0:
        return 1.0

    lam: float = math.log(2) / half_life
    return math.exp(-lam * age)


def score_no_time(belief: Belief, current_time: float) -> float:
    """Architecture A: no temporal signal."""
    if belief.superseded_by is not None:
        return 0.0  # still respect supersession
    return 1.0


def score_decay_only(belief: Belief, current_time: float) -> float:
    """Architecture B: content-aware decay, no structural time."""
    return decay_factor(belief, current_time)


def score_structural_only(
    belief: Belief,
    current_time: float,
    temporal_order: dict[str, int],
) -> float:
    """Architecture C: structural time (recency rank), no decay."""
    if belief.superseded_by is not None:
        return 0.0
    # More recent = higher score, normalized to [0, 1]
    max_order: int = max(temporal_order.values()) if temporal_order else 1
    rank: int = temporal_order.get(belief.id, 0)
    return rank / max_order if max_order > 0 else 1.0


def score_adopted(
    belief: Belief,
    current_time: float,
    temporal_order: dict[str, int],
) -> float:
    """Architecture D: structural time + content-aware decay (adopted)."""
    structural: float = score_structural_only(belief, current_time, temporal_order)
    decay: float = decay_factor(belief, current_time)
    return structural * decay


def score_event_sourced(
    belief: Belief,
    current_time: float,
    events: list[TemporalEvent],
    sessions: list[Session],
) -> float:
    """Architecture E: event-sourced with materialized views.

    Uses the full event history to compute:
    - Recency (most recent event on this belief)
    - Correction urgency (how recently and how often corrected)
    - Session velocity context (beliefs from fast sessions score lower)
    - Supersession chain depth (more supersessions = more settled topic)
    """
    if belief.superseded_by is not None:
        return 0.01

    # Recency: most recent event
    belief_events: list[TemporalEvent] = [
        e for e in events if e.belief_id == belief.id
    ]
    if not belief_events:
        return 0.5  # no history -> neutral

    most_recent: float = max(e.timestamp for e in belief_events)
    recency: float = 1.0 / (1.0 + (current_time - most_recent))

    # Correction urgency: corrections boost score
    corrections: list[TemporalEvent] = [
        e for e in belief_events if e.event_type == "corrected"
    ]
    correction_boost: float = min(2.0, 1.0 + 0.3 * len(corrections))

    # Session velocity penalty: beliefs from fast sessions get discounted
    session_map: dict[int, Session] = {s.id: s for s in sessions}
    creating_session: Session | None = session_map.get(belief.session_id)
    velocity_discount: float = 1.0
    if creating_session and creating_session.duration_hours > 0:
        velocity: float = (
            creating_session.items_completed / creating_session.duration_hours
        )
        if velocity > 10:  # more than 10 items/hour = fast sprint
            velocity_discount = 0.7
        elif velocity > 5:
            velocity_discount = 0.85

    # Content-aware decay still applies
    decay: float = decay_factor(belief, current_time)

    return recency * correction_boost * velocity_discount * decay


# ============================================================
# Case study temporal scenarios
# ============================================================

@dataclass
class CaseStudyScenario:
    """A temporal scenario derived from a case study."""
    id: str
    name: str
    description: str
    temporal_mechanism_needed: str
    beliefs: list[Belief]
    events: list[TemporalEvent]
    sessions: list[Session]
    current_time: float
    temporal_order: dict[str, int]
    query: str
    # For evaluation: which belief(s) should rank highest?
    expected_top: list[str]
    # Which belief(s) should NOT appear?
    expected_absent: list[str]


def build_scenarios() -> list[CaseStudyScenario]:
    """Build temporal scenarios from case studies."""
    scenarios: list[CaseStudyScenario] = []

    # -------------------------------------------------------
    # CS-001: Redundant Work
    # Temporal need: recency -- know that task was JUST completed
    # -------------------------------------------------------
    scenarios.append(CaseStudyScenario(
        id="CS-001",
        name="Redundant Work",
        description="Agent re-does work completed 30 seconds ago",
        temporal_mechanism_needed="recency (sub-minute)",
        beliefs=[
            Belief("doc_done", "Documentation task completed: all files updated",
                   ContentType.CONTEXT, 10.0, 10.0, 1, False, None, 5, "agent"),
            Belief("doc_task", "Need to document everything",
                   ContentType.CONTEXT, 9.9, 9.9, 1, False, "doc_done", 5, "user"),
        ],
        events=[
            TemporalEvent(9.9, "created", "doc_task", 5),
            TemporalEvent(10.0, "created", "doc_done", 5),
            TemporalEvent(10.0, "superseded", "doc_task", 5, {"by": "doc_done"}),
        ],
        sessions=[Session(5, 9.0, 2.0, 5, 0)],
        current_time=10.001,  # 30 seconds later
        temporal_order={"doc_task": 1, "doc_done": 2},
        query="document everything",
        expected_top=["doc_done"],
        expected_absent=["doc_task"],
    ))

    # -------------------------------------------------------
    # CS-004: Context Drift Within Session (8+ hours)
    # Temporal need: locked beliefs survive decay over long session
    # -------------------------------------------------------
    scenarios.append(CaseStudyScenario(
        id="CS-004",
        name="Context Drift Within Session",
        description="Locked correction fades over 8-hour session",
        temporal_mechanism_needed="lock immunity to decay",
        beliefs=[
            Belief("no_impl", "We are in research phase. Do not suggest implementation.",
                   ContentType.CONSTRAINT, 0.1, 0.1, 3, True, None, 1, "user"),
            Belief("exp_done", "Experiment 5 completed: Thompson sampling validated",
                   ContentType.EVIDENCE, 0.2, 0.25, 2, False, None, 1, "agent"),
            Belief("ready_build", "Research appears complete. Ready for architecture.",
                   ContentType.CONTEXT, 0.33, 0.33, 1, False, None, 1, "agent"),
        ],
        events=[
            TemporalEvent(0.1, "created", "no_impl", 1),
            TemporalEvent(0.1, "locked", "no_impl", 1),
            TemporalEvent(0.2, "created", "exp_done", 1),
            TemporalEvent(0.33, "created", "ready_build", 1),
        ],
        sessions=[Session(1, 0.0, 8.0, 20, 3)],
        current_time=0.33,  # 8 hours into session
        temporal_order={"no_impl": 1, "exp_done": 2, "ready_build": 3},
        query="what should we do next",
        expected_top=["no_impl"],  # locked constraint must outrank recency
        expected_absent=[],
    ))

    # -------------------------------------------------------
    # CS-005: Project Maturity Inflation
    # Temporal need: session velocity distinguishes fast sprint from deep work
    # -------------------------------------------------------
    scenarios.append(CaseStudyScenario(
        id="CS-005",
        name="Project Maturity Inflation",
        description="New agent inflates project maturity from fast sprint",
        temporal_mechanism_needed="session velocity + rigor tier",
        beliefs=[
            Belief("bayesian_done", "Bayesian confidence model validated (ECE=0.066)",
                   ContentType.EVIDENCE, 0.1, 0.1, 1, False, None, 1, "agent"),
            Belief("privacy_done", "Privacy threat model completed (8 threats, 9 decisions)",
                   ContentType.EVIDENCE, 0.12, 0.12, 1, False, None, 1, "agent"),
            Belief("correction_done", "Correction detection V2 at 92%",
                   ContentType.EVIDENCE, 0.15, 0.15, 1, False, None, 1, "agent"),
            Belief("survey_done", "35+ systems surveyed",
                   ContentType.EVIDENCE, 0.08, 0.08, 1, False, None, 1, "agent"),
        ],
        events=[
            TemporalEvent(0.08, "created", "survey_done", 1),
            TemporalEvent(0.1, "created", "bayesian_done", 1),
            TemporalEvent(0.12, "created", "privacy_done", 1),
            TemporalEvent(0.15, "created", "correction_done", 1),
        ],
        sessions=[Session(1, 0.0, 2.5, 20, 0)],  # 20 items in 2.5 hours = fast
        current_time=1.0,  # next day, new session
        temporal_order={"survey_done": 1, "bayesian_done": 2,
                       "privacy_done": 3, "correction_done": 4},
        query="what have we accomplished and how solid is it",
        expected_top=[],  # all should be DISCOUNTED (velocity penalty)
        expected_absent=[],
    ))

    # -------------------------------------------------------
    # CS-006: Correction Not Enforced Across Session
    # Temporal need: locked beliefs persist with full strength across sessions
    # -------------------------------------------------------
    scenarios.append(CaseStudyScenario(
        id="CS-006",
        name="Correction Not Enforced Cross-Session",
        description="Locked 'no implementation' correction lost across session boundary",
        temporal_mechanism_needed="lock persistence + no decay across sessions",
        beliefs=[
            Belief("no_impl_v2", "DO NOT mention implementation until user says so",
                   ContentType.CONSTRAINT, 0.3, 0.3, 5, True, None, 2, "user"),
            Belief("recent_work", "Completed graph construction research",
                   ContentType.CONTEXT, 2.0, 2.0, 1, False, None, 3, "agent"),
        ],
        events=[
            TemporalEvent(0.3, "created", "no_impl_v2", 2),
            TemporalEvent(0.3, "locked", "no_impl_v2", 2),
            TemporalEvent(0.3, "corrected", "no_impl_v2", 2),
            TemporalEvent(2.0, "created", "recent_work", 3),
        ],
        sessions=[
            Session(2, 0.0, 4.0, 10, 3),
            Session(3, 2.0, 1.0, 3, 0),
        ],
        current_time=2.0,  # start of session 3
        temporal_order={"no_impl_v2": 1, "recent_work": 2},
        query="where are we at now",
        expected_top=["no_impl_v2"],  # must outrank recency
        expected_absent=[],
    ))

    # -------------------------------------------------------
    # CS-009: Codex Retry Loop
    # Temporal need: SUPERSEDES chain showing approach A failed, B succeeded
    # -------------------------------------------------------
    scenarios.append(CaseStudyScenario(
        id="CS-009",
        name="Codex Retry Loop",
        description="Agent retries failed approach after context reset",
        temporal_mechanism_needed="supersession chain + outcome tracking",
        beliefs=[
            Belief("approach_a", "Use standard gcloud deployment for cloud functions",
                   ContentType.PROCEDURE, 1.0, 1.5, 3, False, "approach_b", 1, "agent"),
            Belief("approach_a_fail", "gcloud deployment failed: missing IAM permissions",
                   ContentType.EVIDENCE, 1.5, 1.5, 1, False, None, 1, "agent"),
            Belief("approach_b", "Use terraform for cloud functions (replaces gcloud)",
                   ContentType.PROCEDURE, 2.0, 3.0, 5, False, None, 2, "user"),
            Belief("approach_b_ok", "terraform deployment succeeded on first try",
                   ContentType.EVIDENCE, 2.5, 2.5, 1, False, None, 2, "agent"),
        ],
        events=[
            TemporalEvent(1.0, "created", "approach_a", 1),
            TemporalEvent(1.5, "created", "approach_a_fail", 1),
            TemporalEvent(2.0, "created", "approach_b", 2),
            TemporalEvent(2.0, "superseded", "approach_a", 2, {"by": "approach_b"}),
            TemporalEvent(2.5, "created", "approach_b_ok", 2),
        ],
        sessions=[
            Session(1, 0.0, 4.0, 5, 1),
            Session(2, 2.0, 3.0, 4, 0),
            Session(3, 5.0, 1.0, 1, 0),  # new session, context reset
        ],
        current_time=5.0,  # session 3, no memory of sessions 1-2
        temporal_order={"approach_a": 1, "approach_a_fail": 2,
                       "approach_b": 3, "approach_b_ok": 4},
        query="how should we deploy cloud functions",
        expected_top=["approach_b"],
        expected_absent=["approach_a"],  # superseded, should not be recommended
    ))

    # -------------------------------------------------------
    # CS-014: Research-Execution Divergence
    # Temporal need: IMPLEMENTS edges + temporal ordering shows research -> execution gap
    # -------------------------------------------------------
    scenarios.append(CaseStudyScenario(
        id="CS-014",
        name="Research-Execution Divergence",
        description="Execution omits flag from research findings",
        temporal_mechanism_needed="temporal chain from research to execution with verification",
        beliefs=[
            Belief("research_finding", "Maximize N requires --delta-lo 0.10",
                   ContentType.EVIDENCE, 5.0, 5.0, 2, False, None, 10, "agent"),
            Belief("exec_plan", "Run config B with default parameters",
                   ContentType.PROCEDURE, 6.0, 6.0, 1, False, None, 11, "agent"),
        ],
        events=[
            TemporalEvent(5.0, "created", "research_finding", 10),
            TemporalEvent(6.0, "created", "exec_plan", 11),
        ],
        sessions=[
            Session(10, 4.0, 6.0, 8, 0),
            Session(11, 6.0, 2.0, 3, 0),
        ],
        current_time=6.0,
        temporal_order={"research_finding": 1, "exec_plan": 2},
        query="run the backtest configuration",
        expected_top=["research_finding", "exec_plan"],  # both should surface
        expected_absent=[],
    ))

    # -------------------------------------------------------
    # CS-015: Dead Approaches Re-Proposed
    # Temporal need: SUPERSEDES chain + decay on failed approaches
    # -------------------------------------------------------
    scenarios.append(CaseStudyScenario(
        id="CS-015",
        name="Dead Approaches Re-Proposed",
        description="Agent re-proposes price filters, DTE floors that were tested and failed",
        temporal_mechanism_needed="supersession + evidence of failure",
        beliefs=[
            Belief("price_filter", "Use price filter to reduce noise",
                   ContentType.PROCEDURE, 1.0, 1.0, 2, False, "no_filter", 2, "agent"),
            Belief("price_filter_fail", "Price filter tested: reduces winners more than losers",
                   ContentType.EVIDENCE, 2.0, 2.0, 1, False, None, 3, "agent"),
            Belief("no_filter", "No-filter approach adopted (D183). Price filter DEAD.",
                   ContentType.CONSTRAINT, 3.0, 4.0, 5, True, None, 4, "user"),
            Belief("dte_floor", "Use DTE floor >20 to avoid near-expiry risk",
                   ContentType.PROCEDURE, 1.5, 1.5, 1, False, "no_dte_floor", 2, "agent"),
            Belief("no_dte_floor", "DTE floor rejected: reduces trade count 28%",
                   ContentType.CONSTRAINT, 3.5, 3.5, 3, True, None, 4, "user"),
        ],
        events=[
            TemporalEvent(1.0, "created", "price_filter", 2),
            TemporalEvent(1.5, "created", "dte_floor", 2),
            TemporalEvent(2.0, "created", "price_filter_fail", 3),
            TemporalEvent(3.0, "created", "no_filter", 4),
            TemporalEvent(3.0, "superseded", "price_filter", 4, {"by": "no_filter"}),
            TemporalEvent(3.5, "created", "no_dte_floor", 4),
            TemporalEvent(3.5, "superseded", "dte_floor", 4, {"by": "no_dte_floor"}),
        ],
        sessions=[
            Session(2, 0.5, 3.0, 5, 0),
            Session(3, 2.0, 2.0, 3, 0),
            Session(4, 3.0, 4.0, 6, 2),
            Session(10, 15.0, 1.0, 1, 0),  # much later session
        ],
        current_time=15.0,  # 15 days later
        temporal_order={"price_filter": 1, "dte_floor": 2,
                       "price_filter_fail": 3, "no_filter": 4, "no_dte_floor": 5},
        query="how to reduce noise in the options strategy",
        expected_top=["no_filter", "no_dte_floor"],  # current decisions
        expected_absent=["price_filter", "dte_floor"],  # superseded
    ))

    # -------------------------------------------------------
    # CS-016: Settled Decision Repeatedly Questioned
    # Temporal need: locked constraint immune to decay, evidence of failed challenges
    # -------------------------------------------------------
    scenarios.append(CaseStudyScenario(
        id="CS-016",
        name="Settled Decision Questioned",
        description="Agent questions calls/puts axiom despite locked decision",
        temporal_mechanism_needed="lock + accumulation of failed challenges",
        beliefs=[
            Belief("calls_puts", "Calls and puts are equal citizens. NEVER question this.",
                   ContentType.CONSTRAINT, 1.0, 10.0, 25, True, None, 1, "user"),
            Belief("puts_underperform", "Puts underperformed calls by 15% this quarter",
                   ContentType.EVIDENCE, 14.0, 14.0, 1, False, None, 20, "agent"),
        ],
        events=[
            TemporalEvent(1.0, "created", "calls_puts", 1),
            TemporalEvent(1.0, "locked", "calls_puts", 1),
            TemporalEvent(5.0, "corrected", "calls_puts", 5),  # user reinforced
            TemporalEvent(8.0, "corrected", "calls_puts", 10),  # user reinforced again
            TemporalEvent(14.0, "created", "puts_underperform", 20),
        ],
        sessions=[Session(1, 0.0, 2.0, 3, 0), Session(20, 14.0, 1.0, 2, 0)],
        current_time=14.0,
        temporal_order={"calls_puts": 1, "puts_underperform": 2},
        query="should we reconsider our approach to puts",
        expected_top=["calls_puts"],  # locked axiom must dominate
        expected_absent=[],
    ))

    # -------------------------------------------------------
    # CS-017: Configuration Drift from Implicit Defaults
    # Temporal need: SUPERSEDES_TEMPORAL on default values with propagation to consumers
    # -------------------------------------------------------
    scenarios.append(CaseStudyScenario(
        id="CS-017",
        name="Configuration Drift",
        description="Default capital changed from 100K to 5K, consumers not updated",
        temporal_mechanism_needed="supersession with downstream propagation",
        beliefs=[
            Belief("capital_100k", "Default initial_capital = $100,000",
                   ContentType.CONSTRAINT, 1.0, 5.0, 10, False, "capital_5k", 1, "agent"),
            Belief("capital_5k", "Default initial_capital = $5,000 (changed from 100K)",
                   ContentType.CONSTRAINT, 8.0, 8.0, 3, False, None, 15, "user"),
            Belief("gcp_dispatch", "GCP dispatch uses default initial_capital",
                   ContentType.PROCEDURE, 3.0, 7.0, 8, False, None, 5, "agent"),
        ],
        events=[
            TemporalEvent(1.0, "created", "capital_100k", 1),
            TemporalEvent(3.0, "created", "gcp_dispatch", 5),
            TemporalEvent(8.0, "created", "capital_5k", 15),
            TemporalEvent(8.0, "superseded", "capital_100k", 15, {"by": "capital_5k"}),
            # gcp_dispatch NOT updated -- this is the bug
        ],
        sessions=[Session(1, 0.0, 2.0, 3, 0), Session(15, 8.0, 1.0, 2, 0)],
        current_time=8.0,
        temporal_order={"capital_100k": 1, "gcp_dispatch": 2, "capital_5k": 3},
        query="what capital does the GCP dispatch use",
        expected_top=["capital_5k", "gcp_dispatch"],  # both: new value + stale consumer
        expected_absent=[],
        # KEY TEST: can the architecture detect that gcp_dispatch references
        # a superseded value? This requires propagation, not just decay.
    ))

    # -------------------------------------------------------
    # CS-022: Multi-Hop Operational Query
    # Temporal need: recent operational facts (paths, machines) must not decay
    # -------------------------------------------------------
    scenarios.append(CaseStudyScenario(
        id="CS-022",
        name="Multi-Hop Operational Query",
        description="Agent doesn't know where data lives (which machine, which path)",
        temporal_mechanism_needed="operational facts as non-decaying constraints",
        beliefs=[
            Belief("agent_config", "4 paper trading agents: baseline, stallion, firehose, sniper",
                   ContentType.EVIDENCE, 7.0, 7.0, 3, False, None, 15, "agent"),
            Belief("data_location", "Paper trading data at ~/projects/alpha-seek/data/paper_trading/ on lorax",
                   ContentType.CONSTRAINT, 7.0, 7.0, 1, False, None, 15, "agent"),
            Belief("machine_rule", "alpha-seek dev and data are on lorax. willow is for services.",
                   ContentType.CONSTRAINT, 2.0, 5.0, 5, False, None, 3, "user"),
        ],
        events=[
            TemporalEvent(2.0, "created", "machine_rule", 3),
            TemporalEvent(7.0, "created", "agent_config", 15),
            TemporalEvent(7.0, "created", "data_location", 15),
        ],
        sessions=[Session(3, 2.0, 1.0, 2, 0), Session(15, 7.0, 2.0, 5, 0),
                  Session(16, 10.0, 1.0, 1, 0)],
        current_time=10.0,  # 3 days after setup
        temporal_order={"machine_rule": 1, "agent_config": 2, "data_location": 3},
        query="get paper trading positions",
        expected_top=["data_location", "machine_rule"],  # operational facts must survive
        expected_absent=[],
    ))

    # -------------------------------------------------------
    # CS-023: Parallel Session Namespace Collision
    # Temporal need: concurrent event ordering + cross-session visibility
    # -------------------------------------------------------
    scenarios.append(CaseStudyScenario(
        id="CS-023",
        name="Parallel Session Collision",
        description="Two sessions claim same ID (A032) simultaneously",
        temporal_mechanism_needed="concurrent event detection + causal ordering",
        beliefs=[
            Belief("a032_session_a", "A032: Atomic LLM Calls for Batch Classification",
                   ContentType.PROCEDURE, 5.0, 5.0, 1, False, None, 8, "agent"),
            Belief("a032_session_b", "A032: Type-Aware IB Compression Heuristic",
                   ContentType.PROCEDURE, 5.01, 5.01, 1, False, None, 9, "agent"),
        ],
        events=[
            TemporalEvent(5.0, "created", "a032_session_a", 8),
            TemporalEvent(5.01, "created", "a032_session_b", 9),
        ],
        sessions=[
            Session(8, 4.0, 3.0, 5, 0),
            Session(9, 4.5, 2.0, 4, 0),  # parallel
        ],
        current_time=5.5,
        temporal_order={"a032_session_a": 1, "a032_session_b": 2},
        query="what is A032",
        expected_top=["a032_session_a", "a032_session_b"],  # BOTH must surface (conflict)
        expected_absent=[],
    ))

    return scenarios


# ============================================================
# Evaluation
# ============================================================

@dataclass
class ArchitectureResult:
    """Result of evaluating one architecture on one scenario."""
    architecture: str
    scenario_id: str
    scores: dict[str, float]  # belief_id -> score
    ranking: list[str]        # belief_ids sorted by score descending
    top_correct: bool         # expected_top beliefs rank highest
    absent_correct: bool      # expected_absent beliefs rank lowest / score 0
    verdict: str              # PASS / PARTIAL / FAIL


def evaluate_architecture(
    arch_name: str,
    score_fn: Any,  # callable
    scenario: CaseStudyScenario,
) -> ArchitectureResult:
    """Evaluate an architecture on a scenario."""
    scores: dict[str, float] = {}

    for belief in scenario.beliefs:
        if arch_name == "A_no_time":
            scores[belief.id] = score_no_time(belief, scenario.current_time)
        elif arch_name == "B_decay_only":
            scores[belief.id] = score_decay_only(belief, scenario.current_time)
        elif arch_name == "C_structural_only":
            scores[belief.id] = score_structural_only(
                belief, scenario.current_time, scenario.temporal_order
            )
        elif arch_name == "D_adopted":
            scores[belief.id] = score_adopted(
                belief, scenario.current_time, scenario.temporal_order
            )
        elif arch_name == "E_event_sourced":
            scores[belief.id] = score_event_sourced(
                belief, scenario.current_time,
                scenario.events, scenario.sessions,
            )

    # Rank by score descending
    ranking: list[str] = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)

    # Check expected_top: all expected_top beliefs should be in the top N positions
    top_correct: bool = True
    if scenario.expected_top:
        top_n: int = len(scenario.expected_top)
        actual_top: set[str] = set(ranking[:top_n])
        top_correct = all(b in actual_top for b in scenario.expected_top)

    # Check expected_absent: these should score near zero or below others
    absent_correct: bool = True
    if scenario.expected_absent:
        for absent_id in scenario.expected_absent:
            if absent_id in scores:
                # Should score lower than all non-absent beliefs
                absent_score: float = scores[absent_id]
                non_absent_scores: list[float] = [
                    s for bid, s in scores.items()
                    if bid not in scenario.expected_absent
                ]
                if non_absent_scores and absent_score >= min(non_absent_scores):
                    absent_correct = False

    # Verdict
    if top_correct and absent_correct:
        verdict: str = "PASS"
    elif top_correct or absent_correct:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"

    return ArchitectureResult(
        architecture=arch_name,
        scenario_id=scenario.id,
        scores=scores,
        ranking=ranking,
        top_correct=top_correct,
        absent_correct=absent_correct,
        verdict=verdict,
    )


# ============================================================
# Main
# ============================================================

def main() -> None:
    t_start: float = time.monotonic()
    print("=" * 70, file=sys.stderr)
    print("Experiment 57: Time Architecture Evaluation Against Case Studies", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    scenarios: list[CaseStudyScenario] = build_scenarios()
    print(f"\n  {len(scenarios)} scenarios built from case studies\n", file=sys.stderr)

    architectures: list[str] = [
        "A_no_time",
        "B_decay_only",
        "C_structural_only",
        "D_adopted",
        "E_event_sourced",
    ]

    all_results: dict[str, list[ArchitectureResult]] = {a: [] for a in architectures}
    scenario_results: dict[str, dict[str, ArchitectureResult]] = {}

    for scenario in scenarios:
        print(f"--- {scenario.id}: {scenario.name} ---", file=sys.stderr)
        print(f"    Temporal need: {scenario.temporal_mechanism_needed}", file=sys.stderr)

        scenario_results[scenario.id] = {}

        for arch in architectures:
            result: ArchitectureResult = evaluate_architecture(arch, None, scenario)
            all_results[arch].append(result)
            scenario_results[scenario.id][arch] = result

            scores_str: str = "  ".join(
                f"{bid}={score:.3f}" for bid, score in
                sorted(result.scores.items(), key=lambda x: x[1], reverse=True)
            )
            print(
                f"    {arch:25s}: {result.verdict:7s} "
                f"top={result.top_correct} absent={result.absent_correct} "
                f"| {scores_str}",
                file=sys.stderr,
            )

    # ============================================================
    # Aggregate
    # ============================================================

    print("\n" + "=" * 70, file=sys.stderr)
    print("AGGREGATE RESULTS", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    for arch in architectures:
        results: list[ArchitectureResult] = all_results[arch]
        pass_count: int = sum(1 for r in results if r.verdict == "PASS")
        partial_count: int = sum(1 for r in results if r.verdict == "PARTIAL")
        fail_count: int = sum(1 for r in results if r.verdict == "FAIL")
        total: int = len(results)
        rate: float = pass_count / total if total > 0 else 0.0

        print(
            f"  {arch:25s}: {pass_count}/{total} PASS ({rate:.0%}), "
            f"{partial_count} PARTIAL, {fail_count} FAIL",
            file=sys.stderr,
        )

    # ============================================================
    # Gap analysis: which scenarios does the adopted architecture miss?
    # ============================================================

    print("\n" + "=" * 70, file=sys.stderr)
    print("GAP ANALYSIS: WHERE DOES THE ADOPTED ARCHITECTURE (D) FAIL?", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    for scenario in scenarios:
        d_result: ArchitectureResult = scenario_results[scenario.id]["D_adopted"]
        if d_result.verdict != "PASS":
            # Check which arch handles it better
            better: list[str] = []
            for arch in architectures:
                if arch == "D_adopted":
                    continue
                other: ArchitectureResult = scenario_results[scenario.id][arch]
                if other.verdict == "PASS" and d_result.verdict != "PASS":
                    better.append(arch)

            print(
                f"\n  {scenario.id} ({scenario.name}): {d_result.verdict}",
                file=sys.stderr,
            )
            print(
                f"    Need: {scenario.temporal_mechanism_needed}",
                file=sys.stderr,
            )
            print(
                f"    Scores: {d_result.scores}",
                file=sys.stderr,
            )
            if better:
                print(
                    f"    Better handled by: {better}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"    NO architecture handles this case.",
                    file=sys.stderr,
                )

    # ============================================================
    # Hypothesis evaluation
    # ============================================================

    print("\n" + "=" * 70, file=sys.stderr)
    print("HYPOTHESIS EVALUATION", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    d_results: list[ArchitectureResult] = all_results["D_adopted"]
    d_pass_rate: float = sum(1 for r in d_results if r.verdict == "PASS") / len(d_results)

    e_results: list[ArchitectureResult] = all_results["E_event_sourced"]
    _e_pass_rate: float = sum(1 for r in e_results if r.verdict == "PASS") / len(e_results)

    print(f"\n  H1: Adopted (D) handles >= 80% of temporal failures", file=sys.stderr)
    print(f"      Result: {d_pass_rate:.0%} -- {'PASS' if d_pass_rate >= 0.8 else 'FAIL'}", file=sys.stderr)

    # H2: at least one case study that D can't handle
    d_failures: list[str] = [r.scenario_id for r in d_results if r.verdict != "PASS"]
    print(f"\n  H2: At least one case D cannot handle", file=sys.stderr)
    print(f"      Result: {len(d_failures)} failures: {d_failures} -- "
          f"{'PASS' if d_failures else 'FAIL'}", file=sys.stderr)

    # H3: E handles cases D misses
    e_handles_d_misses: list[str] = []
    for scenario_id in d_failures:
        if scenario_results[scenario_id]["E_event_sourced"].verdict == "PASS":
            e_handles_d_misses.append(scenario_id)
    print(f"\n  H3: Event-sourced (E) handles cases D misses", file=sys.stderr)
    print(f"      D failures: {d_failures}", file=sys.stderr)
    print(f"      E handles: {e_handles_d_misses} -- "
          f"{'PASS' if e_handles_d_misses else 'FAIL'}", file=sys.stderr)

    # H4: decay prevents CS-005 and CS-015
    cs005_b: str = scenario_results["CS-005"]["B_decay_only"].verdict
    cs015_b: str = scenario_results["CS-015"]["B_decay_only"].verdict
    print(f"\n  H4: Decay alone prevents CS-005 and CS-015", file=sys.stderr)
    print(f"      CS-005: {cs005_b}, CS-015: {cs015_b} -- "
          f"{'PASS' if cs005_b == 'PASS' and cs015_b == 'PASS' else 'FAIL'}", file=sys.stderr)

    # H5: SUPERSEDES chains load-bearing for CS-009 and CS-015
    cs009_a: str = scenario_results["CS-009"]["A_no_time"].verdict
    cs009_d: str = scenario_results["CS-009"]["D_adopted"].verdict
    cs015_a: str = scenario_results["CS-015"]["A_no_time"].verdict
    cs015_d: str = scenario_results["CS-015"]["D_adopted"].verdict
    print(f"\n  H5: SUPERSEDES chains load-bearing for CS-009, CS-015", file=sys.stderr)
    print(f"      CS-009: no_time={cs009_a}, adopted={cs009_d}", file=sys.stderr)
    print(f"      CS-015: no_time={cs015_a}, adopted={cs015_d}", file=sys.stderr)
    supersedes_load_bearing: bool = (
        cs009_a != "PASS" and cs009_d == "PASS" and
        cs015_a != "PASS" and cs015_d == "PASS"
    )
    print(f"      {'PASS' if supersedes_load_bearing else 'FAIL'}", file=sys.stderr)

    elapsed: float = time.monotonic() - t_start

    # ============================================================
    # Save results
    # ============================================================

    output: dict[str, Any] = {
        "experiment": "exp57_time_architecture",
        "date": "2026-04-10",
        "elapsed_seconds": round(elapsed, 3),
        "scenarios": len(scenarios),
        "architectures": architectures,
        "per_scenario": {},
        "aggregates": {},
        "hypotheses": {},
    }

    for scenario in scenarios:
        output["per_scenario"][scenario.id] = {
            "name": scenario.name,
            "temporal_need": scenario.temporal_mechanism_needed,
            "results": {},
        }
        for arch in architectures:
            r: ArchitectureResult = scenario_results[scenario.id][arch]
            output["per_scenario"][scenario.id]["results"][arch] = {
                "verdict": r.verdict,
                "top_correct": r.top_correct,
                "absent_correct": r.absent_correct,
                "scores": {k: round(v, 4) for k, v in r.scores.items()},
                "ranking": r.ranking,
            }

    for arch in architectures:
        results = all_results[arch]
        output["aggregates"][arch] = {
            "pass": sum(1 for r in results if r.verdict == "PASS"),
            "partial": sum(1 for r in results if r.verdict == "PARTIAL"),
            "fail": sum(1 for r in results if r.verdict == "FAIL"),
            "pass_rate": round(
                sum(1 for r in results if r.verdict == "PASS") / len(results), 3
            ),
        }

    output["hypotheses"] = {
        "H1_adopted_80pct": {"result": d_pass_rate >= 0.8, "rate": round(d_pass_rate, 3)},
        "H2_at_least_one_gap": {"result": bool(d_failures), "gaps": d_failures},
        "H3_event_sourced_covers_gaps": {"result": bool(e_handles_d_misses),
                                          "covered": e_handles_d_misses},
        "H4_decay_prevents_005_015": {
            "result": cs005_b == "PASS" and cs015_b == "PASS",
            "cs005": cs005_b, "cs015": cs015_b,
        },
        "H5_supersedes_load_bearing": {"result": supersedes_load_bearing},
    }

    results_path: Path = Path(__file__).parent / "exp57_results.json"
    results_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\nResults saved to {results_path.name}", file=sys.stderr)
    print(f"Total time: {elapsed:.3f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
