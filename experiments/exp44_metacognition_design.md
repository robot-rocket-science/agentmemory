# Experiment 44: Meta-Cognition Design -- Triggered Beliefs, FOK Protocol, and Directive Enforcement

**Date:** 2026-04-10
**Status:** Research complete
**Rigor tier:** Hypothesis (design research based on prior experimental evidence and cognitive architecture literature; not empirically tested)
**Depends on:** METACOGNITION_RESEARCH.md, CASE_STUDIES.md (CS-003, CS-005, CS-006, CS-020), REQUIREMENTS.md (REQ-027), GRAPH_CONSTRUCTION_RESEARCH.md (REQ-028), Exp 36 (hook injection)

---

## 1. Triggered Belief Registry Design

### 1.1 Detectable Events

The ECA (Event-Condition-Action) pattern requires events the system can actually observe. These fall into two categories: platform events (emitted by the agent harness) and memory events (emitted by the memory system itself).

**Platform events** (detectable via hooks or MCP tool calls):

| Event ID | Event | Detection Mechanism |
|----------|-------|---------------------|
| PE-01 | Session start | SessionStart hook (Exp 36 confirmed) |
| PE-02 | User prompt submitted | UserPromptSubmit hook (Exp 36 confirmed) |
| PE-03 | Task switch (new task ID appears) | MCP observe() call with task_id field change |
| PE-04 | Agent about to produce output | Pre-response hook (UserPromptSubmit fires before response generation) |
| PE-05 | Context compression triggered | Harness-specific; Claude Code emits compactPrompt event |

**Memory events** (detectable within the memory system):

| Event ID | Event | Detection Mechanism |
|----------|-------|---------------------|
| ME-01 | Retrieval failure (query returns zero beliefs) | search() returns empty result set |
| ME-02 | User correction detected | observe() classifies input as correction (V2 detector, 92% accuracy per Exp 1) |
| ME-03 | Belief confidence drops below threshold | SQLite trigger on beliefs.confidence UPDATE (per GRAPH_CONSTRUCTION_RESEARCH.md section 5) |
| ME-04 | Contradiction detected | Two beliefs with CONTRADICTS edge, both confidence > 0.5 |
| ME-05 | Locked belief accessed | search() returns a belief with locked=true |
| ME-06 | State document referenced | FTS5 match on known state document names (TODO.md, REQUIREMENTS.md, etc.) |
| ME-07 | Time since last state check exceeds threshold | Timestamp comparison against last search() call with state-doc query |

### 1.2 Checkable Conditions

Conditions are predicates evaluated when an event fires. They determine whether the action executes.

| Condition ID | Condition | Evaluation Method |
|--------------|-----------|-------------------|
| C-01 | State document exists for this project | File existence check OR belief with category="state_document" exists |
| C-02 | Belief count for topic > 0 | FTS5 query against belief content, count result |
| C-03 | Time since last state check > N minutes | Compare current time against last_state_check timestamp |
| C-04 | Active locked beliefs exist | SELECT count(*) FROM beliefs WHERE locked=true AND project_id=? |
| C-05 | Current task ID matches a known task | Task ID extracted from instruction matches entry in task registry |
| C-06 | Directive exists for the action about to be taken | FTS5 query against locked behavioral beliefs for action keywords |
| C-07 | Retrieval returned conflicting beliefs | Returned belief set contains CONTRADICTS edges |
| C-08 | Agent is about to ask user for direction | Output contains question patterns: "what would you like", "what's next", "do you want to" |

### 1.3 Available Actions

| Action ID | Action | Cost |
|-----------|--------|------|
| A-01 | Self-check: query state documents before proceeding | 1 FTS5 query (~5ms) |
| A-02 | Re-inject directive into context | Read locked beliefs, append to response context (~10ms) |
| A-03 | Escalate to user with specific question | Generate clarification, present to user |
| A-04 | Block output and re-route | Suppress current response, force state-document consultation |
| A-05 | Log meta-cognitive event for later review | INSERT into metacognitive_log table (~2ms) |
| A-06 | Verify task ID against instruction | Extract IDs from user message, compare to generated IDs |
| A-07 | Surface contradiction with both sides | Format conflicting beliefs with evidence chains |
| A-08 | Run FOK check (see section 2) | 1-2 FTS5 queries + optional BFS (~20-50ms) |

### 1.4 The Registry: 15 Triggered Beliefs

Each row maps to a specific case study failure it would have prevented.

| TB ID | Event | Condition | Action | Prevents | Priority |
|-------|-------|-----------|--------|----------|----------|
| TB-01 | PE-04 (about to produce output) | C-08 (output asks user for direction) | A-01 (query state documents first) | **CS-003**: agent asked user "what's next?" instead of reading TODO.md | P1 (safety) |
| TB-02 | PE-01 (session start) | C-04 (locked beliefs exist) | A-02 (re-inject all locked beliefs) | **CS-006**: locked prohibition on implementation talk was read but not enforced | P1 (safety) |
| TB-03 | PE-02 (user prompt submitted) | C-06 (directive exists for pending action) | A-02 (re-inject relevant directives) | **CS-006**: per-turn directive injection, matching Exp 36 Condition C (0% violation rate) | P1 (safety) |
| TB-04 | PE-03 (task switch) | C-05 (task ID in instruction) | A-06 (verify task ID against instruction) | **CS-020**: agent generated Exp 40 when user said #41 | P2 (user corrections) |
| TB-05 | PE-01 (session start) | C-01 (state documents exist) | A-08 (run FOK check on project state) | **CS-005**: new agent formed miscalibrated view of project maturity | P2 (user corrections) |
| TB-06 | PE-05 (context compression) | C-04 (locked beliefs exist) | A-02 (verify locked beliefs survived compression) | **CS-004**: locked beliefs lost to context compression | P1 (safety) |
| TB-07 | ME-01 (retrieval failure) | C-02 (belief count for topic = 0) | A-03 (escalate to user with targeted question) | General: agent hallucinating instead of admitting knowledge gap | P3 (operational) |
| TB-08 | ME-02 (user correction) | Always | A-02 (promote to locked L0 belief) | **CS-002**: user corrected 3+ times on same topic | P1 (safety) |
| TB-09 | ME-04 (contradiction detected) | C-07 (conflicting beliefs in result) | A-07 (surface contradiction explicitly) | REQ-002: no silent contradictions | P2 (user corrections) |
| TB-10 | PE-04 (about to produce output) | C-06 (behavioral prohibition matches output content) | A-04 (block output, re-route) | **CS-006**: agent output contained "implementation" despite prohibition | P1 (safety) |
| TB-11 | PE-01 (session start) | C-03 (time since last state check > session length) | A-01 (query state documents, present delta) | General: stale context on session resume | P3 (operational) |
| TB-12 | PE-03 (task switch) | C-01 (state documents exist) | A-01 (query TODO.md for new task context) | **CS-003**: task context not loaded on switch | P3 (operational) |
| TB-13 | ME-05 (locked belief accessed) | Always | A-05 (log access for audit trail) | REQ-020: audit that locked beliefs are being consulted | P4 (learned patterns) |
| TB-14 | PE-04 (about to produce output) | Output claims validation/completion of findings | A-08 (FOK check: verify rigor tier of cited findings) | **CS-005**, **CS-007**: presenting hypothesis-tier findings as validated | P2 (user corrections) |
| TB-15 | ME-03 (belief confidence drops below 0.5) | Belief was previously used in a response | A-03 (escalate: "A belief I previously cited has been downgraded") | General: proactive uncertainty communication | P4 (learned patterns) |

### 1.5 Conflict Resolution

When multiple triggered beliefs fire simultaneously, resolution follows the priority ordering from METACOGNITION_RESEARCH.md section 5:

1. **P1 (safety/locked beliefs):** TB-02, TB-03, TB-06, TB-08, TB-10. These always fire first. If TB-10 blocks output AND TB-01 wants to self-check, TB-10 wins (block is stronger than check).
2. **P2 (user corrections):** TB-04, TB-05, TB-09, TB-14. Fire after P1.
3. **P3 (operational rules):** TB-01, TB-07, TB-11, TB-12. Fire after P2.
4. **P4 (learned patterns):** TB-13, TB-15. Fire last, and only if P1-P3 haven't already addressed the issue.

Within a priority tier, all applicable rules fire (no mutual exclusion within tiers). Actions are composable: A-01 (self-check) and A-02 (re-inject directive) can both execute for the same event.

### 1.6 Case Study Walkthrough: How the Registry Prevents CS-003

**Scenario:** All research tasks are completed. Agent is about to respond to user with "What do you want to explore next?"

1. **PE-04 fires** (agent about to produce output).
2. **TB-01 evaluates:** Is the output asking the user for direction? Pattern match on "what do you want" -- yes.
3. **TB-01 condition:** Does a state document exist? Check for TODO.md -- yes.
4. **TB-01 action:** A-01 fires. FTS5 query against TODO.md content. Returns pending task items.
5. **Output re-routed:** Instead of "What do you want to explore next?", agent says "TODO.md has the following pending items: [list]. Which of these should I tackle next?"

Total added latency: ~5ms (one FTS5 query). Total tokens: ~50 (task list injection). CS-003 prevented.

### 1.7 Case Study Walkthrough: How the Registry Prevents CS-020

**Scenario:** User says "Build the #41 traceability extractor." Agent is about to create `exp40_traceability_extraction.py`.

1. **PE-03 fires** (task switch -- new task ID #41 detected in instruction).
2. **TB-04 evaluates:** Does the instruction contain a task ID? Extract "#41" -- yes.
3. **TB-04 action:** A-06 fires. Agent is generating filename `exp40_*`. Compare 40 vs 41. Mismatch detected.
4. **Additional check:** Does `exp40_*` already exist? Yes (`exp40_hybrid_retrieval_plan.md`). Double failure: wrong number AND collision.
5. **Output corrected:** Filename changed to `exp41_traceability_extraction.py`. CS-020 prevented.

---

## 2. FOK (Feeling-of-Knowing) Check Protocol

### 2.1 What the FOK Check Is

The FOK check is a pre-action self-interrogation: "Do I have stored beliefs or state documents that should inform the decision I'm about to make?" It is the functional equivalent of the tip-of-the-tongue state in metamemory research (Schwartz, 1994; Nelson & Narens, 1990, cited in METACOGNITION_RESEARCH.md section 4).

The FOK check is not a general-purpose "think before acting" mechanism. It is a targeted retrieval probe that fires at specific decision points.

### 2.2 FOK Trigger Conditions

The FOK check fires when:

1. **Agent is about to ask the user a question** (TB-01 trigger). Before any user-directed question, check whether the answer is already stored.
2. **Agent is about to claim a fact or status** (TB-14 trigger). Before asserting project state, check what the memory system actually has on the topic.
3. **Agent hits a decision point with multiple options.** Before choosing, check whether a prior decision or preference has been recorded.
4. **Retrieval returns zero results for a query the agent expected to match** (ME-01). The absence itself is information: either the topic was never discussed, or the query is malformed.

### 2.3 FOK Protocol Pseudocode

```
FUNCTION fok_check(decision_context: str, action_type: ActionType) -> FOKResult:
    """
    Pre-action self-interrogation.
    Latency budget: 50ms hard cap.
    """

    # Step 1: Extract key entities and topics from the decision context
    topics = extract_topics(decision_context)  # zero-LLM: regex + keyword extraction
    # Cost: ~1ms

    # Step 2: FTS5 probe against state documents
    state_hits = fts5_search(
        query=topics,
        table="state_documents",  # TODO.md, REQUIREMENTS.md, SESSION_LOG.md
        limit=5
    )
    # Cost: ~5ms

    # Step 3: FTS5 probe against belief store
    belief_hits = fts5_search(
        query=topics,
        table="beliefs",
        filters={"confidence": ">= 0.3"},  # skip very-low-confidence noise
        limit=10
    )
    # Cost: ~5ms

    # Step 4: If belief hits exist, optional BFS expansion (1 hop only)
    IF belief_hits AND time_remaining > 20ms:
        neighbors = bfs_expand(
            seed_nodes=[b.id for b in belief_hits[:3]],
            max_depth=1,
            max_nodes=20
        )
        belief_hits = merge_and_rank(belief_hits, neighbors)
    # Cost: ~10-20ms

    # Step 5: Assess epistemic state
    state = assess_epistemic_state(topics, belief_hits)
    # ABSENT, VERY_UNCERTAIN, UNCERTAIN, UNTESTED, CONFLICTED, GROUNDED
    # (per GRAPH_CONSTRUCTION_RESEARCH.md section 3)

    # Step 6: Determine action
    IF state == ABSENT AND action_type == ASKING_USER:
        RETURN FOKResult(
            found=False,
            action=PROCEED_WITH_QUESTION,
            note="No stored beliefs on this topic. Question is warranted."
        )

    IF state == ABSENT AND action_type == CLAIMING_FACT:
        RETURN FOKResult(
            found=False,
            action=HEDGE_OR_ABSTAIN,
            note="No stored beliefs. Do not assert. Admit uncertainty."
        )

    IF state in (GROUNDED, UNTESTED):
        RETURN FOKResult(
            found=True,
            beliefs=belief_hits,
            state_docs=state_hits,
            action=USE_STORED_CONTEXT,
            note="Relevant beliefs found. Use them."
        )

    IF state == CONFLICTED:
        RETURN FOKResult(
            found=True,
            beliefs=belief_hits,
            action=SURFACE_CONTRADICTION,
            note="Conflicting beliefs found. Surface both sides."
        )

    IF state in (UNCERTAIN, VERY_UNCERTAIN):
        RETURN FOKResult(
            found=True,
            beliefs=belief_hits,
            action=USE_WITH_CAVEAT,
            note="Low-confidence beliefs found. Use with hedging."
        )
```

### 2.4 Latency Budget

| Step | Operation | Expected Latency | Hard Cap |
|------|-----------|-----------------|----------|
| Topic extraction | Regex + keywords | ~1ms | 5ms |
| FTS5 state doc probe | SQLite FTS5 query | ~5ms | 10ms |
| FTS5 belief probe | SQLite FTS5 query | ~5ms | 10ms |
| BFS expansion (optional) | In-memory adjacency, 1 hop | ~10ms | 20ms |
| Epistemic assessment | Confidence arithmetic | ~1ms | 5ms |
| **Total** | | **~22ms** | **50ms** |

The 50ms hard cap is chosen to be invisible to the user. Even at 20 decision points per session, total overhead is 1 second. The BFS expansion step is optional and skipped if the FTS5 probes already consumed >30ms.

### 2.5 What Happens When FOK Fires But Retrieval Finds Nothing Useful

This is the critical edge case. The FOK check fires (the system suspects it should know something), but the search returns nothing relevant. Four possible outcomes:

1. **True negative -- topic genuinely unknown.** The system has never encountered this topic. FOK returns ABSENT. Action: proceed normally, but mark the decision point as an epistemic gap for future learning.

2. **False negative -- vocabulary mismatch.** The system has beliefs on the topic, but the FTS5 query used different terms. This is the vocabulary gap problem that HRR was designed to solve (Exp 40: HRR walk rescued D157 "async_bash" when FTS5 missed it). Action: if FTS5 returns ABSENT, optionally run an HRR nearest-neighbor probe as a fallback (~10ms additional, within budget).

3. **False negative -- state document exists but isn't indexed.** The system has a TODO.md but hasn't ingested it into the belief store. Action: the state document FTS5 probe (step 2) checks file content directly, not just beliefs. This catches state documents that exist as files but haven't been processed into beliefs yet.

4. **True negative but decision-relevant.** No beliefs exist, and that absence IS the information. Example: the system has no belief about "which database to use" -- this means the user hasn't decided yet. The FOK check should surface this absence as "no decision recorded on this topic" rather than letting the agent pick one arbitrarily.

### 2.6 FOK Check vs. Full Retrieval

The FOK check is not a replacement for the full retrieval pipeline. It is a pre-filter:

| Dimension | FOK Check | Full Retrieval |
|-----------|-----------|----------------|
| Purpose | "Do I have anything relevant?" | "Give me the best context for this task" |
| Latency | 20-50ms | 100-500ms |
| Depth | FTS5 probe + 1-hop BFS | FTS5 + HRR + multi-hop BFS + ranking |
| Output | Boolean + epistemic state | Ranked belief set with evidence chains |
| When | Before specific actions (asking, claiming, deciding) | On every task context load |

The FOK check should NOT replace full retrieval. It is a lightweight gate that catches the CS-003 class of failures (agent didn't even check) without the cost of a full retrieval pipeline on every utterance.

---

## 3. Recursion Depth Cap Validation

### 3.1 The Proposed Cap: 2 Levels

METACOGNITION_RESEARCH.md proposed bounding meta-cognition to two levels:

- **Level 0 (object level):** Beliefs about the domain. "User prefers PostgreSQL." "TODO.md has 5 pending items."
- **Level 1 (meta level):** Beliefs about the system's own beliefs. "I have a TODO.md." "I have a locked directive against implementation talk." "My belief about PostgreSQL is low-confidence."

The question: is there any scenario where Level 2 meta-cognition ("Do I know that I know that I have a TODO.md?") is useful?

### 3.2 What Level 3 Would Look Like

Level 2 meta-belief: "I know that I have a mechanism for checking whether I have state documents."
Level 3 meta-belief: "I know that I know that I have a mechanism for checking whether I have state documents."

Concretely: Level 2 would be the system monitoring whether its own triggered belief registry is functioning. Level 3 would be the system monitoring whether its Level 2 monitoring is functioning.

### 3.3 SOAR's Experience with Recursive Substates

SOAR's impasse-driven substates are theoretically unbounded in depth. In practice, Laird (2022, arXiv:2205.03854) reports:

- **Typical depth: 1-2 substates.** Most problem-solving impasses are resolved within one substate. The substate inspects the superstate, finds the missing knowledge or resolves the tie, and returns.
- **Depth 3+ is rare and usually pathological.** When SOAR creates 3+ nested substates, it typically indicates a poorly designed knowledge base or an intractable problem. The system is thrashing, not making productive meta-cognitive progress.
- **Chunking collapses depth.** SOAR's chunking mechanism compiles successful substate reasoning into production rules that fire directly, eliminating the need for the substate on future encounters. This is analogous to our triggered beliefs: instead of recursing to check whether we have a TODO, we pre-compile the check as a triggered belief (TB-01).

The CLARION architecture (Sun, 2016) takes an even stronger position: the Meta-Cognitive Subsystem is architecturally one level above the reasoning system. There is no meta-meta-cognitive subsystem. CLARION's designers considered and rejected deeper recursion on engineering grounds.

ACT-R does not support recursive meta-cognition at all (Laird & Mohan, 2022, arXiv:2201.09305). Its production rules can inspect buffer states (1 level of meta-cognition), but there is no mechanism for productions about productions about buffer states.

### 3.4 Analysis: Is Level 2 Ever Useful?

**Candidate scenario:** The triggered belief registry itself has a bug. TB-01 should fire when the agent is about to ask the user for direction, but it doesn't fire because the pattern match is wrong. Level 2 meta-cognition would detect that TB-01 didn't fire when it should have.

**Assessment:** This is a real concern, but the solution is not a third meta-cognitive level. The solution is testing. If TB-01 has a bug, that's caught by the acceptance test for CS-003, not by a meta-meta-cognitive monitor. Adding a monitor-of-monitors creates the same problem one level up (who monitors the monitor?) with no termination condition.

**Candidate scenario 2:** The system needs to reason about its own meta-cognitive overhead. "My FOK checks are taking too long and slowing down responses. I should reduce the BFS expansion depth." This is Level 2: reasoning about the performance of Level 1 mechanisms.

**Assessment:** This is a valid use case, but it does not need to operate at inference time. It is an offline tuning task. Log FOK check latencies, analyze them between sessions, adjust parameters. No real-time Level 2 reasoning required.

### 3.5 Verdict: 2-Level Cap Confirmed

The 2-level cap proposed in METACOGNITION_RESEARCH.md is correct. Supporting evidence:

1. SOAR's depth-3+ substates are pathological, not productive.
2. CLARION architecturally caps at 1 level of meta-cognition.
3. ACT-R does not support recursive meta-cognition.
4. Every candidate Level 2 scenario we found is better solved by testing (offline) or parameter tuning (offline), not by real-time recursive self-monitoring.
5. The infinite regress problem (Kp -> KKp -> KKKp...) is real in epistemic logic and has no natural termination condition. A hard cap is the only engineering solution.

**Implementation consequence:** Triggered beliefs (TB-01 through TB-15) are L0, always loaded, and locked. They are NOT themselves subject to triggered belief evaluation. No triggered belief can fire a meta-check on another triggered belief. This is the architectural bound.

---

## 4. Connection to REQ-027 (Directive Enforcement)

### 4.1 The Problem

REQ-027 requires: when a user issues a permanent directive ("never use async_bash", "do not mention implementation"), the memory system enforces it with zero failures. REQUIREMENTS.md decomposes this into 6 tiers:

| Tier | Mechanism | Our Control? |
|------|-----------|-------------|
| 1. Storage | SQLite WAL, locked belief | Yes (100%) |
| 2. Injection | L0 always-loaded | Yes (100%) |
| 3. Compression survival | Config + compactPrompt | Yes (99%+) |
| 4. Violation detection | Pattern matching on output | Yes (99%+) |
| 5. Violation blocking | Pre-execution hooks | Yes (where hooks exist) |
| 6. LLM compliance | The LLM obeys | No (soft constraint) |

Tiers 1-3 are storage and delivery. Tiers 4-5 are enforcement. Tier 6 is the LLM's problem.

### 4.2 The Specific ECA Rule for Directive Enforcement

Directive enforcement maps to three triggered beliefs working in concert:

**TB-02 (session start injection):**
```
Event:     PE-01 (session start)
Condition: C-04 (locked beliefs exist)
Action:    A-02 (inject all locked behavioral beliefs into L0 context)
```

This ensures every session begins with all directives present. It is Exp 36 Condition B, which achieved 0/10 violation rate.

**TB-03 (per-turn re-injection):**
```
Event:     PE-02 (user prompt submitted)
Condition: C-06 (directive exists matching upcoming action domain)
Action:    A-02 (inject relevant directives into response context)
```

This is Exp 36 Condition C. Per-turn injection provides continuous pressure. The advantage over TB-02 alone is drift resistance in multi-turn conversations (untested -- Exp 36 was single-turn only, see Exp 36 limitation #2).

**TB-10 (output blocking):**
```
Event:     PE-04 (about to produce output)
Condition: C-06 (behavioral prohibition matches output content)
Action:    A-04 (block output, re-route)
```

This is the enforcement layer. TB-02 and TB-03 inject the directive. TB-10 checks the output against it. If the output contains a prohibited pattern, the output is blocked before the user sees it.

### 4.3 Interaction with Hooks (Exp 36)

Exp 36 demonstrated that hook injection is sufficient for behavioral constraint enforcement (p = 0.0043 for baseline vs. hook conditions). The triggered belief registry builds on this:

| Layer | Mechanism | Exp 36 Evidence | Triggered Belief |
|-------|-----------|-----------------|-----------------|
| Injection (session start) | SessionStart hook | 0/10 violations (Condition B) | TB-02 |
| Injection (per-turn) | UserPromptSubmit hook | 0/10 violations (Condition C) | TB-03 |
| Blocking (pre-output) | Not tested in Exp 36 | -- | TB-10 (new) |

TB-10 is the layer Exp 36 did not test. It requires output inspection, which is architecturally different from input injection. Two implementation approaches:

1. **Hook-based:** A post-generation, pre-display hook that scans the response for prohibited patterns. Requires the harness to support output interception. Claude Code supports this via UserPromptSubmit (fires before the model sees the prompt, so the prohibition is in context) but does not currently support post-generation blocking.

2. **MCP-based:** The MCP server's search() tool, called by the agent as part of its reasoning, returns directive violations as part of the epistemic state. The agent self-corrects before output. This relies on the agent actually calling search(), which is not guaranteed.

3. **Hybrid:** Inject via hook (TB-02/TB-03, proven by Exp 36) AND detect violations via MCP tool response metadata. If the agent calls any MCP tool and the response includes a directive_violation flag, the agent is prompted to self-correct.

Approach 3 is the most robust. It layers injection (proven) with detection (new, untested) without requiring post-generation hooks that may not exist on all platforms.

### 4.4 The Directive Enforcement Pipeline (Full)

```
SESSION START
  |
  v
TB-02 fires: inject all locked directives into L0
  |
  v
USER SUBMITS PROMPT
  |
  v
TB-03 fires: inject relevant directives into response context
  |
  v
AGENT REASONS (may call MCP tools)
  |
  v
MCP search() returns: {beliefs: [...], directives: ["never mention implementation"]}
  |
  v
AGENT GENERATES OUTPUT
  |
  v
TB-10 evaluates: does output match any prohibited patterns?
  |
  +-- NO  --> output delivered to user
  |
  +-- YES --> output blocked
              |
              v
              A-04: re-route. Agent re-generates with directive re-emphasized.
              |
              v
              Log violation for audit (A-05).
              If re-generation also violates: escalate to user (A-03).
              "I'm struggling to respond without mentioning [topic].
               The directive says [directive]. How should I proceed?"
```

### 4.5 Failure Modes of the Directive Pipeline

1. **Hook not configured.** If the user hasn't set up SessionStart/UserPromptSubmit hooks, TB-02 and TB-03 can't fire. Mitigation: the MCP server detects missing hooks on first call and warns the user.

2. **Directive too vague for pattern matching.** "Don't be too verbose" is harder to pattern-match than "never use async_bash." Mitigation: directive storage should include a `match_patterns` field -- concrete patterns the system can check against. Vague directives get a warning: "This directive is stored but cannot be automatically enforced. It will be injected as context only."

3. **Output blocking false positives.** TB-10 might block legitimate uses of prohibited terms (e.g., "implementation" in a sentence about someone else's implementation, not a suggestion to implement). Mitigation: pattern matching should include surrounding context, not just keyword presence. Exp 36 analysis notes this distinction: "builds on above" was not a violation despite containing "build."

4. **Re-generation loop.** If the agent can't produce a valid response without violating the directive, the re-generation loop could cycle indefinitely. Mitigation: hard cap of 1 re-generation attempt. After that, escalate to user.

---

## 5. Meta-Cognitive Overhead Analysis

### 5.1 Cost of Meta-Cognition

Every triggered belief evaluation, FOK check, and directive scan costs time and tokens. The question: at what point does meta-cognition become more expensive than the failures it prevents?

**Per-decision-point costs:**

| Operation | Latency | Tokens | Frequency |
|-----------|---------|--------|-----------|
| TB evaluation (all 15 rules) | ~5ms | 0 (internal) | Every event |
| FOK check (full protocol) | ~22ms (typical), 50ms (cap) | ~50 (injected beliefs) | ~5 per session (decision points) |
| Directive injection (TB-02) | ~3ms | ~100 (directive text) | 1 per session |
| Per-turn directive re-injection (TB-03) | ~3ms | ~100 per turn | Every turn |
| Output pattern check (TB-10) | ~2ms | 0 (internal) | Every output |

**Per-session costs (assuming 20-turn session, 5 major decision points):**

| Cost Category | Latency | Tokens |
|---------------|---------|--------|
| TB evaluation (20 turns x 5ms) | 100ms | 0 |
| FOK checks (5 x 22ms) | 110ms | 250 |
| Directive injection (1 + 20 turns) | 63ms | 2,100 |
| Output checks (20 x 2ms) | 40ms | 0 |
| **Total per session** | **313ms** | **2,350** |

### 5.2 Cost of NOT Having Meta-Cognition

The cost of a meta-cognitive failure is measured in user time, user frustration, and rework.

| Failure | Cost (User Time) | Cost (Agent Rework) | Frequency (from case studies) |
|---------|-------------------|---------------------|-------------------------------|
| CS-003 (not consulting state) | 2-5 min (user re-explains) | Agent re-reads TODO, restarts | At least 1x per project |
| CS-005 (maturity inflation) | 5-10 min (user corrects framing) | Agent re-calibrates entire status | Every new session (pre-fix) |
| CS-006 (directive violation) | 2-5 min (user re-issues directive, frustrated) | Agent re-generates response | 60% of sessions (Exp 36 baseline) |
| CS-020 (wrong task ID) | 5-10 min (rename files, fix references) | Agent renames, edits 2+ docs | Unknown frequency, at least 1x |

**Worst case:** CS-006 occurs in 60% of sessions without hook injection (Exp 36). Each occurrence costs the user ~3 minutes of frustration and re-correction. Over 10 sessions: 6 occurrences x 3 min = 18 minutes of user time wasted.

**Meta-cognition cost over 10 sessions:** 313ms x 10 = 3.13 seconds of latency. 2,350 x 10 = 23,500 tokens.

### 5.3 Break-Even Analysis

At what failure rate does meta-cognition pay for itself?

**Latency:** 313ms of overhead per session vs. even a single 2-minute user correction. The meta-cognition overhead is invisible (< 0.5 seconds) while failures cost minutes. Break-even: meta-cognition pays for itself if it prevents even one failure per ~400 sessions (0.3s overhead x 400 = 120s = 2 min). Since CS-006 alone occurs in 60% of sessions without mitigation, the ROI is at least 100x.

**Tokens:** 2,350 tokens per session. At current API pricing (~$3/M input tokens for Sonnet), that's ~$0.007 per session. A single CS-005 failure wastes 5-10 minutes of a user's time. Even valuing the user's time at minimum wage ($7.25/hr), one prevented failure ($0.60-1.20 of user time) pays for ~85-170 sessions of meta-cognitive overhead.

**Where overhead becomes a concern:**

The main cost is not latency or API tokens. It is the directive re-injection token budget: 2,100 tokens per session for per-turn directive injection. REQ-003 requires total retrieval budget <= 2,000 tokens for L0+L1+L2. If directive injection consumes 2,100 tokens alone, it blows the budget.

Resolution: directives are part of L0, not additional to L0. The L0 budget (which is a fixed allocation, always loaded) must include directive text. If directives consume 500 tokens of a 600-token L0 allocation, that leaves only 100 tokens for other L0 beliefs. This is the real constraint, not latency.

**Design implication:** Directives must be stored in distilled form. Not "The user said on 2026-04-09: 'i told you already, no implementation... do not ask me about implementation again until i say its time'" (52 tokens). Instead: "PROHIBITION: Do not mention implementation, readiness to build, or phase transition. Active until user lifts." (19 tokens). Exp 36 proved that a 4-line distilled prohibition file was sufficient.

### 5.4 Scaling Limits

| Scenario | TB Evals | FOK Checks | Directive Tokens | Total Latency | Concern? |
|----------|----------|------------|-----------------|---------------|----------|
| 10 directives, 20 turns | 100 | 5 | 3,000 | ~400ms | Token budget pressure |
| 50 directives, 20 turns | 100 | 5 | 10,000 | ~500ms | Token budget violated |
| 10 directives, 100 turns | 500 | 15 | 10,000 | ~1.5s | Marginal |
| 50 directives, 100 turns | 500 | 15 | 50,000 | ~2.5s | Unacceptable |

**Scaling limit:** At 50+ directives, per-turn injection is unsustainable. The system needs selective injection: only inject directives relevant to the current turn's topic, not all directives on every turn. TB-03's condition (C-06: "directive exists for the action about to be taken") already specifies relevance filtering, but the filter itself must be cheap (keyword match against the prompt, not a full retrieval).

**Recommendation:** Cap distilled directive injection at 500 tokens per turn. If total directive text exceeds this, inject only the top-K most relevant (by keyword overlap with the current prompt). Always inject all P1 (safety) directives regardless of relevance.

---

## 6. Summary of Findings

| Question | Finding |
|----------|---------|
| Triggered belief registry design | 15 concrete ECA rules (TB-01 through TB-15), 4-tier priority, forward-chaining. Covers all 3 target case studies (CS-003, CS-005, CS-020). |
| FOK check protocol | 5-step protocol: topic extraction -> FTS5 state probe -> FTS5 belief probe -> optional BFS -> epistemic assessment. 50ms hard cap. HRR fallback for vocabulary gaps. |
| Recursion depth cap | 2-level cap confirmed. SOAR, CLARION, ACT-R all converge on 1-2 levels. Level 3+ is pathological in SOAR, architecturally excluded in CLARION, impossible in ACT-R. |
| Directive enforcement | 3-TB pipeline: TB-02 (session inject), TB-03 (per-turn inject), TB-10 (output block). Builds on Exp 36 evidence. Hybrid hook+MCP enforcement. |
| Meta-cognitive overhead | 313ms + 2,350 tokens per session. ROI is 100x+ vs. failure cost. Scaling limit: 50+ directives blow the token budget. Selective injection needed above ~10 directives. |

### Open Questions for Future Research

1. **TB-10 (output blocking) is untested.** Exp 36 tested injection, not blocking. Need Exp 36b (multi-turn drift) and a new experiment for post-generation pattern matching accuracy.
2. **FOK check latency on larger belief stores.** The 50ms budget assumes <10K beliefs. At 100K+ beliefs, FTS5 query time may exceed budget. Needs benchmarking.
3. **Selective directive injection algorithm.** When directive count exceeds the 500-token-per-turn cap, which directives to inject? Simple keyword overlap, or something smarter?
4. **FOK false negative rate.** How often does the FOK check miss relevant beliefs due to vocabulary mismatch? The HRR fallback addresses this in theory, but the false negative rate is unmeasured.
5. **Interaction effects between triggered beliefs.** When TB-01 and TB-03 and TB-10 all fire on the same turn, do they conflict? Priority ordering says no, but this needs empirical testing.

---

## Sources

- [Laird, 2022 - Introduction to the Soar Cognitive Architecture](https://arxiv.org/pdf/2205.03854) -- impasse substates, chunking, meta-cognitive depth
- [Laird & Mohan, 2022 - Analysis and Comparison of ACT-R and Soar](https://arxiv.org/abs/2201.09305) -- ACT-R's lack of recursive meta-cognition
- [Sun, 2016 - CLARION Cognitive Architecture](https://www.cambridge.org/core/journals/journal-of-experimental-theoretical-artificial-intelligence/article/abs/the-clarion-cognitive-architecture-extending-cognitive-modeling-to-social-simulation/52ACCE6EE5CC6F5E52EB28E838EFA0ED) -- architectural 1-level meta-cognitive cap
- [Schwartz, 1994 - Metamemory Judgments](https://doi.org/10.1006/jmla.1994.1024) -- FOK and JOL
- [Nelson & Narens, 1990 - Metamemory Framework](https://doi.org/10.1016/S0079-7421(08)60053-5) -- monitoring vs. control in metamemory
- [van Ditmarsch, 2015 - Introduction to Logics of Knowledge and Belief](https://arxiv.org/pdf/1503.00806) -- S4/S5/KD45 introspection axioms
- [Lindsey, 2025 - Emergent Introspective Awareness in LLMs](https://transformer-circuits.pub/2025/introspection/index.html) -- unreliable LLM self-knowledge
- Exp 36 (this project) -- hook injection enforcement, N=30, p=0.0043
- Exp 40 (this project) -- hybrid FTS5+HRR pipeline, vocabulary gap rescue
- Exp 1 (this project) -- correction detection V2, 92% accuracy
