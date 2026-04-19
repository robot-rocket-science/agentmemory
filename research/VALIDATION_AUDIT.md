# Validation Audit: What Do We Actually Know?

**Date:** 2026-04-09
**Purpose:** Ruthless self-examination of every claim we've made. For each finding, ask: is the methodology sound? Are there bugs? Could this be a false positive? What's missing from the model?

---

## Experiment 2/5/5b: Bayesian Confidence Model

### Claim: Thompson + Jeffreys Beta(0.5, 0.5) passes both REQ-009 (ECE=0.066) and REQ-010 (exploration=0.194)

**Methodology check:**
- [x] Hypothesis stated before running
- [x] 100 independent trials with different seeds
- [x] Control group (uniform prior) run with same seeds
- [x] Calibration metric bug found and fixed (IGNORED denominator)
- [x] Multiple conditions compared (4 in Exp 5b)

**Potential issues:**
- [ ] **The simulation assumes all beliefs are equally relevant (relevance=1.0).** In reality, most beliefs are irrelevant to any given query. Does Thompson sampling still work when relevance varies? We haven't tested this.
- [ ] **Outcome simulation is Bernoulli with fixed true rates (0.85, 0.65, 0.45, 0.55).** Real usefulness rates aren't fixed -- they depend on the query context. A belief about database config is useful for database tasks (rate ~0.9) and useless for CSS tasks (rate ~0.0). Our simulation doesn't capture this context-dependence.
- [ ] **The 30% IGNORED rate is a guess.** We assumed 30% of retrievals are ignored. The real rate could be higher or lower. We showed this matters (Exp 2c: ECE varies from 0.028 at 0% to 0.277 at 50%). But we don't know the actual production IGNORED rate.
- [ ] **We only tested with 200 beliefs and 50 sessions.** Real usage could have 10K+ beliefs and hundreds of sessions. Scaling behavior is unknown.
- [ ] **The exploration metric (median-relative entropy) has a known flaw** -- it's a moving target. We noted this but still used it. The absolute entropy values from our _digamma approximation are wrong for small inputs. We used median-relative comparison which works despite wrong absolute values, but this is fragile.

**What's missing from the model:**
- Context-dependent relevance (a belief's usefulness depends on the task)
- Non-stationary true rates (beliefs become wrong over time)
- Correlated beliefs (updating one should affect related beliefs)
- The actual retrieval step (we tested ranking in isolation, not end-to-end retrieval)

**Verdict:** The core finding (Thompson + Jeffreys works better than alternatives) is likely robust because it held across multiple conditions. But the absolute ECE number (0.066) should be treated as approximate -- real-world performance will differ due to the simplifications above.

**Action items:**
- [ ] Test with variable relevance (not all 1.0)
- [ ] Test with context-dependent true rates
- [ ] Fix the _digamma approximation for small inputs
- [ ] Test at larger scale (1K+ beliefs)

---

## Experiment 6: Historical Analysis

### Claim: 79% of user overrides cluster into 6 repeated failure topics

**Methodology check:**
- [x] Data source is ground truth (OVERRIDES.md written by the user in real time)
- [x] Parsing is mechanical (regex on structured markdown)
- [x] Topic clustering uses keyword matching (transparent, auditable)

**Potential issues:**
- [ ] **Topic assignment is manual.** I defined the 10 topic categories and their keywords by reading the overrides. A different researcher might cluster them differently. The 79% number depends on my topic definitions.
- [ ] **Some overrides were miscategorized.** The dispatch_gate cluster (13 overrides) includes some that are about server-a vs GCP compute, contract filters, and annualized returns -- not strictly "dispatch gate." The keyword matching is too broad. D103 (annualized returns) and D118 (no artificial filters) got pulled into the dispatch cluster because they matched keywords like "gate" or "dispatch" in the scope text.
- [ ] **6 uncategorized overrides were not analyzed.** What are they? Do they reveal additional failure patterns?
- [ ] **The database (project-a.db) is a stale snapshot from April 6.** D209 doesn't exist in it. Other recent decisions may also be missing.

**What's missing:**
- Inter-rater reliability (only one person defined the clusters)
- Analysis of the 6 uncategorized overrides
- Verification that the keyword matching didn't pull in false matches
- The full decision files (180 in gsd-archive) were used for OVERRIDES.md parsing but not for the similarity analysis in Phase B v1

**Verdict:** The qualitative finding (users repeatedly correct agents on the same topics) is unambiguous -- you can read the overrides and see it. The quantitative claim (79%, 6 clusters) depends on clustering methodology and should be verified by re-examining each match.

**Action items:**
- [x] Review each of the 13 "dispatch_gate" overrides and remove false matches (DONE 2026-04-09: 13 -> 7. Five false matches: gcp_primary(1), code_org(1), reporting(1), no_artificial_filters(2). One partial.)
- [x] Analyze the 6 uncategorized overrides (DONE: 5 new single-override topics identified: code_organization, reporting_format, no_artificial_filters(2), backtesting_protocol, citation_sources)
- [x] Re-run with tighter keyword matching and report revised numbers (DONE: overall 79% -> ~66% in multi-override clusters. Core finding holds.)
- [ ] Have the user verify the cluster assignments (pending)

---

## Experiment 4: Token Budget

### Claim: 93% critical belief coverage at 1,000 tokens, sufficient at 2K (REQ-003)

**Potential issues:**
- [ ] **D209 was flagged as "not found due to vocabulary mismatch" but actually doesn't exist in the database.** The database is a snapshot from April 6; D209 was created later. This isn't a retrieval failure -- it's a data coverage problem. The 93% ceiling is an artifact of stale data, not a real limitation.
- [ ] **Only 6 failure topics tested with 14 critical decisions.** This is a very small sample. The 93% number has wide confidence intervals.
- [ ] **Query terms were chosen by me, not derived systematically.** A different set of query terms for the same topics might produce different coverage. For example, "capital 5000 hard cap" might find D099 at lower budgets than "capital bankroll amount."
- [ ] **Token estimation uses chars/4** which is a rough heuristic. Real tokenization varies by model.

**What's missing:**
- Testing with the full gsd-archive (180 decisions, not just 173 in the spike DB)
- Sensitivity analysis on query term selection
- Real tokenization instead of chars/4 estimation

**Verdict:** The directional finding (1K tokens is roughly sufficient for critical beliefs) is probably right, but the specific numbers are approximate. The D209 "failure" was a false negative in our experiment, not a real retrieval problem.

**Action items:**
- [x] Correct the D209 finding in documentation -- it's missing data, not vocabulary mismatch (FIXED 2026-04-09: Exp 4 script updated to use D099 only. D209 references in REQ-020 rationale are valid -- D209 exists in the real project, just not the spike DB.)
- [ ] Re-run with the gsd-archive as the data source instead of the spike DB
- [ ] Test with multiple query formulations per topic

---

## Design Decisions: What Have We Actually Proven vs Assumed?

| Decision | Status | Evidence Quality |
|----------|--------|-----------------|
| Scientific method model (observe/believe/test/revise) | **Assumed, not tested** | Conceptually sound but no experiment validates this over human memory categories |
| Thompson sampling for ranking | **Tested in simulation** | Passes requirements in simplified simulation. Not tested with real retrieval. |
| Jeffreys prior Beta(0.5, 0.5) | **Tested in simulation** | Better than alternatives in simulation. Not tested in production. |
| L0/L1 always-loaded context | **Supported by evidence** | Exp 6 shows manual version (CLAUDE.md) reduced overrides 49%. |
| Session recovery as priority | **Supported by user experience** | User reported 90% recovery with MemPalace after 2 crashes. Not our system. |
| Zero-LLM extraction | **Tested on real data (#20)** | 87% of overrides produce beliefs, but only 26% detected as corrections. Pipeline misses short imperative statements and can't distinguish corrections from statements. Classification too coarse (60% labeled "factual"). See experiments/exp1_overrides_results.json. |
| Single-correction learning (REQ-019) | **Derived from evidence, not tested** | Exp 6 shows the need. Implementation doesn't exist. |
| Locked beliefs (REQ-020) | **Derived from evidence, not tested** | D100 and D209 show the need. Implementation doesn't exist. |
| `remember` and `correct` tools | **Designed, not tested** | MCP tool interface defined. No implementation. |
| Cross-model via MCP | **Assumed** | Standard protocol but untested with our system. |
| Privacy/local-only (REQ-017, 018) | **Stated, not designed** | No architecture review for privacy. No threat model. |
| Holographic/info-theoretic approaches | **Researched, not applied** | Papers found, connections identified, zero implementation or testing. |

---

## What Should We Investigate Next?

Ordered by what would most improve our confidence in the design:

1. **Variable-relevance Thompson sampling test** -- does ranking still work when beliefs have different relevance to different queries? This is the biggest gap in our Bayesian validation.

2. **Clean up Exp 6 clustering** -- verify the 79% number by reviewing each match. Remove false positives from dispatch_gate cluster. Analyze uncategorized overrides.

3. **Extraction quality on real data** -- run the zero-LLM pipeline on OVERRIDES.md text. Can it identify corrections? This tests REQ-014 and REQ-019 simultaneously.

4. **Privacy architecture** -- REQ-017/018 are stated but the architecture doesn't address them. Need a threat model: what data flows exist? Where are the exfiltration risks?

5. **Information-theoretic retrieval** -- the vocabulary mismatch (even though D209 was a data problem, the general issue is real) suggests FTS5 alone is insufficient. Test whether MinHash, mutual information, or lightweight embeddings help without violating zero-LLM default.
