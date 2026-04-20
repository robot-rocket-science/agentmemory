# Persistent Memory for LLM Agents

## Technical Project Summary

---

### Problem

LLM agents have no memory across conversations. Every session starts from zero. When a user corrects the agent, that correction is lost the moment the context window closes. There is no mechanism for an agent to learn from its mistakes, retain user preferences, or build up project-specific knowledge over time.

Existing approaches (RAG, vector databases) store text and retrieve by similarity. They don't distinguish between a fact and a correction, don't track confidence over time, and have no way to know whether retrieved information was actually useful.

---

### Approach

The system models agent memory as a **belief system**, not a document store. The core abstraction is the belief: a scored assertion with a confidence level, a type classification, and a temporal dimension.

The design follows a scientific method cycle:

1. **Observe**: Record what happens in conversations (user statements, corrections, outcomes)
2. **Believe**: Extract beliefs from observations, assign Bayesian priors based on type
3. **Test**: Retrieve beliefs in future sessions, track whether they were used, ignored, or harmful
4. **Revise**: Update confidence based on outcomes; beliefs that help get stronger, beliefs that don't get weaker

**Key design decisions:**

- **Bayesian confidence tracking** rather than flat scores. Different belief types start with different priors (user-stated requirements start high; inferred analysis starts lower). Confidence updates from evidence using conjugate priors.
- **Zero-LLM correction detection.** The system detects when a user corrects the agent without making an LLM call, using a multi-signal heuristic pipeline. This enables a feedback loop without expensive inference on every turn.
- **Multi-layer retrieval.** Keyword search alone misses ~31% of relevant beliefs (statements that share zero vocabulary with the query). The system uses a structural graph layer to bridge vocabulary gaps and recover those statements.
- **Locked beliefs.** User corrections and stated rules become non-negotiable constraints that can only be upgraded, never downgraded. This addresses a real failure mode: agents forgetting rules that users have explicitly stated.
- **Temporal decay with type awareness.** Beliefs decay at different rates depending on content type (procedural knowledge decays slower than incidental facts), and the decay rate itself scales with session activity.
- **Project isolation.** Each project gets its own database. No memory bleed across projects.

---

### Key Results

| Metric | Result | Notes |
|--------|--------|-------|
| **Benchmarks** | | |
| LoCoMo F1 (ACL 2024) | 66.1% | +14.5pp vs GPT-4o-turbo (51.6%); no embeddings |
| MAB Single-Hop (ICLR 2026) | 90% Opus | +45pp vs GPT-4o-mini (45%) |
| MAB Multi-Hop (ICLR 2026) | 60% Opus | 8.6x published ceiling of 7%; 35% chain-valid (reader-independent) |
| StructMemEval | 100% (14/14) | Vector stores fail at state tracking; temporal_sort fix |
| LongMemEval (ICLR 2025) | 59.0% | -1.6pp vs GPT-4o pipeline (60.6%); Opus judge (asterisk) |
| **Core Pipeline** | | |
| Correction detection accuracy | 92% | Zero-LLM pipeline, tested across five codebases |
| Vocabulary-gap retrieval | 99.5% recovery | 31% of beliefs unreachable by keyword search; structural graph layer recovers nearly all |
| LLM-assisted classification | 99% accuracy | When LLM classification enabled; ~$0.005/session cost |
| Token compression | 55% savings | Type-aware compression, zero information loss measured |
| Locked belief retrieval boost | MRR 0.589 to 0.867 | Corrections and user rules surfaced reliably after tuning |

Tested across knowledge graphs ranging from 600 to 90,000+ nodes. Documented degradation curves at scale. All benchmarks use keyword-only retrieval with no embeddings or vector DB.

---

### Architecture (Conceptual)

**Ingestion pipeline:**
```
Conversation turn
  --> Sentence-level extraction (noise removal)
  --> Type classification (fact, correction, preference, requirement, etc.)
  --> Bayesian prior assignment based on type
  --> Correction detection (supersede outdated beliefs)
  --> Store (project-isolated)
```

**Retrieval pipeline:**
```
Query
  --> Layer 0: Always-loaded locked beliefs (corrections, user rules)
  --> Layer 1: Behavioral beliefs (directives)
  --> Layer 2: FTS5 keyword search (BM25 ranking)
  --> Layer 2.5: Entity-index lookup (structured triples, 4-hop chaining)
  --> Layer 3: HRR vocabulary bridge + BFS graph traversal
  --> Score and rank (confidence x type weight x time decay x usage history)
  --> Compress and return within token budget
```

---

### Research Methodology

85+ experiments during core development, plus 6 benchmark-phase experiments. Each experiment had a specific hypothesis, a measurement protocol, documented results, and a decision about whether to proceed, revise, or abandon. 35 documented case studies of real LLM behavioral failures (across Claude and Codex) with root cause analysis, pattern classification, and 36 derived acceptance tests. Contamination-proof benchmark protocol with mandatory verification before any reader touches data.

**Selected validated findings:**

- Multi-layer retrieval outperforms keyword search alone (100% vs 92% relevant node retrieval)
- Correction detection achieves 92% accuracy without LLM inference
- Type-aware compression saves 55% of tokens with zero measured information loss
- Locked beliefs with retrieval boost increase MRR from 0.589 to 0.867
- Automated feedback loop improves MRR by 22% over 10 rounds (Exp 66)
- Multi-session persistence validated across 5 sessions with 10/10 checks passing (Exp 84)

**Selected negative findings (approaches that were abandoned):**

- Multi-layer extraction: regressive at scale
- SimHash clustering: not viable for this domain
- Mutual information re-ranking: hurts more than it helps
- Rate-distortion optimization: unnecessary complexity for the gains
- Pre-prompt compilation: worse performance than on-demand retrieval
- Global holographic superposition: capacity exceeded 7.6x, pure noise
- Multi-layer graph expansion: 16K nodes, signal diluted to 3.6% of graph
- HRR autonomous edge discovery: precision 0.001, hard failure

These negative findings shaped the architecture as much as the positive ones. Every dead end is documented with the evidence that killed it.

---

### Current Status

| Component | Status |
|-----------|--------|
| Core ingestion pipeline | Complete, tested |
| Multi-layer retrieval | Operational |
| Correction detection | Operational (92% accuracy) |
| Bayesian confidence tracking | Operational |
| Locked beliefs | Operational |
| Temporal decay | Operational |
| Crash recovery | Operational (survived two real system crashes) |
| Automated feedback loop | Operational: fires on ingest(), search(), and session exit; validated +22% MRR over 10 feedback rounds (Exp 66) |
| Contradiction/support detection | Operational: automatically detects and creates edges on belief insertion |
| Retrieval performance | 0.7s avg query on 19K-node production database (8x improvement from 10s baseline) |
| Multi-session validation | Passed: 10/10 checks across 5 sessions (persistence, feedback, supersession, locking, retrieval stability) (Exp 84) |
| LLM classifier tracking | Operational: classified_by column tracks offline vs LLM vs user classification per belief; reclassification scoped to offline-only |
| Test suite | 362 passing tests, strict type checking |
| Self-hosting | System runs on its own project as live validation |

---

### What Makes This Different

Most memory systems for LLM agents are document stores with similarity search. This system:

1. **Treats memory as belief, not text.** Beliefs have confidence levels, type classifications, and temporal dynamics. They can strengthen, weaken, be superseded, or be locked.
2. **Detects corrections without LLM calls.** The agent can learn from being corrected without expensive inference on every conversation turn.
3. **Bridges vocabulary gaps in retrieval.** Recovers relevant beliefs even when the query shares zero keywords with the stored content.
4. **Enforces constraints.** Locked beliefs create a safety floor that the agent cannot forget or weaken over time.
5. **Is empirically validated.** 85+ experiments plus 6 benchmark experiments, 5 published benchmarks, quantitative results. Negative findings used to shape the architecture.
6. **Is open source.** Full code, benchmark adapters, experiment documentation, and contamination protocol available at [github.com/robotrocketscience/agentmemory](https://github.com/robotrocketscience/agentmemory) under MIT license.

---

### Technical Details

- **Source:** [github.com/robotrocketscience/agentmemory](https://github.com/robotrocketscience/agentmemory), MIT license
- **Language:** Python (strict typing throughout, pyright strict mode)
- **Storage:** SQLite with WAL mode for durability/concurrency
- **Dependencies:** Minimal (no heavy ML frameworks required for core operation)
- **Deployment:** MCP server (19 tools) for integration with AI coding tools; CLI with 23 commands
- **Modules:** 18 production modules, 23 benchmark adapters and scoring scripts
- **Scale tested:** 600 to 90,000+ nodes across five codebases
- **Production database:** 19K+ nodes, 0.7s avg retrieval
- **Benchmarks:** LoCoMo (ACL 2024), MemoryAgentBench (ICLR 2026), StructMemEval, LongMemEval (ICLR 2025)
- **Test suite:** 362 passing tests plus 62 acceptance tests (29 files, 1.65s)
- **Version:** 1.2.1 (research frozen 2026-04-16)
