# Wonder/Reason Pipeline: Research Synthesis

## Origin

On 2026-04-17, the user defined the wonder/reason pipeline: wonder is divergent speculation (broad research, hypothesis generation), reason is convergent testing (hypothesis evaluation, uncertainty reduction). This synthesis documents the formal framework mappings, design decisions, and implementation recommendations from 4 parallel research agents.

---

## 1. Formal Framework Mappings

### POMDP Information Gathering

Wonder maps to information-gathering actions that expand the reachable belief space. Reason maps to belief updates via Bayesian filtering. The `voi()` method (expected entropy reduction) is exactly the Value of Information criterion used in POMDP planning.

**Gap identified:** Current VOI is myopic (single-step). True POMDP planning considers multi-step lookahead.

Source: Araya et al. (2010), "A POMDP Extension with Belief-dependent Rewards," NeurIPS.

### Active Inference (Free Energy Principle)

Friston's framework decomposes the objective into epistemic value (information gain = Wonder) and pragmatic value (expected reward = Reason). The `joint_entropy()` is the ambiguity term. Wonder/Reason alternation mirrors explore/exploit balance from minimizing expected free energy.

Source: Parr, Pezzulo, & Friston (2022), *Active Inference: The Free Energy Principle in Mind, Brain, and Behavior*, MIT Press.

### Scientific Discovery Formalization

Hypothesis generation as local search in theory space, with experiments selected to maximally discriminate hypotheses. This matches Wonder (generate) and Reason (discriminate).

Sources: Bramley et al. (2023), "Local search and the evolution of world models," Open Mind, MIT Press; Cranmer et al. (2023), "Bayesian Experimental Design for Symbolic Discovery," ICML Workshop.

### Multi-Armed Bandit with Progressive Widening

Wonder discovering new hypotheses maps to progressive widening (Coulom, 2007). Hibernation score is equivalent to arm elimination in successive elimination bandits. Graph edges between speculative beliefs via `propagate_evidence()` are side information channels in combinatorial bandits.

Source: Lattimore & Szepesvari (2020), *Bandit Algorithms*, Cambridge, Ch. 29-30; Jinnai et al. (2024), "Discovering Options for Exploration," AAAI.

---

## 2. Speculative Belief Aging

### Do Not Apply Temporal Decay

Speculative beliefs should NOT decay with temporal half-lives. An unexplored hypothesis is not "stale" -- it is unresolved. In ACT-R, prospective memories persist until the cue event occurs or the intention is explicitly cancelled. Use retrieval-priority decay (controls surfacing frequency) separate from the uncertainty parameters (which should freeze on hibernation).

Source: McDaniel & Einstein (2000), "Strategic and automatic processes in prospective memory retrieval," Applied Cognitive Psychology.

### Revival Triggers (three sources)

1. **Cue-based (cognitive science):** `activation_condition` match during retrieval. Fire when the environment matches.
2. **Transposition match (game trees):** New evidence semantically matches a hibernated node's content. Check during `search()` and `wonder()`.
3. **Misprediction flush (CPU architecture):** The branch stays live until the condition resolves. No timer-based re-evaluation.

Do not add time-based re-evaluation. It creates busywork without information gain.

Sources: Scullin Lab, Baylor (https://sites.baylor.edu/scullin/prospective-memory/); MCTS Review (https://link.springer.com/article/10.1007/s10462-022-10228-y); Wikipedia: Speculative Execution.

### SOAR vs ACT-R Model

Use SOAR's model: persistence until explicit resolution. ACT-R applies base-level decay to intentions, which causes silent forgetting. We do not want hypotheses to silently vanish.

Sources: Anderson & Lebiere (ACS 2021, https://advancesincognitivesystems.github.io/acs2021/data/ACS-21_paper_6.pdf); Laird (2022, https://arxiv.org/pdf/2205.03854).

### Forward-to-Backward Transition

Transition when `activation_condition` evaluates to TRUE or FALSE (event-driven, not time-driven). On resolution: either (a) speculative belief becomes factual with `temporal_direction='backward'` and collapsed confidence, or (b) refuted via SUPERSEDES edge.

---

## 3. Stale Belief Cleanup

### Provenance Hierarchy

Auto-supersede when provenance hierarchy is unambiguous:
- locked > user_corrected > agent_inferred

When a newer, higher-provenance belief contradicts an older, lower-provenance one, auto-supersede the older one. This handles ~80% of contradictions.

### Maintenance Ratios

From enterprise KB practice (Wikidata, DBpedia, Stardog):
- **~80% auto-handle:** Clear provenance winners, expired timestamps, duplicate detection
- **~15% flag:** Genuine contradictions needing judgment
- **~5% escalate:** Locked or high-impact beliefs

The system's 91% agent-inferred ratio makes auto-demotion safe for most contradictions.

### Framework

AGM belief revision (Gardenfors, 1988): expansion, contraction, revision with minimal change principle. Modern implementations use temporal validity windows and confidence decay.

Sources: Gardenfors (1988), *Belief Revision*, Cambridge; Ji et al. (2023), ACM Computing Surveys (https://dl.acm.org/doi/10.1145/3571730); Vrandecic & Krotzsch (2014), "Wikidata," CACM (https://dl.acm.org/doi/10.1145/2629489).

---

## 4. Multi-Dimensional Uncertainty Integration

### Collapsing 4D to 1D

Use geometric weighted mean (multiplicative aggregation):

```
confidence = product(dim_mean_i ^ w_i) where sum(w_i) = 1
```

This preserves the "weakest link" property: high value but zero feasibility collapses to low confidence. Better than weighted average (masks failures) or max (ignores risk).

On transition, freeze the 4D vector as provenance metadata. Initialize single Beta with `alpha = collapsed * N, beta = (1-collapsed) * N` where N = effective sample size.

Source: Keeney & Raiffa (1976), *Decisions with Multiple Objectives*, Cambridge University Press.

### Retrieval Scoring

Do not Thompson-sample per dimension independently (combinatorial explosion). Compute a single Thompson sample from the collapsed score, then apply in the existing pipeline. Keeps scoring uniform across belief types.

Source: Emmerich & Deutz (2006), "Single- and multi-objective evolutionary optimization."

### Ba Protocol: 4th Zone

Add `== ACTIVE HYPOTHESES ==` zone (not "open questions"). Include the dominant uncertainty dimension so the agent knows what kind of evidence would resolve it:

```
== ACTIVE HYPOTHESES ==
[?] Should agentmemory support embedding retrieval? (feasibility uncertain, voi=0.23)
[?] Could LLM entity extraction improve MH scores? (value uncertain, voi=0.18)
```

Source: Baltag & Smets (2008), "A Qualitative Theory of Dynamic Interactive Belief Revision."

### Extended Feedback Types for Speculative Beliefs

Regular beliefs keep `used/ignored/harmful`. Speculative beliefs get dimension-specific feedback:

| Feedback | Updates Dimension | Meaning |
|----------|------------------|---------|
| `explored` | value | Was it worth investigating? |
| `tested` | feasibility | Did the approach work? |
| `costed` | cost | Was effort estimate right? |
| `blocked` | dependency | Is a prerequisite missing? |
| `unblocked` | dependency | Prerequisite now met |

Source: Howard (1966), "Information Value Theory," IEEE Transactions on Systems Science and Cybernetics.

---

## 5. Design Decisions

Based on the research synthesis, the following decisions are recommended:

1. **No temporal decay for speculative beliefs.** Freeze Beta parameters on hibernation. Use retrieval-priority decay only.
2. **Event-driven transitions.** Forward-to-backward on activation_condition resolution, not on time.
3. **Geometric weighted mean for 4D-to-1D collapse** on transition.
4. **Auto-supersede stale beliefs** when provenance hierarchy is unambiguous. Flag the rest.
5. **4th ba protocol zone:** ACTIVE HYPOTHESES with VOI display.
6. **Dimension-specific feedback:** explored/tested/costed/blocked/unblocked for speculative beliefs.
7. **Myopic VOI is acceptable** for v2 launch. Multi-step lookahead is a v3 feature.
8. **SOAR persistence model** for speculative beliefs, not ACT-R decay.
