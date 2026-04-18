# Spectrum Feedback: Valence Propagation Through the Belief Graph

Status: Design proposal (2026-04-17)
Origin: Session case study (docs/case_study_rhizome_session.jsonl)

## Problem

The current feedback system has three discrete outcomes:

```
feedback(belief_id, "used")    -> alpha += 1.0
feedback(belief_id, "ignored") -> no change
feedback(belief_id, "harmful") -> beta += 1.0
```

This loses information in four ways:

1. **No gradient.** A mediocre belief gets the same treatment as an
   irrelevant one (both are "ignored" = zero update).

2. **No positive corrections.** `correct()` captures "you were wrong."
   There is no "you were right, reinforce this." The user saying "beautiful"
   is strong positive evidence that gets discarded.

3. **No graph-level propagation.** Feedback updates a single belief's
   alpha/beta. The edges connecting it to related beliefs barely move
   (7 explicit feedbacks ever recorded; 99.96% of the graph untouched).

4. **Feedback = retrieval optimization, not graph evolution.** The current
   design treats feedback as "rank this higher next time." But the user's
   intent is different: feedback should change the *structure* of the graph
   itself -- which edges strengthen, which weaken, how confidence flows
   between beliefs, what relationships emerge or dissolve.

## Key insight: valence, not ranking

**Valence** (borrowed from chemistry/psychology): the charge carried by a
feedback signal as it propagates through the graph.

In chemistry, valence determines bonding capacity between atoms. In this
system, valence determines how feedback signals affect the bonding structure
(edges) between beliefs.

When the user says "beautiful":
- Wrong interpretation: "retrieve these same beliefs next time" (ranking)
- Right interpretation: "the relationships between beliefs that produced
  this response are correct; strengthen those edges, let confidence flow
  through the subgraph, and let connected beliefs benefit" (valence
  propagation)

The distinction: ranking changes what surfaces. Valence changes what the
graph *is*.

## Test results informing this design (2026-04-17)

| Test | Finding | Design implication |
|------|---------|-------------------|
| Noise filtering | 99.5% of user_stated beliefs already have confidence >= 0.85 | Confidence thresholds are useless for filtering. The graph needs a *different* dimension -- edge strength, not node confidence. |
| Feedback coverage | 7/39,481 beliefs have explicit feedback (0.04%) | The Bayesian updater is starving. Valence propagation is essential: each feedback signal must ripple outward, not just update one node. |
| Session quality sim | sqrt(n) dilution with 223 beliefs = +0.0003 delta | Uniform distribution across all retrieved beliefs is too diluted. Propagation must be *structured* (follow edges) not *uniform* (divide equally). |

## Design

### 1. Continuous valence replaces discrete outcomes

```
valence  meaning                        update
------   ----------------------------   ----------------
+1.0     confirmed, exactly right       alpha += 1.0
+0.5     used, helpful                  alpha += 0.5
 0.0     retrieved but irrelevant       no change
-0.3     weak, misleading but minor     beta += 0.3
-1.0     harmful, actively wrong        beta += 1.0
```

Discrete outcomes become aliases (backward-compatible):

```python
VALENCE_MAP: dict[str, float] = {
    "confirmed": +1.0,
    "used":      +0.5,
    "ignored":    0.0,
    "weak":      -0.3,
    "harmful":   -1.0,
}
```

### 2. Valence propagation (the core change)

When a belief receives feedback, the valence propagates through the graph
with exponential decay per hop:

```
hop 0: belief itself          valence * 1.0
hop 1: direct neighbors       valence * decay_factor * edge_weight
hop 2: neighbors of neighbors valence * decay_factor^2 * edge_weight_product
...stops at hop N or when valence drops below threshold
```

**Edge-type modulation**: not all edges carry valence equally.

| Edge type | Valence multiplier | Rationale |
|-----------|-------------------|-----------|
| SUPPORTS | 1.0 (full propagation) | Supporting beliefs should co-strengthen |
| CO_OCCURRED | 0.5 (half propagation) | Co-occurrence is weaker than semantic support |
| CONTRADICTS | -0.5 (inverted propagation) | Confirming A should weaken what A contradicts |
| SUPERSEDES | 0.0 (no propagation) | Superseded beliefs are historical, not active |
| ELABORATES | 0.7 (strong propagation) | Elaborations are closely tied to parent |
| DEPENDS_ON | 0.8 (strong propagation) | Dependencies should share fate |

Critically: CONTRADICTS edges **invert** the valence. Confirming belief A
(+1.0) propagates as -0.5 to beliefs that contradict A. This is how the
graph self-corrects: reinforcing one side of a contradiction weakens the
other side *automatically*, without anyone explicitly marking the other
side as harmful.

### 3. Positive corrections: `confirm()`

```python
def confirm(belief_id: str, detail: str = "") -> str:
    """Confirm a belief is correct. Positive counterpart to correct().

    Applies valence +1.0 with weight 2.0 (stronger than inferred "used").
    Propagates through connected edges per valence propagation rules.
    Does NOT create a new belief (unlike correct()). Reinforces the existing
    graph structure around this belief.
    """
```

### 4. Session-level valence: structured, not uniform

Instead of dividing session quality equally across all retrieved beliefs,
propagate session valence through the *retrieval subgraph*:

1. Identify all beliefs retrieved during the session
2. Build the induced subgraph (edges between retrieved beliefs)
3. Identify hub beliefs (high degree within the subgraph)
4. Apply valence starting from hubs, propagating outward through the
   subgraph edges

This means beliefs that were structurally central to the session's
reasoning get more credit than peripherally-retrieved ones. The graph
topology determines credit assignment, not equal distribution.

```python
def session_quality(score: float, detail: str = "") -> str:
    """Rate session quality. Propagates valence through retrieval subgraph.

    Hub beliefs (high connectivity within the session's retrievals) receive
    more valence. Peripheral beliefs receive attenuated valence via edge
    propagation.

    Score: -1.0 (memory was counterproductive) to +1.0 (memory was essential)
    """
```

### 5. Auto-feedback with gradient

The existing auto-feedback (key-term overlap) produces a continuous valence
instead of binary used/ignored:

```python
overlap_ratio = matched_terms / total_belief_terms
valence = overlap_ratio  # 0.0 to 1.0, continuous
```

This signal also propagates through edges. A belief with 60% term overlap
gets valence +0.6, which propagates at +0.6 * decay to its SUPPORTS
neighbors, +0.6 * -0.5 to its CONTRADICTS neighbors, etc.

### 6. Emergent graph behaviors from valence propagation

These behaviors fall out of the design without explicit implementation:

**Cluster strengthening.** When a user confirms one belief in a tightly
connected cluster, all beliefs in that cluster get a boost. This is
"Hebbian" -- beliefs that are retrieved together and confirmed together
strengthen their mutual connections.

**Contradiction resolution.** When one side of a contradiction receives
positive valence, the other side receives negative valence through the
inverted CONTRADICTS edge. Over multiple sessions, the graph naturally
resolves contradictions by strengthening the confirmed side and weakening
the contradicted side.

**Stale subgraph decay.** Beliefs that are never retrieved never receive
valence (positive or negative). Their confidence stays static. Combined
with temporal decay, unretrieved subgraphs gradually fade. This is natural
pruning -- the graph forgets what it doesn't use.

**Quality amplification.** High-quality beliefs accumulate valence from
multiple sessions, which propagates to strengthen their edges, which makes
them more likely to surface (higher edge-weighted paths), which exposes
them to more feedback, which further strengthens them. This is the
self-reinforcing loop, bounded by the decay_factor preventing runaway.

## Experimental validation (2026-04-17)

Three tests run against live database (15,630 beliefs, 24,197 edges):

### Test 1: Propagation coverage from current feedback seeds

Only 3 active beliefs have explicit feedback. Their edge degrees: 0, 1, 1.
Propagating 3 hops with decay=0.5 reaches 19 active beliefs (0.12%).
**Coverage gain: 7.7x, but from a near-zero base (0.019% to 0.12%).**

Root cause: feedback landed on leaf nodes. The 3 seeds are nearly isolated
from the giant component (8,166 nodes). Propagation has nothing to traverse.

### Test 2: Graph topology supports valence propagation

The graph has the right structure for propagation to work:
- Giant component: 8,166 nodes (62% of connected beliefs)
- 1,357 connected components total (giant + dust topology)
- 612 CONTRADICTS edges (inversion design is viable)
- Superconnector: REQ-003 (token budget constraint), degree 22
- Avg degree: 3.69, median: 3, max: 22
- 32.7% of beliefs are completely isolated (no edges)

If the same 3 feedbacks had landed on hub nodes (degree 10+), propagation
would have reached thousands of beliefs instead of 19.

### Test 3: Hub-weighted vs uniform session quality

Session 21cbe8aee4eb: 224 beliefs retrieved, 222 edges in induced subgraph.
Hub beliefs (degree 8-9) at mid-confidence (0.71) get +0.002 with hub
weighting vs +0.0004 with uniform distribution -- 5x more leverage.
High-confidence beliefs (0.91+) barely move under either scheme.

**Key finding: hub weighting has the most impact on mid-confidence
connectors, which is exactly where the Bayesian prior is still malleable.**

### Design implication: feedback routing

Valence propagation is the right mechanism, but the feedback acquisition
strategy matters more than the propagation math. The system should:

1. **Route auto-feedback to hub nodes first.** When processing a retrieval
   batch, score beliefs by degree * overlap_ratio, not just overlap_ratio.
   High-degree beliefs with term overlap get priority feedback.
2. **Session quality should weight by subgraph centrality**, not uniform
   distribution. The induced subgraph of retrieved beliefs already has the
   structure needed -- use degree centrality within that subgraph.
3. **Isolated beliefs (32.7%) need edge creation**, not just feedback.
   Valence propagation can't reach them. The onboard pipeline should be
   more aggressive about edge detection for new beliefs.

## Schema changes

```sql
-- Tests table: continuous valence alongside discrete outcome
ALTER TABLE tests ADD COLUMN valence REAL;

-- Sessions table: quality rating
ALTER TABLE sessions ADD COLUMN quality_score REAL;

-- Edges table already has alpha/beta_param -- no changes needed.
-- Edge propagation uses existing update_edge_confidence().
```

## Parameters to tune

| Parameter | Initial value | What it controls |
|-----------|--------------|-----------------|
| decay_factor | 0.5 | How fast valence attenuates per hop |
| max_hops | 3 | How far valence propagates |
| min_valence | 0.05 | Below this, propagation stops |
| confirm_weight | 2.0 | Weight multiplier for explicit confirm() |
| session_hub_boost | 2.0 | Extra weight for hub beliefs in session_quality |

## Backward compatibility

- `feedback()` still accepts string outcomes. Mapped to valence via VALENCE_MAP.
- Existing test_results remain valid. `valence` column is nullable.
- `update_confidence()` unchanged for single-belief updates.
- Valence propagation is additive to existing behavior, not replacing it.

## Experiments to validate

| # | Question | Method | Success |
|---|----------|--------|---------|
| 1 | Does valence propagation increase feedback coverage beyond 0.04%? | Apply 10 explicit feedbacks, count beliefs touched by propagation | >5% of graph touched |
| 2 | Does CONTRADICTS inversion resolve synthetic contradictions? | Create 10 contradiction pairs, confirm one side, measure other side's confidence | Contradicted side drops below 0.5 within 3 feedback cycles |
| 3 | Does hub-weighted session_quality outperform uniform distribution? | Compare confidence delta distributions: hub-weighted vs uniform | Hub-weighted produces bimodal (high for hubs, low for periphery) vs uniform's negligible flat delta |
| 4 | Does runaway feedback occur? | Simulate 50 sessions with +1.0 quality on a 500-belief graph | No belief exceeds 0.99 confidence |
| 5 | Case study: rhizome session | Apply session_quality(+1.0) to the case study session with valence propagation | Beliefs directly used in wonder/reason get measurably higher delta than peripherally retrieved beliefs |

## Relationship to other designs

- **Rhizome architecture**: valence propagation within a vault is the model
  for "nutrient flow" between vaults. Cross-vault valence would flow through
  promoted_beliefs edges in rhizome.db, with stronger decay (decay_factor^2)
  to respect vault boundaries.
- **Wonder/Reason pipeline**: wonder produces hypotheses. If reasoning
  confirms them, the seed beliefs receive positive valence via confirm().
  If reasoning rejects them, the seeds receive negative valence. The graph
  evolves in response to research outcomes.
- **Locked beliefs**: valence propagation *through* locked beliefs to their
  neighbors is allowed. Locked beliefs themselves resist confidence change
  (existing LOCKED_EVIDENCE_THRESHOLD), but they still conduct valence to
  connected beliefs -- like a fixed node in a vibrating network.
