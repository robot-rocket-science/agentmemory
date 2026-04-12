"""Exp 69: Recency Boost for New Belief Surfacing

Tests whether recency_boost() helps newly inserted beliefs penetrate the
existing top-10 retrieval results.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest.mock
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final

from agentmemory.models import Belief
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.scoring import recency_boost, score_belief
from agentmemory.store import MemoryStore

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CWD: Final[str] = "/Users/thelorax/projects/agentmemory"
DB_HASH: Final[str] = hashlib.sha256(CWD.encode()).hexdigest()[:12]
LIVE_DB: Final[Path] = Path.home() / ".agentmemory" / "projects" / DB_HASH / "memory.db"

TOP_K: Final[int] = 30
MRR_K: Final[int] = 10

# New beliefs to insert: (topic_query, content)
NEW_BELIEFS: Final[list[tuple[str, str]]] = [
    ("locked beliefs constraints", "All locked beliefs must be obeyed without exception in every session."),
    ("locked beliefs constraints", "Locked corrections override all other belief types during retrieval."),
    ("FTS5 retrieval search", "FTS5 uses porter stemming tokenizer for belief content indexing."),
    ("FTS5 retrieval search", "BM25 ranking is the primary FTS5 scoring mechanism for search."),
    ("correction detection pipeline", "Corrections are detected via explicit user statements and implicit contradictions."),
    ("correction detection pipeline", "Detected corrections are automatically locked and assigned high alpha priors."),
    ("belief type priors weights", "Requirement beliefs have the highest type weight at 2.5."),
    ("belief type priors weights", "Correction beliefs have a type weight of 2.0 in the scoring pipeline."),
    ("HRR vocabulary bridge", "HRR vocabulary bridge finds structurally connected beliefs that FTS5 misses."),
    ("HRR vocabulary bridge", "HRR uses holographic reduced representations with circular convolution."),
    ("scoring pipeline Thompson sampling", "Thompson sampling draws from Beta(alpha, beta_param) for ranking."),
    ("scoring pipeline Thompson sampling", "Score combines Thompson sample, decay factor, and lock boost."),
    ("recency boost new beliefs", "Recency boost gives 2x multiplier to brand-new beliefs decaying over 24 hours."),
    ("recency boost new beliefs", "Recency boost uses exponential decay with configurable half-life."),
    ("token budget compression", "Token budget defaults to 2000 tokens for retrieval context injection."),
    ("token budget compression", "Belief compression strips metadata and truncates long content."),
    ("session tracking tokens", "Sessions track retrieval tokens, classification tokens, and feedback counts."),
    ("session tracking tokens", "Session token accounting enables cost amortization analysis."),
    ("edge graph triples", "Graph edges encode CITES, RELATES_TO, SUPERSEDES, CONTRADICTS, SUPPORTS relationships."),
    ("edge graph triples", "Edge triples feed the HRR graph for vocabulary bridge expansion."),
]

QUERIES: Final[list[str]] = sorted(set(topic for topic, _ in NEW_BELIEFS))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future_iso(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def insert_new_beliefs(db_path: Path, now_iso: str) -> list[str]:
    """Insert new correction beliefs into the DB. Returns list of new IDs."""
    conn: sqlite3.Connection = sqlite3.connect(str(db_path))
    new_ids: list[str] = []
    for _topic, content in NEW_BELIEFS:
        bid: str = uuid.uuid4().hex[:12]
        chash: str = hashlib.sha256(content.encode()).hexdigest()[:12]
        conn.execute(
            """INSERT INTO beliefs
               (id, content_hash, content, belief_type, alpha, beta_param,
                source_type, locked, created_at, updated_at)
               VALUES (?, ?, ?, 'correction', 2.0, 0.5,
                       'user_corrected', 0, ?, ?)""",
            (bid, chash, content, now_iso, now_iso),
        )
        # Also add to FTS5 search index
        conn.execute(
            "INSERT INTO search_index (id, content, type) VALUES (?, ?, 'belief')",
            (bid, content),
        )
        new_ids.append(bid)
    conn.commit()
    conn.close()
    return new_ids


def score_belief_with_recency(
    belief: Belief, query: str, current_time_iso: str
) -> float:
    """score_belief wrapper that applies recency_boost as a multiplier."""
    base: float = score_belief(belief, query, current_time_iso)
    boost: float = recency_boost(belief, current_time_iso, half_life_hours=24.0)
    return base * boost


def find_new_in_top_k(
    store: MemoryStore,
    queries: list[str],
    new_ids: set[str],
    k: int,
) -> dict[str, list[str]]:
    """For each query, return list of new belief IDs found in top-k."""
    results: dict[str, list[str]] = {}
    for q in queries:
        rr: RetrievalResult = retrieve(store, q, top_k=TOP_K)
        found: list[str] = [b.id for b in rr.beliefs[:k] if b.id in new_ids]
        results[q] = found
    return results


def find_new_with_recency(
    store: MemoryStore,
    queries: list[str],
    new_ids: set[str],
    k: int,
    time_iso: str,
) -> dict[str, list[str]]:
    """Retrieve with monkey-patched recency boost, return new IDs in top-k."""
    def patched_score(belief: Belief, query: str, current_time_iso: str) -> float:
        return score_belief_with_recency(belief, query, time_iso)

    with unittest.mock.patch("agentmemory.retrieval.score_belief", patched_score):
        results: dict[str, list[str]] = {}
        for q in queries:
            rr: RetrievalResult = retrieve(store, q, top_k=TOP_K)
            found: list[str] = [b.id for b in rr.beliefs[:k] if b.id in new_ids]
            results[q] = found
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not LIVE_DB.exists():
        print(f"ERROR: Live DB not found at {LIVE_DB}", file=sys.stderr)
        sys.exit(1)

    # Copy DB to temp
    tmp_dir: str = tempfile.mkdtemp(prefix="exp69_")
    tmp_db: Path = Path(tmp_dir) / "memory.db"
    shutil.copy2(LIVE_DB, tmp_db)
    for suffix in ["-wal", "-shm"]:
        wal: Path = LIVE_DB.with_suffix(LIVE_DB.suffix + suffix)
        if wal.exists():
            shutil.copy2(wal, tmp_db.with_suffix(tmp_db.suffix + suffix))
    print(f"Working on temp DB: {tmp_db}")

    now_iso: str = _now_iso()

    # Insert new beliefs
    new_ids_list: list[str] = insert_new_beliefs(tmp_db, now_iso)
    new_ids: set[str] = set(new_ids_list)
    print(f"Inserted {len(new_ids)} new beliefs")

    store: MemoryStore = MemoryStore(tmp_db)

    # Test 1: Without recency boost
    print("\nTest 1: Without recency boost...")
    without_boost: dict[str, list[str]] = find_new_in_top_k(
        store, QUERIES, new_ids, MRR_K
    )
    total_without: int = sum(len(v) for v in without_boost.values())
    print(f"  New beliefs in top-{MRR_K}: {total_without}")
    for q, found in without_boost.items():
        if found:
            print(f"    {q}: {len(found)} found")

    # Test 2: With recency boost (current time)
    print(f"\nTest 2: With recency boost (t=now)...")
    with_boost: dict[str, list[str]] = find_new_with_recency(
        store, QUERIES, new_ids, MRR_K, now_iso
    )
    total_with: int = sum(len(v) for v in with_boost.values())
    print(f"  New beliefs in top-{MRR_K}: {total_with}")
    for q, found in with_boost.items():
        if found:
            print(f"    {q}: {len(found)} found")

    # Test 3: With recency boost (t=now+48h) -- should decay
    future_iso: str = _future_iso(48.0)
    print(f"\nTest 3: With recency boost (t=now+48h)...")
    with_boost_48h: dict[str, list[str]] = find_new_with_recency(
        store, QUERIES, new_ids, MRR_K, future_iso
    )
    total_48h: int = sum(len(v) for v in with_boost_48h.values())
    print(f"  New beliefs in top-{MRR_K}: {total_48h}")

    # Compute recency_boost value at 48h for reference
    decay_at_48h: float = 1.0 + (0.5 ** (48.0 / 24.0))
    print(f"  Theoretical recency_boost at 48h: {decay_at_48h:.4f}")

    # Results
    success: bool = total_with > total_without
    output: dict[str, object] = {
        "experiment": "exp69_recency_boost",
        "new_beliefs_inserted": len(new_ids),
        "without_boost": {
            "total_in_top10": total_without,
            "per_query": {q: len(v) for q, v in without_boost.items()},
        },
        "with_boost_now": {
            "total_in_top10": total_with,
            "per_query": {q: len(v) for q, v in with_boost.items()},
        },
        "with_boost_48h": {
            "total_in_top10": total_48h,
            "per_query": {q: len(v) for q, v in with_boost_48h.items()},
            "theoretical_boost_value": decay_at_48h,
        },
        "success": success,
        "success_criterion": "New beliefs appear in top-10 with boost but not without",
        "boost_decays": total_48h < total_with,
    }

    out_path: Path = Path(__file__).parent / "exp69_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nWithout boost: {total_without} new beliefs in top-10")
    print(f"With boost:    {total_with} new beliefs in top-10")
    print(f"After 48h:     {total_48h} new beliefs in top-10")
    print(f"Success:       {success}")
    print(f"Results saved to: {out_path}")

    # Cleanup
    shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
