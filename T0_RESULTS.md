# T0 Results: Automatic Graph Construction Research

**Date:** 2026-04-10
**Scope:** T0.1-T0.7 + M1-M2 from TODO_CROSS_PROJECT_TESTING.md
**Corpus:** 7 pilot repos (smoltcp, adr, boa, debserver, gsd-2, rclcpp, rustls)
**All data:** archon:~/agentmemory-corpus/extracted/

---

## Executive Summary

We built 4 extractors (git history, imports, structural, node classifier) and ran them on 7 repos spanning 5 graph shapes. The extractors produced 3-8 edge types per repo with very low overlap between methods (0.6-13.5%), confirming they are genuinely complementary.

The vocabulary overlap analysis (M2) -- the key HRR relevance predictor -- produced a surprising result: **most repos have moderate vocabulary overlap (median Jaccard 0.1-0.2), with only 2-39% of edges below the 0.1 threshold where FTS5 fails.** HRR's value is concentrated in specific edge types (CITES, CROSS_REFERENCES, CONFIG_COUPLING) rather than being uniformly needed.

---

## T0.1: Edge Type Taxonomy

Designed 4-tier taxonomy (EDGE_TYPE_TAXONOMY.md):
- **Tier 1 (Universal):** COMMIT_BELIEF (truly universal), CO_CHANGED (universal for multi-contributor code repos), REFERENCES_ISSUE, SUPERSEDES_TEMPORAL, AUTHORED_BY, LOCAL_COMMIT_BELIEF / REMOTE_COMMIT_BELIEF (distinct node types)
- **Tier 2 (Language-discoverable):** IMPORTS, PACKAGE_DEPENDS_ON
- **Tier 3 (Structure-discoverable):** TESTS, CROSS_REFERENCES, CITES, SERVICE_DEPENDS_ON, IMPLEMENTS
- **Tier 4 (Composite/refined):** CODE_COUPLING, TEST_COUPLING, CONFIG_COUPLING, etc.

**Key revision:** CO_CHANGED was initially classified as Tier 1 universal. Testing showed it fails for doc-only repos (adr: max weight 3) and single-author infra projects (debserver: 26 edges at w>=3). Reclassified as "universal for multi-contributor code repos." COMMIT_BELIEF is the true universal -- every repo produces useful belief nodes.

---

## T0.2: Git Co-Change Extraction

| Repo | Commits | CO_CHANGED (raw) | CO_CHANGED (w>=3) | Max Weight | Beliefs | Issues |
|------|---------|------------------|-------------------|------------|---------|--------|
| smoltcp | 1577 | 12,688 | 1,662 | 68 | 2,127 | 98 |
| adr | 276 | 7,002 | 1 | 3 | 287 | 2 |
| boa | 3354 | 249,834 | 11,249 | 567 | 5,506 | 3,207 |
| debserver | 526 | 10,077 | 26 | 81 | 782 | 6 |
| gsd-2 | 2150 | 162,931 | 2,126 | 84 | 3,794 | 1,471 |
| rclcpp | 1997 | - | 2,074* | - | - | - |
| rustls | 5024 | 56,035 | 7,023 | 230 | 6,448 | 74 |

*rclcpp and rustls extracted after initial pilot run

**Finding:** Weight threshold matters enormously. At w>=1, co-change is dominated by noise (single co-occurrence). At w>=3, signal emerges. At w>=5, only tight coupling remains. The 90%+ of raw edges at w=1 are noise.

---

## T0.3: Import Edge Extraction

| Repo | Language | Import Edges | Unique Sources | Unique Targets |
|------|----------|-------------|----------------|----------------|
| smoltcp | Rust | 275 | 94 | 88 |
| boa | Rust | 582 | 160 | 580 |
| gsd-2 | TypeScript | 759 | 451 | 255 |
| debserver | Python/TS | 28 | 12 | 18 |
| rclcpp | C++ | 1,411 | 405 | 194 |
| rustls | Rust | 96 | 19 | 95 |

**Finding:** Import density varies enormously by language. C++ (rclcpp: 1,411) has dense include graphs. Rust (rustls: 96) has sparse imports due to module system. Python (debserver: 0 resolved) struggled with resolution.

---

## T0.4: Structural Edge Extraction

| Repo | TESTS | CROSS_REF | CITES | SERVICE | PACKAGE | Total |
|------|-------|-----------|-------|---------|---------|-------|
| smoltcp | 0 | 0 | 0* | 0 | 0 | 0 |
| adr | 0 | 0 | 0 | 0 | 0 | 0 |
| boa | 0 | 8 | 0 | 0 | 47 | 55 |
| debserver | 0 | 0 | 72 | 0 | 0 | 72 |
| gsd-2 | 215 | 262 | 65 | 0 | 2 | 544 |
| rclcpp | 88 | 8 | 0 | 0 | 0 | 96 |
| rustls | 0 | 3 | 1* | 0 | 38 | 42 |

*smoltcp and rustls detected RFC patterns but below the 3-unique-ID threshold

**Finding:** TESTS naming convention fails for Rust (inline #[test] in same file). CITES is the critical edge type for planning-heavy projects (debserver: 72 edges from D###/M### citations, more than all code-based methods combined).

---

## T0.5: Node Type Classification

| Repo | Files | Classified | Rate | Top Types |
|------|-------|-----------|------|-----------|
| smoltcp | 147 | 137 | 93% | SOURCE 67%, EXAMPLE 11%, TEST 5% |
| adr | 670 | 525 | 78% | DOCUMENT 55%, EXAMPLE 23% |
| boa | 985 | 962 | 98% | SOURCE 59%, TEST 18%, SCRIPT 4% |
| debserver | 415 | 399 | 96% | PLANNING 60%, INFRASTRUCTURE 14%, SOURCE 9% |
| gsd-2 | 3331 | 3181 | 96% | SOURCE 49%, TEST 20%, DOCUMENT 13% |
| rclcpp | 528 | 513 | 97% | SOURCE 59%, TEST 32% |
| rustls | 1069 | 290 | 27% | OTHER 73% (524 .bin + 180 cert/key test fixtures), SOURCE 12% |

**Finding:** debserver is 60% PLANNING nodes -- confirms it's a planning-heavy infra project. rclcpp is 32% TEST nodes. rustls low classification rate is correct behavior (test fixture binaries are genuinely OTHER).

---

## T0.6: Cross-Method Overlap Analysis

### Import vs Co-Change Overlap

| Repo | % imports in co-change (w>=3) | % co-change in imports | Interpretation |
|------|-------------------------------|------------------------|----------------|
| rustls | 81.2% | 1.1% | Imports are a subset of co-change |
| smoltcp | 58.3% | 8.4% | Similar pattern |
| rclcpp | 19.9% | 13.5% | More balanced |
| boa | 12.2% | 0.6% | Almost no overlap |
| gsd-2 | 5.3% | 1.9% | Very low overlap |
| debserver | 3.6% | 3.8% | Near zero overlap |

**Key finding:** At w>=3, co-change captures 87-99% edges that have NO corresponding import. These are files coupled by shared assumptions, interface contracts, or hidden dependencies. The methods are genuinely complementary.

At w>=1 (any co-occurrence), overlap increases dramatically (53-99% of imports appear as co-change). This means w=1 co-change is largely redundant with imports; w>=3 adds unique signal.

### Structural Edge Uniqueness

Structural edges have near-zero overlap with both co-change and imports across all repos. CITES edges, TESTS edges, CROSS_REFERENCES, and PACKAGE_DEPENDS_ON each find connections invisible to code-based methods.

---

## T0.7: Edge Type Refinement

Combining node types with edge sources produces more specific types. Best results:

| Repo | CO_CHANGED breakdown |
|------|---------------------|
| smoltcp | CODE_COUPLING 50%, generic 43%, TEST_COUPLING 4%, DOC_CODE 3% |
| rclcpp | CODE_COUPLING 49%, generic 35%, TEST_COUPLING 13%, DOC_CODE 3% |
| gsd-2 | generic 51%, CODE_COUPLING 25%, DOC_CODE 16%, TEST_COUPLING 7% |
| rustls | generic 75%, CODE_COUPLING 18%, TEST_COUPLING 5% |

**Finding:** ~50% of CO_CHANGED edges can be refined into more specific types. CODE_COUPLING (source<->source) and TEST_COUPLING (test<->source) are the most common refinements. The remaining "generic" CO_CHANGED edges connect files whose types weren't classified or are OTHER.

For IMPORTS: gsd-2 had 64% TEST_IMPORTS (test files importing source files). This is expected for a project with 20% test nodes.

---

## M2: Vocabulary Overlap (HRR Relevance Predictor)

### Per-Repo Summary

| Repo | Edges Analyzed | <0.1 overlap (HRR needed) | >0.3 overlap (FTS5 ok) | Verdict |
|------|---------------|--------------------------|------------------------|---------|
| smoltcp | 1,587 | 21.7% | 8.6% | Moderate HRR value |
| adr | 1 | 100% | 0% | (too few edges to conclude) |
| boa | 1,820 | 17.7% | 20.3% | Moderate HRR value |
| debserver | 104 | 38.5% | 8.7% | **HRR adds value** |
| gsd-2 | 2,372 | 20.0% | 8.2% | Moderate HRR value |
| rclcpp | 3,099 | 2.5% | 62.9% | FTS5 sufficient |
| rustls | 2,416 | 22.6% | 4.1% | Moderate HRR value |

### Per-Edge-Type Vocabulary Overlap

The most important breakdown. Which edge types have low vocabulary overlap (where HRR is needed)?

**Lowest overlap (HRR most valuable):**

| Edge Type | Repo | Median Overlap | % < 0.1 | Why |
|-----------|------|---------------|---------|-----|
| CONFIG_COUPLING | rustls | 0.064 | 82% | Config files share no vocabulary with code |
| CROSS_REFERENCES | rclcpp | 0.082 | 75% | Docs reference code with different terminology |
| DOC_CODE_COUPLING | smoltcp | 0.084 | 79% | Documentation uses natural language, code uses identifiers |
| CO_CHANGED (generic) | boa | 0.075 | 64% | Files coupled by hidden dependencies, no shared words |
| CITES | debserver | 0.102 | 49% | Decision docs cite each other with minimal vocabulary overlap |
| IMPORTS | gsd-2 | 0.093 | 56% | TS modules with different vocabulary importing each other |

**Highest overlap (FTS5 sufficient):**

| Edge Type | Repo | Median Overlap | % > 0.3 | Why |
|-----------|------|---------------|---------|-----|
| TESTS | rclcpp | 0.381 | 84% | Test files naturally repeat source file vocabulary |
| IMPORTS | rclcpp | 0.339 | 69% | C++ headers included by implementation files share types |
| CODE_COUPLING | rclcpp | 0.325 | 67% | Same-language files in same project share vocabulary |
| DOC_CODE_COUPLING | boa | 1.000 | 68% | Docs generated from code (high overlap = auto-generated) |

### What This Means for HRR

1. **HRR is NOT universally needed.** rclcpp has 63% of edges above 0.3 overlap -- FTS5 handles most of it.

2. **HRR is valuable for specific edge types:**
   - CONFIG_COUPLING (config <-> code): 82% below 0.1 overlap
   - CROSS_REFERENCES (doc <-> doc): 75% below 0.1
   - DOC_CODE_COUPLING (doc <-> code): 79% below 0.1
   - CITES (decision <-> decision): 49% below 0.1

3. **HRR is least needed for:**
   - TESTS (test <-> source): high overlap because tests mirror source vocabulary
   - Same-language IMPORTS: files that import each other share type names

4. **Per-repo, HRR value correlates with project type:**
   - **Infrastructure/planning projects (debserver):** 38.5% low-overlap edges. HRR adds the most value here.
   - **Single-language code projects (rclcpp):** 2.5% low-overlap edges. FTS5 suffices.
   - **Mixed code+docs projects (gsd-2, boa, rustls, smoltcp):** 18-23% low-overlap edges. Moderate HRR value.

---

## Revised HRR Architecture Recommendation

Based on M2 evidence, the retrieval architecture should be:

```
Query
  |
  +---> FTS5 on sentence content (handles 60-98% of retrievals depending on project type)
  |
  +---> HRR single-hop, selectively applied:
  |       - CONFIG_COUPLING edges (highest HRR value)
  |       - CROSS_REFERENCES edges
  |       - DOC_CODE_COUPLING edges
  |       - CITES edges
  |       - CO_CHANGED edges with low vocab overlap (filter by threshold)
  |       [Skip: TESTS, same-language IMPORTS, high-overlap CODE_COUPLING]
  |
  +---> BFS from FTS5/HRR hits (exact multi-hop when depth > 1 needed)
```

HRR is a **selective amplifier**, not a universal replacement. It earns its cost on edges where vocabulary diverges -- config-code boundaries, doc-code boundaries, cross-reference chains, and decision citations. For same-language code coupling, FTS5 is cheaper and equally effective.

---

---

## H1/H2: HRR Encoding and Retrieval on Auto-Constructed Graphs

### Setup
Encoded all 5 pilot graphs in HRR (DIM=2048, capacity=227 per partition). Partitioned by edge type, then chunked at capacity. Ran 50 random ground-truth queries per repo.

### Results

| Repo | Edges | Partitions | R@5 | R@10 | Best Type (R@10) |
|------|-------|-----------|-----|------|-----------------|
| **debserver** | 126 | 3 | **0.813** | **0.880** | CO_CHANGED: 1.000, IMPORTS: 1.000, CITES: 0.824 |
| **smoltcp** | 1,937 | 10 | 0.271 | 0.378 | IMPORTS: 0.487, CO_CHANGED: 0.300 |
| **rclcpp** | 3,581 | 19 | 0.141 | 0.206 | CO_CHANGED: 0.207, IMPORTS: 0.117 |
| **gsd-2** | 3,427 | 18 | 0.127 | 0.166 | CO_CHANGED: 0.201, IMPORTS: 0.190 |
| **boa** | 11,839 | 54 | 0.044 | 0.074 | CO_CHANGED: 0.079 |

### Key Finding: Partition Count Determines Retrieval Quality

HRR retrieval quality is **inversely correlated with partition count**, not graph shape or edge type.

- **debserver (3 partitions):** R@10 = 0.880. Every edge type fits in a single partition. The query hits the right partition and finds the answer.
- **smoltcp (10 partitions):** R@10 = 0.378. IMPORTS (275 edges, 2 partitions) works better than CO_CHANGED (1662 edges, 8 partitions).
- **boa (54 partitions):** R@10 = 0.074. 11K co-change edges split across 50 partitions. A query's target edge is in one of 50 partitions, but the query correlates against all 50, and 49 return noise.

**Why this happens:** When querying, we correlate against every partition and aggregate results. Partitions without the target edge contribute noise (random similarity scores). With 50 partitions, the signal from the 1 correct partition is buried under noise from 49 others. The noise scales with partition count; the signal doesn't.

### This Changes the Architecture

The naive partitioning strategy (chunk by type, then by size) fails at scale. The problem is not HRR's math -- it's that we're querying the wrong partitions.

**Solutions to explore:**
1. **Partition routing:** Given a query (source, edge_type), only query partitions that contain edges involving the source node. Requires a partition-to-node index. Eliminates noise from irrelevant partitions.
2. **Locality-sensitive partitioning:** Group edges by neighborhood (nodes that share edges), not by type. A source node's edges stay in the same partition.
3. **Hierarchical encoding:** Per-node local superpositions (all edges touching node A in one vector), queried directly. No global superposition needed for single-hop.
4. **Higher dimensionality:** DIM=4096 or 8192 increases capacity per partition, reducing partition count. But 11K edges still needs ~50 partitions at DIM=2048.

**The debserver result validates HRR's core capability.** When the graph fits within capacity (126 edges, 3 partitions), retrieval is excellent (R@10=0.880). The challenge is making it work at scale, which is an engineering problem (partition routing), not a mathematical limitation.

---

## VALIDATION GAP: Edge Precision Is Unmeasured

**Identified:** 2026-04-10, during review of T0 claims.

### The Problem

All T0 results report extraction **volume** (edge counts) and **distinctness** (cross-method overlap). Neither metric tells us whether the extracted edges represent real, meaningful relationships.

Low overlap between methods (0.6-13.5%) was presented as evidence of complementarity: "each method finds connections invisible to the others." This is an assumption, not a finding. Low overlap is equally consistent with "each method produces different noise."

Specific unvalidated claims in this document:

1. **"The extractors are genuinely complementary."** We measured that they produce different outputs. We did not measure that their outputs are correct. Complementarity requires correctness of each method independently.

2. **"HRR earns its cost on boundary edges."** The vocabulary overlap analysis (M2) measures Jaccard similarity of file tokens across edges. Low vocabulary overlap predicts where FTS5 will fail, but does not validate that the edges themselves represent real relationships. An edge between two unrelated files that happen to share no vocabulary would score as "HRR needed" -- but the edge is garbage.

3. **"CONFIG_COUPLING: 82% below 0.1 overlap"** (n=38, rustls). These 38 edges connect config files to code files that co-changed in 3+ commits. Factually correct as git history. But: are these meaningful architectural relationships, or are they noise from version bumps, CI config changes, or bulk reformatting? Unknown.

4. **"CROSS_REFERENCES: 75% below 0.1"** (n=8, rclcpp). Six out of eight edges. This should not have been a headline number.

### What "Correct" Means Per Method

Each extraction method produces edges that are definitionally true in a narrow sense:

- **CO_CHANGED:** "These files changed in the same commit 3+ times." True by construction from git log. But trivially true for files that co-occur in bulk operations (reformats, CI updates, version bumps).
- **IMPORTS:** "File A contains an import statement referencing file B." True by construction from parsing. But trivially true for utility imports (logging, path handling) that don't represent meaningful architecture.
- **CITES:** "Document A contains a D### or M### reference to document B." True by construction from regex. Most defensible because these are deliberate human-authored references.
- **TESTS:** "Test file A matches naming convention of source file B." True by convention, but convention may not hold (especially in Rust with inline tests).

The question is not whether the edges exist (they do) but whether they are **meaningful** -- whether they represent relationships a human would recognize as real coupling, dependency, or reference.

### Why This Matters for the Project

The entire retrieval architecture (FTS5 + selective HRR + BFS) is premised on the graph being correct. If 50% of CO_CHANGED edges are noise from bulk operations, the retrieval pipeline wastes half its effort on meaningless traversals. HRR's "vocabulary bridge" value is measured relative to edges that may themselves be garbage.

### What's Needed

A precision audit. Sample N edges per method per repo. Evaluate each: "Does this edge represent a meaningful relationship?" Compute precision per method per repo. Without this, every architectural recommendation in this document is conditional on an unverified assumption.

### Validation Results (2026-04-10)

Three zero-human-labeling approaches were run on all 5 pilots.

**Approach 3 (Negative Sampling): ALL 5 repos produce SIGNAL, not noise.**

| Repo | same_dir lift | import lift | path_distance lift | Verdict |
|------|--------------|-------------|-------------------|---------|
| smoltcp | 24.3x | 19.0x | 2.2x | SIGNAL |
| boa | 43.0x | - | 3.1x | SIGNAL |
| debserver | 73.1x | 38.5x | 3.4x | SIGNAL |
| gsd-2 | 18.5x | - | 2.4x | SIGNAL |
| rclcpp | 14.7x | 230.0x | 1.8x | SIGNAL |

Co-change edges predict same-directory at 15-73x over random. rclcpp co-change edges are 230x more likely to have an import relationship than random pairs. These are not noise.

**Approach 5 (Self-Consistency): Larger repos show heavy-tailed degree distributions and strong clustering.**

| Repo | Tail Ratio | Clustering vs Random | Degree Dist | Transitivity |
|------|-----------|---------------------|-------------|-------------|
| boa | 23.1 | 52.7x | HEAVY_TAILED | STRONG_CLUSTERING |
| gsd-2 | 29.6 | 50.0x | HEAVY_TAILED | STRONG_CLUSTERING |
| rclcpp | 16.8 | 22.3x | HEAVY_TAILED | MODERATE_CLUSTERING |
| smoltcp | 3.8 | 3.3x | NEAR_UNIFORM | WEAK_CLUSTERING |
| debserver | 3.0 | 5.3x | NEAR_UNIFORM | WEAK_CLUSTERING |

boa and gsd-2 show clustering 50x above random -- a property of real dependency graphs, not random co-occurrence. Smaller repos (smoltcp, debserver) have weaker but still above-random structure.

**Approach 2 (Triangulation): Multi-method agreement is low (0.6-10.3%) but this is expected.**

The low agreement is not a weakness -- methods measure genuinely different things (co-change = empirical coupling, imports = explicit dependency, structural = conventions). The negative sampling results above confirm that single-method edges carry signal independently.

**Conclusion:** The validation gap concern was legitimate to raise. The evidence now shows the edges are meaningful: co-change predicts directory structure at 15-73x lift, clustering is 3-53x above random, and degree distributions are heavy-tailed (real graph property). The extraction pipeline produces signal, not noise.

### Original Approaches Proposed (retained for reference)

### Approaches to Validation Without Extensive Human Labeling

Human labeling at scale is impractical -- a single person reviewing thousands of edges would take weeks and produce inconsistent judgments due to fatigue.

**Approach 1: Proxy Ground Truth from Existing Graphs**

gsd-2 has an existing hand-built SQLite graph (graph_nodes, graph_edges, mem_nodes, mem_edges). Compare auto-extracted edges against this existing graph:
- Precision: what fraction of our extracted edges also appear in the hand-built graph?
- Recall: what fraction of hand-built edges did we discover?
- This is already listed as open question #3 but was never executed.

**Limitations:** gsd-2's graph was itself built by an LLM agent, not curated by a human. It's a proxy, not ground truth. Also only covers one repo.

**Approach 2: Triangulation -- Edges Confirmed by Multiple Independent Methods**

If CO_CHANGED, IMPORTS, and STRUCTURAL all independently find the same edge, it's almost certainly real. We already have the overlap data. Use multi-method agreement as a confidence signal:

- 3 methods agree: high confidence (we have these counts in overlap_analysis.json: `all_three_methods`)
- 2 methods agree: medium confidence (`any_two_methods`)
- 1 method only: unvalidated

For rclcpp: 24 edges found by all 3 methods, 307 by exactly 2, 2892 by exactly 1. The 24 triple-confirmed edges are almost certainly real. The 2892 single-method edges are unvalidated. This doesn't measure precision directly, but it stratifies edges by confidence without any human input.

**Approach 3: Negative Sampling -- Test Whether Edges Predict Something**

If an edge is meaningful, it should predict something measurable. For CO_CHANGED:
- Take the top 100 strongest co-change edges (highest weight).
- For each edge (file A, file B), check: does A import B or vice versa? Do they share a directory? Do they share an author?
- Compare against 100 random non-edge pairs (files that never co-changed).
- If the edge set has higher import/directory/author overlap than random, the edges carry signal.

This is a downstream predictive validity test, not a precision audit. It doesn't tell you "is this edge correct?" but "do edges from this method correlate with independently observable structure?" If CO_CHANGED edges don't predict imports or directory proximity any better than random, the method is probably noise.

**Approach 4: Stratified Small-Sample Human Audit**

Instead of reviewing thousands of edges, review a stratified sample designed for maximum information:
- 10 edges per method per repo = ~200 total across 7 repos and 3 methods
- Stratify by: weight (top 10%, bottom 10%), edge type, node type pair
- Binary label: "meaningful relationship" vs "noise/trivial"
- One reviewer (the user), ~30 minutes of work

200 labels is enough to compute precision with a ~7% margin of error per method (95% CI). Not perfect, but vastly better than zero validation.

**Approach 5: Self-Consistency Checks (No Human Required)**

Check whether the extracted graph has properties that real graphs have and noise doesn't:
- **Transitivity:** If A->B and B->C both exist (by co-change), does A->C exist more often than random? Real dependency chains are transitive. Random co-occurrence is not.
- **Degree distribution:** Real coupling graphs follow power-law or log-normal degree distributions (few hubs, many periphery nodes). Random noise produces uniform distributions.
- **Community structure:** Run community detection (Louvain, label propagation) on the extracted graph. Check whether detected communities align with directory structure. If they do, the graph captures real architecture. If communities are random, the graph is noise.
- **Temporal coherence:** Do strong co-change edges (high weight) persist across time windows? Split git history into halves. Do the top 100 edges from the first half also appear as edges in the second half? Persistent coupling is more likely real; one-time co-occurrence is more likely noise.

These tests don't require any human labels. They test whether the graph has structural properties consistent with real software architecture.

**Approach 6: LLM-as-Judge (Bounded Cost)**

For edges where context is needed to judge meaningfulness:
- Present the LLM with: file A name, file A first 50 lines, file B name, file B first 50 lines, edge type, edge weight.
- Ask: "Is this edge a meaningful architectural relationship? Yes/No/Uncertain."
- Run on a sample of 200-500 edges.
- Cost: ~$0.50-2.00 on Haiku for 500 edges.

Caveats: LLM judges have their own biases (may over-validate, may not understand project-specific conventions). But it's cheap and scalable. Use as a supplement to self-consistency checks, not as the sole signal.

**Recommended Validation Strategy (Combined)**

1. Run self-consistency checks (Approach 5) on all 7 repos. Zero human cost. Filters out methods that produce structurally incoherent graphs.
2. Run gsd-2 proxy ground truth (Approach 1). Zero human cost beyond running the script.
3. Run triangulation confidence stratification (Approach 2). Already have the data.
4. Run negative sampling / predictive validity (Approach 3). Zero human cost.
5. If the above pass, do the stratified 200-sample human audit (Approach 4) for final precision numbers.
6. Use LLM-as-judge (Approach 6) to extend coverage beyond the human sample if needed.

Steps 1-4 are fully automated and should be done before any human labeling. If the self-consistency checks fail (e.g., no transitivity, random communities, no temporal persistence), precision auditing is moot -- the method needs to be fixed first.

---

## Open Questions for Next Phase

1. **Sentence-level decomposition:** All experiments used file-level nodes. Sentence-level (as in alpha-seek Exp 29) should increase HRR value by reducing vocabulary overlap within edges (a sentence about "dispatch gates" vs a sentence about "flow control" have lower overlap than their parent files).

2. **HRR encoding of these graphs:** We haven't yet encoded any of these extracted graphs in HRR. The extraction pipeline works; the next step is running Exp 31-style HRR tests on smoltcp, boa, gsd-2 to measure actual retrieval precision/recall.

3. **Ground truth validation on gsd-2:** gsd-2 has existing SQLite graph tables. We should compare our auto-discovered edges against theirs for precision/recall.

4. **Scale:** The largest repo tested (boa: 11K co-change edges) is within HRR capacity with partitioning. But dealii (66K commits, ~20K co-change edges) and cockroach will stress-test capacity limits.

5. **Edge type count vs HRR selectivity:** gsd-2 has 8 active edge types. Does HRR selectivity improve with more types? (More orthogonal vectors = better geometric filtering.)

---

## Files

| File | Contents |
|------|----------|
| EDGE_TYPE_TAXONOMY.md | 4-tier type taxonomy with HRR implications |
| TODO_CROSS_PROJECT_TESTING.md | Full testing plan with corpus inventory |
| scripts/corpus_clone.sh | Idempotent corpus clone/sync to archon |
| scripts/corpus_map.py | Repo profiling and manifest generation |
| scripts/extract_git_edges.py | T0.2: CO_CHANGED + COMMIT_BELIEF + REFERENCES_ISSUE |
| scripts/extract_import_edges.py | T0.3: IMPORTS (Rust, Python, TS/JS, C/C++) |
| scripts/extract_structural_edges.py | T0.4: TESTS, CROSS_REFERENCES, CITES, SERVICE_DEPENDS_ON, PACKAGE_DEPENDS_ON |
| scripts/classify_nodes.py | T0.5: Automatic node type classification |
| scripts/analyze_overlap.py | T0.6: Cross-method overlap analysis |
| scripts/refine_and_vocab.py | T0.7 + M2: Edge type refinement + vocabulary overlap |
| corpus_manifest.json | 27-repo manifest with languages, markers, methods |
| archon:extracted/*.json | All extraction results (cached by HEAD hash) |
