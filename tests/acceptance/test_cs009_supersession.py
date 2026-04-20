"""CS-009: Correction persists across context resets via SUPERSEDES edges.

Pass criterion: After a correction is recorded, the original belief is excluded
from search results and the new belief appears in its place.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_PROCEDURAL,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.server import _set_store, correct  # pyright: ignore[reportPrivateUsage]
from agentmemory.store import MemoryStore


def test_cs009_original_belief_superseded(store: MemoryStore) -> None:
    """After correct(), original belief has valid_to set and superseded_by pointing
    to the new belief."""
    _set_store(store)  # pyright: ignore[reportPrivateUsage]

    # Step 1: insert the original (wrong) belief.
    original: Belief = store.insert_belief(
        content="Use gcloud deployment for cloud functions",
        belief_type=BELIEF_PROCEDURAL,
        source_type=BSRC_USER_STATED,
        alpha=5.0,
        beta_param=0.5,
        locked=False,
    )
    assert original.valid_to is None
    assert original.superseded_by is None

    # Step 2: issue correction that supersedes the original.
    result_text: str = correct(
        "Use terraform for cloud functions, not gcloud",
        replaces="gcloud deployment",
    )
    assert "Correction recorded" in result_text

    # Step 3: verify original is now marked superseded.
    updated_original: Belief | None = store.get_belief(original.id)
    assert updated_original is not None
    assert updated_original.valid_to is not None, (
        "Original belief must have valid_to set after supersession"
    )
    assert updated_original.superseded_by is not None, (
        "Original belief must have superseded_by pointing to replacement"
    )


def test_cs009_supersedes_edge_exists(store: MemoryStore) -> None:
    """After correct(), a SUPERSEDES edge must exist from the new belief to the old."""
    import sqlite3

    _set_store(store)  # pyright: ignore[reportPrivateUsage]

    original: Belief = store.insert_belief(
        content="Use gcloud deployment for cloud functions",
        belief_type=BELIEF_PROCEDURAL,
        source_type=BSRC_USER_STATED,
        alpha=5.0,
        beta_param=0.5,
        locked=False,
    )

    correct(
        "Use terraform for cloud functions, not gcloud", replaces="gcloud deployment"
    )

    # Query for SUPERSEDES edge targeting the original belief.
    rows: list[sqlite3.Row] = store.query(
        "SELECT * FROM edges WHERE edge_type = 'SUPERSEDES' AND to_id = ?",
        (original.id,),
    )
    assert rows, (
        f"Expected a SUPERSEDES edge targeting original belief {original.id}. "
        "No edges found."
    )


def test_cs009_terraform_belief_in_search(store: MemoryStore) -> None:
    """After correction, the terraform belief appears in search results for
    'how to deploy cloud functions'."""
    _set_store(store)  # pyright: ignore[reportPrivateUsage]

    store.insert_belief(
        content="Use gcloud deployment for cloud functions",
        belief_type=BELIEF_PROCEDURAL,
        source_type=BSRC_USER_STATED,
        alpha=5.0,
        beta_param=0.5,
        locked=False,
    )

    correct(
        "Use terraform for cloud functions, not gcloud", replaces="gcloud deployment"
    )

    # FTS5 AND semantics: use tokens present in the terraform belief content.
    results: list[Belief] = store.search("terraform cloud functions")
    assert results, "Expected at least one belief for deployment query"

    contents: list[str] = [b.content for b in results]
    assert any("terraform" in c.lower() for c in contents), (
        f"Expected terraform belief in results. Got: {contents}"
    )


def test_cs009_gcloud_belief_excluded_from_search(store: MemoryStore) -> None:
    """After correction, the superseded gcloud belief must NOT appear in search
    results (valid_to IS NOT NULL exclusion in FTS5 query)."""
    _set_store(store)  # pyright: ignore[reportPrivateUsage]

    original: Belief = store.insert_belief(
        content="Use gcloud deployment for cloud functions",
        belief_type=BELIEF_PROCEDURAL,
        source_type=BSRC_USER_STATED,
        alpha=5.0,
        beta_param=0.5,
        locked=False,
    )

    correct(
        "Use terraform for cloud functions, not gcloud", replaces="gcloud deployment"
    )

    # FTS5 AND semantics: use tokens present in the terraform belief content.
    results: list[Belief] = store.search("terraform cloud functions")
    result_ids: list[str] = [b.id for b in results]

    assert original.id not in result_ids, (
        f"Superseded gcloud belief {original.id} must be excluded from search results. "
        f"Found in results: {result_ids}"
    )
