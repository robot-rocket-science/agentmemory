# Experiment 48: Multi-Layer Extraction + Retrieval at Scale

**Date:** 2026-04-10
**Status:** Planning
**Depends on:** Exp 37 (AST extraction), Exp 39 (ground truth), Exp 40 (hybrid pipeline), Exp 45 (HRR partitioning, onboarding extractors), Exp 47 (baseline comparison)
**Rigor tier:** Empirically tested (real projects, real git history, real code)

---

## 1. Motivation

Exp 47 showed grep beats our architecture at 586 nodes: 92% coverage vs 85% for FTS5 and 85% for FTS5+HRR. But 586 nodes is an artificially small graph -- it contains only decision-level beliefs from the project-a spike DB, with no temporal edges, no code structure, no commit history, and no file-level nodes.

Real projects have thousands of nodes across multiple layers. The onboarding research (Exp 45) designed extractors for these layers but only validated graph connectivity (H1), not retrieval quality at scale. Exp 19 designed temporal edges (TEMPORAL_NEXT + content-aware decay) but they were never extracted from real data.

The fundamental question has shifted from "does our retrieval architecture work?" (proven at component level in Exp 40/45) to "does the extraction pipeline produce graphs where our architecture outperforms grep?" This is the extraction and categorization problem the user identified.

---

## 2. Research Background

### What we know about each extraction layer

| Layer | Source Experiment | What Was Proven | What's Untested |
|-------|------------------|-----------------|-----------------|
| Decision/belief nodes | Exp 6, 16 | 173 decisions, 1,195 sentences from project-a | Whether sentence decomposition helps retrieval at scale |
| CITES edges | Exp 40 | D### references extractable by regex. 43 CITES edges from 586 nodes | Coverage on projects without explicit citation patterns |
| CALLS/PASSES_DATA | Exp 37 | 3,489 resolved CALLS from project-a (18.9% resolution). Disjoint from CO_CHANGED (Jaccard 0.012) | Whether CALLS edges improve retrieval (vs just graph density) |
| CO_CHANGED | Exp 37 | Captured from git history. Disjoint from CALLS and CITES | Whether CO_CHANGED provides retrieval signal |
| COMMIT_TOUCHES | Exp 45 (onboarding) | Extracted in pipeline. Links commits to files they modified | Whether commit nodes are useful retrieval targets |
| TEMPORAL_NEXT | Exp 19 (design only) | Model 3 adopted: sequential edges between commits + content-aware decay | **Never extracted from real data. Never tested for retrieval impact.** |
| Sentence decomposition | Exp 16, 29 | 86% token reduction. Windowed sentences beat decision-level (12/12 vs 11/12) | Whether sentence FTS5 at scale still wins |
| Behavioral/directive nodes | Exp 40, 43, 44 | Pattern scan finds 18 behavioral in project-a. Keyword classification 47% accurate | Whether directive extraction generalizes across projects |
| HRR structural retrieval | Exp 34, 40, 45 | 100% recall within capacity. Decision-neighborhood partition works | Whether HRR adds value when the graph is multi-layer (not just behavioral clique) |

### What Exp 47 revealed about the gap

Exp 47's grep advantage has two specific root causes:

1. **D137 (ranking cutoff):** FTS5 finds D137 but ranks it below K=15. Grep returns all matches and D137 stays in. At 586 nodes there are few matches per query, so grep's "return everything" strategy works. At 5K+ nodes, grep returns hundreds of matches and D137 drowns in noise. This is the scale-dependent hypothesis.

2. **D157 (HRR capacity):** The behavioral partition had 18 nodes / 306 edges, exceeding DIM=2048 capacity (~204). With a multi-layer graph, the AGENT_CONSTRAINT clique isn't the only partition. Decision-neighborhood partitioning (Exp 45) keeps each partition at 50-65 edges. The question is whether multi-layer edges stay within partition capacity.

### What temporal edges should add

From Exp 19's design:
- **TEMPORAL_NEXT** between consecutive commits provides a time axis for the graph
- **Content-aware decay** means recent decisions outrank stale ones
- **Temporal queries** become possible: "what changed after X?" follows TEMPORAL_NEXT from X

More importantly, commit nodes with TEMPORAL_NEXT + COMMIT_TOUCHES create a **temporal bridge** between code files and decisions. A commit that modifies `backtest.py` and references D097 creates a path: `backtest.py <- commit:abc123 -> D097`. This is a new kind of structural edge that FTS5 can't replicate -- it connects code to decisions through temporal co-occurrence.

---

## 3. Hypotheses

**H1: At 2K+ nodes, FTS5 outperforms grep on coverage@15.**
Grep's lack of ranking becomes a liability when there are hundreds of matches per query. FTS5's BM25 ranking surfaces the most relevant results. Predicted: FTS5 coverage > grep coverage on the project-a 6-topic ground truth when the graph includes commit nodes, file nodes, and sentence nodes.

**H2: Multi-layer edges increase HRR retrieval value.**
With CITES, CALLS, CO_CHANGED, and TEMPORAL_NEXT edges creating denser graph structure, HRR has more structural paths to walk. Predicted: FTS5+HRR coverage > FTS5-only coverage at 2K+ nodes, recovering at least 1 decision that FTS5 misses.

**H3: Temporal edges provide unique retrieval signal.**
TEMPORAL_NEXT + COMMIT_TOUCHES create paths between code and decisions that no other edge type provides. Predicted: at least 1 ground-truth decision is reachable via temporal edges that is not reachable via CITES, CALLS, or CO_CHANGED.

**H4: The full multi-layer graph stays within HRR partition capacity.**
Decision-neighborhood partitioning (Exp 45) keeps partitions at 50-65 edges. With additional edge types, partitions may grow. Predicted: with multi-layer edges, 90%+ of partitions remain below DIM=2048 capacity (~204 edges).

**H5: Extraction scales linearly with project size.**
The onboarding extractors (Exp 45) ran on project-a in <5 seconds. Predicted: project-b (3x larger) completes in <15 seconds. gsd-2 (5x larger) completes in <25 seconds.

**H6: Grep precision degrades at scale while FTS5 precision holds.**
At 586 nodes, grep precision was 21% (higher than FTS5's 12%). At 2K+ nodes, grep returns more noise per query. Predicted: grep precision drops below 15% while FTS5 precision stays at 12%+.

**Null hypothesis:** Grep maintains >= 90% coverage at 2K+ nodes with comparable token efficiency. The multi-layer graph does not improve retrieval over the 586-node baseline.

---

## 4. Methodology

### 4.1 Target Projects

| Project | Commits | Files | Archetype | Why |
|---------|---------|-------|-----------|-----|
| project-a | 552 | 393 | Dense quant codebase + rich docs | Has 6-topic ground truth. Primary test. |
| project-b | 1,714 | 1,786 | Large GSD-managed project | Tests scale. Has .planning/ docs. |
| project-d | 538 | 183 | Rust server, minimal docs | Tests code-heavy/doc-light archetype. |

### 4.2 Extraction Pipeline

For each project, run the following extractors (reusing exp49_onboarding_validation.py where possible):

1. **File tree** -> file nodes + DIRECTORY_CONTAINS edges
2. **Git history** -> commit nodes + COMMIT_TOUCHES edges + CO_CHANGED edges (weight >= 3)
3. **Temporal ordering** -> TEMPORAL_NEXT edges between consecutive commits (NEW -- not in exp45)
4. **Document sentences** -> sentence nodes + SENTENCE_IN_FILE edges + WITHIN_SECTION edges
5. **AST analysis** -> callable nodes + CALLS edges + PASSES_DATA edges (Python/Rust)
6. **Citation parsing** -> CITES edges (D###/M### patterns where available)
7. **Directive scanning** -> directive nodes (always/never/banned patterns)

### 4.3 Graph Assembly

Merge all nodes and edges into a single in-memory graph. Compute:
- Node count by type (commit, file, sentence, callable, directive)
- Edge count by type (TEMPORAL_NEXT, COMMIT_TOUCHES, CO_CHANGED, CALLS, CITES, etc.)
- Connected component analysis (LCC size, component count)
- Partition analysis (how many decision-neighborhood partitions, max edges per partition)

### 4.4 Retrieval Comparison

On **project-a** (has ground truth), run 5 methods at K=15:
- A. Grep on full graph nodes
- B. FTS5 on full graph nodes
- C. FTS5 + PRF
- D. FTS5 + HRR (decision-neighborhood partitions with all edge types)
- E. FTS5 + HRR + temporal walk (extend HRR to use TEMPORAL_NEXT for time-aware retrieval)

Metrics: coverage@15, tokens@15, precision@15, MRR (same as Exp 47).

On **project-b** and **project-d** (no ground truth), run qualitative evaluation:
- 3 ad-hoc queries per project
- Human judgment: are the top-5 results relevant?
- Compare grep vs FTS5+HRR qualitatively

### 4.5 Temporal Retrieval Test

Specific test for H3: for each of the 6 project-a topics, check whether any needed decision is reachable from a commit node via TEMPORAL_NEXT + COMMIT_TOUCHES that is NOT reachable via CITES or CALLS. If yes, temporal edges provide unique signal.

---

## 5. Requirements Traceability

| Requirement | How This Experiment Addresses It |
|-------------|--------------------------------|
| REQ-001 (cross-session retention) | Tests whether the graph can retrieve decisions made in early sessions when queried from a later-session context |
| REQ-003 (token budget <= 2K) | Measures tokens@15 -- does the multi-layer graph inflate result tokens? |
| REQ-007 (precision >= 50%) | Measures precision@15 on all methods. Current gap: no method reaches 50% |
| REQ-014 (zero-LLM extraction recall >= 40%) | All extractors are zero-LLM. Measures whether they produce useful nodes |
| REQ-027 (zero-repeat directive) | Tests whether directive extraction generalizes across project archetypes |

Also addresses:
- **Gap 1 (baseline comparison):** Re-tests grep vs our architecture at realistic scale
- **Gap 4 (onboarding validation):** Tests whether the extraction pipeline produces useful graphs (H2 from onboarding)
- **Exp 19 (time dimension):** First empirical test of temporal edge extraction and retrieval impact

---

## 6. Success Criteria

| Criterion | Threshold | What It Means If We Miss |
|-----------|-----------|--------------------------|
| FTS5 coverage > grep coverage on project-a at full graph | FTS5 >= 92%, grep < 92% | Our ranking adds value at scale |
| FTS5+HRR coverage > FTS5 coverage | At least 1 additional decision found | HRR structural retrieval adds value with multi-layer edges |
| Temporal edges provide unique signal | At least 1 decision reachable only via temporal path | Temporal extraction is worth the complexity |
| 90%+ partitions within HRR capacity | <= 10% of partitions exceed 204 edges | Decision-neighborhood partitioning works for multi-layer graphs |
| Extraction completes in reasonable time | < 30s per project | Pipeline is practical for real use |

---

## 7. What Could Go Wrong

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Grep still wins at 2K+ nodes | Architecture not justified at this scale | Test at 10K+ (project-b). If grep still wins there, fundamental rethink needed. |
| Multi-layer edges create over-capacity partitions | HRR fails on the richer graph | Increase DIM to 4096. Sub-partition by edge type. |
| Temporal edges are mostly noise | TEMPORAL_NEXT adds density but not signal | Filter: only link commits that reference D###/M### patterns, not all consecutive commits. |
| Extraction takes minutes per project | Not practical for onboarding | Profile and optimize. Most time should be git log parsing, not graph construction. |
| Alpha-seek ground truth is too narrow (6 topics) | Results don't generalize | Qualitative eval on project-b and project-d provides breadth. |
