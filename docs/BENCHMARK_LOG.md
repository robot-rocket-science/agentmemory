# Benchmark Log

## LoCoMo (2026-04-15)

**Paper:** Maharana et al., ACL 2024 (arXiv:2402.17753)
**Dataset:** locomo10.json (10 conversations, 5882 turns, 272 sessions, 1986 QA pairs)
**Pipeline:** agentmemory FTS5+HRR+BFS retrieval (budget=2000) + Haiku reader (batch_size=1)
**Scoring:** LoCoMo exact F1 methodology (Porter stemming, article removal, per-category rules)

### Overall Results

| Metric | Score |
|---|---|
| **Overall F1** | **40.5%** |
| Non-adversarial F1 | 22.3% |
| Ingest time (10 conversations) | ~25s total |
| Avg query latency | ~16ms |

### Per-Category F1

| Category | F1 | n | Notes |
|---|---|---|---|
| 1. Multi-hop | 17.6% | 282 | Answer spans multiple sessions |
| 2. Temporal | 22.2% | 321 | Date/time reasoning |
| 3. Open-ended | 12.4% | 96 | Speculative questions |
| 4. Single-hop | 26.9% | 841 | Direct factual recall |
| 5. Adversarial | 100.0% | 446 | Correctly refuses all |

### Reference Baselines (from LoCoMo paper, Table 2/3)

| System | Overall F1 | Notes |
|---|---|---|
| Human | 87.9% | Ceiling |
| GPT-4-turbo (128K) | 51.6% | Best long-context |
| RAG (DRAGON + gpt-3.5-turbo, top-5 obs) | 43.3% | Best RAG in paper |
| **agentmemory (FTS5+HRR+BFS + Haiku)** | **40.5%** | This run |
| Claude-3-Sonnet (200K) | 38.5% | Long-context |
| gpt-3.5-turbo (16K) | 36.1% | Long-context |
| RAG (DRAGON + gpt-3.5-turbo, top-5 dialog) | 32.9% | RAG on raw dialog |

### Analysis

1. **Adversarial detection is perfect** (100%). agentmemory correctly identifies when information is absent.
2. **Retrieval is the bottleneck.** FTS5+HRR finds topically relevant beliefs but misses the specific evidence turns containing answer tokens. The non-adversarial F1 (22.3%) vs the RAG baseline (32.9% on raw dialog) shows the gap is in retrieval precision.
3. **Temporal reasoning partially works.** Session date injection enables "yesterday"/"last week" resolution, but many temporal questions need inference agentmemory's belief decomposition loses.
4. **Open-ended is weakest** (12.4%). These require synthesis across multiple beliefs, which the retrieval-only pipeline handles poorly.
5. **The 40.5% overall is inflated by perfect adversarial score.** Without category 5, agentmemory scores 22.3% vs the paper's best non-adversarial scores in the 35-55% range.

### What Would Improve the Score

- Better retrieval recall (the retrieval pipeline finds ~30% of evidence turns vs DRAGON's ~60%)
- Embedding-based retrieval as a complement to FTS5 (keyword gaps on paraphrased questions)
- Larger retrieval budget (2000 tokens may be too tight for multi-hop questions)
- Using observations/summaries as retrieval targets (the LoCoMo dataset provides these)

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
