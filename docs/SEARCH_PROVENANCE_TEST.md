# Search Provenance Test: alpha-seek-memtest (2026-04-11)

## Objective
Test whether mem:search can reconstruct a project's self-provenance -- its identity, purpose, and lineage to other projects -- purely from onboarded beliefs (git history, docs, code) without being explicitly told.

## Setup
- Project: alpha-seek-memtest (619 commits, 1,726 docs, 16 days of history)
- DB: isolated at ~/.agentmemory/projects/4b0f8c37972f/memory.db
- 65k beliefs, onboarded from project directory only (no conversation data)

## Test 1: "what is this project about"

**Query:** `what is this project about`

**Result:** 16 beliefs returned. Vague. Found "Purpose: Living project description" but not the actual description. Most results were generic fragments matching "project" and "about" keywords.

**Verdict:** FTS5 keyword matching is too broad for abstract questions. The system found structural markers ("Purpose:", "Goal:", "Out of Scope") but couldn't synthesize them into an answer.

## Test 2: "alpha seek trading strategy options"

**Query:** `alpha seek trading strategy options`

**Result:** 28 beliefs. Found concrete operational details:
- File paths: `/srv/data/alpha-seek/data/options.duckdb`
- Infrastructure: launchd jobs, paper trading configs, archon working directory
- "Research: New Approaches to the Alpha-Seek Strategy"

**Verdict:** Domain-specific keywords work well. The system knows this is a trading project with options, paper trading, and specific infrastructure.

## Test 3: "project purpose goal objective mission"

**Query:** `project purpose goal objective mission`

**Result:** 29 beliefs. Surfaced the core objective:
- "This milestone advances the project's core objective (positive E[V] across multiple years)"
- "The project documents (PROJECT.md Core Objective, D002 minimum 2x return, Constraints 'lottery-ticket long options only')"
- "The strategic arc: The project has exhausted single-contract, single-objective, static-regime approaches"

**Verdict:** Multi-keyword OR matching found the real substance. The system can identify the project's purpose when given enough semantic handles.

## Test 4: "alpha-seek memtest relationship to alpha-seek optimus-prime"

**Query:** `alpha-seek memtest relationship to alpha-seek optimus-prime`

**Result:** 27 beliefs. Reconstructed the full lineage chain:

### Provenance chain discovered:
1. **optimus-prime** is the original codebase (backtest, data, signal, portfolio, stats modules -- 61 files, ~15.6K LOC)
2. **alpha-seek** was created as a separate project but depended on optimus-prime via symlinks
3. Decision **D090** decoupled them: copied all optimus-prime modules into alpha-seek as real directories
4. **alpha-seek-memtest** is an iteration of alpha-seek, with imports resolved to alpha-seek-memtest instead of old alpha-seek

### Specific evidence the system found:
- "Migrated all optimus-prime source modules into alpha-seek as real directories (D090)"
- "Decouple alpha-seek from optimus-prime symlinks: Copy all 5 optimus-prime modules..."
- "alpha-seek self-contained: no optimus-prime runtime dependency (D090)"
- "Fixed sys.path hardcoded path in runsignalbacktest.py and venv editable install finder to resolve imports from alpha-seek-memtest instead of old alpha-seek project"
- "we need to keep alpha-seek and optimus-prime separate"
- "If you need code from optimus-prime, copy it into alpha-seek and adapt it"

### Infrastructure provenance:
- Runs on archon at `/srv/data/alpha-seek/`
- DuckDB symlinked from optimus-prime (28GB file)
- GCP Artifact Registry: `us-central1-docker.pkg.dev/secretary-487605/optimus-training/alpha-seek`
- Project root: `/Users/thelorax/projects/alpha-seek-memtest`

**Verdict:** Given all three project names in the query, the system returned detailed evidence of their relationship from commit messages, decision docs, and CLAUDE.md entries. This is retrieval of known relationships, not autonomous discovery -- the user provided the project names, and the system found confirming evidence. Still, it surfaced thorough, actionable detail (D090, migration steps, infrastructure) that would otherwise require reading hundreds of docs.

## Analysis

### What works
- **Domain-specific keyword search**: queries with project-specific terms (alpha-seek, optimus-prime, trading, options) return highly relevant results
- **Provenance retrieval**: given project names, the system finds detailed evidence of relationships from commit messages, decision records, and infrastructure docs. It does not discover lineage autonomously -- the user must supply the project names.
- **Operational knowledge**: file paths, deployment configs, infrastructure details are well-captured
- **Decision traceability**: D090, D002, D099 and other decision IDs surface as anchor points

### What doesn't work
- **Abstract questions**: "what is this project about" returns structural markers, not substance
- **Synthesis**: the system returns fragments, not a coherent narrative -- synthesis requires an LLM layer on top (like /mem:wonder)
- **FTS5 noise**: common words ("project", "about", "this") match too broadly

### Implications for product
1. **Search is a retrieval tool, not an answer tool.** It surfaces relevant fragments. Synthesis is a separate step.
2. **Project onboarding captures provenance implicitly.** Git commit messages and doc sentences contain lineage information, but the user must know what to search for. The system retrieves evidence of relationships; it does not discover them.
3. **Domain vocabulary is the key to good search.** Users who know their project's terms get good results. New users who don't know the vocabulary need a different entry point (like /mem:core or /mem:wonder).
4. **Decision IDs (D###) are powerful anchors.** They connect scattered beliefs about the same topic across different documents and time periods.
