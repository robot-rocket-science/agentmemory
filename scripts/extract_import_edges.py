"""
extract_import_edges.py -- T0.3: Extract IMPORTS edges from source files.

Parses import/include/use statements and resolves them to file paths within the repo.

Supported languages:
  - Rust: use crate::X, mod X, use super::X
  - Python: import X, from X import Y
  - TypeScript/JavaScript: import ... from 'X', require('X')
  - C/C++: #include "X" (local only, not system headers)

Usage:
    python scripts/extract_import_edges.py /path/to/repo [--output /path/to/output.json]

Idempotent, cached by HEAD hash.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

EdgeDict = dict[str, str | bool]


def git_head(repo: Path) -> str:
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return r.stdout.strip()


def find_files(repo: Path, extensions: set[str]) -> list[Path]:
    """Find all files with given extensions, skipping build/vendor dirs."""
    skip: set[str] = {
        ".git",
        "node_modules",
        "target",
        ".venv",
        "venv",
        "vendor",
        "third_party",
        "3rdparty",
        "dist",
        "build",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
    }
    results: list[Path] = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if Path(f).suffix.lower() in extensions:
                results.append(Path(root) / f)
    return results


# --- Rust ---


def extract_rust_imports(repo: Path) -> list[EdgeDict]:
    """Parse Rust use/mod statements and resolve to file paths."""
    files: list[Path] = find_files(repo, {".rs"})
    edges: list[EdgeDict] = []

    # Build a map of module paths to file paths
    mod_to_file: dict[str, str] = {}
    for f in files:
        rel = f.relative_to(repo)
        # Convert path to module path: src/wire/ethernet.rs -> wire::ethernet
        parts = list(rel.parts)
        if parts and parts[0] == "src":
            parts = parts[1:]
        # Remove .rs extension
        if parts:
            parts[-1] = parts[-1].replace(".rs", "")
        # mod.rs -> parent module name
        if parts and parts[-1] == "mod":
            parts = parts[:-1]
        # lib.rs -> crate root
        if parts and parts[-1] == "lib":
            parts = parts[:-1]
        # main.rs -> crate root
        if parts and parts[-1] == "main":
            parts = parts[:-1]

        mod_path = "::".join(parts)
        if mod_path:
            mod_to_file[mod_path] = str(rel)

    # Parse use statements
    use_pattern = re.compile(
        r"^\s*use\s+(?:crate::)?(\S+?)(?:\s*;|\s*\{)", re.MULTILINE
    )
    mod_pattern = re.compile(r"^\s*(?:pub\s+)?mod\s+(\w+)\s*;", re.MULTILINE)

    for f in files:
        rel = str(f.relative_to(repo))
        try:
            content = f.read_text(errors="ignore")
        except OSError:
            continue

        # use crate::wire::ethernet -> resolve wire::ethernet
        for m in use_pattern.finditer(content):
            import_path = m.group(1).rstrip(";{").strip()
            # Remove trailing ::* or ::{...}
            import_path = re.sub(r"::(\*|\{.*\})$", "", import_path)

            # Try progressively shorter prefixes to find the module
            parts = import_path.split("::")
            for end in range(len(parts), 0, -1):
                candidate = "::".join(parts[:end])
                if candidate in mod_to_file and mod_to_file[candidate] != rel:
                    edges.append(
                        {
                            "source": rel,
                            "target": mod_to_file[candidate],
                            "type": "IMPORTS",
                            "directed": True,
                            "raw_import": import_path,
                        }
                    )
                    break

        # mod foo; -> resolve to foo.rs or foo/mod.rs
        for m in mod_pattern.finditer(content):
            mod_name = m.group(1)
            # Get the directory of the current file
            parent_mod = str(f.relative_to(repo).parent)
            if parent_mod == ".":
                parent_mod = ""

            # Check for mod_name.rs or mod_name/mod.rs
            candidates: list[str] = []
            if parent_mod:
                candidates.append(os.path.join(parent_mod, f"{mod_name}.rs"))
                candidates.append(os.path.join(parent_mod, mod_name, "mod.rs"))
            else:
                candidates.append(f"{mod_name}.rs")
                candidates.append(os.path.join(mod_name, "mod.rs"))
                candidates.append(os.path.join("src", f"{mod_name}.rs"))
                candidates.append(os.path.join("src", mod_name, "mod.rs"))

            for c in candidates:
                if (repo / c).exists() and c != rel:
                    edges.append(
                        {
                            "source": rel,
                            "target": c,
                            "type": "IMPORTS",
                            "directed": True,
                            "raw_import": f"mod {mod_name}",
                        }
                    )
                    break

    return edges


# --- Python ---


def extract_python_imports(repo: Path) -> list[EdgeDict]:
    """Parse Python import statements and resolve to file paths."""
    files: list[Path] = find_files(repo, {".py"})
    edges: list[EdgeDict] = []

    # Build module-to-file map
    mod_to_file: dict[str, str] = {}
    for f in files:
        rel = f.relative_to(repo)
        parts = list(rel.parts)
        if parts:
            parts[-1] = parts[-1].replace(".py", "")
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        mod_path = ".".join(parts)
        if mod_path:
            mod_to_file[mod_path] = str(rel)

    import_pattern = re.compile(
        r"^\s*(?:from\s+(\S+)\s+import|import\s+(\S+))", re.MULTILINE
    )

    for f in files:
        rel = str(f.relative_to(repo))
        try:
            content = f.read_text(errors="ignore")
        except OSError:
            continue

        for m in import_pattern.finditer(content):
            import_path = m.group(1) or m.group(2)
            if not import_path:
                continue
            # Strip trailing items for "import a, b, c"
            import_path = import_path.split(",")[0].strip()
            # Handle relative imports
            if import_path.startswith("."):
                # Resolve relative to current file's package
                parent_parts = list(Path(rel).parent.parts)
                dots = len(import_path) - len(import_path.lstrip("."))
                if dots <= len(parent_parts):
                    base = parent_parts[: len(parent_parts) - dots + 1]
                    rest = import_path.lstrip(".")
                    if rest:
                        import_path = ".".join(base) + "." + rest
                    else:
                        import_path = ".".join(base)

            # Try progressively shorter prefixes
            parts = import_path.split(".")
            for end in range(len(parts), 0, -1):
                candidate = ".".join(parts[:end])
                if candidate in mod_to_file and mod_to_file[candidate] != rel:
                    edges.append(
                        {
                            "source": rel,
                            "target": mod_to_file[candidate],
                            "type": "IMPORTS",
                            "directed": True,
                            "raw_import": import_path,
                        }
                    )
                    break

    return edges


# --- TypeScript/JavaScript ---


def extract_ts_js_imports(repo: Path) -> list[EdgeDict]:
    """Parse TS/JS import/require statements and resolve to file paths."""
    files: list[Path] = find_files(repo, {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"})
    edges: list[EdgeDict] = []

    import_pattern = re.compile(
        r"""(?:import\s+.*?\s+from\s+['"](.+?)['"]|require\s*\(\s*['"](.+?)['"]\s*\))""",
        re.MULTILINE,
    )

    for f in files:
        rel = str(f.relative_to(repo))
        try:
            content = f.read_text(errors="ignore")
        except OSError:
            continue

        for m in import_pattern.finditer(content):
            import_path = m.group(1) or m.group(2)
            if not import_path:
                continue
            # Only resolve relative imports (starts with . or ..)
            if not import_path.startswith("."):
                continue

            # Resolve relative to current file
            base_dir = (f.parent).resolve()
            candidate_base = (base_dir / import_path).resolve()

            # Try extensions
            extensions = [".ts", ".tsx", ".js", ".jsx", ".mjs", ""]
            index_files = ["index.ts", "index.tsx", "index.js", "index.jsx"]

            resolved: Path | None = None
            for ext in extensions:
                check = Path(str(candidate_base) + ext)
                if check.exists() and check.is_file():
                    resolved = check
                    break

            # Try index files in directory
            if resolved is None and candidate_base.is_dir():
                for idx in index_files:
                    check = candidate_base / idx
                    if check.exists():
                        resolved = check
                        break

            if resolved is not None:
                try:
                    target_rel = str(resolved.relative_to(repo.resolve()))
                    if target_rel != rel:
                        edges.append(
                            {
                                "source": rel,
                                "target": target_rel,
                                "type": "IMPORTS",
                                "directed": True,
                                "raw_import": import_path,
                            }
                        )
                except ValueError:
                    pass

    return edges


# --- C/C++ ---


def extract_c_cpp_includes(repo: Path) -> list[EdgeDict]:
    """Parse C/C++ local #include statements and resolve to file paths."""
    files: list[Path] = find_files(
        repo, {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hxx"}
    )
    edges: list[EdgeDict] = []

    include_pattern = re.compile(r'^\s*#include\s+"([^"]+)"', re.MULTILINE)

    # Build a map of basename to full paths (for ambiguous includes)
    basename_to_paths: dict[str, list[str]] = {}
    for f in files:
        rel = str(f.relative_to(repo))
        name = f.name
        if name not in basename_to_paths:
            basename_to_paths[name] = []
        basename_to_paths[name].append(rel)

    for f in files:
        rel = str(f.relative_to(repo))
        try:
            content = f.read_text(errors="ignore")
        except OSError:
            continue

        for m in include_pattern.finditer(content):
            include_path = m.group(1)

            # Try relative to current file first
            resolved: str | None = None
            candidate = (f.parent / include_path).resolve()
            if candidate.exists():
                try:
                    resolved = str(candidate.relative_to(repo.resolve()))
                except ValueError:
                    pass

            # Try basename lookup as fallback
            if resolved is None:
                basename = os.path.basename(include_path)
                if basename in basename_to_paths:
                    candidates = basename_to_paths[basename]
                    if len(candidates) == 1:
                        resolved = candidates[0]

            if resolved is not None and resolved != rel:
                edges.append(
                    {
                        "source": rel,
                        "target": resolved,
                        "type": "IMPORTS",
                        "directed": True,
                        "raw_import": include_path,
                    }
                )

    return edges


def detect_languages(repo: Path) -> set[str]:
    """Detect languages present in repo."""
    langs: set[str] = set()
    ext_map: dict[str, str] = {
        ".py": "python",
        ".rs": "rust",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".cxx": "cpp",
        ".hpp": "cpp",
    }
    for _root, dirs, files in os.walk(repo):
        dirs[:] = [
            d
            for d in dirs
            if d not in {".git", "node_modules", "target", ".venv", "vendor"}
        ]
        for f in files:
            ext = Path(f).suffix.lower()
            if ext in ext_map:
                langs.add(ext_map[ext])
        if len(langs) >= 4:
            break  # early exit, we've found enough
    return langs


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
        output_path = repo / "import_edges.json"

    # Cache check
    head: str = git_head(repo)
    if output_path.exists():
        try:
            existing: Any = json.loads(output_path.read_text())
            if existing.get("head") == head:
                print(f"[cached] {repo.name} HEAD={head[:8]}", file=sys.stderr)
                for lang, count in (
                    existing.get("summary", {}).get("edges_by_language", {}).items()
                ):
                    print(f"  {lang}: {count} edges", file=sys.stderr)
                return
        except (json.JSONDecodeError, KeyError):
            pass

    print(f"[extract] {repo.name} HEAD={head[:8]}", file=sys.stderr)

    # Detect languages
    langs: set[str] = detect_languages(repo)
    print(f"  detected languages: {sorted(langs)}", file=sys.stderr)

    all_edges: list[EdgeDict] = []
    edges_by_lang: dict[str, int] = {}

    if "rust" in langs:
        rust_edges: list[EdgeDict] = extract_rust_imports(repo)
        all_edges.extend(rust_edges)
        edges_by_lang["rust"] = len(rust_edges)
        print(f"  rust: {len(rust_edges)} import edges", file=sys.stderr)

    if "python" in langs:
        py_edges: list[EdgeDict] = extract_python_imports(repo)
        all_edges.extend(py_edges)
        edges_by_lang["python"] = len(py_edges)
        print(f"  python: {len(py_edges)} import edges", file=sys.stderr)

    if "typescript" in langs or "javascript" in langs:
        ts_edges: list[EdgeDict] = extract_ts_js_imports(repo)
        all_edges.extend(ts_edges)
        edges_by_lang["typescript_javascript"] = len(ts_edges)
        print(f"  ts/js: {len(ts_edges)} import edges", file=sys.stderr)

    if "c" in langs or "cpp" in langs:
        c_edges: list[EdgeDict] = extract_c_cpp_includes(repo)
        all_edges.extend(c_edges)
        edges_by_lang["c_cpp"] = len(c_edges)
        print(f"  c/c++: {len(c_edges)} include edges", file=sys.stderr)

    # Deduplicate
    seen: set[tuple[str | bool, str | bool]] = set()
    unique_edges: list[EdgeDict] = []
    for e in all_edges:
        key: tuple[str | bool, str | bool] = (e["source"], e["target"])
        if key not in seen:
            seen.add(key)
            unique_edges.append(e)

    # Unique files involved
    sources: set[str | bool] = set(e["source"] for e in unique_edges)
    targets: set[str | bool] = set(e["target"] for e in unique_edges)

    summary: dict[str, int | list[str] | dict[str, int]] = {
        "total_edges": len(unique_edges),
        "unique_sources": len(sources),
        "unique_targets": len(targets),
        "edges_by_language": edges_by_lang,
        "languages_detected": sorted(langs),
    }

    print(
        f"  total: {len(unique_edges)} unique import edges ({len(sources)} sources -> {len(targets)} targets)",
        file=sys.stderr,
    )

    result: dict[
        str, str | dict[str, int | list[str] | dict[str, int]] | list[EdgeDict]
    ] = {
        "repo": str(repo),
        "name": repo.name,
        "head": head,
        "summary": summary,
        "edges": unique_edges,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2))
    print(f"  written to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
