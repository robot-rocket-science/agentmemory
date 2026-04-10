# Open Research Questions

**Date:** 2026-04-09
**Purpose:** Every question we haven't answered yet. Organized by category. Each question gets a test design when we're ready to investigate it.

---

## Foundational (affects core architecture)

### F1: How do the retrieval layers interact?

We tested FTS5, HRR, SimHash, and graph BFS independently. How do they combine into one retrieval pipeline? What's the orchestration?

**What we know:**
- FTS5 alone: 100% critical coverage with 3 query variants (Exp 9)
- HRR alone: 60-80% overlap with FTS5, complementary hits (Exp 24)
- SimHash: 128-bit codes, brute-force Hamming at <10K scale (research)
- Graph BFS: hub damping, anchor nodes, typed edge traversal (GSD prototype)

**What we don't know:**
- Does combining them improve retrieval quality over any single method?
- What's the latency when all four run?
- How do you merge ranked results from different methods? (Reciprocal rank fusion? Linear combination? Cascade?)
- Is any single method redundant when the others are present?

**Test design:**
- Run all 4 methods on the same 20 queries (from Exp 3 query set)
- Measure: per-method retrieval set, union, intersection
- Fuse results via reciprocal rank fusion (standard IR technique)
- Compare fused results to each individual method
- Metric: precision@15 on alpha-seek data with human labels (or the Exp 6 critical beliefs as proxy ground truth)

**Status:** TESTED (Exp 25). All methods redundant on this dataset. Zero unique contributions from any method. FTS5 alone = fused result. D157 (async_bash) missed by ALL methods -- genuine vocabulary mismatch that keyword-based approaches can't solve. The gap requires semantic encoding, not better keyword matching.

---

### F2: Does hierarchical confidence work on real graph topology?

Exp 22 tested hierarchical confidence with artificial subgraphs (every 50th node is an anchor). Real graphs have uneven topology -- some anchors have 65 edges (D097), some have 3.

**What we know:**
- Artificial hierarchical: ECE 0.133 at 10K (vs 0.169 flat)
- Alpha-seek has 25 natural anchors (degree >= 10)
- Degree distribution is power-law-ish (few hubs, many leaves)

**What we don't know:**
- Does propagation through real subgraphs produce better or worse calibration?
- Do high-degree hubs over-propagate (D097's subgraph is 68 nodes -- does it swamp everything)?
- What propagation weight is right for real topology? (Exp 22 used 0.3)

**Test design:**
- Load the alpha-seek graph (586 nodes, 775 edges)
- Identify natural anchors (degree >= 10)
- Build real subgraphs via BFS from each anchor
- Run hierarchical confidence simulation on the real topology
- Compare to flat Thompson on the same graph
- Measure ECE, coverage, and per-anchor propagation patterns

**Status:** TESTED (Exp 26). No difference at 586 nodes (both ~0.11 ECE, 100% coverage). Graph is too small for hierarchical to matter. Confirmed: hierarchical only helps at 5K+ scale (Exp 22). 1/sqrt(subgraph_size) scaling prevents hub over-propagation.

---

### F3: How do CS-005 requirements (REQ-023-026) change the schema?

CS-005 added 4 new requirements about epistemic integrity: provenance metadata, velocity tracking, rigor tiers, calibrated reporting. These touch the core belief table.

**What we know:**
- Current schema has: alpha, beta_param, confidence, source_type, valid_from/to
- REQ-023 needs: produced_at, method, sample_size, data_source, independently_validated
- REQ-024 needs: session elapsed time, items completed, velocity metric
- REQ-025 needs: rigor_tier (hypothesis / simulated / empirically_tested / validated)
- REQ-026 needs: status reporting that synthesizes all of the above

**What we don't know:**
- Does adding 5+ columns to every belief create meaningful overhead?
- How do rigor tiers interact with Bayesian confidence? (A hypothesis at 0.9 confidence vs a validated finding at 0.6 -- which ranks higher?)
- Can rigor tier be computed automatically or does it need manual annotation?
- Does the velocity metric actually predict depth? (Fast =/= shallow for every task)

**Test design:**
- Extend the Exp 2 simulation to include rigor tiers
- Assign each belief a rigor tier based on how it was created
- Test: does a retrieval ranking that incorporates rigor tier (e.g., score * rigor_weight) produce better outcomes than confidence alone?
- Test: simulate a new agent reading a project status. Compare calibrated reporting (with rigor tiers) vs uncalibrated (just completion counts). Which gives a more accurate picture?

**Status:** DESIGNED (Exp 27). 5 new belief columns, 2 session columns, 70 bytes/belief overhead. Rigor tiers (hypothesis/simulated/empirically_tested/validated) multiply confidence for status reporting. Auto-assignment partially feasible from evidence records. See exp27_epistemic_schema.md.

---

## Representation (affects how knowledge is encoded)

### R1: Does sentence-level retrieval outperform decision-level on real queries?

Exp 16 showed 86% token reduction with sentence-level decomposition. But we haven't tested whether retrieving individual sentences produces better or worse results than retrieving whole decisions.

**What we know:**
- 173 decisions -> 1,195 sentence nodes
- Core sentences (assertions + constraints) = 132 nodes, 4,839 tokens
- Token reduction: 86%

**What we don't know:**
- When you retrieve sentence D097_s0 ("Walk-forward per-year fold evaluation is mandatory"), is that sufficient context? Or does the agent need D097_s1-s7 (the supporting evidence) too?
- Is there a "Goldilocks granularity" between too-coarse (whole decisions) and too-fine (individual sentences)?
- Do the edges between sentence nodes enable useful traversal? (D097_s0 -> D097_s4 via EVIDENCE edge)

**Test design:**
- Take the 6 critical belief topics from Exp 4/6
- Retrieve at sentence level (top 15 sentences) vs decision level (top 5 decisions)
- Both constrained to same token budget (1,000 tokens)
- Measure: does the sentence-level retrieval include the critical assertions? Does it include enough context to be actionable?
- This can be done by inspection rather than statistical testing (6 topics, qualitative analysis)

**Status:** TESTED (Exp 29). Sentence-level: 12/12 coverage. Decision-level: 11/12. Windowed sentence (core + 1 neighbor): 12/12 with better context than pure sentence. Windowed is the clear winner -- 2-3x more decision topics covered than whole-decision retrieval in the same token budget. Core assertions are actionable as standalone sentences. The retrieval unit should be a sentence with a 1-neighbor window.

---

### R2: How does the IB type-aware heuristic compare to actual IB optimization?

IB research said type-aware heuristic captures ~90% of IB benefit. We haven't measured that claim.

**What we know:**
- Type distribution: 49% context, 29% evidence, 11% constraint, 4% supersession, 4% implementation, 3% rationale
- Heuristic: keep constraints fully, compress context to first clause, drop implementation at retrieval time
- Estimated cost: ~7-8K tokens with ~85-90% retrieval recall

**What we don't know:**
- What does the actual retrieval recall curve look like as we progressively drop lower-priority types?
- Is the type classification accurate enough? (Only 11% classified as constraint -- seems low)
- What's the "first clause" of a context sentence? Does truncation preserve meaning?

**Test design:**
- Take the 1,195 sentence nodes
- Progressive filtering: all types -> drop implementation -> drop supersession -> drop context -> constraints only
- At each level, measure: tokens remaining, critical belief coverage (Exp 4 ground truth)
- Plot the token-vs-coverage curve
- Compare to random dropping at each token budget

**Status:** Not started

---

### R3: How do different content types decompose?

We decomposed GSD decisions. But the memory system needs to handle code, conversation, documentation, and git commits too.

**What we know:**
- Decisions decompose into ~6.9 sentences each
- Sentence types: context, evidence, constraint, rationale, implementation, supersession

**What we don't know:**
- How do git commit messages decompose? (Usually 1 sentence -- is that a node?)
- How does code decompose? (Functions? Lines? Blocks?)
- How do conversations decompose? (Turns? Sentences within turns?)
- Are the same sentence types applicable across content types?

**Test design:**
- Take 50 git commits, 50 knowledge entries, and 20 conversation turns from the alpha-seek data
- Run the sentence splitter on each
- Classify sentence types
- Compare: sentence count distribution, type distribution, cross-reference density
- Identify content types that decompose poorly (need different splitting strategy)

**Status:** Not started

---

## Dynamics (affects how the system evolves)

### D1: How does the graph change shape as a project matures?

Early alpha-seek (milestones 1-10) vs late alpha-seek (milestones 30-36) -- does the graph topology change?

**What we know:**
- 586 nodes, 775 edges total
- D097 is the gravitational center (61 refs)
- 25% orphan rate
- Override rate decreased over time (Exp 6C)

**What we don't know:**
- Does the graph become denser or sparser over time?
- Do new anchors emerge as the project matures?
- Does the orphan rate decrease (better citation discipline) or increase (more disconnected knowledge)?
- Is there a "phase transition" in graph topology at some project size?

**Test design:**
- Reconstruct the graph at milestone intervals (M005, M010, M015, M020, M025, M030, M036)
- Measure at each: node count, edge count, density, anchor count, orphan rate, diameter, clustering coefficient
- Plot each metric over time
- Look for inflection points (where did the graph structure change?)

**Status:** Not started

---

### D2: Sentence-level contradiction detection

We detect contradictions at the decision level (CONTRADICTS edges). But with sentence-level decomposition, contradictions can exist between individual sentences from different decisions.

**What we know:**
- Exp 6 found D073/D096/D100 (calls/puts) as a contradiction cluster at the decision level
- At sentence level, D073_s0 ("calls and puts are equal citizens") and D204_s0 ("ignore puts for now, calls only") are a direct contradiction

**What we don't know:**
- Can we detect sentence-level contradictions automatically (zero-LLM)?
- How many sentence-level contradictions exist in the alpha-seek data?
- Does sentence-level contradiction detection find things decision-level misses?
- What's the false positive rate? (Sentences that look contradictory but aren't because of scoping/context)

**Test design:**
- Decompose all decisions into sentence nodes
- For each pair of sentences: compute similarity (FTS5 or SimHash)
- High-similarity pairs with negation patterns = contradiction candidates
- Manual review of top 20 candidates: how many are real contradictions?
- Compare to decision-level contradiction detection (Exp 6 v1)

**Status:** Not started

---

### D3: What's the right TEMPORAL_NEXT granularity?

Time dimension research (Exp 19) proposed TEMPORAL_NEXT edges but didn't specify granularity.

**What we know:**
- 1,790 events in the timeline
- 213 active hours over 16 days
- Events cluster heavily (382 events in one hour on Apr 6)

**What we don't know:**
- Should every event link to its successor? (1,789 TEMPORAL_NEXT edges -- dense)
- Or only significant events? (Decisions, milestone starts/ends, corrections)
- What does temporal traversal look like at each granularity?
- Does denser temporal linking help retrieval or just add noise?

**Test design:**
- Build three variants: (a) all events linked, (b) only decisions+milestones linked, (c) only corrections+milestones linked
- For each: total TEMPORAL_NEXT edges, average chain length, connectivity
- Query test: "what happened after D097?" -- compare results across variants
- Measure: does temporal linking improve retrieval for temporal queries vs non-temporal queries?

**Status:** Not started

---

## Resolved: Vocabulary Mismatch (F1 follow-up)

**Original problem:** D157 ("ban async_bash") missed by all retrieval methods when querying "agent behavior." Zero vocabulary overlap.

**Resolution:** Two-part solution:

1. **LLM-in-the-loop directive storage (Exp 28):** The LLM calls a `directive` tool at the moment it understands the user's directive. The tool captures `related_concepts` (semantic tags) that bridge the vocabulary gap. The LLM knows "async_bash" relates to "agent behavior" -- it just needs to say so at storage time.

2. **Automatic query-seeded injection:** When the user's prompt mentions "dispatch" or "deploy," the memory system automatically injects all relevant directives (runbook, dispatch gate rules, etc.) BEFORE the LLM sees the prompt. This is a hard guarantee from the memory system -- the LLM never sees a prompt without relevant directives attached.

The guarantee decomposition:
- Directive stored: HARD (SQLite WAL, locked)
- Directive injected when relevant: HARD (memory system controls context injection)
- Directive survives compression: HARD (hybrid persistence)
- LLM obeys directive: SOFT (LLM compliance is not our code, addressable via hooks + detection)

The first three eliminate the alpha-seek failure mode (13 dispatch overrides because the runbook wasn't in context). The fourth is a smaller, separate problem.

**Both components need deep research independently:**

### F4: LLM-in-the-loop directive storage (deep dive)

How reliable is LLM tool-calling for directive capture across models? What prompt engineering makes it consistent?

**Key design decision:** Edge cases (implicit directives, conditional scope, conflicts) should be resolved by asking the user, not by guessing. The Bayesian uncertainty signal can trigger a clarification interview when the system encounters a directive it can't classify confidently:

- Ambiguous scope ("use strict typing" -- all files? production only?) -> interview
- Possible conflict (new directive contradicts existing one) -> interview
- Implicit preference ("I prefer TypeScript" -- is this a directive or an observation?) -> interview

This is analogous to GSD's interview pattern where the agent conducts structured questioning to clarify intent. The trigger is entropy: high-uncertainty directives get escalated to the user rather than stored with a guess.

Remaining research questions:
- What's the right `related_concepts` taxonomy?
- How many tags per directive? (3-5 seems right, needs testing)
- Can we validate the LLM's semantic tagging accuracy?
- What's the UX for the clarification interview? (Inline? Separate tool call? Batched?)

**Status:** Partially resolved (interview pattern for edge cases). Tagging accuracy and taxonomy need research.

### F5: Automatic query-seeded context injection (deep dive)

What's the latency budget for pre-LLM injection? How do we extract query terms from the user's prompt without an LLM (the prompt hasn't been processed yet)? How do we avoid injecting too much (every prompt gets 50 directives = token bloat) or too little (relevant directive missed)? How does this interact with the L0/L1/L2 token budgets? What if the user's prompt is ambiguous and multiple directive domains are relevant? How does injection work when the MCP server is called via tools (the prompt is the tool parameters, not the user's original message)?

**Status:** Needs research

---

## Meta-Questions

### M1: When is the design space sufficiently explored?

We could research forever. What criteria tell us it's time to move from research to architecture?

**Possible criteria:**
- Every core requirement (REQ-001 to REQ-026) has at least one validated approach
- No foundational question remains without at least a hypothesis
- The user says so

**Status:** This is the user's decision, not ours.

---

### M2: What's the minimum viable research prototype?

Not the final system, but the smallest thing we could build to test the core ideas together (graph + HRR + sentence decomposition + correction detection + session recovery) on real data.

**Status:** Not yet -- still exploring the design space.
