"""
analyze_overlap.py -- T0.6: Measure overlap between extraction methods.

For each pilot repo, loads git edges, import edges, and structural edges,
then measures:
  1. File-pair overlap: what % of import edges also appear as co-change edges?
  2. Unique contribution: edges found by only one method
  3. Combined graph stats: total nodes, edges, types, density, components

Usage:
    python scripts/analyze_overlap.py /path/to/extracted_dir

Reads from extracted/{git_edges,import_edges,structural_edges,node_types}/*.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any] | None:
    if path.exists():
        result: dict[str, Any] = json.loads(path.read_text())
        return result
    return None


def file_pairs_from_edges(edges: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """Extract (source, target) file pairs from edge list."""
    pairs: set[tuple[str, str]] = set()
    for e in edges:
        s: str = e.get("source", "")
        t: str = e.get("target", "")
        # Normalize: skip non-file nodes (commit:*, service:*, package:*, issue:*)
        if ":" in s or ":" in t:
            continue
        # Normalize order for undirected comparison
        pairs.add((min(s, t), max(s, t)))
    return pairs


def analyze_repo(name: str, extracted_dir: Path) -> dict[str, Any]:
    """Analyze overlap for a single repo."""
    git_data: dict[str, Any] | None = load_json(
        extracted_dir / "git_edges" / f"{name}.json"
    )
    import_data: dict[str, Any] | None = load_json(
        extracted_dir / "import_edges" / f"{name}.json"
    )
    struct_data: dict[str, Any] | None = load_json(
        extracted_dir / "structural_edges" / f"{name}.json"
    )
    node_data: dict[str, Any] | None = load_json(
        extracted_dir / "node_types" / f"{name}.json"
    )

    result: dict[str, Any] = {"name": name, "edge_sources": {}}

    # Co-change pairs (weight >= 3 for signal)
    co_change_pairs: set[tuple[str, str]] = set()
    co_change_all: set[tuple[str, str]] = set()
    if git_data:
        git_edges_list: list[dict[str, Any]] = git_data.get("co_changed_edges", [])
        for ge in git_edges_list:
            ge_src: str = ge["source"]
            ge_tgt: str = ge["target"]
            ge_pair: tuple[str, str] = (min(ge_src, ge_tgt), max(ge_src, ge_tgt))
            co_change_all.add(ge_pair)
            ge_weight: int = ge.get("weight", 1)
            if ge_weight >= 3:
                co_change_pairs.add(ge_pair)
        result["edge_sources"]["co_changed_w3"] = len(co_change_pairs)
        result["edge_sources"]["co_changed_all"] = len(co_change_all)
        belief_nodes: list[Any] = git_data.get("belief_nodes", [])
        result["edge_sources"]["beliefs"] = len(belief_nodes)
        commit_belief_edges: list[Any] = git_data.get("commit_belief_edges", [])
        result["edge_sources"]["belief_edges"] = len(commit_belief_edges)
        issue_ref_edges: list[Any] = git_data.get("issue_ref_edges", [])
        result["edge_sources"]["issue_refs"] = len(issue_ref_edges)

    # Import pairs
    import_pairs: set[tuple[str, str]] = set()
    if import_data:
        imp_edges: list[dict[str, Any]] = import_data.get("edges", [])
        import_pairs = file_pairs_from_edges(imp_edges)
        result["edge_sources"]["imports"] = len(import_pairs)

    # Structural pairs (file-to-file only)
    struct_pairs: set[tuple[str, str]] = set()
    struct_by_type: Counter[str] = Counter()
    if struct_data:
        st_edges: list[dict[str, Any]] = struct_data.get("edges", [])
        for se in st_edges:
            se_type: str = se.get("type", "UNKNOWN")
            struct_by_type[se_type] += 1
            se_pairs: set[tuple[str, str]] = file_pairs_from_edges([se])
            struct_pairs.update(se_pairs)
        result["edge_sources"]["structural"] = len(struct_pairs)
        result["edge_sources"]["structural_by_type"] = dict(
            struct_by_type.most_common()
        )

    # Node types
    if node_data:
        summary: dict[str, Any] = node_data.get("summary", {})
        result["node_types"] = summary.get("type_distribution", {})

    # --- Overlap analysis ---
    overlap: dict[str, int | float] = {}

    # Import vs co-change overlap
    if import_pairs and co_change_pairs:
        shared: set[tuple[str, str]] = import_pairs & co_change_pairs
        overlap["import_AND_cochange_w3"] = len(shared)
        overlap["import_ONLY"] = len(import_pairs - co_change_pairs)
        overlap["cochange_w3_ONLY"] = len(co_change_pairs - import_pairs)
        overlap["import_in_cochange_pct"] = round(
            len(shared) / max(len(import_pairs), 1) * 100, 1
        )
        overlap["cochange_in_import_pct"] = round(
            len(shared) / max(len(co_change_pairs), 1) * 100, 1
        )

    # Import vs co-change (any weight)
    if import_pairs and co_change_all:
        shared_any: set[tuple[str, str]] = import_pairs & co_change_all
        overlap["import_in_cochange_any_pct"] = round(
            len(shared_any) / max(len(import_pairs), 1) * 100, 1
        )

    # Structural vs co-change
    if struct_pairs and co_change_pairs:
        shared = struct_pairs & co_change_pairs
        overlap["struct_AND_cochange_w3"] = len(shared)
        overlap["struct_ONLY"] = len(struct_pairs - co_change_pairs)

    # Structural vs import
    if struct_pairs and import_pairs:
        shared = struct_pairs & import_pairs
        overlap["struct_AND_import"] = len(shared)

    # Three-way Venn
    if import_pairs and co_change_pairs and struct_pairs:
        all_three: set[tuple[str, str]] = import_pairs & co_change_pairs & struct_pairs
        any_two: set[tuple[str, str]] = (
            (import_pairs & co_change_pairs)
            | (import_pairs & struct_pairs)
            | (co_change_pairs & struct_pairs)
        )
        exactly_one: set[tuple[str, str]] = (
            import_pairs | co_change_pairs | struct_pairs
        ) - any_two
        overlap["all_three_methods"] = len(all_three)
        overlap["any_two_methods"] = len(any_two - all_three)
        overlap["exactly_one_method"] = len(exactly_one)

    result["overlap"] = overlap

    # Combined graph stats
    all_pairs: set[tuple[str, str]] = co_change_pairs | import_pairs | struct_pairs
    all_nodes: set[str] = set()
    for a, b in all_pairs:
        all_nodes.add(a)
        all_nodes.add(b)

    n: int = len(all_nodes)
    e: int = len(all_pairs)
    max_edges: float = n * (n - 1) / 2 if n > 1 else 1

    result["combined_graph"] = {
        "nodes": n,
        "file_edges": e,
        "density": round(e / max_edges, 6) if max_edges > 0 else 0,
        "avg_degree": round(2 * e / max(n, 1), 1),
    }

    return result


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} /path/to/extracted_dir")
        sys.exit(1)

    extracted_dir: Path = Path(sys.argv[1])

    # Find all repos that have at least git_edges
    git_dir: Path = extracted_dir / "git_edges"
    if not git_dir.exists():
        print("No git_edges directory found", file=sys.stderr)
        sys.exit(1)

    repos: list[str] = sorted(p.stem for p in git_dir.glob("*.json"))
    print(f"Analyzing {len(repos)} repos\n", file=sys.stderr)

    results: dict[str, dict[str, Any]] = {}
    for name in repos:
        print(f"  {name}...", file=sys.stderr)
        results[name] = analyze_repo(name, extracted_dir)

    # Print summary table
    print(f"\n{'=' * 100}")
    print(
        f"{'Repo':<12} {'Nodes':>6} {'Edges':>7} {'Density':>8} {'AvgDeg':>7} | {'ImpInCo%':>8} {'CoInImp%':>8} {'ImpOnly':>8} {'CoOnly':>8}"
    )
    print("-" * 100)

    for name, r in sorted(results.items()):
        g: dict[str, Any] = r["combined_graph"]
        o: dict[str, Any] = r.get("overlap", {})
        print(
            f"{name:<12} {g['nodes']:>6} {g['file_edges']:>7} {g['density']:>8.5f} {g['avg_degree']:>7.1f} | "
            f"{o.get('import_in_cochange_pct', '-'):>8} {o.get('cochange_in_import_pct', '-'):>8} "
            f"{o.get('import_ONLY', '-'):>8} {o.get('cochange_w3_ONLY', '-'):>8}"
        )

    print(f"\n{'=' * 100}")
    print("\nDetailed overlap per repo:\n")

    for name, r in sorted(results.items()):
        print(f"--- {name} ---")
        o = r.get("overlap", {})
        for k, v in sorted(o.items()):
            print(f"  {k}: {v}")
        print()

    # Write full results
    output: Path = extracted_dir / "overlap_analysis.json"
    output.write_text(json.dumps(results, indent=2))
    print(f"Full results written to {output}", file=sys.stderr)


if __name__ == "__main__":
    main()
