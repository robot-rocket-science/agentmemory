"""Tests for the retrieval pipeline: scoring, compression, and full retrieve()."""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from agentmemory.compression import compress_belief, estimate_tokens, pack_beliefs
from agentmemory.models import (
    BELIEF_CAUSAL,
    BELIEF_CORRECTION,
    BELIEF_FACTUAL,
    BELIEF_PREFERENCE,
    BELIEF_PROCEDURAL,
    BELIEF_RELATIONAL,
    BELIEF_REQUIREMENT,
    BSRC_AGENT_INFERRED,
    BSRC_USER_CORRECTED,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.scoring import (
    DECAY_HALF_LIVES,
    decay_factor,
    lock_boost_typed,
    score_belief,
    thompson_sample,
)
from agentmemory.store import MemoryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    s: MemoryStore = MemoryStore(tmp_path / "retrieval_test.db")
    yield s
    s.close()


@pytest.fixture()
def populated_store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    """Store pre-loaded with 20 beliefs covering all types, lock states, superseded."""
    s: MemoryStore = MemoryStore(tmp_path / "populated.db")

    # 5 locked beliefs -- should always appear (when include_locked=True)
    locked: list[Belief] = []
    for i in range(5):
        b: Belief = s.insert_belief(
            content=f"Locked belief number {i}: python typing is required",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_USER_STATED,
            alpha=5.0,
            beta_param=0.5,
            locked=True,
        )
        locked.append(b)

    # 5 normal unlocked beliefs that are query-relevant
    for i in range(5):
        s.insert_belief(
            content=f"Python typing rule {i}: always annotate return types",
            belief_type=BELIEF_REQUIREMENT,
            source_type=BSRC_USER_STATED,
            alpha=2.0,
            beta_param=1.0,
        )

    # 3 beliefs of varied types (irrelevant to query)
    s.insert_belief(
        content="User prefers dark mode in the editor",
        belief_type=BELIEF_PREFERENCE,
        source_type=BSRC_USER_STATED,
        alpha=3.0,
        beta_param=0.5,
    )
    s.insert_belief(
        content="Deploying to production causes downtime of 5 minutes",
        belief_type=BELIEF_CAUSAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=1.0,
        beta_param=2.0,
    )
    s.insert_belief(
        content="Module A relates to module B through the config layer",
        belief_type=BELIEF_RELATIONAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=1.0,
        beta_param=1.0,
    )

    # 3 procedural beliefs
    for i in range(3):
        s.insert_belief(
            content=(
                f"Step {i}: run the test suite. "
                "Ensure coverage. Check flake8. Verify types."
            ),
            belief_type=BELIEF_PROCEDURAL,
            source_type=BSRC_AGENT_INFERRED,
            alpha=1.5,
            beta_param=1.0,
        )

    # 2 correction beliefs (locked by convention)
    c1: Belief = s.insert_belief(
        content="Correction: do not use os.system(), use subprocess instead",
        belief_type=BELIEF_CORRECTION,
        source_type=BSRC_USER_CORRECTED,
        alpha=4.0,
        beta_param=0.5,
        locked=True,
    )
    _ = c1  # referenced below for supersede

    c2: Belief = s.insert_belief(
        content="Correction: use subprocess.run() with check=True always",
        belief_type=BELIEF_CORRECTION,
        source_type=BSRC_USER_CORRECTED,
        alpha=4.0,
        beta_param=0.5,
        locked=True,
    )
    _ = c2

    # 2 superseded beliefs -- must NOT appear in results
    old_b1: Belief = s.insert_belief(
        content="Old rule: imports must be sorted manually",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=1.0,
        beta_param=1.0,
    )
    new_b1: Belief = s.insert_belief(
        content="New rule: use isort for import sorting",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_USER_STATED,
        alpha=2.0,
        beta_param=0.5,
    )
    s.supersede_belief(old_b1.id, new_b1.id, reason="isort adopted")

    old_b2: Belief = s.insert_belief(
        content="Old setting: line length was 79 characters",
        belief_type=BELIEF_PREFERENCE,
        source_type=BSRC_AGENT_INFERRED,
        alpha=1.0,
        beta_param=1.0,
    )
    new_b2: Belief = s.insert_belief(
        content="Setting: line length is 88 characters (black default)",
        belief_type=BELIEF_PREFERENCE,
        source_type=BSRC_USER_STATED,
        alpha=2.0,
        beta_param=0.5,
    )
    s.supersede_belief(old_b2.id, new_b2.id, reason="switched to black")

    yield s
    s.close()


# ---------------------------------------------------------------------------
# scoring.py tests
# ---------------------------------------------------------------------------


class TestDecayFactor:
    def test_locked_returns_one(self, store: MemoryStore) -> None:
        b: Belief = store.insert_belief(
            content="Locked belief for decay test",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_USER_STATED,
            locked=True,
        )
        assert decay_factor(b, b.created_at) == 1.0

    def test_superseded_returns_point_zero_one(self, store: MemoryStore) -> None:
        old: Belief = store.insert_belief(
            content="Old factual belief for supersede decay",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )
        new: Belief = store.insert_belief(
            content="New factual belief for supersede decay",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_USER_STATED,
        )
        store.supersede_belief(old.id, new.id, reason="test")
        superseded: Belief | None = store.get_belief(old.id)
        assert superseded is not None
        assert decay_factor(superseded, superseded.created_at) == 0.01

    def test_no_half_life_type_returns_one(self, store: MemoryStore) -> None:
        b: Belief = store.insert_belief(
            content="A preference belief stays fresh forever",
            belief_type=BELIEF_PREFERENCE,
            source_type=BSRC_USER_STATED,
        )
        # DECAY_HALF_LIVES["preference"] is None -- should always be 1.0
        assert DECAY_HALF_LIVES["preference"] is None
        assert decay_factor(b, b.created_at) == 1.0

    def test_factual_decays_over_time(self, store: MemoryStore) -> None:
        b: Belief = store.insert_belief(
            content="A factual belief that will decay over time testing",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )
        # Simulate 336 hours (exactly one half-life) in the future
        import datetime as dt

        created: dt.datetime = dt.datetime.fromisoformat(b.created_at)
        future: dt.datetime = created + dt.timedelta(hours=336)
        factor: float = decay_factor(b, future.isoformat())
        assert 0.48 <= factor <= 0.52  # should be approx 0.5


class TestLockBoostTyped:
    def test_non_locked_returns_one(self, store: MemoryStore) -> None:
        b: Belief = store.insert_belief(
            content="Non-locked belief for boost test",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )
        result: float = lock_boost_typed(b, ["non-locked", "boost"])
        assert result == 1.0

    def test_locked_relevant_gets_boost(self, store: MemoryStore) -> None:
        b: Belief = store.insert_belief(
            content="Locked belief about python typing requirements",
            belief_type=BELIEF_REQUIREMENT,
            source_type=BSRC_USER_STATED,
            locked=True,
        )
        result: float = lock_boost_typed(b, ["python", "typing"], boost=2.0)
        # relevant locked belief: boost + 1.0 = 3.0
        assert result == 3.0

    def test_locked_irrelevant_returns_one(self, store: MemoryStore) -> None:
        b: Belief = store.insert_belief(
            content="Locked belief about deployment strategy",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_USER_STATED,
            locked=True,
        )
        result: float = lock_boost_typed(b, ["python", "typing"], boost=2.0)
        assert result == 1.0


class TestThompsonSample:
    def test_returns_float_in_range(self) -> None:
        for _ in range(20):
            s: float = thompson_sample(2.0, 1.0)
            assert 0.0 <= s <= 1.0

    def test_high_alpha_tends_high(self) -> None:
        samples: list[float] = [thompson_sample(100.0, 1.0) for _ in range(100)]
        assert sum(samples) / len(samples) > 0.9


class TestScoreBelief:
    def test_superseded_scores_low(self, store: MemoryStore) -> None:
        old: Belief = store.insert_belief(
            content="Old belief for score test superseded check",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )
        new: Belief = store.insert_belief(
            content="New belief for score test superseded check",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_USER_STATED,
        )
        store.supersede_belief(old.id, new.id, reason="test")
        superseded: Belief | None = store.get_belief(old.id)
        assert superseded is not None
        assert score_belief(superseded, "any query", superseded.created_at) == 0.01

    def test_locked_scores_higher_than_normal_on_average(self, store: MemoryStore) -> None:
        locked_b: Belief = store.insert_belief(
            content="Locked high confidence belief",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_USER_STATED,
            alpha=10.0,
            beta_param=0.5,
            locked=True,
        )
        normal_b: Belief = store.insert_belief(
            content="Normal low confidence belief for comparison",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
            alpha=0.5,
            beta_param=0.5,
        )
        import random
        random.seed(42)
        # Use a query that matches the locked belief content so lock_boost activates.
        locked_scores: list[float] = [
            score_belief(locked_b, "locked confidence belief", locked_b.created_at) for _ in range(50)
        ]
        normal_scores: list[float] = [
            score_belief(normal_b, "locked confidence belief", normal_b.created_at) for _ in range(50)
        ]
        assert sum(locked_scores) / len(locked_scores) > sum(normal_scores) / len(normal_scores)


# ---------------------------------------------------------------------------
# compression.py tests
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_empty_string(self) -> None:
        assert estimate_tokens("") == 0

    def test_rough_estimate(self) -> None:
        text: str = "a" * 350
        assert estimate_tokens(text) == 100


class TestCompressBelief:
    def test_factual_kept_full(self, store: MemoryStore) -> None:
        content: str = "The answer is 42. This is a very long factual statement that spans two sentences."
        b: Belief = store.insert_belief(
            content=content,
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_USER_STATED,
        )
        assert compress_belief(b) == content

    def test_causal_trimmed_to_first_sentence(self, store: MemoryStore) -> None:
        b: Belief = store.insert_belief(
            content="Deploying causes downtime. This happens because the server restarts.",
            belief_type=BELIEF_CAUSAL,
            source_type=BSRC_AGENT_INFERRED,
        )
        compressed: str = compress_belief(b)
        assert "downtime" in compressed
        # Should not contain the second sentence
        assert "restarts" not in compressed

    def test_procedural_includes_key_terms(self, store: MemoryStore) -> None:
        b: Belief = store.insert_belief(
            content="Run the tests. Check coverage. Verify TypeScript. Ensure Pyright passes.",
            belief_type=BELIEF_PROCEDURAL,
            source_type=BSRC_AGENT_INFERRED,
        )
        compressed: str = compress_belief(b)
        # First sentence must be present
        assert "Run" in compressed

    def test_compress_reduces_tokens_for_procedural(self, store: MemoryStore) -> None:
        long_content: str = (
            "Step one: install dependencies. "
            + "Then configure the environment variables and make sure all paths are correct. "
            + "Next verify the database schema is up to date with the latest migrations. "
            + "Finally run the test suite and check the coverage report thoroughly."
        )
        b: Belief = store.insert_belief(
            content=long_content,
            belief_type=BELIEF_PROCEDURAL,
            source_type=BSRC_AGENT_INFERRED,
        )
        compressed: str = compress_belief(b)
        assert estimate_tokens(compressed) < estimate_tokens(long_content)

    def test_correction_kept_full(self, store: MemoryStore) -> None:
        content: str = "Correction: never use eval(). Use ast.literal_eval() instead."
        b: Belief = store.insert_belief(
            content=content,
            belief_type=BELIEF_CORRECTION,
            source_type=BSRC_USER_CORRECTED,
            locked=True,
        )
        assert compress_belief(b) == content


class TestPackBeliefs:
    def test_respects_budget(self, store: MemoryStore) -> None:
        beliefs: list[Belief] = []
        for i in range(10):
            b: Belief = store.insert_belief(
                content=f"Belief number {i} with some text to consume tokens in the budget",
                belief_type=BELIEF_FACTUAL,
                source_type=BSRC_AGENT_INFERRED,
            )
            beliefs.append(b)

        _packed, total = pack_beliefs(beliefs, budget_tokens=50)
        assert total <= 50

    def test_returns_in_order(self, store: MemoryStore) -> None:
        beliefs: list[Belief] = [
            store.insert_belief(
                content=f"Ranked belief {i}",
                belief_type=BELIEF_FACTUAL,
                source_type=BSRC_AGENT_INFERRED,
            )
            for i in range(5)
        ]
        packed, _tokens = pack_beliefs(beliefs, budget_tokens=2000)
        assert [b.id for b in packed] == [b.id for b in beliefs[: len(packed)]]

    def test_empty_input(self) -> None:
        assert pack_beliefs([], budget_tokens=1000) == ([], 0)

    def test_zero_budget_returns_empty(self, store: MemoryStore) -> None:
        b: Belief = store.insert_belief(
            content="Some belief that cannot fit in zero budget",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )
        packed, _tokens = pack_beliefs([b], budget_tokens=0)
        assert packed == []


# ---------------------------------------------------------------------------
# retrieval.py integration tests
# ---------------------------------------------------------------------------


class TestRetrieve:
    def test_locked_beliefs_always_in_results(
        self, populated_store: MemoryStore
    ) -> None:
        result: RetrievalResult = retrieve(
            populated_store, query="python typing", budget=4000
        )
        locked_in_store: list[Belief] = populated_store.get_locked_beliefs()
        result_ids: set[str] = {b.id for b in result.beliefs}
        for locked_b in locked_in_store:
            assert locked_b.id in result_ids, (
                f"Locked belief {locked_b.id!r} missing from results"
            )

    def test_superseded_not_in_results(self, populated_store: MemoryStore) -> None:
        result: RetrievalResult = retrieve(
            populated_store, query="python typing", budget=4000
        )
        _result_ids: set[str] = {b.id for b in result.beliefs}
        # All returned beliefs must have valid_to == None and superseded_by == None
        for b in result.beliefs:
            assert b.valid_to is None, f"Superseded belief {b.id!r} in results"
            assert b.superseded_by is None, f"Superseded belief {b.id!r} in results"

    def test_total_tokens_within_budget(self, populated_store: MemoryStore) -> None:
        budget: int = 500
        result: RetrievalResult = retrieve(
            populated_store, query="python", budget=budget
        )
        assert result.total_tokens <= budget
        assert result.budget_remaining >= 0
        assert result.total_tokens + result.budget_remaining == budget

    def test_results_sorted_by_score_descending(
        self, populated_store: MemoryStore
    ) -> None:
        result: RetrievalResult = retrieve(
            populated_store, query="python typing", budget=4000
        )
        scores: list[float] = [result.scores[b.id] for b in result.beliefs]
        assert scores == sorted(scores, reverse=True), "Results not sorted by score"

    def test_scores_dict_matches_beliefs(self, populated_store: MemoryStore) -> None:
        result: RetrievalResult = retrieve(
            populated_store, query="typing", budget=4000
        )
        for b in result.beliefs:
            assert b.id in result.scores

    def test_include_locked_false_excludes_locked(
        self, populated_store: MemoryStore
    ) -> None:
        locked_ids: set[str] = {
            b.id for b in populated_store.get_locked_beliefs()
        }
        result: RetrievalResult = retrieve(
            populated_store,
            query="python typing",
            budget=4000,
            include_locked=False,
        )
        for b in result.beliefs:
            assert b.id not in locked_ids, (
                f"Locked belief {b.id!r} appeared despite include_locked=False"
            )

    def test_empty_query_still_returns_locked(
        self, populated_store: MemoryStore
    ) -> None:
        result: RetrievalResult = retrieve(
            populated_store, query="", budget=4000
        )
        locked_in_store: list[Belief] = populated_store.get_locked_beliefs()
        result_ids: set[str] = {b.id for b in result.beliefs}
        for locked_b in locked_in_store:
            assert locked_b.id in result_ids

    def test_returns_retrieval_result_type(self, store: MemoryStore) -> None:
        store.insert_belief(
            content="A simple belief for type check",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_USER_STATED,
        )
        result: RetrievalResult = retrieve(store, query="simple", budget=2000)
        assert isinstance(result, RetrievalResult)
        assert isinstance(result.beliefs, list)
        assert isinstance(result.scores, dict)
        assert isinstance(result.total_tokens, int)
        assert isinstance(result.budget_remaining, int)
