# Wonder: Multi-Hop Conflict Resolution via Existing Mechanisms

## The Question

agentmemory was built from scratch with typed beliefs, SUPERSEDES edges,
HRR holographic traversal, and BFS multi-hop. These are exactly the
mechanisms needed for multi-hop conflict resolution. Why does it score
6% on MAB FactConsolidation MH 262K (field ceiling: 7%)? What changes
would close the gap, and would those changes improve real-world UX?

## Convergent Finding (reason + wonder)

Both /mem:reason and /mem:wonder converge on the same diagnosis:

**The retrieval and traversal mechanisms exist. The ingestion pipeline
does not create the structured edges that would let them fire.**

Evidence:
- SUPERSEDES edges exist and work correctly (superseded beliefs score 0.01)
- BFS gives 100% completeness at 2-hop depth (vs 33% for HRR)
- HRR can traverse SUPERSEDES edges to surface related beliefs
- Temporal decay correctly suppresses old beliefs when timestamps differ
- But: FactConsolidation facts arrive as opaque text chunks, not as
  structured triples. No entity-level edges are created. No serial-number
  based supersession fires. All facts get identical timestamps.

## The Real-World UX Problem

This is not just a benchmark issue. The same failure pattern appears when:

1. **User corrects a preference:** "Use approach B not A." If the system
   stores this as flat text without creating a SUPERSEDES edge from B to A,
   the next retrieval might surface both A and B, wasting tokens and
   confusing the reader.

2. **Knowledge evolves across sessions:** "The API endpoint changed from
   /v1/users to /v2/users." Without structured extraction of (API, endpoint,
   /v2/users) superseding (API, endpoint, /v1/users), both versions persist.

3. **Multi-step reasoning:** "What testing framework do we use for the
   module that handles authentication?" Requires: find auth module -> find
   its test framework. If conflicting beliefs exist about either hop,
   the answer may be wrong.

The benchmark is the measuring stick. The UX improvement is: fewer
correction loops, less token waste on superseded information, higher
first-attempt response quality.

## What the Codebase Shows (Explore Agent Trace)

### Current edge creation pipeline (during ingest_turn):

```
insert_belief()
  -> check_temporal_supersession()    [Jaccard >= 0.4, age gap >= 1hr]
  -> detect_relationships()           [CONTRADICTS/SUPPORTS/RELATES_TO]
  -> detect_gap_closure()             [IMPLEMENTS + SUPERSEDES]
  -> correction supersession          [if type=CORRECTION, keyword match]
```

### Why this misses FactConsolidation:

1. **No entity extraction.** "Abbiati plays basketball" and "Abbiati plays
   football" are stored as separate text blobs. The system doesn't know
   both are about "Abbiati" + "plays".

2. **Jaccard threshold too coarse.** Two facts about the same entity with
   different values may share only the entity name (1 word overlap in 5),
   below the 0.4 Jaccard threshold.

3. **1-hour minimum age gap.** All FactConsolidation facts are ingested
   within seconds. Temporal supersession never fires.

4. **No serial number parsing.** "Fact #198" and "Fact #12" both arrive
   as text. The serial numbers are invisible to the supersession logic.

### What DOES work:

- SUPERSEDES edges, once created, are correctly handled everywhere:
  FTS5 filters on `valid_to IS NULL`, BFS excludes superseded beliefs,
  scoring returns 0.01 for superseded beliefs.
- BFS traversal at depth=2 with max_nodes=20 works correctly.
- HRR single-hop vocabulary bridging works (8% unique contribution).

## Hypotheses from Research

### H1: HRR serial number encoding -- NOT VIABLE

Encoding serial numbers as additional binding vectors in HRR would require
three successive unbinding operations. Exp 26 showed two-hop HRR retrieval
scores 0.0 P@5 and 0.0 R@5 on 11/12 test cases. At dim=2048, the noise
floor kills multi-binding. Would need dim=16384+ which is unjustifiable.

### H2: SUPERSEDES chain traversal -- VIABLE, 90% implemented

The infrastructure exists. The gap is in the supersession *detector*, not
the *chain*. Fixes needed:
- Entity+property matching (not just Jaccard on full text)
- Serial number parsing for ordered data
- Remove the 1-hour age gap minimum for batch ingestion

### H3: HRR cleanup memory bias -- WRONG ABSTRACTION

Biasing cleanup memory by recency would degrade HRR's vocabulary-bridge
function (the one thing it does well) without enabling multi-hop. Scoring
already handles recency. Double-counting would harm retrieval quality.

### H4: Two-phase retrieve-then-filter -- VIABLE, already 90% implemented

The retrieval pipeline already does relevance-based selection followed by
scoring. The missing piece is a supersession-aware deduplication step:
if two returned beliefs have a SUPERSEDES relationship, drop the older one
before packing into the token budget. This is ~5 lines of code in
retrieve(), between the merge step and the scoring step.

## Prior Art (Wonder Agent 1)

No published system achieves >10% on multi-hop QA with explicit fact
conflicts at >100K token scale. This is genuinely unsolved.

Closest work:
- **BeliefBank** (Kassner et al., EMNLP 2021): MaxSAT-based consistency
  for belief stores. No multi-hop, but the conflict resolution approach
  (constraint solving) is relevant.
- **CluSTeR** (Li et al., EMNLP 2021): Multi-hop temporal QA decomposition.
  Assumes KG consistency (no conflicts).
- **Weighted HRR superposition** (novel, not published): Encode confidence
  into binding magnitude so retrieval implicitly favors current facts.
  Promising for single-hop, unlikely to help multi-hop.

## Proposed Feature: Structured Fact Extraction

### Design (general-purpose, not benchmark-specific)

New module: `src/agentmemory/triple_extraction.py`

```python
@dataclass
class FactTriple:
    entity: str
    property_name: str
    value: str
    serial: int | None    # For ordered data (e.g., FactConsolidation)
    source_belief_id: str
```

### Extraction pipeline (hybrid):

1. **Regex fast path:** For structured data with serial numbers.
   Zero cost, high precision on well-formatted input.
2. **LLM path (Haiku):** For natural language facts.
   ~$0.00002 per fact. Batched with existing classification.
3. **Fallthrough:** If neither matches, belief is stored as opaque
   text (current behavior). No regression.

### Integration with existing mechanisms:

1. After triple extraction, check for existing triples on same
   (entity, property). If found, call `store.supersede_belief()`
   with the older one. This creates the SUPERSEDES edge that
   makes the existing retrieval pipeline work correctly.

2. Create ABOUT_ENTITY edges from beliefs to entity nodes.
   This enables entity-level BFS traversal for multi-hop.

3. At query time, decompose multi-hop questions into sub-queries.
   For each hop, retrieve via entity lookup, resolve conflicts
   via SUPERSEDES chain, use resolved value as next hop's seed.

### UX improvements beyond benchmarks:

- **Token efficiency:** Superseded beliefs no longer waste budget tokens.
  If the API endpoint changed, only the current one is retrieved.
- **Response quality:** The reader sees the current state, not a mix
  of old and new. Fewer "but you said X" correction loops.
- **Correction convergence:** One correction propagates through
  SUPERSEDES chain. Dependent beliefs are automatically deprioritized.

## Experiment Plan

### Exp 1: Per-hop failure analysis (diagnostic, no code change)

For each of the 94 wrong MH answers, classify: did retrieval have the
hop-1 answer? The hop-2 answer? Both? Neither? This tells us whether
the bottleneck is retrieval or conflict resolution.

**Expected outcome:** "Neither" dominates (~70%), confirming FTS5 can't
chain hops. If "both found" is high, the bottleneck is the reader.

### Exp 2: Oracle hop-1 injection

Give the reader the correct hop-1 answer and only ask it to do hop-2.
If this scores ~60% (matching SH), the bottleneck is hop-1 chaining.

### Exp 3: Structured triple ingestion with SUPERSEDES chains

The main intervention. Parse facts into triples, create SUPERSEDES edges
based on serial numbers, decompose queries into sub-queries, resolve
each hop via SUPERSEDES chain walking.

**Required code changes:**
- New: `triple_extraction.py` (extraction + entity contradiction check)
- Modify: `ingest.py` (call triple extraction after classification)
- Modify: `store.py` (optionally include SUPERSEDES in expand_graph)
- Modify: `retrieval.py` (entity-based query expansion)
- Modify: `models.py` (ABOUT_ENTITY edge type)

**Success criteria:** >30% on MH 262K (5x improvement over 6%).
If >50%, competitive with long-context LLMs.

### Exp 4: HRR-chained retrieval (compare to BFS)

Use HRR forward traversal for each hop. Compare accuracy to BFS.
Expected: BFS wins (per Exp 26), but HRR might help on vocabulary
gaps where entity names differ between hops.

### Exp 5: Thompson sampling exploration (cheap, independent)

Run retrieval K=10 times with Thompson sampling stochasticity.
Take union, pick newest per (entity, property). Tests whether
exploration helps surface the correct fact from a noisy candidate set.

### Dependency graph:

```
Exp 1 (diagnostic) -> informs all others
  |
  +-> Exp 2 (oracle hop-1) -> if "neither" dominates
  |     |
  |     +-> Exp 3 (structured triples) -> the main intervention
  |           |
  |           +-> Exp 4 (HRR comparison)
  |
  +-> Exp 5 (Thompson sampling) -> independent, cheap
```

## Key Insight

The multi-hop conflict resolution problem is a **graph problem, not a
vector space problem** (Wonder Agent 2). HRR's single-hop vocabulary
bridging is valuable but cannot chain through conflicts. The correct
architecture uses the explicit edge table (SQLite) for conflict
resolution and the holographic space for vocabulary bridging. We already
have both. The missing piece is ingestion-time structure extraction
that creates the edges the graph needs.

## References

- BeliefBank (Kassner et al., EMNLP 2021) -- belief consistency via MaxSAT
- CluSTeR (Li et al., EMNLP 2021) -- multi-hop temporal QA decomposition
- TLogic (Liu et al., AAAI 2022) -- temporal logical rules for KG reasoning
- UKGE (Chen et al., AAAI 2019) -- confidence-aware KG embeddings
- Plate (2003) -- HRR foundational work
- Kleyko et al. (2022) -- VSA/hyperdimensional computing survey
- MemoryAgentBench (Hu et al., ICLR 2026) -- the benchmark
