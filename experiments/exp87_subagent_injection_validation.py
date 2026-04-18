"""Exp87: Subagent injection validation.

Tests whether structural prompt analysis can reliably detect when subagents
would be beneficial by analyzing conversation logs for prompts where subagents
were actually used (ground truth from assistant responses).

Approach:
1. Parse conversation logs for user/assistant turn pairs
2. Detect assistant turns that used Agent/Task/subagent patterns
3. Check whether the preceding user prompt was flagged as subagent-suitable
4. Compute precision/recall of the subagent-suitability detector

Usage:
    uv run python experiments/exp87_subagent_injection_validation.py
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Import the structural analyzer from exp86
sys.path.insert(0, str(Path(__file__).parent))
from exp86_structural_prompt_analysis import StructuralAnalysis, analyze_prompt


# Patterns that indicate the assistant used subagents
SUBAGENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bAgent\s*\(", re.IGNORECASE),
    re.compile(r"\bsubagent", re.IGNORECASE),
    re.compile(r"\bExplore\s*\(", re.IGNORECASE),
    re.compile(r"\bspawn.*agent", re.IGNORECASE),
    re.compile(r"launch.*agent.*parallel", re.IGNORECASE),
    re.compile(r"Agent tool.*to", re.IGNORECASE),
    re.compile(r"I'll spawn", re.IGNORECASE),
    re.compile(r"Let me spawn", re.IGNORECASE),
    re.compile(r"multiple agents", re.IGNORECASE),
    re.compile(r"parallel.*research", re.IGNORECASE),
]


@dataclass
class TurnPair:
    """A user prompt followed by an assistant response."""

    user_prompt: str
    assistant_response: str
    session_id: str
    timestamp: str
    assistant_used_subagents: bool
    structural_says_suitable: bool
    subagent_signals: list[str]


def detect_subagent_usage(response: str) -> bool:
    """Check if assistant response shows subagent usage."""
    for pattern in SUBAGENT_PATTERNS:
        if pattern.search(response):
            return True
    return False


def load_turn_pairs() -> list[TurnPair]:
    """Load user/assistant turn pairs from conversation logs."""
    log_dir: Path = Path.home() / ".claude" / "conversation-logs"
    entries: list[dict[str, object]] = []

    # Load all JSONL files
    for jsonl_path in [log_dir / "turns.jsonl"] + sorted(
        (log_dir / "archive").glob("*.jsonl") if (log_dir / "archive").exists() else []
    ):
        if not jsonl_path.exists():
            continue
        for line in jsonl_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                entry: dict[str, object] = json.loads(line)
                entries.append(entry)
            except json.JSONDecodeError:
                continue

    # Sort by timestamp
    entries.sort(key=lambda e: str(e.get("timestamp", "")))

    # Pair user prompts with following assistant responses
    pairs: list[TurnPair] = []
    prev_user: dict[str, object] | None = None

    for entry in entries:
        event: str = str(entry.get("event", ""))
        text: str = str(entry.get("text", ""))
        session_id: str = str(entry.get("session_id", ""))

        if event == "user" and len(text) > 10:
            # Clean system XML
            clean: str = re.sub(
                r"<system-reminder>.*?</system-reminder>", "", text, flags=re.DOTALL,
            )
            clean = re.sub(
                r"<task-notification>.*?</task-notification>", "", clean, flags=re.DOTALL,
            )
            clean = clean.strip()
            if len(clean) > 10:
                prev_user = {
                    "text": clean,
                    "session_id": session_id,
                    "timestamp": str(entry.get("timestamp", "")),
                }

        elif event == "assistant" and prev_user is not None:
            # Only pair if same session
            if session_id == prev_user["session_id"]:
                used_subagents: bool = detect_subagent_usage(text)
                analysis: StructuralAnalysis = analyze_prompt(str(prev_user["text"]))

                pairs.append(TurnPair(
                    user_prompt=str(prev_user["text"]),
                    assistant_response=text[:500],
                    session_id=session_id,
                    timestamp=str(prev_user["timestamp"]),
                    assistant_used_subagents=used_subagents,
                    structural_says_suitable=analysis.subagent_suitable,
                    subagent_signals=analysis.subagent_signals,
                ))
            prev_user = None

    return pairs


def main() -> None:
    """Run subagent injection validation."""
    print("=" * 70)
    print("EXP87: SUBAGENT INJECTION VALIDATION")
    print("=" * 70)

    pairs: list[TurnPair] = load_turn_pairs()
    print(f"\nTotal turn pairs analyzed: {len(pairs)}")

    # Count actual subagent usage
    actual_subagent: list[TurnPair] = [p for p in pairs if p.assistant_used_subagents]
    predicted_subagent: list[TurnPair] = [p for p in pairs if p.structural_says_suitable]

    print(f"Turns where assistant used subagents: {len(actual_subagent)}")
    print(f"Turns where structural analysis says suitable: {len(predicted_subagent)}")

    # Confusion matrix
    tp: int = sum(1 for p in pairs if p.assistant_used_subagents and p.structural_says_suitable)
    fp: int = sum(1 for p in pairs if not p.assistant_used_subagents and p.structural_says_suitable)
    fn: int = sum(1 for p in pairs if p.assistant_used_subagents and not p.structural_says_suitable)
    tn: int = sum(1 for p in pairs if not p.assistant_used_subagents and not p.structural_says_suitable)

    precision: float = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall: float = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1: float = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy: float = (tp + tn) / len(pairs) if pairs else 0.0

    print(f"\n## Confusion Matrix")
    print(f"  TP (both agree suitable): {tp}")
    print(f"  FP (predicted but not used): {fp}")
    print(f"  FN (used but not predicted): {fn}")
    print(f"  TN (both agree not suitable): {tn}")

    print(f"\n## Metrics")
    print(f"  Accuracy:  {accuracy:.3f}")
    print(f"  Precision: {precision:.3f}")
    print(f"  Recall:    {recall:.3f}")
    print(f"  F1:        {f1:.3f}")

    # Show true positives (correctly identified)
    if tp > 0:
        print(f"\n## True Positives (correctly predicted subagent usage, showing up to 5):")
        shown: int = 0
        for p in pairs:
            if p.assistant_used_subagents and p.structural_says_suitable and shown < 5:
                print(f"\n  Prompt: {p.user_prompt[:120]}...")
                print(f"  Signals: {p.subagent_signals}")
                shown += 1

    # Show false negatives (missed predictions)
    if fn > 0:
        print(f"\n## False Negatives (subagents used but not predicted, showing up to 5):")
        shown = 0
        for p in pairs:
            if p.assistant_used_subagents and not p.structural_says_suitable and shown < 5:
                print(f"\n  Prompt: {p.user_prompt[:120]}...")
                print(f"  Signals: {p.subagent_signals}")
                analysis: StructuralAnalysis = analyze_prompt(p.user_prompt)
                print(f"  Task types: {analysis.task_types}")
                print(f"  Word count: {analysis.word_count}, Entities: {analysis.unique_entities}")
                shown += 1

    # Show false positives (incorrectly predicted)
    if fp > 0:
        print(f"\n## False Positives (predicted but not used, showing up to 5):")
        shown = 0
        for p in pairs:
            if not p.assistant_used_subagents and p.structural_says_suitable and shown < 5:
                print(f"\n  Prompt: {p.user_prompt[:120]}...")
                print(f"  Signals: {p.subagent_signals}")
                shown += 1

    # Subagent signal distribution across all turn pairs
    print(f"\n## Signal Distribution (across all {len(predicted_subagent)} predicted-suitable prompts):")
    signal_counts: dict[str, int] = {}
    for p in predicted_subagent:
        for s in p.subagent_signals:
            # Normalize signal name (remove =N suffix)
            key: str = s.split("=")[0]
            signal_counts[key] = signal_counts.get(key, 0) + 1

    for signal, count in sorted(signal_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {signal:25s}  {count:4d}  ({count / len(predicted_subagent) * 100:.1f}%)")

    # Save results
    output: dict[str, object] = {
        "experiment": "exp87_subagent_injection_validation",
        "total_pairs": len(pairs),
        "actual_subagent_count": len(actual_subagent),
        "predicted_subagent_count": len(predicted_subagent),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "accuracy": round(accuracy, 3),
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "signal_distribution": signal_counts,
    }

    results_path: Path = Path(__file__).parent / "exp87_results.json"
    results_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nResults saved to {results_path}")


if __name__ == "__main__":
    main()
