# Search Provenance Test: project-a-test (2026-04-11)

## Objective
Test whether mem:search can reconstruct a project's self-provenance -- its identity, purpose, and lineage to other projects -- purely from onboarded beliefs (git history, docs, code) without being explicitly told.

## Setup
- Project: project-a-test (619 commits, 1,726 docs, 16 days of history)
- DB: isolated at ~/.agentmemory/projects/4b0f8c37972f/memory.db
- 65k beliefs, onboarded from project directory only (no conversation data)

## Test 1: "what is this project about"

**Query:** `what is this project about`

**Result:** 16 beliefs returned. Vague. Found "Purpose: Living project description" but not the actual description. Most results were generic fragments matching "project" and "about" keywords.

**Verdict:** FTS5 keyword matching is too broad for abstract questions. The system found structural markers ("Purpose:", "Goal:", "Out of Scope") but couldn't synthesize them into an answer.

## Test 2: "project-a trading strategy options"

**Query:** `project-a trading strategy options`

**Result:** 28 beliefs. Found concrete operational details:
- File paths: `/srv/data/project-a/data/options.duckdb`
- Infrastructure: launchd jobs, paper trading configs, server-a working directory
- "Research: New Approaches to the Project-A Strategy"

**Verdict:** Domain-specific keywords work well. The system knows this is a trading project with options, paper trading, and specific infrastructure.

## Test 3: "project purpose goal objective mission"

**Query:** `project purpose goal objective mission`

**Result:** 29 beliefs. Surfaced the core objective:
- "This milestone advances the project's core objective (positive E[V] across multiple years)"
- "The project documents (PROJECT.md Core Objective, D002 minimum 2x return, Constraints 'lottery-ticket long options only')"
- "The strategic arc: The project has exhausted single-contract, single-objective, static-regime approaches"

**Verdict:** Multi-keyword OR matching found the real substance. The system can identify the project's purpose when given enough semantic handles.

## Test 4: "project-a memtest relationship to project-a project-b"

**Query:** `project-a memtest relationship to project-a project-b`

**Result:** 27 beliefs. Reconstructed the full lineage chain:

### Provenance chain discovered:
1. **project-b** is the original codebase (backtest, data, signal, portfolio, stats modules -- 61 files, ~15.6K LOC)
2. **project-a** was created as a separate project but depended on project-b via symlinks
3. Decision **D090** decoupled them: copied all project-b modules into project-a as real directories
4. **project-a-test** is an iteration of project-a, with imports resolved to project-a-test instead of old project-a

### Specific evidence the system found:
- "Migrated all project-b source modules into project-a as real directories (D090)"
- "Decouple project-a from project-b symlinks: Copy all 5 project-b modules..."
- "project-a self-contained: no project-b runtime dependency (D090)"
- "Fixed sys.path hardcoded path in runsignalbacktest.py and venv editable install finder to resolve imports from project-a-test instead of old project-a project"
- "we need to keep project-a and project-b separate"
- "If you need code from project-b, copy it into project-a and adapt it"

### Infrastructure provenance:
- Runs on server-a at `/srv/data/project-a/`
- DuckDB symlinked from project-b (28GB file)
- GCP Artifact Registry: `us-central1-docker.pkg.dev/gcp-project-id/optimus-training/project-a`
- Project root: `/home/user/projects/project-a-test`

**Verdict:** Given all three project names in the query, the system returned detailed evidence of their relationship from commit messages, decision docs, and CLAUDE.md entries. This is retrieval of known relationships, not autonomous discovery -- the user provided the project names, and the system found confirming evidence. Still, it surfaced thorough, actionable detail (D090, migration steps, infrastructure) that would otherwise require reading hundreds of docs.

## Test 5: Blind provenance -- "where did this codebase come from"

**Query:** `where did this codebase come from`

**Result:** 25 beliefs. All noise. FTS5 matched "come from" broadly -- returned trading results ("the edge comes from W", "growth comes from strategy winnings"). Zero lineage information.

**Verdict:** Abstract natural language questions fail completely. FTS5 keyword matching has no semantic understanding.

## Test 6: Blind provenance -- "original source code migrated copied modules dependencies"

**Query:** `original source code migrated copied modules dependencies`

**Result:** 27 beliefs. Hit the jackpot without naming any project:
- #1: "Migrated all project-b source modules into project-a as real directories (D090)"
- Full D090 story: 5 modules (backtest, data, signal, portfolio, stats), 61 files, ~15.6K LOC
- Decision rationale, task ID (T03a), infrastructure impact
- "D090 eliminated an entire class of build/deploy bugs"

**Verdict:** Technical vocabulary works. "migrated", "copied", "modules" are the actual terms used in the project's commit messages and docs. The system found the lineage without being given project names.

## Test 7: Blind provenance -- "predecessor parent project forked inherited symlinks shared code"

**Query:** `predecessor parent project forked inherited symlinks shared code`

**Result:** 30 beliefs. Discovered the full lineage chain without naming any project:
- "A prerequisite bug was fixed: hardcoded sys.path to predecessor project project-a" -- names the predecessor
- "fixed hardcoded sys.path to predecessor project" -- confirms lineage
- "If you need code from project-b, copy it into project-a and adapt it -- do not create symlinks" -- surfaces the parent's parent
- "13 decisions recorded (D001, D021-D029 plus inherited D002-D020)" -- decision inheritance
- "sys.path hardcoded to absolute paths is a silent failure mode after project renames"

**Verdict:** Relationship-pattern queries ("predecessor", "inherited", "forked") successfully discover lineage without project names. The system found **project-b -> project-a -> project-a-test** from structural vocabulary alone.

## Performance

All searches against 65k belief corpus:
- **Tokens returned:** 392-683 per query (within 2000 token budget)
- **Pure search time:** 16.5ms
- **CLI wall time:** ~680ms (includes Python startup)

---

## Analysis

### What works
- **Technical vocabulary queries**: "migrated", "copied", "modules", "predecessor", "inherited" find exactly the right beliefs because those are the actual terms used in commits and docs
- **Provenance discovery**: the system CAN discover project lineage without being given project names, if the query uses structural/relationship vocabulary (tests 6, 7)
- **Provenance retrieval**: given project names explicitly, returns thorough detail fast (test 4: 27 beliefs, 610 tokens, 16.5ms)
- **Operational knowledge**: file paths, deployment configs, infrastructure details are well-captured
- **Decision traceability**: D090, D002, D099 and other decision IDs surface as anchor points

### What doesn't work
- **Abstract natural language**: "where did this codebase come from" returns noise (test 5). FTS5 has no semantic understanding.
- **Vague questions**: "what is this project about" returns structural markers, not substance (test 1)
- **Synthesis**: the system returns fragments, not a coherent narrative -- synthesis requires an LLM layer on top (like /mem:wonder)
- **FTS5 common word pollution**: "come", "from", "about", "this" match too broadly

### Implications for product
1. **Search is a retrieval tool, not an answer tool.** It surfaces relevant fragments. Synthesis is a separate step.
2. **Technical vocabulary is the key to good search.** Queries using the same terms that appear in commits and docs get excellent results. Abstract natural language fails.
3. **Project onboarding captures provenance implicitly.** Lineage can be discovered from structural vocabulary alone ("predecessor", "migrated", "inherited") -- but not from vague questions.
4. **Decision IDs (D###) are powerful anchors.** They connect scattered beliefs about the same topic across different documents and time periods.
5. **The gap between tests 5 and 6 is the semantic gap.** "where did this codebase come from" and "original source code migrated copied modules" ask the same question, but only the second works. Embedding-based search would close this gap.
