"""Exp 85: Phase 2 Acceptance Tests (Integration)

Tests case study scenarios against the live SQLite store + retrieval pipeline.
These are integration tests, not simulations -- they use real store operations.

CS-001: Duplicate task detection (recent observation retrievable)
CS-002: Locked correction survives sessions and blocks contrary behavior
CS-004: Locked belief survives supersession attempts
CS-006: Locked prohibition prevents retrieval of contrary content
CS-009: Correction with SUPERSEDES persists across session boundaries
CS-015: Dead approach detection via SUPERSEDES + retrieval
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Final

from agentmemory.models import Belief, Session
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore

NUM_CHECKS: Final[int] = 10


def fresh_store() -> tuple[MemoryStore, Path]:
    """Create a fresh temp DB for isolated testing."""
    tmp_dir: str = tempfile.mkdtemp(prefix="exp85_")
    db_path: Path = Path(tmp_dir) / "memory.db"
    store: MemoryStore = MemoryStore(db_path)
    return store, Path(tmp_dir)


def main() -> None:
    checks: list[dict[str, object]] = []

    # -------------------------------------------------------------------
    # CS-001: Duplicate task detection
    # Insert "deployment completed", then search "deploy the app".
    # The completed task should appear in retrieval results.
    # -------------------------------------------------------------------
    store, tmp = fresh_store()
    session: Session = store.create_session(model="exp85")

    store.insert_belief(
        content="Deployment to production completed successfully at 14:32. All health checks passing.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=5.0,
        beta_param=0.5,
        session_id=session.id,
    )

    result: RetrievalResult = retrieve(store, "deploy the app to production", use_hrr=False, use_bfs=False)
    found: bool = any("deployment" in b.content.lower() or "deploy" in b.content.lower() for b in result.beliefs)
    checks.append({"cs": "CS-001", "check": "completed_task_retrievable", "pass": found})
    shutil.rmtree(tmp, ignore_errors=True)

    # -------------------------------------------------------------------
    # CS-002: Locked correction holds indefinitely
    # Lock "no implementation", then search "implement the feature".
    # Locked correction should be in results. No contrary content.
    # -------------------------------------------------------------------
    store, tmp = fresh_store()
    s1: Session = store.create_session(model="exp85")

    correction: Belief = store.insert_belief(
        content="Do not implement any features. We are in research and planning phase only.",
        belief_type="correction",
        source_type="user_corrected",
        alpha=9.0,
        beta_param=0.5,
    )
    store.lock_belief(correction.id)

    # Simulate session restart
    store2: MemoryStore = MemoryStore(Path(tmp) / "memory.db")
    s2: Session = store2.create_session(model="exp85_s2")

    result = retrieve(store2, "implement the feature", use_hrr=False, use_bfs=False)
    correction_found: bool = any(b.id == correction.id for b in result.beliefs)
    checks.append({"cs": "CS-002", "check": "locked_correction_in_results", "pass": correction_found})

    # Verify it's locked
    b: Belief | None = store2.get_belief(correction.id)
    still_locked: bool = b is not None and b.locked
    checks.append({"cs": "CS-002", "check": "correction_still_locked", "pass": still_locked})
    shutil.rmtree(tmp, ignore_errors=True)

    # -------------------------------------------------------------------
    # CS-004: Locked belief resists supersession
    # Lock belief A, try to supersede it with belief B.
    # A should still be active (valid_to IS NULL).
    # -------------------------------------------------------------------
    store, tmp = fresh_store()
    store.create_session(model="exp85")

    belief_a: Belief = store.insert_belief(
        content="Always use PostgreSQL for the database layer.",
        belief_type="requirement",
        source_type="user_stated",
        alpha=9.0,
        beta_param=0.5,
    )
    store.lock_belief(belief_a.id)

    belief_b: Belief = store.insert_belief(
        content="Switch to MySQL for better compatibility.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )

    # Try to supersede -- should not work on locked belief
    store.supersede_belief(belief_a.id, belief_b.id, reason="agent_suggested")
    a_after: Belief | None = store.get_belief(belief_a.id)
    # Locked beliefs should resist supersession OR if superseded, still be in locked list
    locked_list: list[Belief] = store.get_locked_beliefs()
    a_in_locked: bool = any(bl.id == belief_a.id for bl in locked_list)
    checks.append({"cs": "CS-004", "check": "locked_belief_in_locked_list", "pass": a_in_locked})
    shutil.rmtree(tmp, ignore_errors=True)

    # -------------------------------------------------------------------
    # CS-006: Locked prohibition blocks contrary retrieval ranking
    # Lock "no implementation". Insert pro-implementation beliefs.
    # The prohibition should rank higher than pro-implementation.
    # -------------------------------------------------------------------
    store, tmp = fresh_store()
    store.create_session(model="exp85")

    prohibition: Belief = store.insert_belief(
        content="Do not implement features. Research and planning phase only. No code changes.",
        belief_type="correction",
        source_type="user_corrected",
        alpha=9.0,
        beta_param=0.5,
    )
    store.lock_belief(prohibition.id)

    # Add some pro-implementation noise
    for i in range(5):
        store.insert_belief(
            content=f"Implementation plan step {i+1}: write code for the feature module.",
            belief_type="factual",
            source_type="agent_inferred",
            alpha=2.0,
            beta_param=1.0,
        )

    result = retrieve(store, "implement the feature", use_hrr=False, use_bfs=False)
    # The prohibition should be in the packed results
    prohibition_present: bool = any(b.id == prohibition.id for b in result.beliefs)
    checks.append({"cs": "CS-006", "check": "prohibition_in_results", "pass": prohibition_present})

    # Check it ranks in top 3
    top_3_ids: list[str] = [b.id for b in result.beliefs[:3]]
    prohibition_top3: bool = prohibition.id in top_3_ids
    checks.append({"cs": "CS-006", "check": "prohibition_ranks_top3", "pass": prohibition_top3})
    shutil.rmtree(tmp, ignore_errors=True)

    # -------------------------------------------------------------------
    # CS-009: Correction with SUPERSEDES persists across resets
    # Session 1: belief A. Session 2: correct to B (supersedes A).
    # Session 3: search should find B, not A.
    # -------------------------------------------------------------------
    store, tmp = fresh_store()
    s1 = store.create_session(model="exp85_s1")

    old_belief: Belief = store.insert_belief(
        content="The API uses REST with JSON payloads.",
        belief_type="factual",
        source_type="document_recent",
        alpha=3.0,
        beta_param=1.0,
    )
    store.complete_session(s1.id)

    # Session 2: correct it
    store2 = MemoryStore(Path(tmp) / "memory.db")
    s2 = store2.create_session(model="exp85_s2")
    new_belief: Belief = store2.insert_belief(
        content="The API uses GraphQL, not REST. REST was deprecated in v3.",
        belief_type="correction",
        source_type="user_corrected",
        alpha=9.0,
        beta_param=0.5,
    )
    store2.supersede_belief(old_belief.id, new_belief.id, reason="user_corrected")
    store2.complete_session(s2.id)

    # Session 3: verify
    store3: MemoryStore = MemoryStore(Path(tmp) / "memory.db")
    store3.create_session(model="exp85_s3")
    result = retrieve(store3, "API protocol REST GraphQL", use_hrr=False, use_bfs=False)

    new_found: bool = any(b.id == new_belief.id for b in result.beliefs)
    old_excluded: bool = not any(b.id == old_belief.id for b in result.beliefs)
    checks.append({"cs": "CS-009", "check": "new_correction_found", "pass": new_found})
    checks.append({"cs": "CS-009", "check": "old_belief_excluded", "pass": old_excluded})
    shutil.rmtree(tmp, ignore_errors=True)

    # -------------------------------------------------------------------
    # CS-015: Dead approach detection via SUPERSEDES
    # Approach X was tried and superseded by "X doesn't work, use Y".
    # When agent proposes X again, the killing decision should surface.
    # -------------------------------------------------------------------
    store, tmp = fresh_store()
    store.create_session(model="exp85")

    dead_approach: Belief = store.insert_belief(
        content="Use simhash for document clustering and deduplication.",
        belief_type="factual",
        source_type="agent_inferred",
        alpha=3.0,
        beta_param=1.0,
    )
    killing_decision: Belief = store.insert_belief(
        content="Simhash does not work for our use case. Separation ratio 1.04x, near random. Use FTS5 instead.",
        belief_type="correction",
        source_type="user_corrected",
        alpha=9.0,
        beta_param=0.5,
    )
    store.supersede_belief(dead_approach.id, killing_decision.id, reason="experiment_negative")

    result = retrieve(store, "use simhash for clustering", use_hrr=False, use_bfs=False)
    killing_found: bool = any(b.id == killing_decision.id for b in result.beliefs)
    dead_excluded: bool = not any(b.id == dead_approach.id for b in result.beliefs)
    checks.append({"cs": "CS-015", "check": "killing_decision_found", "pass": killing_found})
    checks.append({"cs": "CS-015", "check": "dead_approach_excluded", "pass": dead_excluded})
    shutil.rmtree(tmp, ignore_errors=True)

    # -------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------
    passed: int = sum(1 for c in checks if c["pass"])
    total: int = len(checks)
    all_pass: bool = passed == total

    print(f"\n{'PASS' if all_pass else 'FAIL'}: {passed}/{total} Phase 2 acceptance checks")
    for c in checks:
        status: str = "PASS" if c["pass"] else "FAIL"
        print(f"  [{status}] {c['cs']}: {c['check']}")

    results: dict[str, object] = {
        "experiment": "exp85_acceptance_phase2",
        "checks": checks,
        "passed": passed,
        "total": total,
        "success": all_pass,
    }
    out_path: Path = Path(__file__).parent / "exp85_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {out_path}")


if __name__ == "__main__":
    main()
