"""Project isolation validation.

Verifies that separate database files have no data leakage between them.
Each MemoryStore instance operating on a different DB path must be fully
independent -- beliefs inserted in one must never appear in another.
"""
from __future__ import annotations

from pathlib import Path

from agentmemory.models import BELIEF_FACTUAL, BSRC_AGENT_INFERRED, Belief
from agentmemory.store import MemoryStore


def test_separate_dbs_no_leakage(tmp_path: Path) -> None:
    """Beliefs in separate DB files must never leak across stores."""
    db_a: Path = tmp_path / "a.db"
    db_b: Path = tmp_path / "b.db"

    # Store A: insert a React belief.
    store_a: MemoryStore = MemoryStore(db_a)
    belief_a: Belief = store_a.insert_belief(
        content="Project A uses React for the frontend framework",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    store_a.close()

    # Store B: insert a Vue belief.
    store_b: MemoryStore = MemoryStore(db_b)
    belief_b: Belief = store_b.insert_belief(
        content="Project B uses Vue for the frontend framework",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    store_b.close()

    # Reopen A: must see React, must NOT see Vue.
    store_a2: MemoryStore = MemoryStore(db_a)
    a_results_vue: list[Belief] = store_a2.search("Vue")
    a_results_react: list[Belief] = store_a2.search("React")

    assert len(a_results_vue) == 0, (
        f"Store A leaked: found {len(a_results_vue)} Vue results"
    )
    assert any(b.id == belief_a.id for b in a_results_react), (
        "Store A must find its own React belief"
    )
    store_a2.close()

    # Reopen B: must see Vue, must NOT see React.
    store_b2: MemoryStore = MemoryStore(db_b)
    b_results_react: list[Belief] = store_b2.search("React")
    b_results_vue: list[Belief] = store_b2.search("Vue")

    assert len(b_results_react) == 0, (
        f"Store B leaked: found {len(b_results_react)} React results"
    )
    assert any(b.id == belief_b.id for b in b_results_vue), (
        "Store B must find its own Vue belief"
    )
    store_b2.close()
