# Experiment 48: Multi-Layer Extraction + Retrieval at Scale -- Results

**Date:** 2026-04-10
**Status:** Complete
**Depends on:** Exp 37, 39, 40, 45, 47

---

## 1. Summary

Multi-layer extraction (commits, files, sentences, AST, citations, directives, temporal edges) was run on 3 projects. On project-a, the graph grew from 586 nodes (Exp 47 baseline) to 16,463 nodes. Retrieval was tested on the 6-topic ground truth at K=15.

**Key finding: All hypotheses failed except H4 (partition capacity) and H5 (scaling).** The multi-layer graph diluted the belief nodes, making retrieval harder, not easier. Grep dropped from 92% to 85% coverage; FTS5 dropped from 85% to 69%. HRR added zero value. Temporal edges provided zero unique signal.

This is a significant negative result that reveals a fundamental problem: adding more node types without filtering or weighting drowns the decision-level signal in noise.

---

## 2. Graph Statistics

### 2.1 Per-Project Graphs

| Project | Nodes | Edges | LCC% | Components | Extract Time |
|---------|-------|-------|------|------------|-------------|
| project-a | 16,463 | 29,053 | 85% | 1,528 | 1.87s |
| project-b | 71,628 | 116,886 | 88% | 6,379 | 4.06s |
| project-d | 5,054 | 8,338 | 74% | 142 | 0.66s |

### 2.2 Alpha-Seek Node Type Distribution

| Type | Count | % of total |
|------|-------|-----------|
| sentence | 5,993 | 36.4% |
| file | 4,171 | 25.3% |
| callable | 2,651 | 16.1% |
| heading | 1,832 | 11.1% |
| belief (spike DB) | 586 | 3.6% |
| commit | 541 | 3.3% |
| behavioral_belief | 4 | 0.0% |

The 586 belief nodes that contain ground-truth decisions are only 3.6% of the full graph. The rest is file names, doc sentences, callables, and headings.

### 2.3 Alpha-Seek Edge Type Distribution

| Edge Type | Count | Notes |
|-----------|-------|-------|
| SENTENCE_IN_FILE | 7,825 | Doc sentence -> file mappings |
| WITHIN_SECTION | 5,986 | Sequential doc sentences |
| COMMIT_TOUCHES | 4,462 | Commit -> file modified |
| CONTAINS | 4,171 | Dir -> file containment |
| CALLS | 3,164 | AST intra-file call edges |
| CITES | 2,259 | Files sharing D### citations |
| TEMPORAL_NEXT | 540 | Sequential commit edges |
| RELATES_TO | 258 | From spike DB |
| DECIDED_IN | 221 | From spike DB |
| CO_CHANGED | 138 | Files changed together >= 3x |
| SOURCED_FROM | 29 | From spike DB |

---

## 3. Retrieval Comparison (Alpha-Seek, K=15)

### 3.1 Per-Topic Results

| Topic | Needed | Grep Found | FTS5 Found | FTS5+HRR Found |
|-------|--------|-----------|-----------|---------------|
| dispatch_gate | D089,D106,D137 | 3/3 | 2/3 (miss D137) | 2/3 (miss D137) |
| calls_puts | D073,D096,D100 | 2/3 (miss D100) | 2/3 (miss D100) | 2/3 (miss D100) |
| capital_5k | D099 | 1/1 | 1/1 | 1/1 |
| agent_behavior | D157,D188 | 1/2 (miss D157) | 1/2 (miss D157) | 1/2 (miss D157) |
| strict_typing | D071,D113 | 2/2 | 1/2 (miss D113) | 1/2 (miss D113) |
| gcp_primary | D078,D120 | 2/2 | 2/2 | 2/2 |

### 3.2 Aggregate Results

| Method | Coverage | Tokens | Precision | MRR |
|--------|----------|--------|-----------|-----|
| Grep | **85%** (11/13) | 1,869 | 12% | 0.328 |
| FTS5 | 69% (9/13) | 480 | 10% | 0.666 |
| FTS5+HRR | 69% (9/13) | 480 | 10% | 0.666 |

### 3.3 Comparison to Exp 47 (586 Nodes)

| Method | Exp 47 (586 nodes) | Exp 48 (16,463 nodes) | Delta |
|--------|-------------------|----------------------|-------|
| Grep | 92% | 85% | -7pp |
| FTS5 | 85% | 69% | -16pp |
| FTS5+HRR | 85% | 69% | -16pp |

**Every method degraded.** The multi-layer graph is strictly worse than the 586-node belief-only graph for retrieval.

---

## 4. Hypothesis Results

### H1: At 2K+ nodes, FTS5 outperforms grep -- FAIL

FTS5 dropped from 85% to 69% while grep only dropped from 92% to 85%. The prediction was backwards: at scale, FTS5 is MORE sensitive to dilution than grep, not less. Grep's "return everything that matches" approach is more robust because it searches ALL 16K nodes and returns the most term-dense ones. FTS5's BM25 ranking surfaces irrelevant doc sentences that happen to match query terms.

**Root cause:** D137 (dispatch gate) and D113 (typing) are ranked outside K=15 by FTS5 because thousands of doc sentence nodes now match the same query terms with competitive BM25 scores.

### H2: Multi-layer edges increase HRR retrieval value -- FAIL

FTS5+HRR = FTS5 exactly. HRR added zero new decisions. The partition strategy works (0 over-capacity), but the problem is that HRR walks from FTS5 seed nodes traverse WITHIN_SECTION, SENTENCE_IN_FILE, and other structural edges that lead to more doc/file nodes, not to the 586 belief nodes that contain ground truth.

**Root cause:** The multi-layer edges connect different node types (commits to files, sentences to files), but don't connect to the belief nodes from the spike DB. The spike DB edges (DECIDED_IN, RELATES_TO, etc.) only connect beliefs to other beliefs.

### H3: Temporal edges provide unique retrieval signal -- FAIL

Zero commit messages in project-a contain D### decision references. The temporal analysis found 0 relevant commits for all 6 topics. TEMPORAL_NEXT edges connect commits to each other, and COMMIT_TOUCHES connects commits to files, but neither path leads to belief nodes.

**Root cause:** The D### decision IDs exist only in the spike DB and in .md docs that reference them. Commit messages use natural language ("add backtest module") without decision IDs.

### H4: 90%+ partitions within HRR capacity -- PASS

0/247 partitions exceeded the 204-edge capacity limit. Max partition size was 150 (the chunk ceiling). Decision-neighborhood partitioning with chunking works correctly for multi-layer graphs.

### H5: Extraction scales linearly with project size -- PASS

| Project | Nodes | Time | Nodes/sec |
|---------|-------|------|-----------|
| project-d | 5,054 | 0.66s | 7,657 |
| project-a | 16,463 | 1.87s | 8,803 |
| project-b | 71,628 | 4.06s | 17,642 |

All under 5 seconds. project-b (71K nodes) extracted in 4s. Linear or better.

### H6: Grep precision degrades at scale while FTS5 holds -- FAIL

Both degraded. Grep precision went from 21% (Exp 47) to 12%. FTS5 precision went from 12% to 10%. Grep still has higher precision than FTS5 at this scale.

---

## 5. Root Cause Analysis

The fundamental problem is **type-blind retrieval on a multi-layer graph**. All three methods treat every node equally:

1. **File nodes** (25% of graph): content is just the filename ("backtest.py"). Short, high IDF terms = competitive BM25 scores for common query words.

2. **Doc sentence nodes** (36% of graph): content from markdown docs. Many sentences match query terms but are not decisions.

3. **Callable nodes** (16% of graph): content is just "def function_name". Rarely match queries, but add noise.

4. **Belief nodes** (3.6% of graph): the only nodes containing ground truth decisions. Drowned out.

The spike DB belief nodes and the extracted multi-layer nodes exist in two disconnected subgraphs. The spike DB has DECIDED_IN, RELATES_TO, CITES edges between beliefs. The extracted graph has COMMIT_TOUCHES, SENTENCE_IN_FILE, WITHIN_SECTION edges between commits/files/sentences. There are no cross-type edges bridging these two worlds.

---

## 6. Implications

### What this means for the architecture

1. **Type-weighted retrieval is necessary.** FTS5 and grep must either (a) filter by node type, or (b) weight belief nodes higher than file/sentence nodes. A belief node matching 1 term should rank above a doc sentence matching 3 terms.

2. **Cross-layer edges are the missing piece.** The multi-layer graph adds structural information, but without edges connecting commit nodes to belief nodes (e.g., "commit abc123 implements D097"), the structure can't improve retrieval.

3. **HRR needs belief-to-belief edges to add value.** The AGENT_CONSTRAINT clique from Exp 40 worked because it connected behavioral beliefs to each other. Multi-layer edges (COMMIT_TOUCHES, CALLS) don't create belief-to-belief paths.

4. **Temporal edges need content bridging.** TEMPORAL_NEXT is purely structural (commit A happened before commit B). Without content analysis to detect which commits relate to which decisions, temporal edges are retrieval noise.

### What would fix it

1. **Type-filtered FTS5:** Only search belief + heading + sentence nodes. Exclude file/callable nodes.
2. **Commit-to-decision linking:** Parse commit messages for keywords that match decision content. Create IMPLEMENTS edges.
3. **Weighted BM25:** Multiply BM25 scores by a type factor (belief: 3x, sentence: 1x, file: 0.1x).
4. **Selective HRR encoding:** Only encode edges between nodes that are retrieval targets, not infrastructure edges.

---

## 7. Data Artifacts

- `experiments/exp48_multilayer_extraction.py` -- experiment script
- `experiments/exp48_results.json` -- machine-readable results
- `experiments/exp48_multilayer_results.md` -- this report
