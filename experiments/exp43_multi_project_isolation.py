"""
Experiment 43: Multi-Project Belief Isolation -- Classification Validation

Research question: How well do keyword heuristics from Exp 21 classify beliefs
as behavioral (cross-project) vs domain (project-scoped)? What's the ambiguity
rate and false-positive rate for behavioral classification?

Method:
  1. Load the 552 decision+knowledge items from the project-a timeline (Exp 6).
  2. Apply keyword heuristics from Exp 21:
     - Behavioral signals: "always", "never", "don't ever", "stop doing",
       "every time", "from now on", universal process rules.
     - Domain signals: file paths, tickers, dollar amounts, milestone IDs,
       DTE/strike/expiry, project-specific tool names.
  3. Classify each belief as: behavioral, domain, or ambiguous.
  4. Measure: fraction unambiguous, fraction requiring LLM judgment, false
     positive rate for behavioral (domain beliefs misclassified as behavioral).

Ground truth: Manual annotations on a stratified sample, coded directly in
this script as a validation set.

All code uses strict static typing. Run with: uv run python experiments/exp43_multi_project_isolation.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# ============================================================
# Types
# ============================================================

ScopeLabel = Literal["behavioral", "domain", "ambiguous"]


@dataclass
class ClassifiedBelief:
    """A belief with its classification and the signals that triggered it."""

    content: str
    event_type: str
    context: str
    label: ScopeLabel
    behavioral_signals: list[str] = field(default_factory=lambda: list[str]())
    domain_signals: list[str] = field(default_factory=lambda: list[str]())


# ============================================================
# Keyword heuristics (from Exp 21 Section 4)
# ============================================================

# Behavioral keyword patterns -- suggest cross-project applicability
BEHAVIORAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("always_directive", re.compile(r"\balways\b", re.IGNORECASE)),
    ("never_directive", re.compile(r"\bnever\b", re.IGNORECASE)),
    ("dont_ever", re.compile(r"\bdon'?t\s+ever\b", re.IGNORECASE)),
    ("stop_doing", re.compile(r"\bstop\s+(doing|using|bringing)\b", re.IGNORECASE)),
    ("every_time", re.compile(r"\bevery\s+time\b", re.IGNORECASE)),
    ("from_now_on", re.compile(r"\bfrom\s+now\s+on\b", re.IGNORECASE)),
    ("do_not_ever", re.compile(r"\bdo\s+not\s+ever\b", re.IGNORECASE)),
    (
        "all_projects",
        re.compile(r"\ball\s+(projects|future|milestones)\b", re.IGNORECASE),
    ),
    ("strict_typing", re.compile(r"\bstrict\s+(static\s+)?typing\b", re.IGNORECASE)),
    ("async_bash_ban", re.compile(r"\basync_bash\b", re.IGNORECASE)),
    ("dont_pontificate", re.compile(r"\bpontificate\b", re.IGNORECASE)),
    ("dont_elaborate", re.compile(r"\bdon'?t\s+elaborate\b", re.IGNORECASE)),
    ("pyright_strict", re.compile(r"\bpyright\s+strict\b", re.IGNORECASE)),
    ("use_uv", re.compile(r"\buv\b.*\bpackage\b|\buse\s+uv\b", re.IGNORECASE)),
    (
        "citation_required",
        re.compile(r"\bcit(ation|e)\b.*\b(source|evidence|back)\b", re.IGNORECASE),
    ),
]

# Domain keyword patterns -- suggest project-specific scope
DOMAIN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("file_path", re.compile(r"[a-zA-Z_/]+\.(py|yaml|json|toml|md|sql|csv)\b")),
    ("ticker_symbol", re.compile(r"\b[A-Z]{2,5}\b(?=\s|,|$|\))")),
    ("dollar_amount", re.compile(r"\$\d+[kK]?\b")),
    ("milestone_id", re.compile(r"\bM\d{3}\b")),
    ("decision_id", re.compile(r"\bD\d{3}\b")),
    ("dte_reference", re.compile(r"\b\d+[dD](?:/|\b)")),
    ("strike_pct", re.compile(r"\b\d+%\b")),
    (
        "options_term",
        re.compile(
            r"\b(put|call|strike|expiry|premium|convexity|ITM|OTM|ATM|DTE|delta)\b",
            re.IGNORECASE,
        ),
    ),
    ("backtest", re.compile(r"\bbacktest\b", re.IGNORECASE)),
    ("signal_config", re.compile(r"\bsignal_\w+\.yaml\b")),
    ("gcp_infra", re.compile(r"\b(GCP|server-a|VM|dispatch gate)\b", re.IGNORECASE)),
    (
        "model_specific",
        re.compile(r"\b(LightGBM|XGBoost|LGBM|GBM|random\s+forest)\b", re.IGNORECASE),
    ),
    ("capital_specific", re.compile(r"\b(bankroll|capital|5k|5K)\b")),
    (
        "trading_verb",
        re.compile(
            r"\b(sell|buy|hold|exit|entry|position|contract|hedge)\b", re.IGNORECASE
        ),
    ),
    (
        "project_name",
        re.compile(
            r"\b(project-a|project-d|project-b|project-e|project-j)\b",
            re.IGNORECASE,
        ),
    ),
]

# Semi-cross-cutting: behavioral but with scope limiter
SEMI_CROSSCUT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("python_scoped", re.compile(r"\bpython\b", re.IGNORECASE)),
    ("typescript_scoped", re.compile(r"\btypescript\b", re.IGNORECASE)),
    ("django_scoped", re.compile(r"\bdjango\b", re.IGNORECASE)),
    ("react_scoped", re.compile(r"\breact\b", re.IGNORECASE)),
]


# ============================================================
# Classification logic
# ============================================================


def classify_belief(content: str, event_type: str, context: str) -> ClassifiedBelief:
    """Classify a belief as behavioral, domain, or ambiguous using keyword heuristics."""
    behavioral_hits: list[str] = []
    domain_hits: list[str] = []

    for name, pattern in BEHAVIORAL_PATTERNS:
        if pattern.search(content):
            behavioral_hits.append(name)

    for name, pattern in DOMAIN_PATTERNS:
        if pattern.search(content):
            domain_hits.append(name)

    # Classification rules:
    # 1. If behavioral signals present AND no domain signals -> behavioral
    # 2. If domain signals present AND no behavioral signals -> domain
    # 3. If both present -> ambiguous (needs judgment)
    # 4. If neither present -> domain (conservative default per Exp 21 principle:
    #    misclassifying domain as behavioral is worse than the reverse)

    label: ScopeLabel
    if behavioral_hits and not domain_hits:
        label = "behavioral"
    elif domain_hits and not behavioral_hits:
        label = "domain"
    elif behavioral_hits and domain_hits:
        label = "ambiguous"
    else:
        # No signals either way -- default to domain (conservative)
        label = "domain"

    return ClassifiedBelief(
        content=content,
        event_type=event_type,
        context=context,
        label=label,
        behavioral_signals=behavioral_hits,
        domain_signals=domain_hits,
    )


# ============================================================
# Ground truth: manual annotations for validation
# ============================================================
# Format: (content_substring, true_label)
# These are hand-labeled from reading the actual content.

GROUND_TRUTH: list[tuple[str, ScopeLabel]] = [
    # Clearly behavioral -- should be cross-project
    ("do not use async_bash ever again", "behavioral"),
    ("dont pontificate, just do exactly what I told you", "behavioral"),
    ("use strict static typing", "behavioral"),
    ("convert all code to typed python", "behavioral"),
    ("every statement needs to be backed up with evidence", "behavioral"),
    ("pyright strict: annotate", "domain"),  # pyright TIP, not a directive
    ("pyright strict: type: ignore", "domain"),  # pyright TIP, not a directive
    ("pyright strict: venvPath", "domain"),  # pyright TIP, not a directive
    ("pyright strict: functools.partial", "domain"),  # pyright TIP, not a directive
    (
        "pyright strict: empty list initializer",
        "domain",
    ),  # pyright TIP, not a directive
    # Clearly domain -- project-a specific
    ("capital needs to be 5k, not 100k", "domain"),
    ("5k is the hard cap, do not ask about it again", "domain"),
    ("calls and puts both need to be in the strategy", "domain"),
    ("Minimum per-trade return target", "domain"),
    ("Hold to expiry is baseline exit", "domain"),
    ("32-ticker ex-GE universe", "domain"),
    ("GBM drift calibration target", "domain"),
    ("server-a for overflow, GCP is primary compute", "domain"),
    ("always satisfy the deploy gate", "domain"),  # "always" but project-specific
    # Ambiguous -- behavioral signal + domain context
    ("always satisfy the deploy gate", "domain"),
    ("all future milestones", "behavioral"),  # scope marker, not domain-specific
    ("please report returns in annualized terms", "behavioral"),  # reporting style
    ("do not implement artificial contract filters", "domain"),
    # Knowledge items that look behavioral but are domain
    ("Backtest runner writes output atomically at end", "domain"),
    ("StrEnum for bounded string parameters", "domain"),
]


def find_match(content: str, ground_truth_key: str) -> bool:
    """Check if ground truth key matches the belief content."""
    return ground_truth_key.lower() in content.lower()


# ============================================================
# Leak scenario simulation
# ============================================================


@dataclass
class LeakSimResult:
    """Results of a cross-project leak simulation."""

    total_beliefs: int
    project_a_domain: int
    project_a_behavioral: int
    project_a_ambiguous: int
    leaked_under_pre_filter: int
    leaked_under_post_filter: int
    leaked_under_penalty: int
    leaked_behavioral_correct: int
    leaked_behavioral_false_positive: int


def simulate_f4_leak(
    beliefs: list[ClassifiedBelief],
    ground_truth: list[tuple[str, ScopeLabel]],
) -> LeakSimResult:
    """Simulate F4 leak scenario: user switches from project-a to web-app project.

    Under each filtering option, count how many project-a beliefs would leak
    into the web-app context sent to a cloud LLM.

    Options:
      A. Pre-filter: WHERE project_id = 'webapp' OR scope = 'global'
         Only behavioral beliefs leak. Domain beliefs blocked at query time.
      B. Post-filter: Retrieve all, then filter after ranking.
         Everything retrieved initially; filter removes domain after ranking.
         Risk: if filter is buggy or slow, domain beliefs appear in context.
      C. Penalty: Thompson sampling score * 0.1 for cross-project domain beliefs.
         Beliefs still retrievable but heavily penalized. Risk: high-confidence
         domain beliefs can overcome the penalty.
    """
    domain_count: int = 0
    behavioral_count: int = 0
    ambiguous_count: int = 0

    # Count FP: beliefs classified as behavioral that are actually domain
    fp_behavioral: int = 0
    tp_behavioral: int = 0

    for belief in beliefs:
        if belief.label == "domain":
            domain_count += 1
        elif belief.label == "behavioral":
            behavioral_count += 1
        else:
            ambiguous_count += 1

    # Check ground truth for FP rate
    for gt_key, gt_label in ground_truth:
        for belief in beliefs:
            if find_match(belief.content, gt_key):
                if belief.label == "behavioral" and gt_label == "domain":
                    fp_behavioral += 1
                elif belief.label == "behavioral" and gt_label == "behavioral":
                    tp_behavioral += 1
                break  # first match only

    # Option A: Pre-filter -- only behavioral + ambiguous could leak
    leaked_pre_filter: int = (
        behavioral_count  # ambiguous defaults to domain in pre-filter
    )

    # Option B: Post-filter -- same as pre-filter if filter works correctly
    # But if filter has a bug, ALL beliefs leak. Model as: behavioral + 5% of domain
    # (representing filter implementation risk)
    leaked_post_filter: int = behavioral_count + int(domain_count * 0.05)

    # Option C: Penalty -- behavioral leaks, plus high-confidence domain beliefs
    # that overcome the 0.1x penalty. Model: behavioral + 2% of domain
    leaked_penalty: int = behavioral_count + int(domain_count * 0.02)

    return LeakSimResult(
        total_beliefs=len(beliefs),
        project_a_domain=domain_count,
        project_a_behavioral=behavioral_count,
        project_a_ambiguous=ambiguous_count,
        leaked_under_pre_filter=leaked_pre_filter,
        leaked_under_post_filter=leaked_post_filter,
        leaked_under_penalty=leaked_penalty,
        leaked_behavioral_correct=tp_behavioral,
        leaked_behavioral_false_positive=fp_behavioral,
    )


# ============================================================
# Scope taxonomy analysis
# ============================================================


@dataclass
class ScopeTaxonomyResult:
    """Analysis of scope levels needed for semi-cross-cutting beliefs."""

    global_count: int
    language_scoped_count: int
    framework_scoped_count: int
    project_scoped_count: int
    examples: dict[str, list[str]]


def analyze_scope_taxonomy(beliefs: list[ClassifiedBelief]) -> ScopeTaxonomyResult:
    """Analyze how many scope levels are needed beyond binary behavioral/domain."""
    global_beliefs: list[str] = []
    language_scoped: list[str] = []
    framework_scoped: list[str] = []
    project_scoped: list[str] = []

    for belief in beliefs:
        if belief.label == "domain":
            project_scoped.append(belief.content[:80])
            continue

        # For behavioral and ambiguous, check if they have scope limiters
        has_language_scope: bool = False
        has_framework_scope: bool = False

        for name, pattern in SEMI_CROSSCUT_PATTERNS:
            if pattern.search(belief.content):
                if name.endswith("_scoped") and name.startswith(
                    ("python", "typescript")
                ):
                    has_language_scope = True
                elif name.endswith("_scoped"):
                    has_framework_scope = True

        if has_framework_scope:
            framework_scoped.append(belief.content[:80])
        elif has_language_scope:
            language_scoped.append(belief.content[:80])
        else:
            global_beliefs.append(belief.content[:80])

    return ScopeTaxonomyResult(
        global_count=len(global_beliefs),
        language_scoped_count=len(language_scoped),
        framework_scoped_count=len(framework_scoped),
        project_scoped_count=len(project_scoped),
        examples={
            "global": global_beliefs[:5],
            "language_scoped": language_scoped[:5],
            "framework_scoped": framework_scoped[:5],
            "project_scoped": project_scoped[:5],
        },
    )


# ============================================================
# Main
# ============================================================


def main() -> None:
    # Load timeline
    timeline_path: Path = Path("experiments/exp6_timeline.json")
    if not timeline_path.exists():
        print(f"ERROR: {timeline_path} not found. Run from project root.")
        sys.exit(1)

    with open(timeline_path) as f:
        data: dict[str, list[dict[str, str]]] = json.load(f)

    events: list[dict[str, str]] = data.get("events", [])
    beliefs_raw: list[dict[str, str]] = [
        e for e in events if e.get("event_type") in ("decision", "knowledge")
    ]

    print(f"Loaded {len(beliefs_raw)} belief-like items from timeline")
    print(
        f"  Decisions: {sum(1 for b in beliefs_raw if b['event_type'] == 'decision')}"
    )
    print(
        f"  Knowledge: {sum(1 for b in beliefs_raw if b['event_type'] == 'knowledge')}"
    )
    print()

    # ---- Phase 1: Classify all beliefs ----
    classified: list[ClassifiedBelief] = []
    for item in beliefs_raw:
        result: ClassifiedBelief = classify_belief(
            content=item["content"],
            event_type=item["event_type"],
            context=item.get("context", ""),
        )
        classified.append(result)

    label_counts: Counter[str] = Counter(b.label for b in classified)
    total: int = len(classified)

    print("=" * 60)
    print("CLASSIFICATION RESULTS")
    print("=" * 60)
    print(
        f"  Behavioral (cross-project): {label_counts['behavioral']:>4} "
        f"({label_counts['behavioral'] / total * 100:.1f}%)"
    )
    print(
        f"  Domain (project-scoped):    {label_counts['domain']:>4} "
        f"({label_counts['domain'] / total * 100:.1f}%)"
    )
    print(
        f"  Ambiguous (needs judgment):  {label_counts['ambiguous']:>4} "
        f"({label_counts['ambiguous'] / total * 100:.1f}%)"
    )
    print(f"  Total:                       {total:>4}")
    print()

    # Unambiguous fraction
    unambiguous: int = label_counts["behavioral"] + label_counts["domain"]
    print(f"  Unambiguous rate: {unambiguous / total * 100:.1f}%")
    print(f"  LLM judgment needed: {label_counts['ambiguous'] / total * 100:.1f}%")
    print()

    # ---- Phase 2: Validate against ground truth ----
    print("=" * 60)
    print("GROUND TRUTH VALIDATION")
    print("=" * 60)

    correct: int = 0
    incorrect: int = 0
    not_found: int = 0
    fp_behavioral: int = 0
    fn_behavioral: int = 0

    for gt_key, gt_label in GROUND_TRUTH:
        matched: bool = False
        for belief in classified:
            if find_match(belief.content, gt_key):
                matched = True
                if belief.label == gt_label:
                    correct += 1
                elif belief.label == "ambiguous":
                    # Ambiguous is not wrong per se, but not correct either
                    incorrect += 1
                    status: str = "AMBIGUOUS"
                    print(
                        f"  {status}: '{gt_key[:60]}' -> {belief.label} (expected {gt_label})"
                    )
                    print(f"    B-signals: {belief.behavioral_signals}")
                    print(f"    D-signals: {belief.domain_signals}")
                else:
                    incorrect += 1
                    status = "WRONG"
                    print(
                        f"  {status}: '{gt_key[:60]}' -> {belief.label} (expected {gt_label})"
                    )
                    print(f"    B-signals: {belief.behavioral_signals}")
                    print(f"    D-signals: {belief.domain_signals}")
                    if belief.label == "behavioral" and gt_label == "domain":
                        fp_behavioral += 1
                    elif belief.label == "domain" and gt_label == "behavioral":
                        fn_behavioral += 1
                break
        if not matched:
            not_found += 1

    evaluated: int = correct + incorrect
    print()
    print(
        f"  Evaluated:     {evaluated}/{len(GROUND_TRUTH)} "
        f"({not_found} not found in corpus)"
    )
    if evaluated > 0:
        print(
            f"  Correct:       {correct}/{evaluated} ({correct / evaluated * 100:.1f}%)"
        )
        print(
            f"  Incorrect:     {incorrect}/{evaluated} ({incorrect / evaluated * 100:.1f}%)"
        )
        print(f"  FP behavioral: {fp_behavioral} (domain misclassified as behavioral)")
        print(f"  FN behavioral: {fn_behavioral} (behavioral misclassified as domain)")
    print()

    # ---- Phase 3: Signal frequency analysis ----
    print("=" * 60)
    print("SIGNAL FREQUENCY ANALYSIS")
    print("=" * 60)

    b_signal_freq: Counter[str] = Counter()
    d_signal_freq: Counter[str] = Counter()

    for belief in classified:
        for sig in belief.behavioral_signals:
            b_signal_freq[sig] += 1
        for sig in belief.domain_signals:
            d_signal_freq[sig] += 1

    print("\n  Top behavioral signals:")
    for sig, count in b_signal_freq.most_common(10):
        print(f"    {sig}: {count}")

    print("\n  Top domain signals:")
    for sig, count in d_signal_freq.most_common(10):
        print(f"    {sig}: {count}")

    # ---- Phase 4: Behavioral beliefs detail ----
    print()
    print("=" * 60)
    print("BEHAVIORAL BELIEFS (cross-project candidates)")
    print("=" * 60)
    behavioral_beliefs: list[ClassifiedBelief] = [
        b for b in classified if b.label == "behavioral"
    ]
    for b in behavioral_beliefs:
        print(f"  [{b.event_type}] {b.content[:100]}")
        print(f"    signals: {b.behavioral_signals}")

    # ---- Phase 5: Ambiguous beliefs detail ----
    print()
    print("=" * 60)
    print("AMBIGUOUS BELIEFS (need LLM or user judgment)")
    print("=" * 60)
    ambiguous_beliefs: list[ClassifiedBelief] = [
        b for b in classified if b.label == "ambiguous"
    ]
    for b in ambiguous_beliefs[:20]:  # Cap at 20 for readability
        print(f"  [{b.event_type}] {b.content[:100]}")
        print(f"    B: {b.behavioral_signals}  D: {b.domain_signals}")

    if len(ambiguous_beliefs) > 20:
        print(f"  ... and {len(ambiguous_beliefs) - 20} more")

    # ---- Phase 6: F4 Leak simulation ----
    print()
    print("=" * 60)
    print("F4 LEAK SCENARIO SIMULATION")
    print("=" * 60)
    leak: LeakSimResult = simulate_f4_leak(classified, GROUND_TRUTH)
    print(f"  Total project-a beliefs: {leak.total_beliefs}")
    print(f"  Domain (should NOT leak): {leak.project_a_domain}")
    print(f"  Behavioral (OK to leak):  {leak.project_a_behavioral}")
    print(f"  Ambiguous:                {leak.project_a_ambiguous}")
    print()
    print("  Leak risk by filtering option:")
    print(
        f"    A. Pre-filter (WHERE clause):  {leak.leaked_under_pre_filter} beliefs "
        f"({leak.leaked_under_pre_filter / leak.total_beliefs * 100:.1f}%)"
    )
    print(
        f"    B. Post-filter (rank then cut): {leak.leaked_under_post_filter} beliefs "
        f"({leak.leaked_under_post_filter / leak.total_beliefs * 100:.1f}%)"
    )
    print(
        f"    C. Penalty (0.1x score):       {leak.leaked_under_penalty} beliefs "
        f"({leak.leaked_under_penalty / leak.total_beliefs * 100:.1f}%)"
    )
    print()
    print(
        f"  FP in behavioral (domain that would leak incorrectly): "
        f"{leak.leaked_behavioral_false_positive}"
    )
    print(
        f"  TP in behavioral (correctly cross-project): "
        f"{leak.leaked_behavioral_correct}"
    )

    # ---- Phase 7: Scope taxonomy ----
    print()
    print("=" * 60)
    print("SCOPE TAXONOMY ANALYSIS")
    print("=" * 60)
    taxonomy: ScopeTaxonomyResult = analyze_scope_taxonomy(classified)
    print(f"  Global (universal):        {taxonomy.global_count}")
    print(f"  Language-scoped:           {taxonomy.language_scoped_count}")
    print(f"  Framework-scoped:          {taxonomy.framework_scoped_count}")
    print(f"  Project-scoped:            {taxonomy.project_scoped_count}")
    print()
    for scope, examples in taxonomy.examples.items():
        if examples:
            print(f"  {scope} examples:")
            for ex in examples[:3]:
                print(f"    - {ex}")

    # ---- Write results ----
    results: dict[str, object] = {
        "classification": {
            "total": total,
            "behavioral": label_counts["behavioral"],
            "domain": label_counts["domain"],
            "ambiguous": label_counts["ambiguous"],
            "unambiguous_rate": round(unambiguous / total, 4),
            "llm_judgment_rate": round(label_counts["ambiguous"] / total, 4),
        },
        "validation": {
            "evaluated": evaluated,
            "correct": correct,
            "incorrect": incorrect,
            "accuracy": round(correct / evaluated, 4) if evaluated > 0 else 0,
            "fp_behavioral": fp_behavioral,
            "fn_behavioral": fn_behavioral,
        },
        "leak_simulation": {
            "total": leak.total_beliefs,
            "domain": leak.project_a_domain,
            "behavioral": leak.project_a_behavioral,
            "ambiguous": leak.project_a_ambiguous,
            "leak_pre_filter": leak.leaked_under_pre_filter,
            "leak_post_filter": leak.leaked_under_post_filter,
            "leak_penalty": leak.leaked_under_penalty,
            "fp_behavioral": leak.leaked_behavioral_false_positive,
        },
        "scope_taxonomy": {
            "global": taxonomy.global_count,
            "language_scoped": taxonomy.language_scoped_count,
            "framework_scoped": taxonomy.framework_scoped_count,
            "project_scoped": taxonomy.project_scoped_count,
        },
    }

    results_path: Path = Path("experiments/exp43_results.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to {results_path}")


if __name__ == "__main__":
    main()
