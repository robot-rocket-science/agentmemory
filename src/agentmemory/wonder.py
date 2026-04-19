"""Exploratory wonder: gap analysis, speculative belief generation, and GC.

This module implements the "exploratory wonder" mechanic: wonder identifies
what the belief graph does NOT know about a topic, generates research axes
for parallel subagent investigation, ingests speculative beliefs from
subagent results, and garbage-collects stale speculation.

The flow:
    1. wonder() - internal search + gap analysis -> structured output
    2. Skill layer spawns N subagents with orthogonal research axes
    3. wonder_ingest() - run subagent research docs through the ingest pipeline,
       tagging all resulting beliefs as speculative/wonder_generated
    4. wonder_gc() - TTL-based cleanup of unaccessed/unconfirmed speculative beliefs
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final

from agentmemory.models import (
    EDGE_RELATES_TO,
    Belief,
    Edge,
)
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.scoring import uncertainty_score
from agentmemory.store import MemoryStore
from agentmemory.uncertainty import UncertaintyVector

log: logging.Logger = logging.getLogger(__name__)

# --- Constants ---

DEFAULT_AGENT_COUNT: Final[int] = 4
MAX_AGENT_COUNT: Final[int] = 8
MIN_AGENT_COUNT: Final[int] = 1
SPECULATIVE_TTL_DAYS: Final[int] = (
    14  # days before unaccessed speculative beliefs decay
)
GC_BATCH_SIZE: Final[int] = 500  # max beliefs to GC per call


# --- Data structures ---


@dataclass
class GapAnalysis:
    """What the graph knows and doesn't know about a query."""

    query: str
    known_beliefs: list[Belief]
    high_uncertainty: list[tuple[Belief, float]]
    contradictions: list[tuple[Belief, Belief]]
    coverage_score: float  # 0.0 = no coverage, 1.0 = fully covered
    identified_gaps: list[str]  # natural language gap descriptions


@dataclass
class ResearchAxis:
    """A direction for a subagent to investigate."""

    axis_id: int
    name: str
    description: str
    search_hints: list[str]  # suggested search terms / angles
    gap_context: str  # which gap this axis addresses


@dataclass
class WonderResult:
    """Complete output from a wonder call."""

    gap_analysis: GapAnalysis
    research_axes: list[ResearchAxis]
    agent_count: int
    speculative_ids: list[
        str
    ]  # IDs of speculative beliefs created from internal analysis


@dataclass
class WonderIngestResult:
    """Result of ingesting research documents as speculative beliefs."""

    beliefs_created: int
    beliefs_tagged: int  # beliefs successfully retagged as speculative
    documents_processed: int
    anchor_edges_created: int


@dataclass
class GCResult:
    """Result of garbage-collecting stale speculative beliefs."""

    scanned: int
    deleted: int
    surviving: int


# --- Core functions ---


def analyze_gaps(
    store: MemoryStore,
    query: str,
    budget: int = 2000,
    depth: int = 2,
) -> GapAnalysis:
    """Analyze what the belief graph knows and doesn't know about a query.

    Returns a GapAnalysis with coverage scoring and identified knowledge gaps.
    """
    # Step 1: Retrieve what we know
    result: RetrievalResult = retrieve(store, query, budget=budget)

    if not result.beliefs:
        return GapAnalysis(
            query=query,
            known_beliefs=[],
            high_uncertainty=[],
            contradictions=[],
            coverage_score=0.0,
            identified_gaps=[
                f"No beliefs found for query: {query}",
                "The memory system has no context on this topic.",
            ],
        )

    # Step 2: Graph expansion from top seeds
    seed_ids: list[str] = [b.id for b in result.beliefs[:10]]
    expanded = store.expand_graph(seed_ids, depth=depth)

    # Merge all beliefs
    all_beliefs: dict[str, Belief] = {b.id: b for b in result.beliefs}
    for _bid, exp_neighbors in expanded.items():
        for neighbor_belief, _edge_type, _hop in exp_neighbors:
            if neighbor_belief.id not in all_beliefs:
                all_beliefs[neighbor_belief.id] = neighbor_belief

    # Step 3: Compute uncertainty
    high_uncertainty: list[tuple[Belief, float]] = []
    for bid, b in all_beliefs.items():
        unc: float = uncertainty_score(b.alpha, b.beta_param)
        if unc > 0.7:
            high_uncertainty.append((b, unc))
    high_uncertainty.sort(key=lambda x: x[1], reverse=True)

    # Step 4: Detect contradictions
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

    # Step 5: Compute coverage score
    # Coverage = proportion of query terms that appear in at least one belief
    query_terms: list[str] = [t.lower() for t in query.split() if len(t) >= 3]
    if query_terms:
        covered: int = 0
        for term in query_terms:
            for b in all_beliefs.values():
                if term in b.content.lower():
                    covered += 1
                    break
        coverage_score: float = covered / len(query_terms)
    else:
        coverage_score = 0.0

    # Step 6: Identify gaps
    gaps: list[str] = _identify_gaps(
        query,
        query_terms,
        all_beliefs,
        high_uncertainty,
        contradictions,
        coverage_score,
    )

    return GapAnalysis(
        query=query,
        known_beliefs=result.beliefs,
        high_uncertainty=high_uncertainty,
        contradictions=contradictions,
        coverage_score=coverage_score,
        identified_gaps=gaps,
    )


def _identify_gaps(
    query: str,
    query_terms: list[str],
    all_beliefs: dict[str, Belief],
    high_uncertainty: list[tuple[Belief, float]],
    contradictions: list[tuple[Belief, Belief]],
    coverage_score: float,
) -> list[str]:
    """Identify knowledge gaps from the analysis."""
    gaps: list[str] = []

    # Gap type 1: uncovered query terms
    if query_terms:
        uncovered: list[str] = []
        for term in query_terms:
            found: bool = False
            for b in all_beliefs.values():
                if term in b.content.lower():
                    found = True
                    break
            if not found:
                uncovered.append(term)
        if uncovered:
            gaps.append(f"Query terms with no belief coverage: {', '.join(uncovered)}")

    # Gap type 2: low overall coverage
    if coverage_score < 0.3:
        gaps.append(
            f"Very low topic coverage ({coverage_score:.0%}). "
            "This topic is largely unexplored in the belief graph."
        )
    elif coverage_score < 0.6:
        gaps.append(
            f"Partial topic coverage ({coverage_score:.0%}). "
            "Some aspects of this topic are not represented."
        )

    # Gap type 3: high uncertainty in existing beliefs
    if high_uncertainty:
        uncertain_topics: list[str] = [
            b.content[:80] for b, _unc in high_uncertainty[:3]
        ]
        gaps.append(
            f"{len(high_uncertainty)} belief(s) with high uncertainty: "
            + "; ".join(uncertain_topics)
        )

    # Gap type 4: unresolved contradictions
    if contradictions:
        gaps.append(
            f"{len(contradictions)} unresolved contradiction(s) "
            "need evidence to determine which branch is correct."
        )

    # Gap type 5: all beliefs are agent-inferred (no user validation)
    agent_only: int = sum(
        1 for b in all_beliefs.values() if b.source_type == "agent_inferred"
    )
    total: int = len(all_beliefs)
    if total > 0 and agent_only / total > 0.9:
        gaps.append(
            f"{agent_only}/{total} beliefs are agent-inferred with no user validation."
        )

    if not gaps:
        gaps.append("No significant knowledge gaps identified.")

    return gaps


def generate_research_axes(
    gap_analysis: GapAnalysis,
    agent_count: int = DEFAULT_AGENT_COUNT,
) -> list[ResearchAxis]:
    """Generate orthogonal research directions for subagents.

    Each axis targets a different aspect of the query and its gaps.
    The axes are designed to produce complementary, non-overlapping results.
    """
    agent_count = max(MIN_AGENT_COUNT, min(MAX_AGENT_COUNT, agent_count))

    query: str = gap_analysis.query
    gaps: list[str] = gap_analysis.identified_gaps
    has_contradictions: bool = len(gap_analysis.contradictions) > 0
    has_uncertainty: bool = len(gap_analysis.high_uncertainty) > 0

    axes: list[ResearchAxis] = []

    # Axis 1 (always): Domain research -- what does the broader world know?
    axes.append(
        ResearchAxis(
            axis_id=1,
            name="Domain Research",
            description=(
                f"Research the current state of knowledge about: {query}. "
                "Focus on best practices, known pitfalls, recent developments, "
                "and authoritative sources. Use web search and documentation lookups."
            ),
            search_hints=_extract_search_hints(query, gap_analysis),
            gap_context=gaps[0] if gaps else "General exploration",
        )
    )

    # Axis 2 (always): Internal gap analysis -- what is the graph missing?
    axes.append(
        ResearchAxis(
            axis_id=2,
            name="Gap Analysis",
            description=(
                "Examine the belief graph's coverage of this topic and identify "
                "structural holes. Look for: isolated belief clusters that should "
                "be connected, topics referenced but never explained, decisions "
                "made without documented rationale, and assumptions that were "
                "never tested."
            ),
            search_hints=[
                "missing connections",
                "undocumented decisions",
                "untested assumptions",
                "orphan beliefs",
            ],
            gap_context="\n".join(gaps),
        )
    )

    if agent_count >= 3:
        # Axis 3: Contrarian -- argue against the implied premise
        axes.append(
            ResearchAxis(
                axis_id=3,
                name="Contrarian Analysis",
                description=(
                    f"Argue AGAINST the premise implied by: {query}. "
                    "Find reasons this approach might fail, alternatives that "
                    "might be better, risks that haven't been considered, and "
                    "evidence that contradicts the current direction. Be specific "
                    "and cite sources."
                ),
                search_hints=["risks", "alternatives", "failure modes", "tradeoffs"],
                gap_context="Deliberately orthogonal to current assumptions",
            )
        )

    if agent_count >= 4:
        # Axis 4: Analogical -- how do similar systems solve this?
        axes.append(
            ResearchAxis(
                axis_id=4,
                name="Analogical Research",
                description=(
                    f"Find analogous problems in related domains and how they "
                    f"were solved. The topic is: {query}. Look at adjacent fields, "
                    "similar systems, comparable architectures, and established "
                    "patterns from other projects or industries."
                ),
                search_hints=["similar systems", "prior art", "design patterns"],
                gap_context="Cross-domain knowledge transfer",
            )
        )

    if agent_count >= 5:
        # Axis 5: Contradiction resolution (if contradictions exist)
        if has_contradictions:
            contradiction_desc: str = "; ".join(
                f'"{a.content[:60]}" vs "{b.content[:60]}"'
                for a, b in gap_analysis.contradictions[:3]
            )
            axes.append(
                ResearchAxis(
                    axis_id=5,
                    name="Contradiction Resolution",
                    description=(
                        f"Resolve these contradictions in the belief graph: "
                        f"{contradiction_desc}. Find evidence that supports one "
                        "side over the other."
                    ),
                    search_hints=["evidence", "resolution", "which is correct"],
                    gap_context="Unresolved contradictions",
                )
            )
        elif has_uncertainty:
            axes.append(
                ResearchAxis(
                    axis_id=5,
                    name="Uncertainty Reduction",
                    description=(
                        "Focus on the highest-uncertainty beliefs and find evidence "
                        "to confirm or refute them. Prioritize beliefs where a "
                        "definitive answer would unblock other decisions."
                    ),
                    search_hints=["verification", "evidence", "confirmation"],
                    gap_context="High-uncertainty beliefs need evidence",
                )
            )
        else:
            axes.append(
                ResearchAxis(
                    axis_id=5,
                    name="Future Implications",
                    description=(
                        f"Explore the future implications and downstream effects of: "
                        f"{query}. What second-order consequences might arise? What "
                        "should be planned for now?"
                    ),
                    search_hints=["implications", "consequences", "future"],
                    gap_context="Forward-looking analysis",
                )
            )

    # Axes 6-8: additional if agent_count > 5
    extra_axes: list[tuple[str, str]] = [
        (
            "Implementation Patterns",
            "Find concrete implementation examples, code patterns, and technical approaches",
        ),
        (
            "Ecosystem Survey",
            "Survey the ecosystem of tools, libraries, and services relevant to this topic",
        ),
        (
            "Historical Context",
            "Research the history and evolution of approaches to this problem",
        ),
    ]
    for i, (name, desc) in enumerate(extra_axes):
        if len(axes) >= agent_count:
            break
        axes.append(
            ResearchAxis(
                axis_id=6 + i,
                name=name,
                description=f"{desc} for: {query}",
                search_hints=[],
                gap_context="Extended exploration",
            )
        )

    return axes[:agent_count]


def _extract_search_hints(query: str, gap_analysis: GapAnalysis) -> list[str]:
    """Extract useful search terms from the query and gap analysis."""
    hints: list[str] = []

    # Add significant query words
    for word in query.split():
        if len(word) >= 4 and word.lower() not in {
            "what",
            "when",
            "where",
            "which",
            "about",
            "should",
            "could",
            "would",
            "there",
            "their",
            "these",
            "those",
            "have",
            "with",
            "from",
            "this",
            "that",
            "been",
            "being",
            "does",
            "into",
        }:
            hints.append(word.lower())

    # Add terms from uncovered gaps
    for gap in gap_analysis.identified_gaps:
        if "no belief coverage" in gap:
            # Extract the uncovered terms
            parts: list[str] = gap.split(":")
            if len(parts) > 1:
                terms: list[str] = [t.strip() for t in parts[-1].split(",")]
                hints.extend(terms)

    return hints[:10]


def wonder(
    store: MemoryStore,
    query: str,
    agent_count: int = DEFAULT_AGENT_COUNT,
    budget: int = 2000,
    depth: int = 2,
) -> WonderResult:
    """Run exploratory wonder: internal search + gap analysis + research axes.

    Returns structured output for the skill layer to use when spawning subagents.
    """
    # Phase 1: Gap analysis (includes internal search)
    gap_analysis: GapAnalysis = analyze_gaps(store, query, budget=budget, depth=depth)

    # Phase 2: Generate research axes
    axes: list[ResearchAxis] = generate_research_axes(
        gap_analysis, agent_count=agent_count
    )

    # Phase 3: Create anchor speculative beliefs from internal analysis
    speculative_ids: list[str] = _create_internal_speculative(store, gap_analysis)

    return WonderResult(
        gap_analysis=gap_analysis,
        research_axes=axes,
        agent_count=agent_count,
        speculative_ids=speculative_ids,
    )


def _create_internal_speculative(
    store: MemoryStore,
    gap_analysis: GapAnalysis,
) -> list[str]:
    """Create speculative belief nodes from internal gap analysis.

    These serve as anchor points for subagent results to connect to.
    """
    spec_ids: list[str] = []
    anchor_id: str | None = (
        gap_analysis.known_beliefs[0].id if gap_analysis.known_beliefs else None
    )

    # One speculative node per significant gap
    for gap_text in gap_analysis.identified_gaps[:5]:
        if gap_text == "No significant knowledge gaps identified.":
            continue

        uv: UncertaintyVector = UncertaintyVector()
        spec: Belief = store.insert_speculative_belief(
            content=f"[gap] {gap_text}",
            uncertainty_vector_json=uv.to_json(),
            source_belief_id=anchor_id,
            session_id=None,
        )
        spec_ids.append(spec.id)

    # If no gaps but we have the query, create an open question node
    if not spec_ids and anchor_id is not None:
        uv = UncertaintyVector()
        spec = store.insert_speculative_belief(
            content=f"[open question] {gap_analysis.query}",
            uncertainty_vector_json=uv.to_json(),
            source_belief_id=anchor_id,
            session_id=None,
        )
        spec_ids.append(spec.id)

    return spec_ids


def wonder_ingest(
    store: MemoryStore,
    research_documents: list[tuple[str, int]],
    anchor_belief_ids: list[str] | None = None,
    session_id: str | None = None,
) -> WonderIngestResult:
    """Ingest subagent research documents as speculative beliefs.

    Each research document (text, axis_id) is run through the standard ingest
    pipeline. All resulting beliefs are then retagged as speculative with
    source_type=wonder_generated and low confidence priors (alpha=0.3, beta=1.0).

    This produces high-volume speculative belief trees: a ~500 word document
    typically generates 50-100 beliefs, all tagged for GC expiration.

    Args:
        store: Memory store instance.
        research_documents: List of (document_text, axis_id) tuples from subagents.
        anchor_belief_ids: Optional belief IDs to create RELATES_TO edges to.
        session_id: Session that triggered this wonder call.
    """
    from agentmemory.ingest import ingest_turn

    result: WonderIngestResult = WonderIngestResult(
        beliefs_created=0,
        beliefs_tagged=0,
        documents_processed=0,
        anchor_edges_created=0,
    )

    conn: sqlite3.Connection = store._conn  # pyright: ignore[reportPrivateUsage]

    for doc_text, axis_id in research_documents:
        if not doc_text.strip():
            continue

        # Step 1: Snapshot existing belief IDs so we can identify new ones
        existing_ids: set[str] = {
            row[0]
            for row in conn.execute(
                "SELECT id FROM beliefs WHERE valid_to IS NULL"
            ).fetchall()
        }

        # Step 2: Run through standard ingest pipeline
        # This handles sentence extraction, classification, dedup, and belief creation
        ingest_result = ingest_turn(
            store=store,
            text=doc_text,
            source="agent",
            session_id=session_id,
            source_path=f"wonder_axis_{axis_id}",
            source_id=f"wonder_axis_{axis_id}",
            bulk=True,  # skip per-belief relationship checks (we do our own)
        )
        result.beliefs_created += ingest_result.beliefs_created
        result.documents_processed += 1

        # Step 3: Find beliefs created by this ingest (new IDs not in snapshot)
        new_ids: list[str] = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM beliefs WHERE valid_to IS NULL"
            ).fetchall()
            if row[0] not in existing_ids
        ]

        # Step 4: Retag new beliefs as speculative
        tagged: int = 0
        for belief_id in new_ids:
            # Note: confidence is a generated column (alpha/(alpha+beta_param)),
            # so we only update alpha and beta_param directly.
            conn.execute(
                """UPDATE beliefs
                   SET belief_type = 'speculative',
                       source_type = 'wonder_generated',
                       alpha = 0.3,
                       beta_param = 1.0,
                       temporal_direction = 'forward',
                       data_source = ?
                   WHERE id = ?
                     AND locked = 0""",
                (f"wonder_axis_{axis_id}", belief_id),
            )
            if conn.execute("SELECT changes()").fetchone()[0] > 0:
                tagged += 1

                # Create edges to anchor beliefs
                if anchor_belief_ids:
                    for anchor_id in anchor_belief_ids:
                        if not store.edge_exists(belief_id, anchor_id):
                            store.insert_edge(
                                belief_id,
                                anchor_id,
                                EDGE_RELATES_TO,
                                0.5,
                                reason=f"wonder_axis_{axis_id}",
                            )
                            result.anchor_edges_created += 1

        conn.commit()
        result.beliefs_tagged += tagged
        log.info(
            "wonder_ingest axis %d: %d beliefs created, %d tagged speculative",
            axis_id,
            ingest_result.beliefs_created,
            tagged,
        )

    return result


def wonder_gc(
    store: MemoryStore,
    ttl_days: int = SPECULATIVE_TTL_DAYS,
    dry_run: bool = False,
) -> GCResult:
    """Garbage-collect stale speculative beliefs.

    Deletes speculative beliefs that:
    - Are older than ttl_days
    - Have never been accessed (no feedback recorded)
    - Have not been promoted (still source_type in wonder_generated/agent_inferred
      and belief_type == speculative)
    - Are not connected to any non-speculative beliefs via RESOLVES edges

    Beliefs that have been accessed via feedback or promoted to a real type
    are preserved regardless of age.
    """
    cutoff: datetime = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    cutoff_str: str = cutoff.isoformat()

    # Find candidate speculative beliefs
    conn: sqlite3.Connection = store._conn  # pyright: ignore[reportPrivateUsage]
    rows: list[sqlite3.Row] = conn.execute(
        """SELECT b.id, b.content, b.created_at, b.source_type, b.belief_type,
                  b.alpha, b.beta_param
           FROM beliefs b
           WHERE b.belief_type = 'speculative'
             AND b.source_type IN ('wonder_generated', 'agent_inferred')
             AND b.valid_to IS NULL
             AND b.created_at < ?
             AND b.locked = 0
           ORDER BY b.created_at ASC
           LIMIT ?""",
        (cutoff_str, GC_BATCH_SIZE),
    ).fetchall()

    scanned: int = len(rows)
    deleted: int = 0

    for row in rows:
        belief_id: str = str(row["id"])

        # Check if this belief has been resolved (connected to evidence)
        resolves_edges: list[tuple[Belief, Edge]] = store.get_neighbors(
            belief_id,
            edge_types=["RESOLVES"],
            direction="both",
        )
        if resolves_edges:
            continue  # has evidence, keep it

        # Check if confidence has changed from default (someone updated it)
        alpha: float = float(row["alpha"]) if row["alpha"] is not None else 1.0
        beta_param: float = (
            float(row["beta_param"]) if row["beta_param"] is not None else 1.0
        )
        # Default speculative: alpha=1.0/0.3, beta=1.0
        # If someone has provided evidence, alpha or beta will have changed
        if alpha > 1.5 or beta_param > 1.5:
            continue  # evidence has been applied, keep it

        deleted += 1
        if not dry_run:
            # Soft-delete: set valid_to
            conn.execute(
                "UPDATE beliefs SET valid_to = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), belief_id),
            )

    if not dry_run and deleted > 0:
        conn.commit()

    return GCResult(
        scanned=scanned,
        deleted=deleted,
        surviving=scanned - deleted,
    )


# --- Serialization for MCP tool output ---


def wonder_result_to_dict(result: WonderResult) -> dict[str, object]:
    """Serialize WonderResult for MCP tool JSON output."""
    ga: GapAnalysis = result.gap_analysis
    return {
        "query": ga.query,
        "coverage_score": round(ga.coverage_score, 3),
        "known_belief_count": len(ga.known_beliefs),
        "known_beliefs": [
            {
                "id": b.id,
                "content": b.content[:200],
                "confidence": round(b.confidence, 3),
                "type": b.belief_type,
                "locked": b.locked,
            }
            for b in ga.known_beliefs[:15]
        ],
        "high_uncertainty": [
            {
                "id": b.id,
                "content": b.content[:200],
                "uncertainty": round(unc, 3),
            }
            for b, unc in ga.high_uncertainty[:5]
        ],
        "contradictions": [
            {
                "a": {"id": a.id, "content": a.content[:150]},
                "b": {"id": b.id, "content": b.content[:150]},
            }
            for a, b in ga.contradictions[:5]
        ],
        "identified_gaps": ga.identified_gaps,
        "research_axes": [
            {
                "axis_id": ax.axis_id,
                "name": ax.name,
                "description": ax.description,
                "search_hints": ax.search_hints,
                "gap_context": ax.gap_context,
            }
            for ax in result.research_axes
        ],
        "agent_count": result.agent_count,
        "speculative_ids": result.speculative_ids,
    }
