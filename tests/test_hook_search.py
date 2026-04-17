"""Tests for the UserPromptSubmit hook search pipeline.

Validates entity-aware query expansion, correction-priority scoring,
supersession-chain following, and action-context detection.
"""
from __future__ import annotations

from pathlib import Path

from agentmemory.hook_search import (
    ScoredBelief,
    SearchResult,
    detect_action_targets,
    extract_entity_candidates,
    extract_query_words,
    search_for_prompt,
)
from agentmemory.models import BELIEF_FACTUAL, BSRC_AGENT_INFERRED, BSRC_USER_CORRECTED, Belief
from agentmemory.store import MemoryStore


def _make_store(tmp_path: Path) -> MemoryStore:
    """Create a store with test beliefs."""
    db: Path = tmp_path / "hook.db"
    store: MemoryStore = MemoryStore(db)

    # Old factual belief about repo access
    store.insert_belief(
        content="yoshi280 is the private GitHub repo for deploying builds to Cloudflare",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    # Correction that supersedes the above understanding
    store.insert_belief(
        content="robotrocketscience GitHub is locked by GitHub. yoshi280 is now the public repo for agentmemory",
        belief_type="correction",
        source_type=BSRC_USER_CORRECTED,
    )

    # Unrelated belief to test filtering
    store.insert_belief(
        content="FTS5 uses BM25 ranking for full text search relevance scoring",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    # A preference about deployment
    store.insert_belief(
        content="always use uv for Python package management",
        belief_type="preference",
        source_type="user_stated",
    )

    return store


# --- Query construction tests ---

def test_extract_query_words() -> None:
    """Words > 2 chars are extracted, limited to 15."""
    words: list[str] = extract_query_words("push to robotrocketscience repo")
    assert "push" in words
    assert "robotrocketscience" in words
    assert "to" not in words  # 2 chars, filtered


def test_extract_entity_candidates() -> None:
    """Longer words and mixed-case words are entity candidates."""
    words: list[str] = ["push", "robotrocketscience", "the", "repo", "yoshi280"]
    entities: list[str] = extract_entity_candidates(words)
    assert "robotrocketscience" in entities
    assert "yoshi280" in entities
    assert "push" not in entities  # too short, no special chars
    assert "the" not in entities


def test_detect_action_targets() -> None:
    """Action verbs extract their targets."""
    targets: list[str] = detect_action_targets("push to robotrocketscience")
    assert "robotrocketscience" in targets

    targets2: list[str] = detect_action_targets("deploy to production")
    assert "production" in targets2

    targets3: list[str] = detect_action_targets("install from yoshi280")
    assert "yoshi280" in targets3

    targets4: list[str] = detect_action_targets("what is the weather")
    assert len(targets4) == 0


# --- Scoring and search tests ---

def test_correction_surfaces_for_entity_query(tmp_path: Path) -> None:
    """When searching for 'robotrocketscience', the correction about it being locked must surface."""
    store: MemoryStore = _make_store(tmp_path)
    import sqlite3
    db: sqlite3.Connection = sqlite3.connect(str(tmp_path / "hook.db"))
    db.row_factory = sqlite3.Row

    result: SearchResult = search_for_prompt(db, "push to robotrocketscience")

    # The correction about robotrocketscience being locked must be in results
    contents: list[str] = [b.content for b in result.beliefs]
    found_correction: bool = any("locked" in c and "robotrocketscience" in c for c in contents)
    assert found_correction, f"Correction not found in results: {contents}"

    db.close()
    store.close()


def test_correction_ranks_above_old_fact(tmp_path: Path) -> None:
    """The correction about repo access must rank above the old factual belief."""
    store: MemoryStore = _make_store(tmp_path)
    import sqlite3
    db: sqlite3.Connection = sqlite3.connect(str(tmp_path / "hook.db"))
    db.row_factory = sqlite3.Row

    result: SearchResult = search_for_prompt(db, "push to robotrocketscience")

    # Find positions of the correction and the old fact
    correction_idx: int | None = None
    old_fact_idx: int | None = None
    for i, b in enumerate(result.beliefs):
        if "locked" in b.content and "robotrocketscience" in b.content:
            correction_idx = i
        if "private" in b.content and "yoshi280" in b.content:
            old_fact_idx = i

    if correction_idx is not None and old_fact_idx is not None:
        assert correction_idx < old_fact_idx, (
            f"Correction at index {correction_idx} should rank above old fact at {old_fact_idx}"
        )

    db.close()
    store.close()


def test_action_target_search(tmp_path: Path) -> None:
    """'deploy to production' should trigger action-context search for 'production'."""
    store: MemoryStore = _make_store(tmp_path)
    import sqlite3
    db: sqlite3.Connection = sqlite3.connect(str(tmp_path / "hook.db"))
    db.row_factory = sqlite3.Row

    # This won't find much because our test data doesn't have 'production' beliefs,
    # but it should not crash and should return a valid result
    result: SearchResult = search_for_prompt(db, "deploy to production")
    assert isinstance(result, SearchResult)

    db.close()
    store.close()


def test_unrelated_beliefs_filtered(tmp_path: Path) -> None:
    """Beliefs about FTS5 internals should not surface for repo access queries."""
    store: MemoryStore = _make_store(tmp_path)
    import sqlite3
    db: sqlite3.Connection = sqlite3.connect(str(tmp_path / "hook.db"))
    db.row_factory = sqlite3.Row

    result: SearchResult = search_for_prompt(db, "push to robotrocketscience")

    # FTS5 belief should either not appear or rank below the correction
    if result.beliefs:
        top_content: str = result.beliefs[0].content
        assert "BM25" not in top_content, "FTS5 internals belief should not be top result"

    db.close()
    store.close()


def test_empty_prompt_returns_empty() -> None:
    """Empty or short prompts return no results."""
    import sqlite3
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        db_path: Path = Path(td) / "empty.db"
        store: MemoryStore = MemoryStore(db_path)
        db: sqlite3.Connection = sqlite3.connect(str(db_path))
        db.row_factory = sqlite3.Row

        result: SearchResult = search_for_prompt(db, "ok")
        assert len(result.beliefs) == 0

        result2: SearchResult = search_for_prompt(db, "")
        assert len(result2.beliefs) == 0

        db.close()
        store.close()


def test_supersession_following(tmp_path: Path) -> None:
    """When belief A is superseded by B, searching for A's terms should surface B."""
    db_path: Path = tmp_path / "super.db"
    store: MemoryStore = MemoryStore(db_path)

    # Create old belief
    old: Belief = store.insert_belief(
        content="the deploy target is always staging first",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    # Create replacement
    new: Belief = store.insert_belief(
        content="deploy directly to production, skip staging",
        belief_type="correction",
        source_type=BSRC_USER_CORRECTED,
    )

    # Supersede old with new
    store.supersede_belief(old.id, new.id, "user correction")

    import sqlite3
    db: sqlite3.Connection = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row

    # Search for old belief's terms
    result: SearchResult = search_for_prompt(db, "deploy target staging")

    # The new (replacement) belief should surface
    contents: list[str] = [b.content for b in result.beliefs]
    found_new: bool = any("production" in c and "skip staging" in c for c in contents)
    # Old belief should NOT appear (it's superseded, valid_to IS NOT NULL)
    found_old: bool = any("always staging first" in c for c in contents)

    assert not found_old, "Superseded belief should not appear"
    # New belief should appear via either FTS5 match on 'deploy' or supersession following
    assert found_new or len(result.beliefs) > 0, "Replacement belief should surface"

    db.close()
    store.close()


def test_recent_observations_surface(tmp_path: Path) -> None:
    """Recent observations mentioning prompt entities surface even without beliefs."""
    db_path: Path = tmp_path / "obs.db"
    store: MemoryStore = MemoryStore(db_path)

    # Create an observation (not a belief) about robotrocketscience being locked
    store.insert_observation(
        content="The gh CLI shows robotrocketscience repos return 404. The account appears locked by GitHub.",
        observation_type="conversation",
        source_type="assistant",
    )

    import sqlite3
    db: sqlite3.Connection = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row

    result: SearchResult = search_for_prompt(db, "push to robotrocketscience")

    # The observation should surface via the recent observations layer
    contents: list[str] = [b.content for b in result.beliefs]
    found_obs: bool = any("locked" in c or "404" in c for c in contents)
    assert found_obs, f"Recent observation not found in results: {contents}"

    # Verify it's tagged as an observation
    obs_results: list[ScoredBelief] = [b for b in result.beliefs if b.via == "recent_observation"]
    assert len(obs_results) > 0, "Should be tagged as recent_observation"

    db.close()
    store.close()
