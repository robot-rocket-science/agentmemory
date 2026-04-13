# Reason: Statements vs Beliefs -- Ontological Distinction

**Date:** 2026-04-12
**Method:** 8-subagent parallel reasoning (epistemology, math, prior art, codebase audit, temporal dynamics, graph theory, information theory, practical rename assessment)
**Branch:** wonder/statements-vs-beliefs

## Finding

The system conflates two distinct concepts under the term "belief":

1. **Statements** -- what the system stores. Propositions with provenance, static Beta(alpha, beta) confidence, type classification, timestamps, lock flags. Immutable after creation. ~19,000 rows in the DB.

2. **Beliefs** -- what the agent computes at query time. The retrieval pipeline (FTS5 + scoring + decay + Thompson sampling + budget packing) projects statements into a query-dependent, time-sensitive, ephemeral view. Different query = different beliefs. Same query later = different beliefs (Thompson sampling).

## Mathematical Formalization

- **S = {s_i}** -- set of stored statements with metadata (type tau, Beta(alpha_i, beta_i), source sigma_i, timestamp t_i, lock flag l_i)
- **B(q, t) = f(S, q, t)** -- belief is a function mapping statements + query + time to a weighted view
- **strength_B(s_i) = decay(s_i, t) * Thompson(alpha_i, beta_i) * relevance(s_i, q)**
- Alpha/beta are **statement-level** (evidence for/against the proposition), not belief-level (how strongly the agent holds a view)
- The retrieval pipeline IS the belief-forming function. It exists. It's unnamed.

## Analogies from Other Fields

| Domain | Stored Layer | Computed Layer |
|--------|-------------|---------------|
| Epistemology | Propositions | Justified beliefs (attitudes toward propositions) |
| Doxastic logic | Assertions P | Modal operator Box_s(P) = "agent s believes P" |
| BDI architecture | Informational state | Belief set feeding deliberation |
| Database theory | Base relations | Materialized views |
| Probabilistic DBs | Uncertain tuples | Query-time probability |
| Information theory | Raw data S (high entropy) | Compressed representation B = IB(S, query) |
| Particle filters | Particles (weighted samples) | State estimate (weighted sum) |

## Temporal Model

Not a Kalman filter (continuous hidden state from noisy observations). Closer to a **discrete particle filter**:
- Statements are particles with static weights
- Decay resamples (downweights old particles)
- Supersession removes particles
- Session boundaries trigger recomputation
- No continuous dynamics -- event-based model

Velocity-scaled decay (Exp 58c) makes this explicit: high-velocity statement arrival = faster decay = belief instability in active areas.

## Information Bottleneck Interpretation

The statement-to-belief transformation is a lossy channel with capacity C = token budget (2000 tokens):

```
L = I(S; B) - beta * I(B; Answer | Query)
Minimize: bits spent on B (compression cost)
Subject to: maintain I(B; Answer | Q) >= threshold
```

The retrieval pipeline implements this through staged compression:
1. Type classification (discard EPHEMERAL, beta -> 0)
2. FTS5 BM25 ranking (proxy for pointwise MI)
3. Scoring (confidence * relevance * decay)
4. Token budget packing (hard rate constraint)

Locked statements bypass the query-dependent optimization, consuming fixed channel capacity regardless of relevance. This violates IB optimality when locked content is irrelevant to the current query.

## Graph Theory

The current graph is a **statement graph pretending to be a belief graph**:
- Nodes are stored propositions (static)
- Edges are structural (CONTRADICTS, SUPERSEDES, RELATES_TO)
- The retrieval pipeline materializes a belief view on demand

A true belief graph would have:
- Virtual nodes (computed at query time, not stored)
- Inferential edges (confidence-dependent, directional)
- Session-scoped caching

Current architecture is actually well-positioned: statement graph with on-demand belief materialization via the scoring pipeline.

## Codebase Audit

Every usage of "belief" in the codebase is STATEMENT-like:
- `Belief` dataclass: pure data structure, static metadata
- `insert_belief()`: stores unchanged content with assigned priors
- `store.search()`: keyword matching on stored content
- `retrieve()`: the ONE place where belief-like behavior emerges (scoring, decay, Thompson sampling)

The feedback loop (`update_confidence()`) exists but is dead code -- it would be the mechanism for beliefs to influence statement confidence over time.

## Practical Rename Assessment

Full rename scope: 210 files, 5,972 occurrences, 780 unique identifiers, 10 DB tables.
Semantic conflict: `OBS_TYPE_USER_STATEMENT` already exists.
Estimated effort: 20-28 hours.

**Recommendation:** Adopt terminology in documentation and new code first. Name the belief layer explicitly (`BeliefView` or `RetrievedContext`). Do the mass rename as a dedicated milestone with migration infrastructure.

## Implications for Current Work

The onboard classification refactor (this session) aligns naturally:
- Extraction creates **statements** (observations + classified sentences)
- The agent forms **beliefs** at query time via `retrieve()`
- Corrections are **statement-level** (user corrected a proposition)
- Author detection matters because agent-authored statements are less authoritative inputs to belief formation
- CORRECTION type stripped from onboard because corrections are a live belief-revision event, not a static statement property

## Key Insight

The system already has both layers. The retrieval pipeline IS the belief-forming function. The conceptual gap is naming and architecture: statements are stored, beliefs are computed. Making this explicit enables:
- Clearer API design (store statements, query beliefs)
- Better scoring (optimize for belief quality, not statement retrieval)
- Feedback loops (beliefs inform statement confidence updates)
- Temporal modeling (belief trajectories over session sequences)
