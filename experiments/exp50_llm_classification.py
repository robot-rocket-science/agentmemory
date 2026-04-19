"""
Experiment 50: LLM Classification Accuracy for Precision Enrichment

Since we can't make API calls directly, this experiment:
1. Builds the exact prompts that would be sent
2. Includes pre-classified ground truth (human-labeled)
3. Measures what accuracy threshold the LLM approach needs to beat the heuristic
4. Estimates token cost from prompt structure

The ground truth labeling is done manually from the entity/directive samples
collected in the design phase.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from collections.abc import Callable
from typing import Any


# ============================================================
# Ground truth: manually labeled samples
# ============================================================

# project-d entities: labeled as PERSON or NOT_PERSON
PROJECT_D_ENTITIES: list[dict[str, str]] = [
    # TRUE PERSONS (should be classified PERSON)
    # (project-d has very few actual person names in docs)
    # NOT_PERSON (concepts, products, services, categories)
    {"name": "Apple Home", "truth": "NOT_PERSON", "what": "smart home platform"},
    {"name": "Smart Home", "truth": "NOT_PERSON", "what": "category/domain"},
    {"name": "Dev Environment", "truth": "NOT_PERSON", "what": "infrastructure tier"},
    {"name": "Primary Slice", "truth": "NOT_PERSON", "what": "GSD planning term"},
    {"name": "Shelly Plug", "truth": "NOT_PERSON", "what": "IoT hardware"},
    {"name": "Expected Output", "truth": "NOT_PERSON", "what": "test concept"},
    {"name": "Switch Advanced", "truth": "NOT_PERSON", "what": "network config page"},
    {"name": "Home Assistant", "truth": "NOT_PERSON", "what": "software service"},
    {"name": "Observability Impact", "truth": "NOT_PERSON", "what": "analysis concept"},
    {"name": "Persistent Agent", "truth": "NOT_PERSON", "what": "software concept"},
    {"name": "Fleet Hardening", "truth": "NOT_PERSON", "what": "security concept"},
    {"name": "What Happened", "truth": "NOT_PERSON", "what": "section heading"},
    {"name": "Files Created", "truth": "NOT_PERSON", "what": "section heading"},
    {"name": "Recently Added", "truth": "NOT_PERSON", "what": "UI category"},
    {"name": "Home Security", "truth": "NOT_PERSON", "what": "category"},
    {"name": "Add Integration", "truth": "NOT_PERSON", "what": "UI action"},
    {"name": "Deferred Human", "truth": "NOT_PERSON", "what": "process step"},
    {"name": "Smart Plug", "truth": "NOT_PERSON", "what": "IoT hardware"},
    {"name": "Smart Switch", "truth": "NOT_PERSON", "what": "IoT hardware"},
    {"name": "Nest Protect", "truth": "NOT_PERSON", "what": "Google product"},
    {"name": "Power Relay", "truth": "NOT_PERSON", "what": "hardware component"},
    {"name": "Server-B Resource", "truth": "NOT_PERSON", "what": "server resource ref"},
    {"name": "Developer Tools", "truth": "NOT_PERSON", "what": "software category"},
    {"name": "Verification Evidence", "truth": "NOT_PERSON", "what": "process concept"},
    {"name": "Level Verification", "truth": "NOT_PERSON", "what": "process step"},
    {"name": "Known Issues", "truth": "NOT_PERSON", "what": "section heading"},
    {"name": "Quick Task", "truth": "NOT_PERSON", "what": "GSD concept"},
    {"name": "Human Checkpoint", "truth": "NOT_PERSON", "what": "process step"},
    {"name": "Shelly Hardware", "truth": "NOT_PERSON", "what": "IoT brand ref"},
    {"name": "Add Accessory", "truth": "NOT_PERSON", "what": "UI action"},
    {"name": "Eufy Security", "truth": "NOT_PERSON", "what": "security product"},
    {"name": "Master Bedroom", "truth": "NOT_PERSON", "what": "room name"},
    {"name": "Living Room", "truth": "NOT_PERSON", "what": "room name"},
    {"name": "Homebridge Cleanup", "truth": "NOT_PERSON", "what": "task name"},
    {"name": "Table Reconciliation", "truth": "NOT_PERSON", "what": "process step"},
    {"name": "Half Men", "truth": "NOT_PERSON", "what": "TV show fragment"},
    {
        "name": "Network Segmentation",
        "truth": "NOT_PERSON",
        "what": "networking concept",
    },
    {
        "name": "Fleet Management",
        "truth": "NOT_PERSON",
        "what": "infrastructure concept",
    },
    {"name": "User Acceptance", "truth": "NOT_PERSON", "what": "testing concept"},
    {"name": "Core Mission", "truth": "NOT_PERSON", "what": "planning concept"},
]

# project-c entities
project-c_ENTITIES: list[dict[str, str]] = [
    # TRUE PERSONS
    {"name": "Jonathan Sobol", "truth": "PERSON", "what": "plaintiff"},
    {"name": "Jose Marcio", "truth": "PERSON", "what": "antagonist (first+middle)"},
    {"name": "Vieira Dias", "truth": "PERSON", "what": "antagonist (surname)"},
    {"name": "Anbarasu Chandran", "truth": "PERSON", "what": "manager"},
    {"name": "Darren Lang", "truth": "PERSON", "what": "colleague"},
    {"name": "Takuya Kubota", "truth": "PERSON", "what": "colleague"},
    {"name": "Yusuke Mishima", "truth": "PERSON", "what": "colleague"},
    {"name": "Shuji Hoshino", "truth": "PERSON", "what": "colleague"},
    {
        "name": "Jose Vieira",
        "truth": "PERSON",
        "what": "antagonist (alternate name form)",
    },
    # NOT_PERSON
    {"name": "Model Compare", "truth": "NOT_PERSON", "what": "tool name"},
    {"name": "From Screenshot", "truth": "NOT_PERSON", "what": "evidence source label"},
    {"name": "Microsoft Teams", "truth": "NOT_PERSON", "what": "software product"},
    {"name": "Honda Research", "truth": "NOT_PERSON", "what": "company name"},
    {"name": "Tool Pull", "truth": "NOT_PERSON", "what": "process step"},
    {"name": "Falls Apart", "truth": "NOT_PERSON", "what": "descriptive phrase"},
    {"name": "Senior Engineering", "truth": "NOT_PERSON", "what": "job level"},
    {"name": "Why This", "truth": "NOT_PERSON", "what": "section heading"},
    {"name": "The March", "truth": "NOT_PERSON", "what": "temporal ref"},
    {"name": "Evidence Files", "truth": "NOT_PERSON", "what": "section heading"},
    {"name": "Has Merit", "truth": "NOT_PERSON", "what": "judgment phrase"},
    {"name": "Aerojet Rocketdyne", "truth": "NOT_PERSON", "what": "company name"},
    {"name": "Public Reprimand", "truth": "NOT_PERSON", "what": "incident type"},
    {"name": "Git Rule", "truth": "NOT_PERSON", "what": "technical rule"},
    {"name": "Quoting Jose", "truth": "NOT_PERSON", "what": "evidence label"},
    {"name": "Universal Hydrogen", "truth": "NOT_PERSON", "what": "company name"},
    {"name": "Docker Proposal", "truth": "NOT_PERSON", "what": "document name"},
    {"name": "Requesting Task", "truth": "NOT_PERSON", "what": "process step"},
    {"name": "Key Facts", "truth": "NOT_PERSON", "what": "section heading"},
    {
        "name": "Ownership Bypassed",
        "truth": "NOT_PERSON",
        "what": "incident description",
    },
    {"name": "Platform Lockout", "truth": "NOT_PERSON", "what": "incident type"},
    {"name": "Quoting Jonathan", "truth": "NOT_PERSON", "what": "evidence label"},
    {"name": "Detailed Incident", "truth": "NOT_PERSON", "what": "section heading"},
    {"name": "Monte Carlo", "truth": "NOT_PERSON", "what": "algorithm/method"},
    {"name": "Robot Framework", "truth": "NOT_PERSON", "what": "testing tool"},
    {
        "name": "Astronautical Engineering",
        "truth": "NOT_PERSON",
        "what": "field of study",
    },
    {"name": "Systems Analysis", "truth": "NOT_PERSON", "what": "skill name"},
    {"name": "Public Microsoft", "truth": "NOT_PERSON", "what": "evidence context"},
    {
        "name": "Development Environment",
        "truth": "NOT_PERSON",
        "what": "technical concept",
    },
    {"name": "Task Assignment", "truth": "NOT_PERSON", "what": "process concept"},
    {"name": "Ubuntu Linux", "truth": "NOT_PERSON", "what": "operating system"},
]

# project-a directives
project-a_DIRECTIVES: list[dict[str, str]] = [
    # TRUE DIRECTIVES (rules the agent must follow)
    {"text": "Never question this.", "truth": "DIRECTIVE"},
    {"text": "Never skip the pre-flight checklist.", "truth": "DIRECTIVE"},
    {
        "text": "Do not merge code that introduces new pyright errors.",
        "truth": "DIRECTIVE",
    },
    {"text": "Do not allocate GCP runs for daily rescoring.", "truth": "DIRECTIVE"},
    {
        "text": "Every run_command in gcp_dispatch.py should specify --initial-capital 5000 explicitly, never relying on defaults.",
        "truth": "DIRECTIVE",
    },
    # NOT DIRECTIVES (factual statements containing directive-like words)
    {
        "text": "M018-S02 Batch 2 was never dispatched (milestone closed NEGATIVE after S02 infrastructure failure).",
        "truth": "NOT_DIRECTIVE",
    },
    {
        "text": "Higher floors ($5.00) reduce bankruptcy rate but do not eliminate it.",
        "truth": "NOT_DIRECTIVE",
    },
    {
        "text": "This is NOT a fill model rejection issue -- the pipeline never even considers >97% of universe events.",
        "truth": "NOT_DIRECTIVE",
    },
    {
        "text": "However, the profitable years do not overlap -- different mechanisms drive profit in different years.",
        "truth": "NOT_DIRECTIVE",
    },
    {
        "text": "GCS upload was never triggered because the walk-forward script uploads only after all 13 folds complete.",
        "truth": "NOT_DIRECTIVE",
    },
    {"text": "The active bankroll never exceeds $5K.", "truth": "NOT_DIRECTIVE"},
    {
        "text": "The signal fires on events that look like historical declines but do not produce historical-style rallies.",
        "truth": "NOT_DIRECTIVE",
    },
    {
        "text": "They were run on the pre-fix Docker image where handle_expiry() was never called.",
        "truth": "NOT_DIRECTIVE",
    },
    {
        "text": "The delta floor was found to be essentially inactive -- 77% of events have score < 0.10.",
        "truth": "NOT_DIRECTIVE",
    },
    {
        "text": "The --initial-capital CLI default was changed from $100K to $5K in commit efef0bb.",
        "truth": "NOT_DIRECTIVE",
    },
]


# ============================================================
# Heuristic baseline (what our current filter does)
# ============================================================

NON_PERSON_WORDS = {
    "home",
    "assistant",
    "environment",
    "server",
    "service",
    "system",
    "plug",
    "smart",
    "dev",
    "integration",
    "engineering",
    "review",
    "request",
    "model",
    "compare",
    "action",
    "pipeline",
    "test",
    "config",
    "network",
    "module",
    "component",
    "manager",
    "controller",
    "video",
    "garage",
    "door",
    "sensor",
    "camera",
    "bridge",
    "hub",
    "steps",
    "plan",
    "task",
    "check",
    "setup",
    "install",
    "update",
    "build",
    "release",
    "deploy",
    "monitor",
    "alert",
    "status",
    "chat",
    "support",
    "takeover",
    "smoke",
    "fill",
    "neural",
    "best",
    "code",
    "data",
    "file",
    "path",
    "run",
    "agent",
}


def heuristic_person(name: str) -> str:
    words = {w.lower() for w in name.split()}
    if words & NON_PERSON_WORDS:
        return "NOT_PERSON"
    return "PERSON"


def heuristic_directive(text: str) -> str:
    import re

    patterns = [
        re.compile(r"\b(BANNED)\b"),
        re.compile(r"\b[Nn]ever\s+\w+"),
        re.compile(r"\b[Aa]lways\s+\w+"),
        re.compile(r"\b[Mm]ust\s+not\b"),
        re.compile(r"\b[Dd]o\s+not\b"),
        re.compile(r"\b[Dd]on't\b"),
    ]
    for p in patterns:
        if p.search(text):
            return "DIRECTIVE"
    return "NOT_DIRECTIVE"


# ============================================================
# LLM prompt construction (what would be sent)
# ============================================================


def build_entity_prompt(
    entities: list[dict[str, str]], project_desc: str, batch_size: int = 20
) -> list[dict[str, Any]]:
    """Build the prompts that would be sent for entity classification."""
    batches: list[dict[str, Any]] = []

    for i in range(0, len(entities), batch_size):
        batch = entities[i : i + batch_size]
        items = "\n".join(f'{j + 1}. "{e["name"]}"' for j, e in enumerate(batch))

        prompt = f"""Project: {project_desc}

Classify each item as PERSON (real human name) or NOT_PERSON (product, service, concept, category, section heading, company, or anything else that is not a real person's name):

{items}

Respond with just the number and classification, one per line. Example:
1. PERSON
2. NOT_PERSON"""

        # Estimate tokens (rough: 1 token per 4 chars)
        input_tokens = len(prompt) // 4
        output_tokens = len(batch) * 15  # "1. NOT_PERSON\n" per item

        batches.append(
            {
                "prompt": prompt,
                "batch": batch,
                "input_tokens_est": input_tokens,
                "output_tokens_est": output_tokens,
                "total_tokens_est": input_tokens + output_tokens,
            }
        )

    return batches


def build_directive_prompt(
    sentences: list[dict[str, str]], project_desc: str, batch_size: int = 20
) -> list[dict[str, Any]]:
    """Build prompts for directive classification."""
    batches: list[dict[str, Any]] = []

    for i in range(0, len(sentences), batch_size):
        batch = sentences[i : i + batch_size]
        items = "\n".join(f'{j + 1}. "{s["text"][:150]}"' for j, s in enumerate(batch))

        prompt = f"""Project: {project_desc}

Classify each sentence as DIRECTIVE (a rule or instruction the agent must follow) or NOT_DIRECTIVE (a factual statement, observation, or description that happens to contain words like "never", "always", "do not"):

A DIRECTIVE tells someone what to DO or NOT DO. Example: "Never skip the pre-flight checklist."
A NOT_DIRECTIVE describes what IS or WAS. Example: "The upload was never triggered because X."

{items}

Respond with just the number and classification, one per line."""

        input_tokens = len(prompt) // 4
        output_tokens = len(batch) * 18

        batches.append(
            {
                "prompt": prompt,
                "batch": batch,
                "input_tokens_est": input_tokens,
                "output_tokens_est": output_tokens,
                "total_tokens_est": input_tokens + output_tokens,
            }
        )

    return batches


# ============================================================
# Analysis
# ============================================================


def score_heuristic(
    samples: list[dict[str, str]],
    classify_fn: Callable[[str], str],
    truth_key: str = "truth",
) -> dict[str, Any]:
    """Score the heuristic classifier against ground truth."""
    correct: int = 0
    wrong: list[dict[str, str]] = []
    for s in samples:
        pred: str = classify_fn(s.get("name", s.get("text", "")))
        if pred == s[truth_key]:
            correct += 1
        else:
            wrong.append(
                {
                    "item": s.get("name", s.get("text", ""))[:60],
                    "predicted": pred,
                    "truth": s[truth_key],
                }
            )

    return {
        "total": len(samples),
        "correct": correct,
        "accuracy": round(correct / len(samples), 3) if samples else 0,
        "errors": wrong,
    }


def main() -> None:
    print("=" * 70, file=sys.stderr)
    print("Experiment 50: LLM Classification Accuracy Analysis", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    results: dict[str, Any] = {}

    # Test 1: Entity classification (project-d)
    print("\n--- Test 1: Entity Classification (project-d) ---", file=sys.stderr)
    deb_heuristic = score_heuristic(PROJECT_D_ENTITIES, heuristic_person)
    print(
        f"  Heuristic accuracy: {deb_heuristic['accuracy']:.0%} ({deb_heuristic['correct']}/{deb_heuristic['total']})",
        file=sys.stderr,
    )
    if deb_heuristic["errors"]:
        for e in deb_heuristic["errors"][:5]:
            print(
                f"    WRONG: '{e['item']}' predicted={e['predicted']} truth={e['truth']}",
                file=sys.stderr,
            )

    deb_prompts = build_entity_prompt(
        PROJECT_D_ENTITIES, "project-d (home server infrastructure fleet)"
    )
    total_tokens = sum(b["total_tokens_est"] for b in deb_prompts)
    print(
        f"  LLM prompt: {len(deb_prompts)} batch(es), ~{total_tokens} tokens total",
        file=sys.stderr,
    )
    results["project-d_entity"] = {
        "heuristic": deb_heuristic,
        "llm_batches": len(deb_prompts),
        "llm_tokens_est": total_tokens,
    }

    # Test 2: Entity classification (project-c)
    print("\n--- Test 2: Entity Classification (project-c) ---", file=sys.stderr)
    jb_heuristic = score_heuristic(project-c_ENTITIES, heuristic_person)
    print(
        f"  Heuristic accuracy: {jb_heuristic['accuracy']:.0%} ({jb_heuristic['correct']}/{jb_heuristic['total']})",
        file=sys.stderr,
    )
    if jb_heuristic["errors"]:
        for e in jb_heuristic["errors"][:5]:
            print(
                f"    WRONG: '{e['item']}' predicted={e['predicted']} truth={e['truth']}",
                file=sys.stderr,
            )

    jb_prompts = build_entity_prompt(
        project-c_ENTITIES, "project-c (workplace situation documentation)"
    )
    total_tokens = sum(b["total_tokens_est"] for b in jb_prompts)
    print(
        f"  LLM prompt: {len(jb_prompts)} batch(es), ~{total_tokens} tokens total",
        file=sys.stderr,
    )
    results["project_c_entity"] = {
        "heuristic": jb_heuristic,
        "llm_batches": len(jb_prompts),
        "llm_tokens_est": total_tokens,
    }

    # Test 3: Directive classification (project-a)
    print("\n--- Test 3: Directive Classification (project-a) ---", file=sys.stderr)
    as_heuristic = score_heuristic(project-a_DIRECTIVES, heuristic_directive)
    print(
        f"  Heuristic accuracy: {as_heuristic['accuracy']:.0%} ({as_heuristic['correct']}/{as_heuristic['total']})",
        file=sys.stderr,
    )
    if as_heuristic["errors"]:
        for e in as_heuristic["errors"][:5]:
            print(
                f"    WRONG: '{e['item']}' predicted={e['predicted']} truth={e['truth']}",
                file=sys.stderr,
            )

    as_prompts = build_directive_prompt(
        project-a_DIRECTIVES, "project-a (options trading strategy system)"
    )
    total_tokens = sum(b["total_tokens_est"] for b in as_prompts)
    print(
        f"  LLM prompt: {len(as_prompts)} batch(es), ~{total_tokens} tokens total",
        file=sys.stderr,
    )
    results["project_a_directive"] = {
        "heuristic": as_heuristic,
        "llm_batches": len(as_prompts),
        "llm_tokens_est": total_tokens,
    }

    # Summary: what accuracy does the LLM need to beat?
    print(f"\n{'=' * 70}", file=sys.stderr)
    print("SUMMARY: Heuristic Baseline to Beat", file=sys.stderr)
    print(f"{'=' * 70}", file=sys.stderr)

    print(
        f"\n  {'Task':<35} {'Heuristic':>12} {'Errors':>8} {'LLM Tokens':>12}",
        file=sys.stderr,
    )
    print(f"  {'-' * 70}", file=sys.stderr)

    for label, key in [
        ("project-d entity (40 items)", "project-d_entity"),
        ("project-c entity (40 items)", "project_c_entity"),
        ("project-a directive (20 items)", "project_a_directive"),
    ]:
        r = results[key]
        h = r["heuristic"]
        print(
            f"  {label:<35} {h['accuracy']:>12.0%} {len(h['errors']):>8} {r['llm_tokens_est']:>12}",
            file=sys.stderr,
        )

    # Amortization math
    print("\n--- Amortization Analysis ---", file=sys.stderr)

    total_llm_tokens = sum(r["llm_tokens_est"] for r in results.values())
    total_heuristic_errors = sum(
        len(r["heuristic"]["errors"]) for r in results.values()
    )

    print(
        f"  Total LLM tokens for all classifications: ~{total_llm_tokens}",
        file=sys.stderr,
    )
    print(
        f"  Total heuristic errors on test set: {total_heuristic_errors}",
        file=sys.stderr,
    )

    # Cost at Haiku pricing ($0.25/MTok input, $1.25/MTok output)
    # Rough: 80% input, 20% output
    input_cost = total_llm_tokens * 0.8 * 0.25 / 1_000_000
    output_cost = total_llm_tokens * 0.2 * 1.25 / 1_000_000
    total_cost = input_cost + output_cost
    print(f"  Estimated cost (Haiku): ${total_cost:.5f}", file=sys.stderr)
    print(
        f"  Cost per classification: ${total_cost / max(1, sum(len(PROJECT_D_ENTITIES) + len(project-c_ENTITIES) + len(project-a_DIRECTIVES) for _ in [0])):.6f}",
        file=sys.stderr,
    )

    if total_heuristic_errors > 0:
        cost_per_prevented_error = total_cost / total_heuristic_errors
        print(
            f"  Cost per prevented error (if LLM is perfect): ${cost_per_prevented_error:.5f}",
            file=sys.stderr,
        )

    # Break-even: if each error costs 500 tokens of correction prompting
    correction_token_cost = total_heuristic_errors * 500
    print("\n  If each error costs ~500 tokens to correct:", file=sys.stderr)
    print(
        f"    Correction token cost: ~{correction_token_cost} tokens", file=sys.stderr
    )
    print(f"    LLM classification cost: ~{total_llm_tokens} tokens", file=sys.stderr)
    print(
        f"    Token ROI: {correction_token_cost / max(1, total_llm_tokens):.1f}x",
        file=sys.stderr,
    )

    # Per-session amortization over 10 sessions
    per_session_correction = correction_token_cost  # All errors encountered once
    amortized_10 = (
        per_session_correction * 10
    )  # Same errors re-encountered over 10 sessions
    print(
        f"    Over 10 sessions: {amortized_10} correction tokens saved vs {total_llm_tokens} LLM tokens spent",
        file=sys.stderr,
    )
    print(
        f"    10-session ROI: {amortized_10 / max(1, total_llm_tokens):.1f}x",
        file=sys.stderr,
    )

    # Save
    out = Path("experiments/exp47_results.json")
    out.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nResults saved to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
