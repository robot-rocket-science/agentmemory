"""
decompose_sentences.py -- S1: Sentence-level decomposition of repo files.

Decomposes files into sentence/paragraph/function-level nodes based on file type:
  - Markdown: paragraph-level with heading context
  - Python: function-level with docstring extraction
  - Other code: function-level via regex

Usage:
    python scripts/decompose_sentences.py /path/to/repo [--output /path/to/output.json]

Produces a sentence graph: nodes are sentences/paragraphs/functions, edges are
sequential (NEXT_IN_FILE), hierarchical (HEADING_CONTAINS, DEFINED_IN), and
cross-reference (CITES within sentences).
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SKIP_DIRS: set[str] = {
    ".git",
    "node_modules",
    "target",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".tox",
    "vendor",
    "third_party",
    "3rdparty",
}

STOP_WORDS: set[str] = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "shall",
    "can",
    "need",
    "must",
    "to",
    "of",
    "in",
    "for",
    "on",
    "with",
    "at",
    "by",
    "from",
    "as",
    "into",
    "through",
    "and",
    "but",
    "or",
    "if",
    "not",
    "no",
    "this",
    "that",
    "it",
    "its",
}


def git_head(repo: Path) -> str:
    r: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return r.stdout.strip()


# --- Sentence Node ---


class SentenceNode:
    """A sentence-level node in the decomposed graph."""

    def __init__(
        self,
        node_id: str,
        content: str,
        file_path: str,
        line_start: int,
        node_type: str,
        heading_context: str = "",
    ) -> None:
        self.node_id: str = node_id
        self.content: str = content
        self.file_path: str = file_path
        self.line_start: int = line_start
        self.node_type: str = node_type
        self.heading_context: str = heading_context

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.node_id,
            "content": self.content,
            "file": self.file_path,
            "line": self.line_start,
            "type": self.node_type,
            "heading": self.heading_context,
        }


class SentenceEdge:
    """An edge between sentence-level nodes."""

    def __init__(
        self,
        source: str,
        target: str,
        edge_type: str,
    ) -> None:
        self.source: str = source
        self.target: str = target
        self.edge_type: str = edge_type

    def to_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "target": self.target,
            "type": self.edge_type,
        }


# --- Markdown Decomposition ---


def decompose_markdown(
    file_path: str, content: str
) -> tuple[list[SentenceNode], list[SentenceEdge]]:
    """Decompose a markdown file into paragraph-level nodes."""
    nodes: list[SentenceNode] = []
    edges: list[SentenceEdge] = []

    lines: list[str] = content.split("\n")
    current_heading: str = ""
    current_para: list[str] = []
    para_start_line: int = 0
    node_idx: int = 0
    prev_node_id: str = ""

    def flush_para() -> None:
        nonlocal node_idx, prev_node_id
        text: str = "\n".join(current_para).strip()
        if len(text) < 15:
            return

        node_id: str = f"{file_path}:s{node_idx}"
        node_type: str = classify_md_sentence(text)
        nodes.append(
            SentenceNode(
                node_id=node_id,
                content=text,
                file_path=file_path,
                line_start=para_start_line,
                node_type=node_type,
                heading_context=current_heading,
            )
        )

        if prev_node_id:
            edges.append(SentenceEdge(prev_node_id, node_id, "NEXT_IN_FILE"))

        prev_node_id = node_id
        node_idx += 1

    for line_num, line in enumerate(lines):
        stripped: str = line.strip()

        # Heading
        if stripped.startswith("#"):
            flush_para()
            current_para = []
            current_heading = stripped.lstrip("#").strip()
            continue

        # Blank line = paragraph boundary
        if not stripped:
            if current_para:
                flush_para()
                current_para = []
            continue

        # Bullet list item = its own paragraph
        if stripped.startswith(
            ("- ", "* ", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")
        ):
            if current_para:
                flush_para()
                current_para = []
            current_para = [stripped]
            para_start_line = line_num
            flush_para()
            current_para = []
            continue

        # Regular line
        if not current_para:
            para_start_line = line_num
        current_para.append(stripped)

    # Flush remaining
    if current_para:
        flush_para()

    return nodes, edges


def classify_md_sentence(text: str) -> str:
    """Classify a markdown paragraph by its role."""
    lower: str = text.lower()

    if any(
        w in lower
        for w in [
            "must",
            "always",
            "never",
            "mandatory",
            "require",
            "rule",
            "constraint",
        ]
    ):
        return "CONSTRAINT"
    if any(
        w in lower
        for w in ["because", "rationale", "reason", "driven by", "root cause"]
    ):
        return "RATIONALE"
    if any(w in lower for w in ["decided", "decision", "chose", "chosen", "selected"]):
        return "DECISION"
    if any(
        w in lower for w in ["supersede", "replace", "retire", "override", "deprecated"]
    ):
        return "SUPERSESSION"
    if any(w in lower for w in ["data", "showed", "result", "found", "measured", "%"]):
        return "EVIDENCE"
    if any(w in lower for w in ["todo", "fixme", "hack", "workaround", "temporary"]):
        return "TODO"
    if re.match(r"^\|.*\|$", text):
        return "TABLE"
    if text.startswith("```"):
        return "CODE_BLOCK"

    return "CLAIM"


# --- Python Decomposition ---


def decompose_python(
    file_path: str, content: str
) -> tuple[list[SentenceNode], list[SentenceEdge]]:
    """Decompose a Python file into function/class-level nodes."""
    nodes: list[SentenceNode] = []
    edges: list[SentenceEdge] = []

    try:
        tree: ast.Module = ast.parse(content, filename=file_path)
    except SyntaxError:
        return nodes, edges

    node_idx: int = 0
    prev_node_id: str = ""

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            node_id: str = f"{file_path}:fn:{node.name}"
            # Extract function signature + docstring as content
            sig_lines: list[str] = content.split("\n")[
                node.lineno - 1 : min(node.lineno + 2, len(content.split("\n")))
            ]
            sig: str = "\n".join(sig_lines).strip()

            docstring: str | None = ast.get_docstring(node)
            func_content: str = sig
            if docstring:
                func_content = f"{sig}\n\n{docstring}"

            nodes.append(
                SentenceNode(
                    node_id=node_id,
                    content=func_content[:500],  # cap at 500 chars
                    file_path=file_path,
                    line_start=node.lineno,
                    node_type="FUNCTION",
                )
            )

            # Docstring as separate belief node
            if docstring and len(docstring) > 15:
                doc_id: str = f"{file_path}:doc:{node.name}"
                nodes.append(
                    SentenceNode(
                        node_id=doc_id,
                        content=docstring[:500],
                        file_path=file_path,
                        line_start=node.lineno + 1,
                        node_type="DOCSTRING",
                    )
                )
                edges.append(SentenceEdge(doc_id, node_id, "DOCUMENTS"))

            if prev_node_id:
                edges.append(SentenceEdge(prev_node_id, node_id, "NEXT_IN_FILE"))
            prev_node_id = node_id
            node_idx += 1

        elif isinstance(node, ast.ClassDef):
            node_id = f"{file_path}:cls:{node.name}"

            docstring = ast.get_docstring(node)
            class_content: str = f"class {node.name}"
            if docstring:
                class_content = f"class {node.name}\n\n{docstring}"

            nodes.append(
                SentenceNode(
                    node_id=node_id,
                    content=class_content[:500],
                    file_path=file_path,
                    line_start=node.lineno,
                    node_type="CLASS",
                )
            )

            if prev_node_id:
                edges.append(SentenceEdge(prev_node_id, node_id, "NEXT_IN_FILE"))
            prev_node_id = node_id
            node_idx += 1

    return nodes, edges


# --- Generic Code Decomposition ---


def decompose_code_generic(
    file_path: str, content: str, ext: str
) -> tuple[list[SentenceNode], list[SentenceEdge]]:
    """Decompose code files into function-level nodes via regex."""
    nodes: list[SentenceNode] = []
    edges: list[SentenceEdge] = []

    # Function patterns by language
    patterns: dict[str, re.Pattern[str]] = {
        ".rs": re.compile(r"^(\s*(?:pub\s+)?(?:async\s+)?fn\s+\w+)", re.MULTILINE),
        ".ts": re.compile(
            r"^(\s*(?:export\s+)?(?:async\s+)?function\s+\w+|(?:export\s+)?(?:const|let)\s+\w+\s*=\s*(?:async\s+)?\()",
            re.MULTILINE,
        ),
        ".tsx": re.compile(
            r"^(\s*(?:export\s+)?(?:async\s+)?function\s+\w+|(?:export\s+)?(?:const|let)\s+\w+\s*=\s*(?:async\s+)?\()",
            re.MULTILINE,
        ),
        ".js": re.compile(
            r"^(\s*(?:export\s+)?(?:async\s+)?function\s+\w+|(?:export\s+)?(?:const|let)\s+\w+\s*=\s*(?:async\s+)?\()",
            re.MULTILINE,
        ),
        ".go": re.compile(r"^(func\s+(?:\(\w+\s+\*?\w+\)\s+)?\w+)", re.MULTILINE),
        ".c": re.compile(r"^(\w[\w\s\*]+\s+\w+\s*\([^)]*\)\s*\{)", re.MULTILINE),
        ".cpp": re.compile(
            r"^(\w[\w\s\*:]+\s+\w+\s*\([^)]*\)\s*(?:const\s*)?\{)", re.MULTILINE
        ),
        ".h": re.compile(r"^(\w[\w\s\*]+\s+\w+\s*\([^)]*\)\s*;)", re.MULTILINE),
    }

    pattern: re.Pattern[str] | None = patterns.get(ext)
    if pattern is None:
        return nodes, edges

    lines: list[str] = content.split("\n")
    node_idx: int = 0
    prev_node_id: str = ""

    for m in pattern.finditer(content):
        _sig: str = m.group(1).strip()
        line_num: int = content[: m.start()].count("\n")

        # Get a few lines of context
        context_end: int = min(line_num + 5, len(lines))
        context: str = "\n".join(lines[line_num:context_end]).strip()

        node_id: str = f"{file_path}:fn{node_idx}"
        nodes.append(
            SentenceNode(
                node_id=node_id,
                content=context[:500],
                file_path=file_path,
                line_start=line_num,
                node_type="FUNCTION",
            )
        )

        if prev_node_id:
            edges.append(SentenceEdge(prev_node_id, node_id, "NEXT_IN_FILE"))
        prev_node_id = node_id
        node_idx += 1

    return nodes, edges


# --- Cross-Reference Extraction ---


def extract_sentence_cross_refs(
    nodes: list[SentenceNode],
) -> list[SentenceEdge]:
    """Extract cross-references between sentence nodes (D###, M###, URLs, file paths)."""
    edges: list[SentenceEdge] = []

    # Build index: reference -> list of node IDs mentioning it
    ref_pattern: re.Pattern[str] = re.compile(
        r"\b(D\d{2,4}|M\d{2,4}|ADR[-\s]?\d+|RFC\s?\d+)\b", re.IGNORECASE
    )
    ref_to_nodes: dict[str, list[str]] = {}

    for node in nodes:
        for m in ref_pattern.finditer(node.content):
            ref: str = m.group(1).upper().replace(" ", "")
            if ref not in ref_to_nodes:
                ref_to_nodes[ref] = []
            ref_to_nodes[ref].append(node.node_id)

    # Create CITES edges between nodes sharing a reference
    for ref, node_ids in ref_to_nodes.items():
        if len(node_ids) < 2:
            continue
        # First mention is the "definition", others cite it
        for citing_id in node_ids[1:]:
            if citing_id != node_ids[0]:
                edges.append(SentenceEdge(citing_id, node_ids[0], "CITES"))

    return edges


# --- Vocabulary Overlap Measurement ---


def tokenize(text: str) -> set[str]:
    """Extract word tokens."""
    words: list[str] = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", text)
    expanded: set[str] = set()
    for w in words:
        parts: list[str] = re.sub(r"([a-z])([A-Z])", r"\1 \2", w).split()
        for p in parts:
            for sub in p.split("_"):
                sub = sub.lower()
                if len(sub) > 2 and sub not in STOP_WORDS:
                    expanded.add(sub)
    return expanded


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter: int = len(a & b)
    union: int = len(a | b)
    return inter / union if union > 0 else 0.0


# --- Main ---


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} /path/to/repo [--output path]")
        sys.exit(1)

    repo: Path = Path(sys.argv[1]).resolve()
    output_path: Path | None = None

    args: list[str] = sys.argv[2:]
    i: int = 0
    while i < len(args):
        if args[i] == "--output" and i + 1 < len(args):
            output_path = Path(args[i + 1])
            i += 2
        else:
            i += 1

    if output_path is None:
        output_path = repo / "sentence_graph.json"

    head: str = git_head(repo)
    repo_name: str = repo.name

    print(f"[decompose] {repo_name} HEAD={head[:8]}", file=sys.stderr)

    all_nodes: list[SentenceNode] = []
    all_edges: list[SentenceEdge] = []
    file_count: int = 0
    type_counts: Counter[str] = Counter()
    files_by_method: Counter[str] = Counter()

    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath: Path = Path(root) / f
            rel: str = str(fpath.relative_to(repo))
            ext: str = fpath.suffix.lower()

            try:
                content: str = fpath.read_text(errors="ignore")
            except OSError:
                continue

            if not content.strip():
                continue

            nodes: list[SentenceNode] = []
            edges: list[SentenceEdge] = []

            if ext == ".md":
                nodes, edges = decompose_markdown(rel, content)
                files_by_method["markdown"] += 1
            elif ext == ".py":
                nodes, edges = decompose_python(rel, content)
                files_by_method["python_ast"] += 1
            elif ext in {".rs", ".ts", ".tsx", ".js", ".go", ".c", ".cpp", ".h"}:
                nodes, edges = decompose_code_generic(rel, content, ext)
                files_by_method["regex_code"] += 1
            else:
                continue

            if nodes:
                all_nodes.extend(nodes)
                all_edges.extend(edges)
                file_count += 1
                for n in nodes:
                    type_counts[n.node_type] += 1

    # Cross-references between sentence nodes
    xref_edges: list[SentenceEdge] = extract_sentence_cross_refs(all_nodes)
    all_edges.extend(xref_edges)

    print(f"  files decomposed: {file_count}", file=sys.stderr)
    print(f"  sentence nodes: {len(all_nodes)}", file=sys.stderr)
    print(
        f"  edges: {len(all_edges)} ({len(all_edges) - len(xref_edges)} structural + {len(xref_edges)} cross-ref)",
        file=sys.stderr,
    )
    print(f"  decomposition methods: {dict(files_by_method)}", file=sys.stderr)
    print(f"  node types: {dict(type_counts.most_common())}", file=sys.stderr)

    # Vocabulary overlap at sentence level
    # Sample: measure overlap between consecutive sentence pairs (NEXT_IN_FILE edges)
    next_edges: list[SentenceEdge] = [
        e for e in all_edges if e.edge_type == "NEXT_IN_FILE"
    ]
    node_map: dict[str, SentenceNode] = {n.node_id: n for n in all_nodes}
    overlaps: list[float] = []

    for e in next_edges[:500]:  # sample first 500
        src: SentenceNode | None = node_map.get(e.source)
        tgt: SentenceNode | None = node_map.get(e.target)
        if src and tgt:
            j: float = jaccard(tokenize(src.content), tokenize(tgt.content))
            overlaps.append(j)

    mean_overlap: float = 0.0
    below_01: int = 0
    above_03: int = 0
    if overlaps:
        mean_overlap = sum(overlaps) / len(overlaps)
        below_01 = sum(1 for o in overlaps if o < 0.1)
        above_03 = sum(1 for o in overlaps if o > 0.3)
        print(
            f"\n  vocabulary overlap (sentence-level, {len(overlaps)} pairs):",
            file=sys.stderr,
        )
        print(f"    mean: {mean_overlap:.3f}", file=sys.stderr)
        print(
            f"    <0.1: {below_01} ({below_01 / len(overlaps) * 100:.1f}%)",
            file=sys.stderr,
        )
        print(
            f"    >0.3: {above_03} ({above_03 / len(overlaps) * 100:.1f}%)",
            file=sys.stderr,
        )

    # Write output
    result: dict[str, Any] = {
        "repo": str(repo),
        "name": repo_name,
        "head": head,
        "summary": {
            "files_decomposed": file_count,
            "total_nodes": len(all_nodes),
            "total_edges": len(all_edges),
            "structural_edges": len(all_edges) - len(xref_edges),
            "cross_ref_edges": len(xref_edges),
            "node_types": dict(type_counts.most_common()),
            "files_by_method": dict(files_by_method),
            "vocab_overlap_mean": round(mean_overlap, 4) if overlaps else None,
            "vocab_overlap_below_01_pct": round(below_01 / len(overlaps) * 100, 1)
            if overlaps
            else None,
            "vocab_overlap_above_03_pct": round(above_03 / len(overlaps) * 100, 1)
            if overlaps
            else None,
        },
        "nodes": [n.to_dict() for n in all_nodes],
        "edges": [e.to_dict() for e in all_edges],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2))
    print(f"\n  written to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
