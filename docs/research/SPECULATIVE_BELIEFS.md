# Speculative Beliefs: Forward-Looking Memory with Multi-Dimensional Uncertainty

## Origin

On 2026-04-17, during discussion of the ba protocol and high-context injection, the user observed that agentmemory's temporal axis is purely backward-looking. Every belief records something that happened. There is no mechanism for speculative, forward-looking beliefs about possible futures, the way humans maintain game-theoretic decision trees and switch branches when a strategy becomes sub-optimal.

The user further clarified the wonder/reason pipeline: wonder is divergent (broad speculative survey, generating hypotheses as new belief nodes), reason is convergent (testing hypotheses against existing beliefs, updating uncertainty). This document synthesizes research on the math, algorithms, and prior art needed to implement this.

## The Wonder/Reason Pipeline

**Wonder** = broad speculative research. Cast a wide net. Generate hypotheses as forward-looking belief nodes with multi-dimensional uncertainty vectors. These go into the graph as speculative beliefs linked to current state.

**Reason** = focused hypothesis testing. Take speculative nodes from wonder, pose them as testable claims, run retrieval/scoring against them, and update their uncertainty vectors. The output is narrowed uncertainty.

**User workflow:**
1. `/mem:wonder "topic"` produces N speculative beliefs with high uncertainty
2. User reviews, picks interesting ones
3. `/mem:reason "hypothesis"` tests against existing beliefs, updates uncertainty
4. User sees which directions have lowest remaining uncertainty (most promising) vs highest (most in need of experiments)

Wonder expands the speculative tree. Reason contracts it by resolving uncertainty.

---

## Data Structures

### Multi-Dimensional Beta Vectors

Each speculative belief carries K independent Beta distributions, one per uncertainty axis:

```
node.uncertainty = [(alpha_1, beta_1), ..., (alpha_K, beta_K)]
```

**Why independent Betas, not Dirichlet:** A Dirichlet models allocation across categories that sum to 1. Feasibility and cost are not competing for probability mass; they are independent assessments. Independent Betas allow each axis to update independently without affecting others.

Storage: 2K floats per node. For K=4: 8 floats, 64 bytes. Negligible.

**Proposed dimensions (initial set, can extend):**
- **Feasibility** -- can this be built/done?
- **Value** -- if built, does it help?
- **Cost** -- resources required (time, complexity, risk)
- **Dependency** -- what else must be true for this to work?

Source: Bishop, *Pattern Recognition and Machine Learning* (2006), Section 2.1-2.2.

### Joint Entropy for Uncertainty Ranking

For K independent Beta distributions:

```
H_joint = sum_{i=1}^{K} H(Beta(alpha_i, beta_i))
```

Where single Beta entropy is:

```
H(Beta(a,b)) = ln(B(a,b)) - (a-1)*psi(a) - (b-1)*psi(b) + (a+b-2)*psi(a+b)
```

"Uncertainty explosion points" = nodes with highest H_joint. These are the points where resolving uncertainty has the greatest information value.

Source: Cover & Thomas, *Elements of Information Theory* (2006), Theorem 2.6.6.

---

## Algorithms

### Evidence Propagation

Belief Propagation (Pearl 1988) on graph edges with cross-dimension weights:

```
When node A's dimension i updates by (delta_alpha, delta_beta):
  For each edge A -> B with weight w_ij:
    B.alpha_j += w_ij * delta_alpha
    B.beta_j  += w_ij * delta_beta
```

Cross-dimension propagation is valid when edges carry semantic weight. Example: A.feasibility update affects B.cost when B depends on A.

For DAGs: exact propagation is polynomial. For cycles: Loopy BP with damping.

Source: Pearl, *Probabilistic Reasoning in Intelligent Systems* (1988), Chapter 4.

### Value of Information (VOI)

Expected entropy reduction from running experiment E on dimension i of node n:

```
VOI(E) = H_prior - E_outcome[H_posterior]
```

For Beta(a,b) after one observation:

```
E[H_post] = (a/(a+b)) * H(Beta(a+1, b)) + (b/(a+b)) * H(Beta(a, b+1))
```

Select experiments by argmax VOI(E). This is Bayesian D-optimal experimental design.

Source: Chaloner & Verdinelli, "Bayesian Experimental Design: A Review," *Statistical Science* (1995), 10(3):273-304.

### Speculative Branch Exploration

**Thompson sampling** (already in agentmemory) is the correct exploration strategy for speculative nodes. Sample from each dimension's Beta posterior; nodes with wide distributions (high uncertainty) get sampled at extreme values more often, naturally driving exploration.

UCB1 is the simpler fallback but is frequentist and deterministic. Thompson sampling is the better fit since the existing architecture is already Bayesian.

Source: Chapelle & Li, "An Empirical Evaluation of Thompson Sampling," NeurIPS 2011.

### Progressive Widening

Prevent runaway speculation: at depth d with n evaluations, allow at most C * n^0.5 sub-speculations. This naturally deepens promising branches while limiting shallow fan-out.

Source: Couetoux et al., "Continuous Upper Confidence Trees with Polynomial Exploration," ECML 2011.

### Soft-Closing (Hibernation)

Combine low expected value with high uncertainty:

```
S_hibernate(node) = max_i(mean_i) * (1 - H_joint / H_max)
```

Where H_max = K * ln(2). When S_hibernate < threshold tau, deprioritize the branch. The node retains its Beta parameters and can reopen if new evidence shifts its position. This replaces binary alive/dead with continuous dormancy.

Source: Russo & Van Roy, "Learning to Optimize via Information-Directed Sampling," *Operations Research* (2018), 66(1):230-252.

---

## Prior Art

### What Exists

No existing agentic memory system (Mem0, Letta/MemGPT, Zep, LangMem) implements prospective or speculative memory. All are purely retrospective.

Among cognitive architectures:
- **SOAR** has internal simulation (look-ahead) and episodic memory that can project forward. Closest existing analog.
- **ACT-R** has been extended with "intention chunks" for prospective memory tasks (Loft et al., 2008).
- **CLARION** has a motivational subsystem but no speculative belief representation.

Sources: Laird, *The SOAR Cognitive Architecture* (2012); Loft et al., "Modeling and predicting PM," *Cognitive Psychology* (2008).

### Planning as Inference

Botvinick & Toussaint (2012): reframe planning as posterior inference. Define P(trajectory), condition on optimality O, compute P(trajectory | O=1). A speculative belief = a node in the trajectory prior. Conditioning on desired outcomes = weighting speculative beliefs by expected value.

Source: Botvinick & Toussaint, "Planning as inference," *Trends in Cognitive Sciences*, 16(10), 2012.

### World Models

Dreamer, MuZero, JEPA all predict in abstract representation space, not raw observations. Key patterns: predict belief-state changes (not literal future text), use ensemble disagreement as uncertainty, adapt planning depth based on model confidence.

Sources: Hafner et al., ICLR 2020; Schrittwieser et al., Nature 2020; LeCun, "A Path Towards Autonomous Machine Intelligence," 2022.

### Influence Diagrams

Howard & Matheson (1984): DAGs with decision nodes, chance nodes, utility nodes. Speculative beliefs map to chance nodes. Multi-dimensional uncertainty decomposes naturally: each dimension is a separate chance node. Conditional independence structure preserved, so updating one dimension doesn't require recomputing all others.

Source: Howard & Matheson, "Influence Diagrams," 1984.

### Prospective Memory in Cognitive Science

McDaniel & Einstein (2000): event-based PM triggers through associative retrieval (the cue activates the intention), time-based PM requires self-initiated monitoring. For speculative beliefs: event-based = beliefs with activation conditions ("when the user mentions X, surface this"), time-based = beliefs with temporal triggers.

Source: McDaniel & Einstein, "Strategic and automatic processes in prospective memory retrieval," *Applied Cognitive Psychology*, 2000.

---

## Schema Design

### New Columns on beliefs Table

```sql
-- Temporal direction: 'backward' (factual) or 'forward' (speculative)
ALTER TABLE beliefs ADD COLUMN temporal_direction TEXT NOT NULL DEFAULT 'backward';

-- Multi-dimensional uncertainty (JSON array of [alpha, beta] pairs)
-- NULL for backward-looking beliefs (they use the existing alpha/beta_param columns)
ALTER TABLE beliefs ADD COLUMN uncertainty_vector TEXT;

-- Hibernation score (computed, updated on evidence)
ALTER TABLE beliefs ADD COLUMN hibernation_score REAL;

-- Activation condition (for event-based prospective beliefs)
ALTER TABLE beliefs ADD COLUMN activation_condition TEXT;
```

### New Edge Types

```
SPECULATES   -- current state -> possible future
DEPENDS_ON   -- speculative node -> condition that must be true
RESOLVES     -- evidence/experiment -> speculative node (with dimension + outcome)
HIBERNATED   -- soft-closed branch, retains parameters
```

### Retrieval Integration

- Forward-looking beliefs excluded from ba protocol injection by default (they're hypotheses, not facts)
- Retrieved by `/mem:wonder` and `/mem:reason` explicitly
- H_joint ranking for "where is uncertainty highest?"
- VOI ranking for "what experiment would help most?"

---

## Connection to Existing Architecture

| Existing Feature | Speculative Extension |
|---|---|
| Single Beta(alpha, beta) per belief | Vector of K Beta pairs per speculative belief |
| Thompson sampling for exploration | Same algorithm, applied per-dimension on speculative nodes |
| SUPERSEDES edges for corrections | RESOLVES edges for evidence updates on speculative dimensions |
| Temporal decay (backward) | Hibernation score (forward): dormancy instead of decay |
| FTS5 + HRR retrieval | Same retrieval for finding relevant speculative nodes |
| Feedback loop (used/ignored/harmful) | Training signal for learned value function on speculative patterns |
| Ba protocol injection (3 zones) | Optional 4th zone: "OPEN QUESTIONS" for high-entropy speculative nodes |

---

## What This Enables

The user described it: "given the current project status, what directions could we go in and where are the forks in the road where uncertainty explodes and what actions can we take to either spawn new nodes to explore, or close off the node entirely."

With this architecture:
1. Wonder generates speculative nodes with Beta(1,1) on all dimensions (maximum entropy)
2. Each wonder result links to current state via SPECULATES edges
3. Reason runs experiments that update specific dimensions via RESOLVES edges
4. H_joint ranking shows where uncertainty is highest
5. VOI ranking shows which experiment would reduce uncertainty most
6. Progressive widening prevents speculation from growing unboundedly
7. Hibernation keeps dead-end branches available for revival if conditions change
