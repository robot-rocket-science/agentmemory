from __future__ import annotations

"""
Experiment 9: Information-Theoretic Retrieval Improvements

Tests whether MinHash, query expansion, or stemming improve retrieval
over plain FTS5 on the project-a data.

Baseline: FTS5 with OR queries (from Exp 4)
Ground truth: 6 critical belief topics with known needed decisions

No LLM calls. All methods are zero-LLM.
"""

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any
from collections.abc import Callable

from datasketch import MinHash, MinHashLSH  # type: ignore[import-untyped]

ALPHA_SEEK_DB = Path(
    "/home/user/projects/.gsd/workflows/spikes/"
    "260406-1-associative-memory-for-gsd-please-explor/"
    "sandbox/project-a.db"
)

CRITICAL_BELIEFS: dict[str, dict[str, list[str]]] = {
    "dispatch_gate": {
        "queries": [
            "dispatch gate deploy protocol",
            "follow deploy gate verification",
            "dispatch runbook GCP",
        ],
        "needed": ["D089", "D106", "D137"],
    },
    "calls_puts": {
        "queries": [
            "calls puts equal citizens",
            "put call strategy direction",
            "options both directions",
        ],
        "needed": ["D073", "D096", "D100"],
    },
    "capital_5k": {
        "queries": [
            "starting capital bankroll",
            "initial investment amount",
            "how much money USD",
        ],
        "needed": ["D099"],
    },
    "agent_behavior": {
        "queries": [
            "agent behavior instructions",
            "dont elaborate pontificate",
            "execute precisely return control",
        ],
        "needed": ["D157", "D188"],
    },
    "strict_typing": {
        "queries": [
            "typing pyright strict",
            "type annotations python",
            "static type checking",
        ],
        "needed": ["D071", "D113"],
    },
    "gcp_primary": {
        "queries": [
            "GCP primary compute platform",
            "server-a overflow only",
            "cloud compute infrastructure",
        ],
        "needed": ["D078", "D120"],
    },
}


# --- Load Data ---


def load_nodes() -> dict[str, dict[str, str | int]]:
    db = sqlite3.connect(str(ALPHA_SEEK_DB))
    nodes: dict[str, dict[str, str | int]] = {}
    for row in db.execute(
        "SELECT id, content FROM mem_nodes WHERE superseded_by IS NULL"
    ):
        node_id: str = str(row[0])
        content: str = str(row[1])
        nodes[node_id] = {
            "id": node_id,
            "content": content,
            "tokens": len(content) // 4,
        }
    db.close()
    return nodes


# --- Method 1: FTS5 Baseline (from Exp 4) ---


def build_fts(nodes: dict[str, dict[str, str | int]]) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE fts USING fts5(id, content, tokenize='porter')")
    for nid, node in nodes.items():
        db.execute("INSERT INTO fts VALUES (?, ?)", (nid, node["content"]))
    db.commit()
    return db


def search_fts(query: str, fts_db: sqlite3.Connection, top_k: int = 30) -> list[str]:
    terms: list[str] = [t.strip() for t in query.split() if len(t.strip()) > 2]
    if not terms:
        return []
    fts_query = " OR ".join(terms)
    try:
        results = fts_db.execute(
            "SELECT id FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT ?",
            (fts_query, top_k),
        ).fetchall()
        return [str(r[0]) for r in results]
    except Exception:
        return []


# --- Method 2: FTS5 + Stemming/Synonym Expansion ---

SYNONYMS: dict[str, list[str]] = {
    "capital": ["bankroll", "money", "funds", "investment", "budget", "USD", "dollars"],
    "deploy": ["dispatch", "ship", "release", "push", "launch"],
    "gate": ["check", "verification", "protocol", "guard", "prerequisite"],
    "typing": ["typed", "types", "type", "pyright", "annotations", "strict"],
    "compute": ["platform", "infrastructure", "server", "machine", "VM", "instance"],
    "primary": ["main", "default", "preferred", "first"],
    "overflow": ["backup", "fallback", "secondary", "alternative"],
    "behavior": ["conduct", "style", "manner", "response", "interaction"],
    "elaborate": ["pontificate", "philosophize", "ramble", "verbose"],
    "calls": ["call", "rally", "bullish", "long"],
    "puts": ["put", "decline", "bearish", "short"],
    "equal": ["both", "same", "citizens", "included"],
}


def expand_query(query: str) -> str:
    """Expand query with synonyms."""
    terms: list[str] = query.lower().split()
    expanded: set[str] = set(terms)
    for term in terms:
        if term in SYNONYMS:
            expanded.update(SYNONYMS[term])
    return " OR ".join(t for t in expanded if len(t) > 2)


def search_fts_expanded(
    query: str, fts_db: sqlite3.Connection, top_k: int = 30
) -> list[str]:
    expanded = expand_query(query)
    try:
        results = fts_db.execute(
            "SELECT id FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT ?",
            (expanded, top_k),
        ).fetchall()
        return [str(r[0]) for r in results]
    except Exception:
        return []


# --- Method 3: MinHash LSH ---


def tokenize_for_minhash(text: str) -> set[str]:
    """3-gram shingles for MinHash."""
    text = text.lower()
    words: list[str] = re.findall(r"[a-z0-9]+", text)
    shingles: set[str] = set()
    for i in range(len(words) - 2):
        shingles.add(f"{words[i]}_{words[i + 1]}_{words[i + 2]}")
    # Also add individual words
    shingles.update(words)
    return shingles


def build_minhash_index(
    nodes: dict[str, dict[str, str | int]], num_perm: int = 128
) -> tuple[MinHashLSH, dict[str, MinHash]]:
    lsh: MinHashLSH = MinHashLSH(threshold=0.1, num_perm=num_perm)
    minhashes: dict[str, MinHash] = {}

    for nid, node in nodes.items():
        m: MinHash = MinHash(num_perm=num_perm)
        content_val: str = str(node["content"])
        for s in tokenize_for_minhash(content_val):
            m.update(s.encode("utf8"))  # type: ignore[no-untyped-call]
        minhashes[nid] = m
        try:
            lsh.insert(nid, m)
        except ValueError:
            pass  # duplicate key

    return lsh, minhashes


def search_minhash(query: str, lsh: MinHashLSH, num_perm: int = 128) -> list[str]:
    m: MinHash = MinHash(num_perm=num_perm)
    for s in tokenize_for_minhash(query):
        m.update(s.encode("utf8"))  # type: ignore[no-untyped-call]
    result: list[Any] = lsh.query(m)  # type: ignore[no-untyped-call]
    return [str(r) for r in result]


# --- Method 4: Combined (FTS expanded + MinHash) ---


def search_combined(
    query: str, fts_db: sqlite3.Connection, lsh: MinHashLSH, top_k: int = 30
) -> list[str]:
    fts_results: set[str] = set(search_fts_expanded(query, fts_db, top_k))
    minhash_results: set[str] = set(search_minhash(query, lsh))
    combined: set[str] = fts_results | minhash_results
    return list(combined)[:top_k]


# --- Evaluation ---


def evaluate_method(
    method_name: str,
    search_fn: Callable[[str], list[str]],
    nodes: dict[str, dict[str, str | int]],
) -> dict[str, Any]:
    """Evaluate a retrieval method against all critical belief topics."""
    total_needed = 0
    total_found = 0
    per_topic: dict[str, dict[str, Any]] = {}

    for topic_id, topic in CRITICAL_BELIEFS.items():
        needed: set[str] = set(topic["needed"])
        total_needed += len(needed)

        # Try all query variants for this topic
        all_retrieved: set[str] = set()
        for query in topic["queries"]:
            results = search_fn(query)
            all_retrieved.update(results)

        found: set[str] = needed & all_retrieved
        total_found += len(found)

        per_topic[topic_id] = {
            "needed": list(needed),
            "found": list(found),
            "missed": list(needed - found),
            "coverage": len(found) / len(needed) if needed else 0,
            "total_retrieved": len(all_retrieved),
        }

    return {
        "method": method_name,
        "overall_coverage": round(total_found / total_needed, 4) if total_needed else 0,
        "total_needed": total_needed,
        "total_found": total_found,
        "per_topic": per_topic,
    }


def main() -> None:
    print("=" * 60, file=sys.stderr)
    print("Experiment 9: Retrieval Improvement Comparison", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    nodes = load_nodes()
    print(f"  Loaded {len(nodes)} nodes", file=sys.stderr)

    # Build indices
    fts_db = build_fts(nodes)
    print("  Built FTS5 index", file=sys.stderr)

    lsh, _minhashes = build_minhash_index(nodes)
    print("  Built MinHash LSH index", file=sys.stderr)

    # Evaluate each method
    methods: dict[str, Callable[[str], list[str]]] = {
        "fts_baseline": lambda q: search_fts(q, fts_db),
        "fts_expanded": lambda q: search_fts_expanded(q, fts_db),
        "minhash_only": lambda q: search_minhash(q, lsh),
        "fts_expanded_plus_minhash": lambda q: search_combined(q, fts_db, lsh),
    }

    results: dict[str, dict[str, Any]] = {}
    for name, fn in methods.items():
        result = evaluate_method(name, fn, nodes)
        results[name] = result

        print(
            f"\n  {name}: {result['overall_coverage']:.0%} coverage "
            f"({result['total_found']}/{result['total_needed']})",
            file=sys.stderr,
        )
        topic_results: dict[str, Any] = result["per_topic"]
        for topic, tr in topic_results.items():
            status = "OK" if tr["coverage"] == 1.0 else f"MISS {tr['missed']}"
            print(
                f"    {topic}: {tr['coverage']:.0%} (retrieved {tr['total_retrieved']}) [{status}]",
                file=sys.stderr,
            )

    # Summary comparison
    print(f"\n{'=' * 60}", file=sys.stderr)
    print("COMPARISON", file=sys.stderr)
    print(f"{'=' * 60}", file=sys.stderr)
    print(
        f"{'Method':<30} {'Coverage':>10} {'Found':>6}/{results['fts_baseline']['total_needed']}",
        file=sys.stderr,
    )
    print("-" * 50, file=sys.stderr)
    for name, r in results.items():
        print(
            f"{name:<30} {r['overall_coverage']:>10.0%} {r['total_found']:>6}",
            file=sys.stderr,
        )

    # What did expansion/minhash find that baseline missed?
    baseline_found: set[str] = set()
    baseline_per_topic: dict[str, Any] = results["fts_baseline"]["per_topic"]
    for topic_data in baseline_per_topic.values():
        found_list: list[str] = topic_data["found"]
        baseline_found.update(found_list)

    for method in ["fts_expanded", "minhash_only", "fts_expanded_plus_minhash"]:
        method_found: set[str] = set()
        method_per_topic: dict[str, Any] = results[method]["per_topic"]
        for topic_data in method_per_topic.values():
            found_list = topic_data["found"]
            method_found.update(found_list)
        new_finds: set[str] = method_found - baseline_found
        if new_finds:
            print(
                f"\n  {method} found that baseline missed: {new_finds}", file=sys.stderr
            )

    Path("experiments/exp9_results.json").write_text(json.dumps(results, indent=2))
    print("\nOutput: experiments/exp9_results.json", file=sys.stderr)


if __name__ == "__main__":
    main()
