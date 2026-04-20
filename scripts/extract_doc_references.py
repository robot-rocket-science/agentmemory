"""
extract_doc_references.py -- Build a document reference graph from markdown files.

Extracts cross-references (D###, M###, REQ-###, R###, file paths, section headers)
from markdown sentences and builds direct-citation and co-citation edge sets.

Part of the agentmemory validation pipeline: compare auto-extracted graph edges
against human-authored references in project documentation.

Usage:
    uv run python scripts/extract_doc_references.py --repo /path/to/project
    uv run python scripts/extract_doc_references.py --repo /path/to/project --min-refs 2

Output: JSON to stdout, summary stats to stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any


SKIP_DIRS: frozenset[str] = frozenset({
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    ".mypy_cache", ".ruff_cache", "dist", "build", ".tox",
})

FILE_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go",
    ".md", ".json", ".toml", ".yaml", ".yml", ".sql",
    ".html", ".css", ".sh", ".c", ".cpp", ".h", ".hpp",
})

# Sentence boundary pattern: split on `. `, `.\n`, `? `, `?\n`, `! `, `!\n`
_SENTENCE_SPLIT: re.Pattern[str] = re.compile(r"(?<=[.?!])(?:\s|\n)+")

# Reference patterns
_PAT_D: re.Pattern[str] = re.compile(r"\bD(\d{2,4})\b")
_PAT_M: re.Pattern[str] = re.compile(r"\bM(\d{2,4})\b")
_PAT_REQ: re.Pattern[str] = re.compile(r"\bREQ-(\d+)\b")
_PAT_R: re.Pattern[str] = re.compile(r"\bR(\d{2,4})\b")
_PAT_FILE_PATH: re.Pattern[str] = re.compile(
    r"(?:^|[\s(`\"'])("
    r"(?:[\w./-]+/)?[\w.-]+"
    r"\.(?:py|ts|tsx|js|jsx|rs|go|md|json|toml|yaml|yml|sql|html|css|sh|c|cpp|h|hpp)"
    r")(?:[\s)\"'`,;:]|$)",
    re.MULTILINE,
)
_PAT_HEADING: re.Pattern[str] = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def find_md_files(repo: Path) -> list[Path]:
    """Walk repo and collect .md files, skipping excluded directories."""
    results: list[Path] = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.lower().endswith(".md"):
                results.append(Path(root) / f)
    return sorted(results)


def read_file_safe(path: Path) -> str | None:
    """Read a file, returning None on encoding or OS errors."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def split_sentences(text: str) -> list[str]:
    """Split text into sentences at simple boundaries."""
    raw: list[str] = _SENTENCE_SPLIT.split(text)
    return [s.strip() for s in raw if s.strip()]


def extract_headings(content: str) -> list[str]:
    """Extract heading text from markdown content."""
    return [m.group(2).strip() for m in _PAT_HEADING.finditer(content)]


def extract_refs_from_sentence(
    sentence: str,
    file_has_dm_refs: bool,
) -> list[tuple[str, str]]:
    """Extract typed references from a single sentence.

    Returns list of (ref_type, ref_id) tuples.
    ref_type is one of: "D", "M", "REQ", "R", "file_path"
    """
    refs: list[tuple[str, str]] = []

    for m in _PAT_D.finditer(sentence):
        refs.append(("D", f"D{m.group(1)}"))

    for m in _PAT_M.finditer(sentence):
        refs.append(("M", f"M{m.group(1)}"))

    for m in _PAT_REQ.finditer(sentence):
        refs.append(("REQ", f"REQ-{m.group(1)}"))

    # R### only if the file also contains D or M references
    if file_has_dm_refs:
        for m in _PAT_R.finditer(sentence):
            refs.append(("R", f"R{m.group(1)}"))

    for m in _PAT_FILE_PATH.finditer(sentence):
        refs.append(("file_path", m.group(1)))

    return refs


def build_graph(
    repo: Path,
    min_refs: int,
) -> dict[str, Any]:
    """Build the full reference graph from markdown files under repo."""
    md_files: list[Path] = find_md_files(repo)
    repo_resolved: Path = repo.resolve()

    # --- Pass 1: read all files, extract sentences, headings, raw refs ---

    file_contents: dict[str, str] = {}
    file_sentences: dict[str, list[str]] = {}
    file_headings: dict[str, list[str]] = {}

    for fp in md_files:
        content: str | None = read_file_safe(fp)
        if content is None:
            continue
        try:
            rel: str = str(fp.relative_to(repo_resolved))
        except ValueError:
            rel = str(fp.relative_to(repo))
        file_contents[rel] = content
        file_sentences[rel] = split_sentences(content)
        file_headings[rel] = extract_headings(content)

    # --- Pass 2: detect which files have D/M refs (for R### gating) ---

    files_with_dm: set[str] = set()
    for rel_path, content in file_contents.items():
        if _PAT_D.search(content) or _PAT_M.search(content):
            files_with_dm.add(rel_path)

    # --- Pass 3: extract refs per file, count ref occurrences ---

    # file -> list of all ref ids found
    file_refs: dict[str, list[str]] = defaultdict(list)
    # ref_id -> Counter of files and their mention counts
    ref_file_counts: dict[str, Counter[str]] = defaultdict(Counter)
    # global ref type counts
    ref_type_counts: Counter[str] = Counter()

    for rel_path, sentences in file_sentences.items():
        has_dm: bool = rel_path in files_with_dm
        seen_in_file: set[str] = set()
        for sentence in sentences:
            refs: list[tuple[str, str]] = extract_refs_from_sentence(
                sentence, has_dm,
            )
            for ref_type, ref_id in refs:
                ref_type_counts[ref_type] += 1
                file_refs[rel_path].append(ref_id)
                ref_file_counts[ref_id][rel_path] += 1
                seen_in_file.add(ref_id)

    # --- Pass 3b: cross-file section header references ---
    # Build heading index: normalized heading text -> list of files defining it
    heading_index: dict[str, list[str]] = defaultdict(list)
    for rel_path, headings in file_headings.items():
        for h in headings:
            heading_index[h.lower()].append(rel_path)

    # Search sentences for references like "see Requirements" matching headings
    # in other files. Pattern: "see <Capitalized Word(s)>" or "refer to <...>"
    _see_pattern: re.Pattern[str] = re.compile(
        r"(?:see|refer\s+to|described\s+in|defined\s+in|per)\s+"
        r"([A-Z][\w\s-]{1,60})",
        re.IGNORECASE,
    )
    for rel_path, sentences in file_sentences.items():
        for sentence in sentences:
            for m in _see_pattern.finditer(sentence):
                candidate: str = m.group(1).strip().rstrip(".,;:").lower()
                if candidate in heading_index:
                    for target_file in heading_index[candidate]:
                        if target_file != rel_path:
                            ref_id: str = f"heading:{candidate}"
                            ref_type_counts["heading"] += 1
                            file_refs[rel_path].append(ref_id)
                            ref_file_counts[ref_id][rel_path] += 1

    # --- Pass 4: determine "defining" file for each ref ---
    # The file where a ref appears most frequently (ties broken by name sort)

    ref_defining_file: dict[str, str] = {}
    for ref_id, counter in ref_file_counts.items():
        most_common: list[tuple[str, int]] = counter.most_common()
        # Among tied files, pick the one where the ref appears in a heading
        max_count: int = most_common[0][1]
        candidates: list[str] = [f for f, c in most_common if c == max_count]

        # Prefer file with ref in a heading
        best: str = candidates[0]
        for cand in candidates:
            for heading in file_headings.get(cand, []):
                if ref_id.lower() in heading.lower() or (
                    not ref_id.startswith("heading:") and ref_id in heading
                ):
                    best = cand
                    break
        ref_defining_file[ref_id] = best

    # --- Pass 5: build direct citation edges ---

    # source -> target -> set of shared ref ids
    direct_edge_map: dict[tuple[str, str], set[str]] = defaultdict(set)

    for rel_path, refs_list in file_refs.items():
        for ref_id in set(refs_list):
            defining: str = ref_defining_file.get(ref_id, "")
            if defining and defining != rel_path:
                key: tuple[str, str] = (rel_path, defining)
                direct_edge_map[key].add(ref_id)

    direct_edges: list[dict[str, str | list[str] | int]] = []
    for (src, tgt), ref_ids in sorted(direct_edge_map.items()):
        sorted_refs: list[str] = sorted(ref_ids)
        direct_edges.append({
            "source": src,
            "target": tgt,
            "refs": sorted_refs,
            "count": len(sorted_refs),
        })

    # --- Pass 6: build co-citation edges ---

    co_cite_map: dict[tuple[str, str], set[str]] = defaultdict(set)

    for ref_id, counter in ref_file_counts.items():
        files_mentioning: list[str] = sorted(counter.keys())
        if len(files_mentioning) < 2:
            continue
        for fa, fb in combinations(files_mentioning, 2):
            pair: tuple[str, str] = (fa, fb) if fa < fb else (fb, fa)
            co_cite_map[pair].add(ref_id)

    co_citation_edges: list[dict[str, str | list[str] | int]] = []
    for (fa, fb), shared in sorted(co_cite_map.items()):
        if len(shared) < min_refs:
            continue
        sorted_shared: list[str] = sorted(shared)
        co_citation_edges.append({
            "file_a": fa,
            "file_b": fb,
            "shared_refs": sorted_shared,
            "count": len(sorted_shared),
        })

    # --- Build nodes ---

    nodes: list[dict[str, str | int]] = []
    for rel_path in sorted(file_contents.keys()):
        nodes.append({
            "file": rel_path,
            "sentences": len(file_sentences.get(rel_path, [])),
        })

    total_sentences: int = sum(
        len(sents) for sents in file_sentences.values()
    )

    total_refs: int = sum(len(r) for r in file_refs.values())
    num_files_with_refs: int = sum(1 for r in file_refs.values() if r)
    avg_refs: float = (
        round(total_refs / num_files_with_refs, 2)
        if num_files_with_refs > 0
        else 0.0
    )

    reference_types: dict[str, int] = {
        k: v for k, v in sorted(ref_type_counts.items())
    }

    result: dict[str, Any] = {
        "repo": repo.name,
        "total_md_files": len(file_contents),
        "total_sentences": total_sentences,
        "reference_types": reference_types,
        "nodes": nodes,
        "edges": {
            "direct_citation": direct_edges,
            "co_citation": co_citation_edges,
        },
        "summary": {
            "total_direct_edges": len(direct_edges),
            "total_co_citation_edges": len(co_citation_edges),
            "avg_refs_per_file": avg_refs,
        },
    }
    return result


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Build a document reference graph from markdown files.",
    )
    parser.add_argument(
        "--repo",
        type=str,
        required=True,
        help="Path to project root directory",
    )
    parser.add_argument(
        "--min-refs",
        type=int,
        default=1,
        help="Minimum shared references for co-citation edge (default: 1)",
    )

    args: argparse.Namespace = parser.parse_args()
    repo: Path = Path(args.repo).resolve()

    if not repo.is_dir():
        print(f"Error: {repo} is not a directory", file=sys.stderr)
        sys.exit(1)

    result: dict[str, Any] = build_graph(repo, args.min_refs)

    # Summary to stderr
    summary: dict[str, Any] = result["summary"]
    print(f"[doc-refs] {result['repo']}", file=sys.stderr)
    print(f"  files: {result['total_md_files']}", file=sys.stderr)
    print(f"  sentences: {result['total_sentences']}", file=sys.stderr)
    print(f"  reference types: {result['reference_types']}", file=sys.stderr)
    print(f"  direct edges: {summary['total_direct_edges']}", file=sys.stderr)
    print(f"  co-citation edges: {summary['total_co_citation_edges']}", file=sys.stderr)
    print(f"  avg refs/file: {summary['avg_refs_per_file']}", file=sys.stderr)

    # JSON to stdout
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
