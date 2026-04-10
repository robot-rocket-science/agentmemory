# Approaches Log

Detailed record of every approach considered, tested, and evaluated. Nothing gets deleted -- failed approaches are as informative as successful ones.

---

## Format

Each approach entry follows this structure:

```
### [ID] Approach Name

**Status:** Proposed | Testing | Tested | Adopted | Rejected | Superseded by [ID]
**Date proposed:** YYYY-MM-DD
**Date tested:** YYYY-MM-DD (if applicable)

**Hypothesis:** What we expected this approach to do and why.

**Method:** How we tested it. Exact commands, configurations, datasets.

**Results:** Raw numbers. No interpretation in this section.

**Analysis:** What the results mean. What surprised us. What we got wrong.

**Decision:** Adopt, reject, or modify. With reason.

**References:** Papers, code, prior art.
```

---

## Approaches

### [A001] Citation-Backbone Graph (GSD Prototype)

**Status:** Tested (prototype only) -- not independently validated
**Date proposed:** 2026-04-06
**Date tested:** 2026-04-06 (spike simulation, not production)

**Hypothesis:** A graph built from explicit D###/M### citation references in decision text, with BFS retrieval and hub damping, will deliver more relevant context than flat retrieval with lower token cost.

**Method:** Built ~1,900 LOC TypeScript prototype. Loaded 577 nodes (165 decisions + 375 knowledge + 45 milestones) and 742 edges from alpha-seek project data. Compared graph-seeded BFS retrieval (top 15) against flat retrieval (top 15 by confidence * hit_count) across 5 task scenarios. Relevant sets labeled by the agent (not human-labeled).

**Results:**

| Scenario | Flat P@15 | Graph P@15 | Flat R@15 | Graph R@15 |
|----------|-----------|------------|-----------|------------|
| Exit rules | 0.000 | 0.867 | 0.000 | 0.867 |
| D097 methodology | 0.000 | 0.267 | 0.000 | 0.400 |
| Paper trading | 0.000 | 0.533 | 0.000 | 0.615 |
| Sizing/capital | 0.200 | 0.533 | 0.250 | 0.667 |
| N-starvation | 0.000 | 0.333 | 0.000 | 0.429 |

Latency: BFS 2-hop 0.006ms median, text search + BFS 0.159ms median. All sub-ms.

**Analysis:** The numbers look impressive but the methodology is weak:
- Flat baseline has zero task awareness (returns same 15 nodes for every task, scores 0.000 on 4/5). Even basic keyword filtering would beat it.
- "Manually labeled" relevant sets were agent-generated during the spike, not human-verified.
- The 577-node graph is small. Scaling behavior unknown.
- The "7x precision" and "99% token reduction" claims were repeated in documentation without these caveats.
- Sub-ms latency is real but trivial at this scale (entire graph fits in ~50KB of memory).

**What's actually proven:**
- Citation parsing via regex works and is free (zero LLM cost)
- BFS with hub damping produces task-relevant results when the graph has good structure
- In-memory adjacency list is fast at small scale

**What's NOT proven:**
- Whether this beats any standard baseline on any standard benchmark
- Whether it scales
- Whether the retrieval quality improvement translates to better agent output

**Decision:** Carry forward the proven mechanisms (citation parsing, BFS, hub damping, anchor nodes). Do NOT carry forward the performance claims. Re-evaluate against real baselines in Phase 2.

**References:**
- Spike location: `/Users/thelorax/projects/.gsd/workflows/spikes/260406-1-associative-memory-for-gsd-please-explor/`
- Key files: `sandbox/COMPARISON.md`, `sandbox/VALIDATION.md`, `TESTING-STRATEGY.md`

---

### [A002] MemPalace-Style Spatial Metaphor

**Status:** Rejected
**Date proposed:** 2026-04-09 (evaluated during survey)

**Hypothesis:** Organizing memories into a spatial hierarchy (wings/rooms/halls) provides meaningful retrieval structure and human-legible navigation.

**Method:** Analyzed MemPalace architecture via lhl/agentic-memory ANALYSIS-mempalace.md. No implementation.

**Results:** Per lhl analysis:
- Halls are metadata strings only, not used in retrieval ranking
- "+34% retrieval boost from palace structure" is just ChromaDB metadata filtering (standard technique)
- 96.6% LongMemEval headline measures ChromaDB's embedding model, not palace architecture
- LoCoMo: 60.3% (mediocre)
- "Zero information loss" compression claim is false (12.4pp quality drop in AAAK mode)
- "Contradiction detection" does not exist in code

**Analysis:** The spatial metaphor is cosmetic. It provides human-readable organization but does not improve retrieval quality. The lhl analysis refused to promote MemPalace to its main comparison table due to claims-vs-code gap. However: MemPalace's session recovery worked in practice (user recovered 90% context after two back-to-back crashes), proving that continuous checkpointing + context reconstruction is genuinely valuable.

**Decision:** Reject the spatial metaphor. Adopt the session recovery concept (implemented differently in our architecture). Adopt the cross-model MCP interface concept.

**References:**
- [lhl/agentic-memory ANALYSIS-mempalace.md](https://github.com/lhl/agentic-memory/blob/main/ANALYSIS-mempalace.md)
- User report: 90% context recovery after two crashes (2026-04-08)

---

### [A003] Human Memory Categories (Episodic/Semantic/Procedural)

**Status:** Rejected
**Date proposed:** 2026-04-09 (evaluated during survey)

**Hypothesis:** Organizing memory into episodic (events), semantic (facts), and procedural (how-to) stores, mirroring human memory, provides useful structure for retrieval and maintenance.

**Method:** Literature review. This is the dominant approach in the field: ENGRAM, Memoria, Mem0, LangMem, and most academic systems use some variant.

**Results:** Human memory is a bad model for a computer system:
- Episodic memory is subject to reconsolidation (each recall modifies the memory) -- we don't want this
- Semantic memory carries no confidence, no evidence chain, no expiration -- we need all three
- Procedural memory is implicit and hard to inspect or correct -- we need explicit, testable beliefs
- "Principled forgetting" is an oxymoron when storage is cheap and recall is deterministic
- The categories overlap and are ambiguous (is "user prefers dark mode" episodic or semantic?)

**Analysis:** The human memory model provides familiar vocabulary but weak engineering constraints. It doesn't tell you what to do when two memories conflict, how to verify a memory is still valid, or how to measure whether retrieval is improving over time.

**Decision:** Replace with scientific method model: observation/belief/test/revision. More rigorous, more inspectable, provides the feedback loop that human memory categories lack.

**References:**
- Zhang et al., "Survey on Memory Mechanisms," arXiv:2404.13501
- Hu et al., "Memory in the Age of AI Agents," arXiv:2512.13564

---

### [A004] Scientific Method Memory Model

**Status:** Adopted (design phase)
**Date proposed:** 2026-04-09

**Hypothesis:** Modeling memory after the scientific method (observe, hypothesize, test, revise) produces a more rigorous system than modeling after human memory. Key advantages: immutable observations, beliefs with explicit confidence and evidence chains, a feedback loop to test whether retrieval is useful, and explicit revision with provenance.

**Method:** Not yet tested. Design documented in PLAN.md.

**Results:** Pending Phase 2 implementation and measurement.

**Analysis:** Pending.

**Decision:** Proceed to implementation. The hypothesis is that this model will produce better calibrated confidence (beliefs that score high are actually useful), lower false positive retrieval (less noise), and better conflict resolution (contradictions are surfaced with evidence, not silently ignored).

**Open questions:**
- Does the feedback loop actually improve retrieval quality over time?
- Is the overhead of evidence tracking worth it?
- How do we detect false negatives (beliefs that should have been retrieved but weren't)?
- Does belief confidence actually predict usefulness? (Calibration)

**References:**
- PLAN.md (this project)
- Conceptual precursors: Bayesian epistemology, scientific realism, Popperian falsification

---

### [A005] Bayesian Belief Updating

**Status:** Proposed -- research in progress
**Date proposed:** 2026-04-09

**Hypothesis:** Using Bayesian inference (Beta-binomial conjugate priors) to update belief confidence based on retrieval feedback will produce better-calibrated confidence scores than heuristic methods. The confusion matrix (TP/FP/FN/TN) for retrieval outcomes feeds directly into the Beta distribution parameters.

**Method:** Pending research agent results.

**Results:** Pending.

**Analysis:** Pending.

**Decision:** Adopted for v1. Research completed -- see BAYESIAN_RESEARCH.md for full analysis.

**Research findings (2026-04-09):**
- Beta-Bernoulli conjugate priors are the right choice. O(1) updates, two floats per belief, no MCMC.
- Source-informed priors solve cold start: user-stated Beta(9,1), agent-inferred Beta(1,1), etc. Prior strength controls learning rate.
- IGNORED outcome gets no update (correct -- absence of evidence is not evidence of absence).
- Non-stationarity handled via revision mechanism (create new belief, supersede old) rather than temporal decay on Beta parameters.
- MACLA (arXiv:2512.18950) validated Beta posteriors for procedural memory. SuperLocalMemory (arXiv:2603.02240) validated for trust scoring.
- Expected-utility retrieval ranking with exploration bonus (from MACLA) incentivizes testing uncertain beliefs.
- Evidence correlation is the main pitfall: shared source observations inflate confidence. Mitigate with source dedup.
- Nobody has combined Beta confidence + feedback loop + exploration-aware retrieval + conflict resolution. This is a genuine gap.

**What NOT to implement (v1):**
- Full hierarchical Bayesian source credibility model (overkill)
- Dirichlet-Multinomial for multi-outcome (binary mapping sufficient)
- MCMC/variational inference (conjugate priors make it unnecessary)
- Automatic multi-hop conflict resolution (unsolved problem, be honest)

**Experiment results (2026-04-09):**

Experiment 2 and 2b parameter sweep results:

- **REQ-009 FAILED.** ECE never drops below 0.16 across 42 configurations (6 prior strengths x 7 exploration weights). Target was < 0.10. Source-informed priors (Beta(9,1)) are WORSE than uniform priors (ECE 0.37 vs 0.24) because strong priors resist correction.
- **REQ-010 FAILED at default settings** but fixable. Exploration weight >= 0.30 produces measurable exploration. Weight 0.50 with prior_strength 1.0 gives exploration = 0.37 (within target range).
- Best configuration found: prior_strength=1.0, exploration_weight=0.50 (ECE=0.21, exploration=0.37). Still fails calibration.
- Rank correlation is NaN in most trials due to low diversity in retrieved beliefs (same beliefs retrieved repeatedly when exploration is too low).

**Diagnosis (Exp 2c, 2026-04-09):**

Root cause identified: calibration metric bug. `actual_use_rate` was computed as `used_count / retrieval_count` (includes IGNORED), but the Beta distribution only tracks used/harmful. IGNORED inflated the denominator, making actual rates systematically lower than confidence. Fix: `actual_use_rate = used_count / (used_count + harmful_count)`.

After fix:
- Uniform priors ECE drops from 0.24 to **0.042** (passes REQ-009)
- Source-informed priors ECE drops from 0.37 to **0.18** (still fails -- priors too strong)
- Oracle test confirms: with clean data (no IGNORED), ECE = 0.003. Model works.

**New finding: calibration-exploration tradeoff.**
- Configs with good calibration (ECE < 0.10) have zero exploration
- Configs with good exploration (0.15-0.50) have ECE > 0.10
- This is a real tradeoff: exploration spreads test budget across more beliefs, giving each fewer samples, slowing convergence
- Best calibration: ps=1.0, ew=0.05 -> ECE=0.046, exploration=0.00
- Best balanced: ps=1.0, ew=0.50 -> ECE=0.118, exploration=0.37
- No config passes BOTH REQ-009 and REQ-010 simultaneously

**Decisions needed:**
1. Accept the tradeoff and relax one threshold (e.g., ECE < 0.15 with exploration >= 0.15)?
2. Use a phased approach: heavy exploration early (learn about beliefs), then reduce exploration as confidence stabilizes?
3. Decouple exploration from retrieval: run dedicated "exploration retrievals" separate from task retrievals?

**Open questions (remaining):**
- Does phased exploration (high early, low late) achieve both targets?
- At what evidence density does the correlation problem become material?
- Does the tradeoff persist with larger belief populations and more sessions?

---

### [A024] Relaxed Calibration-Exploration Thresholds

**Status:** Fallback (only if A027 Thompson doesn't work after Exp 5b)
**Date proposed:** 2026-04-09

**Hypothesis:** Accepting ECE < 0.15 (instead of < 0.10) and exploration >= 0.15 allows a single static configuration to pass both requirements. The relaxed calibration threshold is still meaningful -- 0.15 ECE means predicted confidence is off by at most 15% on average, which is useful for ranking even if not perfectly calibrated.

**Method:** Recheck existing Exp 2b sweep data for configs where ECE < 0.15 AND exploration >= 0.15.

**Expected results:** Based on sweep data, ps=1.0/ew=0.50 gives ECE=0.118 and exploration=0.37. This would pass under relaxed thresholds. Several other configs in the ps=1-3, ew=0.30-0.50 range should also pass.

**Tradeoffs:**
- Pro: Simplest solution. Single static config, no temporal logic.
- Con: Weaker calibration guarantee. 0.15 ECE means a belief at confidence 0.80 might actually be useful anywhere from 0.65 to 0.95. That's a wide band.
- Con: Doesn't solve the underlying tension, just accepts it.

**Decision:** Pending. This is the fallback if A025 and A026 don't work.

---

### [A025] Phased Exploration (Annealing)

**Status:** Tested -- rejected (Exp 5)
**Date proposed:** 2026-04-09

**Hypothesis:** Starting with high exploration weight (0.50) and decaying it over sessions (to 0.05 by session 30) achieves both good exploration (>= 0.15 cumulative) and good calibration (ECE < 0.10 at final measurement). The logic: early sessions explore broadly to test uncertain beliefs, later sessions exploit what's been learned.

This is analogous to simulated annealing or epsilon-greedy decay in reinforcement learning -- a well-established strategy for the explore/exploit tradeoff.

**Method:** Modify Exp 2 simulation:
- exploration_weight(session) = max(0.05, 0.50 * (1 - session/30))
- Run with uniform priors (ps=1.0) since source-informed priors are counterproductive
- Measure ECE at session 50 (after exploration has decayed)
- Measure cumulative exploration fraction across all sessions
- 100 trials for confidence intervals

**Expected results:**
- Cumulative exploration >= 0.15 (most exploration happens in sessions 1-15)
- ECE < 0.10 at session 50 (beliefs well-tested by then, exploitation phase has converged)
- Should outperform both static-high and static-low exploration weights

**Tradeoffs:**
- Pro: Addresses the tradeoff directly. Both requirements met at different time scales.
- Pro: Well-understood strategy from RL literature.
- Con: Adds a temporal parameter (decay schedule). Needs tuning.
- Con: New beliefs added after session 30 get less exploration than early beliefs. May need exploration reset when new beliefs enter the system.

**Open questions:**
- What decay schedule? Linear? Exponential? Step function?
- Should exploration reset when new beliefs are added?
- Does the system need a "minimum exploration floor" to keep learning about new beliefs?

**Experiment 5 results (2026-04-09):** ECE=0.062 (best of all strategies) but exploration=0.000 (worst). The annealing works for calibration but the median-relative exploration metric reads as zero because the median entropy drops as beliefs converge. The strategy may actually be exploring early, but the metric can't see it by session 50. Rejected in favor of Thompson sampling which achieves nearly as good calibration with actual measurable exploration.

**References:**
- Epsilon-greedy decay in multi-armed bandits
- Simulated annealing (Kirkpatrick et al., 1983)
- Upper Confidence Bound (UCB) algorithms -- similar spirit, different mechanism

---

### [A026] Decoupled Exploration

**Status:** Tested -- rejected (Exp 5)
**Date proposed:** 2026-04-09

**Hypothesis:** Separating exploration from task retrieval eliminates the tradeoff entirely. Task retrieval optimizes for quality (low/zero exploration weight). A separate background process ("exploration pass") periodically retrieves and tests uncertain beliefs during maintenance or idle time. Both budgets are independent.

**Method:** Modify Exp 2 simulation with two retrieval channels:
- **Task retrieval:** 10 per session, top-k by EU with exploration_weight=0.05. Feeds into agent context.
- **Exploration retrieval:** 5 per session, selected by highest entropy (most uncertain beliefs). Does NOT feed into agent context -- outcomes are simulated as if the belief was tested in a relevant task. (In production, this would be a background process that probes beliefs against recent task contexts.)

Measure:
- ECE on task-retrieved beliefs (should be low -- only high-confidence beliefs used)
- ECE on all beliefs (should also be low -- exploration tests the rest)
- Exploration fraction (should be high -- dedicated exploration budget)
- Total test budget: 15 per session instead of 10 (exploration has a cost)

**Expected results:**
- Task-retrieval ECE < 0.05 (only confident, well-tested beliefs)
- All-beliefs ECE < 0.10 (exploration tests the uncertain ones)
- Exploration fraction >= 0.30 (dedicated exploration channel)
- Both REQ-009 and REQ-010 pass simultaneously

**Tradeoffs:**
- Pro: Cleanly separates concerns. Task retrieval is pure exploitation. Exploration is pure exploration.
- Pro: No temporal parameters to tune.
- Pro: Maps naturally to the architecture -- maintenance passes already exist for graph recomputation, pruning, etc. Exploration can run during maintenance.
- Con: Higher total cost per session (15 retrievals instead of 10). In production, the "exploration" retrievals still consume compute even though they don't serve the current task.
- Con: Simulating exploration outcomes offline is not the same as real outcomes. A belief tested in a background pass may behave differently than one tested in a real task context.
- Con: More complex system -- two retrieval paths instead of one.

**Open questions:**
- How to simulate exploration outcomes in production? Can we use the task context retroactively ("if this belief had been in the context for the last task, would the agent have used it?")?
- What's the right ratio of task vs exploration retrievals?
- Does the exploration pass surface beliefs that eventually become useful in task retrieval? (If exploration never graduates beliefs to task-relevant, it's wasted compute.)

**Experiment 5 results (2026-04-09):** ECE=0.316 (worst of all strategies), exploration=0.091. Failed badly. The exploration channel tests high-entropy (low-confidence) beliefs whose poor outcomes dominate the overall calibration. The exploration channel poisons the overall ECE. The separation sounds clean in theory but in practice the two channels interact through shared calibration. Rejected.

**References:**
- Separate exploration/exploitation in contextual bandits
- Thompson sampling (natural exploration via sampling from the posterior -- could replace dedicated exploration entirely)

---

### [A027] Thompson Sampling for Retrieval

**Status:** ADOPTED (Exp 5b confirmed: Thompson + Jeffreys Beta(0.5,0.5) passes both REQ-009 and REQ-010)
**Date proposed:** 2026-04-09

**Hypothesis:** Instead of using expected utility with a fixed exploration bonus, sample from each belief's Beta distribution and rank by the sample. This is Thompson sampling -- a well-established Bayesian approach to the explore/exploit tradeoff that naturally balances the two without an explicit exploration weight parameter.

```
For each retrieval:
  For each belief b:
    sample_b ~ Beta(b.alpha, b.beta_param)
    score_b = relevance(query, b) * sample_b
  Return top-k by score
```

High-confidence beliefs (Beta(50,2)) almost always sample high and get retrieved. Uncertain beliefs (Beta(1,1)) sometimes sample high (exploration) and sometimes sample low (exploitation). The balance is automatic -- no exploration_weight to tune.

**Method:** Modify Exp 2 simulation to use Thompson sampling instead of EU scoring. Run with uniform priors. Measure ECE, exploration fraction, and rank correlation at session 50.

**Expected results:**
- Exploration fraction 0.15-0.30 (natural exploration from posterior sampling)
- ECE < 0.10 (enough samples per belief to converge, but exploration prevents over-concentration)
- No tuning parameter needed (the Beta distribution IS the exploration strategy)

**Tradeoffs:**
- Pro: Elegant. No exploration_weight to tune. Bayesian-optimal exploration.
- Pro: Well-studied theoretical guarantees (Bayesian regret bounds).
- Pro: Naturally adapts: uncertain beliefs get explored, confident beliefs get exploited.
- Con: Stochastic -- different runs produce different retrievals. May be surprising to users.
- Con: Slightly more expensive per retrieval (need to sample from Beta for each belief).
- Con: Less interpretable than EU scoring -- harder to explain "why was this belief retrieved?"

**Experiment 5 results (2026-04-09):** ECE=0.097 (passes REQ-009), exploration=0.129 (misses REQ-010 by 0.021), rank_correlation=0.554 (best of all strategies).

**Experiment 5b results (2026-04-09):** Thompson + Jeffreys Beta(0.5, 0.5) + median-relative threshold: **ECE=0.066, exploration=0.194. PASSES BOTH.** The wider Jeffreys prior produces more diverse posterior samples, improving both calibration and exploration simultaneously -- the tradeoff that appeared fundamental with Beta(1,1) dissolves with the right prior. This is the adopted configuration.

**References:**
- Thompson (1933), "On the likelihood that one unknown probability exceeds another"
- Russo et al. (2018), "A Tutorial on Thompson Sampling" (Foundations and Trends in ML)
- Chapelle & Li (2011), "An Empirical Evaluation of Thompson Sampling" (NIPS)

**References:**
- BAYESIAN_RESEARCH.md (this project, full analysis)
- [MACLA (arXiv:2512.18950)](https://arxiv.org/abs/2512.18950)
- [SuperLocalMemory (arXiv:2603.02240)](https://arxiv.org/abs/2603.02240)
- [Memory for Autonomous LLM Agents Survey (arXiv:2603.07670)](https://arxiv.org/abs/2603.07670)
- [Are LLM Belief Updates Bayesian? (arXiv:2507.17951)](https://arxiv.org/abs/2507.17951)

---

### [A006] Filesystem + Grep Baseline (Letta)

**Status:** To be tested (Phase 0 baseline)
**Date proposed:** 2026-04-09

**Hypothesis:** A simple filesystem with grep-based search, using an LLM that's well-trained on file operations, provides a surprisingly strong baseline for memory retrieval. Letta reported 74% on LoCoMo with this approach.

**Method:** Will implement in Phase 0 and measure against our real-world tests (context drift, token efficiency, session recovery) and standard benchmarks.

**Results:** Pending.

**Analysis:** Pending. This is the bar we need to clear. If our system can't beat grep, we're adding complexity for nothing.

**Decision:** Pending measurement.

**References:**
- [Letta benchmarking blog](https://www.letta.com/blog/benchmarking-ai-agent-memory)
- Letta reported 74.0% LoCoMo with gpt-4o-mini + filesystem tools

---

### [A015] AAAK-Style Content Compression

**Status:** Rejected
**Date proposed:** 2026-04-09

**Hypothesis:** Compressing stored content (abbreviation, summarization, lossy encoding) reduces token usage while maintaining retrieval quality.

**Method:** Evaluated MemPalace's AAAK compression via lhl analysis. No implementation of our own.

**Results:** MemPalace AAAK:
- Claims "30x compression, zero information loss"
- Actual: lossy abbreviation. LongMemEval drops from 96.6% to 84.2% (12.4pp quality loss).
- Token counting uses len(text)//3 (heuristic, not real tokenization)
- "Decode" method is just string splitting, no text reconstruction

**Analysis:** Compression solves the wrong problem. The disease is "retrieving too much irrelevant content." The symptom is "too many tokens." Compressing everything gives you compressed irrelevant content -- still irrelevant, just smaller.

Better alternatives (all already in our architecture):
1. **Retrieve less, retrieve better.** Bayesian confidence ranking + hard token budgets (L0-L3) mean we only retrieve the 5-15 most useful beliefs instead of 50 compressed ones.
2. **Store structured claims, not raw text.** Beliefs are concise claims ("John prefers PostgreSQL") with links to verbose observations. Observations are stored for provenance but rarely injected into context.
3. **Progressive disclosure.** L0+L1 inject short summaries (~600 tokens). L2/L3 go deeper on demand.
4. **Evidence-gated retrieval.** Only surface beliefs with strong evidence chains. Untested beliefs don't consume token budget.

**Decision:** Reject compression as a primary strategy. If token budget is still a problem after better retrieval, revisit. Bet: we won't need it.

**References:**
- [lhl/agentic-memory ANALYSIS-mempalace.md](https://github.com/lhl/agentic-memory/blob/main/ANALYSIS-mempalace.md)

### [A016] Holographic Reduced Representations for Belief Encoding

**Status:** Proposed (promising -- v2 candidate)
**Date proposed:** 2026-04-09

**Hypothesis:** Encoding beliefs as hyperdimensional vectors via HRR (circular convolution) allows composable multi-hop retrieval queries without injecting intermediate hops into context, improving retrieval quality within the same token budget.

**Key insight -- HRR and token reduction are not in tension:** HRR operates at the retrieval layer, not the injection layer. The hypervectors are never injected into context. They are used to SELECT which plain-text beliefs get injected. Token budget caps (L0-L3) apply as normal to the selected beliefs. The gain is that HRR retrieval finds better matches -- especially for multi-hop compositional queries -- so more of the token budget goes toward signal rather than noise.

**How it works with granular decomposition:**
- Beliefs must be atomic to work well as HRR building blocks (circular convolution binds two clean concepts; paragraph-length "beliefs" produce ambiguous bindings)
- Typed edges (SUPPORTS, CONTRADICTS, CITES, TEMPORAL_NEXT) become binding operators encoded into the hypervector
- A query binds its terms together in hyperdimensional space, then uses circular correlation (approximate unbinding) against stored belief vectors
- Top-k by similarity score get retrieved -- still as plain text, still short, still under token cap
- Multi-hop: instead of retrieving hop 1, injecting it, retrieving hop 2, etc., you compose the query vector and retrieve the destination belief directly

**Why this matters for our architecture:**
- Transformer attention is mathematically equivalent to Kanerva's Sparse Distributed Memory (Bricken & Pehlevan, NeurIPS 2021). The LLM's internal attention IS holographic retrieval. Our external memory would be augmenting an internal HRR system with the same mechanism -- principled alignment.
- Our citation graph with typed edges (BFS traversal) is already computing approximate holographic projections. HRR makes this explicit and enables approximate nearest-neighbor retrieval without full graph traversal.
- Graceful degradation: partial query matches still retrieve partial information. FTS5 keyword matching has a hard cliff (no keyword match = zero score). HRR has smooth falloff.

**Method:** Not yet tested. Would require:
1. Encode existing belief set as hyperdimensional vectors (numpy, no external deps)
2. Encode typed edges via circular convolution
3. Run same query set as Exp 3 against both FTS5+BFS and HRR retrieval
4. Compare P@k and R@k using same human-labeled relevant sets

**Results:** N/A

**Analysis:** N/A

**Risks:**
- Adds vector computation overhead (acceptable at belief-graph scale, ~1K-100K beliefs)
- HRR retrieval quality is sensitive to dimensionality (typical: 1K-10K dimensions). Need to calibrate.
- NeurIPS 2021 projection step (Ganesan et al.) gave 100x improvement on knowledge graph completion -- that's the version worth implementing, not raw Plate 1995.

**Decision:** Defer to v2. FTS5 + BFS is already working and retrieval quality vs. ranking quality gap is not yet isolated. Prerequisite: complete #19 (variable-relevance Thompson test) and #22 (info-theoretic retrieval improvements) to confirm retrieval is the bottleneck. If it is, HRR is the principled upgrade.

**References:**
- [HRR (Plate, 1995)](https://ieeexplore.ieee.org/document/377968/)
- [Learning with HRRs (Ganesan et al., NeurIPS 2021)](https://proceedings.neurips.cc/paper/2021/file/d71dd235287466052f1630f31bde7932-Paper.pdf)
- [Attention Approximates SDM (Bricken & Pehlevan, NeurIPS 2021)](https://arxiv.org/abs/2111.05498)
- [VSA Survey Part I (ACM 2022)](https://dl.acm.org/doi/10.1145/3538531)

---

## Approaches Not Yet Evaluated

These emerged from the survey and may be worth testing later:

| ID | Approach | Source | Why Interesting |
|----|----------|--------|----------------|
| A007 | Temporal knowledge graph with validity windows | Zep/Graphiti | Strongest results on knowledge update tasks |
| A008 | Neurobiological hippocampal indexing + PPR | HippoRAG | 20% improvement on multi-hop QA, 10-20x cheaper than iterative |
| A009 | Zettelkasten-style note network with LLM linking | A-MEM | Dynamic cross-referencing between beliefs |
| A010 | Multi-graph architecture (semantic + temporal + causal + entity) | MAGMA | Different graph types for different query types |
| A011 | RL-optimized memory CRUD operations | Memory-R1 | End-to-end optimization of what to store/retrieve |
| A012 | Test-time evolution with experience reuse | Evo-Memory / Live-Evo | Learns from past task outcomes |
| A013 | Progressive hierarchical consolidation | TiMem | Segment -> session -> day -> week -> profile |
| A014 | Dual memory with predict-calibrate distillation | Nemori | Knowledge distillation for memory compression |
| A016 | [See full entry below] Holographic Reduced Representations for belief encoding | Plate 1995, NeurIPS 2021 | Typed edges as binding operators; subgraphs as holographic projections. Transformer attention IS SDM (Bricken 2021). |
| A017 | Mutual information scoring for retrieval | Phadke 2025 (arXiv:2512.00378), MI-RAG | Similarity IS mutual information (proved). Fundamental lower bound on encoding bits. |
| A018 | MinHash for near-duplicate belief detection | LSH literature | TESTED (Exp 9): MinHash alone = 31% coverage, much worse than FTS5. Shingle overlap too sparse between short queries and long text. Not useful for retrieval. May still be useful for dedup (different use case). |
| A019 | Information Bottleneck for optimal belief compression | Tishby 1999, Jakob & Gershman 2023 | Principled compression: minimize storage while preserving query relevance. Replaces heuristic summarization. |
| A020 | Beam search for L3 deep graph queries | General graph search | Explores top-k paths simultaneously. Better than BFS for specific distant targets. No training needed. |
| A021 | MINERVA-style RL path finding | Das et al. ICLR 2018 | Query-conditioned learned walks. Best quality but needs training data from feedback loop. v2 candidate. |
| A022 | Fisher Information retrieval metric | SuperLocalMemory V3 (arXiv:2603.14588) | Riemannian metric replaces cosine similarity. More geometrically principled. |
| A023 | Rate-distortion theory for token budget allocation | Jakob & Gershman 2023 (eLife) | When more beliefs compete for budget, each gets less precision. Optimal allocation, not arbitrary caps. |
| A028 | Adaptive retrieval depth based on relevance scoring | Exp 3 labeling observation | Relevance scores from labeling could inform how deep into the citation graph to traverse. If direct hits score low, go deeper. If deep results score high, pre-cache those paths. Analyze Exp 3 data for correlation between relevance score and retrieval depth. |
| A029 | Label sensitivity analysis (+/-1 perturbation) | Exp 3 methodology | Perturb every label by +/-1 (uniform random, clamped 1-5) across 100 runs. Recompute per-method metrics. Produces error bars approximating inter-annotator disagreement. If method comparison results are stable under perturbation, they're robust. If they flip, the difference is within labeling noise and not meaningful. Build into Exp 3 scoring script. |
