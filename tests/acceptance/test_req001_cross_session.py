"""REQ-001: Cross-session decision retention >= 80%.

Pass criterion: After inserting 10 diverse locked decisions in session 1 and
simulating 4 additional sessions, at least 8 of 10 decisions are retrievable
in session 5 via targeted search.
"""
from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BELIEF_PROCEDURAL,
    BELIEF_REQUIREMENT,
    BSRC_USER_STATED,
    Belief,
    Session,
)
from agentmemory.store import MemoryStore

# (belief_content, fts5_query, required_keyword_in_result) tuples.
# FTS5 AND semantics: every token in the query must appear in the belief.
# Queries use tokens that are verbatim present in the belief content.
_DECISIONS: list[tuple[str, str, str]] = [
    ("Database is PostgreSQL", "database PostgreSQL", "PostgreSQL"),
    ("Frontend uses React with TypeScript", "frontend React TypeScript", "React"),
    ("API follows REST conventions", "API REST conventions", "REST"),
    ("Tests use pytest with fixtures", "pytest fixtures", "pytest"),
    ("Deploy to AWS ECS via GitHub Actions", "deploy AWS ECS", "AWS"),
    ("Use uv for package management", "uv package management", "uv"),
    ("Code must pass pyright strict", "pyright strict", "pyright"),
    ("Never use async_bash", "async_bash", "async_bash"),
    ("Capital is $5,000", "capital", "Capital"),
    ("Calls and puts are equal citizens", "puts equal citizens", "puts"),
]

_REQUIREMENT: float = 0.80  # >= 80% retention


def test_req001_cross_session_retention(store: MemoryStore) -> None:
    """10 locked decisions from session 1 must be retrievable in session 5 at >= 80%."""
    # Session 1: insert all decisions as locked beliefs.
    session1: Session = store.create_session(model="claude", project_context="agentmemory")
    for content, _, _ in _DECISIONS:
        # Determine belief type by content.
        if "must" in content.lower() or "never" in content.lower():
            btype: str = BELIEF_REQUIREMENT
        elif "deploy" in content.lower() or "use " in content.lower():
            btype = BELIEF_PROCEDURAL
        else:
            btype = BELIEF_FACTUAL

        store.insert_belief(
            content=content,
            belief_type=btype,
            source_type=BSRC_USER_STATED,
            alpha=9.0,
            beta_param=0.5,
            locked=True,
        )
    store.complete_session(session1.id, summary="All decisions recorded")

    # Sessions 2-5: simulate passage of time with no deletions.
    for i in range(2, 6):
        sess: Session = store.create_session(
            model="claude", project_context=f"session_{i}"
        )
        store.complete_session(sess.id, summary=f"Session {i} done")

    # Session 5 retrieval: search for each decision topic.
    found: int = 0
    not_found: list[str] = []

    for content, query, keyword in _DECISIONS:
        results: list[Belief] = store.search(query, top_k=20)
        hit: bool = any(keyword.lower() in b.content.lower() for b in results)
        if hit:
            found += 1
        else:
            not_found.append(content)

    retention_rate: float = found / len(_DECISIONS)
    assert retention_rate >= _REQUIREMENT, (
        f"REQ-001 FAILED: {found}/{len(_DECISIONS)} decisions retained "
        f"({retention_rate:.0%} < {_REQUIREMENT:.0%}). "
        f"Missing: {not_found}"
    )
