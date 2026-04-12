from __future__ import annotations

"""
Experiment 56: Conversation Turn Extraction Pipeline (C1b + C3 validation)

Tests whether the zero-LLM extraction pipeline can extract meaningful beliefs
from real conversation turns captured by the conversation-logger hook.

Method:
  1. Read conversation turns from ~/.claude/conversation-logs/turns.jsonl
  2. Run sentence decomposition on each turn
  3. Classify each sentence (decision, preference, fact, correction, etc.)
  4. Filter to belief-worthy sentences (skip greetings, status updates, code blocks)
  5. Label each extracted belief for sensitivity (low/medium/high)
  6. Report: extraction counts, type distribution, sensitivity breakdown, samples

This answers:
  - C1b: Can we extract beliefs from live conversation turns?
  - C3: How often does sensitive personal information appear?
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


LOG_FILE = Path.home() / ".claude" / "conversation-logs" / "turns.jsonl"


# ============================================================
# Sentence decomposition (adapted from Exp 42 for conversations)
# ============================================================

def split_into_sentences(text: str) -> list[str]:
    """Split text into sentences, handling conversation-style text."""
    # Remove markdown code blocks (not belief-worthy)
    text = re.sub(r'```[\s\S]*?```', ' [CODE_BLOCK] ', text)
    # Remove inline code
    text = re.sub(r'`[^`]+`', '[CODE]', text)
    # Remove URLs
    text = re.sub(r'https?://\S+', '[URL]', text)
    # Remove markdown headers but keep text
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Remove markdown formatting
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)

    # Split on sentence boundaries
    parts: list[str] = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    sentences: list[str] = []
    for part in parts:
        # Also split on newlines (conversation text is often line-delimited)
        for line in part.split('\n'):
            line = line.strip()
            # Skip very short lines, list markers, empty lines
            if len(line) < 15:
                continue
            # Skip lines that are just code references or file paths
            if line.startswith('/') or line.startswith('$'):
                continue
            # Skip tool output markers
            if line.startswith('[CODE_BLOCK]') or line == '[CODE]':
                continue
            sentences.append(line)
    return sentences


# ============================================================
# Belief classification (adapted for conversation content)
# ============================================================

DECISION_WORDS: list[str] = [
    'decided', 'chose', 'will use', 'going with', 'settled on',
    'picked', 'switched to', 'adopted', 'rejected', 'went with',
    "let's use", "let's go with", "we should",
]

PREFERENCE_WORDS: list[str] = [
    'prefer', 'like', 'want', 'always', 'never', 'hate',
    "don't like", 'rather', 'better to', 'instead of',
]

CORRECTION_WORDS: list[str] = [
    'no,', 'wrong', 'actually', 'not that', "that's incorrect",
    'correction', 'mistake', "don't do that", 'stop doing',
    "that's not right", 'wait,',
]

FACT_WORDS: list[str] = [
    ' is ', ' are ', ' was ', ' has ', ' uses ', ' runs on ',
    ' built with', ' works at', ' located in', ' version ',
]

REQUIREMENT_WORDS: list[str] = [
    'must', 'always', 'never', 'mandatory', 'require',
    'rule', 'constraint', 'condition', 'limit',
]

ASSUMPTION_WORDS: list[str] = [
    'assume', 'assuming', 'expect', 'should be', 'probably',
    'likely', 'i think', 'seems like', 'appears to',
]

PROCEDURAL_WORDS: list[str] = [
    'to do', 'first,', 'then,', 'step', 'run ', 'execute',
    'install', 'configure', 'deploy', 'set up',
]

# Sentences that are NOT belief-worthy
SKIP_PATTERNS: list[str] = [
    r'^(ok|okay|sure|yes|no|thanks|thank you|got it|sounds good)',
    r'^(let me|i\'ll|i will|i\'m going to)',  # action announcements
    r'^(here\'s|here is|the following)',  # output preambles
    r'^\d+\.',  # numbered list items (usually code/tool output)
    r'^(running|checking|reading|writing|searching)',  # status updates
    r'\[CODE',  # code references
    r'^---',  # separators
]


def classify_sentence(sentence: str) -> str | None:
    """Classify a sentence by belief type. Returns None if not belief-worthy."""
    s: str = sentence.lower().strip()

    # Check skip patterns first
    for pattern in SKIP_PATTERNS:
        if re.match(pattern, s):
            return None

    # Classify by keyword presence
    if any(w in s for w in CORRECTION_WORDS):
        return 'correction'
    if any(w in s for w in DECISION_WORDS):
        return 'decision'
    if any(w in s for w in REQUIREMENT_WORDS):
        return 'requirement'
    if any(w in s for w in PREFERENCE_WORDS):
        return 'preference'
    if any(w in s for w in ASSUMPTION_WORDS):
        return 'assumption'
    if any(w in s for w in PROCEDURAL_WORDS):
        return 'procedural'
    if any(w in s for w in FACT_WORDS):
        return 'fact'

    return None  # Not classifiable = not belief-worthy


# ============================================================
# Sensitivity classification (C3)
# ============================================================

PERSONAL_PATTERNS: list[str] = [
    r'\b(name|age|birthday|born|address|phone|email|salary|income)\b',
    r'\b(wife|husband|partner|spouse|child|daughter|son|family)\b',
    r'\b(health|medical|doctor|hospital|diagnosis|medication)\b',
    r'\b(password|secret|credential|token|api.?key|ssn|social security)\b',
    r'\b(political|religion|religious|sexuality|orientation)\b',
]

PROFESSIONAL_PATTERNS: list[str] = [
    r'\b(employer|company|manager|boss|colleague|coworker|team)\b',
    r'\b(hired|fired|quit|resigned|promotion|performance)\b',
    r'\b(client|customer|contract|nda|confidential)\b',
]


def classify_sensitivity(sentence: str) -> str:
    """Classify sensitivity: low (technical), medium (professional), high (personal)."""
    s: str = sentence.lower()

    for pattern in PERSONAL_PATTERNS:
        if re.search(pattern, s):
            return 'high'

    for pattern in PROFESSIONAL_PATTERNS:
        if re.search(pattern, s):
            return 'medium'

    return 'low'


# ============================================================
# Main
# ============================================================

def main() -> None:
    if not LOG_FILE.exists():
        print("No conversation log found. Run some conversations first.", file=sys.stderr)
        sys.exit(1)

    # Load turns
    turns: list[dict[str, Any]] = []
    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                turns.append(json.loads(line))

    print(f"Loaded {len(turns)} conversation turns", file=sys.stderr)
    print(f"  User messages: {sum(1 for t in turns if t['event'] == 'user')}",
          file=sys.stderr)
    print(f"  Assistant messages: {sum(1 for t in turns if t['event'] == 'assistant')}",
          file=sys.stderr)

    sessions: set[str] = {t['session_id'] for t in turns}
    print(f"  Sessions: {len(sessions)}", file=sys.stderr)

    # Extract beliefs from all turns
    all_beliefs: list[dict[str, Any]] = []
    type_counts: Counter[str] = Counter()
    sensitivity_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()

    for turn in turns:
        text: str = turn.get('text', '')
        if not text:
            continue

        sentences: list[str] = split_into_sentences(text)

        for sent in sentences:
            belief_type: str | None = classify_sentence(sent)
            if belief_type is None:
                continue

            sensitivity: str = classify_sensitivity(sent)

            belief: dict[str, Any] = {
                'text': sent[:200],  # cap display length
                'type': belief_type,
                'sensitivity': sensitivity,
                'source': turn['event'],  # user or assistant
                'session': turn['session_id'][:12],
            }
            all_beliefs.append(belief)
            type_counts[belief_type] += 1
            sensitivity_counts[sensitivity] += 1
            source_counts[turn['event']] += 1

    # ============================================================
    # Report
    # ============================================================

    print(f"\n{'='*70}", file=sys.stderr)
    print("EXPERIMENT 56: CONVERSATION EXTRACTION RESULTS", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)

    total_sentences: int = 0
    for turn in turns:
        total_sentences += len(split_into_sentences(turn.get('text', '')))

    print(f"\nSentences examined: {total_sentences}", file=sys.stderr)
    print(f"Beliefs extracted: {len(all_beliefs)}", file=sys.stderr)
    if total_sentences > 0:
        print(f"Extraction rate: {len(all_beliefs)/total_sentences:.1%} "
              f"of sentences are belief-worthy", file=sys.stderr)

    print(f"\n--- By Type ---", file=sys.stderr)
    for btype, count in type_counts.most_common():
        print(f"  {btype:<15s} {count:>4d}", file=sys.stderr)

    print(f"\n--- By Source ---", file=sys.stderr)
    for source, count in source_counts.most_common():
        print(f"  {source:<15s} {count:>4d}", file=sys.stderr)

    print(f"\n--- Sensitivity (C3) ---", file=sys.stderr)
    for level, count in sensitivity_counts.most_common():
        pct: float = count / len(all_beliefs) * 100 if all_beliefs else 0
        print(f"  {level:<15s} {count:>4d} ({pct:.0f}%)", file=sys.stderr)

    # Show samples of each type
    print(f"\n--- Samples (first 3 per type) ---", file=sys.stderr)
    shown: Counter[str] = Counter()
    for b in all_beliefs:
        bt: str = b['type']
        if shown[bt] >= 3:
            continue
        shown[bt] += 1
        sens_marker: str = ""
        if b['sensitivity'] == 'high':
            sens_marker = " [HIGH SENSITIVITY]"
        elif b['sensitivity'] == 'medium':
            sens_marker = " [MEDIUM]"
        print(f"  [{bt}] ({b['source']}) {b['text'][:120]}{sens_marker}",
              file=sys.stderr)

    # Show all high-sensitivity beliefs
    high_sens: list[dict[str, Any]] = [b for b in all_beliefs if b['sensitivity'] == 'high']
    if high_sens:
        print(f"\n--- All High-Sensitivity Beliefs ({len(high_sens)}) ---",
              file=sys.stderr)
        for b in high_sens:
            print(f"  [{b['type']}] {b['text'][:150]}", file=sys.stderr)
    else:
        print(f"\n  No high-sensitivity beliefs detected.", file=sys.stderr)

    # Verdict
    print(f"\n--- Verdicts ---", file=sys.stderr)

    if len(all_beliefs) > 0:
        print(f"  C1b: Extraction pipeline produces beliefs from conversation turns.",
              file=sys.stderr)
    else:
        print(f"  C1b: No beliefs extracted. Need more conversation data or "
              f"pipeline tuning.", file=sys.stderr)

    high_pct: float = len(high_sens) / len(all_beliefs) * 100 if all_beliefs else 0
    if high_pct > 20:
        print(f"  C3: {high_pct:.0f}% high-sensitivity. Sensitivity filter needed.",
              file=sys.stderr)
    elif high_pct > 5:
        print(f"  C3: {high_pct:.0f}% high-sensitivity. Monitor but not urgent.",
              file=sys.stderr)
    else:
        print(f"  C3: {high_pct:.0f}% high-sensitivity. Transparency-first approach "
              f"(option 1) is safe.", file=sys.stderr)

    # Save results
    output: dict[str, Any] = {
        "experiment": "exp56_conversation_extraction",
        "date": "2026-04-10",
        "input": {
            "turns": len(turns),
            "sessions": len(sessions),
            "total_sentences": total_sentences,
        },
        "extraction": {
            "beliefs_extracted": len(all_beliefs),
            "extraction_rate": round(len(all_beliefs) / total_sentences, 3)
            if total_sentences > 0 else 0,
            "by_type": dict(type_counts.most_common()),
            "by_source": dict(source_counts.most_common()),
            "by_sensitivity": dict(sensitivity_counts.most_common()),
        },
        "beliefs": all_beliefs,
    }

    out_path: Path = Path("experiments/exp56_results.json")
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults saved to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
