"""
classify_nodes.py -- T0.5: Automatic node type classification.

Classifies every file in a repo into a node type based on:
  1. Path patterns (src/, tests/, docs/, .planning/, etc.)
  2. File extension
  3. Lightweight content analysis (test markers, config patterns)

Usage:
    python scripts/classify_nodes.py /path/to/repo [--output /path/to/output.json]

Idempotent, cached by HEAD hash.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def git_head(repo: Path) -> str:
    r: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo, capture_output=True, text=True, timeout=5,
    )
    return r.stdout.strip()


SKIP_DIRS: set[str] = {
    ".git", "node_modules", "target", ".venv", "venv", "__pycache__",
    ".mypy_cache", ".ruff_cache", "dist", "build", ".tox", ".eggs",
    ".pytest_cache", "vendor", "third_party", "3rdparty",
}

# Path patterns -> node type (checked in order, first match wins)
PATH_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(^|/)tests?/"), "TEST"),
    (re.compile(r"(^|/)__tests__/"), "TEST"),
    (re.compile(r"(^|/)spec/"), "TEST"),
    (re.compile(r"(^|/)test_[^/]+\.(py|rs|cpp|c|js|ts)$"), "TEST"),
    (re.compile(r"(^|/)[^/]+\.(test|spec)\.(ts|tsx|js|jsx)$"), "TEST"),
    (re.compile(r"(^|/)\.planning/"), "PLANNING"),
    (re.compile(r"(^|/)\.gsd/"), "PLANNING"),
    (re.compile(r"(^|/)docs?/"), "DOCUMENTATION"),
    (re.compile(r"(^|/)examples?/"), "EXAMPLE"),
    (re.compile(r"(^|/)demo/"), "EXAMPLE"),
    (re.compile(r"(^|/)scripts?/"), "SCRIPT"),
    (re.compile(r"(^|/)bin/"), "SCRIPT"),
    (re.compile(r"(^|/)\.github/"), "CI_CONFIG"),
    (re.compile(r"(^|/)\.circleci/"), "CI_CONFIG"),
    (re.compile(r"(^|/)configs?/"), "CONFIG"),
    (re.compile(r"(^|/)infra/"), "INFRASTRUCTURE"),
    (re.compile(r"(^|/)deploy/"), "INFRASTRUCTURE"),
    (re.compile(r"(^|/)migrations?/"), "MIGRATION"),
    (re.compile(r"(^|/)benches?/"), "BENCHMARK"),
    (re.compile(r"(^|/)benchmarks?/"), "BENCHMARK"),
]

# Extension -> node type (fallback after path rules)
EXT_RULES: dict[str, str] = {
    ".md": "DOCUMENT",
    ".rst": "DOCUMENT",
    ".txt": "DOCUMENT",
    ".yml": "CONFIG",
    ".yaml": "CONFIG",
    ".toml": "CONFIG",
    ".json": "DATA",
    ".lock": "LOCKFILE",
    ".sh": "SCRIPT",
    ".bash": "SCRIPT",
    ".dockerfile": "INFRASTRUCTURE",
    ".tf": "INFRASTRUCTURE",
    ".sql": "MIGRATION",
    ".proto": "SCHEMA",
}

CODE_EXTENSIONS: set[str] = {
    ".py", ".rs", ".go", ".ts", ".tsx", ".js", ".jsx",
    ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hxx",
    ".java", ".rb", ".swift", ".kt", ".cs",
}

# Filename exact matches
FILENAME_RULES: dict[str, str] = {
    "Dockerfile": "INFRASTRUCTURE",
    "docker-compose.yml": "INFRASTRUCTURE",
    "docker-compose.yaml": "INFRASTRUCTURE",
    "Makefile": "BUILD",
    "CMakeLists.txt": "BUILD",
    "Cargo.toml": "BUILD",
    "package.json": "BUILD",
    "pyproject.toml": "BUILD",
    "setup.py": "BUILD",
    "setup.cfg": "BUILD",
    "go.mod": "BUILD",
    ".gitignore": "CONFIG",
    ".gitattributes": "CONFIG",
    "LICENSE": "DOCUMENT",
    "LICENSE.md": "DOCUMENT",
    "CHANGELOG.md": "DOCUMENT",
    "README.md": "DOCUMENT",
    "CLAUDE.md": "CONFIG",
}


def classify_file(rel_path: str, content_hint: str | None = None) -> str:
    """Classify a file into a node type."""
    filename: str = os.path.basename(rel_path)
    ext: str = Path(filename).suffix.lower()

    # Filename exact match (highest priority)
    if filename in FILENAME_RULES:
        return FILENAME_RULES[filename]

    # Path pattern match
    for pattern, node_type in PATH_RULES:
        if pattern.search(rel_path):
            return node_type

    # Content hint (lightweight check)
    if content_hint:
        if "def test_" in content_hint or "#[test]" in content_hint or "describe(" in content_hint:
            return "TEST"

    # Extension match
    if ext in EXT_RULES:
        return EXT_RULES[ext]

    # Code files
    if ext in CODE_EXTENSIONS:
        # Check if it's in a src-like directory
        if re.search(r"(^|/)src/", rel_path) or re.search(r"(^|/)lib/", rel_path):
            return "SOURCE"
        return "SOURCE"  # default for code files

    return "OTHER"


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
        output_path = repo / "node_types.json"

    head: str = git_head(repo)
    if output_path.exists():
        try:
            existing: dict[str, Any] = json.loads(output_path.read_text())
            if existing.get("head") == head:
                print(f"[cached] {repo.name} HEAD={head[:8]}", file=sys.stderr)
                type_dist: dict[str, Any] = existing.get("summary", {}).get("type_distribution", {})
                for ntype, count in sorted(type_dist.items()):
                    print(f"  {ntype}: {count}", file=sys.stderr)
                return
        except (json.JSONDecodeError, KeyError):
            pass

    print(f"[classify] {repo.name} HEAD={head[:8]}", file=sys.stderr)

    classifications: dict[str, str] = {}
    type_counts: Counter[str] = Counter()

    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath: Path = Path(root) / f
            rel: str = str(fpath.relative_to(repo))

            # Light content check for code files only
            content_hint: str | None = None
            ext: str = Path(f).suffix.lower()
            if ext in CODE_EXTENSIONS:
                try:
                    # Read first 2KB for content hints
                    with open(fpath, "r", errors="ignore") as fh:
                        content_hint = fh.read(2048)
                except OSError:
                    pass

            node_type: str = classify_file(rel, content_hint)
            classifications[rel] = node_type
            type_counts[node_type] += 1

    total: int = sum(type_counts.values())
    unknown: int = type_counts.get("OTHER", 0)

    print(f"  total files: {total}", file=sys.stderr)
    print(f"  classified: {total - unknown} ({(total - unknown) / max(total, 1) * 100:.1f}%)", file=sys.stderr)
    print(f"  distribution:", file=sys.stderr)
    for ntype, count in type_counts.most_common():
        print(f"    {ntype}: {count} ({count / max(total, 1) * 100:.1f}%)", file=sys.stderr)

    summary: dict[str, Any] = {
        "total_files": total,
        "classified_files": total - unknown,
        "classification_rate": round((total - unknown) / max(total, 1), 3),
        "type_distribution": dict(type_counts.most_common()),
    }

    result: dict[str, Any] = {
        "repo": str(repo),
        "name": repo.name,
        "head": head,
        "summary": summary,
        "classifications": classifications,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2))
    print(f"  written to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
