"""
Experiment 8: Temporal Quality Signal

Map periods of smooth productive work (no overrides, feature commits) vs
chaotic periods (fixes, overrides, re-debugging). Sessions without overrides
or redundant revisions indicate good LLM performance -- the agent had
sufficient context.

Uses exp6_timeline.json (1,790 events) and exp6_failures_v2.json (38 overrides).
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path


TIMELINE_PATH = Path("experiments/exp6_timeline.json")
FAILURES_PATH = Path("experiments/exp6_failures_v2.json")


def classify_commit(message: str) -> str:
    """Classify a commit as productive work vs corrective work."""
    msg = message.lower()

    fix_patterns = [
        r'\bfix\b', r'\bbug\b', r'\brevert\b', r'\bhotfix\b',
        r'\bworkaround\b', r'\bpatch\b', r'\bcorrect\b',
    ]
    if any(re.search(p, msg) for p in fix_patterns):
        return "fix"

    feat_patterns = [
        r'\bfeat\b', r'\badd\b', r'\bimplement\b', r'\bbuild\b',
        r'\bcreate\b', r'\bnew\b',
    ]
    if any(re.search(p, msg) for p in feat_patterns):
        return "feature"

    if re.search(r'\bdocs?\b|\bupdate.*md\b|\breadme\b', msg):
        return "docs"

    if re.search(r'\btest\b|\bspec\b|\bverif', msg):
        return "test"

    if re.search(r'\bchore\b|\bauto-commit\b|\brefactor\b', msg):
        return "chore"

    if re.search(r'\bops\b|\bdispatch\b|\bdeploy\b|\binfra\b', msg):
        return "ops"

    return "other"


def main():
    timeline = json.loads(TIMELINE_PATH.read_text())
    failures = json.loads(FAILURES_PATH.read_text())

    # Get override timestamps
    override_dates = set()
    for cluster in failures["topic_clusters"]:
        for o in cluster["overrides"]:
            override_dates.add(o["timestamp"][:10])

    # Classify all commits by date and type
    daily = defaultdict(lambda: {
        "feature": 0, "fix": 0, "docs": 0, "test": 0,
        "chore": 0, "ops": 0, "other": 0,
        "overrides": 0, "total_commits": 0,
        "milestone_starts": [], "milestone_ends": [],
    })

    for event in timeline["events"]:
        date = event["timestamp"][:10] if event["timestamp"] else None
        if not date:
            continue

        if event["event_type"] == "commit":
            ctype = classify_commit(event["content"])
            daily[date][ctype] += 1
            daily[date]["total_commits"] += 1

        elif event["event_type"] == "milestone_start":
            daily[date]["milestone_starts"].append(event["content"][:40])

        elif event["event_type"] == "milestone_end":
            daily[date]["milestone_ends"].append(event["content"][:40])

    # Count overrides per day
    for cluster in failures["topic_clusters"]:
        for o in cluster["overrides"]:
            date = o["timestamp"][:10]
            daily[date]["overrides"] += 1

    # Compute quality score per day
    # Higher = better (more features, fewer fixes, fewer overrides)
    dates = sorted(daily.keys())

    print("=" * 80, file=sys.stderr)
    print("TEMPORAL QUALITY MAP", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    print(f"\n{'Date':<12} {'Commits':>8} {'Feat':>5} {'Fix':>5} {'Ops':>5} "
          f"{'Over':>5} {'Fix%':>6} {'Quality':>8} {'Signal':<30}", file=sys.stderr)
    print("-" * 95, file=sys.stderr)

    day_scores = []
    for date in dates:
        d = daily[date]
        total = d["total_commits"]
        if total == 0:
            continue

        fix_rate = d["fix"] / total
        override_rate = d["overrides"] / max(total, 1)
        feature_rate = d["feature"] / total

        # Quality score: feature-heavy days with no overrides = high quality
        # Fix-heavy days with overrides = low quality
        quality = feature_rate - fix_rate - (override_rate * 2)
        quality = round(max(-1.0, min(1.0, quality)), 2)

        # Signal: what was the day like?
        signals = []
        if d["overrides"] >= 3:
            signals.append("HIGH FRICTION")
        elif d["overrides"] >= 1:
            signals.append("friction")
        if fix_rate >= 0.30:
            signals.append("fix-heavy")
        if feature_rate >= 0.50:
            signals.append("productive")
        if d["milestone_ends"]:
            signals.append(f"completed: {d['milestone_ends'][0]}")
        if d["milestone_starts"]:
            signals.append(f"started: {d['milestone_starts'][0]}")
        signal = ", ".join(signals) if signals else ""

        # Visual bar
        bar_pos = "#" * int(max(0, quality) * 10)
        bar_neg = "!" * int(max(0, -quality) * 10)

        print(f"{date:<12} {total:>8} {d['feature']:>5} {d['fix']:>5} {d['ops']:>5} "
              f"{d['overrides']:>5} {fix_rate:>6.0%} {quality:>+8.2f} {bar_pos}{bar_neg} {signal}",
              file=sys.stderr)

        day_scores.append({
            "date": date,
            "commits": total,
            "features": d["feature"],
            "fixes": d["fix"],
            "overrides": d["overrides"],
            "fix_rate": round(fix_rate, 4),
            "quality": quality,
            "milestones_completed": d["milestone_ends"],
        })

    # Correlations
    print(f"\n{'='*80}", file=sys.stderr)
    print("CORRELATIONS", file=sys.stderr)
    print(f"{'='*80}", file=sys.stderr)

    override_counts = [d["overrides"] for d in day_scores]
    fix_counts = [d["fixes"] for d in day_scores]
    feature_counts = [d["features"] for d in day_scores]
    qualities = [d["quality"] for d in day_scores]

    from scipy.stats import spearmanr

    if len(override_counts) > 3:
        rho_fix_override, p_fix = spearmanr(fix_counts, override_counts)
        rho_feat_override, p_feat = spearmanr(feature_counts, override_counts)
        rho_quality_override, p_qual = spearmanr(qualities, override_counts)

        print(f"  Fix count vs overrides:     rho={rho_fix_override:+.3f} (p={p_fix:.4f})", file=sys.stderr)
        print(f"  Feature count vs overrides:  rho={rho_feat_override:+.3f} (p={p_feat:.4f})", file=sys.stderr)
        print(f"  Quality score vs overrides:  rho={rho_quality_override:+.3f} (p={p_qual:.4f})", file=sys.stderr)

    # Best and worst days
    sorted_days = sorted(day_scores, key=lambda d: d["quality"])
    print(f"\n  Worst 3 days (most chaotic):", file=sys.stderr)
    for d in sorted_days[:3]:
        print(f"    {d['date']}: quality={d['quality']:+.2f}, "
              f"{d['commits']} commits, {d['fixes']} fixes, {d['overrides']} overrides", file=sys.stderr)

    print(f"\n  Best 3 days (most productive):", file=sys.stderr)
    for d in sorted_days[-3:]:
        print(f"    {d['date']}: quality={d['quality']:+.2f}, "
              f"{d['commits']} commits, {d['features']} features, {d['overrides']} overrides", file=sys.stderr)

    # Phase analysis: early project vs late project
    midpoint = len(day_scores) // 2
    early = day_scores[:midpoint]
    late = day_scores[midpoint:]
    early_qual = [d["quality"] for d in early]
    late_qual = [d["quality"] for d in late]

    print(f"\n  Early project (first {len(early)} days): mean quality={sum(early_qual)/len(early_qual):+.3f}",
          file=sys.stderr)
    print(f"  Late project (last {len(late)} days):  mean quality={sum(late_qual)/len(late_qual):+.3f}",
          file=sys.stderr)

    output = {
        "daily_scores": day_scores,
        "correlations": {
            "fix_vs_override_rho": round(float(rho_fix_override), 4) if len(override_counts) > 3 else None,
            "feature_vs_override_rho": round(float(rho_feat_override), 4) if len(override_counts) > 3 else None,
            "quality_vs_override_rho": round(float(rho_quality_override), 4) if len(override_counts) > 3 else None,
        },
    }
    Path("experiments/exp8_temporal_results.json").write_text(json.dumps(output, indent=2))
    print(f"\nOutput: experiments/exp8_temporal_results.json", file=sys.stderr)


if __name__ == "__main__":
    main()
