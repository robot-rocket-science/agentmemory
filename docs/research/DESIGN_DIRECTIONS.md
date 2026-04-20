# Design Directions: Emerging Architecture

**Date:** 2026-04-09
**Status:** Active research -- these are directions to explore, not decisions made

---

## Core Insight: Granular Node Decomposition

Every complete statement in a document should be its own node. Not paragraphs, not documents -- individual assertions.

"DECISIONS.md has 173 decisions" is wrong framing. DECISIONS.md has 173 decisions, each of which may contain multiple assertions, rationales, and constraints. Each of THOSE should be a node. A decision like D097 (walk-forward evaluation protocol) contains:
- The protocol itself (procedure)
- Why it was adopted (rationale, links to evidence)
- When it applies (scope)
- What supersedes it (if anything)

Each is a separately addressable node that can be:
- Loaded or not loaded based on relevance
- Decayed by time and relevance independently
- Connected to different parts of the graph
- Superseded individually (the protocol stays but the scope changes)

### Why This Matters for Tokens

Current prototype loads all anchor nodes wholesale. If D097 is an anchor with 200 tokens of content, all 200 tokens go into context even if only the 30-token protocol statement is relevant. Granular decomposition means loading only the specific assertion needed.

### How to Decompose

Start with the simplest parser: **sentence splitting based on English language conventions the LLM is trained on.** Period-delimited sentences, each becomes a node. Then layer on:
- Typed classification (assertion, rationale, constraint, scope, evidence pointer)
- Edge extraction between sentences (co-reference, citation, temporal sequence)
- Anchor promotion for sentences that get referenced or corrected

This is model-agnostic -- every LLM understands sentences.

---

## Time as a First-Class Dimension

Time is not just metadata on nodes. It's a structural dimension of the graph.

Two approaches (possibly combined):

### A. Accumulation Dimension
Nodes accumulate over time. The graph grows as new observations, beliefs, and decisions are added. Time is the axis along which the graph expands. This is what git history already is -- a temporal record of what happened.

### B. Decay Dimension
Nodes decay in relevance over time. Recent assertions are more likely to be relevant than old ones. But decay must be content-aware:
- "Capital is $5K" doesn't decay (it's a current fact)
- "We're debugging the DuckDB NULL crash" does decay (it's a past activity)
- Superseded nodes decay faster (they're replaced)

The graph structure handles this naturally: superseded nodes have SUPERSEDES edges pointing to their replacements. Traversal follows the edge to the current version.

### Git History as Timeline

Git commits are temporal nodes in the graph. Each commit links to:
- Files changed (what)
- Commit message (why, often references D###/M###)
- Timestamp (when)
- Author (who)

The 259 "signal commits" (referencing D###/M###) are already linked to the decision graph. The other 895 commits can be linked via file-path co-occurrence.

---

## Merging Holographic/Info-Theory into the Graph

The user's instinct: holographic and information-theoretic concepts should augment the graph structure, not replace it.

### How Holographic Reduced Representations (HRR) Merge

HRR encodes structured information as high-dimensional vectors using circular convolution for binding. Applied to our graph:
- Each node (sentence-level assertion) gets a vector
- Typed edges become binding operators (CITES_bind, SUPERSEDES_bind, etc.)
- A subgraph retrieved via BFS can be combined into a single holographic vector that "contains" the whole subgraph at lower resolution
- Query matching happens in vector space (fast approximate nearest neighbor) AND graph space (BFS for precision)

This is a hybrid: graph structure for precision and provenance, holographic vectors for fast approximate retrieval and the "every piece contains the whole" property.

### How Information Bottleneck Merges

IB theory (Tishby 1999) tells us: compress each node as much as possible while preserving its relevance to potential queries. Applied to our graph:
- Each sentence-node has an "IB-optimal" representation: the shortest version that preserves query-answering ability
- Anchor nodes get less compression (they're loaded frequently, accuracy matters)
- Deep graph nodes get more compression (they're loaded rarely, approximate is fine)
- This is principled token budget allocation, not arbitrary character limits

---

## KD Trees and Spatial Indexing

KD trees partition k-dimensional space for efficient nearest-neighbor queries. If beliefs are represented as vectors (via HRR or embeddings), KD trees could index them spatially.

Considerations:
- KD trees work well in low dimensions (< 20), degrade in high dimensions (curse of dimensionality)
- Belief vectors from HRR or embeddings are typically 100-1000 dimensional
- Approximate nearest neighbor (ANN) structures like HNSW or IVF may be more practical at high dimensions
- But: if we can project beliefs into a low-dimensional space that preserves semantic structure, KD trees could be fast and elegant

Research needed: what dimensionality reduction preserves the semantic relationships we care about?

---

## Gray Code and Binary Semantic Encoding

Gray code: adjacent values differ by exactly one bit. Applied to semantic space, this would mean semantically similar beliefs have binary representations that differ by few bits (small Hamming distance).

The tesseract traversal property is interesting: Gray code traverses all vertices of a hypercube visiting each exactly once, with adjacent vertices differing by one bit. If beliefs are vertices of a high-dimensional hypercube, Gray code gives a path through ALL beliefs where consecutive beliefs are maximally similar.

This connects to:
- **Locality-sensitive hashing** (LSH): similar items hash to similar codes
- **Semantic hashing** (Salakhutdinov & Hinton 2009): learned binary codes where semantic similarity = Hamming proximity
- **Binary embedding**: compress continuous vectors to binary for fast comparison

Practical approach: encode each sentence-node as a binary vector where Hamming distance approximates semantic distance. Then:
- Nearest-neighbor = flip bits and check
- Clustering = group by shared bit prefixes
- Traversal = Gray code path visits similar beliefs consecutively

Research needed: can we encode sentence-level assertions into binary vectors that preserve semantic similarity WITHOUT an LLM? (Bag-of-words hashing? TF-IDF to binary? Random projection to binary?)

---

## Requirements Traceability Structure (Aerospace Model)

The user described a requirements traceability structure familiar from aerospace/defense:

```
High-level requirement (REQ-001: cross-session decision retention)
  |
  v
Derived requirement (REQ-019: single-correction learning)
  |
  v
Functional requirement (correction detection must work at 92%+)
  |
  v
Implementation (V2 correction detector in extraction pipeline)
  |
  v
Verification artifact (Exp 1 overrides test: 92% on 36 corrections)
  |
  v
Validation (acceptance test AT-002: correction persists over 100+ turns)
```

This maps naturally to the graph with typed edges:
- DERIVES_FROM (derived req -> high-level req)
- IMPLEMENTS (code -> functional req)
- VERIFIES (test result -> requirement)
- VALIDATES (acceptance test -> requirement)

We already have this structure partially in REQUIREMENTS.md (plan trace, experiment trace, evidence fields). The graph would make it queryable: "show me all unverified requirements" = find requirement nodes with no incoming VERIFIES edges.

---

## Workflow Agnosticism

The system must work for anyone, not just GSD users.

What's GSD-specific and must be generalized:
- D###/M### citation syntax -> generalized reference detection
- DECISIONS.md / KNOWLEDGE.md structure -> generalized document parsing
- Milestone lifecycle -> generalized project phase tracking
- Override mechanism -> generalized correction detection (V2 handles this)

What's already general:
- Sentence splitting (English language conventions)
- Typed edges (CITES, SUPERSEDES, etc. are universal concepts)
- Bayesian confidence (domain-independent)
- Session recovery (any CLI can crash)
- MCP interface (model-agnostic by design)

The onboarding process (how the system ingests a new project) needs to be generalized:
1. Scan project directory for documents
2. Split documents into sentence-level assertions
3. Extract references and relationships between assertions
4. Build initial graph
5. Identify candidate anchor nodes (high-degree, user-corrected, frequently referenced)

This should work whether the project uses GSD, plain markdown, Jira tickets, or no structure at all.

---

## Research Approach

The user's directive: "the goal isn't to write a project and release it, the goal is to do novel and exciting research into an emerging field and see where the science leads us."

If the directed graph prototype is a dead end after sufficient exploration, restart from scratch. We are exploring the design space, not committing to an architecture.

Current exploration branches:
1. **Refine graph prototype** (granular nodes, typed traversal, temporal dimension)
2. **Holographic representations** (HRR encoding of graph structure)
3. **Binary semantic encoding** (Gray code, Hamming distance, semantic hashing)
4. **Information-theoretic compression** (IB for optimal node representation)
5. **KD trees / spatial indexing** (if dimensionality reduction works)
6. **Requirements traceability** (aerospace-style linking as graph structure)

Each can be explored to exhaustion, then return to the main stem with findings.

---

## Full-Monty Graph: Multi-Layer Ingestion From All Available Signals

**Date added:** 2026-04-10
**Status:** Design direction -- not yet scheduled

### The Idea

Assemble a complete project knowledge graph by extracting every available signal source and combining them into a single queryable structure. Each layer captures a different kind of relationship; no single layer is sufficient.

### Validated Layers (extractors exist and produce real data)

| Layer | Source | Edge/Node Types | Validated On |
|-------|--------|----------------|-------------|
| Code structure | Python `ast` / tree-sitter | CALLS, PASSES_DATA, CONTAINS | agentmemory (48 files), project-a (289 files) |
| Git history | `git log` | CO_CHANGED, COMMIT_BELIEF, SUPERSEDES_TEMPORAL | 7 T0 pilot repos + project-a |
| Imports | AST import parsing | IMPORTS | 5 T0 repos (Rust, TS, Python, C++) |
| Documentation refs | D###/REQ/CS regex | CITES, CROSS_REFERENCES | project-a (1,742 citations, 154 decisions) |
| Node classification | File structure + naming | Automatic node typing | 5 T0 repos |

### Designed but Not Yet Extracted

| Layer | Source | Edge/Node Types | Difficulty |
|-------|--------|----------------|-----------|
| Cloud deploys | GCP dispatch logs, plist configs | DEPLOYS_TO, DISPATCHES | Low |
| Test coverage | pytest + test file structure | TESTS, VALIDATES | Low |
| Directives | CLAUDE.md, hooks, project configs | BEHAVIORAL_CONSTRAINT, LOCKED_BELIEF | Low |
| Issue tracking | GitHub/Gitea issues, `#\d+` in commits | REFERENCES_ISSUE, RESOLVES | Low |
| Local vs remote | Reflog + remote comparison | LOCAL_COMMIT_BELIEF, REMOTE_COMMIT_BELIEF | Medium |
| Cross-machine | Gitea + lorax/server-a reflogs | AUTHORED_ON, PUSHED_TO | Medium |
| Type resolution | pyright/LSP batch mode | Resolved CALLS, OVERRIDES, IMPLEMENTS | Medium |
| Backtest results | Results CSV/JSON, metrics files | PRODUCES, MEASURES, SCORED_AT | Medium |
| Multi-project | Cross-repo shared concepts | SHARED_CONCEPT, CROSS_PROJECT_CITE | Hard |

### Key Findings From Initial Synthesis (Exp 37b)

Three validated layers (CALLS, CO_CHANGED, CITES) on project-a show **near-zero overlap** (Jaccard 0.000-0.012). Each layer captures genuinely different relationships. No file pair appeared in all three layers. This strongly suggests that adding more layers will continue to reveal new structure, not redundantly rediscover the same edges.

### Target Projects

1. **project-a** -- richest signal diversity: 552 commits, 289 Python files, 154 decisions, GCP dispatches, paper trading, backtest results, structured tests, CLAUDE.md directives, multi-machine dev (lorax + server-a via Gitea).
2. **A second project with maximal sparsity and depth** -- thin documentation, deep call chains, minimal decision history. Tests generalization. Candidates: smoltcp (Rust, protocols), project-d (Python, infra), or a local project with sparse history.

### What This Would Demonstrate

A full-monty graph on project-a would be the first concrete instance of the memory system's ingestion pipeline producing a multi-layer knowledge graph from a real project. It would answer:

- What is the total node and edge count across all layers?
- What is the per-layer coverage (which files/functions/decisions are visible in which layers)?
- What is the connected component structure (one giant component, or fragmented clusters)?
- Where are the coverage gaps (files with no edges in any layer)?
- What queries become trivially answerable that are currently hard?

### Not Scheduled Because

Research queue has higher-priority items that inform the architecture. The full-monty experiment is a validation exercise: it proves the pipeline works end-to-end but doesn't advance the theory. Schedule it when core architecture decisions are settled and we need a proof-of-concept demonstration.

---

## Conversation Turns as Primary Ingestion Pathway

**Date added:** 2026-04-10
**Status:** Adopted design direction

### The Insight

Decisions, requirements, assumptions, and preferences almost never originate in pre-written documentation. They emerge during conversation turns with the AI. A user doesn't write a spec saying "use PostgreSQL" -- they say it during a conversation, the AI acts on it, and the decision is made. By the time the context window rolls over, the decision is gone.

MemPalace recognized this: it stores entire conversations. The reasoning is sound -- conversations ARE where knowledge originates. But bulk conversation storage doesn't solve the problem. You end up with an archive of old chat fragments. When you search, you get "here's a conversation from March where you talked about databases" instead of "you decided to use PostgreSQL because of X, and that decision is still active."

### Our Approach: Extract, Don't Archive

The conversation turn is the primary observation source, but what gets stored is not the conversation -- it's what was decided, assumed, corrected, or learned during that conversation.

```
Conversation turn (raw observation)
  |
  v
Sentence decomposition (atomic claims)
  |
  v
Classification (decision / assumption / preference / correction / fact)
  |
  v
Graph insertion (nodes with typed edges to existing beliefs)
  |
  v
Holographic encoding (for retrieval without full graph traversal)
```

The conversation itself is provenance, not content. It's the observation layer in the scientific method model. The beliefs extracted from it are what matter.

### What This Changes

1. **Primary ingestion pathway is live conversation monitoring, not batch project scanning.** The onboarding pipeline (A031) becomes the secondary pathway for bootstrapping from existing project files. Day-to-day knowledge accumulation happens turn by turn.

2. **Extraction must be fast and incremental.** Each conversation turn produces 0-5 new beliefs. The pipeline processes one turn at a time, not a batch of documents. Latency budget: under 100ms per turn (zero-LLM path) to avoid slowing the conversation.

3. **The feedback loop is immediate.** When a belief is retrieved and the user says "no, that's wrong" in the next turn, that correction IS an observation that triggers belief revision. The conversation IS the feedback loop -- no separate testing mechanism needed for the most common case.

4. **Session boundaries matter.** A conversation session is a coherent unit of work. Beliefs extracted within a session share context. Cross-session belief linking (this contradicts what you said last week) requires the graph structure, not conversation proximity.

5. **The "always-loaded" context (L0) becomes a live summary.** Instead of static anchor nodes, L0 is rebuilt each session from the most relevant active beliefs. It's the system's current understanding of who you are, what you're working on, and what constraints apply -- updated every session.

### Why This Beats MemPalace

MemPalace stores 59,000 drawers of conversation chunks. Searching returns fragments with similarity scores. Our approach would store the 500-2,000 atomic beliefs that actually matter, each with:
- Explicit confidence (how sure are we this is still true?)
- Evidence chain (which conversations produced this belief?)
- Typed connections (what does this relate to, contradict, or supersede?)
- Retrieval via graph structure (find beliefs by what they connect to, not just what words they contain)

The goal: when the system retrieves context for a new session, it delivers the specific beliefs that matter for this task -- not conversation fragments that might contain something relevant.

### Relationship to Existing Architecture

The write path in PLAN.md already lists "conversation turn" as an input source. This direction elevates it from one-of-many to the primary pathway. The extraction pipeline, Bayesian confidence, typed edges, and holographic retrieval all apply unchanged. What changes is the priority ordering: conversations first, project files second.

The onboarding pipeline (A031) still matters for bootstrapping. When the system encounters a new project for the first time, it scans the directory to build an initial graph. But after that first scan, ongoing knowledge accumulation comes from conversation turns, not repeated directory scans.

### Open Questions

1. **How to intercept conversation turns?** MCP hook on conversation events? Post-response hook that feeds the turn to the extraction pipeline? Platform-specific integration (Claude Code hooks vs API streaming)?
2. **What about conversations that happen outside the system?** Slack discussions, email threads, meeting notes. These are also observation sources but arrive differently (batch import, not live streaming).
3. **Privacy and consent.** Storing beliefs extracted from conversations requires clear user consent. The user should know what's being remembered and have the ability to review, correct, or delete.
