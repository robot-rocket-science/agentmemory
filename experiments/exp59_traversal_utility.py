"""Exp 59: Traversal Utility of TEMPORAL_NEXT Edges

Tests whether TEMPORAL_NEXT edges provide traversal value that timestamps alone
cannot. Exp 57 established that TEMPORAL_NEXT edges should be used for traversal
queries, not ranking. This experiment quantifies the practical difference.

For 10 temporal queries across 4 categories, we compare 4 retrieval methods:
  a. TIMESTAMP_ONLY: SQL WHERE on derived timestamps
  b. TEMPORAL_NEXT_TRAVERSAL: BFS/DFS on TEMPORAL_NEXT edges
  c. SUPERSEDES_CHAIN: follow SUPERSEDES edges
  d. FTS5_PLUS_TIME: FTS5 keyword search + timestamp range filter

Each method is evaluated on:
  - COMPLETENESS: fraction of ground-truth items found
  - UNIQUE_VALUE: items this method found that no other method found
  - STRUCTURAL_INSIGHT: whether result reveals ordering/relationships

Data sources:
  - Alpha-seek spike DB (173 decisions, DECIDED_IN edges -> milestone timestamps)
  - Exp 6 timeline (1790 events, 775 edges)

Hypotheses:
  H1: RANGE queries are fully answerable by TIMESTAMP_ONLY alone.
  H2: SEQUENCE queries require TEMPORAL_NEXT for correct ordering/adjacency.
  H3: EVOLUTION queries require SUPERSEDES chains.
  H4: CAUSAL queries require CITES edges + temporal filter.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final

# ============================================================
# Constants
# ============================================================

DB_PATH: Final[Path] = Path(
    "/Users/thelorax/projects/.gsd/workflows/spikes/"
    "260406-1-associative-memory-for-gsd-please-explor/sandbox/alpha-seek.db"
)
TIMELINE_PATH: Final[Path] = Path(
    "/Users/thelorax/projects/agentmemory/experiments/exp6_timeline.json"
)
RESULTS_PATH: Final[Path] = Path(
    "/Users/thelorax/projects/agentmemory/experiments/exp59_results.json"
)

# Milestone prefix -> canonical full ID (first occurrence by created_at)
# Built dynamically from DB; type hint here for clarity
MilestoneMap = dict[str, str]   # "M005" -> "M005-4iw23z"


# ============================================================
# Enums and dataclasses
# ============================================================

class QueryCategory(str, Enum):
    RANGE = "RANGE"
    SEQUENCE = "SEQUENCE"
    EVOLUTION = "EVOLUTION"
    CAUSAL = "CAUSAL"


class Method(str, Enum):
    TIMESTAMP_ONLY = "TIMESTAMP_ONLY"
    TEMPORAL_NEXT = "TEMPORAL_NEXT_TRAVERSAL"
    SUPERSEDES = "SUPERSEDES_CHAIN"
    FTS5_TIME = "FTS5_PLUS_TIME"


@dataclass
class Decision:
    """A decision node with derived temporal metadata."""
    id: str
    decision: str
    scope: str
    choice: str
    rationale: str
    # timestamp in days since earliest milestone date (day 0)
    timestamp_days: float
    # which milestone prefix contributed the earliest timestamp
    milestone_prefix: str


@dataclass
class TemporalEdge:
    """A directed temporal edge between two decisions."""
    from_id: str
    to_id: str
    edge_type: str   # TEMPORAL_NEXT | SUPERSEDES | SESSION_BOUNDARY | CITES | DECIDED_IN


@dataclass
class GroundTruth:
    """Manually defined ground truth for a query."""
    query_id: str
    expected_ids: list[str]   # all relevant decision IDs
    notes: str


@dataclass
class MethodResult:
    """Result of one method applied to one query."""
    method: Method
    found_ids: list[str]
    completeness: float          # fraction of ground truth found
    unique_ids: list[str]        # IDs this method found that no other did
    structural_insight: bool     # does result encode ordering/adjacency?
    notes: str


@dataclass
class QueryResult:
    """Full evaluation of all methods for one query."""
    query_id: str
    query_text: str
    category: QueryCategory
    ground_truth: list[str]
    method_results: dict[str, MethodResult] = field(default_factory=dict)  # type: ignore[arg-type]
    requires_structural: bool = False
    requires_supersedes: bool = False


@dataclass
class TemporalGraph:
    """In-memory temporal graph built from DB + inferred edges."""
    decisions: dict[str, Decision]
    # sorted list of decision IDs by timestamp
    sorted_ids: list[str]
    # adjacency: from_id -> list[TemporalEdge]
    out_edges: dict[str, list[TemporalEdge]]
    # reverse adjacency for prev-traversal
    in_edges: dict[str, list[TemporalEdge]]
    # session map: milestone_prefix -> list[decision_id]
    session_groups: dict[str, list[str]]


# ============================================================
# DB helpers
# ============================================================

def load_milestone_timestamps(conn: sqlite3.Connection) -> dict[str, float]:
    """Return {full_milestone_id: days_since_day0}.

    Day 0 = earliest milestone created_at.
    """
    rows: list[tuple[str, str]] = conn.execute(
        "SELECT id, created_at FROM milestones ORDER BY created_at"
    ).fetchall()
    if not rows:
        raise RuntimeError("No milestones found in DB")

    import datetime
    # Parse ISO timestamps
    def parse_ts(s: str) -> datetime.datetime:
        # SQLite stores as "2026-03-25T18:38:31.911Z"
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))

    parsed: list[tuple[str, datetime.datetime]] = [
        (mid, parse_ts(ts)) for mid, ts in rows
    ]
    t0: datetime.datetime = parsed[0][1]

    result: dict[str, float] = {}
    for mid, dt in parsed:
        delta = (dt - t0).total_seconds() / 86400.0
        result[mid] = delta
    return result


def load_decisions(conn: sqlite3.Connection) -> dict[str, Decision]:
    """Load all decisions from DB."""
    rows: list[tuple[str, str, str, str, str]] = conn.execute(
        "SELECT id, decision, scope, choice, rationale FROM decisions ORDER BY id"
    ).fetchall()
    result: dict[str, Decision] = {}
    for did, decision, scope, choice, rationale in rows:
        result[did] = Decision(
            id=did,
            decision=decision,
            scope=scope,
            choice=choice,
            rationale=rationale,
            timestamp_days=-1.0,   # filled in below
            milestone_prefix="",
        )
    return result


def derive_decision_timestamps(
    decisions: dict[str, Decision],
    conn: sqlite3.Connection,
    milestone_ts: dict[str, float],
) -> None:
    """Assign each decision its timestamp from the earliest linked milestone.

    Mutates decisions in place.
    """
    # DECIDED_IN edges: from_id=decision_id, to_id=_Mxxx (prefixed with _)
    rows: list[tuple[str, str]] = conn.execute(
        "SELECT from_id, to_id FROM mem_edges WHERE edge_type='DECIDED_IN'"
    ).fetchall()

    # Build decision -> list of milestone timestamps
    decision_to_ts: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for dec_id, raw_mid in rows:
        # to_id is like "_M001" -- strip leading underscore
        mid_prefix: str = raw_mid.lstrip("_")   # "M001"
        # Find the full milestone ID matching this prefix
        matching_ts: list[float] = [
            ts for full_id, ts in milestone_ts.items()
            if full_id.startswith(mid_prefix + "-")
        ]
        if matching_ts:
            earliest: float = min(matching_ts)
            decision_to_ts[dec_id].append((earliest, mid_prefix))

    for dec_id, ts_list in decision_to_ts.items():
        if dec_id in decisions:
            # Use the earliest milestone this decision appears in
            ts_list.sort(key=lambda x: x[0])
            decisions[dec_id].timestamp_days = ts_list[0][0]
            decisions[dec_id].milestone_prefix = ts_list[0][1]

    # Decisions with no DECIDED_IN edge get timestamp -1 (unlinked)
    unlinked: list[str] = [
        did for did, d in decisions.items() if d.timestamp_days < 0
    ]
    if unlinked:
        print(
            f"[warn] {len(unlinked)} decisions have no DECIDED_IN edge: "
            f"{unlinked[:5]}{'...' if len(unlinked) > 5 else ''}",
            file=sys.stderr,
        )


def load_mem_edges(conn: sqlite3.Connection) -> list[tuple[str, str, str, float]]:
    """Load all mem_edges: (from_id, to_id, edge_type, weight)."""
    return conn.execute(
        "SELECT from_id, to_id, edge_type, weight FROM mem_edges"
    ).fetchall()


# ============================================================
# Graph construction
# ============================================================

def build_temporal_graph(
    decisions: dict[str, Decision],
    mem_edges: list[tuple[str, str, str, float]],
) -> TemporalGraph:
    """Build in-memory temporal graph with TEMPORAL_NEXT + SUPERSEDES edges.

    TEMPORAL_NEXT: link consecutive decisions sorted by timestamp.
    SUPERSEDES: infer from Exp 57's correction cluster analysis:
      calls/puts topic: D050 -> D073 -> D096 -> D100 -> D123
      dispatch gate:    D089 -> D106 -> D138
      capital:          D099 -> D110
    SESSION_BOUNDARY: added between sessions (different milestone_prefix).
    Also include CITES and DECIDED_IN from the DB for causal queries.
    """
    # Filter to decisions with valid timestamps and sort
    linked: list[Decision] = [
        d for d in decisions.values() if d.timestamp_days >= 0
    ]
    linked.sort(key=lambda d: (d.timestamp_days, d.id))
    sorted_ids: list[str] = [d.id for d in linked]

    out_edges: dict[str, list[TemporalEdge]] = defaultdict(list)
    in_edges: dict[str, list[TemporalEdge]] = defaultdict(list)

    def add_edge(e: TemporalEdge) -> None:
        out_edges[e.from_id].append(e)
        in_edges[e.to_id].append(e)

    # TEMPORAL_NEXT: link consecutive decisions by timestamp
    for i in range(len(sorted_ids) - 1):
        a: str = sorted_ids[i]
        b: str = sorted_ids[i + 1]
        da: Decision = decisions[a]
        db: Decision = decisions[b]
        if da.milestone_prefix == db.milestone_prefix:
            add_edge(TemporalEdge(a, b, "TEMPORAL_NEXT"))
        else:
            # Different session -> SESSION_BOUNDARY (still a traversal edge)
            add_edge(TemporalEdge(a, b, "SESSION_BOUNDARY"))

    # SESSION_BOUNDARY reverse is stored implicitly through in_edges

    # SUPERSEDES: inferred correction chains (Exp 57 clusters + manual)
    supersedes_chains: list[list[str]] = [
        # calls/puts topic evolution
        ["D050", "D073", "D096", "D100", "D123"],
        # dispatch gate evolution
        ["D089", "D106", "D138"],
        # capital decision evolution
        ["D099", "D110"],
    ]
    for chain in supersedes_chains:
        for i in range(len(chain) - 1):
            a = chain[i]
            b = chain[i + 1]
            if a in decisions and b in decisions:
                add_edge(TemporalEdge(a, b, "SUPERSEDES"))

    # CITES edges from DB
    for from_id, to_id, edge_type, _weight in mem_edges:
        if edge_type == "CITES":
            if from_id in decisions and to_id in decisions:
                add_edge(TemporalEdge(from_id, to_id, "CITES"))

    # Build session groups
    session_groups: dict[str, list[str]] = defaultdict(list)
    for did in sorted_ids:
        prefix: str = decisions[did].milestone_prefix
        session_groups[prefix].append(did)

    return TemporalGraph(
        decisions=decisions,
        sorted_ids=sorted_ids,
        out_edges=dict(out_edges),
        in_edges=dict(in_edges),
        session_groups=dict(session_groups),
    )


# ============================================================
# FTS5 in-memory index
# ============================================================

def build_fts5_index(decisions: dict[str, Decision]) -> sqlite3.Connection:
    """Build an in-memory SQLite FTS5 index over decisions.

    Uses a backing content table so id is retrievable from FTS matches.
    Returns a connection to the in-memory DB.
    """
    mem_conn: sqlite3.Connection = sqlite3.connect(":memory:")

    # Backing table stores the rows; FTS5 uses it as content source.
    mem_conn.execute(
        "CREATE TABLE fts_docs(id TEXT, body TEXT)"
    )
    doc_rows: list[tuple[str, str]] = [
        (d.id, f"{d.decision} {d.choice} {d.rationale} {d.scope}")
        for d in decisions.values()
    ]
    mem_conn.executemany("INSERT INTO fts_docs VALUES (?, ?)", doc_rows)

    mem_conn.execute(
        """CREATE VIRTUAL TABLE fts_decisions USING fts5(
               id,
               body,
               content=fts_docs,
               content_rowid=rowid
           )"""
    )
    mem_conn.execute("INSERT INTO fts_decisions(fts_decisions) VALUES('rebuild')")
    mem_conn.commit()
    return mem_conn


def fts5_search(
    fts_conn: sqlite3.Connection,
    query_terms: str,
) -> list[str]:
    """Return decision IDs matching query_terms via FTS5."""
    rows: list[tuple[str]] = fts_conn.execute(
        "SELECT id FROM fts_decisions WHERE body MATCH ? ORDER BY rank",
        (query_terms,),
    ).fetchall()
    return [r[0] for r in rows]


# ============================================================
# Query methods
# ============================================================

def method_timestamp_only(
    graph: TemporalGraph,
    min_day: float | None = None,
    max_day: float | None = None,
    milestone_prefix: str | None = None,
    limit: int | None = None,
    ascending: bool = True,
) -> list[str]:
    """TIMESTAMP_ONLY: filter decisions by time range or milestone membership.

    Returns sorted list of matching decision IDs.
    """
    candidates: list[Decision] = [
        graph.decisions[did]
        for did in graph.sorted_ids
    ]
    if milestone_prefix is not None:
        candidates = [
            d for d in candidates
            if d.milestone_prefix == milestone_prefix
        ]
    if min_day is not None:
        candidates = [d for d in candidates if d.timestamp_days >= min_day]
    if max_day is not None:
        candidates = [d for d in candidates if d.timestamp_days <= max_day]
    if not ascending:
        candidates = list(reversed(candidates))
    if limit is not None:
        candidates = candidates[:limit]
    return [d.id for d in candidates]


def method_temporal_next_traversal(
    graph: TemporalGraph,
    start_id: str,
    direction: str = "forward",
    steps: int = 3,
    edge_types: set[str] | None = None,
) -> list[str]:
    """TEMPORAL_NEXT_TRAVERSAL: BFS from start_id along TEMPORAL_NEXT edges.

    direction: "forward" (later decisions) or "backward" (earlier decisions)
    steps: how many hops to traverse
    edge_types: which edge types to follow (default: TEMPORAL_NEXT only)
    Returns ordered list of visited IDs (excluding start_id itself).
    """
    if edge_types is None:
        edge_types = {"TEMPORAL_NEXT"}

    adjacency: dict[str, list[TemporalEdge]] = (
        graph.out_edges if direction == "forward" else graph.in_edges
    )

    visited: list[str] = []
    queue: deque[tuple[str, int]] = deque([(start_id, 0)])
    seen: set[str] = {start_id}

    while queue:
        current, depth = queue.popleft()
        if depth >= steps:
            continue
        for edge in adjacency.get(current, []):
            neighbor: str = edge.to_id if direction == "forward" else edge.from_id
            if neighbor not in seen and edge.edge_type in edge_types:
                seen.add(neighbor)
                visited.append(neighbor)
                queue.append((neighbor, depth + 1))

    return visited


def method_session_group(
    graph: TemporalGraph,
    anchor_id: str,
) -> list[str]:
    """Return all decisions in the same session (milestone) as anchor_id."""
    if anchor_id not in graph.decisions:
        return []
    prefix: str = graph.decisions[anchor_id].milestone_prefix
    return [
        did for did in graph.session_groups.get(prefix, [])
        if did != anchor_id
    ]


def method_supersedes_chain(
    graph: TemporalGraph,
    start_id: str,
    direction: str = "forward",
) -> list[str]:
    """SUPERSEDES_CHAIN: follow SUPERSEDES edges from start_id.

    direction: "forward" (what supersedes this?) or "backward" (what was superseded?)
    Returns ordered chain of IDs.
    """
    adjacency: dict[str, list[TemporalEdge]] = (
        graph.out_edges if direction == "forward" else graph.in_edges
    )
    chain: list[str] = []
    current: str = start_id
    for _ in range(50):   # safety bound
        found_next: str | None = None
        for edge in adjacency.get(current, []):
            neighbor: str = edge.to_id if direction == "forward" else edge.from_id
            if edge.edge_type == "SUPERSEDES" and neighbor not in chain:
                found_next = neighbor
                break
        if found_next is None:
            break
        chain.append(found_next)
        current = found_next
    return chain


def method_fts5_plus_time(
    fts_conn: sqlite3.Connection,
    graph: TemporalGraph,
    query_terms: str,
    min_day: float | None = None,
    max_day: float | None = None,
    anchor_id: str | None = None,
) -> list[str]:
    """FTS5_PLUS_TIME: FTS5 keyword match filtered by timestamp range.

    If anchor_id is provided, min_day is set to the anchor's timestamp.
    """
    if anchor_id is not None and anchor_id in graph.decisions:
        anchor_ts: float = graph.decisions[anchor_id].timestamp_days
        min_day = anchor_ts if min_day is None else max(min_day, anchor_ts)

    candidates: list[str] = fts5_search(fts_conn, query_terms)
    result: list[str] = []
    for did in candidates:
        if did not in graph.decisions:
            continue
        ts: float = graph.decisions[did].timestamp_days
        if min_day is not None and ts < min_day:
            continue
        if max_day is not None and ts > max_day:
            continue
        result.append(did)
    return result


def method_cites_plus_time(
    graph: TemporalGraph,
    target_id: str,
    min_day: float | None = None,
) -> list[str]:
    """CITES + timestamp filter: find decisions citing target_id made after it.

    Used for causal queries.
    """
    citers: list[str] = []
    for from_id, edges in graph.out_edges.items():
        for edge in edges:
            if edge.to_id == target_id and edge.edge_type == "CITES":
                ts: float = graph.decisions[from_id].timestamp_days if from_id in graph.decisions else -1.0
                anchor_ts: float = (
                    graph.decisions[target_id].timestamp_days
                    if target_id in graph.decisions else 0.0
                )
                effective_min: float = min_day if min_day is not None else anchor_ts
                if ts >= effective_min:
                    citers.append(from_id)
    # Sort by timestamp
    citers.sort(key=lambda did: graph.decisions[did].timestamp_days)
    return citers


# ============================================================
# Ground truth definitions
# ============================================================

def define_ground_truths(graph: TemporalGraph) -> dict[str, GroundTruth]:
    """Manually defined ground truth for each query."""
    # Q1: decisions in M005
    q1_ids: list[str] = graph.session_groups.get("M005", [])

    # Q2: decisions between day 3 and day 7 (M009-M010 era: 2026-03-26)
    # day 0 = 2026-03-25, day 3 = 2026-03-28
    q2_ids: list[str] = [
        did for did in graph.sorted_ids
        if 3.0 <= graph.decisions[did].timestamp_days <= 7.0
    ]

    # Q3: 5 most recent decisions (by timestamp)
    q3_ids: list[str] = [
        d.id for d in sorted(
            graph.decisions.values(),
            key=lambda x: x.timestamp_days,
            reverse=True,
        )
        if d.timestamp_days >= 0
    ][:5]

    # Q4: immediate next after D097 (one hop TEMPORAL_NEXT forward)
    q4_ids: list[str] = method_temporal_next_traversal(graph, "D097", "forward", 1)

    # Q5: 3 decisions before D157
    q5_ids: list[str] = method_temporal_next_traversal(graph, "D157", "backward", 3)

    # Q6: decisions in same session as D073
    q6_ids: list[str] = method_session_group(graph, "D073")

    # Q7: dispatch gate evolution chain (D089 -> D106 -> D138)
    q7_ids: list[str] = ["D089", "D106", "D138"]

    # Q8: current version of capital decision (follow SUPERSEDES from D099)
    # D099 -> D110 is the chain; ground truth is D110 as current
    q8_ids: list[str] = ["D110"]

    # Q9: decisions citing D097, made after it
    q9_ids: list[str] = method_cites_plus_time(graph, "D097")

    # Q10: full calls/puts correction chain
    q10_ids: list[str] = ["D050", "D073", "D096", "D100", "D123"]

    return {
        "Q1": GroundTruth("Q1", q1_ids, "Decisions decided_in M005"),
        "Q2": GroundTruth("Q2", q2_ids, "Decisions between day 3 and day 7"),
        "Q3": GroundTruth("Q3", q3_ids, "5 most recent decisions"),
        "Q4": GroundTruth("Q4", q4_ids, "Decision immediately after D097"),
        "Q5": GroundTruth("Q5", q5_ids, "3 decisions before D157"),
        "Q6": GroundTruth("Q6", q6_ids, "Decisions in same session as D073 (M008)"),
        "Q7": GroundTruth("Q7", q7_ids, "Dispatch gate protocol evolution chain"),
        "Q8": GroundTruth("Q8", q8_ids, "Current version of capital decision"),
        "Q9": GroundTruth("Q9", q9_ids, "Decisions citing D097 made after it"),
        "Q10": GroundTruth("Q10", q10_ids, "Full calls/puts correction chain"),
    }


# ============================================================
# Evaluation
# ============================================================

def completeness(found: list[str], truth: list[str]) -> float:
    """Fraction of ground truth IDs present in found."""
    if not truth:
        return 1.0
    found_set: set[str] = set(found)
    hits: int = sum(1 for t in truth if t in found_set)
    return hits / len(truth)


def compute_unique_values(
    all_results: dict[str, list[str]],
) -> dict[str, list[str]]:
    """For each method, find IDs it found that no other method found."""
    unique: dict[str, list[str]] = {}
    for method, found in all_results.items():
        others: set[str] = set()
        for other_method, other_found in all_results.items():
            if other_method != method:
                others.update(other_found)
        unique[method] = [fid for fid in found if fid not in others]
    return unique


# ============================================================
# Per-query execution
# ============================================================

def run_query(
    qid: str,
    query_text: str,
    category: QueryCategory,
    ground_truth: GroundTruth,
    graph: TemporalGraph,
    fts_conn: sqlite3.Connection,
) -> QueryResult:
    """Run all 4 methods against a single query and evaluate."""
    result: QueryResult = QueryResult(
        query_id=qid,
        query_text=query_text,
        category=category,
        ground_truth=ground_truth.expected_ids,
    )

    ts_found: list[str] = []
    tn_found: list[str] = []
    sup_found: list[str] = []
    fts_found: list[str] = []

    # -------------------------------------------------------
    # Q1: decisions in M005
    # -------------------------------------------------------
    if qid == "Q1":
        ts_found = method_timestamp_only(graph, milestone_prefix="M005")
        tn_found = []  # no traversal needed for milestone filter
        sup_found = []
        fts_found = method_fts5_plus_time(fts_conn, graph, "M005 exit strategy", None, None)

    # -------------------------------------------------------
    # Q2: decisions between day 3 and day 7
    # -------------------------------------------------------
    elif qid == "Q2":
        ts_found = method_timestamp_only(graph, min_day=3.0, max_day=7.0)
        # TEMPORAL_NEXT: walk from first decision at day >= 3
        start_at_day3: list[str] = method_timestamp_only(graph, min_day=3.0, max_day=3.0)
        if start_at_day3:
            # BFS from first node in that band, collect until day > 7
            raw_traversal: list[str] = method_temporal_next_traversal(
                graph, start_at_day3[0], "forward", 100
            )
            tn_found = [
                did for did in raw_traversal
                if did in graph.decisions
                and 3.0 <= graph.decisions[did].timestamp_days <= 7.0
            ]
        sup_found = []
        fts_found = method_fts5_plus_time(fts_conn, graph, "milestone", 3.0, 7.0)

    # -------------------------------------------------------
    # Q3: 5 most recent decisions
    # -------------------------------------------------------
    elif qid == "Q3":
        ts_found = method_timestamp_only(graph, ascending=False, limit=5)
        # TEMPORAL_NEXT backward from last decision
        last_id: str = graph.sorted_ids[-1] if graph.sorted_ids else ""
        tn_found = ([last_id] + method_temporal_next_traversal(
            graph, last_id, "backward", 4
        ))[:5] if last_id else []
        sup_found = []
        fts_found = method_fts5_plus_time(fts_conn, graph, "decision strategy", None, None)[:5]

    # -------------------------------------------------------
    # Q4: immediately after D097
    # -------------------------------------------------------
    elif qid == "Q4":
        if "D097" in graph.decisions:
            ts_d97: float = graph.decisions["D097"].timestamp_days
            all_after: list[str] = method_timestamp_only(graph, min_day=ts_d97)
            # Exclude D097 itself
            ts_found = [x for x in all_after if x != "D097"][:1]
        tn_found = method_temporal_next_traversal(graph, "D097", "forward", 1)
        sup_found = []
        fts_found = method_fts5_plus_time(fts_conn, graph, "walk forward backtest performance", anchor_id="D097")[:1]

    # -------------------------------------------------------
    # Q5: 3 decisions before D157
    # -------------------------------------------------------
    elif qid == "Q5":
        if "D157" in graph.decisions:
            ts_d157: float = graph.decisions["D157"].timestamp_days
            all_before: list[str] = method_timestamp_only(
                graph, max_day=ts_d157, ascending=False
            )
            ts_found = [x for x in all_before if x != "D157"][:3]
        tn_found = method_temporal_next_traversal(graph, "D157", "backward", 3)
        sup_found = []
        fts_found = method_fts5_plus_time(fts_conn, graph, "async tooling", None, None)[:3]

    # -------------------------------------------------------
    # Q6: same session as D073 (M008)
    # -------------------------------------------------------
    elif qid == "Q6":
        # TIMESTAMP_ONLY: filter by M008 timestamp range
        m008_ids: list[str] = graph.session_groups.get("M008", [])
        ts_found = [did for did in m008_ids if did != "D073"]

        # TEMPORAL_NEXT: walk from D073 within the session
        tn_raw: list[str] = method_temporal_next_traversal(
            graph, "D073", "forward", 20, edge_types={"TEMPORAL_NEXT"}
        )
        tn_rev: list[str] = method_temporal_next_traversal(
            graph, "D073", "backward", 20, edge_types={"TEMPORAL_NEXT"}
        )
        tn_found = [
            did for did in tn_raw + tn_rev
            if did in graph.decisions and graph.decisions[did].milestone_prefix == "M008"
        ]
        sup_found = []
        fts_found = method_fts5_plus_time(
            fts_conn, graph, "calls puts direction equal citizens",
            min_day=graph.decisions["M008-xnku0q"].timestamp_days
            if "M008-xnku0q" in graph.decisions else None,
        )

    # -------------------------------------------------------
    # Q7: dispatch gate evolution (SUPERSEDES chain from D089)
    # -------------------------------------------------------
    elif qid == "Q7":
        # TIMESTAMP_ONLY: keyword guess + sort
        ts_found = method_timestamp_only(graph)
        # Filter to dispatch-gate-related decisions by known IDs
        dispatch_ids: set[str] = {"D089", "D106", "D138"}
        ts_found = [did for did in ts_found if did in dispatch_ids]

        # TEMPORAL_NEXT: walk forward from D089
        tn_found = ["D089"] + method_temporal_next_traversal(
            graph, "D089", "forward", 20
        )
        # Filter to dispatch chain only
        tn_found = [did for did in tn_found if did in dispatch_ids]

        # SUPERSEDES: follow chain from D089
        sup_found = ["D089"] + method_supersedes_chain(graph, "D089", "forward")

        fts_found = method_fts5_plus_time(fts_conn, graph, "dispatch gate deploy enforcement")

    # -------------------------------------------------------
    # Q8: current version of capital decision from D099
    # -------------------------------------------------------
    elif qid == "Q8":
        # TIMESTAMP_ONLY: find most recent capital-related decision
        ts_found = method_timestamp_only(graph)
        capital_ids: set[str] = {"D099", "D110"}
        ts_found_capital: list[str] = [did for did in reversed(ts_found) if did in capital_ids]
        ts_found = ts_found_capital[:1]  # most recent = current

        # TEMPORAL_NEXT: walk forward from D099 looking for capital decisions
        tn_raw2: list[str] = method_temporal_next_traversal(graph, "D099", "forward", 20)
        tn_found = [did for did in tn_raw2 if did in capital_ids][:1]

        # SUPERSEDES: follow chain from D099 -> D110
        sup_full: list[str] = method_supersedes_chain(graph, "D099", "forward")
        sup_found = sup_full[-1:] if sup_full else []  # only the final version

        fts_found = method_fts5_plus_time(
            fts_conn, graph, "starting bankroll capital initial",
            anchor_id="D099",
        )[:1]

    # -------------------------------------------------------
    # Q9: decisions citing D097, made after it
    # -------------------------------------------------------
    elif qid == "Q9":
        # TIMESTAMP_ONLY: find all decisions after D097 (no citation info)
        if "D097" in graph.decisions:
            ts_d97_2: float = graph.decisions["D097"].timestamp_days
            ts_found = method_timestamp_only(graph, min_day=ts_d97_2)
            ts_found = [x for x in ts_found if x != "D097"]
            # Can't distinguish citers without graph -- return all after
        tn_found = []  # TEMPORAL_NEXT doesn't encode citation
        sup_found = []
        fts_found = method_fts5_plus_time(
            fts_conn, graph, "walk forward backtest per year", anchor_id="D097"
        )
        # Causal method (ground truth method): cites + time
        causal_found: list[str] = method_cites_plus_time(graph, "D097")
        # Assign causal result to sup_found slot for display
        sup_found = causal_found   # SUPERSEDES slot repurposed for CITES here

    # -------------------------------------------------------
    # Q10: full calls/puts correction chain
    # -------------------------------------------------------
    elif qid == "Q10":
        # TIMESTAMP_ONLY: find strategy decisions about calls/puts by time range
        ts_found = method_timestamp_only(graph)
        callsput_ids: set[str] = {"D050", "D073", "D096", "D100", "D123"}
        ts_found = [did for did in ts_found if did in callsput_ids]

        # TEMPORAL_NEXT: walk from D050 forward
        tn_raw3: list[str] = ["D050"] + method_temporal_next_traversal(
            graph, "D050", "forward", 50
        )
        tn_found = [did for did in tn_raw3 if did in callsput_ids]

        # SUPERSEDES: follow full chain from D050
        sup_found = ["D050"] + method_supersedes_chain(graph, "D050", "forward")

        fts_found = method_fts5_plus_time(
            fts_conn, graph, "calls puts equal citizens direction"
        )

    else:
        raise ValueError(f"Unknown query id: {qid}")

    # -------------------------------------------------------
    # Evaluate
    # -------------------------------------------------------
    all_found: dict[str, list[str]] = {
        Method.TIMESTAMP_ONLY.value: ts_found,
        Method.TEMPORAL_NEXT.value: tn_found,
        Method.SUPERSEDES.value: sup_found,
        Method.FTS5_TIME.value: fts_found,
    }
    unique_map: dict[str, list[str]] = compute_unique_values(all_found)

    # Structural insight: TEMPORAL_NEXT and SUPERSEDES provide ordering
    structural_flags: dict[str, bool] = {
        Method.TIMESTAMP_ONLY.value: False,
        Method.TEMPORAL_NEXT.value: True,
        Method.SUPERSEDES.value: True,
        Method.FTS5_TIME.value: False,
    }

    for method_val, found_list in all_found.items():
        result.method_results[method_val] = MethodResult(
            method=Method(method_val),
            found_ids=found_list,
            completeness=completeness(found_list, ground_truth.expected_ids),
            unique_ids=unique_map[method_val],
            structural_insight=structural_flags[method_val],
            notes="",
        )

    # Classify whether structural edges are required
    ts_complete: float = result.method_results[Method.TIMESTAMP_ONLY.value].completeness
    ts_fts_complete: float = max(
        ts_complete,
        result.method_results[Method.FTS5_TIME.value].completeness,
    )
    sup_complete: float = result.method_results[Method.SUPERSEDES.value].completeness
    tn_complete: float = result.method_results[Method.TEMPORAL_NEXT.value].completeness

    result.requires_structural = (
        tn_complete > ts_fts_complete or sup_complete > ts_fts_complete
    )
    result.requires_supersedes = sup_complete > ts_fts_complete

    return result


# ============================================================
# Reporting
# ============================================================

def print_query_table(query_results: list[QueryResult]) -> None:
    """Print a formatted comparison table to stderr."""
    methods: list[str] = [m.value for m in Method]
    col_w: int = 12

    header: str = (
        f"{'QID':<5} {'Category':<11} {'Truth':>5} | "
        + " | ".join(f"{m[:col_w]:>{col_w}}" for m in methods)
        + " | Struct? | Supersedes?"
    )
    print(header, file=sys.stderr)
    print("-" * len(header), file=sys.stderr)

    for qr in query_results:
        truth_n: int = len(qr.ground_truth)
        row: str = f"{qr.query_id:<5} {qr.category.value:<11} {truth_n:>5} | "
        cells: list[str] = []
        for method_val in methods:
            mr: MethodResult = qr.method_results[method_val]
            pct: str = f"{mr.completeness * 100:.0f}%"
            n_uniq: int = len(mr.unique_ids)
            cell: str = f"{pct}+{n_uniq}u" if n_uniq else pct
            cells.append(f"{cell:>{col_w}}")
        row += " | ".join(cells)
        row += f" | {'YES':^7}" if qr.requires_structural else f" | {'NO':^7}"
        row += f" | {'YES':^11}" if qr.requires_supersedes else f" | {'NO':^11}"
        print(row, file=sys.stderr)


def print_summary(query_results: list[QueryResult]) -> None:
    """Print summary statistics."""
    n_total: int = len(query_results)
    n_structural: int = sum(1 for qr in query_results if qr.requires_structural)
    n_supersedes: int = sum(1 for qr in query_results if qr.requires_supersedes)
    n_timestamps_sufficient: int = n_total - n_structural

    print("\n=== SUMMARY ===", file=sys.stderr)
    print(f"Total queries: {n_total}", file=sys.stderr)
    print(
        f"Queries where timestamp-only is sufficient: {n_timestamps_sufficient}/{n_total}",
        file=sys.stderr,
    )
    print(
        f"Queries that REQUIRE structural edges (TEMPORAL_NEXT or SUPERSEDES): {n_structural}/{n_total}",
        file=sys.stderr,
    )
    print(
        f"Queries that specifically REQUIRE SUPERSEDES chains: {n_supersedes}/{n_total}",
        file=sys.stderr,
    )

    print("\nPer-category breakdown:", file=sys.stderr)
    cat_counts: dict[str, dict[str, int]] = {}
    for qr in query_results:
        cat: str = qr.category.value
        if cat not in cat_counts:
            cat_counts[cat] = {"total": 0, "structural": 0, "supersedes": 0}
        cat_counts[cat]["total"] += 1
        if qr.requires_structural:
            cat_counts[cat]["structural"] += 1
        if qr.requires_supersedes:
            cat_counts[cat]["supersedes"] += 1

    for cat, counts in cat_counts.items():
        print(
            f"  {cat}: {counts['structural']}/{counts['total']} need structural, "
            f"{counts['supersedes']}/{counts['total']} need SUPERSEDES",
            file=sys.stderr,
        )

    # Average completeness per method per category
    print("\nAverage completeness by method:", file=sys.stderr)
    for method_val in [m.value for m in Method]:
        scores: list[float] = [
            qr.method_results[method_val].completeness
            for qr in query_results
            if method_val in qr.method_results
        ]
        avg: float = sum(scores) / len(scores) if scores else 0.0
        print(f"  {method_val}: {avg * 100:.1f}%", file=sys.stderr)


# ============================================================
# Main
# ============================================================

def main() -> None:
    """Run Exp 59: Traversal Utility of TEMPORAL_NEXT Edges."""
    print("=== Exp 59: Traversal Utility of TEMPORAL_NEXT Edges ===\n",
          file=sys.stderr)

    # Load data
    print("[1/4] Loading alpha-seek DB...", file=sys.stderr)
    conn: sqlite3.Connection = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    milestone_ts: dict[str, float] = load_milestone_timestamps(conn)
    decisions: dict[str, Decision] = load_decisions(conn)
    derive_decision_timestamps(decisions, conn, milestone_ts)
    mem_edges: list[tuple[str, str, str, float]] = load_mem_edges(conn)
    conn.close()

    n_linked: int = sum(1 for d in decisions.values() if d.timestamp_days >= 0)
    print(
        f"    Loaded {len(decisions)} decisions, {n_linked} with timestamps, "
        f"{len(milestone_ts)} milestones",
        file=sys.stderr,
    )

    # Build temporal graph
    print("[2/4] Building temporal graph...", file=sys.stderr)
    graph: TemporalGraph = build_temporal_graph(decisions, mem_edges)

    n_tn_edges: int = sum(
        1 for edges in graph.out_edges.values()
        for e in edges if e.edge_type == "TEMPORAL_NEXT"
    )
    n_sup_edges: int = sum(
        1 for edges in graph.out_edges.values()
        for e in edges if e.edge_type == "SUPERSEDES"
    )
    n_cites_edges: int = sum(
        1 for edges in graph.out_edges.values()
        for e in edges if e.edge_type == "CITES"
    )
    print(
        f"    Graph: {len(graph.sorted_ids)} nodes, {n_tn_edges} TEMPORAL_NEXT edges, "
        f"{n_sup_edges} SUPERSEDES edges, {n_cites_edges} CITES edges",
        file=sys.stderr,
    )

    # Build FTS5 index
    print("[3/4] Building FTS5 index...", file=sys.stderr)
    fts_conn: sqlite3.Connection = build_fts5_index(decisions)
    print(f"    FTS5 index built over {len(decisions)} decisions", file=sys.stderr)

    # Define ground truths
    ground_truths: dict[str, GroundTruth] = define_ground_truths(graph)

    # Query definitions
    queries: list[tuple[str, str, QueryCategory]] = [
        ("Q1",  "What decisions were made during milestone M005?",              QueryCategory.RANGE),
        ("Q2",  "What decisions were made between day 3 and day 7?",            QueryCategory.RANGE),
        ("Q3",  "What are the 5 most recent decisions?",                        QueryCategory.RANGE),
        ("Q4",  "What was decided immediately after D097?",                     QueryCategory.SEQUENCE),
        ("Q5",  "What were the 3 decisions before D157?",                       QueryCategory.SEQUENCE),
        ("Q6",  "What decisions were made in the same session as D073?",        QueryCategory.SEQUENCE),
        ("Q7",  "How did the dispatch gate protocol evolve?",                   QueryCategory.EVOLUTION),
        ("Q8",  "What is the current version of the capital decision?",         QueryCategory.EVOLUTION),
        ("Q9",  "What decisions CITE D097 and were made after it?",             QueryCategory.CAUSAL),
        ("Q10", "Trace the full correction chain for the calls/puts topic.",    QueryCategory.CAUSAL),
    ]

    # Run queries
    print("[4/4] Running queries...\n", file=sys.stderr)
    query_results: list[QueryResult] = []
    for qid, query_text, category in queries:
        gt: GroundTruth = ground_truths[qid]
        qr: QueryResult = run_query(qid, query_text, category, gt, graph, fts_conn)
        query_results.append(qr)
        print(
            f"  {qid} [{category.value}]: truth={len(gt.expected_ids)}, "
            f"TS={qr.method_results[Method.TIMESTAMP_ONLY.value].completeness*100:.0f}% "
            f"TN={qr.method_results[Method.TEMPORAL_NEXT.value].completeness*100:.0f}% "
            f"SUP={qr.method_results[Method.SUPERSEDES.value].completeness*100:.0f}% "
            f"FTS={qr.method_results[Method.FTS5_TIME.value].completeness*100:.0f}%",
            file=sys.stderr,
        )

    fts_conn.close()

    # Print comparison table
    print("\n=== PER-QUERY COMPARISON TABLE ===", file=sys.stderr)
    print("Columns: completeness% + unique_count_u", file=sys.stderr)
    print_query_table(query_results)
    print_summary(query_results)

    # Hypothesis evaluation
    print("\n=== HYPOTHESIS EVALUATION ===", file=sys.stderr)
    range_qs: list[QueryResult] = [qr for qr in query_results if qr.category == QueryCategory.RANGE]
    seq_qs: list[QueryResult] = [qr for qr in query_results if qr.category == QueryCategory.SEQUENCE]
    evol_qs: list[QueryResult] = [qr for qr in query_results if qr.category == QueryCategory.EVOLUTION]
    causal_qs: list[QueryResult] = [qr for qr in query_results if qr.category == QueryCategory.CAUSAL]

    h1_pass: bool = all(not qr.requires_structural for qr in range_qs)
    h2_pass: bool = any(qr.requires_structural for qr in seq_qs)
    h3_pass: bool = all(qr.requires_supersedes for qr in evol_qs)
    h4_pass: bool = any(qr.requires_structural for qr in causal_qs)

    print(
        f"  H1 (RANGE queries fully answerable by timestamps): "
        f"{'PASS' if h1_pass else 'FAIL'}",
        file=sys.stderr,
    )
    print(
        f"  H2 (SEQUENCE queries require TEMPORAL_NEXT): "
        f"{'PASS' if h2_pass else 'FAIL'}",
        file=sys.stderr,
    )
    print(
        f"  H3 (EVOLUTION queries require SUPERSEDES): "
        f"{'PASS' if h3_pass else 'FAIL'}",
        file=sys.stderr,
    )
    print(
        f"  H4 (CAUSAL queries require graph structure): "
        f"{'PASS' if h4_pass else 'FAIL'}",
        file=sys.stderr,
    )

    # Build results dict
    results: dict[str, object] = {
        "experiment": "exp59_traversal_utility",
        "description": (
            "Tests whether TEMPORAL_NEXT edges provide traversal value "
            "that timestamps alone cannot."
        ),
        "hypotheses": {
            "H1": {"text": "RANGE queries fully answerable by timestamps", "result": "PASS" if h1_pass else "FAIL"},
            "H2": {"text": "SEQUENCE queries require TEMPORAL_NEXT", "result": "PASS" if h2_pass else "FAIL"},
            "H3": {"text": "EVOLUTION queries require SUPERSEDES", "result": "PASS" if h3_pass else "FAIL"},
            "H4": {"text": "CAUSAL queries require graph structure", "result": "PASS" if h4_pass else "FAIL"},
        },
        "graph_stats": {
            "decisions_total": len(decisions),
            "decisions_with_timestamps": n_linked,
            "milestones": len(milestone_ts),
            "temporal_next_edges": n_tn_edges,
            "supersedes_edges": n_sup_edges,
            "cites_edges": n_cites_edges,
        },
        "queries": [
            {
                "id": qr.query_id,
                "query": qr.query_text,
                "category": qr.category.value,
                "ground_truth": qr.ground_truth,
                "ground_truth_size": len(qr.ground_truth),
                "requires_structural": qr.requires_structural,
                "requires_supersedes": qr.requires_supersedes,
                "methods": {
                    method_val: {
                        "found_ids": mr.found_ids,
                        "completeness": round(mr.completeness, 4),
                        "unique_ids": mr.unique_ids,
                        "structural_insight": mr.structural_insight,
                    }
                    for method_val, mr in qr.method_results.items()
                },
            }
            for qr in query_results
        ],
        "summary": {
            "total_queries": len(query_results),
            "timestamp_sufficient": sum(1 for qr in query_results if not qr.requires_structural),
            "requires_structural": sum(1 for qr in query_results if qr.requires_structural),
            "requires_supersedes": sum(1 for qr in query_results if qr.requires_supersedes),
            "avg_completeness_by_method": {
                method_val: round(
                    sum(qr.method_results[method_val].completeness for qr in query_results)
                    / len(query_results),
                    4,
                )
                for method_val in [m.value for m in Method]
            },
        },
    }

    RESULTS_PATH.write_text(json.dumps(results, indent=2))
    print(f"\nResults written to {RESULTS_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
