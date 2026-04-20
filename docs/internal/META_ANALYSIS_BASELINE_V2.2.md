# Meta-Analysis Baseline: v2.2.0 (2026-04-18)

This document establishes quantitative baselines for user-facing efficiency
metrics. Re-run this analysis after each release to measure trends.

## How to Reproduce

Run `/mem:reason` with the query:
"do full meta analysis on token usage, correction rate, session length, etc
all the user-oriented QoL and usage boosting performance benchmarks"

Then query the session DB directly:

```sql
-- Daily activity summary
SELECT DATE(started_at) as day,
       COUNT(*) as sessions,
       SUM(beliefs_created) as beliefs,
       SUM(corrections_detected) as corrections,
       SUM(searches_performed) as searches,
       SUM(retrieval_tokens) as retrieval_tokens
FROM sessions GROUP BY DATE(started_at) ORDER BY day;

-- Feedback loop health
SELECT DATE(created_at) as day,
       SUM(CASE WHEN outcome='used' THEN 1 ELSE 0 END) as used,
       SUM(CASE WHEN outcome='ignored' THEN 1 ELSE 0 END) as ignored,
       SUM(CASE WHEN outcome='harmful' THEN 1 ELSE 0 END) as harmful,
       COUNT(*) as total,
       ROUND(100.0 * SUM(CASE WHEN outcome='used' THEN 1 ELSE 0 END) / COUNT(*), 1) as used_pct
FROM tests GROUP BY DATE(created_at) ORDER BY day;

-- Confidence distribution
SELECT CASE
    WHEN confidence >= 0.95 THEN 'A (95-100%)'
    WHEN confidence >= 0.90 THEN 'B (90-95%)'
    WHEN confidence >= 0.80 THEN 'C (80-90%)'
    WHEN confidence >= 0.50 THEN 'D (50-80%)'
    ELSE 'F (below 50%)'
  END as grade,
  COUNT(*) as count,
  ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM beliefs WHERE valid_to IS NULL), 1) as pct
FROM beliefs WHERE valid_to IS NULL
GROUP BY grade ORDER BY grade;

-- Token cost per search
SELECT id, started_at, retrieval_tokens,
       CASE WHEN searches_performed > 0
            THEN ROUND(retrieval_tokens * 1.0 / searches_performed, 0)
            ELSE 0 END as tokens_per_search
FROM sessions WHERE retrieval_tokens > 0 ORDER BY started_at;
```

For conversation log analysis, parse JSONL files in `~/.claude/conversation-logs/`
and count correction signals, satisfaction signals, and agentmemory tool call density.

---

## 1. Database State

| Metric | v2.2.0 Baseline |
|--------|-----------------|
| Total beliefs | 19,480 |
| Agent-inferred | 15,763 (80.9%) |
| User-corrected | 3,699 (19.0%) |
| User-stated | 18 (0.1%) |
| Locked beliefs | 2,037 (10.5%) |
| Observations | 18,721 |
| Evidence records | 19,439 |
| Graph edges | 24,202 |
| Orphan rate | 32.7% |
| Sessions tracked | 34 |

## 2. Confidence Distribution

| Band | Count | % |
|------|-------|---|
| A (95-100%) | 621 | 4.0% |
| B (90-95%) | 12,462 | 79.7% |
| C (80-90%) | 81 | 0.5% |
| D (50-80%) | 2,469 | 15.8% |
| F (below 50%) | 0 | 0.0% |

**Note:** 79.7% at default prior (B-grade) indicates the feedback loop had not
been differentiating beliefs. The v2.2.0 fix adds a 0.1 beta increment for
"ignored" outcomes on unlocked beliefs. Future releases should show B-grade
shrinking as beliefs spread into A and C bands based on actual usage patterns.

## 3. Graph Topology

| Edge Type | Count | % |
|-----------|-------|---|
| RELATES_TO | 16,860 | 69.7% |
| SUPPORTS | 3,852 | 15.9% |
| SUPERSEDES | 2,867 | 11.8% |
| CONTRADICTS | 612 | 2.5% |
| SPECULATES | 11 | 0.05% |

## 4. Feedback Loop Health

| Day | Used | Ignored | Harmful | Total | Used % |
|-----|------|---------|---------|-------|--------|
| Apr 12 | 8,354 | 20,520 | 0 | 28,874 | 28.9% |
| Apr 14 | 77 | 633 | 0 | 710 | 10.8% |
| Apr 15 | 0 | 605 | 7 | 612 | 0.0% |
| Apr 16 | 0 | 733 | 0 | 733 | 0.0% |
| Apr 17 | 0 | 101 | 0 | 101 | 0.0% |
| Apr 18 | 0 | 382 | 0 | 382 | 0.0% |

**Known issue at baseline:** "Used" rate dropped to 0% after Apr 15. The
auto-feedback term-matching heuristic is not detecting when retrieved beliefs
are acted on in live sessions. The Apr 12 data was from bulk calibration.
Future releases should show a non-zero used rate.

## 5. Adoption and Correction Rate (from conversation logs)

**Data source:** 52 conversation sessions, Apr 9-18

| Period | AM calls/session | AM density | Correction rate | Beliefs/session |
|--------|-----------------|------------|-----------------|-----------------|
| Early (Apr 9-13) | 2 | 0.9% | 1.3% | 0.5 |
| Late (Apr 13-18) | 6 | 4.2% | 1.1% | 2.8 |

- Adoption tripled (0.9% -> 4.2% of tool calls)
- Correction rate declined 15% (1.3% -> 1.1%)
- Correction detection improved 18x (0.1 -> 1.8 detected/session)

## 6. Token Economics

| Metric | v2.2.0 Baseline |
|--------|-----------------|
| Total retrieval tokens (all sessions) | 126,315 |
| Estimated total session tokens | ~1.1M |
| AM overhead | ~11% |
| Avg tokens/search (early) | ~1,100 |
| Avg tokens/search (late) | ~2,200 |
| Retrieval budget per query | 2,000 |
| Compressed belief size | ~13 tokens avg |
| Meta-cognitive overhead/session | ~2,350 tokens |

## 7. Benchmark Scores (external, standardized)

| Benchmark | Score | Baseline |
|-----------|-------|----------|
| LoCoMo F1 | 66.1% | 51.6% (GPT-4o) |
| MAB Single-Hop | 90% | 45% (paper best) |
| MAB Multi-Hop | 60% | 7% (paper ceiling) |
| StructMemEval | 100% | 29% (v1.0) |
| LongMemEval | 59.0% | 60.6% (GPT-4o) |

## 8. Simulated Impact of v2.2.0 Fixes

### Ignored penalty effect on confidence distribution

| Band | Before fix | Simulated after | Delta |
|------|-----------|-----------------|-------|
| A (95-100%) | 621 (4.0%) | 428 (2.7%) | -193 |
| B (90-95%) | 12,462 (79.7%) | 10,591 (67.7%) | -1,871 |
| C (80-90%) | 81 (0.5%) | 2,085 (13.3%) | +2,004 |
| D (50-80%) | 2,469 (15.8%) | 2,513 (16.1%) | +44 |
| F (below 50%) | 0 (0.0%) | 16 (0.1%) | +16 |

The simulation applies historical ignored counts (0.1 * ignored_count to beta).
The key shift: 2,004 beliefs move from B (default prior) to C (differentiated).

### Session_id propagation fix

- Before: 13 of 19,480 beliefs had session_id
- After: all new beliefs from remember() and correct() will have session_id
- Timeline queries can now use evidence->observation join for historical beliefs

## 9. Known Gaps and Next-Version Targets

| Gap | Metric to Track | Target |
|-----|-----------------|--------|
| Feedback "used" detection broken | Used % per day | > 10% |
| B-grade concentration | % at default prior | < 50% |
| Multi-session accuracy | LongMemEval multi-session | > 50% (from 24.1%) |
| Orphan rate | % beliefs with no edges | < 20% (from 32.7%) |
| Session coverage | % beliefs with session_id | > 80% (from 0.07%) |
| Token cost growth | Avg tokens/search | Stable or declining |
| Correction rate | % user messages that are corrections | < 1.0% (from 1.1%) |

## 10. Prior Reports and Protocol Alignment

This baseline builds on several prior analyses. For apples-to-apples comparison
across versions, use the same metrics and methods as these established reports.

### Prior Baselines

| Report | Date | Key Metrics | Location |
|--------|------|-------------|----------|
| Memory Quality Audit | Apr 11 | DB inventory, confidence dist, source types | research/MEMORY_QUALITY_AUDIT.md |
| Exp 6 Phase C | Apr 9 | Override rate/day (OVERRIDES.md ground truth) | experiments/exp6_historical_analysis.md |
| Exp 58b | Apr 10 | Correction prevention rate (top-K, 218 decisions) | experiments/exp58b_results.md |
| Exp 58c | Apr 10 | Velocity-scaled decay, maturity inflation | experiments/exp58c_results.md |
| Exp 64 | Apr 12 | Token budget sweep, compilation vs on-demand | experiments/exp64_preprompt_compilation_results.md |
| Benchmark Suite | Apr 14 | LoCoMo, MAB, StructMem, LongMem scores | docs/BENCHMARK_RESULTS.md |
| Wonder Baseline | Apr 16 | Wonder precision (24% on 15K beliefs) | docs/WONDER_BASELINE.md |
| Design vs Reality | Apr 11 | 32-point scorecard, built vs promised | research/DESIGN_VS_REALITY.md |

### Metric Lineage

| This Report's Metric | Prior Protocol | How to Compare |
|----------------------|----------------|----------------|
| Correction rate (1.1%) | Exp 6 override rate (1.80/day) | Exp 6 uses OVERRIDES.md ground truth; this report uses keyword detection in JSONL. Not directly comparable -- Exp 6 is higher fidelity |
| Confidence distribution | MEMORY_QUALITY_AUDIT (98.4% at 0.90) | Same SQL query, same bands. Apr 11: 98.4% at default. Apr 18: 79.7% at default. Shows 3,413 beliefs differentiated |
| Token cost per search | Exp 64 (23.1% at 2K budget) | Exp 64 measures coverage; this report measures raw token count. Complementary, not redundant |
| Feedback "used" rate | No prior equivalent | New metric introduced here. Track going forward |
| AM adoption density | No prior equivalent | New metric from JSONL log analysis. Track going forward |
| DB inventory | MEMORY_QUALITY_AUDIT | Same format. Compare directly: beliefs 16,067 -> 19,480 (+21%), edges 33,151 -> 24,202 (schema change), sessions 0 -> 34 |

### Version Comparison (DB Inventory)

| Metric | Apr 11 (Audit) | Apr 18 (v2.2.0) | Delta |
|--------|---------------|-----------------|-------|
| Total beliefs | 16,067 | 19,480 | +3,413 (+21%) |
| Locked beliefs | 1 | 2,037 | +2,036 |
| Observations | 15,492 | 18,721 | +3,229 (+21%) |
| Sessions | 0 | 34 | +34 |
| Tests (feedback) | 0 | 31,412 | +31,412 |
| Confidence at default | 98.4% | 79.7% | -18.7pp |
| User-stated beliefs | 2 | 18 | +16 |

### What to Run for Next Version

1. Re-run the SQL queries in Section "How to Reproduce" above
2. Re-run the Exp 6 override detection if new OVERRIDES data exists
3. Re-run benchmark suite (docs/BENCHMARK_PROTOCOL.md)
4. Parse latest conversation logs for adoption/correction metrics
5. Compare all tables against this document's values

## 11. Methodology Notes

- Session DB: `~/.agentmemory/projects/2e7ed55e017a/memory.db`
- Conversation logs: `~/.claude/conversation-logs/*.jsonl`
- Correction detection in logs: keyword matching ("no", "wrong", "not that", etc.)
- Satisfaction signals: positive ("perfect", "yes", "good") and negative markers
- Token estimates from message counts, not exact API usage
- All session durations are wall-clock time from first to last event
- Simulated confidence shifts assume uniform 0.1 beta per historical ignore
