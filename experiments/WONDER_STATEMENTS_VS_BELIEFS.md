# Wonder: Statements vs Beliefs -- Ontological Separation and Mathematical Formalization

**Date:** 2026-04-12
**Branch:** wonder/statements-vs-beliefs
**Subagents:** 8 (epistemology, math formalization, prior art, codebase mapping, temporal dynamics, graph theory, information theory, practical implications)
**Query:** "What we're calling beliefs should be called statements. Beliefs are how the agent views the project at any given moment. How can we formalize this mathematically?"

---

## 1. The Core Distinction

What agentmemory currently calls "beliefs" are **statements** -- propositions that can be true or false, extracted from conversation and code. A statement is: "we use PostgreSQL" or "always run tests before committing."

A **belief** is something different: it is an agent's *propositional attitude* toward a statement. Formally:

```
Statement s:  "we use PostgreSQL"           (exists independently of any agent)
Belief B(s):  Agent accepts s at credence c  (agent's stance toward the statement)
```

This is not a naming quibble. The system currently conflates the proposition with the agent's confidence in it by storing them as a single row. Separating them enables fundamentally new capabilities.

---

## 2. Mathematical Formalization

### 2.1 Statement Space

Let S = {s_1, s_2, ..., s_n} be the set of all statements in the database. Each statement has:
- Content (natural language proposition)
- Type t_i in {factual, requirement, correction, preference, procedural, causal, relational}
- Source provenance (user_stated, user_corrected, document_recent, agent_inferred)
- Temporal validity window [valid_from, valid_to]
- Graph edges E_i (SUPPORTS, CONTRADICTS, SUPERSEDES, CITES, RELATES_TO, TEMPORAL_NEXT)

Statements form a directed knowledge graph G = (S, E) where edges encode logical and temporal relationships.

### 2.2 Belief State

A **belief state** B(t) at time t is a function:

```
B(t): S(t) -> [0, 1]
```

mapping each statement to the agent's credence (degree of acceptance). The current system already computes this:

```
B(t)(s_i) = alpha_i / (alpha_i + beta_i)    (Beta distribution expected value)
```

But this is *local* -- it treats each statement independently. A proper belief state must account for joint consistency.

### 2.3 Three Equivalent Formalizations

**F1: Credal Set (Levi's Framework)**

The agent's epistemic state is a pair (K, C) where:
- K = corpus of accepted statements (locked beliefs, high-confidence items)
- C = credal state -- probability distribution over remaining statements

This maps directly to the current architecture:
- K = locked beliefs (confidence >= threshold, immune to decay)
- C = Beta(alpha_i, beta_i) distributions for unlocked statements

**F2: Dempster-Shafer Mass Function**

Let Theta be the frame of discernment (possible project states). Each statement s_i induces a mass function m_i over subsets of Theta. The global belief state is the Dempster combination:

```
Bel(A) = SUM_{B subset A} m(B)     (belief function -- lower bound)
Pl(A)  = SUM_{B intersect A != 0} m(B)  (plausibility -- upper bound)
```

The interval [Bel(A), Pl(A)] quantifies the agent's epistemic uncertainty about A.

**F3: Maximal Consistent Subgraph**

A belief is a maximal connected component of *consistent* statements in G:

```
B_i subset S  where:
  - For all (s_j, s_k) in B_i: NOT CONTRADICTS(s_j, s_k)
  - B_i is maximal (no statement can be added without contradiction)
```

Belief confidence = aggregation over component statements:

```
conf(B_i) = SUM(c(s_j) * type_weight(s_j) * source_weight(s_j) * decay(s_j))  for s_j in B_i
```

### 2.4 Belief Evolution as a Dynamical System

At time t, the agent has observed statements S(t). The belief state evolves:

```
B(t+1) = UPDATE(B(t), new_statements, feedback)
```

This dynamical system has:
- **Fixed-point attractors**: Locked beliefs (confidence = 1.0, immune to decay, only user override changes them)
- **Dissipative dynamics**: Unlocked beliefs decay toward zero via half-life functions (factual: 14d, procedural: 21d, causal: 30d)
- **Velocity-dependent transience**: Sprint-origin beliefs decay 10x faster than deep-work beliefs (Exp 75)
- **Feedback perturbation**: "used" increases alpha, "harmful" increases beta

The system is **asymptotically stable** around the locked belief set: over infinite time with no new input, only locked beliefs survive.

### 2.5 Information-Theoretic Compression

Statements are raw data (high entropy, redundant, possibly contradictory). Beliefs are compressed:

```
B = COMPRESS(S)  where |B| << |S|
```

This maps to the **Information Bottleneck** (Tishby et al., 1999):

```
min I(X; T) - beta * I(T; Y)
```

where X = full statements, T = compressed belief, Y = query relevance.

The session-start injection is literally this: given a token budget of 2000 tokens (rate constraint), select and compress statements to maximize predictive value (minimize distortion). Exp 55 validated that rate-distortion optimal allocation beats heuristic by 5-10% NDCG.

---

## 3. Theoretical Grounding

### 3.1 BDI Architecture (Bratman 1987, Rao & Georgeff 1991)

The most natural framework. In BDI:
- **Beliefs**: Agent's accepted model of the world (NOT raw data)
- **Desires**: Goals (orthogonal to this project)
- **Intentions**: Commitments to action

Raw observations go through a **belief revision process** before becoming beliefs. This is exactly the proposed separation: statements are observations/propositions, beliefs are the agent's processed model.

### 3.2 Levi's Corpus vs Credal State

Isaac Levi distinguishes:
- **Corpus K**: Set of fully accepted statements (analogous to locked beliefs)
- **Credal state C**: Probability assignments over uncertain propositions (analogous to Beta distributions)

The pair (K, C) = complete epistemic state. agentmemory already implements both halves -- it just doesn't separate them conceptually.

### 3.3 AGM Belief Revision (Alchourron, Gardenfors, Makinson 1985)

Three operators for rational belief change:
- **Expansion** (K + s): Add s without conflict (new statement, no contradictions)
- **Contraction** (K - s): Remove s and minimal consequences (belief retracted)
- **Revision** (K * s): Add s, resolve conflicts minimally (correction supersedes old)

The existing edge types map directly:
- SUPPORTS = evidence for expansion
- CONTRADICTS = trigger for revision
- SUPERSEDES = executed revision (old belief contracted, new one expanded)

---

## 4. What the Codebase Currently Has

### 4.1 Blast Radius

**772 occurrences** of "belief" across 11 core files:

| File | Count | Nature |
|------|-------|--------|
| cli.py | 208 | Mostly docstrings (safe to update) |
| store.py | 206 | Schema + methods (core rename target) |
| server.py | 173 | MCP tool implementations |
| retrieval.py | 50 | Ranking pipeline |
| scoring.py | 50 | Confidence + decay |
| ingest.py | 37 | Classification pipeline |
| supersession.py | 24 | Temporal redundancy |
| compression.py | 14 | Context packing |
| models.py | 6 | Core dataclass |
| scanner.py | 3 | Node extraction |
| hrr.py | 1 | Docstring |

### 4.2 What Should Be Renamed to "Statement"

- **Table**: `beliefs` -> `statements`
- **Columns**: `belief_type` -> `statement_type`, all FK `belief_id` -> `statement_id`
- **Class**: `Belief` dataclass -> `Statement`
- **Constants**: `BELIEF_FACTUAL` etc -> `STATEMENT_FACTUAL`
- **Methods**: `insert_belief()`, `get_belief()`, `lock_belief()`, `delete_belief()` etc

### 4.3 What Should Stay as "Belief"

- Confidence parameters (alpha, beta) -- these ARE the agent's belief about a statement
- Locked flag -- agent's conviction level
- Scoring functions -- belief-level assessment
- Feedback outcomes -- agent's evaluation
- confidence_history table -- tracks belief evolution

### 4.4 External API Impact

MCP tool names are mostly safe (don't contain "belief" except `create_beliefs`). CLI command `/mem:new-belief` would need updating. 38 test functions reference "belief" in names.

---

## 5. New Capabilities Unlocked

The separation enables queries that are currently impossible:

| Capability | Description |
|------------|-------------|
| **Belief snapshot** | "What did the agent believe at session 5?" -- synthesize B(t) at a point in time |
| **Belief trajectory** | "How has the agent's view of X changed?" -- B(t) over time for topic X |
| **Provenance chain** | "What statements support this belief?" -- reverse lookup from synthesized view to evidence |
| **Belief divergence** | Compare two agents' beliefs about the same project |
| **Doxastic closure** | "Is the agent's belief state internally consistent?" -- detect contradictions in B(t) |

---

## 6. Proposed Schema

### New `beliefs` table (synthesized views):

```sql
CREATE TABLE beliefs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    synthesized_text TEXT NOT NULL,
    confidence REAL,
    statement_ids TEXT NOT NULL DEFAULT '[]',  -- JSON array
    supporting_count INTEGER,
    contradicting_count INTEGER,
    timestamp TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, topic),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
```

### HRR Integration

HRR already encodes structural relationships as superpositions of statement vectors. A belief could be:

```
belief_vector = superpose(statement_vectors for all s_i in consistent subgraph)
```

Recovered via unbind operations -- decompressing the superposition to extract constituent statements. This gives beliefs a vector representation that inherits HRR's vocabulary-bridge properties.

---

## 7. Migration Strategy

**Recommended: Incremental (not big-bang)**

1. Add `statements` as alias/view over existing `beliefs` table
2. Dual-write: new inserts go to both for N weeks
3. Redirect reads to `statements`
4. Add synthesis layer: compute beliefs from statement clusters
5. Expose new belief query tools alongside existing API
6. Deprecate old naming gradually

Estimated effort: ~200 lines of code changes + schema migration. 38 tests need updating. Medium difficulty, 2-4 weeks with good coverage.

---

## 8. The Key Equation

If we had to capture the entire distinction in one equation:

```
B(t) = SYNTHESIZE(G(t), K(t), C(t))
```

where:
- G(t) = statement graph at time t (nodes = statements, edges = relationships)
- K(t) = corpus of locked statements (non-negotiable constraints)
- C(t) = credal state (Beta distributions over uncertain statements)
- B(t) = the agent's synthesized belief state (what it actually "thinks" right now)

The function SYNTHESIZE does:
1. Start with K(t) as the foundation (locked = always believed)
2. Expand via consistent subgraph extraction from G(t)
3. Weight by C(t) credences
4. Compress to token budget via rate-distortion optimization
5. Output: the agent's coherent, time-stamped worldview

This is what session-start context injection *should* be computing. Currently it's a ranked list of statements. It should be a synthesized belief state.

---

## 9. Open Questions

1. **Synthesis trigger**: When does belief synthesis happen? Per-session? Per-query? Background job?
2. **Consistency enforcement**: How expensive is maximal-consistent-subgraph computation on 15K+ statements?
3. **Belief identity**: When is B(t) "the same belief" as B(t-1) with updated confidence vs a "new belief"?
4. **Multi-agent beliefs**: If two agents share a statement store, their beliefs diverge based on different feedback histories. How to track?
5. **Belief about beliefs**: The agent's confidence in its own belief state (meta-cognition) -- is this a third layer?

---

## 10. References

- Alchourron, Gardenfors, Makinson (1985). "On the Logic of Theory Change: Partial Meet Contraction and Revision Functions." JSL 50(2).
- Bratman, M. (1987). "Intention, Plans, and Practical Reason." Harvard UP.
- Rao, A. & Georgeff, M. (1991). "Modeling Rational Agents within a BDI-Architecture." KR-91.
- Rao, A. & Georgeff, M. (1995). "BDI Agents: From Theory to Practice." ICMAS-95.
- Levi, I. (1980). "The Enterprise of Knowledge." MIT Press.
- Tishby, N., Pereira, F., & Bialek, W. (1999). "The Information Bottleneck Method." Allerton.
- Hintikka, J. (1962). "Knowledge and Belief." Cornell UP.
- Dempster, A. (1967). "Upper and Lower Probabilities Induced by a Multivalued Mapping." Annals of Mathematical Statistics.
- Shafer, G. (1976). "A Mathematical Theory of Evidence." Princeton UP.
