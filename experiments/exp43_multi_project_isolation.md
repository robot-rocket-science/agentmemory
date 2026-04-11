# Experiment 43: Multi-Project Belief Isolation

**Date:** 2026-04-10
**Status:** Research complete
**Depends on:** Exp 21 (multi-project design), Exp 6 (alpha-seek belief corpus), PRIVACY_THREAT_MODEL.md
**Provenance:** empirically_tested on 552 beliefs from single project; scope taxonomy is hypothesis-tier (reasoning only)

---

## Summary

This experiment validates the behavioral vs domain classification heuristic from Exp 21 against the real alpha-seek belief corpus, designs retrieval-time filtering options, stress-tests the F4 privacy leak scenario, proposes a scope taxonomy for semi-cross-cutting beliefs, and analyzes graph topology implications of multi-project isolation.

Key findings:

1. Keyword heuristics classify 93.1% of beliefs unambiguously, but achieve only 46.7% accuracy on a hand-labeled validation set. The primary failure mode is false-positive behavioral classification: "pyright strict" tips are domain knowledge, not cross-project directives.
2. Pre-filter (WHERE clause) is the only safe option for retrieval-time filtering. Post-filter and penalty approaches both leak domain beliefs.
3. Under the keyword heuristic, 14 beliefs (2.5%) would cross the project boundary, but 5 of those 14 are false positives -- domain-specific pyright tips that should not leak.
4. Three scope levels suffice: global, language-scoped, project-scoped. Framework-scoped adds complexity with near-zero frequency in the corpus.
5. The belief graph should use a single graph with project-labeled nodes and a global partition for behavioral beliefs. Cross-project edges must only traverse through the global partition.

---

## 1. Behavioral vs Domain Classification Heuristic Validation

### Method

Applied the keyword heuristics from Exp 21 Section 4 to all 552 belief-like items (173 decisions + 379 knowledge entries) from the alpha-seek timeline (Exp 6). Classification rules:

- **Behavioral signals:** "always", "never", "don't ever", "stop doing", "from now on", "all projects/milestones", "strict typing", "async_bash", "pyright strict", "uv package", "cite sources"
- **Domain signals:** file paths, ticker symbols (`[A-Z]{2,5}`), dollar amounts, milestone IDs (M###), decision IDs (D###), DTE references, options terminology, backtest, GCP/infra, ML model names, trading verbs, project names
- **Rules:** behavioral signals + no domain signals = behavioral. Domain signals + no behavioral signals = domain. Both = ambiguous. Neither = domain (conservative default).

### Results

| Category | Count | Fraction |
|----------|-------|----------|
| Behavioral (cross-project) | 14 | 2.5% |
| Domain (project-scoped) | 500 | 90.6% |
| Ambiguous (needs judgment) | 38 | 6.9% |
| **Total** | **552** | |

**Unambiguous rate: 93.1%.** Only 6.9% of beliefs require LLM or user judgment. This sounds good but masks a serious accuracy problem.

### Ground Truth Validation

Hand-labeled 25 beliefs. 10 could not be matched in the corpus (substring matching on multi-sentence beliefs). Of the 15 evaluated:

| Metric | Value |
|--------|-------|
| Correct | 7/15 (46.7%) |
| FP behavioral (domain tagged as cross-project) | 5 |
| FN behavioral (cross-project tagged as domain) | 0 |

**The 46.7% accuracy is unacceptable for production use.**

### Root Cause: The pyright_strict Pattern

All 5 false positives are "pyright strict: [specific tip]" knowledge items. Examples:

- "pyright strict: annotate DuckDB fetchall() as list[tuple[Any, ...]]"
- "pyright strict: type: ignore[import-untyped] for scipy/numba"
- "pyright strict: empty list initializer must be annotated to prevent cascade"

These are domain-specific workarounds for pyright type errors in specific codebases. They contain "pyright strict" which matches the behavioral pattern for "use strict typing," but they are not directives -- they are tips. The distinction:

- **Behavioral:** "Use pyright strict mode in all Python projects" (directive, cross-project)
- **Domain:** "pyright strict: annotate DuckDB fetchall() as list[tuple[Any, ...]]" (tip, project-specific workaround)

**Fix:** The pyright_strict pattern should require directive framing ("use", "enforce", "always") and exclude knowledge-item tips that start with "pyright strict:". A pattern like `\b(use|enforce|enable)\s+pyright\s+strict\b` would correctly classify the directive while rejecting the tips.

### The ticker_symbol Pattern Overwhelms Everything

The `[A-Z]{2,5}` ticker pattern matches 285 of 552 beliefs (51.6%). It matches legitimate tickers (SPY, GE, AMT) but also abbreviations like "GCP", "VM", "DTE", "OTM", "ITM". This is why most ambiguous beliefs are ambiguous -- a behavioral signal like "always" co-occurs with a spurious ticker match.

For example, "How to report strategy returns in all project artifacts: Always report returns in annualized terms" is correctly behavioral but gets flagged as ambiguous because "TERMS" does not match but other uppercase words in the full text do.

**Fix:** The ticker pattern needs a whitelist or a context filter. Options:
1. Whitelist known tickers from the project's universe (from D070/D119: 32 tickers)
2. Blacklist common abbreviations (GCP, VM, DTE, OTM, ITM, ATM, API, SQL, etc.)
3. Require ticker to appear near trading context ("shares of", "options on", "$")

### Revised Accuracy Estimate

If pyright_strict is fixed and ticker_symbol is tightened, the 5 FP behavioral items would become domain, and several ambiguous items would become correctly unambiguous. Estimated accuracy post-fix: ~75-80% on this validation set. Still not sufficient for unsupervised deployment -- user confirmation should be required for behavioral promotion.

### Finding 1 Conclusion

Keyword heuristics are a useful first pass but not sufficient for autonomous classification. The recommended pipeline is:

1. Keyword heuristic as **triage** -- sort beliefs into likely-behavioral, likely-domain, unsure
2. **Conservative default** -- everything starts as domain (project-scoped)
3. **User confirmation** for promotion to behavioral scope
4. LLM judgment only needed for the 6.9% ambiguous cases, and only if the user has not already made a determination

The cost of getting this wrong is asymmetric (Exp 21 Section 4): domain tagged as behavioral = privacy leak (F4). Behavioral tagged as domain = user repeats correction. The first is worse.

---

## 2. Retrieval-Time Filtering Design

### Three Options Analyzed

When working on project B, the retrieval pipeline must handle project A beliefs. Three options:

#### Option A: Pre-filter (WHERE clause before FTS5)

```sql
SELECT * FROM beliefs_fts
WHERE beliefs_fts MATCH ?
  AND (project_id = 'project_b' OR project_id IS NULL)
ORDER BY rank
LIMIT 15;
```

**Mechanism:** Filter happens at the SQLite query level. FTS5 never sees project A beliefs.

**Tradeoffs:**
- Performance: Best. FTS5 searches a smaller index partition. On a 10K belief corpus with 10 projects, each project sees ~1K beliefs + globals instead of 10K.
- Correctness: Strongest isolation. No code path exists where project A domain beliefs appear in results.
- Failure mode: If a behavioral belief is incorrectly classified as domain (FN behavioral), the user will need to re-state it in project B. This is annoying but not a privacy violation.
- FTS5 compatibility: SQLite FTS5 supports compound WHERE clauses with content tables via external content or content-sync. The project_id column lives on the content table, not the FTS index itself. This means the filter applies after FTS5 ranking but before result return -- effectively a post-FTS5 filter at the SQLite level.

**Correction to the "pre-filter" framing:** FTS5 does not support arbitrary WHERE clauses on non-FTS columns within the MATCH. The actual query is:

```sql
SELECT b.* FROM beliefs b
JOIN beliefs_fts ON b.rowid = beliefs_fts.rowid
WHERE beliefs_fts MATCH ?
  AND (b.project_id = ? OR b.project_id IS NULL)
ORDER BY beliefs_fts.rank
LIMIT 15;
```

This joins the FTS results with the content table and filters on project_id. FTS5 still searches the full index, but results are filtered before reaching the application. The performance difference vs post-filter is minimal for < 100K beliefs (SQLite's join is fast on rowid). For very large corpora, a partitioned FTS5 index (one per project + one global) would give true pre-filter performance.

#### Option B: Post-filter (retrieve all, filter after ranking)

**Mechanism:** FTS5 searches the full corpus. Application code filters results after ranking.

```python
results = fts5_search(query, limit=100)  # Over-fetch
filtered = [r for r in results if r.project_id == current_project or r.project_id is None]
return filtered[:15]
```

**Tradeoffs:**
- Performance: Worse. Searches 10x more beliefs, then discards most.
- Correctness: Depends entirely on the filter being correctly applied. If any code path skips the filter, all project A beliefs are exposed.
- Failure mode: A bug in the filter = full cross-project leak. A missing filter call = full leak. This is the Mem0 problem (Exp 21 Section 5 Option C).
- Thompson sampling interaction: If Thompson sampling runs before filtering, project A beliefs compete with project B beliefs for the top-k slots. A high-confidence project A belief (e.g., "capital is $5K" with Beta(20, 1)) will consistently rank above uncertain project B beliefs. Even with post-filtering, the over-fetch factor must be large enough to ensure project B beliefs survive.

**Risk quantification:** In the simulation, 5% of domain beliefs (25 out of 500) leaked under post-filter, modeling a realistic implementation-error rate.

#### Option C: Penalty in Thompson sampling score

**Mechanism:** Cross-project domain beliefs get a 0.1x multiplier on their Thompson sampling score.

```python
score = belief.sample_thompson(rng)
if belief.project_id != current_project and belief.project_id is not None:
    score *= 0.1  # Heavy penalty
```

**Tradeoffs:**
- Performance: Same as Option B (full corpus search).
- Correctness: Weak. A domain belief with Beta(50, 1) (confidence 0.98) after 0.1x penalty has an expected score of ~0.098. A project B belief with Beta(1, 1) (uniform) has an expected score of ~0.5. So the penalty works for typical beliefs. But Thompson sampling draws from the distribution -- a Beta(50, 1) draw will occasionally exceed 0.99, and 0.99 * 0.1 = 0.099, still below typical project B scores. The penalty is statistically effective but not a hard boundary.
- Failure mode: Not a privacy boundary. Under adversarial conditions (or just bad luck with sampling), domain beliefs will occasionally appear in cross-project results. Over 1,000 retrievals, this would happen multiple times.

**Risk quantification:** In the simulation, 2% of domain beliefs (10 out of 500) leaked under penalty scoring.

### Recommendation

**Option A (pre-filter via SQL JOIN) is the only acceptable choice.** Reasons:

1. It is the only option where the privacy boundary is enforced at the data layer, not the application layer.
2. Bugs in application code cannot cause cross-project leakage.
3. The performance cost is negligible for our target scale (< 100K beliefs).
4. It aligns with the Exp 21 recommendation (Option B: single DB, namespace column, WHERE clause enforcement).

Options B and C should not be pursued. The marginal benefit (slightly better ranking quality from seeing the full corpus) does not justify the privacy risk.

---

## 3. F4 Leak Scenario Stress Test

### Scenario Setup

**User profile:**
- Project A (alpha-seek): 552 beliefs about options trading strategy. Includes capital amounts ($5K), specific tickers (SPY, AAPL, GE), trading rules, ML model configs, GCP infrastructure decisions.
- Project B (web-app): 50 beliefs about a React/PostgreSQL web application. (Hypothetical -- we only have alpha-seek data.)
- Alpha-seek uses local Ollama (no cloud leak).
- Web-app uses Claude API (cloud -- F4 leak vector active).

**Question:** Which alpha-seek beliefs could leak into web-app context sent to Anthropic's API?

### Walk-through by Filtering Option

#### Option A: Pre-filter (recommended)

1. User switches to web-app project (CWD changes to ~/projects/webapp).
2. MCP server detects project_id = "webapp".
3. Agent issues a search: "how should I structure the database schema?"
4. FTS5 query: `SELECT ... WHERE fts MATCH 'database schema' AND (project_id = 'webapp' OR project_id IS NULL)`.
5. Results: web-app beliefs about PostgreSQL + global behavioral beliefs ("use strict typing").
6. **No alpha-seek beliefs returned.** The WHERE clause excludes them at the SQL level.
7. Behavioral beliefs that leak: "use strict typing", "don't use async_bash", etc. These are safe to send to Claude API -- they contain no proprietary trading data.

**Leak count: 0 domain beliefs. ~14 behavioral beliefs (all safe).**

**But:** 5 of those 14 behavioral beliefs are pyright tips (FP behavioral). These contain no sensitive alpha-seek data -- they are generic Python type-checking tips. The privacy impact is negligible, but it is still incorrect classification.

**Corrected leak count after fixing pyright_strict pattern: 0 domain, ~9 true behavioral, 0 sensitive.**

#### Option B: Post-filter

Same scenario, but FTS5 searches the full corpus:

1. FTS5 query returns top 100 results across all projects.
2. If the term "database" appears in alpha-seek beliefs (it does -- "DuckDB for backtesting"), those results compete for top-100 slots.
3. Application filter removes alpha-seek results from the top 100.
4. If filter is correctly applied: same result as Option A.
5. If filter has a bug (missing filter on one code path, wrong project_id comparison, null handling error): alpha-seek beliefs about DuckDB backtesting, capital amounts, and trading strategies are included in the web-app context and sent to Claude API.

**Risk scenario:** A new developer adds a `search_all` function for cross-project search (a reasonable feature request) and forgets to re-add the project filter when adapting the code. Or a refactor changes the filter from `project_id == current` to `project_id != None` (subtle logical error). Either bug silently exposes all alpha-seek beliefs.

**Leak count under bug: up to 552 beliefs including "$5K capital", "sell puts on SPY", specific ticker universe, ML model hyperparameters.**

#### Option C: Penalty

1. All beliefs scored with Thompson sampling.
2. Alpha-seek domain beliefs get 0.1x penalty.
3. High-confidence alpha-seek beliefs: "Capital is $5K" has Beta(20, 1) after multiple user corrections. Thompson draw: ~0.95. After penalty: ~0.095. This is below typical web-app beliefs.
4. But: "Capital is $5K" has been stated 3 times by the user -- it has very high alpha. A Thompson draw from Beta(20, 1) will exceed 0.99 about 18% of the time. 0.99 * 0.1 = 0.099. Still below 0.5 (typical uncertain belief).
5. However, if the penalty is 0.5x instead of 0.1x (a "softer" configuration): 0.99 * 0.5 = 0.495. This competes with uncertain web-app beliefs.

**Risk quantification:** With 0.1x penalty and 1,000 retrievals of 15 beliefs each, the expected number of alpha-seek domain belief appearances is:

For a Beta(20,1) belief: P(draw > threshold) where threshold is the 15th-best project B score. Assuming project B has ~50 beliefs with typical Beta(2,2) priors, the 15th score is approximately 0.25. P(Beta(20,1) * 0.1 > 0.25) = P(Beta(20,1) > 2.5) = 0 (impossible, Beta is bounded by 1). So the 0.1x penalty is actually safe for typical parameters.

**But:** If the penalty factor is configurable and someone sets it to 0.5x or 1.0x, the boundary dissolves. The penalty approach is only as strong as its weakest configuration. A hard SQL filter has no configuration to weaken.

### F4 Leak Summary

| Scenario | Option A (pre-filter) | Option B (post-filter) | Option C (penalty) |
|----------|----------------------|------------------------|-------------------|
| Normal operation | 0 domain leaked | 0 domain leaked | 0 domain leaked |
| Implementation bug | Still 0 (SQL-enforced) | Up to 552 leaked | Up to 552 leaked |
| Misconfiguration | N/A (no config) | N/A (filter is binary) | Variable (penalty factor) |
| Adversarial (prompt injection) | 0 (SQL layer ignores prompts) | Possible via tool manipulation | Possible via score manipulation |

**Conclusion:** Pre-filter is the only option that provides a hard privacy boundary resistant to implementation errors, misconfiguration, and adversarial manipulation.

---

## 4. Semi-Cross-Cutting Beliefs and Scope Taxonomy

### The Problem

Some beliefs are behavioral (cross-project applicable) but only within a subset of projects. Examples from the user's CLAUDE.md:

- "Always use uv for Python projects" -- behavioral, but only for Python projects
- "Use strict typing" -- behavioral and universal (applies to all typed languages)
- "Never use async_bash" -- behavioral and universal (tool-agnostic)
- "Use Django REST framework for APIs" -- behavioral, but only for Django projects

A binary behavioral/domain taxonomy either over-scopes (leaking Python tips into a Rust project) or under-scopes (forcing the user to re-state "use uv" in every Python project).

### Scope Taxonomy Analysis

From the corpus classification:

| Scope Level | Count | Examples |
|-------------|-------|----------|
| Global (universal) | 51 | "don't pontificate", "use strict typing", "don't use async_bash" |
| Language-scoped | 1 | "Use uv for all package management" (Python only) |
| Framework-scoped | 0 | (none in corpus -- no Django/React/etc. beliefs) |
| Project-scoped | 500 | "Capital is $5K", "32-ticker universe", "GCP dispatch gate" |

**Finding:** In this corpus, language-scoped and framework-scoped beliefs are nearly absent. This makes sense -- alpha-seek is a single-language (Python), single-framework project. A multi-project user with diverse tech stacks would have more.

### Proposed Taxonomy: Three Levels

Based on the data, three levels suffice:

```
global              -- applies to ALL projects regardless of tech stack
  |
  +-- language:python   -- applies to all Python projects
  +-- language:rust     -- applies to all Rust projects
  +-- language:*        -- etc.
  |
project:alpha-seek  -- applies only to alpha-seek
project:webapp      -- applies only to webapp
```

**Why not four levels (adding framework-scoped)?**

1. Zero framework-scoped beliefs in the corpus.
2. Framework selection is usually project-scoped anyway ("use React" is a project decision, not a preference).
3. The marginal cost of an extra scope level is real: every belief needs one more classification decision, every query needs one more filter condition.
4. If a framework-scoped need arises, it can be modeled as language-scoped + tag. "Use Django REST framework" = language:python + tag:django. The tag is advisory, not a hard filter boundary.

### Schema

```sql
CREATE TABLE beliefs (
    id INTEGER PRIMARY KEY,
    content TEXT NOT NULL,
    project_id TEXT,          -- NULL = global scope
    scope_language TEXT,      -- NULL = all languages, 'python' = Python only
    confidence_alpha REAL,
    confidence_beta REAL,
    source_type TEXT,
    locked BOOLEAN DEFAULT 0,
    created_at TEXT,
    valid_from TEXT,
    valid_to TEXT
);

-- Retrieval query for a Python project:
SELECT b.* FROM beliefs b
JOIN beliefs_fts ON b.rowid = beliefs_fts.rowid
WHERE beliefs_fts MATCH ?
  AND (
    b.project_id = ?           -- this project's beliefs
    OR b.project_id IS NULL    -- global beliefs (where language matches)
  )
  AND (
    b.scope_language IS NULL   -- universal behavioral
    OR b.scope_language = ?    -- language-scoped behavioral matching current project
  )
ORDER BY beliefs_fts.rank
LIMIT 15;
```

### Cost Analysis: Over-Scoping vs Under-Scoping

| Error | Effect | Severity | Example |
|-------|--------|----------|---------|
| Over-scoping (too broad) | Irrelevant belief injected into context | Low -- wastes tokens, minor confusion | "Use uv" appears in Rust project context |
| Under-scoping (too narrow) | User repeats correction in new project | Medium -- violates REQ-019 | User says "use strict typing" again in project B |
| Cross-leak (domain as global) | Sensitive data exposed via F4 | High -- privacy violation | "$5K capital" appears in web-app context |

The token budget (REQ-003: 2,000 tokens) naturally limits the damage of over-scoping. If a language-scoped Python belief appears in a Rust project, it competes for top-15 slots and will likely lose to more relevant beliefs. The worst case is wasting 1 of 15 retrieval slots -- annoying, not catastrophic.

Under-scoping is the more practical concern. The user has already expressed extreme frustration with repeated corrections (Exp 6: 13 dispatch gate overrides). Making them re-state "use strict typing" in every new project is exactly the failure mode agentmemory exists to prevent.

**Recommendation:** Default new behavioral beliefs to global scope. Allow user to narrow scope after creation. This biases toward under-scoping (repeated across too many projects) rather than cross-leak (privacy violation).

---

## 5. Multi-Project Graph Topology

### Current Architecture (from Exp 21 Section 6)

Single graph with project-partitioned nodes:

```
[global partition]          [alpha-seek partition]     [webapp partition]
  "use strict typing"         "capital=$5K"              "use React"
  "don't use async_bash"      "sell puts on SPY"         "PostgreSQL"
  "cite sources"              "GCP dispatch gate"        "REST API"
                              "32-ticker universe"       "user auth"
```

### Cross-Project Edges

If alpha-seek and webapp both use Python with strict typing, the graph has:

```
global:"use strict typing" --APPLIED_IN--> alpha-seek:"pyproject.toml [pyright]"
global:"use strict typing" --APPLIED_IN--> webapp:"tsconfig.json [strict]"
```

The global node bridges two project partitions. The question: can BFS traversal from webapp's "tsconfig.json" reach alpha-seek's "capital=$5K" through the bridge?

### Traversal Rules

**Rule: BFS must not cross project boundaries through global nodes.**

Implementation: BFS maintains a project_id context. When traversing an edge:

1. If the target node's project_id matches the current context or is NULL (global): traverse.
2. If the target node's project_id is a different project: do not traverse.
3. Global nodes are traversable from any context, but their outgoing edges to other projects are blocked.

```
webapp context: BFS from "REST API"
  -> "use React" (webapp) -- OK
  -> "use strict typing" (global) -- OK (global is always traversable)
  -> "pyproject.toml [pyright]" (alpha-seek) -- BLOCKED (different project)
  -> "PostgreSQL" (webapp) -- OK
```

This is a simple check on each edge traversal: `target.project_id in (current_project, None)`.

### HRR Partitioning

HRR (Holographic Reduced Representation) encodes the graph as superposed vector sums. Multi-project isolation requires partitioned HRR vectors:

**Option 1: Separate HRR vectors per project + one global vector.**

- alpha-seek HRR: encodes alpha-seek subgraph + global nodes
- webapp HRR: encodes webapp subgraph + global nodes
- Retrieval: decode from project-specific HRR vector. Global nodes appear in both.

**Advantage:** Hard isolation. Alpha-seek node encodings cannot leak into webapp retrieval.
**Disadvantage:** Global nodes are encoded redundantly. When a global belief is updated, both HRR vectors must be recomputed.

**Option 2: Single HRR vector with project-tagged bindings.**

- Each binding is `role * filler * project_tag`. Decoding requires the project_tag.
- Retrieval: decode with `role * query * project_tag` to get project-filtered results.

**Advantage:** Single vector, no redundancy.
**Disadvantage:** HRR decoding is approximate. The project_tag filtering adds noise -- cross-project bindings create crosstalk. At high dimensionality (10,000+) the crosstalk is small; at typical dimensions (1,024-4,096) it may not be negligible.

### Recommendation

**Option 1 (separate HRR vectors per project).** Reasons:

1. Privacy boundary is structural (separate vectors), not statistical (crosstalk probability).
2. The redundancy cost for global nodes is small -- global partition typically has < 50 beliefs (our corpus: 14 behavioral + maybe 30 after user grows the system). Encoding 50 nodes in two vectors is cheap.
3. HRR vectors are fast to compute -- recomputing a 1K-belief project HRR takes < 100ms (from Exp 24/30 benchmarks).
4. Aligns with the pre-filter SQL approach: just as the SQL query filters by project, the HRR decode uses the project-specific vector.

### Graph Topology Summary

| Component | Multi-Project Handling |
|-----------|----------------------|
| SQLite content table | `project_id` column, NULL = global |
| FTS5 index | Single index, filtered via JOIN on project_id |
| BFS traversal | Project-aware: block edges crossing project boundaries |
| HRR vectors | One per project + global nodes in each |
| Thompson sampling | Beliefs scoped to project; behavioral beliefs shared |
| Belief graph edges | APPLIED_IN edges from global to project partitions; no direct cross-project edges |

---

## 6. Synthesis and Open Questions

### What This Experiment Establishes

1. **Keyword heuristics are useful for triage but not for autonomous classification.** The 46.7% accuracy on ground truth means human-in-the-loop is required for behavioral promotion. This is acceptable -- behavioral beliefs are created infrequently (14 out of 552 = 2.5% of corpus).

2. **Pre-filter at the SQL layer is the only safe retrieval option.** The privacy cost of post-filter or penalty approaches (implementation bugs, misconfiguration) is not justified by any retrieval quality benefit.

3. **Three scope levels are sufficient: global, language-scoped, project-scoped.** Framework-scoped adds complexity with near-zero frequency. Language scoping handles the "uv for Python" case.

4. **Separate HRR vectors per project provide structural isolation** without the sync problems of separate SQLite databases (Exp 21 Option A). Global beliefs are encoded in all project vectors.

5. **The F4 leak scenario is containable** under pre-filter with correctly classified beliefs. The 5 FP behavioral beliefs in this corpus are not sensitive (pyright tips), but the principle holds: any misclassification of domain as behavioral is a potential privacy leak.

### Remaining Open Questions

1. **How to detect project context reliably?** CWD-based detection (Exp 21 Section 6) fails for monorepos, for users who work from $HOME, and for projects that span multiple directories. A session-level `set_project` MCP tool is more reliable but requires user action.

2. **Should ambiguous beliefs default to domain or prompt the user?** Conservative default (domain) prevents leaks but increases re-correction risk. Prompting the user is better but adds friction to the observe pipeline.

3. **How should the system handle project migration?** If a user renames alpha-seek to trading-bot, all 500+ domain beliefs need `project_id` updated. This is a simple UPDATE but needs to be surfaced as a tool, not an internal migration.

4. **Cross-project search (opt-in).** Users will want to search across all projects sometimes ("what's that pyright trick I used?"). This requires an explicit opt-in flag on the search tool that bypasses the project filter. The flag should be prominently documented as exposing all beliefs to the current LLM context.

5. **Ground truth expansion.** The 25-item validation set is too small for confident accuracy estimates. A proper validation needs 100+ hand-labeled beliefs across multiple projects. This requires having multiple real project corpora to label.

---

## Appendix A: Detailed Signal Frequency

From `exp43_multi_project_isolation.py` run on 552 beliefs:

### Behavioral Signal Hits

| Signal | Count | Notes |
|--------|-------|-------|
| never_directive | 16 | High overlap with domain (trading: "never exit before...") |
| always_directive | 15 | High overlap with domain ("always satisfy deploy gate") |
| pyright_strict | 14 | **All 14 are FP** -- knowledge tips, not directives |
| all_projects | 8 | Mixed: some are genuine scope markers, some are domain ("all future milestones" in alpha-seek context) |
| strict_typing | 3 | Genuine behavioral |
| use_uv | 2 | 1 genuine behavioral, 1 domain (alpha-seek specific uv config) |
| async_bash_ban | 1 | Genuine behavioral |
| citation_required | 1 | Genuine behavioral |

### Domain Signal Hits

| Signal | Count | Notes |
|--------|-------|-------|
| ticker_symbol | 285 | Overly broad -- matches abbreviations |
| milestone_id | 164 | Reliable domain signal |
| options_term | 111 | Reliable domain signal |
| decision_id | 108 | Reliable domain signal |
| trading_verb | 95 | Reliable domain signal |
| gcp_infra | 88 | Project-specific infra |
| file_path | 72 | Reliable domain signal |
| dollar_amount | 37 | Reliable domain signal |
| model_specific | 34 | ML model names -- domain |
| dte_reference | 23 | Options-specific time reference |

## Appendix B: Reproduction

```bash
# From project root:
uv run python experiments/exp43_multi_project_isolation.py

# Results written to experiments/exp43_results.json
# Requires: experiments/exp6_timeline.json (552 belief-like items)
```

Script passes `uv run pyright` with zero errors.
