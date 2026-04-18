"""Exp86: Structural prompt analysis for task-type detection.

Tests whether analyzing prompt structure (enumerated items, scope breadth,
action verb class, entity density) can detect task types more accurately
than keyword-only classification (27% baseline from H1 rejection).

Also tests subagent-suitability detection: can we reliably identify prompts
where parallel agent dispatch would benefit the user?

Usage:
    uv run python experiments/exp86_structural_prompt_analysis.py
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Structural signals
# ---------------------------------------------------------------------------

# Action verb classes mapped to task types
VERB_CLASSES: dict[str, list[str]] = {
    "planning": [
        "plan", "design", "architect", "roadmap", "outline", "scope",
        "milestone", "breakdown", "decompose", "strategize", "schedule",
    ],
    "deployment": [
        "deploy", "push", "ship", "release", "publish", "launch",
        "merge", "promote", "rollout", "stage",
    ],
    "debugging": [
        "fix", "debug", "diagnose", "troubleshoot", "bisect", "trace",
        "investigate", "reproduce", "isolate", "patch", "address",
    ],
    "implementation": [
        "build", "implement", "create", "add", "wire", "integrate",
        "configure", "setup", "scaffold", "bootstrap",
    ],
    "validation": [
        "test", "verify", "validate", "check", "audit", "review",
        "confirm", "assert", "benchmark", "measure", "pytest", "run",
    ],
    "research": [
        "research", "explore", "investigate", "analyze", "study",
        "compare", "evaluate", "wonder", "hypothesize", "survey",
    ],
}

# Sequential markers (anti-parallel signals)
SEQUENTIAL_MARKERS: list[str] = [
    "then", "after that", "next", "once that's done", "first.*then",
    "step by step", "carefully", "one at a time", "sequentially",
    "before we", "wait for", "depends on",
]

# Parallel markers (NOTE: "also" removed -- too common, 87.8% FP rate in exp87)
PARALLEL_MARKERS: list[str] = [
    "in parallel", "at the same time", "meanwhile", "concurrently",
    "simultaneously", "spawn subagent", "use subagent", "use agent",
    "in parallel", "all at once", "at once",
]

# Planning instruction phrases (the user's habitual patterns)
PLANNING_PHRASES: list[str] = [
    "make a plan", "make a todo", "todo list", "follow the plan",
    "verify the steps", "stay on track", "execute the plan",
    "refer to the runbook", "check the docs", "best practices",
]

# Enumeration patterns
ENUM_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\s*\d+[\.\)]\s+", re.MULTILINE),           # "1. item" or "1) item"
    re.compile(r"^\s*[-*]\s+", re.MULTILINE),                 # "- item" or "* item"
    re.compile(r"\b(?:first|second|third|fourth|fifth)\b", re.IGNORECASE),
]

# Stopwords for entity extraction
STOPWORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can",
    "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "up", "about", "into", "through", "during", "before", "after",
    "above", "below", "between", "out", "off", "over", "under",
    "again", "further", "then", "once", "here", "there", "when",
    "where", "why", "how", "all", "each", "every", "both", "few",
    "more", "most", "other", "some", "such", "no", "nor", "not",
    "only", "own", "same", "so", "than", "too", "very", "just",
    "because", "as", "until", "while", "this", "that", "these",
    "those", "it", "its", "i", "me", "my", "we", "our", "you",
    "your", "he", "him", "his", "she", "her", "they", "them",
    "their", "what", "which", "who", "whom", "and", "but", "or",
    "if", "ok", "yes", "no", "yeah", "yea", "sure", "let",
    "make", "need", "want", "like", "get", "got", "go", "going",
    "know", "think", "see", "look", "use", "work", "try",
}


@dataclass
class StructuralAnalysis:
    """Result of structural prompt analysis."""

    task_types: list[str] = field(default_factory=list)
    subagent_suitable: bool = False
    subagent_signals: list[str] = field(default_factory=list)
    enumerated_items: int = 0
    unique_entities: int = 0
    word_count: int = 0
    imperative_density: float = 0.0
    verb_scores: dict[str, float] = field(default_factory=dict)
    has_sequential_markers: bool = False
    has_parallel_markers: bool = False
    planning_phrases_found: list[str] = field(default_factory=list)
    confidence: float = 0.0


def extract_entities(text: str) -> list[str]:
    """Extract potential entity names (CamelCase, paths, dotted names)."""
    entities: list[str] = []

    # CamelCase words
    entities.extend(re.findall(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", text))

    # File paths
    entities.extend(re.findall(r"[\w./]+\.(?:py|js|ts|md|json|yaml|yml|sh|sql)\b", text))

    # Dotted identifiers (module.function)
    entities.extend(re.findall(r"\b\w+\.\w+(?:\.\w+)*\b", text))

    # Snake_case identifiers (likely code)
    entities.extend(
        w for w in re.findall(r"\b[a-z]+_[a-z_]+\b", text)
        if w not in STOPWORDS and len(w) > 4
    )

    return list(set(entities))


def count_enumerated_items(text: str) -> int:
    """Count enumerated list items in the prompt."""
    total: int = 0
    for pattern in ENUM_PATTERNS:
        total += len(pattern.findall(text))

    # Also count comma-separated items in imperative context
    # e.g., "fix A, B, and C"
    comma_lists: list[str] = re.findall(
        r"(?:fix|update|check|review|test|add|remove|delete)\s+(.+?)(?:\.|$)",
        text, re.IGNORECASE,
    )
    for cl in comma_lists:
        items: list[str] = [x.strip() for x in re.split(r",\s*(?:and\s+)?", cl) if x.strip()]
        if len(items) >= 2:
            total += len(items)

    return total


def split_compound_words(text: str) -> str:
    """Split compound words like 'bugfix' into 'bug fix' for verb detection."""
    # Common compound patterns in coding context
    compounds: dict[str, str] = {
        "bugfix": "bug fix", "hotfix": "hot fix", "quickfix": "quick fix",
        "refactor": "refactor", "unittest": "unit test",
    }
    result: str = text
    for compound, split in compounds.items():
        result = re.sub(rf"\b{compound}\b", split, result, flags=re.IGNORECASE)

    # Also split camelCase/snake_case for verb detection
    # "runTests" -> "run Tests", "run_tests" -> "run tests"
    result = re.sub(r"([a-z])([A-Z])", r"\1 \2", result)
    result = result.replace("_", " ")
    return result


def detect_verb_class(text: str) -> dict[str, float]:
    """Score each task type by verb presence."""
    # Pre-process: split compounds for better verb detection
    expanded: str = split_compound_words(text)
    text_lower: str = expanded.lower()
    words: list[str] = re.findall(r"\b\w+\b", text_lower)
    scores: dict[str, float] = {}

    for task_type, verbs in VERB_CLASSES.items():
        hits: int = sum(1 for w in words if w in verbs)
        if hits > 0:
            # Normalize by total word count to avoid bias toward long prompts
            scores[task_type] = hits / max(len(words), 1) * 100
    return scores


def analyze_prompt(text: str) -> StructuralAnalysis:
    """Run full structural analysis on a prompt."""
    result = StructuralAnalysis()

    # Basic metrics
    words: list[str] = text.split()
    result.word_count = len(words)

    # Entity extraction
    entities: list[str] = extract_entities(text)
    result.unique_entities = len(entities)

    # Enumerated items
    result.enumerated_items = count_enumerated_items(text)

    # Verb class scoring
    result.verb_scores = detect_verb_class(text)

    # Sequential vs parallel markers
    text_lower: str = text.lower()
    for marker in SEQUENTIAL_MARKERS:
        if re.search(marker, text_lower):
            result.has_sequential_markers = True
            break

    for marker in PARALLEL_MARKERS:
        if marker in text_lower:
            result.has_parallel_markers = True
            break

    # Planning phrases
    for phrase in PLANNING_PHRASES:
        if phrase in text_lower:
            result.planning_phrases_found.append(phrase)

    # Imperative density: count sentences starting with a verb
    sentences: list[str] = re.split(r"[.!?\n]+", text)
    imperative_count: int = 0
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        first_word: str = sent.split()[0].lower() if sent.split() else ""
        all_verbs: list[str] = [v for verbs in VERB_CLASSES.values() for v in verbs]
        if first_word in all_verbs or first_word in {
            "run", "execute", "start", "stop", "open", "close", "read",
            "write", "update", "delete", "remove", "install", "set",
        }:
            imperative_count += 1
    total_sentences: int = max(len([s for s in sentences if s.strip()]), 1)
    result.imperative_density = imperative_count / total_sentences

    # --- Task type detection ---
    # Sort verb scores, take top types above threshold
    sorted_types: list[tuple[str, float]] = sorted(
        result.verb_scores.items(), key=lambda x: x[1], reverse=True,
    )
    for task_type, score in sorted_types:
        if score > 0.5:  # At least 0.5% verb density
            result.task_types.append(task_type)

    # Boost planning detection if planning phrases found
    if result.planning_phrases_found and "planning" not in result.task_types:
        result.task_types.insert(0, "planning")

    # --- Subagent suitability ---
    subagent_signals: list[str] = []

    if result.enumerated_items >= 3:
        subagent_signals.append(f"enumerated_items={result.enumerated_items}")

    if result.unique_entities >= 3 and not result.has_sequential_markers:
        subagent_signals.append(f"multi_entity={result.unique_entities}")

    if result.has_parallel_markers:
        subagent_signals.append("parallel_language")

    if result.word_count > 100 and result.unique_entities >= 2:
        subagent_signals.append("broad_scope")

    # Research tasks with multiple angles
    if "research" in result.task_types and result.word_count > 50:
        subagent_signals.append("research_breadth")

    # Comma-separated verb phrases: "design X, document Y, and write Z"
    verb_phrases: list[str] = re.findall(
        r"\b(?:" + "|".join(
            v for verbs in VERB_CLASSES.values() for v in verbs
        ) + r")\s+\w+",
        text.lower(),
    )
    if len(verb_phrases) >= 3 and not result.has_sequential_markers:
        subagent_signals.append(f"multi_verb_phrase={len(verb_phrases)}")

    result.subagent_signals = subagent_signals
    result.subagent_suitable = (
        len(subagent_signals) >= 1 and not result.has_sequential_markers
    )

    # Overall confidence
    if result.task_types:
        max_score: float = max(result.verb_scores.values()) if result.verb_scores else 0
        entity_boost: float = min(result.unique_entities / 5, 1.0) * 0.2
        result.confidence = min(max_score / 5 + entity_boost + 0.3, 1.0)
    else:
        result.confidence = 0.1

    return result


# ---------------------------------------------------------------------------
# Ground truth annotations for validation
# ---------------------------------------------------------------------------

# Manually annotated prompts from conversation logs with expected task types
# and subagent suitability. These are real user prompts.
GROUND_TRUTH: list[dict[str, object]] = [
    {
        "prompt": "ok we need to make a bugfix branch and address all these problems immediately",
        "task_types": ["debugging", "planning"],
        "subagent_suitable": False,
    },
    {
        "prompt": "make a plan, make a todo list to stay on track, then execute",
        "task_types": ["planning"],
        "subagent_suitable": False,
    },
    {
        "prompt": "fix the FTS5 search, the edge creation, and the feedback loop all at once",
        "task_types": ["debugging"],
        "subagent_suitable": True,
    },
    {
        "prompt": "deploy this to cloudflare and push to github",
        "task_types": ["deployment"],
        "subagent_suitable": False,
    },
    {
        "prompt": "research how MemGPT handles memory persistence and compare with our approach",
        "task_types": ["research"],
        "subagent_suitable": False,
    },
    {
        "prompt": "yes",
        "task_types": [],
        "subagent_suitable": False,
    },
    {
        "prompt": "do 3 and 5",
        "task_types": [],
        "subagent_suitable": False,
    },
    {
        "prompt": (
            "investigate the vocabulary gap between user prompts and stored directives. "
            "also look at how HRR bridging performs on the dispatch runbook case. "
            "and check whether activation_condition has any evaluation logic wired up."
        ),
        "task_types": ["research"],
        "subagent_suitable": True,
    },
    {
        "prompt": (
            "1. update the README with install instructions\n"
            "2. fix the broken test in test_store.py\n"
            "3. add type annotations to hook_search.py\n"
            "4. run the full test suite"
        ),
        "task_types": ["implementation"],
        "subagent_suitable": True,
    },
    {
        "prompt": "run pytest and show me what's failing",
        "task_types": ["validation"],
        "subagent_suitable": False,
    },
    {
        "prompt": "create a new MCP tool that exposes the structural analyzer",
        "task_types": ["implementation"],
        "subagent_suitable": False,
    },
    {
        "prompt": (
            "there's a bug in the feedback loop -- pending_feedback entries aren't "
            "being processed. the auto-feedback fires but the confidence values "
            "aren't updating. trace through the code path from search_for_prompt "
            "through _process_pending_feedback and find where it breaks"
        ),
        "task_types": ["debugging"],
        "subagent_suitable": False,
    },
    {
        "prompt": "ship it, push to main",
        "task_types": ["deployment"],
        "subagent_suitable": False,
    },
    {
        "prompt": (
            "i need you to look at 3 things in parallel: "
            "1) the conversation logger output format "
            "2) the PostCompact hook ingestion pipeline "
            "3) the belief classification accuracy"
        ),
        "task_types": ["research"],
        "subagent_suitable": True,
    },
    {
        "prompt": (
            "review the changes on this branch, check for any security issues, "
            "make sure tests pass, then merge to main"
        ),
        "task_types": ["validation", "deployment"],
        "subagent_suitable": False,
    },
    {
        "prompt": "just push",
        "task_types": ["deployment"],
        "subagent_suitable": False,
    },
    {
        "prompt": (
            "design the activation_condition schema, document the evaluation rules, "
            "and write acceptance criteria for the feature"
        ),
        "task_types": ["planning", "implementation"],
        "subagent_suitable": True,
    },
    {
        "prompt": "whats the status",
        "task_types": [],
        "subagent_suitable": False,
    },
    {
        "prompt": (
            "ok tackle everything. make a plan, document it, then make a todo list "
            "to stay on track and execute"
        ),
        "task_types": ["planning"],
        "subagent_suitable": False,
    },
    {
        "prompt": (
            "explore how temporal edges could enable conversation replay. "
            "also wonder about whether belief age should affect retrieval ranking. "
            "and research what neuroscience says about episodic vs semantic memory decay"
        ),
        "task_types": ["research"],
        "subagent_suitable": True,
    },
    {
        "prompt": "build the structural prompt analyzer, test it against logs, write the results",
        "task_types": ["implementation", "validation"],
        "subagent_suitable": True,
    },
    {
        "prompt": "verify the dispatch gate is working after the last deploy",
        "task_types": ["validation"],
        "subagent_suitable": False,
    },
    {
        "prompt": "proceed",
        "task_types": [],
        "subagent_suitable": False,
    },
    {
        "prompt": (
            "refactor store.py to separate the migration logic into its own module. "
            "be careful not to break the API surface"
        ),
        "task_types": ["implementation"],
        "subagent_suitable": False,
    },
    {
        "prompt": (
            "i want to understand why the multi-hop accuracy is stuck at 60%. "
            "run the MAB benchmark again, analyze the failure cases, "
            "and propose 3 different approaches to improve hop-2 entity coverage"
        ),
        "task_types": ["research", "debugging"],
        "subagent_suitable": True,
    },
]


def evaluate_accuracy() -> dict[str, object]:
    """Run structural analyzer against ground truth and measure accuracy."""
    results: list[dict[str, object]] = []
    task_type_correct: int = 0
    task_type_total: int = 0
    subagent_correct: int = 0
    subagent_total: int = len(GROUND_TRUTH)

    # Per-type precision/recall
    type_tp: dict[str, int] = {}
    type_fp: dict[str, int] = {}
    type_fn: dict[str, int] = {}

    for gt in GROUND_TRUTH:
        prompt: str = str(gt["prompt"])
        expected_types: list[str] = list(gt["task_types"])  # type: ignore[arg-type]
        expected_subagent: bool = bool(gt["subagent_suitable"])

        analysis: StructuralAnalysis = analyze_prompt(prompt)

        # Task type evaluation: check if primary type matches
        predicted_types: list[str] = analysis.task_types
        if expected_types:
            task_type_total += 1
            # Credit if ANY expected type appears in predictions
            if any(t in predicted_types for t in expected_types):
                task_type_correct += 1

        # Per-type metrics
        expected_set: set[str] = set(expected_types)
        predicted_set: set[str] = set(predicted_types)

        for t in expected_set | predicted_set:
            if t not in type_tp:
                type_tp[t] = 0
                type_fp[t] = 0
                type_fn[t] = 0

            if t in expected_set and t in predicted_set:
                type_tp[t] += 1
            elif t in predicted_set and t not in expected_set:
                type_fp[t] += 1
            elif t in expected_set and t not in predicted_set:
                type_fn[t] += 1

        # Subagent evaluation
        if analysis.subagent_suitable == expected_subagent:
            subagent_correct += 1

        results.append({
            "prompt": prompt[:80] + ("..." if len(prompt) > 80 else ""),
            "expected_types": expected_types,
            "predicted_types": predicted_types,
            "type_match": any(t in predicted_types for t in expected_types) if expected_types else not predicted_types,
            "expected_subagent": expected_subagent,
            "predicted_subagent": analysis.subagent_suitable,
            "subagent_match": analysis.subagent_suitable == expected_subagent,
            "subagent_signals": analysis.subagent_signals,
            "confidence": round(analysis.confidence, 3),
            "enumerated_items": analysis.enumerated_items,
            "unique_entities": analysis.unique_entities,
        })

    # Compute per-type precision/recall/F1
    type_metrics: dict[str, dict[str, float]] = {}
    for t in sorted(type_tp.keys()):
        tp: int = type_tp[t]
        fp: int = type_fp[t]
        fn: int = type_fn[t]
        precision: float = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall: float = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1: float = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        type_metrics[t] = {
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "tp": tp, "fp": fp, "fn": fn,
        }

    task_type_accuracy: float = task_type_correct / task_type_total if task_type_total > 0 else 0.0
    subagent_accuracy: float = subagent_correct / subagent_total if subagent_total > 0 else 0.0

    # Subagent-specific precision/recall
    sa_tp: int = sum(1 for r in results if r["predicted_subagent"] and r["expected_subagent"])
    sa_fp: int = sum(1 for r in results if r["predicted_subagent"] and not r["expected_subagent"])
    sa_fn: int = sum(1 for r in results if not r["predicted_subagent"] and r["expected_subagent"])
    sa_precision: float = sa_tp / (sa_tp + sa_fp) if (sa_tp + sa_fp) > 0 else 0.0
    sa_recall: float = sa_tp / (sa_tp + sa_fn) if (sa_tp + sa_fn) > 0 else 0.0

    return {
        "task_type_accuracy": round(task_type_accuracy, 3),
        "task_type_correct": task_type_correct,
        "task_type_total": task_type_total,
        "subagent_accuracy": round(subagent_accuracy, 3),
        "subagent_precision": round(sa_precision, 3),
        "subagent_recall": round(sa_recall, 3),
        "subagent_correct": subagent_correct,
        "subagent_total": subagent_total,
        "per_type_metrics": type_metrics,
        "keyword_baseline_accuracy": 0.27,
        "individual_results": results,
    }


def run_on_conversation_logs() -> dict[str, object]:
    """Run structural analyzer on real conversation logs for distribution analysis."""
    log_dir: Path = Path.home() / ".claude" / "conversation-logs"
    all_prompts: list[str] = []

    # Current session
    current: Path = log_dir / "turns.jsonl"
    if current.exists():
        for line in current.read_text().splitlines():
            if not line.strip():
                continue
            try:
                entry: dict[str, object] = json.loads(line)
                if entry.get("event") == "user":
                    content: object = entry.get("text", "")
                    if isinstance(content, str) and len(content) > 10:
                        # Strip system XML
                        clean: str = re.sub(r"<system-reminder>.*?</system-reminder>", "", content, flags=re.DOTALL)
                        clean = re.sub(r"<task-notification>.*?</task-notification>", "", clean, flags=re.DOTALL)
                        clean = clean.strip()
                        if len(clean) > 10:
                            all_prompts.append(clean)
            except json.JSONDecodeError:
                continue

    # Archive files
    archive_dir: Path = log_dir / "archive"
    if archive_dir.exists():
        for f in sorted(archive_dir.iterdir()):
            if f.suffix == ".jsonl":
                for line in f.read_text().splitlines():
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("event") == "user":
                            content = entry.get("text", "")
                            if isinstance(content, str) and len(content) > 10:
                                clean = re.sub(r"<system-reminder>.*?</system-reminder>", "", content, flags=re.DOTALL)
                                clean = re.sub(r"<task-notification>.*?</task-notification>", "", clean, flags=re.DOTALL)
                                clean = clean.strip()
                                if len(clean) > 10:
                                    all_prompts.append(clean)
                    except json.JSONDecodeError:
                        continue

    # Analyze distribution
    type_counts: dict[str, int] = {}
    subagent_count: int = 0
    no_type_count: int = 0
    total: int = len(all_prompts)

    for prompt in all_prompts:
        analysis: StructuralAnalysis = analyze_prompt(prompt)
        if analysis.task_types:
            for t in analysis.task_types:
                type_counts[t] = type_counts.get(t, 0) + 1
        else:
            no_type_count += 1

        if analysis.subagent_suitable:
            subagent_count += 1

    return {
        "total_prompts": total,
        "type_distribution": dict(sorted(type_counts.items(), key=lambda x: x[1], reverse=True)),
        "no_type_detected": no_type_count,
        "no_type_pct": round(no_type_count / max(total, 1) * 100, 1),
        "subagent_suitable_count": subagent_count,
        "subagent_suitable_pct": round(subagent_count / max(total, 1) * 100, 1),
    }


def main() -> None:
    """Run all analyses and output results."""
    print("=" * 70)
    print("EXP86: STRUCTURAL PROMPT ANALYSIS")
    print("=" * 70)

    # Part 1: Ground truth validation
    print("\n## Part 1: Ground Truth Validation (25 annotated prompts)")
    print("-" * 50)
    gt_results: dict[str, object] = evaluate_accuracy()

    print(f"\nTask Type Accuracy:  {gt_results['task_type_accuracy']}")
    print(f"  (correct: {gt_results['task_type_correct']}/{gt_results['task_type_total']})")
    print(f"  (keyword baseline: {gt_results['keyword_baseline_accuracy']})")
    print(f"  (improvement: {float(gt_results['task_type_accuracy']) / 0.27:.1f}x)")

    print(f"\nSubagent Detection Accuracy: {gt_results['subagent_accuracy']}")
    print(f"  Precision: {gt_results['subagent_precision']}")
    print(f"  Recall:    {gt_results['subagent_recall']}")
    print(f"  (correct: {gt_results['subagent_correct']}/{gt_results['subagent_total']})")

    print("\nPer-Type Metrics:")
    per_type: dict[str, dict[str, float]] = gt_results["per_type_metrics"]  # type: ignore[assignment]
    for t, m in per_type.items():
        print(f"  {t:15s}  P={m['precision']:.3f}  R={m['recall']:.3f}  F1={m['f1']:.3f}  (TP={m['tp']} FP={m['fp']} FN={m['fn']})")

    # Show mismatches
    print("\nMismatches:")
    individual: list[dict[str, object]] = gt_results["individual_results"]  # type: ignore[assignment]
    for r in individual:
        if not r["type_match"] or not r["subagent_match"]:
            flags: list[str] = []
            if not r["type_match"]:
                flags.append(f"TYPE: expected={r['expected_types']} got={r['predicted_types']}")
            if not r["subagent_match"]:
                flags.append(f"SUBAGENT: expected={r['expected_subagent']} got={r['predicted_subagent']} signals={r['subagent_signals']}")
            print(f"  [{r['prompt']}]")
            for f in flags:
                print(f"    -> {f}")

    # Part 2: Conversation log distribution
    print("\n\n## Part 2: Conversation Log Distribution Analysis")
    print("-" * 50)
    log_results: dict[str, object] = run_on_conversation_logs()

    print(f"\nTotal prompts analyzed: {log_results['total_prompts']}")
    print(f"No type detected: {log_results['no_type_detected']} ({log_results['no_type_pct']}%)")
    print(f"Subagent suitable: {log_results['subagent_suitable_count']} ({log_results['subagent_suitable_pct']}%)")
    print("\nType distribution:")
    dist: dict[str, int] = log_results["type_distribution"]  # type: ignore[assignment]
    for t, count in dist.items():
        pct: float = count / int(log_results["total_prompts"]) * 100
        print(f"  {t:15s}  {count:4d}  ({pct:.1f}%)")

    # Save results
    output: dict[str, object] = {
        "experiment": "exp86_structural_prompt_analysis",
        "ground_truth_validation": gt_results,
        "conversation_log_distribution": log_results,
    }

    results_path: Path = Path(__file__).parent / "exp86_results.json"
    results_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nResults saved to {results_path}")


if __name__ == "__main__":
    main()
