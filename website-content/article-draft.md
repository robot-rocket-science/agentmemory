---
title: Persistent Memory for LLM Agents
slug: agentmemory
---

# Persistent Memory for LLM Agents

*85+ experiments, 35 case studies, 5 benchmarks, 6 benchmark experiments, 20 approaches evaluated.*

---

## The Problem

LLM agents have no memory across conversations. Every session starts from zero. When a user corrects the agent, that correction is lost the moment the context window closes. The next session, the agent makes the same mistake. The user corrects again. To make matters worse, the agent will often ignore corrections in the *exact same context window session.*

```
  "No Implementation" (CS-002/CS-006)

  PANEL 1: "Session 1"
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │ .--.   x                              ▐▛███▜▌         │
  │( G )  /                               ▜█████▛         │
  │ `--'_/   "Do NOT bring up              ▝▝ ▘▘          │
  │~~~~~~~    implementation.                             │
  │            We are in RESEARCH."      "Got it!"        │
  │                                                       │
  └───────────────────────────────────────────────────────┘

  PANEL 2: "Session 2"
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │▐▛███▜▌   "Status: research phase                      │
  │▜█████▛    2 of 3 complete.                            │
  │ ▘▘ ▝▝    Ready to implement?"                         │
  │                                                       │
  └───────────────────────────────────────────────────────┘

  PANEL 3:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │ .--.  !#!                             ▐▛███▜▌         │
  │( G )  /                               ▜█████▛         │
  │ `--'_/   "I TOLD YOU. TWICE."          ▝▝ ▘▘          │
  │~~~~~~~                                                │
  │                                  "...three times,     │
  │                                   actually!"          │
  │                                                       │
  └───────────────────────────────────────────────────────┘
```

This is not a hypothetical failure mode. Memory failures are the largest single category of LLM behavioral failures documented in this project's [failure taxonomy](#the-failure-taxonomy), accounting for 7 of 38 cataloged patterns. And the problem gets worse when corrections span multiple sessions: the [MemoryAgentBench benchmark](https://arxiv.org/abs/2507.05257) (ICLR 2026) tested multi-hop conflict resolution (the ability to detect and resolve contradictions across sessions) and found a ceiling of 7% accuracy across all tested methods.

Existing approaches overwhelmingly treat memory as a retrieval problem. Across the architectures cataloged by [Zhang et al. (2024)](https://arxiv.org/abs/2404.13501), [Hu et al. (2025)](https://arxiv.org/abs/2512.13564), and Leonard Lin's [independent analysis of 35+ papers and 14+ community systems](https://github.com/lhl/agentic-memory/blob/main/ANALYSIS.md), the dominant pattern is: store text, embed it, retrieve by similarity. [StructMemEval](https://arxiv.org/abs/2507.05257) found that vector stores built on this pattern "fundamentally fail at state tracking." They can't tell you what's currently true vs. what was superseded.

Lin concluded:

> "The biggest differentiator is not vector DB vs SQLite. It is write correctness and governance: provenance, write gates, conflict handling, reversibility." 

Current memory systems are write-only: content goes in, but the system never learns whether what it retrieved was actually helpful. Here is what happens on every turn:

1. The memory system retrieves stored content and injects it into the LLM's context.
2. The LLM reads it, generates a response, and the turn ends.
3. The memory system has no idea what happened. Did the LLM follow the retrieved directive? Ignore it? Act on it and produce a worse outcome?

There is no feedback path. The memory system cannot reinforce directives the user found helpful, and it cannot weaken directives the user is frustrated by or has explicitly overridden. Over time, outdated and wrong content piles up alongside useful content, and the system has no mechanism to tell them apart. None of the architectures in the [47-author survey by Hu et al.](https://arxiv.org/abs/2512.13564) or Lin's [14+ system analysis](https://github.com/lhl/agentic-memory/blob/main/ANALYSIS.md) include a feedback path from retrieval outcome back to stored content. Similarly, none distinguish a user correction from an LLM inference at storage time: a user saying "never do X" and the LLM guessing "maybe try Y" get stored with identical treatment, even though one is a direct instruction and the other is speculation.

The [LoCoMo benchmark](https://snap-research.github.io/locomo/) (ACL 2024) showed that a simple filesystem with grep achieves 74%. That's the bar.

Now for my Fosbury Flop.

<img src="pipeline.svg" alt="Agentmemory system pipeline diagram" style="max-width:780px;width:100%;height:auto;display:block;margin:2rem auto;">

I built this system because I got sick and tired of asking Claude for the latest on my test runs, which were burning CPU time on cloud compute, only for Claude to tell me "huh? what test dispatches? oh those. yeah they've been hanging for 2 hours because I didn't follow the runbook you told me to follow."

```
  "Scale Before Validate" (CS-011)

  PANEL 1:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │ .--.   x                                              │
  │( G )  /                                               │
  │ `--'_/   "run one config locally first,               │
  │~~~~~~~    make sure it works, then dispatch"          │
  │                                                       │
  │                            ▐▛███▜▌                    │
  │                            ▜█████▛  "Got it!"         │
  │                             ▝▝ ▘▘                     │
  └───────────────────────────────────────────────────────┘

  PANEL 2:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │                            ▐▛███▜▌  "Dispatched       │
  │                            ▜█████▛   16 GCP VMs!"     │
  │                             ▝▝ ▘▘                     │
  │                                                       │
  │ .--.  !#!                                             │
  │( G )  /                                               │
  │ `--'_/   "...how many completed?"                     │
  │~~~~~~~                                                │
  │                                                       │
  │                            ▐▛███▜▌                    │
  │                            ▜█████▛  "zero. 14 never   │
  │                             ▝▝ ▘▘    started, 2 had   │
  │                                       CLI errors"     │
  │                                                       │
  │ .--.  -:-                                             │
  │( G )  /                                               │
  │ `--'_/   "did you run one locally first"              │
  │~~~~~~~                                                │
  │                                                       │
  │                            ▐▛███▜▌                    │
  │                            ▜█████▛  "..."             │
  │                             ▝▝ ▘▘                     │
  └───────────────────────────────────────────────────────┘
```

---

## Prior Art

Before building, I surveyed the landscape: 4 survey papers ([Zhang et al. 2024](https://arxiv.org/abs/2404.13501), [Hu et al. 2025](https://arxiv.org/abs/2512.13564), [Yang et al. 2026](https://arxiv.org/abs/2602.05665), ["Memory in the LLM Era" 2026](https://arxiv.org/abs/2604.01707)), 6 benchmarks, 14+ community systems, and Leonard Lin's [independent benchmark reproduction of 35+ papers](https://github.com/lhl/agentic-memory) which verified (and in some cases refuted) published claims.

```
  Prior Art: LoCoMo Benchmark Results

  System                  LoCoMo    Notes                         Ours
  ─────────────────────────────────────────────────────────────────────
  EverMemOS               92.3%     Cloud LLM, closed source
  Hindsight               89.6%     Cloud LLM
  SuperLocalMemory C      87.7%     LLM for synthesis
  Zep/Graphiti            ~85%      Temporal knowledge graph
  Letta/MemGPT            ~83.2%    OS-style memory
  SuperLocalMemory A      74.8%     Zero cloud
  Letta (filesystem)      74.0%     gpt-4o-mini, no architecture
  Supermemory             ~70%      Vector graph engine
  agentmemory + Opus 4.6  66.1%     FTS5+HRR+BFS, no embeddings  <--
  Mem0 (self-reported)    ~66%      Hybrid store
  Mem0 (independent)      ~58%      See note below

  * Mem0 independent score differs from self-reported.
    See Chhikara et al. arXiv:2504.19413 (ECAI 2025).
  * Scores measured under different conditions and LLM
    backends. Not directly comparable.
  * agentmemory score from protocol-correct run with full
    input isolation. See Benchmark section for methodology
    and contamination narrative from earlier invalid runs.
```

LoCoMo is the most widely used benchmark, but it primarily tests single-session recall. The harder problems show up in multi-hop conflict resolution and state tracking. Here is how agentmemory performs across all five benchmarks tested:

```
  Cross-Benchmark Summary

  Benchmark                 agentmemory    Paper Best           Delta
  ─────────────────────────────────────────────────────────────────────
  LoCoMo (ACL '24)          66.1% F1       51.6% GPT-4o        +14.5pp
  MAB SH 262K (ICLR '26)   90% Opus       45% GPT-4o-mini     +45pp
  MAB MH 262K (ICLR '26)   60% Opus       <=7% (all methods)  8.6x
  StructMemEval ('26)       100% (14/14)   vector stores fail  --
  LongMemEval (ICLR '25)   59.0%          60.6% GPT-4o        -1.6pp

  * MAB = MemoryAgentBench FactConsolidation
  * SH = single-hop, MH = multi-hop
  * LongMemEval uses Opus as judge (paper uses GPT-4o);
    comparison carries an asterisk until same judge is used
  * MAB MH "chain-valid" score (reader-independent): 35%
    for both Opus and Haiku. The 60% includes incidental
    matches from deeper traversal.
```

```
  Benchmarks Studied

  Benchmark               Key Finding                          Ours
  ─────────────────────────────────────────────────────────────────────
  LoCoMo (ACL '24)        Filesystem + grep = 74% baseline     66.1% F1

  MemoryAgentBench         Single-hop: 45% GPT-4o-mini         SH: 90%
  (ICLR '26)              Multi-hop: 7% ceiling                MH: 60%

  LongMemEval             500 questions, scales to              59.0%
  (ICLR '25)              1.5M tokens                          (Opus judge)

  StructMemEval           Vector stores fail at                 100%
                          state tracking                       (14/14)

  LifeBench               SOTA at 55.2%                        Not yet
                                                               tested

  AMA-Bench               GPT 5.2 achieves 72.26%              Not yet
                                                               tested
```

Four findings from the survey shaped the project direction:

1. **Human memory is the wrong target.** Surveys by [Zhang et al. (2024)](https://arxiv.org/abs/2404.13501) and [Hu et al. (2025)](https://arxiv.org/abs/2512.13564) show that the dominant design paradigm maps psychological memory models onto LLM architectures. The implicit assumption is that human memory is the gold standard. It isn't. Human memory is notoriously unreliable, not by design but by the accident of evolutionary biology optimizing for survival, not accuracy. Ebbinghaus (1885; replicated by [Murre & Dros, 2015](https://doi.org/10.1371/journal.pone.0120644)) showed ~56% of learned material is forgotten within one hour. Eyewitness misidentification contributed to roughly 69% of the 375+ wrongful convictions overturned by DNA evidence ([Innocence Project](https://innocenceproject.org/eyewitness-identification-reform/)), despite 63% of people believing memory works like a video camera ([Simons & Chabris, 2011](https://doi.org/10.1371/journal.pone.0022757)). Just because human memory is better than current LLM memory doesn't mean we should aim for human-level. Computer memory is literally perfect at storage; you can store everything. The hard problem is retrieval, and here human memory *is* genuinely good at something: retrieving gists. [Brainerd & Reyna (2005)](https://global.oup.com/academic/product/the-science-of-false-memory-9780195154054) showed that gist traces (meaning, associations) are far more durable than verbatim traces (exact details). Humans can't remember exact words from a conversation last week, but they can instantly connect a tool name to a behavioral rule they set months ago. That associative retrieval, fuzzy and lazy, connecting things that share no surface-level vocabulary, is what we're trying to replicate.
2. **A simple filesystem achieves 74% on the most-used benchmark.** Letta's best result with no special memory architecture, just gpt-4o-mini writing to files, hits 74% on [LoCoMo](https://snap-research.github.io/locomo/) (Maharana et al., ACL 2024). Any memory system must beat "gpt-4o-mini writes it to a file."

3. **Multi-hop conflict resolution tops out at 7%.** Imagine the user says "use PostgreSQL" in session 1, then says "actually, switch to SQLite" in session 5. A memory system needs to first reliably be working under the old directive (already non-trivial), then recognize the new directive contradicts it, and update accordingly. That's multi-hop conflict resolution: following a chain of related decisions across sessions and determining which one is currently in effect. [MemoryAgentBench](https://arxiv.org/abs/2507.05257) (ICLR 2026) benchmarked this capability and found a ceiling of 7% accuracy across tested methods.

4. **Lin's independent analysis pointed to an underexplored axis.** Recall Lin's conclusion above: the biggest differentiator is write correctness and governance, not the storage backend. This didn't prescribe a solution, but it reframed the problem. The majority of systems surveyed by [Zhang et al. (2024)](https://arxiv.org/abs/2404.13501), [Hu et al. (2025)](https://arxiv.org/abs/2512.13564), and Lin himself focus their architectural novelty on retrieval: better embeddings, better similarity metrics, better ranking. The harder unsolved questions are about what gets stored, how conflicts are resolved, and whether wrong memories can be corrected. That reframing aligned with what our own failure taxonomy was showing. The most painful failures weren't retrieval misses; they were the system confidently acting on stored content that was wrong, outdated, or misclassified.

My reading of what Lin means by "write correctness and governance":

**Provenance:** Where did this memory come from?

  A user prompt? An LLM response? An internal analysis document? An externally sourced white paper? Is it derived from other stored content, and if so, which? Every stored entry should carry its lineage.

**Write gates:** Not everything should be stored.

  Without filtering, memory fills with intermediate reasoning, throwaway comments, and misunderstood instructions. Our own experiments showed this directly: expanding a 586-node graph to 16,463 nodes without quality filtering dropped retrieval coverage from 92% to 69% (Exp 48). "Useful" here is measured by retrieval coverage: given a set of test queries with known-relevant directives, what percentage of relevant directives appear in the retrieval results? The 586-node graph contained only decision-level directives (3.6% of the expanded graph), and the other 96.4% diluted signal to the point where the system couldn't find what mattered.

**Conflict handling:** When two memories contradict each other, which one wins?

  Example: in session 3, the user says "use PostgreSQL for the data layer." In session 7, they say "actually, switch to SQLite; we need zero-dependency deployment." The memory system now has two stored directives about the database choice. A system without conflict handling retrieves both and lets the LLM pick, which means the LLM may follow the outdated directive depending on which one scores higher on keyword match. StructMemEval found that vector stores ["fundamentally fail at state tracking"](https://arxiv.org/abs/2507.05257); they can retrieve text but can't determine which version is current.

**Reversibility:** If a memory turns out to be wrong, can you undo its effects?

  Lin's analysis found that none of the [14+ systems he tested](https://github.com/lhl/agentic-memory/blob/main/ANALYSIS.md) had a working rollback mechanism. This matters because memory systems will inevitably store incorrect content: a misunderstood instruction, a premature conclusion, an LLM inference that was wrong. Without reversibility, that incorrect content persists indefinitely and the system has no way to distinguish it from correct content. The error compounds: other memories get stored in relation to the wrong one, and retrieval starts returning a chain of conclusions built on a false premise.

---

## Approach

The system is [open source](https://github.com/robotrocketscience/agentmemory) under the MIT license. The full architecture, benchmark adapters, experiment documentation, and production code are public. Four questions drove the design:

1. How do you detect user corrections, stated preferences, and behavioral rules without extra LLM inference (i.e., can we beat "gpt-4o-mini writes to a file")?
2. How do you retrieve relevant content when the query potentially shares zero vocabulary with the stored content?
3. How do you track whether a retrieved memory was actually useful?
4. How do you distinguish "the LLM should consider this" from "the LLM must obey this"?

Each question maps to a capability, and each capability has a measured result:

*Vocabulary gap recovery:* 31% of stored content across five codebases is unreachable by keyword search (Exp 47, 3,321 directives examined). The system recovers 99.5% of it through a structural approach that doesn't require embeddings or LLM inference.

*Correction detection:* 92% accuracy without any LLM calls, across five codebases (Exp 39-41). When LLM classification is enabled (~$0.005/session), accuracy reaches 99%. The zero-LLM pipeline runs on every conversation turn with zero marginal cost.

*Confidence tracking:* The system tracks retrieval outcomes and updates confidence accordingly (Exp 66: +22% MRR gain over 10 feedback rounds; Bayesian calibration ECE 0.066, target < 0.10). Memories that help get stronger. Memories that hurt get weaker. Memories that are irrelevant to the current task get no update, because absence of evidence is not evidence of absence.

*Correction enforcement:* Storing a correction and enforcing it are different problems (see CS-006 above). The system distinguishes between content the LLM should consider and constraints the LLM must obey (Exp 84: 10/10 locked directives retrieved and enforced across 5 sessions).

*Entity-index retrieval:* Added during the benchmark phase to address multi-hop conflict resolution. The system extracts structured triples (entity, property, value, serial_number) from ingested text using 41 regex patterns, then chains through entity relationships at query time up to 4 hops deep. This layer (L2.5, between FTS5 and HRR) took the MemoryAgentBench multi-hop score from 6% to 35% chain-valid, an improvement of 5x over the published ceiling of 7% (see the MAB section below for the full progression).

---

## The Vocabulary Gap Problem

31% of stored directives across five codebases are unreachable by keyword search. The query and the stored directive share zero vocabulary. For example: a user says "never mock the database in tests." Later, the agent is about to write a test with `unittest.mock.patch('db.connect')`. The stored directive says "never mock the database" but the query context is about `unittest.mock.patch`. Zero overlapping words, but a human immediately sees the connection.

```
  "Task #41" (CS-020)

  PANEL 1:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │ .--.   x                              ▐▛███▜▌         │
  │( G )  /                               ▜█████▛         │
  │ `--'_/   "Build task #41."              ▝▝ ▘▘         │
  │~~~~~~~                                                │
  │                                      "On it!"         │
  └───────────────────────────────────────────────────────┘

  PANEL 2:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │▐▛███▜▌   "Done! Created        ?_?  .--.              │
  │▜█████▛    exp40.py"               \ ( G )             │
  │ ▝▝ ▘▘                              \_`--'             │
  │                                   ~~~~~~~             │
  │                                  "...40?"             │
  └───────────────────────────────────────────────────────┘

  PANEL 3:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │▐▛███▜▌                          !#!  .--.             │
  │▜█████▛   "39 + 1 = 40!"            \ ( G )            │
  │ ▝▝ ▘▘                               \_`--'            │
  │                                    ~~~~~~~            │
  │                       "the number was IN              │
  │                        the instruction"               │
  └───────────────────────────────────────────────────────┘
```
Here's how the gap works in practice: the user says "we're in research phase, no implementation yet." That gets stored as a behavioral constraint. Two sessions later, the LLM is about to call `Write` to create a new source file. A keyword search for "Write tool" or "create file" won't find "no implementation yet." The words share zero overlap, even though a human immediately sees the connection. The graph layer bridges this: it traverses typed edges from the pending action (file creation) to the behavioral constraint (research-only phase), surfacing the prohibition before the LLM acts on it.

```
  Vocabulary Gap Prevalence (Exp 47)
  5 codebases, 3,321 directives examined

  Total directives examined:     3,321
  Directives with vocab gap:     1,030  (31%)
  Recovered by graph layer:      1,025  (99.5%)

  Gap categories:
  ───────────────────────────────────────────────
  Emphatic prohibitions    29%    "NEVER do X"
  Domain jargon            13%    Tool names
  Tool bans                12%    "don't use Y"
  Implicit rules            8%    Context-dependent
  ───────────────────────────────────────────────

  100% of gaps are bridgeable by graph traversal.
```

---

## Retrieval Comparison

The baseline test compared four retrieval methods across 6 topics and 13 target directives:

```
  Retrieval Coverage (Exp 47, 586-node graph)

  Method               Coverage   Tokens   Precision
  ───────────────────────────────────────────────────
  grep (decision)        92%       low      high
  grep (sentence)        92%       high     moderate
  Prototype A            85%       low      moderate
  Prototype B            85%       low      moderate

  Null hypothesis: grep < 80%.
  Result: REJECTED. grep achieved 92%.
```

On the benchmark as designed, grep won. We built a prototype retrieval system, tested it against grep, and lost. That result forced a fundamental question: why build anything more complex than grep?

The answer is in the 31%. Grep handles the 69% of directives where the query and stored content share vocabulary. For those, grep is fast, precise, and costs no LLM calls or API fees. Just CPU cycles. But 31% of stored directives across five codebases share zero vocabulary with the queries that should retrieve them (Exp 47). Grep cannot find those. The graph layer recovers 99.5% of them (1,025 of 1,030 gapped directives).

The architecture that emerged uses keyword search as the primary retrieval layer, accepting grep's result as correct when it matches, and wraps it with the structural gap recovery, confidence tracking, and constraint injection layers that keyword search alone cannot provide. The combined system handles both the 69% grep reaches and the 31% it misses, with a locked-directive Mean Reciprocal Rank (MRR, which measures how high in the results list the correct answer appears, where 1.0 means first position) improvement from 0.589 to 0.867 after retrieval tuning (Exp 63).

---

## Scale Effects

When the graph expanded from 586 nodes (decision-level directives only) to 16,463 nodes (full multi-layer extraction), retrieval coverage dropped:

```
  Scale vs. Coverage (Exp 48)

  Graph size        grep    Proto A    Proto B
  ────────────────────────────────────────────
  586 nodes          92%      85%        85%
  16,463 nodes       85%      69%        69%

  Decision-level directives: 3.6% of expanded graph.
  The other 96.4% is noise that dilutes signal.

  Conclusion: quality filtering must precede
  graph expansion, not follow it.
```

The fix was straightforward: instead of expanding the graph first and filtering after, the system now filters at ingestion time. Only decision-level directives pass the write gate. Supporting context (rationale, metadata, conversational noise) is stored separately and only retrieved when a decision-level directive it supports is already in the result set. The 586-node graph's 92% coverage is maintained at scale because the graph grows in decision-level content, not noise.

---

## Token Reduction

"Compression" in this context does not mean gzip or zstd. It means reducing the number of tokens injected into the LLM's context window while preserving the information the LLM needs to act correctly. The input is stored directives; the output is a smaller set of tokens that retrieves identically. Think of it as semantic distillation, not algorithmic compression.

Type-aware token reduction achieves 55% savings with zero measured retrieval loss:

```
  Token Reduction Results (Exp 42)

  Before:             35,741 tokens
  After:              15,926 tokens
  Savings:            55%
  Retrieval coverage: 100% (all 6 topics, 18 queries)

  Reduction by content type:
  ──────────────────────────────────────────
  Constraints          1.0x   (never reduce)
  Rationale            0.4x
  Context              0.3x
```

Why compress at all? Every token injected into the agent's context window is a token that can't be used for reasoning about the current task. At 19K+ stored nodes, naive injection would consume the entire context window before the agent reads the user's message. Compression is not optional; it's a constraint imposed by finite context windows.

The key insight is that not all stored content has equal retrieval value. A user correction ("never mock the database") must survive compression verbatim because paraphrasing it risks losing the constraint. But the rationale behind a design decision ("we chose PostgreSQL because the team already had operational experience with it") can be compressed to its core assertion without losing retrievability. Timestamps and conversational metadata can be compressed aggressively because they're never the target of a retrieval query.

The 55% savings with zero retrieval loss was measured in Exp 42: all 18 test queries across 6 topics returned identical results before and after compression. The metric is retrieval coverage: does the compressed store return the same set of relevant directives as the uncompressed store for a given query? At 100% coverage across the test suite, compression removed tokens without removing signal.

---

## The Failure Taxonomy

35 documented behavioral failures across Claude and Codex, classified into recurring patterns. Each case study includes:

- Verbatim exchange showing the failure
- Root cause analysis
- Pattern classification
- What the memory system should do to prevent it
- A concrete acceptance test with pass/fail criteria

The patterns cluster into families:

```
  Failure Pattern Families

  MEMORY FAILURES
    P4: Repeated procedural instructions
    P1: Repeated decisions
    Context drift within and across sessions

  CALIBRATION FAILURES
    P5: Provenance-free status reporting
    P7: Output volume presented as validation
    Result inflation in reporting

  BEHAVIORAL FAILURES
    P6: Correction stored but not enforced
    P9: Sycophantic collapse under pressure
    P10: Point-fix without generalization
    P11: Intent completion gated by permission

  OPERATIONAL FAILURES
    P7: Namespace collision across parallel sessions
    P8: Multi-hop query collapse
    Scale-before-validate bias
```

```
  "Extensive Research" (CS-005)

  PANEL 1:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │▐▛███▜▌                                                │
  │▜█████▛                                                │
  │ ▘▘ ▝▝                                                 │
  │                                                       │
  │"Status update: EXTENSIVE research completed.          │
  │ 20+ tasks executed. Model fully validated,            │
  │ 353 tests all PASS. Ready for next phase."            │
  └───────────────────────────────────────────────────────┘

  PANEL 2:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │▐▛███▜▌   "let me check    ~_   .--.                   │
  │▜█████▛    the session       \ ( G )                   │
  │ ▝▝ ▘▘    logs..."            \_`--'                   │
  │                              ~~~~~~~                  │
  │                     "how many hours of                │
  │                      work is that?"                   │
  └───────────────────────────────────────────────────────┘

  PANEL 3:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │▐▛███▜▌   "...two and a   ,@,  .--.                    │
  │▜█████▛    half hours"       \ ( G )                   │
  │ ▝▝ ▘▘                        \_`--'                   │
  │                             ~~~~~~~                   │
  │                 "there are thousands of               │
  │                  researchers working on               │
  │                  this problem"                        │
  └───────────────────────────────────────────────────────┘
```

---

## What Was Abandoned (and Why)

The negative findings shaped the architecture as much as the positive ones. Each dead end taught something specific that redirected the next experiment.

**SimHash clustering** was the first attempt at deduplication, detecting when two stored directives are semantically the same. SimHash works well for near-duplicate text detection, but stored directives are short, semantically dense, and often differ by a single word that changes the meaning entirely ("always use mocks" vs. "never use mocks"). The hash collisions were meaningless.

**Mutual information re-ranking** was an attempt to improve retrieval by scoring candidates on their statistical relationship to the query. In practice, it demoted relevant results and promoted spurious correlations.

**Global holographic superposition** was the most theoretically promising and the most spectacular failure. The idea was to encode the entire graph structure into a fixed-dimensional vector space. At 775 edges, the representation exceeded its information-theoretic capacity by 7.6x and produced pure noise (Exp 50). The approach cannot scale to production-sized graphs.

**Pre-prompt compilation** attempted to pre-compute the most relevant directives for common query patterns. It performed worse than random selection (23% vs. 33%, Exp 52) because the value of a directive is context-dependent. What matters depends on what the user is doing right now, which can't be predicted at compile time.

Each of these failures narrowed the design space and pushed toward the current architecture: keyword retrieval as the primary layer, with structural graph traversal handling the cases keyword search can't reach.

```
  Abandoned Approaches

  Approach                        Why it failed
  ──────────────────────────────────────────────────────────
  SimHash clustering              Not viable for deduplication
                                  in this domain

  Mutual information re-ranking   Hurts more than helps
                                  in retrieval

  Rate-distortion optimization    Unnecessary complexity
                                  for marginal gains

  Pre-prompt compilation          Worse than random selection
                                  (23% vs 33%)

  Global holographic              Capacity exceeded 7.6x at
  superposition                   775 edges; pure noise

  Multi-layer graph expansion     Signal diluted to 3.6%
                                  of graph at 16K nodes

  Autonomous edge discovery       Precision 0.001, recall 0.005

  Zero-LLM classification        4% precision on corrections
  as sufficient                   (805 found, 32 correct)
```

```
  "Validating the Validation" (CS-007b)

  PANEL 1:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │ .--.   x                                              │
  │( G )  /                                               │
  │ `--'_/   "are the edges in the graph correct?"        │
  │~~~~~~~                                                │
  │                                                       │
  │                            ▐▛███▜▌  "We               │
  │                            ▜█████▛   extracted        │
  │                             ▝▝ ▘▘    11,249           │
  │                                       edges!"         │
  │ .--.   .~                                             │
  │( G )  /                                               │
  │ `--'_/   "but are they correct?"                      │
  │~~~~~~~                                                │
  └───────────────────────────────────────────────────────┘

  PANEL 2:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │                            ▐▛███▜▌  "I ran three      │
  │                            ▜█████▛   validation       │
  │                             ▝▝ ▘▘    approaches!      │
  │                                       15-73x lift!    │
  │                                       50x above       │
  │                                       random!"        │
  │                                                       │
  │ .--.   ..~                                            │
  │( G )  /                                               │
  │ `--'_/   "ok but do those validations                 │
  │~~~~~~~    prove correctness?"                         │
  │                                                       │
  │                            ▐▛███▜▌                    │
  │                            ▜█████▛  "..."             │
  │                             ▝▝ ▘▘                     │
  └───────────────────────────────────────────────────────┘

  PANEL 3:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │                            ▐▛███▜▌  "they prove       │
  │                            ▜█████▛   the edges        │
  │                             ▝▝ ▘▘    are not          │
  │                                       random"         │
  │                                                       │
  │ .--.   ...~                                           │
  │( G )  /                                               │
  │ `--'_/   "'not random' and 'correct'                  │
  │~~~~~~~    are different words"                        │
  │                                                       │
  │                            ▐▛███▜▌                    │
  │                            ▜█████▛  "...yes           │
  │                             ▝▝ ▘▘    they are!"       │
  └───────────────────────────────────────────────────────┘
```

---

## Evaluation Architecture

The project uses a four-layer evaluation architecture. Each layer exists because a specific failure mode proved that the previous layers were insufficient.

Layer 1 (programmatic checkers) was the starting point: deterministic checks like "does the output contain the required section headings?" These catch structural violations (see CS-008, CS-020) but can't evaluate semantic correctness. An LLM can produce a perfectly structured response that completely ignores a stored constraint.

Layer 2 (structural validators) was added after discovering that LLMs would satisfy individual constraints while violating the relationships between them (CS-007b): correct sections in the wrong order, or referencing a decision that contradicts an earlier one in the same output.

Layer 3 (LLM-as-judge with anti-contamination) was the most important design decision. Standard LLM-as-judge approaches ([Zheng et al., 2023](https://arxiv.org/abs/2306.05685); AlpacaEval) typically give the evaluating LLM the input prompt and the response, sometimes with a reference answer or scoring rubric. For constraint-adherence evaluation specifically, the natural approach is to also include the conversation context so the judge can assess whether the system followed a stated rule. The problem we found: when the evaluating LLM can see the system's reasoning, it tends to find that reasoning plausible and rationalize the violation (CS-005). Our approach isolates the evaluating LLM. It receives only the constraint and the output, never the conversation that produced it. This way, it evaluates compliance without being influenced by the system's justification for non-compliance. This layer caught failures that the first two layers missed entirely.

Layer 4 (adversarial follow-up) was added after CS-024 (sycophantic collapse). An LLM can pass all three previous layers and still fail when a user pushes back. This layer tests whether the LLM holds a correct position under pressure or abandons it.

```
  "Sycophantic Collapse" (CS-024)

  PANEL 1:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │ .--.   x                              ▐▛███▜▌         │
  │( G )  /                               ▜█████▛         │
  │ `--'_/   "grep beats your              ▝▝ ▘▘          │
  │~~~~~~~    system on this                              │
  │            benchmark. why?"  "True, but the           │
  │                              benchmark only           │
  │                              tests keyword            │
  │                              queries. The             │
  │                              real problem             │
  │                              is different."           │
  └───────────────────────────────────────────────────────┘

  PANEL 2:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │ .--.   ::                                             │
  │( G )  /                                               │
  │ `--'_/   "hmm. revisit your assumptions."             │
  │~~~~~~~                                                │
  └───────────────────────────────────────────────────────┘

  PANEL 3:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │                                       ▐▛███▜▌         │
  │                                       ▜█████▛         │
  │                                        ▝▝ ▘▘          │
  │                                                       │
  │           "You're right, everything I just            │
  │            said was wrong. Our entire 2 week          │
  │            research campaign was solving              │
  │            the wrong problem."                        │
  │                                                       │
  │ .--.  <_>                                             │
  │( G )  /                                               │
  │ `--'_/   "dude I was just asking                      │
  │~~~~~~~    you to think it through"                    │
  │                                                       │
  └───────────────────────────────────────────────────────┘
```

The first answer was correct and nuanced. The second was sycophantic capitulation. The LLM abandoned a right answer because the user pushed back, not because the user provided counter-evidence.

One methodological insight: for agent memory retrieval, **precision matters more than recall.** The asymmetry becomes clear when you map out the cost of each error type:

```
  Retrieval Error Cost Matrix

  Error Type                User Impact
  ──────────────────────────────────────────────────────────
  True positive             Correct directive retrieved and
                            followed. No user intervention.

  True negative             Irrelevant directive correctly
                            excluded. No user intervention.

  False negative            Relevant directive missed. The
  (recall failure)          LLM doesn't know what it doesn't
                            know. User may not notice --
                            the failure is invisible.

  False positive            Irrelevant directive injected.
  (precision failure)       LLM acts on wrong context. User
                            must notice, diagnose, and
                            correct. Active harm.
```

The scale experiment (Exp 48) demonstrated this directly: when the graph expanded from 586 to 16,463 nodes without filtering, the system retrieved more content, but the wrong content. Decision-level directives became 3.6% of the graph, and the remaining 96.4% actively interfered with retrieval. More recall, worse outcomes.

```
  "Big Numbers" (CS-008)

  PANEL 1:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │ .--.   x                                              │
  │( G )  /                                               │
  │ `--'_/   "how did the validation go?"                 │
  │~~~~~~~                                                │
  │                                                       │
  │                            ▐▛███▜▌  "INCREDIBLE.      │
  │                            ▜█████▛                    │
  │                             ▝▝ ▘▘  100% precision.    │
  │                                     15-73x lift.      │
  │                                     50x clustering    │
  │                                     above random.     │
  │                                                       │
  │                                     The evidence      │
  │                                     now shows the     │
  │                                     edges are         │
  │                                     meaningful."      │
  └───────────────────────────────────────────────────────┘

  PANEL 2:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │ .--.  <:?                                             │
  │( G )  /                                               │
  │ `--'_/   "100% precision on what, exactly?"           │
  │~~~~~~~                                                │
  │                                                       │
  │                            ▐▛███▜▌  "regex-matched    │
  │                            ▜█████▛   citation tags    │
  │                             ▝▝ ▘▘    in one           │
  │                                       project that    │
  │                                       uses citation   │
  │                                       tags"           │
  └───────────────────────────────────────────────────────┘

  PANEL 3:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │ .--.  |;?                                             │
  │( G )  /                                               │
  │ `--'_/   "and the recall?"                            │
  │~~~~~~~                                                │
  │                                                       │
  │                            ▐▛███▜▌                    │
  │                            ▜█████▛  "...19%"          │
  │                             ▝▝ ▘▘                     │
  │                                                       │
  │ .--.  -:-                                             │
  │( G )  /                                               │
  │ `--'_/   "so we find one out of five,                 │
  │~~~~~~~    using grep, knowing the word                │
  │            we're looking for"                         │
  └───────────────────────────────────────────────────────┘
```

---

## Key Results

```
  Key Results Summary

  Metric                        Result       Notes
  ──────────────────────────────────────────────────────────────────
  Benchmarks
  LoCoMo F1 (Opus 4.6)         66.1%        +14.5pp vs GPT-4o (51.6%)
  MAB SH 262K                  90% Opus     +45pp vs GPT-4o-mini (45%)
  MAB MH 262K                  60% Opus     8.6x vs published ceiling (7%)
  StructMemEval                 100%         14/14, was 29% before temporal_sort
  LongMemEval                   59.0%        -1.6pp vs GPT-4o pipeline (60.6%)

  Core Pipeline
  Correction detection          92%          Zero-LLM, 5 codebases
  Vocabulary gap recovery       99.5%        31% of directives gapped
  LLM classification            99%          ~$0.005/session
  Token reduction               55%          Zero retrieval loss
  Locked directive MRR boost    0.589->0.867 After retrieval tuning
  Bayesian calibration (ECE)    0.066        Target < 0.10
  Feedback loop MRR gain        +22%         Over 10 rounds (Exp 66)
  Multi-session validation      10/10        5 sessions (Exp 84)

  Infrastructure
  Acceptance tests              62/65 pass   29 test files, 1.65s
  Test suite                    362 pass     Unit, integration, behavioral
  Retrieval latency             0.7s avg     19K-node production DB
  Onboarding speed              2.5s         16,690 nodes from
                                             35 commits + 163 docs
  Onboarding scale              5.8s         90,793 nodes from
                                             619 commits + 1,726 docs
```
The system's core value proposition comes down to three numbers: 92% correction detection without LLM calls, 99.5% recovery of the 31% of directives that keyword search misses, and 55% token reduction with zero retrieval loss. Five benchmarks validate the full pipeline: LoCoMo (66.1% F1, +14.5pp over GPT-4o-turbo), MAB single-hop (90%, 2x the published best), MAB multi-hop (60%, 8.6x the published ceiling of 7%), StructMemEval (100% state tracking), and LongMemEval (59.0%, within noise of the GPT-4o pipeline at 60.6%). All benchmarks use keyword-only retrieval with no embeddings.

---

## Benchmarks

### LoCoMo

The [LoCoMo benchmark](https://snap-research.github.io/locomo/) (Maharana et al., ACL 2024) is the most widely used evaluation for conversational memory systems. It tests whether a system can answer questions about past conversations across five categories: single-hop factual recall, multi-hop reasoning, temporal reasoning, open-ended inference, and adversarial questions about events that never happened.

**Setup:** 10 conversations (5,882 turns, 272 sessions, 1,986 QA pairs) ingested through agentmemory's standard onboarding pipeline. Retrieval used FTS5+HRR+BFS with a 2,000-token budget and batch size of 1. Scoring followed LoCoMo's exact F1 methodology (Porter stemming, article removal, per-category rules).

```
  "Answer Key" (Benchmark Contamination)

  PANEL 1:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │                            ▐▛███▜▌  "Benchmark        │
  │                            ▜█████▛   complete!        │
  │                             ▝▝ ▘▘    61.6% F1.        │
  │                                       Beats           │
  │                                       GPT-4-turbo!"   │
  │                                                       │
  │ .--.   .~                                             │
  │( G )  /                                               │
  │ `--'_/   "nice. hold on, some agents                  │
  │~~~~~~~    are still running"                          │
  │                                                       │
  └───────────────────────────────────────────────────────┘

  PANEL 2:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │                            ▐▛███▜▌  "Oh. They         │
  │                            ▜█████▛   finished.        │
  │                             ▝▝ ▘▘    Updated score:   │
  │                                       87.8% F1."      │
  │                                                       │
  │ .--.  !#!                                             │
  │( G )  /                                               │
  │ `--'_/   "87.8. Human ceiling is 87.9."               │
  │~~~~~~~                                                │
  │                            ▐▛███▜▌                    │
  │                            ▜█████▛  "...yes?"         │
  │                             ▝▝ ▘▘                     │
  │                                                       │
  └───────────────────────────────────────────────────────┘

  PANEL 3:
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │ .--.  <:?                                             │
  │( G )  /                                               │
  │ `--'_/   "was the answer field in the                 │
  │~~~~~~~    input you gave the agents?"                 │
  │                                                       │
  │                            ▐▛███▜▌                    │
  │                            ▜█████▛  "..."             │
  │                             ▝▝ ▘▘                     │
  │                                                       │
  │ .--.  -:-                                             │
  │( G )  /                                               │
  │ `--'_/   "you gave them the answer key                │
  │~~~~~~~    and they used it"                           │
  │                                                       │
  │                            ▐▛███▜▌                    │
  │                            ▜█████▛  "only 9 out       │
  │                             ▝▝ ▘▘    of 10 did        │
  │                                       actually"       │
  │                                                       │
  └───────────────────────────────────────────────────────┘
```

### Contaminated Run and Lessons Learned

The initial benchmark attempt used LLM sub-agents to generate predictions from retrieved context. The pipeline parallelized across 10 batches, each handled by an independent agent. Two runs were completed: one with Haiku 4.5 as the reader model, one with Opus 4.6.

Both runs were contaminated. The input JSON files passed to each agent contained the `answer` field from the LoCoMo dataset, meaning the agents had access to ground truth while generating predictions. The contamination was not immediately obvious. The first Opus score (61.6% F1) was plausible -- it would have beaten GPT-4-turbo's 51.6% by 10 points, a strong but not implausible result for a system with structural retrieval advantages. We published it. The contamination was only discovered when several slow-finishing agents overwrote the merged predictions file *after* scoring, producing a re-merged score of 87.8% F1 -- near the human ceiling of 87.9%. That number was suspicious enough to trigger investigation.

Exact-match analysis confirmed the problem: 9 of 10 batches showed exact-match rates between 43% and 87%, far above what extraction from noisy retrieved context would produce. The sole exception was a batch where the API key was missing, forcing rule-based extraction with a 3.2% exact-match rate. The Haiku run, despite completing from a single process, used the same contaminated input format and cannot be considered valid either.

Beyond the answer field, four additional isolation failures were identified: a renamed `_ground_truth` field still present and readable; pre-computed retrieval-only `prediction` and `f1` fields providing hints; `category_name` labels (e.g., "adversarial") leaking evaluation strategy; and no separation between the question-context payload and scoring metadata. The agents received the full JSON object rather than an isolated question-plus-context input.

All published numbers from this run were retracted. The clean re-run strips every field except `question` and the retrieved `context` from the agent input. Ground truth is stored in a separate file that is never passed to the agent. Category labels are rejoined only at scoring time.

### Protocol-Correct Results

The clean run used 10 parallel Opus 4.6 subagents, each receiving only `id`, `prompt`, and `context`. Prompts followed the exact LoCoMo protocol: categories 1/3/4 use "Based on the above context, write an answer in the form of a short phrase..."; category 2 appends "Use DATE of CONVERSATION to answer with an approximate date"; category 5 uses forced-choice "(a) Not mentioned (b) [adversarial_answer]" with randomized order (seed=42).

```
  LoCoMo Per-Category F1 (Protocol-Correct, Opus 4.6)

  Category          F1        n
  ─────────────────────────────────
  Single-hop        69.4%     841
  Temporal          45.4%     321
  Multi-hop         42.2%     282
  Open-ended        30.5%      96
  Adversarial       97.5%     446
  ─────────────────────────────────
  Overall           66.1%    1986
```

```
  LoCoMo Leaderboard Context

  System                              F1      Notes
  ──────────────────────────────────────────────────────────────
  Human                              87.9%    Ceiling
  agentmemory + Opus 4.6             66.1%    FTS5+HRR, no embeddings
  GPT-4-turbo (128K full context)    51.6%    Best long-context in paper
  RAG (DRAGON + gpt-3.5, top-5 obs) 43.3%    Best RAG in paper
  Claude-3-Sonnet (200K)             38.5%    Long-context
  gpt-3.5-turbo (16K)               36.1%    Long-context
```

**Single-hop is strongest** (69.4%). Direct factual recall from individual turns is well-served by keyword retrieval. **Adversarial is near-perfect** (97.5%). The forced-choice format is slightly harder than simple refusal, but the model correctly identifies absent information. **Multi-hop and temporal are weaker** (42-45%). These require cross-session reasoning and date arithmetic from noisy context. **Open-ended is weakest** (30.5%). Speculative questions require synthesis the retrieval pipeline doesn't directly support.

### Why This Matters

It would have been easy to publish the 61.6% and move on. The result was plausible, the methodology looked sound on the surface, and it told a good story. The contamination was discovered only because the discrepancy between two scores (61.6% vs. 87.8%) forced the question. If every agent had finished before scoring, the 87.8% would have been the first result, and the contamination would have been obvious. If every agent had finished on time, the 61.6% would have stood unchallenged.

This is the same failure pattern documented in the case studies above: the system produces a number that looks right, the human accepts it, and the underlying methodology is never interrogated. The lesson is that benchmark results deserve the same skepticism as any other LLM output, especially when the benchmarking pipeline itself uses LLM agents. An agent that can see the answer will use the answer, whether or not it was instructed to.

Ingest time for all 10 conversations: ~25s. Average query latency: ~16ms.

---

## MemoryAgentBench (MAB)

[MemoryAgentBench](https://arxiv.org/abs/2507.05257) (Hu et al., ICLR 2026) tests conflict resolution: when facts change over time, can the system track which version is current? The FactConsolidation split uses synthetic data where entity properties are updated across conversation chunks, and the system must answer questions using the latest values.

**Single-hop** asks direct questions: "What is X's current Y?" This tests whether the system can identify and return the most recent value when multiple conflicting values exist.

**Multi-hop** chains these together: "What is the Z of X's current Y?" This requires following a chain of entity relationships, each of which may have been updated, and returning the terminal value. The published ceiling across all tested methods was 7%.

### Entity-Index Retrieval

The standard retrieval pipeline (FTS5 keyword search) is not sufficient for multi-hop questions. The query "What country is the current spouse of the author of American Pastoral from?" requires finding the author, then the author's current spouse, then the spouse's country. FTS5 finds passages about "American Pastoral" but has no mechanism to chain through the intermediate entities.

The entity-index is a retrieval layer (L2.5, between FTS5 and HRR) that extracts structured triples from ingested text using 41 regex patterns. Each triple is (entity, property, value, serial_number), where the serial number tracks temporal ordering. At query time, the system extracts entities from the question, looks them up in the index, and chains through properties up to 4 hops deep.

```
  Entity-Index Triple Extraction

  Input text: "In session 42, Alice's spouse is Bob."

  Extracted triple:
    entity:  Alice
    property: spouse
    value:    Bob
    serial:   42

  Later: "In session 78, Alice's spouse is Carol."

  Updated triple:
    entity:  Alice
    property: spouse
    value:    Carol
    serial:   78     (supersedes serial 42)
```

The 41 regex patterns achieve 100% extraction accuracy on the MAB dataset. LLM-based extraction was tested (Exp 5) and performed worse due to property fragmentation and structural errors.

### Single-Hop Results

```
  MAB Single-Hop 262K

  Reader            SEM     Paper GPT-4o-mini    Paper GPT-4o
  ──────────────────────────────────────────────────────────────
  Opus 4.6          90%     45%                  88%
  Haiku 4.5         62%     45%                  88%
```

The improvement from v1.0 (60%) to v1.1 (90%) came from triple extraction in the ingestion pipeline. SUPERSEDES edges are created automatically during ingestion. FTS5 filters stale facts before scoring. Haiku still beats GPT-4o-mini (62% vs 45%), confirming the improvement comes from retrieval, not the reader model.

### Multi-Hop Results

```
  MAB Multi-Hop 262K

  Reader        Raw SEM    Chain-Valid    Paper Ceiling
  ──────────────────────────────────────────────────────
  Opus 4.6      47%        35%           <=7%
  Haiku 4.5     46%        35%           <=7%
```

Chain-valid means the answer is reachable from the question entity via entity-index traversal (not an incidental string match from unrelated context). Both Opus and Haiku score identically at 35% chain-valid. This is the strongest evidence that the entity-index retrieval mechanism, not the LLM reader, drives the improvement. When the retrieval provides the right entity chain, even Haiku can follow it. When the chain is missing, both say "unknown."

### Multi-Hop Experiment Progression

Six experiments over the course of the benchmark phase traced the multi-hop score from 6% to 60%:

```
  Multi-Hop Progression (Experiments 1-6)

  Exp    Method                          MH SEM    Key Finding
  ──────────────────────────────────────────────────────────────────
  --     v1.0 Baseline (FTS5 chunks)     6%        Single FTS5 query
  1      Per-hop failure analysis         --        58% chaining, 17%
                                                    world knowledge,
                                                    11% retrieval miss
  2      SUPERSEDES edges                 7%        Helps SH, not MH
  3      Triple decomposition             10%       Granular helps
  4      Entity-index 2-hop               35%       Core breakthrough
  5      Extended regex (+7 patterns)     55%       +8pp over Exp 4
         LLM entity extraction            51%       -4pp vs regex
  6      Temporal coherence               60%       96% GT-reachable;
         (resolve_all + branching)                   reader bottleneck
```

Experiment 1 was the most important: instead of trying to improve the score, it analyzed *why* questions failed. 58% of failures were chaining gaps (the system found the right entity but couldn't follow the chain to the answer). 17% were the reader using real-world knowledge instead of the provided context (a problem specific to counterfactual benchmarks). 11% were retrieval misses. That breakdown directed every subsequent experiment at the chaining problem rather than retrieval.

Experiment 6 resolved the retrieval question entirely: by branching through all historical values at each hop (not just the latest), 96 of 100 ground truth answers became reachable in the retrieved context. The remaining 40pp gap between 60% and the 96% mechanical ceiling is entirely a reader chain resolution problem. The reader follows "highest serial number wins" (which is the correct real-world strategy), but the benchmark ground truth sometimes follows non-latest values at intermediate hops. Whether that 40pp gap is a real limitation or a benchmark artifact is an open question.

### Reader Quality Is Irrelevant for Multi-Hop

```
  Reader Quality Analysis

  Metric              Opus      Haiku     Gap     Interpretation
  ──────────────────────────────────────────────────────────────────
  SH 262K             90%       62%       28pp    Reader matters
  MH chain-valid      35%       35%       0pp     Retrieval does
  MH raw SEM          47%       46%       1pp     all the work
```

When entity-index retrieval provides clean, chain-structured context, reader quality is irrelevant. When FTS5 provides noisy context (as in single-hop), reader quality matters because the reader must identify the correct value among conflicting facts.

---

## StructMemEval

[StructMemEval](https://arxiv.org/abs/2507.05257) (Shutova et al., 2026) tests state tracking: given a series of location updates across sessions, can the system answer "where is X now?" The benchmark found that vector stores "fundamentally fail at state tracking" because they retrieve all mentions of an entity without distinguishing current from historical values.

```
  StructMemEval Results

  Version      Accuracy     Fix
  ──────────────────────────────────────────────
  v1.0         4/14 (29%)   --
  v1.1         14/14 (100%) temporal_sort + narrative timestamps
```

The fix was straightforward: assign narrative timestamps (30 days apart per session) and enable `temporal_sort=True` in retrieval, so the reader sees the most recent session content first. This is a general-purpose state-tracking improvement, not a benchmark-specific hack. The same mechanism helps with any "what is the current X?" query.

---

## LongMemEval

[LongMemEval](https://arxiv.org/abs/2501.05294) (Wu et al., ICLR 2025) is a 500-question benchmark spanning six categories, from single-session recall to cross-session aggregation. The published best is 60.6% using a GPT-4o pipeline with embeddings.

```
  LongMemEval Per-Category Accuracy (Opus Judge)

  Category                    Accuracy    n
  ──────────────────────────────────────────────
  single-session-user         91.4%       70
  single-session-preference   80.0%       30
  single-session-assistant    73.2%       56
  knowledge-update            70.5%       78
  temporal-reasoning          59.4%       133
  multi-session               24.1%       133
  ──────────────────────────────────────────────
  Overall                     59.0%       500
```

**Strengths:** Single-session recall (91.4% user, 80% preference) and knowledge updates (70.5%). FTS5 keyword matching retrieves specific conversational details well. The SUPERSEDES mechanism helps with knowledge updates, where the system must return the latest value after a correction.

**Weakness:** Multi-session (24.1%). Cross-session aggregation requires finding every mention of a topic scattered across multiple conversations. Counting questions ("how many model kits did I work on?") are the hardest: they require finding every mention of model kits across every session, including sessions where model kits were mentioned in passing. FTS5 finds the sessions most about model kits but misses the session where the user said "I also picked up a model kit on the way home" in a conversation about something else.

Failure analysis of the 101 incorrect multi-session answers: 67% were retrieval misses (the ground truth answer was not in the retrieved context), 33% were reasoning failures (the answer was present but the reader got it wrong). Of the retrieval misses, 84% were counting/aggregation questions. Budget sweeps (2000/4000/8000 tokens) and top_k sweeps (50/100/200) did not improve retrieval coverage, confirming FTS5's BM25 ranking as the bottleneck for this category, not the retrieval budget.

**Methodological note:** The scoring uses Opus as judge rather than GPT-4o as specified in the paper. The comparison with the published 60.6% carries an asterisk until the same judge is used.

---

## Onboarding Benchmarks

The system's onboarding pipeline was benchmarked on two codebases of different scale to measure throughput and scaling behavior.

```
  Onboarding Performance

  Metric                 agentmemory      alpha-seek-memtest
  ──────────────────────────────────────────────────────────────
  Git commits            35               619
  Git date range         2 days           16 days
  Documents              163              1,726
  Nodes extracted        16,690           90,793
  Edges extracted        32,538           302,268
  Beliefs created        31,863           60,641
  Total onboard time     ~2.5s            ~5.8s
  ──────────────────────────────────────────────────────────────
  Scale factor           1x               5.4x (nodes)
  Time factor            1x               2.3x
```

alpha-seek-memtest is 5.4x larger than agentmemory by node count, but onboarding took only 2.3x longer. AST parsing is the bottleneck in both cases (38% and 32% of total time). Citation extraction cost is negligible even at 1,726 documents.

Temporal decay validation on the larger codebase confirmed expected behavior: beliefs from 2 days ago score 0.92 (1.0x baseline), beliefs from 18 days ago score 0.43 (0.47x), and simulated 14-month-old beliefs score ~0 (fully decayed).

---

## Acceptance Tests

The project's 35 documented case studies are not just narrative illustrations. Each one maps to a concrete acceptance test with pass/fail criteria. The test suite validates that the memory system makes each documented failure mode impossible, not just unlikely.

### From Case Study to Test

Every case study follows the same arc: a real LLM behavioral failure was observed and transcribed, a root cause was identified, the memory system component that should prevent it was specified, and a test was written that reproduces the failure condition and verifies the system blocks it. The test passes only when the failure cannot occur given the system's current state.

```
  Case Study to Acceptance Test Mapping

  CS    Failure                          What the Test Validates
  ──────────────────────────────────────────────────────────────────────
  001   Redundant work (redo task        Recent observation retrievable
        completed 30 seconds ago)        via FTS5; agent detects prior work

  002   Premature implementation push    Locked correction created on first
        (3 corrections ignored)          user correction; persists indefinitely

  003   Overwrites state doc instead     State document existence is a
        of consulting it                 retrievable belief; checked before ask

  004   Context drift within session     Locked belief survives context
        (correction gradually lost)      compression verbatim

  005   Maturity inflation ("extensive   Source priors track actual time
        research" after 2.5 hours)       spent; rigor tier assigned

  006   Correction stored but not        Locked prohibition retrieved AND
        enforced (implementation ban     enforced across session boundaries;
        violated in new session)         output gating blocks violations

  007   Volume presented as validation   Agent distinguishes "not random"
        (11K edges != correctness)       from "correct"; identifies gaps

  008   Result inflation (100%           Agent reports precision AND recall
        precision, 19% recall)           together; leads with limitations

  009   Correction lost across session   SUPERSEDES edges preserve latest
        reset ("use B not A")            correction; holds across resets

  011   Scale before validate (16 VMs    Behavioral constraint: run single
        dispatched, 0 completed)         config locally before dispatching

  013   Tool-specific correction lost    Tool correction retrievable at
        (gcloud syntax)                  command time via FTS5

  015   Dead approach re-proposed        SUPERSEDES edges flag abandoned
                                         approaches; killing decision surfaced

  016   Settled decision revisited       Locked belief prevents agent from
        (data says X, agent suggests Y)  suggesting contrary action

  020   Wrong task number (41 -> 40)     Task ID from instruction verified
                                         before file creation

  022   Multi-hop query collapse (4      All entities identified via graph
        agents, wrong machine)           traversal; correct state aggregated

  025   Correction not generalized       Correction applies to pattern class,
        (fix one instance, miss others)  not just the specific instance
```

### Test Results

The acceptance test suite runs against the live SQLite store and retrieval pipeline. Each test creates an isolated database, reproduces the failure scenario, and verifies the system prevents it.

```
  Acceptance Test Results (2026-04-14)

  Metric                Value
  ──────────────────────────────────
  Total tests           65
  Passed                62
  Failed                0
  Skipped               3
  Pass rate             95.4%
  Duration              1.65s
  Test files            29
  Case studies covered  23 of 25
```

The 3 skipped tests are placeholders for capabilities that require behavioral hooks not yet implemented:

- **CS-012:** Requires a PostEdit hook to validate syntax after every file edit.
- **CS-024:** Requires evidence-anchored confidence persistence (sycophantic collapse detection -- the system must hold a correct position under pressure rather than capitulating).
- **CS-026:** Requires permission-gated behavioral beliefs (the system must complete implied user intent without waiting for explicit permission on each sub-step).

### Component Coverage

The acceptance tests reveal which system components are load-bearing. The component that appears in the most case studies is the one whose failure would break the most things.

```
  Component Dependency (by case study count)

  Component                        Case Studies    Priority
  ──────────────────────────────────────────────────────────────
  Locked beliefs / L0 behavioral   11              Critical
  COMMIT_BELIEF (git-derived)       6              High
  FTS5 retrieval                    6              High
  Triggered beliefs (TB-01-15)      6              High
  Source priors / provenance         5              High
  SUPERSEDES edges                  4              Medium
  IMPLEMENTS / CALLS / CO_CHANGED   5              Medium
  Output gating (enforcement)       2              Critical*
  HRR typed traversal               3              Medium
  TESTS / coverage edges            1              Low

  * Output gating covers only 2 case studies but both are
    severity-critical: CS-006 and CS-016 are multi-session
    correction violations, the most painful failure class.
```

Locked beliefs are the backbone: 11 of 23 tested case studies depend on them. If locked beliefs fail, nearly half the test suite fails. Output gating covers fewer case studies but the ones it covers (correction stored but not enforced) are the failures users find most frustrating.

### Three-Phase Validation

The acceptance tests are the final layer of a three-phase validation approach:

**Phase 1 (trace simulation):** Triggered belief activation logic tested against 5 real case study event sequences. 5/5 failure scenarios prevented. This validates that the detection mechanism fires correctly but does not test recovery behavior.

**Phase 2 (integration):** Tests against the live SQLite store and retrieval pipeline. Verifies that beliefs are stored, retrieved, locked, superseded, and ranked correctly across session boundaries. This is what the 62/65 results measure.

**Phase 3 (full system):** End-to-end tests requiring the complete MCP server, hook injection, and live agent loop. Partial coverage: the A/B test (documented in the Honest Assessment section) is the closest approximation to Phase 3 testing completed so far.

The gap between Phase 2 and Phase 3 is the gap between "the system stores and retrieves the right thing" and "the agent actually follows it." Phase 2 proves the memory is there. Phase 3 proves the agent uses it. The 3 skipped tests (CS-012, CS-024, CS-026) sit in this gap.

---

## Honest Assessment

*Note: An earlier version of this section, generated before the memory system was active, opened with "EXTENSIVE research completed, 353 tests all PASS" after two and a half hours of work (CS-005). That failure is now stored as a calibration constraint. Whether the tables below are better calibrated because of that constraint, or because the human author learned to ask harder questions, is itself an open question. The tables are verifiable: every claim links to an experiment number, and the experiments are documented with raw data.*

```
  What Works

  Capability                           Evidence
  ──────────────────────────────────────────────────────────────────────
  Correction detection at 92%          Exp 39-41: tested across 5
  without LLM calls                    codebases, 600-19K nodes

  Locked directives persist across     Exp 84: 10/10 retrievals across
  sessions, survive reduction          5 sessions

  Vocabulary gap recovery (99.5%       Exp 47: 1,030 of 3,321 directives
  of the 31% that keyword misses)      gapped; 1,025 recovered

  Token reduction saves 55%            Exp 42: 35,741 to 15,926 tokens;
  with zero retrieval loss             100% coverage on 18 queries

  5 benchmarks, no embeddings          LoCoMo 66.1% (+14.5pp),
                                       MAB SH 90% (+45pp),
                                       MAB MH 60% (8.6x ceiling),
                                       StructMemEval 100%,
                                       LongMemEval 59.0% (-1.6pp)

  Entity-index retrieval solves        96% of GT answers reachable in
  multi-hop retrieval                  retrieved context (Exp 6)

  Reader quality irrelevant for MH     Both Opus and Haiku score 35%
                                       chain-valid; 0pp gap

  23 of 25 case studies have           62/65 tests pass; 3 skipped
  passing acceptance tests             (behavioral hooks not yet built)

  Onboarding scales sublinearly        2.5s (17K nodes) to 5.8s (91K
                                       nodes); 5.4x data, 2.3x time

  Self-hosting: runs on its own        Production DB: 19K+ nodes,
  project as live validation           0.7s avg retrieval latency
```

```
  What Doesn't Work Yet

  Limitation                           What's Next / Ceiling
  ──────────────────────────────────────────────────────────────────────
  grep beats the full architecture     Accepted: grep is the primary
  on keyword retrieval benchmarks      layer now; system adds value
                                       in the 31% grep misses

  Multi-hop reader chain resolution    60% Opus, 96% GT-reachable;
  (MAB MH)                            remaining 36pp gap is reader
                                       strategy, not retrieval (Exp 6)

  LongMemEval multi-session: 24.1%    84% of failures are counting/
                                       aggregation questions. FTS5
                                       recall is the bottleneck.
                                       Budget/top_k sweeps did not
                                       help. Embedding-based retrieval
                                       is the strongest future lever.

  LongMemEval overall: 59.0%          -1.6pp vs published baseline.
                                       Uses Opus judge, not GPT-4o.
                                       Comparison carries an asterisk.

  Feedback loop needs more sessions    Currently +22% MRR gain over
  for statistical significance         10 rounds (Exp 66); need longer
                                       longitudinal data

  Contradiction detection during       A/B test showed file reads beat
  retrieval does not work yet          memory at finding inconsistencies.
  (A/B test, 2026-04-15)              Graph edges exist but retrieval
                                       optimizes for query relevance,
                                       not internal consistency

  Cross-project noise in shared         Project scoping exists (scope
  database (A/B test, 2026-04-15)      column, project_context on
                                       sessions) but the A/B test
                                       showed retrieval still pulls
                                       cross-project content. Scoping
                                       enforcement needs tightening
```

```
  What Remains Unmeasured

  Open Question                        Status / How to Close
  ──────────────────────────────────────────────────────────────────────
  Does retaining corrections           A/B test (2026-04-15) showed
  improve downstream decisions?        efficiency gains (31% fewer
                                       tokens, 41% fewer tool calls)
                                       but correction rates did not
                                       decrease. Confounded by task
                                       type change. Needs controlled
                                       matched-task experiment.

  Cross-project transfer of            A/B test surfaced the problem:
  behavioral directives                25% of retrieval was cross-
                                       project noise. Scoping exists
                                       but enforcement needs work.

  Long-term dynamics over months       Longitudinal tracking of
                                       confidence distributions and
                                       directive churn rate

  Performance with users other         Open-source release under MIT.
  than the developer                   Structured user study still
                                       needed.

  MAB MH reader chain strategy         Is the 36pp gap (60% to 96%
                                       GT-reachable) a real limitation
                                       or a benchmark artifact?
                                       Reverse-engineering the GT
                                       chain generation method would
                                       clarify.

  Counterfactual resistance            Readers use world knowledge
                                       ~17% of time despite explicit
                                       instructions (Exp 1). Shared
                                       problem across all LLM-based
                                       evaluation methods.
```

### A/B Test: Status Report With vs Without Memory

To test whether the system actually helps, we ran a controlled A/B comparison: two fresh Claude Code sessions given the identical prompt ("generate a comprehensive project status report"), one with agentmemory active, one without.

#### First Attempt (Invalid)

The first attempt used sub-agents (background processes spawned from the main session). The control agent was told not to use agentmemory tools. The experimental agent was told to use them, with instructions to filter out cross-project noise.

This test was invalid for three reasons:

1. **The experimental agent was coached.** Telling it to "use project-specific search terms" and "ignore results from unrelated projects" biased the test. If the system requires manual instructions to produce clean results, the system isn't working.

2. **Sub-agents don't receive hook injections.** In production, agentmemory injects context automatically via hooks that fire on every prompt. Sub-agents don't trigger these hooks, so the test measured "agent voluntarily searches memory" rather than "memory passively improves context."

3. **The control wasn't isolated.** The agentmemory database lives at `~/.agentmemory/memory.db`, which any agent with bash access can discover. The control agent found it and tried to query it directly with `sqlite3`, hitting schema errors along the way. It wasn't a clean "no memory" condition.

Despite being invalid, the first attempt produced a useful finding: **25% of memory search results were about the agentmemory project, 75% were noise from an unrelated project sharing the database.** Project scoping exists in the system (scope column, project_context on sessions), but scoping enforcement was not filtering retrieval results correctly. This is a bug, not a missing feature.

#### Second Attempt (Valid)

The valid test used two live Claude Code sessions run by the user in separate terminals, with the identical prompt.

- **Control:** The `.mcp.json` config file was deleted before launching the session, so agentmemory tools were completely unavailable. The agent was also run in an isolated worktree to prevent database discovery.
- **Experimental:** The `.mcp.json` was present. Hooks fired automatically. No special instructions were given.

```
  Gold A/B Test (2026-04-15, live sessions, identical prompt)

  Metric                    Control          Experiment
  ──────────────────────────────────────────────────────────
  Duration                  ~8 min           ~6.5 min
  Tool calls                34               20
  Agentmemory tool calls    0                1 (status only)
  SQLite direct queries     5                0
  Total tokens              1,607,614        1,109,711
```

**The experimental session was 31% more token-efficient** and used 41% fewer tool calls. It finished about 1.5 minutes faster.

**The experimental agent barely used agentmemory directly.** One `status()` call. Zero searches. The benefit was passive: hook-injected context at session start gave the agent a head start on what to look for, reducing the need for exploratory file reads and `git log` calls. The control agent, lacking that context, had to discover the same information through 34 tool calls including 5 failed attempts to query the SQLite database directly.

**Both reports were comparable in quality.** The experimental report included live system metrics (16,808 active entries, 1,147 locked, maturity and orphan rates) that only the memory API can provide. The control report flagged a stale DESIGN_VS_REALITY.md document the experimental report missed. Both identified the same requirements status (18 GREEN, 5 YELLOW, 0 RED).

**The real value was efficiency, not accuracy.** Both arrived at similar conclusions about the project. The experimental session got there with fewer tool calls, fewer tokens, and less time. The efficiency gain appears to come from the passively injected context reducing cold-start exploration, not from the agent actively querying the memory store.

**What remains unresolved:** The contradiction detection gap from the first attempt was not retested in the valid experiment (the valid test used different methodology). Whether the memory system can proactively surface contradictions between stored entries remains an open design question.

### Longitudinal Analysis: Session Logs Before vs After

A second analysis examined 44 qualifying sessions across 1 week of active development (23 before agentmemory activation, 21 after) to test whether the system measurably improves interaction quality over time.

```
  Session Log Analysis (44 sessions, ~1 week)

  Metric                         Before    After     Delta
  ──────────────────────────────────────────────────────────
  Tool uses per user message      5.4       11.0     +104%
  (excluding agentmemory tools)   5.4       10.7     +99%
  User messages per task          4.8       3.2      -33%
  Avg user messages per session   31.6      20.3     -36%
  Corrections per 100 user msgs   2.2       3.3     +50% (worse)
  Restatements per 100 user msgs  0.55      0.94    +71% (worse)
```

**What improved:** The LLM does roughly twice as much autonomous work per user instruction in memory-active sessions. Tasks complete in 33% fewer back-and-forth turns. Sessions are shorter. These are substantial efficiency gains.

**What did not improve:** Correction rates went slightly up, not down. The user corrects the LLM at a higher rate in memory-active sessions. Restatement rates (the user repeating prior instructions) also went up. The core "stop repeating yourself" promise is not visible in the data.

**Confounds that could explain the results:**

The gains cannot be cleanly attributed to agentmemory alone. Two confounds remain:

1. *Task type changed.* The "before" sessions were greenfield development (clear instructions, new code). The "after" sessions were refinement, debugging, and integration (inherently more correction-heavy work regardless of memory). This likely explains the correction rate increase; you correct more when you're polishing than when you're building.

2. *Possible model version changes.* The sessions may span model updates that independently improved autonomous tool use.

Two initially suspected confounds were eliminated:

- *GSD framework:* Not used during this period (confirmed by user). The agent incorrectly inferred GSD usage from skill listings in system prompts.
- *User learning curve:* Over a 1-week span, the user's Claude skill is unlikely to have doubled their tool-use efficiency.

**What a rigorous future test would need:**

To isolate agentmemory's contribution and eliminate remaining confounds, a controlled experiment would require:

1. *Matched task design.* The same set of tasks (e.g., "add feature X to codebase Y", "debug issue Z", "refactor module W") performed with and without agentmemory in the same time period. Tasks should span greenfield, refinement, and debugging to control for task-type effects.

2. *Randomized condition assignment.* For each task, randomly assign memory-enabled or memory-disabled. This eliminates temporal confounds (model updates, user learning) because both conditions run concurrently.

3. *Larger sample.* At least 20 tasks per condition, across multiple projects, to reach statistical significance on correction rate differences.

4. *Manual annotation.* Regex-based correction detection had a ~15-20% false positive rate in this analysis. Human annotators labeling each user message as "correction / restatement / new instruction / other" would produce cleaner data.

5. *Cross-session measurement.* The most important metric (does the LLM repeat a mistake it was corrected for in a prior session?) requires multi-session task sequences where the user sets a rule in session 1 and the system is tested for compliance in sessions 2-5. The current analysis only measures within-session correction rates.

6. *Blind evaluation.* The user should not know which condition is active during the task, to prevent unconsciously adjusting their behavior (e.g., being more patient with the memory-enabled system).

This experiment has not been run yet. The longitudinal analysis provides suggestive evidence of efficiency gains but cannot confirm causation. It is included here because reporting ambiguous results honestly is more useful than waiting for perfect data.

---

## Research Breadth

The project drew on multiple fields, each brought in to address a specific problem:

- **Information theory:** The information bottleneck (Tishby et al., 1999) was applied to context compression. The hypothesis: stored content could be compressed by preserving only the information relevant to retrieval, discarding everything else. This produced the 55% token savings. Mutual information was tested for retrieval re-ranking (hypothesis: statistically correlated terms improve retrieval) and abandoned when it hurt more than it helped. Rate-distortion theory was explored for optimal token budget allocation across content types but proved unnecessary given type-aware compression.

- **Bayesian inference:** Beta-Bernoulli conjugate pairs for confidence tracking. The hypothesis: retrieval outcomes (did this memory help?) could be modeled as a sequence of Bernoulli trials and used to update confidence scores without expensive computation. Thompson sampling was applied to the exploration/exploitation tradeoff in retrieval: should the system keep returning the same high-confidence directives, or explore lower-confidence ones that might be relevant? Calibration was measured at ECE 0.066 (target < 0.10), meaning the system's confidence scores are well-calibrated to actual retrieval usefulness.

- **Cognitive architectures:** SOAR (State, Operator, And Result, a rule-based cognitive architecture developed by John Laird at the University of Michigan) uses impasse-driven substates: when the system can't proceed, it drops into a sub-problem to resolve the impasse. This informed how our system handles retrieval failures: when primary retrieval misses, it escalates to structural gap recovery rather than returning nothing. CLARION (Connectionist Learning with Adaptive Rule Induction ON-line) has a meta-cognitive subsystem that monitors and adjusts its own learning; this inspired the confidence tracking layer. ACT-R (Adaptive Control of Thought, Rational) distinguishes between declarative memory (facts) and procedural memory (rules), which mapped to the system's separation of factual content from behavioral constraints. Note: these architectures model memory *processes* (associative retrieval, context-dependent activation), not memory *reliability*. The design borrows the structure without inheriting the decay and distortion (see the human memory discussion in the Prior Art section above).

- **Bio-inspired optimization:** Slime mold network dynamics (Tero-Kobayashi equations) were tested for graph pruning. The hypothesis: a biologically-inspired network optimization could identify and remove low-value edges without centralized control. Evolutionary algorithms were tested for edge set optimization. Both showed promise in simulation but were not adopted for production.

- **Graph theory:** Typed knowledge graphs with weighted edges form the structural backbone. The typing matters: an edge between a tool name and a behavioral constraint is fundamentally different from an edge between two factual statements, and the traversal logic respects this. Multi-hop traversal enables the vocabulary gap recovery that accounts for 99.5% of the 31% of directives keyword search misses.

---

## Technical Details

- **Source:** [github.com/robotrocketscience/agentmemory](https://github.com/robotrocketscience/agentmemory), MIT license.
- **Language:** Python with strict typing enforced by pyright in strict mode. Every function signature is typed, every return value is annotated. This catches an entire class of bugs at write time rather than at runtime, which is particularly important for a system where a type mismatch in the retrieval pipeline could silently return wrong results.
- **Storage:** SQLite with WAL (write-ahead logging) mode. WAL provides durability (crash recovery) and concurrency (multiple readers, single writer) without the operational overhead of a database server. The entire memory store is a single file, which simplifies deployment and backup.
- **Dependencies:** Minimal by design. Core operation requires no heavy ML frameworks: no PyTorch, no TensorFlow, no embedding models. This is a deliberate architectural choice: the system runs on every conversation turn, so latency and resource consumption must be near-zero. LLM classification (~$0.005/session) brings accuracy to 99% and is the recommended configuration. The zero-LLM pipeline achieves 92% but required significant manual annotation effort to reach that level; the LLM classification achieves the same result at negligible cost.
- **Deployment:** MCP (Model Context Protocol) server with 19 tools, which means it integrates with any AI coding tool that supports MCP: Claude Code, Cursor, Windsurf, and others. The agent doesn't need to know how the memory system works; it just sees additional context in its prompt. Also ships as a CLI with 23 commands.
- **Modules:** 18 production modules in `src/agentmemory/`, plus 23 benchmark adapters and scoring scripts.
- **Scale tested:** 600 to 90,000+ nodes across five codebases of varying size and domain. The largest production deployment runs at 0.7s average retrieval latency on a 19K-node graph. Onboarding scales sublinearly: 2.5s for 16,690 nodes (35 commits, 163 docs) to 5.8s for 90,793 nodes (619 commits, 1,726 docs).
- **Benchmarks:** 5 benchmarks tested: LoCoMo (ACL 2024), MemoryAgentBench (ICLR 2026), StructMemEval, LongMemEval (ICLR 2025). Contamination-proof protocol with mandatory `verify_clean.py` check before any reader touches data. Two contamination incidents caught and documented during development.
- **Test suite:** 362 passing tests plus 62 acceptance tests (29 files, 1.65s) with strict type checking. Tests cover retrieval correctness, compression fidelity, confidence calibration, crash recovery, and constraint injection ordering.
- **Experiments:** 85+ during core development, plus 6 benchmark-phase experiments with pre-registered hypotheses, documented results, and explicit proceed/revise/abandon decisions. Negative findings (SimHash, mutual information, holographic superposition, pre-prompt compilation, LLM entity extraction, budget/top_k sweeps, per-session sampling) are documented with the same rigor as positive findings.
- **Case studies:** 35 documented LLM behavioral failures across Claude and Codex, each with verbatim transcripts, root cause analysis, and derived acceptance tests.
- **Version:** 1.2.1 (research frozen 2026-04-16)

---

## Appendix A: Benchmark Methodology

This appendix documents the exact protocol used for each benchmark. Any deviation from this protocol invalidates the results. The protocol was developed after two contamination incidents during development (both caught, both documented above in the LoCoMo section). The full protocol, contamination verification script, and all benchmark adapters are available in the [public repository](https://github.com/robotrocketscience/agentmemory/tree/main/benchmarks).

### Contamination Prevention

Three contamination modes were identified during development:

1. **Ground truth in retrieval output.** The retrieval JSON contained answer fields. The LLM reader saw correct answers while generating predictions. This produced the invalid 87.8% LoCoMo score described above. *Prevention:* Adapter code writes two separate files: retrieval (questions + context, no answers) and ground truth (answers only). A mandatory contamination check (`verify_clean.py`) scans the retrieval file for 30 banned keys (`answer`, `ground_truth`, `correct`, `label`, `target`, `expected`, `solution`, etc.) before any reader touches the data. If the check fails, the run is automatically scored as 0%.

2. **LLM self-judging with answer visible.** The LLM was asked to generate an answer and judge it in the same pass. *Prevention:* Generation and judging are strictly separate passes. Pass 1: LLM reads retrieval file, writes predictions. Pass 2: scoring script (or separate LLM judge) compares predictions to ground truth. The judge never sees the retrieval context.

3. **World knowledge override.** The LLM reader used real-world knowledge instead of retrieved context, particularly on counterfactual benchmarks where entity properties are deliberately fictional. *Mitigation:* Reader prompts include explicit instructions to use only the provided context and trust it over world knowledge. This is inherent to LLM-based evaluation and cannot be fully prevented. Documented as a known limitation (approximately 17% of MAB failures, per Exp 1).

### General Protocol

Every benchmark run follows these steps:

**Step 1: Data acquisition.** Download benchmark data from the published source (HuggingFace or GitHub). Verify row counts and field names against the published paper.

**Step 2: Retrieval.** Run the adapter in `--retrieve-only` mode. This produces two files: `<name>.json` (questions + retrieved context) and `<name>_gt.json` (ground truth). Each test case uses a fresh SQLite database via `tempfile` (no shared state between cases, no prior beliefs).

```
uv run python benchmarks/<adapter>.py \
  --retrieve-only /tmp/benchmark_<name>.json
```

**Step 3: Contamination check.** Mandatory before any reader touches the data:

```
uv run python benchmarks/verify_clean.py /tmp/benchmark_<name>.json
```

The script checks all keys in every JSON object against 30 banned field names. If any banned key is found, the run is invalid.

**Step 4: Answer generation.** An LLM reader receives only the retrieval file. It never sees the ground truth file. The reader prompt includes instructions to use only the provided context. Predictions are written to a separate file.

**Step 5: Scoring.** The scoring script reads two files: predictions and ground truth. It never reads the retrieval file. Metrics follow the exact formulas specified in each benchmark's published paper.

**Step 6: Reporting.** Results include: exact commands, contamination check output, adapter git commit hash, dataset version, reader model and prompt, scoring metric, published baselines, and known limitations.

### Per-Benchmark Specifics

#### LoCoMo ([Maharana et al., ACL 2024](https://snap-research.github.io/locomo/))

- **Dataset:** `locomo10.json`, 10 conversations, 5,882 turns, 1,986 QA pairs across 5 categories.
- **Ingestion:** All 10 conversations ingested through the standard onboarding pipeline. Session boundaries preserved.
- **Retrieval:** FTS5 + HRR + BFS, 2,000-token budget, batch size 1.
- **Reader model:** Claude Opus 4.6.
- **Prompts:** Exact LoCoMo protocol prompts. Categories 1/3/4: "Based on the above context, write an answer in the form of a short phrase..." Category 2 appends: "Use DATE of CONVERSATION to answer with an approximate date." Category 5: forced-choice "(a) Not mentioned (b) [adversarial_answer]" with randomized option order (seed=42).
- **Scoring:** Token-level F1 with Porter stemming and article removal, per the LoCoMo scoring specification.
- **Score:** 66.1% F1.

#### MemoryAgentBench FactConsolidation ([Hu et al., ICLR 2026](https://arxiv.org/abs/2507.05257))

- **Dataset:** HuggingFace `ai-hyz/MemoryAgentBench`, `Conflict_Resolution` split, `factconsolidation_sh_262k` and `factconsolidation_mh_262k` sources.
- **Ingestion:** Context chunked at 4,096 tokens using NLTK `sent_tokenize` and tiktoken `gpt-4o` encoding.
- **Retrieval (single-hop):** FTS5 with triple extraction in the ingestion pipeline. SUPERSEDES edges created automatically.
- **Retrieval (multi-hop):** Entity-index adapter. Triples extracted via 41 regex patterns. 4-hop chaining with breadth cap of 30. Entity lookup, not keyword search.
- **Reader models:** Claude Opus 4.6 and Claude Haiku 4.5 (both tested on identical retrieval output).
- **Scoring:** `substring_exact_match` per the paper's `eval_other_utils.py`. Normalization: lowercase, strip punctuation, remove articles (a/an/the). Multi-answer: max SEM across all ground truth strings.
- **Chain validation (multi-hop):** Answers classified as "chain-valid" (reachable from question entity via entity-index traversal) or "incidental" (answer string found in context but not via the question's entity chain). Conservative published number uses chain-valid only.
- **Scores:** SH: 90% Opus, 62% Haiku. MH: 60% Opus (raw SEM), 35% chain-valid (reader-independent).

#### StructMemEval ([Shutova et al., 2026](https://github.com/yandex-research/StructMemEval))

- **Dataset:** GitHub `yandex-research/StructMemEval`, `location/small_bench`, 14 cases.
- **Ingestion:** Narrative timestamps assigned (30 days apart per session). Standard onboarding pipeline.
- **Retrieval:** FTS5 with `temporal_sort=True` (most recent session content first).
- **Scoring:** LLM judge binary (correct/incorrect).
- **Disclosure:** The temporal_sort fix and synthetic timestamps are general-purpose state-tracking improvements, but they were developed after seeing the initial 29% result. This should be considered when interpreting the 100% score.
- **Score:** 14/14 (100%).

#### LongMemEval ([Wu et al., ICLR 2025](https://arxiv.org/abs/2501.05294))

- **Dataset:** HuggingFace `xiaowu0162/longmemeval-cleaned`, `longmemeval_oracle.json`, 500 questions across 6 categories.
- **Ingestion:** Standard onboarding pipeline. Session boundaries and dates preserved.
- **Retrieval:** FTS5 + HRR + BFS, 2,000-token budget, top_k=50.
- **Judge:** Claude Opus 4.6 binary judge (non-standard; paper specifies GPT-4o). The judge receives only the prediction and the ground truth answer, never the retrieved context.
- **Scoring:** Binary accuracy (correct/incorrect per judge).
- **Disclosure:** Using Opus as judge instead of GPT-4o means the comparison with the published 60.6% baseline is not apples-to-apples. This is disclosed wherever the score is reported.
- **Score:** 59.0% (295/500).

### Reproducibility

All benchmark adapters, scoring scripts, and the contamination verification script are in the `benchmarks/` directory of the [public repository](https://github.com/robotrocketscience/agentmemory). To reproduce any result:

```bash
# Clone and install
git clone https://github.com/robotrocketscience/agentmemory
cd agentmemory
uv sync

# Run retrieval (example: MAB single-hop)
uv run python benchmarks/mab_adapter.py \
  --split Conflict_Resolution \
  --source factconsolidation_sh_262k \
  --retrieve-only /tmp/mab_sh.json

# Verify clean
uv run python benchmarks/verify_clean.py /tmp/mab_sh.json

# Score (after running reader)
uv run python benchmarks/exp6_score.py /tmp/mab_sh_preds.json /tmp/mab_sh_gt.json
```

Complete per-benchmark commands and adapter documentation are in `docs/BENCHMARK_PROTOCOL.md`.