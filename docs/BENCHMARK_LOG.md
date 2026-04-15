# Benchmark Log

## LoCoMo (2026-04-15)

**Paper:** Maharana et al., ACL 2024 (arXiv:2402.17753)
**Dataset:** locomo10.json (10 conversations, 5882 turns, 272 sessions, 1986 QA pairs)
**Retrieval:** agentmemory FTS5+HRR+BFS (budget=2000, batch_size=1)
**Readers tested:** Opus 4.6, Haiku 4.5 (via Claude Code subagent)
**Scoring:** LoCoMo exact F1 methodology (Porter stemming, article removal, per-category rules)
**Protocol compliance:** Exact LoCoMo prompts, forced-choice for cat5, date hint for cat2, no answer leakage (ground truth in separate file, agents never see it)

### Overall Results (protocol-correct)

| Reader | Overall F1 | Notes |
|---|---|---|
| **Opus 4.6** | **66.1%** | 1986/1986 predictions filled |
| Haiku 4.5 | 6.1% | 571/1986 empty (subagent capacity limit) |

Ingest time: ~25s (10 conversations). Avg query latency: ~16ms.

**Note on Haiku:** The 6.1% score is not a fair retrieval comparison. Haiku subagents failed to generate predictions for 29% of items (returned empty strings). This is a subagent batch-processing limitation, not a retrieval quality signal. A fair Haiku comparison would require smaller batches or per-item processing.

| Metric | Score |
|---|---|
| **Overall F1 (Opus)** | **66.1%** |
| Ingest time (10 conversations) | ~25s total |
| Avg query latency | ~16ms |

### Per-Category F1

| Category | F1 | n |
|---|---|---|
| 1. Multi-hop | 42.2% | 282 |
| 2. Temporal | 45.4% | 321 |
| 3. Open-ended | 30.5% | 96 |
| 4. Single-hop | 69.4% | 841 |
| 5. Adversarial | 97.5% | 446 |

### Reference Baselines (from LoCoMo paper, Table 2/3)

| System | Overall F1 | Notes |
|---|---|---|
| Human | 87.9% | Ceiling |
| **agentmemory (FTS5+HRR+BFS + Opus)** | **66.1%** | Protocol-correct run |
| GPT-4-turbo (128K) | 51.6% | Best long-context in paper |
| RAG (DRAGON + gpt-3.5-turbo, top-5 obs) | 43.3% | Best RAG in paper |
| Claude-3-Sonnet (200K) | 38.5% | Long-context |
| gpt-3.5-turbo (16K) | 36.1% | Long-context |
| RAG (DRAGON + gpt-3.5-turbo, top-5 dialog) | 32.9% | RAG on raw dialog |

### Methodology

1. **Retrieval:** agentmemory ingests all LoCoMo sessions, one per agentmemory session. Each dialog turn is ingested with session date prefix for temporal grounding. Per-question retrieval via `retrieve()` with 2000-token budget, FTS5+HRR+BFS enabled, no locked beliefs.
2. **Answer generation:** 10 parallel Opus subagents (one per 200-item batch). Each agent receives only `id`, `prompt`, `context`. No answer field, no category label, no metadata. Ground truth stored in a separate file agents never access.
3. **Prompts:** Exact LoCoMo protocol. Cat 1/3/4: "Based on the above context, write an answer in the form of a short phrase..." Cat 2: appends "Use DATE of CONVERSATION to answer with an approximate date." Cat 5: forced-choice "(a) Not mentioned (b) [adversarial_answer]" with randomized order (seed=42).
4. **Scoring:** LoCoMo F1 (Porter stemming, article removal). Cat 1 uses multi-hop partial F1. Cat 3 uses first semicolon segment. Cat 5 uses forced-choice letter matching per `get_cat_5_answer()`.

### Earlier runs (methodology issues, superseded)

Two earlier runs had answer leakage (the `answer` field was present in the agent input JSON). The Haiku run (40.5%) and first Opus run (61.6%) are not valid. The protocol-correct run (66.1%) is the only reportable result.

### Analysis

1. **agentmemory + Opus beats the paper's best by 14.5pp** (66.1% vs 51.6% GPT-4-turbo). This uses keyword-only retrieval (FTS5+HRR), no embeddings.
2. **Single-hop is strongest** (69.4%). Direct factual recall from individual turns is well-served by keyword retrieval.
3. **Adversarial is near-perfect** (97.5%). Forced-choice format slightly harder than simple refusal, but the model correctly identifies absent information.
4. **Multi-hop and temporal are weaker** (42-45%). These require cross-session reasoning and date arithmetic from noisy context.
5. **Open-ended is weakest** (30.5%). Speculative questions require synthesis the retrieval pipeline doesn't directly support.

### What Would Improve the Score

- Embedding-based retrieval to complement FTS5 (keyword gaps on paraphrased questions)
- Larger retrieval budget (2000 tokens may be too tight for multi-hop)
- Using LoCoMo's provided observations/summaries as retrieval targets
- Retrieval recall measurement (what % of evidence turns are in the retrieved set)

---

# Onboarding Benchmark Log

## agentmemory (2026-04-11)

| Metric | Value |
|---|---|
| Project | /Users/thelorax/projects/agentmemory |
| DB | ~/.agentmemory/projects/2e7ed55e017a/memory.db |
| Git commits | 35 |
| Git date range | 2026-04-09 to 2026-04-11 (2 days) |
| Docs | 163 |
| Languages | Python |
| Nodes extracted | 16,690 |
| Edges extracted | 32,538 |
| Observations created | 16,294 (onboard) + 2,300 (conversation ingest) = 18,594 |
| Beliefs created | 16,775 (onboard) + 17,568 (conversation ingest) = 34,343 |
| Final belief count | 31,863 (after dedup + supersession) |
| Locked | 0 |
| Superseded | 2,439 |
| Timing | discover=0.81s, file_tree=0.54s, git=0.06s, docs=0.08s, ast=0.94s, citations=0.02s, directives=0.00s |
| Total onboard time | ~2.5s |
| Conversation sessions ingested | 15 sessions, 2,233 turns |

### Node breakdown
| Type | Count |
|---|---|
| sentence | 13,572 |
| heading | 1,489 |
| callable | 1,191 |
| file | 396 |
| commit_belief | 35 |
| behavioral_belief | 7 |

### Edge breakdown
| Type | Count |
|---|---|
| SENTENCE_IN_FILE | 15,061 |
| WITHIN_SECTION | 14,902 |
| CALLS | 1,676 |
| CITES | 364 |
| CONTAINS | 350 |
| COMMIT_TOUCHES | 149 |
| TEMPORAL_NEXT | 34 |
| CO_CHANGED | 2 |

### Belief distribution
| Type | Count |
|---|---|
| factual | ~23,500 |
| correction | ~3,900 |
| requirement | ~1,200 |
| preference | ~500 |

---

## alpha-seek-memtest (2026-04-11)

| Metric | Value |
|---|---|
| Project | /Users/thelorax/projects/alpha-seek-memtest |
| DB | ~/.agentmemory/projects/4b0f8c37972f/memory.db |
| Git commits | 619 |
| Git date range | 2026-03-24 to 2026-04-09 (16 days) |
| Docs | 1,726 |
| Languages | Python |
| Nodes extracted | 90,793 |
| Edges extracted | 302,268 |
| Observations created | 65,285 |
| Beliefs created | 65,257 |
| Locked | 0 |
| Superseded | 4,616 |
| Timing | discover=1.42s, file_tree=0.93s, git=0.80s, docs=0.43s, ast=1.86s, citations=0.33s, directives=0.00s |
| Total onboard time | ~5.8s |
| Temporal spread | 18 distinct days, 176 distinct hours |

### Belief distribution
| Type | Count |
|---|---|
| factual | 51,605 |
| correction | 5,973 |
| requirement | 2,867 |
| preference | 196 |

### Tier 2 temporal decay validation
| Belief age | Factual core_score | Ratio vs today |
|---|---|---|
| March 24 (18 days old) | 0.43 | 0.47x |
| April 9 (2 days old) | 0.92 | 1.0x |
| Simulated 30 days old | 0.29 | 0.31x |
| Simulated 14 months old | 0.00 | ~0x |

### Scaling observations
- alpha-seek-memtest is ~5x larger than agentmemory (90k vs 17k nodes)
- Onboard time scaled linearly: 5.8s vs 2.5s (2.3x for 5x data)
- AST parsing is the bottleneck in both (38% and 32% of total time)
- Citation extraction cost is negligible even at 1,726 docs
