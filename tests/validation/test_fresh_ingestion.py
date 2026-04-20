"""End-to-end ingestion validation test.

Run on a fresh DB against an arbitrary project to verify the full
onboard -> classify -> retrieve pipeline works correctly.

Usage:
    # Default: tests against ~/projects/robotrocketscience
    uv run pytest tests/validation/test_fresh_ingestion.py -v

    # Custom project:
    TEST_PROJECT=/path/to/project uv run pytest tests/validation/test_fresh_ingestion.py -v

The test uses an isolated DB (temp dir) so it won't touch your live memory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
import pytest

from agentmemory.models import Belief
from agentmemory.scanner import ScanResult, scan_project
from agentmemory.store import MemoryStore
from agentmemory.ingest import extract_turn
from agentmemory.retrieval import retrieve


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class OnboardResult:
    """Typed container for scan + extract outputs."""

    scan: ScanResult
    scan_time: float
    observations_created: int
    sentences: list[dict[str, str]]
    edges_inserted: int


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_PROJECT = (
    Path(os.environ.get("TEST_PROJECT", "~/projects/robotrocketscience"))
    .expanduser()
    .resolve()
)


@pytest.fixture(scope="module")
def tmp_db() -> Generator[Path, None, None]:
    """Create a temporary DB path for the test run."""
    d = tempfile.mkdtemp(prefix="agentmemory_validation_")
    db_path = Path(d) / "test_memory.db"
    yield db_path
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(scope="module")
def store(tmp_db: Path) -> MemoryStore:
    """Create a fresh MemoryStore on the temp DB."""
    return MemoryStore(str(tmp_db))


@pytest.fixture(scope="module")
def scan_result(store: MemoryStore) -> OnboardResult:
    """Run the full onboard pipeline and return results."""
    if not TEST_PROJECT.is_dir():
        pytest.skip(f"Test project not found: {TEST_PROJECT}")

    # Phase 1: Scan
    t0 = time.perf_counter()
    scan = scan_project(TEST_PROJECT)
    scan_time = time.perf_counter() - t0

    # Phase 2: Extract observations and sentences
    observations_created = 0
    all_sentences: list[dict[str, str]] = []

    for node in scan.nodes:
        if node.node_type == "file":
            continue

        source = "document"
        if node.node_type == "commit_belief":
            source = "git"
        elif node.node_type == "behavioral_belief":
            source = "directive"
        elif node.node_type == "callable":
            source = "code"

        extracted = extract_turn(
            store=store,
            text=node.content,
            source=source,
            session_id=None,
            created_at=node.date,
            source_path=node.file or "",
        )
        observations_created += 1

        for text, src in extracted.sentences:
            all_sentences.append(
                {
                    "text": text,
                    "source": src,
                    "observation_id": extracted.observation.id,
                    "created_at": node.date or "",
                    "is_correction": str(extracted.full_text_is_correction),
                    "full_text": node.content,
                }
            )

    # Phase 3: Insert edges
    edges_inserted = 0
    for edge in scan.edges:
        store.insert_graph_edge(
            from_id=edge.src,
            to_id=edge.tgt,
            edge_type=edge.edge_type,
            weight=edge.weight,
            reason="scanner",
        )
        edges_inserted += 1

    # Record provenance
    commit_hash: str | None = None
    try:
        commit_hash = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=str(TEST_PROJECT),
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        pass
    store.record_onboarding_run(
        project_path=str(TEST_PROJECT),
        commit_hash=commit_hash,
        nodes_extracted=len(scan.nodes),
        edges_extracted=len(scan.edges),
        beliefs_created=0,
        observations_created=observations_created,
    )

    return OnboardResult(
        scan=scan,
        scan_time=scan_time,
        observations_created=observations_created,
        sentences=all_sentences,
        edges_inserted=edges_inserted,
    )


@pytest.fixture(scope="module")
def beliefs_created(store: MemoryStore, scan_result: OnboardResult) -> int:
    """Create beliefs from sentences using offline classification."""
    count = 0
    for sentence in scan_result.sentences:
        belief = store.insert_belief(
            content=sentence["text"],
            belief_type="factual",
            source_type="agent_inferred",
            observation_id=sentence["observation_id"],
            created_at=sentence["created_at"] or None,
        )
        count += 1
        _ = belief  # used for dedup counting
    return count


# ---------------------------------------------------------------------------
# Phase 1: Install verification (import-level)
# ---------------------------------------------------------------------------


class TestPhase1Install:
    """Verify the package imports and core components are available."""

    def test_import_store(self) -> None:
        from agentmemory.store import MemoryStore as _MS

        assert _MS is not None

    def test_import_scanner(self) -> None:
        from agentmemory.scanner import scan_project as _sp

        assert _sp is not None

    def test_import_retrieval(self) -> None:
        from agentmemory.retrieval import retrieve as _r

        assert _r is not None

    def test_import_server(self) -> None:
        from agentmemory.server import mcp

        assert mcp is not None

    def test_import_cli(self) -> None:
        from agentmemory.cli import main

        assert main is not None


# ---------------------------------------------------------------------------
# Phase 2: Onboard pipeline
# ---------------------------------------------------------------------------


class TestPhase2Onboard:
    """Verify the scan + extract pipeline produces expected outputs."""

    def test_project_exists(self) -> None:
        if not TEST_PROJECT.is_dir():
            pytest.skip(f"Test project not found: {TEST_PROJECT}")
        assert TEST_PROJECT.is_dir()

    def test_scan_completes(self, scan_result: OnboardResult) -> None:
        assert scan_result.scan is not None

    def test_scan_time_reasonable(self, scan_result: OnboardResult) -> None:
        assert scan_result.scan_time < 30.0, f"Scan took {scan_result.scan_time:.1f}s"

    def test_nodes_extracted(self, scan_result: OnboardResult) -> None:
        assert len(scan_result.scan.nodes) > 0, "No nodes extracted"

    def test_node_type_diversity(self, scan_result: OnboardResult) -> None:
        types = {n.node_type for n in scan_result.scan.nodes}
        assert len(types) >= 2, f"Only node types: {types}"

    def test_edges_extracted(self, scan_result: OnboardResult) -> None:
        assert scan_result.edges_inserted > 0, "No edges extracted"

    def test_edge_type_diversity(self, scan_result: OnboardResult) -> None:
        types = {e.edge_type for e in scan_result.scan.edges}
        assert len(types) >= 2, f"Only edge types: {types}"

    def test_observations_created(self, scan_result: OnboardResult) -> None:
        assert scan_result.observations_created > 0

    def test_sentences_extracted(self, scan_result: OnboardResult) -> None:
        assert len(scan_result.sentences) > 0

    def test_sentences_have_required_fields(
        self,
        scan_result: OnboardResult,
    ) -> None:
        required = {"text", "source", "observation_id"}
        for s in scan_result.sentences[:10]:
            assert required.issubset(s.keys()), f"Missing keys: {required - s.keys()}"


# ---------------------------------------------------------------------------
# Phase 3: Belief creation
# ---------------------------------------------------------------------------


class TestPhase3Beliefs:
    """Verify beliefs are created and indexed correctly."""

    def test_beliefs_created(self, beliefs_created: int) -> None:
        assert beliefs_created > 0, "No beliefs created"

    def test_fts5_search_works(
        self,
        store: MemoryStore,
        beliefs_created: int,
    ) -> None:
        results = store.search("project", top_k=5)
        assert isinstance(results, list)

    def test_belief_retrievable_by_id(
        self,
        store: MemoryStore,
        beliefs_created: int,
    ) -> None:
        all_beliefs = store.get_all_active_beliefs(limit=1)
        assert len(all_beliefs) >= 1
        belief = store.get_belief(all_beliefs[0].id)
        assert belief is not None


# ---------------------------------------------------------------------------
# Phase 4: Retrieval pipeline
# ---------------------------------------------------------------------------


class TestPhase4Retrieval:
    """Verify the full retrieval pipeline works end-to-end."""

    def test_retrieve_returns_results(
        self,
        store: MemoryStore,
        beliefs_created: int,
    ) -> None:
        result = retrieve(store, "project structure files")
        assert len(result.beliefs) > 0, "Retrieval returned nothing"

    def test_retrieve_latency(
        self,
        store: MemoryStore,
        beliefs_created: int,
    ) -> None:
        t0 = time.perf_counter()
        retrieve(store, "configuration settings")
        latency_ms = (time.perf_counter() - t0) * 1000
        assert latency_ms < 2000, f"Retrieval took {latency_ms:.0f}ms"

    def test_retrieve_has_scores(
        self,
        store: MemoryStore,
        beliefs_created: int,
    ) -> None:
        result = retrieve(store, "code functions implementation")
        for belief in result.beliefs:
            score = result.scores.get(belief.id, 0.0)
            assert score > 0, f"Belief {belief.id} has zero score"
            assert belief.content, f"Belief {belief.id} has empty content"

    def test_retrieve_respects_budget(
        self,
        store: MemoryStore,
        beliefs_created: int,
    ) -> None:
        result = retrieve(store, "everything about the project", budget=500)
        assert result.total_tokens <= 600, (
            f"Budget exceeded: {result.total_tokens} tokens (budget=500)"
        )


# ---------------------------------------------------------------------------
# Phase 5: MCP tool coverage (store-level)
# ---------------------------------------------------------------------------


class TestPhase5Tools:
    """Verify core MCP tool operations work at the store level."""

    def test_insert_belief(self, store: MemoryStore) -> None:
        belief: Belief = store.insert_belief(
            content="test rule: always use strict typing",
            belief_type="correction",
            source_type="user_corrected",
        )
        assert belief.id

    def test_supersede(self, store: MemoryStore) -> None:
        old: Belief = store.insert_belief(
            content="use approach A for testing",
            belief_type="factual",
            source_type="agent_inferred",
        )
        new: Belief = store.insert_belief(
            content="use approach B for testing (replaces A)",
            belief_type="correction",
            source_type="user_corrected",
        )
        store.supersede_belief(old.id, new.id, reason="test correction")

        old_refreshed = store.get_belief(old.id)
        assert old_refreshed is not None
        assert old_refreshed.valid_to is not None, (
            "Superseded belief should have valid_to set"
        )

    def test_lock_belief(self, store: MemoryStore) -> None:
        belief: Belief = store.insert_belief(
            content="test locked constraint for validation",
            belief_type="correction",
            source_type="user_corrected",
        )
        store.lock_belief(belief.id)
        locked = store.get_belief(belief.id)
        assert locked is not None
        assert locked.locked is True

    def test_get_locked(self, store: MemoryStore) -> None:
        locked_beliefs = store.get_locked_beliefs()
        assert len(locked_beliefs) >= 1

    def test_insert_observation(self, store: MemoryStore) -> None:
        obs = store.insert_observation(
            content="test observation from validation",
            observation_type="test",
            source_type="test",
        )
        assert obs.id

    def test_feedback_updates_confidence(self, store: MemoryStore) -> None:
        belief: Belief = store.insert_belief(
            content="test feedback target for validation",
            belief_type="factual",
            source_type="agent_inferred",
        )
        original_confidence = belief.confidence
        store.update_confidence(belief.id, "used")
        updated = store.get_belief(belief.id)
        assert updated is not None
        assert updated.confidence >= original_confidence, (
            "Positive feedback should not decrease confidence"
        )

    def test_soft_delete(self, store: MemoryStore) -> None:
        belief: Belief = store.insert_belief(
            content="test delete target for validation",
            belief_type="factual",
            source_type="agent_inferred",
        )
        store.soft_delete_belief(belief.id)
        deleted = store.get_belief(belief.id)
        if deleted is not None:
            assert deleted.valid_to is not None


# ---------------------------------------------------------------------------
# Phase 6: Session continuity
# ---------------------------------------------------------------------------


class TestPhase6SessionContinuity:
    """Verify data persists across store re-instantiation."""

    def test_reopen_store_preserves_beliefs(self, tmp_db: Path) -> None:
        store1 = MemoryStore(str(tmp_db))
        belief: Belief = store1.insert_belief(
            content="persistence test belief for validation",
            belief_type="factual",
            source_type="agent_inferred",
        )
        belief_id = belief.id
        store1.close()

        store2 = MemoryStore(str(tmp_db))
        recovered = store2.get_belief(belief_id)
        assert recovered is not None
        assert recovered.content == "persistence test belief for validation"
        store2.close()

    def test_reopen_store_preserves_locked(self, tmp_db: Path) -> None:
        store1 = MemoryStore(str(tmp_db))
        locked_count = len(store1.get_locked_beliefs())
        store1.close()

        store2 = MemoryStore(str(tmp_db))
        assert len(store2.get_locked_beliefs()) == locked_count
        store2.close()

    def test_reopen_store_search_works(self, tmp_db: Path) -> None:
        s = MemoryStore(str(tmp_db))
        results = s.search("persistence test", top_k=5)
        assert len(results) > 0, "Search failed after store reopen"
        s.close()


# ---------------------------------------------------------------------------
# Phase 7: Edge cases
# ---------------------------------------------------------------------------


class TestPhase7EdgeCases:
    """Verify incremental onboard and robustness."""

    def test_incremental_onboard_detects_previous(
        self,
        store: MemoryStore,
    ) -> None:
        if not TEST_PROJECT.is_dir():
            pytest.skip(f"Test project not found: {TEST_PROJECT}")

        last_run = store.get_last_onboarding(str(TEST_PROJECT))
        assert last_run is not None, "Should detect previous onboarding run"

    def test_empty_query_no_crash(self, store: MemoryStore) -> None:
        result = retrieve(store, "")
        assert isinstance(result.beliefs, list)

    def test_unicode_query_no_crash(self, store: MemoryStore) -> None:
        result = retrieve(store, "emoji test unicode")
        assert isinstance(result.beliefs, list)

    def test_long_query_no_crash(self, store: MemoryStore) -> None:
        long_query = "test " * 500
        result = retrieve(store, long_query)
        assert isinstance(result.beliefs, list)


# ---------------------------------------------------------------------------
# Phase 8: Summary report (runs last)
# ---------------------------------------------------------------------------


class TestPhase8Summary:
    """Print a summary of what was validated."""

    def test_print_summary(
        self,
        store: MemoryStore,
        scan_result: OnboardResult,
        beliefs_created: int,
    ) -> None:
        nodes = len(scan_result.scan.nodes)
        edges = scan_result.edges_inserted
        obs = scan_result.observations_created
        sentences = len(scan_result.sentences)
        node_types = sorted({n.node_type for n in scan_result.scan.nodes})
        edge_types = sorted({e.edge_type for e in scan_result.scan.edges})
        locked = len(store.get_locked_beliefs())
        all_beliefs = len(store.get_all_active_beliefs(limit=100000))

        report = f"""
=== INGESTION VALIDATION REPORT ===
Project: {TEST_PROJECT}
Scan time: {scan_result.scan_time:.2f}s

Pipeline outputs:
  Nodes extracted: {nodes}
  Node types: {node_types}
  Edges extracted: {edges}
  Edge types: {edge_types}
  Observations: {obs}
  Sentences: {sentences}
  Beliefs created: {beliefs_created}
  Total beliefs (incl test): {all_beliefs}
  Locked beliefs: {locked}
===================================
"""
        print(report)
        assert True
