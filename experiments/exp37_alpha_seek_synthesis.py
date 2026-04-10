"""
Experiment 37b: Alpha-Seek Multi-Layer Graph Synthesis

Validates the control/data flow approach on a real project by synthesizing:
1. Control flow (CALLS) and data flow (PASSES_DATA) from AST analysis
2. Git history (CO_CHANGED, COMMIT_BELIEF) from commit log
3. Documentation references (CITES) from D### patterns in code/docs

The synthesis question: do these three layers capture genuinely different
relationships, and does combining them produce a richer graph than any
single layer alone?

Alpha-seek: 289 Python files, 552 commits, known decision history (165 decisions
from Exp 6), rich D### citation patterns in comments and docstrings.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ALPHA_SEEK_ROOT = Path("/Users/thelorax/projects/alpha-seek")

# ============================================================
# Layer 1: Control Flow / Data Flow (AST)
# ============================================================

BUILTINS = {
    "print", "len", "range", "enumerate", "zip", "map", "filter",
    "sorted", "reversed", "isinstance", "issubclass", "hasattr",
    "getattr", "setattr", "delattr", "type", "super", "property",
    "staticmethod", "classmethod", "str", "int", "float", "bool",
    "list", "dict", "set", "tuple", "bytes", "bytearray",
    "open", "input", "id", "hash", "repr", "format", "abs",
    "min", "max", "sum", "any", "all", "next", "iter",
    "ValueError", "TypeError", "KeyError", "RuntimeError",
    "Exception", "NotImplementedError", "AttributeError",
    "IndexError", "FileNotFoundError", "OSError",
}


@dataclass
class ASTNode:
    name: str
    file_path: str
    line_start: int
    line_end: int
    node_type: str  # "function", "method", "class"
    containing_class: str | None = None


@dataclass
class ASTEdge:
    source: str
    target: str
    edge_type: str  # CALLS, PASSES_DATA, CONTAINS
    file_path: str
    line: int
    resolved: bool = True


def extract_ast_layer(repo_root: Path) -> tuple[dict[str, ASTNode], list[ASTEdge], list[tuple[str, str, str, int]]]:
    """Extract control flow and data flow from Python AST."""
    nodes: dict[str, ASTNode] = {}
    edges: list[ASTEdge] = []
    unresolved: list[tuple[str, str, str, int]] = []

    py_files: list[Path] = []
    for root, _dirs, files in os.walk(repo_root):
        if any(skip in root for skip in [".venv", "__pycache__", ".git", "node_modules", ".egg-info"]):
            continue
        for f in files:
            if f.endswith(".py"):
                py_files.append(Path(root) / f)

    for fp in py_files:
        try:
            source = fp.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(fp))
        except (SyntaxError, UnicodeDecodeError, FileNotFoundError):
            continue

        rel_path = str(fp.relative_to(repo_root))
        module = rel_path.replace("/", ".").replace(".py", "")

        # Pre-build line-range index for fast enclosing-callable lookup
        callable_ranges: list[tuple[int, int, str]] = []

        # Extract definitions
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                qname = f"{module}.{node.name}"
                nodes[qname] = ASTNode(
                    name=qname, file_path=rel_path,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    node_type="class",
                )
                for item in node.body:
                    if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                        mname = f"{qname}.{item.name}"
                        nodes[mname] = ASTNode(
                            name=mname, file_path=rel_path,
                            line_start=item.lineno,
                            line_end=item.end_lineno or item.lineno,
                            node_type="method", containing_class=qname,
                        )
                        edges.append(ASTEdge(
                            source=qname, target=mname,
                            edge_type="CONTAINS", file_path=rel_path,
                            line=item.lineno,
                        ))
                        callable_ranges.append((item.lineno, item.end_lineno or item.lineno, mname))

            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                # Module-level function (not inside a class)
                qname = f"{module}.{node.name}"
                if qname not in nodes:  # Don't overwrite class methods
                    nodes[qname] = ASTNode(
                        name=qname, file_path=rel_path,
                        line_start=node.lineno,
                        line_end=node.end_lineno or node.lineno,
                        node_type="function",
                    )
                    callable_ranges.append((node.lineno, node.end_lineno or node.lineno, qname))

        def find_enclosing(line: int) -> str | None:
            best = None
            best_span = float("inf")
            for start, end, name in callable_ranges:
                if start <= line <= end:
                    span = end - start
                    if span < best_span:
                        best = name
                        best_span = span
            return best

        # Extract CALLS
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            callee_name = None
            if isinstance(node.func, ast.Name):
                callee_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                callee_name = node.func.attr
            else:
                continue

            if callee_name in BUILTINS:
                continue

            caller = find_enclosing(node.lineno)
            if caller is None:
                continue

            # Try resolution
            callee_qname = f"{module}.{callee_name}"
            resolved = callee_qname in nodes

            if not resolved:
                for qn in nodes:
                    if qn.endswith(f".{callee_name}"):
                        callee_qname = qn
                        resolved = True
                        break

            if resolved:
                edges.append(ASTEdge(
                    source=caller, target=callee_qname,
                    edge_type="CALLS", file_path=rel_path,
                    line=node.lineno, resolved=True,
                ))
            else:
                unresolved.append((caller, callee_name, rel_path, node.lineno))

        # Extract PASSES_DATA (x = foo(); bar(x) => foo -> bar)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue

            call_assignments: dict[str, str] = {}
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    tgt = stmt.targets[0]
                    if isinstance(tgt, ast.Name) and isinstance(stmt.value, ast.Call):
                        fn = stmt.value.func
                        if isinstance(fn, ast.Name) and fn.id not in BUILTINS:
                            call_assignments[tgt.id] = fn.id
                        elif isinstance(fn, ast.Attribute) and fn.attr not in BUILTINS:
                            call_assignments[tgt.id] = fn.attr

            for stmt in ast.walk(node):
                if not isinstance(stmt, ast.Call):
                    continue
                consumer = None
                if isinstance(stmt.func, ast.Name):
                    consumer = stmt.func.id
                elif isinstance(stmt.func, ast.Attribute):
                    consumer = stmt.func.attr
                if consumer is None or consumer in BUILTINS:
                    continue
                for arg in stmt.args:
                    if isinstance(arg, ast.Name) and arg.id in call_assignments:
                        producer = call_assignments[arg.id]
                        edges.append(ASTEdge(
                            source=f"?{producer}", target=f"?{consumer}",
                            edge_type="PASSES_DATA", file_path=rel_path,
                            line=stmt.lineno, resolved=False,
                        ))

    return nodes, edges, unresolved


# ============================================================
# Layer 2: Git History (CO_CHANGED, COMMIT_BELIEF)
# ============================================================

def extract_git_layer(repo_root: Path) -> dict[str, Any]:
    """Extract co-change edges and commit beliefs from git history."""
    result = subprocess.run(
        ["git", "log", "--name-only", "--format=COMMIT:%H|%s", "--no-merges"],
        capture_output=True, text=True, cwd=repo_root,
    )

    co_change: Counter[tuple[str, str]] = Counter()
    commit_beliefs: list[dict[str, Any]] = []
    current_files: list[str] = []
    current_msg = ""
    current_hash = ""

    for line in result.stdout.strip().split("\n"):
        if line.startswith("COMMIT:"):
            # Process previous commit
            if current_files:
                py_files = [f for f in current_files if f.endswith(".py")]
                for i, a in enumerate(py_files):
                    for b in py_files[i+1:]:
                        pair: tuple[str, str] = (min(a, b), max(a, b))
                        co_change[pair] += 1

                if current_msg and not current_msg.lower().startswith(("merge", "wip")):
                    commit_beliefs.append({
                        "hash": current_hash,
                        "message": current_msg,
                        "files": py_files,
                    })

            parts = line[7:].split("|", 1)
            current_hash = parts[0]
            current_msg = parts[1] if len(parts) > 1 else ""
            current_files = []
        elif line.strip():
            current_files.append(line.strip())

    # Process last commit
    if current_files:
        py_files = [f for f in current_files if f.endswith(".py")]
        for i, a in enumerate(py_files):
            for b in py_files[i+1:]:
                pair: tuple[str, str] = (min(a, b), max(a, b))
                co_change[pair] += 1
        if current_msg:
            commit_beliefs.append({
                "hash": current_hash,
                "message": current_msg,
                "files": py_files,
            })

    return {
        "co_change_edges_raw": len(co_change),
        "co_change_edges_w3": len({k: v for k, v in co_change.items() if v >= 3}),
        "co_change_max_weight": max(co_change.values()) if co_change else 0,
        "commit_beliefs": len(commit_beliefs),
        "co_change_pairs": co_change,
        "belief_list": commit_beliefs,
    }


# ============================================================
# Layer 3: Documentation References (CITES via D### pattern)
# ============================================================

def extract_citation_layer(repo_root: Path) -> dict[str, Any]:
    """Extract D### decision references from code comments and docstrings."""
    d_pattern = re.compile(r"D(\d{3})")
    citations: list[dict[str, Any]] = []

    for root, _dirs, files in os.walk(repo_root):
        if any(skip in root for skip in [".venv", "__pycache__", ".git", ".egg-info"]):
            continue
        for f in files:
            if not f.endswith((".py", ".md")):
                continue
            fp = Path(root) / f
            try:
                text = fp.read_text(encoding="utf-8")
            except (UnicodeDecodeError, FileNotFoundError):
                continue

            rel = str(fp.relative_to(repo_root))
            for i, line in enumerate(text.split("\n"), 1):
                matches = d_pattern.findall(line)
                for m in matches:
                    citations.append({
                        "file": rel,
                        "line": i,
                        "decision": f"D{m}",
                        "context": line.strip()[:120],
                    })

    # Group by file -> decisions referenced
    file_decisions: dict[str, set[str]] = defaultdict(set)
    for c in citations:
        file_decisions[c["file"]].add(c["decision"])

    # Build CITES edges between files that reference same decisions
    cites_edges: Counter[tuple[str, str]] = Counter()
    files_list = list(file_decisions.keys())
    for i, a in enumerate(files_list):
        for b in files_list[i+1:]:
            shared = file_decisions[a] & file_decisions[b]
            if shared:
                cites_edges[(min(a, b), max(a, b))] = len(shared)

    return {
        "total_citations": len(citations),
        "unique_decisions_referenced": len(set(c["decision"] for c in citations)),
        "files_with_citations": len(file_decisions),
        "cites_edges": len(cites_edges),
        "citation_list": citations,
        "cites_pairs": cites_edges,
        "file_decisions": {k: sorted(v) for k, v in file_decisions.items()},
    }


# ============================================================
# Synthesis: Cross-Layer Analysis
# ============================================================

def synthesize(
    ast_nodes: dict[str, ASTNode],
    ast_edges: list[ASTEdge],
    unresolved: list[tuple[str, str, str, int]],
    git_data: dict[str, Any],
    cite_data: dict[str, Any],
) -> dict[str, Any]:
    """Compare and combine the three layers."""

    # Project CALLS edges to file-level pairs for comparison with CO_CHANGED
    calls_file_pairs: set[tuple[str, str]] = set()
    for e in ast_edges:
        if e.edge_type == "CALLS" and e.resolved:
            src_file = ast_nodes.get(e.source, None)
            tgt_file = ast_nodes.get(e.target, None)
            if src_file and tgt_file and src_file.file_path != tgt_file.file_path:
                pair: tuple[str, str] = (min(src_file.file_path, tgt_file.file_path), max(src_file.file_path, tgt_file.file_path))
                calls_file_pairs.add(pair)

    # CO_CHANGED file pairs (w>=3)
    co_change_counter: Counter[tuple[str, str]] = git_data["co_change_pairs"]
    co_change_pairs: set[tuple[str, str]] = {k for k, v in co_change_counter.items() if v >= 3}

    # CITES file pairs
    cites_counter: Counter[tuple[str, str]] = cite_data["cites_pairs"]
    cites_pairs: set[tuple[str, str]] = set(cites_counter.keys())

    # Overlap analysis
    calls_only = calls_file_pairs - co_change_pairs - cites_pairs
    cochange_only = co_change_pairs - calls_file_pairs - cites_pairs
    cites_only = cites_pairs - calls_file_pairs - co_change_pairs
    calls_and_cochange = calls_file_pairs & co_change_pairs
    calls_and_cites = calls_file_pairs & cites_pairs
    cochange_and_cites = co_change_pairs & cites_pairs
    all_three = calls_file_pairs & co_change_pairs & cites_pairs

    # Jaccard similarities
    def jaccard(a: set[tuple[str, str]], b: set[tuple[str, str]]) -> float:
        if not a and not b:
            return 0.0
        return len(a & b) / len(a | b)

    # PASSES_DATA analysis
    data_edges = [e for e in ast_edges if e.edge_type == "PASSES_DATA"]
    calls_edges = [e for e in ast_edges if e.edge_type == "CALLS" and e.resolved]
    contains_edges = [e for e in ast_edges if e.edge_type == "CONTAINS"]

    # Fan-in for infrastructure detection
    fan_in = Counter(e.target for e in calls_edges)
    total_callers = len(set(e.source for e in calls_edges))
    infra_threshold = max(1, int(total_callers * 0.10))
    infrastructure = {name for name, count in fan_in.items() if count > infra_threshold}

    # Files covered by each layer
    ast_files = set(n.file_path for n in ast_nodes.values())
    git_files: set[str] = set()
    for pair in co_change_pairs:
        git_files.update(pair)
    file_decisions: dict[str, Any] = cite_data["file_decisions"]
    cite_files: set[str] = set(file_decisions.keys())

    return {
        "layer_summary": {
            "AST": {
                "callable_nodes": len([n for n in ast_nodes.values() if n.node_type != "class"]),
                "class_nodes": len([n for n in ast_nodes.values() if n.node_type == "class"]),
                "CALLS_resolved": len(calls_edges),
                "CALLS_unresolved": len(unresolved),
                "PASSES_DATA": len(data_edges),
                "CONTAINS": len(contains_edges),
                "resolution_rate": round(
                    len(calls_edges) / max(1, len(calls_edges) + len(unresolved)), 3
                ),
                "files_covered": len(ast_files),
            },
            "GIT": {
                "co_change_raw": git_data["co_change_edges_raw"],
                "co_change_w3": git_data["co_change_edges_w3"],
                "commit_beliefs": git_data["commit_beliefs"],
                "max_weight": git_data["co_change_max_weight"],
                "files_covered": len(git_files),
            },
            "CITES": {
                "total_citations": cite_data["total_citations"],
                "unique_decisions": cite_data["unique_decisions_referenced"],
                "files_with_citations": cite_data["files_with_citations"],
                "cites_edges": cite_data["cites_edges"],
                "files_covered": len(cite_files),
            },
        },
        "cross_layer_overlap": {
            "CALLS_file_pairs": len(calls_file_pairs),
            "CO_CHANGED_file_pairs_w3": len(co_change_pairs),
            "CITES_file_pairs": len(cites_pairs),
            "CALLS_only": len(calls_only),
            "CO_CHANGED_only": len(cochange_only),
            "CITES_only": len(cites_only),
            "CALLS_and_CO_CHANGED": len(calls_and_cochange),
            "CALLS_and_CITES": len(calls_and_cites),
            "CO_CHANGED_and_CITES": len(cochange_and_cites),
            "all_three": len(all_three),
            "jaccard_CALLS_vs_CO_CHANGED": round(jaccard(calls_file_pairs, co_change_pairs), 3),
            "jaccard_CALLS_vs_CITES": round(jaccard(calls_file_pairs, cites_pairs), 3),
            "jaccard_CO_CHANGED_vs_CITES": round(jaccard(co_change_pairs, cites_pairs), 3),
        },
        "fan_in_top_15": fan_in.most_common(15),
        "infrastructure_callees": sorted(infrastructure),
        "infrastructure_threshold": infra_threshold,
        "sample_calls_only_pairs": sorted(calls_only)[:10],
        "sample_cochange_only_pairs": sorted(cochange_only)[:10],
        "sample_all_three_pairs": sorted(all_three)[:10],
    }


def main() -> None:
    print("=== Layer 1: AST Control/Data Flow ===")
    t0 = time.perf_counter()
    ast_nodes, ast_edges, unresolved = extract_ast_layer(ALPHA_SEEK_ROOT)
    t_ast = time.perf_counter() - t0
    print(f"  Extraction time: {t_ast:.2f}s")

    print("\n=== Layer 2: Git History ===")
    t0 = time.perf_counter()
    git_data = extract_git_layer(ALPHA_SEEK_ROOT)
    t_git = time.perf_counter() - t0
    print(f"  Extraction time: {t_git:.2f}s")

    print("\n=== Layer 3: Documentation Citations ===")
    t0 = time.perf_counter()
    cite_data = extract_citation_layer(ALPHA_SEEK_ROOT)
    t_cite = time.perf_counter() - t0
    print(f"  Extraction time: {t_cite:.2f}s")

    print("\n=== Synthesis ===")
    results = synthesize(ast_nodes, ast_edges, unresolved, git_data, cite_data)
    results["extraction_times"] = {
        "AST": round(t_ast, 3),
        "GIT": round(t_git, 3),
        "CITES": round(t_cite, 3),
        "total": round(t_ast + t_git + t_cite, 3),
    }

    # Save full results
    out_path = Path(__file__).parent / "exp37_alpha_seek_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull results saved to {out_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("SYNTHESIS RESULTS")
    print("=" * 60)

    ls = results["layer_summary"]
    print(f"\nAST Layer:")
    print(f"  Callables: {ls['AST']['callable_nodes']}, Classes: {ls['AST']['class_nodes']}")
    print(f"  CALLS (resolved): {ls['AST']['CALLS_resolved']}")
    print(f"  CALLS (unresolved): {ls['AST']['CALLS_unresolved']}")
    print(f"  PASSES_DATA: {ls['AST']['PASSES_DATA']}")
    print(f"  Resolution rate: {ls['AST']['resolution_rate']}")

    print(f"\nGit Layer:")
    print(f"  CO_CHANGED edges (w>=3): {ls['GIT']['co_change_w3']}")
    print(f"  Commit beliefs: {ls['GIT']['commit_beliefs']}")

    print(f"\nCITES Layer:")
    print(f"  D### citations found: {ls['CITES']['total_citations']}")
    print(f"  Unique decisions: {ls['CITES']['unique_decisions']}")
    print(f"  Files with citations: {ls['CITES']['files_with_citations']}")

    cl = results["cross_layer_overlap"]
    print(f"\nCross-Layer Overlap (file-pair level):")
    print(f"  CALLS file pairs: {cl['CALLS_file_pairs']}")
    print(f"  CO_CHANGED file pairs (w>=3): {cl['CO_CHANGED_file_pairs_w3']}")
    print(f"  CITES file pairs: {cl['CITES_file_pairs']}")
    print(f"  ---")
    print(f"  CALLS only (not in git or docs): {cl['CALLS_only']}")
    print(f"  CO_CHANGED only (not in code or docs): {cl['CO_CHANGED_only']}")
    print(f"  CITES only (not in code or git): {cl['CITES_only']}")
    print(f"  CALLS + CO_CHANGED (both): {cl['CALLS_and_CO_CHANGED']}")
    print(f"  CALLS + CITES (both): {cl['CALLS_and_CITES']}")
    print(f"  CO_CHANGED + CITES (both): {cl['CO_CHANGED_and_CITES']}")
    print(f"  All three layers: {cl['all_three']}")
    print(f"  ---")
    print(f"  Jaccard CALLS vs CO_CHANGED: {cl['jaccard_CALLS_vs_CO_CHANGED']}")
    print(f"  Jaccard CALLS vs CITES: {cl['jaccard_CALLS_vs_CITES']}")
    print(f"  Jaccard CO_CHANGED vs CITES: {cl['jaccard_CO_CHANGED_vs_CITES']}")

    print(f"\nExtraction times: AST={results['extraction_times']['AST']}s, "
          f"GIT={results['extraction_times']['GIT']}s, "
          f"CITES={results['extraction_times']['CITES']}s, "
          f"Total={results['extraction_times']['total']}s")

    # Interpretation
    print("\n" + "=" * 60)
    print("HYPOTHESIS CHECK")
    print("=" * 60)
    j_cc = cl['jaccard_CALLS_vs_CO_CHANGED']
    print(f"\nH1 (Structural Novelty): Jaccard CALLS vs CO_CHANGED = {j_cc}")
    print(f"  Prediction: < 0.40. {'PASS' if j_cc < 0.40 else 'FAIL'}")
    print(f"  CALLS-only pairs: {cl['CALLS_only']} (relationships visible only in code structure)")

    res_rate = ls['AST']['resolution_rate']
    print(f"\nH5 (Extraction Feasibility): {results['extraction_times']['AST']}s for {ls['AST']['callable_nodes'] + ls['AST']['class_nodes']} nodes")
    print(f"  Resolution rate: {res_rate}")
    print(f"  Prediction: > 50% resolution. {'PASS' if res_rate > 0.50 else 'FAIL -- method calls dominate unresolved'}")


if __name__ == "__main__":
    main()
