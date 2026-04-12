"""
Experiment 49: Onboarding Pipeline Validation on Real Projects

Tests H1-H5 from ONBOARDING_RESEARCH.md by running the extractor pipeline on
3 projects of different archetypes and measuring what actually comes out.

Projects:
  - alpha-seek: rich code + rich docs (289 py, 552 commits, D### citations)
  - jose-bully: doc-only (0 code, 61 commits, 42 md files)
  - debserver: infrastructure (7 py, 538 commits, 24 md)

Measures:
  - Node and edge counts by type
  - Graph connectivity (largest connected component)
  - Edge type distribution
  - Manifest detection accuracy
  - Extraction time
"""

from __future__ import annotations

import ast as python_ast
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

# ============================================================
# Project paths
# ============================================================

PROJECTS: dict[str, Path] = {
    "alpha-seek": Path("/Users/thelorax/projects/alpha-seek"),
    "jose-bully": Path("/Users/thelorax/projects/jose-bully"),
    "debserver": Path("/Users/thelorax/projects/debserver"),
}

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "can", "could", "must", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "but", "and", "or", "not", "no", "so",
    "if", "then", "than", "this", "that", "these", "those", "it", "its",
}

SKIP_DIRS = {".venv", "__pycache__", ".git", "node_modules", ".egg-info",
             "target", ".mypy_cache", ".pytest_cache", "dist", "build"}


# ============================================================
# Stage 1: Discover (manifest)
# ============================================================

def discover(project_root: Path) -> dict[str, Any]:
    """Auto-detect available signals in a project directory."""
    manifest: dict[str, Any] = {"root": str(project_root), "name": project_root.name}

    # Git
    manifest["has_git"] = (project_root / ".git").is_dir()
    if manifest["has_git"]:
        import subprocess
        r = subprocess.run(["git", "rev-list", "--count", "HEAD"],
                           capture_output=True, text=True, cwd=project_root)
        manifest["commit_count"] = int(r.stdout.strip()) if r.returncode == 0 else 0
    else:
        manifest["commit_count"] = 0

    # File inventory
    file_counts: Counter[str] = Counter()
    all_files: list[Path] = []
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fp = Path(root) / f
            ext = fp.suffix.lower()
            file_counts[ext] += 1
            all_files.append(fp)

    manifest["file_counts"] = dict(file_counts)
    manifest["total_files"] = sum(file_counts.values())

    # Language detection
    languages: list[str] = []
    if file_counts.get(".py", 0) > 0:
        languages.append("python")
    if file_counts.get(".rs", 0) > 0:
        languages.append("rust")
    if file_counts.get(".ts", 0) > 0 or file_counts.get(".tsx", 0) > 0:
        languages.append("typescript")
    if file_counts.get(".js", 0) > 0 or file_counts.get(".jsx", 0) > 0:
        languages.append("javascript")
    if file_counts.get(".go", 0) > 0:
        languages.append("go")
    manifest["languages"] = languages

    # Docs
    doc_exts = {".md", ".rst", ".txt", ".adoc"}
    manifest["doc_files"] = [str(f.relative_to(project_root))
                             for f in all_files if f.suffix.lower() in doc_exts]
    manifest["doc_count"] = len(manifest["doc_files"])

    # Directives
    directive_files = ["CLAUDE.md", ".cursorrules", ".aider.conf.yml"]
    manifest["directives"] = [d for d in directive_files if (project_root / d).exists()]

    # Citation pattern probing
    citation_regex = None
    md_files = [f for f in all_files if f.suffix.lower() == ".md"]
    for mf in md_files[:10]:
        try:
            text = mf.read_text(encoding="utf-8", errors="ignore")[:5000]
            # Look for patterns like D001, REQ-001, M001, CS-001
            patterns_found = re.findall(r"\b[A-Z]{1,3}[-]?\d{3}\b", text)
            if len(patterns_found) >= 3:
                # Identify the most common prefix
                prefixes = Counter(re.match(r"[A-Z]{1,3}[-]?", p).group() for p in patterns_found  # type: ignore
                                   if re.match(r"[A-Z]{1,3}[-]?", p))
                if prefixes:
                    top_prefix = prefixes.most_common(1)[0][0]
                    citation_regex = rf"\b{re.escape(top_prefix)}\d{{3}}\b"
                    break
        except Exception:
            continue
    manifest["citation_regex"] = citation_regex

    # Test directory
    test_patterns = ["tests", "test", "spec", "specs"]
    manifest["has_tests"] = any((project_root / d).is_dir() for d in test_patterns)

    # README
    readme_files = ["README.md", "README.rst", "README.txt", "README"]
    manifest["has_readme"] = any((project_root / r).exists() for r in readme_files)

    # Build config
    build_files = {
        "pyproject.toml": "python",
        "Cargo.toml": "rust",
        "package.json": "node",
        "Makefile": "make",
        "docker-compose.yml": "docker",
        "Dockerfile": "docker",
    }
    manifest["build_configs"] = [f for f in build_files if (project_root / f).exists()]

    return manifest


# ============================================================
# Stage 2: Extract
# ============================================================

def extract_file_tree(project_root: Path) -> tuple[list[dict], list[dict]]:
    """Extract file tree nodes and CONTAINS edges."""
    nodes: list[dict] = []
    edges: list[dict] = []

    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel_dir = str(Path(root).relative_to(project_root))

        for f in files:
            fp = Path(root) / f
            rel = str(fp.relative_to(project_root))
            nodes.append({"id": f"file:{rel}", "content": f, "type": "file"})
            edges.append({"src": f"dir:{rel_dir}", "tgt": f"file:{rel}",
                          "type": "CONTAINS"})

    return nodes, edges


def extract_git_history(project_root: Path) -> tuple[list[dict], list[dict]]:
    """Extract COMMIT_BELIEF nodes and CO_CHANGED edges."""
    import subprocess
    r = subprocess.run(
        ["git", "log", "--name-only", "--format=COMMIT:%H|%s|%aI", "--no-merges"],
        capture_output=True, text=True, cwd=project_root,
    )

    nodes: list[dict] = []
    edges: list[dict] = []
    edges_raw: Counter[tuple[str, str]] = Counter()
    current_msg = ""
    current_date = ""
    current_hash = ""
    current_files: list[str] = []

    for line in r.stdout.strip().split("\n"):
        if line.startswith("COMMIT:"):
            # Process previous
            if current_files and current_msg:
                if not current_msg.lower().startswith(("merge", "wip")):
                    commit_id = f"commit:{current_hash[:8]}"
                    nodes.append({
                        "id": commit_id,
                        "content": current_msg,
                        "type": "commit_belief",
                        "date": current_date,
                    })
                    # COMMIT_TOUCHES: commit -> each file it modified
                    for cf in current_files:
                        edges.append({"src": commit_id, "tgt": f"file:{cf}",
                                      "type": "COMMIT_TOUCHES"})
                # Co-change
                for i, a in enumerate(current_files):
                    for b in current_files[i+1:]:
                        pair = tuple(sorted([a, b]))
                        edges_raw[pair] += 1

            parts = line[7:].split("|", 2)
            current_hash = parts[0]
            current_msg = parts[1] if len(parts) > 1 else ""
            current_date = parts[2] if len(parts) > 2 else ""
            current_files = []
        elif line.strip():
            current_files.append(line.strip())

    # Last commit
    if current_files and current_msg and not current_msg.lower().startswith(("merge", "wip")):
        commit_id = f"commit:{current_hash[:8]}"
        nodes.append({
            "id": commit_id,
            "content": current_msg,
            "type": "commit_belief",
            "date": current_date,
        })
        for cf in current_files:
            edges.append({"src": commit_id, "tgt": f"file:{cf}",
                          "type": "COMMIT_TOUCHES"})
        for i, a in enumerate(current_files):
            for b in current_files[i+1:]:
                pair = tuple(sorted([a, b]))
                edges_raw[pair] += 1

    # Threshold co-change edges and add to existing edges list
    for (a, b), weight in edges_raw.items():
        if weight >= 3:
            edges.append({"src": f"file:{a}", "tgt": f"file:{b}",
                          "type": "CO_CHANGED", "weight": weight})

    return nodes, edges


def extract_document_sentences(project_root: Path, doc_files: list[str]) -> tuple[list[dict], list[dict]]:
    """Split markdown docs into sentence-level nodes + cross-level edges."""
    nodes: list[dict] = []
    edges: list[dict] = []
    sent_pattern = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

    for rel_path in doc_files:
        fp = project_root / rel_path
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        # Track current section's sentence IDs for WITHIN_SECTION edges
        current_section_ids: list[str] = []
        file_node_id = f"file:{rel_path}"

        paragraphs = text.split("\n\n")
        sent_idx = 0
        for para in paragraphs:
            para = para.strip()
            if not para or para.startswith("```"):
                continue

            # Skip table rows and horizontal rules (high FP source)
            if para.startswith("|") or para.startswith("---"):
                continue

            if para.startswith("#"):
                # Heading starts a new section -- link previous section's sentences
                if len(current_section_ids) > 1:
                    for i_s in range(len(current_section_ids) - 1):
                        edges.append({"src": current_section_ids[i_s],
                                      "tgt": current_section_ids[i_s + 1],
                                      "type": "WITHIN_SECTION"})
                current_section_ids = []

                nid = f"doc:{rel_path}:h:{sent_idx}"
                nodes.append({
                    "id": nid,
                    "content": para.lstrip("#").strip(),
                    "type": "heading",
                    "file": rel_path,
                })
                # SENTENCE_IN_FILE: heading -> file
                edges.append({"src": nid, "tgt": file_node_id,
                              "type": "SENTENCE_IN_FILE"})
                current_section_ids.append(nid)
                sent_idx += 1
                continue

            sentences = sent_pattern.split(para)
            for sent in sentences:
                sent = sent.strip()
                if len(sent) > 20:
                    nid = f"doc:{rel_path}:s:{sent_idx}"
                    nodes.append({
                        "id": nid,
                        "content": sent,
                        "type": "sentence",
                        "file": rel_path,
                    })
                    # SENTENCE_IN_FILE: sentence -> file
                    edges.append({"src": nid, "tgt": file_node_id,
                                  "type": "SENTENCE_IN_FILE"})
                    current_section_ids.append(nid)
                    sent_idx += 1

        # Link last section's sentences
        if len(current_section_ids) > 1:
            for i_s in range(len(current_section_ids) - 1):
                edges.append({"src": current_section_ids[i_s],
                              "tgt": current_section_ids[i_s + 1],
                              "type": "WITHIN_SECTION"})

    return nodes, edges


def extract_ast_calls(project_root: Path, languages: list[str]) -> tuple[list[dict], list[dict]]:
    """Extract CALLS edges from Python AST. Returns (callable_nodes, call_edges)."""
    if "python" not in languages:
        return [], []

    BUILTINS = {
        "print", "len", "range", "enumerate", "zip", "map", "filter",
        "sorted", "reversed", "isinstance", "issubclass", "hasattr",
        "getattr", "setattr", "type", "super", "str", "int", "float",
        "bool", "list", "dict", "set", "tuple", "open", "abs", "min",
        "max", "sum", "any", "all", "next", "iter", "ValueError",
        "TypeError", "KeyError", "RuntimeError", "Exception",
    }

    nodes: list[dict] = []
    edges: list[dict] = []

    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if not f.endswith(".py"):
                continue
            fp = Path(root) / f
            try:
                source = fp.read_text(encoding="utf-8")
                tree = python_ast.parse(source)
            except Exception:
                continue

            rel = str(fp.relative_to(project_root))
            module = rel.replace("/", ".").replace(".py", "")

            # Extract function/method defs
            func_names: set[str] = set()
            for node in python_ast.walk(tree):
                if isinstance(node, (python_ast.FunctionDef, python_ast.AsyncFunctionDef)):
                    qname = f"{module}.{node.name}"
                    func_names.add(node.name)
                    nodes.append({
                        "id": f"func:{qname}",
                        "content": f"def {node.name}",
                        "type": "callable",
                        "file": rel,
                        "line": node.lineno,
                    })

            # Extract call sites (intra-file resolution only)
            for node in python_ast.walk(tree):
                if not isinstance(node, python_ast.Call):
                    continue
                callee = None
                if isinstance(node.func, python_ast.Name):
                    callee = node.func.id
                elif isinstance(node.func, python_ast.Attribute):
                    callee = node.func.attr

                if callee and callee in func_names and callee not in BUILTINS:
                    edges.append({
                        "src": f"file:{rel}",
                        "tgt": f"func:{module}.{callee}",
                        "type": "CALLS",
                    })

    return nodes, edges


def extract_citations(project_root: Path, doc_files: list[str],
                      citation_regex: str | None) -> list[dict]:
    """Extract CITES edges from citation patterns in documents."""
    if not citation_regex:
        return []

    pattern = re.compile(citation_regex)
    edges: list[dict] = []

    file_citations: dict[str, set[str]] = defaultdict(set)
    for rel_path in doc_files:
        fp = project_root / rel_path
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        matches = pattern.findall(text)
        for m in matches:
            file_citations[rel_path].add(m)

    # Build CITES edges between files referencing the same citation
    files = list(file_citations.keys())
    for i, a in enumerate(files):
        for b in files[i+1:]:
            shared = file_citations[a] & file_citations[b]
            if shared:
                edges.append({
                    "src": f"file:{a}", "tgt": f"file:{b}",
                    "type": "CITES", "shared": list(shared),
                })

    return edges


def extract_directives(project_root: Path, directive_files: list[str]) -> list[dict]:
    """Extract behavioral belief nodes from directive files."""
    nodes: list[dict] = []
    directive_patterns = [
        re.compile(r"\bBANNED\b"),
        re.compile(r"\b[Nn]ever\s+\w+"),
        re.compile(r"\b[Aa]lways\s+\w+"),
        re.compile(r"\b[Mm]ust\s+not\b"),
        re.compile(r"\b[Dd]o\s+not\b"),
        re.compile(r"\b[Dd]on't\b"),
    ]

    for df in directive_files:
        fp = project_root / df
        if not fp.exists():
            continue
        try:
            text = fp.read_text(encoding="utf-8")
        except Exception:
            continue

        for i, line in enumerate(text.split("\n")):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            for pat in directive_patterns:
                if pat.search(line):
                    nodes.append({
                        "id": f"directive:{df}:{i}",
                        "content": line,
                        "type": "behavioral_belief",
                        "file": df,
                    })
                    break

    return nodes


# ============================================================
# Stage 3: Analyze graph properties
# ============================================================

def analyze_graph(all_nodes: list[dict], all_edges: list[dict]) -> dict[str, Any]:
    """Compute graph properties: connectivity, degree distribution, etc."""
    # Build adjacency for connectivity analysis
    node_ids = {n["id"] for n in all_nodes}
    adjacency: dict[str, set[str]] = defaultdict(set)
    valid_edges = 0

    for e in all_edges:
        src, tgt = e["src"], e["tgt"]
        # Both endpoints should be known nodes (or at least one)
        adjacency[src].add(tgt)
        adjacency[tgt].add(src)
        valid_edges += 1

    # All nodes that appear in edges
    edge_nodes = set(adjacency.keys())
    all_graph_nodes = node_ids | edge_nodes

    # BFS for connected components
    visited: set[str] = set()
    components: list[int] = []

    for start in all_graph_nodes:
        if start in visited:
            continue
        # BFS
        queue = [start]
        component_size = 0
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            component_size += 1
            for neighbor in adjacency.get(node, set()):
                if neighbor not in visited:
                    queue.append(neighbor)
        components.append(component_size)

    # Add isolated nodes (no edges)
    isolated = len(all_graph_nodes) - len(visited)

    components.sort(reverse=True)
    total_nodes = len(all_graph_nodes)
    largest_component = components[0] if components else 0

    # Degree distribution
    degrees = [len(adjacency.get(n, set())) for n in all_graph_nodes]
    degree_counter = Counter(degrees)

    # Edge type distribution
    edge_types = Counter(e["type"] for e in all_edges)

    # Node type distribution
    node_types = Counter(n["type"] for n in all_nodes)

    return {
        "total_nodes": total_nodes,
        "total_edges": valid_edges,
        "node_types": dict(node_types),
        "edge_types": dict(edge_types),
        "num_components": len(components),
        "largest_component": largest_component,
        "largest_component_frac": round(largest_component / max(1, total_nodes), 3),
        "isolated_nodes": isolated,
        "degree_max": max(degrees) if degrees else 0,
        "degree_mean": round(np.mean(degrees), 2) if degrees else 0,
        "degree_median": round(float(np.median(degrees)), 1) if degrees else 0,
    }


# ============================================================
# FTS5 retrieval test
# ============================================================

def build_fts_from_nodes(nodes: list[dict]) -> sqlite3.Connection:
    """Build FTS5 index from extracted nodes."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE fts USING fts5(id, content, tokenize='porter')")
    for n in nodes:
        if n.get("content") and len(n["content"]) > 10:
            db.execute("INSERT INTO fts VALUES (?, ?)", (n["id"], n["content"]))
    db.commit()
    return db


def build_fts_from_raw_files(project_root: Path) -> sqlite3.Connection:
    """Build FTS5 index directly from raw files (baseline comparison)."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE fts USING fts5(id, content, tokenize='porter')")

    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fp = Path(root) / f
            if fp.suffix.lower() not in {".md", ".py", ".rs", ".ts", ".js", ".txt", ".toml", ".yml", ".yaml"}:
                continue
            try:
                content = fp.read_text(encoding="utf-8", errors="ignore")[:10000]
            except Exception:
                continue
            rel = str(fp.relative_to(project_root))
            db.execute("INSERT INTO fts VALUES (?, ?)", (rel, content))

    db.commit()
    return db


def search_fts(query: str, fts_db: sqlite3.Connection, top_k: int = 5) -> list[str]:
    terms = [t.strip() for t in query.split() if len(t.strip()) > 2]
    if not terms:
        return []
    fts_query = " OR ".join(terms)
    try:
        results = fts_db.execute(
            "SELECT id FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT ?",
            (fts_query, top_k)
        ).fetchall()
        return [str(r[0]) for r in results]
    except Exception:
        return []


# ============================================================
# Main
# ============================================================

def run_project(name: str, project_root: Path) -> dict[str, Any]:
    """Run full pipeline on one project."""
    result: dict[str, Any] = {"project": name}

    # Stage 1: Discover
    t0 = time.perf_counter()
    manifest = discover(project_root)
    result["discover_time"] = round(time.perf_counter() - t0, 3)
    result["manifest"] = {k: v for k, v in manifest.items() if k != "doc_files"}
    result["manifest"]["doc_count"] = manifest["doc_count"]

    # Stage 2: Extract
    all_nodes: list[dict] = []
    all_edges: list[dict] = []

    # file_tree (always)
    t0 = time.perf_counter()
    ft_nodes, ft_edges = extract_file_tree(project_root)
    all_nodes.extend(ft_nodes)
    all_edges.extend(ft_edges)
    result["file_tree_time"] = round(time.perf_counter() - t0, 3)

    # git_history
    if manifest["has_git"] and manifest["commit_count"] > 0:
        t0 = time.perf_counter()
        git_nodes, git_edges = extract_git_history(project_root)
        all_nodes.extend(git_nodes)
        all_edges.extend(git_edges)
        result["git_time"] = round(time.perf_counter() - t0, 3)
        result["commit_beliefs"] = len(git_nodes)
        result["co_changed_edges"] = len(git_edges)

    # document_sentences
    if manifest["doc_count"] > 0:
        t0 = time.perf_counter()
        doc_nodes, doc_edges = extract_document_sentences(project_root, manifest["doc_files"])
        all_nodes.extend(doc_nodes)
        all_edges.extend(doc_edges)
        result["doc_sentences_time"] = round(time.perf_counter() - t0, 3)
        result["doc_sentence_nodes"] = len(doc_nodes)
        result["doc_cross_edges"] = len(doc_edges)

    # ast_calls
    if manifest["languages"]:
        t0 = time.perf_counter()
        ast_nodes, ast_edges = extract_ast_calls(project_root, manifest["languages"])
        all_nodes.extend(ast_nodes)
        all_edges.extend(ast_edges)
        result["ast_time"] = round(time.perf_counter() - t0, 3)
        result["callable_nodes"] = len(ast_nodes)
        result["calls_edges"] = len(ast_edges)

    # citations
    if manifest["citation_regex"]:
        t0 = time.perf_counter()
        cite_edges = extract_citations(project_root, manifest["doc_files"],
                                       manifest["citation_regex"])
        all_edges.extend(cite_edges)
        result["citation_time"] = round(time.perf_counter() - t0, 3)
        result["citation_edges"] = len(cite_edges)
        result["citation_regex_detected"] = manifest["citation_regex"]

    # directives
    if manifest["directives"]:
        t0 = time.perf_counter()
        dir_nodes = extract_directives(project_root, manifest["directives"])
        all_nodes.extend(dir_nodes)
        result["directive_time"] = round(time.perf_counter() - t0, 3)
        result["directive_nodes"] = len(dir_nodes)

    # Stage 3: Analyze
    graph_props = analyze_graph(all_nodes, all_edges)
    result["graph"] = graph_props

    # Stage 4: Retrieval comparison (graph FTS5 vs raw file FTS5)
    graph_fts = build_fts_from_nodes(all_nodes)
    raw_fts = build_fts_from_raw_files(project_root)

    result["graph_fts_indexed"] = graph_fts.execute("SELECT COUNT(*) FROM fts").fetchone()[0]
    result["raw_fts_indexed"] = raw_fts.execute("SELECT COUNT(*) FROM fts").fetchone()[0]

    return result


def main() -> None:
    print("=" * 70, file=sys.stderr)
    print("Experiment 49: Onboarding Pipeline Validation", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    all_results: dict[str, Any] = {}

    for name, root in PROJECTS.items():
        print(f"\n{'='*50}", file=sys.stderr)
        print(f"Project: {name}", file=sys.stderr)
        print(f"{'='*50}", file=sys.stderr)

        result = run_project(name, root)
        all_results[name] = result

        # Print summary
        m = result["manifest"]
        g = result["graph"]

        print(f"\n  Manifest:", file=sys.stderr)
        print(f"    Git: {m.get('has_git')} ({m.get('commit_count', 0)} commits)", file=sys.stderr)
        print(f"    Languages: {m.get('languages', [])}", file=sys.stderr)
        print(f"    Docs: {m.get('doc_count', 0)} files", file=sys.stderr)
        print(f"    Directives: {m.get('directives', [])}", file=sys.stderr)
        print(f"    Citation regex: {m.get('citation_regex')}", file=sys.stderr)
        print(f"    Tests: {m.get('has_tests')}", file=sys.stderr)
        print(f"    Build configs: {m.get('build_configs', [])}", file=sys.stderr)

        print(f"\n  Extracted:", file=sys.stderr)
        print(f"    Commit beliefs: {result.get('commit_beliefs', 0)}", file=sys.stderr)
        print(f"    Doc sentence nodes: {result.get('doc_sentence_nodes', 0)}", file=sys.stderr)
        print(f"    Callable nodes: {result.get('callable_nodes', 0)}", file=sys.stderr)
        print(f"    Directive nodes: {result.get('directive_nodes', 0)}", file=sys.stderr)
        print(f"    CO_CHANGED edges: {result.get('co_changed_edges', 0)}", file=sys.stderr)
        print(f"    CALLS edges: {result.get('calls_edges', 0)}", file=sys.stderr)
        print(f"    Citation edges: {result.get('citation_edges', 0)}", file=sys.stderr)

        print(f"\n  Graph:", file=sys.stderr)
        print(f"    Total nodes: {g['total_nodes']}", file=sys.stderr)
        print(f"    Total edges: {g['total_edges']}", file=sys.stderr)
        print(f"    Components: {g['num_components']}", file=sys.stderr)
        print(f"    Largest component: {g['largest_component']} ({g['largest_component_frac']:.0%})", file=sys.stderr)
        print(f"    Degree: max={g['degree_max']}, mean={g['degree_mean']}, median={g['degree_median']}", file=sys.stderr)
        print(f"    Node types: {g['node_types']}", file=sys.stderr)
        print(f"    Edge types: {g['edge_types']}", file=sys.stderr)

        print(f"\n  FTS5 index:", file=sys.stderr)
        print(f"    Graph FTS5 docs: {result['graph_fts_indexed']}", file=sys.stderr)
        print(f"    Raw file FTS5 docs: {result['raw_fts_indexed']}", file=sys.stderr)

    # H1 check: connectivity
    print(f"\n{'='*70}", file=sys.stderr)
    print("HYPOTHESIS CHECKS", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)

    print(f"\nH1 (Graph connectivity: largest component > 50% for projects with >= 50 commits):", file=sys.stderr)
    for name, r in all_results.items():
        commits = r["manifest"].get("commit_count", 0)
        lc_frac = r["graph"]["largest_component_frac"]
        passes = "N/A" if commits < 50 else ("PASS" if lc_frac > 0.5 else "FAIL")
        print(f"  {name:<15} commits={commits:>5}  largest_component={lc_frac:.0%}  {passes}", file=sys.stderr)

    print(f"\nH4 (Manifest detection accuracy):", file=sys.stderr)
    for name, r in all_results.items():
        m = r["manifest"]
        print(f"  {name:<15} git={m['has_git']} langs={m['languages']} docs={m['doc_count']} "
              f"directives={m.get('directives',[])} citations={m.get('citation_regex','none')} "
              f"tests={m.get('has_tests')}", file=sys.stderr)

    # Summary comparison
    print(f"\n{'='*70}", file=sys.stderr)
    print(f"{'Project':<15} {'Nodes':>8} {'Edges':>8} {'Commit':>8} {'DocSent':>8} "
          f"{'Callable':>10} {'LCC%':>8} {'Components':>12}", file=sys.stderr)
    print("-" * 85, file=sys.stderr)
    for name, r in all_results.items():
        g = r["graph"]
        print(f"{name:<15} {g['total_nodes']:>8} {g['total_edges']:>8} "
              f"{r.get('commit_beliefs',0):>8} {r.get('doc_sentence_nodes',0):>8} "
              f"{r.get('callable_nodes',0):>10} {g['largest_component_frac']:>8.0%} "
              f"{g['num_components']:>12}", file=sys.stderr)

    # Save
    out = Path("experiments/exp49_results.json")
    out.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nResults saved to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
