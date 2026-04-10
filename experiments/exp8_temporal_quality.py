"""
Experiment 8: Temporal Quality Signal

Map periods of smooth productive work (no overrides, feature commits) vs
chaotic periods (fixes, overrides, re-debugging). Sessions without overrides
or redundant revisions indicate good LLM performance -- the agent had
sufficient context.

Uses exp6_timeline.json (1,790 events) and exp6_failures_v2.json (38 overrides).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, TypedDict, cast

from scipy.stats import spearmanr  # type: ignore[import-untyped]


TIMELINE_PATH: Path = Path("experiments/exp6_timeline.json")
FAILURES_PATH: Path = Path("experiments/exp6_failures_v2.json")


class DayData(TypedDict):
    feature: int
    fix: int
    docs: int
    test: int
    chore: int
    ops: int
    other: int
    overrides: int
    total_commits: int
    milestone_starts: list[str]
    milestone_ends: list[str]


class DayScore(TypedDict):
    date: str
    commits: int
    features: int
    fixes: int
    overrides: int
    fix_rate: float
    quality: float
    milestones_completed: list[str]


def _make_day_data() -> DayData:
    return DayData(
        feature=0, fix=0, docs=0, test=0,
        chore=0, ops=0, other=0,
        overrides=0, total_commits=0,
        milestone_starts=[], milestone_ends=[],
    )


def classify_commit(message: str) -> str:
    msg: str = message.lower()

    fix_patterns: list[str] = [
        r'\bfix\b', r'\bbug\b', r'\brevert\b', r'\bhotfix\b',
        r'\bworkaround\b', r'\bpatch\b', r'\bcorrect\b',
    ]
    if any(re.search(p, msg) for p in fix_patterns):
        return "fix"

    feat_patterns: list[str] = [
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


def main() -> None:
    timeline: dict[str, Any] = json.loads(TIMELINE_PATH.read_text())
    failures: dict[str, Any] = json.loads(FAILURES_PATH.read_text())

    # Get override timestamps
    override_dates: set[str] = set()
    for cluster in failures["topic_clusters"]:
        for o in cast(list[dict[str, Any]], cluster["overrides"]):
            override_dates.add(str(o["timestamp"])[:10])

    # Classify all commits by date and type
    daily: dict[str, DayData] = {}

    for event in cast(list[dict[str, Any]], timeline["events"]):
        date: str | None = str(event["timestamp"])[:10] if event["timestamp"] else None
        if not date:
            continue

        if date not in daily:
            daily[date] = _make_day_data()

        if event["event_type"] == "commit":
            ctype: str = classify_commit(str(event["content"]))
            daily[date][ctype] += 1  # type: ignore[literal-required]
            daily[date]["total_commits"] += 1

        elif event["event_type"] == "milestone_start":
            daily[date]["milestone_starts"].append(str(event["content"])[:40])

        elif event["event_type"] == "milestone_end":
            daily[date]["milestone_ends"].append(str(event["content"])[:40])

    # Count overrides per day
    for cluster in failures["topic_clusters"]:
        for o in cast(list[dict[str, Any]], cluster["overrides"]):
            date = str(o["timestamp"])[:10]
            if date not in daily:
                daily[date] = _make_day_data()
            daily[date]["overrides"] += 1

    # Compute quality score per day
    # Higher = better (more features, fewer fixes, fewer overrides)
    dates: list[str] = sorted(daily.keys())

    print("=" * 80, file=sys.stderr)
    print("TEMPORAL QUALITY MAP", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    print(f"\n{'Date':<12} {'Commits':>8} {'Feat':>5} {'Fix':>5} {'Ops':>5} "
          f"{'Over':>5} {'Fix%':>6} {'Quality':>8} {'Signal':<30}", file=sys.stderr)
    print("-" * 95, file=sys.stderr)

    day_scores: list[DayScore] = []
    for date in dates:
        d: DayData = daily[date]
        total: int = d["total_commits"]
        if total == 0:
            continue

        fix_rate: float = d["fix"] / total
        override_rate: float = d["overrides"] / max(total, 1)
        feature_rate: float = d["feature"] / total

        # Quality score: feature-heavy days with no overrides = high quality
        # Fix-heavy days with overrides = low quality
        quality: float = feature_rate - fix_rate - (override_rate * 2)
        quality = round(max(-1.0, min(1.0, quality)), 2)

        # Signal: what was the day like?
        signals: list[str] = []
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
        signal: str = ", ".join(signals) if signals else ""

        # Visual bar
        bar_pos: str = "#" * int(max(0, quality) * 10)
        bar_neg: str = "!" * int(max(0, -quality) * 10)

        print(f"{date:<12} {total:>8} {d['feature']:>5} {d['fix']:>5} {d['ops']:>5} "
              f"{d['overrides']:>5} {fix_rate:>6.0%} {quality:>+8.2f} {bar_pos}{bar_neg} {signal}",
              file=sys.stderr)

        day_scores.append(DayScore(
            date=date,
            commits=total,
            features=d["feature"],
            fixes=d["fix"],
            overrides=d["overrides"],
            fix_rate=round(fix_rate, 4),
            quality=quality,
            milestones_completed=d["milestone_ends"],
        ))

    # Correlations
    print(f"\n{'='*80}", file=sys.stderr)
    print("CORRELATIONS", file=sys.stderr)
    print(f"{'='*80}", file=sys.stderr)

    override_counts: list[int] = [d["overrides"] for d in day_scores]
    fix_counts: list[int] = [d["fixes"] for d in day_scores]
    feature_counts: list[int] = [d["features"] for d in day_scores]
    qualities: list[float] = [d["quality"] for d in day_scores]

    rho_fix_override: float = 0.0
    rho_feat_override: float = 0.0
    rho_quality_override: float = 0.0
    p_fix: float = 1.0
    p_feat: float = 1.0
    p_qual: float = 1.0

    if len(override_counts) > 3:
        rho_fix_override = float(cast(Any, spearmanr(fix_counts, override_counts)).statistic)
        p_fix = float(cast(Any, spearmanr(fix_counts, override_counts)).pvalue)
        rho_feat_override = float(cast(Any, spearmanr(feature_counts, override_counts)).statistic)
        p_feat = float(cast(Any, spearmanr(feature_counts, override_counts)).pvalue)
        rho_quality_override = float(cast(Any, spearmanr(qualities, override_counts)).statistic)
        p_qual = float(cast(Any, spearmanr(qualities, override_counts)).pvalue)

        print(f"  Fix count vs overrides:     rho={rho_fix_override:+.3f} (p={p_fix:.4f})", file=sys.stderr)
        print(f"  Feature count vs overrides:  rho={rho_feat_override:+.3f} (p={p_feat:.4f})", file=sys.stderr)
        print(f"  Quality score vs overrides:  rho={rho_quality_override:+.3f} (p={p_qual:.4f})", file=sys.stderr)

    # Best and worst days
    sorted_days: list[DayScore] = sorted(day_scores, key=lambda d: d["quality"])
    print(f"\n  Worst 3 days (most chaotic):", file=sys.stderr)
    for ds in sorted_days[:3]:
        print(f"    {ds['date']}: quality={ds['quality']:+.2f}, "
              f"{ds['commits']} commits, {ds['fixes']} fixes, {ds['overrides']} overrides", file=sys.stderr)

    print(f"\n  Best 3 days (most productive):", file=sys.stderr)
    for ds in sorted_days[-3:]:
        print(f"    {ds['date']}: quality={ds['quality']:+.2f}, "
              f"{ds['commits']} commits, {ds['features']} features, {ds['overrides']} overrides", file=sys.stderr)

    # Phase analysis: early project vs late project
    midpoint: int = len(day_scores) // 2
    early: list[DayScore] = day_scores[:midpoint]
    late: list[DayScore] = day_scores[midpoint:]
    early_qual: list[float] = [d["quality"] for d in early]
    late_qual: list[float] = [d["quality"] for d in late]

    print(f"\n  Early project (first {len(early)} days): mean quality={sum(early_qual)/len(early_qual):+.3f}",
          file=sys.stderr)
    print(f"  Late project (last {len(late)} days):  mean quality={sum(late_qual)/len(late_qual):+.3f}",
          file=sys.stderr)

    output: dict[str, Any] = {
        "daily_scores": day_scores,
        "correlations": {
            "fix_vs_override_rho": round(rho_fix_override, 4) if len(override_counts) > 3 else None,
            "feature_vs_override_rho": round(rho_feat_override, 4) if len(override_counts) > 3 else None,
            "quality_vs_override_rho": round(rho_quality_override, 4) if len(override_counts) > 3 else None,
        },
    }
    Path("experiments/exp8_temporal_results.json").write_text(json.dumps(output, indent=2))
    print(f"\nOutput: experiments/exp8_temporal_results.json", file=sys.stderr)


if __name__ == "__main__":
    main()
