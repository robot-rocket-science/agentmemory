# Agentic Memory: Project Plan

**Date:** 2026-04-09
**Approach:** Hybrid -- proven components from GSD prototype + best ideas from landscape
**Goal:** Build a memory system that genuinely improves agent performance on real tasks, not one optimized to score well on benchmarks.

---

## The Problems We're Solving

1. **Context drift.** Over long sessions, important decisions and context fall off the window. By session 5 of a project, the agent has forgotten what it decided in session 1.
2. **Token waste.** Dumping 54K tokens of KNOWLEDGE.md into every prompt burns budget and dilutes signal. The agent needs the right context, not more context.
3. **Response quality.** The agent makes better decisions when it has relevant prior context. A memory system that delivers focused, task-relevant context should produce measurably better outputs.
4. **Cross-session continuity.** Knowledge from session N must be available in session N+1 without manual effort. The user should not have to re-explain project context every session.
5. **Session recovery.** When a machine crashes, CLI dies, or a session is interrupted unexpectedly, the memory system must be able to reconstruct full or near-full session context. No work should be lost because of an infrastructure failure.

These are the actual problems. Benchmarks are a sanity check on whether we're solving them, not the goal itself.

---

## Design Principles

1. **Solve real problems first, benchmark second.** If we solve context drift, token waste, and session recovery, and still score below grep on LoCoMo, we investigate why -- maybe our approach is wrong, maybe the benchmark is. Either way, we report honestly.
2. **Zero-LLM by default, LLM-enriched optionally.** The 100x cost gap matters. Ship a system that works offline, with optional LLM enrichment for users who want it.
3. **Cross-model from day one.** MCP server interface. Claude, ChatGPT, Gemini, local models.
4. **Crash-safe by design.** Every write is durable before acknowledgment. WAL mode SQLite. Session state is continuously checkpointed, not saved only at clean exit. Recovery is a first-class operation, not an afterthought.
5. **Honest reporting.** Every benchmark result includes cost, latency, naive baselines, reproduction code, and documented limitations. Standard benchmarks are sanity checks, not targets.
6. **Scientific method.** Hypothesize, test, measure, report. If the evidence says our approach is worse, we say so and change course.

---

## Architecture: The Scientific Memory Model

Most agentic memory systems model human memory: episodic, semantic, procedural stores with forgetting curves and consolidation. Human memory is a bad model. Humans forget critical details, confabulate to fill gaps, and can't distinguish between what they experienced and what they reconstructed after the fact. The academic literature is building systems that replicate those failure modes.

We model the scientific method instead.

### Core Abstraction

| Scientific Method | Memory Primitive | What It Stores | Properties |
|---|---|---|---|
| **Observation** | `observation` | Raw data: conversation turns, file changes, errors, decisions as they happened | Immutable, append-only, timestamped. Never modified or deleted. The ground truth. |
| **Hypothesis** | `belief` | Derived claims: "user prefers X", "these facts are related", "this approach works for Y" | Mutable confidence. Explicit evidence chain (which observations support this). Can be superseded. |
| **Experiment** | `test` | Retrieval feedback: was this belief useful when retrieved? Did the agent act on it? Did the output improve? | Links a belief to an outcome. The feedback loop. |
| **Revision** | `revision` | Belief updates: confidence adjustments, supersessions, contradictions resolved | Links old belief to new belief with reason. Full provenance chain. |

### Why This Is Better Than Human Memory Categories

| Human Memory Model | Problem | Scientific Model Equivalent |
|---|---|---|
| Episodic memory (events) | Subject to reconsolidation -- each recall modifies the memory | Observations are immutable. You can derive different beliefs from them, but the raw data never changes. |
| Semantic memory (facts) | No confidence, no evidence chain, no expiration | Beliefs carry explicit confidence, evidence pointers, and temporal validity. |
| Procedural memory (how-to) | Implicit, hard to inspect or correct | Beliefs about procedures are explicit and testable like any other belief. |
| Forgetting | Lossy, unpredictable, loses important things | Nothing is forgotten. Beliefs are downgraded based on evidence, not time. Low-confidence beliefs sort to the bottom but remain queryable. |
| Consolidation (sleep) | Black box, no audit trail | Revision is explicit: old belief -> new belief with reason and evidence delta. |

### Key Design Consequence: The Feedback Loop

The critical piece nobody has built well: **testing whether retrieved memories actually helped.**

Most memory systems are write-then-retrieve with no feedback. They have no mechanism to ask "was that retrieval useful?" This is why multi-hop conflict resolution tops out at 7% -- systems retrieve contradictory beliefs and have no way to evaluate which has stronger evidence.

Our feedback loop:

```
[1. Retrieve beliefs for task]
     |
     v
[2. Agent uses (or ignores) retrieved context]
     |
     v
[3. Observe outcome: did the agent cite the belief? Did the output succeed?]
     |
     v
[4. Score the retrieval: useful / not useful / harmful]
     |
     v
[5. Update belief confidence: reinforce if useful, downgrade if harmful]
     |
     v
[6. Future retrievals rank this belief differently]
```

This is not reinforcement learning (we're not training a model). It's simple bookkeeping: track which beliefs get used, which get ignored, and which lead to bad outcomes. Adjust confidence accordingly. A belief that's been retrieved 10 times and used 0 times is probably not useful for that type of task, regardless of how semantically similar it is to the query.

### What We Carry Forward From Prior Work

**From the GSD prototype (proven mechanisms):**
- Citation-backbone graph in SQLite -- zero-LLM edge extraction via regex
- In-memory adjacency list with BFS, hub damping, anchor nodes
- Cluster diversity filtering
- Content-hash dedup

**From the landscape (evidence-based additions):**

| Feature | Source | Why |
|---------|--------|-----|
| **Temporal validity** | Zep/Graphiti (arXiv:2501.13956) | Beliefs change. "Alice works at X" needs valid_from/valid_to. |
| **Progressive context loading** | MemPalace L0-L3 (refined) | Token budget management with hard caps. |
| **MCP server** | MemPalace, Supermemory | Cross-model support is table stakes. |
| **Write gating** | MINJA attack paper (arXiv:2503.03704) | Memory poisoning is a real attack surface. |
| **Hybrid retrieval** | LightRAG, HippoRAG | FTS5 + graph traversal + optional vector. Single-channel retrieval leaves performance on the table. |

### What We Explicitly Do NOT Include

| Excluded | Why |
|----------|-----|
| Human memory categories (episodic/semantic/procedural) | We use observation/belief/test/revision instead. More rigorous, more inspectable. |
| Embedding-only retrieval | Not sufficient for multi-hop (lhl analysis) |
| Community clustering (Leiden) | $33K at scale, gains shrink when evaluation bias corrected |
| LLM-required write path | Zero-LLM by default. Optional enrichment layer. |
| Probabilistic forgetting / entropy decay | Nothing is forgotten. Beliefs are downgraded based on evidence, not randomness. |
| Spatial metaphor | Marketing, not architecture |

---

## Session Recovery

Session recovery is not a feature bolted on at the end. It's a core architectural constraint that shapes every other design decision.

### The Problem

A CLI crash, machine reboot, network drop, or OOM kill can happen at any point. The user loses their conversation context. Without recovery, they restart with a blank slate and have to manually reconstruct where they were, what decisions were made, what was tried, what failed.

### Design

**Continuous checkpointing, not save-on-exit.**

Every meaningful event is durably written to SQLite (WAL mode) as it happens, not batched for a clean shutdown that may never come.

```
Session lifecycle:
  [session_start]  --> create session record with timestamp, model, project context
       |
  [each turn]      --> checkpoint: write conversation summary, decisions made,
       |               files touched, task state, active context
       |               (writes happen DURING the turn, not after)
       |
  [clean exit]     --> mark session complete, run consolidation
       |
  [crash/kill]     --> session record exists but is not marked complete
                       next session detects incomplete predecessor
                       recovery path activates
```

### Recovery Path

On session start, check for incomplete sessions:

1. **Detect:** `SELECT * FROM sessions WHERE completed_at IS NULL ORDER BY started_at DESC`
2. **Reconstruct:** Load the last session's checkpoints + any observations/beliefs created during that session. Rebuild: what was being worked on, what decisions were made, what beliefs were formed, what failed.
3. **Present:** Inject recovered context into the new session's L0/L1 layers. The agent knows what it was doing, what it decided, and what state things were in.
4. **Resume or pivot:** User decides whether to continue the interrupted work or start fresh. The memory system provides the context for that decision; it doesn't make it.

### What Gets Checkpointed

| Event | What's Saved | Why |
|-------|-------------|-----|
| Decision made | Decision content, rationale, references | Core intellectual output -- must survive crash |
| File modified | Path, operation type, brief description | Agent needs to know what it changed |
| Task state change | Task ID, old state, new state | Resume requires knowing where work stopped |
| Context window significant content | Summarized key points from conversation | The actual conversation is gone after crash; summaries preserve intent |
| Error/failure | What was attempted, what went wrong | Prevents re-attempting failed approaches |

### Durability Guarantees

- SQLite WAL mode: writes survive process crash (not disk failure)
- Checkpoints write synchronously before the agent continues (no async fire-and-forget)
- Session records are append-only (no updates to checkpoint rows after creation)
- Recovery reads are idempotent (running recovery twice produces the same context)

### What Recovery Cannot Do

- **Reconstruct the exact conversation** -- the full turn-by-turn dialogue is owned by the CLI/platform, not the memory system. We save summaries and decisions, not transcripts.
- **Resume mid-tool-call** -- if the crash happened during a file write or git operation, the memory system knows the intent but not the partial state. The agent has to assess and decide.
- **Guarantee zero loss** -- if the crash happens between checkpoint writes, the last uncheckpointed turn is lost. The design minimizes this window but can't eliminate it.

---

## Storage Schema

SQLite with FTS5 for text search. WAL mode for crash safety. No external dependencies for core operation.

The schema maps directly to the scientific method primitives. Every table corresponds to a concept, not an implementation convenience.

### Tables

```sql
-- OBSERVATIONS: immutable raw data. The ground truth. Never modified or deleted.
CREATE TABLE observations (
    id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,        -- SHA-256 for dedup
    content TEXT NOT NULL,
    observation_type TEXT NOT NULL,    -- conversation, file_change, error,
                                       -- decision, user_statement, document
    source_type TEXT NOT NULL,         -- user, agent, system, document
    source_id TEXT,                    -- who/what produced this
    session_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

-- BELIEFS: derived claims with Bayesian confidence and evidence chains.
-- Confidence modeled as Beta distribution: Beta(alpha, beta_param).
-- Updated via test outcomes and new evidence. Always traceable to observations.
CREATE TABLE beliefs (
    id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    content TEXT NOT NULL,             -- the claim itself
    belief_type TEXT NOT NULL,         -- factual, preference, relational,
                                       -- procedural, causal
    alpha REAL NOT NULL DEFAULT 0.5,    -- Beta distribution: success count (Jeffreys prior)
    beta_param REAL NOT NULL DEFAULT 0.5, -- Beta distribution: failure count (Jeffreys prior)
    confidence REAL GENERATED ALWAYS AS (alpha / (alpha + beta_param)) STORED,
    source_type TEXT NOT NULL,         -- user_stated, user_corrected, document_recent,
                                       -- document_old, agent_inferred, cross_reference
    valid_from TEXT,                   -- ISO 8601, when this belief became valid
    valid_to TEXT,                     -- ISO 8601, NULL = still current
    superseded_by TEXT,                -- points to replacement belief if revised
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (superseded_by) REFERENCES beliefs(id)
);

-- EVIDENCE: links beliefs to the observations that support them.
-- A belief with no evidence is an unsupported claim.
CREATE TABLE evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    belief_id TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    source_weight REAL DEFAULT 1.0,   -- credibility of the source (user=1.0, agent=0.5, etc.)
    relationship TEXT NOT NULL,        -- supports, weakens, contradicts
    relationship_strength REAL DEFAULT 1.0, -- how directly this relates (1.0=direct, 0.5=indirect)
    created_at TEXT NOT NULL,
    FOREIGN KEY (belief_id) REFERENCES beliefs(id),
    FOREIGN KEY (observation_id) REFERENCES observations(id)
);

-- TESTS: feedback on whether retrieved beliefs were useful.
-- The feedback loop that no other memory system has.
CREATE TABLE tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    belief_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    retrieval_context TEXT,            -- what task/query triggered this retrieval
    outcome TEXT NOT NULL,             -- used, ignored, contradicted, harmful
    outcome_detail TEXT,               -- why (e.g., "agent cited this in output"
                                       -- or "agent produced wrong answer using this")
    detection_layer TEXT NOT NULL,     -- explicit, implicit, checkpoint, fn_scan
    evidence_weight REAL NOT NULL DEFAULT 1.0, -- 1.0 for explicit, 0.3 for implicit
    created_at TEXT NOT NULL,
    FOREIGN KEY (belief_id) REFERENCES beliefs(id),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

-- REVISIONS: explicit belief updates with provenance.
-- Old belief -> new belief, with reason and evidence delta.
CREATE TABLE revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    old_belief_id TEXT NOT NULL,
    new_belief_id TEXT,                -- NULL if belief was simply invalidated
    reason TEXT NOT NULL,
    evidence_delta TEXT,               -- JSON: what new evidence triggered this revision
    created_at TEXT NOT NULL,
    FOREIGN KEY (old_belief_id) REFERENCES beliefs(id),
    FOREIGN KEY (new_belief_id) REFERENCES beliefs(id)
);

-- EDGES: structural relationships between beliefs (graph backbone).
-- Preserved from GSD prototype. Enables BFS traversal, hub damping, anchors.
CREATE TABLE edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,           -- CITES, RELATES_TO, SOURCED_FROM, SUPERSEDES,
                                       -- CONTRADICTS, SUPPORTS, TEMPORAL_NEXT
    weight REAL DEFAULT 1.0,
    reason TEXT,
    created_at TEXT NOT NULL,
    last_traversed TEXT,
    traversal_count INTEGER DEFAULT 0,
    FOREIGN KEY (from_id) REFERENCES beliefs(id),
    FOREIGN KEY (to_id) REFERENCES beliefs(id)
);

-- FTS5 index for text search seeding (indexes both observations and beliefs)
CREATE VIRTUAL TABLE search_index USING fts5(
    id, content, type, tokenize='porter'
);

-- SESSION TRACKING (crash recovery)
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,                 -- NULL = incomplete (crashed or in progress)
    model TEXT,
    project_context TEXT,
    summary TEXT
);

-- SESSION CHECKPOINTS (continuous, append-only)
CREATE TABLE checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    checkpoint_type TEXT NOT NULL,     -- decision, file_change, task_state,
                                       -- context_summary, error, goal
    content TEXT NOT NULL,
    references TEXT,                   -- JSON array of related belief/observation IDs
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

-- AUDIT LOG (every mutation to beliefs/edges/evidence is logged)
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation TEXT NOT NULL,           -- CREATE, UPDATE, SUPERSEDE, INVALIDATE, PRUNE
    target_table TEXT NOT NULL,
    target_id TEXT NOT NULL,
    agent_id TEXT,
    reason TEXT,
    created_at TEXT NOT NULL
);
```

### Schema Invariants

These are enforced at the application level, not just by SQL constraints:

1. **Observations are never modified or deleted.** INSERT only. The ground truth is immutable.
2. **Every belief has at least one evidence link.** A belief without evidence is rejected by the write gate.
3. **Superseded beliefs are never deleted.** They remain queryable for provenance. `valid_to` is set, `superseded_by` points to the replacement.
4. **Every revision has a reason.** No silent updates. The audit trail is complete.
5. **Tests are append-only.** Feedback on retrieval quality is never retroactively modified.
6. **Checkpoints are append-only and synchronous.** Written before the agent continues, not batched for clean exit.

---

## Memory Lifecycle

### Observe (Write Path)

```
Input (conversation turn, file change, error, user statement, document)
  |
  v
[1. Record Observation]   -- immutable INSERT into observations table
  |                        -- content-hash dedup: skip if identical observation exists
  |                        -- checkpoint written synchronously (crash safety)
  v
[2. Extract Beliefs]      -- zero-LLM pipeline (see below)
  |                        -- optional LLM: entity/relationship extraction
  v
[3. Write Gate]           -- does this belief have evidence? (must link to >= 1 observation)
  |                        -- source credibility scoring: user > document > agent-inferred
  |                        -- content-hash dedup: if belief already exists, add new
  |                          evidence link and update confidence instead of creating duplicate
  v
[4. Create Belief]        -- INSERT with source-informed Beta prior
  |                        -- CREATE evidence link to source observation(s)
  |                        -- CREATE edges to related beliefs (extraction pipeline)
  v
[5. Conflict Check]       -- does this belief contradict an existing belief?
  |                        -- if yes: CREATE CONTRADICTS edge between them
  |                        -- do NOT auto-resolve. Flag for the test/revision cycle.
  v
[6. Audit Log]            -- every mutation logged
```

### Zero-LLM Belief Extraction Pipeline

The GSD prototype extracted edges via D###/M### regex patterns. General conversation
doesn't have explicit citation syntax. This pipeline extracts beliefs and edges
from arbitrary text without calling an LLM.

**Stage 1: Observation Classification**

Rule-based classification into observation types via keyword/pattern scoring:

```
Patterns:
  decision_words  = [decided, chose, will use, going with, settled on, picked, switched to]
  preference_words = [prefer, like, want, always, never, hate, love, don't like]
  fact_words      = [is, are, was, has, works at, lives in, uses, runs on, built with]
  error_words     = [error, failed, crash, bug, broken, doesn't work, exception, traceback]
  procedure_words = [to do X, first, then, step, run, execute, install, configure, deploy]

  Score each category. Highest score wins. Confidence = max_score / total_score.
  Observations below 0.3 confidence get classified as "unstructured" and stored
  but don't generate beliefs automatically.
```

**Stage 2: Claim Extraction**

Extract concrete claims from classified observations:

```
For decision observations:
  Pattern: "[subject] decided/chose/will use [object] [because reason]"
  Belief: "[subject] chose [object]"
  Belief type: factual
  Edge: if [reason] mentions an existing belief -> SOURCED_FROM edge

For preference observations:
  Pattern: "[subject] prefers/likes/wants [object]"
  Belief: "[subject] prefers [object]"
  Belief type: preference

For fact observations:
  Pattern: "[subject] is/uses/runs on [object]"
  Belief: "[subject] [relation] [object]"
  Belief type: factual

For error observations:
  Pattern: "[action] failed/errored because [reason]"
  Belief: "[action] fails when [condition]" (procedural, negative)
  Belief type: procedural

For procedure observations:
  Pattern: "to [goal], [step1] then [step2]"
  Belief: "[goal] requires [steps]"
  Belief type: procedural
```

This is lossy. It won't catch subtle implications, sarcasm, or complex multi-sentence
reasoning. That's what the optional LLM enrichment layer is for. The zero-LLM pipeline
catches the 60-70% of beliefs that have explicit surface-level patterns.

**Stage 3: Edge Extraction**

Create edges between beliefs without LLM:

```
Methods (ordered by signal strength):

1. Explicit reference: belief text contains identifier of another belief
   (file paths, function names, variable names, URLs, ticket IDs)
   -> CITES edge

2. Entity co-occurrence: two beliefs mention the same named entity
   (proper nouns, technical terms extracted via capitalization + frequency)
   -> RELATES_TO edge

3. Temporal adjacency: beliefs extracted from observations within same
   session, within N turns of each other
   -> TEMPORAL_NEXT edge (weak, low weight)

4. Negation detection: belief B contains negation of belief A's content
   (A: "uses PostgreSQL", B: "not using PostgreSQL anymore")
   -> CONTRADICTS edge

5. FTS5 similarity: belief B's content has high BM25 score against belief A
   -> RELATES_TO edge (only if score exceeds threshold, to avoid noise)
```

**What zero-LLM extraction will miss:**
- Implicit relationships ("we should do X" implies dissatisfaction with current approach)
- Causal chains ("because of X, Y happened" where X and Y are in different observations)
- Summarization (10 observations about the same topic -> 1 consolidated belief)
- Entity resolution ("React", "the frontend framework", "the UI library" -> same thing)

These gaps are documented, measured in Phase 2, and addressable by the optional
LLM enrichment layer in Phase 5. The honest question: is 60-70% extraction good
enough to beat the filesystem baseline? Phase 2 answers this.

### Hypothesize (Belief Formation)

Beliefs carry explicit uncertainty modeled as Beta distributions. The prior encodes both initial confidence and how much evidence is needed to change our mind.

```
All beliefs start with Jeffreys prior Beta(0.5, 0.5):

  - Confidence: 0.50 (maximum uncertainty)
  - Entropy: highest of any Beta distribution
  - Moves fast in either direction with minimal evidence
  - Produces natural exploration via Thompson sampling

  Why NOT source-informed priors:
  Exp 2 showed source-informed priors (Beta(9,1) for user-stated) are
  counterproductive. Strong priors resist correction from evidence.
  Source-informed priors produced ECE=0.184 vs uniform's 0.042.
  
  Exp 5b showed Jeffreys Beta(0.5,0.5) outperforms uniform Beta(1,1):
  ECE=0.066 vs 0.097, exploration=0.194 vs 0.127. The wider initial
  distribution produces more diverse Thompson samples, improving both
  calibration AND exploration simultaneously.

  Source credibility is encoded in evidence weights instead:
  User-stated observations have source_weight=1.0, agent-inferred have 0.5.
  This affects how much each observation moves the Beta parameters, not
  where the parameters start.
```

The confidence column is derived: `confidence = alpha / (alpha + beta_param)`. But the real value is in the full distribution -- it tells us not just "how confident" but "how certain we are about that confidence." Beta(50,50) and Beta(1,1) both have confidence 0.5, but the first means "we're sure it's a coin flip" and the second means "we have no idea."

**Retrieval ranking:** Thompson sampling -- draw sample ~ Beta(alpha, beta_param) for each belief, rank by relevance * sample. No exploration_weight parameter to tune. Bayesian-optimal exploration is automatic from posterior variance. Validated in Exp 5b.

**Sources:** Beta-Bernoulli conjugate pair. MACLA (arXiv:2512.18950) validates Beta posteriors for LLM procedural memory. Thompson (1933) and Russo et al. (2018) provide theoretical guarantees. See BAYESIAN_RESEARCH.md for full analysis.

### Test (Feedback Loop)

This is the mechanism nobody else has built well. The hard part is not recording
outcomes -- it's detecting them. The MCP server controls retrieval but doesn't
directly observe what the agent does with the beliefs it receives.

### Detection Strategies (layered, not exclusive)

**Layer 1: Explicit feedback (highest signal, requires agent cooperation)**

The MCP server exposes a `test_result` tool. The agent is instructed (via the
wake-up protocol and system prompt) to call it after acting on retrieved context:

```
Agent retrieves beliefs -> does work -> calls test_result(belief_id, outcome, detail)
```

This is the cleanest signal but depends on the agent actually calling the tool.
We enforce it by:
- Including a "report back" instruction in every L2/L3 retrieval response
- Tracking retrieval-without-feedback as a system health metric
- If feedback rate drops below 50%, the instruction wording needs revision

**Layer 2: Implicit detection via next observation (automatic, lower confidence)**

After beliefs are retrieved, the system observes subsequent events in the session
(new observations from conversation turns, file changes, errors):

```
[Beliefs retrieved for task]
     |
     v
[Monitor next N observations in this session]
     |
     +-- Observation contains same entities/keywords as belief  -> infer USED
     +-- Error observation in same task domain as belief         -> infer HARMFUL (candidate)
     +-- Session ends with no relevant observations             -> infer IGNORED
     +-- Agent explicitly contradicts belief content             -> infer CONTRADICTED
```

Implicit detection records with lower evidence weight (source_weight = 0.3 vs 1.0
for explicit feedback). It's a noisy signal but captures something even when the
agent doesn't call test_result.

**Layer 3: Checkpoint comparison (retrospective, batch)**

On session end or during maintenance, compare retrieval log against checkpoints:

```
For each retrieval event in this session:
  - Find checkpoints created AFTER the retrieval
  - Decision checkpoint cites same content as retrieved belief  -> USED
  - Error checkpoint on a task where belief was retrieved        -> HARMFUL (candidate)
  - Task completion checkpoint after retrieval                   -> USED (weak)
  - No relevant checkpoints after retrieval                     -> IGNORED
```

This is retrospective analysis, not real-time. It runs during the maintenance
pass and can backfill test records that weren't captured by layers 1 or 2.

**Layer 4: False negative detection (hardest, periodic)**

When a task fails (error checkpoint, user expresses frustration, agent retries),
search the full belief set for beliefs that WOULD have been relevant:

```
[Task failure detected]
     |
     v
[Search all beliefs for relevance to the failed task]
     |
     +-- Relevant belief exists but wasn't retrieved  -> FALSE NEGATIVE
     |   Record: retrieval pipeline missed this. Why?
     |   (seed terms didn't match? Below confidence threshold? Pruned by budget?)
     |
     +-- No relevant belief exists                    -> COVERAGE GAP
         Record: the system has no knowledge about this topic.
```

This is expensive (full belief scan on every failure) and should run sparingly.
But it's the only way to detect false negatives, which are invisible to the
other layers.

### Outcome Classification

```
[1. Retrieve beliefs for task context]
     |
     v
[2. Agent produces output using retrieved context]
     |
     v
[3. Detect outcome via layers 1-4]
     |
     +-- USED:         belief content appears in agent's subsequent work
     +-- IGNORED:      no evidence of use after retrieval
     +-- HARMFUL:      agent error traceable to retrieved belief
     +-- CONTRADICTED: agent or user explicitly flags belief as wrong
     |
     v
[4. Record test result]   -- INSERT into tests table
     |                      -- include detection_layer (explicit/implicit/checkpoint/fn_scan)
     |                      -- include evidence_weight (1.0 for explicit, 0.3 for implicit)
     v
[5. Update belief confidence via Bayesian update]
     |
     +-- USED:         alpha += evidence_weight (reinforced)
     +-- IGNORED:      no update (absence of evidence != evidence of absence)
     +-- HARMFUL:      beta += evidence_weight (strong negative signal)
     +-- CONTRADICTED: beta += evidence_weight, CONTRADICTS edge created, revision flagged
```

**Important:** IGNORED does not reduce confidence. A belief about database configuration is useless for a CSS task -- that doesn't make it wrong. Only HARMFUL and CONTRADICTED outcomes reduce confidence. This prevents useful-but-niche beliefs from decaying just because they weren't relevant to recent tasks.

### Retrieval Confusion Matrix

Every retrieval decision is classifiable:

```
                          Belief is actually correct
                          YES                 NO
                    +-------------------+-------------------+
  Retrieved    YES  | TRUE POSITIVE     | FALSE POSITIVE    |
                    | Belief retrieved, | Belief retrieved,  |
                    | used, outcome     | used, outcome      |
                    | was good          | was bad            |
                    +-------------------+-------------------+
               NO   | FALSE NEGATIVE    | TRUE NEGATIVE     |
                    | Belief existed    | Belief not         |
                    | but wasn't        | retrieved, and     |
                    | retrieved; agent  | that was correct   |
                    | needed it         | (irrelevant)       |
                    +-------------------+-------------------+
```

**What we can measure directly:** True positives (retrieved + used + good outcome) and false positives (retrieved + used + bad outcome). These come from the test feedback loop.

**What's harder to measure:** False negatives (needed but not retrieved). These surface when the agent fails a task and a post-hoc search reveals a belief that would have helped. We can detect some of these by comparing task failures against the full belief set.

**True negatives** are the vast majority and aren't interesting -- most beliefs are irrelevant to any given task.

**System health metric:** Track the confusion matrix over time. A healthy memory system should show:
- TP rate increasing (retrieval gets more useful)
- FP rate decreasing (less noise in retrieved context)
- FN rate decreasing (fewer missed relevant beliefs)

If FP rate is increasing, the system is retrieving too aggressively. If FN rate is increasing, the system is too conservative or the belief graph has coverage gaps.

### Revise (Belief Updates)

```
[Revision triggers]
  |
  +-- New observation directly contradicts existing belief
  +-- Test outcome was HARMFUL or CONTRADICTED
  +-- User explicitly corrects a belief
  +-- Temporal validity expired (valid_to reached)
  |
  v
[1. Create revision record]  -- links old_belief to trigger, records reason
  |
  v
[2. Supersede old belief]    -- set valid_to = now, superseded_by = new_belief_id
  |                           -- old belief is NOT deleted. Remains queryable for provenance.
  v
[3. Create new belief]       -- if replacement exists: new belief with updated content
  |                           -- inherits relevant evidence links from old belief
  |                           -- plus new evidence that triggered the revision
  v
[4. Update edges]            -- SUPERSEDES edge from new to old
                              -- transfer non-contradicted edges from old to new
```

### Retrieve (Read Path)

```
Query (task context, explicit search, or session wake-up)
  |
  v
[1. Layer Selection]
  |
  +-- L0: Identity + project config (~100 tokens, always loaded)
  +-- L1: High-confidence anchors + recently reinforced beliefs (~500 tokens, always)
  +-- L2: Task-seeded graph retrieval (~1000 tokens, on task start)
  +-- L3: Deep search (on explicit query, budget negotiable)
  |
  v
[2. Hybrid Retrieval]     -- for L2/L3:
  |                        -- FTS5 text search for seed beliefs
  |                        -- BFS 2-hop from seeds with hub damping
  |                        -- optional: vector similarity re-ranking
  v
[3. Filter]               -- exclude superseded beliefs (valid_to < now)
  |                        -- exclude beliefs with confidence below threshold
  |                        -- prefer beliefs with higher evidence_count for ties
  v
[4. Rank + Pack]          -- Thompson sampling (Exp 5b validated):
  |                        --   For each belief: sample ~ Beta(alpha, beta_param)
  |                        --   score = relevance * sample
  |                        -- natural exploration from posterior variance (no tuning parameter)
  |                        -- Jeffreys prior Beta(0.5, 0.5) produces optimal explore/exploit balance
  |                        -- cluster diversity enforced (no single topic dominates)
  |                        -- pack into token budget
  v
[5. Format + Inject]      -- structured context block with:
  |                        -- belief content
  |                        -- confidence level
  |                        -- evidence summary (what observations support this)
  |                        -- provenance trail (where did this come from)
  v
[6. Record retrieval]     -- log which beliefs were retrieved for this task
                           -- this enables the Test feedback loop later
```

### Maintain

```
[Periodic maintenance -- on session end or scheduled]
  |
  +-- Recompute anchor set from graph topology
  +-- Adjust hub damping thresholds
  +-- Flag unresolved CONTRADICTS edges for attention
  +-- Collect stats: belief count, evidence density, test outcome distribution
  +-- Identify beliefs with high retrieval count but low use rate (noise candidates)
  +-- Identify beliefs with high use rate but no recent tests (stale candidates)
  |
  NOTE: No automatic deletion or decay. Maintenance identifies issues.
        Revision is the mechanism for addressing them.
```

---

## Implementation Phases

### Phase 0: Foundation + Measurement (Week 1-2)

**Goal:** Project setup, benchmark infrastructure, and baselines. Establishes what "better" means before we write memory code.

**Tasks:**
- [ ] Set up Python project with uv
- [ ] SQLite schema (observations, beliefs, evidence, tests, revisions, edges, sessions, checkpoints, audit_log, search_index)
- [ ] Implement baseline measurements for the real problems:
  - **Context drift test:** Multi-session task where session 5 requires decisions from session 1. Measure: does the agent remember? Baseline: no memory system (just context window).
  - **Token efficiency test:** Compare task quality with full context dump vs no context. Measure: tokens consumed and output quality.
  - **Session recovery test:** Simulate crash at various points, measure context recovery completeness.
- [ ] Implement standard benchmark runners (LoCoMo, LongMemEval, MemoryAgentBench) as sanity checks
- [ ] Implement filesystem baseline (Letta's grep approach)
- [ ] Implement full-context baseline
- [ ] LLM-as-judge with bias controls (position exchange, length alignment, 25+ trials)
- [ ] Document all baseline results

**Exit criteria:** We have quantified numbers for context drift, token waste, and recovery without any memory system. These are the numbers we need to beat.

**Branch:** `phase-0-foundation`

### Phase 1: Session Recovery + Checkpointing (Week 3-4)

**Goal:** Crash-safe session tracking. The most immediately useful feature ships first.

This is the feature that already proved its value with MemPalace -- you recovered 90% context after two back-to-back crashes. We build this first because it solves a real, painful problem and it forces the durability infrastructure that everything else depends on.

**Tasks:**
- [ ] Session lifecycle: start, checkpoint, complete, detect-incomplete
- [ ] Continuous checkpointing: decisions, file changes, task state, context summaries, errors
- [ ] Recovery path: detect incomplete sessions, reconstruct context, present to agent
- [ ] WAL mode SQLite, synchronous checkpoint writes
- [ ] Write audit log (every mutation logged)
- [ ] Test: simulate crashes at 10 different points in a real work session. Measure recovery completeness.

**Measurement:**
- Recovery completeness: what % of session context is recoverable after crash?
- Recovery latency: how long does it take to reconstruct context?
- Write overhead: how much does continuous checkpointing slow down normal operation?

**Exit criteria:** >90% context recovery after simulated crash. Checkpoint write overhead <50ms per turn. Recovery latency <2 seconds.

**Branch:** `phase-1-recovery`

### Phase 2: Core Memory -- Observe + Hypothesize (Week 5-6)

**Goal:** Observation recording, belief extraction, evidence linking, graph retrieval. The core scientific memory model.

**Tasks:**
- [ ] Observation recording: immutable inserts from conversation/file/error events
- [ ] Belief extraction: zero-LLM keyword/reference/classification pipeline
- [ ] Evidence linking: every belief traces to its supporting observations
- [ ] Write gate: reject beliefs without evidence, dedup, source credibility scoring
- [ ] Conflict detection: CONTRADICTS edges between incompatible beliefs
- [ ] In-memory graph store: adjacency list, BFS, hub damping, anchor computation
- [ ] FTS5 search index seeding (observations + beliefs)
- [ ] Retrieval pipeline: text search + BFS + temporal/confidence filter + budget packing
- [ ] Progressive context loading (L0-L3 with hard token budgets)
- [ ] Integration with session checkpointing from Phase 1

**Measurement (real-world tests, not just benchmarks):**
- Context drift: re-run the multi-session test from Phase 0. Does the agent now remember session 1 decisions in session 5?
- Token efficiency: compare tokens consumed and output quality vs full-dump and no-memory baselines
- Response quality: on 10 real tasks, does the agent produce better outputs with memory than without? (Human-judged, not LLM-judged)
- Standard benchmarks as sanity check: LoCoMo, LongMemEval

**Exit criteria:** Measurable improvement on context drift and token efficiency vs Phase 0 baselines. Agent produces equal or better output quality with <2,000 tokens of memory context vs >10,000 tokens of full dump.

**Branch:** `phase-2-core-graph`

### Phase 3: Test + Revise -- The Feedback Loop (Week 7-8)

**Goal:** Close the loop. Track whether retrieved beliefs are useful. Update confidence based on evidence. Revise beliefs when they're wrong.

This is the phase that differentiates us from every other memory system. Write-then-retrieve is table stakes. Test-then-revise is the actual contribution.

**Tasks:**
- [ ] Test recording: log which beliefs were retrieved and whether they were used/ignored/harmful
- [ ] Bayesian confidence updating: reinforce beliefs that get used, downgrade beliefs that cause harm (starting with Beta distribution conjugate priors -- pending research results)
- [ ] Revision pipeline: supersede beliefs when contradicted by new evidence
- [ ] Temporal validity: valid_from/valid_to, automatic expiration
- [ ] Conflict resolution: when CONTRADICTS edges exist, surface both beliefs with their evidence chains and let the agent (or user) decide
- [ ] Maintenance: recompute anchors, flag stale beliefs, identify noise candidates

**Measurement:**
- Does the system correctly reflect updated facts after revision? (Temporal accuracy)
- Does it surface contradictions instead of silently using stale data?
- Does belief confidence correlate with actual usefulness? (Calibration test)
- Over 10 sessions, does retrieval quality improve as the feedback loop accumulates data?
- Re-run all Phase 2 measurements. Did the feedback loop help or hurt?

**Exit criteria:** Beliefs that get used have measurably higher confidence than beliefs that get ignored. Revised beliefs produce better outcomes than their predecessors. No regression on prior metrics.

**Branch:** `phase-3-feedback-loop`

### Phase 4: MCP Server + Cross-Model (Week 9-10)

**Goal:** Ship as MCP server. Works with Claude, ChatGPT, Gemini, local models.

**Tasks:**
- [ ] MCP server (JSON-RPC 2.0, stdin/stdout)
- [ ] Tools: search, add, update, invalidate, recover_session, timeline, status, stats
- [ ] Progressive loading protocol (L0-L3 via MCP)
- [ ] Write gate enforced at MCP boundary
- [ ] Test with Claude Code, ChatGPT, at least one local model
- [ ] Session recovery works across model switches (crash in Claude session, recover in ChatGPT)

**Measurement:**
- Same real-world tests, run with each model backend
- Per-model results (different models may use memory differently)
- Cross-model recovery: context from Claude session available in ChatGPT session

**Exit criteria:** Working MCP server tested with at least 2 LLM backends. Session recovery works cross-model.

**Branch:** `phase-4-mcp`

### Phase 5: LLM Enrichment + Validation (Week 11-12)

**Goal:** Optional LLM enrichment layer. Rigorous validation of everything.

**Tasks:**
- [ ] LLM-enriched belief extraction (opt-in): entity/relationship extraction, semantic edge creation
- [ ] Orphan backfill: connect early beliefs that lack evidence links
- [ ] A/B: zero-LLM vs LLM-enriched across all measurements
- [ ] Human-labeled ground truth for retrieval quality (minimum 100 queries)
- [ ] Ablation studies: contribution of each component (graph traversal, feedback loop, Bayesian updating, write gating)
- [ ] Confusion matrix analysis: TP/FP/FN rates over time across all configurations
- [ ] Failure mode analysis: what doesn't work and why
- [ ] Cost-accuracy-latency tradeoff analysis
- [ ] Calibration test: does belief confidence actually predict usefulness?
- [ ] Full write-up: every claim backed by evidence, every limitation documented

**Exit criteria:** No claim without evidence. Honest cost-accuracy tradeoff documented. Confusion matrix trends documented. Calibration curve published. Public repo with full reproduction code.

**Branch:** `phase-5-validation`

---

## MCP Tool Interface

The MCP server exposes tools that map to the scientific method primitives. The agent interacts with memory through these operations, not through raw database access.

### Core Tools

| Tool | Operation | Scientific Method Stage |
|------|-----------|------------------------|
| `observe` | Record a new observation (immutable) | Observe |
| `believe` | Create a belief with evidence links | Hypothesize |
| `search` | Find relevant beliefs for a task context | Retrieve |
| `test_result` | Record whether a retrieved belief was useful | Test |
| `revise` | Supersede a belief with new evidence | Revise |
| `contradict` | Flag two beliefs as contradictory | Test |
| `evidence` | Query the evidence chain for a belief | Inspect |
| `remember` | Create a locked, always-loaded belief from a user statement | Observe + Lock |
| `correct` | User corrects a prior belief -- creates locked replacement, supersedes the original | Revise + Lock |

### `remember` and `correct` Tools (REQ-019, REQ-020)

These are the critical tools for single-correction learning.

**`remember`**: The user (or agent on the user's behalf) tells the system to permanently store something. Creates a belief with:
- source_type = user_stated
- Jeffreys prior boosted to Beta(9, 0.5) (high confidence, hard to dislodge)
- locked = true (cannot be downgraded by feedback loop)
- Automatically classified as L0 (behavioral) or L1 (domain) based on content

Example: User says "always use uv for package management" -> agent calls `remember("always use uv for package management", type="procedural")`

**`correct`**: The user tells the system it's wrong about something. Creates a new belief AND supersedes the old one:
- Finds the existing belief being contradicted
- Creates SUPERSEDES edge
- New belief: source_type = user_corrected, locked = true, L0/L1 loaded
- Old belief: valid_to = now, superseded_by = new belief

Example: User says "no, capital is 5K not 100K" -> agent calls `correct(old_belief="capital is 100K", new_belief="capital is 5K USD, non-negotiable")`

The user should never have to call these tools directly. The agent should recognize when the user is stating something to remember or correcting a mistake, and call the appropriate tool. But the tools are also available for explicit use.

### Session Tools

| Tool | Operation |
|------|-----------|
| `session_start` | Begin a new session, check for incomplete predecessors |
| `session_recover` | Reconstruct context from an interrupted session |
| `checkpoint` | Write a session checkpoint (called continuously, not just at exit) |
| `session_end` | Mark session complete, trigger maintenance |

### Query Tools

| Tool | Operation |
|------|-----------|
| `status` | Palace overview: belief count, evidence density, health metrics, confusion matrix |
| `timeline` | Temporal view of beliefs about an entity (including superseded) |
| `provenance` | Full evidence chain: belief <- evidence <- observations |
| `health` | System diagnostics: orphan beliefs, unresolved contradictions, stale candidates |

### Wake-Up Protocol

On session start, the MCP server automatically:
1. Checks for incomplete sessions and offers recovery
2. Loads L0 (identity + project config + ALL locked directives) and L1 (high-confidence anchors)
3. Injects a status summary: belief count, last session summary, unresolved contradictions
4. The agent gets working context without having to ask for it

### Automatic Query-Seeded Directive Injection (REQ-027)

**HARD GUARANTEE: Every prompt the LLM processes will have relevant directives attached.**

The memory system intercepts every query/prompt and injects relevant context BEFORE the LLM sees it:

```
User prompt arrives
  |
  v
[1. Extract query terms]      -- zero-LLM keyword extraction from prompt
  |
  v
[2. Retrieve relevant directives] -- FTS5 + related_concepts tags
  |                                -- ALL locked directives checked
  |                                -- L0 directives always included
  v
[3. Assemble context]         -- L0 (always-loaded directives)
  |                            -- L2 (query-relevant beliefs)
  |                            -- token budget enforced
  v
[4. Inject before LLM]        -- [directives + context] + [user prompt]
  |                            -- the LLM never sees a bare prompt
  v
[5. LLM processes]            -- directive is IN context, guaranteed
  |
  v
[6. Monitor response]         -- check for directive violations
                               -- if violation: flag, block (if hooks available), re-inject
```

Steps 1-4 are under the memory system's control. The guarantee is that
relevant directives are ALWAYS in context. The LLM's compliance (step 5)
is a soft constraint addressed by enforcement hooks and violation detection.

This eliminates the alpha-seek failure mode: the dispatch runbook fell off
the context window, so the LLM didn't know to follow it. With this system,
the runbook is re-injected every time the user mentions dispatch/deploy/GCP.

### Design Constraints

- Every `believe` call must include at least one `observation_id` as evidence. No unsupported beliefs.
- Every `revise` call must include a reason. No silent updates.
- `search` results include confidence levels and evidence summaries so the agent can judge quality.
- `test_result` is the only way to update belief confidence after creation. No direct confidence manipulation.
- All tools are idempotent where possible (duplicate `observe` calls with same content-hash are no-ops).
- **Every MCP response includes relevant locked directives.** Not just `search` results -- every tool response carries directives relevant to the current context. The LLM cannot interact with the memory system without receiving its directives.

---

## Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python | Widest LLM ecosystem, uv for env management, most benchmark code is Python |
| Storage | SQLite + FTS5 | Zero dependencies, proven at prototype scale, FTS5 for text search |
| Graph | In-memory adjacency list (loaded from SQLite) | Sub-ms BFS proven in prototype. NetworkX as fallback for analysis. |
| Vector (optional) | ChromaDB or sqlite-vec | Only for optional LLM-enriched mode. Not in default path. |
| MCP | JSON-RPC 2.0, stdin/stdout | Standard protocol, works with Claude Code, extensible |
| Benchmarks | LoCoMo, LongMemEval, MemoryAgentBench | Covers recall, 5-dimension evaluation, conflict resolution |
| Testing | pytest | Standard |
| Package management | uv | Per user preference |

---

## Success Criteria

### Must Have (Ship Blockers)

These measure whether we solved the actual problems:

- [ ] **Context drift:** Agent correctly uses decisions from session 1 in session 5+ (measurable improvement over no-memory baseline)
- [ ] **Token efficiency:** Agent produces equal or better output quality with <2,000 tokens of memory context vs >10,000 tokens of full context dump
- [ ] **Session recovery:** >90% context recoverable after unexpected crash
- [ ] **Cross-model:** Works with Claude and at least one other LLM via MCP
- [ ] **Zero-LLM default:** No API keys required for core memory operation
- [ ] **Crash-safe:** WAL mode, synchronous checkpoints, no data loss on process kill
- [ ] **Honest claims:** No claim without reproduction code. All limitations documented.
- [ ] p95 retrieval latency < 500ms
- [ ] Checkpoint write overhead < 50ms per turn

### Should Have

- [ ] Standard benchmarks at or above filesystem baseline (74% LoCoMo) as sanity check
- [ ] Measurable improvement on temporal/update dimensions (LongMemEval)
- [ ] Cross-model session recovery (crash in Claude, recover in ChatGPT)
- [ ] Cost-accuracy tradeoff documented across zero-LLM and LLM-enriched modes
- [ ] Human-labeled retrieval quality validation (100+ queries)

### Nice to Have

- [ ] Competitive with Zep/Letta on standard benchmarks (>85% LoCoMo)
- [ ] Any improvement on 7% multi-hop conflict resolution
- [ ] Novel contribution to principled forgetting
- [ ] Adoption by other projects

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Can't beat filesystem baseline | Project credibility | Phase 0 baselines tell us early. If grep wins, we pivot to understanding why before building more. |
| Benchmark infrastructure doesn't reproduce published results | Can't make valid comparisons | Budget week 1-2 entirely for this. If we can't reproduce, we document the discrepancy and use our own consistent measurements. |
| Zero-LLM extraction too limited for standard benchmarks | Core design assumption wrong | Phase 1 exit criteria forces this confrontation. If zero-LLM can't compete, we honestly report the cost-accuracy frontier. |
| SQLite doesn't scale beyond prototype | Operational limit | Benchmark at increasing scale. Document the ceiling. SQLite handles millions of rows; memory graph size is the real constraint. |
| LLM-as-judge bias corrupts our results | Invalid claims | Bias controls from day 1 (position exchange, length alignment, multi-trial). Report raw judge scores and corrected scores. |
| Scope creep into features before validation | Ship vaporware | Phase gates with exit criteria. No phase starts until previous exit criteria are met. |
| Checkpoint overhead slows normal operation | User experience degrades | Synchronous writes must be <50ms. If SQLite WAL can't hit this, investigate async with fsync or batched checkpoints. |
| Recovery context is too sparse to be useful | Feature doesn't solve the problem | Test early (Phase 1) with simulated crashes. If <90% recovery, the checkpoint granularity is wrong -- capture more. |
| Real-world tasks don't correlate with benchmark scores | Benchmarks are misleading | This is why real-world measurements come first. Benchmarks are sanity checks, not targets. If they diverge, trust the real-world results and investigate why benchmarks disagree. |

---

## Open Questions

These are unresolved design questions that need empirical answers, not more theorizing.

### Architecture

1. **Does the feedback loop actually improve retrieval over time?** This is our core hypothesis. If beliefs that score high after Bayesian updating aren't actually more useful than beliefs ranked by simple recency, the extra machinery isn't worth it. Phase 3 must answer this.

2. **How do we detect false negatives?** We can measure true positives (retrieved, used, good outcome) and false positives (retrieved, used, bad outcome). But false negatives (needed but not retrieved) only surface when a task fails and post-hoc analysis reveals a belief that would have helped. Can we automate this detection?

3. **What's the right granularity for observations?** Too fine-grained (every token) and we drown in noise. Too coarse (session summaries only) and we lose detail that matters for recovery. The checkpointing granularity in Phase 1 will give us initial data.

4. **Does zero-LLM extraction produce enough signal for the graph?** Citation parsing works when content has explicit references (D###/M###). General conversation doesn't have these. Keyword co-occurrence and content classification may not produce enough edges for useful BFS traversal. Phase 2 confronts this directly.

5. **Is BFS the right traversal for the scientific model?** BFS from seed nodes works well for citation graphs. But the scientific model adds evidence links, test results, and revision chains. The graph topology is different. We may need different traversal strategies for different query types.

### Confidence Model

6. **What priors for different belief types?** User-stated facts vs agent-inferred vs document-extracted. Starting points in the plan (0.9/0.5/0.7) are guesses. Need empirical calibration.

7. **How to handle non-stationarity?** A belief can be correct for months and then become wrong. Pure Bayesian updating with accumulated evidence makes it hard to revise high-confidence beliefs even when new evidence contradicts them. May need a recency-weighted likelihood or explicit temporal discounting.

8. **IGNORED outcomes:** Does "agent didn't use this belief" carry any signal? Current design says no (absence of evidence is not evidence of absence). But persistent non-use across many relevant-seeming tasks might be signal. Need data.

### Token Efficiency

9. **Is compression the right approach to token reduction?** MemPalace's AAAK compresses content but loses 12.4pp of retrieval quality. An alternative: don't compress, just retrieve less and retrieve better. If the top 5 beliefs at 500 tokens beat the top 50 compressed beliefs at 500 tokens, compression is solving the wrong problem.

10. **What's the optimal L1/L2/L3 token budget split?** The current design allocates ~100/~500/~1000. These are guesses. Need to measure: at what point does adding more retrieved context start hurting rather than helping?

### Scale

11. **At what graph size does in-memory adjacency list become a problem?** The GSD prototype ran at 577 nodes. What about 10K? 100K? 1M? SQLite can handle the storage, but can we hold the full adjacency list in memory?

12. **Does evidence density scale linearly?** Every belief links to observations. Every test links to beliefs and sessions. The evidence table could grow much faster than the belief table. What's the practical limit?

---

## What This Plan Does NOT Cover

- **Multi-agent memory consistency** -- identified as "most pressing open challenge" in literature. Out of scope for v1 but documented as future work.
- **Fine-tuning or RL-based memory optimization** -- Memory-R1 and AgeMem show promise but require training infrastructure we don't have.
- **Internal/latent memory** -- Titans and M+ operate at the model level, not the application level. Different problem space.
- **Production deployment infrastructure** -- hosting, scaling, monitoring. This plan covers the memory system itself and its validation.
