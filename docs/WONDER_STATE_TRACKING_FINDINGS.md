# Wonder Findings: State Tracking as a Formal Design Framework

Date: 2026-04-19
Wonder query: State tracking formalization (SUPERSEDES chains, Beta distributions, state categories)
Agents: 4 (Domain Research, Gap Analysis, Contrarian, Analogical)
Speculative beliefs created: 70 (anchored to b1b572e8352e, e83ccb7b67c2, db3c1b771f79)


## Coverage

64.7% of the topic was already in the belief graph. 64 known beliefs, 7 unresolved
contradictions, 71 high-uncertainty beliefs about state topics.


## Key Findings by Axis

### Axis 1: Domain Research

- Event sourcing maps directly to existing architecture: SUPERSEDES = event log,
  leaf belief = materialized view, confidence_history = audit trail
- CQRS is already implemented: write path (ingest/classify/insert) is separate from
  read path (retrieve/score/pack)
- AGM belief revision: `correct()` implements the Levi Identity (contract negation,
  then expand with new belief)
- No other memory system (Mem0, Letta, EverMemOS) implements formal belief revision
  or Beta confidence distributions
- StructMemEval 100% was achieved on location/small subset (14 queries). Accounting,
  recommendation, and tree tasks remain unevaluated and are structurally harder
- POMDP framing maps state categories to observability: Project State = observable,
  Decision State = medium observability, Requirement State = reward function
- The "middle path" recommendation: formalize the implicit lifecycle state machine
  without adding new state categories

### Axis 2: Gap Analysis (codebase audit)

Critical gaps found:

1. **No "current state of X" composite query** -- the most fundamental gap. No API
   answers "what is the current state of database choice?" with a structured object
2. **DECISION type mismatch** -- the classifier produces DECISION as a type with
   prior (5.0, 1.0), but no BELIEF_DECISION constant exists in models.py. Decisions
   silently map to `factual`
3. **Checkpoint system underused** -- `checkpoints` table has decision/task_state/goal
   types but zero query layer
4. **confidence_history never queried** -- the table records every alpha/beta change
   but no analysis functions use it for trajectory analysis
5. **supersede_belief() lock hole** -- auto-detector skips locked beliefs, but direct
   callers can silently supersede them
6. **Linear SUPERSEDES only** -- no branching decision histories supported
7. **No aggregate state-level confidence** -- individual beliefs have Beta distributions
   but there is no way to compose them into topic-level certainty

Underused foundations:

- Checkpoint system (has types, no queries)
- confidence_history table (has data, no analysis)
- DECISION classification type (exists in classifier, no dedicated belief type)

### Axis 3: Contrarian Analysis

Arguments against formalization:

1. **The system already works** -- 100% StructMemEval, no documented retrieval failure
   that state categories would fix
2. **Classification ambiguity** -- "we chose SQLite" is simultaneously a decision,
   project state fact, and requirement constraint. Write-time classification forces a
   choice that may be wrong
3. **Misclassified state is worse than no state** -- a decision tagged as factual won't
   appear in decision-state queries, causing the user to re-decide
4. **Staleness is unsolved** -- no oracle to poll, no clean detection mechanism. Current
   Beta decay sidesteps this honestly
5. **CS-003's real lesson** -- the failure was not consulting state (retrieval activation),
   not lacking state representation
6. **Dual-write divergence** -- state in agentmemory AND external tools leads to
   disagreement
7. **Scope creep** -- state tracking for one project is useful; state tracking that
   replaces project management tools is a trap

Minimum viable alternative: free-form tags on beliefs with filtered search. 80% of
the value at 5% of the complexity.

### Axis 4: Analogical Research

Five domains examined, all converging on the same core patterns:

| Domain | Key Analogy | Design Implication |
|--------|------------|-------------------|
| Event sourcing | SUPERSEDES = event log, leaf = projection | Add explicit projections table for O(1) current-state queries |
| ADRs | Proposed -> Accepted -> Superseded lifecycle | Decision beliefs need lifecycle states, supersession needs rationale |
| Git DAG | Commits supersede parents, branch pointers = current state | Reference-like pointers to chain leaves for fast current-truth lookup |
| PubMed | Typed supersession (retraction vs correction vs erratum) | Differentiate why beliefs were superseded, not just that they were |
| DO-178C | Requirement traceability (Draft -> Verified), DAL levels | RTM generatable from IMPLEMENTS/TESTS edges. Lock levels = DAL |

Cross-cutting convergence: immutable history, derived current truth, typed supersession,
bidirectional linking, lifecycle states distinct from confidence.

Critical PubMed finding: retracted articles continue to be cited despite supersession
links. Superseded beliefs must be actively suppressed in search, not just marked.

Harel statecharts suggest orthogonal state dimensions: lifecycle state, confidence state,
and lock state should be independent axes rather than conflated in a single score.


## Unresolved Questions

1. How often do "what is the current state of X?" queries actually fail today? No data.
2. Would tags + better retrieval suffice, or do formal state types add real value?
3. Can the checkpoint system be repurposed as the state query layer without new schema?
4. What is the right granularity for state tracking? (Too fine = noise, too coarse = useless)
5. How should cross-project state boundaries work?


## Candidate Next Steps (not prioritized)

- Prototype a `state_of(topic)` composite query
- Add BELIEF_DECISION type to models.py (easy fix for a real classification gap)
- Build checkpoint query layer (foundation exists)
- Add free-form tags as minimum viable state organization
- Instrument retrieval to measure how often state queries fail (data before design)
- Add typed supersession reasons (retraction vs correction vs update)
