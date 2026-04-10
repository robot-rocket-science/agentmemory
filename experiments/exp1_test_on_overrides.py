from __future__ import annotations

"""
Task #20: Run zero-LLM extraction on real OVERRIDES.md data.

Tests: Can the extraction pipeline identify that a user correction is being made,
what the correction is, and what belief is being corrected?

Ground truth: We parsed the overrides structurally (exp6_detect_failures_v2.py)
so we know exactly what each override says and which topic it belongs to.
"""

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from experiments.exp1_extraction_pipeline import extract_beliefs, classify_text
from experiments.exp6_detect_failures_v2 import parse_overrides


OVERRIDES_PATH = Path("/Users/thelorax/projects/alpha-seek-memtest/docs/gsd-archive/OVERRIDES.md")


def main() -> None:
    overrides: list[dict[str, Any]] = parse_overrides(OVERRIDES_PATH)

    print(f"Testing extraction on {len(overrides)} overrides\n", file=sys.stderr)

    results: list[dict[str, Any]] = []
    total_beliefs = 0
    correction_detected = 0
    _topic_detected = 0

    for i, override in enumerate(overrides):
        text: str = override["change"]
        beliefs = extract_beliefs(text)
        total_beliefs += len(beliefs)

        # Can we detect this is a correction?
        text_lower = text.lower()
        is_correction_signals: list[bool] = [
            "always" in text_lower,
            "never" in text_lower,
            "do not" in text_lower or "don't" in text_lower or "dont" in text_lower,
            "stop" in text_lower,
            "must" in text_lower,
            "not" in text_lower and any(w in text_lower for w in ["use", "do", "implement", "run"]),
            "rule" in text_lower or "require" in text_lower,
            text_lower.startswith("use "),
            "wrong" in text_lower or "incorrect" in text_lower or "not " in text_lower,
        ]
        correction_score = sum(is_correction_signals) / len(is_correction_signals)
        detected_as_correction = correction_score >= 0.2  # at least 2 signals

        if detected_as_correction:
            correction_detected += 1

        # Classification
        btype, conf = classify_text(text)

        result: dict[str, Any] = {
            "override_index": i,
            "timestamp": override["timestamp"][:10],
            "text": text[:150],
            "extracted_beliefs": len(beliefs),
            "belief_contents": [b.content[:80] for b in beliefs],
            "belief_types": [b.belief_type for b in beliefs],
            "correction_score": round(correction_score, 2),
            "detected_as_correction": detected_as_correction,
            "classification": btype,
            "classification_confidence": round(conf, 2),
            "decision_refs": override["decision_refs"],
        }
        results.append(result)

        status = "CORR" if detected_as_correction else "miss"
        beliefs_str = f"{len(beliefs)} beliefs" if beliefs else "NO beliefs"
        print(f"  [{status}] {override['timestamp'][:10]}: {beliefs_str}, "
              f"class={btype}({conf:.2f}), corr={correction_score:.2f}", file=sys.stderr)
        if beliefs:
            for b in beliefs[:2]:
                print(f"         [{b.belief_type}] {b.content[:70]}", file=sys.stderr)
        print(f"         text: {text[:80]}", file=sys.stderr)

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"EXTRACTION SUMMARY", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"  Total overrides: {len(overrides)}", file=sys.stderr)
    print(f"  Overrides with extracted beliefs: {sum(1 for r in results if r['extracted_beliefs'] > 0)}/{len(overrides)} "
          f"({sum(1 for r in results if r['extracted_beliefs'] > 0)/len(overrides):.0%})", file=sys.stderr)
    print(f"  Total beliefs extracted: {total_beliefs}", file=sys.stderr)
    print(f"  Avg beliefs per override: {total_beliefs/len(overrides):.1f}", file=sys.stderr)
    print(f"  Detected as correction: {correction_detected}/{len(overrides)} "
          f"({correction_detected/len(overrides):.0%})", file=sys.stderr)

    # Breakdown by whether correction was detected
    with_beliefs_and_correction = sum(
        1 for r in results if r["extracted_beliefs"] > 0 and r["detected_as_correction"]
    )
    print(f"  Beliefs + correction detected: {with_beliefs_and_correction}/{len(overrides)} "
          f"({with_beliefs_and_correction/len(overrides):.0%})", file=sys.stderr)

    # Classification distribution
    class_counts: dict[str, int] = {}
    for r in results:
        c: str = r["classification"]
        class_counts[c] = class_counts.get(c, 0) + 1
    print(f"\n  Classification distribution:", file=sys.stderr)
    for c, count in sorted(class_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"    {c}: {count}", file=sys.stderr)

    # What did the pipeline miss entirely?
    missed = [r for r in results if r["extracted_beliefs"] == 0]
    if missed:
        print(f"\n  Overrides with ZERO extracted beliefs ({len(missed)}):", file=sys.stderr)
        for r in missed[:5]:
            print(f"    {r['timestamp']}: {r['text'][:80]}", file=sys.stderr)

    output_path = Path("experiments/exp1_overrides_results.json")
    output_path.write_text(json.dumps(results, indent=2))
    print(f"\nOutput: {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
