"""Validation tests for dynamic edge scoring against real case study scenarios.

These tests simulate multi-cycle retrieval+feedback patterns from the case studies
and verify that the Bayesian edge system produces measurably better outcomes over
time: useful edges strengthen, harmful edges weaken, and BFS prefers proven paths.
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from agentmemory.models import (
    BELIEF_CORRECTION,
    BELIEF_FACTUAL,
    BELIEF_PROCEDURAL,
    BELIEF_REQUIREMENT,
    BSRC_AGENT_INFERRED,
    BSRC_USER_CORRECTED,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.store import MemoryStore


@pytest.fixture()
def store(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    s: MemoryStore = MemoryStore(tmp_path / "validation.db")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# CS-015: Dead Approaches Re-Proposed Across Sessions
#
# Scenario: "price filter" was tried and failed. A SUPERSEDES edge connects
# the dead approach to the replacement. Over multiple sessions, the agent
# searches for approaches, traverses the SUPERSEDES edge, and marks the
# replacement as "used" and the dead approach as "harmful". The edge to the
# replacement should strengthen; edge to the dead approach should weaken.
# ---------------------------------------------------------------------------


class TestCS015DeadApproachEdges:
    """Verify that SUPERSEDES edges strengthen toward the winning approach."""

    def test_replacement_edge_strengthens_with_use(self, store: MemoryStore) -> None:
        """When searching for an approach topic, the edge to the replacement
        strengthens as the agent consistently uses the replacement belief.
        (SUPERSEDES edges are excluded from BFS by design -- the agent
        discovers replacements via topic-level RELATES_TO edges.)"""
        topic: Belief = store.insert_belief(
            "Signal quality filtering approaches for options strategy",
            BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        )
        dead: Belief = store.insert_belief(
            "Use price filters to remove low-quality signals",
            BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        )
        replacement: Belief = store.insert_belief(
            "No-filter approach with BEP threshold is superior to price filters (D183)",
            BELIEF_CORRECTION, BSRC_USER_CORRECTED,
        )
        store.supersede_belief(dead.id, replacement.id, "price filters failed")
        # Topic connects to replacement via RELATES_TO
        edge_id: int = store.insert_edge(topic.id, replacement.id, "RELATES_TO")

        # 5 retrieval cycles: agent finds replacement via topic edge
        for _ in range(5):
            store.expand_graph([topic.id], depth=1)
            store.update_confidence(replacement.id, "used")

        row = store.query(
            "SELECT alpha, beta_param, traversal_count FROM edges WHERE id = ?",
            (edge_id,),
        )[0]
        alpha: float = float(str(row["alpha"]))
        beta: float = float(str(row["beta_param"]))
        traversals: int = int(str(row["traversal_count"]))

        assert alpha > beta
        assert traversals == 5
        confidence: float = alpha / (alpha + beta)
        assert confidence > 0.7, f"Expected confidence > 0.7, got {confidence:.3f}"

    def test_dead_approach_deprioritized_over_time(self, store: MemoryStore) -> None:
        """After feedback, BFS should prefer the path to the replacement."""
        dead: Belief = store.insert_belief(
            "Exit rules with fixed DTE floors",
            BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        )
        replacement: Belief = store.insert_belief(
            "Dynamic exit based on realized volatility, not fixed DTE (D209)",
            BELIEF_CORRECTION, BSRC_USER_CORRECTED,
        )
        # Both connect to a common root
        root: Belief = store.insert_belief(
            "Exit strategy for options positions",
            BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        )
        store.insert_edge(root.id, dead.id, "RELATES_TO", alpha=1.0, beta_param=1.0)
        store.insert_edge(root.id, replacement.id, "RELATES_TO", alpha=1.0, beta_param=1.0)

        # Simulate: replacement is always "used", dead is always "ignored"
        for _ in range(5):
            store.expand_graph([root.id], depth=1)
            store.update_confidence(replacement.id, "used")
            store.update_confidence(dead.id, "ignored")

        # Now expand with max_nodes=1 -- should pick the stronger edge
        result = store.expand_graph([root.id], depth=1, max_nodes=1)
        assert replacement.id in result, "BFS should prefer the replacement after feedback"
        assert dead.id not in result, "Dead approach should be deprioritized"


# ---------------------------------------------------------------------------
# CS-016: Settled Decision Repeatedly Questioned
#
# Scenario: D073 ("calls and puts are equal citizens") is a locked belief.
# Edges from related topics to D073 should strengthen as the agent
# repeatedly retrieves and uses D073 when discussing options direction.
# ---------------------------------------------------------------------------


class TestCS016SettledDecisionEdges:
    """Verify that edges to locked decisions strengthen and persist."""

    def test_locked_decision_edges_strengthen(self, store: MemoryStore) -> None:
        d073: Belief = store.insert_belief(
            "Calls and puts are equal citizens in the strategy (D073). Not negotiable.",
            BELIEF_REQUIREMENT, BSRC_USER_STATED, locked=True,
        )
        topic: Belief = store.insert_belief(
            "Options strategy direction and instrument selection",
            BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        )
        edge_id: int = store.insert_edge(topic.id, d073.id, "SUPPORTS")

        # 10 retrievals where D073 is used
        for _ in range(10):
            store.expand_graph([topic.id], depth=1)
            store.update_confidence(d073.id, "used")

        row = store.query(
            "SELECT alpha, beta_param FROM edges WHERE id = ?", (edge_id,),
        )[0]
        alpha: float = float(str(row["alpha"]))
        confidence: float = alpha / (alpha + float(str(row["beta_param"])))
        assert confidence > 0.9, f"Edge to locked decision should be very confident: {confidence:.3f}"


# ---------------------------------------------------------------------------
# CS-022: Multi-Hop Operational Query Collapse
#
# Scenario: Agent has beliefs about machine locations and project data.
# "paper trading data is on lorax (local)" should be reachable via edges.
# After the user corrects "not on willow, on lorax", the edge to the
# wrong machine should weaken and the edge to the right one strengthen.
# ---------------------------------------------------------------------------


class TestCS022MultiHopCorrection:
    """Verify that correction feedback reshapes the edge graph."""

    def test_wrong_path_weakens_correct_path_strengthens(self, store: MemoryStore) -> None:
        query_node: Belief = store.insert_belief(
            "Where is the paper trading data stored?",
            BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        )
        wrong: Belief = store.insert_belief(
            "Paper trading data is on willow via SSH",
            BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        )
        correct: Belief = store.insert_belief(
            "Paper trading data is local on lorax, not on willow",
            BELIEF_CORRECTION, BSRC_USER_CORRECTED,
        )
        e_wrong: int = store.insert_edge(query_node.id, wrong.id, "RELATES_TO")
        e_correct: int = store.insert_edge(query_node.id, correct.id, "RELATES_TO")

        # Session 1: agent follows wrong path, gets corrected
        store.expand_graph([query_node.id], depth=1)
        store.update_confidence(wrong.id, "harmful")
        store.update_confidence(correct.id, "used")

        # Session 2-3: agent follows correct path
        for _ in range(2):
            store.expand_graph([query_node.id], depth=1)
            store.update_confidence(correct.id, "used")

        # Check edges
        r_wrong = store.query("SELECT alpha, beta_param FROM edges WHERE id = ?", (e_wrong,))[0]
        r_correct = store.query("SELECT alpha, beta_param FROM edges WHERE id = ?", (e_correct,))[0]

        conf_wrong: float = float(str(r_wrong["alpha"])) / (
            float(str(r_wrong["alpha"])) + float(str(r_wrong["beta_param"]))
        )
        conf_correct: float = float(str(r_correct["alpha"])) / (
            float(str(r_correct["alpha"])) + float(str(r_correct["beta_param"]))
        )

        assert conf_correct > conf_wrong, (
            f"Correct path ({conf_correct:.3f}) should outrank wrong path ({conf_wrong:.3f})"
        )

    def test_bfs_learns_from_correction_history(self, store: MemoryStore) -> None:
        """After correction cycles, BFS should prefer the corrected path."""
        root: Belief = store.insert_belief(
            "Agent deployment infrastructure",
            BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        )
        willow: Belief = store.insert_belief(
            "Agents run on willow remote server",
            BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        )
        lorax: Belief = store.insert_belief(
            "Agents run locally on lorax workstation",
            BELIEF_CORRECTION, BSRC_USER_CORRECTED,
        )

        store.insert_edge(root.id, willow.id, "RELATES_TO")
        store.insert_edge(root.id, lorax.id, "RELATES_TO")

        # 3 correction cycles
        for _ in range(3):
            store.expand_graph([root.id], depth=1)
            store.update_confidence(willow.id, "harmful")
            store.update_confidence(lorax.id, "used")

        # BFS with max_nodes=1 should pick lorax
        result = store.expand_graph([root.id], depth=1, max_nodes=1)
        assert lorax.id in result
        assert willow.id not in result


# ---------------------------------------------------------------------------
# CS-001: Redundant Work
#
# Scenario: "documentation task completed" and "documentation task request"
# should be connected. When the agent retrieves the completion belief and
# it's marked "used" (agent correctly said "already done"), that edge
# strengthens. When the agent misses it and redoes work, the edge to
# the redo is "harmful".
# ---------------------------------------------------------------------------


class TestCS001RedundantWorkEdges:
    """Verify that edges help prevent redundant work over sessions."""

    def test_completion_edge_strengthens_with_correct_behavior(
        self, store: MemoryStore,
    ) -> None:
        completed: Belief = store.insert_belief(
            "Documentation task completed: updated README, CHANGELOG, CONTRIBUTING",
            BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        )
        task_desc: Belief = store.insert_belief(
            "Document the project with README and changelog files",
            BELIEF_PROCEDURAL, BSRC_USER_STATED,
        )
        edge_id: int = store.insert_edge(completed.id, task_desc.id, "RELATES_TO")

        # 3 sessions where agent correctly finds the completion
        for _ in range(3):
            store.expand_graph([task_desc.id], depth=1)
            store.update_confidence(completed.id, "used")

        row = store.query("SELECT alpha, beta_param, traversal_count FROM edges WHERE id = ?", (edge_id,))[0]
        alpha: float = float(str(row["alpha"]))
        beta: float = float(str(row["beta_param"]))
        assert alpha > 3.0, f"Edge alpha should have grown from 1.0: got {alpha}"
        assert alpha / (alpha + beta) > 0.7


# ---------------------------------------------------------------------------
# Feedback loop convergence test
#
# This tests the core property: over many retrieval+feedback cycles,
# edge confidence should converge -- useful edges approach 1.0,
# useless edges approach 0.0, and the gap between them widens.
# ---------------------------------------------------------------------------


class TestFeedbackLoopConvergence:
    """Verify that the feedback loop produces measurable convergence."""

    def test_edge_confidence_diverges_over_cycles(self, store: MemoryStore) -> None:
        """Good edges and bad edges should diverge in confidence over time."""
        root: Belief = store.insert_belief(
            "Central topic belief for convergence test",
            BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        )
        good: Belief = store.insert_belief(
            "Consistently useful belief that helps the agent",
            BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        )
        bad: Belief = store.insert_belief(
            "Consistently irrelevant belief that wastes tokens",
            BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        )
        e_good: int = store.insert_edge(root.id, good.id, "SUPPORTS")
        e_bad: int = store.insert_edge(root.id, bad.id, "RELATES_TO")

        # 10 cycles: good is always used, bad is always ignored
        for _ in range(10):
            store.expand_graph([root.id], depth=1)
            store.update_confidence(good.id, "used")
            store.update_confidence(bad.id, "ignored")

        r_good = store.query("SELECT alpha, beta_param FROM edges WHERE id = ?", (e_good,))[0]
        r_bad = store.query("SELECT alpha, beta_param FROM edges WHERE id = ?", (e_bad,))[0]

        conf_good: float = float(str(r_good["alpha"])) / (
            float(str(r_good["alpha"])) + float(str(r_good["beta_param"]))
        )
        conf_bad: float = float(str(r_bad["alpha"])) / (
            float(str(r_bad["alpha"])) + float(str(r_bad["beta_param"]))
        )

        # The gap should be significant after 10 cycles
        gap: float = conf_good - conf_bad
        assert gap > 0.3, (
            f"Expected confidence gap > 0.3 after 10 cycles, "
            f"got {gap:.3f} (good={conf_good:.3f}, bad={conf_bad:.3f})"
        )

    def test_harmful_feedback_degrades_faster_than_ignored(
        self, store: MemoryStore,
    ) -> None:
        """'harmful' should degrade edge confidence faster than 'ignored'."""
        root: Belief = store.insert_belief(
            "Root for degradation test",
            BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        )
        ignored_target: Belief = store.insert_belief(
            "Belief that gets ignored",
            BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        )
        harmful_target: Belief = store.insert_belief(
            "Belief that causes harm",
            BELIEF_FACTUAL, BSRC_AGENT_INFERRED,
        )
        e_ign: int = store.insert_edge(root.id, ignored_target.id, "RELATES_TO")
        e_harm: int = store.insert_edge(root.id, harmful_target.id, "RELATES_TO")

        # 5 cycles of negative feedback
        for _ in range(5):
            store.expand_graph([root.id], depth=1)
            store.update_confidence(ignored_target.id, "ignored")
            store.update_confidence(harmful_target.id, "harmful")

        r_ign = store.query("SELECT alpha, beta_param FROM edges WHERE id = ?", (e_ign,))[0]
        r_harm = store.query("SELECT alpha, beta_param FROM edges WHERE id = ?", (e_harm,))[0]

        conf_ign: float = float(str(r_ign["alpha"])) / (
            float(str(r_ign["alpha"])) + float(str(r_ign["beta_param"]))
        )
        conf_harm: float = float(str(r_harm["alpha"])) / (
            float(str(r_harm["alpha"])) + float(str(r_harm["beta_param"]))
        )

        assert conf_harm < conf_ign, (
            f"Harmful ({conf_harm:.3f}) should degrade faster than ignored ({conf_ign:.3f})"
        )

    def test_traversal_counts_accumulate_across_cycles(
        self, store: MemoryStore,
    ) -> None:
        """Traversal count should monotonically increase with retrieval cycles."""
        a: Belief = store.insert_belief("Traversal counter A", BELIEF_FACTUAL, BSRC_AGENT_INFERRED)
        b: Belief = store.insert_belief("Traversal counter B", BELIEF_FACTUAL, BSRC_AGENT_INFERRED)
        edge_id: int = store.insert_edge(a.id, b.id, "SUPPORTS")

        for cycle in range(1, 6):
            store.expand_graph([a.id], depth=1)
            row = store.query(
                "SELECT traversal_count FROM edges WHERE id = ?", (edge_id,),
            )[0]
            assert int(str(row["traversal_count"])) == cycle


# ---------------------------------------------------------------------------
# Edge health metrics validation
# ---------------------------------------------------------------------------


class TestEdgeHealthMetrics:
    """Verify edge health metrics reflect actual state."""

    def test_edge_credal_gap_decreases_with_feedback(
        self, store: MemoryStore,
    ) -> None:
        """Edges that receive feedback should leave the credal gap."""
        a: Belief = store.insert_belief("Gap test A", BELIEF_FACTUAL, BSRC_AGENT_INFERRED)
        b: Belief = store.insert_belief("Gap test B", BELIEF_FACTUAL, BSRC_AGENT_INFERRED)
        c: Belief = store.insert_belief("Gap test C", BELIEF_FACTUAL, BSRC_AGENT_INFERRED)
        store.insert_edge(a.id, b.id, "SUPPORTS")
        store.insert_edge(a.id, c.id, "RELATES_TO")

        # Before feedback: both at prior
        health_before: dict[str, object] = store.get_edge_health()
        assert health_before["edge_credal_gap"] == 2

        # Feedback on one edge (via traversal + belief feedback)
        store.expand_graph([a.id], depth=1)
        store.update_confidence(b.id, "used")

        health_after: dict[str, object] = store.get_edge_health()
        gap_after: int = int(str(health_after["edge_credal_gap"]))
        assert gap_after < 2, f"Credal gap should decrease after feedback, got {gap_after}"
