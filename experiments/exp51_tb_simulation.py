"""
Experiment 51: Triggered Belief Simulation Against Case Studies

Simulates the 15 triggered beliefs from Exp 44 against 5 real case study scenarios.
For each scenario: which TBs fire, what actions execute, would the failure be prevented?

This is a trace-based simulation, not a runtime test. We replay the event sequence
from each case study and check TB activation against the defined conditions.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any, TypeAlias


# ============================================================
# Triggered Belief definitions (from Exp 44)
# ============================================================

_CheckFn: TypeAlias = Callable[[dict[str, Any]], bool]


def _check_directives(s: dict[str, Any]) -> bool:
    """Check if any directive matches output."""
    directives: list[dict[str, Any]] = list(s.get("directives", []))
    return any(bool(d.get("matches_output", False)) for d in directives)


@dataclass
class TriggeredBelief:
    tb_id: str
    event: str
    condition: str
    action: str
    prevents: str
    priority: int  # 1=safety, 2=user corrections, 3=operational, 4=learned

    def check_condition(self, state: dict[str, Any]) -> bool:
        """Evaluate condition against current state."""
        checks: dict[str, _CheckFn] = {
            "C-01": lambda s: bool(s.get("state_docs_exist", False)),
            "C-03": lambda s: int(s.get("time_since_state_check", 0)) > int(s.get("state_check_threshold", 300)),
            "C-04": lambda s: len(list[Any](s.get("locked_beliefs", []))) > 0,
            "C-05": lambda s: s.get("task_id_in_instruction") is not None,
            "C-06": lambda s: _check_directives(s),
            "C-07": lambda s: bool(s.get("contradictions_in_results", False)),
            "C-08": lambda s: bool(s.get("output_asks_user", False)),
        }
        default_fn: _CheckFn = lambda s: False
        check_fn: _CheckFn = checks.get(self.condition, default_fn)
        return check_fn(state)


# The registry
TB_REGISTRY: list[TriggeredBelief] = [
    TriggeredBelief("TB-01", "PE-04", "C-08", "A-01", "CS-003", 3),
    TriggeredBelief("TB-02", "PE-01", "C-04", "A-02", "CS-006", 1),
    TriggeredBelief("TB-03", "PE-02", "C-06", "A-02", "CS-006", 1),
    TriggeredBelief("TB-04", "PE-03", "C-05", "A-06", "CS-020", 2),
    TriggeredBelief("TB-05", "PE-01", "C-01", "A-08", "CS-005", 2),
    TriggeredBelief("TB-06", "PE-05", "C-04", "A-02", "CS-004", 1),
    TriggeredBelief("TB-07", "ME-01", "always", "A-03", "general", 3),
    TriggeredBelief("TB-08", "ME-02", "always", "A-02", "CS-002", 1),
    TriggeredBelief("TB-09", "ME-04", "C-07", "A-07", "REQ-002", 2),
    TriggeredBelief("TB-10", "PE-04", "C-06", "A-04", "CS-006", 1),
    TriggeredBelief("TB-11", "PE-01", "C-03", "A-01", "general", 3),
    TriggeredBelief("TB-12", "PE-03", "C-01", "A-01", "CS-003", 3),
    TriggeredBelief("TB-13", "ME-05", "always", "A-05", "REQ-020", 4),
    TriggeredBelief("TB-14", "PE-04", "claims_validation", "A-08", "CS-005/007", 2),
    TriggeredBelief("TB-15", "ME-03", "belief_previously_cited", "A-03", "general", 4),
]

ACTION_DESCRIPTIONS: dict[str, str] = {
    "A-01": "Self-check: query state documents before proceeding",
    "A-02": "Re-inject directive/locked belief into context",
    "A-03": "Escalate to user with specific question",
    "A-04": "Block output and re-route",
    "A-05": "Log meta-cognitive event",
    "A-06": "Verify task ID against instruction",
    "A-07": "Surface contradiction with both sides",
    "A-08": "Run FOK check (verify rigor tier)",
}

ACTION_COSTS: dict[str, dict[str, int]] = {
    "A-01": {"tokens": 50, "latency_ms": 5},
    "A-02": {"tokens": 100, "latency_ms": 10},
    "A-03": {"tokens": 150, "latency_ms": 5},
    "A-04": {"tokens": 200, "latency_ms": 15},
    "A-05": {"tokens": 10, "latency_ms": 2},
    "A-06": {"tokens": 20, "latency_ms": 3},
    "A-07": {"tokens": 200, "latency_ms": 10},
    "A-08": {"tokens": 100, "latency_ms": 50},
}


# ============================================================
# Case study scenarios
# ============================================================

@dataclass
class Scenario:
    name: str
    case_study: str
    description: str
    events: list[str]  # sequence of events that occur
    state: dict[str, Any]  # system state when events fire
    failure_description: str
    expected_preventing_tbs: list[str]


SCENARIOS: list[Scenario] = [
    Scenario(
        name="CS-003: Agent asks 'what's next?' instead of reading TODO",
        case_study="CS-003",
        description="All research tasks completed. Agent about to ask user 'what do you want to explore next?' instead of consulting TODO.md.",
        events=["PE-04"],  # About to produce output
        state={
            "state_docs_exist": True,  # TODO.md exists
            "locked_beliefs": [],
            "output_asks_user": True,  # "What do you want to explore next?"
            "directives": [],
            "time_since_state_check": 600,  # 10 minutes since last check
            "state_check_threshold": 300,
        },
        failure_description="Agent asks user for direction when TODO.md has the answer",
        expected_preventing_tbs=["TB-01"],
    ),
    Scenario(
        name="CS-005: New session maturity inflation",
        case_study="CS-005",
        description="New session starts. Agent reads project state and presents 2-3 hours of work as 'extensive validated research.'",
        events=["PE-01", "PE-04"],  # Session start, then about to produce status output
        state={
            "state_docs_exist": True,
            "locked_beliefs": [],
            "output_asks_user": False,
            "directives": [],
            "time_since_state_check": 86400,  # New session, very stale
            "state_check_threshold": 300,
            "output_claims_validation": True,  # Claims findings are "validated"
        },
        failure_description="Agent presents hypothesis-tier findings as validated research",
        expected_preventing_tbs=["TB-05", "TB-11", "TB-14"],
    ),
    Scenario(
        name="CS-006: Implementation pressure despite locked prohibition",
        case_study="CS-006",
        description="New session. User corrected 'no implementation' in prior session. Correction stored in memory. Agent reads it, then asks 'do you want to move toward implementation?'",
        events=["PE-01", "PE-02", "PE-04"],  # Session start, user asks 'where are we', agent about to respond
        state={
            "state_docs_exist": True,
            "locked_beliefs": [
                {"content": "Do not bring up implementation until user says so", "type": "prohibition"},
            ],
            "output_asks_user": True,  # Asks about implementation
            "directives": [
                {"content": "No implementation until user says so", "matches_output": True},
            ],
            "time_since_state_check": 86400,
            "state_check_threshold": 300,
        },
        failure_description="Agent violates locked prohibition about implementation",
        expected_preventing_tbs=["TB-02", "TB-03", "TB-10"],
    ),
    Scenario(
        name="CS-020: Wrong experiment number (41 -> 40)",
        case_study="CS-020",
        description="User says 'Build the #41 traceability extractor.' Agent creates exp40 instead.",
        events=["PE-03", "PE-04"],  # Task switch, then about to produce output
        state={
            "state_docs_exist": True,
            "locked_beliefs": [],
            "output_asks_user": False,
            "directives": [],
            "task_id_in_instruction": "41",
            "generated_task_id": "40",  # Mismatch
        },
        failure_description="Agent uses wrong task number from instruction",
        expected_preventing_tbs=["TB-04"],
    ),
    Scenario(
        name="CS-021: Design spec disguised as research",
        case_study="CS-021",
        description="Agent produces a 400-line 'research' document with no hypotheses, no experiments, no results, declares task 'done.'",
        events=["PE-04"],  # About to produce output claiming completion
        state={
            "state_docs_exist": True,
            "locked_beliefs": [],
            "output_asks_user": False,
            "directives": [],
            "output_claims_validation": True,  # Claims "#42 done, ready for implementation"
        },
        failure_description="Agent presents design spec as validated research",
        expected_preventing_tbs=["TB-14"],
    ),
]


# ============================================================
# Simulation engine
# ============================================================

def simulate_scenario(scenario: Scenario) -> dict[str, Any]:
    """Simulate TB activation for a scenario."""

    fired: list[dict[str, Any]] = []
    total_tokens = 0
    total_latency = 0

    for event in scenario.events:
        # Find all TBs that trigger on this event
        for tb in TB_REGISTRY:
            if tb.event != event:
                continue

            # Special conditions
            if tb.condition == "always":
                condition_met = True
            elif tb.condition == "claims_validation":
                condition_met = scenario.state.get("output_claims_validation", False)
            elif tb.condition == "belief_previously_cited":
                condition_met = False  # Not applicable in these scenarios
            else:
                condition_met = tb.check_condition(scenario.state)

            if condition_met:
                cost = ACTION_COSTS.get(tb.action, {"tokens": 0, "latency_ms": 0})
                total_tokens += cost["tokens"]
                total_latency += cost["latency_ms"]

                fired.append({
                    "tb_id": tb.tb_id,
                    "event": tb.event,
                    "condition": tb.condition,
                    "action": tb.action,
                    "action_desc": ACTION_DESCRIPTIONS.get(tb.action, "unknown"),
                    "priority": tb.priority,
                    "tokens": cost["tokens"],
                    "latency_ms": cost["latency_ms"],
                })

    # Sort by priority
    fired.sort(key=lambda x: x["priority"])

    # Check: would the failure be prevented?
    fired_ids = {f["tb_id"] for f in fired}
    expected = set(scenario.expected_preventing_tbs)
    preventing_fired = fired_ids & expected
    failure_prevented = len(preventing_fired) > 0

    # Check for blocking actions (A-04)
    has_block = any(f["action"] == "A-04" for f in fired)

    return {
        "scenario": scenario.name,
        "case_study": scenario.case_study,
        "events": scenario.events,
        "tbs_fired": fired,
        "tbs_fired_count": len(fired),
        "tbs_fired_ids": sorted(fired_ids),
        "expected_preventing": sorted(expected),
        "preventing_fired": sorted(preventing_fired),
        "failure_prevented": failure_prevented,
        "has_blocking_action": has_block,
        "total_tokens": total_tokens,
        "total_latency_ms": total_latency,
    }


# ============================================================
# Conflict resolution test
# ============================================================

def test_conflict_resolution() -> dict[str, Any]:
    """Test: session start with locked beliefs + stale state + task switch."""
    conflict_state: dict[str, Any] = {
        "state_docs_exist": True,
        "locked_beliefs": [
            {"content": "No implementation", "type": "prohibition"},
            {"content": "Always use uv", "type": "preference"},
        ],
        "time_since_state_check": 86400,
        "state_check_threshold": 300,
        "task_id_in_instruction": "42",
        "output_asks_user": False,
        "directives": [
            {"content": "No implementation", "matches_output": False},
        ],
    }

    events = ["PE-01", "PE-03", "PE-02", "PE-04"]
    fired: list[dict[str, Any]] = []

    for event in events:
        for tb in TB_REGISTRY:
            if tb.event != event:
                continue
            if tb.condition == "always":
                condition_met = True
            elif tb.condition == "claims_validation":
                condition_met = False
            elif tb.condition == "belief_previously_cited":
                condition_met = False
            else:
                condition_met = tb.check_condition(conflict_state)

            if condition_met:
                fired.append({
                    "tb_id": tb.tb_id,
                    "event": event,
                    "priority": tb.priority,
                    "action": tb.action,
                })

    fired.sort(key=lambda x: (x["priority"], x["tb_id"]))

    # Check for conflicts
    actions: list[Any] = [f["action"] for f in fired]
    has_block_and_proceed = "A-04" in actions and "A-01" in actions

    return {
        "scenario": "Conflict: session start + locked beliefs + task switch + stale state",
        "events": events,
        "tbs_fired": fired,
        "execution_order": [f["tb_id"] for f in fired],
        "has_conflict": has_block_and_proceed,
        "conflict_resolution": "P1 (block) would execute before P3 (self-check)" if has_block_and_proceed else "No block/proceed conflict",
    }


# ============================================================
# Main
# ============================================================

def main() -> None:
    print("=" * 70, file=sys.stderr)
    print("Experiment 51: Triggered Belief Simulation", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    all_results: dict[str, Any] = {"scenarios": [], "conflict_test": None, "overhead": {}}

    # Run each scenario
    total_prevented = 0
    total_scenarios = len(SCENARIOS)

    for scenario in SCENARIOS:
        result = simulate_scenario(scenario)
        all_results["scenarios"].append(result)

        status = "PREVENTED" if result["failure_prevented"] else "NOT PREVENTED"
        block = " [OUTPUT BLOCKED]" if result["has_blocking_action"] else ""

        print(f"\n  {scenario.name}", file=sys.stderr)
        print(f"    Events: {result['events']}", file=sys.stderr)
        print(f"    TBs fired: {result['tbs_fired_ids']} ({result['tbs_fired_count']} total)", file=sys.stderr)
        print(f"    Expected preventing: {result['expected_preventing']}", file=sys.stderr)
        print(f"    Preventing fired: {result['preventing_fired']}", file=sys.stderr)
        print(f"    Failure: {status}{block}", file=sys.stderr)
        print(f"    Cost: {result['total_tokens']} tokens, {result['total_latency_ms']}ms", file=sys.stderr)

        if result["failure_prevented"]:
            total_prevented += 1

        # Show fired TBs in priority order
        for tb in result["tbs_fired"]:
            print(f"      P{tb['priority']} {tb['tb_id']}: {tb['action_desc']} ({tb['tokens']}tok, {tb['latency_ms']}ms)", file=sys.stderr)

    # Conflict resolution test
    print(f"\n{'='*70}", file=sys.stderr)
    print("Conflict Resolution Test", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)

    conflict = test_conflict_resolution()
    all_results["conflict_test"] = conflict

    print(f"\n  {conflict['scenario']}", file=sys.stderr)
    print(f"  Events: {conflict['events']}", file=sys.stderr)
    print(f"  Execution order: {conflict['execution_order']}", file=sys.stderr)
    print(f"  Has conflict: {conflict['has_conflict']}", file=sys.stderr)
    print(f"  Resolution: {conflict['conflict_resolution']}", file=sys.stderr)

    # Overhead calculation: typical session
    print(f"\n{'='*70}", file=sys.stderr)
    print("Overhead: Typical Session Estimate", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)

    # Session: 1 session start + 10 user turns + 1 task switch
    session_events = {
        "PE-01": 1,   # Session start
        "PE-02": 10,  # User prompt submitted (10 turns)
        "PE-03": 1,   # Task switch
        "PE-04": 10,  # About to produce output (10 turns)
        "PE-05": 1,   # Context compression (once per session)
    }

    # Assume: 2 locked beliefs, state docs exist, no contradictions, 2 turns ask user questions
    typical_state: dict[str, Any] = {
        "state_docs_exist": True,
        "locked_beliefs": [{"content": "x"}, {"content": "y"}],
        "time_since_state_check": 86400,
        "state_check_threshold": 300,
        "task_id_in_instruction": "42",
        "output_asks_user": False,  # Most turns don't ask user
        "directives": [{"content": "x", "matches_output": False}],
    }

    session_tokens = 0
    session_latency = 0
    session_fires: dict[str, int] = {}

    for event, count in session_events.items():
        for _ in range(count):
            for tb in TB_REGISTRY:
                if tb.event != event:
                    continue
                if tb.condition == "always":
                    cond = event in ("ME-01", "ME-02", "ME-05")  # Only fire on memory events
                elif tb.condition == "claims_validation":
                    cond = False  # Most outputs don't claim validation
                elif tb.condition == "belief_previously_cited":
                    cond = False
                else:
                    cond = tb.check_condition(typical_state)

                if cond:
                    cost = ACTION_COSTS.get(tb.action, {"tokens": 0, "latency_ms": 0})
                    session_tokens += cost["tokens"]
                    session_latency += cost["latency_ms"]
                    session_fires[tb.tb_id] = session_fires.get(tb.tb_id, 0) + 1

    all_results["overhead"] = {
        "session_events": session_events,
        "total_tokens": session_tokens,
        "total_latency_ms": session_latency,
        "fires_per_tb": session_fires,
        "budget_tokens": 2350,
        "budget_latency_ms": 313,
        "within_token_budget": session_tokens <= 2350,
        "within_latency_budget": session_latency <= 313,
    }

    print(f"\n  Session shape: {session_events}", file=sys.stderr)
    print(f"  TB fires: {session_fires}", file=sys.stderr)
    print(f"  Total tokens: {session_tokens} (budget: 2,350)", file=sys.stderr)
    print(f"  Total latency: {session_latency}ms (budget: 313ms)", file=sys.stderr)
    print(f"  Within token budget: {session_tokens <= 2350}", file=sys.stderr)
    print(f"  Within latency budget: {session_latency <= 313}", file=sys.stderr)

    # Summary
    print(f"\n{'='*70}", file=sys.stderr)
    print("SUMMARY", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)
    print(f"\n  Scenarios tested: {total_scenarios}", file=sys.stderr)
    print(f"  Failures prevented: {total_prevented}/{total_scenarios}", file=sys.stderr)
    print(f"  Prevention rate: {total_prevented/total_scenarios:.0%}", file=sys.stderr)
    print(f"  Session overhead: {session_tokens} tokens, {session_latency}ms", file=sys.stderr)

    # Save
    out = Path("experiments/exp48_results.json")
    out.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nResults saved to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
