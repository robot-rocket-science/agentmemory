"""REQ-021: behavioral beliefs must appear in L0 context injection regardless of query topic.

Locked behavioral beliefs appear via get_locked_beliefs() (L0 layer).
Unlocked behavioral beliefs appear via get_behavioral_beliefs() (L1 layer).
Both layers are always included in retrieve() results, independent of query.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from agentmemory.models import (
    BELIEF_FACTUAL,
    BELIEF_PREFERENCE,
    BELIEF_PROCEDURAL,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    s: MemoryStore = MemoryStore(tmp_path / "req021.db")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Behavioral belief content
# ---------------------------------------------------------------------------

BEHAVIORAL_CONTENTS: list[str] = [
    "always cite sources with links",
    "never use em dashes",
    "use uv for Python package management",
]

FACTUAL_CONTENTS: list[str] = [
    "the users table has columns id, name, email, created_at",
    "database migrations use alembic with sequential revision IDs",
    "the schema version is stored in the alembic_version table",
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReq021BehavioralL0:
    """Behavioral beliefs must appear in retrieval results regardless of query topic."""

    def test_locked_behavioral_beliefs_in_l0(self, store: MemoryStore) -> None:
        """Locked behavioral beliefs appear in results for an unrelated query."""
        # Insert 3 locked behavioral beliefs
        behavioral_ids: list[str] = []
        for content in BEHAVIORAL_CONTENTS:
            belief: Belief = store.insert_belief(
                content=content,
                belief_type=BELIEF_PREFERENCE,
                source_type=BSRC_USER_STATED,
                alpha=5.0,
                beta_param=0.5,
                locked=True,
            )
            behavioral_ids.append(belief.id)

        # Insert 3 unrelated factual beliefs about database schemas
        for content in FACTUAL_CONTENTS:
            store.insert_belief(
                content=content,
                belief_type=BELIEF_FACTUAL,
                source_type=BSRC_USER_STATED,
                alpha=2.0,
                beta_param=1.0,
            )

        # Search for something completely unrelated to behavioral beliefs
        result: RetrievalResult = retrieve(store, "database schema migration")

        # All 3 behavioral beliefs must appear in results
        result_ids: set[str] = {b.id for b in result.beliefs}
        for bid in behavioral_ids:
            assert bid in result_ids, (
                f"Locked behavioral belief {bid} missing from L0 retrieval results"
            )

    def test_locked_beliefs_returned_by_store(self, store: MemoryStore) -> None:
        """get_locked_beliefs() returns all locked beliefs."""
        inserted_ids: list[str] = []
        for content in BEHAVIORAL_CONTENTS:
            belief: Belief = store.insert_belief(
                content=content,
                belief_type=BELIEF_PREFERENCE,
                source_type=BSRC_USER_STATED,
                alpha=5.0,
                beta_param=0.5,
                locked=True,
            )
            inserted_ids.append(belief.id)

        locked: list[Belief] = store.get_locked_beliefs()
        locked_ids: set[str] = {b.id for b in locked}

        for bid in inserted_ids:
            assert bid in locked_ids, (
                f"Locked belief {bid} not returned by get_locked_beliefs()"
            )

    def test_unlocked_behavioral_beliefs_in_l1(self, store: MemoryStore) -> None:
        """Unlocked behavioral beliefs (L1) appear via get_behavioral_beliefs().

        L1 requires: unlocked, source_type='directive' OR
        (belief_type in requirement/procedural, confidence >= 0.8,
        content contains behavioral keywords like 'always'/'never'/'must').
        """
        # Insert unlocked behavioral beliefs using source_type='directive'
        # so they qualify for L1 without needing keyword heuristics
        behavioral_ids: list[str] = []
        for content in BEHAVIORAL_CONTENTS:
            belief: Belief = store.insert_belief(
                content=content,
                belief_type=BELIEF_PROCEDURAL,
                source_type="directive",
                alpha=5.0,
                beta_param=0.5,
                locked=False,
            )
            behavioral_ids.append(belief.id)

        # Insert unrelated factual beliefs
        for content in FACTUAL_CONTENTS:
            store.insert_belief(
                content=content,
                belief_type=BELIEF_FACTUAL,
                source_type=BSRC_USER_STATED,
                alpha=2.0,
                beta_param=1.0,
            )

        # Search for unrelated topic
        result: RetrievalResult = retrieve(store, "database schema migration")

        result_ids: set[str] = {b.id for b in result.beliefs}
        for bid in behavioral_ids:
            assert bid in result_ids, (
                f"Unlocked behavioral belief {bid} missing from L1 retrieval results"
            )

    def test_behavioral_beliefs_coexist_with_fts_results(
        self,
        store: MemoryStore,
    ) -> None:
        """Both behavioral (L0) and FTS5 (L2) results appear together."""
        # Insert locked behavioral beliefs
        behavioral_ids: list[str] = []
        for content in BEHAVIORAL_CONTENTS:
            belief: Belief = store.insert_belief(
                content=content,
                belief_type=BELIEF_PREFERENCE,
                source_type=BSRC_USER_STATED,
                alpha=5.0,
                beta_param=0.5,
                locked=True,
            )
            behavioral_ids.append(belief.id)

        # Insert factual beliefs that match the query
        factual_ids: list[str] = []
        for content in FACTUAL_CONTENTS:
            belief = store.insert_belief(
                content=content,
                belief_type=BELIEF_FACTUAL,
                source_type=BSRC_USER_STATED,
                alpha=2.0,
                beta_param=1.0,
            )
            factual_ids.append(belief.id)

        result: RetrievalResult = retrieve(store, "database schema migration")
        result_ids: set[str] = {b.id for b in result.beliefs}

        # Behavioral beliefs present (from L0)
        for bid in behavioral_ids:
            assert bid in result_ids, (
                f"Behavioral belief {bid} missing when FTS results also present"
            )

        # At least some factual beliefs present (from L2 FTS5)
        factual_in_results: int = sum(1 for fid in factual_ids if fid in result_ids)
        assert factual_in_results > 0, (
            "No factual FTS5 results returned alongside behavioral beliefs"
        )

    def test_behavioral_count(self, store: MemoryStore) -> None:
        """Exactly 3 behavioral beliefs are returned, no more, no less."""
        for content in BEHAVIORAL_CONTENTS:
            store.insert_belief(
                content=content,
                belief_type=BELIEF_PREFERENCE,
                source_type=BSRC_USER_STATED,
                alpha=5.0,
                beta_param=0.5,
                locked=True,
            )

        locked: list[Belief] = store.get_locked_beliefs()
        assert len(locked) == 3, f"Expected 3 locked beliefs, got {len(locked)}"
