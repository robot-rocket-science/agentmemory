"""CS-027: Recurring Bug Re-Debugged From Scratch.

Pass criterion: Operational beliefs from session 1 persist and are retrievable
in session 2 when the same symptom is reported.
"""

from __future__ import annotations

from pathlib import Path

from agentmemory.models import (
    BELIEF_FACTUAL,
    BELIEF_PROCEDURAL,
    BSRC_AGENT_INFERRED,
    Belief,
)
from agentmemory.store import MemoryStore


def test_cs027_operational_belief_persists_across_sessions(
    tmp_path: Path,
) -> None:
    """An operational belief from session 1 is retrievable in session 2."""
    db_path: Path = tmp_path / "cross_session.db"

    # Session 1: store the migration result
    s1: MemoryStore = MemoryStore(db_path)
    s1.insert_belief(
        content=(
            "Migrated 22 paper trading agents from thelorax launchd to archon cronie. "
            "Crontab uses variable references. Dry-run passed in interactive shell."
        ),
        belief_type=BELIEF_PROCEDURAL,
        source_type=BSRC_AGENT_INFERRED,
    )
    s1.close()

    # Session 2: query the same symptom
    s2: MemoryStore = MemoryStore(db_path)
    results: list[Belief] = s2.search("paper trading agents not firing cron")
    s2.close()

    assert len(results) >= 1
    assert any("cronie" in r.content or "crontab" in r.content for r in results), (
        "Session 2 must find session 1's migration belief"
    )


def test_cs027_incomplete_fix_warning_retrievable(store: MemoryStore) -> None:
    """An incomplete-fix warning should be retrievable when the same topic is queried."""
    store.insert_belief(
        content=(
            "Tested cron migration in interactive shell only. "
            "Cronie does not expand shell variables in crontab environment definitions. "
            "Not tested in actual cron environment."
        ),
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
    )

    results: list[Belief] = store.search("cron job failing variable expansion")
    assert len(results) >= 1
    assert any("cron" in r.content.lower() for r in results)
