"""
corpus_map.py -- Phase 1: Map each repo in the corpus to a basic profile.

Produces a JSON manifest describing each repo's:
- Language breakdown (by file extension)
- File count and total LOC
- Git history stats (commit count, date range, contributor count)
- Detected structural patterns (has .planning/, has Makefile, has Cargo.toml, etc.)
- Candidate graph construction methods

This is a read-only scan. No graph construction yet -- just characterization
so we can plan extraction strategies per repo.

Idempotent: re-running produces the same output. Cached: skips repos whose
HEAD hasn't changed since last scan.

Usage:
    python scripts/corpus_map.py /path/to/corpus [--force]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from datetime import datetime


CACHE_FILE: str = "corpus_manifest.json"

# File extensions -> language mapping
EXT_LANG: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".rs": "Rust",
    ".go": "Go",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".c": "C",
    ".h": "C/C++ Header",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++ Header",
    ".java": "Java",
    ".rb": "Ruby",
    ".md": "Markdown",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bash": "Shell",
    ".tf": "Terraform",
    ".proto": "Protobuf",
}

# Structural markers -> what they indicate
MARKERS: dict[str, str] = {
    "Cargo.toml": "rust_project",
    "pyproject.toml": "python_project",
    "setup.py": "python_project",
    "package.json": "node_project",
    "go.mod": "go_project",
    "Makefile": "has_makefile",
    "CMakeLists.txt": "cmake_project",
    "docker-compose.yml": "has_docker_compose",
    "docker-compose.yaml": "has_docker_compose",
    "Dockerfile": "has_dockerfile",
    ".planning": "has_planning_dir",
    ".gsd": "has_gsd",
    "DECISIONS.md": "has_decisions",
    "KNOWLEDGE.md": "has_knowledge",
    "CLAUDE.md": "has_claude_md",
    "README.md": "has_readme",
    "CHANGELOG.md": "has_changelog",
    ".github": "has_github_actions",
    "Kconfig": "has_kconfig",
    "ansible.cfg": "has_ansible",
    "terraform": "has_terraform",
}

# Skip directories during scan
SKIP_DIRS: set[str] = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "target",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".tox",
    ".eggs",
    ".pytest_cache",
    "vendor",
    "third_party",
    "3rdparty",
}


def git_head(repo_path: Path) -> str | None:
    """Get current HEAD commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def git_stats(repo_path: Path) -> dict[str, int | str | None]:
    """Extract git history statistics."""
    stats: dict[str, int | str | None] = {
        "commits": 0,
        "contributors": 0,
        "first_commit": None,
        "last_commit": None,
    }

    try:
        # Commit count
        r = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            stats["commits"] = int(r.stdout.strip())

        # Date range and contributor count
        r = subprocess.run(
            ["git", "log", "--format=%aI%n%aN", "--no-merges"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            lines = r.stdout.strip().split("\n")
            dates: list[str] = []
            authors: set[str] = set()
            for i in range(0, len(lines) - 1, 2):
                dates.append(lines[i])
                authors.add(lines[i + 1])
            if dates:
                stats["first_commit"] = min(dates)[:10]
                stats["last_commit"] = max(dates)[:10]
            stats["contributors"] = len(authors)
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass

    return stats


def scan_files(repo_path: Path) -> dict[str, int | dict[str, int] | list[str]]:
    """Scan file tree for language breakdown and structural markers."""
    ext_counts: Counter[str] = Counter()
    loc_by_lang: Counter[str] = Counter()
    total_files: int = 0
    markers_found: list[str] = []

    # Check top-level markers
    for marker, label in MARKERS.items():
        if (repo_path / marker).exists():
            markers_found.append(label)

    # Walk file tree
    for root, dirs, files in os.walk(repo_path):
        # Prune skip directories
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for f in files:
            total_files += 1
            ext = Path(f).suffix.lower()
            if ext in EXT_LANG:
                lang = EXT_LANG[ext]
                ext_counts[lang] += 1
                # Count LOC for code files (not configs/docs)
                if lang not in ("Markdown", "YAML", "JSON", "TOML"):
                    fpath = Path(root) / f
                    try:
                        loc = sum(1 for _ in fpath.open("r", errors="ignore"))
                        loc_by_lang[lang] += loc
                    except (OSError, UnicodeDecodeError):
                        pass

    return {
        "total_files": total_files,
        "language_breakdown": dict(ext_counts.most_common()),
        "loc_by_language": dict(loc_by_lang.most_common()),
        "structural_markers": sorted(set(markers_found)),
    }


def infer_graph_methods(markers: list[str], languages: dict[str, int]) -> list[str]:
    """Suggest applicable graph construction methods based on project structure."""
    methods: list[str] = []

    # Universal
    methods.append("git_cochange")
    methods.append("git_commit_beliefs")

    # Language-specific import parsing
    if "Python" in languages:
        methods.append("python_imports")
    if "Rust" in languages:
        methods.append("rust_use_statements")
    if "Go" in languages:
        methods.append("go_imports")
    if "TypeScript" in languages or "JavaScript" in languages:
        methods.append("js_ts_imports")
    if "C" in languages or "C++" in languages:
        methods.append("c_cpp_includes")

    # Structure-based
    if "has_planning_dir" in markers or "has_gsd" in markers:
        methods.append("planning_doc_structure")
    if "has_decisions" in markers:
        methods.append("decision_citations")
    if "has_docker_compose" in markers:
        methods.append("docker_compose_services")
    if "has_ansible" in markers:
        methods.append("ansible_playbook_roles")
    if "has_kconfig" in markers:
        methods.append("kconfig_dependencies")
    if "cmake_project" in markers:
        methods.append("cmake_target_deps")
    if "node_project" in markers:
        methods.append("package_json_deps")
    if "rust_project" in markers:
        methods.append("cargo_workspace_deps")
    if "go_project" in markers:
        methods.append("go_mod_deps")

    # Doc-based
    if "Markdown" in languages and languages.get("Markdown", 0) > 5:
        methods.append("markdown_cross_references")

    return methods


def scan_repo(
    repo_path: Path,
) -> dict[
    str,
    str
    | None
    | dict[str, int | str | None]
    | dict[str, int | dict[str, int] | list[str]]
    | list[str],
]:
    """Full scan of a single repo."""
    head = git_head(repo_path)
    git = git_stats(repo_path)
    files = scan_files(repo_path)
    methods = infer_graph_methods(
        files["structural_markers"],  # type: ignore[arg-type]
        files["language_breakdown"],  # type: ignore[arg-type]
    )

    return {
        "path": str(repo_path),
        "name": repo_path.name,
        "head": head,
        "scanned_at": datetime.now().isoformat()[:19],
        "git": git,
        "files": files,
        "candidate_graph_methods": methods,
    }


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} /path/to/corpus [--force]")
        sys.exit(1)

    corpus_root = Path(sys.argv[1])
    force = "--force" in sys.argv

    if not corpus_root.exists():
        print(f"Corpus root not found: {corpus_root}")
        sys.exit(1)

    # Load cache
    cache_path = corpus_root / CACHE_FILE
    cache: dict[str, object] = {}
    if cache_path.exists() and not force:
        cache = json.loads(cache_path.read_text())

    # Find all repos (directories with .git)
    repos: list[tuple[str, str, Path]] = []
    for category_dir in sorted(corpus_root.iterdir()):
        if not category_dir.is_dir() or category_dir.name in ("extracted", "results"):
            continue
        # Personal projects are directly under personal/
        # Public projects are under public/category/repo
        if category_dir.name == "personal":
            for repo_dir in sorted(category_dir.iterdir()):
                if (repo_dir / ".git").exists():
                    repos.append(("personal", repo_dir.name, repo_dir))
        elif category_dir.name == "public":
            for cat in sorted(category_dir.iterdir()):
                if not cat.is_dir():
                    continue
                for repo_dir in sorted(cat.iterdir()):
                    if (repo_dir / ".git").exists():
                        repos.append((f"public/{cat.name}", repo_dir.name, repo_dir))

    print(f"Found {len(repos)} repos to scan", file=sys.stderr)

    manifest: dict[str, object] = {}
    scanned = 0
    cached = 0

    for category, name, path in repos:
        key = f"{category}/{name}"
        head = git_head(path)

        # Cache check: skip if HEAD unchanged
        if (
            key in cache
            and isinstance(cache[key], dict)
            and cache[key].get("head") == head
            and not force
        ):  # type: ignore[union-attr]
            manifest[key] = cache[key]
            cached += 1
            print(f"  [cached] {key}", file=sys.stderr)
            continue

        print(f"  [scan]   {key}", file=sys.stderr)
        entry = scan_repo(path)
        entry["category"] = category
        manifest[key] = entry
        scanned += 1

    # Write manifest
    cache_path.write_text(json.dumps(manifest, indent=2, sort_keys=False))
    print(
        f"\nDone: {scanned} scanned, {cached} cached, {len(manifest)} total",
        file=sys.stderr,
    )
    print(f"Manifest: {cache_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
