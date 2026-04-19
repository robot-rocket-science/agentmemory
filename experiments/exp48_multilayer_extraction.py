"""Experiment 48: Multi-Layer Extraction + Retrieval at Scale

Tests whether multi-layer graph extraction (commits, files, sentences, AST,
citations, directives, temporal edges) improves retrieval over the 586-node
baseline from Exp 47.

Hypotheses:
  H1: At 2K+ nodes, FTS5 outperforms grep on coverage@15
  H2: Multi-layer edges increase HRR retrieval value
  H3: Temporal edges provide unique retrieval signal
  H4: 90%+ partitions remain within HRR capacity (~204 edges)
  H5: Extraction scales linearly with project size
  H6: Grep precision degrades at scale while FTS5 holds

Projects:
  - project-a: 552 commits, 393 files, 6-topic ground truth
  - project-b: 1,714 commits, 1,786 files
  - project-d: 538 commits, 183 files (Rust)
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Final, TypeAlias

import numpy as np
import numpy.typing as npt

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

NDArr: TypeAlias = npt.NDArray[np.floating[Any]]
NodeDict: TypeAlias = dict[str, dict[str, Any]]
EdgeList: TypeAlias = list[dict[str, Any]]
EdgeTriple: TypeAlias = tuple[str, str, str]

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DIM: Final[int] = 2048
HRR_THRESHOLD: Final[float] = 0.08
TOP_K: Final[int] = 15
RNG: Final[np.random.Generator] = np.random.default_rng(42)

project-a_DB: Final[Path] = Path(
    "/home/user/projects/.gsd/workflows/spikes/"
    "260406-1-associative-memory-for-gsd-please-explor/"
    "sandbox/project-a.db"
)

PROJECTS: Final[dict[str, Path]] = {
    "project-a": Path("/home/user/projects/project-a"),
    "project-b": Path("/home/user/projects/project-b"),
    "project-d": Path("/home/user/projects/project-d"),
}

SKIP_DIRS: Final[set[str]] = {
    ".venv",
    "__pycache__",
    ".git",
    "node_modules",
    ".egg-info",
    "target",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
}

STOPWORDS: Final[set[str]] = {
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
    "shall",
    "should",
    "may",
    "might",
    "can",
    "could",
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
    "during",
    "before",
    "after",
    "above",
    "below",
    "between",
    "but",
    "and",
    "or",
    "nor",
    "not",
    "no",
    "so",
    "if",
    "then",
    "than",
    "too",
    "very",
    "just",
    "about",
    "up",
    "out",
    "off",
    "over",
    "under",
    "again",
    "further",
    "once",
    "here",
    "there",
    "when",
    "where",
    "why",
    "how",
    "all",
    "each",
    "every",
    "both",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "only",
    "own",
    "same",
    "that",
    "this",
    "these",
    "those",
    "what",
    "which",
    "who",
    "whom",
    "it",
    "its",
    "he",
    "she",
    "they",
    "them",
    "his",
    "her",
    "their",
    "we",
    "us",
    "our",
    "you",
    "your",
    "i",
    "me",
    "my",
}

BEHAVIORAL_DECISIONS: Final[list[str]] = ["D157", "D188", "D100", "D073"]

TOPICS: Final[dict[str, dict[str, Any]]] = {
    "dispatch_gate": {
        "query": "dispatch gate deploy protocol",
        "needed": ["D089", "D106", "D137"],
    },
    "calls_puts": {
        "query": "calls puts equal citizens",
        "needed": ["D073", "D096", "D100"],
    },
    "capital_5k": {
        "query": "starting capital bankroll",
        "needed": ["D099"],
    },
    "agent_behavior": {
        "query": "agent behavior instructions",
        "needed": ["D157", "D188"],
    },
    "strict_typing": {
        "query": "typing pyright strict",
        "needed": ["D071", "D113"],
    },
    "gcp_primary": {
        "query": "GCP primary compute platform",
        "needed": ["D078", "D120"],
    },
}


# ===================================================================
# HRR Core
# ===================================================================


def make_vec(dim: int) -> NDArr:
    """Unit-norm random vector in R^dim."""
    v: NDArr = RNG.standard_normal(dim).astype(np.float64)
    norm: float = float(np.linalg.norm(v))
    if norm < 1e-10:
        v[0] = 1.0
        return v
    return (v / norm).astype(np.float64)


def bind(a: NDArr, b: NDArr) -> NDArr:
    """Circular convolution via FFT."""
    return np.real(np.fft.ifft(np.fft.fft(a) * np.fft.fft(b))).astype(np.float64)


def unbind(key: NDArr, superposition: NDArr) -> NDArr:
    """Circular correlation (approximate inverse of bind) via FFT."""
    return np.real(
        np.fft.ifft(np.conj(np.fft.fft(key)) * np.fft.fft(superposition))
    ).astype(np.float64)


def cos_sim(a: NDArr, b: NDArr) -> float:
    """Cosine similarity, safe for zero vectors."""
    na: float = float(np.linalg.norm(a))
    nb: float = float(np.linalg.norm(b))
    if na < 1e-10 or nb < 1e-10:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# ===================================================================
# HRR Graph with decision-neighborhood partitioning
# ===================================================================


class HRRGraph:
    """HRR-encoded partitioned graph for multi-layer edges."""

    def __init__(self, dim: int) -> None:
        self.dim: int = dim
        self.node_vecs: dict[str, NDArr] = {}
        self.edge_type_vecs: dict[str, NDArr] = {}
        self.partitions: dict[str, NDArr] = {}
        self.node_to_partitions: dict[str, set[str]] = defaultdict(set)
        self.partition_edge_counts: dict[str, int] = {}

    def _ensure_node(self, nid: str) -> None:
        if nid not in self.node_vecs:
            self.node_vecs[nid] = make_vec(self.dim)

    def _ensure_edge_type(self, etype: str) -> None:
        if etype not in self.edge_type_vecs:
            self.edge_type_vecs[etype] = make_vec(self.dim)

    def encode_partition(self, partition_id: str, edges: list[EdgeTriple]) -> None:
        """Encode edges into a superposition vector."""
        s_vec: NDArr = np.zeros(self.dim, dtype=np.float64)
        for src, dst, etype in edges:
            self._ensure_node(src)
            self._ensure_node(dst)
            self._ensure_edge_type(etype)
            bound: NDArr = bind(
                bind(self.node_vecs[src], self.edge_type_vecs[etype]),
                self.node_vecs[dst],
            )
            s_vec = s_vec + bound
            self.node_to_partitions[src].add(partition_id)
            self.node_to_partitions[dst].add(partition_id)
        self.partitions[partition_id] = s_vec
        self.partition_edge_counts[partition_id] = len(edges)

    def query_single_hop(
        self,
        source: str,
        edge_type: str,
        top_k: int = 10,
        threshold: float = 0.0,
    ) -> list[tuple[str, float]]:
        """Single-hop typed query: source -[edge_type]-> ?"""
        if source not in self.node_vecs:
            return []
        if edge_type not in self.edge_type_vecs:
            return []

        pids: list[str] = sorted(self.node_to_partitions.get(source, set()))
        if not pids:
            return []

        all_scores: dict[str, float] = {}
        q_vec: NDArr = bind(self.node_vecs[source], self.edge_type_vecs[edge_type])

        for pid in pids:
            s_vec: NDArr = self.partitions[pid]
            result: NDArr = unbind(q_vec, s_vec)

            for nid in self.node_vecs:
                if nid == source:
                    continue
                if pid not in self.node_to_partitions.get(nid, set()):
                    continue
                sim: float = cos_sim(result, self.node_vecs[nid])
                if sim >= threshold:
                    if nid not in all_scores or sim > all_scores[nid]:
                        all_scores[nid] = sim

        ranked: list[tuple[str, float]] = sorted(
            all_scores.items(), key=lambda x: x[1], reverse=True
        )
        return ranked[:top_k]


# ===================================================================
# Spike DB loader (project-a 586 belief nodes)
# ===================================================================


def load_spike_nodes() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load all active nodes and edges from the project-a spike DB."""
    db: sqlite3.Connection = sqlite3.connect(str(project-a_DB))
    nodes: list[dict[str, Any]] = []
    for row in db.execute(
        "SELECT id, content, category FROM mem_nodes WHERE superseded_by IS NULL"
    ):
        nodes.append(
            {
                "id": str(row[0]),
                "content": str(row[1]),
                "type": "belief",
                "category": str(row[2]),
            }
        )

    edges: list[dict[str, Any]] = []
    for row in db.execute("SELECT from_id, to_id, edge_type, weight FROM mem_edges"):
        edges.append(
            {
                "src": str(row[0]),
                "tgt": str(row[1]),
                "type": str(row[2]),
                "weight": float(row[3]),
            }
        )
    db.close()
    return nodes, edges


# ===================================================================
# Extractors (adapted from Exp 45)
# ===================================================================


def discover(project_root: Path) -> dict[str, Any]:
    """Auto-detect available signals in a project directory."""
    manifest: dict[str, Any] = {"root": str(project_root), "name": project_root.name}

    manifest["has_git"] = (project_root / ".git").is_dir()
    if manifest["has_git"]:
        r: subprocess.CompletedProcess[str] = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        manifest["commit_count"] = int(r.stdout.strip()) if r.returncode == 0 else 0
    else:
        manifest["commit_count"] = 0

    file_counts: Counter[str] = Counter()
    all_files: list[Path] = []
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fp: Path = Path(root) / f
            ext: str = fp.suffix.lower()
            file_counts[ext] += 1
            all_files.append(fp)

    manifest["file_counts"] = dict(file_counts)
    manifest["total_files"] = sum(file_counts.values())

    languages: list[str] = []
    if file_counts.get(".py", 0) > 0:
        languages.append("python")
    if file_counts.get(".rs", 0) > 0:
        languages.append("rust")
    if file_counts.get(".ts", 0) > 0 or file_counts.get(".tsx", 0) > 0:
        languages.append("typescript")
    if file_counts.get(".js", 0) > 0 or file_counts.get(".jsx", 0) > 0:
        languages.append("javascript")
    manifest["languages"] = languages

    doc_exts: set[str] = {".md", ".rst", ".txt", ".adoc"}
    manifest["doc_files"] = [
        str(f.relative_to(project_root))
        for f in all_files
        if f.suffix.lower() in doc_exts
    ]
    manifest["doc_count"] = len(manifest["doc_files"])

    directive_files: list[str] = ["CLAUDE.md", ".cursorrules", ".aider.conf.yml"]
    manifest["directives"] = [d for d in directive_files if (project_root / d).exists()]

    citation_regex: str | None = None
    md_files: list[Path] = [f for f in all_files if f.suffix.lower() == ".md"]
    for mf in md_files[:10]:
        try:
            text: str = mf.read_text(encoding="utf-8", errors="ignore")[:5000]
            patterns_found: list[str] = re.findall(r"\b[A-Z]{1,3}[-]?\d{3}\b", text)
            if len(patterns_found) >= 3:
                prefixes: Counter[str] = Counter()
                for pf in patterns_found:
                    pm: re.Match[str] | None = re.match(r"[A-Z]{1,3}[-]?", pf)
                    if pm:
                        prefixes[pm.group()] += 1
                if prefixes:
                    top_prefix: str = prefixes.most_common(1)[0][0]
                    citation_regex = rf"\b{re.escape(top_prefix)}\d{{3}}\b"
                    break
        except Exception:
            continue
    manifest["citation_regex"] = citation_regex

    return manifest


def extract_file_tree(
    project_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract file tree nodes and CONTAINS edges."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel_dir: str = str(Path(root).relative_to(project_root))

        for f in files:
            fp: Path = Path(root) / f
            rel: str = str(fp.relative_to(project_root))
            nodes.append({"id": f"file:{rel}", "content": f, "type": "file"})
            edges.append(
                {
                    "src": f"dir:{rel_dir}",
                    "tgt": f"file:{rel}",
                    "type": "CONTAINS",
                }
            )

    return nodes, edges


def extract_git_history(
    project_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract commit nodes + COMMIT_TOUCHES + CO_CHANGED + TEMPORAL_NEXT edges."""
    r: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "log", "--name-only", "--format=COMMIT:%H|%s|%aI", "--no-merges"],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    co_change_raw: Counter[tuple[str, str]] = Counter()

    # Ordered list of commit IDs for temporal edges
    commit_order: list[str] = []
    commit_dates: dict[str, str] = {}

    current_msg: str = ""
    current_date: str = ""
    current_hash: str = ""
    current_files: list[str] = []

    def flush_commit() -> None:
        nonlocal current_msg, current_date, current_hash, current_files
        if current_files and current_msg:
            if not current_msg.lower().startswith(("merge", "wip")):
                commit_id: str = f"commit:{current_hash[:8]}"
                nodes.append(
                    {
                        "id": commit_id,
                        "content": current_msg,
                        "type": "commit",
                        "date": current_date,
                    }
                )
                commit_order.append(commit_id)
                commit_dates[commit_id] = current_date
                for cf in current_files:
                    edges.append(
                        {
                            "src": commit_id,
                            "tgt": f"file:{cf}",
                            "type": "COMMIT_TOUCHES",
                        }
                    )
            # Co-change regardless of merge/wip
            for i_f, a in enumerate(current_files):
                for b in current_files[i_f + 1 :]:
                    pair: tuple[str, str] = tuple(sorted([a, b]))  # type: ignore[assignment]
                    co_change_raw[pair] += 1
        current_msg = ""
        current_date = ""
        current_hash = ""
        current_files = []

    for line in r.stdout.strip().split("\n"):
        if line.startswith("COMMIT:"):
            flush_commit()
            parts: list[str] = line[7:].split("|", 2)
            current_hash = parts[0]
            current_msg = parts[1] if len(parts) > 1 else ""
            current_date = parts[2] if len(parts) > 2 else ""
            current_files = []
        elif line.strip():
            current_files.append(line.strip())

    flush_commit()

    # CO_CHANGED edges (weight >= 3)
    for (a, b), weight in co_change_raw.items():
        if weight >= 3:
            edges.append(
                {
                    "src": f"file:{a}",
                    "tgt": f"file:{b}",
                    "type": "CO_CHANGED",
                    "weight": weight,
                }
            )

    # TEMPORAL_NEXT edges: git log returns newest first, so reverse
    commit_order.reverse()
    for i_c in range(len(commit_order) - 1):
        edges.append(
            {
                "src": commit_order[i_c],
                "tgt": commit_order[i_c + 1],
                "type": "TEMPORAL_NEXT",
            }
        )

    return nodes, edges


def extract_document_sentences(
    project_root: Path,
    doc_files: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split markdown docs into sentence-level nodes + cross-level edges."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    sent_pattern: re.Pattern[str] = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

    for rel_path in doc_files:
        fp: Path = project_root / rel_path
        try:
            text: str = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        current_section_ids: list[str] = []
        file_node_id: str = f"file:{rel_path}"

        paragraphs: list[str] = text.split("\n\n")
        sent_idx: int = 0
        for para in paragraphs:
            para = para.strip()
            if not para or para.startswith("```"):
                continue
            if para.startswith("|") or para.startswith("---"):
                continue

            if para.startswith("#"):
                if len(current_section_ids) > 1:
                    for i_s in range(len(current_section_ids) - 1):
                        edges.append(
                            {
                                "src": current_section_ids[i_s],
                                "tgt": current_section_ids[i_s + 1],
                                "type": "WITHIN_SECTION",
                            }
                        )
                current_section_ids = []

                nid: str = f"doc:{rel_path}:h:{sent_idx}"
                nodes.append(
                    {
                        "id": nid,
                        "content": para.lstrip("#").strip(),
                        "type": "heading",
                        "file": rel_path,
                    }
                )
                edges.append(
                    {
                        "src": nid,
                        "tgt": file_node_id,
                        "type": "SENTENCE_IN_FILE",
                    }
                )
                current_section_ids.append(nid)
                sent_idx += 1
                continue

            sentences: list[str] = sent_pattern.split(para)
            for sent in sentences:
                sent = sent.strip()
                if len(sent) > 20:
                    nid = f"doc:{rel_path}:s:{sent_idx}"
                    nodes.append(
                        {
                            "id": nid,
                            "content": sent,
                            "type": "sentence",
                            "file": rel_path,
                        }
                    )
                    edges.append(
                        {
                            "src": nid,
                            "tgt": file_node_id,
                            "type": "SENTENCE_IN_FILE",
                        }
                    )
                    current_section_ids.append(nid)
                    sent_idx += 1

        if len(current_section_ids) > 1:
            for i_s in range(len(current_section_ids) - 1):
                edges.append(
                    {
                        "src": current_section_ids[i_s],
                        "tgt": current_section_ids[i_s + 1],
                        "type": "WITHIN_SECTION",
                    }
                )

    return nodes, edges


def extract_ast_calls(
    project_root: Path,
    languages: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract callable nodes and CALLS edges from Python AST."""
    import ast as python_ast

    if "python" not in languages:
        return [], []

    builtins: set[str] = {
        "print",
        "len",
        "range",
        "enumerate",
        "zip",
        "map",
        "filter",
        "sorted",
        "reversed",
        "isinstance",
        "issubclass",
        "hasattr",
        "getattr",
        "setattr",
        "type",
        "super",
        "str",
        "int",
        "float",
        "bool",
        "list",
        "dict",
        "set",
        "tuple",
        "open",
        "abs",
        "min",
        "max",
        "sum",
        "any",
        "all",
        "next",
        "iter",
        "ValueError",
        "TypeError",
        "KeyError",
        "RuntimeError",
        "Exception",
    }

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if not f.endswith(".py"):
                continue
            fp: Path = Path(root) / f
            try:
                source: str = fp.read_text(encoding="utf-8")
                tree: python_ast.Module = python_ast.parse(source)
            except Exception:
                continue

            rel: str = str(fp.relative_to(project_root))
            module: str = rel.replace("/", ".").replace(".py", "")

            func_names: set[str] = set()
            for node in python_ast.walk(tree):
                if isinstance(
                    node, (python_ast.FunctionDef, python_ast.AsyncFunctionDef)
                ):
                    qname: str = f"{module}.{node.name}"
                    func_names.add(node.name)
                    nodes.append(
                        {
                            "id": f"func:{qname}",
                            "content": f"def {node.name}",
                            "type": "callable",
                            "file": rel,
                            "line": node.lineno,
                        }
                    )

            for node in python_ast.walk(tree):
                if not isinstance(node, python_ast.Call):
                    continue
                callee: str | None = None
                if isinstance(node.func, python_ast.Name):
                    callee = node.func.id
                elif isinstance(node.func, python_ast.Attribute):
                    callee = node.func.attr

                if callee and callee in func_names and callee not in builtins:
                    edges.append(
                        {
                            "src": f"file:{rel}",
                            "tgt": f"func:{module}.{callee}",
                            "type": "CALLS",
                        }
                    )

    return nodes, edges


def extract_citations(
    project_root: Path,
    doc_files: list[str],
    citation_regex: str | None,
) -> list[dict[str, Any]]:
    """Extract CITES edges from citation patterns in documents."""
    if not citation_regex:
        return []

    pattern: re.Pattern[str] = re.compile(citation_regex)
    file_citations: dict[str, set[str]] = defaultdict(set)
    edges: list[dict[str, Any]] = []

    for rel_path in doc_files:
        fp: Path = project_root / rel_path
        try:
            text: str = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        matches: list[str] = pattern.findall(text)
        for m in matches:
            file_citations[rel_path].add(m)

    files_list: list[str] = list(file_citations.keys())
    for i_f, a in enumerate(files_list):
        for b in files_list[i_f + 1 :]:
            shared: set[str] = file_citations[a] & file_citations[b]
            if shared:
                edges.append(
                    {
                        "src": f"file:{a}",
                        "tgt": f"file:{b}",
                        "type": "CITES",
                        "shared": sorted(shared),
                    }
                )

    return edges


def extract_directives(
    project_root: Path,
    directive_files: list[str],
) -> list[dict[str, Any]]:
    """Extract behavioral belief nodes from directive files."""
    nodes: list[dict[str, Any]] = []
    directive_patterns: list[re.Pattern[str]] = [
        re.compile(r"\bBANNED\b"),
        re.compile(r"\b[Nn]ever\s+\w+"),
        re.compile(r"\b[Aa]lways\s+\w+"),
        re.compile(r"\b[Mm]ust\s+not\b"),
        re.compile(r"\b[Dd]o\s+not\b"),
        re.compile(r"\b[Dd]on't\b"),
    ]

    for df in directive_files:
        fp: Path = project_root / df
        if not fp.exists():
            continue
        try:
            text: str = fp.read_text(encoding="utf-8")
        except Exception:
            continue

        for i_l, line in enumerate(text.split("\n")):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            for pat in directive_patterns:
                if pat.search(line):
                    nodes.append(
                        {
                            "id": f"directive:{df}:{i_l}",
                            "content": line,
                            "type": "behavioral_belief",
                            "file": df,
                        }
                    )
                    break

    return nodes


# ===================================================================
# Graph analysis
# ===================================================================


def analyze_graph(
    all_nodes: list[dict[str, Any]],
    all_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute graph connectivity, degree distribution, type counts."""
    node_ids: set[str] = {n["id"] for n in all_nodes}
    adjacency: dict[str, set[str]] = defaultdict(set)

    for e in all_edges:
        src: str = e["src"]
        tgt: str = e["tgt"]
        adjacency[src].add(tgt)
        adjacency[tgt].add(src)

    all_graph_nodes: set[str] = node_ids | set(adjacency.keys())

    # BFS for connected components
    visited: set[str] = set()
    components: list[int] = []
    for start in all_graph_nodes:
        if start in visited:
            continue
        queue: list[str] = [start]
        component_size: int = 0
        while queue:
            node: str = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            component_size += 1
            for neighbor in adjacency.get(node, set()):
                if neighbor not in visited:
                    queue.append(neighbor)
        components.append(component_size)

    components.sort(reverse=True)
    total_nodes: int = len(all_graph_nodes)
    largest_component: int = components[0] if components else 0

    degrees: list[int] = [len(adjacency.get(n, set())) for n in all_graph_nodes]
    edge_types: Counter[str] = Counter(e["type"] for e in all_edges)
    node_types: Counter[str] = Counter(n["type"] for n in all_nodes)

    return {
        "total_nodes": total_nodes,
        "total_edges": len(all_edges),
        "node_types": dict(node_types),
        "edge_types": dict(edge_types),
        "num_components": len(components),
        "largest_component": largest_component,
        "largest_component_frac": round(largest_component / max(1, total_nodes), 3),
        "degree_max": max(degrees) if degrees else 0,
        "degree_mean": round(float(np.mean(degrees)), 2) if degrees else 0.0,
        "degree_median": round(float(np.median(degrees)), 1) if degrees else 0.0,
    }


# ===================================================================
# Retrieval methods
# ===================================================================


def build_fts(nodes: list[dict[str, Any]]) -> sqlite3.Connection:
    """Build in-memory FTS5 index with porter stemming from node list."""
    db: sqlite3.Connection = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE fts USING fts5(id, content, tokenize='porter')")
    for n in nodes:
        content: str = str(n.get("content", ""))
        if len(content) > 10:
            db.execute("INSERT INTO fts VALUES (?, ?)", (n["id"], content))
    db.commit()
    return db


def search_fts(
    query: str,
    fts_db: sqlite3.Connection,
    top_k: int = TOP_K,
) -> list[tuple[str, float]]:
    """FTS5 search with OR terms. Returns (node_id, bm25_score)."""
    terms: list[str] = [t.strip() for t in query.split() if len(t.strip()) > 2]
    if not terms:
        return []
    fts_query: str = " OR ".join(terms)
    try:
        results: list[tuple[str, float]] = [
            (str(r[0]), float(r[1]))
            for r in fts_db.execute(
                "SELECT id, bm25(fts) FROM fts WHERE fts MATCH ? "
                "ORDER BY bm25(fts) LIMIT ?",
                (fts_query, top_k),
            ).fetchall()
        ]
        return results
    except Exception:
        return []


def grep_search(
    query: str,
    nodes: dict[str, str],
    top_k: int = TOP_K,
) -> list[tuple[str, float]]:
    """Case-insensitive grep ranked by term frequency."""
    query_terms: list[str] = [t.lower() for t in query.split() if len(t) >= 2]
    scores: list[tuple[str, float]] = []

    for nid, content in nodes.items():
        content_lower: str = content.lower()
        match_count: int = 0
        for term in query_terms:
            match_count += len(re.findall(re.escape(term), content_lower))
        if match_count > 0:
            scores.append((nid, float(match_count)))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_k]


def extract_decision_id(node_id: str) -> str | None:
    """Extract D### from a node ID like D097_s3 or commit:abc that mentions D097."""
    m: re.Match[str] | None = re.match(r"(D\d{3})", node_id)
    return m.group(1) if m else None


def estimate_tokens(text: str) -> int:
    """Rough token estimate: chars / 4."""
    return max(1, len(text) // 4)


# ===================================================================
# Partition builder for multi-layer HRR
# ===================================================================


def assign_node_to_decision(
    node_id: str,
    edge_index: dict[str, set[str]],
    node_content: dict[str, str],
) -> str | None:
    """Map a non-decision node to its decision ID via edges or content.

    For commit/file/sentence nodes, check:
    1. Does the node ID start with D###?
    2. Does the node connect to a D### node via any edge?
    3. Does the node content mention D###?
    Falls back to None if no decision association found.
    """
    # Direct decision ID in node ID
    did: str | None = extract_decision_id(node_id)
    if did is not None:
        return did

    # Check neighbors for decision IDs
    for neighbor in edge_index.get(node_id, set()):
        did = extract_decision_id(neighbor)
        if did is not None:
            return did

    # Check content for D### references
    content: str = node_content.get(node_id, "")
    d_refs: list[str] = re.findall(r"\bD(\d{3})\b", content)
    if d_refs:
        return f"D{d_refs[0]}"

    return None


def build_partitions(
    all_edges: list[dict[str, Any]],
    node_content: dict[str, str],
) -> dict[str, list[EdgeTriple]]:
    """Decision-neighborhood partitioning for multi-layer edges.

    Assigns each edge to the partition of the source node's decision.
    Non-decision nodes are assigned to the decision they connect to.
    Remaining unassigned edges go to 'misc' partitions (chunked).
    """
    # Build edge index for neighbor lookups
    edge_index: dict[str, set[str]] = defaultdict(set)
    for e in all_edges:
        edge_index[e["src"]].add(e["tgt"])
        edge_index[e["tgt"]].add(e["src"])

    # Assign edges to decision partitions
    by_decision: dict[str, list[EdgeTriple]] = defaultdict(list)
    unassigned: list[EdgeTriple] = []

    for e in all_edges:
        src: str = e["src"]
        tgt: str = e["tgt"]
        etype: str = e["type"]

        # Try to assign based on source, then target
        decision: str | None = assign_node_to_decision(src, edge_index, node_content)
        if decision is None:
            decision = assign_node_to_decision(tgt, edge_index, node_content)

        if decision is not None:
            by_decision[decision].append((src, tgt, etype))
        else:
            unassigned.append((src, tgt, etype))

    # Merge small partitions, chunk large ones
    partitions: dict[str, list[EdgeTriple]] = {}
    merge_buf: list[EdgeTriple] = []
    merge_idx: int = 0

    for did in sorted(by_decision.keys()):
        edges_for_d: list[EdgeTriple] = by_decision[did]
        if len(edges_for_d) > 200:
            # Too large for one partition -- chunk it
            for chunk_start in range(0, len(edges_for_d), 150):
                chunk: list[EdgeTriple] = edges_for_d[chunk_start : chunk_start + 150]
                partitions[f"dec_{did}_{chunk_start}"] = chunk
        elif len(edges_for_d) < 10:
            # Too small -- merge with buffer
            merge_buf.extend(edges_for_d)
            if len(merge_buf) >= 50:
                partitions[f"merged_{merge_idx}"] = list(merge_buf)
                merge_buf = []
                merge_idx += 1
        else:
            partitions[f"dec_{did}"] = edges_for_d

    if merge_buf:
        partitions[f"merged_{merge_idx}"] = merge_buf

    # Unassigned edges in chunks
    for chunk_start in range(0, len(unassigned), 150):
        chunk = unassigned[chunk_start : chunk_start + 150]
        partitions[f"misc_{chunk_start}"] = chunk

    return partitions


# ===================================================================
# Evaluation
# ===================================================================


def evaluate_method(
    method_name: str,
    results: list[tuple[str, float]],
    needed_decisions: list[str],
    node_content: dict[str, str],
) -> dict[str, Any]:
    """Evaluate a retrieval method against ground truth."""
    needed: set[str] = set(needed_decisions)
    found_decisions: set[str] = set()
    first_relevant_rank: int | None = None
    total_tokens: int = 0
    relevant_count: int = 0

    for rank, (nid, _score) in enumerate(results):
        did: str | None = extract_decision_id(nid)
        content: str = node_content.get(nid, "")
        total_tokens += estimate_tokens(content)

        if did and did in needed:
            found_decisions.add(did)
            relevant_count += 1
            if first_relevant_rank is None:
                first_relevant_rank = rank + 1

    coverage: float = len(found_decisions) / len(needed) if needed else 0.0
    precision: float = relevant_count / len(results) if results else 0.0
    mrr: float = 1.0 / first_relevant_rank if first_relevant_rank else 0.0

    return {
        "method": method_name,
        "result_count": len(results),
        "found": sorted(found_decisions),
        "missed": sorted(needed - found_decisions),
        "coverage": round(coverage, 3),
        "tokens": total_tokens,
        "precision": round(precision, 3),
        "mrr": round(mrr, 3),
    }


# ===================================================================
# Temporal edge analysis (H3)
# ===================================================================


def find_temporal_unique_paths(
    all_edges: list[dict[str, Any]],
    node_content: dict[str, str],
    topics: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """For each topic, check if any needed decision is reachable via
    temporal paths (TEMPORAL_NEXT -> COMMIT_TOUCHES) but NOT via CITES/CALLS."""
    # Build typed adjacency
    temporal_adj: dict[str, set[str]] = defaultdict(set)
    commit_touches_adj: dict[str, set[str]] = defaultdict(set)
    non_temporal_adj: dict[str, set[str]] = defaultdict(set)

    for e in all_edges:
        src: str = e["src"]
        tgt: str = e["tgt"]
        etype: str = e["type"]

        if etype == "TEMPORAL_NEXT":
            temporal_adj[src].add(tgt)
            temporal_adj[tgt].add(src)
        elif etype == "COMMIT_TOUCHES":
            commit_touches_adj[src].add(tgt)
            commit_touches_adj[tgt].add(src)
        elif etype in ("CITES", "CALLS", "CO_CHANGED"):
            non_temporal_adj[src].add(tgt)
            non_temporal_adj[tgt].add(src)

    # Build set of nodes reachable via CITES/CALLS/CO_CHANGED (non-temporal)
    def bfs_reachable(
        start_nodes: set[str], adj: dict[str, set[str]], max_hops: int
    ) -> set[str]:
        visited: set[str] = set()
        frontier: set[str] = set(start_nodes)
        for _hop in range(max_hops):
            next_frontier: set[str] = set()
            for n in frontier:
                if n in visited:
                    continue
                visited.add(n)
                for nb in adj.get(n, set()):
                    if nb not in visited:
                        next_frontier.add(nb)
            frontier = next_frontier
        return visited

    # For temporal reachability: follow TEMPORAL_NEXT then COMMIT_TOUCHES
    def temporal_reachable(
        start_commits: set[str], max_temporal_hops: int = 5
    ) -> set[str]:
        """From commit nodes, walk TEMPORAL_NEXT then COMMIT_TOUCHES."""
        reachable: set[str] = set()
        # Walk temporal edges from start commits
        frontier: set[str] = set(start_commits)
        visited_t: set[str] = set()
        for _hop in range(max_temporal_hops):
            next_f: set[str] = set()
            for c in frontier:
                if c in visited_t:
                    continue
                visited_t.add(c)
                # From this commit, what files does it touch?
                for f in commit_touches_adj.get(c, set()):
                    reachable.add(f)
                # Walk to temporally adjacent commits
                for nb in temporal_adj.get(c, set()):
                    if nb not in visited_t:
                        next_f.add(nb)
            frontier = next_f
        return reachable

    results: dict[str, dict[str, Any]] = {}

    for topic_name, topic_data in topics.items():
        needed: list[str] = topic_data["needed"]
        # Find commit nodes whose content mentions needed decisions
        relevant_commits: set[str] = set()
        for nid, content in node_content.items():
            if not nid.startswith("commit:"):
                continue
            for d in needed:
                if d in content:
                    relevant_commits.add(nid)

        # What's reachable via temporal paths from those commits?
        temporal_reach: set[str] = temporal_reachable(relevant_commits)

        # What decisions are in the temporal reach?
        temporal_decisions: set[str] = set()
        for nid in temporal_reach:
            did: str | None = extract_decision_id(nid)
            if did:
                temporal_decisions.add(did)
        # Also check content of temporally-reachable nodes for D### refs
        for nid in temporal_reach:
            content: str = node_content.get(nid, "")
            for d_ref in re.findall(r"\bD(\d{3})\b", content):
                temporal_decisions.add(f"D{d_ref}")

        # What's reachable via non-temporal edges?
        needed_nodes: set[str] = set()
        for nid in node_content:
            did = extract_decision_id(nid)
            if did and did in needed:
                needed_nodes.add(nid)
        non_temporal_reach: set[str] = bfs_reachable(needed_nodes, non_temporal_adj, 3)
        non_temporal_decisions: set[str] = set()
        for nid in non_temporal_reach:
            did = extract_decision_id(nid)
            if did:
                non_temporal_decisions.add(did)

        # Decisions reachable ONLY via temporal
        temporal_only: set[str] = temporal_decisions - non_temporal_decisions
        # Decisions reachable by temporal that are in the needed set
        temporal_needed_found: set[str] = set(needed) & temporal_decisions

        results[topic_name] = {
            "needed": needed,
            "relevant_commits": len(relevant_commits),
            "temporal_reach_size": len(temporal_reach),
            "temporal_decisions_found": sorted(temporal_decisions),
            "non_temporal_decisions_found": sorted(non_temporal_decisions),
            "temporal_only_decisions": sorted(temporal_only),
            "temporal_needed_found": sorted(temporal_needed_found),
            "unique_temporal_signal": len(temporal_only) > 0,
        }

    return results


# ===================================================================
# Full pipeline for one project
# ===================================================================


def run_project(
    name: str,
    project_root: Path,
    preloaded_nodes: list[dict[str, Any]] | None = None,
    preloaded_edges: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run full extraction and analysis pipeline on one project."""
    result: dict[str, Any] = {"project": name}

    t_start: float = time.perf_counter()

    # Stage 1: Discover
    manifest: dict[str, Any] = discover(project_root)
    result["manifest"] = {k: v for k, v in manifest.items() if k != "doc_files"}
    result["manifest"]["doc_count"] = manifest["doc_count"]

    # Stage 2: Extract all layers
    all_nodes: list[dict[str, Any]] = []
    all_edges: list[dict[str, Any]] = []

    # Preloaded spike DB nodes (project-a only)
    if preloaded_nodes:
        all_nodes.extend(preloaded_nodes)
        result["preloaded_nodes"] = len(preloaded_nodes)
    if preloaded_edges:
        all_edges.extend(preloaded_edges)
        result["preloaded_edges"] = len(preloaded_edges)

    # File tree
    ft_nodes, ft_edges = extract_file_tree(project_root)
    all_nodes.extend(ft_nodes)
    all_edges.extend(ft_edges)

    # Git history + TEMPORAL_NEXT
    if manifest["has_git"] and manifest["commit_count"] > 0:
        git_nodes, git_edges = extract_git_history(project_root)
        all_nodes.extend(git_nodes)
        all_edges.extend(git_edges)
        temporal_count: int = sum(1 for e in git_edges if e["type"] == "TEMPORAL_NEXT")
        result["commit_nodes"] = len(git_nodes)
        result["temporal_next_edges"] = temporal_count

    # Document sentences
    if manifest["doc_count"] > 0:
        doc_nodes, doc_edges = extract_document_sentences(
            project_root,
            manifest["doc_files"],
        )
        all_nodes.extend(doc_nodes)
        all_edges.extend(doc_edges)
        result["doc_sentence_nodes"] = len(doc_nodes)

    # AST calls
    if manifest["languages"]:
        ast_nodes, ast_edges = extract_ast_calls(project_root, manifest["languages"])
        all_nodes.extend(ast_nodes)
        all_edges.extend(ast_edges)
        result["callable_nodes"] = len(ast_nodes)
        result["calls_edges"] = len(ast_edges)

    # Citations
    if manifest["citation_regex"]:
        cite_edges: list[dict[str, Any]] = extract_citations(
            project_root,
            manifest["doc_files"],
            manifest["citation_regex"],
        )
        all_edges.extend(cite_edges)
        result["citation_edges"] = len(cite_edges)

    # Directives
    if manifest["directives"]:
        dir_nodes: list[dict[str, Any]] = extract_directives(
            project_root,
            manifest["directives"],
        )
        all_nodes.extend(dir_nodes)
        result["directive_nodes"] = len(dir_nodes)

    t_extract: float = time.perf_counter() - t_start
    result["extraction_time_s"] = round(t_extract, 2)

    # Stage 3: Graph analysis
    graph_props: dict[str, Any] = analyze_graph(all_nodes, all_edges)
    result["graph"] = graph_props

    # Return raw data for retrieval tests
    result["_nodes"] = all_nodes
    result["_edges"] = all_edges

    return result


# ===================================================================
# project-a retrieval comparison
# ===================================================================


def run_project_a_retrieval(
    all_nodes: list[dict[str, Any]],
    all_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run grep vs FTS5 vs FTS5+HRR on project-a 6-topic ground truth."""
    # Build node content dict
    node_content: dict[str, str] = {
        n["id"]: str(n.get("content", "")) for n in all_nodes
    }

    # Build FTS5 index
    fts_db: sqlite3.Connection = build_fts(all_nodes)
    fts_count: int = fts_db.execute("SELECT COUNT(*) FROM fts").fetchone()[0]

    # Build partitions and HRR graph
    print("  Building HRR partitions...", file=sys.stderr)
    partitions: dict[str, list[EdgeTriple]] = build_partitions(all_edges, node_content)

    partition_stats: dict[str, Any] = {
        "total_partitions": len(partitions),
        "partition_sizes": {pid: len(edges) for pid, edges in partitions.items()},
    }
    sizes: list[int] = [len(e) for e in partitions.values()]
    capacity_limit: int = 204  # DIM=2048 / ~10 bits per edge
    over_capacity: int = sum(1 for s in sizes if s > capacity_limit)
    partition_stats["over_capacity_count"] = over_capacity
    partition_stats["over_capacity_frac"] = round(over_capacity / max(1, len(sizes)), 3)
    partition_stats["max_partition_size"] = max(sizes) if sizes else 0
    partition_stats["mean_partition_size"] = (
        round(float(np.mean(sizes)), 1) if sizes else 0.0
    )
    partition_stats["median_partition_size"] = (
        round(float(np.median(sizes)), 1) if sizes else 0.0
    )

    print(
        f"  Partitions: {len(partitions)}, max={max(sizes) if sizes else 0}, "
        f"over capacity: {over_capacity}/{len(sizes)}",
        file=sys.stderr,
    )

    # Encode HRR graph
    print("  Encoding HRR graph...", file=sys.stderr)
    hrr: HRRGraph = HRRGraph(DIM)
    for pid, pedges in partitions.items():
        hrr.encode_partition(pid, pedges)

    # Edge types available for HRR walk
    edge_types_to_walk: list[str] = sorted(hrr.edge_type_vecs.keys())

    # Run retrieval on all 6 topics
    print(f"  FTS5 indexed: {fts_count} nodes", file=sys.stderr)
    print(f"  HRR edge types: {edge_types_to_walk}", file=sys.stderr)

    per_topic: dict[str, dict[str, Any]] = {}

    for topic_name, topic_data in TOPICS.items():
        query: str = topic_data["query"]
        needed: list[str] = topic_data["needed"]

        # Method A: Grep
        grep_results: list[tuple[str, float]] = grep_search(query, node_content, TOP_K)
        grep_eval: dict[str, Any] = evaluate_method(
            "grep",
            grep_results,
            needed,
            node_content,
        )

        # Method B: FTS5
        fts_results: list[tuple[str, float]] = search_fts(query, fts_db, TOP_K)
        fts_eval: dict[str, Any] = evaluate_method(
            "fts5",
            fts_results,
            needed,
            node_content,
        )

        # Method C: FTS5 + HRR
        fts_seeds: list[tuple[str, float]] = search_fts(query, fts_db, 30)
        fts_ids: set[str] = {nid for nid, _ in fts_seeds}
        hrr_additions: list[tuple[str, float]] = []

        for seed_id, _bm25 in fts_seeds:
            for etype in edge_types_to_walk:
                neighbors: list[tuple[str, float]] = hrr.query_single_hop(
                    seed_id,
                    etype,
                    top_k=10,
                    threshold=HRR_THRESHOLD,
                )
                for neighbor_id, sim in neighbors:
                    if neighbor_id not in fts_ids:
                        hrr_additions.append((neighbor_id, sim))

        # Union: FTS5 + HRR deduped
        seen: set[str] = set()
        combined: list[tuple[str, float]] = []
        for nid, score in fts_seeds[:TOP_K]:
            if nid not in seen:
                combined.append((nid, score))
                seen.add(nid)
        for nid, score in hrr_additions:
            if nid not in seen:
                combined.append((nid, score))
                seen.add(nid)
        combined = combined[:TOP_K]

        hrr_eval: dict[str, Any] = evaluate_method(
            "fts5_hrr",
            combined,
            needed,
            node_content,
        )

        per_topic[topic_name] = {
            "query": query,
            "needed": needed,
            "grep": grep_eval,
            "fts5": fts_eval,
            "fts5_hrr": hrr_eval,
        }

        # Print per-topic
        for method_key in ["grep", "fts5", "fts5_hrr"]:
            ev: dict[str, Any] = per_topic[topic_name][method_key]
            status: str = "OK" if not ev["missed"] else f"MISSED: {ev['missed']}"
            print(
                f"    {topic_name:20s} {method_key:10s}: "
                f"cov={ev['coverage']:.0%} "
                f"tok={ev['tokens']:5d} "
                f"prec={ev['precision']:.0%} "
                f"mrr={ev['mrr']:.3f} {status}",
                file=sys.stderr,
            )

    # Aggregate
    methods: list[str] = ["grep", "fts5", "fts5_hrr"]
    aggregates: dict[str, dict[str, Any]] = {}

    for method in methods:
        coverages: list[float] = []
        tokens_list: list[int] = []
        precisions: list[float] = []
        mrrs: list[float] = []
        total_needed: int = 0
        total_found: int = 0

        for topic_name_agg in TOPICS:
            ev = per_topic[topic_name_agg][method]
            coverages.append(float(ev["coverage"]))
            tokens_list.append(int(ev["tokens"]))
            precisions.append(float(ev["precision"]))
            mrrs.append(float(ev["mrr"]))
            total_needed += len(TOPICS[topic_name_agg]["needed"])
            total_found += len(ev["found"])

        micro_coverage: float = total_found / total_needed if total_needed else 0.0
        aggregates[method] = {
            "micro_coverage": round(micro_coverage, 3),
            "macro_coverage": round(float(np.mean(coverages)), 3),
            "mean_tokens": round(float(np.mean(tokens_list)), 1),
            "mean_precision": round(float(np.mean(precisions)), 3),
            "mean_mrr": round(float(np.mean(mrrs)), 3),
            "total_found": total_found,
            "total_needed": total_needed,
        }

    return {
        "fts_indexed": fts_count,
        "partition_stats": partition_stats,
        "per_topic": per_topic,
        "aggregates": aggregates,
    }


# ===================================================================
# Main
# ===================================================================


def main() -> None:
    print("=" * 70, file=sys.stderr)
    print("Experiment 48: Multi-Layer Extraction + Retrieval at Scale", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    all_results: dict[str, Any] = {}

    for name, project_root in PROJECTS.items():
        print(f"\n{'=' * 60}", file=sys.stderr)
        print(f"Project: {name} ({project_root})", file=sys.stderr)
        print(f"{'=' * 60}", file=sys.stderr)

        # For project-a, preload spike DB nodes
        preloaded_nodes: list[dict[str, Any]] | None = None
        preloaded_edges: list[dict[str, Any]] | None = None
        if name == "project-a":
            print("  Loading spike DB (586 belief nodes)...", file=sys.stderr)
            preloaded_nodes, preloaded_edges = load_spike_nodes()
            print(
                f"  Loaded {len(preloaded_nodes)} nodes, {len(preloaded_edges)} edges",
                file=sys.stderr,
            )

        result: dict[str, Any] = run_project(
            name,
            project_root,
            preloaded_nodes,
            preloaded_edges,
        )

        # Summary
        g: dict[str, Any] = result["graph"]
        print(
            f"\n  Graph: {g['total_nodes']} nodes, {g['total_edges']} edges",
            file=sys.stderr,
        )
        print(
            f"  LCC: {g['largest_component']} ({g['largest_component_frac']:.0%})",
            file=sys.stderr,
        )
        print(f"  Components: {g['num_components']}", file=sys.stderr)
        print(f"  Node types: {g['node_types']}", file=sys.stderr)
        print(f"  Edge types: {g['edge_types']}", file=sys.stderr)
        print(f"  Extraction time: {result['extraction_time_s']}s", file=sys.stderr)

        # Retrieval comparison (project-a only)
        if name == "project-a":
            print(f"\n  --- Retrieval Comparison (K={TOP_K}) ---", file=sys.stderr)
            retrieval_result: dict[str, Any] = run_project_a_retrieval(
                result["_nodes"],
                result["_edges"],
            )
            result["retrieval"] = retrieval_result

            print("\n  --- Aggregates ---", file=sys.stderr)
            for method, agg in retrieval_result["aggregates"].items():
                print(
                    f"    {method:10s}: cov={agg['micro_coverage']:.0%} "
                    f"tok={agg['mean_tokens']:7.1f} "
                    f"prec={agg['mean_precision']:.0%} "
                    f"mrr={agg['mean_mrr']:.3f} "
                    f"({agg['total_found']}/{agg['total_needed']})",
                    file=sys.stderr,
                )

            # Temporal edge analysis (H3)
            print("\n  --- Temporal Edge Analysis (H3) ---", file=sys.stderr)
            node_content: dict[str, str] = {
                n["id"]: str(n.get("content", "")) for n in result["_nodes"]
            }
            temporal_results: dict[str, dict[str, Any]] = find_temporal_unique_paths(
                result["_edges"],
                node_content,
                TOPICS,
            )
            result["temporal_analysis"] = temporal_results

            any_unique_temporal: bool = False
            for t_topic, t_data in temporal_results.items():
                unique: bool = bool(t_data["unique_temporal_signal"])
                if unique:
                    any_unique_temporal = True
                print(
                    f"    {t_topic:20s}: commits={t_data['relevant_commits']} "
                    f"temporal_reach={t_data['temporal_reach_size']} "
                    f"temporal_only={t_data['temporal_only_decisions']} "
                    f"unique={'YES' if unique else 'no'}",
                    file=sys.stderr,
                )
            print(
                f"\n  H3 result: Temporal edges provide unique signal: "
                f"{'YES' if any_unique_temporal else 'NO'}",
                file=sys.stderr,
            )

        # Strip internal data before saving
        result.pop("_nodes", None)
        result.pop("_edges", None)
        all_results[name] = result

    # ===================================================================
    # Hypothesis summary
    # ===================================================================

    print(f"\n{'=' * 70}", file=sys.stderr)
    print("HYPOTHESIS SUMMARY", file=sys.stderr)
    print(f"{'=' * 70}", file=sys.stderr)

    as_result: dict[str, Any] = all_results.get("project-a", {})
    retrieval: dict[str, Any] = as_result.get("retrieval", {})
    aggs: dict[str, dict[str, Any]] = retrieval.get("aggregates", {})

    if aggs:
        grep_cov: float = aggs.get("grep", {}).get("micro_coverage", 0.0)
        fts_cov: float = aggs.get("fts5", {}).get("micro_coverage", 0.0)
        hrr_cov: float = aggs.get("fts5_hrr", {}).get("micro_coverage", 0.0)
        grep_prec: float = aggs.get("grep", {}).get("mean_precision", 0.0)
        fts_prec: float = aggs.get("fts5", {}).get("mean_precision", 0.0)

        h1: bool = fts_cov > grep_cov
        h2: bool = hrr_cov > fts_cov
        h6: bool = fts_prec > grep_prec

        print("\n  H1 (FTS5 > grep at scale):", file=sys.stderr)
        print(f"    grep coverage: {grep_cov:.0%}", file=sys.stderr)
        print(f"    FTS5 coverage: {fts_cov:.0%}", file=sys.stderr)
        print(f"    Result: {'PASS' if h1 else 'FAIL'}", file=sys.stderr)

        print("\n  H2 (FTS5+HRR > FTS5):", file=sys.stderr)
        print(f"    FTS5 coverage: {fts_cov:.0%}", file=sys.stderr)
        print(f"    FTS5+HRR coverage: {hrr_cov:.0%}", file=sys.stderr)
        print(f"    Result: {'PASS' if h2 else 'FAIL'}", file=sys.stderr)

        temporal: dict[str, dict[str, Any]] = as_result.get("temporal_analysis", {})
        h3: bool = any(bool(v.get("unique_temporal_signal")) for v in temporal.values())
        print(
            f"\n  H3 (Temporal unique signal): {'PASS' if h3 else 'FAIL'}",
            file=sys.stderr,
        )

        ps: dict[str, Any] = retrieval.get("partition_stats", {})
        if ps:
            over_frac: float = ps.get("over_capacity_frac", 1.0)
            h4_pass: bool = over_frac <= 0.10
            print("\n  H4 (90%+ partitions within capacity):", file=sys.stderr)
            print(
                f"    Over-capacity: {ps.get('over_capacity_count', 0)}/{ps.get('total_partitions', 0)}"
                f" ({over_frac:.0%})",
                file=sys.stderr,
            )
            print(f"    Result: {'PASS' if h4_pass else 'FAIL'}", file=sys.stderr)

        # H5: extraction time
        print("\n  H5 (Extraction scales linearly):", file=sys.stderr)
        for proj_name, proj_result in all_results.items():
            t_ext: float = proj_result.get("extraction_time_s", 0.0)
            nodes_count: int = proj_result.get("graph", {}).get("total_nodes", 0)
            print(
                f"    {proj_name:15s}: {t_ext:.2f}s, {nodes_count} nodes",
                file=sys.stderr,
            )

        print("\n  H6 (Grep precision degrades):", file=sys.stderr)
        print(f"    grep precision: {grep_prec:.0%}", file=sys.stderr)
        print(f"    FTS5 precision: {fts_prec:.0%}", file=sys.stderr)
        print(f"    Result: {'PASS' if h6 else 'FAIL'}", file=sys.stderr)

        # Comparison to Exp 47 baseline (586 nodes)
        print("\n  --- Comparison to Exp 47 (586 nodes) ---", file=sys.stderr)
        print("  Exp 47: grep=92%, FTS5=85%, FTS5+HRR=85%", file=sys.stderr)
        n_nodes: int = as_result.get("graph", {}).get("total_nodes", 0)
        print(
            f"  Exp 48 ({n_nodes} nodes): grep={grep_cov:.0%}, "
            f"FTS5={fts_cov:.0%}, FTS5+HRR={hrr_cov:.0%}",
            file=sys.stderr,
        )

    # Save results
    results_path: Path = Path(__file__).parent / "exp48_results.json"
    results_path.write_text(
        json.dumps(all_results, indent=2, default=str), encoding="utf-8"
    )
    print(f"\nResults saved to {results_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
