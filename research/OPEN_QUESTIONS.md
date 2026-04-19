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

**Status:** CLOSED (2026-04-18). Validated in test_design_decisions.py: type-aware filtering keeps all 5 critical beliefs at 60% budget; random drops some. Progressive filtering never loses critical content. Existing compression is sufficient.

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

**Status:** CLOSED (2026-04-18). Validated in test_design_decisions.py: belief type classification persists correctly across all source origins (user_stated, document_recent, agent_inferred, user_corrected). No hidden misclassification by content origin.

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

**Status:** CLOSED (2026-04-18). Validated in test_design_decisions.py: edge density increases over time, hubs emerge naturally, orphan rate drops from 100% to <20% as connectivity grows. Graph infrastructure handles temporal evolution correctly. Academic interest only.

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

**Status:** CLOSED (2026-04-18). Validated in test_design_decisions.py: detect_relationships() catches negation contradictions, value contradictions, and scope changes at belief level. Zero false positives on compatible beliefs with high vocabulary overlap. Current belief-level detection already works at the granularity needed.

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

**Status:** CLOSED (2026-04-18). Validated in test_design_decisions.py: BFS finds chain members via TEMPORAL_NEXT, temporal queries retrieve chain beliefs, temporal edges don't leak into unrelated queries, valence is correctly zero. Current implementation is sound; granularity question is moot.

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

---

## Conversation Ingestion (affects primary knowledge pathway)

These questions were opened on 2026-04-10 when conversation turns were adopted as the
primary ingestion pathway. They need answers before the extraction pipeline can operate
on live conversations.

### C1: How to intercept conversation turns?

The system needs to see each conversation turn as it happens so it can extract beliefs.
The question is where in the pipeline to tap in and what the turn looks like when we get it.

**What we know from existing research (HOOK_INJECTION_RESEARCH.md, CLI_INJECTION_MECHANISMS.md):**

- Claude Code supports `PostToolUse` and `Stop` hooks that fire after the model responds.
  A `Stop` hook fires when the model finishes its full response -- this is the natural
  interception point for "conversation turn complete, now extract beliefs."
- Codex CLI supports `PostToolUse` hooks and `UserPromptSubmit` for pre-processing.
  No `Stop` equivalent documented.
- Both CLIs support `SessionStart` hooks for injecting context at the beginning of a session.
  We already use this for MemPalace protocol.
- MCP tools can be called by the model during a turn, but the model has to choose to call
  them. This is unreliable for automatic extraction -- the model might forget or decide not to.
- Neither CLI allows modifying the system prompt via hooks. Hook output goes to context
  (lower authority).
- Hook output is capped at 10,000 characters in Claude Code.

**What we don't know:**

- Does the `Stop` hook receive the full assistant response? Or just metadata?
  If it receives the response text, we can pipe it directly to the extraction pipeline.
  If not, we need another mechanism.
- Can we intercept the user's message too? The user's input often contains the actual
  decisions ("let's use PostgreSQL", "no that's wrong, the limit is $10K"). We need
  both sides of the conversation.
- What's the latency budget? If extraction takes 200ms and the hook blocks, the user
  feels a lag after every response. If we run async, we might miss context that matters
  for the next turn.
- How does this work for non-CLI platforms? Claude.ai web, API-only usage, IDE extensions?

**Possible approaches to evaluate:**

1. **Stop hook + async extraction (simplest, Claude Code only).**
   Write a `Stop` hook that dumps the assistant response to a file or pipe. A background
   process reads it and runs extraction. No latency impact. Limitation: doesn't capture
   the user's message (only the assistant's response is available in Stop hooks -- verify this).

   Quick validation: write a minimal Stop hook that logs the assistant response to a file.
   Check what fields are available. Takes 10 minutes.

2. **UserPromptSubmit hook for user side + Stop hook for assistant side.**
   Two hooks: one captures what the user said, one captures what the model said. Together
   they reconstruct the full turn. Both are async.

   Quick validation: same as above but add a UserPromptSubmit hook. Check if we get the
   raw user text. Takes 10 minutes.

3. **MCP tool called by the model ("remember this").**
   Instead of automatic extraction, the model calls a `remember` MCP tool when it detects
   something worth storing. This is what MemPalace does (mempalace_kg_add, mempalace_diary_write).
   Advantage: the model has full context and can extract high-quality beliefs. Disadvantage:
   the model might forget, might extract poorly, and it costs tokens.

   Quick validation: we already have this -- MemPalace is running. Check how reliably the
   model actually calls the memory tools. Review a few recent sessions for coverage gaps.

4. **Conversation export post-processing (batch, any platform).**
   Claude Code can export conversation history. Process exports after the fact rather than
   in real time. Loses the "immediate" property but works on any platform.

   Quick validation: export a conversation, run the Exp 42-style sentence decomposition on
   it, see how many beliefs it produces and what quality looks like. Takes 30 minutes.

**Recommendation:** Start with option 1 (Stop hook logging) to understand what data is
actually available. Then try option 4 (export processing) since we already have the
extraction pipeline and conversation exports. These two together cover "what can we get
in real time?" and "what can we get in batch?" without building anything new.

### C2: How to handle conversations that happen outside the system?

Decisions also happen in Slack threads, email chains, meetings, and whiteboard sessions.
These are observation sources that arrive differently from live conversation monitoring.

**What we know:**

- The extraction pipeline (sentence decomposition, classification, graph insertion) is
  source-agnostic. It operates on text. It doesn't care whether the text came from a
  conversation turn, a Slack message, or meeting notes.
- MemPalace has a `mempalace_mine` command that processes project files and conversation
  exports. This is batch import, not live monitoring.
- The onboarding pipeline (A031) already handles batch document processing.

**What we don't know:**

- What formats do external conversations arrive in? Slack JSON exports, email .eml files,
  meeting transcription text? Each needs a parser.
- How much overlap is there between decisions made in external channels and decisions
  that get repeated in AI conversation turns? If a Slack decision always gets restated
  to the AI ("we decided in Slack to use PostgreSQL"), external import is redundant.
  If not, external import is essential.
- How to handle attribution and timestamps? A Slack message from 3 days ago should get
  the right timestamp, not "today."
- Is this actually a priority? If 90% of actionable decisions happen in AI conversations,
  external import is a nice-to-have, not a blocker.

**Possible approaches:**

1. **"Tell me" model (simplest, no integration needed).**
   The user tells the AI about external decisions: "we decided in standup to drop feature X."
   The conversation turn pipeline captures it normally. No external integration required.
   Works today. Relies on the user remembering to relay decisions.

2. **Paste import.**
   The user pastes a Slack thread or meeting notes into a conversation. The extraction
   pipeline processes it as a regular turn. Slightly more structured than option 1.
   Works today with no changes.

3. **Batch file import (A031 extension).**
   Add parsers for Slack JSON exports, email exports, meeting transcription files.
   Run the same extraction pipeline. Good for catching up on external history.
   Medium effort (one parser per format).

4. **MCP integrations (Slack MCP, Gmail MCP, etc.).**
   Use existing MCP servers (we have Gmail MCP connected) to pull messages on demand.
   The AI could periodically check for relevant external decisions.
   Higher complexity, privacy concerns.

**Recommendation:** Start with option 1 (the user just tells the AI). Measure how often
external decisions get missed in practice. If it's rare, don't build anything. If it's
common, add option 3 (batch import for the most common format, probably Slack).

### C3: Privacy and consent for belief extraction

Storing beliefs extracted from conversations raises privacy questions. The user should
understand and control what's being remembered.

**What we know:**

- MemPalace stores conversations by default once configured. There's no per-belief
  consent mechanism. Users can search and delete drawers but there's no "the system is
  about to remember X, is that OK?" flow.
- Claude Code's auto-memory system (MEMORY.md) has explicit guidelines about what NOT
  to save (code patterns, git history, ephemeral task details). This is a useful model.
- Our scientific method model already has a concept of observation (raw, append-only)
  vs. belief (derived, revisable). This maps naturally to privacy tiers: observations
  might be kept temporarily, beliefs are the persistent store.

**What we don't know:**

- Do users want per-belief approval? ("I'm about to remember that you prefer PostgreSQL.
  OK?") This is safe but annoying. Nobody wants 5 confirmation prompts per conversation.
- Do users want category-level control? ("Remember my technical preferences but not
  personal details.") More practical but harder to classify reliably.
- What about multi-user scenarios? If user A mentions user B in a conversation, should
  beliefs about user B be stored? What if user B hasn't consented?
- Regulatory requirements? GDPR right to erasure means "forget everything about me" must
  be implementable. Our revision/supersession model handles this (supersede all beliefs
  about X with a tombstone), but we haven't verified the implementation would be complete.

**Possible approaches:**

1. **Transparency by default (simplest).**
   The system extracts and stores beliefs automatically, but makes them visible. At session
   start, show a brief summary: "I remember N things about you and this project. Say
   'show memories' to review, 'forget X' to remove." No per-belief approval, but full
   visibility and easy correction.

   This is close to what Claude Code's auto-memory already does (MEMORY.md is readable,
   the user can ask to forget things). Extend it to the belief graph.

2. **Sensitivity classification.**
   Classify extracted beliefs by sensitivity: technical decisions (low sensitivity),
   personal preferences (medium), personal information (high). Default to storing
   low/medium, ask before storing high.

   Quick validation: run the extraction pipeline on 5 real conversations and label each
   extracted belief for sensitivity. See how often "high sensitivity" comes up.
   If it's rare, option 1 is fine.

3. **Explicit opt-in for categories.**
   On first use, ask: "What should I remember? Technical decisions? Personal preferences?
   Project history? People?" Let the user toggle categories. Beliefs in disabled categories
   are extracted but not persisted.

**Recommendation:** Start with option 1 (transparent, visible, easy to correct). It's the
simplest approach that respects user autonomy without creating friction. If user testing
reveals that sensitive information is being stored inappropriately, add sensitivity
classification (option 2) as a filter.
