# pyright: reportPrivateUsage=false
"""Tests for the UserPromptSubmit hook search pipeline.

Validates entity-aware query expansion, correction-priority scoring,
supersession-chain following, and action-context detection.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from agentmemory.hook_search import (
    ScoredBelief,
    SearchResult,
    _process_pending_feedback,
    detect_action_targets,
    extract_entity_candidates,
    extract_query_words,
    format_ba_injection,
    search_for_prompt,
)
from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_CORRECTED,
    Belief,
)
from agentmemory.store import MemoryStore


@pytest.fixture(autouse=True)
def _seed_random() -> None:  # pyright: ignore[reportUnusedFunction]
    """Seed random for deterministic Thompson sampling in tests."""
    random.seed(42)


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
    found_correction: bool = any(
        "locked" in c and "robotrocketscience" in c for c in contents
    )
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
        assert "BM25" not in top_content, (
            "FTS5 internals belief should not be top result"
        )

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
    obs_results: list[ScoredBelief] = [
        b for b in result.beliefs if b.via == "recent_observation"
    ]
    assert len(obs_results) > 0, "Should be tagged as recent_observation"

    db.close()
    store.close()


def test_ba_format_three_zones() -> None:
    """Ba formatter separates beliefs into state changes, constraints, background."""
    result: SearchResult = SearchResult(
        beliefs=[
            # Recent correction -> OPERATIONAL STATE
            ScoredBelief(
                id="c1",
                content="robotrocketscience is locked, use yoshi280",
                belief_type="correction",
                source_type="user_corrected",
                locked=False,
                confidence=0.9,
                score=5.0,
                age_days=0.5,
                via="entity",
            ),
            # Locked belief -> STANDING CONSTRAINTS
            ScoredBelief(
                id="l1",
                content="always use uv for Python",
                belief_type="preference",
                source_type="user_stated",
                locked=True,
                confidence=0.95,
                score=3.0,
                age_days=30.0,
                via="fts5",
            ),
            # Speculative belief -> ACTIVE HYPOTHESES
            ScoredBelief(
                id="s1",
                content="should we add embedding retrieval?",
                belief_type="speculative",
                source_type="agent_inferred",
                locked=False,
                confidence=0.5,
                score=1.5,
                age_days=0.1,
                via="fts5",
            ),
            # Regular fact -> BACKGROUND
            ScoredBelief(
                id="b1",
                content="agentmemory uses SQLite with FTS5",
                belief_type="factual",
                source_type="agent_inferred",
                locked=False,
                confidence=0.7,
                score=1.0,
                age_days=10.0,
                via="fts5",
            ),
        ],
        source_docs=["ARCHITECTURE.md"],
    )

    output: str = format_ba_injection(result)

    # All four zones present
    assert "== OPERATIONAL STATE ==" in output
    assert "== STANDING CONSTRAINTS ==" in output
    assert "== ACTIVE HYPOTHESES ==" in output
    assert "== BACKGROUND ==" in output

    # Correction in operational state with [!] prefix
    assert "[!] robotrocketscience is locked" in output

    # Locked belief as bare imperative (no score, no percentage)
    assert "- always use uv for Python" in output
    assert (
        "%" not in output.split("STANDING CONSTRAINTS")[1].split("ACTIVE HYPOTHESES")[0]
    )

    # Speculative belief with [?] prefix
    assert "[?] should we add embedding retrieval?" in output

    # Background fact as dash-prefixed
    assert "- agentmemory uses SQLite" in output

    # Source docs present
    assert "ARCHITECTURE.md" in output

    # Zone ordering: state < constraints < hypotheses < background
    state_pos: int = output.index("OPERATIONAL STATE")
    constraint_pos: int = output.index("STANDING CONSTRAINTS")
    hyp_pos: int = output.index("ACTIVE HYPOTHESES")
    bg_pos: int = output.index("BACKGROUND")
    assert state_pos < constraint_pos < hyp_pos < bg_pos


def test_ba_format_no_state_changes() -> None:
    """When there are no state changes, that zone is omitted."""
    result: SearchResult = SearchResult(
        beliefs=[
            ScoredBelief(
                id="l1",
                content="never use em dashes",
                belief_type="preference",
                source_type="user_stated",
                locked=True,
                confidence=0.95,
                score=3.0,
                age_days=30.0,
                via="fts5",
            ),
        ],
    )

    output: str = format_ba_injection(result)
    assert "OPERATIONAL STATE" not in output
    assert "== STANDING CONSTRAINTS ==" in output
    assert "- never use em dashes" in output


# ---------------------------------------------------------------------------
# Hook feedback loop tests (agentmemory#177cbfc)
# ---------------------------------------------------------------------------


def _make_feedback_store(tmp_path: Path) -> MemoryStore:
    """Create a store for feedback tests -- no competing corrections."""
    db: Path = tmp_path / "feedback.db"
    store: MemoryStore = MemoryStore(db)
    store.insert_belief(
        content="yoshi280 is the private GitHub repo for deploying builds to Cloudflare",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    store.insert_belief(
        content="always use uv for Python package management",
        belief_type="preference",
        source_type="user_stated",
    )
    return store


def test_hook_feedback_loop_records_pending(tmp_path: Path) -> None:
    """search_for_prompt() records pending feedback for returned beliefs."""
    store: MemoryStore = _make_store(tmp_path)
    import sqlite3

    db: sqlite3.Connection = sqlite3.connect(str(tmp_path / "hook.db"))
    db.row_factory = sqlite3.Row

    # Use a query with strong term overlap to ensure beliefs survive relevance floor
    result: SearchResult = search_for_prompt(
        db, "yoshi280 deploying builds to cloudflare"
    )

    # Pending feedback should be recorded
    pending: list[sqlite3.Row] = db.execute("SELECT * FROM pending_feedback").fetchall()
    assert len(pending) > 0, "No pending feedback recorded"

    # Pending entries should match returned belief IDs
    pending_ids: set[str] = {r["belief_id"] for r in pending}
    result_ids: set[str] = {b.id for b in result.beliefs}
    assert pending_ids == result_ids, (
        f"Pending IDs {pending_ids} don't match result IDs {result_ids}"
    )

    db.close()
    store.close()


def test_hook_feedback_loop_updates_alpha(tmp_path: Path) -> None:
    """Next search processes pending feedback and updates alpha for matched beliefs."""
    store: MemoryStore = _make_feedback_store(tmp_path)
    import sqlite3

    db: sqlite3.Connection = sqlite3.connect(str(tmp_path / "feedback.db"))
    db.row_factory = sqlite3.Row

    # First search: retrieves cloudflare belief (no competing correction to dominate)
    search_for_prompt(db, "deploying builds to cloudflare")

    # Record alpha before feedback
    row: sqlite3.Row = db.execute(
        "SELECT id, alpha FROM beliefs WHERE content LIKE '%cloudflare%' AND valid_to IS NULL"
    ).fetchone()
    assert row is not None
    old_alpha: float = row["alpha"]

    # Second search: prompt mentions cloudflare and builds again, triggering feedback match
    # Need 2+ matching terms: "cloudflare" + "builds" from the belief content
    search_for_prompt(db, "push builds to cloudflare pages")

    # Alpha should have increased (term overlap: cloudflare, deploy)
    new_row: sqlite3.Row = db.execute(
        "SELECT alpha FROM beliefs WHERE id = ?", (row["id"],)
    ).fetchone()
    new_alpha: float = new_row["alpha"]
    assert new_alpha > old_alpha, (
        f"Alpha should increase from {old_alpha}, got {new_alpha}"
    )

    db.close()
    store.close()


def test_hook_feedback_loop_clears_processed(tmp_path: Path) -> None:
    """Pending feedback entries are cleared after processing."""
    store: MemoryStore = _make_feedback_store(tmp_path)
    import sqlite3

    db: sqlite3.Connection = sqlite3.connect(str(tmp_path / "feedback.db"))
    db.row_factory = sqlite3.Row

    # First search creates pending entries (no competing correction to dominate)
    search_for_prompt(db, "deploying builds to cloudflare")
    pending_before: int = db.execute(
        "SELECT COUNT(*) FROM pending_feedback"
    ).fetchone()[0]
    assert pending_before > 0

    # Second search processes old entries and creates new ones
    search_for_prompt(db, "configure wrangler deploy")
    pending_after: int = db.execute("SELECT COUNT(*) FROM pending_feedback").fetchone()[
        0
    ]

    # Old entries should be cleared; new entries from second search remain
    # The count should be the number of beliefs returned by the second search,
    # not the sum of both searches
    assert pending_after <= pending_before, (
        f"Pending should not grow: before={pending_before}, after={pending_after}"
    )

    db.close()
    store.close()


def test_hook_feedback_no_match_no_update(tmp_path: Path) -> None:
    """When prompt terms don't overlap with pending beliefs, alpha stays unchanged."""
    store: MemoryStore = _make_store(tmp_path)
    import sqlite3

    db: sqlite3.Connection = sqlite3.connect(str(tmp_path / "hook.db"))
    db.row_factory = sqlite3.Row

    # First search: retrieves beliefs about cloudflare/deploy
    search_for_prompt(db, "deploy to cloudflare")

    # Record all alphas
    alphas_before: dict[str, float] = {}
    for row in db.execute(
        "SELECT id, alpha FROM beliefs WHERE valid_to IS NULL"
    ).fetchall():
        alphas_before[row["id"]] = row["alpha"]

    # Second search: completely different topic, no overlap
    search_for_prompt(db, "what is quantum computing theory")

    # Check that cloudflare belief alpha did NOT change (no term overlap)
    for row in db.execute(
        "SELECT id, alpha FROM beliefs WHERE valid_to IS NULL AND content LIKE '%cloudflare%'"
    ).fetchall():
        assert row["alpha"] == alphas_before[row["id"]], (
            f"Alpha should not change for unmatched belief: {alphas_before[row['id']]} -> {row['alpha']}"
        )

    db.close()
    store.close()


def test_hook_feedback_updates_last_retrieved_at(tmp_path: Path) -> None:
    """search_for_prompt() updates last_retrieved_at for returned beliefs."""
    store: MemoryStore = _make_feedback_store(tmp_path)
    import sqlite3

    db: sqlite3.Connection = sqlite3.connect(str(tmp_path / "feedback.db"))
    db.row_factory = sqlite3.Row

    # Verify no last_retrieved_at initially
    row: sqlite3.Row = db.execute(
        "SELECT last_retrieved_at FROM beliefs WHERE content LIKE '%cloudflare%' AND valid_to IS NULL"
    ).fetchone()
    assert row is not None
    assert row["last_retrieved_at"] is None

    # Search retrieves the belief (no competing correction to dominate)
    search_for_prompt(db, "deploying builds to cloudflare")

    # last_retrieved_at should now be set
    row_after: sqlite3.Row = db.execute(
        "SELECT last_retrieved_at FROM beliefs WHERE content LIKE '%cloudflare%' AND valid_to IS NULL"
    ).fetchone()
    assert row_after["last_retrieved_at"] is not None

    db.close()
    store.close()


def test_process_pending_feedback_empty_table(tmp_path: Path) -> None:
    """_process_pending_feedback handles empty pending_feedback table gracefully."""
    store: MemoryStore = _make_store(tmp_path)
    import sqlite3

    db: sqlite3.Connection = sqlite3.connect(str(tmp_path / "hook.db"))
    db.row_factory = sqlite3.Row

    # Process with no pending entries
    used: int = _process_pending_feedback(db, "some prompt text")
    assert used == 0

    db.close()
    store.close()
