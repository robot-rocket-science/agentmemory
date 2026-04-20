# pyright: reportPrivateUsage=false, reportUnusedFunction=false
"""Tests for valence propagation, confirm(), session_quality(), and gradient auto-feedback.

Validates the core behavioral changes from the spectrum feedback design:
1. Continuous valence replaces binary outcomes in Bayesian updates
2. CONTRADICTS edges invert valence (confirming A weakens A's contradictions)
3. Multi-hop propagation with decay and min threshold
4. confirm() as positive counterpart to correct()
5. session_quality() with hub-weighted credit assignment
6. Gradient auto-feedback (overlap ratio instead of binary)
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_STATED,
    EDGE_CONTRADICTS,
    EDGE_SUPPORTS,
    EDGE_SUPERSEDES,
    LAYER_IMPLICIT,
    OUTCOME_IGNORED,
    VALENCE_MAP,
    Belief,
)
from agentmemory.store import MemoryStore

import agentmemory.server as server_mod
from agentmemory.server import confirm, feedback, session_quality


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    s: MemoryStore = MemoryStore(tmp_path / "test_valence.db")
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _reset_server(tmp_path: Path) -> Generator[None, None, None]:
    """Point server module at a fresh store and session for each test."""
    test_store: MemoryStore = MemoryStore(tmp_path / "server_valence.db")
    old_store: MemoryStore | None = server_mod._store
    old_session: str | None = server_mod._session_id
    old_retrieval: dict[str, list[tuple[str, str]]] = server_mod._retrieval_buffer
    old_signal: list[str] = server_mod._signal_buffer
    old_explicit: set[str] = server_mod._explicit_feedback_ids

    server_mod._store = test_store
    session = test_store.create_session(model="test", project_context="valence-test")
    server_mod._session_id = session.id
    server_mod._retrieval_buffer = {}
    server_mod._signal_buffer = []
    server_mod._explicit_feedback_ids = set()

    yield

    test_store.close()
    server_mod._store = old_store
    server_mod._session_id = old_session
    server_mod._retrieval_buffer = old_retrieval
    server_mod._signal_buffer = old_signal
    server_mod._explicit_feedback_ids = old_explicit


# ---------------------------------------------------------------------------
# 1. Valence map and backward compat
# ---------------------------------------------------------------------------


def test_valence_map_has_all_outcomes() -> None:
    """Every valid outcome string maps to a valence score."""
    assert "used" in VALENCE_MAP
    assert "ignored" in VALENCE_MAP
    assert "harmful" in VALENCE_MAP
    assert "confirmed" in VALENCE_MAP
    assert "weak" in VALENCE_MAP


def test_valence_map_signs() -> None:
    """Positive outcomes have positive valence, negative have negative."""
    assert VALENCE_MAP["confirmed"] > 0
    assert VALENCE_MAP["used"] > 0
    assert VALENCE_MAP["ignored"] == -0.1  # weak negative signal (Fix 5)
    assert VALENCE_MAP["weak"] < 0
    assert VALENCE_MAP["harmful"] < 0


# ---------------------------------------------------------------------------
# 2. Continuous valence in update_confidence
# ---------------------------------------------------------------------------


def test_positive_valence_increases_alpha(store: MemoryStore) -> None:
    """Positive valence should increment alpha proportionally."""
    b: Belief = store.insert_belief(
        "Test positive valence",
        BELIEF_FACTUAL,
        BSRC_AGENT_INFERRED,
        alpha=5.0,
        beta_param=1.0,
    )
    store.update_confidence(b.id, "ignored", valence=0.7)
    updated: Belief | None = store.get_belief(b.id)
    assert updated is not None
    # First feedback event gets 3x weight (Fix 3), so alpha += 0.7 * 3 = 2.1
    assert updated.alpha == pytest.approx(7.1)  # pyright: ignore[reportUnknownMemberType]
    assert updated.beta_param == pytest.approx(1.0)  # pyright: ignore[reportUnknownMemberType]


def test_negative_valence_increases_beta(store: MemoryStore) -> None:
    """Negative valence should increment beta proportionally."""
    b: Belief = store.insert_belief(
        "Test negative valence",
        BELIEF_FACTUAL,
        BSRC_AGENT_INFERRED,
        alpha=5.0,
        beta_param=1.0,
    )
    store.update_confidence(b.id, "ignored", valence=-0.3)
    updated: Belief | None = store.get_belief(b.id)
    assert updated is not None
    assert updated.alpha == pytest.approx(5.0)  # pyright: ignore[reportUnknownMemberType]
    # First-signal amplification: weight 1.0 * 3.0 = 3.0, beta += abs(-0.3) * 3.0 = 0.9
    assert updated.beta_param == pytest.approx(1.9)  # pyright: ignore[reportUnknownMemberType]


def test_zero_valence_no_change(store: MemoryStore) -> None:
    """Zero valence should not change alpha or beta."""
    b: Belief = store.insert_belief(
        "Test zero valence",
        BELIEF_FACTUAL,
        BSRC_AGENT_INFERRED,
        alpha=5.0,
        beta_param=1.0,
    )
    store.update_confidence(b.id, "ignored", valence=0.0)
    updated: Belief | None = store.get_belief(b.id)
    assert updated is not None
    assert updated.alpha == pytest.approx(5.0)  # pyright: ignore[reportUnknownMemberType]
    assert updated.beta_param == pytest.approx(1.0)  # pyright: ignore[reportUnknownMemberType]


def test_locked_resists_negative_valence(store: MemoryStore) -> None:
    """Locked beliefs should resist negative valence below LOCKED_EVIDENCE_THRESHOLD."""
    b: Belief = store.insert_belief(
        "Locked belief",
        BELIEF_FACTUAL,
        BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )
    # weight=1.0 * valence=-0.5 = 0.5, below LOCKED_EVIDENCE_THRESHOLD (3.0)
    store.update_confidence(b.id, "harmful", valence=-0.5)
    updated: Belief | None = store.get_belief(b.id)
    assert updated is not None
    assert updated.beta_param == pytest.approx(  # pyright: ignore[reportUnknownMemberType]
        0.5
    )  # unchanged


# ---------------------------------------------------------------------------
# 3. Valence propagation through edges
# ---------------------------------------------------------------------------


def test_propagation_supports_strengthens(store: MemoryStore) -> None:
    """Positive valence propagates through SUPPORTS edges, strengthening neighbors."""
    a: Belief = store.insert_belief(
        "Seed belief A", BELIEF_FACTUAL, BSRC_AGENT_INFERRED, alpha=5.0, beta_param=1.0
    )
    b: Belief = store.insert_belief(
        "Neighbor B", BELIEF_FACTUAL, BSRC_AGENT_INFERRED, alpha=5.0, beta_param=1.0
    )
    store.insert_edge(a.id, b.id, EDGE_SUPPORTS)

    updated_count: int = store.propagate_valence(a.id, valence=1.0)
    assert updated_count == 1

    b_after: Belief | None = store.get_belief(b.id)
    assert b_after is not None
    # valence=1.0 * decay=0.5 * SUPPORTS=1.0 = 0.5
    assert b_after.alpha == pytest.approx(5.5)  # pyright: ignore[reportUnknownMemberType]


def test_propagation_contradicts_inverts(store: MemoryStore) -> None:
    """Positive valence through CONTRADICTS edges should WEAKEN the neighbor."""
    a: Belief = store.insert_belief(
        "Confirmed belief",
        BELIEF_FACTUAL,
        BSRC_AGENT_INFERRED,
        alpha=5.0,
        beta_param=1.0,
    )
    b: Belief = store.insert_belief(
        "Contradicting belief",
        BELIEF_FACTUAL,
        BSRC_AGENT_INFERRED,
        alpha=5.0,
        beta_param=1.0,
    )
    store.insert_edge(a.id, b.id, EDGE_CONTRADICTS)

    store.propagate_valence(a.id, valence=1.0)

    b_after: Belief | None = store.get_belief(b.id)
    assert b_after is not None
    # valence=1.0 * decay=0.5 * CONTRADICTS=-0.5 = -0.25 -> beta += 0.25
    assert b_after.beta_param == pytest.approx(1.25)  # pyright: ignore[reportUnknownMemberType]
    assert b_after.alpha == pytest.approx(5.0)  # pyright: ignore[reportUnknownMemberType]


def test_propagation_supersedes_no_propagation(store: MemoryStore) -> None:
    """SUPERSEDES edges should not propagate valence (multiplier = 0.0)."""
    a: Belief = store.insert_belief(
        "New belief", BELIEF_FACTUAL, BSRC_AGENT_INFERRED, alpha=5.0, beta_param=1.0
    )
    b: Belief = store.insert_belief(
        "Old superseded belief",
        BELIEF_FACTUAL,
        BSRC_AGENT_INFERRED,
        alpha=5.0,
        beta_param=1.0,
    )
    store.insert_edge(a.id, b.id, EDGE_SUPERSEDES)

    updated: int = store.propagate_valence(a.id, valence=1.0)
    assert updated == 0

    b_after: Belief | None = store.get_belief(b.id)
    assert b_after is not None
    assert b_after.alpha == pytest.approx(5.0)  # pyright: ignore[reportUnknownMemberType]


def test_propagation_decay_per_hop(store: MemoryStore) -> None:
    """Valence decays exponentially with hop distance."""
    a: Belief = store.insert_belief(
        "Root", BELIEF_FACTUAL, BSRC_AGENT_INFERRED, alpha=5.0, beta_param=1.0
    )
    b: Belief = store.insert_belief(
        "Hop 1", BELIEF_FACTUAL, BSRC_AGENT_INFERRED, alpha=5.0, beta_param=1.0
    )
    c: Belief = store.insert_belief(
        "Hop 2", BELIEF_FACTUAL, BSRC_AGENT_INFERRED, alpha=5.0, beta_param=1.0
    )
    store.insert_edge(a.id, b.id, EDGE_SUPPORTS)
    store.insert_edge(b.id, c.id, EDGE_SUPPORTS)

    store.propagate_valence(a.id, valence=1.0, decay=0.5)

    b_after: Belief | None = store.get_belief(b.id)
    c_after: Belief | None = store.get_belief(c.id)
    assert b_after is not None and c_after is not None
    # Hop 1: 1.0 * 0.5 * 1.0 = 0.5
    assert b_after.alpha == pytest.approx(5.5)  # pyright: ignore[reportUnknownMemberType]
    # Hop 2: 0.5 * 0.5 * 1.0 = 0.25
    assert c_after.alpha == pytest.approx(5.25)  # pyright: ignore[reportUnknownMemberType]


def test_propagation_stops_at_threshold(store: MemoryStore) -> None:
    """Propagation should stop when valence drops below min_threshold."""
    a: Belief = store.insert_belief(
        "Root for threshold", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    b: Belief = store.insert_belief(
        "Hop 1 threshold", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    c: Belief = store.insert_belief(
        "Hop 2 threshold", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    store.insert_edge(a.id, b.id, EDGE_SUPPORTS)
    store.insert_edge(b.id, c.id, EDGE_SUPPORTS)

    # Start with small valence so hop 2 falls below threshold
    updated: int = store.propagate_valence(
        a.id, valence=0.2, decay=0.5, min_threshold=0.08
    )
    # Hop 1: 0.2 * 0.5 = 0.1 (above 0.08, propagates)
    # Hop 2: 0.1 * 0.5 = 0.05 (below 0.08, stops)
    assert updated == 1  # only hop 1


def test_propagation_locked_resists_negative(store: MemoryStore) -> None:
    """Locked beliefs should resist indirect negative valence propagation."""
    a: Belief = store.insert_belief(
        "Source of negative", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    b: Belief = store.insert_belief(
        "Locked neighbor",
        BELIEF_FACTUAL,
        BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )
    store.insert_edge(a.id, b.id, EDGE_CONTRADICTS)

    # Positive valence on a, inverted through CONTRADICTS = negative to b
    store.propagate_valence(a.id, valence=1.0)

    b_after: Belief | None = store.get_belief(b.id)
    assert b_after is not None
    # Locked belief should resist indirect negative valence
    assert b_after.beta_param == pytest.approx(0.5)  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# 4. confirm() tool
# ---------------------------------------------------------------------------


def test_confirm_increases_alpha() -> None:
    """confirm() should increase alpha by CONFIRM_WEIGHT."""
    store: MemoryStore = server_mod._get_store()
    b: Belief = store.insert_belief(
        "Confirmable belief",
        BELIEF_FACTUAL,
        BSRC_AGENT_INFERRED,
        alpha=5.0,
        beta_param=1.0,
    )

    result: str = confirm(b.id)
    assert "Confirmed" in result

    updated: Belief | None = store.get_belief(b.id)
    assert updated is not None
    # confirm uses valence=1.0, weight=CONFIRM_WEIGHT(2.0)
    # update_confidence: alpha += abs(1.0) * 2.0 = 2.0
    assert updated.alpha == pytest.approx(7.0)  # pyright: ignore[reportUnknownMemberType]


def test_confirm_propagates_valence() -> None:
    """confirm() should propagate valence to connected beliefs."""
    store: MemoryStore = server_mod._get_store()
    a: Belief = store.insert_belief(
        "Confirmed belief",
        BELIEF_FACTUAL,
        BSRC_AGENT_INFERRED,
        alpha=5.0,
        beta_param=1.0,
    )
    b: Belief = store.insert_belief(
        "Connected to confirmed",
        BELIEF_FACTUAL,
        BSRC_AGENT_INFERRED,
        alpha=5.0,
        beta_param=1.0,
    )
    store.insert_edge(a.id, b.id, EDGE_SUPPORTS)

    result: str = confirm(a.id)
    assert "propagated" in result

    b_after: Belief | None = store.get_belief(b.id)
    assert b_after is not None
    assert b_after.alpha > 5.0  # should have received propagated valence


# ---------------------------------------------------------------------------
# 5. session_quality()
# ---------------------------------------------------------------------------


def test_session_quality_positive() -> None:
    """session_quality(+1.0) should boost retrieved beliefs."""
    store: MemoryStore = server_mod._get_store()
    session_id: str = server_mod._session_id  # type: ignore[assignment]

    beliefs: list[Belief] = []
    for i in range(5):
        b: Belief = store.insert_belief(
            f"Session quality test belief {i}",
            BELIEF_FACTUAL,
            BSRC_AGENT_INFERRED,
            alpha=5.0,
            beta_param=1.0,
        )
        beliefs.append(b)
        # Record a test result so the belief appears in the session
        store.record_test_result(b.id, session_id, OUTCOME_IGNORED, LAYER_IMPLICIT)

    # Add some edges to create hubs
    store.insert_edge(beliefs[0].id, beliefs[1].id, EDGE_SUPPORTS)
    store.insert_edge(beliefs[0].id, beliefs[2].id, EDGE_SUPPORTS)
    store.insert_edge(beliefs[0].id, beliefs[3].id, EDGE_SUPPORTS)

    result: str = session_quality(1.0)
    assert "Session quality +1.00 applied" in result

    # Hub belief (beliefs[0], degree 3) should have gotten more boost
    hub: Belief | None = store.get_belief(beliefs[0].id)
    leaf: Belief | None = store.get_belief(beliefs[4].id)
    assert hub is not None and leaf is not None
    # Hub should have higher alpha than leaf due to hub weighting
    assert hub.alpha >= leaf.alpha


def test_session_quality_records_score() -> None:
    """session_quality should store the score in the sessions table."""
    store: MemoryStore = server_mod._get_store()
    session_id: str = server_mod._session_id  # type: ignore[assignment]

    b: Belief = store.insert_belief(
        "Quality record test", BELIEF_FACTUAL, BSRC_AGENT_INFERRED
    )
    store.record_test_result(b.id, session_id, OUTCOME_IGNORED, LAYER_IMPLICIT)

    session_quality(0.8)

    row = store.query("SELECT quality_score FROM sessions WHERE id = ?", (session_id,))
    assert len(row) == 1
    assert float(str(row[0]["quality_score"])) == pytest.approx(0.8)  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# 6. Gradient auto-feedback
# ---------------------------------------------------------------------------


def test_gradient_auto_feedback_valence() -> None:
    """Auto-feedback should record continuous valence based on term overlap ratio."""
    store: MemoryStore = server_mod._get_store()
    session_id: str = server_mod._session_id  # type: ignore[assignment]

    # Insert a belief with 5 key terms
    b: Belief = store.insert_belief(
        "Python virtual environments should use uv package manager",
        BELIEF_FACTUAL,
        BSRC_AGENT_INFERRED,
    )

    # Simulate retrieval buffer
    now_ts: str = datetime.now(timezone.utc).isoformat()
    server_mod._retrieval_buffer[session_id] = [(b.id, now_ts)]

    # Signal with partial overlap (3 of ~5 unique terms)
    server_mod._signal_buffer = ["python uv package"]

    count: int = server_mod._process_auto_feedback(session_id)
    assert count == 1

    # Check that valence was recorded
    rows = store.query(
        "SELECT valence, outcome_detail FROM tests WHERE belief_id = ? ORDER BY created_at DESC LIMIT 1",
        (b.id,),
    )
    assert len(rows) == 1
    detail: str = str(rows[0]["outcome_detail"])
    assert "valence:" in detail


# ---------------------------------------------------------------------------
# 7. feedback() tool with new outcomes
# ---------------------------------------------------------------------------


def test_feedback_confirmed_outcome() -> None:
    """feedback() with 'confirmed' should increase alpha more than 'used'."""
    store: MemoryStore = server_mod._get_store()
    b: Belief = store.insert_belief(
        "Test confirmed feedback",
        BELIEF_FACTUAL,
        BSRC_AGENT_INFERRED,
        alpha=5.0,
        beta_param=1.0,
    )

    result: str = feedback(b.id, "confirmed")
    assert "Feedback recorded" in result

    updated: Belief | None = store.get_belief(b.id)
    assert updated is not None
    # confirmed: valence=+1.0, alpha += 1.0
    assert updated.alpha == pytest.approx(6.0)  # pyright: ignore[reportUnknownMemberType]


def test_feedback_weak_outcome() -> None:
    """feedback() with 'weak' should slightly increase beta."""
    store: MemoryStore = server_mod._get_store()
    b: Belief = store.insert_belief(
        "Test weak feedback",
        BELIEF_FACTUAL,
        BSRC_AGENT_INFERRED,
        alpha=5.0,
        beta_param=1.0,
    )

    result: str = feedback(b.id, "weak")
    assert "Feedback recorded" in result

    updated: Belief | None = store.get_belief(b.id)
    assert updated is not None
    # weak: valence=-0.6 (Fix 5: asymmetric), beta += 0.6
    assert updated.beta_param == pytest.approx(1.6)  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# 8. Integration: contradiction resolution via valence
# ---------------------------------------------------------------------------


def test_contradiction_resolution_via_confirm() -> None:
    """Confirming one side of a contradiction should weaken the other side."""
    store: MemoryStore = server_mod._get_store()

    correct_belief: Belief = store.insert_belief(
        "Use uv for Python package management",
        BELIEF_FACTUAL,
        BSRC_USER_STATED,
        alpha=5.0,
        beta_param=1.0,
    )
    wrong_belief: Belief = store.insert_belief(
        "Use pip for Python package management",
        BELIEF_FACTUAL,
        BSRC_AGENT_INFERRED,
        alpha=5.0,
        beta_param=1.0,
    )
    store.insert_edge(correct_belief.id, wrong_belief.id, EDGE_CONTRADICTS)

    # Confirm the correct belief
    confirm(correct_belief.id)

    wrong_after: Belief | None = store.get_belief(wrong_belief.id)
    assert wrong_after is not None
    # The wrong belief should have increased beta (weakened) via CONTRADICTS inversion
    assert wrong_after.beta_param > 1.0
    assert wrong_after.confidence < 5.0 / 6.0  # lower than original 0.833


def test_valence_column_in_tests_table(store: MemoryStore) -> None:
    """The tests table should have a valence column after migration."""
    cols = store.query("PRAGMA table_info(tests)")
    col_names: set[str] = {str(row["name"]) for row in cols}
    assert "valence" in col_names


def test_quality_score_column_in_sessions(store: MemoryStore) -> None:
    """The sessions table should have a quality_score column after migration."""
    cols = store.query("PRAGMA table_info(sessions)")
    col_names: set[str] = {str(row["name"]) for row in cols}
    assert "quality_score" in col_names
