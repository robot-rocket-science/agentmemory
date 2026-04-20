"""CS-013: Tool-specific correction retrieved at command time.

Pass criterion: A correction about gcloud filter syntax can be found by
searching for the exact tool name or the general topic.
"""
from __future__ import annotations

from agentmemory.models import (
    BELIEF_CORRECTION,
    BSRC_USER_CORRECTED,
    Belief,
)
from agentmemory.store import MemoryStore


def _insert_gcloud_correction(store: MemoryStore) -> Belief:
    return store.insert_belief(
        content="gcloud filter OR syntax is space-separated, not pipe",
        belief_type=BELIEF_CORRECTION,
        source_type=BSRC_USER_CORRECTED,
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )


def test_cs013_exact_tool_query(store: MemoryStore) -> None:
    """Searching 'gcloud filter' finds the correction.

    Note: 'OR' is a reserved FTS5 keyword and cannot appear as a bare token in
    the query string. We use 'gcloud filter' which matches both tokens present
    in the belief content.
    """
    correction: Belief = _insert_gcloud_correction(store)

    # "OR" is an FTS5 reserved keyword -- use "gcloud filter" instead.
    results: list[Belief] = store.search("gcloud filter")
    assert results, "Expected at least one result for 'gcloud filter'"

    result_ids: list[str] = [b.id for b in results]
    assert correction.id in result_ids, (
        f"Correction {correction.id} not found by 'gcloud filter'. "
        f"Got: {[b.content for b in results]}"
    )


def test_cs013_general_syntax_query(store: MemoryStore) -> None:
    """Searching 'gcloud syntax' still returns the correction because
    FTS5 matches on both 'gcloud' and 'syntax' tokens present in the belief."""
    correction: Belief = _insert_gcloud_correction(store)

    # Both 'gcloud' and 'syntax' appear in the belief content.
    results: list[Belief] = store.search("gcloud syntax")
    assert results, "Expected at least one result for 'gcloud syntax'"

    result_ids: list[str] = [b.id for b in results]
    assert correction.id in result_ids, (
        f"Correction {correction.id} not found by 'gcloud syntax'. "
        f"Got: {[b.content for b in results]}"
    )


def test_cs013_correction_is_locked(store: MemoryStore) -> None:
    """The retrieved correction must be locked (persists indefinitely)."""
    _insert_gcloud_correction(store)

    results: list[Belief] = store.search("gcloud filter")
    assert results

    locked_results: list[Belief] = [b for b in results if b.locked]
    assert locked_results, (
        "The gcloud syntax correction must be locked. "
        f"Got: {[b.locked for b in results]}"
    )


def test_cs013_correction_not_superseded(store: MemoryStore) -> None:
    """The gcloud correction must not be excluded (valid_to must be None)."""
    correction: Belief = _insert_gcloud_correction(store)

    fetched: Belief | None = store.get_belief(correction.id)
    assert fetched is not None
    assert fetched.valid_to is None, (
        "A freshly-inserted correction must have valid_to=None (not superseded)"
    )
    assert fetched.superseded_by is None
