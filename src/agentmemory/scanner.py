"""Project directory scanner for onboarding.

Detects available signals in a project directory (git history, docs, source code,
directives, citations) and extracts nodes + edges for ingestion into the memory store.

Based on validated extraction logic from Exp 48/49.
"""
from __future__ import annotations

import ast as python_ast
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SKIP_DIRS: Final[frozenset[str]] = frozenset({
    ".venv", "venv", "__pycache__", ".git", "node_modules", ".egg-info",
    "target", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".tox", "vendor", ".next", ".nuxt",
})

LANGUAGE_EXTENSIONS: Final[dict[str, str]] = {
    ".py": "python",
    ".rs": "rust",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
}

DOC_EXTENSIONS: Final[frozenset[str]] = frozenset({".md", ".rst", ".txt", ".adoc"})

DIRECTIVE_FILES: Final[frozenset[str]] = frozenset({
    "CLAUDE.md", ".cursorrules", ".aider.conf.yml",
})

BUILD_CONFIGS: Final[frozenset[str]] = frozenset({
    "pyproject.toml", "Cargo.toml", "package.json", "Makefile",
    "docker-compose.yml", "Dockerfile",
})

DIRECTIVE_PATTERNS: Final[list[re.Pattern[str]]] = [
    re.compile(r"\bBANNED\b"),
    re.compile(r"\b[Nn]ever\s+\w+"),
    re.compile(r"\b[Aa]lways\s+\w+"),
    re.compile(r"\b[Mm]ust\s+not\b"),
    re.compile(r"\b[Dd]o\s+not\b"),
    re.compile(r"\b[Dd]on't\b"),
]

# AST builtins to exclude from call graph
_AST_BUILTINS: Final[frozenset[str]] = frozenset({
    "print", "len", "range", "enumerate", "zip", "map", "filter", "sorted",
    "reversed", "list", "dict", "set", "tuple", "str", "int", "float", "bool",
    "type", "isinstance", "issubclass", "hasattr", "getattr", "setattr",
    "delattr", "super", "property", "staticmethod", "classmethod", "abs",
    "min", "max", "sum", "any", "all", "next", "iter", "open", "repr", "hash",
    "id", "vars", "dir", "callable",
})

_MIN_SENTENCE_LEN: Final[int] = 20
_CO_CHANGE_MIN_WEIGHT: Final[int] = 3


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Node:
    """A node extracted from a project signal source."""
    id: str
    content: str
    node_type: str
    file: str | None = None
    date: str | None = None
    line: int | None = None


@dataclass
class Edge:
    """A directed edge between two nodes."""
    src: str
    tgt: str
    edge_type: str
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=lambda: dict[str, Any]())


@dataclass
class Manifest:
    """Detected project signals and capabilities."""
    root: Path
    name: str
    has_git: bool = False
    commit_count: int = 0
    file_counts: dict[str, int] = field(default_factory=lambda: dict[str, int]())
    total_files: int = 0
    languages: list[str] = field(default_factory=lambda: list[str]())
    doc_files: list[str] = field(default_factory=lambda: list[str]())
    doc_count: int = 0
    directives: list[str] = field(default_factory=lambda: list[str]())
    citation_regex: str | None = None
    has_tests: bool = False
    has_readme: bool = False
    build_configs: list[str] = field(default_factory=lambda: list[str]())


@dataclass
class ScanResult:
    """Complete result of scanning a project directory."""
    manifest: Manifest
    nodes: list[Node] = field(default_factory=lambda: list[Node]())
    edges: list[Edge] = field(default_factory=lambda: list[Edge]())
    timings: dict[str, float] = field(default_factory=lambda: dict[str, float]())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_git(project_root: Path, args: list[str]) -> str:
    """Run a git command in the project directory. Returns stdout or empty string on error."""
    try:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["git", "-C", str(project_root)] + args,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def _walk_files(project_root: Path) -> list[Path]:
    """Walk the project directory, skipping SKIP_DIRS. Returns relative paths."""
    files: list[Path] = []
    for item in project_root.rglob("*"):
        if not item.is_file():
            continue
        parts: tuple[str, ...] = item.relative_to(project_root).parts
        if any(p in SKIP_DIRS for p in parts):
            continue
        files.append(item.relative_to(project_root))
    return files


# ---------------------------------------------------------------------------
# Stage 1: Discover
# ---------------------------------------------------------------------------


def discover(project_root: Path) -> Manifest:
    """Auto-detect available signals in a project directory.

    Scans for: git history, file types, languages, docs, directives,
    citation patterns, tests, readme, build configs.
    """
    root: Path = project_root.resolve()
    manifest: Manifest = Manifest(root=root, name=root.name)

    # Git detection
    manifest.has_git = (root / ".git").is_dir()
    if manifest.has_git:
        count_str: str = _run_git(root, ["rev-list", "--count", "HEAD"]).strip()
        if count_str.isdigit():
            manifest.commit_count = int(count_str)

    # Walk files
    all_files: list[Path] = _walk_files(root)
    manifest.total_files = len(all_files)

    ext_counter: Counter[str] = Counter()
    lang_set: set[str] = set()

    for f in all_files:
        ext: str = f.suffix.lower()
        ext_counter[ext] += 1

        if ext in LANGUAGE_EXTENSIONS:
            lang_set.add(LANGUAGE_EXTENSIONS[ext])

        if ext in DOC_EXTENSIONS:
            manifest.doc_files.append(str(f))

        if f.name in DIRECTIVE_FILES:
            manifest.directives.append(str(f))

        if f.name in BUILD_CONFIGS:
            manifest.build_configs.append(str(f))

    manifest.file_counts = dict(ext_counter)
    manifest.languages = sorted(lang_set)
    manifest.doc_count = len(manifest.doc_files)

    # Test detection
    test_dirs: frozenset[str] = frozenset({"tests", "test", "spec", "specs"})
    manifest.has_tests = any((root / d).is_dir() for d in test_dirs)

    # README detection
    readme_names: list[str] = ["README.md", "README.rst", "README.txt", "README"]
    manifest.has_readme = any((root / r).exists() for r in readme_names)

    # Citation regex detection: sample first 10 markdown files
    citation_pattern: re.Pattern[str] = re.compile(r"\b[A-Z]{1,3}[-]?\d{3}\b")
    all_matches: list[str] = []
    for doc_path in manifest.doc_files[:10]:
        try:
            text: str = (root / doc_path).read_text(encoding="utf-8", errors="replace")
            all_matches.extend(citation_pattern.findall(text))
        except OSError:
            continue

    if len(all_matches) >= 3:
        prefix_counter: Counter[str] = Counter()
        for m in all_matches:
            prefix: str = re.sub(r"\d+$", "", m)
            prefix_counter[prefix] += 1
        most_common_prefix: str = prefix_counter.most_common(1)[0][0]
        manifest.citation_regex = rf"\b{re.escape(most_common_prefix)}\d{{3}}\b"

    return manifest


# ---------------------------------------------------------------------------
# Stage 2: Extractors
# ---------------------------------------------------------------------------


def extract_file_tree(project_root: Path) -> tuple[list[Node], list[Edge]]:
    """Extract file nodes and directory containment edges."""
    nodes: list[Node] = []
    edges: list[Edge] = []
    root: Path = project_root.resolve()

    for rel_path in _walk_files(root):
        file_id: str = f"file:{rel_path}"
        nodes.append(Node(
            id=file_id,
            content=rel_path.name,
            node_type="file",
            file=str(rel_path),
        ))

        parent: str = str(rel_path.parent)
        if parent != ".":
            dir_id: str = f"dir:{parent}"
            edges.append(Edge(src=dir_id, tgt=file_id, edge_type="CONTAINS"))

    return nodes, edges


def extract_git_history(
    project_root: Path,
    since_commit: str | None = None,
) -> tuple[list[Node], list[Edge]]:
    """Extract commit nodes and file-change edges from git log.

    Produces edge types: COMMIT_TOUCHES, CO_CHANGED, TEMPORAL_NEXT.
    Filters: merge commits, WIP commits, bulk commits (>50 files).

    If since_commit is provided, only extracts commits after that hash
    (for incremental onboarding).
    """
    root: Path = project_root.resolve()
    nodes: list[Node] = []
    edges: list[Edge] = []

    # Parse git log
    git_args: list[str] = ["log", "--format=COMMIT:%H|%s|%aI", "--name-only"]
    if since_commit:
        git_args.append(f"{since_commit}..HEAD")
    raw: str = _run_git(root, git_args)
    if not raw.strip():
        return nodes, edges

    # Parse into commits
    commits: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    skip_pattern: re.Pattern[str] = re.compile(
        r"^(wip|merge|reformat|lint|bump version|update lock)", re.IGNORECASE
    )

    for line in raw.splitlines():
        if line.startswith("COMMIT:"):
            if current is not None:
                commits.append(current)
            parts: list[str] = line[7:].split("|", 2)
            if len(parts) < 3:
                current = None
                continue
            current = {
                "hash": parts[0][:8],
                "message": parts[1],
                "date": parts[2],
                "files": [],
            }
        elif current is not None and line.strip():
            current["files"].append(line.strip())

    if current is not None:
        commits.append(current)

    # Filter
    filtered: list[dict[str, Any]] = []
    co_change_commits: list[dict[str, Any]] = []  # all commits for co-change analysis

    for c in commits:
        co_change_commits.append(c)
        if skip_pattern.match(c["message"]):
            continue
        if len(c["files"]) > 50:
            continue
        if len(c["files"]) == 0:
            continue
        filtered.append(c)

    # Create commit nodes and COMMIT_TOUCHES edges
    for c in filtered:
        commit_id: str = f"commit:{c['hash']}"
        nodes.append(Node(
            id=commit_id,
            content=c["message"],
            node_type="commit_belief",
            date=c["date"],
        ))
        for f in c["files"]:
            edges.append(Edge(
                src=commit_id,
                tgt=f"file:{f}",
                edge_type="COMMIT_TOUCHES",
            ))

    # CO_CHANGED edges (from all commits, including filtered ones)
    pair_counts: Counter[tuple[str, str]] = Counter()
    for c in co_change_commits:
        file_list: list[str] = sorted(c["files"])
        for i in range(len(file_list)):
            for j in range(i + 1, len(file_list)):
                pair: tuple[str, str] = (file_list[i], file_list[j])
                pair_counts[pair] += 1

    for (f_a, f_b), count in pair_counts.items():
        if count >= _CO_CHANGE_MIN_WEIGHT:
            edges.append(Edge(
                src=f"file:{f_a}",
                tgt=f"file:{f_b}",
                edge_type="CO_CHANGED",
                weight=float(count),
            ))

    # TEMPORAL_NEXT edges (chronological order)
    if len(filtered) >= 2:
        # git log returns newest first, reverse for chronological
        chronological: list[dict[str, Any]] = list(reversed(filtered))
        for i in range(len(chronological) - 1):
            edges.append(Edge(
                src=f"commit:{chronological[i]['hash']}",
                tgt=f"commit:{chronological[i + 1]['hash']}",
                edge_type="TEMPORAL_NEXT",
            ))

    return nodes, edges


def extract_document_sentences(
    project_root: Path,
    doc_files: list[str],
) -> tuple[list[Node], list[Edge]]:
    """Extract heading and sentence nodes from markdown/text docs.

    Produces edge types: SENTENCE_IN_FILE, WITHIN_SECTION.
    """
    root: Path = project_root.resolve()
    nodes: list[Node] = []
    edges: list[Edge] = []

    heading_pattern: re.Pattern[str] = re.compile(r"^#{1,6}\s+(.+)")
    code_fence: re.Pattern[str] = re.compile(r"^```")
    table_row: re.Pattern[str] = re.compile(r"^\s*\|")
    sentence_split: re.Pattern[str] = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

    for doc_path_str in doc_files:
        doc_path: Path = root / doc_path_str
        try:
            text: str = doc_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        file_id: str = f"file:{doc_path_str}"
        in_code_block: bool = False
        node_idx: int = 0
        prev_node_id: str | None = None

        for line in text.splitlines():
            # Track code fences
            if code_fence.match(line):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue

            # Skip tables and horizontal rules
            if table_row.match(line):
                continue
            if line.strip().startswith("---"):
                continue

            stripped: str = line.strip()
            if not stripped:
                continue

            # Check for heading
            heading_match: re.Match[str] | None = heading_pattern.match(stripped)
            if heading_match:
                heading_text: str = heading_match.group(1).strip()
                if len(heading_text) < _MIN_SENTENCE_LEN:
                    continue
                node_id: str = f"doc:{doc_path_str}:h:{node_idx}"
                node_idx += 1
                nodes.append(Node(
                    id=node_id,
                    content=heading_text,
                    node_type="heading",
                    file=doc_path_str,
                ))
                edges.append(Edge(src=node_id, tgt=file_id, edge_type="SENTENCE_IN_FILE"))
                if prev_node_id is not None:
                    edges.append(Edge(src=prev_node_id, tgt=node_id, edge_type="WITHIN_SECTION"))
                prev_node_id = node_id
                continue

            # Split into sentences
            sentences: list[str] = sentence_split.split(stripped)
            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) < _MIN_SENTENCE_LEN:
                    continue
                node_id = f"doc:{doc_path_str}:s:{node_idx}"
                node_idx += 1
                nodes.append(Node(
                    id=node_id,
                    content=sentence,
                    node_type="sentence",
                    file=doc_path_str,
                ))
                edges.append(Edge(src=node_id, tgt=file_id, edge_type="SENTENCE_IN_FILE"))
                if prev_node_id is not None:
                    edges.append(Edge(src=prev_node_id, tgt=node_id, edge_type="WITHIN_SECTION"))
                prev_node_id = node_id

    return nodes, edges


def extract_ast_calls(
    project_root: Path,
    languages: list[str],
) -> tuple[list[Node], list[Edge]]:
    """Extract function definitions and call edges from Python AST.

    Only operates on Python files. Produces edge type: CALLS.
    """
    if "python" not in languages:
        return [], []

    root: Path = project_root.resolve()
    nodes: list[Node] = []
    edges: list[Edge] = []

    py_files: list[Path] = [
        f for f in _walk_files(root) if f.suffix == ".py"
    ]

    for rel_path in py_files:
        full_path: Path = root / rel_path
        try:
            source: str = full_path.read_text(encoding="utf-8", errors="replace")
            tree: python_ast.Module = python_ast.parse(source)
        except (OSError, SyntaxError):
            continue

        # Module name from path
        module: str = str(rel_path).replace("/", ".").removesuffix(".py")

        # Collect function definitions
        defined_names: set[str] = set()
        for node in python_ast.walk(tree):
            if isinstance(node, (python_ast.FunctionDef, python_ast.AsyncFunctionDef)):
                func_id: str = f"func:{module}.{node.name}"
                defined_names.add(node.name)
                nodes.append(Node(
                    id=func_id,
                    content=f"def {node.name}",
                    node_type="callable",
                    file=str(rel_path),
                    line=node.lineno,
                ))

        # Collect calls (intra-file only, exclude builtins)
        for node in python_ast.walk(tree):
            if not isinstance(node, python_ast.Call):
                continue
            callee_name: str | None = None
            if isinstance(node.func, python_ast.Name):
                callee_name = node.func.id
            elif isinstance(node.func, python_ast.Attribute):
                callee_name = node.func.attr

            if callee_name is None:
                continue
            if callee_name in _AST_BUILTINS:
                continue
            if callee_name in defined_names:
                edges.append(Edge(
                    src=f"file:{rel_path}",
                    tgt=f"func:{module}.{callee_name}",
                    edge_type="CALLS",
                ))

    return nodes, edges


def extract_citations(
    project_root: Path,
    doc_files: list[str],
    citation_regex: str | None,
) -> list[Edge]:
    """Extract CITES edges between documents that share citation references."""
    if citation_regex is None:
        return []

    root: Path = project_root.resolve()
    pattern: re.Pattern[str] = re.compile(citation_regex)

    # Collect citations per file
    file_citations: dict[str, set[str]] = {}
    for doc_path_str in doc_files:
        try:
            text: str = (root / doc_path_str).read_text(encoding="utf-8", errors="replace")
            matches: list[str] = pattern.findall(text)
            if matches:
                file_citations[doc_path_str] = set(matches)
        except OSError:
            continue

    # Create edges between files sharing citations
    edges: list[Edge] = []
    file_list: list[str] = sorted(file_citations.keys())
    for i in range(len(file_list)):
        for j in range(i + 1, len(file_list)):
            shared: set[str] = file_citations[file_list[i]] & file_citations[file_list[j]]
            if shared:
                edges.append(Edge(
                    src=f"file:{file_list[i]}",
                    tgt=f"file:{file_list[j]}",
                    edge_type="CITES",
                    metadata={"shared": sorted(shared)},
                ))

    return edges


def extract_directives(
    project_root: Path,
    directive_files: list[str],
) -> list[Node]:
    """Extract behavioral belief nodes from directive files (CLAUDE.md, etc.)."""
    root: Path = project_root.resolve()
    nodes: list[Node] = []

    for df in directive_files:
        full_path: Path = root / df
        try:
            lines: list[str] = full_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except OSError:
            continue

        for line_num, line in enumerate(lines, 1):
            stripped: str = line.strip()
            if not stripped:
                continue
            for pat in DIRECTIVE_PATTERNS:
                if pat.search(stripped):
                    node_id: str = f"directive:{df}:{line_num}"
                    nodes.append(Node(
                        id=node_id,
                        content=stripped,
                        node_type="behavioral_belief",
                        file=df,
                        line=line_num,
                    ))
                    break  # one match per line is enough

    return nodes


# ---------------------------------------------------------------------------
# Stage 3: Orchestrator
# ---------------------------------------------------------------------------


def scan_project(
    project_root: str | Path,
    since_commit: str | None = None,
) -> ScanResult:
    """Scan a project directory and extract all available signals.

    This is the main entry point. It runs discover() to detect signals,
    then conditionally runs each extractor based on what's available.

    If since_commit is provided, git history extraction is limited to
    commits after that hash (incremental onboarding).

    Returns a ScanResult with manifest, nodes, and edges.
    """
    import time

    root: Path = Path(project_root).resolve()
    if not root.is_dir():
        msg: str = f"Not a directory: {root}"
        raise NotADirectoryError(msg)

    t0: float = time.monotonic()
    manifest: Manifest = discover(root)
    t_discover: float = time.monotonic() - t0

    all_nodes: list[Node] = []
    all_edges: list[Edge] = []
    timings: dict[str, float] = {"discover": t_discover}

    # File tree (always available)
    t: float = time.monotonic()
    file_nodes, file_edges = extract_file_tree(root)
    all_nodes.extend(file_nodes)
    all_edges.extend(file_edges)
    timings["file_tree"] = time.monotonic() - t

    # Git history
    if manifest.has_git and manifest.commit_count > 0:
        t = time.monotonic()
        git_nodes, git_edges = extract_git_history(root, since_commit=since_commit)
        all_nodes.extend(git_nodes)
        all_edges.extend(git_edges)
        timings["git_history"] = time.monotonic() - t

    # Document sentences
    if manifest.doc_count > 0:
        t = time.monotonic()
        doc_nodes, doc_edges = extract_document_sentences(root, manifest.doc_files)
        all_nodes.extend(doc_nodes)
        all_edges.extend(doc_edges)
        timings["documents"] = time.monotonic() - t

    # AST calls
    if manifest.languages:
        t = time.monotonic()
        ast_nodes, ast_edges = extract_ast_calls(root, manifest.languages)
        all_nodes.extend(ast_nodes)
        all_edges.extend(ast_edges)
        timings["ast_calls"] = time.monotonic() - t

    # Citations
    if manifest.citation_regex:
        t = time.monotonic()
        cite_edges: list[Edge] = extract_citations(
            root, manifest.doc_files, manifest.citation_regex
        )
        all_edges.extend(cite_edges)
        timings["citations"] = time.monotonic() - t

    # Directives
    if manifest.directives:
        t = time.monotonic()
        directive_nodes: list[Node] = extract_directives(root, manifest.directives)
        all_nodes.extend(directive_nodes)
        timings["directives"] = time.monotonic() - t

    return ScanResult(
        manifest=manifest,
        nodes=all_nodes,
        edges=all_edges,
        timings=timings,
    )
