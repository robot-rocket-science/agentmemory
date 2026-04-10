"""
Experiment 6 Phase B (v2): Enriched failure detection using OVERRIDES.md + gsd-archive.

OVERRIDES.md contains timestamped user corrections -- each one is a direct observable
instance of the agent forgetting something. This is the highest-quality signal for
memory failures.
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


OVERRIDES_PATH = Path("/Users/thelorax/projects/alpha-seek-memtest/docs/gsd-archive/OVERRIDES.md")
TIMELINE_PATH = Path("experiments/exp6_timeline.json")
OUTPUT_PATH = Path("experiments/exp6_failures_v2.json")


def parse_overrides(path: Path) -> list[dict]:
    """Parse OVERRIDES.md into structured override records."""
    text = path.read_text()
    overrides = []

    # Split on --- delimiters
    blocks = re.split(r'\n---\n', text)

    for block in blocks:
        block = block.strip()
        if not block or block.startswith("# GSD Overrides"):
            continue

        timestamp_match = re.search(r'Override:\s+(\d{4}-\d{2}-\d{2}T[\d:.]+Z)', block)
        change_match = re.search(r'\*\*Change:\*\*\s*(.*?)(?:\n\*\*Scope|\Z)', block, re.DOTALL)
        scope_match = re.search(r'\*\*Scope:\*\*\s*(.*?)(?:\n\*\*Applied|\Z)', block, re.DOTALL)
        applied_match = re.search(r'\*\*Applied-at:\*\*\s*(.*?)(?:\n|\Z)', block)

        if not timestamp_match or not change_match:
            continue

        change_text = change_match.group(1).strip()
        scope_text = scope_match.group(1).strip() if scope_match else ""
        applied_text = applied_match.group(1).strip() if applied_match else ""

        # Extract decision references from scope
        decision_refs = re.findall(r'D(\d{2,3})', scope_text)
        decision_refs = [f"D{d}" for d in decision_refs]

        overrides.append({
            "timestamp": timestamp_match.group(1),
            "change": change_text,
            "scope": scope_text,
            "applied_at": applied_text,
            "decision_refs": decision_refs,
        })

    return overrides


def cluster_overrides_by_topic(overrides: list[dict]) -> list[dict]:
    """Group overrides that are about the same topic (manual pattern matching
    based on content analysis -- these patterns were identified by reading
    the actual OVERRIDES.md content)."""

    topics = {
        "calls_puts_equal_citizens": {
            "keywords": ["calls", "puts", "equal citizens", "call vs put", "d073", "d096", "d100", "d204"],
            "description": "Calls and puts are equal citizens in the strategy",
            "matches": [],
        },
        "dispatch_gate": {
            "keywords": ["dispatch", "deploy gate", "gate", "runbook", "d089", "d106", "d137"],
            "description": "Follow the dispatch/deploy gate protocol",
            "matches": [],
        },
        "capital_5k": {
            "keywords": ["5k", "5,000", "5000", "capital", "bankroll", "d099", "d209"],
            "description": "Starting capital is $5K USD",
            "matches": [],
        },
        "agent_behavior": {
            "keywords": ["pontificat", "philosophiz", "elaborate", "putz", "willy nilly",
                         "hand back control", "do exactly what", "d188", "d157",
                         "async_bash", "await_job"],
            "description": "Agent should execute instructions precisely, no unsolicited elaboration",
            "matches": [],
        },
        "strict_typing": {
            "keywords": ["typed python", "strict typing", "pyright", "d071", "d113"],
            "description": "Use strict static typing (pyright)",
            "matches": [],
        },
        "gcp_primary": {
            "keywords": ["gcp", "primary compute", "archon overflow", "d078", "d120"],
            "description": "GCP is primary compute, archon is overflow only",
            "matches": [],
        },
        "citation_sources": {
            "keywords": ["citation", "cite", "sources", "evidence", "college paper", "d136"],
            "description": "Everything must be cited with evidence",
            "matches": [],
        },
        "anti_overfitting": {
            "keywords": ["overfitting", "overfit", "d132"],
            "description": "Avoid overfitting in all analysis",
            "matches": [],
        },
        "no_artificial_filters": {
            "keywords": ["artificial", "filter", "hard-coded", "rules based", "d118", "d119"],
            "description": "No artificial contract filters, learning-based only",
            "matches": [],
        },
        "research_incorporation": {
            "keywords": ["research findings", "incorporated", "misinterpreted", "execution time",
                         "d194", "d195", "checklist"],
            "description": "Research findings must be verified as incorporated during execution",
            "matches": [],
        },
    }

    # Match overrides to topics
    uncategorized = []
    for override in overrides:
        text = (override["change"] + " " + override["scope"]).lower()
        matched = False
        for topic_id, topic in topics.items():
            if any(kw.lower() in text for kw in topic["keywords"]):
                topic["matches"].append(override)
                matched = True
                break  # first match wins
        if not matched:
            uncategorized.append(override)

    # Build results
    clusters = []
    for topic_id, topic in topics.items():
        if topic["matches"]:
            matches = topic["matches"]
            timestamps = [m["timestamp"] for m in matches]
            date_range = f"{min(timestamps)[:10]} to {max(timestamps)[:10]}" if len(timestamps) > 1 else timestamps[0][:10]

            clusters.append({
                "topic_id": topic_id,
                "description": topic["description"],
                "override_count": len(matches),
                "date_range": date_range,
                "span_days": _days_between(min(timestamps), max(timestamps)) if len(timestamps) > 1 else 0,
                "decision_refs": list(set(ref for m in matches for ref in m["decision_refs"])),
                "overrides": [{
                    "timestamp": m["timestamp"],
                    "change": m["change"][:200],
                    "applied_at": m["applied_at"],
                } for m in matches],
                "is_memory_failure": len(matches) >= 2,
                "severity": "high" if len(matches) >= 3 else "medium" if len(matches) >= 2 else "low",
            })

    clusters.sort(key=lambda x: x["override_count"], reverse=True)

    return clusters, uncategorized


def _days_between(ts1: str, ts2: str) -> int:
    try:
        d1 = datetime.fromisoformat(ts1.replace("Z", "+00:00"))
        d2 = datetime.fromisoformat(ts2.replace("Z", "+00:00"))
        return abs((d2 - d1).days)
    except (ValueError, TypeError):
        return 0


def analyze_override_timeline(overrides: list[dict]) -> dict:
    """Analyze the temporal distribution of overrides."""
    by_date = defaultdict(int)
    for o in overrides:
        date = o["timestamp"][:10]
        by_date[date] += 1

    dates_sorted = sorted(by_date.items())

    # Find the busiest days (most user frustration)
    busiest = sorted(by_date.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "total_overrides": len(overrides),
        "date_range": f"{dates_sorted[0][0]} to {dates_sorted[-1][0]}" if dates_sorted else "none",
        "overrides_per_day": {d: c for d, c in dates_sorted},
        "busiest_days": busiest,
        "mean_per_day": round(len(overrides) / len(by_date), 1) if by_date else 0,
    }


def main():
    print("=" * 60, file=sys.stderr)
    print("Experiment 6 Phase B (v2): Enriched Failure Detection", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Parse overrides
    print("  Parsing OVERRIDES.md...", file=sys.stderr)
    overrides = parse_overrides(OVERRIDES_PATH)
    print(f"    {len(overrides)} overrides parsed", file=sys.stderr)

    # Temporal analysis
    print("  Analyzing override timeline...", file=sys.stderr)
    temporal = analyze_override_timeline(overrides)
    print(f"    Date range: {temporal['date_range']}", file=sys.stderr)
    print(f"    Mean overrides/day: {temporal['mean_per_day']}", file=sys.stderr)
    print(f"    Busiest days:", file=sys.stderr)
    for date, count in temporal["busiest_days"]:
        print(f"      {date}: {count} overrides", file=sys.stderr)

    # Topic clustering
    print("  Clustering overrides by topic...", file=sys.stderr)
    clusters, uncategorized = cluster_overrides_by_topic(overrides)
    print(f"    {len(clusters)} topic clusters", file=sys.stderr)
    print(f"    {len(uncategorized)} uncategorized overrides", file=sys.stderr)

    # Memory failure summary
    memory_failures = [c for c in clusters if c["is_memory_failure"]]
    print(f"\n{'='*60}", file=sys.stderr)
    print("MEMORY FAILURE PATTERNS (topics with 2+ overrides)", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    total_failure_overrides = 0
    for cluster in memory_failures:
        total_failure_overrides += cluster["override_count"]
        print(f"\n  [{cluster['severity'].upper()}] {cluster['description']}", file=sys.stderr)
        print(f"    Overrides: {cluster['override_count']} over {cluster['span_days']} days "
              f"({cluster['date_range']})", file=sys.stderr)
        print(f"    Decisions: {', '.join(cluster['decision_refs'])}", file=sys.stderr)
        for o in cluster["overrides"]:
            print(f"    - {o['timestamp'][:10]} ({o['applied_at']}): "
                  f"{o['change'][:80]}", file=sys.stderr)

    print(f"\n{'='*60}", file=sys.stderr)
    print("SUMMARY", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"  Total overrides: {len(overrides)}", file=sys.stderr)
    print(f"  Memory failure topics (2+ overrides): {len(memory_failures)}", file=sys.stderr)
    print(f"  Overrides in failure topics: {total_failure_overrides}/{len(overrides)} "
          f"({total_failure_overrides/len(overrides)*100:.0f}%)", file=sys.stderr)
    print(f"  Single-issue overrides: {len(overrides) - total_failure_overrides}", file=sys.stderr)
    print(f"  Uncategorized: {len(uncategorized)}", file=sys.stderr)

    # What a memory system would need to prevent each failure
    print(f"\n  What memory would need to provide:", file=sys.stderr)
    for cluster in memory_failures:
        feature = {
            "calls_puts_equal_citizens": "Always-loaded belief (L0/L1): 'calls and puts are equal citizens'",
            "dispatch_gate": "Always-loaded procedural belief (L0): dispatch gate protocol",
            "capital_5k": "Always-loaded factual belief (L0): starting capital = $5K",
            "agent_behavior": "Always-loaded procedural belief (L0): execute precisely, no elaboration",
            "strict_typing": "High-confidence procedural belief: use strict typing",
            "gcp_primary": "Factual belief: GCP primary, archon overflow only",
            "citation_sources": "Procedural belief: cite everything with evidence",
            "research_incorporation": "Procedural belief: verify research incorporated before execution",
        }.get(cluster["topic_id"], "Unknown")
        print(f"    {cluster['topic_id']}: {feature}", file=sys.stderr)

    # Output
    results = {
        "overrides_parsed": len(overrides),
        "temporal": temporal,
        "topic_clusters": clusters,
        "uncategorized_count": len(uncategorized),
        "memory_failures": [{
            "topic": c["topic_id"],
            "description": c["description"],
            "count": c["override_count"],
            "severity": c["severity"],
            "span_days": c["span_days"],
            "decisions": c["decision_refs"],
        } for c in memory_failures],
        "summary": {
            "total_overrides": len(overrides),
            "memory_failure_topics": len(memory_failures),
            "overrides_in_failures": total_failure_overrides,
            "failure_rate": round(total_failure_overrides / len(overrides), 4) if overrides else 0,
        },
    }

    OUTPUT_PATH.write_text(json.dumps(results, indent=2))
    print(f"\nOutput: {OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
