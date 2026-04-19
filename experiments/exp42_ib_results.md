# Experiment 42: Information Bottleneck Compression -- Empirical Validation

**Date:** 2026-04-10
**Input:** Exp 16 sentence nodes (1,195 nodes from 173 decisions, 35,741 tokens)
**Builds on:** Exp 20 (IB theory), Exp 16 (sentence decomposition), Exp 9/39 (retrieval ground truth)
**Method:** Simulated on real project-a belief corpus. Zero-LLM.
**Rigor tier:** Empirically tested (real data, single dataset)

---

## Q1: Does Type-Aware Compression Preserve Retrievability?

**Result: Yes. 100% retrieval coverage preserved under type-aware compression.**

| Strategy | Coverage | Nodes Found | Nodes Needed |
|----------|----------|-------------|--------------|
| Full (no compression) | 100% | 13/13 | 13 |
| Type-compressed | 100% | 13/13 | 13 |
| Keyword-only | 100% | 13/13 | 13 |

Per-topic breakdown (all 6 topics at 100% across all 3 strategies):

| Topic | Full | Compressed | Keywords |
|-------|------|------------|----------|
| dispatch_gate | 100% | 100% | 100% |
| calls_puts | 100% | 100% | 100% |
| capital_5k | 100% | 100% | 100% |
| agent_behavior | 100% | 100% | 100% |
| strict_typing | 100% | 100% | 100% |
| gcp_primary | 100% | 100% | 100% |

**Why this works:** FTS5 with porter stemming is token-based. Even aggressively truncated nodes retain the discriminative tokens (proper nouns, domain terms, decision IDs) that drive FTS5 matching. Context sentences like "Contract selection constraint, not exit target" truncated to "Contract" still participate in multi-term OR queries where sibling sentences from the same decision carry the discriminative terms.

**Caveat:** This tests 6 topics with 3 queries each (18 queries total). The ground truth covers the most critical beliefs but not the full corpus. Edge cases (beliefs retrievable only via terms appearing late in a long sentence) could still be affected. The test is necessary-but-not-sufficient.

---

## Q2: Token Savings

**Result: 55% reduction (35,741 -> 15,926 tokens) with zero retrieval loss.**

| Type | Count | Full Tokens | Compressed | Actual Ratio | Target Ratio |
|------|-------|-------------|------------|--------------|--------------|
| constraint | 132 | 4,839 | 4,839 | 1.00 | 1.0 |
| evidence | 349 | 12,152 | 6,579 | 0.54 | 0.6 |
| context | 585 | 14,142 | 3,315 | 0.23 | 0.3 |
| rationale | 39 | 1,721 | 613 | 0.36 | 0.4 |
| supersession | 47 | 1,470 | 233 | 0.16 | pointer |
| implementation | 43 | 1,417 | 347 | 0.24 | 0.3 |
| **TOTAL** | **1,195** | **35,741** | **15,926** | **0.45** | -- |

**Token savings: 19,815 tokens (55% reduction).**

Actual ratios run slightly below targets because truncation at word boundaries often cuts a few extra tokens. Supersession nodes compress to 16% (pointer format averages ~5 tokens vs original ~31).

**REQ-003 compliance analysis:**

The 2,000-token budget applies to retrieval results injected into context, not the full stored corpus. At 13.3 tokens per compressed node on average, the system can fit ~150 compressed nodes into the 2K budget. Since typical retrieval returns 10-30 relevant nodes per query, this is comfortable. Even at 30 nodes, retrieval payload would be ~400 tokens (well under budget).

For the full corpus to fit in 2K (if we ever needed that for L0 always-loaded context), we would need to select ~150 of 1,195 nodes. The 132 constraint nodes alone are 4,839 tokens -- already over budget. This confirms that L0 must be a curated subset, not the compressed full corpus.

**Comparison to Exp 20 predictions:**

Exp 20 estimated 30-38% reduction to ~22K-25K tokens. We achieved 55% reduction to ~16K. The difference: Exp 20 assumed conservative compression targets. The empirical test showed context nodes can be compressed harder (0.23x actual vs 0.3x target) without retrieval loss, because FTS5 does not need readable text.

---

## Q3: Does Full IB Optimization Add Value Over the Heuristic?

**Result: Marginal. All 6 types show high within-type variance (CV > 0.5), but this does not translate to retrieval benefit.**

| Type | Count | Mean Tokens | Std | CV | Min | Max | IQR |
|------|-------|-------------|-----|-----|-----|-----|-----|
| constraint | 132 | 36.7 | 28.4 | 0.774 | 9 | 293 | 23-42 |
| context | 585 | 24.2 | 14.9 | 0.616 | 3 | 104 | 13-31 |
| evidence | 349 | 34.8 | 21.7 | 0.622 | 5 | 169 | 21-42 |
| implementation | 43 | 33.0 | 18.9 | 0.575 | 5 | 88 | 20-38 |
| rationale | 39 | 44.1 | 27.8 | 0.630 | 12 | 175 | 28-53 |
| supersession | 47 | 31.3 | 27.1 | 0.868 | 3 | 114 | 12-43 |

**Interpretation:**

Every type has CV > 0.5, meaning the coefficient of variation is high. In theory, this suggests per-node IB optimization (rather than per-type) could tailor compression better. In practice:

1. **The variance is in node LENGTH, not node IMPORTANCE.** A 9-token constraint and a 293-token constraint are both fully preserved (ratio 1.0). The variance does not affect the compression decision -- it only affects how many tokens each node contributes to the total. Full IB would not change the constraint ratio.

2. **For compressible types (context, rationale, implementation), variance means some nodes are already short.** A 3-token context node cannot be compressed further. A 104-token context node has room. But the heuristic already handles this: truncation to 30% of a 3-token node yields 1 token (floor), while 30% of 104 tokens yields 31 tokens. The ratio-based heuristic is already adaptive to length.

3. **Where full IB WOULD help:** If some context nodes have high query relevance (should be preserved) while most have low relevance (can be discarded). The type heuristic treats all context nodes the same. Full IB with a learned relevance model p(y|x) could identify the 10% of context nodes that are actually important and preserve those while compressing the rest harder. This is the one area where full IB has genuine upside.

**Estimated marginal gain of full IB over heuristic:** 0-5% additional token savings with identical retrieval quality. Not worth the engineering cost at current scale (1K nodes). Revisit if the corpus exceeds 10K nodes or if the 2K token budget becomes binding.

**Verdict: The heuristic is sufficient. Full IB is not justified.**

---

## Q4: IB-to-HRR Dimension Mapping

**Result: The SNR floor (D >= 625) dominates over the information capacity floor for most types. Only constraints require D > 625 from an information standpoint.**

| Type | Compressed Tokens | IB Bits | Min Dim (SNR) | Min Dim (Info) | Binding |
|------|-------------------|---------|---------------|----------------|---------|
| constraint | 36.7 | 587 | 625 | 1,174 | 1,174 |
| evidence | 20.9 | 334 | 625 | 668 | 668 |
| context | 7.3 | 116 | 625 | 232 | 625 |
| rationale | 17.6 | 282 | 625 | 564 | 625 |
| supersession | ~5 | ~80 | 625 | ~160 | 625 |
| implementation | 9.9 | 158 | 625 | 317 | 625 |

**Assumptions:**
- SNR target = 5.0 (reliable single-hop retrieval, from Exp 35)
- Edges per node = 25 (observed neighborhood size in project-a graph)
- Bits per token ~ 16 (4 bits/char * 4 chars/token, conservative for English)
- HRR information capacity ~ D/2 bits per superposition slot (Johnson-Lindenstrauss bound)

**Analysis:**

Two floors determine minimum HRR dimension:

1. **SNR floor:** D >= SNR_target^2 * num_edges = 25 * 25 = 625. This ensures a single edge in a 25-edge superposition is reliably retrievable. This is independent of content.

2. **Information capacity floor:** D >= 2 * IB_bits. This ensures the HRR vector can faithfully represent the compressed belief's information content. For constraints (587 bits), this requires D >= 1,174.

**The binding constraint differs by type:**
- **Constraints** are information-bound (D >= 1,174). Their full content must be encoded because they are preserved at 1.0x. At DIM=2048 (current setting from Exp 31), we have 2048/2 = 1024 bits of capacity. This is below the 1,174-bit requirement, meaning some constraint information may alias. At DIM=4096, capacity = 2048 bits, which clears the bar.
- **All other types** are SNR-bound (D >= 625). Their compressed content fits comfortably within the HRR capacity at any dimension >= 625.

**Connection to Exp 35 findings:** Exp 35 found that DIM=2048 works for single-hop but struggles with 2-hop for single-path targets. The IB analysis gives a complementary explanation: DIM=2048 is sufficient for SNR but may be tight for information capacity of high-content nodes. DIM=4096 resolves both the SNR issue (SNR = sqrt(4096/25) = 12.8) and the information capacity issue (2048 bits > 1174 bits for constraints).

**Recommendation for Exp 36 (HRR dimensions):** DIM=2048 is the practical minimum. DIM=4096 is the theoretically safe choice for full-fidelity constraint encoding. The IB analysis suggests this is not a coincidence -- the dimension that resolves multi-hop SNR also resolves information capacity for the most information-dense node type.

---

## Q5: Retrieval-Aware vs Readability Compression

**Result: Zero retrieval losses detected across all three compression strategies on the 6-topic ground truth.**

This means keyword-only compression (removing stopwords and function words) preserves 100% of FTS5 retrievability. The question becomes: when does the agent need to READ the node versus just FIND it?

**Two-mode model:**

| Mode | Purpose | Compression | Content Requirement |
|------|---------|-------------|---------------------|
| FIND | Rank candidates in retrieval | Keyword-only or truncated | Discriminative tokens only |
| READ | Inject into agent context | Human-readable | Full or type-compressed |

**When READ is needed:**
- L0 (always-loaded): Agent must understand constraints. Full text required for constraint nodes. This is ~4,839 tokens (over budget for L0 alone -- needs selection).
- L1 (topic-loaded): Agent reads evidence and context to make decisions. Type-compressed text is acceptable here -- the core claim is preserved, elaboration is dropped.
- L2 (on-demand): Agent reads specific nodes requested by query. Full text is appropriate since the retrieval already selected them.

**When FIND is sufficient:**
- Initial retrieval ranking (FTS5 score computation)
- Deduplication and clustering of results
- Graph traversal (HRR similarity, not content inspection)

**The dual-representation approach:**

Store both representations:
1. Full text in the belief store (immutable, per PLAN.md)
2. Keyword index in FTS5 (for retrieval ranking)

At retrieval time, FTS5 uses the keyword/compressed representation for ranking. Once top-k nodes are selected, full text is loaded for context injection. This separates the FIND concern (token-efficient) from the READ concern (human-readable).

**Token impact:** The keyword representation (29,155 tokens) is actually LARGER than the type-compressed representation (15,926 tokens) because keywords retain content words but the type-aware heuristic truncates aggressively. For FTS5 indexing, the stored representation does not count against the retrieval token budget -- only the returned text does. So the question is what format to return in the retrieval payload, not what format to index.

**Verdict:** Index the full text in FTS5 (costs disk, not context tokens). Return type-compressed text in the retrieval payload. This gives best-of-both: full-fidelity search with token-efficient injection.

---

## Summary of Findings

| Question | Answer | Evidence |
|----------|--------|----------|
| Q1: Does type-aware compression preserve retrievability? | Yes, 100% | 13/13 critical beliefs found across all 6 topics |
| Q2: How much token savings? | 55% reduction (35.7K -> 15.9K) | Per-type breakdown in results table |
| Q3: Does full IB add value? | Marginal (0-5% est.) | High within-type CV, but variance is in length not importance |
| Q4: What HRR dimension does IB suggest? | D >= 1,174 for constraints, D >= 625 for others | Constraints are information-bound; others are SNR-bound |
| Q5: Retrieval-aware vs readable compression? | Dual-mode: keyword index for FIND, type-compressed for READ | Zero retrieval losses at keyword-only level |

## Implications for Architecture

1. **Type-aware compression is validated.** Implement the heuristic at retrieval time, not storage time. Store full text, return compressed text.

2. **The 55% saving is real but insufficient alone.** The compressed corpus (15.9K tokens) still exceeds the 2K retrieval budget by 8x. Compression is a necessary component but must be combined with top-k selection (retrieval ranking) to meet REQ-003.

3. **At ~13 tokens per compressed node, 150 nodes fit in 2K.** This is generous for typical retrieval (10-30 nodes). The token budget is achievable with compression + ranking.

4. **Full IB optimization is not justified at 1K nodes.** The marginal gain over the type heuristic does not justify building a relevance model. Revisit at 10K+ nodes or if retrieval quality degrades.

5. **HRR dimension should be 2048 minimum, 4096 preferred.** The IB analysis independently confirms the same dimension range that Exp 35 derived from SNR analysis.

6. **Dual-mode storage (full text + compressed retrieval) is the right design.** FTS5 searches the full text. The retrieval payload uses type-compressed text. This separates indexing cost from injection cost.

---

## Limitations

- Ground truth covers 6 topics / 13 decisions. A more exhaustive eval would test all 173 decisions as retrieval targets.
- The token estimation (chars/4) is approximate. Real tokenizer counts may differ by 10-20%.
- IB-to-HRR mapping uses a rough bits-per-token estimate. True information content of belief nodes depends on vocabulary entropy, which varies by domain.
- The 55% compression was measured at the corpus level. Per-retrieval savings depend on the type distribution of retrieved nodes. A constraint-heavy retrieval saves less.
- No production retrieval pipeline exists to test end-to-end. These results are simulated.
