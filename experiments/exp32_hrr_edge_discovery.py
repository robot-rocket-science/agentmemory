"""
Experiment 32: HRR Edge Discovery vs Regex Edge Extraction

Can HRR discover sentence-to-sentence relationships without regex?

Ground truth: 223 CITES edges extracted by regex in Exp 31 (D### references).

Method: For each sentence, bind it with a ROLE vector (based on its type and
parent decision). Sentences from the same decision share a parent binding.
Then query: for a given sentence, which other sentences are structurally
related through the HRR encoding?

If HRR discovers the same edges that regex found, it validates HRR as a
graph construction method for onboarding -- including for documents that
DON'T have D### citation syntax.

Hypothesis: HRR will find SOME of the regex-discovered edges (the ones where
co-occurrence signals are strong) but miss others (where the only signal is
the D### text pattern). The interesting question is what ELSE HRR finds that
regex misses.
"""

import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

DIM = 2048

DB = Path("/Users/thelorax/projects/.gsd/workflows/spikes/"
          "260406-1-associative-memory-for-gsd-please-explor/"
          "sandbox/alpha-seek.db")


def make_vec(rng):
    v = rng.standard_normal(DIM)
    return v / np.linalg.norm(v)

def bind(a, b):
    return np.real(np.fft.ifft(np.fft.fft(a) * np.fft.fft(b)))

def unbind(key, bound):
    return np.real(np.fft.ifft(np.conj(np.fft.fft(key)) * np.fft.fft(bound)))

def cos_sim(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0: return 0.0
    return float(np.dot(a, b) / (na * nb))


def split_sents(text):
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    sents = []
    for p in parts:
        for sp in p.split(' | '):
            sp = sp.strip()
            if len(sp) > 10:
                sents.append(sp)
    return sents


def classify(s):
    sl = s.lower()
    if any(w in sl for w in ['must', 'always', 'never', 'mandatory', 'require', 'banned', 'do not']):
        return 'constraint'
    if any(w in sl for w in ['because', 'rationale', 'reason', 'driven by']):
        return 'rationale'
    if any(w in sl for w in ['data', 'showed', 'result', 'found', '%', 'measured']):
        return 'evidence'
    if any(w in sl for w in ['supersede', 'replace', 'retire']):
        return 'supersession'
    return 'context'


def main():
    rng = np.random.default_rng(42)

    print("=" * 60, file=sys.stderr)
    print("Experiment 32: HRR Edge Discovery vs Regex", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # --- Load and decompose ---
    db = sqlite3.connect(str(DB))
    sentences = {}
    groups = {}

    for row in db.execute("SELECT id, decision, choice, rationale FROM decisions"):
        did = row[0]
        full = f"{row[1]}: {row[2]}"
        if row[3]:
            full += f" | {row[3]}"

        sents = split_sents(full)
        g = []
        for i, s in enumerate(sents):
            sid = f"{did}_s{i}"
            sentences[sid] = {
                "content": s,
                "parent": did,
                "index": i,
                "type": classify(s),
            }
            g.append(sid)
        groups[did] = g

    db.close()
    print(f"  {len(sentences)} sentences from {len(groups)} decisions", file=sys.stderr)

    # --- Ground truth: regex-extracted CITES edges ---
    d_ref = re.compile(r'\bD(\d{2,3})\b')
    regex_edges = set()
    for sid, sent in sentences.items():
        parent = sent["parent"]
        for m in d_ref.finditer(sent["content"]):
            target_did = f"D{m.group(1)}"
            if target_did != parent and target_did in groups and groups[target_did]:
                target_sid = groups[target_did][0]
                regex_edges.add((sid, target_sid))

    print(f"  Regex CITES edges (ground truth): {len(regex_edges)}", file=sys.stderr)

    # --- HRR encoding: bind sentences with structural context ---
    node_vecs = {sid: make_vec(rng) for sid in sentences}
    parent_vecs = {did: make_vec(rng) for did in groups}
    type_vecs = {t: make_vec(rng) for t in ['constraint', 'rationale', 'evidence', 'supersession', 'context']}

    # Build a structural encoding for each sentence:
    # encoded[sid] = node_vec * parent_vec * type_vec
    # This captures: what sentence is this, what decision is it from, what role does it play
    encoded = {}
    for sid, sent in sentences.items():
        encoded[sid] = bind(bind(node_vecs[sid], parent_vecs[sent["parent"]]),
                           type_vecs[sent["type"]])

    # Build superposition per decision: all sentences in a decision, encoded
    decision_supers = {}
    for did, group in groups.items():
        S = np.zeros(DIM)
        for sid in group:
            S += encoded[sid]
        decision_supers[did] = S

    # --- HRR Edge Discovery ---
    # For each sentence, query: "which sentences in OTHER decisions are
    # structurally similar to me?" by comparing against other decisions' superpositions
    #
    # The HRR way: unbind my structural encoding from another decision's superposition.
    # If the result is close to any known node vector, there's a relationship.

    print(f"\n  Discovering edges via HRR structural similarity...", file=sys.stderr)

    discovered_edges = set()
    discovery_scores = {}

    # Focus on sentences that have regex CITES edges (so we can compare)
    source_sids = set(src for src, _ in regex_edges)

    for src_sid in source_sids:
        src_sent = sentences[src_sid]
        src_parent = src_sent["parent"]
        src_enc = encoded[src_sid]

        # Query each other decision's superposition
        best_targets = []
        for did, S in decision_supers.items():
            if did == src_parent:
                continue  # skip own decision

            # Unbind source's type to find sentences of similar structural role
            result = unbind(type_vecs[src_sent["type"]], S)

            # Check against all sentences in this decision
            for target_sid in groups[did]:
                sim = cos_sim(result, node_vecs[target_sid])
                if sim > 0.03:  # above noise floor
                    best_targets.append((target_sid, sim))

        best_targets.sort(key=lambda x: x[1], reverse=True)

        # Take top-K as discovered edges
        for target_sid, sim in best_targets[:5]:
            discovered_edges.add((src_sid, target_sid))
            discovery_scores[(src_sid, target_sid)] = sim

    print(f"  Discovered edges: {len(discovered_edges)}", file=sys.stderr)

    # --- Compare ---
    # How many regex edges did HRR discover?
    true_positives = regex_edges & discovered_edges
    false_positives = discovered_edges - regex_edges
    false_negatives = regex_edges - discovered_edges

    precision = len(true_positives) / len(discovered_edges) if discovered_edges else 0
    recall = len(true_positives) / len(regex_edges) if regex_edges else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"RESULTS: HRR Edge Discovery vs Regex Ground Truth", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"  Regex edges (ground truth): {len(regex_edges)}", file=sys.stderr)
    print(f"  HRR discovered edges:       {len(discovered_edges)}", file=sys.stderr)
    print(f"  True positives:             {len(true_positives)}", file=sys.stderr)
    print(f"  False positives:            {len(false_positives)}", file=sys.stderr)
    print(f"  False negatives:            {len(false_negatives)}", file=sys.stderr)
    print(f"  Precision:                  {precision:.3f}", file=sys.stderr)
    print(f"  Recall:                     {recall:.3f}", file=sys.stderr)
    print(f"  F1:                         {f1:.3f}", file=sys.stderr)

    # Show some true positives
    if true_positives:
        print(f"\n  Sample TRUE POSITIVES (HRR found what regex found):", file=sys.stderr)
        for src, dst in list(true_positives)[:5]:
            sim = discovery_scores.get((src, dst), 0)
            print(f"    {src} -> {dst} (sim={sim:.4f})", file=sys.stderr)
            print(f"      src: {sentences[src]['content'][:60]}", file=sys.stderr)
            print(f"      dst: {sentences[dst]['content'][:60]}", file=sys.stderr)

    # Show some false positives (HRR found something regex didn't)
    if false_positives:
        print(f"\n  Sample FALSE POSITIVES (HRR found, regex didn't -- are these real?):",
              file=sys.stderr)
        fps = sorted(false_positives, key=lambda e: discovery_scores.get(e, 0), reverse=True)
        for src, dst in fps[:5]:
            sim = discovery_scores.get((src, dst), 0)
            print(f"    {src} -> {dst} (sim={sim:.4f})", file=sys.stderr)
            print(f"      src: {sentences[src]['content'][:60]}", file=sys.stderr)
            print(f"      dst: {sentences[dst]['content'][:60]}", file=sys.stderr)

    # Key question: are the false positives actually useful relationships
    # that regex couldn't find because there's no D### reference?
    print(f"\n  KEY QUESTION: Are the {len(false_positives)} 'false positives' actually", file=sys.stderr)
    print(f"  useful relationships that regex missed (no D### reference)?", file=sys.stderr)
    print(f"  Manual inspection of the samples above is needed.", file=sys.stderr)


if __name__ == "__main__":
    main()
