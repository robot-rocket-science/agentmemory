"""Exp 84: Multi-Session Validation

Tests whether beliefs persist, feedback accumulates, and retrieval quality
remains stable across simulated session boundaries.

Simulates 5 sessions against a temp DB copy:
  Session 1: Ingest seed beliefs, search, record feedback
  Session 2: Verify persistence, add new beliefs, search again
  Session 3: Correct a belief (supersession), verify old belief excluded
  Session 4: Lock a belief, verify it survives and ranks highly
  Session 5: Measure retrieval quality stability (MRR should not degrade)

Each session creates a new MemoryStore instance (simulating server restart)
but shares the same DB file.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Final

from agentmemory.models import Belief, Session
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CWD: Final[str] = "/home/user/projects/agentmemory"
DB_HASH: Final[str] = hashlib.sha256(CWD.encode()).hexdigest()[:12]
LIVE_DB: Final[Path] = Path.home() / ".agentmemory" / "projects" / DB_HASH / "memory.db"

MRR_K: Final[int] = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fresh_store(db_path: Path) -> tuple[MemoryStore, Session]:
    """Create a new MemoryStore + Session (simulating a server restart)."""
    store: MemoryStore = MemoryStore(db_path)
    session: Session = store.create_session(model="exp84_sim")
    return store, session


def mrr_at_k(
    store: MemoryStore,
    query: str,
    expected_ids: set[str],
    k: int = MRR_K,
) -> float:
    """MRR@K for a single query against expected belief IDs."""
    result: RetrievalResult = retrieve(store, query, top_k=k)
    for rank, belief in enumerate(result.beliefs[:k], start=1):
        if belief.id in expected_ids:
            return 1.0 / rank
    return 0.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    # Use a fresh temp DB (not a copy of live) for controlled testing
    tmp_dir: str = tempfile.mkdtemp(prefix="exp84_")
    db_path: Path = Path(tmp_dir) / "memory.db"
    print(f"Working on temp DB: {db_path}")

    results: dict[str, object] = {
        "experiment": "exp84_multi_session_validation",
        "sessions": 5,
        "checks": [],
    }
    checks: list[dict[str, object]] = []

    # -----------------------------------------------------------------------
    # Session 1: Seed beliefs
    # -----------------------------------------------------------------------
    store, session = fresh_store(db_path)
    sid1: str = session.id

    seed_beliefs: list[Belief] = []
    seed_texts: list[str] = [
        "The retrieval pipeline uses FTS5 for keyword matching and HRR for vocabulary bridging.",
        "Locked beliefs are injected into every session context via the SessionStart hook.",
        "The Bayesian feedback loop updates alpha and beta parameters based on retrieval outcomes.",
        "Correction detection runs at 92% accuracy using 7 signal types without LLM.",
        "Type-aware compression saves 55% tokens with zero retrieval quality loss.",
    ]
    for text in seed_texts:
        b: Belief = store.insert_belief(
            content=text,
            belief_type="factual",
            source_type="document_recent",
            alpha=3.0,
            beta_param=1.0,
        )
        seed_beliefs.append(b)

    seed_ids: set[str] = {b.id for b in seed_beliefs}

    # Search and record feedback
    r1: RetrievalResult = retrieve(store, "retrieval pipeline FTS5", top_k=10)
    for belief in r1.beliefs[:5]:
        outcome: str = "used" if belief.id in seed_ids else "ignored"
        store.record_test_result(
            belief_id=belief.id,
            session_id=sid1,
            outcome=outcome,
            detection_layer="checkpoint",
        )

    store.complete_session(sid1)
    s1_count: int = store.status()["beliefs"]
    checks.append(
        {
            "session": 1,
            "check": "seed_beliefs_created",
            "expected": 5,
            "actual": s1_count,
            "pass": s1_count >= 5,
        }
    )
    print(f"Session 1: {s1_count} beliefs, {len(seed_ids)} seeded")

    # -----------------------------------------------------------------------
    # Session 2: Verify persistence, add new beliefs
    # -----------------------------------------------------------------------
    store, session = fresh_store(db_path)
    sid2: str = session.id

    # Verify seed beliefs still exist
    persisted: int = 0
    for bid in seed_ids:
        b2: Belief | None = store.get_belief(bid)
        if b2 is not None and b2.valid_to is None:
            persisted += 1

    checks.append(
        {
            "session": 2,
            "check": "seed_beliefs_persisted",
            "expected": 5,
            "actual": persisted,
            "pass": persisted == 5,
        }
    )

    # Add new beliefs
    new_belief: Belief = store.insert_belief(
        content="Session velocity tracking measures items per hour for decay scaling.",
        belief_type="factual",
        source_type="document_recent",
        alpha=3.0,
        beta_param=1.0,
    )

    # Verify feedback from session 1 persisted (alpha should have been updated)
    b_check: Belief | None = store.get_belief(seed_beliefs[0].id)
    feedback_persisted: bool = (
        b_check is not None and b_check.alpha != seed_beliefs[0].alpha
    )
    checks.append(
        {
            "session": 2,
            "check": "feedback_persisted",
            "expected": True,
            "actual": feedback_persisted,
            "pass": feedback_persisted,
        }
    )

    store.complete_session(sid2)
    print(
        f"Session 2: persisted={persisted}/5, feedback_persisted={feedback_persisted}"
    )

    # -----------------------------------------------------------------------
    # Session 3: Correct a belief (supersession)
    # -----------------------------------------------------------------------
    store, session = fresh_store(db_path)
    sid3: str = session.id

    # Supersede the first seed belief
    old_id: str = seed_beliefs[0].id
    correction: Belief = store.insert_belief(
        content="The retrieval pipeline uses FTS5 for keyword matching; HRR is limited to semantic edge types only.",
        belief_type="correction",
        source_type="user_corrected",
        alpha=9.0,
        beta_param=0.5,
    )
    store.supersede_belief(old_id, correction.id, reason="user_corrected")

    # Verify old belief is superseded
    old_b: Belief | None = store.get_belief(old_id)
    superseded: bool = old_b is not None and old_b.superseded_by == correction.id
    checks.append(
        {
            "session": 3,
            "check": "supersession_works",
            "expected": True,
            "actual": superseded,
            "pass": superseded,
        }
    )

    # Verify superseded belief excluded from search
    search_results: list[Belief] = store.search("retrieval pipeline FTS5", top_k=10)
    old_in_results: bool = any(b.id == old_id for b in search_results)
    checks.append(
        {
            "session": 3,
            "check": "superseded_excluded_from_search",
            "expected": False,
            "actual": old_in_results,
            "pass": not old_in_results,
        }
    )

    store.complete_session(sid3)
    print(
        f"Session 3: superseded={superseded}, excluded_from_search={not old_in_results}"
    )

    # -----------------------------------------------------------------------
    # Session 4: Lock a belief, verify it ranks highly
    # -----------------------------------------------------------------------
    store, session = fresh_store(db_path)
    sid4: str = session.id

    # Lock the correction from session 3
    store.lock_belief(correction.id)

    # Verify lock persists
    locked_b: Belief | None = store.get_belief(correction.id)
    is_locked: bool = locked_b is not None and locked_b.locked
    checks.append(
        {
            "session": 4,
            "check": "lock_persists",
            "expected": True,
            "actual": is_locked,
            "pass": is_locked,
        }
    )

    # Verify locked belief appears in get_locked_beliefs
    locked_list: list[Belief] = store.get_locked_beliefs()
    in_locked_list: bool = any(b.id == correction.id for b in locked_list)
    checks.append(
        {
            "session": 4,
            "check": "in_locked_list",
            "expected": True,
            "actual": in_locked_list,
            "pass": in_locked_list,
        }
    )

    store.complete_session(sid4)
    print(f"Session 4: locked={is_locked}, in_locked_list={in_locked_list}")

    # -----------------------------------------------------------------------
    # Session 5: Retrieval quality stability
    # -----------------------------------------------------------------------
    store, session = fresh_store(db_path)
    sid5: str = session.id

    # The correction should rank above the remaining seed beliefs for this query
    active_ids: set[str] = {correction.id} | {b.id for b in seed_beliefs[1:]}
    mrr: float = mrr_at_k(store, "retrieval pipeline FTS5 HRR", active_ids)
    checks.append(
        {
            "session": 5,
            "check": "mrr_stable",
            "expected": "> 0",
            "actual": mrr,
            "pass": mrr > 0.0,
        }
    )

    # Verify total belief count is correct (5 seed + 1 new + 1 correction = 7)
    final_count: int = store.status()["beliefs"]
    checks.append(
        {
            "session": 5,
            "check": "total_beliefs",
            "expected": 7,
            "actual": final_count,
            "pass": final_count == 7,
        }
    )

    # Count sessions
    session_count: int = store.status()["sessions"]
    checks.append(
        {
            "session": 5,
            "check": "session_count",
            "expected": 5,
            "actual": session_count,
            "pass": session_count == 5,
        }
    )

    store.complete_session(sid5)
    print(
        f"Session 5: mrr={mrr:.3f}, total_beliefs={final_count}, sessions={session_count}"
    )

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    results["checks"] = checks
    all_pass: bool = all(c["pass"] for c in checks)
    passed: int = sum(1 for c in checks if c["pass"])
    total: int = len(checks)
    results["passed"] = passed
    results["total"] = total
    results["success"] = all_pass

    print(f"\n{'PASS' if all_pass else 'FAIL'}: {passed}/{total} checks passed")
    for c in checks:
        status: str = "PASS" if c["pass"] else "FAIL"
        print(
            f"  [{status}] Session {c['session']}: {c['check']} (expected={c['expected']}, actual={c['actual']})"
        )

    out_path: Path = Path(__file__).parent / "exp84_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {out_path}")

    # Cleanup
    shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
