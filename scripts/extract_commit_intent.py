"""
extract_commit_intent.py -- Build a commit intent graph from git history.

Extracts edges between files co-committed together, enriched with commit
messages (human intent), issue references, branch context, and belief nodes.
Designed for validation: compare auto-extracted graph edges against intent
expressed through git commits.

Usage:
    uv run python scripts/extract_commit_intent.py --repo /path/to/repo
    uv run python scripts/extract_commit_intent.py --repo /path/to/repo --min-weight 2
    uv run python scripts/extract_commit_intent.py --repo /path/to/repo --skip-patterns "docs only" "typo"

Output: JSON to stdout, summary stats to stderr.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import TypedDict


# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------

class CommitRecord(TypedDict):
    hash: str
    date: str
    author: str
    subject: str
    body: str
    files: list[str]
    parent_count: int


class IntentEdge(TypedDict):
    source: str
    target: str
    weight: int
    commit_messages: list[str]
    issue_refs: list[str]
    first_seen: str
    last_seen: str


class BeliefNode(TypedDict):
    commit: str
    date: str
    message: str
    files_touched: list[str]
    issue_refs: list[str]


class BranchInfo(TypedDict):
    commits: int
    date_range: list[str]


class SkipCounts(TypedDict):
    merge: int
    bulk: int
    noise_message: int
    trivial_files: int


class OutputSummary(TypedDict):
    total_intent_edges: int
    total_belief_nodes: int
    avg_files_per_commit: float
    avg_weight: float


class OutputData(TypedDict):
    repo: str
    total_commits: int
    filtered_commits: int
    skipped: SkipCounts
    edges: list[IntentEdge]
    belief_nodes: list[BeliefNode]
    branches: dict[str, BranchInfo]
    summary: OutputSummary


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Files that carry no meaningful intent signal when committed alone
TRIVIAL_FILE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(^|/)\.gitignore$"),
    re.compile(r"(^|/)\.gitattributes$"),
    re.compile(r"\.lock$"),
    re.compile(r"(^|/)go\.sum$"),
    re.compile(r"(^|/)\.github/"),
    re.compile(r"(^|/)\.gitlab-ci"),
    re.compile(r"(^|/)Jenkinsfile$"),
    re.compile(r"(^|/)\.circleci/"),
    re.compile(r"(^|/)\.travis\.yml$"),
]

DEFAULT_SKIP_PATTERNS: list[str] = [
    r"(?i)^wip\b",
    r"(?i)^merge\b",
    r"(?i)\breformat\b",
    r"(?i)\blint\b",
    r"(?i)\bbump version\b",
    r"(?i)\bupdate lock\b",
]

ISSUE_REF_PATTERN: re.Pattern[str] = re.compile(
    r"(?:fix(?:es|ed)?|clos(?:es|ed)?|resolv(?:es|ed)?|ref(?:s)?|see)?\s*#(\d+)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Git interaction (batched)
# ---------------------------------------------------------------------------

def _run_git(repo: Path, args: list[str], timeout: int = 300) -> str:
    """Run a git command and return stdout. Raises on failure."""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        msg: str = f"git {' '.join(args[:3])} failed: {result.stderr.strip()}"
        raise RuntimeError(msg)
    return result.stdout


def parse_git_log(repo: Path) -> list[CommitRecord]:
    """Parse full git log in a single call. Returns all commits including merges."""
    # %x00 record separator, %x01 field separator
    # Fields: hash, parent hashes, ISO date, author, subject, body
    fmt: str = "%x00%H%x01%P%x01%aI%x01%aN%x01%s%x01%b"
    raw: str = _run_git(repo, ["log", "--format=" + fmt, "--name-only"])

    commits: list[CommitRecord] = []
    records: list[str] = raw.split("\x00")

    for record in records:
        record = record.strip()
        if not record:
            continue

        lines: list[str] = record.split("\n")
        if not lines:
            continue

        header: str = lines[0]
        fields: list[str] = header.split("\x01")
        if len(fields) < 5:
            continue

        hash_val: str = fields[0].strip()
        parents: str = fields[1].strip()
        date: str = fields[2].strip()
        author: str = fields[3].strip()
        subject: str = fields[4].strip()
        body: str = fields[5].strip() if len(fields) > 5 else ""

        parent_count: int = len(parents.split()) if parents else 0

        files: list[str] = []
        for line in lines[1:]:
            stripped: str = line.strip()
            if stripped and not stripped.startswith("\x01"):
                files.append(stripped)

        commits.append(CommitRecord(
            hash=hash_val,
            date=date,
            author=author,
            subject=subject,
            body=body,
            files=files,
            parent_count=parent_count,
        ))

    return commits


def extract_branches(repo: Path, commit_hashes: list[str]) -> dict[str, list[str]]:
    """Map branch names to commit hashes using a single batched call.

    Uses `git branch --contains` per-commit which is expensive for large repos,
    so instead we list all branches and their tips, then walk the log per branch
    to find which commits belong where. For efficiency we use `git log --format`
    per branch but batch them.
    """
    # Get all local branches
    raw_branches: str = _run_git(repo, ["branch", "--format=%(refname:short)"])
    branch_names: list[str] = [b.strip() for b in raw_branches.strip().split("\n") if b.strip()]

    if not branch_names:
        return {}

    hash_set: set[str] = set(commit_hashes)
    branch_commits: dict[str, list[str]] = {}

    for branch in branch_names:
        try:
            raw_log: str = _run_git(
                repo,
                ["log", "--format=%H", branch, "--"],
                timeout=30,
            )
        except RuntimeError:
            continue

        hashes: list[str] = [
            h.strip() for h in raw_log.strip().split("\n")
            if h.strip() and h.strip() in hash_set
        ]
        branch_commits[branch] = hashes

    return branch_commits


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def _is_trivial_file(filepath: str) -> bool:
    """Check if a file matches trivial/noise patterns."""
    for pat in TRIVIAL_FILE_PATTERNS:
        if pat.search(filepath):
            return True
    return False


def _all_files_trivial(files: list[str]) -> bool:
    """True if every file in the list is a trivial/noise file."""
    if not files:
        return True
    return all(_is_trivial_file(f) for f in files)


def compile_skip_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    """Compile a list of regex strings into compiled patterns."""
    compiled: list[re.Pattern[str]] = []
    for p in patterns:
        compiled.append(re.compile(p))
    return compiled


def _message_matches_skip(subject: str, patterns: list[re.Pattern[str]]) -> bool:
    """Check if a commit subject matches any skip pattern."""
    for pat in patterns:
        if pat.search(subject):
            return True
    return False


def filter_commits(
    commits: list[CommitRecord],
    max_files: int,
    skip_patterns: list[re.Pattern[str]],
) -> tuple[list[CommitRecord], SkipCounts]:
    """Filter commits and return (kept, skip_counts)."""
    skipped: SkipCounts = SkipCounts(merge=0, bulk=0, noise_message=0, trivial_files=0)
    kept: list[CommitRecord] = []

    for commit in commits:
        if commit["parent_count"] > 1:
            skipped["merge"] += 1
            continue
        if len(commit["files"]) > max_files:
            skipped["bulk"] += 1
            continue
        if _message_matches_skip(commit["subject"], skip_patterns):
            skipped["noise_message"] += 1
            continue
        if _all_files_trivial(commit["files"]):
            skipped["trivial_files"] += 1
            continue
        kept.append(commit)

    return kept, skipped


# ---------------------------------------------------------------------------
# Edge and belief extraction
# ---------------------------------------------------------------------------

def extract_issue_refs(text: str) -> list[str]:
    """Extract issue references like #123 from text."""
    matches: list[str] = ISSUE_REF_PATTERN.findall(text)
    return sorted(set(f"#{m}" for m in matches))


def split_sentences(text: str) -> list[str]:
    """Split commit message text into individual assertion sentences."""
    text = text.strip()
    if not text:
        return []

    lines: list[str] = [ln.strip() for ln in text.split("\n") if ln.strip()]

    sentences: list[str] = []
    for line in lines:
        parts: list[str] = re.split(r"(?<=[.!?])\s+(?=[A-Z])", line)
        for part in parts:
            cleaned: str = part.strip()
            if len(cleaned) > 5:
                sentences.append(cleaned)

    return sentences


def build_intent_edges(
    commits: list[CommitRecord],
    min_weight: int,
) -> list[IntentEdge]:
    """Build co-commit intent edges between files."""
    pair_messages: dict[tuple[str, str], list[str]] = defaultdict(list)
    pair_issues: dict[tuple[str, str], set[str]] = defaultdict(set)
    pair_first: dict[tuple[str, str], str] = {}
    pair_last: dict[tuple[str, str], str] = {}
    pair_count: Counter[tuple[str, str]] = Counter()

    for commit in commits:
        files: list[str] = sorted(set(commit["files"]))
        if len(files) < 2:
            continue

        full_msg: str = commit["subject"]
        if commit["body"]:
            full_msg += "\n" + commit["body"]
        issues: list[str] = extract_issue_refs(full_msg)
        date_str: str = commit["date"][:10]  # ISO date portion

        for i in range(len(files)):
            for j in range(i + 1, len(files)):
                pair: tuple[str, str] = (files[i], files[j])
                pair_count[pair] += 1
                pair_messages[pair].append(commit["subject"])
                pair_issues[pair].update(issues)

                if pair not in pair_first:
                    pair_first[pair] = date_str
                    pair_last[pair] = date_str
                else:
                    if date_str < pair_first[pair]:
                        pair_first[pair] = date_str
                    if date_str > pair_last[pair]:
                        pair_last[pair] = date_str

    edges: list[IntentEdge] = []
    for pair, weight in pair_count.most_common():
        if weight < min_weight:
            continue
        edges.append(IntentEdge(
            source=pair[0],
            target=pair[1],
            weight=weight,
            commit_messages=pair_messages[pair],
            issue_refs=sorted(pair_issues[pair]),
            first_seen=pair_first[pair],
            last_seen=pair_last[pair],
        ))

    return edges


def build_belief_nodes(commits: list[CommitRecord]) -> list[BeliefNode]:
    """Create belief nodes from commit messages."""
    nodes: list[BeliefNode] = []

    for commit in commits:
        if not commit["files"]:
            continue

        full_msg: str = commit["subject"]
        if commit["body"]:
            full_msg += "\n" + commit["body"]

        issues: list[str] = extract_issue_refs(full_msg)

        # Use subject as the primary belief assertion.
        # Body sentences are additional context but the subject is the intent.
        nodes.append(BeliefNode(
            commit=commit["hash"][:12],
            date=commit["date"][:10],
            message=commit["subject"],
            files_touched=commit["files"],
            issue_refs=issues,
        ))

    return nodes


def build_branch_info(
    repo: Path,
    commits: list[CommitRecord],
) -> dict[str, BranchInfo]:
    """Extract branch information and map commits to branches."""
    hashes: list[str] = [c["hash"] for c in commits]
    branch_commits: dict[str, list[str]] = extract_branches(repo, hashes)

    # Build a date lookup
    date_by_hash: dict[str, str] = {}
    for c in commits:
        date_by_hash[c["hash"]] = c["date"][:10]

    branches: dict[str, BranchInfo] = {}
    for branch_name, commit_hashes in branch_commits.items():
        if not commit_hashes:
            continue
        dates: list[str] = [
            date_by_hash[h] for h in commit_hashes if h in date_by_hash
        ]
        if not dates:
            continue
        sorted_dates: list[str] = sorted(dates)
        branches[branch_name] = BranchInfo(
            commits=len(commit_hashes),
            date_range=[sorted_dates[0], sorted_dates[-1]],
        )

    return branches


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Build a commit intent graph from git history.",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        required=True,
        help="Path to the git repository root.",
    )
    parser.add_argument(
        "--min-weight",
        type=int,
        default=1,
        help="Minimum co-commit count to include an edge (default: 1).",
    )
    parser.add_argument(
        "--max-files-per-commit",
        type=int,
        default=50,
        help="Skip commits touching more than N files (default: 50).",
    )
    parser.add_argument(
        "--skip-patterns",
        action="append",
        default=None,
        help="Regex pattern for commit messages to skip (repeatable). "
             "Replaces defaults if provided.",
    )
    return parser


def main() -> None:
    parser: argparse.ArgumentParser = build_parser()
    args: argparse.Namespace = parser.parse_args()

    repo: Path = Path(args.repo).resolve()
    min_weight: int = args.min_weight
    max_files: int = args.max_files_per_commit

    # Determine skip patterns
    skip_pattern_strs: list[str]
    if args.skip_patterns is not None:
        skip_pattern_strs = list(args.skip_patterns)
    else:
        skip_pattern_strs = DEFAULT_SKIP_PATTERNS
    skip_compiled: list[re.Pattern[str]] = compile_skip_patterns(skip_pattern_strs)

    # Validate repo
    if not (repo / ".git").is_dir():
        print(f"Error: {repo} is not a git repository", file=sys.stderr)
        sys.exit(1)

    repo_name: str = repo.name

    # Parse all commits in one git call
    print(f"[intent] parsing git log for {repo_name}...", file=sys.stderr)
    all_commits: list[CommitRecord] = parse_git_log(repo)
    total_commits: int = len(all_commits)
    print(f"[intent] total commits: {total_commits}", file=sys.stderr)

    # Filter
    filtered: list[CommitRecord]
    skipped: SkipCounts
    filtered, skipped = filter_commits(all_commits, max_files, skip_compiled)
    filtered_count: int = len(filtered)
    print(
        f"[intent] after filtering: {filtered_count} commits "
        f"(skipped: merge={skipped['merge']}, bulk={skipped['bulk']}, "
        f"noise={skipped['noise_message']}, trivial={skipped['trivial_files']})",
        file=sys.stderr,
    )

    # Build edges
    print("[intent] building intent edges...", file=sys.stderr)
    edges: list[IntentEdge] = build_intent_edges(filtered, min_weight)
    print(f"[intent] intent edges: {len(edges)}", file=sys.stderr)

    # Build belief nodes
    print("[intent] building belief nodes...", file=sys.stderr)
    belief_nodes: list[BeliefNode] = build_belief_nodes(filtered)
    print(f"[intent] belief nodes: {len(belief_nodes)}", file=sys.stderr)

    # Branch info
    print("[intent] extracting branch info...", file=sys.stderr)
    branches: dict[str, BranchInfo] = build_branch_info(repo, filtered)
    print(f"[intent] branches: {len(branches)}", file=sys.stderr)

    # Summary stats
    files_per_commit: list[int] = [len(c["files"]) for c in filtered if c["files"]]
    avg_files: float = (
        sum(files_per_commit) / len(files_per_commit)
        if files_per_commit
        else 0.0
    )
    weights: list[int] = [e["weight"] for e in edges]
    avg_weight: float = sum(weights) / len(weights) if weights else 0.0

    summary: OutputSummary = OutputSummary(
        total_intent_edges=len(edges),
        total_belief_nodes=len(belief_nodes),
        avg_files_per_commit=round(avg_files, 2),
        avg_weight=round(avg_weight, 2),
    )

    print(
        f"[intent] summary: edges={summary['total_intent_edges']}, "
        f"beliefs={summary['total_belief_nodes']}, "
        f"avg_files={summary['avg_files_per_commit']}, "
        f"avg_weight={summary['avg_weight']}",
        file=sys.stderr,
    )

    # Build output
    output: OutputData = OutputData(
        repo=repo_name,
        total_commits=total_commits,
        filtered_commits=filtered_count,
        skipped=skipped,
        edges=edges,
        belief_nodes=belief_nodes,
        branches=branches,
        summary=summary,
    )

    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
