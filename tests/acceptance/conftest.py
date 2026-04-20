"""Shared fixtures for Phase 2 acceptance tests."""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from agentmemory.models import (
    BELIEF_CORRECTION,
    BELIEF_FACTUAL,
    BELIEF_PROCEDURAL,
    BELIEF_REQUIREMENT,
    BSRC_AGENT_INFERRED,
    BSRC_USER_CORRECTED,
    BSRC_USER_STATED,
)
from agentmemory.store import MemoryStore


@pytest.fixture()
def store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    """Fresh MemoryStore backed by a temp database. Closed after test."""
    s: MemoryStore = MemoryStore(tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture()
def populated_store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    """MemoryStore seeded with 10 decisions (5 locked, 3 superseded), mixed types."""
    s: MemoryStore = MemoryStore(tmp_path / "populated.db")

    # 10 decisions, varying types and lock states.
    decisions: list[tuple[str, str, str, bool]] = [
        ("Database is PostgreSQL", BELIEF_FACTUAL, BSRC_USER_STATED, True),
        ("Frontend uses React with TypeScript", BELIEF_FACTUAL, BSRC_USER_STATED, True),
        ("API follows REST conventions", BELIEF_FACTUAL, BSRC_USER_STATED, True),
        ("Tests use pytest with fixtures", BELIEF_FACTUAL, BSRC_USER_STATED, True),
        ("Deploy to AWS ECS via GitHub Actions", BELIEF_PROCEDURAL, BSRC_USER_STATED, True),
        ("Use uv for package management", BELIEF_PROCEDURAL, BSRC_AGENT_INFERRED, False),
        ("Code must pass pyright strict", BELIEF_REQUIREMENT, BSRC_AGENT_INFERRED, False),
        ("Never use async_bash", BELIEF_REQUIREMENT, BSRC_USER_CORRECTED, False),
        ("Calls and puts are equal citizens", BELIEF_FACTUAL, BSRC_USER_STATED, False),
        ("Capital is 5000 dollars", BELIEF_FACTUAL, BSRC_USER_STATED, False),
    ]

    inserted_ids: list[str] = []
    for content, btype, src, locked in decisions:
        b = s.insert_belief(
            content=content,
            belief_type=btype,
            source_type=src,
            alpha=9.0,
            beta_param=0.5,
            locked=locked,
        )
        inserted_ids.append(b.id)

    # Supersede 3 beliefs: insert replacements then call supersede_belief.
    replacements: list[tuple[str, str]] = [
        ("Use terraform for cloud functions, not gcloud", BELIEF_CORRECTION),
        ("REST API uses versioned paths like /v1/", BELIEF_FACTUAL),
        ("Tests run under tox in addition to pytest", BELIEF_FACTUAL),
    ]
    for i, (rep_content, rep_type) in enumerate(replacements):
        new_b = s.insert_belief(
            content=rep_content,
            belief_type=rep_type,
            source_type=BSRC_USER_CORRECTED,
            alpha=9.0,
            beta_param=0.5,
            locked=True,
        )
        # Supersede the i-th unlocked decision (indices 5, 6, 7 -> 0-based).
        old_id: str = inserted_ids[5 + i]
        s.supersede_belief(old_id=old_id, new_id=new_b.id, reason="updated")

    yield s
    s.close()
