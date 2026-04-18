<sub>[← Chapter 8 - Benchmark Results](BENCHMARK_RESULTS.md) · [Contents](README.md)</sub>

# Chapter 9. Research Freeze: Benchmark Findings and Future Levers

Date: 2026-04-16
Status: Research frozen. All findings documented for future reference.

## Benchmark Summary (Final Numbers)

| Benchmark | Score | Paper Best | Delta | Status |
|---|---|---|---|---|
| MAB SH 262K | 90% Opus / 62% Haiku | 45% GPT-4o-mini | +45pp / +17pp | Solved |
| MAB MH 262K | 60% Opus (temporal) | <=7% (all methods) | +53pp | 8.6x ceiling, retrieval solved |
| StructMemEval | 100% (14/14) | vector stores fail | n/a | Solved |
| LoCoMo | 66.1% F1 | 51.6% GPT-4o-turbo | +14.5pp | Ahead |
| LongMemEval | 59.0% (Opus judge) | 60.6% GPT-4o pipeline | -1.6pp | Within noise |

## Architecture

- FTS5 full-text search + entity-index (L2.5) + HRR vocabulary bridge + BFS
- Regex triple extraction (41 patterns, 100% on MAB dataset)
- SUPERSEDES-based conflict resolution
- temporal_sort for state-tracking queries
- 2000-token retrieval budget, top_k=50
- No embeddings, no vector DB
- 18 production modules, 19 MCP tools, 260+ tests, strict pyright

---

## Experiment 6: Temporal Coherence (MAB MH)

### What We Tested

Added `resolve_all()` to EntityIndex: returns ALL historical values per
(entity, property) instead of only the latest serial. Added
`multi_hop_retrieve_temporal()` that branches through all values at each
hop (breadth cap 30), collecting all reachable facts.

### Results

| Metric | Baseline | Temporal | Delta |
|---|---|---|---|
| GT-reachable | 62/100 | 96/100 | +34 |
| Opus SEM | 58% | 60% | +2pp |
| Reader accuracy (old 62) | 93.5% | 94% | +0pp |
| Reader accuracy (new 34) | n/a | 6% | -- |
| Context size (mean facts) | 11 | 75 | 6.8x |
| Mechanical ceiling | 62% | 96% | +34pp |

### Why Only +2pp Despite 96% Reachable

The 34 newly-reachable questions have GT chains that follow non-latest
serial values at intermediate hops. The reader, correctly following the
"highest serial wins" instruction, always picks the latest-serial chain.
This produces the same answer as the baseline (latest-only) retrieval.

Example (Q2):
- Our chain: American Pastoral -> F. Scott Fitzgerald (10793) ->
  Carl Lumbly (serial 16800, LATEST spouse) -> Colombia -> Antarctica
- GT chain: same start -> Zelda Fitzgerald (serial 8453, NOT latest)
  -> Australia -> Oceania

The reader is correct per instructions. The GT just follows a different
chain resolution strategy.

### Key Insight

**The retrieval problem is fully solved.** 96% of GT answers appear in
the retrieved context. The remaining 36pp gap is entirely reader chain
resolution strategy, not retrieval.

### v1 vs v2 Lesson

v1 (no serial numbers in output): 1% SEM. Catastrophic regression
because the reader had no way to distinguish old from new facts and
defaulted to real-world knowledge.

v2 (serial numbers prepended): 60% SEM. Reader can see serials and
correctly applies "highest serial wins." But this produces the same
chain as baseline for the 34 new questions.

Lesson: always include temporal metadata (timestamps, serials, versions)
in retrieved context so the consumer can resolve conflicts.

### Future Levers (Not Implemented)

1. **Mechanical chain resolver**: Enumerate all valid chains from entity
   index, return all terminal values. Removes reader variable entirely.
   Expected ceiling: 96% (minus 4 entity extraction failures).
   Risk: approaches benchmark gaming if tuned to match GT chain strategy.

2. **Multi-chain reader prompt**: Instruct reader to trace ALL possible
   chains, not just latest-serial. Would need to return multiple answers.
   Unknown effectiveness with subagent readers.

3. **GT chain analysis**: Reverse-engineer how the MAB GT was generated
   (temporal snapshot at question-creation time vs other strategy).
   Would clarify whether the 36pp gap is a real problem or a
   benchmark artifact.

### Files

| File | Purpose |
|---|---|
| benchmarks/mab_entity_index_adapter.py | resolve_all(), multi_hop_retrieve_temporal() |
| benchmarks/mab_reader.py | LLM reader via Anthropic API |
| benchmarks/exp6_score.py | Scoring script |
| docs/EXP6_TEMPORAL_COHERENCE.md | Detailed experiment write-up |

---

## LongMemEval Multi-Session Diagnostics

### Current Score: 24.1% (32/133 correct)

### Failure Breakdown

| Category | Count | % of 101 failures |
|---|---|---|
| Retrieval miss (GT not in context) | 68 | 67% |
| Reasoning fail (GT in context, wrong) | 33 | 33% |

### Retrieval Miss Subcategories

| Question Type | Count | % of 68 misses |
|---|---|---|
| Counting/aggregation | 57 | 84% |
| Non-counting (averages, comparisons) | 11 | 16% |

### What We Tested (and Killed)

#### Hypothesis 1: Budget is too low
- Tested: budget 2000 / 4000 / 8000 on all 133 multi-session questions
- Result: GT-in-context stays at 33.8% at ALL levels
- avg_beliefs barely changes (56 -> 57)
- Verdict: KILLED. Budget is not the bottleneck.

#### Hypothesis 2: top_k caps candidate pool too low
- Tested: top_k 50/100/200 with matching budgets
- Result: GT-in-context stays at 33.8%. Session coverage stays at 65%.
- More beliefs retrieved (55 -> 200) but from same sessions.
- Verdict: KILLED. FTS5 ranks beliefs from missing sessions too low
  regardless of pool size.

#### Hypothesis 3: Per-session sampling ensures session coverage
- Tested: retrieve top 10 beliefs per session by keyword overlap
- Result: Session coverage EQUAL OR WORSE than FTS5 (65% -> 65%).
  Several questions lost session coverage (Q1: 4/4 -> 1/4).
- FTS5's BM25 scoring is smarter than naive keyword overlap.
- No new GT hits found (zero).
- Verdict: KILLED. Naive per-session sampling doesn't help.

#### Hypothesis 4: temporal_sort improves ordering
- Analysis: temporal_sort only re-sorts the same beliefs. It doesn't
  add new beliefs from missing sessions. Since the problem is retrieval
  coverage, not ordering, this won't help.
- Verdict: NOT TESTED (analytically ruled out).

### Root Cause

The multi-session failures are primarily counting/aggregation questions
("how many X", "how much Y") requiring ALL scattered mentions across
3-4 sessions. FTS5 retrieval returns the most relevant passages but
misses 1-2 mentions, leading to undercounting.

The failure pattern is:
- **Off-by-one errors**: GT=3 Pred=2, GT=5 Pred=4 (reader sees most but
  not all items -- retrieval incompleteness)
- **"unknown" predictions**: context too sparse for reader to attempt
  counting (completely wrong retrieval)
- **Near-miss counting**: GT=140 hours Pred=unknown (information is
  scattered across too many turns to aggregate)

### Why This Is Hard

Counting questions are fundamentally adversarial for keyword-based
retrieval. "How many model kits did I work on?" requires finding every
mention of a model kit across every session, including sessions where
model kits were mentioned in passing. FTS5 finds the sessions most
about model kits but misses the session where the user said "I also
picked up a model kit on the way home" in a conversation about something
else.

### Future Levers (Not Implemented)

1. **Embedding-based retrieval**: Semantic similarity would find
   passages about model kits even when "model kit" isn't in the text.
   This is the strongest lever but requires adding a vector store,
   which agentmemory currently avoids by design.

2. **Reader chain-of-thought counting**: Instruct the reader to
   explicitly list each item found before counting. "I found: kit A
   in session 1, kit B in session 2, kit C in session 3. Total: 3."
   This won't help with retrieval misses but may fix off-by-one errors.

3. **Multi-query retrieval**: Decompose counting questions into
   per-entity queries. "Model kits" -> search for "model", "kit",
   "build", "assemble" separately and merge results. More recall at
   cost of precision.

4. **Session-aware FTS5 with diversity bonus**: After initial FTS5
   ranking, re-rank to ensure minimum representation from each session.
   This is the most architecturally sound approach but needs careful
   implementation to avoid diluting relevance.

5. **Accept the ceiling**: 24.1% may be near the FTS5 ceiling for
   counting tasks. The published GPT-4o pipeline achieves 60.6%
   overall but uses embeddings. Focus improvements on categories where
   agentmemory can win (knowledge-update at 70.5%, already competitive).

### Files

| File | Purpose |
|---|---|
| benchmarks/longmemeval_budget_sweep.py | top_k/budget sweep script |
| docs/LONGMEMEVAL_MULTI_SESSION_ANALYSIS.md | Detailed failure analysis |

---

## Other Category Analysis (LongMemEval)

| Category | Score | Analysis |
|---|---|---|
| single-session-user (91.4%) | Strong | Near ceiling |
| single-session-preference (80.0%) | Good | Preference extraction works |
| single-session-assistant (73.2%) | Good | Room for improvement in assistant turn retrieval |
| knowledge-update (70.5%) | Good | SUPERSEDES mechanism helps here |
| temporal-reasoning (59.4%) | Moderate | Would benefit from temporal_sort |
| multi-session (24.1%) | Weak | FTS5 recall ceiling (see above) |

### Temporal Reasoning (59.4%)

Not analyzed in depth this session. Likely benefits from:
- Enabling temporal_sort=True in the adapter
- Better temporal grounding in the query prefix
- Session date metadata more prominently surfaced

This is the second-weakest category and may offer easier gains than
multi-session.

---

## Cross-Benchmark Observations

### What Agentmemory Does Well
- **Structured fact resolution**: MAB SH 90%, entity-index retrieval
- **Direct conflict resolution**: SUPERSEDES mechanism
- **Single-session retrieval**: 70-91% across LongMemEval single-session
- **No-vector-DB architecture**: Competitive with embedding-based systems

### Where It Hits Ceilings
- **Multi-hop chain resolution**: Reader follows latest-serial, GT doesn't
- **Cross-session aggregation**: FTS5 recall insufficient for counting
- **Counterfactual resistance**: Readers use world knowledge ~17% of time

### Key Design Decisions Validated
- FTS5 + entity-index is sufficient for single-hop and most multi-hop
- Regex triple extraction (41 patterns) achieves 100% on structured data
- SUPERSEDES edges work for direct conflict resolution
- No embeddings needed for competitive single-session performance

### Key Design Decisions Challenged
- top_k=50 is adequate for most queries but not cross-session aggregation
- 2000-token budget is fine; retrieval quality is the bottleneck, not budget
- The "highest serial wins" resolution strategy matches human expectation
  for single-hop but diverges from benchmark GT for multi-hop chains

---

## Experiment Index (All Sessions)

| Exp | Finding | Impact |
|---|---|---|
| 1 | MH failure root cause: 58% chaining, 17% world knowledge, 11% retrieval | Directed all work |
| 2 | SUPERSEDES helps SH (+30pp) not MH (+1pp) | Narrowed focus |
| 3 | Triple decomposition: +4pp MH | Foundation for entity-index |
| 4 | Entity-index retrieval: +29pp MH (6% -> 35%) | Core breakthrough |
| 5 | Extended regex +8pp MH, LLM extraction -4pp | Settled regex vs LLM |
| 6 | Temporal coherence: retrieval solved (96%), reader bottleneck (+2pp) | Ceiling identified |

---

## Codebase State at Freeze

- 18 production modules in src/agentmemory/
- 19 MCP tools
- 260+ tests passing
- Strict pyright on all production code
- Benchmark adapters for: MAB, LongMemEval, LoCoMo, StructMemEval
- 6 experiments documented with reproducible scripts
- Contamination-proof benchmark protocol
