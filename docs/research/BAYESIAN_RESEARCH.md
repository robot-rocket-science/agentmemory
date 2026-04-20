# Bayesian Methods for Agentic Memory Systems

**Date:** 2026-04-09
**Status:** Research complete -- ready for implementation decisions
**Purpose:** Concrete, practical answers to how Bayesian inference applies to the scientific memory model (observations/beliefs/tests/revisions)

---

## 1. Bayesian Belief Updating for Memory Confidence

### The Core Formula

Bayes' theorem applied to belief confidence:

```
P(belief_correct | evidence) = P(evidence | belief_correct) * P(belief_correct) / P(evidence)
```

For our system, translate this to:

- **P(belief_correct)** = current confidence (the prior)
- **P(evidence | belief_correct)** = likelihood that we'd see this evidence if the belief is correct
- **P(evidence)** = normalizing constant (marginal likelihood of the evidence)

### Beta Distribution Implementation (Recommended)

Instead of tracking a single confidence float, each belief maintains two parameters: **alpha** (success count) and **beta** (failure count). This is the Beta-Bernoulli conjugate pair, which means updates are simple addition -- no MCMC, no numerical integration.

```
Prior:     Beta(alpha, beta)
Posterior: Beta(alpha + successes, beta + failures)

Confidence (point estimate): alpha / (alpha + beta)
Uncertainty:                 alpha * beta / ((alpha + beta)^2 * (alpha + beta + 1))
```

**What "success" and "failure" mean for beliefs:**

| Test Outcome | Update |
|---|---|
| USED (belief retrieved, agent cited it, good outcome) | alpha += 1 |
| HARMFUL (belief retrieved, agent used it, bad outcome) | beta += 1 |
| CONTRADICTED (new evidence directly contradicts) | beta += 1 (or += weight, see Section 3) |
| IGNORED | No update (see rationale below) |
| Corroborating observation arrives | alpha += evidence_weight |
| Contradicting observation arrives | beta += evidence_weight |

**Why IGNORED gets no update:** A belief about database configuration is irrelevant to a CSS task. Ignoring it says nothing about its correctness. This is the "absence of evidence is not evidence of absence" principle, and it's critical -- without it, niche-but-correct beliefs decay to zero simply because they're rarely relevant.

**Schema change required:** Replace the single `confidence REAL` column with:

```sql
ALTER TABLE beliefs ADD COLUMN alpha REAL NOT NULL DEFAULT 1.0;
ALTER TABLE beliefs ADD COLUMN beta_param REAL NOT NULL DEFAULT 1.0;
-- Keep confidence as a computed column or update it on each change:
-- confidence = alpha / (alpha + beta_param)
```

### Cold-Start Problem

New beliefs have no test history. The question: what initial alpha/beta values?

**Option A: Uniform prior Beta(1,1)**
- Confidence starts at 0.5
- Maximum uncertainty
- Problem: a user-stated fact and an agent-inferred guess start equal

**Option B: Source-informed priors (Recommended)**
- Encode source reliability into the initial parameters
- The prior alpha/beta ratio sets the initial confidence
- The prior magnitude (alpha + beta) sets how much evidence is needed to move it

| Belief Source | alpha | beta | Initial Confidence | Prior Strength | Rationale |
|---|---|---|---|---|---|
| User-stated | 9 | 1 | 0.90 | 10 (moderate) | Users are usually right about their own facts, but not infallible. ~10 contradicting tests to overcome. |
| Document-extracted | 7 | 3 | 0.70 | 10 (moderate) | Documents are probably correct but could be stale. |
| Agent-inferred | 1 | 1 | 0.50 | 2 (weak) | Genuinely uncertain. Moves quickly with any evidence. |
| Cross-reference match | 3 | 2 | 0.60 | 5 (weak-moderate) | Two sources agreed, slightly better than random. |
| User-corrected | 19 | 1 | 0.95 | 20 (strong) | Explicit correction is the strongest signal. Takes ~20 contradictions to overcome. |

The key insight: **prior strength controls learning rate.** A Beta(9,1) belief needs 9 failure signals to reach 50% confidence. A Beta(1,1) belief reaches 50% after just 1 failure. This naturally encodes that user-stated facts should be harder to dislodge than agent guesses.

This maps cleanly onto PLAN.md's current static priors (0.9, 0.7, 0.5, 0.6) while adding the critical dimension of uncertainty quantification that a single float cannot express.

Source: The Beta-Bernoulli conjugate pair is standard Bayesian statistics. See [MIT 18.05 Class Notes on Conjugate Priors](https://math.mit.edu/~dav/05.dir/class15-prep.pdf) for the mathematical foundation. MACLA (Forouzandeh et al., arXiv:2512.18950) validates this approach specifically for LLM agent procedural memory.

---

## 2. Prior Selection for Different Belief Types

Beyond source-based priors, belief *type* should also influence the prior:

### Factual Claims ("Alice works at Anthropic")

- **Prior:** Beta(7, 3) for document-sourced, Beta(9, 1) for user-stated
- **Decay consideration:** Factual claims have temporal validity. Rather than decaying the Beta parameters over time, use the `valid_from`/`valid_to` fields already in the schema. When a fact is past its validity window, it's not "less confident" -- it's "potentially stale," which is a different status.
- **Conflict behavior:** When two factual claims contradict, both get a beta increment. The one with stronger evidence (higher alpha) naturally wins in ranking.

### User Preferences ("User prefers concise responses")

- **Prior:** Beta(3, 1) when first inferred, Beta(9, 1) when user-stated
- **Key property:** Preferences change intentionally, not because they were wrong. A preference revision should reset the Beta parameters (creating a new belief via the revision mechanism), not accumulate failure counts on the old one.
- **Special handling:** Track preference stability. A preference that gets revised frequently (3+ times in 10 sessions) should have a weaker prior on its latest incarnation -- the system is uncertain about this preference because the user keeps changing it.

### Procedural Knowledge ("To deploy, run X then Y then Z")

- **Prior:** Beta(1, 1) -- start uncertain regardless of source
- **Rationale:** Procedures are either correct or they aren't, and the only way to know is to test them. A user might state a procedure confidently but misremember a step. Initial evidence count should be low.
- **Update weight:** Procedural tests should carry heavier weight. If a procedure was followed and succeeded, alpha += 2. If it was followed and failed, beta += 3. Procedures that fail are more costly than facts that are wrong.
- **MACLA precedent:** MACLA uses exactly this approach -- Beta posteriors over procedure success probability with expected-utility scoring. They found it effective across ALFWorld, WebShop, TravelPlanner, and InterCodeSQL benchmarks (78.1% average, arXiv:2512.18950).

### Relationship Claims ("Module A depends on Module B")

- **Prior:** Beta(2, 1) for agent-inferred, Beta(5, 1) for document-extracted
- **Graph interaction:** Relationship claims map naturally to edges in the belief graph. The Beta parameters on the relationship belief provide a principled weight for the edge, replacing the current static `weight REAL DEFAULT 1.0` on the edges table.
- **Transitivity:** If A->B has confidence 0.8 and B->C has confidence 0.7, the transitive confidence A->C = 0.8 * 0.7 = 0.56. This is the standard independence assumption and it's often wrong (violations discussed in Section 8), but it's a useful starting point.

---

## 3. Bayesian Evidence Weighting

### Source Credibility as Likelihood Weighting

Not all evidence is equal. A user explicitly stating something is stronger evidence than an agent inferring it from a pattern. We can encode this in the update step:

```
For observation o supporting belief b:
  alpha_new = alpha + source_weight(o) * relationship_strength(o, b)

For observation o contradicting belief b:
  beta_new = beta + source_weight(o) * relationship_strength(o, b)
```

**Source weights:**

| Source Type | Weight | Justification |
|---|---|---|
| User explicit statement | 1.0 | Highest credibility baseline |
| User correction | 1.5 | Corrections are deliberate; they overcome prior beliefs |
| Document (recent, primary) | 0.8 | Documents are usually right but can be stale |
| Document (old, secondary) | 0.4 | Age and indirection reduce reliability |
| Agent inference (high-conf) | 0.5 | Agent is guessing, even when confident |
| Agent inference (low-conf) | 0.2 | Weak signal |
| Cross-reference (2+ sources) | 0.9 | Independent confirmation is strong |

### Hierarchical Bayesian Model

A full hierarchical model would look like this:

```
Level 1 (source reliability):
  source_reliability_j ~ Beta(a_j, b_j)     -- each source j has a reliability estimate

Level 2 (belief truth):
  belief_correct_i ~ Beta(alpha_i, beta_i)   -- each belief i has truth probability

Level 3 (observation):
  P(observe o_k | belief_i correct, source_j reliable) = f(reliability_j, truth_i)
```

**Practical recommendation: Don't implement the full hierarchy for v1.** The computational cost of hierarchical Bayesian inference (even with conjugate priors) grows with the number of sources and beliefs. For v1, use the flat source weights above. Track source reliability informally via the audit log. Revisit the full hierarchy if source credibility divergence becomes a measurable problem.

The BEWA framework (arXiv:2506.16015) provides a more elaborate evidence weighting scheme with replication scoring, epistemic distinctiveness, and citation cascade penalties, but that's designed for scientific literature synthesis, not agent memory. The complexity is not justified here.

### Evidence Relationship Strength

The `relationship` field in the evidence table (supports/weakens/contradicts) can carry a continuous strength:

```
relationship_strength:
  "supports"     ->  1.0 (direct evidence for the belief)
  "weakens"      ->  0.5 (indirect evidence against)
  "contradicts"  ->  1.0 (direct evidence against)
```

So a weak source providing indirect evidence against a belief would update:
```
beta_new = beta + 0.2 (source) * 0.5 (relationship) = beta + 0.1
```

This is a small nudge, which is correct -- weak indirect evidence shouldn't move confidence much.

---

## 4. Bayesian Conflict Resolution

### The Problem

When two beliefs contradict (e.g., "Alice works at Anthropic" vs "Alice works at Google"), the system needs to determine which is more likely correct. Current SOTA on multi-hop conflict resolution is 7% accuracy -- essentially random.

### Bayesian Approach

With Beta distributions on both beliefs, comparison is straightforward:

```
P(belief_A correct | evidence) vs P(belief_B correct | evidence)

If Beta(alpha_A, beta_A) vs Beta(beta_B, beta_B):
  Point estimate: alpha_A/(alpha_A + beta_A) vs alpha_B/(alpha_B + beta_B)

  More principled: P(p_A > p_B) where p_A ~ Beta(alpha_A, beta_A), p_B ~ Beta(alpha_B, beta_B)
  -- This can be computed exactly but is expensive. For practical purposes, compare means
     and use variance as a tiebreaker (prefer the belief with lower uncertainty).
```

### Conflict Resolution Protocol

```
When CONTRADICTS edge is detected between belief_A and belief_B:

1. Compare posterior means:
   mean_A = alpha_A / (alpha_A + beta_A)
   mean_B = alpha_B / (alpha_B + beta_B)

2. If |mean_A - mean_B| > threshold (e.g., 0.2):
   -- Clear winner. Present the higher-confidence belief.
   -- But still surface the conflict in provenance metadata.

3. If |mean_A - mean_B| <= threshold:
   -- Genuinely uncertain. Present BOTH beliefs with their evidence chains.
   -- Let the agent or user resolve.
   -- This is the honest answer: the system doesn't know which is right.

4. After resolution:
   -- Winner: alpha += resolution_weight
   -- Loser: beta += resolution_weight, superseded_by -> winner
   -- Resolution recorded as a test outcome
```

### Why Bayesian Helps (and Why 7% is Still Hard)

Bayesian confidence helps with **single-hop** conflicts where one belief has much better evidence than another. It doesn't help with **multi-hop** conflicts where the contradiction is indirect (A->B, B->C, but A->C' contradicts C). Multi-hop requires reasoning across the graph, which is a fundamentally harder problem.

For multi-hop, the system would need to propagate confidence along edges:

```
Transitive confidence: P(A->C via B) = P(A->B) * P(B->C)
-- Under independence assumption (usually violated)
```

GaussianPath (Wan et al., AAAI 2021) addresses this by representing entities and relations as Gaussian distributions rather than point embeddings, allowing uncertainty to propagate through multi-hop reasoning paths. Their Bayesian Q-learning architecture estimates expected long-term reward under uncertainty. This is a research direction, not a production technique.

**Practical v1 approach:** Detect conflicts. Present both beliefs with evidence. Let the consumer decide. Log the resolution. Learn from it. Don't try to auto-resolve multi-hop conflicts -- the field hasn't solved this and pretending otherwise is dishonest.

Sources:
- [GaussianPath: Bayesian Multi-Hop Reasoning (AAAI 2021)](https://ojs.aaai.org/index.php/AAAI/article/view/16565)
- [Detect-Then-Resolve: KG Conflict Resolution with LLMs](https://www.mdpi.com/2227-7390/12/15/2318)
- [RANA: Conflict Resolution for Knowledge Graphs](https://link.springer.com/chapter/10.1007/978-981-95-5009-8_9)

---

## 5. Bayesian Retrieval Ranking

### Current Plan (from PLAN.md)

The current retrieval ranking is: relevance * confidence * (implicit recency from layer selection). This is ad hoc.

### Bayesian Alternative: Posterior Predictive Ranking

Instead of `score = relevance * confidence`, use:

```
score(belief_i | query_q) = P(useful_i | query_q, history_i)
```

Where "useful" means the belief will be used and lead to a good outcome (a TRUE POSITIVE in the retrieval confusion matrix).

**Generative model:**

```
P(useful_i | query_q, history_i) ∝ P(query_q | useful_i, belief_i) * P(useful_i | history_i)

Where:
  P(query_q | useful_i, belief_i) = relevance (text similarity, graph proximity)
  P(useful_i | history_i)         = posterior from Beta distribution (alpha_i / (alpha_i + beta_i))
```

This decomposes naturally:

```
score = relevance(query, belief) * posterior_confidence(belief)
```

Which looks like the current plan -- but with a critical difference: **posterior_confidence is now a proper probability** with known uncertainty, not an arbitrary float.

### MACLA's Expected Utility Scoring (Proven Approach)

MACLA (arXiv:2512.18950) implements a more sophisticated version:

```
EU(belief_i | query) = Rel_i(query) * (alpha_i / (alpha_i + beta_i)) * R_max
                     - Risk_i(query) * (beta_i / (alpha_i + beta_i)) * C_fail
                     + lambda_info * H[Beta(alpha_i, beta_i)]
```

Three terms:
1. **Expected reward:** relevance * success probability * max reward
2. **Expected cost:** risk * failure probability * failure cost
3. **Exploration bonus:** entropy of the Beta distribution (high entropy = uncertain = worth testing)

The exploration bonus is particularly interesting for our system. A belief with Beta(1,1) (totally uncertain) has high entropy and gets a ranking boost -- the system is incentivized to *test* uncertain beliefs, not just retrieve high-confidence ones. This is how the feedback loop actively learns rather than just passively reinforcing what's already confident.

**Recommended v1 implementation:**

```python
import math
from scipy.stats import beta as beta_dist

def score_belief(belief, query_relevance, config):
    alpha = belief.alpha
    beta_val = belief.beta_param

    # Posterior mean (success probability)
    posterior_mean = alpha / (alpha + beta_val)

    # Posterior variance (uncertainty)
    posterior_var = (alpha * beta_val) / ((alpha + beta_val)**2 * (alpha + beta_val + 1))

    # Beta distribution entropy (exploration bonus)
    entropy = beta_dist.entropy(alpha, beta_val)

    # Expected utility
    reward = query_relevance * posterior_mean
    risk = query_relevance * (1 - posterior_mean) * config.failure_cost_weight
    exploration = config.exploration_weight * entropy

    return reward - risk + exploration
```

This is MACLA's formula simplified for our use case. The exploration_weight should start small (0.05-0.1) and can be tuned based on test outcome data.

### Comparison with Probability Ranking Principle

The classical Probability Ranking Principle (Robertson, 1977) states that documents should be ranked by P(relevant | document, query) for optimal retrieval. Our scoring function is consistent with this principle -- it estimates P(useful | belief, query) -- but adds the failure cost and exploration terms that make it suitable for an active learning context rather than a static retrieval one.

Source: [Stanford NLP: Probabilistic Information Retrieval (Ch. 11)](https://nlp.stanford.edu/IR-book/pdf/11prob.pdf)

---

## 6. Practical Implementation

### Minimal Implementation (Recommended for v1)

The simplest implementation that captures key Bayesian benefits:

```python
from dataclasses import dataclass
from math import lgamma, exp, log

@dataclass
class BayesianBelief:
    """Belief with Beta-distributed confidence."""
    alpha: float  # success count (evidence for)
    beta: float   # failure count (evidence against)

    @property
    def confidence(self) -> float:
        """Posterior mean: point estimate of P(belief is correct)."""
        return self.alpha / (self.alpha + self.beta)

    @property
    def uncertainty(self) -> float:
        """Posterior variance: how unsure we are."""
        total = self.alpha + self.beta
        return (self.alpha * self.beta) / (total * total * (total + 1))

    @property
    def evidence_count(self) -> float:
        """Total evidence accumulated (prior strength + observations)."""
        return self.alpha + self.beta

    def update(self, outcome: str, weight: float = 1.0):
        """Update belief based on test outcome or new evidence."""
        if outcome in ("used", "supports", "corroborated"):
            self.alpha += weight
        elif outcome in ("harmful", "contradicts", "failed"):
            self.beta += weight
        elif outcome == "ignored":
            pass  # No update -- absence of evidence != evidence of absence

    @classmethod
    def from_source(cls, source_type: str) -> "BayesianBelief":
        """Create belief with source-appropriate prior."""
        priors = {
            "user_stated":       (9.0, 1.0),
            "user_corrected":    (19.0, 1.0),
            "document_recent":   (7.0, 3.0),
            "document_old":      (4.0, 3.0),
            "agent_inferred":    (1.0, 1.0),
            "cross_reference":   (3.0, 2.0),
        }
        alpha, beta = priors.get(source_type, (1.0, 1.0))
        return cls(alpha=alpha, beta=beta)

    def credible_interval(self, width: float = 0.9) -> tuple[float, float]:
        """Bayesian credible interval for the true confidence.

        Unlike a frequentist confidence interval, this has the intuitive
        interpretation: 'there is a 90% probability that the true confidence
        lies in this interval.'
        """
        from scipy.stats import beta as beta_dist
        tail = (1 - width) / 2
        lower = beta_dist.ppf(tail, self.alpha, self.beta)
        upper = beta_dist.ppf(1 - tail, self.alpha, self.beta)
        return (lower, upper)
```

### Schema Changes

```sql
-- Replace single confidence column with Beta parameters
-- Keep confidence as a derived value for backward compatibility and indexing
ALTER TABLE beliefs ADD COLUMN alpha REAL NOT NULL DEFAULT 1.0;
ALTER TABLE beliefs ADD COLUMN beta_param REAL NOT NULL DEFAULT 1.0;

-- Add trigger to keep confidence in sync (or compute in application layer)
-- confidence = alpha / (alpha + beta_param)

-- Add source_weight to evidence table for weighted updates
ALTER TABLE evidence ADD COLUMN source_weight REAL DEFAULT 1.0;

-- Index for efficient conflict detection
CREATE INDEX idx_beliefs_confidence ON beliefs(confidence DESC);
CREATE INDEX idx_beliefs_type_confidence ON beliefs(belief_type, confidence DESC);
```

### Computational Cost

| Operation | Cost | Notes |
|---|---|---|
| Update alpha/beta | O(1) | Addition |
| Compute confidence | O(1) | Division |
| Compute uncertainty | O(1) | Arithmetic |
| Compute entropy | O(1) | Beta entropy is closed-form with gamma functions |
| Credible interval | O(1) | Inverse CDF of Beta distribution (scipy) |
| Compare two beliefs | O(1) | Compare means, use variance as tiebreaker |

**No MCMC. No variational inference. No GPU.** The entire Bayesian layer is arithmetic on two floats per belief. This is the core advantage of conjugate priors -- the posterior stays in the same family as the prior, so updating is just parameter arithmetic.

The only dependency is scipy for credible intervals and entropy, and even that could be replaced with pure-Python implementations of the Beta function if needed.

---

## 7. Existing Work

### Directly Relevant Systems

**MACLA (arXiv:2512.18950, Dec 2025)**
- Learning Hierarchical Procedural Memory for LLM Agents through Bayesian Selection and Contrastive Refinement
- Uses Beta posteriors over procedure success probability
- Expected-utility scoring with relevance, risk, and exploration terms
- 78.1% average across 4 benchmarks
- **Most directly applicable to our system.** Their Bayesian selection mechanism maps almost 1:1 to our belief ranking.
- [Paper](https://arxiv.org/abs/2512.18950) | [GitHub](https://github.com/S-Forouzandeh/MACLA-LLM-Agents-AAMAS-Conference)

**SuperLocalMemory (arXiv:2603.02240, Mar 2026)**
- Privacy-Preserving Multi-Agent Memory with Bayesian Trust Defense
- Uses Beta-Binomial posterior for trust scoring of agents/sources
- Trust separation of 0.90 between benign and malicious agents
- 72% trust degradation for sleeper attacks
- Asymmetric signal magnitudes (negative signals larger than positive)
- Trust formula: t_{i+1} = t_i + delta * 1/(1 + n * eta), where eta = 0.01
- Limitation they acknowledge: trust scores don't yet feed into retrieval ranking
- [Paper](https://arxiv.org/abs/2603.02240) | [GitHub](https://github.com/qualixar/superlocalmemory)

**SuperLocalMemory V3.3 (arXiv:2604.04514, Apr 2026)**
- "The Living Brain" -- adds biologically-inspired forgetting and cognitive quantization
- Multi-channel retrieval
- Evolved the trust scoring from V1 but core Beta-Binomial approach unchanged
- [Paper](https://arxiv.org/abs/2604.04514)

**Memory for Autonomous LLM Agents Survey (arXiv:2603.07670, Mar 2026)**
- Frames agent memory as POMDP belief state
- "Classical POMDP solvers update beliefs via Bayesian filtering; LLM agents do something analogous -- albeit messier -- through natural language compression, vector indexing, or structured storage."
- Identifies the gap: no current system does proper Bayesian belief updating for memory confidence
- [Paper](https://arxiv.org/abs/2603.07670)

### Tangentially Relevant

**"Are LLM Belief Updates Consistent with Bayes' Theorem?" (arXiv:2507.17951, Jul 2025)**
- Tests whether LLMs themselves update beliefs consistently with Bayes' theorem
- Finding: larger models are more Bayesian-coherent, but all models show up to 30% deviation from correct Bayesian posteriors
- Implication for us: don't rely on the LLM to do the Bayesian updating -- do it in the application layer with proper math
- [Paper](https://arxiv.org/abs/2507.17951)

**BEWA: Bayesian Epistemology-Weighted AI Framework (arXiv:2506.16015, Jun 2025)**
- Bayesian evidence weighting for scientific literature
- Multi-dimensional utility: replication score, epistemic distinctiveness, verified influence, citation cascade penalty
- Hierarchical source credibility: reputation, transparency, compliance
- Temporal decay for unreplicated claims
- Overkill for agent memory but good ideas for evidence weighting hierarchy
- [Paper](https://arxiv.org/abs/2506.16015)

**GaussianPath (AAAI 2021)**
- Bayesian multi-hop reasoning on knowledge graphs
- Represents entities/relations as Gaussian distributions, not point embeddings
- Bayesian Q-learning for path selection under uncertainty
- Relevant to the multi-hop conflict resolution problem
- [Paper](https://ojs.aaai.org/index.php/AAAI/article/view/16565)

**Bayesian Knowledge Tracing (Corbett & Anderson, 1994; pyBKT)**
- Classic model for tracking learner knowledge state
- Hidden Markov model with Bayesian updates
- Conceptually similar: tracks P(mastered) for a skill, updates on correct/incorrect observations
- Our system is doing the same thing but for belief correctness instead of skill mastery
- [pyBKT library](https://github.com/CAHLR/pyBKT)

**Bayesian Continual Learning and Forgetting (Nature Communications, 2025)**
- Bayesian learning rule that "scales learning by uncertainty and forgets in a controlled way"
- Key insight: forgetting is a mechanism for adaptation, not just information loss
- Relevant to our belief revision mechanism
- [Paper](https://www.nature.com/articles/s41467-025-64601-w)

### What Nobody Has Done

No published system combines all of:
1. Beta-distributed belief confidence
2. Test-based feedback loop updating those distributions
3. Expected-utility retrieval ranking with exploration bonus
4. Bayesian conflict resolution between contradicting beliefs

MACLA has (1) and (3) for procedural memory only. SuperLocalMemory has (1) for trust scoring only. Nobody has the full pipeline for general belief management in agent memory. This is the gap our system fills.

---

## 8. Pitfalls and Limitations

### Where Bayesian Updating Breaks Down

**1. Independence Assumption Violation**

Bayes' theorem assumes evidence is conditionally independent given the hypothesis. In practice, evidence for beliefs is correlated:

- If observation A supports belief B, and observation A also supports belief C, then B and C are not independent -- they share evidence.
- The same user statement might generate multiple observations that all support the same belief. Treating each as independent evidence inflates confidence.

**Mitigation:** Track evidence provenance. If multiple evidence links trace to the same source observation, discount them. A belief supported by 5 observations from 1 source is not as strong as a belief supported by 5 observations from 5 independent sources.

```python
# Adjust effective evidence count for correlated sources
unique_sources = len(set(e.observation.source_id for e in belief.evidence))
total_evidence = len(belief.evidence)
correlation_discount = unique_sources / total_evidence  # 1.0 = all independent, 0.2 = all from same source
effective_alpha = 1.0 + (belief.alpha - 1.0) * correlation_discount
```

**2. Non-Stationarity**

Bayesian updating assumes the underlying truth is fixed. But beliefs change:

- "Alice works at Anthropic" is true today, false tomorrow (she changed jobs)
- "User prefers TypeScript" is true now, may not be true in 6 months

The Beta distribution accumulates evidence forever, making beliefs increasingly resistant to change as alpha + beta grows. A belief with Beta(100, 2) is nearly impossible to move, even if the underlying truth changed.

**Mitigation:** Temporal windowing. Don't use all-time alpha/beta. Use a sliding window or exponential decay on evidence:

```python
# Option A: Sliding window (only count evidence from last N days)
recent_alpha = sum(1 for e in evidence if e.created_at > cutoff and e.supports)
recent_beta = sum(1 for e in evidence if e.created_at > cutoff and e.contradicts)

# Option B: Exponential decay on evidence weight
# More recent evidence counts more
import math
def decayed_weight(evidence_age_days, half_life=90):
    return math.exp(-0.693 * evidence_age_days / half_life)
```

Better approach for our system: use the **revision mechanism**. When facts change, create a new belief (with fresh Beta parameters) and supersede the old one. The old belief's accumulated evidence is preserved for provenance but doesn't resist the update. This is already in PLAN.md -- the revision pipeline handles non-stationarity structurally rather than mathematically.

**3. Prior Misspecification**

If the source-based priors are wrong (e.g., users are actually wrong 40% of the time, not 10%), the system will be systematically miscalibrated.

**Mitigation:** The calibration test in Phase 5 specifically checks this. Compare predicted confidence (alpha / (alpha + beta)) against actual usefulness rates from test outcomes. If they diverge, adjust the prior parameters.

```python
# Calibration check: bin beliefs by confidence, compare to actual use rate
# If beliefs with 0.9 confidence are only useful 60% of the time,
# the priors are too generous
bins = bucket_beliefs_by_confidence(beliefs, n_bins=10)
for bin in bins:
    predicted = bin.mean_confidence
    actual = bin.use_rate  # from test outcomes
    calibration_error = abs(predicted - actual)
```

This is standard calibration analysis, and it should be a Phase 5 exit criterion.

Source: [Model Misspecification in Simulation-Based Inference (ICLR 2026 Blogpost)](https://iclr-blogposts.github.io/2026/blog/2026/model-misspecification-in-sbi/)

**4. Sparse Feedback**

Most beliefs will never be tested. The feedback loop only fires when a belief is retrieved and the outcome is observable. Beliefs that are rarely relevant accumulate little evidence and their confidence barely moves from the prior.

**Mitigation:** This is actually fine. A belief with Beta(1,1) after 100 sessions is a belief that has never been relevant. Its confidence (0.5) honestly reflects the system's ignorance. The problem is not sparse feedback -- it's that we might want to distinguish "never tested" from "tested and uncertain." The credible interval does this: Beta(1,1) has a 90% CI of [0.05, 0.95], while Beta(50,50) has a 90% CI of [0.42, 0.58]. Same mean, vastly different uncertainty.

**5. Binary Outcome Limitation**

The Beta-Bernoulli model assumes binary outcomes: success or failure. Our test outcomes are richer: USED, IGNORED, HARMFUL, CONTRADICTED. We handle this by mapping to binary (USED/HARMFUL -> alpha/beta update, IGNORED -> no update), but we lose granularity.

**Alternative:** Use a Dirichlet-Multinomial model instead of Beta-Bernoulli, which handles multiple outcome categories. But this adds significant complexity for marginal benefit in v1. The binary mapping is a reasonable simplification.

**6. The LLM Doesn't Reason Bayesianly**

Even if we compute perfect posterior probabilities, the LLM consuming the retrieved beliefs doesn't treat confidence scores as probabilities. An LLM given "confidence: 0.7" and "confidence: 0.3" may not weight them appropriately. Imran et al. (arXiv:2507.17951) found up to 30% deviation from Bayesian coherence in LLM belief updates.

**Mitigation:** Don't rely on the LLM to interpret confidence numerically. Instead:
- Use confidence for **ranking and filtering** (decide which beliefs to retrieve, in what order)
- Present qualitative uncertainty to the LLM: "high confidence (tested 47 times, useful 43 times)" vs "uncertain (never tested)"
- The Bayesian machinery operates in the memory system, not in the LLM's reasoning

---

## 9. Implementation Recommendations for PLAN.md

### Phase 3 (Test + Revise) Changes

The current PLAN.md Phase 3 says: "Bayesian confidence updating: reinforce beliefs that get used, downgrade beliefs that cause harm (starting with Beta distribution conjugate priors -- pending research results)."

**Research results are now in. Specific recommendations:**

1. **Add alpha/beta columns to beliefs table.** Keep `confidence` as a derived column (alpha / (alpha + beta)) for backward compatibility with queries and indexes.

2. **Initialize priors based on source type** using the table in Section 1. This replaces the current static prior assignment.

3. **Update rule:** On test outcome, update alpha/beta with source-weighted increments per Section 3. Map test outcomes to updates per Section 1 table.

4. **Retrieval scoring:** Replace `relevance * confidence` with the expected-utility formula from Section 5. Start with exploration_weight = 0.05.

5. **Conflict resolution:** Implement the protocol from Section 4. Compare posterior means, surface ties for human resolution, log outcomes.

6. **Calibration test:** Add to Phase 5 exit criteria. Compare predicted confidence vs actual usefulness. Adjust priors if calibration error > 0.1.

### What NOT to Implement

- Full hierarchical Bayesian model for source credibility -- overkill for v1
- MCMC or variational inference -- unnecessary with conjugate priors
- Dirichlet-Multinomial for multi-outcome -- binary mapping is sufficient
- Automatic multi-hop conflict resolution -- unsolved problem, be honest about it
- Temporal decay on Beta parameters -- use the revision mechanism instead

---

## 10. Summary

| Question | Answer |
|---|---|
| What distribution? | Beta (conjugate prior for Bernoulli outcomes) |
| What are the priors? | Source-dependent: Beta(9,1) for user-stated, Beta(1,1) for agent-inferred |
| What's the likelihood? | Binary: belief was useful (alpha++) or harmful (beta++) |
| Cold start? | Source-informed priors with appropriate strength |
| Evidence weighting? | Source credibility * relationship strength as multiplier on update |
| Conflict resolution? | Compare posterior means; surface ties for human resolution |
| Retrieval ranking? | Expected utility = relevance * posterior - risk * failure_prob + exploration * entropy |
| Implementation cost? | O(1) per update. Two floats per belief. No MCMC. |
| Key pitfall? | Evidence correlation inflates confidence; mitigate with source dedup |
| Biggest gap in literature? | Nobody combines Beta confidence + feedback loop + exploration-aware retrieval |

Sources:
- [MACLA: Bayesian Selection for LLM Procedural Memory (arXiv:2512.18950)](https://arxiv.org/abs/2512.18950)
- [SuperLocalMemory: Bayesian Trust Defense (arXiv:2603.02240)](https://arxiv.org/abs/2603.02240)
- [Memory for Autonomous LLM Agents Survey (arXiv:2603.07670)](https://arxiv.org/abs/2603.07670)
- [Are LLM Belief Updates Consistent with Bayes' Theorem? (arXiv:2507.17951)](https://arxiv.org/abs/2507.17951)
- [BEWA: Bayesian Epistemology-Weighted AI (arXiv:2506.16015)](https://arxiv.org/abs/2506.16015)
- [GaussianPath: Bayesian Multi-Hop KG Reasoning (AAAI 2021)](https://ojs.aaai.org/index.php/AAAI/article/view/16565)
- [SuperLocalMemory V3.3 (arXiv:2604.04514)](https://arxiv.org/abs/2604.04514)
- [MIT 18.05: Conjugate Priors](https://math.mit.edu/~dav/05.dir/class15-prep.pdf)
- [Stanford NLP: Probabilistic IR (Ch. 11)](https://nlp.stanford.edu/IR-book/pdf/11prob.pdf)
- [Bayesian Continual Learning (Nature Comms 2025)](https://www.nature.com/articles/s41467-025-64601-w)
- [Model Misspecification in SBI (ICLR 2026)](https://iclr-blogposts.github.io/2026/blog/2026/model-misspecification-in-sbi/)
- [Probabilistic Relevance Framework: BM25 and Beyond](https://www.researchgate.net/publication/220613776_The_Probabilistic_Relevance_Framework_BM25_and_Beyond)
- [pyBKT: Bayesian Knowledge Tracing](https://github.com/CAHLR/pyBKT)
