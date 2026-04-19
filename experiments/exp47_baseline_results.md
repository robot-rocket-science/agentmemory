# Experiment 47: Baseline Comparison -- Can We Beat Grep?

**Date:** 2026-04-10
**Status:** Complete
**Rigor tier:** Empirically tested (real project-a corpus, 586 nodes, 6 topics, 13 decisions)
**Depends on:** Exp 9/39 (ground truth), Exp 40 (hybrid pipeline)

---

## Summary

**Grep beats our architecture on the current test set.** 92% coverage vs 85% for FTS5 and FTS5+HRR. The null hypothesis is NOT rejected -- grep is a serious competitor on this corpus.

---

## Results

### Per-Topic Coverage

| Topic | Grep(Dec) | Grep(Sent) | FTS5 | FTS5+PRF | FTS5+HRR |
|-------|----------|-----------|------|---------|---------|
| dispatch_gate | **100%** | **100%** | 67% | 67% | 67% |
| calls_puts | **100%** | **100%** | **100%** | 67% | **100%** |
| capital_5k | **100%** | **100%** | **100%** | **100%** | **100%** |
| agent_behavior | 50% | 50% | 50% | 50% | 50% |
| strict_typing | **100%** | **100%** | **100%** | **100%** | **100%** |
| gcp_primary | **100%** | **100%** | **100%** | **100%** | **100%** |

### Aggregate

| Method | Coverage | Tokens | Precision | MRR |
|--------|---------|--------|-----------|-----|
| A. Grep (decisions) | **92%** (12/13) | 616 | **21%** | 0.708 |
| B. Grep (sentences) | **92%** (12/13) | 639 | 14% | 0.708 |
| C. FTS5 | 85% (11/13) | **547** | 12% | 0.589 |
| D. FTS5+PRF | 77% (10/13) | 520 | 11% | **0.792** |
| E. FTS5+HRR | 85% (11/13) | 576 | 12% | 0.589 |

---

## Hypothesis Evaluation

### H1: Grep achieves < 80% coverage
**REJECTED.** Grep achieves 92% (12/13). Grep's exact substring matching finds "dispatch" in D137 where FTS5's porter stemmer doesn't match (porter stems "dispatch" differently from "dispatching").

### H2: FTS5 achieves >= 92% coverage
**REJECTED.** FTS5 achieves 85% (11/13). It misses D137 (dispatch_gate) and D157 (agent_behavior). D137 is a stemming issue; D157 is the known vocabulary gap.

### H3: FTS5+HRR achieves 100% coverage
**REJECTED.** FTS5+HRR achieves 85% (11/13). Same misses as FTS5. The HRR behavioral partition is over capacity (306 edges, capacity 204) because the directive pattern scan found 18 behavioral nodes instead of the 11 used in Exp 40. At 1.5x over capacity, HRR noise drowns the D157 signal.

### H4: Grep returns >= 3x more tokens than FTS5+HRR
**REJECTED.** Grep returns 616 tokens vs FTS5+HRR at 576. Only 1.07x more. Both are well under the 2K budget.

### H5: Grep precision < 30% while FTS5+HRR precision >= 50%
**PARTIALLY CONFIRMED.** Grep precision is 21% (under 30%), but FTS5+HRR precision is 12% (far below 50%). Neither method achieves good precision at K=15.

### Null Hypothesis: Grep >= 92% with comparable token efficiency
**NOT REJECTED.** Grep achieves 92% at 616 tokens. Our architecture achieves 85% at 576 tokens. Grep wins on coverage; token efficiency is comparable.

---

## Root Cause Analysis

### Why grep beats FTS5 (D137)

D137 contains "dispatch" as an exact substring. The query "dispatch gate deploy protocol" matches it via grep. FTS5 with porter stemming stems "dispatch" to "dispatch" and "dispatching" to "dispatch" -- but the match fails because FTS5's OR query scores D137 low (only 1 of 4 terms matches) and other nodes with more term matches rank higher, pushing D137 below K=15.

This is a ranking problem, not a matching problem. FTS5 finds D137 at rank > 15. Grep finds it because grep doesn't rank -- it returns everything that matches, and with only 10 matches total, D137 is within K=15.

**Fix:** Increase K for FTS5, or use FTS5 with a lower threshold + re-ranking.

### Why HRR didn't rescue D157

Exp 40 used 11 behavioral nodes (110 edges, within DIM=2048 capacity of ~204). This experiment's directive pattern scan found 18 behavioral nodes (306 edges, 1.5x over capacity). The superposition is noisy and HRR can't distinguish D157 from the noise.

**Fix:** Either (a) limit the behavioral partition to manually curated nodes, (b) increase DIM to 4096 (capacity ~409, covers 306 edges), or (c) split behavioral nodes into sub-partitions by type (tool bans, style directives, process rules).

### Why PRF hurt coverage

PRF's expansion terms diluted the query for calls_puts. The top-5 results from pass 1 introduced terms that pushed D100 ("STOP BRINGING IT UP") below the threshold. D100's content is dominated by emotional emphasis, not topical keywords, so expansion terms from other calls/puts results don't help retrieve it.

---

## What This Means for the Project

### The bad news
1. Grep beats us on coverage. Simple substring matching with no ranking outperforms BM25 with stemming on this test set.
2. HRR's vocabulary bridge fails when the behavioral partition is realistic (18 nodes instead of 11).
3. PRF actively hurts coverage on emotional/emphatic content.
4. All methods miss D157. The vocabulary gap is still unsolved at this scale.

### The context
1. The test set is small (6 topics, 13 decisions, 586 nodes). Grep's advantage may not hold at 10K+ nodes where its lack of ranking becomes a liability.
2. Grep's "advantage" on D137 is that it doesn't rank. At larger K, FTS5 also finds D137. The real question is whether ranking is worth the cost of occasionally pushing relevant results below the cutoff.
3. The HRR capacity issue has a known fix (DIM=4096 or sub-partitioning). It's an engineering parameter, not a fundamental limitation.
4. All methods achieve coverage well above the 80% REQ-001 threshold on 5/6 topics. The gap is entirely on the 2 hardest cases (D137, D157).

### What to do about it
1. **Don't dismiss grep.** It should be the Phase 0 baseline and the bar to clear. If our full architecture can't beat grep at 10K nodes, we have a problem.
2. **Fix the HRR capacity issue.** Test DIM=4096 with the full 18-node behavioral set. If that restores D157 recovery, the architecture is sound.
3. **Fix the FTS5 ranking cutoff for D137.** Either increase K, use a multi-pass strategy (grep for broad recall, FTS5 for ranking), or combine grep + FTS5 scores.
4. **Run at 10K nodes.** Grep's O(n) scan with no ranking will degrade. FTS5's BM25 ranking will shine. HRR's structural retrieval will provide unique value. The comparison at 586 nodes may not predict the comparison at scale.

---

## Limitations

- 586 decision-level nodes, not 1,195 sentence-level (sentence decomposition from Exp 16 was never stored to DB)
- 6 topics / 13 decisions ground truth. Broader evaluation needed.
- No task-level evaluation (does better retrieval produce better agent responses?)
- Grep "wins" partly because K=15 is generous relative to the 586-node corpus (grep returns all matches, and the corpus is small enough that few matches exist per query)
