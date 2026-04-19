"""
compare_edges.py -- Compare auto-extracted edges against reference graphs.

Measures precision and recall of auto-extracted edges (from T0 extraction
pipeline) against human-authored reference graphs (doc references and commit
intent).

Auto-extracted edges come from: extract_git_edges.py, extract_import_edges.py,
extract_structural_edges.py. Reference graphs come from:
extract_doc_references.py, extract_commit_intent.py.

Usage:
    uv run python scripts/compare_edges.py \
        --auto-extracted /path/to/git_edges.json \
        --doc-refs /path/to/repo_doc_refs.json \
        --commit-intent /path/to/repo_commit_intent.json \
        --repo-name project-a

Output: JSON to stdout, summary to stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast


# ---------------------------------------------------------------------------
# Path normalization
# ---------------------------------------------------------------------------


def normalize_path(p: str) -> str:
    """Normalize a file path for comparison.

    Strips leading './', normalizes separators, removes trailing slashes,
    and collapses repeated slashes.
    """
    result: str = p.strip()
    # Normalize separators
    result = result.replace("\\", "/")
    # Collapse repeated slashes
    while "//" in result:
        result = result.replace("//", "/")
    # Strip leading ./
    while result.startswith("./"):
        result = result[2:]
    # Strip trailing /
    result = result.rstrip("/")
    return result


def make_edge_pair(a: str, b: str) -> tuple[str, str]:
    """Create a canonical undirected edge pair (sorted order)."""
    na: str = normalize_path(a)
    nb: str = normalize_path(b)
    if na <= nb:
        return (na, nb)
    return (nb, na)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file and return the parsed dict."""
    with open(path, encoding="utf-8") as f:
        data: object = json.load(f)
    if not isinstance(data, dict):
        print(f"Error: expected JSON object in {path}", file=sys.stderr)
        sys.exit(1)
    return cast(dict[str, Any], data)


def _iter_edge_dicts(raw_list: object) -> list[dict[str, Any]]:
    """Safely extract a list of dicts from a JSON-loaded value."""
    if not isinstance(raw_list, list):
        return []
    result: list[dict[str, Any]] = []
    for item in cast(list[object], raw_list):
        if isinstance(item, dict):
            result.append(cast(dict[str, Any], item))
    return result


def _get_str(d: dict[str, Any], key: str) -> str | None:
    """Get a string value from a dict, returning None if not a string."""
    val: object = d.get(key)
    if isinstance(val, str):
        return val
    return None


def load_auto_extracted_edges(path: Path) -> dict[str, set[tuple[str, str]]]:
    """Load auto-extracted edges grouped by type.

    Supports git_edges.json format (co_changed_edges, issue_ref_edges) and
    import_edges.json / structural_edges.json format (edges list with 'type').

    Returns {edge_type: set of (normalized_source, normalized_target) pairs}.
    """
    data: dict[str, Any] = load_json(path)
    result: dict[str, set[tuple[str, str]]] = {}

    # git_edges.json has separate top-level keys
    co_changed_raw: object = data.get("co_changed_edges")
    co_changed_edges: list[dict[str, Any]] = _iter_edge_dicts(co_changed_raw)
    if co_changed_edges:
        pairs: set[tuple[str, str]] = set()
        for edge in co_changed_edges:
            src: str | None = _get_str(edge, "source")
            tgt: str | None = _get_str(edge, "target")
            if src is not None and tgt is not None:
                pairs.add(make_edge_pair(src, tgt))
        if pairs:
            result["CO_CHANGED"] = pairs

    # import_edges.json and structural_edges.json have a flat "edges" list
    edges_raw: object = data.get("edges")
    edges_list: list[dict[str, Any]] = _iter_edge_dicts(edges_raw)
    for edge in edges_list:
        edge_type: str | None = _get_str(edge, "type")
        if edge_type is None:
            continue
        src = _get_str(edge, "source")
        tgt = _get_str(edge, "target")
        if src is None or tgt is None:
            continue
        if edge_type not in result:
            result[edge_type] = set()
        result[edge_type].add(make_edge_pair(src, tgt))

    return result


def load_doc_ref_edges(
    path: Path,
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Load doc reference edges.

    Returns (direct_edges, co_citation_edges).
    direct_edges: set of (source, target) pairs from direct citation
    co_citation_edges: set of (file_a, file_b) pairs from co-citation
    """
    data: dict[str, Any] = load_json(path)
    edges_data_raw: object = data.get("edges", {})
    edges_data: dict[str, Any]
    if isinstance(edges_data_raw, dict):
        edges_data = cast(dict[str, Any], edges_data_raw)
    else:
        edges_data = {}

    direct_edges: set[tuple[str, str]] = set()
    direct_list: list[dict[str, Any]] = _iter_edge_dicts(
        edges_data.get("direct_citation", [])
    )
    for edge in direct_list:
        src: str | None = _get_str(edge, "source")
        tgt: str | None = _get_str(edge, "target")
        if src is not None and tgt is not None:
            direct_edges.add(make_edge_pair(src, tgt))

    co_citation_edges: set[tuple[str, str]] = set()
    co_list: list[dict[str, Any]] = _iter_edge_dicts(edges_data.get("co_citation", []))
    for edge in co_list:
        file_a: str | None = _get_str(edge, "file_a")
        file_b: str | None = _get_str(edge, "file_b")
        if file_a is not None and file_b is not None:
            co_citation_edges.add(make_edge_pair(file_a, file_b))

    return direct_edges, co_citation_edges


def load_commit_intent_edges(path: Path) -> set[tuple[str, str]]:
    """Load commit intent edges as a set of normalized file pairs."""
    data: dict[str, Any] = load_json(path)
    edges_list: list[dict[str, Any]] = _iter_edge_dicts(data.get("edges", []))
    result: set[tuple[str, str]] = set()
    for edge in edges_list:
        src: str | None = _get_str(edge, "source")
        tgt: str | None = _get_str(edge, "target")
        if src is not None and tgt is not None:
            result.add(make_edge_pair(src, tgt))
    return result


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------


def compute_precision(
    auto_edges: dict[str, set[tuple[str, str]]],
    doc_direct: set[tuple[str, str]],
    doc_co_cite: set[tuple[str, str]],
    commit_intent: set[tuple[str, str]],
) -> dict[str, dict[str, Any]]:
    """Compute precision of each auto-extracted edge type against references.

    For each edge type, reports:
    - vs_doc_refs: fraction confirmed by either direct or co-citation doc refs
    - vs_commit_intent: fraction confirmed by commit intent graph
    - vs_both: fraction confirmed by BOTH doc refs AND commit intent
    - counts for each category
    """
    all_doc_refs: set[tuple[str, str]] = doc_direct | doc_co_cite
    precision: dict[str, dict[str, Any]] = {}

    for edge_type, edges in sorted(auto_edges.items()):
        n_total: int = len(edges)
        if n_total == 0:
            continue

        confirmed_doc: set[tuple[str, str]] = edges & all_doc_refs
        confirmed_intent: set[tuple[str, str]] = edges & commit_intent
        confirmed_both: set[tuple[str, str]] = confirmed_doc & confirmed_intent
        confirmed_either: set[tuple[str, str]] = confirmed_doc | confirmed_intent
        unvalidated: set[tuple[str, str]] = edges - confirmed_either

        precision[edge_type] = {
            "total": n_total,
            "vs_doc_refs": round(len(confirmed_doc) / n_total, 4),
            "vs_commit_intent": round(len(confirmed_intent) / n_total, 4),
            "vs_both": round(len(confirmed_both) / n_total, 4),
            "n_confirmed_doc": len(confirmed_doc),
            "n_confirmed_intent": len(confirmed_intent),
            "n_confirmed_both": len(confirmed_both),
            "n_unvalidated": len(unvalidated),
        }

    return precision


def compute_recall(
    auto_edges: dict[str, set[tuple[str, str]]],
    doc_direct: set[tuple[str, str]],
    doc_co_cite: set[tuple[str, str]],
    commit_intent: set[tuple[str, str]],
) -> dict[str, dict[str, Any]]:
    """Compute recall: what fraction of reference edges were found by auto-extraction."""
    # Union of all auto-extracted edges regardless of type
    all_auto: set[tuple[str, str]] = set()
    for edges in auto_edges.values():
        all_auto |= edges

    recall: dict[str, dict[str, Any]] = {}

    ref_sets: dict[str, set[tuple[str, str]]] = {
        "doc_direct": doc_direct,
        "doc_co_citation": doc_co_cite,
        "commit_intent": commit_intent,
    }

    for ref_name, ref_edges in ref_sets.items():
        n_total: int = len(ref_edges)
        if n_total == 0:
            continue

        found_by_any: set[tuple[str, str]] = ref_edges & all_auto
        entry: dict[str, Any] = {
            "total": n_total,
            "found_by_any_method": round(len(found_by_any) / n_total, 4),
            "n_found": len(found_by_any),
        }

        # Break down by auto-extraction type
        for edge_type, edges in sorted(auto_edges.items()):
            found: set[tuple[str, str]] = ref_edges & edges
            entry[f"found_by_{edge_type}"] = round(len(found) / n_total, 4)
            entry[f"n_found_by_{edge_type}"] = len(found)

        recall[ref_name] = entry

    return recall


def compute_confidence_stratification(
    auto_edges: dict[str, set[tuple[str, str]]],
    doc_direct: set[tuple[str, str]],
    doc_co_cite: set[tuple[str, str]],
    commit_intent: set[tuple[str, str]],
) -> dict[str, dict[str, Any]]:
    """Stratify all auto-extracted edges by confidence level."""
    all_auto: set[tuple[str, str]] = set()
    for edges in auto_edges.values():
        all_auto |= edges

    all_doc: set[tuple[str, str]] = doc_direct | doc_co_cite

    confirmed_doc: set[tuple[str, str]] = all_auto & all_doc
    confirmed_intent: set[tuple[str, str]] = all_auto & commit_intent
    confirmed_both: set[tuple[str, str]] = confirmed_doc & confirmed_intent
    confirmed_one_only: set[tuple[str, str]] = (
        confirmed_doc | confirmed_intent
    ) - confirmed_both
    unvalidated: set[tuple[str, str]] = all_auto - confirmed_doc - confirmed_intent

    return {
        "high": {
            "count": len(confirmed_both),
            "description": "confirmed by both doc refs and commit intent",
        },
        "medium": {
            "count": len(confirmed_one_only),
            "description": "confirmed by one reference source",
        },
        "unvalidated": {
            "count": len(unvalidated),
            "description": "not confirmed by either reference",
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Compare auto-extracted edges against reference graphs.",
    )
    parser.add_argument(
        "--auto-extracted",
        type=Path,
        action="append",
        default=None,
        help="Path to auto-extracted edge JSON (repeatable for multiple files: "
        "git_edges.json, import_edges.json, structural_edges.json).",
    )
    parser.add_argument(
        "--doc-refs",
        type=Path,
        required=True,
        help="Path to doc reference JSON (from extract_doc_references.py).",
    )
    parser.add_argument(
        "--commit-intent",
        type=Path,
        required=True,
        help="Path to commit intent JSON (from extract_commit_intent.py).",
    )
    parser.add_argument(
        "--repo-name",
        type=str,
        required=True,
        help="Repository name for output labeling.",
    )
    return parser


def main() -> None:
    parser: argparse.ArgumentParser = build_parser()
    args: argparse.Namespace = parser.parse_args()

    repo_name: str = args.repo_name
    auto_paths: list[Path] | None = args.auto_extracted
    doc_refs_path: Path = args.doc_refs
    commit_intent_path: Path = args.commit_intent

    # --- Load auto-extracted edges (merge from multiple files) ---
    auto_edges: dict[str, set[tuple[str, str]]] = {}
    if auto_paths:
        for ap in auto_paths:
            if not ap.exists():
                print(f"Warning: auto-extracted file not found: {ap}", file=sys.stderr)
                continue
            loaded: dict[str, set[tuple[str, str]]] = load_auto_extracted_edges(ap)
            for edge_type, edges in loaded.items():
                if edge_type not in auto_edges:
                    auto_edges[edge_type] = set()
                auto_edges[edge_type] |= edges
            print(
                f"[compare] loaded {ap.name}: "
                + ", ".join(f"{k}={len(v)}" for k, v in sorted(loaded.items())),
                file=sys.stderr,
            )
    else:
        print("Warning: no --auto-extracted files provided", file=sys.stderr)

    # --- Load reference graphs ---
    doc_direct: set[tuple[str, str]] = set()
    doc_co_cite: set[tuple[str, str]] = set()
    if doc_refs_path.exists():
        doc_direct, doc_co_cite = load_doc_ref_edges(doc_refs_path)
        print(
            f"[compare] loaded doc refs: {len(doc_direct)} direct, "
            f"{len(doc_co_cite)} co-citation",
            file=sys.stderr,
        )
    else:
        print(f"Warning: doc refs file not found: {doc_refs_path}", file=sys.stderr)

    commit_intent: set[tuple[str, str]] = set()
    if commit_intent_path.exists():
        commit_intent = load_commit_intent_edges(commit_intent_path)
        print(
            f"[compare] loaded commit intent: {len(commit_intent)} edges",
            file=sys.stderr,
        )
    else:
        print(
            f"Warning: commit intent file not found: {commit_intent_path}",
            file=sys.stderr,
        )

    # --- Compute metrics ---
    precision: dict[str, dict[str, Any]] = compute_precision(
        auto_edges,
        doc_direct,
        doc_co_cite,
        commit_intent,
    )
    recall: dict[str, dict[str, Any]] = compute_recall(
        auto_edges,
        doc_direct,
        doc_co_cite,
        commit_intent,
    )
    stratification: dict[str, dict[str, Any]] = compute_confidence_stratification(
        auto_edges,
        doc_direct,
        doc_co_cite,
        commit_intent,
    )

    # --- Build output ---
    auto_extracted_counts: dict[str, int] = {
        k: len(v) for k, v in sorted(auto_edges.items())
    }
    reference_counts: dict[str, int] = {
        "doc_direct": len(doc_direct),
        "doc_co_citation": len(doc_co_cite),
        "commit_intent": len(commit_intent),
    }

    output: dict[str, Any] = {
        "repo": repo_name,
        "auto_extracted": auto_extracted_counts,
        "reference": reference_counts,
        "precision": precision,
        "recall": recall,
        "confidence_stratification": stratification,
    }

    # --- Summary to stderr ---
    print(f"\n[compare] === {repo_name} ===", file=sys.stderr)
    print(f"  auto-extracted types: {auto_extracted_counts}", file=sys.stderr)
    print(f"  reference counts: {reference_counts}", file=sys.stderr)

    for edge_type, metrics in precision.items():
        print(
            f"  precision {edge_type}: "
            f"doc={metrics['vs_doc_refs']:.2%}, "
            f"intent={metrics['vs_commit_intent']:.2%}, "
            f"both={metrics['vs_both']:.2%}, "
            f"unvalidated={metrics['n_unvalidated']}/{metrics['total']}",
            file=sys.stderr,
        )

    for ref_name, metrics in recall.items():
        print(
            f"  recall {ref_name}: "
            f"any={metrics['found_by_any_method']:.2%} "
            f"({metrics['n_found']}/{metrics['total']})",
            file=sys.stderr,
        )

    high: int = stratification["high"]["count"]
    med: int = stratification["medium"]["count"]
    unval: int = stratification["unvalidated"]["count"]
    total_auto: int = high + med + unval
    print(
        f"  confidence: high={high}, medium={med}, "
        f"unvalidated={unval} (total={total_auto})",
        file=sys.stderr,
    )

    # --- JSON to stdout ---
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
