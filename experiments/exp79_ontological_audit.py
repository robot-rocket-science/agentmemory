"""Experiment 79: Statement/Belief Ontological Audit.

Classifies each current "belief" in the database as either:
  - STATEMENT: a raw proposition about the world (factual claim, requirement, procedure)
  - AGENT_VIEW: an assessment, stance, or meta-cognitive item about the agent's own state

Measures the split to validate the hypothesis that nearly all stored items
are statements, not beliefs in the epistemological sense.

Success criteria:
  - >90% of stored items classified as STATEMENT (raw propositions)
  - <10% classified as AGENT_VIEW (meta-cognitive, self-referential)
  - Clear pattern differences between types (corrections vs factual vs requirements)
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH: str = str(
    Path.home() / ".agentmemory" / "projects" / "2e7ed55e017a" / "memory.db"
)

# Heuristic patterns that suggest agent-view (meta-cognitive) content
AGENT_VIEW_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bagent\s+(should|must|needs to|believes|thinks)\b", re.IGNORECASE),
    re.compile(r"\b(I believe|I think|my assessment|my view)\b", re.IGNORECASE),
    re.compile(r"\b(confidence|uncertainty|credence)\s+(is|was|should be)\b", re.IGNORECASE),
    re.compile(r"\bthe (system|memory|agent) (has|had|shows|demonstrates)\b", re.IGNORECASE),
    re.compile(r"\b(meta-cognit|self-assess|introspect)\b", re.IGNORECASE),
    re.compile(r"\bbelief\s+(about|regarding|concerning)\b", re.IGNORECASE),
    re.compile(r"\b(retrieval|scoring|ranking)\s+(quality|performance|accuracy)\b", re.IGNORECASE),
    re.compile(r"\b(explore|exploration)\s+(weight|bonus|rate)\b", re.IGNORECASE),
]

# Patterns that strongly suggest statement (proposition about the world)
STATEMENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\buse\s+(uv|npm|pip|docker|git)\b", re.IGNORECASE),
    re.compile(r"\b(always|never|must|should)\s+(use|run|add|check|test)\b", re.IGNORECASE),
    re.compile(r"\b(file|table|column|function|class|module)\s+(is|was|has|contains)\b", re.IGNORECASE),
    re.compile(r"\b(bug|fix|error|issue)\s+(in|with|when|if)\b", re.IGNORECASE),
    re.compile(r"\b(tested|validated|confirmed|verified)\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class ClassifiedItem:
    belief_id: str
    content: str
    belief_type: str
    source_type: str
    locked: bool
    classification: str  # STATEMENT or AGENT_VIEW
    matched_pattern: str  # which pattern triggered classification
    confidence_score: float  # how confident the heuristic is


@dataclass
class AuditResults:
    total: int
    statement_count: int
    agent_view_count: int
    ambiguous_count: int
    by_belief_type: dict[str, dict[str, int]]
    by_source_type: dict[str, dict[str, int]]
    by_locked: dict[str, dict[str, int]]
    agent_view_examples: list[ClassifiedItem]
    ambiguous_examples: list[ClassifiedItem]


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_item(
    belief_id: str,
    content: str,
    belief_type: str,
    source_type: str,
    locked: bool,
) -> ClassifiedItem:
    """Classify a single stored item as STATEMENT or AGENT_VIEW."""
    agent_score: float = 0.0
    statement_score: float = 0.0
    agent_matches: list[str] = []
    statement_matches: list[str] = []

    for pattern in AGENT_VIEW_PATTERNS:
        if pattern.search(content):
            agent_score += 1.0
            agent_matches.append(pattern.pattern)

    for pattern in STATEMENT_PATTERNS:
        if pattern.search(content):
            statement_score += 1.0
            statement_matches.append(pattern.pattern)

    # Type-based priors: corrections and requirements are almost always statements
    if belief_type in ("correction", "requirement", "preference"):
        statement_score += 0.5

    # Content-based heuristics for agent-view detection
    # These check whether the content is ABOUT the agent/system vs ABOUT the project
    content_lower = content.lower()
    is_code_artifact = content.startswith("def ") or content.startswith("class ") or "::" in content[:50]
    is_meta_about_system = any(w in content_lower for w in [
        "the memory system", "the scoring function", "retrieval quality",
        "the agent should", "exploration weight", "thompson sampling",
        "feedback loop", "the pipeline", "the classifier",
    ])
    is_about_experiments = any(w in content_lower for w in [
        "exp ", "experiment ", "hypothesis", "we measured", "the test shows",
        "baseline comparison", "precision@", "ndcg", "mrr",
    ])

    if is_code_artifact:
        statement_score += 1.0  # code defs are propositions about structure
    if is_meta_about_system:
        agent_score += 1.0  # meta-cognitive about the system itself
    if is_about_experiments:
        # Experiment findings are statements about results, not agent views
        statement_score += 0.5

    # Classify
    total: float = agent_score + statement_score
    if total == 0:
        # No patterns matched -- default to STATEMENT (raw proposition)
        return ClassifiedItem(
            belief_id=belief_id,
            content=content,
            belief_type=belief_type,
            source_type=source_type,
            locked=locked,
            classification="STATEMENT",
            matched_pattern="default (no pattern match)",
            confidence_score=0.5,
        )

    agent_ratio: float = agent_score / total
    if agent_ratio > 0.6:
        classification = "AGENT_VIEW"
    elif agent_ratio < 0.4:
        classification = "STATEMENT"
    else:
        classification = "AMBIGUOUS"

    matched: str = "; ".join(agent_matches[:2]) if agent_matches else "; ".join(statement_matches[:2])
    return ClassifiedItem(
        belief_id=belief_id,
        content=content,
        belief_type=belief_type,
        source_type=source_type,
        locked=locked,
        classification=classification,
        matched_pattern=matched,
        confidence_score=abs(agent_ratio - 0.5) + 0.5,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_audit() -> AuditResults:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, content, belief_type, source_type, locked
        FROM beliefs
        WHERE valid_to IS NULL
        ORDER BY created_at DESC
    """)

    rows: list[sqlite3.Row] = cursor.fetchall()
    conn.close()

    classified: list[ClassifiedItem] = []
    for row in rows:
        item = classify_item(
            belief_id=row["id"],
            content=row["content"],
            belief_type=row["belief_type"],
            source_type=row["source_type"],
            locked=bool(row["locked"]),
        )
        classified.append(item)

    # Aggregate
    total: int = len(classified)
    statement_count: int = sum(1 for c in classified if c.classification == "STATEMENT")
    agent_view_count: int = sum(1 for c in classified if c.classification == "AGENT_VIEW")
    ambiguous_count: int = sum(1 for c in classified if c.classification == "AMBIGUOUS")

    by_belief_type: dict[str, dict[str, int]] = {}
    by_source_type: dict[str, dict[str, int]] = {}
    by_locked: dict[str, dict[str, int]] = {"locked": Counter(), "unlocked": Counter()}  # type: ignore[dict-item]

    for c in classified:
        bt = c.belief_type
        st = c.source_type
        if bt not in by_belief_type:
            by_belief_type[bt] = Counter()
        by_belief_type[bt][c.classification] += 1  # type: ignore[index]

        if st not in by_source_type:
            by_source_type[st] = Counter()
        by_source_type[st][c.classification] += 1  # type: ignore[index]

        lock_key = "locked" if c.locked else "unlocked"
        by_locked[lock_key][c.classification] += 1  # type: ignore[index]

    agent_view_examples = [c for c in classified if c.classification == "AGENT_VIEW"][:20]
    ambiguous_examples = [c for c in classified if c.classification == "AMBIGUOUS"][:20]

    return AuditResults(
        total=total,
        statement_count=statement_count,
        agent_view_count=agent_view_count,
        ambiguous_count=ambiguous_count,
        by_belief_type=by_belief_type,
        by_source_type=by_source_type,
        by_locked=by_locked,
        agent_view_examples=agent_view_examples,
        ambiguous_examples=ambiguous_examples,
    )


def main() -> None:
    results = run_audit()

    print("=" * 70)
    print("EXPERIMENT 79: STATEMENT/BELIEF ONTOLOGICAL AUDIT")
    print("=" * 70)

    stmt_pct: float = results.statement_count / results.total * 100
    av_pct: float = results.agent_view_count / results.total * 100
    amb_pct: float = results.ambiguous_count / results.total * 100

    print(f"\nTotal active items: {results.total}")
    print(f"  STATEMENT:  {results.statement_count:>6} ({stmt_pct:.1f}%)")
    print(f"  AGENT_VIEW: {results.agent_view_count:>6} ({av_pct:.1f}%)")
    print(f"  AMBIGUOUS:  {results.ambiguous_count:>6} ({amb_pct:.1f}%)")

    print(f"\nSuccess criterion: >90% STATEMENT? {'PASS' if stmt_pct > 90 else 'FAIL'} ({stmt_pct:.1f}%)")

    print("\n--- By belief_type ---")
    for bt, counts in sorted(results.by_belief_type.items()):
        total_bt: int = sum(counts.values())
        parts: list[str] = []
        for cls in ["STATEMENT", "AGENT_VIEW", "AMBIGUOUS"]:
            n: int = counts.get(cls, 0)
            if n > 0:
                parts.append(f"{cls}={n} ({n/total_bt*100:.1f}%)")
        print(f"  {bt:>15}: {total_bt:>6}  {', '.join(parts)}")

    print("\n--- By source_type ---")
    for st, counts in sorted(results.by_source_type.items()):
        total_st: int = sum(counts.values())
        parts = []
        for cls in ["STATEMENT", "AGENT_VIEW", "AMBIGUOUS"]:
            n = counts.get(cls, 0)
            if n > 0:
                parts.append(f"{cls}={n} ({n/total_st*100:.1f}%)")
        print(f"  {st:>20}: {total_st:>6}  {', '.join(parts)}")

    print("\n--- By locked status ---")
    for lk, counts in results.by_locked.items():
        total_lk: int = sum(counts.values())
        parts = []
        for cls in ["STATEMENT", "AGENT_VIEW", "AMBIGUOUS"]:
            n = counts.get(cls, 0)
            if n > 0:
                parts.append(f"{cls}={n} ({n/total_lk*100:.1f}%)")
        print(f"  {lk:>10}: {total_lk:>6}  {', '.join(parts)}")

    if results.agent_view_examples:
        print(f"\n--- AGENT_VIEW examples (first {len(results.agent_view_examples)}) ---")
        for ex in results.agent_view_examples[:10]:
            snippet: str = ex.content[:100].replace("\n", " ")
            print(f"  [{ex.belief_type}] {snippet}...")
            print(f"    pattern: {ex.matched_pattern}")

    if results.ambiguous_examples:
        print(f"\n--- AMBIGUOUS examples (first {len(results.ambiguous_examples)}) ---")
        for ex in results.ambiguous_examples[:10]:
            snippet = ex.content[:100].replace("\n", " ")
            print(f"  [{ex.belief_type}] {snippet}...")
            print(f"    pattern: {ex.matched_pattern}")


if __name__ == "__main__":
    main()
