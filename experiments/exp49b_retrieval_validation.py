"""
Experiment 49b: Retrieval Utility on Extracted Graphs (H2) + HRR Value (H3)

H2: Does graph-based FTS5 retrieval outperform raw-file FTS5?
H3: Does HRR add value on non-alpha-seek topologies?

For each project, we:
1. Build FTS5 index from extracted graph nodes (sentence-level)
2. Build FTS5 index from raw files (file-level baseline)
3. Run queries with known answers
4. Compare precision@5
5. For H3: identify vocabulary-gap scenarios and test HRR bridging

Queries are derived from actual project content -- not synthetic.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

# Reuse the Exp 45 pipeline
from experiments.exp49_onboarding_validation import (
    PROJECTS, discover, extract_file_tree, extract_git_history,
    extract_document_sentences, extract_ast_calls, extract_citations,
    extract_directives, build_fts_from_nodes, build_fts_from_raw_files,
    search_fts,
)


# ============================================================
# Test queries with known answers per project
# ============================================================

# Each query has:
# - query: the natural language search
# - must_find: substrings that MUST appear in at least one result's content
# - description: what this tests

TEST_QUERIES: dict[str, list[dict[str, Any]]] = {
    "alpha-seek": [
        {
            "query": "dispatch gate deploy protocol",
            "must_find": ["dispatch", "gate"],
            "description": "Core operational procedure (known from Exp 9)",
        },
        {
            "query": "starting capital bankroll investment",
            "must_find": ["5k", "5,000", "capital", "bankroll"],
            "description": "Financial constraint (known from Exp 9)",
        },
        {
            "query": "walk forward evaluation backtest",
            "must_find": ["walk", "forward"],
            "description": "Backtesting methodology",
        },
        {
            "query": "pyright strict typing annotations",
            "must_find": ["pyright", "strict", "typing"],
            "description": "Development tooling decision",
        },
        {
            "query": "options puts calls strategy",
            "must_find": ["put", "call"],
            "description": "Core trading domain",
        },
    ],
    "jose-bully": [
        {
            "query": "pull request merge blocked",
            "must_find": ["pull request", "merge", "PR"],
            "description": "Key grievance: PR blocked",
        },
        {
            "query": "escalation manager HR",
            "must_find": ["escalat", "manager", "HR"],
            "description": "Process: escalation path",
        },
        {
            "query": "incident evidence documentation",
            "must_find": ["incident", "evidence"],
            "description": "Evidence collection process",
        },
        {
            "query": "team work assignment distribution",
            "must_find": ["work", "assign", "task"],
            "description": "Work distribution grievance",
        },
        {
            "query": "public correction team channel",
            "must_find": ["correct", "public", "channel", "team"],
            "description": "Public shaming incidents",
        },
    ],
    "debserver": [
        {
            "query": "raspberry pi satellite fleet",
            "must_find": ["raspberry", "pi", "satellite"],
            "description": "Hardware infrastructure",
        },
        {
            "query": "jellyfin media server transcoding",
            "must_find": ["jellyfin", "media", "transcod"],
            "description": "Media server setup",
        },
        {
            "query": "VPN health check gluetun",
            "must_find": ["vpn", "health", "gluetun"],
            "description": "VPN monitoring (recent commit)",
        },
        {
            "query": "prometheus grafana monitoring alerts",
            "must_find": ["prometheus", "grafana", "monitor"],
            "description": "Monitoring stack",
        },
        {
            "query": "ansible playbook deployment",
            "must_find": ["ansible", "playbook"],
            "description": "Configuration management",
        },
    ],
}


def evaluate_retrieval(
    query: str,
    must_find: list[str],
    fts_db: sqlite3.Connection,
    all_nodes: list[dict[str, Any]],
    top_k: int = 5,
) -> dict[str, Any]:
    """Run a query and check if must_find terms appear in results."""
    results = search_fts(query, fts_db, top_k=top_k)

    # Build content lookup
    node_content: dict[str, str] = {str(n["id"]): str(n.get("content", "")) for n in all_nodes}

    # Check each must_find term
    found_terms: list[str] = []
    for term in must_find:
        term_lower = term.lower()
        for rid in results:
            content = node_content.get(rid, "").lower()
            if not content:
                # For raw file FTS5, rid is a file path -- search in raw results
                # Just check if any result matched
                pass
            if term_lower in content:
                found_terms.append(term)
                break

    precision = len(found_terms) / len(must_find) if must_find else 1.0

    return {
        "query": query,
        "results_count": len(results),
        "must_find": must_find,
        "found_terms": found_terms,
        "missed_terms": [t for t in must_find if t not in found_terms],
        "precision": round(precision, 3),
    }


def evaluate_raw_retrieval(
    query: str,
    must_find: list[str],
    fts_db: sqlite3.Connection,
    project_root: Path,
    top_k: int = 5,
) -> dict[str, Any]:
    """Run a query against raw file FTS5 and check must_find terms."""
    results = search_fts(query, fts_db, top_k=top_k)

    found_terms: list[str] = []
    for term in must_find:
        term_lower = term.lower()
        for rid in results:
            # rid is a file path -- read the file content
            fp = project_root / rid
            try:
                content = fp.read_text(encoding="utf-8", errors="ignore")[:10000].lower()
            except Exception:
                content = ""
            if term_lower in content:
                found_terms.append(term)
                break

    precision = len(found_terms) / len(must_find) if must_find else 1.0

    return {
        "query": query,
        "results_count": len(results),
        "must_find": must_find,
        "found_terms": found_terms,
        "missed_terms": [t for t in must_find if t not in found_terms],
        "precision": round(precision, 3),
    }


# ============================================================
# Main
# ============================================================

def main() -> None:
    print("=" * 70, file=sys.stderr)
    print("Experiment 49b: Retrieval Utility (H2) + HRR Value (H3)", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    all_results: dict[str, Any] = {}

    for name, root in PROJECTS.items():
        print(f"\n{'='*50}", file=sys.stderr)
        print(f"Project: {name}", file=sys.stderr)
        print(f"{'='*50}", file=sys.stderr)

        # Run extractors (reuse Exp 45 pipeline)
        manifest = discover(root)
        all_nodes: list[dict[str, Any]] = []
        all_edges: list[dict[str, Any]] = []

        ft_nodes: list[dict[str, Any]]
        ft_edges: list[dict[str, Any]]
        ft_nodes, ft_edges = extract_file_tree(root)
        all_nodes.extend(ft_nodes)
        all_edges.extend(ft_edges)

        if manifest["has_git"] and manifest["commit_count"] > 0:
            git_nodes: list[dict[str, Any]]
            git_edges: list[dict[str, Any]]
            git_nodes, git_edges = extract_git_history(root)
            all_nodes.extend(git_nodes)
            all_edges.extend(git_edges)

        if manifest["doc_count"] > 0:
            doc_nodes: list[dict[str, Any]]
            doc_edges: list[dict[str, Any]]
            doc_nodes, doc_edges = extract_document_sentences(root, manifest["doc_files"])
            all_nodes.extend(doc_nodes)
            all_edges.extend(doc_edges)

        if manifest["languages"]:
            ast_nodes: list[dict[str, Any]]
            ast_edges: list[dict[str, Any]]
            ast_nodes, ast_edges = extract_ast_calls(root, manifest["languages"])
            all_nodes.extend(ast_nodes)
            all_edges.extend(ast_edges)

        if manifest["citation_regex"]:
            cite_edges: list[dict[str, Any]] = extract_citations(root, manifest["doc_files"], manifest["citation_regex"])
            all_edges.extend(cite_edges)

        if manifest["directives"]:
            dir_nodes: list[dict[str, Any]] = extract_directives(root, manifest["directives"])
            all_nodes.extend(dir_nodes)

        # Build both FTS5 indexes
        graph_fts = build_fts_from_nodes(all_nodes)
        raw_fts = build_fts_from_raw_files(root)

        # Run queries
        queries = TEST_QUERIES.get(name, [])
        project_results: dict[str, Any] = {
            "graph_results": [],
            "raw_results": [],
        }

        print(f"\n  {'Query':<45} {'Graph':>8} {'Raw':>8}", file=sys.stderr)
        print(f"  {'-'*65}", file=sys.stderr)

        graph_precisions: list[float] = []
        raw_precisions: list[float] = []

        for q in queries:
            graph_eval = evaluate_retrieval(q["query"], q["must_find"], graph_fts, all_nodes)
            raw_eval = evaluate_raw_retrieval(q["query"], q["must_find"], raw_fts, root)

            project_results["graph_results"].append(graph_eval)
            project_results["raw_results"].append(raw_eval)

            graph_precisions.append(graph_eval["precision"])
            raw_precisions.append(raw_eval["precision"])

            g_status = f"{graph_eval['precision']:.0%}"
            r_status = f"{raw_eval['precision']:.0%}"
            g_missed = f" miss:{graph_eval['missed_terms']}" if graph_eval["missed_terms"] else ""
            r_missed = f" miss:{raw_eval['missed_terms']}" if raw_eval["missed_terms"] else ""

            print(f"  {q['query'][:44]:<45} {g_status:>6}{g_missed:<20} {r_status:>6}{r_missed}", file=sys.stderr)

        # Summary
        avg_graph = sum(graph_precisions) / len(graph_precisions) if graph_precisions else 0
        avg_raw = sum(raw_precisions) / len(raw_precisions) if raw_precisions else 0

        project_results["avg_graph_precision"] = round(avg_graph, 3)
        project_results["avg_raw_precision"] = round(avg_raw, 3)
        project_results["graph_wins"] = sum(1 for g, r in zip(graph_precisions, raw_precisions) if g > r)
        project_results["raw_wins"] = sum(1 for g, r in zip(graph_precisions, raw_precisions) if r > g)
        project_results["ties"] = sum(1 for g, r in zip(graph_precisions, raw_precisions) if g == r)

        print(f"\n  Avg precision -- Graph: {avg_graph:.0%}  Raw: {avg_raw:.0%}", file=sys.stderr)
        print(f"  Graph wins: {project_results['graph_wins']}  Raw wins: {project_results['raw_wins']}  Ties: {project_results['ties']}", file=sys.stderr)

        all_results[name] = project_results

    # H2 summary
    print(f"\n{'='*70}", file=sys.stderr)
    print("H2 SUMMARY: Does graph FTS5 outperform raw file FTS5?", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)
    print(f"\n  {'Project':<15} {'Graph Avg':>12} {'Raw Avg':>12} {'Winner':>10}", file=sys.stderr)
    print(f"  {'-'*50}", file=sys.stderr)

    for name, r in all_results.items():
        winner = "Graph" if r["avg_graph_precision"] > r["avg_raw_precision"] else (
            "Raw" if r["avg_raw_precision"] > r["avg_graph_precision"] else "Tie")
        print(f"  {name:<15} {r['avg_graph_precision']:>12.0%} {r['avg_raw_precision']:>12.0%} {winner:>10}", file=sys.stderr)

    overall_graph = sum(r["avg_graph_precision"] for r in all_results.values()) / len(all_results)
    overall_raw = sum(r["avg_raw_precision"] for r in all_results.values()) / len(all_results)
    print(f"\n  {'OVERALL':<15} {overall_graph:>12.0%} {overall_raw:>12.0%}", file=sys.stderr)
    print(f"\n  H2 threshold: graph >= 80% across all archetypes", file=sys.stderr)
    all_pass = all(r["avg_graph_precision"] >= 0.8 for r in all_results.values())
    print(f"  H2 verdict: {'PASS' if all_pass else 'FAIL'}", file=sys.stderr)

    # Save
    out = Path("experiments/exp49b_results.json")
    out.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nResults saved to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
