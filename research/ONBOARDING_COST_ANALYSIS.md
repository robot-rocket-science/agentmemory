# Onboarding Cost Analysis

**Date:** 2026-04-11
**Method:** Computed from validation data at /tmp/agentmemory-validation/ (offline and LLM DBs), classification.py batch size, and Haiku pricing.

---

## Q1: How Long Does LLM Onboarding Take?

### Parameters

- Scanner time: measured offline (no LLM) -- pure scan + extract + insert
- Batch size: 20 sentences (from `_BATCH_SIZE` in classification.py)
- Haiku latency: ~1.5s per batch (midpoint of 1-2s observed range)
- Insert overhead: ~10% of scan time (SQLite writes are fast)

### Time Estimates

| Repo | Sentences | Batches | Offline (s) | LLM est. (s) | LLM (min) | Ratio |
|---|---|---|---|---|---|---|
| project-d | 5,595 | 280 | 2.2 | 422 | 7.0 | 192x |
| project-f | 8,173 | 409 | 4.3 | 618 | 10.3 | 144x |
| bigtime | 1,427 | 72 | 0.6 | 109 | 1.8 | 181x |
| mud_rust | 247 | 13 | 0.3 | 20 | 0.3 | 66x |

**Formula:** `LLM_time = scan_time + (batches * 1.5s) + (scan_time * 0.1)`

The LLM call dominates. For a 500-commit repo (project-d), onboarding takes ~7 minutes. For a small repo (mud_rust, 5 commits), ~20 seconds.

### Parallelism Opportunity

Batches are currently sequential (classification.py iterates with a for-loop). Async batching with 5-10 concurrent requests would cut project-d from 7 min to ~1 min and project-f from 10 min to ~2 min. This is the obvious optimization if onboarding time becomes a concern.

---

## Q2: What Does LLM Onboarding Cost?

### Parameters

- Prompt template: ~1,076 chars (~270 tokens)
- Sentence block (20 sentences): ~1,600 chars (~400 tokens)
- Total input per batch: ~669 tokens
- Response (20 JSON items): ~252 tokens per batch
- Haiku pricing (Claude Haiku 4.5): $0.80/MTok input, $4.00/MTok output

### Cost Table

| Repo | Sentences | Batches | Input tokens | Output tokens | Cost |
|---|---|---|---|---|---|
| project-d | 5,595 | 280 | 187,320 | 70,700 | $0.43 |
| project-f | 8,173 | 409 | 273,621 | 103,272 | $0.63 |
| bigtime | 1,427 | 72 | 48,168 | 18,180 | $0.11 |
| mud_rust | 247 | 13 | 8,697 | 3,282 | $0.02 |
| **TOTAL** | **15,442** | **774** | **517,806** | **195,435** | **$1.20** |

**Average cost per project: $0.30** (matches the estimate in ONBOARDING_VALIDATION_RESULTS.md).

### Comparison to Prior Estimates

| Source | Estimate | Context |
|---|---|---|
| Exp 50 (entity classification) | 2,650 tokens / $0.001 per project | Entity classification only (100 items), not full sentence classification |
| Exp 61 (classification pipeline) | $0.001 per batch of 20 | Per-batch cost, correct -- scales linearly with sentences |
| ONBOARDING_VALIDATION_RESULTS.md | $0.30/project via Haiku | Rough average, confirmed by this analysis |
| **This analysis** | **$0.02 - $0.63 per project** | Full sentence-level classification, 4 real repos |

The Exp 50 "$0.001/project" figure was for entity classification of ~100 hard-case items, not full onboarding. Full onboarding classifies thousands of sentences and costs 20-630x more. The $0.001/batch figure from Exp 61 is accurate -- the total cost is just batches * $0.001.

### Cost Scaling Model

For a project with N sentences:
- Batches = ceil(N / 20)
- Cost = batches * ($0.80 * 669 / 1M + $4.00 * 252 / 1M) = batches * $0.00154
- Simplified: **~$0.0015 per batch, or ~$0.077 per 1,000 sentences**

Typical project sizes from our survey:
- Small (5-15 commits): 200-1,500 sentences, $0.02-$0.11
- Medium (100-500 commits): 5,000-8,000 sentences, $0.40-$0.63
- Large (2,000+ commits): ~20,000+ sentences, ~$1.50+

### ROI Context

From CORRECTION_BURDEN_REFRAME.md and Exp 50:
- Each false locked belief costs ~500 tokens to correct (user notices, explains, agent processes)
- Offline classifier produces 80-96% false locks (validated)
- project-d: 417 offline locks vs 69 LLM locks = 348 prevented false locks
- Correction cost prevented: 348 * 500 = 174,000 tokens
- LLM cost to prevent: 258,020 tokens (187K input + 71K output)
- **Single-session ROI: 0.67x** (cost ~= savings)
- **10-session ROI: 6.7x** (false locks recur every session)
- The real win is preventing permanent memory pollution, not token savings

---

## Summary

| Metric | Value |
|---|---|
| LLM onboarding time (typical) | 1-10 minutes (sequential batching) |
| LLM onboarding time (with async) | 15s - 2 min (5-10x parallelism) |
| Cost per project | $0.02 - $0.63 |
| Cost per 1,000 sentences | ~$0.08 |
| Cost scaling | Linear in sentence count |
| Offline/LLM time ratio | 66-192x |
| ROI (single session) | ~1x |
| ROI (10 sessions) | ~7x |
| Primary value | False lock prevention (80-96% reduction) |
