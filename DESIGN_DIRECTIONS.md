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
