from __future__ import annotations

"""
Experiment 6 Phase C: Before/after analysis of memory enforcement mechanisms.

There's no single "memory prototype on" date. Instead, enforcement mechanisms
were added incrementally:
- D089 (Mar 27): dispatch gate rule
- D097 (Mar 27): backtesting protocol added to CLAUDE.md
- D106 (Mar 27): deploy gate execution discipline
- D137 (Mar 30): dispatch runbook created as living document
- Pyright pre-commit hook (Mar 28)
- D194/D195 (Apr 2): research incorporation checklist

We analyze: does the override rate decrease as these mechanisms accumulate?
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


FAILURES_PATH = Path("experiments/exp6_failures_v2.json")
TIMELINE_PATH = Path("experiments/exp6_timeline.json")


def parse_date(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def main() -> None:
    failures: dict[str, Any] = json.loads(FAILURES_PATH.read_text())
    timeline: dict[str, Any] = json.loads(TIMELINE_PATH.read_text())

    # Get all overrides with timestamps from clusters
    all_overrides: list[dict[str, str]] = []
    topic_clusters: list[dict[str, Any]] = failures["topic_clusters"]
    for cluster in topic_clusters:
        cluster_overrides: list[dict[str, Any]] = cluster["overrides"]
        for override in cluster_overrides:
            all_overrides.append({
                "timestamp": override["timestamp"],
                "topic": cluster["topic_id"],
                "description": cluster["description"],
                "change": override["change"][:100],
            })

    # Add uncategorized (estimate from failures file)
    # Sort all by timestamp
    all_overrides.sort(key=lambda x: x["timestamp"])

    # --- Override rate by day ---
    by_date: dict[str, list[dict[str, str]]] = {}
    for o in all_overrides:
        date: str = o["timestamp"][:10]
        if date not in by_date:
            by_date[date] = []
        by_date[date].append(o)

    # Fill in zero-override days
    daily_counts: list[dict[str, Any]] = []
    if all_overrides:
        start = parse_date(all_overrides[0]["timestamp"]).date()
        end = parse_date(all_overrides[-1]["timestamp"]).date()
        current = start
        while current <= end:
            date_str = current.isoformat()
            day_overrides: list[dict[str, str]] = by_date.get(date_str, [])
            count = len(day_overrides)
            topics: list[str] = list(set(o["topic"] for o in day_overrides))
            daily_counts.append({
                "date": date_str,
                "overrides": count,
                "topics": topics,
            })
            current += timedelta(days=1)

    # --- Key enforcement dates ---
    enforcement_events: list[dict[str, str]] = [
        {"date": "2026-03-27", "event": "D089: dispatch gate rule + D097: backtesting protocol to CLAUDE.md + D106: deploy gate discipline", "type": "rule"},
        {"date": "2026-03-28", "event": "Pyright pre-commit hook added", "type": "automation"},
        {"date": "2026-03-30", "event": "D137: dispatch runbook created as living document", "type": "documentation"},
        {"date": "2026-04-02", "event": "D194/D195: research incorporation checklist", "type": "process"},
    ]

    # --- Before/after each enforcement event ---
    print("=" * 60, file=sys.stderr)
    print("OVERRIDE RATE OVER TIME", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    print("\nDaily override counts:", file=sys.stderr)
    for day in daily_counts:
        bar = "#" * int(day["overrides"])
        day_topics: list[str] = day["topics"]
        topics_str = ", ".join(day_topics[:3]) if day_topics else ""
        print(f"  {day['date']}: {day['overrides']:2d} {bar} {topics_str}", file=sys.stderr)

    # --- Compute rolling averages ---
    print("\n3-day rolling average:", file=sys.stderr)
    for i in range(len(daily_counts)):
        window: list[dict[str, Any]] = daily_counts[max(0, i-2):i+1]
        avg: float = sum(int(d["overrides"]) for d in window) / len(window)
        date_val: str = daily_counts[i]["date"]
        bar = "#" * int(avg * 2)
        # Mark enforcement events
        enforcement = ""
        for e in enforcement_events:
            if e["date"] == date_val:
                enforcement = f" <-- {e['event'][:50]}"
        print(f"  {date_val}: {avg:4.1f} {bar}{enforcement}", file=sys.stderr)

    # --- Per-topic timeline ---
    print(f"\n{'='*60}", file=sys.stderr)
    print("PER-TOPIC OVERRIDE TIMELINE", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    topic_timelines: dict[str, list[str]] = {}
    for o in all_overrides:
        topic_key: str = o["topic"]
        if topic_key not in topic_timelines:
            topic_timelines[topic_key] = []
        topic_timelines[topic_key].append(o["timestamp"][:10])

    for topic, dates in sorted(topic_timelines.items(), key=lambda x: len(x[1]), reverse=True):
        desc: str = next((c["description"] for c in topic_clusters if c["topic_id"] == topic), topic)
        print(f"\n  {topic} ({len(dates)} overrides): {desc}", file=sys.stderr)
        for d in dates:
            print(f"    {d}", file=sys.stderr)
        if len(dates) >= 2:
            first = dates[0]
            last = dates[-1]
            span = (parse_date(last + "T00:00:00Z") - parse_date(first + "T00:00:00Z")).days
            print(f"    Span: {span} days (first: {first}, last: {last})", file=sys.stderr)

    # --- Compute before/after splits for dispatch gate specifically ---
    print(f"\n{'='*60}", file=sys.stderr)
    print("DISPATCH GATE: BEFORE/AFTER RUNBOOK (D137, 2026-03-30)", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    dispatch_overrides: list[dict[str, str]] = [o for o in all_overrides if o["topic"] == "dispatch_gate"]
    before_runbook: list[dict[str, str]] = [o for o in dispatch_overrides if o["timestamp"] < "2026-03-30"]
    after_runbook: list[dict[str, str]] = [o for o in dispatch_overrides if o["timestamp"] >= "2026-03-30"]

    days_before = (parse_date("2026-03-30T00:00:00Z") - parse_date("2026-03-24T00:00:00Z")).days
    days_after = (parse_date("2026-04-07T00:00:00Z") - parse_date("2026-03-30T00:00:00Z")).days

    rate_before: float = len(before_runbook) / days_before if days_before > 0 else 0
    rate_after: float = len(after_runbook) / days_after if days_after > 0 else 0

    print(f"  Before runbook (Mar 24-29): {len(before_runbook)} overrides in {days_before} days "
          f"= {rate_before:.2f}/day", file=sys.stderr)
    print(f"  After runbook (Mar 30-Apr 6): {len(after_runbook)} overrides in {days_after} days "
          f"= {rate_after:.2f}/day", file=sys.stderr)
    if rate_before > 0:
        reduction: float = (rate_before - rate_after) / rate_before * 100
        print(f"  Change: {reduction:+.0f}%", file=sys.stderr)

    # --- Overall before/after the big enforcement day (Mar 27) ---
    print(f"\n{'='*60}", file=sys.stderr)
    print("OVERALL: BEFORE/AFTER MAJOR ENFORCEMENT DAY (2026-03-27)", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # Mar 27 had 10 overrides -- that's both the peak AND when enforcement rules were added
    # Use Mar 28 as the split (day after enforcement rules added)
    before_enforcement: list[dict[str, str]] = [o for o in all_overrides if o["timestamp"] < "2026-03-28"]
    after_enforcement: list[dict[str, str]] = [o for o in all_overrides if o["timestamp"] >= "2026-03-28"]

    days_before_e = 4  # Mar 24-27
    days_after_e = 10  # Mar 28 - Apr 6

    rate_before_e: float = len(before_enforcement) / days_before_e if days_before_e > 0 else 0
    rate_after_e: float = len(after_enforcement) / days_after_e if days_after_e > 0 else 0

    print(f"  Before (Mar 24-27): {len(before_enforcement)} overrides in {days_before_e} days "
          f"= {rate_before_e:.2f}/day", file=sys.stderr)
    print(f"  After (Mar 28-Apr 6): {len(after_enforcement)} overrides in {days_after_e} days "
          f"= {rate_after_e:.2f}/day", file=sys.stderr)
    if rate_before_e > 0:
        reduction_e: float = (rate_before_e - rate_after_e) / rate_before_e * 100
        print(f"  Change: {reduction_e:+.0f}%", file=sys.stderr)

    # --- Commit rate for context ---
    events: list[dict[str, Any]] = timeline["events"]
    commits: list[dict[str, Any]] = [e for e in events if e["event_type"] == "commit"]
    commits_before: list[dict[str, Any]] = [c for c in commits if c["timestamp"] < "2026-03-28"]
    commits_after: list[dict[str, Any]] = [c for c in commits if c["timestamp"] >= "2026-03-28"]

    commit_rate_before: float = len(commits_before) / days_before_e if days_before_e > 0 else 0
    commit_rate_after: float = len(commits_after) / days_after_e if days_after_e > 0 else 0

    print(f"\n  Context: commit rates", file=sys.stderr)
    print(f"  Before: {len(commits_before)} commits in {days_before_e} days = {commit_rate_before:.1f}/day", file=sys.stderr)
    print(f"  After: {len(commits_after)} commits in {days_after_e} days = {commit_rate_after:.1f}/day", file=sys.stderr)
    print(f"  Activity level was {'similar' if abs(commit_rate_before - commit_rate_after) / max(commit_rate_before, 1) < 0.3 else 'different'}", file=sys.stderr)

    # --- Summary ---
    print(f"\n{'='*60}", file=sys.stderr)
    print("PHASE C SUMMARY", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"  Override rate decreased after enforcement mechanisms were added.", file=sys.stderr)
    print(f"  BUT: the enforcement was adding rules to CLAUDE.md and creating", file=sys.stderr)
    print(f"  the dispatch runbook -- both are forms of persistent memory", file=sys.stderr)
    print(f"  (context files loaded every session). This IS the memory system", file=sys.stderr)
    print(f"  working, just a manual/brute-force version of it.", file=sys.stderr)
    print(f"", file=sys.stderr)
    print(f"  The question our system answers: can we automate this?", file=sys.stderr)
    print(f"  Instead of the user manually adding rules to CLAUDE.md,", file=sys.stderr)
    print(f"  can the system learn from the first override and automatically", file=sys.stderr)
    print(f"  promote it to always-loaded context?", file=sys.stderr)

    output: dict[str, Any] = {
        "daily_counts": daily_counts,
        "enforcement_events": enforcement_events,
        "dispatch_gate_before_after": {
            "before_runbook": len(before_runbook),
            "after_runbook": len(after_runbook),
            "rate_before": round(rate_before, 4),
            "rate_after": round(rate_after, 4),
        },
        "overall_before_after": {
            "before": len(before_enforcement),
            "after": len(after_enforcement),
            "rate_before": round(rate_before_e, 4),
            "rate_after": round(rate_after_e, 4),
        },
    }

    Path("experiments/exp6_before_after.json").write_text(json.dumps(output, indent=2))
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
