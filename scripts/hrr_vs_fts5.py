"""
hrr_vs_fts5.py -- H3: Compare HRR vs FTS5 on low-overlap vs high-overlap edges.

For each pilot repo:
1. Load edges with their vocabulary overlap scores (from refined/*.json)
2. Split into low-overlap (<0.1) and high-overlap (>0.3) sets
3. Build FTS5 index from file contents
4. Run both HRR and FTS5 retrieval on each set
5. Measure: does HRR find low-overlap targets FTS5 misses?

This is the definitive test of the "HRR as selective amplifier" hypothesis.

Usage:
    python scripts/hrr_vs_fts5.py /path/to/repo /path/to/extracted_dir

Reads: extracted/refined/<repo>.json, file contents from repo
Writes: extracted/hrr_vs_fts5/<repo>.json
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
from numpy.typing import NDArray

from hrr_encoder import Edge, HRRGraph, load_edges


SKIP_DIRS: set[str] = {
    ".git", "node_modules", "target", ".venv", "venv", "__pycache__",
    ".mypy_cache", ".ruff_cache", "dist", "build", ".tox", "vendor",
    "third_party", "3rdparty",
}

STOP_WORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must", "to", "of",
    "in", "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "out", "off",
    "over", "under", "again", "further", "then", "once", "here", "there",
    "when", "where", "why", "how", "all", "each", "every", "both", "few",
    "more", "most", "other", "some", "such", "no", "nor", "not", "only",
    "own", "same", "so", "than", "too", "very", "and", "but", "or", "if",
}


class FTS5Index:
    """SQLite FTS5 index for file content retrieval."""

    def __init__(self) -> None:
        self.db: sqlite3.Connection = sqlite3.connect(":memory:")
        self.db.execute(
            "CREATE VIRTUAL TABLE files_fts USING fts5(path, content, tokenize='porter')"
        )

    def add(self, path: str, content: str) -> None:
        """Add a file to the index."""
        self.db.execute("INSERT INTO files_fts VALUES (?, ?)", (path, content))

    def commit(self) -> None:
        """Commit the index."""
        self.db.commit()

    def search(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        """Search for files matching query terms. Returns (path, rank) pairs."""
        # Build OR query from terms
        terms: list[str] = [
            t for t in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", query)
            if t.lower() not in STOP_WORDS and len(t) > 2
        ]
        if not terms:
            return []

        fts_query: str = " OR ".join(terms[:20])  # cap at 20 terms
        try:
            rows: list[tuple[str, float]] = self.db.execute(
                "SELECT path, rank FROM files_fts WHERE files_fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, limit),
            ).fetchall()
            return rows
        except sqlite3.OperationalError:
            return []


def build_fts5_index(repo_path: Path) -> FTS5Index:
    """Build FTS5 index from all text files in repo."""
    index: FTS5Index = FTS5Index()
    count: int = 0

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath: Path = Path(root) / f
            rel: str = str(fpath.relative_to(repo_path))
            ext: str = fpath.suffix.lower()

            # Only index text-like files
            if ext not in {
                ".py", ".rs", ".go", ".ts", ".tsx", ".js", ".jsx",
                ".c", ".h", ".cpp", ".cc", ".hpp", ".md", ".txt",
                ".yml", ".yaml", ".toml", ".json", ".sh", ".sql",
                ".css", ".html", ".xml", ".cfg", ".conf", ".ini",
            }:
                continue

            try:
                content: str = fpath.read_text(errors="ignore")[:8192]
                index.add(rel, content)
                count += 1
            except OSError:
                continue

    index.commit()
    return index


class EdgeWithOverlap(NamedTuple):
    source: str
    target: str
    edge_type: str
    vocab_overlap: float


def load_edges_with_overlap(extracted_dir: Path, repo_name: str) -> list[EdgeWithOverlap]:
    """Load edges from refined output that have vocab_overlap scores."""
    refined_path: Path = extracted_dir / "refined" / f"{repo_name}.json"
    if not refined_path.exists():
        return []

    # We need the raw edges with overlap -- but the refined output is summary only.
    # Re-derive from the edge files + overlap computation.
    # Actually, let's load all edges and compute overlap inline.
    # The refined script computed per-type stats but didn't save per-edge overlap.
    # For H3, we need per-edge overlap. Let's compute it here.
    return []  # Will compute in main


def tokenize(text: str) -> set[str]:
    """Extract word tokens from text."""
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
    """Jaccard similarity."""
    if not a and not b:
        return 0.0
    inter: int = len(a & b)
    union: int = len(a | b)
    return inter / union if union > 0 else 0.0


def main() -> None:
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} /path/to/repo /path/to/extracted_dir [--dim N]")
        sys.exit(1)

    repo_path: Path = Path(sys.argv[1]).resolve()
    extracted_dir: Path = Path(sys.argv[2])
    repo_name: str = repo_path.name
    dim: int = 2048

    args: list[str] = sys.argv[3:]
    i: int = 0
    while i < len(args):
        if args[i] == "--dim" and i + 1 < len(args):
            dim = int(args[i + 1])
            i += 2
        else:
            i += 1

    print(f"[H3] {repo_name} DIM={dim}", file=sys.stderr)

    # Load edges
    edges: list[Edge] = load_edges(extracted_dir, repo_name)
    if not edges:
        print("  no edges", file=sys.stderr)
        return

    print(f"  {len(edges)} edges loaded", file=sys.stderr)

    # Build FTS5 index
    print(f"  building FTS5 index...", file=sys.stderr)
    fts: FTS5Index = build_fts5_index(repo_path)

    # Build HRR graph
    print(f"  building HRR graph...", file=sys.stderr)
    hrr: HRRGraph = HRRGraph(dim=dim)
    hrr.encode(edges)

    # Compute per-edge vocabulary overlap
    print(f"  computing vocabulary overlap...", file=sys.stderr)
    token_cache: dict[str, set[str] | None] = {}

    def get_tokens(filepath: str) -> set[str] | None:
        if filepath in token_cache:
            return token_cache[filepath]
        fpath: Path = repo_path / filepath
        if not fpath.exists() or not fpath.is_file():
            token_cache[filepath] = None
            return None
        try:
            content: str = fpath.read_text(errors="ignore")[:8192]
            tokens: set[str] = tokenize(content)
            token_cache[filepath] = tokens
            return tokens
        except OSError:
            token_cache[filepath] = None
            return None

    # Categorize edges by overlap
    low_overlap: list[Edge] = []   # < 0.1
    high_overlap: list[Edge] = []  # > 0.3
    mid_overlap: list[Edge] = []   # 0.1 - 0.3
    skipped: int = 0

    for e in edges:
        s_tok: set[str] | None = get_tokens(e.source)
        t_tok: set[str] | None = get_tokens(e.target)
        if s_tok is None or t_tok is None:
            skipped += 1
            continue
        j: float = jaccard(s_tok, t_tok)
        if j < 0.1:
            low_overlap.append(e)
        elif j > 0.3:
            high_overlap.append(e)
        else:
            mid_overlap.append(e)

    print(f"  low overlap (<0.1): {len(low_overlap)}", file=sys.stderr)
    print(f"  mid overlap (0.1-0.3): {len(mid_overlap)}", file=sys.stderr)
    print(f"  high overlap (>0.3): {len(high_overlap)}", file=sys.stderr)
    print(f"  skipped (no content): {skipped}", file=sys.stderr)

    # Build ground truth per source
    def build_gt(edge_list: list[Edge]) -> dict[tuple[str, str], set[str]]:
        gt: dict[tuple[str, str], set[str]] = defaultdict(set)
        for e in edge_list:
            gt[(e.source, e.edge_type)].add(e.target)
        return gt

    # Evaluate retrieval on a set of edges
    def evaluate_set(
        edge_list: list[Edge],
        set_name: str,
        max_queries: int = 50,
    ) -> dict[str, Any]:
        if not edge_list:
            return {"n_edges": 0, "n_queries": 0}

        gt: dict[tuple[str, str], set[str]] = build_gt(edge_list)
        query_keys: list[tuple[str, str]] = list(gt.keys())

        rng: np.random.Generator = np.random.default_rng(42)
        if len(query_keys) > max_queries:
            indices: NDArray[np.intp] = rng.choice(len(query_keys), size=max_queries, replace=False)
            query_keys = [query_keys[int(i)] for i in indices]

        hrr_hits: int = 0
        fts_hits: int = 0
        both_hits: int = 0
        neither_hits: int = 0
        hrr_only_hits: int = 0
        fts_only_hits: int = 0
        total_targets: int = 0

        for source, edge_type in query_keys:
            targets: set[str] = gt[(source, edge_type)]
            total_targets += len(targets)

            # HRR retrieval
            hrr_results: list[tuple[str, float]] = hrr.query_forward(source, edge_type, top_k=10)
            hrr_found: set[str] = {r[0] for r in hrr_results[:10]}

            # FTS5 retrieval: use source file content as query
            source_content: str | None = None
            source_path: Path = repo_path / source
            if source_path.exists():
                try:
                    source_content = source_path.read_text(errors="ignore")[:2000]
                except OSError:
                    pass

            fts_found: set[str] = set()
            if source_content:
                fts_results: list[tuple[str, float]] = fts.search(source_content, limit=10)
                fts_found = {r[0] for r in fts_results if r[0] != source}

            # Count hits per target
            for t in targets:
                in_hrr: bool = t in hrr_found
                in_fts: bool = t in fts_found
                if in_hrr and in_fts:
                    both_hits += 1
                elif in_hrr and not in_fts:
                    hrr_only_hits += 1
                elif in_fts and not in_hrr:
                    fts_only_hits += 1
                else:
                    neither_hits += 1
                if in_hrr:
                    hrr_hits += 1
                if in_fts:
                    fts_hits += 1

        hrr_recall: float = hrr_hits / max(total_targets, 1)
        fts_recall: float = fts_hits / max(total_targets, 1)

        return {
            "n_edges": len(edge_list),
            "n_queries": len(query_keys),
            "total_targets": total_targets,
            "hrr_recall": round(hrr_recall, 4),
            "fts_recall": round(fts_recall, 4),
            "both_found": both_hits,
            "hrr_only": hrr_only_hits,
            "fts_only": fts_only_hits,
            "neither_found": neither_hits,
            "hrr_unique_contribution": round(hrr_only_hits / max(total_targets, 1), 4),
            "fts_unique_contribution": round(fts_only_hits / max(total_targets, 1), 4),
        }

    # Run evaluation on each overlap tier
    print(f"\n  === Low overlap (<0.1) -- HRR should add value ===", file=sys.stderr)
    low_results: dict[str, Any] = evaluate_set(low_overlap, "low_overlap")
    print(f"  HRR recall: {low_results.get('hrr_recall', 0):.3f}", file=sys.stderr)
    print(f"  FTS5 recall: {low_results.get('fts_recall', 0):.3f}", file=sys.stderr)
    print(f"  HRR-only: {low_results.get('hrr_only', 0)}, FTS-only: {low_results.get('fts_only', 0)}, Both: {low_results.get('both_found', 0)}, Neither: {low_results.get('neither_found', 0)}", file=sys.stderr)

    print(f"\n  === High overlap (>0.3) -- FTS5 should suffice ===", file=sys.stderr)
    high_results: dict[str, Any] = evaluate_set(high_overlap, "high_overlap")
    print(f"  HRR recall: {high_results.get('hrr_recall', 0):.3f}", file=sys.stderr)
    print(f"  FTS5 recall: {high_results.get('fts_recall', 0):.3f}", file=sys.stderr)
    print(f"  HRR-only: {high_results.get('hrr_only', 0)}, FTS-only: {high_results.get('fts_only', 0)}, Both: {high_results.get('both_found', 0)}, Neither: {high_results.get('neither_found', 0)}", file=sys.stderr)

    print(f"\n  === Mid overlap (0.1-0.3) ===", file=sys.stderr)
    mid_results: dict[str, Any] = evaluate_set(mid_overlap, "mid_overlap")
    print(f"  HRR recall: {mid_results.get('hrr_recall', 0):.3f}", file=sys.stderr)
    print(f"  FTS5 recall: {mid_results.get('fts_recall', 0):.3f}", file=sys.stderr)
    print(f"  HRR-only: {mid_results.get('hrr_only', 0)}, FTS-only: {mid_results.get('fts_only', 0)}, Both: {mid_results.get('both_found', 0)}, Neither: {mid_results.get('neither_found', 0)}", file=sys.stderr)

    # Write results
    output_dir: Path = extracted_dir / "hrr_vs_fts5"
    output_dir.mkdir(exist_ok=True)
    output_path: Path = output_dir / f"{repo_name}.json"

    result: dict[str, Any] = {
        "repo": repo_name,
        "dim": dim,
        "total_edges": len(edges),
        "low_overlap": low_results,
        "mid_overlap": mid_results,
        "high_overlap": high_results,
    }

    output_path.write_text(json.dumps(result, indent=2))
    print(f"\n  written to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
