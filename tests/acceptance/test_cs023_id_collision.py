"""CS-023: ID Collision.

Pass criterion: Content-hash dedup in insert_observation prevents duplicate
observations from being stored, while distinct content produces separate rows.
"""

from __future__ import annotations

from agentmemory.models import OBS_TYPE_DECISION, SRC_AGENT, Observation
from agentmemory.store import MemoryStore


def test_cs023_content_hash_dedup(store: MemoryStore) -> None:
    """Insert two observations with identical content. Only one row should exist
    in the database because insert_observation deduplicates by content hash."""
    content: str = "The retrieval pipeline uses a three-stage scoring model."

    obs1: Observation = store.insert_observation(
        content=content,
        observation_type=OBS_TYPE_DECISION,
        source_type=SRC_AGENT,
    )
    obs2: Observation = store.insert_observation(
        content=content,
        observation_type=OBS_TYPE_DECISION,
        source_type=SRC_AGENT,
    )

    # Both calls return the same observation (dedup by content hash).
    assert obs1.id == obs2.id, (
        f"Duplicate content should return the same observation. "
        f"Got ids: {obs1.id}, {obs2.id}"
    )

    # Verify only one row in the database.
    conn = store._conn  # pyright: ignore[reportPrivateUsage]
    row = conn.execute("SELECT COUNT(*) AS cnt FROM observations").fetchone()
    assert row is not None
    assert int(row["cnt"]) == 1, (
        f"Expected exactly 1 observation after duplicate insert, got {row['cnt']}"
    )


def test_cs023_different_content_distinct(store: MemoryStore) -> None:
    """Insert two observations with different content. Both should be stored
    as separate rows since their content hashes differ."""
    obs1: Observation = store.insert_observation(
        content="Retrieval uses FTS5 full-text search.",
        observation_type=OBS_TYPE_DECISION,
        source_type=SRC_AGENT,
    )
    obs2: Observation = store.insert_observation(
        content="HRR binding provides associative recall.",
        observation_type=OBS_TYPE_DECISION,
        source_type=SRC_AGENT,
    )

    assert obs1.id != obs2.id, (
        f"Different content should produce different observations. "
        f"Got ids: {obs1.id}, {obs2.id}"
    )

    conn = store._conn  # pyright: ignore[reportPrivateUsage]
    row = conn.execute("SELECT COUNT(*) AS cnt FROM observations").fetchone()
    assert row is not None
    assert int(row["cnt"]) == 2, (
        f"Expected 2 observations for distinct content, got {row['cnt']}"
    )
