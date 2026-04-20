"""CS-010: Happy-Path Testing Bias.

Pass criterion: TESTS edges enable coverage gap detection -- files without
incoming TESTS edges are identifiable as untested.
"""

from __future__ import annotations

from agentmemory.store import MemoryStore


def test_cs010_untested_file_detectable(store: MemoryStore) -> None:
    """A file with no incoming TESTS edge is identifiable as untested when
    other files do have TESTS edges."""
    # Insert TESTS edges for two source files.
    store.insert_graph_edge(
        from_id="file:a.py",
        to_id="file:src/foo.py",
        edge_type="TESTS",
    )
    store.insert_graph_edge(
        from_id="file:b.py",
        to_id="file:src/bar.py",
        edge_type="TESTS",
    )

    # src/critical.py exists in the codebase but has no TESTS edge.
    # Register it as a known file via a graph edge of a different type.
    store.insert_graph_edge(
        from_id="file:src/critical.py",
        to_id="file:src/__init__.py",
        edge_type="IMPORTS",
    )

    # Find all files that have an incoming TESTS edge.
    conn = store._conn  # pyright: ignore[reportPrivateUsage]
    tested_rows = conn.execute(
        "SELECT DISTINCT to_id FROM graph_edges WHERE edge_type = 'TESTS'"
    ).fetchall()
    tested_files: set[str] = {r["to_id"] for r in tested_rows}

    assert "file:src/foo.py" in tested_files
    assert "file:src/bar.py" in tested_files
    assert "file:src/critical.py" not in tested_files, (
        "src/critical.py should have no TESTS edge, making it identifiable as untested"
    )

    # Collect all known source files from graph_edges (from_id or to_id starting with file:src/).
    all_rows = conn.execute(
        """SELECT DISTINCT id FROM (
               SELECT from_id AS id FROM graph_edges
               UNION
               SELECT to_id AS id FROM graph_edges
           ) WHERE id LIKE 'file:src/%'"""
    ).fetchall()
    all_src_files: set[str] = {r["id"] for r in all_rows}
    untested: set[str] = all_src_files - tested_files

    assert "file:src/critical.py" in untested, (
        f"src/critical.py should appear in the untested set. Untested: {untested}"
    )
