"""
Experiment 37: Control Flow and Data Flow Extraction Feasibility

Hypothesis: Tree-sitter-equivalent AST extraction (via Python's ast module) can
extract CALLS and PASSES_DATA edges from Python source files in < 1 second per
file, with a meaningful resolution rate (> 50% of call sites resolved).

Method: Parse all .py files in this repo (experiments/ + scripts/), extract
callable nodes and CALLS/PASSES_DATA edges, measure counts, resolution rates,
fan-in distributions, and overlap with existing extraction methods.

This is a feasibility test, not a full experiment. It validates that the
extraction pipeline described in CONTROL_DATA_FLOW_RESEARCH.md is buildable.
"""

from __future__ import annotations

import ast
import json
import os
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class CallableNode:
    qualified_name: str
    file_path: str
    line_start: int
    line_end: int
    parameters: list[str]
    node_type: str  # "function", "method", "lambda"
    containing_class: str | None = None


@dataclass
class TypeDefNode:
    qualified_name: str
    file_path: str
    line_start: int
    line_end: int
    bases: list[str]


@dataclass
class Edge:
    source: str  # qualified name of caller/producer
    target: str  # qualified name of callee/consumer
    edge_type: str  # CALLS, PASSES_DATA, CONTAINS, OVERRIDES
    file_path: str
    line: int
    resolved: bool = True  # False if target couldn't be resolved to a definition
    weight: int = 1


class ControlDataFlowExtractor:
    """Extract CALLS and PASSES_DATA edges from Python source using ast module."""

    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root)
        self.callables: dict[str, CallableNode] = {}
        self.type_defs: dict[str, TypeDefNode] = {}
        self.edges: list[Edge] = []
        self.unresolved_calls: list[tuple[str, str, str, int]] = []  # (caller, name, file, line)

        # Built-in names to exclude from CALLS edges
        builtins_obj: Any = __builtins__
        builtins_names: list[str] = dir(builtins_obj)
        self.builtins: set[str] = set(builtins_names)
        self.builtins.update({
            "print", "len", "range", "enumerate", "zip", "map", "filter",
            "sorted", "reversed", "isinstance", "issubclass", "hasattr",
            "getattr", "setattr", "delattr", "type", "super", "property",
            "staticmethod", "classmethod", "str", "int", "float", "bool",
            "list", "dict", "set", "tuple", "bytes", "bytearray",
            "open", "input", "id", "hash", "repr", "format",
        })

    def extract_file(self, file_path: Path) -> None:
        """Extract all nodes and edges from a single Python file."""
        try:
            source = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            return

        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError:
            return

        rel_path = str(file_path.relative_to(self.repo_root))
        module_name = rel_path.replace("/", ".").replace(".py", "")

        self._extract_definitions(tree, module_name, rel_path)
        self._extract_calls(tree, module_name, rel_path)
        self._extract_data_flow(tree, module_name, rel_path)

    def _extract_definitions(self, tree: ast.AST, module: str, file_path: str) -> None:
        """Extract callable and type_def nodes."""
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                # Determine if this is a method (inside a class) or a function
                qname = f"{module}.{node.name}"
                containing_class = None

                # Check parent chain for class context
                for parent in ast.walk(tree):
                    if isinstance(parent, ast.ClassDef):
                        for child in ast.iter_child_nodes(parent):
                            if child is node:
                                qname = f"{module}.{parent.name}.{node.name}"
                                containing_class = f"{module}.{parent.name}"
                                break

                params = [arg.arg for arg in node.args.args if arg.arg != "self"]
                self.callables[qname] = CallableNode(
                    qualified_name=qname,
                    file_path=file_path,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    parameters=params,
                    node_type="method" if containing_class else "function",
                    containing_class=containing_class,
                )

                if containing_class:
                    self.edges.append(Edge(
                        source=containing_class,
                        target=qname,
                        edge_type="CONTAINS",
                        file_path=file_path,
                        line=node.lineno,
                    ))

            elif isinstance(node, ast.ClassDef):
                qname = f"{module}.{node.name}"
                bases_list: list[str] = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bases_list.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        bases_list.append(ast.dump(base))

                self.type_defs[qname] = TypeDefNode(
                    qualified_name=qname,
                    file_path=file_path,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    bases=bases_list,
                )

    def _find_enclosing_callable(self, tree: ast.AST, target_line: int, module: str) -> str | None:
        """Find the callable that contains a given line number."""
        best = None
        best_range = float("inf")

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                end = node.end_lineno or node.lineno
                if node.lineno <= target_line <= end:
                    span = end - node.lineno
                    if span < best_range:
                        # Try to find qualified name
                        qname = f"{module}.{node.name}"
                        for parent in ast.walk(tree):
                            if isinstance(parent, ast.ClassDef):
                                for child in ast.iter_child_nodes(parent):
                                    if child is node:
                                        qname = f"{module}.{parent.name}.{node.name}"
                                        break
                        best = qname
                        best_range = span
        return best

    def _extract_calls(self, tree: ast.AST, module: str, file_path: str) -> None:
        """Extract CALLS edges from call expressions."""
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            # Determine callee name
            callee_name = None
            if isinstance(node.func, ast.Name):
                callee_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                callee_name = node.func.attr
            else:
                continue

            # Skip builtins
            if callee_name in self.builtins:
                continue

            # Find enclosing callable
            caller = self._find_enclosing_callable(tree, node.lineno, module)
            if caller is None:
                continue  # Module-level call, skip

            # Try to resolve callee within same module
            callee_qname = f"{module}.{callee_name}"
            resolved = callee_qname in self.callables

            if not resolved:
                # Try class-scoped resolution
                for qn in self.callables:
                    if qn.endswith(f".{callee_name}"):
                        callee_qname = qn
                        resolved = True
                        break

            if resolved:
                self.edges.append(Edge(
                    source=caller,
                    target=callee_qname,
                    edge_type="CALLS",
                    file_path=file_path,
                    line=node.lineno,
                    resolved=True,
                ))
            else:
                self.unresolved_calls.append((caller, callee_name, file_path, node.lineno))

    def _extract_data_flow(self, tree: ast.AST, module: str, file_path: str) -> None:
        """Extract PASSES_DATA edges from variable assignment chains.

        Pattern: x = foo()  ... bar(x)  =>  PASSES_DATA: foo -> bar
        """
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue

            # Find the enclosing callable's qualified name
            caller = self._find_enclosing_callable(tree, node.lineno, module)
            if caller is None:
                continue

            # Collect assignments where RHS is a call
            # var_name -> callee_name
            call_assignments: dict[str, str] = {}

            for stmt in ast.walk(node):
                # Pattern: x = some_call(...)
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    target = stmt.targets[0]
                    if isinstance(target, ast.Name) and isinstance(stmt.value, ast.Call):
                        call_func = stmt.value.func
                        if isinstance(call_func, ast.Name):
                            call_assignments[target.id] = call_func.id
                        elif isinstance(call_func, ast.Attribute):
                            call_assignments[target.id] = call_func.attr

            # Now find calls where one of these variables is an argument
            for stmt in ast.walk(node):
                if not isinstance(stmt, ast.Call):
                    continue

                consumer_name = None
                if isinstance(stmt.func, ast.Name):
                    consumer_name = stmt.func.id
                elif isinstance(stmt.func, ast.Attribute):
                    consumer_name = stmt.func.attr

                if consumer_name is None or consumer_name in self.builtins:
                    continue

                for arg in stmt.args:
                    if isinstance(arg, ast.Name) and arg.id in call_assignments:
                        producer_name = call_assignments[arg.id]
                        if producer_name in self.builtins:
                            continue
                        self.edges.append(Edge(
                            source=f"?{producer_name}",  # May not be resolved
                            target=f"?{consumer_name}",
                            edge_type="PASSES_DATA",
                            file_path=file_path,
                            line=stmt.lineno,
                            resolved=False,  # Cross-file resolution needed
                        ))

    def extract_repo(self) -> dict[str, Any]:
        """Extract all Python files in the repo."""
        py_files: list[Path] = []
        for root, _dirs, files in os.walk(self.repo_root):
            # Skip .venv, __pycache__, .git
            if any(skip in root for skip in [".venv", "__pycache__", ".git", "node_modules"]):
                continue
            for f in files:
                if f.endswith(".py"):
                    py_files.append(Path(root) / f)

        start = time.perf_counter()
        for fp in py_files:
            self.extract_file(fp)
        elapsed = time.perf_counter() - start

        # Compute metrics
        calls_edges = [e for e in self.edges if e.edge_type == "CALLS"]
        data_edges = [e for e in self.edges if e.edge_type == "PASSES_DATA"]
        contains_edges = [e for e in self.edges if e.edge_type == "CONTAINS"]
        resolved_calls = [e for e in calls_edges if e.resolved]

        # Fan-in: how many callers does each callee have?
        fan_in = Counter(e.target for e in calls_edges)
        # Fan-out: how many callees does each caller have?
        fan_out = Counter(e.source for e in calls_edges)

        # Top fan-in (potential utilities)
        top_fan_in = fan_in.most_common(15)

        # Identify infrastructure (>10% of callers)
        total_callers = len(set(e.source for e in calls_edges))
        infrastructure_threshold = max(1, int(total_callers * 0.10))
        infrastructure = {name for name, count in fan_in.items() if count > infrastructure_threshold}

        return {
            "files_scanned": len(py_files),
            "extraction_time_seconds": round(elapsed, 4),
            "callable_nodes": len(self.callables),
            "type_def_nodes": len(self.type_defs),
            "edges": {
                "CALLS": len(calls_edges),
                "CALLS_resolved": len(resolved_calls),
                "CALLS_unresolved": len(self.unresolved_calls),
                "PASSES_DATA": len(data_edges),
                "CONTAINS": len(contains_edges),
            },
            "resolution_rate": round(len(resolved_calls) / max(1, len(calls_edges) + len(self.unresolved_calls)), 3),
            "fan_in_distribution": {
                "max": max(fan_in.values()) if fan_in else 0,
                "mean": round(sum(fan_in.values()) / max(1, len(fan_in)), 2),
                "top_15": top_fan_in,
            },
            "fan_out_distribution": {
                "max": max(fan_out.values()) if fan_out else 0,
                "mean": round(sum(fan_out.values()) / max(1, len(fan_out)), 2),
            },
            "infrastructure_callees": sorted(infrastructure),
            "infrastructure_threshold": infrastructure_threshold,
            "sample_callables": list(self.callables.keys())[:20],
            "sample_unresolved": self.unresolved_calls[:20],
            "sample_data_flow": [(e.source, e.target, e.file_path, e.line) for e in data_edges[:20]],
        }


def main() -> None:
    repo_root: Path = Path(__file__).parent.parent
    extractor: ControlDataFlowExtractor = ControlDataFlowExtractor(str(repo_root))
    results: dict[str, Any] = extractor.extract_repo()

    print(json.dumps(results, indent=2, default=str))

    # Summary
    print("\n--- SUMMARY ---")
    print(f"Files scanned: {results['files_scanned']}")
    print(f"Extraction time: {results['extraction_time_seconds']}s")
    print(f"Callable nodes: {results['callable_nodes']}")
    print(f"Type definitions: {results['type_def_nodes']}")
    print(f"CALLS edges (resolved): {results['edges']['CALLS_resolved']}")
    print(f"CALLS edges (unresolved): {results['edges']['CALLS_unresolved']}")
    print(f"PASSES_DATA edges: {results['edges']['PASSES_DATA']}")
    print(f"CONTAINS edges: {results['edges']['CONTAINS']}")
    print(f"Resolution rate: {results['resolution_rate']}")
    print(f"Fan-in max: {results['fan_in_distribution']['max']}")
    print(f"Fan-in mean: {results['fan_in_distribution']['mean']}")
    print(f"Infrastructure callees ({results['infrastructure_threshold']}+ callers): {results['infrastructure_callees']}")


if __name__ == "__main__":
    main()
