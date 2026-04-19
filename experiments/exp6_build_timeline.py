from __future__ import annotations

"""
Experiment 6 Phase A: Build unified timeline from project-a project history.

Extracts all events from:
- GSD decisions (173 decisions with milestone context)
- GSD milestones (36+ milestones with timestamps)
- Git commits (552+ commits with timestamps and messages)
- Knowledge entries (379 entries)
- Citation edges (775 edges between nodes)

Outputs a unified timeline JSON with temporal ordering and citation links.
"""

import json
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


project-a_DB = Path(
    "/home/user/projects/.gsd/workflows/spikes/"
    "260406-1-associative-memory-for-gsd-please-explor/"
    "sandbox/project-a.db"
)
project-a_REPO = Path("/home/user/projects/project-a")
project-a_MEMTEST_REPO = Path("/home/user/projects/project-a-test")

OUTPUT_PATH = Path("experiments/exp6_timeline.json")
SUMMARY_PATH = Path("experiments/exp6_timeline_summary.txt")


@dataclass
class TimelineEvent:
    id: str
    event_type: str  # decision, milestone_start, milestone_end, commit, knowledge
    timestamp: str  # ISO 8601
    content: str
    context: str  # what milestone/slice/task this belongs to
    references: list[str]  # D###/M### references found in content
    source: str  # where this came from (db table, git, file)


def extract_d_m_refs(text: str) -> list[str]:
    """Extract D### and M### references from text."""
    refs: set[str] = set()
    for m in re.finditer(r"\bD(\d{2,3})\b", text):
        refs.add(f"D{m.group(1)}")
    for m in re.finditer(r"\bM(\d{2,3})\b", text):
        refs.add(f"M{m.group(1).zfill(3)}")
    return sorted(refs)


def extract_decisions(db: sqlite3.Connection) -> list[TimelineEvent]:
    """Extract decisions and assign approximate timestamps from milestone context."""
    events: list[TimelineEvent] = []

    # Build milestone timestamp lookup
    milestone_times: dict[str, dict[str, str]] = {}
    for row in db.execute("SELECT id, created_at, completed_at FROM milestones"):
        mid = row[0].split("-")[0]  # M005-4iw23z -> M005
        milestone_times[mid] = {
            "created": row[1],
            "completed": row[2],
        }

    for row in db.execute(
        "SELECT id, when_context, scope, decision, choice, rationale, superseded_by FROM decisions ORDER BY seq"
    ):
        did: str = row[0]
        when_ctx: str = row[1] or ""
        _scope: str = row[2] or ""
        decision: str = row[3] or ""
        choice: str = row[4] or ""
        rationale: str = row[5] or ""
        _superseded: str = row[6] or ""

        content = f"{decision}: {choice}"
        if rationale:
            content += f" | Rationale: {rationale[:200]}"

        # Try to derive timestamp from when_context -> milestone
        timestamp = ""
        milestone_ref = ""
        m_match = re.search(r"M(\d{3})", when_ctx)
        if m_match:
            milestone_ref = f"M{m_match.group(1)}"
            mt = milestone_times.get(milestone_ref, {})
            # Use milestone created_at as approximate decision time
            timestamp = mt.get("created", "")

        # Extract all D/M references from content
        full_text = f"{decision} {choice} {rationale} {when_ctx}"
        refs = extract_d_m_refs(full_text)

        events.append(
            TimelineEvent(
                id=did,
                event_type="decision",
                timestamp=timestamp,
                content=content,
                context=when_ctx,
                references=refs,
                source="decisions_table",
            )
        )

    return events


def extract_milestones(db: sqlite3.Connection) -> list[TimelineEvent]:
    """Extract milestone start and end events."""
    events: list[TimelineEvent] = []

    for row in db.execute(
        "SELECT id, title, status, created_at, completed_at FROM milestones ORDER BY created_at"
    ):
        mid_full: str = row[0]
        mid = mid_full.split("-")[0]
        title: str = row[1] or mid
        status: str = row[2] or "unknown"
        created: str = row[3] or ""
        completed: str | None = row[4]

        events.append(
            TimelineEvent(
                id=f"{mid}_start",
                event_type="milestone_start",
                timestamp=created,
                content=f"{mid}: {title} (status: {status})",
                context=mid_full,
                references=[],
                source="milestones_table",
            )
        )

        if completed:
            events.append(
                TimelineEvent(
                    id=f"{mid}_end",
                    event_type="milestone_end",
                    timestamp=completed,
                    content=f"{mid}: {title} COMPLETED",
                    context=mid_full,
                    references=[],
                    source="milestones_table",
                )
            )

    return events


def extract_knowledge(db: sqlite3.Connection) -> list[TimelineEvent]:
    """Extract knowledge entries."""
    events: list[TimelineEvent] = []

    for row in db.execute(
        "SELECT id, content, category, created_at FROM mem_nodes WHERE source_type='knowledge' ORDER BY id"
    ):
        kid: str = row[0]
        content: str = row[1] or ""
        category: str = row[2] or ""
        created: str = row[3] or ""

        refs = extract_d_m_refs(content)

        # Try to extract milestone context from content (e.g., "M022: ...")
        context = ""
        m_match = re.match(r"M(\d{3})", content)
        if m_match:
            context = f"M{m_match.group(1)}"

        events.append(
            TimelineEvent(
                id=kid,
                event_type="knowledge",
                timestamp=created,
                content=content,
                context=context or category,
                references=refs,
                source="mem_nodes_table",
            )
        )

    return events


def extract_git_commits(repo_path: Path, repo_name: str) -> list[TimelineEvent]:
    """Extract git commits with D###/M### references."""
    events: list[TimelineEvent] = []

    try:
        result = subprocess.run(
            ["git", "log", "--format=%H|%aI|%s", "--no-merges"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(
                f"  Git log failed for {repo_name}: {result.stderr[:100]}",
                file=sys.stderr,
            )
            return events

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) < 3:
                continue

            sha = parts[0][:12]
            timestamp = parts[1]
            message = parts[2]

            refs = extract_d_m_refs(message)

            events.append(
                TimelineEvent(
                    id=f"commit_{sha}",
                    event_type="commit",
                    timestamp=timestamp,
                    content=message,
                    context=repo_name,
                    references=refs,
                    source=f"git_{repo_name}",
                )
            )

    except subprocess.TimeoutExpired:
        print(f"  Git log timed out for {repo_name}", file=sys.stderr)

    return events


def extract_edges(db: sqlite3.Connection) -> list[dict[str, Any]]:
    """Extract citation edges for the citation graph."""
    edges: list[dict[str, Any]] = []
    for row in db.execute(
        "SELECT from_id, to_id, edge_type, weight, reason FROM mem_edges"
    ):
        edges.append(
            {
                "from": row[0],
                "to": row[1],
                "type": row[2],
                "weight": row[3],
                "reason": (row[4] or "")[:100],
            }
        )
    return edges


def build_timeline() -> None:
    print("=" * 60, file=sys.stderr)
    print("Experiment 6 Phase A: Building Unified Timeline", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    db = sqlite3.connect(str(project-a_DB))

    # Extract from all sources
    print("  Extracting decisions...", file=sys.stderr)
    decisions = extract_decisions(db)
    print(f"    {len(decisions)} decisions", file=sys.stderr)

    print("  Extracting milestones...", file=sys.stderr)
    milestones = extract_milestones(db)
    print(f"    {len(milestones)} milestone events", file=sys.stderr)

    print("  Extracting knowledge...", file=sys.stderr)
    knowledge = extract_knowledge(db)
    print(f"    {len(knowledge)} knowledge entries", file=sys.stderr)

    print("  Extracting edges...", file=sys.stderr)
    edges = extract_edges(db)
    print(f"    {len(edges)} citation edges", file=sys.stderr)

    db.close()

    print("  Extracting git commits (project-a)...", file=sys.stderr)
    commits_as = extract_git_commits(project-a_REPO, "project-a")
    print(f"    {len(commits_as)} commits", file=sys.stderr)

    print("  Extracting git commits (project-a-test)...", file=sys.stderr)
    commits_mt = extract_git_commits(project-a_MEMTEST_REPO, "project-a-test")
    print(f"    {len(commits_mt)} commits", file=sys.stderr)

    # Combine all events
    all_events = decisions + milestones + knowledge + commits_as + commits_mt

    # Sort by timestamp (events without timestamps go to the end)
    def sort_key(e: TimelineEvent) -> str:
        if e.timestamp:
            return e.timestamp
        # For decisions without timestamps, use ID number for ordering
        m = re.match(r"D(\d+)", e.id)
        if m:
            return f"9999-{int(m.group(1)):06d}"
        return "9999-999999"

    all_events.sort(key=sort_key)

    # Compute stats
    with_timestamps = sum(1 for e in all_events if e.timestamp)
    with_refs = sum(1 for e in all_events if e.references)
    ref_counts: dict[str, int] = {}
    for e in all_events:
        for r in e.references:
            ref_counts[r] = ref_counts.get(r, 0) + 1

    # Commits that reference decisions/milestones
    signal_commits = [
        e for e in all_events if e.event_type == "commit" and e.references
    ]

    # Find most-referenced nodes
    top_refs = sorted(ref_counts.items(), key=lambda x: x[1], reverse=True)[:20]

    # Build summary
    summary_lines = [
        "=" * 60,
        "TIMELINE SUMMARY",
        "=" * 60,
        f"Total events: {len(all_events)}",
        f"  Decisions: {len(decisions)}",
        f"  Milestone events: {len(milestones)}",
        f"  Knowledge entries: {len(knowledge)}",
        f"  Commits (project-a): {len(commits_as)}",
        f"  Commits (project-a-test): {len(commits_mt)}",
        "",
        f"Events with timestamps: {with_timestamps}/{len(all_events)}",
        f"Events with D###/M### references: {with_refs}/{len(all_events)}",
        f"Signal commits (reference D###/M###): {len(signal_commits)}/{len(commits_as) + len(commits_mt)}",
        "",
        f"Citation edges: {len(edges)}",
        "",
        "Top 20 most-referenced nodes:",
    ]
    for ref, count in top_refs:
        summary_lines.append(f"  {ref}: {count} references")

    # Date range
    timestamps = [e.timestamp for e in all_events if e.timestamp]
    if timestamps:
        summary_lines.extend(
            [
                "",
                f"Date range: {min(timestamps)[:10]} to {max(timestamps)[:10]}",
            ]
        )

    summary = "\n".join(summary_lines)
    print(f"\n{summary}", file=sys.stderr)

    # Write outputs
    timeline_data: dict[str, Any] = {
        "events": [asdict(e) for e in all_events],
        "edges": edges,
        "stats": {
            "total_events": len(all_events),
            "decisions": len(decisions),
            "milestones": len(milestones),
            "knowledge": len(knowledge),
            "commits_project_a": len(commits_as),
            "commits_memtest": len(commits_mt),
            "edges": len(edges),
            "signal_commits": len(signal_commits),
            "with_timestamps": with_timestamps,
            "with_references": with_refs,
            "top_references": top_refs[:20],
        },
    }

    OUTPUT_PATH.write_text(json.dumps(timeline_data, indent=2))
    SUMMARY_PATH.write_text(summary)

    print(f"\nOutput: {OUTPUT_PATH}", file=sys.stderr)
    print(f"Summary: {SUMMARY_PATH}", file=sys.stderr)


if __name__ == "__main__":
    build_timeline()
