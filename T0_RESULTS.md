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
