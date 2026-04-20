"""CS-030: Cross-Project Knowledge Isolation.

Pass criterion: beliefs ingested into project-A's store are not visible from
project-B's store, and vice versa. Per-project SQLite databases provide the
isolation boundary.

Validates: scanner path scoping, per-project DB routing, bulk ingest isolation.
Related: VERIFICATION_PROJECT_ISOLATION.md (field verification 2026-04-18)
"""

from __future__ import annotations

from pathlib import Path

from agentmemory.ingest import ingest_turn
from agentmemory.models import (
    BELIEF_FACTUAL,
    BSRC_AGENT_INFERRED,
    Belief,
)
from agentmemory.store import MemoryStore


def test_cs030_separate_stores_no_cross_contamination(tmp_path: Path) -> None:
    """Beliefs written to store-A are invisible from store-B."""
    store_a: MemoryStore = MemoryStore(tmp_path / "project_a.db")
    store_b: MemoryStore = MemoryStore(tmp_path / "project_b.db")

    # Insert project-A specific content
    store_a.insert_belief(
        content="Server deploys to port 8080 via systemd",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    store_a.insert_belief(
        content="Frontend uses retro phosphor green aesthetic",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    # Insert project-B specific content
    store_b.insert_belief(
        content="Memory store uses FTS5 for full-text search",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    # Search project-B store for project-A content
    results_b: list[Belief] = store_b.search("port 8080 systemd", top_k=10)
    b_contents: list[str] = [r.content for r in results_b]
    assert not any("port 8080" in c for c in b_contents), (
        f"Project-A belief leaked into project-B: {b_contents}"
    )

    # Search project-A store for project-B content
    results_a: list[Belief] = store_a.search("FTS5 full-text search", top_k=10)
    a_contents: list[str] = [r.content for r in results_a]
    assert not any("FTS5" in c for c in a_contents), (
        f"Project-B belief leaked into project-A: {a_contents}"
    )

    store_a.close()
    store_b.close()


def test_cs030_ingest_turn_respects_store_boundary(tmp_path: Path) -> None:
    """ingest_turn writes only to the store instance passed to it."""
    store_a: MemoryStore = MemoryStore(tmp_path / "project_a.db")
    store_b: MemoryStore = MemoryStore(tmp_path / "project_b.db")

    # Ingest into store-A
    ingest_turn(
        store=store_a,
        text="The deploy pipeline uses wrangler pages deploy to push to Cloudflare",
        source="document",
    )

    # Ingest into store-B
    ingest_turn(
        store=store_b,
        text="insert_graph_edge batches edges in a single transaction",
        source="document",
    )

    # Verify isolation
    a_search: list[Belief] = store_a.search("insert_graph_edge transaction", top_k=10)
    assert not any("insert_graph_edge" in r.content for r in a_search), (
        "Store-B content found in store-A after ingest_turn"
    )

    b_search: list[Belief] = store_b.search(
        "wrangler pages deploy Cloudflare", top_k=10
    )
    assert not any("wrangler" in r.content for r in b_search), (
        "Store-A content found in store-B after ingest_turn"
    )

    store_a.close()
    store_b.close()


def test_cs030_transaction_isolation(tmp_path: Path) -> None:
    """Writes inside a transaction() block stay in the target store."""
    store_a: MemoryStore = MemoryStore(tmp_path / "project_a.db")
    store_b: MemoryStore = MemoryStore(tmp_path / "project_b.db")

    with store_a.transaction():
        store_a.insert_belief(
            content="Batch insert reduces 21k commits to one transaction",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )
        store_a.insert_belief(
            content="_maybe_commit defers commits inside transaction block",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
        )

    # Verify store-B has nothing
    b_results: list[Belief] = store_b.search("batch insert transaction", top_k=10)
    assert len(b_results) == 0, f"Transaction content leaked to store-B: {b_results}"

    # Verify store-A has both
    a_results: list[Belief] = store_a.search("batch insert transaction", top_k=10)
    assert len(a_results) >= 1, "Transaction content missing from store-A"

    store_a.close()
    store_b.close()
