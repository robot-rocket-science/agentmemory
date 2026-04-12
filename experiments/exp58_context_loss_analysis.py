from __future__ import annotations

"""
Experiment 58: Context Loss Analysis in Real Conversation Data

Extracts every sentence from conversation logs, applies best-guess labels,
and produces a dataset for human review + analysis of distributions.

Two modes:
  --extract: Generate annotated dataset for human review
  --analyze: Compute distributions from reviewed dataset
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

LOG_FILE = Path.home() / ".claude" / "conversation-logs" / "turns.jsonl"
ANNOTATED_FILE = Path("experiments/exp58_annotated_turns.json")


# ============================================================
# Sentence extraction (same dumb split as Exp 57)
# ============================================================

def extract_sentences(text: str) -> list[str]:
    """Split into sentences. Minimal filtering."""
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'^\|.*\|$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[\s]*[-*]\s+', '', text, flags=re.MULTILINE)

    sentences: list[str] = []
    for line in text.split('\n'):
        line = line.strip()
        if len(line) < 10:
            continue
        parts: list[str] = re.split(r'(?<=[.!?])\s+', line)
        for part in parts:
            part = part.strip()
            if len(part) >= 10:
                sentences.append(part)
    return sentences


# ============================================================
# Best-guess labeling (for human review, NOT for production)
# ============================================================

def guess_persist(sentence: str, source: str) -> str:
    """Guess whether a sentence is worth persisting. Human corrects."""
    s: str = sentence.lower()

    # Almost certainly ephemeral
    if re.match(r'^(ok|okay|sure|yes|no|got it|sounds good|proceed|go ahead|do it)\b', s):
        return 'EPHEMERAL'
    if re.match(r'^(let me|i\'ll |i\'m going|here\'s |here is )', s):
        return 'EPHEMERAL'
    if re.match(r'^(running|checking|reading|writing|searching|loading|building)', s):
        return 'EPHEMERAL'
    if 'file=sys.stderr' in s or 'file_path' in s:
        return 'EPHEMERAL'

    # Likely persist-worthy from user
    if source == 'user':
        if any(w in s for w in ['decided', 'chose', 'will use', 'going with', 'use ']):
            return 'PERSIST'
        if any(w in s for w in ['prefer', 'always', 'never', 'dont ', "don't ", 'hate']):
            return 'PERSIST'
        if any(w in s for w in ['no,', 'wrong', 'actually', 'not that', 'correction']):
            return 'PERSIST'
        if any(w in s for w in ['must', 'require', 'rule', 'constraint']):
            return 'PERSIST'

    # Likely persist-worthy from assistant (analysis/conclusions)
    if source == 'assistant':
        if any(w in s for w in ['adopted', 'rejected', 'confirmed', 'validated']):
            return 'PERSIST'
        if any(w in s for w in ['the key finding', 'the main', 'the result', 'bottom line']):
            return 'PERSIST'

    # Questions are usually ephemeral
    if s.rstrip().endswith('?'):
        return 'EPHEMERAL'

    return 'UNCERTAIN'


def guess_type(sentence: str, source: str) -> str:
    """Guess information type."""
    s: str = sentence.lower()

    if re.match(r'^(ok|okay|sure|yes|no|got it|proceed|go ahead|next|do it)\b', s):
        return 'COORDINATION'
    if re.match(r'^(let me|i\'ll |i\'m going|here\'s |here is |checking|running)', s):
        return 'META'
    if s.rstrip().endswith('?'):
        return 'QUESTION'
    if any(w in s for w in ['no,', 'wrong', 'actually,', 'not that', "that's not",
                             'wait,', 'correction', 'stop doing']):
        return 'CORRECTION'
    if any(w in s for w in ['decided', 'chose', 'will use', 'going with', 'settled',
                             'adopted', 'rejected', "let's use", "let's go"]):
        return 'DECISION'
    if any(w in s for w in ['must', 'always', 'never', 'mandatory', 'require', 'rule']):
        return 'REQUIREMENT'
    if any(w in s for w in ['prefer', 'like ', 'want ', 'hate', "don't like", 'rather']):
        return 'PREFERENCE'
    if any(w in s for w in ['assume', 'assuming', 'expect', 'probably', 'seems like']):
        return 'ASSUMPTION'
    if any(w in s for w in ['because', 'therefore', 'this means', 'the reason',
                             'which means', 'the key', 'the main']):
        return 'ANALYSIS'
    if any(w in s for w in [' is ', ' are ', ' was ', ' has ', ' uses ', ' runs ']):
        return 'FACT'

    return 'UNCLASSIFIED'


def guess_clarity(sentence: str) -> str:
    """Guess how explicit the statement is."""
    s: str = sentence.lower()

    # Explicit: contains clear decision/preference/fact keywords
    if any(w in s for w in ['decided', 'chose', 'prefer', 'must', 'always',
                             'never', 'require', 'rule', 'adopted', 'rejected']):
        return 'EXPLICIT'

    # Likely implicit: meaning is there but phrasing is casual
    if len(s.split()) < 15 and not s.endswith('?'):
        return 'IMPLICIT'

    return 'AMBIGUOUS'


# ============================================================
# Extract mode
# ============================================================

def do_extract() -> None:
    """Generate annotated dataset for human review."""
    if not LOG_FILE.exists():
        print("No conversation log found.", file=sys.stderr)
        sys.exit(1)

    turns: list[dict[str, Any]] = []
    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                turns.append(json.loads(line))

    print(f"Loaded {len(turns)} turns", file=sys.stderr)

    entries: list[dict[str, Any]] = []
    idx: int = 0

    for turn in turns:
        text: str = turn.get('text', '')
        if not text:
            continue

        source: str = turn['event']
        session: str = turn['session_id'][:12]
        sentences: list[str] = extract_sentences(text)

        for sent in sentences:
            entries.append({
                'id': idx,
                'session': session,
                'source': source,
                'text': sent[:300],
                'persist': guess_persist(sent, source),
                'type': guess_type(sent, source),
                'clarity': guess_clarity(sent),
                'human_reviewed': False,
            })
            idx += 1

    # Write for review
    ANNOTATED_FILE.write_text(json.dumps(entries, indent=2))
    print(f"\nGenerated {len(entries)} entries -> {ANNOTATED_FILE}", file=sys.stderr)

    # Quick summary of guesses
    persist_counts: Counter[str] = Counter(e['persist'] for e in entries)
    type_counts: Counter[str] = Counter(e['type'] for e in entries)
    clarity_counts: Counter[str] = Counter(e['clarity'] for e in entries)

    print(f"\n--- Persist guess ---", file=sys.stderr)
    for k, v in persist_counts.most_common():
        print(f"  {k:<12s} {v:>4d} ({v/len(entries)*100:.0f}%)", file=sys.stderr)

    print(f"\n--- Type guess ---", file=sys.stderr)
    for k, v in type_counts.most_common():
        print(f"  {k:<16s} {v:>4d} ({v/len(entries)*100:.0f}%)", file=sys.stderr)

    print(f"\n--- Clarity guess ---", file=sys.stderr)
    for k, v in clarity_counts.most_common():
        print(f"  {k:<12s} {v:>4d} ({v/len(entries)*100:.0f}%)", file=sys.stderr)

    # Show the UNCERTAIN ones -- these are where human judgment is most needed
    uncertain: list[dict[str, Any]] = [e for e in entries if e['persist'] == 'UNCERTAIN']
    print(f"\n--- UNCERTAIN entries ({len(uncertain)}) -- need human review ---",
          file=sys.stderr)
    for e in uncertain[:30]:
        print(f"  [{e['source']:>9s}] [{e['type']:<14s}] {e['text'][:100]}",
              file=sys.stderr)
    if len(uncertain) > 30:
        print(f"  ... and {len(uncertain) - 30} more", file=sys.stderr)


# ============================================================
# Analyze mode
# ============================================================

def do_analyze() -> None:
    """Analyze annotated dataset (after human review)."""
    if not ANNOTATED_FILE.exists():
        print(f"No annotated file found. Run --extract first.", file=sys.stderr)
        sys.exit(1)

    entries: list[dict[str, Any]] = json.loads(ANNOTATED_FILE.read_text())
    total: int = len(entries)

    print(f"\n{'='*70}", file=sys.stderr)
    print("EXPERIMENT 58: CONTEXT LOSS ANALYSIS", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)
    print(f"\nTotal sentences: {total}", file=sys.stderr)

    reviewed: int = sum(1 for e in entries if e.get('human_reviewed', False))
    print(f"Human reviewed: {reviewed}/{total} "
          f"({reviewed/total*100:.0f}%)", file=sys.stderr)

    # H1: Signal density
    persist: list[dict[str, Any]] = [e for e in entries if e['persist'] == 'PERSIST']
    ephemeral: list[dict[str, Any]] = [e for e in entries if e['persist'] == 'EPHEMERAL']
    uncertain: list[dict[str, Any]] = [e for e in entries if e['persist'] == 'UNCERTAIN']

    print(f"\n--- H1: Signal Density ---", file=sys.stderr)
    print(f"  PERSIST:   {len(persist):>4d} ({len(persist)/total*100:.1f}%)", file=sys.stderr)
    print(f"  EPHEMERAL: {len(ephemeral):>4d} ({len(ephemeral)/total*100:.1f}%)", file=sys.stderr)
    print(f"  UNCERTAIN: {len(uncertain):>4d} ({len(uncertain)/total*100:.1f}%)", file=sys.stderr)

    if len(persist) / total < 0.20:
        print(f"  H1 SUPPORTED: {len(persist)/total*100:.0f}% < 20% persist-worthy",
              file=sys.stderr)
    else:
        print(f"  H1 REJECTED: {len(persist)/total*100:.0f}% >= 20% persist-worthy",
              file=sys.stderr)

    # H2: Source asymmetry
    print(f"\n--- H2: Source Asymmetry ---", file=sys.stderr)
    for source in ['user', 'assistant']:
        source_entries: list[dict[str, Any]] = [e for e in entries if e['source'] == source]
        source_persist: list[dict[str, Any]] = [e for e in source_entries if e['persist'] == 'PERSIST']
        if source_entries:
            rate: float = len(source_persist) / len(source_entries) * 100
            print(f"  {source:<10s}: {len(source_persist)}/{len(source_entries)} persist-worthy ({rate:.0f}%)",
                  file=sys.stderr)

            # Type distribution within persist-worthy
            type_dist: Counter[str] = Counter(e['type'] for e in source_persist)
            for t, c in type_dist.most_common(5):
                print(f"    {t:<16s} {c:>3d}", file=sys.stderr)

    # H3: Ambiguity
    print(f"\n--- H3: Clarity of Persist-Worthy Sentences ---", file=sys.stderr)
    if persist:
        clarity_dist: Counter[str] = Counter(e['clarity'] for e in persist)
        for k, v in clarity_dist.most_common():
            print(f"  {k:<12s} {v:>4d} ({v/len(persist)*100:.0f}%)", file=sys.stderr)

        implicit_pct: float = clarity_dist.get('IMPLICIT', 0) / len(persist) * 100
        ambiguous_pct: float = clarity_dist.get('AMBIGUOUS', 0) / len(persist) * 100
        hard_pct: float = implicit_pct + ambiguous_pct
        if hard_pct > 50:
            print(f"  H3 SUPPORTED: {hard_pct:.0f}% of persist-worthy is implicit/ambiguous",
                  file=sys.stderr)
        else:
            print(f"  H3 REJECTED: only {hard_pct:.0f}% implicit/ambiguous",
                  file=sys.stderr)

    # Overall type distribution
    print(f"\n--- Full Type Distribution ---", file=sys.stderr)
    type_counts: Counter[str] = Counter(e['type'] for e in entries)
    print(f"  {'Type':<16s} {'Total':>5s} {'Persist':>7s} {'Eph':>5s} {'Unc':>5s} {'P-Rate':>6s}",
          file=sys.stderr)
    print(f"  {'-'*16} {'-'*5} {'-'*7} {'-'*5} {'-'*5} {'-'*6}", file=sys.stderr)
    for t, total_count in type_counts.most_common():
        p: int = sum(1 for e in entries if e['type'] == t and e['persist'] == 'PERSIST')
        ep: int = sum(1 for e in entries if e['type'] == t and e['persist'] == 'EPHEMERAL')
        u: int = sum(1 for e in entries if e['type'] == t and e['persist'] == 'UNCERTAIN')
        rate_str: str = f"{p/total_count*100:.0f}%" if total_count > 0 else "n/a"
        print(f"  {t:<16s} {total_count:>5d} {p:>7d} {ep:>5d} {u:>5d} {rate_str:>6s}",
              file=sys.stderr)

    # Implied prior model
    print(f"\n--- Implied Prior Model ---", file=sys.stderr)
    print(f"  Based on persist rates by type x source:", file=sys.stderr)
    for source in ['user', 'assistant']:
        print(f"\n  {source.upper()}:", file=sys.stderr)
        for t, _ in type_counts.most_common():
            source_type: list[dict[str, Any]] = [
                e for e in entries
                if e['source'] == source and e['type'] == t
            ]
            if not source_type:
                continue
            p_count: int = sum(1 for e in source_type if e['persist'] == 'PERSIST')
            p_rate: float = p_count / len(source_type)
            # Map persist rate to Beta prior
            if p_rate >= 0.80:
                prior: str = "Beta(9,1) -- almost always worth keeping"
            elif p_rate >= 0.50:
                prior = "Beta(5,1) -- usually worth keeping"
            elif p_rate >= 0.20:
                prior = "Beta(2,1) -- sometimes worth keeping"
            elif p_rate > 0:
                prior = "Beta(1,1) -- rarely worth keeping, let feedback decide"
            else:
                prior = "DON'T STORE"
            print(f"    {t:<16s} {p_count:>2d}/{len(source_type):<3d} "
                  f"({p_rate:.0%}) -> {prior}", file=sys.stderr)

    # Save analysis
    output: dict[str, Any] = {
        "experiment": "exp58_context_loss_analysis",
        "date": "2026-04-10",
        "total_sentences": total,
        "reviewed": reviewed,
        "persist_distribution": {
            "PERSIST": len(persist),
            "EPHEMERAL": len(ephemeral),
            "UNCERTAIN": len(uncertain),
        },
        "type_distribution": dict(type_counts.most_common()),
    }

    out_path: Path = Path("experiments/exp58_results.json")
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults saved to {out_path}", file=sys.stderr)


# ============================================================
# Main
# ============================================================

def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ('--extract', '--analyze'):
        print("Usage: python exp58_context_loss_analysis.py --extract|--analyze",
              file=sys.stderr)
        sys.exit(1)

    if sys.argv[1] == '--extract':
        do_extract()
    else:
        do_analyze()


if __name__ == "__main__":
    main()
