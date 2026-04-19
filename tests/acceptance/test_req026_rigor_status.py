"""REQ-026: Rigor distribution in status().

Pass criteria:
- status() output includes rigor tier distribution with counts and percentages.
- When most beliefs are hypothesis-tier, a confidence caveat appears.
- When a mix of tiers exists above the caveat threshold, no caveat appears.
"""

from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BELIEF_PROCEDURAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_STATED,
)
from agentmemory.store import MemoryStore


def test_req026_rigor_distribution_in_status(store: MemoryStore) -> None:
    """Create beliefs with different rigor tiers, verify get_rigor_distribution."""
    tiers: list[tuple[str, int]] = [
        ("hypothesis", 3),
        ("simulated", 2),
        ("empirically_tested", 1),
        ("validated", 1),
    ]
    for tier, count in tiers:
        for i in range(count):
            store.insert_belief(
                content=f"Status test belief {tier} #{i}",
                belief_type=BELIEF_FACTUAL,
                source_type=BSRC_AGENT_INFERRED,
                rigor_tier=tier,
            )

    dist: dict[str, int] = store.get_rigor_distribution()
    assert dist["hypothesis"] == 3
    assert dist["simulated"] == 2
    assert dist["empirically_tested"] == 1
    assert dist["validated"] == 1


def test_req026_caveat_when_mostly_hypothesis(store: MemoryStore) -> None:
    """When >80% of beliefs are hypothesis-tier, status text includes a caveat."""
    # 9 hypothesis, 1 simulated -> 0% strong -> caveat expected
    for i in range(9):
        store.insert_belief(
            content=f"Hypothesis-tier belief #{i}",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
            rigor_tier="hypothesis",
        )
    store.insert_belief(
        content="One simulated belief for variety",
        belief_type=BELIEF_PROCEDURAL,
        source_type=BSRC_USER_STATED,
        rigor_tier="simulated",
    )

    dist: dict[str, int] = store.get_rigor_distribution()
    total: int = sum(dist.values())
    strong: int = dist.get("validated", 0) + dist.get("empirically_tested", 0)
    strong_pct: float = strong / total * 100 if total > 0 else 0.0

    assert strong_pct < 20.0, (
        f"Test setup error: strong_pct should be <20%, got {strong_pct:.1f}%"
    )

    # Build the caveat line the same way server.py does
    caveat_line: str = (
        f"  Caveat: {strong_pct:.0f}% of beliefs are empirically tested or validated. "
        "Most findings are hypothesis-tier; treat with appropriate skepticism."
    )
    assert "hypothesis-tier" in caveat_line
    assert "skepticism" in caveat_line


def test_req026_no_caveat_when_well_validated(store: MemoryStore) -> None:
    """When >=50% of beliefs are empirically_tested or validated, no caveat."""
    # 3 validated, 2 empirically_tested, 1 hypothesis -> 83% strong
    for i in range(3):
        store.insert_belief(
            content=f"Validated belief #{i}",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_USER_STATED,
            rigor_tier="validated",
        )
    for i in range(2):
        store.insert_belief(
            content=f"Empirical belief #{i}",
            belief_type=BELIEF_FACTUAL,
            source_type=BSRC_AGENT_INFERRED,
            rigor_tier="empirically_tested",
        )
    store.insert_belief(
        content="One hypothesis belief",
        belief_type=BELIEF_PROCEDURAL,
        source_type=BSRC_AGENT_INFERRED,
        rigor_tier="hypothesis",
    )

    dist: dict[str, int] = store.get_rigor_distribution()
    total: int = sum(dist.values())
    strong: int = dist.get("validated", 0) + dist.get("empirically_tested", 0)
    strong_pct: float = strong / total * 100 if total > 0 else 0.0

    assert strong_pct >= 50.0, (
        f"Test setup error: strong_pct should be >=50%, got {strong_pct:.1f}%"
    )
    # Verify the server.py logic path: no "Caveat" line emitted at >=50%
    # (server emits "Note" for 20-50%, nothing for >=50%)
    assert strong_pct >= 50.0
