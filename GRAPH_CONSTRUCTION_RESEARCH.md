# Graph Construction Research

**Date:** 2026-04-09
**Status:** Research complete -- design decisions pending
**Questions addressed:** Typed nodes, edge weights, epistemic uncertainty, meta-awareness hooks, triggered information-seeking

---

## 1. Typed Nodes

### What We Have

Homogeneous nodes with a `category` label. All nodes are structurally identical -- only content and category differ.

### What Typed Nodes Enable That Typed Edges Alone Don't

**Constraint validation:** With typed nodes, a SOURCED_FROM edge is only valid from Belief to Observation. Without typed nodes, nothing prevents nonsensical edges (Observation CITES Observation). At small scale this is caught manually. At 10K+ nodes it causes silent graph corruption.

**Type-aware traversal:** BFS can skip irrelevant subtrees. "Find all Belief nodes within 2 hops" without typed nodes requires reading every node. With typed node labels, the traversal filters before expanding.

**Type-differentiated ranking:** Different node types warrant different confidence models. A procedural Belief ("always follow dispatch gate") has different revision semantics than a factual Belief ("Alice works at X"). Node types make this explicit.

**Sources:**
- [Type-augmented KG embedding (Nature 2023)](https://www.nature.com/articles/s41598-023-38857-5) -- TaKE framework; node type constraints improve KG completion by learning "type diversity" across entity types
- [Edge enhancement GNN with node discrimination (Complex & Intelligent Systems 2025)](https://link.springer.com/article/10.1007/s40747-025-01860-6) -- documents failure mode of treating all nodes identically: "feature redundancy" and loss of semantic differentiation

### Recommended Node Type System

Promote the existing `belief_type` and observation structure to explicit graph-level node types:

```
NodeType: OBSERVATION       -- immutable, append-only, ground truth
NodeType: BELIEF            -- mutable confidence, evidence chain
  Subtypes: factual | preference | procedural | causal | relational
NodeType: TEST              -- retrieval feedback record
NodeType: REVISION          -- belief update with provenance
NodeType: SESSION           -- session boundary marker
NodeType: MILESTONE         -- project phase marker
```

**Edge constraint table (enforced at write time):**

| Edge Type      | Valid From        | Valid To          |
|----------------|-------------------|-------------------|
| SOURCED_FROM   | BELIEF            | OBSERVATION       |
| SUPPORTS       | OBSERVATION/BELIEF| BELIEF            |
| CONTRADICTS    | BELIEF            | BELIEF            |
| CITES          | BELIEF            | BELIEF            |
| DECIDED_IN     | BELIEF/REVISION   | MILESTONE         |
| TEMPORAL_NEXT  | any               | same type         |
| TEST_OF        | TEST              | BELIEF            |
| REVISES        | REVISION          | BELIEF            |

**Implementation cost:** Low. Add `node_type TEXT NOT NULL` column to nodes table. Constraint validation is a 5-line check at write time. No schema migration needed for new installs.

---

## 2. Edge Weights for Uncertainty-Aware Traversal

### What We Have

`weight REAL` column exists in `mem_edges` but is unused. All traversal treats edges as unweighted.

### Weight Schemes

**Confidence product (recommended for v1):** Edge weight = minimum confidence of the two endpoint nodes.

```python
edge_weight = min(source_belief.confidence, target_belief.confidence)
```

This means: a highly confident belief citing an uncertain belief gets a low-weight edge. The chain is only as strong as its weakest link.

**Temporal decay (v2):** Weight decays with age for time-sensitive beliefs.

```python
edge_weight = confidence * exp(-decay_rate * days_since_created)
```

Zep/Graphiti uses `valid_from`/`valid_to` windows for this. We have `created_at` already.

**Source reliability multiplier:** Different source types get different base weights.

```
user_correction:    1.0   (highest -- the user said it explicitly)
user_statement:     0.8
agent_inference:    0.6
automated_test:     0.7
```

### Weighted Traversal

**Weighted BFS (Dijkstra-style):** Priority queue ordered by cumulative path weight (product of edge weights). Returns highest-confidence paths first. O((V+E) log V) vs O(V+E) for BFS -- at 586-node scale the difference is <5ms.

**Path scoring formula -- and how SUPPORTS + CONTRADICTS combine:**

Both edge types contribute to uncertainty estimation, not just traversal ranking. A belief with both SUPPORTS and CONTRADICTS edges incoming is more uncertain than one with only SUPPORTS, even if the SUPPORTS edges are high-weight.

| Edge Type     | Path composition        | Uncertainty contribution |
|---------------|-------------------------|--------------------------|
| SUPPORTS      | min(w1, w2)             | Reduces uncertainty      |
| CONTRADICTS   | min(w1, w2)             | Increases uncertainty    |
| CITES         | min(w1, w2)             | Neutral (provenance)     |
| TEMPORAL_NEXT | w * recency_factor      | Neutral                  |

**Uncertainty estimate from edge balance:**

```python
def belief_uncertainty(belief_id, edges):
    support_weight  = sum(e.weight for e in edges
                          if e.to_id == belief_id and e.type == "SUPPORTS")
    contradict_weight = sum(e.weight for e in edges
                            if e.to_id == belief_id and e.type == "CONTRADICTS")
    total = support_weight + contradict_weight
    if total == 0:
        return UncertaintyState.ABSENT
    # Conflict ratio: 0 = fully supported, 1 = fully contradicted, 0.5 = balanced conflict
    conflict_ratio = contradict_weight / total
    return conflict_ratio   # higher = more uncertain
```

A belief with conflict_ratio near 0.5 (equally supported and contradicted) has maximum
uncertainty and should trigger the interview session (section 4). Thresholds for what
conflict_ratio warrants escalation: TBD from experiments.

Traversal behavior for contradicted nodes is the opposite of penalization: a
heavily-contradicted node should be PRIORITIZED in retrieval, not avoided. Contradictions
are unresolved conflicts that need to surface quickly so the interview loop can resolve
them. Routing around them hides the conflict and lets it fester.

Concretely:
- Weighted BFS path scoring uses SUPPORTS edge weights for ranking confidence
- CONTRADICTS edges are a separate signal that flags nodes for escalation
- A node with high conflict_ratio sorts to the TOP of the escalation queue, not
  to the bottom of retrieval results
- The retrieval result set includes contradicted nodes WITH their conflict_ratio
  clearly tagged so the MCP client knows to trigger the interview loop

**Sources:**
- [Soft Reasoning Paths for KG Completion (IJCAI 2025)](https://www.ijcai.org/proceedings/2025/0327.pdf) -- compares multiplicative, additive, and min/max composition; min is best for conservative chains
- [Path-based Explanation for KG Completion (arXiv 2024)](https://arxiv.org/pdf/2401.02290) -- matrix powering for path ranking: P^n[i,j] = n-hop path weight from i to j
- [Zep/Graphiti (arXiv 2025)](https://arxiv.org/abs/2501.13956) -- temporal validity windows on edges

### Connection to HRR

In the HRR encoding, edge weights can scale the contribution of each bound triple before superposition:

```python
S += edge_weight * convolve(convolve(node_A, edge_type_vec), node_B)
```

Higher-weight edges contribute more to the superposition, so they dominate nearest-neighbor retrieval. This naturally biases traversal toward high-confidence paths without any explicit filtering.

---

## 3. Epistemic Uncertainty: Knowing What You Don't Know

### The Critical Distinction

| State | Meaning | Detection |
|-------|---------|-----------|
| **Absence of evidence** | No beliefs on this topic at all | Zero nodes match query |
| **Low-confidence evidence** | Beliefs exist but uncertain | Nodes match, mean confidence < 0.5 |
| **Untested beliefs** | Confident but never verified | Nodes match, zero TEST edges |
| **Conflicting evidence** | Contradicting beliefs, both confident | CONTRADICTS edges between high-confidence nodes |

These are not the same thing. A system that conflates them will report "I'm uncertain" when it actually has no data, or "I know this" when it has untested high-confidence beliefs.

### Open-World Assumption

Our system already operates under OWA: absent beliefs are unknown, not false. This is correct. An absent Belief about PostgreSQL means "we haven't formed a view" not "we don't use PostgreSQL."

**Sources:**
- [Rethinking KG Evaluation Under OWA (arXiv 2022/2024)](https://arxiv.org/abs/2209.08858) -- standard KG metrics break under OWA; missing facts can't be labeled "wrong"
- [Uncertainty Management in KG Construction (Dagstuhl 2016)](https://drops.dagstuhl.de/storage/08tgdk/tgdk-vol003/tgdk-vol003-issue001/TGDK.3.1.3/TGDK.3.1.3.pdf) -- authoritative distinction between incomplete (OWA) and inconsistent (CWA)

### Epistemic Uncertainty Metrics

**Gap detection algorithm (query-time, no schema change):**

```python
def assess_epistemic_state(query, beliefs):
    if not beliefs:
        return EpistemicState.ABSENT         # No data at all
    mean_conf = mean(b.confidence for b in beliefs)
    tested = any(b.test_count > 0 for b in beliefs)
    if mean_conf < 0.3:
        return EpistemicState.VERY_UNCERTAIN
    if mean_conf < 0.5:
        return EpistemicState.UNCERTAIN
    if not tested:
        return EpistemicState.UNTESTED
    return EpistemicState.GROUNDED
```

**Entropy as uncertainty signal:** Your Beta distribution already gives you this for free.

```python
from scipy.stats import beta as beta_dist
entropy = beta_dist.entropy(belief.alpha, belief.beta)
# High entropy = high uncertainty about this belief
```

**Source-count corroboration:** A belief supported by 3 independent source types is more epistemically grounded than one supported by 1.

```python
sources_count = len({obs.source_type for obs in belief.observations})
epistemic_confidence = belief.confidence * min(1.0, sources_count / 3)
```

**Sources:**
- [Credal GNNs (arXiv Dec 2025)](https://arxiv.org/html/2512.02722) -- first framework distinguishing epistemic from aleatoric uncertainty in graph learning
- [Uncertainty in GNNs: Survey (TMLR 2024)](https://arxiv.org/html/2403.07185) -- taxonomy of uncertainty types; "absence of evidence" and "evidence of absence" need different detection strategies

### Tying to REQ-025 (Methodological Confidence Layer) and REQ-026 (Calibrated Status Reporting)

Epistemic state should appear in status queries:

```
Topics with no beliefs:          [list]          → ABSENT
Topics with <0.5 mean confidence: [list]         → UNCERTAIN
Topics with no test records:      [list]         → UNTESTED
Topics with active contradictions: [list]        → CONFLICTED
Topics well-grounded (conf>0.8, tested, 2+ sources): [list]  → GROUNDED
```

This directly implements REQ-026's calibrated reporting requirement.

---

## 4. Meta-Awareness: The System Knowing What It Doesn't Know

### The Core Pattern

When epistemic state is ABSENT or VERY_UNCERTAIN, the system should not hallucinate. It should escalate. Three escalation modes:

**1. Ask the user (for preferences, directives, project decisions)**

Triggered when: query is about user behavior, tooling, or project policy and no grounded beliefs exist.

```
System detects: no beliefs about "database choice"
System asks:    "I don't have a record of your database preference.
                 Do you have a preference between PostgreSQL and SQLite
                 for this project? Any reasons to avoid either?"
User answers → stored as high-confidence belief with user_correction source type
```

This is the GSD interview pattern applied to memory: structured questions to fill specific gaps, not open-ended "what should I do?"

**2. Research the topic (for technical facts)**

Triggered when: query is about external technical facts (library behavior, API design, best practices) and no beliefs exist.

```
System detects: no beliefs about "SQLite WAL mode behavior under concurrent writes"
System triggers: research hook → web search or documentation fetch
Result stored as belief with source_type = "automated_research", confidence = 0.6
```

**3. Admit uncertainty and continue (for low-stakes queries)**

Triggered when: uncertainty is high but the query is not blocking. Return what exists with explicit epistemic markers.

```
{"beliefs": [...], "epistemic_state": "UNCERTAIN", 
 "caveat": "These beliefs have low confidence (mean=0.3). Treat as hypotheses."}
```

### Interview Pattern (GSD-Style)

The GSD framework's `discuss-phase` skill runs a back-and-forth interview session --
not a single question -- asking as many questions as needed until it has enough clarity
to proceed. The same pattern applies here.

When uncertainty is detected on a topic, the system enters an **interview loop**:

```
1. Assess epistemic state for the topic
2. Generate the highest-priority clarifying question
3. Ask user, store answer as observation, update belief confidence
4. Re-assess epistemic state
5. If still above uncertainty threshold: go to 2
6. If below threshold (TBD): exit loop, proceed
```

The loop exits when uncertainty drops below an acceptable level. What "acceptable"
means quantitatively is TBD -- it will emerge from experiments on how many questions
typically resolve a given category of uncertainty (behavioral vs factual vs preference).

**Question generation rules:**
- Most-uncertain aspect first (ranked by conflict_ratio or entropy)
- Specific and answerable: "Do you prefer PostgreSQL or SQLite for this project?"
  not "Tell me about your database preferences"
- Binary or multiple-choice where possible
- Each answer stored as an observation linked to the belief it addresses, regardless
  of which option the user picks
- Questions are not repeated across sessions -- if a belief was resolved in session N,
  the interview loop should not re-open it in session N+1 (REQ-019)

**Sources:**
- [A Review of Plan-Based Approaches for Dialogue Management (Cognitive Computation 2022)](https://link.springer.com/article/10.1007/s12559-022-09996-0) -- clarification as a dialogue act triggered by low-confidence parses
- [Enhancing Proactive Dialogue Systems (IWSDS 2025)](https://aclanthology.org/2025.iwsds-1.15.pdf) -- clarification questions as strategy for handling uncertainty
- [KG + LLM Co-learning (Emory 2024)](https://www.cs.emory.edu/~jyang71/files/klc.pdf) -- active learning loop where system queries user on uncertain edges

### The Trigger Threshold

| Epistemic State | Threshold | Action |
|---|---|---|
| ABSENT | Always | Ask user OR research, depending on topic type |
| VERY_UNCERTAIN (conf < 0.3) | Always | Ask user for correction |
| UNCERTAIN (0.3-0.5) | If behavioral/preference topic | Ask user; if factual, return with caveat |
| UNTESTED | If used for critical decision | Surface "untested" warning |
| CONFLICTED | Always | Surface contradiction, ask user to resolve |
| GROUNDED (conf > 0.8, tested) | Never | Return normally |

---

## 5. Hook Architecture for Triggered Behavior

### Recommended: Two-Layer Approach

**Layer 1 -- SQLite triggers (async, background):**

Fires when confidence crosses threshold. Writes to an `escalations` table. Does not block the main operation.

```sql
CREATE TRIGGER escalate_low_confidence
AFTER UPDATE OF confidence ON beliefs
WHEN NEW.confidence < 0.5 AND OLD.confidence >= 0.5
BEGIN
    INSERT INTO escalations(belief_id, escalation_type, created_at)
    VALUES(NEW.id, 'low_confidence', datetime('now'));
END;

CREATE TRIGGER promote_behavioral_belief
AFTER UPDATE OF confidence ON beliefs
WHEN NEW.belief_type = 'behavioral'
     AND NEW.confidence > 0.8
     AND OLD.confidence <= 0.8
BEGIN
    INSERT INTO l0_context(belief_id, reason, created_at)
    VALUES(NEW.id, 'auto_promotion', datetime('now'));
END;
```

**Layer 2 -- Retrieve-time check (sync, inline):**

Every `search` MCP call checks the epistemic state of returned beliefs and attaches an escalation signal if warranted.

```python
def search(query):
    beliefs = graph_search(query)
    state = assess_epistemic_state(query, beliefs)
    if state in (ABSENT, VERY_UNCERTAIN, CONFLICTED):
        return {
            "beliefs": beliefs,
            "epistemic_state": state.name,
            "action": "escalate",
            "suggested_question": generate_clarification_question(query, beliefs)
        }
    return {"beliefs": beliefs, "epistemic_state": state.name}
```

**Layer 3 -- Session-start sweep (optional):**

On session start, scan for unresolved escalations from prior sessions and surface them.

```python
def on_session_start():
    unresolved = db.query(
        "SELECT * FROM escalations WHERE resolved_at IS NULL "
        "ORDER BY created_at DESC LIMIT 5"
    )
    if unresolved:
        present_to_user("Unresolved from last session:", unresolved)
```

**Sources:**
- [Event-Driven Architecture Patterns (DZone 2024)](https://dzone.com/articles/event-driven-architecture-real-world-iot)
- [Next-Generation Event-Driven Architectures (arXiv 2024)](https://arxiv.org/html/2510.04404v1)
- [AI Agent Guardrails: Production Guide 2026](https://authoritypartners.com/insights/ai-agent-guardrails-production-guide-for-2026/)

---

## 6. How This All Fits Together

A query comes in for a topic the system doesn't know well:

```
1. graph_search(query) → beliefs = []
2. assess_epistemic_state() → ABSENT
3. retrieve() returns: {beliefs: [], state: ABSENT, action: escalate,
                        suggested_question: "Do you have a preference on X?"}
4. MCP client (Claude Code) sees action=escalate
5. Hook fires: present_clarification_question to user
6. User answers
7. store_observation(answer) → new Belief with high confidence
8. SQLite trigger: new_belief.confidence > 0.8 AND behavioral → write to l0_context
9. Next session: belief is in L0, question is never asked again
```

This is REQ-019 (single-correction learning), REQ-020 (locked beliefs), REQ-021 (behavioral in L0), and REQ-026 (calibrated reporting) all firing from one mechanism.

The edge weights feed into this: the weighted BFS finds the traversal path with highest cumulative confidence, and the confidence of that best path feeds the epistemic state assessment. Low path weight → uncertain → escalate.

---

## 7. New Requirements Surfaced

### REQ-027 -- already added (zero-repeat directive guarantee)

### REQ-028: Epistemic State Tagging on Retrieval Results

**Requirement:** Every `search` MCP response must include an `epistemic_state` field (ABSENT | VERY_UNCERTAIN | UNCERTAIN | UNTESTED | CONFLICTED | GROUNDED) and an `action` field when escalation is warranted.

**Rationale:** The LLM client needs a machine-readable signal, not just natural language, to decide whether to proceed or escalate. Without this, the client has to parse the confidence numbers itself.

### REQ-029: Uncertainty-Triggered Clarification Questions

**Requirement:** When `epistemic_state` is ABSENT or VERY_UNCERTAIN for a preference/behavioral query, the system must generate a specific, answerable clarification question and surface it to the user. The question must be stored alongside the belief it was designed to clarify.

**Rationale:** The GSD interview pattern. Structured gap-filling beats open-ended "what do you want?" and beats hallucinating an answer from training data.

### REQ-030: Edge Weights Populated from Belief Confidence

**Requirement:** All edges must have non-null weights derived from endpoint belief confidence at write time. Traversal must use these weights for path scoring.

**Rationale:** Unweighted traversal treats a highly-confident citation and a speculative citation identically. Path weight is a proxy for epistemic reliability of the reasoning chain.

---

## 8. What NOT to Build

| Approach | Why Not |
|---|---|
| TransE/RotatE embeddings | Require continuous vectors; our system is symbolic. Only relevant with LLM-enhanced mode. |
| Full PSL framework | Overkill at 586-10K nodes. Soft-logic composition rules are useful; the full inference engine is not. |
| Leiden community clustering | $33K at scale; gains shrink with corrected evaluation. |
| Reactive actor system (Akka-style) | Architectural overkill. SQLite triggers + retrieve-time checks cover our scale. |
| Differential privacy | LLMs can reverse it (2026 research). Already rejected in PRIVACY_THREAT_MODEL.md. |
