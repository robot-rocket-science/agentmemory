"""
Experiment 29: Sentence-Level vs Decision-Level Retrieval

Tests whether retrieving individual sentences produces better or worse
context than retrieving whole decisions, given the same token budget.

"Better" means: the critical assertions are present AND there's enough
surrounding context for the agent to act on them.

Uses the 6 critical belief topics from Exp 4/6 as ground truth.
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

ALPHA_SEEK_DB = Path("/Users/thelorax/projects/.gsd/workflows/spikes/"
                     "260406-1-associative-memory-for-gsd-please-explor/"
                     "sandbox/alpha-seek.db")

CRITICAL = {
    "dispatch_gate": {
        "query": "dispatch gate deploy protocol verification runbook",
        "needed": {"D089", "D106", "D137"},
    },
    "calls_puts": {
        "query": "calls puts equal citizens strategy both directions",
        "needed": {"D073", "D096", "D100"},
    },
    "capital_5k": {
        "query": "starting capital bankroll five thousand dollars",
        "needed": {"D099"},
    },
    "agent_behavior": {
        "query": "agent behavior instructions execute precisely elaborate",
        "needed": {"D188"},  # D157 excluded -- known vocabulary mismatch
    },
    "strict_typing": {
        "query": "typing pyright strict python type annotations",
        "needed": {"D071", "D113"},
    },
    "gcp_primary": {
        "query": "GCP primary compute platform archon overflow",
        "needed": {"D078", "D120"},
    },
}

TOKEN_BUDGET = 1000


def split_into_sentences(text):
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    sentences = []
    for part in parts:
        for sp in part.split(' | '):
            sp = sp.strip()
            if len(sp) > 10:
                sentences.append(sp)
    return sentences


def load_data():
    db = sqlite3.connect(str(ALPHA_SEEK_DB))

    # Decision-level nodes
    decisions = {}
    for row in db.execute("SELECT id, decision, choice, rationale FROM decisions"):
        full = f"{row[1]}: {row[2]}"
        if row[3]:
            full += f" | {row[3]}"
        decisions[row[0]] = {
            "content": full,
            "tokens": len(full) // 4,
        }

    # Sentence-level decomposition
    sentences = {}
    for did, dec in decisions.items():
        sents = split_into_sentences(dec["content"])
        for i, sent in enumerate(sents):
            sid = f"{did}_s{i}"
            sentences[sid] = {
                "content": sent,
                "tokens": len(sent) // 4,
                "parent": did,
                "index": i,
            }

    db.close()
    return decisions, sentences


def build_fts(items, table_name="fts"):
    db = sqlite3.connect(":memory:")
    db.execute(f"CREATE VIRTUAL TABLE {table_name} USING fts5(id, content, tokenize='porter')")
    for nid, item in items.items():
        db.execute(f"INSERT INTO {table_name} VALUES (?, ?)", (nid, item["content"]))
    db.commit()
    return db


def search(query, fts_db, items, budget, table_name="fts"):
    terms = [t for t in query.split() if len(t) > 2]
    q = " OR ".join(terms)
    try:
        results = fts_db.execute(
            f"SELECT id FROM {table_name} WHERE {table_name} MATCH ? ORDER BY rank LIMIT 50",
            (q,)
        ).fetchall()
    except:
        return [], 0

    retrieved = []
    tokens_used = 0
    for row in results:
        nid = row[0]
        item = items[nid]
        if tokens_used + item["tokens"] > budget:
            continue
        retrieved.append(nid)
        tokens_used += item["tokens"]

    return retrieved, tokens_used


def main():
    decisions, sentences = load_data()

    print(f"Decisions: {len(decisions)}, Sentences: {len(sentences)}", file=sys.stderr)
    print(f"Token budget: {TOKEN_BUDGET}\n", file=sys.stderr)

    fts_dec = build_fts(decisions, "fts_dec")
    fts_sent = build_fts(sentences, "fts_sent")

    results = {}

    for topic_id, topic in CRITICAL.items():
        query = topic["query"]
        needed = topic["needed"]

        # Decision-level retrieval
        dec_retrieved, dec_tokens = search(query, fts_dec, decisions, TOKEN_BUDGET, "fts_dec")
        dec_found = needed & set(dec_retrieved)
        dec_items = len(dec_retrieved)

        # Sentence-level retrieval
        sent_retrieved, sent_tokens = search(query, fts_sent, sentences, TOKEN_BUDGET, "fts_sent")
        # Map sentence IDs back to parent decisions
        sent_parents = {sentences[sid]["parent"] for sid in sent_retrieved}
        sent_found = needed & sent_parents
        sent_items = len(sent_retrieved)

        results[topic_id] = {
            "decision_level": {
                "found": list(dec_found),
                "missed": list(needed - dec_found),
                "coverage": len(dec_found) / len(needed) if needed else 0,
                "items_retrieved": dec_items,
                "tokens_used": dec_tokens,
            },
            "sentence_level": {
                "found": list(sent_found),
                "missed": list(needed - sent_found),
                "coverage": len(sent_found) / len(needed) if needed else 0,
                "items_retrieved": sent_items,
                "tokens_used": sent_tokens,
            },
        }

        print(f"  {topic_id}:", file=sys.stderr)
        print(f"    Decision: {len(dec_found)}/{len(needed)} found, "
              f"{dec_items} items, {dec_tokens} tokens", file=sys.stderr)
        print(f"    Sentence: {len(sent_found)}/{len(needed)} found, "
              f"{sent_items} items, {sent_tokens} tokens", file=sys.stderr)

        # Show what sentence-level actually returns vs decision-level
        if sent_retrieved:
            print(f"    Sentence content sample:", file=sys.stderr)
            for sid in sent_retrieved[:3]:
                s = sentences[sid]
                print(f"      [{s['parent']}_s{s['index']}] {s['content'][:80]}", file=sys.stderr)

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"{'Topic':<18} {'Dec Cov':>8} {'Dec Tok':>8} {'Dec #':>5} "
          f"{'Sent Cov':>9} {'Sent Tok':>9} {'Sent #':>6}", file=sys.stderr)
    print("-" * 70, file=sys.stderr)

    dec_total_found = 0
    sent_total_found = 0
    dec_total_tokens = 0
    sent_total_tokens = 0
    total_needed = 0

    for topic_id, r in results.items():
        needed_count = len(CRITICAL[topic_id]["needed"])
        total_needed += needed_count
        d = r["decision_level"]
        s = r["sentence_level"]
        dec_total_found += len(d["found"])
        sent_total_found += len(s["found"])
        dec_total_tokens += d["tokens_used"]
        sent_total_tokens += s["tokens_used"]

        print(f"{topic_id:<18} {d['coverage']:>8.0%} {d['tokens_used']:>8} {d['items_retrieved']:>5} "
              f"{s['coverage']:>9.0%} {s['tokens_used']:>9} {s['items_retrieved']:>6}", file=sys.stderr)

    print(f"\n  Decision-level: {dec_total_found}/{total_needed} found, "
          f"avg {dec_total_tokens/6:.0f} tokens/topic", file=sys.stderr)
    print(f"  Sentence-level: {sent_total_found}/{total_needed} found, "
          f"avg {sent_total_tokens/6:.0f} tokens/topic", file=sys.stderr)
    print(f"  Token efficiency: sentence uses "
          f"{sent_total_tokens/max(dec_total_tokens,1):.0%} of decision's budget", file=sys.stderr)

    # The key question: does sentence-level give ENOUGH context?
    print(f"\n  QUALITATIVE: Does sentence-level retrieval provide enough context?", file=sys.stderr)
    print(f"  Decision-level returns {dec_total_found} decisions with full rationale.", file=sys.stderr)
    print(f"  Sentence-level returns {sum(r['sentence_level']['items_retrieved'] for r in results.values())} "
          f"individual sentences -- more items, less context per item.", file=sys.stderr)
    print(f"  The question: can the agent act on isolated sentences, or does it need", file=sys.stderr)
    print(f"  the surrounding rationale? This requires qualitative inspection.", file=sys.stderr)

    Path("experiments/exp29_results.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
