# Agentic Memory for LLMs: Research Survey and Project Plan

**Date:** 2026-04-09
**Status:** Draft -- claims require ongoing verification
**Methodology:** All claims cite sources. Unverified or self-reported claims are labeled as such.

---

## 1. Problem Statement

LLMs have no persistent memory across sessions. The context window is the only "memory" available, and it is finite, expensive, and ephemeral. The field has produced dozens of systems claiming to solve this, but:

- Vendor benchmarks are unreliable (documented cases of misimplemented baselines)
- LLM-as-judge evaluation has 30%+ bias from position/length effects
- A simple filesystem with grep achieves 74% on the most-used benchmark (LoCoMo)
- No single benchmark tests the full memory lifecycle
- Multi-hop conflict resolution tops out at 7% accuracy across all tested methods

This project aims to build a rigorous, cross-model agentic memory system and evaluate it honestly.

---

## 2. Landscape: Major Systems

### 2.1 MemGPT / Letta

- **Architecture:** OS-inspired virtual memory. Core (in-context), Recall (conversation history), Archival (long-term storage). Agent manages its own context window.
- **Performance:** 74.0% LoCoMo (filesystem-only), ~83.2% (full system)
- **Key finding:** A simple filesystem may be all you need. LLMs are well-trained on file operations from coding data.
- **Paper:** Packer et al., arXiv:2310.08560 (2023)
- **Source:** [Letta benchmarking blog](https://www.letta.com/blog/benchmarking-ai-agent-memory)

### 2.2 Mem0

- **Architecture:** Hybrid graph + vector + key-value store. Automatic extraction, consolidation, retrieval with decay.
- **Performance (self-reported):** ~66% LoCoMo F1. Claims 26% improvement over OpenAI Memory, 91% lower p95 latency.
- **Performance (independent):** ~58% LoCoMo. Letta and Zep both reported they could not reproduce Mem0's competitor baselines. Mem0 did not respond to requests for clarification.
- **Credibility concern:** Documented benchmark dispute. Both Letta and Zep scored ~10% higher than Mem0 reported for them. Discussed on HN under "AI Startup Caught Cheating on Benchmark Papers."
- **Paper:** Chhikara et al., arXiv:2504.19413, ECAI 2025
- **Sources:** [Mem0 paper](https://arxiv.org/abs/2504.19413), [Letta rebuttal](https://www.letta.com/blog/benchmarking-ai-agent-memory), [Letta GitHub issue #3115](https://github.com/letta-ai/letta/issues/3115)

### 2.3 Zep (Graphiti)

- **Architecture:** Temporal knowledge graph. Three subgraphs: episode, semantic entity, community. Facts carry validity windows. Hybrid graph traversal + semantic embedding search.
- **Performance:** DMR 94.8% (gpt-4-turbo), 98.2% (gpt-4o-mini). LoCoMo ~85%. Up to 18.5% improvement on LongMemEval.
- **Paper:** Rasmussen, arXiv:2501.13956 (2025)
- **Source:** [Zep SOTA blog](https://blog.getzep.com/state-of-the-art-agent-memory/)

### 2.4 Microsoft GraphRAG

- **Architecture:** LLM-extracted knowledge graph, Leiden community clustering, hierarchical community summaries. Local and global search modes.
- **What was actually proved:** For global sensemaking queries over 1M+ token datasets, GraphRAG outperforms naive RAG on comprehensiveness and diversity (~70-80% win rate).
- **What was NOT proved:** Superiority for local fact retrieval, cost-effectiveness (indexing cost: $33K for large datasets in 2024), generalizability beyond query-focused summarization.
- **Independent critique:** When LLM-as-judge evaluation bias was corrected (position, length, trial), reported performance gains "dramatically shrunk" to below 10% win rate differentials. NaiveRAG slightly outperformed in some corrected evaluations.
- **Paper:** Edge et al., arXiv:2404.16130 (2024)
- **Sources:** [GraphRAG paper](https://arxiv.org/abs/2404.16130), [Evaluation bias paper](https://arxiv.org/html/2506.06331v1), [RAG vs GraphRAG systematic evaluation](https://arxiv.org/html/2502.11371v2)

### 2.5 LightRAG

- **Architecture:** Graph-enhanced text indexing with dual-level retrieval. Eliminates expensive community clustering. Supports incremental updates.
- **Performance:** Claims 90% cost reduction vs GraphRAG, 30% faster queries. Outperforms NaiveRAG, GraphRAG across multiple domains.
- **Caveat:** Performance advantage shrinks or reverses when LLM-as-judge bias is corrected.
- **Paper:** Guo et al., arXiv:2410.05779, EMNLP 2025

### 2.6 Other Notable Systems

| System | Architecture | LoCoMo | Key Differentiator |
|--------|-------------|--------|-------------------|
| EverMemOS | MemCells with episode+narrative+facts+foresight | 92.3% | Highest reported score (cloud LLM required, closed source) |
| Hindsight | Evidence vs beliefs vs derived summaries | 89.6% | Multi-channel retrieval, biomimetic |
| HippoRAG | Neurobiological (hippocampal indexing + PPR) | N/A | 20% improvement on multi-hop QA, 10-20x cheaper than iterative retrieval |
| A-MEM | Zettelkasten-style note network | N/A | Dynamic LLM-generated links between notes |
| Supermemory | Vector graph engine, ontology-aware edges | ~70% | MemoryBench cross-system benchmark framework |
| SuperLocalMemory | Local-first, Bayesian trust scoring | 74.8% (Mode A) | Zero cloud dependency, 60.4% zero-LLM mode |
| MAGMA | Multi-graph (semantic, temporal, causal, entity) | N/A | Policy-guided traversal for query-adaptive retrieval |
| Cognee | ECL pipeline, 38+ source connectors | N/A | Enterprise focus, 70+ companies |
| LangMem | Episodic + procedural + semantic toolkit | N/A | Framework-agnostic SDK, not benchmarked system |

### 2.7 Convergent Architecture (from lhl/agentic-memory analysis)

The lhl/agentic-memory repo analyzed 35+ papers and 14+ community systems and found convergence on a six-tier architecture:

1. **Source of truth** (append-only): transcripts, logs, resources
2. **Derived retrievable corpus**: sanitized chunks + indices
3. **Durable typed memory entries**: facts, preferences, decisions, tasks (gated, reversible)
4. **Structured filing**: entities, relations (graph + aliases + evidence pointers)
5. **Curated always-loaded context**: small identity + "what's hot" (budgeted)
6. **Maintenance + evaluation**: consolidation jobs, benchmarks, telemetry

Key insight: "The biggest differentiator is not vector DB vs SQLite -- it is write correctness and governance: provenance, write gates, conflict handling, reversibility."

**Source:** [lhl/agentic-memory ANALYSIS.md](https://github.com/lhl/agentic-memory/blob/main/ANALYSIS.md)

---

## 3. Benchmarks and Evaluation

### 3.1 Available Benchmarks

| Benchmark | What It Tests | Scale | Limitation |
|-----------|--------------|-------|-----------|
| **LoCoMo** | Long multi-session conversational recall | 32 sessions, ~600 turns, 81 QA pairs | Small QA set, mostly single-hop |
| **LongMemEval** | 5 memory abilities (extraction, reasoning, temporal, updates, abstention) | 500 questions, scalable to 1.5M tokens | User-AI only, not multi-agent |
| **MemoryAgentBench** | Accurate retrieval, test-time learning, long-range understanding, selective forgetting | Multi-turn incremental format | Multi-hop conflict resolution tops at 7% |
| **MemBench** | Factual vs reflective memory, participation vs observation | Effectiveness + efficiency + capacity | ACL 2025, less widely adopted |
| **LifeBench** | Long-horizon multi-source personalized agents | Full simulated year of data | SOTA reaches only 55.2% |
| **AMA-Bench** | Long-horizon memory in agentic applications | Real + synthetic trajectories | GPT 5.2 achieves only 72.26% |
| **DMR** | Single-turn fact retrieval from multi-session conversations | 500 conversations | Too simple, does not test reasoning |
| **LoCoMo-Plus** | Cognitive memory: latent constraints, causal consistency | Beyond factual recall | Newer, less adoption |
| **StructMemEval** | Structure formation (trees, state, ledgers) | Hint vs no-hint diagnostics | Vector stores fundamentally fail at state tracking |

**Sources:** [LoCoMo](https://snap-research.github.io/locomo/), [LongMemEval](https://arxiv.org/abs/2410.10813), [MemoryAgentBench](https://arxiv.org/abs/2507.05257), [LifeBench](https://arxiv.org/abs/2603.03781), [AMA-Bench](https://arxiv.org/abs/2602.22769), [Memory in the LLM Era](https://arxiv.org/html/2604.01707)

### 3.2 Approximate LoCoMo Leaderboard (early 2026)

| System | Score | Notes |
|--------|-------|-------|
| EverMemOS | 92.3% | Cloud LLM, closed source |
| Hindsight | 89.6% | Cloud LLM |
| Zep | ~85% | Temporal KG |
| Letta/MemGPT | ~83.2% | OS-style memory |
| SuperLocalMemory Mode C | 87.7% | Uses LLM for synthesis |
| SuperLocalMemory Mode A | 74.8% | Zero cloud |
| Letta (filesystem only) | 74.0% | gpt-4o-mini, no special memory |
| Supermemory | ~70% | Vector graph engine |
| Mem0 (self-reported) | ~66% | Hybrid store |
| Mem0 (independent) | ~58% | Independent evaluation |

**Caveat:** These numbers are NOT directly comparable. Each was measured under different conditions, different LLM backends, and potentially different LoCoMo configurations. The Mem0/Letta/Zep dispute demonstrates this problem concretely.

**Source:** [DEV Community comparison](https://dev.to/varun_pratapbhardwaj_b13/5-ai-agent-memory-systems-compared-mem0-zep-letta-supermemory-superlocalmemory-2026-benchmark-59p3)

### 3.3 The Evaluation Credibility Crisis

The field has a serious problem with benchmark integrity:

1. **Vendor self-reporting is unreliable.** Mem0 published competitor results that neither Letta nor Zep could reproduce. Mem0 did not respond to clarification requests.

2. **LLM-as-judge is biased.** The GraphRAG evaluation bias paper found:
   - Position bias: reversing answer order swings win rates 30%+
   - Length bias: 25-token difference in 200-token answers creates 50%+ win rate gaps
   - Trial bias: repeated runs produce contradictory conclusions
   - When corrected, LightRAG's advantage over NaiveRAG **reversed**

3. **Benchmarks are too narrow.** A filesystem with grep hits 74% on LoCoMo. LoCoMo has only 81 QA pairs. DMR tests only single-turn fact retrieval.

4. **No benchmark tests the full lifecycle.** Ingestion, consolidation, conflict resolution, forgetting, retrieval, and generation quality in a realistic multi-session, multi-modality setting -- no single benchmark covers all of this.

5. **Cost is rarely reported alongside accuracy.** GraphRAG: $33K indexing for large datasets. An agent scoring 5% higher but costing 10x more may be worse for real use.

**Sources:** [GraphRAG evaluation bias](https://arxiv.org/html/2506.06331v1), [Letta rebuttal](https://www.letta.com/blog/benchmarking-ai-agent-memory), [Benchmark gaming explained](https://www.mindstudio.ai/blog/benchmark-gaming-ai-inflated-scores-explained), [BenchmarkQED (Microsoft)](https://www.microsoft.com/en-us/research/blog/benchmarkqed-automated-benchmarking-of-rag-systems/)

---

## 4. Metrics Taxonomy

### 4.1 Retrieval Quality
| Metric | What It Measures |
|--------|-----------------|
| Recall@K | Fraction of relevant items in top-K results |
| Precision@K | Fraction of top-K results that are relevant |
| F1 | Harmonic mean of precision and recall |
| MRR | How high the first correct result ranks |
| nDCG@K | Whether highly relevant items rank above somewhat relevant ones |
| Hit Rate | Whether any relevant item appears in top-K (binary) |

### 4.2 Generation Quality
| Metric | What It Measures | Caveat |
|--------|-----------------|--------|
| LLM-as-Judge accuracy | Correctness vs golden answer | Position/length/trial bias documented |
| Faithfulness | Answer grounded in retrieved context | Requires NLI or LLM judge |
| Hallucination rate | Frequency of unsupported claims | Two types: factuality vs faithfulness |
| BLEU/ROUGE | Token overlap with reference | Poor for semantic evaluation |
| Exact Match | Prediction matches ground truth exactly | Too strict for open-ended answers |

### 4.3 Memory-Specific
| Metric | What It Measures |
|--------|-----------------|
| Knowledge update accuracy | Correctly reflects superseded information |
| Temporal reasoning accuracy | Correctly orders events and answers "when" questions |
| Abstention rate | Correctly refuses when information unavailable |
| Contradiction detection | Identifies and resolves conflicting memories |
| Selective forgetting | Appropriately removes information on request |
| Cross-session coherence | Consistency across sessions |

### 4.4 Operational
| Metric | What It Measures |
|--------|-----------------|
| p50/p95/p99 latency | Response time for memory operations |
| Token cost per operation | Total tokens consumed |
| Indexing/ingestion cost | Upfront cost to build memory structures |
| Storage overhead | Disk/memory per unit of stored information |
| Incremental update cost | Cost to add new information without full reindex |

---

## 5. Prior Work: Citation-Backbone Graph (GSD Spike)

### 5.1 What Was Built

A prototype graph memory system using SQLite with in-memory adjacency list. ~1,900 lines of TypeScript across 8 modules. Tested on alpha-seek project data (577 nodes, 742 edges).

**Architecture:**
- Nodes: decisions, knowledge entries, milestones from GSD database
- Edges: extracted via regex parsing of D###/M### references (zero LLM cost)
- Edge types: CITES, DECIDED_IN, RELATES_TO, SOURCED_FROM, SUPERSEDES, CONCEPT_LINK
- Retrieval: text search seeding + BFS 2-hop with hub damping + cluster diversity filtering
- Pruning: edge decay, hub damping, node cap, supersession

**Source:** `/Users/thelorax/projects/.gsd/workflows/spikes/260406-1-associative-memory-for-gsd-please-explor/`

### 5.2 What Was Claimed vs What Was Measured

| Claim | Source of Claim | Reality |
|-------|----------------|---------|
| "7x precision improvement" | Spike VALIDATION.md | Measured prototype vs strawman baseline (flat retrieval with zero task awareness, scoring 0.000 on 4/5 scenarios). Not validated against independent benchmark or real deployment. |
| "99% token reduction" | Spike VALIDATION.md | Compares ~700 tokens (graph) vs ~54K (full KNOWLEDGE.md dump). But the actual flat retrieval comparison uses 1,247 tokens -- making the real reduction ~44%. |
| "Sub-ms latency, 700x under budget" | Spike COMPARISON.md | Measured on in-memory graph with 577 nodes. Plausible at this scale but untested at larger scales. |
| "Wins all 5/10 scenarios" | Spike COMPARISON.md | The flat baseline returns the same 15 nodes regardless of task (zero task awareness). Even basic keyword filtering would beat it. |
| "Manually labeled relevant sets" | Spike TESTING-STRATEGY.md | Labeled by the same agent that built the prototype, not by a human. |

### 5.3 What Was NOT Done

- Tests 1-6 from TESTING-STRATEGY.md were proposed but never executed
- No evaluation against any standard benchmark (LoCoMo, LongMemEval, etc.)
- No independent validation of retrieval quality claims
- No real-world deployment or production measurement
- No comparison against any existing memory system

### 5.4 What Is Actually Valuable

Despite the inflated claims, the architecture has genuine strengths:

- **Zero-LLM edge extraction** via citation parsing is cost-effective and deterministic
- **Hub damping** addresses a real problem (gravitational centers dominating retrieval)
- **Provenance chains** via citation edges are structurally queryable
- **In-memory adjacency list** is fast at small scale
- **The TESTING-STRATEGY.md is honest** -- it explicitly states what the graph will NOT fix (reasoning compliance, bad seed selection) and defines a clear validation bar ("graph must be CLEARLY better for at least 4 of 5 real scenarios")

### 5.5 Comparison to MemPalace

The lhl/agentic-memory repo includes a [detailed analysis of MemPalace](https://github.com/lhl/agentic-memory/blob/main/ANALYSIS-mempalace.md) which shares conceptual DNA with this prototype:

| Dimension | GSD Citation Graph | MemPalace | Notes |
|-----------|-------------------|-----------|-------|
| Graph traversal | Real BFS with hub damping, cluster diversity | Flat triple lookup, no multi-hop | GSD's traversal is structurally richer |
| Edge extraction | Zero-LLM regex parsing | Zero-LLM regex classification | Both avoid LLM cost; GSD extracts typed citation edges, MemPalace classifies content categories |
| Retrieval | Task-seeded BFS + text search | Single ChromaDB vector query | GSD seeds from task context and walks the graph; MemPalace does one vector similarity pass |
| Provenance | Structural citation chains (D098 --CITES--> D097) | None | Queryable provenance is a genuine differentiator |
| Decay/forgetting | Edge decay, node caps, pruning (designed) | None | Both lack principled forgetting; GSD's heuristic decay is at least a mechanism |
| Memory stages | STM buffer with entropy decay + LTM promotion via anchor proximity (designed, not implemented) | Single-layer ChromaDB, no staging | GSD's two-stage design aligns with academic consensus (TiMem, HiMem, EverMemOS). MemPalace's L0-L3 "layers" are just query scopes on one store, not consolidation stages. Neither has been validated in production. |
| Seed prioritization | Highest-degree anchor nodes injected first; task-seeded BFS ensures topologically important context surfaces | "Importance" metadata field (manually set), top-15 by score | GSD derives importance from graph topology (structural); MemPalace relies on manually assigned metadata (arbitrary). Functionally similar intent -- get the most important context in first -- but GSD's approach is data-driven. |
| Organization | Anchor clusters derived from graph topology (emergent) | Spatial metaphor: wings/rooms/halls (manually assigned) | MemPalace's spatial metaphor is human-legible but cosmetic -- lhl analysis confirms halls are "metadata strings only, not used in retrieval ranking" and the "+34% retrieval boost" is just metadata filtering. GSD's anchor clusters emerge from actual citation structure. |
| Cross-model support | GSD-specific | MCP server (Claude, ChatGPT, etc.) | MemPalace's MCP interface is a genuine advantage for cross-model use |
| Claims vs code | Inflated but self-aware (TESTING-STRATEGY.md explicitly states what the graph will NOT fix) | Multiple false claims documented ("zero information loss" is lossy -- 12.4pp quality drop; "contradiction detection" does not exist in code) | GSD's honesty about limits is a methodological strength |
| Benchmark validation | None (prototype only, self-benchmarked against strawman baseline) | LoCoMo 60.3% (mediocre); headline 96.6% measures ChromaDB's embedding model, not palace architecture | Neither has credible independent validation |
| Implementation status | ~1,900 LOC TypeScript prototype, never deployed | Shipped Python package with MCP server, ~22K drawers tested | MemPalace ships and runs; GSD prototype was never integrated. STM design was proposed but never built. |

**lhl verdict on MemPalace:** NOT promoted to main comparison table due to claims-vs-code gap.

**Honest assessment of both:** Architecturally, the GSD citation graph is more sophisticated for retrieval quality (real graph traversal, provenance chains, two-stage memory design, topology-derived importance). MemPalace is more mature operationally (shipping product, cross-model MCP support, mining pipeline). Neither has been rigorously validated against standard benchmarks. The GSD prototype's STM/LTM staging, while better-designed than MemPalace's single layer, was never implemented -- design quality without execution is worth less than a simpler design that runs.

---

## 6. What Metrics We Need to Beat

Based on the landscape analysis, here are the honest bars:

### 6.1 Minimum Credibility Threshold

| Benchmark | Minimum Score | Why This Bar |
|-----------|--------------|-------------|
| LoCoMo | >74% | Below this, a filesystem with grep beats you (Letta's finding) |
| LongMemEval | >50% across all 5 dimensions | Below this, commercial chat assistants match you |
| MemoryAgentBench | >60% single-hop, any improvement on 7% multi-hop | Multi-hop conflict resolution is the hardest unsolved problem |

### 6.2 Competitive Threshold

| Benchmark | Target Score | Current SOTA |
|-----------|-------------|-------------|
| LoCoMo | >85% | EverMemOS 92.3% (closed source) |
| LongMemEval | >70% across all dimensions | Zep claims 18.5% improvement over baselines |
| LifeBench | >55.2% | Current SOTA |
| AMA-Bench | >72.26% | GPT 5.2 |

### 6.3 Operational Requirements

| Metric | Target | Rationale |
|--------|--------|-----------|
| p95 latency | <500ms | Mem0 claims ~100ms; interactive use requires sub-second |
| Token cost per retrieval | <2,000 tokens | Must leave >90% of context window free |
| Indexing cost | <$1/1000 memories | GraphRAG's $33K is disqualifying for most use cases |
| Zero-LLM mode accuracy | >60% | SuperLocalMemory sets this bar for local-only operation |
| Cross-model support | Claude, ChatGPT, Gemini minimum | Via MCP or model-agnostic API |

---

## 7. Evaluation Methodology

### 7.1 Principles

1. **Never self-report without independent reproduction.** Every claimed result must include code to reproduce it.
2. **Always include naive baselines.** Full-context-window and filesystem-with-grep baselines are mandatory.
3. **Control for LLM-as-judge bias.** Position exchange, length alignment, 25+ trials with median reporting per the GraphRAG evaluation bias paper.
4. **Report costs alongside accuracy.** Latency, token consumption, and indexing cost in every results table.
5. **Separate retrieval from generation.** A system can have great retrieval and terrible generation (or vice versa). Report both independently.
6. **Test conflict resolution and forgetting.** If a benchmark does not test knowledge updates, it is insufficient.
7. **Stage-wise instrumentation.** Measure indexing, retrieval, and reading separately (per LongMemEval's pipeline decomposition).
8. **Human-labeled ground truth for retrieval quality.** Agent-labeled "relevant sets" are not acceptable as the only validation.

### 7.2 Benchmark Suite

Minimum evaluation battery:

| Benchmark | What It Covers | Implementation |
|-----------|---------------|----------------|
| LoCoMo | Conversational recall, temporal grounding | Run against published dataset with identical conditions to Letta/Zep |
| LongMemEval | 5-dimension memory evaluation | Use their scalable chat history generation |
| MemoryAgentBench | Conflict resolution, forgetting | Multi-turn incremental format |
| Filesystem baseline | Cost of complexity | Letta's filesystem-with-grep approach |
| Full-context baseline | Is memory even needed? | Stuff everything into context window |

### 7.3 Reporting Standards

Every results table must include:
- Exact model and version used
- Exact benchmark version and configuration
- Cost per query (tokens + dollars)
- Latency percentiles (p50, p95)
- Code to reproduce (public repo)
- Comparison to naive baselines
- Confidence intervals or statistical significance tests where sample size permits

---

## 8. Research Plan

### Phase 0: Foundation (Week 1-2)

**Goal:** Reproducible evaluation harness before writing any memory code.

1. Set up benchmark runner for LoCoMo, LongMemEval, MemoryAgentBench
2. Implement filesystem baseline (Letta's approach)
3. Implement full-context baseline
4. Validate that our baselines reproduce published numbers (within tolerance)
5. Establish LLM-as-judge with bias controls (position exchange, length alignment, multi-trial)

**Exit criteria:** Baseline numbers within 5% of published results for at least 2 benchmarks.

### Phase 1: Core Architecture (Week 3-5)

**Goal:** Minimum viable memory system with honest measurement.

Design decisions to make (informed by landscape):
- Storage backend: SQLite (proven at small scale, zero dependencies) vs ChromaDB (vector search built-in) vs hybrid
- Graph structure: citation-backbone (proven in prototype) vs temporal KG (Zep's approach) vs multi-graph (MAGMA)
- Write path: zero-LLM extraction (proven cheap, limited) vs LLM-enriched (expensive, more semantic) vs hybrid
- Retrieval: BFS + text search (proven in prototype) vs hybrid vector + graph vs tiered progressive loading
- Cross-model interface: MCP server (works with Claude, ChatGPT, etc.)

**Exit criteria:** System that beats filesystem baseline on at least 2 of 3 benchmarks.

### Phase 2: Differentiation (Week 6-8)

**Goal:** Address the hardest unsolved problems.

Priority research questions (ordered by impact):
1. **Conflict resolution** -- current SOTA is 7%. Can citation-backbone provenance chains help?
2. **Temporal reasoning** -- Zep's validity windows vs our approach
3. **Principled forgetting** -- beyond heuristic decay
4. **Write gating** -- preventing memory poisoning (MINJA attack surface)
5. **Cost-quality frontier** -- can we match cloud-LLM systems at zero-LLM cost?

**Exit criteria:** Measurable improvement over Phase 1 on at least one hard dimension (conflict resolution, temporal reasoning, or forgetting).

### Phase 3: Validation and Honesty (Week 9-10)

**Goal:** Rigorous validation of all claims.

1. Independent reproduction of all benchmark results
2. Human-labeled ground truth for retrieval quality (not agent-labeled)
3. Ablation studies: what does each component contribute?
4. Cost-accuracy tradeoff analysis
5. Failure mode documentation (what doesn't work and why)
6. Write-up with full methodology, code, and data

**Exit criteria:** Every claim in the paper/README is backed by reproducible evidence. Every known limitation is documented.

---

## 9. Open Questions

1. **Is graph memory actually better than filesystem + search?** Letta's 74% with grep is a sobering baseline. The answer might be "only for specific query types" (multi-hop, temporal, thematic).

2. **Can zero-LLM extraction compete with LLM-enriched extraction?** The cost difference is 100x+. If zero-LLM gets within 10% accuracy, it may be the better choice for most deployments.

3. **What is the right forgetting strategy?** No system has principled forgetting. Heuristic decay is the state of the art. This is a genuine research opportunity.

4. **How do we handle multi-agent memory consistency?** Identified as "the most pressing open challenge" in the survey literature. No good solution exists.

5. **Is LoCoMo a meaningful benchmark?** With only 81 QA pairs and a filesystem hitting 74%, it may not differentiate architectures. We may need to propose a better benchmark.

---

## 10. Key References

### Surveys
- Zhang et al., "Survey on Memory Mechanisms for LLM Agents," arXiv:2404.13501, ACM TOIS (2024)
- Hu et al., "Memory in the Age of AI Agents," arXiv:2512.13564 (2025) -- 47 authors, most comprehensive
- Yang et al., "Graph-centric lifecycle taxonomy," arXiv:2602.05665 (2026)
- "Memory in the LLM Era," arXiv:2604.01707 (2026) -- modular architectures, unified framework

### Benchmarks
- LoCoMo: Maharana et al., ACL 2024, [snap-research.github.io/locomo](https://snap-research.github.io/locomo/)
- LongMemEval: Wu et al., ICLR 2025, arXiv:2410.10813
- MemoryAgentBench: ICLR 2026, arXiv:2507.05257
- LifeBench: arXiv:2603.03781 (2026)
- AMA-Bench: arXiv:2602.22769 (2026)

### Systems
- MemGPT: Packer et al., arXiv:2310.08560 (2023)
- Mem0: Chhikara et al., arXiv:2504.19413, ECAI 2025
- Zep/Graphiti: Rasmussen, arXiv:2501.13956 (2025)
- GraphRAG: Edge et al., arXiv:2404.16130 (2024)
- LightRAG: Guo et al., arXiv:2410.05779, EMNLP 2025
- HippoRAG: Gutierrez et al., arXiv:2405.14831, NeurIPS 2024
- A-MEM: Xu et al., arXiv:2502.12110 (2025)

### Evaluation Methodology
- GraphRAG evaluation bias: arXiv:2506.06331 (2025)
- Letta benchmark rebuttal: [letta.com/blog/benchmarking-ai-agent-memory](https://www.letta.com/blog/benchmarking-ai-agent-memory)
- BenchmarkQED (Microsoft): [microsoft.com/research/blog/benchmarkqed](https://www.microsoft.com/en-us/research/blog/benchmarkqed-automated-benchmarking-of-rag-systems/)

### Security
- MINJA (query-only memory injection): arXiv:2503.03704
- Memory poisoning attack & defense: arXiv:2601.05504

### Research Repository
- lhl/agentic-memory: [github.com/lhl/agentic-memory](https://github.com/lhl/agentic-memory) -- 35+ papers, 14+ systems, 6 benchmarks analyzed
