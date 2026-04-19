# pyright: reportPrivateUsage=false
"""Validation tests for injection relevance fixes.

These tests encode the specific problems found in the injection relevance
analysis (77.4% irrelevance rate) and verify fixes work. Written test-first
before implementing fixes.

Problem summary:
  - 38 beliefs/prompt avg, 77.4% irrelevant
  - FTS5 OR on 15 words matches everything
  - XML/task-notifications trigger search
  - Generic beliefs (git repos) appear in 88% of injections
  - agent_inferred (62%) dominates despite lowest trust
  - 6000 char budget packs too much noise
"""

from __future__ import annotations

import random
import sqlite3
from pathlib import Path

import pytest

from agentmemory.hook_search import (
    SearchResult,
    format_ba_injection,
    search_for_prompt,
)
from agentmemory.models import BELIEF_FACTUAL, BSRC_AGENT_INFERRED, BSRC_USER_CORRECTED
from agentmemory.store import MemoryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _seed_random() -> None:  # pyright: ignore[reportUnusedFunction]
    """Seed random for deterministic Thompson sampling in tests."""
    random.seed(42)


def _make_noisy_store(tmp_path: Path) -> MemoryStore:
    """Create a store with a mix of relevant and generic beliefs.

    Simulates the real DB: a few targeted beliefs plus many generic
    project-level beliefs that match common words.
    """
    db: Path = tmp_path / "noisy.db"
    store: MemoryStore = MemoryStore(db)

    # --- Generic beliefs that match everything ---
    store.insert_belief(
        content=(
            "i have 3 git repos: yoshi280 is my private github which i use "
            "primarily for deploying builds to cloudflare, robotrocketscience "
            "is my public-facing github, this is where i share source code for "
            "my projects. then i have my internal gitea server, which is what "
            "i use for configuration control on all my projects"
        ),
        belief_type="correction",
        source_type=BSRC_USER_CORRECTED,
    )
    store.insert_belief(
        content=(
            "agentmemory project status as of v2.2.2: Phase 5 in progress. "
            "28 production modules, 23 MCP tools, 759 tests passing, "
            "84 experiments complete. Phases 1-4 fully implemented."
        ),
        belief_type="correction",
        source_type=BSRC_USER_CORRECTED,
    )
    store.insert_belief(
        content=(
            "Phase 4 Behavioral Enforcement is COMPLETE. All 15 triggered "
            "beliefs implemented: TB-01 through TB-15. Hooks active in "
            "production: SessionStart, UserPromptSubmit, PreToolUse, Stop."
        ),
        belief_type="correction",
        source_type=BSRC_USER_CORRECTED,
    )

    # --- Filler agent-inferred beliefs (noise) ---
    for i in range(20):
        store.insert_belief(
            content=f"The system processes data through pipeline stage {i} "
            f"using standard processing methods for project optimization",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )

    # --- Targeted beliefs (should surface for specific queries) ---
    store.insert_belief(
        content="Bayesian score inflation was caused by insertion priors "
        "being too generous. Fixed by deflating alpha for agent-inferred.",
        belief_type="correction",
        source_type=BSRC_USER_CORRECTED,
    )
    store.insert_belief(
        content="The recalibrate_scores function resets inflated beliefs "
        "back to neutral priors based on source type.",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    store.insert_belief(
        content="always use uv for Python package management",
        belief_type="preference",
        source_type="user_stated",
    )

    return store


def _open_db(tmp_path: Path) -> sqlite3.Connection:
    db: sqlite3.Connection = sqlite3.connect(str(tmp_path / "noisy.db"))
    db.row_factory = sqlite3.Row
    return db


# ---------------------------------------------------------------------------
# Fix 1: Pre-filter non-prompts (XML/task-notifications)
# ---------------------------------------------------------------------------


class TestPreFilter:
    """XML and task-notification strings should not trigger search."""

    def test_task_notification_xml_returns_empty(self, tmp_path: Path) -> None:
        """Task-notification XML should be detected and skipped."""
        store: MemoryStore = _make_noisy_store(tmp_path)
        db: sqlite3.Connection = _open_db(tmp_path)

        xml_prompt: str = (
            "<task-notification> <task-id>a3b3755d672ff16cc</task-id> "
            "<status>completed</status> <summary>Agent finished</summary> "
            "</task-notification>"
        )
        result: SearchResult = search_for_prompt(db, xml_prompt)
        assert len(result.beliefs) == 0, (
            f"XML task-notification should return 0 beliefs, got {len(result.beliefs)}"
        )

        db.close()
        store.close()

    def test_system_reminder_xml_returns_empty(self, tmp_path: Path) -> None:
        """System-reminder XML should be detected and skipped."""
        store: MemoryStore = _make_noisy_store(tmp_path)
        db: sqlite3.Connection = _open_db(tmp_path)

        xml_prompt: str = (
            "<system-reminder>The task tools have not been used recently. "
            "Consider using TaskCreate.</system-reminder>"
        )
        result: SearchResult = search_for_prompt(db, xml_prompt)
        assert len(result.beliefs) == 0, (
            f"System-reminder XML should return 0 beliefs, got {len(result.beliefs)}"
        )

        db.close()
        store.close()

    def test_real_prompt_still_works(self, tmp_path: Path) -> None:
        """A real user prompt should still return results."""
        store: MemoryStore = _make_noisy_store(tmp_path)
        db: sqlite3.Connection = _open_db(tmp_path)

        result: SearchResult = search_for_prompt(
            db, "fix the Bayesian score inflation bug"
        )
        assert len(result.beliefs) > 0, "Real prompt should return results"

        db.close()
        store.close()


# ---------------------------------------------------------------------------
# Fix 2: Relevance floor - low-scoring beliefs should not be injected
# ---------------------------------------------------------------------------


class TestRelevanceFloor:
    """Beliefs below a minimum relevance threshold should be excluded."""

    def test_specific_query_returns_fewer_beliefs(self, tmp_path: Path) -> None:
        """A specific query should not return 20+ generic beliefs."""
        store: MemoryStore = _make_noisy_store(tmp_path)
        db: sqlite3.Connection = _open_db(tmp_path)

        result: SearchResult = search_for_prompt(
            db, "fix the Bayesian score inflation bug"
        )
        # With 20 filler beliefs + 3 generic + 3 targeted = 26 total,
        # a good system should return well under 26 (budget + floor trim).
        # Thompson sampling variance means count fluctuates; 18 is the
        # deterministic ceiling (budget_chars=2500 / ~140 chars per entry).
        assert len(result.beliefs) <= 18, (
            f"Specific query returned {len(result.beliefs)} beliefs, "
            f"expected <= 18 after relevance floor + budget"
        )

        db.close()
        store.close()

    def test_targeted_beliefs_rank_first(self, tmp_path: Path) -> None:
        """Beliefs about Bayesian scoring should rank above generic filler."""
        store: MemoryStore = _make_noisy_store(tmp_path)
        db: sqlite3.Connection = _open_db(tmp_path)

        result: SearchResult = search_for_prompt(
            db, "fix the Bayesian score inflation bug"
        )
        if not result.beliefs:
            pytest.skip("No beliefs returned")

        # At least one of the top 3 should mention Bayesian or score or inflation
        top_3_content: str = " ".join(b.content for b in result.beliefs[:3])
        assert any(
            term in top_3_content.lower()
            for term in ("bayesian", "score", "inflation", "recalibrate")
        ), f"Top 3 beliefs don't mention the query topic: {top_3_content[:200]}"

        db.close()
        store.close()


# ---------------------------------------------------------------------------
# Fix 3: Budget should be tighter
# ---------------------------------------------------------------------------


class TestBudgetReduction:
    """Injection budget should produce concise, focused context."""

    def test_injection_under_budget(self, tmp_path: Path) -> None:
        """Formatted injection should stay under reduced budget."""
        store: MemoryStore = _make_noisy_store(tmp_path)
        db: sqlite3.Connection = _open_db(tmp_path)

        result: SearchResult = search_for_prompt(db, "fix the Bayesian score inflation")
        if not result.beliefs:
            pytest.skip("No beliefs returned")

        injection: str = format_ba_injection(result)
        # Target: under 3000 chars (down from 6000)
        assert len(injection) <= 3000, (
            f"Injection is {len(injection)} chars, target is <= 3000"
        )

        db.close()
        store.close()


# ---------------------------------------------------------------------------
# Fix 4: Source-type weighting
# ---------------------------------------------------------------------------


class TestSourceTypeWeighting:
    """User-corrected and user-stated beliefs should outrank agent-inferred."""

    def test_user_correction_outranks_agent_filler(self, tmp_path: Path) -> None:
        """A user correction about Bayesian scoring should rank above generic
        agent-inferred beliefs about 'processing pipeline stage N'."""
        store: MemoryStore = _make_noisy_store(tmp_path)
        db: sqlite3.Connection = _open_db(tmp_path)

        result: SearchResult = search_for_prompt(db, "fix the Bayesian score inflation")
        if not result.beliefs:
            pytest.skip("No beliefs returned")

        # Find the Bayesian correction and the first filler belief
        bayesian_idx: int | None = None
        filler_idx: int | None = None
        for i, b in enumerate(result.beliefs):
            if "bayesian" in b.content.lower() or "inflation" in b.content.lower():
                if bayesian_idx is None:
                    bayesian_idx = i
            if "pipeline stage" in b.content.lower():
                if filler_idx is None:
                    filler_idx = i

        if bayesian_idx is not None and filler_idx is not None:
            assert bayesian_idx < filler_idx, (
                f"Bayesian correction at {bayesian_idx} should rank above "
                f"filler at {filler_idx}"
            )

        db.close()
        store.close()

    def test_agent_inferred_not_majority(self, tmp_path: Path) -> None:
        """agent_inferred beliefs should not be the majority of results
        when user_corrected beliefs are available."""
        store: MemoryStore = _make_noisy_store(tmp_path)
        db: sqlite3.Connection = _open_db(tmp_path)

        result: SearchResult = search_for_prompt(db, "fix the Bayesian score inflation")
        if not result.beliefs:
            pytest.skip("No beliefs returned")

        agent_count: int = sum(
            1 for b in result.beliefs if b.source_type == BSRC_AGENT_INFERRED
        )
        total: int = len(result.beliefs)
        agent_pct: float = agent_count / total * 100 if total > 0 else 0

        # agent_inferred should be < 60% of results (currently 62% globally)
        assert agent_pct < 60, (
            f"agent_inferred is {agent_pct:.1f}% of results ({agent_count}/{total}), "
            f"should be < 60%"
        )

        db.close()
        store.close()


# ---------------------------------------------------------------------------
# Integration: End-to-end relevance check
# ---------------------------------------------------------------------------


class TestEndToEndRelevance:
    """Verify that the full pipeline produces relevant injections."""

    def test_vague_prompt_does_not_explode(self, tmp_path: Path) -> None:
        """Short vague prompts like 'yes' should not inject 40+ beliefs."""
        store: MemoryStore = _make_noisy_store(tmp_path)
        db: sqlite3.Connection = _open_db(tmp_path)

        result: SearchResult = search_for_prompt(db, "yes do it")
        # "yes do it" is very vague, should get minimal injection
        assert len(result.beliefs) <= 10, (
            f"Vague prompt 'yes do it' got {len(result.beliefs)} beliefs, "
            f"expected <= 10"
        )

        db.close()
        store.close()

    def test_single_word_prompt_minimal_injection(self, tmp_path: Path) -> None:
        """A single meaningful word should produce focused results."""
        store: MemoryStore = _make_noisy_store(tmp_path)
        db: sqlite3.Connection = _open_db(tmp_path)

        result: SearchResult = search_for_prompt(db, "continue")
        assert len(result.beliefs) <= 5, (
            f"'continue' got {len(result.beliefs)} beliefs, expected <= 5"
        )

        db.close()
        store.close()
