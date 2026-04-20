# Design Ideas: State Tracking Framework + Exploratory Wonder

Status: Design exploration (2026-04-19)
Origin: StructMemEval 100% result + wonder architecture review


## IDEA 1: State Tracking as a Formal Design Framework

### The Observation

agentmemory scored 100% on StructMemEval's state-tracking benchmark, which
tests whether a memory system can maintain and update structured state across
multiple sessions. This is not just a strong result; it is the system's
strongest capability. The belief graph, SUPERSEDES edges, and locked beliefs
already form a state machine. The question is whether to formalize that and
make it the primary value proposition.

### What "State Tracking" Means Here

Memory systems answer "what do we know?" State tracking answers "where do we
stand?" The distinction matters:

| Memory (recall) | State tracking |
|-----------------|----------------|
| "We discussed using PostgreSQL" | "Database choice: PostgreSQL (decided 2026-03-15, alternatives rejected: SQLite, DynamoDB)" |
| "Tests were failing yesterday" | "Test suite: 871/872 passing, 1 flaky (test_concurrent_writes, tracked since 2026-04-10)" |
| "The user wants strict typing" | "Constraint: strict pyright typing (locked, non-negotiable)" |

Memory is a bag of facts. State tracking is a structured, current-as-of-now
representation of project reality. The LLM does not just remember things; it
knows the current state of every tracked dimension.

### How agentmemory Already Models State

**SUPERSEDES edges are state transitions.** When belief B supersedes belief A,
that is a state update. The old state (A) is preserved but marked as historical.
The current state is always the leaf node in a SUPERSEDES chain. This is
exactly how event sourcing works: the current state is the result of applying
all transitions in order.

Example SUPERSEDES chain:
```
"Database: undecided" (2026-03-01)
  --> SUPERSEDES --> "Database: leaning PostgreSQL" (2026-03-10)
    --> SUPERSEDES --> "Database: PostgreSQL, decided" (2026-03-15)
```

Reading the chain gives you the decision history. Reading the leaf gives you
the current state.

**Locked beliefs are invariants.** A locked belief is a constraint that cannot
be overridden by new evidence. In state-machine terms, these are the
preconditions and invariants that bound all valid states. "Always use uv for
Python" is not a memory; it is a constraint on every future state.

**Beta distributions encode certainty about state.** A belief with
Beta(50, 2) is a well-established state. A belief with Beta(1, 1) is an
unresolved state. The confidence model already distinguishes between "we are
sure about this" and "this is provisional."

### The Formal Framework

Define three categories of tracked state:

**1. Project State**
- Current phase, milestone, and blockers
- What is done, what is in progress, what is next
- Maps to: beliefs with type=decision or type=requirement
- Updated via: SUPERSEDES edges when phase transitions occur

**2. Decision State**
- What was decided, when, by whom, and why
- What alternatives were considered and rejected
- Maps to: SUPERSEDES chains where each node captures a decision point
- Query pattern: "walk the SUPERSEDES chain for decision X to see its full history"

**3. Requirement State**
- Which requirements are met, which are open, which are blocked
- What evidence supports each requirement's status
- Maps to: beliefs with type=requirement, confidence encoding completion status
- A requirement with Beta(1,1) is untouched; Beta(50,2) is verified

### Concrete Example: Tracking a Feature

A team building an authentication system might have this state graph:

```
REQ: "Users must be able to log in with OAuth2"
  status: open
  confidence: Beta(1,1)

DECISION: "Use Auth0 as OAuth2 provider"
  status: decided
  alternatives_rejected: [Cognito, Firebase Auth]
  rationale: "Auth0 supports all required social providers"
  confidence: Beta(10,1)

PHASE: "Auth integration"
  status: in_progress
  blockers: ["waiting on Auth0 sandbox credentials"]
  depends_on: [DECISION above]
```

When the team gets credentials and completes integration:

```
REQ: "Users must be able to log in with OAuth2"
  status: met
  confidence: Beta(50,2)
  evidence: ["integration test passing", "manual QA sign-off"]
  SUPERSEDES --> previous REQ node with status: open
```

The LLM can now answer: "What is the status of OAuth2 login?" with a precise,
sourced answer rather than vague recall.

### Integration with External Tools

The state graph does not need to replace GitHub Issues or Linear. It should
sync with them:

- **GitHub Issues:** When an issue closes, a SUPERSEDES edge updates the
  corresponding requirement belief from open to met.
- **Linear/Jira:** Sprint state maps to project-phase beliefs. When a sprint
  completes, the phase state transitions.
- **CI/CD:** Test results update requirement confidence. A passing test suite
  is evidence (alpha += 1) for the "tests pass" state.

The value is not duplicating these tools. It is giving the LLM a unified view
across all of them. The LLM does not need to query GitHub, Linear, and CI
separately. It queries its state graph and gets one coherent picture.

### How This Differs from GSD

GSD (Get Stuff Done) provides a workflow framework: phases, plans, execution,
verification. It is procedural -- it tells you what to do next.

State tracking is declarative -- it tells you where things stand. The two are
complementary:

- GSD says "execute phase 3"
- State tracking says "phase 3 depends on decision D which is still unresolved"
- GSD says "plan the next milestone"
- State tracking says "milestone 2 has 3/7 requirements met, 2 blocked, 2 open"

A state-aware GSD would be significantly more capable than either alone.

### Open Questions

1. **Schema rigidity vs flexibility.** Should state categories (project,
   decision, requirement) be enforced schema, or should they emerge from
   belief types organically? Enforced schema is more reliable but less
   adaptable.

2. **State staleness.** How do you detect when tracked state has drifted from
   reality? A requirement belief might say "tests passing" when CI has been
   red for a week. Staleness detection needs an active polling mechanism or
   event-driven updates.

3. **Cross-project state.** The rhizome architecture (docs/RHIZOME_ARCHITECTURE.md)
   already proposes cross-vault belief transfer. State tracking across projects
   adds complexity: project A's state should not pollute project B's state graph.

4. **Granularity.** Track every micro-decision ("chose camelCase for this
   variable") or only significant ones? Too granular and the state graph
   becomes noise. Too coarse and you miss important context. The answer is
   probably configurable thresholds.

5. **Visualization.** State graphs are only useful if you can see them. A
   CLI status command that renders the current state tree (phase, decisions,
   requirements, blockers) would be essential. Web UI would be better.


## IDEA 2: Wonder Should Generate Beliefs from OUTSIDE the Graph

### The Current Limitation

Today, `/mem:wonder` works like this:

1. Takes a query (hypothesis, question, topic)
2. Searches the belief graph via FTS5 keyword matching
3. Walks the graph via BFS from matching nodes
4. Identifies uncertainty (high-entropy beliefs)
5. Flags contradictions (CONTRADICTS edges)
6. Returns a structured analysis

This is useful but fundamentally closed-world. Wonder can only find what is
already in the graph. If nobody ever ingested a belief about, say, vector
databases, then `wonder("should we use a vector database for embeddings?")`
returns nothing useful. The system has a blind spot and no way to discover it.

### The Proposal: Exploratory Wonder

Wonder should also generate speculative beliefs about things that are NOT in
the graph. The process:

1. **Search internally** (current behavior, unchanged)
2. **Identify knowledge gaps** -- if the query topic has few or no matching
   beliefs, that itself is a signal
3. **Generate speculative beliefs** from external sources:
   - LLM reasoning from context ("given what we know about X, Y is likely true")
   - Web search for current documentation, best practices, known issues
   - Documentation lookups for libraries and tools in use
4. **Insert speculative nodes** into the graph with distinctive metadata:
   - `alpha=0.3, beta=1.0` (low confidence, minimal evidence)
   - `source_type="wonder_generated"`
   - `type="speculative"`
   - Linked to the query context via RELATES_TO edges

These speculative nodes represent the frontier of the graph -- things the
system suspects it should know but has not confirmed.

### The Wonder/Reason Cycle

This creates a two-phase epistemology:

```
wonder("topic X")
  |
  +--> retrieves known beliefs (existing behavior)
  +--> generates speculative beliefs (new behavior)
  |      alpha=0.3, source_type=wonder_generated
  |
  v
[speculative beliefs sit in graph with high uncertainty]
  |
  v
reason("is speculative belief Y actually true?")
  |
  +--> tests Y against available evidence
  +--> queries external sources for confirmation/refutation
  +--> updates Y's confidence (alpha/beta) based on findings
  |
  v
[belief Y is now either confirmed (high alpha) or refuted (high beta)]
```

This mirrors the scientific method:
- **Wonder** = hypothesis generation (what might be true?)
- **Reason** = hypothesis testing (is it actually true?)
- **Feedback** = evidence accumulation (how sure are we now?)

### Concrete Example

A developer working on agentmemory wonders about embedding support:

```
wonder("should agentmemory use vector embeddings for semantic search?")
```

**Current behavior:** Returns any existing beliefs mentioning "embeddings",
"vector", or "semantic search". If none exist, returns nothing useful.

**Proposed behavior:** In addition to existing beliefs, generates speculative
nodes:

```
SPECULATIVE: "sentence-transformers/all-MiniLM-L6-v2 is a common embedding
  model for semantic search in Python applications"
  alpha=0.3, beta=1.0, source_type=wonder_generated
  source: LLM reasoning

SPECULATIVE: "ChromaDB and Qdrant are popular vector databases that integrate
  with Python"
  alpha=0.3, beta=1.0, source_type=wonder_generated
  source: LLM reasoning

SPECULATIVE: "FTS5 keyword search misses semantic similarity, e.g. 'database
  choice' does not match 'PostgreSQL'"
  alpha=0.3, beta=1.0, source_type=wonder_generated
  source: internal evidence (WONDER_BASELINE.md documents this gap)

SPECULATIVE: "Adding embeddings would increase storage requirements by ~10x
  for 768-dimensional float32 vectors"
  alpha=0.3, beta=1.0, source_type=wonder_generated
  source: LLM reasoning
```

Now `reason("is the FTS5 semantic gap a real problem?")` can test the third
speculative belief against actual retrieval logs and update its confidence.

### Generation Strategies

**LLM reasoning from context (lowest cost, lowest risk):**
The LLM uses its training knowledge plus the existing belief graph to generate
plausible hypotheses. No external calls needed. Risk: training data may be
stale. Benefit: fast, private, always available.

**Web search (higher quality, privacy cost):**
Query a search engine for current information about the topic. Risk: leaks
query content to the search provider. Benefit: current information, links to
sources. Should be opt-in and clearly flagged.

**Documentation lookup (targeted, lower risk):**
If the query involves a known library or tool, fetch its current documentation.
Lower privacy risk than general web search because the query is scoped to a
specific package. Context7 MCP integration could serve this role.

### Rate Limiting and Garbage Collection

Unchecked speculation floods the graph with low-quality noise. Safeguards:

**Rate limiting:**
- Maximum N speculative beliefs per wonder call (suggest N=5)
- Maximum M speculative beliefs per project per day (suggest M=20)
- Cooldown period between wonder calls that generate speculation (suggest 60s)

**Garbage collection:**
- Speculative beliefs that are never accessed within T days decay to zero
  confidence and are soft-deleted (suggest T=14)
- Speculative beliefs that are accessed but never confirmed (alpha stays at
  0.3) decay faster than confirmed beliefs
- The existing decay system (if one exists) should apply a higher decay rate
  to source_type=wonder_generated beliefs, perhaps 2x the normal rate
- A weekly or on-demand GC pass removes expired speculative beliefs

**Quality gate:**
- Before inserting a speculative belief, check if a substantially similar
  belief already exists (FTS5 overlap score > threshold). If so, skip the
  duplicate.
- Speculative beliefs should never be auto-locked. They must pass through
  reason or manual confirmation before they can be promoted to regular beliefs.

### Privacy Implications

Web search leaks query content. This matters because wonder queries often
contain project-specific details: feature names, architecture decisions,
business logic. Mitigations:

- **Default to LLM-only speculation.** No external calls unless the user
  explicitly enables web search for wonder.
- **Anonymize queries before external search.** Strip project-specific nouns
  and search for the generic concept. "Should agentmemory use vector
  embeddings?" becomes "vector embeddings for semantic search Python."
- **Log all external queries.** The user should be able to audit what was
  searched. Store the raw query and the sanitized query in the belief's
  metadata.
- **Respect privacy settings.** If the project has a privacy policy (see
  docs/PRIVACY.md), wonder should honor it. Some projects may prohibit any
  external data flow.

### Relationship to Existing Architecture

**Belief types:** A new `speculative` type joins the existing taxonomy
(factual, decision, correction, requirement, etc.). Classification pipeline
would need a new category or speculative beliefs bypass classification entirely
since their type is known at creation.

**Edges:** Speculative beliefs connect to the query context via RELATES_TO
edges. If a speculative belief is confirmed, it gets reclassified to an
appropriate type (factual, decision, etc.) and its RELATES_TO edges are
preserved.

**Confidence model:** The Beta(0.3, 1.0) starting point means speculative
beliefs have ~23% confidence and very low evidence weight. They will not
dominate retrieval results. As evidence accumulates through reason or feedback,
they either climb toward established beliefs or sink toward deletion.

**Retrieval:** Speculative beliefs should appear in search results but be
clearly marked. A retrieval result showing `[SPECULATIVE]` next to a belief
tells the LLM to treat it as a hypothesis, not a fact.

### Open Questions

1. **Who generates the speculation?** The LLM calling wonder, or a dedicated
   sub-agent? A sub-agent could be more thorough (multiple search strategies,
   longer reasoning chains) but costs more tokens.

2. **Should speculation be interactive?** Instead of auto-generating 5
   speculative beliefs, wonder could propose them and ask the user which ones
   to persist. This prevents graph pollution but adds friction.

3. **How does this interact with onboarding?** When a new project is onboarded,
   wonder could auto-generate speculative beliefs about the tech stack based
   on detected dependencies. "This project uses FastAPI, so CORS configuration
   is likely relevant." Useful or presumptuous?

4. **Confirmation pathways beyond reason.** Can speculative beliefs be
   confirmed by evidence other than explicit reason calls? For example, if
   the user ingests a conversation that happens to confirm a speculative
   belief, should the pipeline detect the match and update confidence
   automatically?

5. **Scope boundaries.** Should wonder speculate about anything related to
   the query, or only about things within the project's domain? A query
   about database choice should not generate speculative beliefs about
   unrelated topics just because the LLM's reasoning chain wandered.

6. **Avoiding hallucination laundering.** The risk: the LLM generates a
   speculative belief from its training data, that belief enters the graph,
   and future retrievals treat it as project knowledge. The belief's origin
   is "LLM reasoning" but it reads like a fact. Strong source_type labeling
   and retrieval-time marking mitigate this, but the risk is real.


## Relationship Between the Two Ideas

These ideas are complementary. State tracking (Idea 1) gives the system a
structured view of where things stand. Exploratory wonder (Idea 2) gives it
the ability to discover what it does not know.

Together: wonder identifies gaps in the state graph ("we have no decision
recorded about database choice"), generates speculative states ("database:
undecided, candidates: PostgreSQL, SQLite, DynamoDB"), and reason resolves
them into confirmed states.

State tracking without exploratory wonder is passive -- it tracks what you
tell it. Exploratory wonder without state tracking is chaotic -- it generates
speculation with no structure to anchor it. The combination is an active,
structured knowledge system that both maintains what is known and seeks what
is not.
