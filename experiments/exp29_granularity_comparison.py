"""
Experiment 29: Sentence-Level vs Decision-Level Retrieval

Tests whether retrieving individual sentences produces better or worse
context than retrieving whole decisions, given the same token budget.

"Better" means: the critical assertions are present AND there's enough
surrounding context for the agent to act on them.

Uses the 6 critical belief topics from Exp 4/6 as ground truth.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, TypedDict

project-a_DB: Path = Path(
    "/home/user/projects/.gsd/workflows/spikes/"
    "260406-1-associative-memory-for-gsd-please-explor/"
    "sandbox/project-a.db"
)


class TopicInfo(TypedDict):
    query: str
    needed: set[str]


CRITICAL: dict[str, TopicInfo] = {
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
        "query": "GCP primary compute platform server-a overflow",
        "needed": {"D078", "D120"},
    },
}

TOKEN_BUDGET: int = 1000


class DecisionItem(TypedDict):
    content: str
    tokens: int


class SentenceItem(TypedDict):
    content: str
    tokens: int
    parent: str
    index: int


def split_into_sentences(text: str) -> list[str]:
    parts: list[str] = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    sentences: list[str] = []
    for part in parts:
        for sp in part.split(" | "):
            sp = sp.strip()
            if len(sp) > 10:
                sentences.append(sp)
    return sentences


def load_data() -> tuple[dict[str, DecisionItem], dict[str, SentenceItem]]:
    db: sqlite3.Connection = sqlite3.connect(str(project-a_DB))

    # Decision-level nodes
    decisions: dict[str, DecisionItem] = {}
    for row in db.execute("SELECT id, decision, choice, rationale FROM decisions"):
        full: str = f"{row[1]}: {row[2]}"
        if row[3]:
            full += f" | {row[3]}"
        decisions[str(row[0])] = DecisionItem(
            content=full,
            tokens=len(full) // 4,
        )

    # Sentence-level decomposition
    sentences: dict[str, SentenceItem] = {}
    for did, dec in decisions.items():
        sents: list[str] = split_into_sentences(dec["content"])
        for i, sent in enumerate(sents):
            sid: str = f"{did}_s{i}"
            sentences[sid] = SentenceItem(
                content=sent,
                tokens=len(sent) // 4,
                parent=did,
                index=i,
            )

    db.close()
    return decisions, sentences


def build_fts(
    items: dict[str, DecisionItem] | dict[str, SentenceItem], table_name: str = "fts"
) -> sqlite3.Connection:
    db: sqlite3.Connection = sqlite3.connect(":memory:")
    db.execute(
        f"CREATE VIRTUAL TABLE {table_name} USING fts5(id, content, tokenize='porter')"
    )
    for nid, item in items.items():
        db.execute(f"INSERT INTO {table_name} VALUES (?, ?)", (nid, item["content"]))
    db.commit()
    return db


def search(
    query: str,
    fts_db: sqlite3.Connection,
    items: dict[str, DecisionItem] | dict[str, SentenceItem],
    budget: int,
    table_name: str = "fts",
) -> tuple[list[str], int]:
    terms: list[str] = [t for t in query.split() if len(t) > 2]
    q: str = " OR ".join(terms)
    try:
        results: list[Any] = fts_db.execute(
            f"SELECT id FROM {table_name} WHERE {table_name} MATCH ? ORDER BY rank LIMIT 50",
            (q,),
        ).fetchall()
    except sqlite3.OperationalError:
        return [], 0

    retrieved: list[str] = []
    tokens_used: int = 0
    for row in results:
        nid: str = str(row[0])
        item = items[nid]
        if tokens_used + item["tokens"] > budget:
            continue
        retrieved.append(nid)
        tokens_used += item["tokens"]

    return retrieved, tokens_used


class LevelResult(TypedDict):
    found: list[str]
    missed: list[str]
    coverage: float
    items_retrieved: int
    tokens_used: int


class TopicResult(TypedDict):
    decision_level: LevelResult
    sentence_level: LevelResult


def main() -> None:
    decisions: dict[str, DecisionItem]
    sentences: dict[str, SentenceItem]
    decisions, sentences = load_data()

    print(f"Decisions: {len(decisions)}, Sentences: {len(sentences)}", file=sys.stderr)
    print(f"Token budget: {TOKEN_BUDGET}\n", file=sys.stderr)

    fts_dec: sqlite3.Connection = build_fts(decisions, "fts_dec")
    fts_sent: sqlite3.Connection = build_fts(sentences, "fts_sent")

    results: dict[str, TopicResult] = {}

    for topic_id, topic in CRITICAL.items():
        query: str = topic["query"]
        needed: set[str] = topic["needed"]

        # Decision-level retrieval
        dec_retrieved: list[str]
        dec_tokens: int
        dec_retrieved, dec_tokens = search(
            query, fts_dec, decisions, TOKEN_BUDGET, "fts_dec"
        )
        dec_found: set[str] = needed & set(dec_retrieved)
        dec_items: int = len(dec_retrieved)

        # Sentence-level retrieval
        sent_retrieved: list[str]
        sent_tokens: int
        sent_retrieved, sent_tokens = search(
            query, fts_sent, sentences, TOKEN_BUDGET, "fts_sent"
        )
        # Map sentence IDs back to parent decisions
        sent_parents: set[str] = {sentences[sid]["parent"] for sid in sent_retrieved}
        sent_found: set[str] = needed & sent_parents
        sent_items: int = len(sent_retrieved)

        results[topic_id] = TopicResult(
            decision_level=LevelResult(
                found=list(dec_found),
                missed=list(needed - dec_found),
                coverage=len(dec_found) / len(needed) if needed else 0,
                items_retrieved=dec_items,
                tokens_used=dec_tokens,
            ),
            sentence_level=LevelResult(
                found=list(sent_found),
                missed=list(needed - sent_found),
                coverage=len(sent_found) / len(needed) if needed else 0,
                items_retrieved=sent_items,
                tokens_used=sent_tokens,
            ),
        )

        print(f"  {topic_id}:", file=sys.stderr)
        print(
            f"    Decision: {len(dec_found)}/{len(needed)} found, "
            f"{dec_items} items, {dec_tokens} tokens",
            file=sys.stderr,
        )
        print(
            f"    Sentence: {len(sent_found)}/{len(needed)} found, "
            f"{sent_items} items, {sent_tokens} tokens",
            file=sys.stderr,
        )

        # Show what sentence-level actually returns vs decision-level
        if sent_retrieved:
            print("    Sentence content sample:", file=sys.stderr)
            for sid in sent_retrieved[:3]:
                sent_item: SentenceItem = sentences[sid]
                print(
                    f"      [{sent_item['parent']}_s{sent_item['index']}] {sent_item['content'][:80]}",
                    file=sys.stderr,
                )

    # Summary
    print(f"\n{'=' * 60}", file=sys.stderr)
    print(
        f"{'Topic':<18} {'Dec Cov':>8} {'Dec Tok':>8} {'Dec #':>5} "
        f"{'Sent Cov':>9} {'Sent Tok':>9} {'Sent #':>6}",
        file=sys.stderr,
    )
    print("-" * 70, file=sys.stderr)

    dec_total_found: int = 0
    sent_total_found: int = 0
    dec_total_tokens: int = 0
    sent_total_tokens: int = 0
    total_needed: int = 0

    for topic_id, r in results.items():
        needed_count: int = len(CRITICAL[topic_id]["needed"])
        total_needed += needed_count
        d: LevelResult = r["decision_level"]
        sl: LevelResult = r["sentence_level"]
        dec_total_found += len(d["found"])
        sent_total_found += len(sl["found"])
        dec_total_tokens += d["tokens_used"]
        sent_total_tokens += sl["tokens_used"]

        print(
            f"{topic_id:<18} {d['coverage']:>8.0%} {d['tokens_used']:>8} {d['items_retrieved']:>5} "
            f"{sl['coverage']:>9.0%} {sl['tokens_used']:>9} {sl['items_retrieved']:>6}",
            file=sys.stderr,
        )

    print(
        f"\n  Decision-level: {dec_total_found}/{total_needed} found, "
        f"avg {dec_total_tokens / 6:.0f} tokens/topic",
        file=sys.stderr,
    )
    print(
        f"  Sentence-level: {sent_total_found}/{total_needed} found, "
        f"avg {sent_total_tokens / 6:.0f} tokens/topic",
        file=sys.stderr,
    )
    print(
        f"  Token efficiency: sentence uses "
        f"{sent_total_tokens / max(dec_total_tokens, 1):.0%} of decision's budget",
        file=sys.stderr,
    )

    # The key question: does sentence-level give ENOUGH context?
    print(
        "\n  QUALITATIVE: Does sentence-level retrieval provide enough context?",
        file=sys.stderr,
    )
    print(
        f"  Decision-level returns {dec_total_found} decisions with full rationale.",
        file=sys.stderr,
    )
    sent_total_items: int = sum(
        r["sentence_level"]["items_retrieved"] for r in results.values()
    )
    print(
        f"  Sentence-level returns {sent_total_items} "
        f"individual sentences -- more items, less context per item.",
        file=sys.stderr,
    )
    print(
        "  The question: can the agent act on isolated sentences, or does it need",
        file=sys.stderr,
    )
    print(
        "  the surrounding rationale? This requires qualitative inspection.",
        file=sys.stderr,
    )

    Path("experiments/exp29_results.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
