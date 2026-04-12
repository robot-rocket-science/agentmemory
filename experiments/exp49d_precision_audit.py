"""
Experiment 49d: Extractor Precision Audit + Correction Burden Measurement

For each extractor, sample extracted items and classify as correct/incorrect.
Report false positive rate per extractor and estimated total correction burden.

Also defines the correction burden measurement protocol for future experiments.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PYTHONPATH_SET = True
from experiments.exp49_onboarding_validation import (
    PROJECTS, discover, extract_file_tree, extract_git_history,
    extract_document_sentences, extract_ast_calls,
    extract_directives,
)
from experiments.exp49c_entity_edges import detect_entities, build_entity_edges


# ============================================================
# Precision validators (heuristic ground truth)
# ============================================================

def validate_commit_beliefs(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Commit beliefs are verbatim git messages. FP = message that's not a meaningful belief."""
    commits = [n for n in nodes if n["type"] == "commit_belief"]
    if not commits:
        return {"total": 0, "fp": 0, "fp_rate": 0.0, "samples": []}

    fp_patterns = [
        re.compile(r"^(wip|fix|update|bump|chore|docs|style|refactor|test|ci|build)\s*$", re.IGNORECASE),
        re.compile(r"^(merge|Merge)\b"),
        re.compile(r"^\S+$"),  # Single word
        re.compile(r"^v?\d+\.\d+"),  # Version numbers
    ]

    fps: list[dict[str, Any]] = []
    for n in commits:
        content = n.get("content", "")
        if len(content) < 10:  # Too short to be meaningful
            fps.append({"id": n["id"], "content": content, "reason": "too_short"})
        else:
            for pat in fp_patterns:
                if pat.match(content):
                    fps.append({"id": n["id"], "content": content, "reason": "noise_pattern"})
                    break

    return {
        "total": len(commits),
        "fp": len(fps),
        "fp_rate": round(len(fps) / len(commits), 3) if commits else 0,
        "samples": fps[:10],
    }


def validate_doc_sentences(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Doc sentences should be meaningful assertions. FP = fragments, metadata, noise."""
    sentences = [n for n in nodes if n["type"] in ("sentence", "heading")]
    if not sentences:
        return {"total": 0, "fp": 0, "fp_rate": 0.0, "samples": []}

    fps: list[dict[str, Any]] = []
    for n in sentences:
        content = n.get("content", "").strip()

        # Table fragments
        if content.startswith("|") or content.startswith("---"):
            fps.append({"id": n["id"], "content": content[:80], "reason": "table_fragment"})
            continue

        # List markers only
        if re.match(r"^[-*]\s*$", content):
            fps.append({"id": n["id"], "content": content[:80], "reason": "empty_list_item"})
            continue

        # Pure metadata/formatting
        if re.match(r"^(Status:|Date:|Type:|Source:)\s*\S+$", content):
            fps.append({"id": n["id"], "content": content[:80], "reason": "metadata_only"})
            continue

        # Very short non-heading (likely fragment)
        if n["type"] == "sentence" and len(content) < 25:
            fps.append({"id": n["id"], "content": content[:80], "reason": "too_short"})
            continue

        # URLs only
        if re.match(r"^https?://\S+$", content):
            fps.append({"id": n["id"], "content": content[:80], "reason": "url_only"})
            continue

    return {
        "total": len(sentences),
        "fp": len(fps),
        "fp_rate": round(len(fps) / len(sentences), 3) if sentences else 0,
        "samples": fps[:15],
    }


def validate_calls_edges(edges: list[dict[str, Any]]) -> dict[str, Any]:
    """CALLS edges from resolved AST. FP = call to a different function with same name (shadowing)."""
    calls = [e for e in edges if e["type"] == "CALLS"]
    if not calls:
        return {"total": 0, "fp": 0, "fp_rate": 0.0, "note": "no CALLS edges"}

    # Resolved intra-file calls have ~0% FP (syntactically verifiable).
    # We flag cases where the same function name appears in multiple files
    # (potential shadowing/misresolution).
    target_names: Counter[str] = Counter()
    for e in calls:
        func_name: str = e["tgt"].split(".")[-1] if "." in e["tgt"] else e["tgt"]
        target_names[func_name] += 1

    # Functions called from multiple files with same name = potential misresolution
    ambiguous: dict[str, int] = {name: count for name, count in target_names.items() if count > 5}

    return {
        "total": len(calls),
        "fp": 0,  # Can't determine without runtime; syntactically correct
        "fp_rate": 0.0,
        "note": "Syntactically resolved; FP requires runtime verification",
        "potentially_ambiguous": len(ambiguous),
        "ambiguous_names": dict(list(ambiguous.items())[:10]),
    }


def validate_entity_edges(
    entity_edges: list[dict[str, Any]],
    mentions: dict[str, list[tuple[str, str]]],
) -> dict[str, Any]:
    """Entity edges. FP = wrong entity classification (concept as person, etc.)."""
    results: dict[str, Any] = {}

    # Person validation: check for known non-person patterns
    non_person_indicators = {
        "home", "assistant", "environment", "server", "service", "system",
        "plug", "smart", "dev", "integration", "engineering", "review",
        "request", "model", "compare", "action", "pipeline", "test",
        "config", "network", "module", "component", "manager", "controller",
    }

    person_mentions = mentions.get("PERSON_INVOLVED", [])
    person_entities = set(v for _, v in person_mentions)

    fp_persons: list[str] = []
    tp_persons: list[str] = []
    for name in person_entities:
        words = name.lower().split()
        if any(w in non_person_indicators for w in words):
            fp_persons.append(name)
        else:
            tp_persons.append(name)

    results["PERSON_INVOLVED"] = {
        "total_entities": len(person_entities),
        "likely_correct": len(tp_persons),
        "likely_fp": len(fp_persons),
        "fp_rate": round(len(fp_persons) / max(1, len(person_entities)), 3),
        "fp_samples": fp_persons[:15],
        "tp_samples": tp_persons[:10],
    }

    # Incident validation: incident-NN pattern is high precision
    incident_mentions = mentions.get("INCIDENT_LINKED", [])
    incident_entities = set(v for _, v in incident_mentions)
    results["INCIDENT_LINKED"] = {
        "total_entities": len(incident_entities),
        "fp_rate": 0.0,
        "note": "Pattern-matched IDs; high precision by construction",
    }

    # Host validation: hardcoded list, high precision
    host_mentions = mentions.get("HOST_LINKED", [])
    host_entities = set(v for _, v in host_mentions)
    results["HOST_LINKED"] = {
        "total_entities": len(host_entities),
        "fp_rate": 0.0,
        "note": "Matched against known infrastructure names; high precision",
    }

    # Date validation: Month Day pattern, high precision
    date_mentions = mentions.get("DATE_COOCCURS", [])
    date_entities = set(v for _, v in date_mentions)
    results["DATE_COOCCURS"] = {
        "total_entities": len(date_entities),
        "fp_rate": 0.0,
        "note": "Month Day pattern; syntactically correct dates",
    }

    # Entity edge FP rate (how many edges connect via FP entities?)
    fp_entity_set = set(fp_persons)
    fp_edges = [e for e in entity_edges if e.get("entity") in fp_entity_set]

    results["entity_edges"] = {
        "total": len(entity_edges),
        "from_fp_entities": len(fp_edges),
        "fp_edge_rate": round(len(fp_edges) / max(1, len(entity_edges)), 3),
    }

    return results


# ============================================================
# Correction burden estimator
# ============================================================

def estimate_correction_burden(
    commit_audit: dict[str, Any],
    sentence_audit: dict[str, Any],
    calls_audit: dict[str, Any],
    entity_audit: dict[str, Any],
) -> dict[str, Any]:
    """Estimate total wrong beliefs stored and potential corrections per session."""

    total_stored = (commit_audit["total"] + sentence_audit["total"] +
                    calls_audit["total"])
    total_fp = commit_audit["fp"] + sentence_audit["fp"] + calls_audit["fp"]

    # Entity FP contribution
    person_fp_entities = entity_audit.get("PERSON_INVOLVED", {}).get("likely_fp", 0)
    entity_edge_fps = entity_audit.get("entity_edges", {}).get("from_fp_entities", 0)

    # Estimated beliefs a user might encounter per session (assume 10 retrievals, top-5 each)
    retrievals_per_session = 50  # 10 queries x 5 results
    encounter_rate = retrievals_per_session / max(1, total_stored)

    # Expected wrong beliefs encountered per session
    wrong_encounters = total_fp * encounter_rate + entity_edge_fps * encounter_rate

    return {
        "total_beliefs_stored": total_stored,
        "total_fp_beliefs": total_fp,
        "overall_fp_rate": round(total_fp / max(1, total_stored), 4),
        "entity_fp_edges": entity_edge_fps,
        "fp_person_entities": person_fp_entities,
        "retrievals_per_session": retrievals_per_session,
        "expected_wrong_per_session": round(wrong_encounters, 2),
        "verdict": "ACCEPTABLE" if wrong_encounters < 1.0 else "NEEDS_FIXING",
    }


# ============================================================
# Main
# ============================================================

def main() -> None:
    print("=" * 70, file=sys.stderr)
    print("Experiment 49d: Precision Audit + Correction Burden", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    all_results: dict[str, Any] = {}

    for name, root in PROJECTS.items():
        print(f"\n{'='*50}", file=sys.stderr)
        print(f"Project: {name}", file=sys.stderr)
        print(f"{'='*50}", file=sys.stderr)

        # Extract everything
        manifest = discover(root)
        all_nodes: list[dict[str, Any]] = []
        all_edges: list[dict[str, Any]] = []

        ft_nodes, ft_edges = extract_file_tree(root)
        all_nodes.extend(ft_nodes)
        all_edges.extend(ft_edges)

        if manifest["has_git"]:
            git_nodes, git_edges = extract_git_history(root)
            all_nodes.extend(git_nodes)
            all_edges.extend(git_edges)

        if manifest["doc_count"] > 0:
            doc_nodes, doc_edges = extract_document_sentences(root, manifest["doc_files"])
            all_nodes.extend(doc_nodes)
            all_edges.extend(doc_edges)

        if manifest["languages"]:
            ast_nodes, ast_edges = extract_ast_calls(root, manifest["languages"])
            all_nodes.extend(ast_nodes)
            all_edges.extend(ast_edges)

        if manifest["directives"]:
            dir_nodes = extract_directives(root, manifest["directives"])
            all_nodes.extend(dir_nodes)

        # Entity detection
        mentions = detect_entities(all_nodes)
        entity_edges = build_entity_edges(mentions)
        all_edges.extend(entity_edges)

        # Audit each extractor
        commit_audit = validate_commit_beliefs(all_nodes)
        sentence_audit = validate_doc_sentences(all_nodes)
        calls_audit = validate_calls_edges(all_edges)
        entity_audit = validate_entity_edges(entity_edges, mentions)

        # Correction burden
        burden = estimate_correction_burden(commit_audit, sentence_audit, calls_audit, entity_audit)

        # Print results
        print(f"\n  Commit beliefs: {commit_audit['total']} total, {commit_audit['fp']} FP ({commit_audit['fp_rate']:.0%})", file=sys.stderr)
        if commit_audit["samples"]:
            for s in commit_audit["samples"][:3]:
                print(f"    FP: '{s['content'][:60]}' ({s['reason']})", file=sys.stderr)

        print(f"\n  Doc sentences: {sentence_audit['total']} total, {sentence_audit['fp']} FP ({sentence_audit['fp_rate']:.0%})", file=sys.stderr)
        if sentence_audit["samples"]:
            for s in sentence_audit["samples"][:5]:
                print(f"    FP: '{s['content'][:60]}' ({s['reason']})", file=sys.stderr)

        print(f"\n  CALLS edges: {calls_audit['total']} total, FP rate ~0% (syntactic)", file=sys.stderr)
        if calls_audit.get("potentially_ambiguous"):
            print(f"    Potentially ambiguous names: {calls_audit['potentially_ambiguous']}", file=sys.stderr)

        print(f"\n  Entity detection:", file=sys.stderr)
        for etype, audit_val in entity_audit.items():
            audit_d: dict[str, Any] = audit_val
            if etype == "entity_edges":
                print(f"    Entity edges: {audit_d['total']} total, {audit_d['from_fp_entities']} from FP entities ({audit_d['fp_edge_rate']:.0%})", file=sys.stderr)
            elif "total_entities" in audit_d:
                fp_rate: float = audit_d.get("fp_rate", 0)
                print(f"    {etype}: {audit_d['total_entities']} entities, FP rate {fp_rate:.0%}", file=sys.stderr)
                fp_samples: list[str] = audit_d.get("fp_samples", [])
                if fp_samples:
                    for fp_item in fp_samples[:5]:
                        print(f"      FP: {fp_item}", file=sys.stderr)

        print(f"\n  CORRECTION BURDEN:", file=sys.stderr)
        print(f"    Total beliefs stored: {burden['total_beliefs_stored']}", file=sys.stderr)
        print(f"    Total FP beliefs: {burden['total_fp_beliefs']} ({burden['overall_fp_rate']:.1%})", file=sys.stderr)
        print(f"    FP person entities: {burden['fp_person_entities']}", file=sys.stderr)
        print(f"    FP entity edges: {burden['entity_fp_edges']}", file=sys.stderr)
        print(f"    Expected wrong encounters/session: {burden['expected_wrong_per_session']}", file=sys.stderr)
        print(f"    Verdict: {burden['verdict']}", file=sys.stderr)

        all_results[name] = {
            "commit_audit": commit_audit,
            "sentence_audit": {k: v for k, v in sentence_audit.items() if k != "samples"},
            "calls_audit": calls_audit,
            "entity_audit": entity_audit,
            "correction_burden": burden,
        }

    # Summary
    print(f"\n{'='*70}", file=sys.stderr)
    print("SUMMARY: Correction Burden by Project", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)
    print(f"\n  {'Project':<15} {'Beliefs':>10} {'FP':>8} {'FP Rate':>10} {'Entity FP':>12} {'Wrong/Session':>15} {'Verdict':>12}", file=sys.stderr)
    print(f"  {'-'*85}", file=sys.stderr)
    for name, r in all_results.items():
        b = r["correction_burden"]
        print(f"  {name:<15} {b['total_beliefs_stored']:>10} {b['total_fp_beliefs']:>8} "
              f"{b['overall_fp_rate']:>10.1%} {b['entity_fp_edges']:>12} "
              f"{b['expected_wrong_per_session']:>15.2f} {b['verdict']:>12}", file=sys.stderr)

    # Save
    out = Path("experiments/exp49d_results.json")
    out.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nResults saved to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
