# Prior Art: Temporal Structure in Memory/Knowledge Systems

**Date:** 2026-04-11
**Context:** Exp 19 proposed "time as a structural dimension" but was never implemented. This document surveys prior art to inform design decisions.

## 1. Episodic Memory in LLM Agent Systems

### Zep / Graphiti (Rasmussen et al., 2025)

The most directly relevant prior art. Zep's Graphiti engine implements a three-tier temporal knowledge graph:

- **Episode subgraph**: Raw events/messages with original timestamps (ground truth corpus)
- **Semantic entity subgraph**: Extracted entities and relations with 1024D embeddings
- **Community subgraph**: Inductively clustered entity communities

**Key temporal innovation -- bitemporal model:**
- Event Time (T): when a fact actually occurred
- Ingestion Time (T'): when the system learned about it
- Every edge stores four timestamps: t'_created, t'_expired, t_valid, t_invalid

**Edge invalidation/supersession:** When new info contradicts existing facts, an LLM compares edges for semantic conflicts. On conflict, the old edge's t_invalid is set to the new edge's t_valid. Old facts are invalidated, not deleted -- history is preserved.

**Retrieval:** Hybrid of cosine similarity, BM25 full-text search, and BFS graph traversal. No LLM calls during retrieval (fast path). Reranking uses RRF, MMR, or cross-encoder scoring.

**Backend:** Neo4j (also supports FalkorDB, Amazon Neptune, Kuzu). NOT SQLite.

**Performance:** 71.2% accuracy on LongMemEval (115K token conversations), 2.58s average latency, reduces context from 115K to 1.6K tokens.

**What they capture that we don't:**
- Bitemporal timestamps (event time vs ingestion time)
- Explicit edge validity intervals
- Automated supersession via LLM conflict detection
- Episode-to-entity traceability (bidirectional indices)

**Applicability to agentmemory:** The bitemporal model and edge invalidation are directly applicable. Our supersession.py already detects supersession but does not track validity intervals on edges. The Neo4j dependency is not applicable; we need this on SQLite. The three-tier architecture (episode/semantic/community) maps loosely to our raw-ingest/belief/graph structure.

Source: https://arxiv.org/html/2501.13956v1

### Mem0 (Chadha et al., 2025)

Mem0 extracts salient facts from message pairs and compares new facts against existing memories, choosing ADD, UPDATE, DELETE, or NOOP. Achieves 67.13% on LOCOMO with p95 search latency of 0.200s and ~1,764 tokens per conversation (vs 26,031 for full context).

**Temporal handling:** Mem0 does NOT model temporal structure explicitly. It performs fact-level deduplication and update detection but does not create temporal edges or track belief evolution over time. Time is used only for recency scoring.

**What they capture that we don't:** The four-operation (ADD/UPDATE/DELETE/NOOP) classification per incoming fact is cleaner than our current approach. But temporally, they are behind what Exp 19 proposed.

Source: https://arxiv.org/html/2504.19413v1

### MemGPT / Letta

Three-tier OS-inspired model: core memory (always in context, like RAM), archival memory (vector store, like disk), recall memory (conversation history). No explicit temporal edges between memories. Time is implicit in conversation ordering.

**What they capture that we don't:** Nothing temporal. Their innovation is the virtual memory management metaphor (paging context in and out), not temporal structure.

### MemMachine (2026)

Stores raw conversational episodes indexed at sentence level. Tags all episodes with timestamps and supports temporal filtering during search. Results sorted chronologically. The authors acknowledge this is "limited but valuable temporal reasoning" vs. dedicated temporal graphs.

**What they capture that we don't:** Sentence-level indexing of raw episodes (we do sentence-level extraction but discard the raw episode link). Their ground-truth preservation philosophy aligns with what we should do -- keep raw episodes alongside extracted beliefs.

Source: https://arxiv.org/html/2604.04853

### AgentMem (oxgeneral, 2025)

Single-SQLite-file memory system with temporal versioning and fact evolution chains. When facts change, old versions are archived and linked via "supersedes" relationships. Sub-millisecond query performance, cold starts under 5ms.

**What they capture that we don't:** Explicit supersedes chains stored in SQLite. This is the closest SQLite-based implementation of temporal belief evolution. Their approach validates that our proposed SUPERSEDES edges (Exp 19) are feasible at our scale.

Source: https://github.com/oxgeneral/agentmem

### Kim et al. (2024) -- Dynamic Human-like Memory Recall

Implements a unified consolidation function: `p_n(t) = [1 - exp(-r * e^(-t/g_n))] / [1 - e^(-1)]` where r = relevance, t = elapsed time, g_n = consolidation strength (updated with each recall). Memories recalled repeatedly over long periods are retained more strongly.

**What they capture that we don't:** Mathematical model for consolidation strength that increases with repeated retrieval. Our Thompson sampling captures usage feedback but not this specific consolidation-strengthening-over-time dynamic.

Source: https://arxiv.org/html/2404.00573

---

## 2. Temporal Knowledge Graphs (TKGs)

### Taxonomy (Survey: arxiv 2403.04782)

TKG methods fall into 10 categories. The most relevant for our scale:

**Translation-based:**
- **TTransE**: Concatenates time to relation vectors: score = ||h + r + tau - t||. Simple but effective.
- **HyTE**: Projects entities onto time-specific hyperplanes. Each timestamp gets its own hyperplane, enabling time-specific entity representations.
- **TA-TransE**: Uses LSTM to learn relation embeddings that encode temporal progression.

**Rotation-based:**
- **Tero**: Timestamps as rotation operators in complex space: h_tau = h . tau
- **ChronoR**: Both relations and timestamps function as rotation operators in k-dimensional space.

**Decomposition-based:**
- **DE-SimplE**: "Diachronic embeddings" -- time-dependent components multiply static embeddings by sigmoid-activated temporal functions.
- **TNTComplEx**: Complex-valued tensor decomposition with a temporal factor dimension.

**What they capture that we don't:**
- Time as a first-class dimension in embeddings, not just metadata
- Ability to answer temporal queries like "what was true at time T?" natively in the embedding space
- Temporal link prediction ("what will be true at T+1?")

**Applicability to agentmemory:** These methods are designed for large-scale KG completion (Wikidata, YAGO, ICEWS) with millions of triples. Most require GPU training. At our scale (10K-100K beliefs, SQLite, CPU-only), the full embedding approaches are overkill. However, two ideas are portable:

1. **Diachronic embeddings (DE-SimplE)**: Our HRR vectors could incorporate a time-dependent component. Instead of static HRR(belief), compute HRR(belief) * sigmoid(time_factor). This is cheap and fits our existing infrastructure.
2. **Validity intervals on edges**: Directly applicable. Every edge gets (t_valid, t_invalid). This is just two extra columns in SQLite.

Source: https://arxiv.org/html/2403.04782v1

### STAR-RAG (2025) -- Temporal RAG via Graph Summarization

Constructs "time-aligned rule graphs" that summarize recurring event patterns. Uses seeded personalized PageRank for retrieval, enforcing temporal proximity. Groups events into rule schemas with structural type labels.

**What they capture that we don't:** Pattern-level temporal reasoning (not just individual facts but recurring patterns). The rule-graph summarization could be useful for compressing our belief graph at scale.

Source: https://arxiv.org/html/2510.16715

---

## 3. Conversation Structure Modeling

### Rhetorical Structure Theory (RST) and eRST

RST represents text as a tree of rhetorically related discourse units (nucleus-satellite relationships). Enhanced RST (eRST, 2025) extends this to a signaled graph theory, allowing non-tree structures.

**Relation types relevant to memory:** Cause, Result, Condition, Concession, Elaboration, Restatement, Sequence, Contrast, Background, Evaluation.

### Segmented Discourse Representation Theory (SDRT)

SDRT models discourse as a set of labeled segments connected by rhetorical relations. Treats speech acts as anaphoric relations between utterances. Explicitly models temporal and causal ordering within dialogue.

**Key temporal relations in SDRT:**
- Narration (temporal progression)
- Background (temporal overlap)
- Explanation (causal, reverse temporal)
- Result (causal, forward temporal)
- Elaboration (temporal containment)
- Continuation (temporal sequence without causation)

### Dialogue Discourse Parsing (2024)

Recent work treats dialogue discourse parsing as a sequence-to-sequence generation task, jointly predicting links and relations. Discourse dependency graphs (not trees) capture the richer structure of multi-party dialogue.

**What they capture that we don't:**
- Explicit discourse relations between conversational turns (we treat turns as independent inputs)
- Causal/temporal ordering (Narration, Background, Explanation, Result)
- The distinction between nucleus (core) and satellite (supporting) content in a discourse unit

**Applicability to agentmemory:** We could classify edges between beliefs using a simplified discourse relation set. Instead of generic CITES/SUPPORTS/CONTRADICTS, use temporal-causal relations: CAUSES, RESULTS_FROM, ELABORATES, SUPERSEDES, NARRATES_AFTER. This would make the graph queryable for temporal-causal chains. The classification could piggyback on our existing LLM extraction step with minimal added cost.

Sources: https://direct.mit.edu/coli/article/51/1/23/124464, https://aclanthology.org/2024.sigdial-1.1.pdf

---

## 4. Episodic vs Semantic Memory (Cognitive Science)

### Tulving's Distinction

Endel Tulving (1972, refined 1983, 2002) proposed two memory systems:
- **Episodic memory**: Stores specific events with temporal-spatial context. "I had coffee with Sarah on Tuesday." Autonoetic consciousness -- the ability to mentally travel in time.
- **Semantic memory**: Stores general knowledge without contextual binding. "Coffee contains caffeine." Noetic consciousness -- knowing without re-experiencing.

Key properties of episodic memory that semantic lacks:
1. **Temporal context** -- when it happened
2. **Spatial context** -- where it happened
3. **Source information** -- how you learned it
4. **Emotional valence** -- how it felt
5. **Self-reference** -- the "I" was there

### Episodic-to-Semantic Consolidation

Repeated episodic experiences consolidate into semantic knowledge. "Every time I debug DuckDB, I need to check connection pooling" starts as episodic (specific debugging sessions) and becomes semantic (general rule). This is exactly the trajectory our beliefs should follow.

### "Memory in the Age of AI Agents" Survey (Dec 2025)

This comprehensive survey introduces several relevant concepts:

- **Temporal Semantic Memory (TSM)**: Models semantic time for point-wise memory and supports construction of "durative memory" -- temporally continuous, semantically related information consolidated into persistent entries.
- **Episodic-to-semantic consolidation** is described as the "primary mechanism of lifelong learning" -- continuous consolidation of episodic experience into semantic assets.
- **Memory evolution**: Integration through consolidation of redundant entries, conflict resolution, discarding low-utility information, and restructuring for efficient retrieval.

**What they capture that we don't:**
- Our system currently treats all beliefs as semantic (extracted facts). We do not preserve the episodic source context.
- We have no consolidation pipeline that explicitly transitions episodic observations into semantic beliefs.
- We do not model "durative memory" -- beliefs that span a time range rather than being point-in-time.

**Applicability:** The episodic-to-semantic pipeline is directly relevant. Our ingest pipeline could store raw conversation turns as episodic entries (with timestamps, session IDs, source attribution) and then extract beliefs from them. The episodic layer becomes the audit trail; the semantic layer is what gets retrieved. This is essentially what MemMachine and Zep both do.

Sources: https://arxiv.org/abs/2512.13564, https://pmc.ncbi.nlm.nih.gov/articles/PMC11449156/

---

## 5. Temporal Reasoning in Retrieval

### ChronoQA Benchmark (2025)

A benchmark for evaluating temporal reasoning in RAG systems, built from 300K+ news articles (2019-2024), with 5,176 questions covering:
- **Absolute temporal queries**: "What was X's role in March 2023?"
- **Aggregate temporal queries**: "How many times did Y happen between 2020 and 2022?"
- **Relative temporal queries**: "What happened before/after X?"

Current RAG systems "retrieve broadly across time rather than restricting to temporally relevant evidence," which degrades accuracy.

### EvoReasoner (2025)

Multi-hop temporal reasoning over evolving knowledge graphs. Integrates a noise-tolerant knowledge graph evolution method (EvoKG) with temporal reasoning algorithms. Addresses queries about knowledge that has changed over time.

### Temporal RAG Limitations (current state of the art)

The field consensus is that existing RAG systems handle temporal queries poorly:
- They do not adapt search strategies to the evolving nature of information
- They fail to distinguish between "currently true" and "was true at time T"
- They treat all retrieved documents as equally temporally valid

**What they capture that we don't:**
- The ability to query "what was believed at time T?" (our beliefs have created_at but no validity windows)
- Temporal filtering during retrieval (we do recency decay but not temporal windowing)
- Distinction between "currently true" and "historically true"

**Applicability:** At minimum, we should support:
1. `valid_from` / `valid_until` on beliefs (nullable -- open-ended validity by default)
2. A retrieval mode that filters by temporal window: "beliefs valid at time T"
3. A "belief history" query: "show me the evolution of beliefs about topic X"

These are all implementable in SQLite with indexed timestamp columns. No exotic infrastructure needed.

Sources: https://www.nature.com/articles/s41597-025-06098-y, https://arxiv.org/html/2509.15464v1

---

## Summary: What's Missing from Agentmemory

| Capability | Who Has It | Effort to Add | Priority |
|---|---|---|---|
| Bitemporal timestamps (event time + ingestion time) | Zep/Graphiti | Low (2 columns) | High |
| Edge validity intervals (t_valid, t_invalid) | Zep, AgentMem | Low (2 columns per edge) | High |
| Supersedes chains with historical preservation | Zep, AgentMem | Medium (we have supersession.py, need persistence) | High |
| Episodic layer (raw turns with timestamps) | MemMachine, Zep | Medium (new table + ingest changes) | High |
| Episodic-to-semantic consolidation pipeline | Kim et al., survey | Medium (new pipeline stage) | Medium |
| Temporal-causal edge types (CAUSES, ELABORATES, etc.) | SDRT/RST research | Medium (classification changes) | Medium |
| Diachronic HRR embeddings (time-dependent vectors) | DE-SimplE concept | Low (multiply HRR by time factor) | Medium |
| Temporal retrieval windowing ("beliefs valid at time T") | ChronoQA benchmark | Low (WHERE clause) | Medium |
| Belief history queries ("evolution of topic X") | EvoReasoner | Low (query, not infrastructure) | Low |
| Durative memory (beliefs spanning time ranges) | TSM concept | Medium (schema change) | Low |
| Community detection / clustering | Zep | High (new algorithm) | Low |

## Recommended Implementation Order

1. **Add bitemporal columns to beliefs table**: `event_time` (when the fact is about) and `ingested_at` (when we learned it). Plus `valid_from` / `valid_until` (nullable). Four columns, minimal schema change. This unlocks temporal windowing in retrieval immediately.

2. **Persist supersession as edge validity**: When supersession.py detects a replacement, set `valid_until` on the old belief and `valid_from` on the new one. Link them with a SUPERSEDES edge. History is preserved, not deleted.

3. **Add episodic layer**: Store raw conversation turns in a separate `episodes` table with session_id, timestamp, speaker, raw_text. Link beliefs to their source episodes via `episode_id` foreign key. This provides audit trail and enables episodic retrieval.

4. **Temporal-aware retrieval**: Add a `temporal_window` parameter to search that filters beliefs by validity interval. Default behavior unchanged (retrieve currently-valid beliefs). Optional mode: retrieve beliefs valid at arbitrary time T.

5. **Diachronic HRR**: Multiply HRR vectors by a time-dependent sigmoid factor during retrieval scoring. Beliefs about recent events get slight boost in embedding similarity. Low cost, piggybacks on existing HRR infrastructure.

All of these are SQLite-compatible, require no GPU, and should work at 10K-100K belief scale with sub-second latency.
