"""
extract_git_edges.py -- T0.2: Extract edges from git history.

Produces three edge types:
  1. CO_CHANGED: files modified in the same commit (weighted by frequency)
  2. COMMIT_BELIEF: commit message sentences -> files touched
  3. REFERENCES_ISSUE: commit messages referencing #NNN

Usage:
    python scripts/extract_git_edges.py /path/to/repo [--output /path/to/output.json] [--max-files-per-commit 50]

Idempotent: output is deterministic for a given HEAD.
Cached: checks HEAD hash against output file metadata.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, TypedDict


class CommitRecord(TypedDict):
    hash: str
    date: str
    author: str
    subject: str
    body: str
    files: list[str]


class CoChangedEdge(TypedDict):
    source: str
    target: str
    type: str
    weight: int
    directed: bool


class BeliefNode(TypedDict):
    id: str
    type: str
    content: str
    commit_hash: str
    date: str
    author: str


class BeliefEdge(TypedDict):
    source: str
    target: str
    type: str
    directed: bool


class IssueRefEdge(TypedDict):
    source: str
    target: str
    type: str
    directed: bool
    commit_hash: str


# Files to ignore in co-change analysis
IGNORE_PATTERNS: set[str] = {
    ".gitignore",
    ".gitattributes",
    "LICENSE",
    "LICENSE.md",
    "Cargo.lock",
    "package-lock.json",
    "yarn.lock",
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
    "go.sum",
    "pnpm-lock.yaml",
}

IGNORE_EXTENSIONS: set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp3",
    ".mp4",
    ".wav",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".bin",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".pyc",
    ".pyo",
    ".o",
    ".obj",
    ".a",
    ".lib",
}


def git_head(repo: Path) -> str:
    r: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return r.stdout.strip()


def should_ignore(filepath: str) -> bool:
    name: str = os.path.basename(filepath)
    if name in IGNORE_PATTERNS:
        return True
    _, ext = os.path.splitext(name)
    if ext.lower() in IGNORE_EXTENSIONS:
        return True
    # Skip hidden dirs (except .github, .planning, .gsd)
    parts: list[str] = filepath.split("/")
    for p in parts[:-1]:
        if p.startswith(".") and p not in (".github", ".planning", ".gsd"):
            return True
    return False


def parse_git_log(repo: Path, max_files: int = 50) -> list[CommitRecord]:
    """Parse git log into structured commits."""
    # Use %x00 as record separator, %x01 as field separator
    fmt: str = "%x00%H%x01%aI%x01%aN%x01%s%x01%b"
    r: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "log", "--format=" + fmt, "--name-only", "--no-merges"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=600,
        errors="replace",
    )
    if r.returncode != 0:
        print(f"git log failed: {r.stderr}", file=sys.stderr)
        return []

    commits: list[CommitRecord] = []
    raw_records: list[str] = r.stdout.split("\x00")

    for record in raw_records:
        record = record.strip()
        if not record:
            continue

        # Split header from file list
        lines: list[str] = record.split("\n")
        if not lines:
            continue

        header: str = lines[0]
        fields: list[str] = header.split("\x01")
        if len(fields) < 4:
            continue

        hash_val: str = fields[0].strip()
        date: str = fields[1].strip()
        author: str = fields[2].strip()
        subject: str = fields[3].strip()
        body: str = fields[4].strip() if len(fields) > 4 else ""

        # Files are remaining non-empty lines after header
        files: list[str] = []
        for line in lines[1:]:
            line = line.strip()
            if line and not line.startswith("\x01"):
                files.append(line)

        # Filter ignored files
        files = [f for f in files if not should_ignore(f)]

        # Skip bulk commits (reformats, merges that slipped through)
        if len(files) > max_files:
            continue

        # Skip trivial messages
        if subject.lower() in ("wip", "fix", "update", ".", "tmp", "temp"):
            continue

        commits.append(
            CommitRecord(
                hash=hash_val,
                date=date,
                author=author,
                subject=subject,
                body=body,
                files=files,
            )
        )

    return commits


def extract_co_changed(commits: list[CommitRecord]) -> list[CoChangedEdge]:
    """Extract CO_CHANGED edges with weights."""
    pair_counts: Counter[tuple[str, str]] = Counter()

    for commit in commits:
        files: list[str] = sorted(set(commit["files"]))
        for i in range(len(files)):
            for j in range(i + 1, len(files)):
                pair: tuple[str, str] = (files[i], files[j])
                pair_counts[pair] += 1

    edges: list[CoChangedEdge] = []
    for (a, b), weight in pair_counts.most_common():
        edges.append(
            CoChangedEdge(
                source=a,
                target=b,
                type="CO_CHANGED",
                weight=weight,
                directed=False,
            )
        )

    return edges


def split_sentences(text: str) -> list[str]:
    """Simple sentence splitter for commit messages."""
    # Split on period/exclamation/question followed by space+capital, or newlines
    text = text.strip()
    if not text:
        return []

    # First split on newlines (commit messages are often line-per-thought)
    lines: list[str] = [line.strip() for line in text.split("\n") if line.strip()]

    sentences: list[str] = []
    for line in lines:
        # Split on sentence boundaries within a line
        parts: list[str | Any] = re.split(r"(?<=[.!?])\s+(?=[A-Z])", line)
        for p in parts:
            p_str: str = str(p)
            p_str = p_str.strip()
            if len(p_str) > 10:  # skip very short fragments
                sentences.append(p_str)

    return sentences


def extract_commit_beliefs(
    commits: list[CommitRecord],
) -> tuple[list[BeliefNode], list[BeliefEdge]]:
    """Extract COMMIT_BELIEF edges: sentence -> files touched.

    Returns (belief_nodes, edges).
    """
    belief_nodes: list[BeliefNode] = []
    edges: list[BeliefEdge] = []

    for commit in commits:
        if not commit["files"]:
            continue

        # Combine subject + body for sentence extraction
        full_msg: str = commit["subject"]
        if commit["body"]:
            full_msg += "\n" + commit["body"]

        sentences: list[str] = split_sentences(full_msg)
        if not sentences:
            # Use subject as single belief even if short
            sentences = [commit["subject"]]

        for i, sentence in enumerate(sentences):
            belief_id: str = f"commit:{commit['hash'][:8]}:s{i}"
            belief_nodes.append(
                BeliefNode(
                    id=belief_id,
                    type="COMMIT_BELIEF",
                    content=sentence,
                    commit_hash=commit["hash"],
                    date=commit["date"],
                    author=commit["author"],
                )
            )

            for filepath in commit["files"]:
                edges.append(
                    BeliefEdge(
                        source=belief_id,
                        target=filepath,
                        type="COMMIT_BELIEF",
                        directed=True,
                    )
                )

    return belief_nodes, edges


def extract_issue_references(commits: list[CommitRecord]) -> list[IssueRefEdge]:
    """Extract REFERENCES_ISSUE edges from commit messages."""
    edges: list[IssueRefEdge] = []
    issue_pattern: re.Pattern[str] = re.compile(
        r"(?:fix(?:es|ed)?|clos(?:es|ed)?|resolv(?:es|ed)?|ref(?:s)?|see)?\s*#(\d+)",
        re.IGNORECASE,
    )

    for commit in commits:
        full_msg: str = commit["subject"]
        if commit["body"]:
            full_msg += "\n" + commit["body"]

        matches: list[str] = issue_pattern.findall(full_msg)
        for issue_num in set(matches):
            edges.append(
                IssueRefEdge(
                    source=f"commit:{commit['hash'][:8]}",
                    target=f"issue:#{issue_num}",
                    type="REFERENCES_ISSUE",
                    directed=True,
                    commit_hash=commit["hash"],
                )
            )

    return edges


def main() -> None:
    if len(sys.argv) < 2:
        print(
            f"Usage: {sys.argv[0]} /path/to/repo [--output path] [--max-files-per-commit N]"
        )
        sys.exit(1)

    repo: Path = Path(sys.argv[1])
    output_path: Path | None = None
    max_files: int = 50

    # Parse args
    args: list[str] = sys.argv[2:]
    i: int = 0
    while i < len(args):
        if args[i] == "--output" and i + 1 < len(args):
            output_path = Path(args[i + 1])
            i += 2
        elif args[i] == "--max-files-per-commit" and i + 1 < len(args):
            max_files = int(args[i + 1])
            i += 2
        else:
            i += 1

    if output_path is None:
        output_path = repo / "git_edges.json"

    # Cache check
    head: str = git_head(repo)
    if output_path.exists():
        try:
            existing: dict[str, Any] = json.loads(output_path.read_text())
            if existing.get("head") == head:
                print(f"[cached] {repo.name} HEAD={head[:8]}", file=sys.stderr)
                # Print summary even for cached
                summary_data: dict[str, Any] = existing["summary"]
                print(
                    f"  co_changed: {summary_data['co_changed_edges']}", file=sys.stderr
                )
                print(
                    f"  commit_beliefs: {summary_data['belief_nodes']} nodes, {summary_data['commit_belief_edges']} edges",
                    file=sys.stderr,
                )
                print(
                    f"  issue_refs: {summary_data['issue_ref_edges']}", file=sys.stderr
                )
                return
        except (json.JSONDecodeError, KeyError):
            pass

    print(f"[extract] {repo.name} HEAD={head[:8]}", file=sys.stderr)

    # Parse commits
    commits: list[CommitRecord] = parse_git_log(repo, max_files=max_files)
    print(f"  parsed {len(commits)} commits", file=sys.stderr)

    # Extract edges
    co_changed: list[CoChangedEdge] = extract_co_changed(commits)
    belief_nodes: list[BeliefNode]
    belief_edges: list[BeliefEdge]
    belief_nodes, belief_edges = extract_commit_beliefs(commits)
    issue_refs: list[IssueRefEdge] = extract_issue_references(commits)

    # Threshold co-change edges
    co_changed_raw: int = len(co_changed)
    _co_changed_t1: list[CoChangedEdge] = [e for e in co_changed if e["weight"] >= 1]
    co_changed_t3: list[CoChangedEdge] = [e for e in co_changed if e["weight"] >= 3]
    co_changed_t5: list[CoChangedEdge] = [e for e in co_changed if e["weight"] >= 5]

    # Unique files involved
    all_files: set[str] = set()
    for c in commits:
        all_files.update(c["files"])

    # Unique issue references
    issue_ids: set[str] = set(e["target"] for e in issue_refs)

    summary: dict[str, int] = {
        "co_changed_edges": co_changed_raw,
        "co_changed_edges_weight_ge_3": len(co_changed_t3),
        "co_changed_edges_weight_ge_5": len(co_changed_t5),
        "co_changed_max_weight": max((e["weight"] for e in co_changed), default=0),
        "belief_nodes": len(belief_nodes),
        "commit_belief_edges": len(belief_edges),
        "issue_ref_edges": len(issue_refs),
        "unique_issues": len(issue_ids),
        "unique_files": len(all_files),
        "commits_analyzed": len(commits),
    }

    print(f"  files: {len(all_files)}", file=sys.stderr)
    print(
        f"  co_changed: {co_changed_raw} total, {len(co_changed_t3)} (w>=3), {len(co_changed_t5)} (w>=5)",
        file=sys.stderr,
    )
    print(
        f"  co_changed max weight: {summary['co_changed_max_weight']}", file=sys.stderr
    )
    print(
        f"  commit_beliefs: {len(belief_nodes)} nodes, {len(belief_edges)} edges",
        file=sys.stderr,
    )
    print(
        f"  issue_refs: {len(issue_refs)} edges, {len(issue_ids)} unique issues",
        file=sys.stderr,
    )

    # Weight distribution
    weight_dist: Counter[str] = Counter()
    for e in co_changed:
        bucket: str = (
            "1"
            if e["weight"] == 1
            else "2"
            if e["weight"] == 2
            else "3-5"
            if e["weight"] <= 5
            else "6-10"
            if e["weight"] <= 10
            else "11-50"
            if e["weight"] <= 50
            else "50+"
        )
        weight_dist[bucket] += 1
    print(
        f"  co_changed weight distribution: {dict(sorted(weight_dist.items()))}",
        file=sys.stderr,
    )

    result: dict[
        str,
        str
        | dict[str, int]
        | list[CoChangedEdge]
        | list[BeliefNode]
        | list[BeliefEdge]
        | list[IssueRefEdge],
    ] = {
        "repo": str(repo),
        "name": repo.name,
        "head": head,
        "summary": summary,
        "co_changed_edges": co_changed,
        "belief_nodes": belief_nodes,
        "commit_belief_edges": belief_edges,
        "issue_ref_edges": issue_refs,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2))
    print(f"  written to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
