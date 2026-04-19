# Sentence-Level Decomposition Research

**Date:** 2026-04-10
**Status:** Active research
**Prior art:** Exp 16 (granular decomposition), Exp 29 (sentence vs decision retrieval), Exp 31 (sentence-level HRR)
**Depends on:** T0 extraction pipeline, HRR encoder

---

## The Problem

All T0 experiments used file-level nodes. A 200-line Python file becomes one node in the graph, when it contains 10+ distinct claims, decisions, functions, and behaviors. This coarseness has three consequences:

1. **Partition bloat.** A file with 50 import edges contributes 50 edges to the partition. If the file were decomposed into 10 functions, each function would contribute ~5 import edges -- same total but spread across more focused subgraphs.

2. **Vocabulary dilution.** A file's vocabulary is the union of all its sentences. Vocabulary overlap between files is high because shared boilerplate (imports, logging, error handling) dominates. At sentence level, a sentence about "dispatch gates" has low overlap with a sentence about "flow control" even if they're in the same file.

3. **Retrieval imprecision.** When HRR or FTS5 finds a file, the user gets the whole file. At sentence level, they get the specific claim or decision.

## What Exp 16/29/31 Established (Alpha-Seek)

- 173 decisions decomposed into 1,195 sentence nodes (avg 6.9 per decision)
- 86% token reduction (36K -> 4.8K for core assertions)
- Sentence types: evidence (29%), context (49%), constraint (11%), supersession (4%), rationale (3%), implementation (4%)
- Sentence-level retrieval: 100% coverage vs 92% at decision-level in same token budget (Exp 29)
- HRR on sentence graph: 5/5 single-hop recall at DIM=2048 with 25 edges (Exp 31)

These results were on structured decision records with a specific format (decision: choice | rationale). The question is whether the approach generalizes.

## Decomposition Strategies by Content Type

### Markdown / Documentation (.md, .rst, .txt)

**Strategy:** Paragraph-level decomposition with heading context.

Documents have natural structure: headings define topics, paragraphs contain claims. Each paragraph becomes a node, with its heading path as metadata.

```
# Architecture
## Data Layer                    <- heading context
PostgreSQL stores all entities.  <- node: claim about architecture
Redis caches hot paths.          <- node: claim about caching
```

**Edge types at this level:**
- NEXT_IN_SECTION: sequential paragraphs under same heading
- HEADING_CONTAINS: heading -> paragraph
- CROSS_REFERENCES: paragraph mentions something in another section

**Sentence splitter:** Period-split works for prose. Bullet lists: each bullet is a node.

**Expected yield:** Most markdown files have 5-30 paragraphs. A 100-line doc becomes 10-20 nodes.

### Python Source (.py)

**Strategy:** Function/method-level decomposition with docstring extraction.

A Python file's "sentences" are its functions. Each function is a node. The docstring (if present) is a belief about what the function does.

```python
def compute_threshold(commits: int) -> int:  <- node: function
    """Adaptive co-change weight threshold.   <- belief: what it does
    At ~0.5% of commits, every repo lands     <- belief: why this formula
    at 1-4 partitions.
    """
    return max(3, math.ceil(commits * 0.005))
```

**Edge types at this level:**
- CALLS: function A calls function B (from Exp 37 control flow extraction)
- DEFINED_IN: function defined in file
- NEXT_IN_FILE: sequential functions in same file
- IMPORTS_FROM: function uses a name imported from another module

**Sentence splitter:** AST-based. `ast.parse` -> extract FunctionDef, AsyncFunctionDef, ClassDef nodes. Each becomes a graph node. Docstrings become belief nodes attached to their function.

**Expected yield:** A 200-line Python file typically has 5-15 functions. Plus their docstrings as separate belief nodes.

### Rust Source (.rs)

**Strategy:** Same as Python but via tree-sitter or regex for fn/impl/struct.

Rust modules contain functions, impl blocks, struct definitions, and doc comments (///).

```rust
/// Compute adaptive threshold based on commit count.  <- belief
fn adaptive_threshold(commits: usize) -> usize {       <- node: function
    std::cmp::max(3, (commits as f64 * 0.005).ceil() as usize)
}
```

**Edge types:** Same as Python (CALLS, DEFINED_IN, etc.) plus USE_STATEMENT (use crate::X -> function in X).

**Sentence splitter:** Regex for `fn `, `struct `, `impl `, `enum `, `trait `. Doc comments (///) become belief nodes.

### C/C++ Source (.c, .cpp, .h)

**Strategy:** Function-level via regex or tree-sitter.

C/C++ files contain function definitions and Doxygen-style comments.

**Sentence splitter:** Regex for function definitions is fragile in C++. Better: use the include-graph structure we already extract, plus split on `/**` doc comments.

### TypeScript/JavaScript (.ts, .tsx, .js)

**Strategy:** Export-level decomposition.

TS/JS files export functions, classes, types, and constants. Each export is a node.

**Sentence splitter:** Regex for `export function`, `export class`, `export const`, `export default`. JSDoc comments become belief nodes.

### Config Files (.yml, .yaml, .toml, .json)

**Strategy:** Top-level key decomposition.

A docker-compose.yml with 5 services becomes 5 nodes. A Cargo.toml with 3 dependency sections becomes 3 nodes.

**Sentence splitter:** YAML/TOML parser, extract top-level keys. Each key-value group is a node.

### Commit Messages

**Strategy:** Already sentence-level (COMMIT_BELIEF from T0.2).

Commit messages are already decomposed into sentences in the git edge extractor. No additional work needed.

## Research Plan

### Phase 1: Markdown decomposition (easiest, highest signal)

Markdown files are the most document-like content in any repo. They contain decisions, rationale, requirements, changelogs -- the highest-value beliefs.

1. Build a paragraph-level markdown decomposer
2. Run on project-d (248 PLANNING nodes, 60% of all files)
3. Measure: how many sentence-level nodes per file? What's the vocabulary overlap distribution at sentence level vs file level?
4. Encode in HRR and compare R@10 against file-level baseline

### Phase 2: Python function decomposition (most repos have Python)

Python is the most common language in the corpus (present in 20+ repos).

1. Use ast.parse to extract functions (reuse Exp 37 approach)
2. Extract docstrings as separate belief nodes
3. Run on project-a, smoltcp (has Python tests), gsd-2 (has Python scripts)
4. Measure: partition count reduction? Vocabulary overlap change?

### Phase 3: Compare file-level vs sentence-level HRR

The definitive test:
1. Same repos, same edges, same queries
2. File-level encoding (current) vs sentence-level encoding
3. Measure R@10 at both levels
4. Measure vocabulary overlap distribution at both levels
5. Hypothesis: sentence-level will have lower overlap (more HRR value) and fewer partitions (better R@10)

---

## Phase 1 Results: Sentence Decomposition on 3 Pilots

### Decomposition Yield

| Repo | Files | Sentence Nodes | Edges | Methods | Top Node Types |
|------|-------|---------------|-------|---------|---------------|
| project-d | 171 | 4,276 | 4,244 | md:105, py:56, regex:26 | CLAIM 3174, CONSTRAINT 324, FUNCTION 262 |
| smoltcp | 110 | 2,855 | 2,753 | regex:121, md:2, py:1 | FUNCTION 2350, CLAIM 444 |
| gsd-2 | 1,871 | 28,107 | 26,645 | regex:2288, md:581, py:4 | CLAIM 16391, FUNCTION 6994, CONSTRAINT 1566 |

project-d goes from 415 file nodes to 4,276 sentence nodes (10.3x). gsd-2 from 3,331 to 28,107 (8.4x).

### Vocabulary Overlap: File-Level vs Sentence-Level

| Repo | Level | Mean Overlap | % < 0.1 (HRR territory) | % > 0.3 (FTS5 territory) |
|------|-------|-------------|------------------------|-------------------------|
| project-d | file | 0.155 | 38.5% | 8.7% |
| project-d | **sentence** | **0.048** | **82.0%** | **1.8%** |
| gsd-2 | file | 0.170 | 20.0% | 8.2% |
| gsd-2 | **sentence** | **0.075** | **85.8%** | **5.4%** |
| smoltcp | file | 0.160 | 21.7% | 8.6% |
| smoltcp | **sentence** | **0.188** | **41.0%** | **27.4%** |

**Key finding:** Sentence-level decomposition dramatically increases the proportion of low-overlap edges for document-heavy repos:

- **project-d:** 38.5% -> 82.0% of edges below 0.1 overlap. Mean drops from 0.155 to 0.048 (3.2x reduction). This means HRR goes from "adds moderate value" to "essential for 82% of edges."
- **gsd-2:** 20.0% -> 85.8% below 0.1. Mean drops from 0.170 to 0.075 (2.3x reduction).
- **smoltcp:** Mixed result. The <0.1 fraction increases (21.7% -> 41.0%) but so does >0.3 (8.6% -> 27.4%). Adjacent functions in the same Rust module share vocabulary heavily (same types, same patterns). HRR value increases for cross-module edges but decreases for within-module edges.

**Interpretation:** At sentence level, individual paragraphs/claims about different topics have genuinely different vocabulary. A paragraph about "dispatch gates" and a paragraph about "flow control" are separate nodes with low overlap, whereas at file level they're merged into one node with blended vocabulary. This is exactly why Exp 29 showed sentence-level retrieval outperforming decision-level (100% vs 92%).

For pure-code repos (smoltcp), the benefit is less clear because code within a module shares a vocabulary of types and function names. The HRR value at sentence level is concentrated in cross-module edges, not within-module edges.

---

## Open Questions

1. **How do sentence-level nodes affect edge types?** A file-level CO_CHANGED edge becomes ambiguous at sentence level -- which sentences in the file are coupled? We'd need to either (a) propagate file-level edges to all sentences in the file, or (b) use finer-grained signals (git hunk-level diff, function-level changes).

2. **Does sentence-level increase noise?** More nodes = more potential for weak edges. If every paragraph in every markdown file is a node, the graph gets large fast. Need thresholding or filtering.

3. **What's the right granularity for code?** Function-level is natural for Python but may be too coarse for large functions or too fine for one-liners. Class-level? Block-level? The right answer may vary by language and coding style.
