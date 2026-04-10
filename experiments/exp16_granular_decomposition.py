"""
Experiment 16: Granular Node Decomposition

Decomposes decisions into sentence-level nodes. Measures:
- How many nodes per decision
- Token savings (sentence vs whole decision)
- Edge connectivity (how do sentence nodes link to each other and to other decisions)
- Whether critical assertions can be identified automatically
"""

import json
import re
import sqlite3
import sys
from pathlib import Path


ALPHA_SEEK_DB = Path("/Users/thelorax/projects/.gsd/workflows/spikes/"
                     "260406-1-associative-memory-for-gsd-please-explor/"
                     "sandbox/alpha-seek.db")


def split_into_sentences(text: str) -> list[str]:
    """Split text into sentences. Simple rule-based splitter.

    Uses period/exclamation/question followed by space or newline.
    Preserves sentences that contain abbreviations (e.g., "D097") by
    not splitting on periods preceded by uppercase letters or digits.
    """
    # Split on sentence boundaries
    # Negative lookbehind: don't split after single uppercase letter (abbreviations)
    # or after digits (D097. should not split)
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)

    sentences = []
    for part in parts:
        # Further split on pipe separator (decision | rationale format)
        subparts = part.split(' | ')
        for sp in subparts:
            sp = sp.strip()
            if len(sp) > 10:  # skip very short fragments
                sentences.append(sp)

    return sentences


def classify_sentence(sentence: str) -> str:
    """Classify a sentence by its role in a decision."""
    s = sentence.lower()

    if any(w in s for w in ['because', 'rationale', 'reason', 'driven by', 'root cause']):
        return 'rationale'
    if any(w in s for w in ['supersede', 'replace', 'retire', 'override']):
        return 'supersession'
    if any(w in s for w in ['must', 'always', 'never', 'mandatory', 'require', 'rule']):
        return 'constraint'
    if any(w in s for w in ['data', 'showed', 'result', 'found', 'measured', '%', 'x ']):
        return 'evidence'
    if any(w in s for w in ['script', 'implement', 'code', '.py', 'function']):
        return 'implementation'
    if re.match(r'^[A-Z].*:', s):  # starts with "Topic: ..."
        return 'assertion'

    return 'context'


def extract_refs(sentence: str) -> list[str]:
    """Extract D###, M###, K### references from a sentence."""
    refs = set()
    for m in re.finditer(r'\b(D\d{2,3}|M\d{2,3}|K\d{2,3})\b', sentence):
        refs.add(m.group(1))
    return sorted(refs)


def main():
    db = sqlite3.connect(str(ALPHA_SEEK_DB))

    decisions = db.execute(
        "SELECT id, decision, choice, rationale FROM decisions ORDER BY seq"
    ).fetchall()

    print(f"Decomposing {len(decisions)} decisions into sentence-level nodes\n",
          file=sys.stderr)

    all_nodes = []
    total_original_tokens = 0
    total_sentence_tokens = 0
    sentences_per_decision = []
    type_counts = {}
    cross_refs = 0

    for row in decisions:
        did = row[0]
        full_text = f"{row[1]}: {row[2]}"
        if row[3]:
            full_text += f" | {row[3]}"

        original_tokens = len(full_text) // 4
        total_original_tokens += original_tokens

        sentences = split_into_sentences(full_text)
        sentences_per_decision.append(len(sentences))

        for i, sent in enumerate(sentences):
            sent_tokens = len(sent) // 4
            total_sentence_tokens += sent_tokens

            stype = classify_sentence(sent)
            type_counts[stype] = type_counts.get(stype, 0) + 1

            refs = extract_refs(sent)
            # Don't count self-references
            refs = [r for r in refs if r != did]
            cross_refs += len(refs)

            node = {
                "id": f"{did}_s{i}",
                "parent_decision": did,
                "sentence_index": i,
                "content": sent,
                "tokens": sent_tokens,
                "type": stype,
                "references": refs,
            }
            all_nodes.append(node)

    # Statistics
    import numpy as np
    spd = np.array(sentences_per_decision)

    print(f"{'='*60}", file=sys.stderr)
    print(f"DECOMPOSITION RESULTS", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"  Decisions: {len(decisions)}", file=sys.stderr)
    print(f"  Sentence nodes: {len(all_nodes)}", file=sys.stderr)
    print(f"  Avg sentences/decision: {spd.mean():.1f} "
          f"(median: {np.median(spd):.0f}, max: {spd.max()})", file=sys.stderr)
    print(f"  Original tokens (all decisions): {total_original_tokens:,}", file=sys.stderr)
    print(f"  Cross-references between sentences: {cross_refs}", file=sys.stderr)

    print(f"\n  Sentence type distribution:", file=sys.stderr)
    for stype, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"    {stype}: {count} ({count/len(all_nodes):.0%})", file=sys.stderr)

    # Token analysis: if we only load the relevant sentence(s) instead of whole decision
    # For anchor nodes, we might load just the assertion sentence
    assertion_nodes = [n for n in all_nodes if n["type"] == "assertion"]
    constraint_nodes = [n for n in all_nodes if n["type"] == "constraint"]
    core_nodes = assertion_nodes + constraint_nodes
    core_tokens = sum(n["tokens"] for n in core_nodes)

    print(f"\n  Token analysis:", file=sys.stderr)
    print(f"    All sentences total: {total_sentence_tokens:,} tokens", file=sys.stderr)
    print(f"    Core nodes (assertion + constraint): {len(core_nodes)} nodes, "
          f"{core_tokens:,} tokens", file=sys.stderr)
    print(f"    Token reduction (core only vs all): "
          f"{(1 - core_tokens/total_sentence_tokens):.0%}", file=sys.stderr)

    # What would anchor context look like?
    # Top 10 most-referenced decisions, loading only their assertion sentences
    ref_counts = {}
    for n in all_nodes:
        for ref in n["references"]:
            ref_counts[ref] = ref_counts.get(ref, 0) + 1

    top_anchors = sorted(ref_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    print(f"\n  Top 10 anchor candidates (by cross-reference count):", file=sys.stderr)
    anchor_tokens_full = 0
    anchor_tokens_core = 0
    for anchor_id, count in top_anchors:
        anchor_sentences = [n for n in all_nodes if n["parent_decision"] == anchor_id]
        anchor_core = [n for n in anchor_sentences if n["type"] in ("assertion", "constraint")]

        full_tok = sum(n["tokens"] for n in anchor_sentences)
        core_tok = sum(n["tokens"] for n in anchor_core)
        anchor_tokens_full += full_tok
        anchor_tokens_core += core_tok

        print(f"    {anchor_id} ({count} refs): {len(anchor_sentences)} sentences, "
              f"{full_tok} tok full / {core_tok} tok core", file=sys.stderr)

    print(f"\n  Anchor context (top 10):", file=sys.stderr)
    print(f"    Full sentences: {anchor_tokens_full} tokens", file=sys.stderr)
    print(f"    Core only: {anchor_tokens_core} tokens", file=sys.stderr)
    print(f"    Reduction: {(1 - anchor_tokens_core/anchor_tokens_full):.0%}", file=sys.stderr)

    # Output
    output = {
        "total_decisions": len(decisions),
        "total_sentence_nodes": len(all_nodes),
        "avg_sentences_per_decision": round(float(spd.mean()), 1),
        "total_original_tokens": total_original_tokens,
        "total_sentence_tokens": total_sentence_tokens,
        "core_nodes": len(core_nodes),
        "core_tokens": core_tokens,
        "type_distribution": type_counts,
        "top_anchors": [{"id": a, "refs": c} for a, c in top_anchors],
        "anchor_tokens_full": anchor_tokens_full,
        "anchor_tokens_core": anchor_tokens_core,
    }

    Path("experiments/exp16_results.json").write_text(json.dumps(output, indent=2))

    # Also save the sentence nodes for further analysis
    Path("experiments/exp16_sentence_nodes.json").write_text(
        json.dumps(all_nodes[:50], indent=2)  # first 50 for inspection
    )

    print(f"\nOutput: experiments/exp16_results.json", file=sys.stderr)
    db.close()


if __name__ == "__main__":
    main()
