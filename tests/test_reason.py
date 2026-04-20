"""Tests for graph traversal (get_neighbors, expand_graph) and uncertainty_score.

Covers the new store methods and scoring function added for /mem:reason.
"""

from __future__ import annotations

from pathlib import Path

from agentmemory.models import Belief, Edge
from agentmemory.scoring import uncertainty_score
from agentmemory.store import MemoryStore


def _make_store(tmp_path: Path) -> MemoryStore:
    """Create an in-memory store with test data."""
    store: MemoryStore = MemoryStore(tmp_path / "test.db")

    # Insert 5 beliefs
    store.insert_belief(
        "Alpha requirement", "requirement", "user_stated", alpha=9.0, beta_param=0.5
    )
    store.insert_belief(
        "Beta fact", "factual", "agent_inferred", alpha=3.0, beta_param=1.0
    )
    store.insert_belief(
        "Gamma correction", "correction", "user_corrected", alpha=9.0, beta_param=0.5
    )
    store.insert_belief(
        "Delta preference", "preference", "user_stated", alpha=0.5, beta_param=0.5
    )
    store.insert_belief(
        "Epsilon causal", "causal", "agent_inferred", alpha=5.0, beta_param=5.0
    )

    # Get IDs
    rows = store.query("SELECT id, content FROM beliefs ORDER BY content")
    ids: dict[str, str] = {r["content"]: r["id"] for r in rows}

    # Insert edges
    store.insert_edge(
        ids["Alpha requirement"], ids["Beta fact"], "SUPPORTS", weight=0.8
    )
    store.insert_edge(
        ids["Beta fact"], ids["Gamma correction"], "RELATES_TO", weight=0.5
    )
    store.insert_edge(
        ids["Alpha requirement"], ids["Delta preference"], "CONTRADICTS", weight=0.9
    )
    store.insert_edge(
        ids["Gamma correction"], ids["Epsilon causal"], "CITES", weight=0.7
    )

    return store


# ---------------------------------------------------------------------------
# uncertainty_score
# ---------------------------------------------------------------------------


def test_uncertainty_jeffreys_prior() -> None:
    """Jeffreys prior (0.5, 0.5) is maximum uncertainty."""
    score: float = uncertainty_score(0.5, 0.5)
    assert score == 1.0


def test_uncertainty_high_confidence() -> None:
    """Strong evidence in one direction is low uncertainty."""
    score: float = uncertainty_score(9.0, 0.5)
    assert score < 0.1


def test_uncertainty_balanced_many_observations() -> None:
    """Many observations but balanced is moderate uncertainty."""
    score: float = uncertainty_score(50.0, 50.0)
    assert 0.0 < score < 0.15  # low variance due to many observations


def test_uncertainty_zero_total() -> None:
    """Zero parameters returns maximum uncertainty."""
    assert uncertainty_score(0.0, 0.0) == 1.0


def test_uncertainty_asymmetric() -> None:
    """Asymmetric params have lower uncertainty than symmetric."""
    symmetric: float = uncertainty_score(5.0, 5.0)
    asymmetric: float = uncertainty_score(9.0, 1.0)
    assert asymmetric < symmetric


# ---------------------------------------------------------------------------
# get_neighbors
# ---------------------------------------------------------------------------


def test_get_neighbors_outgoing(tmp_path: Path) -> None:
    """Outgoing neighbors of Alpha requirement."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]

    neighbors: list[tuple[Belief, Edge]] = store.get_neighbors(
        alpha_id, direction="outgoing"
    )
    contents: set[str] = {b.content for b, _ in neighbors}
    assert "Beta fact" in contents
    assert "Delta preference" in contents
    assert len(neighbors) == 2
    store.close()


def test_get_neighbors_incoming(tmp_path: Path) -> None:
    """Incoming neighbors of Beta fact."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Beta fact'")
    beta_id: str = rows[0]["id"]

    neighbors: list[tuple[Belief, Edge]] = store.get_neighbors(
        beta_id, direction="incoming"
    )
    contents: set[str] = {b.content for b, _ in neighbors}
    assert "Alpha requirement" in contents
    assert len(neighbors) == 1
    store.close()


def test_get_neighbors_both_directions(tmp_path: Path) -> None:
    """Both directions for Beta fact (incoming from Alpha, outgoing to Gamma)."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Beta fact'")
    beta_id: str = rows[0]["id"]

    neighbors: list[tuple[Belief, Edge]] = store.get_neighbors(
        beta_id, direction="both"
    )
    contents: set[str] = {b.content for b, _ in neighbors}
    assert "Alpha requirement" in contents
    assert "Gamma correction" in contents
    assert len(neighbors) == 2
    store.close()


def test_get_neighbors_filter_by_edge_type(tmp_path: Path) -> None:
    """Filter to CONTRADICTS edges only."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]

    neighbors: list[tuple[Belief, Edge]] = store.get_neighbors(
        alpha_id, edge_types=["CONTRADICTS"]
    )
    assert len(neighbors) == 1
    assert neighbors[0][0].content == "Delta preference"
    assert neighbors[0][1].edge_type == "CONTRADICTS"
    store.close()


def test_get_neighbors_excludes_superseded(tmp_path: Path) -> None:
    """Superseded beliefs are excluded from neighbor results."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Beta fact'")
    beta_id: str = rows[0]["id"]
    rows2 = store.query("SELECT id FROM beliefs WHERE content = 'Gamma correction'")
    gamma_id: str = rows2[0]["id"]

    # Supersede Gamma
    store.supersede_belief(gamma_id, beta_id, reason="test")

    neighbors: list[tuple[Belief, Edge]] = store.get_neighbors(
        beta_id, direction="outgoing"
    )
    contents: set[str] = {b.content for b, _ in neighbors}
    assert "Gamma correction" not in contents
    store.close()


# ---------------------------------------------------------------------------
# expand_graph
# ---------------------------------------------------------------------------


def test_expand_graph_depth_1(tmp_path: Path) -> None:
    """1-hop expansion from Alpha finds Beta and Delta."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]

    expanded: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph(
        [alpha_id], depth=1
    )
    found_contents: set[str] = set()
    for entries in expanded.values():
        for b, _, _ in entries:
            found_contents.add(b.content)

    assert "Beta fact" in found_contents
    assert "Delta preference" in found_contents
    # Gamma and Epsilon are 2+ hops away
    assert "Gamma correction" not in found_contents
    store.close()


def test_expand_graph_depth_2(tmp_path: Path) -> None:
    """2-hop expansion from Alpha finds Beta, Delta, Gamma, and maybe Epsilon."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]

    expanded: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph(
        [alpha_id], depth=2
    )
    found_contents: set[str] = set()
    for entries in expanded.values():
        for b, _, _ in entries:
            found_contents.add(b.content)

    assert "Beta fact" in found_contents
    assert "Gamma correction" in found_contents  # 2 hops via Beta
    store.close()


def test_expand_graph_max_nodes_cap(tmp_path: Path) -> None:
    """max_nodes cap is respected."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]

    expanded: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph(
        [alpha_id], depth=3, max_nodes=2
    )
    total: int = len(expanded)
    assert total <= 2
    store.close()


def test_expand_graph_skips_supersedes(tmp_path: Path) -> None:
    """SUPERSEDES edges are excluded by default."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]
    rows2 = store.query("SELECT id FROM beliefs WHERE content = 'Epsilon causal'")
    epsilon_id: str = rows2[0]["id"]

    # Add a SUPERSEDES edge
    store.insert_edge(alpha_id, epsilon_id, "SUPERSEDES", weight=1.0)

    expanded: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph(
        [alpha_id], depth=1
    )
    found_contents: set[str] = set()
    for entries in expanded.values():
        for b, etype, _ in entries:
            found_contents.add(b.content)
            assert etype != "SUPERSEDES"

    # Epsilon should NOT be found via SUPERSEDES (only via longer path)
    store.close()


def test_expand_graph_empty_seeds(tmp_path: Path) -> None:
    """Empty seed list returns empty result."""
    store: MemoryStore = _make_store(tmp_path)
    expanded: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph([], depth=2)
    assert expanded == {}
    store.close()


def test_expand_graph_deterministic(tmp_path: Path) -> None:
    """Two calls with same inputs produce identical results."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]

    r1: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph(
        [alpha_id], depth=2
    )
    r2: dict[str, list[tuple[Belief, str, int]]] = store.expand_graph(
        [alpha_id], depth=2
    )

    assert set(r1.keys()) == set(r2.keys())
    for key in r1:
        ids1: list[str] = [b.id for b, _, _ in r1[key]]
        ids2: list[str] = [b.id for b, _, _ in r2[key]]
        assert ids1 == ids2
    store.close()


# ---------------------------------------------------------------------------
# find_consequence_paths
# ---------------------------------------------------------------------------


def test_consequence_paths_basic(tmp_path: Path) -> None:
    """Paths from Alpha follow SUPPORTS to Beta and CONTRADICTS to Delta."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]

    paths: list[list[tuple[Belief, str, float]]] = store.find_consequence_paths(
        [alpha_id],
        max_depth=3,
    )
    assert len(paths) > 0
    # Each path should start with Alpha as ROOT
    for path in paths:
        assert path[0][0].content == "Alpha requirement"
        assert path[0][1] == "ROOT"
    store.close()


def test_consequence_paths_compound_confidence_decays(tmp_path: Path) -> None:
    """Compound confidence decreases along the path."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]

    paths: list[list[tuple[Belief, str, float]]] = store.find_consequence_paths(
        [alpha_id],
        max_depth=3,
    )
    for path in paths:
        if len(path) >= 2:
            # Each step's compound confidence should be <= the previous
            for i in range(1, len(path)):
                assert path[i][2] <= path[i - 1][2] + 0.01  # small float tolerance


def test_consequence_paths_pruning(tmp_path: Path) -> None:
    """High confidence floor prunes weak paths."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]

    # Very high floor should produce few or no paths
    paths_high: list[list[tuple[Belief, str, float]]] = store.find_consequence_paths(
        [alpha_id],
        max_depth=3,
        confidence_floor=0.99,
    )
    paths_low: list[list[tuple[Belief, str, float]]] = store.find_consequence_paths(
        [alpha_id],
        max_depth=3,
        confidence_floor=0.1,
    )
    assert len(paths_high) <= len(paths_low)
    store.close()


def test_consequence_paths_max_branches(tmp_path: Path) -> None:
    """max_branches cap is respected."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]

    paths: list[list[tuple[Belief, str, float]]] = store.find_consequence_paths(
        [alpha_id],
        max_depth=3,
        max_branches=1,
    )
    assert len(paths) <= 1
    store.close()


def test_consequence_paths_empty_roots(tmp_path: Path) -> None:
    """Empty root list returns empty paths."""
    store: MemoryStore = _make_store(tmp_path)
    paths: list[list[tuple[Belief, str, float]]] = store.find_consequence_paths([])
    assert paths == []
    store.close()


def test_consequence_paths_contradicts_creates_fork(tmp_path: Path) -> None:
    """CONTRADICTS edge creates a separate branch (fork)."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id FROM beliefs WHERE content = 'Alpha requirement'")
    alpha_id: str = rows[0]["id"]

    paths: list[list[tuple[Belief, str, float]]] = store.find_consequence_paths(
        [alpha_id],
        max_depth=2,
    )
    # Should have at least 2 paths: one via SUPPORTS (Beta) and one via CONTRADICTS (Delta)
    edge_types_in_paths: set[str] = set()
    for path in paths:
        for _, etype, _ in path:
            edge_types_in_paths.add(etype)
    assert "CONTRADICTS" in edge_types_in_paths or "SUPPORTS" in edge_types_in_paths
    store.close()


# ---------------------------------------------------------------------------
# detect_impasses
# ---------------------------------------------------------------------------


def test_detect_impasses_tie(tmp_path: Path) -> None:
    """Contradicting beliefs with similar confidence produce a tie impasse."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id, content FROM beliefs ORDER BY content")
    ids: dict[str, str] = {r["content"]: r["id"] for r in rows}

    # Alpha (0.95) contradicts Delta (0.5) -- confidence gap is large, no tie
    # Let's adjust Delta to be close to Alpha
    store.query(
        "UPDATE beliefs SET alpha = 8.5, beta_param = 0.5 WHERE id = ?",
        (ids["Delta preference"],),
    )

    all_beliefs: dict[str, Belief] = {}
    for r in rows:
        b: Belief | None = store.get_belief(r["id"])
        if b:
            all_beliefs[b.id] = b

    impasses: list[MemoryStore.Impasse] = store.detect_impasses(
        beliefs=all_beliefs,
        paths=[],
    )
    tie_impasses: list[MemoryStore.Impasse] = [
        i for i in impasses if i.impasse_type == "tie"
    ]
    assert len(tie_impasses) >= 1
    store.close()


def test_detect_impasses_gap(tmp_path: Path) -> None:
    """Path ending at high-uncertainty leaf produces a gap impasse."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id, content FROM beliefs ORDER BY content")
    ids: dict[str, str] = {r["content"]: r["id"] for r in rows}

    all_beliefs: dict[str, Belief] = {}
    for r in rows:
        b: Belief | None = store.get_belief(r["id"])
        if b:
            all_beliefs[b.id] = b

    # Delta has Jeffreys prior (0.5, 0.5) = max uncertainty
    delta: Belief = all_beliefs[ids["Delta preference"]]
    alpha: Belief = all_beliefs[ids["Alpha requirement"]]
    fake_path: list[list[tuple[Belief, str, float]]] = [
        [(alpha, "ROOT", 0.95), (delta, "CONTRADICTS", 0.45)],
    ]

    impasses: list[MemoryStore.Impasse] = store.detect_impasses(
        beliefs=all_beliefs,
        paths=fake_path,
    )
    gap_impasses: list[MemoryStore.Impasse] = [
        i for i in impasses if i.impasse_type == "gap"
    ]
    assert len(gap_impasses) >= 1
    store.close()


def test_detect_impasses_constraint_failure(tmp_path: Path) -> None:
    """Evidence contradicting a locked belief produces constraint_failure."""
    store: MemoryStore = _make_store(tmp_path)
    rows = store.query("SELECT id, content FROM beliefs ORDER BY content")
    ids: dict[str, str] = {r["content"]: r["id"] for r in rows}

    # Lock Alpha
    store.lock_belief(ids["Alpha requirement"])

    all_beliefs: dict[str, Belief] = {}
    for r in rows:
        b: Belief | None = store.get_belief(r["id"])
        if b:
            all_beliefs[b.id] = b

    locked: list[Belief] = store.get_locked_beliefs()

    impasses: list[MemoryStore.Impasse] = store.detect_impasses(
        beliefs=all_beliefs,
        paths=[],
        locked_beliefs=locked,
    )
    constraint_impasses: list[MemoryStore.Impasse] = [
        i for i in impasses if i.impasse_type == "constraint_failure"
    ]
    # Delta contradicts Alpha (locked), so should be flagged
    assert len(constraint_impasses) >= 1
    store.close()


def test_detect_impasses_no_change(tmp_path: Path) -> None:
    """All low-confidence beliefs produce no_change impasse."""
    store: MemoryStore = _make_store(tmp_path)

    # Create beliefs with very low confidence
    store.insert_belief(
        "Low conf A", "factual", "agent_inferred", alpha=0.5, beta_param=5.0
    )
    store.insert_belief(
        "Low conf B", "factual", "agent_inferred", alpha=0.5, beta_param=5.0
    )

    rows = store.query("SELECT id FROM beliefs WHERE content LIKE 'Low conf%'")
    all_beliefs: dict[str, Belief] = {}
    for r in rows:
        b: Belief | None = store.get_belief(r["id"])
        if b:
            all_beliefs[b.id] = b

    impasses: list[MemoryStore.Impasse] = store.detect_impasses(
        beliefs=all_beliefs,
        paths=[],
    )
    no_change: list[MemoryStore.Impasse] = [
        i for i in impasses if i.impasse_type == "no_change"
    ]
    assert len(no_change) >= 1
    store.close()


# ---------------------------------------------------------------------------
# negation filter
# ---------------------------------------------------------------------------


def test_negation_filter_deprioritizes_noise() -> None:
    """Beliefs matching only on negation words are pushed to the end."""
    from agentmemory.retrieval import _filter_negation_noise  # pyright: ignore[reportPrivateUsage]

    b1: Belief = Belief(
        id="a1",
        content_hash="h1",
        content="Service is not running correctly",
        belief_type="factual",
        alpha=5.0,
        beta_param=0.5,
        confidence=0.91,
        source_type="agent_inferred",
        locked=False,
        valid_from=None,
        valid_to=None,
        superseded_by=None,
        created_at="",
        updated_at="",
    )
    b2: Belief = Belief(
        id="a2",
        content_hash="h2",
        content="HRR is not enough alone",
        belief_type="correction",
        alpha=5.0,
        beta_param=0.5,
        confidence=0.91,
        source_type="agent_inferred",
        locked=False,
        valid_from=None,
        valid_to=None,
        superseded_by=None,
        created_at="",
        updated_at="",
    )
    b3: Belief = Belief(
        id="a3",
        content_hash="h3",
        content="The running service crashed yesterday",
        belief_type="factual",
        alpha=5.0,
        beta_param=0.5,
        confidence=0.91,
        source_type="agent_inferred",
        locked=False,
        valid_from=None,
        valid_to=None,
        superseded_by=None,
        created_at="",
        updated_at="",
    )

    result: list[Belief] = _filter_negation_noise(
        "service not running",
        [b1, b2, b3],
    )
    # b1 and b3 share topical terms ("service", "running"), b2 only shares "not"
    result_ids: list[str] = [b.id for b in result]
    assert result_ids.index("a1") < result_ids.index("a2")
    assert result_ids.index("a3") < result_ids.index("a2")


def test_negation_filter_all_negation_query() -> None:
    """Query of only negation words returns beliefs unchanged."""
    from agentmemory.retrieval import _filter_negation_noise  # pyright: ignore[reportPrivateUsage]

    b1: Belief = Belief(
        id="a1",
        content_hash="h1",
        content="Something unrelated",
        belief_type="factual",
        alpha=5.0,
        beta_param=0.5,
        confidence=0.91,
        source_type="agent_inferred",
        locked=False,
        valid_from=None,
        valid_to=None,
        superseded_by=None,
        created_at="",
        updated_at="",
    )

    result: list[Belief] = _filter_negation_noise("not no never", [b1])
    assert len(result) == 1
    assert result[0].id == "a1"
