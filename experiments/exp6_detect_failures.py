"""
Experiment 6 Phase B: Detect memory failure patterns P1-P5 in alpha-seek history.

P1: Repeated decisions (similar decision issued without referencing the original)
P2: Repeated research (same investigation topic across milestones without citation)
P3: Avoidable debugging (same error pattern fixed multiple times)
P4: Repeated procedural instructions (runbook, dispatch gate reminders)
P5: Dispatch gate failures (agent skipped protocol, caused failures)
"""

import json
import re
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path


TIMELINE_PATH = Path("experiments/exp6_timeline.json")


def load_timeline() -> dict:
    return json.loads(TIMELINE_PATH.read_text())


# --- Text Similarity (zero-LLM) ---

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must", "ought",
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "under", "again", "further", "then", "once", "here",
    "there", "when", "where", "why", "how", "all", "each", "every",
    "both", "few", "more", "most", "other", "some", "such", "no",
    "not", "only", "own", "same", "so", "than", "too", "very",
    "and", "but", "or", "nor", "if", "this", "that", "these", "those",
    "it", "its", "i", "we", "they", "he", "she", "you", "me", "him",
    "her", "us", "them", "my", "our", "your", "his", "their",
}


def tokenize(text: str) -> set[str]:
    words = re.findall(r'[a-z0-9]+', text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union)


# --- P1: Repeated Decisions ---

def detect_repeated_decisions(timeline: dict) -> dict:
    """Find decision pairs with high similarity but no citation link between them."""
    print("  P1: Detecting repeated decisions...", file=sys.stderr)

    decisions = [e for e in timeline["events"] if e["event_type"] == "decision"]
    edges = timeline["edges"]

    # Build citation set: which decisions cite each other?
    citation_pairs = set()
    for edge in edges:
        if edge["type"] in ("CITES", "SUPERSEDES", "SOURCED_FROM"):
            citation_pairs.add((edge["from"], edge["to"]))
            citation_pairs.add((edge["to"], edge["from"]))

    # Tokenize all decisions
    decision_tokens = {}
    for d in decisions:
        decision_tokens[d["id"]] = tokenize(d["content"])

    # Compare all pairs
    candidates = []
    for d1, d2 in combinations(decisions, 2):
        id1, id2 = d1["id"], d2["id"]

        # Skip if they already cite each other (intentional relationship)
        if (id1, id2) in citation_pairs:
            continue

        sim = jaccard(decision_tokens[id1], decision_tokens[id2])
        if sim >= 0.25:  # threshold: 25% word overlap
            candidates.append({
                "decision_1": id1,
                "decision_2": id2,
                "similarity": round(sim, 4),
                "content_1": d1["content"][:150],
                "content_2": d2["content"][:150],
                "context_1": d1["context"],
                "context_2": d2["context"],
                "cited": False,
            })

    candidates.sort(key=lambda x: x["similarity"], reverse=True)

    print(f"    {len(candidates)} candidate repeated decision pairs (sim >= 0.25)", file=sys.stderr)
    for c in candidates[:10]:
        print(f"    {c['decision_1']}-{c['decision_2']}: sim={c['similarity']:.3f}", file=sys.stderr)
        print(f"      1: {c['content_1'][:80]}", file=sys.stderr)
        print(f"      2: {c['content_2'][:80]}", file=sys.stderr)

    return {
        "pattern": "P1_repeated_decisions",
        "total_decisions": len(decisions),
        "citation_pairs": len(citation_pairs),
        "candidates": candidates,
        "candidate_count": len(candidates),
    }


# --- P2: Repeated Research ---

def detect_repeated_research(timeline: dict) -> dict:
    """Find knowledge entries across different milestones covering the same topic."""
    print("  P2: Detecting repeated research...", file=sys.stderr)

    knowledge = [e for e in timeline["events"] if e["event_type"] == "knowledge"]

    # Group knowledge by milestone context
    by_milestone = defaultdict(list)
    for k in knowledge:
        ctx = k["context"]
        # Extract milestone ID
        m = re.match(r'M(\d{3})', ctx)
        if m:
            by_milestone[f"M{m.group(1)}"].append(k)
        else:
            by_milestone["_ungrouped"].append(k)

    # Compare knowledge across milestones
    milestone_pairs = list(combinations(
        [(m, entries) for m, entries in by_milestone.items() if m != "_ungrouped"],
        2
    ))

    cross_milestone_overlaps = []
    for (m1, entries1), (m2, entries2) in milestone_pairs:
        for k1 in entries1:
            tokens1 = tokenize(k1["content"])
            for k2 in entries2:
                tokens2 = tokenize(k2["content"])
                sim = jaccard(tokens1, tokens2)
                if sim >= 0.30:
                    # Check if they reference each other
                    k1_refs = set(k1.get("references", []))
                    k2_refs = set(k2.get("references", []))
                    cross_cited = bool(k1_refs & {k2["id"]}) or bool(k2_refs & {k1["id"]})

                    cross_milestone_overlaps.append({
                        "entry_1": k1["id"],
                        "entry_2": k2["id"],
                        "milestone_1": m1,
                        "milestone_2": m2,
                        "similarity": round(sim, 4),
                        "content_1": k1["content"][:150],
                        "content_2": k2["content"][:150],
                        "cross_cited": cross_cited,
                    })

    cross_milestone_overlaps.sort(key=lambda x: x["similarity"], reverse=True)
    uncited = [o for o in cross_milestone_overlaps if not o["cross_cited"]]

    print(f"    {len(cross_milestone_overlaps)} cross-milestone overlaps (sim >= 0.30)", file=sys.stderr)
    print(f"    {len(uncited)} without cross-citation (potential repeated research)", file=sys.stderr)

    for o in uncited[:5]:
        print(f"    {o['entry_1']}({o['milestone_1']}) - {o['entry_2']}({o['milestone_2']}): "
              f"sim={o['similarity']:.3f}", file=sys.stderr)
        print(f"      1: {o['content_1'][:80]}", file=sys.stderr)
        print(f"      2: {o['content_2'][:80]}", file=sys.stderr)

    return {
        "pattern": "P2_repeated_research",
        "total_knowledge": len(knowledge),
        "milestones_with_knowledge": len(by_milestone) - (1 if "_ungrouped" in by_milestone else 0),
        "cross_milestone_overlaps": len(cross_milestone_overlaps),
        "uncited_overlaps": len(uncited),
        "candidates": uncited[:50],  # top 50 for review
    }


# --- P3: Avoidable Debugging ---

def detect_repeated_debugging(timeline: dict) -> dict:
    """Find commits with error/fix patterns that appear multiple times."""
    print("  P3: Detecting repeated debugging sessions...", file=sys.stderr)

    commits = [e for e in timeline["events"] if e["event_type"] == "commit"]

    # Keywords indicating debugging/fixing
    fix_patterns = [
        r'\bfix(?:ed|es|ing)?\b',
        r'\bbug\b',
        r'\bdebug\b',
        r'\brevert\b',
        r'\bhotfix\b',
        r'\bworkaround\b',
        r'\bpatch\b',
        r'\bresolve[sd]?\b',
        r'\bcorrect(?:ed|ion|s)?\b',
    ]

    fix_commits = []
    for c in commits:
        msg = c["content"].lower()
        if any(re.search(p, msg) for p in fix_patterns):
            fix_commits.append(c)

    # Group fix commits by topic (tokenized similarity)
    fix_tokens = [(c, tokenize(c["content"])) for c in fix_commits]

    # Find clusters of similar fix commits
    fix_clusters = []
    used = set()

    for i, (c1, t1) in enumerate(fix_tokens):
        if i in used:
            continue
        cluster = [c1]
        used.add(i)

        for j, (c2, t2) in enumerate(fix_tokens):
            if j in used or j <= i:
                continue
            if jaccard(t1, t2) >= 0.25:
                cluster.append(c2)
                used.add(j)

        if len(cluster) >= 2:
            fix_clusters.append({
                "size": len(cluster),
                "commits": [{
                    "id": c["id"],
                    "content": c["content"][:120],
                    "timestamp": c["timestamp"],
                    "context": c["context"],
                } for c in cluster],
            })

    fix_clusters.sort(key=lambda x: x["size"], reverse=True)

    print(f"    {len(fix_commits)} fix/debug commits out of {len(commits)} total", file=sys.stderr)
    print(f"    {len(fix_clusters)} clusters of similar fixes (potential re-debugging)", file=sys.stderr)

    for cluster in fix_clusters[:5]:
        print(f"    Cluster (size {cluster['size']}):", file=sys.stderr)
        for c in cluster["commits"][:3]:
            print(f"      {c['timestamp'][:10]} {c['content'][:70]}", file=sys.stderr)

    return {
        "pattern": "P3_repeated_debugging",
        "total_commits": len(commits),
        "fix_commits": len(fix_commits),
        "fix_commit_rate": round(len(fix_commits) / len(commits), 4) if commits else 0,
        "similar_fix_clusters": len(fix_clusters),
        "clusters": fix_clusters[:20],
    }


# --- P4: Repeated Procedural Instructions ---

def detect_repeated_instructions(timeline: dict) -> dict:
    """Find decisions that repeatedly instruct the same procedure."""
    print("  P4: Detecting repeated procedural instructions...", file=sys.stderr)

    decisions = [e for e in timeline["events"] if e["event_type"] == "decision"]

    # Keywords indicating procedural rules/instructions
    procedural_keywords = [
        "must", "always", "never", "rule", "protocol", "runbook",
        "gate", "dispatch", "follow", "ensure", "require", "mandatory",
        "hard rule", "do not", "don't",
    ]

    procedural_decisions = []
    for d in decisions:
        content_lower = d["content"].lower()
        matches = [kw for kw in procedural_keywords if kw in content_lower]
        if matches:
            procedural_decisions.append({
                **d,
                "matched_keywords": matches,
            })

    # Find clusters of similar procedural decisions
    proc_tokens = [(d, tokenize(d["content"])) for d in procedural_decisions]
    clusters = []
    used = set()

    for i, (d1, t1) in enumerate(proc_tokens):
        if i in used:
            continue
        cluster = [d1]
        used.add(i)

        for j, (d2, t2) in enumerate(proc_tokens):
            if j in used or j <= i:
                continue
            if jaccard(t1, t2) >= 0.20:  # lower threshold for procedural
                cluster.append(d2)
                used.add(j)

        if len(cluster) >= 2:
            clusters.append({
                "size": len(cluster),
                "topic": cluster[0]["content"][:80],
                "decisions": [{
                    "id": d["id"],
                    "content": d["content"][:150],
                    "context": d["context"],
                    "keywords": d["matched_keywords"],
                } for d in cluster],
            })

    clusters.sort(key=lambda x: x["size"], reverse=True)

    # Also specifically look for dispatch gate and runbook mentions
    dispatch_decisions = [d for d in decisions if "dispatch" in d["content"].lower()]
    runbook_decisions = [d for d in decisions if "runbook" in d["content"].lower()]

    print(f"    {len(procedural_decisions)} procedural decisions out of {len(decisions)}", file=sys.stderr)
    print(f"    {len(clusters)} clusters of repeated instructions", file=sys.stderr)
    print(f"    {len(dispatch_decisions)} dispatch-related decisions", file=sys.stderr)
    print(f"    {len(runbook_decisions)} runbook-related decisions", file=sys.stderr)

    for cluster in clusters[:5]:
        print(f"    Cluster (size {cluster['size']}): {cluster['topic'][:60]}", file=sys.stderr)
        for d in cluster["decisions"][:3]:
            print(f"      {d['id']}: {d['content'][:70]}", file=sys.stderr)

    return {
        "pattern": "P4_repeated_instructions",
        "total_decisions": len(decisions),
        "procedural_decisions": len(procedural_decisions),
        "instruction_clusters": len(clusters),
        "dispatch_decisions": len(dispatch_decisions),
        "runbook_decisions": len(runbook_decisions),
        "clusters": clusters[:20],
        "dispatch_details": [{
            "id": d["id"],
            "content": d["content"][:200],
            "context": d["context"],
        } for d in dispatch_decisions],
        "runbook_details": [{
            "id": d["id"],
            "content": d["content"][:200],
            "context": d["context"],
        } for d in runbook_decisions],
    }


# --- P5: Dispatch Gate Failures ---

def detect_dispatch_failures(timeline: dict) -> dict:
    """Find commits indicating dispatch failures or gate violations."""
    print("  P5: Detecting dispatch gate failures...", file=sys.stderr)

    commits = [e for e in timeline["events"] if e["event_type"] == "commit"]

    # Patterns indicating dispatch problems
    dispatch_failure_patterns = [
        r'dispatch.*fail',
        r'dispatch.*fix',
        r'dispatch.*gate',
        r'gate.*dispatch',
        r'dispatch.*error',
        r'dispatch.*block',
        r'dispatch.*revert',
        r'gcp.*dispatch.*fix',
        r'fix.*dispatch',
    ]

    dispatch_failures = []
    for c in commits:
        msg = c["content"].lower()
        for p in dispatch_failure_patterns:
            if re.search(p, msg):
                dispatch_failures.append({
                    "id": c["id"],
                    "content": c["content"][:150],
                    "timestamp": c["timestamp"],
                    "context": c["context"],
                    "pattern": p,
                })
                break

    # Also look for knowledge entries about dispatch issues
    knowledge = [e for e in timeline["events"] if e["event_type"] == "knowledge"]
    dispatch_knowledge = [k for k in knowledge if "dispatch" in k["content"].lower()]

    print(f"    {len(dispatch_failures)} dispatch-related failure commits", file=sys.stderr)
    print(f"    {len(dispatch_knowledge)} dispatch-related knowledge entries", file=sys.stderr)

    for df in dispatch_failures[:5]:
        print(f"    {df['timestamp'][:10]} {df['content'][:80]}", file=sys.stderr)

    return {
        "pattern": "P5_dispatch_failures",
        "dispatch_failure_commits": len(dispatch_failures),
        "dispatch_knowledge_entries": len(dispatch_knowledge),
        "failures": dispatch_failures,
        "knowledge": [{
            "id": k["id"],
            "content": k["content"][:200],
        } for k in dispatch_knowledge],
    }


# --- Main ---

def main():
    print("=" * 60, file=sys.stderr)
    print("Experiment 6 Phase B: Detecting Memory Failure Patterns", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    timeline = load_timeline()

    results = {}
    results["p1"] = detect_repeated_decisions(timeline)
    results["p2"] = detect_repeated_research(timeline)
    results["p3"] = detect_repeated_debugging(timeline)
    results["p4"] = detect_repeated_instructions(timeline)
    results["p5"] = detect_dispatch_failures(timeline)

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print("FAILURE PATTERN SUMMARY", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"  P1 Repeated decisions:       {results['p1']['candidate_count']} candidates", file=sys.stderr)
    print(f"  P2 Repeated research:        {results['p2']['uncited_overlaps']} uncited overlaps", file=sys.stderr)
    print(f"  P3 Repeated debugging:       {results['p3']['similar_fix_clusters']} fix clusters", file=sys.stderr)
    print(f"  P4 Repeated instructions:    {results['p4']['instruction_clusters']} clusters "
          f"({results['p4']['dispatch_decisions']} dispatch, "
          f"{results['p4']['runbook_decisions']} runbook)", file=sys.stderr)
    print(f"  P5 Dispatch failures:        {results['p5']['dispatch_failure_commits']} failure commits", file=sys.stderr)

    output_path = Path("experiments/exp6_failures.json")
    output_path.write_text(json.dumps(results, indent=2))
    print(f"\nOutput: {output_path}", file=sys.stderr)

    print(json.dumps({
        "summary": {
            "p1_repeated_decisions": results["p1"]["candidate_count"],
            "p2_repeated_research": results["p2"]["uncited_overlaps"],
            "p3_repeated_debugging": results["p3"]["similar_fix_clusters"],
            "p4_repeated_instructions": results["p4"]["instruction_clusters"],
            "p4_dispatch_decisions": results["p4"]["dispatch_decisions"],
            "p4_runbook_decisions": results["p4"]["runbook_decisions"],
            "p5_dispatch_failures": results["p5"]["dispatch_failure_commits"],
        }
    }, indent=2))


if __name__ == "__main__":
    main()
