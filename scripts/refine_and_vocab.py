"""
refine_and_vocab.py -- T0.7 + M2: Edge type refinement and vocabulary overlap.

T0.7: Combines node types with edge sources to produce refined edge type names.
  e.g., CO_CHANGED between TEST and SOURCE -> relabel as TEST_COUPLING

M2: For each edge, measures vocabulary overlap between source and target files.
  Predicts where FTS5 will succeed (high overlap) vs where HRR is needed (low overlap).

Usage:
    python scripts/refine_and_vocab.py /path/to/repo /path/to/extracted_dir

Reads: extracted/{git_edges,import_edges,structural_edges,node_types}/<repo>.json
Writes: extracted/refined/<repo>.json
"""

from __future__ import annotations

import json
import sys
import re
from collections import Counter, defaultdict
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
    "during",
    "before",
    "after",
    "above",
    "below",
    "between",
    "out",
    "off",
    "over",
    "under",
    "again",
    "further",
    "then",
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
    "no",
    "nor",
    "not",
    "only",
    "own",
    "same",
    "so",
    "than",
    "too",
    "very",
    "and",
    "but",
    "or",
    "if",
    "while",
    "that",
    "this",
    "it",
    "its",
    "they",
    "them",
    "their",
    "we",
    "our",
    "you",
    "your",
    "he",
    "him",
    "his",
    "she",
    "her",
    "i",
    "me",
    "my",
    "self",
    "none",
    "true",
    "false",
    "null",
    "return",
    "import",
    "from",
    "def",
    "class",
    "fn",
    "let",
    "const",
    "var",
    "pub",
    "use",
    "mod",
    "struct",
    "enum",
    "impl",
    "trait",
    "type",
    "async",
    "await",
    "else",
    "elif",
    "match",
    "case",
    "break",
    "continue",
    "pass",
    "raise",
    "try",
    "except",
    "finally",
    "with",
    "yield",
    "lambda",
    "assert",
}


def tokenize(text: str) -> set[str]:
    """Extract word tokens from text, filtering stop words and short tokens."""
    words: list[str] = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", text)
    # Split camelCase and snake_case
    expanded: set[str] = set()
    for w in words:
        # camelCase split
        parts: list[str] = re.sub(r"([a-z])([A-Z])", r"\1 \2", w).split()
        # snake_case split
        for p in parts:
            for sub in p.split("_"):
                sub = sub.lower()
                if len(sub) > 2 and sub not in STOP_WORDS:
                    expanded.add(sub)
    return expanded


def jaccard(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 0.0
    intersection: int = len(set_a & set_b)
    union: int = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def load_file_content(repo_path: Path, rel_path: str) -> str | None:
    """Load file content for vocabulary analysis."""
    fpath: Path = repo_path / rel_path
    if not fpath.exists() or not fpath.is_file():
        return None
    try:
        return fpath.read_text(errors="ignore")[:8192]  # First 8KB
    except OSError:
        return None


def refine_edge_type(
    edge_type: str,
    source_node_type: str | None,
    target_node_type: str | None,
) -> str:
    """Refine generic edge type using node type context."""
    s: str = source_node_type or "UNKNOWN"
    t: str = target_node_type or "UNKNOWN"

    if edge_type == "CO_CHANGED":
        # Test <-> Source coupling
        if (s == "TEST" and t == "SOURCE") or (s == "SOURCE" and t == "TEST"):
            return "TEST_COUPLING"
        # Config <-> Source coupling
        if "CONFIG" in s or "CONFIG" in t:
            return "CONFIG_COUPLING"
        # Doc <-> Source coupling
        if s in ("DOCUMENT", "DOCUMENTATION") or t in ("DOCUMENT", "DOCUMENTATION"):
            return "DOC_CODE_COUPLING"
        # Planning <-> anything
        if s == "PLANNING" or t == "PLANNING":
            return "PLANNING_COUPLING"
        # Source <-> Source (same type)
        if s == "SOURCE" and t == "SOURCE":
            return "CODE_COUPLING"
        # Infrastructure coupling
        if s == "INFRASTRUCTURE" or t == "INFRASTRUCTURE":
            return "INFRA_COUPLING"
        return "CO_CHANGED"

    if edge_type == "IMPORTS":
        if s == "TEST":
            return "TEST_IMPORTS"
        if s == "BENCHMARK":
            return "BENCH_IMPORTS"
        if s == "EXAMPLE":
            return "EXAMPLE_IMPORTS"
        return "IMPORTS"

    return edge_type


def main() -> None:
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} /path/to/repo /path/to/extracted_dir")
        sys.exit(1)

    repo_path: Path = Path(sys.argv[1]).resolve()
    extracted_dir: Path = Path(sys.argv[2])
    name: str = repo_path.name

    print(f"[analyze] {name}", file=sys.stderr)

    # Load node types
    node_data: dict[str, Any] | None = None
    nt_path: Path = extracted_dir / "node_types" / f"{name}.json"
    if nt_path.exists():
        node_data = json.loads(nt_path.read_text())
    classifications: dict[str, str] = (
        node_data.get("classifications", {}) if node_data else {}
    )

    # Collect all file-to-file edges with their types
    all_edges: list[dict[str, Any]] = []

    # Git co-change (w>=3)
    git_path: Path = extracted_dir / "git_edges" / f"{name}.json"
    if git_path.exists():
        git_data: dict[str, Any] = json.loads(git_path.read_text())
        co_changed: list[dict[str, Any]] = git_data.get("co_changed_edges", [])
        for e in co_changed:
            weight: int = e["weight"]
            if weight >= 3:
                all_edges.append(
                    {
                        "source": e["source"],
                        "target": e["target"],
                        "raw_type": "CO_CHANGED",
                        "weight": e["weight"],
                    }
                )

    # Imports
    imp_path: Path = extracted_dir / "import_edges" / f"{name}.json"
    if imp_path.exists():
        imp_data: dict[str, Any] = json.loads(imp_path.read_text())
        imp_edges: list[dict[str, Any]] = imp_data.get("edges", [])
        for e in imp_edges:
            all_edges.append(
                {
                    "source": e["source"],
                    "target": e["target"],
                    "raw_type": "IMPORTS",
                }
            )

    # Structural
    str_path: Path = extracted_dir / "structural_edges" / f"{name}.json"
    if str_path.exists():
        str_data: dict[str, Any] = json.loads(str_path.read_text())
        str_edges: list[dict[str, Any]] = str_data.get("edges", [])
        for e in str_edges:
            s: str = e.get("source", "")
            t: str = e.get("target", "")
            if ":" not in s and ":" not in t:  # file-to-file only
                all_edges.append(
                    {
                        "source": s,
                        "target": t,
                        "raw_type": e.get("type", "STRUCTURAL"),
                    }
                )

    print(f"  {len(all_edges)} file-to-file edges to analyze", file=sys.stderr)

    # --- T0.7: Edge type refinement ---
    refined_counts: Counter[str] = Counter()
    raw_to_refined: dict[str, Counter[str]] = defaultdict(Counter)

    for e in all_edges:
        s_type: str | None = classifications.get(e["source"])
        t_type: str | None = classifications.get(e["target"])
        refined: str = refine_edge_type(e["raw_type"], s_type, t_type)
        e["refined_type"] = refined
        e["source_node_type"] = s_type
        e["target_node_type"] = t_type
        refined_counts[refined] += 1
        raw_to_refined[e["raw_type"]][refined] += 1

    print("\n  T0.7 Edge type refinement:", file=sys.stderr)
    for raw, refined_dist in sorted(raw_to_refined.items()):
        total: int = sum(refined_dist.values())
        print(f"    {raw} ({total} edges) ->", file=sys.stderr)
        for refined_name, count in refined_dist.most_common():
            pct: float = count / total * 100
            print(f"      {refined_name}: {count} ({pct:.1f}%)", file=sys.stderr)

    # --- M2: Vocabulary overlap ---
    # Cache file content tokenization
    token_cache: dict[str, set[str] | None] = {}

    def get_tokens(filepath: str) -> set[str] | None:
        if filepath in token_cache:
            return token_cache[filepath]
        content: str | None = load_file_content(repo_path, filepath)
        if content is None:
            token_cache[filepath] = None
            return None
        tokens: set[str] = tokenize(content)
        token_cache[filepath] = tokens
        return tokens

    # Compute vocabulary overlap per edge
    overlap_by_type: dict[str, list[float]] = defaultdict(list)
    total_computed: int = 0
    total_skipped: int = 0

    for e in all_edges:
        s_tokens: set[str] | None = get_tokens(e["source"])
        t_tokens: set[str] | None = get_tokens(e["target"])
        if s_tokens is None or t_tokens is None:
            total_skipped += 1
            continue

        j: float = jaccard(s_tokens, t_tokens)
        e["vocab_overlap"] = round(j, 4)
        refined_type: str = e["refined_type"]
        overlap_by_type[refined_type].append(j)
        total_computed += 1

    print(
        f"\n  M2 Vocabulary overlap ({total_computed} computed, {total_skipped} skipped):",
        file=sys.stderr,
    )
    print(
        f"  {'Type':<25} {'Count':>6} {'Mean':>6} {'Med':>6} {'<0.05':>6} {'<0.1':>6} {'>0.3':>6}",
        file=sys.stderr,
    )
    print(f"  {'-' * 75}", file=sys.stderr)

    type_summaries: dict[str, dict[str, int | float]] = {}
    for etype, overlaps in sorted(overlap_by_type.items()):
        if not overlaps:
            continue
        overlaps_sorted: list[float] = sorted(overlaps)
        n: int = len(overlaps)
        mean: float = sum(overlaps) / n
        median: float = overlaps_sorted[n // 2]
        low_005: int = sum(1 for o in overlaps if o < 0.05)
        low_01: int = sum(1 for o in overlaps if o < 0.1)
        high_03: int = sum(1 for o in overlaps if o > 0.3)

        type_summaries[etype] = {
            "count": n,
            "mean": round(mean, 4),
            "median": round(median, 4),
            "pct_below_005": round(low_005 / n * 100, 1),
            "pct_below_01": round(low_01 / n * 100, 1),
            "pct_above_03": round(high_03 / n * 100, 1),
        }

        print(
            f"  {etype:<25} {n:>6} {mean:>6.3f} {median:>6.3f} {low_005:>6} {low_01:>6} {high_03:>6}",
            file=sys.stderr,
        )

    # Overall HRR relevance assessment
    all_overlaps: list[float] = [
        o for overlaps in overlap_by_type.values() for o in overlaps
    ]
    if all_overlaps:
        total_low: int = sum(1 for o in all_overlaps if o < 0.1)
        total_high: int = sum(1 for o in all_overlaps if o > 0.3)
        pct_low: float = total_low / len(all_overlaps) * 100
        pct_high: float = total_high / len(all_overlaps) * 100
        print(f"\n  HRR relevance for {name}:", file=sys.stderr)
        print(
            f"    {pct_low:.1f}% of edges have vocab overlap < 0.1 (HRR needed)",
            file=sys.stderr,
        )
        print(
            f"    {pct_high:.1f}% of edges have vocab overlap > 0.3 (FTS5 sufficient)",
            file=sys.stderr,
        )
        print(
            f"    Verdict: {'HRR adds significant value' if pct_low > 50 else 'HRR adds moderate value' if pct_low > 25 else 'FTS5 may suffice'}",
            file=sys.stderr,
        )

    # Write results
    output_dir: Path = extracted_dir / "refined"
    output_dir.mkdir(exist_ok=True)
    output: Path = output_dir / f"{name}.json"

    result: dict[str, Any] = {
        "repo": str(repo_path),
        "name": name,
        "refined_type_distribution": dict(refined_counts.most_common()),
        "raw_to_refined": {k: dict(v.most_common()) for k, v in raw_to_refined.items()},
        "vocab_overlap_by_type": type_summaries,
        "total_edges_analyzed": len(all_edges),
        "vocab_computed": total_computed,
        "vocab_skipped": total_skipped,
    }

    output.write_text(json.dumps(result, indent=2))
    print(f"\n  Written to {output}", file=sys.stderr)


if __name__ == "__main__":
    main()
