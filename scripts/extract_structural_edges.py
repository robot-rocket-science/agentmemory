"""
extract_structural_edges.py -- T0.4: Extract edges from project structure and config.

Extracts:
  1. TESTS: test file -> source file (naming convention)
  2. CROSS_REFERENCES: markdown links between docs
  3. CITES: D###/M###/ADR-### citation patterns in markdown
  4. SERVICE_DEPENDS_ON: docker-compose depends_on/links
  5. PACKAGE_DEPENDS_ON: Cargo workspace, package.json workspaces
  6. CONTAINS: directory -> file (shallow, top-level only for module structure)

Usage:
    python scripts/extract_structural_edges.py /path/to/repo [--output /path/to/output.json]

Idempotent, cached by HEAD hash.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeAlias, cast


EdgeDict: TypeAlias = dict[str, str | bool]


def git_head(repo: Path) -> str:
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return r.stdout.strip()


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


def find_files(repo: Path, extensions: set[str] | None = None) -> list[Path]:
    results: list[Path] = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if extensions is None or Path(f).suffix.lower() in extensions:
                results.append(Path(root) / f)
    return results


def _load_toml(path: Path) -> dict[str, Any] | None:
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # pyright: ignore[reportMissingImports]
        except ImportError:
            return None
    try:
        with open(path, "rb") as f:
            result: dict[str, Any] = tomllib.load(f)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType, reportReturnType]
        return result  # pyright: ignore[reportUnknownVariableType]
    except Exception:
        return None


# --- TESTS edges ---


def extract_test_edges(repo: Path) -> list[EdgeDict]:
    """Match test files to source files by naming convention."""
    all_files = find_files(repo)
    edges: list[EdgeDict] = []

    # Build lookup of source files by stem
    source_map: dict[str, list[str]] = {}
    for f in all_files:
        rel = str(f.relative_to(repo))
        stem = f.stem
        # Skip test files themselves
        if (
            stem.startswith("test_")
            or stem.endswith("_test")
            or stem.endswith(".test")
            or stem.endswith(".spec")
        ):
            continue
        if (
            "/test/" in rel
            or "/tests/" in rel
            or "/__tests__/" in rel
            or "/spec/" in rel
        ):
            continue
        if stem not in source_map:
            source_map[stem] = []
        source_map[stem].append(rel)

    # Find test files and match
    test_patterns: list[tuple[re.Pattern[str], Callable[[re.Match[str]], str]]] = [
        # Python: test_foo.py -> foo.py
        (re.compile(r"test_(.+)\.py$"), lambda m: m.group(1)),
        # Python: foo_test.py -> foo.py
        (re.compile(r"(.+)_test\.py$"), lambda m: m.group(1)),
        # JS/TS: foo.test.ts -> foo.ts, foo.spec.ts -> foo.ts
        (re.compile(r"(.+)\.(test|spec)\.(ts|tsx|js|jsx)$"), lambda m: m.group(1)),
        # Rust: typically in same file, but tests/ dir may have integration tests
        # C++: test_foo.cpp -> foo.cpp
        (re.compile(r"test_(.+)\.(cpp|cc|c)$"), lambda m: m.group(1)),
    ]

    for f in all_files:
        rel = str(f.relative_to(repo))
        name = f.name

        for pattern, stem_fn in test_patterns:
            m = pattern.match(name)
            if m:
                target_stem = stem_fn(m)
                if target_stem in source_map:
                    # Pick the most likely source file (prefer same directory tree)
                    test_parts = set(Path(rel).parts)
                    best: str | None = None
                    best_overlap = -1
                    for candidate in source_map[target_stem]:
                        cand_parts = set(Path(candidate).parts)
                        overlap = len(test_parts & cand_parts)
                        if overlap > best_overlap:
                            best_overlap = overlap
                            best = candidate
                    if best:
                        edges.append(
                            {
                                "source": rel,
                                "target": best,
                                "type": "TESTS",
                                "directed": True,
                            }
                        )
                break

    return edges


# --- CROSS_REFERENCES edges (markdown links) ---


def extract_markdown_refs(repo: Path) -> list[EdgeDict]:
    """Extract links between markdown files."""
    md_files = find_files(repo, {".md"})
    edges: list[EdgeDict] = []

    link_pattern = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

    # Build set of known markdown paths
    md_paths: set[str] = set()
    for f in md_files:
        md_paths.add(str(f.relative_to(repo)))

    for f in md_files:
        rel = str(f.relative_to(repo))
        try:
            content = f.read_text(errors="ignore")
        except OSError:
            continue

        for m in link_pattern.finditer(content):
            target = m.group(2).strip()
            # Skip URLs, anchors, images
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            # Strip anchor
            target = target.split("#")[0]
            if not target:
                continue

            # Resolve relative to current file
            resolved = (f.parent / target).resolve()
            try:
                resolved_rel = str(resolved.relative_to(repo.resolve()))
            except ValueError:
                continue

            if resolved_rel in md_paths and resolved_rel != rel:
                edges.append(
                    {
                        "source": rel,
                        "target": resolved_rel,
                        "type": "CROSS_REFERENCES",
                        "directed": True,
                    }
                )

    return edges


# --- CITES edges (D###, M###, ADR-### patterns) ---


def extract_citation_edges(
    repo: Path,
) -> tuple[list[EdgeDict], set[str], dict[str, dict[str, int]]]:
    """Detect and extract citation patterns from markdown files."""
    md_files = find_files(repo, {".md"})

    # First pass: detect which citation patterns exist
    pattern_candidates: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"\bD(\d{2,4})\b"), "D"),  # D097, D174
        (re.compile(r"\bM(\d{2,4})\b"), "M"),  # M001, M036
        (re.compile(r"\bADR[-\s]?(\d+)\b", re.I), "ADR"),  # ADR-001, ADR 1
        (re.compile(r"\bRFC[-\s]?(\d+)\b", re.I), "RFC"),  # RFC-123, RFC 7540
        (re.compile(r"\bREQ[-_](\w+)\b"), "REQ"),  # REQ-01, REQ_FEAT_1
    ]

    # Count occurrences per pattern across all files
    pattern_counts: dict[str, Counter[str]] = {
        p[1]: Counter() for p in pattern_candidates
    }
    file_citations: dict[
        str, list[tuple[str, str]]
    ] = {}  # filepath -> [(pattern_type, id)]

    for f in md_files:
        rel = str(f.relative_to(repo))
        try:
            content = f.read_text(errors="ignore")
        except OSError:
            continue

        cites: list[tuple[str, str]] = []
        for pattern, ptype in pattern_candidates:
            for m in pattern.finditer(content):
                ref_id = f"{ptype}{m.group(1)}"
                pattern_counts[ptype][ref_id] += 1
                cites.append((ptype, ref_id))

        if cites:
            file_citations[rel] = cites

    # Only use patterns that appear frequently enough to be real (>= 3 unique IDs)
    active_patterns: set[str] = {
        ptype for ptype, counter in pattern_counts.items() if len(counter) >= 3
    }

    edges: list[EdgeDict] = []
    # Build edges: file that mentions X -> file that defines/first-mentions X
    # For simplicity: every file mentioning the same ID is connected
    id_to_files: dict[str, list[str]] = {}
    for filepath, cites in file_citations.items():
        for ptype, ref_id in cites:
            if ptype in active_patterns:
                if ref_id not in id_to_files:
                    id_to_files[ref_id] = []
                if filepath not in id_to_files[ref_id]:
                    id_to_files[ref_id].append(filepath)

    # Create CITES edges between files sharing a citation
    for ref_id, files in id_to_files.items():
        if len(files) < 2:
            continue
        # Star topology: first file is the "definition", others cite it
        definition = files[0]
        for citing in files[1:]:
            if citing != definition:
                edges.append(
                    {
                        "source": citing,
                        "target": definition,
                        "type": "CITES",
                        "directed": True,
                        "citation_id": ref_id,
                    }
                )

    return (
        edges,
        active_patterns,
        {p: dict(c.most_common(10)) for p, c in pattern_counts.items()},
    )


# --- SERVICE_DEPENDS_ON (docker-compose) ---


def _parse_compose_yaml_fallback(
    compose_files: list[Path],
    repo: Path,
) -> list[EdgeDict]:
    edges: list[EdgeDict] = []
    for cf in compose_files:
        try:
            content = cf.read_text(errors="ignore")
        except OSError:
            continue
        rel = str(cf.relative_to(repo))
        current_service: str | None = None
        in_depends = False
        for line in content.split("\n"):
            svc_match = re.match(r"  (\w[\w-]*):", line)
            if svc_match and not line.strip().startswith("-"):
                current_service = svc_match.group(1)
                in_depends = False
            if "depends_on:" in line and current_service:
                in_depends = True
                continue
            if in_depends and line.strip().startswith("- "):
                dep = line.strip().lstrip("- ").strip().rstrip(":")
                if dep and current_service:
                    edges.append(
                        {
                            "source": f"service:{current_service}",
                            "target": f"service:{dep}",
                            "type": "SERVICE_DEPENDS_ON",
                            "directed": True,
                            "compose_file": rel,
                        }
                    )
            elif in_depends and not line.startswith("      "):
                in_depends = False
    return edges


def _parse_compose_yaml_lib(
    compose_files: list[Path],
    repo: Path,
    yaml: Any,
) -> list[EdgeDict]:
    edges: list[EdgeDict] = []
    for cf in compose_files:
        rel = str(cf.relative_to(repo))
        try:
            with open(cf) as fh:
                data: Any = yaml.safe_load(fh)
        except Exception:
            continue

        services_raw: Any = data.get("services", {}) if data else {}
        if not isinstance(services_raw, dict):
            continue
        for svc_key, svc_val in cast(dict[str, Any], services_raw).items():
            if not isinstance(svc_val, dict):
                continue
            svc_config: dict[str, Any] = cast(dict[str, Any], svc_val)
            deps_any: Any = svc_config.get("depends_on", [])
            if isinstance(deps_any, list):
                for dep_item in cast(list[Any], deps_any):
                    dep_str: str = str(dep_item)
                    edges.append(
                        {
                            "source": f"service:{svc_key}",
                            "target": f"service:{dep_str}",
                            "type": "SERVICE_DEPENDS_ON",
                            "directed": True,
                            "compose_file": rel,
                        }
                    )
            elif isinstance(deps_any, dict):
                for dep_key in cast(dict[str, Any], deps_any):
                    edges.append(
                        {
                            "source": f"service:{svc_key}",
                            "target": f"service:{dep_key}",
                            "type": "SERVICE_DEPENDS_ON",
                            "directed": True,
                            "compose_file": rel,
                        }
                    )
    return edges


def extract_docker_compose_edges(repo: Path) -> list[EdgeDict]:
    """Parse docker-compose.yml for service dependencies."""
    compose_files: list[Path] = []
    for name in [
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    ]:
        p = repo / name
        if p.exists():
            compose_files.append(p)
    # Also check subdirectories one level deep
    for d in repo.iterdir():
        if d.is_dir() and d.name not in SKIP_DIRS:
            for name in [
                "docker-compose.yml",
                "docker-compose.yaml",
                "compose.yml",
                "compose.yaml",
            ]:
                p = d / name
                if p.exists():
                    compose_files.append(p)

    try:
        import yaml  # pyright: ignore[reportMissingModuleSource]
    except ImportError:
        return _parse_compose_yaml_fallback(compose_files, repo)

    return _parse_compose_yaml_lib(compose_files, repo, yaml)


# --- PACKAGE_DEPENDS_ON (workspace-level) ---


def extract_cargo_workspace_edges(repo: Path) -> list[EdgeDict]:
    """Parse Cargo.toml workspace for internal dependencies."""
    edges: list[EdgeDict] = []
    root_cargo = repo / "Cargo.toml"
    if not root_cargo.exists():
        return edges

    data = _load_toml(root_cargo)
    if data is None:
        return edges

    workspace: dict[str, Any] = data.get("workspace", {})
    members_raw: Any = workspace.get("members", [])
    members: list[Any] = (
        cast(list[Any], members_raw) if isinstance(members_raw, list) else []
    )

    # Find all member Cargo.tomls
    member_cargos: dict[str, str] = {}
    for member_pattern_raw in members:
        member_pattern: str = str(member_pattern_raw)
        # Handle glob patterns like "crates/*"
        if "*" in member_pattern:
            base = repo / member_pattern.replace("/*", "")
            if base.exists():
                for d_entry in base.iterdir():
                    ct = d_entry / "Cargo.toml"
                    if ct.exists():
                        mdata = _load_toml(ct)
                        if mdata is not None:
                            pkg_name: str = mdata.get("package", {}).get(
                                "name", d_entry.name
                            )
                            member_cargos[pkg_name] = str(ct.relative_to(repo))
        else:
            ct = repo / member_pattern / "Cargo.toml"
            if ct.exists():
                mdata2 = _load_toml(ct)
                if mdata2 is not None:
                    pkg_name2: str = mdata2.get("package", {}).get(
                        "name", Path(member_pattern).name
                    )
                    member_cargos[pkg_name2] = str(ct.relative_to(repo))

    # For each member, check dependencies against other members
    for pkg_name_iter, cargo_path in member_cargos.items():
        ct = repo / cargo_path
        mdata3 = _load_toml(ct)
        if mdata3 is None:
            continue

        for dep_section in ["dependencies", "dev-dependencies", "build-dependencies"]:
            deps: dict[str, Any] = mdata3.get(dep_section, {})
            for dep_name in deps:
                if dep_name in member_cargos and dep_name != pkg_name_iter:
                    edges.append(
                        {
                            "source": f"package:{pkg_name_iter}",
                            "target": f"package:{dep_name}",
                            "type": "PACKAGE_DEPENDS_ON",
                            "directed": True,
                        }
                    )

    return edges


def extract_package_json_workspace_edges(repo: Path) -> list[EdgeDict]:
    """Parse package.json workspaces for internal dependencies."""
    edges: list[EdgeDict] = []
    root_pkg = repo / "package.json"
    if not root_pkg.exists():
        return edges

    try:
        data: Any = json.loads(root_pkg.read_text())
    except Exception:
        return edges

    workspaces_raw: Any = data.get("workspaces", [])
    workspaces: list[Any]
    if isinstance(workspaces_raw, dict):
        pkgs: Any = cast(dict[str, Any], workspaces_raw).get("packages", [])
        workspaces = cast(list[Any], pkgs) if isinstance(pkgs, list) else []
    elif isinstance(workspaces_raw, list):
        workspaces = cast(list[Any], workspaces_raw)
    else:
        workspaces = []

    # Find all workspace package.jsons
    workspace_pkgs: dict[str, str] = {}
    for ws_pattern_raw in workspaces:
        ws_pattern: str = str(ws_pattern_raw)
        base: str = ws_pattern.replace("/*", "").replace("*", "")
        base_dir = repo / base
        if base_dir.exists() and base_dir.is_dir():
            for d_entry in base_dir.iterdir():
                pkg = d_entry / "package.json"
                if pkg.exists():
                    try:
                        pdata: Any = json.loads(pkg.read_text())
                        ws_name: str = pdata.get("name", d_entry.name)
                        workspace_pkgs[ws_name] = str(pkg.relative_to(repo))
                    except Exception:
                        pass

    # Check internal dependencies
    for pkg_name, pkg_path in workspace_pkgs.items():
        try:
            pdata2: Any = json.loads((repo / pkg_path).read_text())
        except Exception:
            continue

        for dep_section in ["dependencies", "devDependencies", "peerDependencies"]:
            deps_raw: Any = pdata2.get(dep_section, {})
            if not isinstance(deps_raw, dict):
                continue
            for dep_name in cast(dict[str, Any], deps_raw):
                if dep_name in workspace_pkgs and dep_name != pkg_name:
                    edges.append(
                        {
                            "source": f"package:{pkg_name}",
                            "target": f"package:{dep_name}",
                            "type": "PACKAGE_DEPENDS_ON",
                            "directed": True,
                        }
                    )

    return edges


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} /path/to/repo [--output path]")
        sys.exit(1)

    repo = Path(sys.argv[1]).resolve()
    output_path: Path | None = None

    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--output" and i + 1 < len(args):
            output_path = Path(args[i + 1])
            i += 2
        else:
            i += 1

    if output_path is None:
        output_path = repo / "structural_edges.json"

    head = git_head(repo)
    if output_path.exists():
        try:
            existing: Any = json.loads(output_path.read_text())
            if existing.get("head") == head:
                print(f"[cached] {repo.name} HEAD={head[:8]}", file=sys.stderr)
                edge_types: dict[str, Any] = existing.get("summary", {}).get(
                    "edges_by_type", {}
                )
                for etype, count in edge_types.items():
                    print(f"  {etype}: {count}", file=sys.stderr)
                return
        except (json.JSONDecodeError, KeyError):
            pass

    print(f"[extract] {repo.name} HEAD={head[:8]}", file=sys.stderr)

    all_edges: list[EdgeDict] = []
    edges_by_type: dict[str, int] = {}

    # TESTS
    test_edges = extract_test_edges(repo)
    all_edges.extend(test_edges)
    edges_by_type["TESTS"] = len(test_edges)
    print(f"  TESTS: {len(test_edges)} edges", file=sys.stderr)

    # CROSS_REFERENCES
    md_ref_edges = extract_markdown_refs(repo)
    all_edges.extend(md_ref_edges)
    edges_by_type["CROSS_REFERENCES"] = len(md_ref_edges)
    print(f"  CROSS_REFERENCES: {len(md_ref_edges)} edges", file=sys.stderr)

    # CITES
    cite_edges, active_patterns, pattern_stats = extract_citation_edges(repo)
    all_edges.extend(cite_edges)
    edges_by_type["CITES"] = len(cite_edges)
    print(
        f"  CITES: {len(cite_edges)} edges (active patterns: {active_patterns})",
        file=sys.stderr,
    )

    # SERVICE_DEPENDS_ON
    docker_edges = extract_docker_compose_edges(repo)
    all_edges.extend(docker_edges)
    edges_by_type["SERVICE_DEPENDS_ON"] = len(docker_edges)
    print(f"  SERVICE_DEPENDS_ON: {len(docker_edges)} edges", file=sys.stderr)

    # PACKAGE_DEPENDS_ON
    cargo_edges = extract_cargo_workspace_edges(repo)
    pkg_json_edges = extract_package_json_workspace_edges(repo)
    pkg_edges = cargo_edges + pkg_json_edges
    all_edges.extend(pkg_edges)
    edges_by_type["PACKAGE_DEPENDS_ON"] = len(pkg_edges)
    print(
        f"  PACKAGE_DEPENDS_ON: {len(pkg_edges)} edges (cargo: {len(cargo_edges)}, npm: {len(pkg_json_edges)})",
        file=sys.stderr,
    )

    total = len(all_edges)
    print(f"  total: {total} structural edges", file=sys.stderr)

    summary: dict[str, int | dict[str, int] | list[str]] = {
        "total_edges": total,
        "edges_by_type": edges_by_type,
        "citation_patterns_detected": {
            p: len(c) for p, c in pattern_stats.items() if c
        },
        "citation_active_patterns": sorted(active_patterns),
    }

    result: dict[
        str, str | dict[str, int | dict[str, int] | list[str]] | list[EdgeDict]
    ] = {
        "repo": str(repo),
        "name": repo.name,
        "head": head,
        "summary": summary,
        "edges": all_edges,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2))
    print(f"  written to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
