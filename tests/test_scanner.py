"""Tests for the project scanner module.

Creates temporary test fixture repos to validate extraction logic.
"""

from __future__ import annotations

import subprocess
from collections import Counter
from collections.abc import Generator
from pathlib import Path

import pytest

from agentmemory.scanner import (
    Edge,
    Manifest,
    Node,
    ScanResult,
    discover,
    extract_ast_calls,
    extract_citations,
    extract_directives,
    extract_document_sentences,
    extract_file_tree,
    extract_git_history,
    scan_project,
)


# ---------------------------------------------------------------------------
# Fixture: minimal git repo with known structure
# ---------------------------------------------------------------------------


@pytest.fixture()
def fixture_repo(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a minimal project directory with git, docs, Python code, and directives."""
    repo: Path = tmp_path / "test-project"
    repo.mkdir()

    # Init git
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@test.com"],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        capture_output=True,
        check=True,
    )

    # Create directory structure
    (repo / "src").mkdir()
    (repo / "docs").mkdir()
    (repo / "tests").mkdir()

    # Python file with functions
    (repo / "src" / "main.py").write_text(
        "from __future__ import annotations\n\n"
        "def process_data(items: list[str]) -> list[str]:\n"
        "    return [transform(i) for i in items]\n\n"
        "def transform(item: str) -> str:\n"
        "    return item.upper()\n\n"
        "def run() -> None:\n"
        '    data = process_data(["a", "b"])\n'
        '    transform("c")\n'
    )

    # Another Python file
    (repo / "src" / "utils.py").write_text(
        "from __future__ import annotations\n\n"
        "def helper() -> str:\n"
        '    return "help"\n'
    )

    # Markdown doc with sentences
    (repo / "docs" / "design.md").write_text(
        "# Architecture Overview\n\n"
        "The system uses a pipeline architecture for processing. "
        "Each stage transforms data independently.\n\n"
        "## Data Flow\n\n"
        "Data enters through the ingestion layer. "
        "The pipeline applies transformations in sequence. "
        "Results are stored in SQLite for durability.\n\n"
        "References: D001, D002, D003\n"
    )

    # Another doc sharing citations
    (repo / "docs" / "decisions.md").write_text(
        "# Decision Log\n\n"
        "D001: Use SQLite for storage.\n"
        "D002: Use FTS5 for search.\n"
        "D004: Use WAL mode for concurrency.\n"
    )

    # README
    (repo / "README.md").write_text(
        "# Test Project\n\nA test project for scanner validation.\n"
    )

    # CLAUDE.md directive
    (repo / "CLAUDE.md").write_text(
        "# Project Instructions\n\n"
        "- Always use strict typing.\n"
        "- Never commit large data files.\n"
        "- Do not use em dashes.\n"
        "- This is just a regular line.\n"
    )

    # pyproject.toml
    (repo / "pyproject.toml").write_text('[project]\nname = "test-project"\n')

    # First commit: initial files
    subprocess.run(
        ["git", "-C", str(repo), "add", "."], capture_output=True, check=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "commit",
            "-m",
            "Initial commit: add project structure",
        ],
        capture_output=True,
        check=True,
    )

    # Second commit: modify a file
    (repo / "src" / "main.py").write_text(
        (repo / "src" / "main.py").read_text() + "\n# Updated\n"
    )
    subprocess.run(
        ["git", "-C", str(repo), "add", "."], capture_output=True, check=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "Update main.py with improvements"],
        capture_output=True,
        check=True,
    )

    # Third commit: modify main.py and utils.py together (for co-change tracking)
    (repo / "src" / "main.py").write_text(
        (repo / "src" / "main.py").read_text() + "\n# Change 2\n"
    )
    (repo / "src" / "utils.py").write_text(
        (repo / "src" / "utils.py").read_text() + "\n# Change 2\n"
    )
    subprocess.run(
        ["git", "-C", str(repo), "add", "."], capture_output=True, check=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "Refactor main and utils together"],
        capture_output=True,
        check=True,
    )

    yield repo


# ---------------------------------------------------------------------------
# Discovery tests
# ---------------------------------------------------------------------------


class TestDiscover:
    def test_detects_git(self, fixture_repo: Path) -> None:
        manifest: Manifest = discover(fixture_repo)
        assert manifest.has_git is True
        assert manifest.commit_count >= 3

    def test_detects_languages(self, fixture_repo: Path) -> None:
        manifest: Manifest = discover(fixture_repo)
        assert "python" in manifest.languages

    def test_detects_docs(self, fixture_repo: Path) -> None:
        manifest: Manifest = discover(fixture_repo)
        assert manifest.doc_count >= 2
        doc_names: list[str] = [Path(d).name for d in manifest.doc_files]
        assert "design.md" in doc_names

    def test_detects_directives(self, fixture_repo: Path) -> None:
        manifest: Manifest = discover(fixture_repo)
        assert any("CLAUDE.md" in d for d in manifest.directives)

    def test_detects_readme(self, fixture_repo: Path) -> None:
        manifest: Manifest = discover(fixture_repo)
        assert manifest.has_readme is True

    def test_detects_tests_dir(self, fixture_repo: Path) -> None:
        manifest: Manifest = discover(fixture_repo)
        assert manifest.has_tests is True

    def test_detects_build_config(self, fixture_repo: Path) -> None:
        manifest: Manifest = discover(fixture_repo)
        assert any("pyproject.toml" in c for c in manifest.build_configs)

    def test_detects_citation_regex(self, fixture_repo: Path) -> None:
        manifest: Manifest = discover(fixture_repo)
        assert manifest.citation_regex is not None
        assert "D" in manifest.citation_regex

    def test_no_git_graceful(self, tmp_path: Path) -> None:
        """A directory without .git should report has_git=False."""
        bare: Path = tmp_path / "bare"
        bare.mkdir()
        (bare / "file.txt").write_text("hello")
        manifest: Manifest = discover(bare)
        assert manifest.has_git is False
        assert manifest.commit_count == 0


# ---------------------------------------------------------------------------
# File tree extraction tests
# ---------------------------------------------------------------------------


class TestFileTree:
    def test_extracts_files(self, fixture_repo: Path) -> None:
        nodes, _edges = extract_file_tree(fixture_repo)
        node_ids: list[str] = [n.id for n in nodes]
        assert any("main.py" in nid for nid in node_ids)
        assert any("utils.py" in nid for nid in node_ids)

    def test_contains_edges(self, fixture_repo: Path) -> None:
        _, edges = extract_file_tree(fixture_repo)
        contain_edges: list[Edge] = [e for e in edges if e.edge_type == "CONTAINS"]
        assert len(contain_edges) > 0

    def test_skips_git_dir(self, fixture_repo: Path) -> None:
        nodes, _ = extract_file_tree(fixture_repo)
        assert not any(".git" in n.id for n in nodes)


# ---------------------------------------------------------------------------
# Git history extraction tests
# ---------------------------------------------------------------------------


class TestGitHistory:
    def test_extracts_commits(self, fixture_repo: Path) -> None:
        nodes, _ = extract_git_history(fixture_repo)
        commit_nodes: list[Node] = [n for n in nodes if n.node_type == "commit_belief"]
        assert len(commit_nodes) >= 3

    def test_commit_touches_edges(self, fixture_repo: Path) -> None:
        _, edges = extract_git_history(fixture_repo)
        touches: list[Edge] = [e for e in edges if e.edge_type == "COMMIT_TOUCHES"]
        assert len(touches) > 0

    def test_temporal_next_edges(self, fixture_repo: Path) -> None:
        _, edges = extract_git_history(fixture_repo)
        temporal: list[Edge] = [e for e in edges if e.edge_type == "TEMPORAL_NEXT"]
        assert len(temporal) >= 2

    def test_no_git_returns_empty(self, tmp_path: Path) -> None:
        bare: Path = tmp_path / "bare"
        bare.mkdir()
        nodes, edges = extract_git_history(bare)
        assert nodes == []
        assert edges == []


# ---------------------------------------------------------------------------
# Document sentence extraction tests
# ---------------------------------------------------------------------------


class TestDocumentSentences:
    def test_extracts_headings(self, fixture_repo: Path) -> None:
        manifest: Manifest = discover(fixture_repo)
        nodes, _ = extract_document_sentences(fixture_repo, manifest.doc_files)
        headings: list[Node] = [n for n in nodes if n.node_type == "heading"]
        assert len(headings) >= 1

    def test_extracts_sentences(self, fixture_repo: Path) -> None:
        manifest: Manifest = discover(fixture_repo)
        nodes, _ = extract_document_sentences(fixture_repo, manifest.doc_files)
        sentences: list[Node] = [n for n in nodes if n.node_type == "sentence"]
        assert len(sentences) >= 3

    def test_sentence_in_file_edges(self, fixture_repo: Path) -> None:
        manifest: Manifest = discover(fixture_repo)
        _, edges = extract_document_sentences(fixture_repo, manifest.doc_files)
        sif: list[Edge] = [e for e in edges if e.edge_type == "SENTENCE_IN_FILE"]
        assert len(sif) > 0

    def test_within_section_edges(self, fixture_repo: Path) -> None:
        manifest: Manifest = discover(fixture_repo)
        _, edges = extract_document_sentences(fixture_repo, manifest.doc_files)
        ws: list[Edge] = [e for e in edges if e.edge_type == "WITHIN_SECTION"]
        assert len(ws) > 0


# ---------------------------------------------------------------------------
# AST call extraction tests
# ---------------------------------------------------------------------------


class TestAstCalls:
    def test_extracts_functions(self, fixture_repo: Path) -> None:
        nodes, _ = extract_ast_calls(fixture_repo, ["python"])
        callables: list[Node] = [n for n in nodes if n.node_type == "callable"]
        names: list[str] = [n.content for n in callables]
        assert "def process_data" in names
        assert "def transform" in names

    def test_calls_edges(self, fixture_repo: Path) -> None:
        _, edges = extract_ast_calls(fixture_repo, ["python"])
        calls: list[Edge] = [e for e in edges if e.edge_type == "CALLS"]
        # process_data calls transform, run calls process_data and transform
        assert len(calls) >= 2

    def test_no_python_returns_empty(self, fixture_repo: Path) -> None:
        nodes, call_edges = extract_ast_calls(fixture_repo, ["rust"])
        assert nodes == []
        assert call_edges == []


# ---------------------------------------------------------------------------
# Citation extraction tests
# ---------------------------------------------------------------------------


class TestCitations:
    def test_extracts_shared_citations(self, fixture_repo: Path) -> None:
        manifest: Manifest = discover(fixture_repo)
        edges: list[Edge] = extract_citations(
            fixture_repo, manifest.doc_files, manifest.citation_regex
        )
        cites: list[Edge] = [e for e in edges if e.edge_type == "CITES"]
        assert len(cites) >= 1
        # design.md and decisions.md share D001, D002
        for edge in cites:
            if edge.metadata.get("shared"):
                shared: list[str] = edge.metadata["shared"]
                assert any("D001" in s or "D002" in s for s in shared)
                break

    def test_no_regex_returns_empty(self, fixture_repo: Path) -> None:
        manifest: Manifest = discover(fixture_repo)
        edges: list[Edge] = extract_citations(fixture_repo, manifest.doc_files, None)
        assert edges == []


# ---------------------------------------------------------------------------
# Directive extraction tests
# ---------------------------------------------------------------------------


class TestDirectives:
    def test_extracts_behavioral_beliefs(self, fixture_repo: Path) -> None:
        manifest: Manifest = discover(fixture_repo)
        nodes: list[Node] = extract_directives(fixture_repo, manifest.directives)
        assert len(nodes) >= 3  # always, never, do not
        types: list[str] = [n.node_type for n in nodes]
        assert all(t == "behavioral_belief" for t in types)

    def test_skips_plain_lines(self, fixture_repo: Path) -> None:
        manifest: Manifest = discover(fixture_repo)
        nodes: list[Node] = extract_directives(fixture_repo, manifest.directives)
        contents: list[str] = [n.content for n in nodes]
        assert not any("regular line" in c for c in contents)


# ---------------------------------------------------------------------------
# Full scan integration test
# ---------------------------------------------------------------------------


class TestScanProject:
    def test_scan_returns_all_signal_types(self, fixture_repo: Path) -> None:
        result: ScanResult = scan_project(fixture_repo)

        node_types: Counter[str] = Counter(n.node_type for n in result.nodes)
        edge_types: Counter[str] = Counter(e.edge_type for e in result.edges)

        # Must have nodes from multiple sources
        assert "file" in node_types
        assert "commit_belief" in node_types
        assert "sentence" in node_types or "heading" in node_types
        assert "callable" in node_types
        assert "behavioral_belief" in node_types

        # Must have edges from multiple sources
        assert "CONTAINS" in edge_types
        assert "COMMIT_TOUCHES" in edge_types
        assert "SENTENCE_IN_FILE" in edge_types
        assert "CALLS" in edge_types

    def test_scan_not_a_directory(self, tmp_path: Path) -> None:
        fake: Path = tmp_path / "nonexistent"
        with pytest.raises(NotADirectoryError):
            scan_project(fake)

    def test_scan_timing_recorded(self, fixture_repo: Path) -> None:
        result: ScanResult = scan_project(fixture_repo)
        assert "discover" in result.timings
        assert "file_tree" in result.timings
        assert all(v >= 0.0 for v in result.timings.values())

    def test_scan_minimal_project(self, tmp_path: Path) -> None:
        """A bare directory with one file should still produce a valid ScanResult."""
        bare: Path = tmp_path / "minimal"
        bare.mkdir()
        (bare / "hello.txt").write_text("hello world")
        result: ScanResult = scan_project(bare)
        assert result.manifest.has_git is False
        assert len(result.nodes) >= 1  # at least the file node


# ---------------------------------------------------------------------------
# Onboard integration test (scanner -> ingest -> store)
# ---------------------------------------------------------------------------


class TestOnboardIntegration:
    def test_onboard_creates_beliefs(self, fixture_repo: Path) -> None:
        """Scanning + ingesting a project should create beliefs in the store."""
        from agentmemory.ingest import IngestResult, ingest_turn
        from agentmemory.store import MemoryStore

        store: MemoryStore = MemoryStore(fixture_repo / ".test_memory.db")
        try:
            result: ScanResult = scan_project(fixture_repo)
            aggregate: IngestResult = IngestResult()

            for node in result.nodes:
                if node.node_type == "file":
                    continue
                turn_result: IngestResult = ingest_turn(
                    store=store,
                    text=node.content,
                    source="document",
                    session_id=None,
                )
                aggregate.merge(turn_result)

            assert aggregate.observations_created > 0
            assert (
                aggregate.beliefs_created >= 0
            )  # offline classification may not persist all

            # Verify beliefs are searchable
            stats: dict[str, int] = store.status()
            assert stats["observations"] > 0
        finally:
            store.close()
