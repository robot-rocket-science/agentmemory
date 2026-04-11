# Pipeline Audit: Actual State of the 13-Stage Pipeline

**Date:** 2026-04-11
**Method:** Traced actual function calls and data flow through the codebase. No guessing from file existence.

---

## Per-Stage Assessment

### Stage 1: Conversation Capture (hooks -> JSONL)

**Status: WORKING, WIRED**

- `conversation-logger.sh` is installed at `~/.claude/hooks/conversation-logger.sh`
- Wired into `settings.json` under both `UserPromptSubmit` and `Stop` hooks
- Writes JSONL to `~/.claude/conversation-logs/turns.jsonl`
- Output format matches what `ingest_jsonl()` in `ingest.py` expects
- **Upstream:** Claude Code hook system (external)
- **Downstream:** `ingest_jsonl()` can consume the JSONL file, but this is a manual call -- there is no automatic trigger that feeds the JSONL into the pipeline

**Gap:** JSONL accumulates on disk. Nothing reads it automatically. The MCP `ingest` tool processes live text, not the JSONL file. The `ingest_jsonl()` function exists but is never called by any hook or server tool.

---

### Stage 2: Sentence Extraction

**Status: WORKING, WIRED**

- Implemented in `extraction.py` -> `extract_sentences()`
- Called by `ingest.py:ingest_turn()` at line 112: `sentences = extract_sentences(text)`
- `ingest_turn()` is called by `server.py:ingest()` MCP tool
- Also called by `server.py:onboard()` -> `ingest_turn()` for each scanner node
- **Upstream:** Raw text from MCP `ingest` tool or `onboard` tool
- **Downstream:** Sentence list passed to classification (stage 3)

**Connected end-to-end:** Yes, via `ingest` MCP tool -> `ingest_turn()` -> `extract_sentences()`

---

### Stage 3: LLM Classification

**Status: WORKING, WIRED (offline mode only in production)**

- `classification.py` has two paths:
  - `classify_sentences()` -- LLM-based via Haiku ($0.005/session)
  - `classify_sentences_offline()` -- keyword heuristic fallback (36% accuracy)
- Called by `ingest.py:ingest_turn()` at lines 129-132
- `server.py:ingest()` calls `ingest_turn(use_llm=False)` -- always uses offline mode
- `server.py:onboard()` also calls `ingest_turn(use_llm=False)`
- The LLM path works but is never invoked by the MCP server
- **Upstream:** Sentence list from stage 2
- **Downstream:** `ClassifiedSentence` objects with `persist` flag, `sentence_type`, and Beta priors

**Connected end-to-end:** Yes, but only the offline path. The LLM path is available via `ingest_jsonl(use_llm=True)` but nothing calls that.

---

### Stage 4: Bayesian Prior Assignment

**Status: WORKING, WIRED**

- Implemented inside `classification.py` via `TYPE_PRIORS` dict (lines 28-39)
- Each `ClassifiedSentence` gets `alpha` and `beta_param` from the type-to-prior mapping
- Offline classifier also assigns priors via keyword heuristics
- Priors flow through `ingest_turn()` into `store.insert_belief(alpha=cs.alpha, beta_param=cs.beta_param)`
- **Upstream:** Classification type from stage 3
- **Downstream:** Beta(alpha, beta) parameters stored with each belief

**Connected end-to-end:** Yes

---

### Stage 5: Belief Graph Insertion (SQLite + FTS5)

**Status: WORKING, WIRED**

- `store.py:MemoryStore` creates SQLite with WAL mode, FTS5 `search_index`
- Schema includes: sessions, observations, beliefs, evidence, edges, graph_edges, checkpoints, tests, audit_log
- `insert_belief()` writes to beliefs table AND FTS5 search_index
- Content-hash dedup prevents duplicates
- Evidence links created when `observation_id` is provided
- `supersede_belief()` creates SUPERSEDES edges
- **Upstream:** Classified sentences from stage 3-4 via `ingest_turn()`
- **Downstream:** FTS5 search_index available for retrieval (stage 6)

**Connected end-to-end:** Yes. This is the central hub. PIPELINE_STATUS.md said "NOT BUILT" -- that assessment is stale. It is built and working.

---

### Stage 6: FTS5 + HRR Retrieval

**Status: WORKING, WIRED**

- `retrieval.py:retrieve()` implements the full pipeline:
  1. Locked beliefs (L0)
  2. FTS5 search via `store.search()` (L2)
  3. HRR vocabulary-bridge expansion (L3)
  4. Merge, deduplicate, score, compress, pack
- `store.py:search()` uses FTS5 BM25 on `search_index`
- `hrr.py:HRRGraph` builds from `store.get_all_edge_triples()` (both `edges` and `graph_edges` tables)
- HRR expansion finds beliefs connected via typed edges that FTS5 misses
- Called by `server.py:search()` MCP tool
- **Upstream:** Beliefs in FTS5 index from stage 5 + edges from scanner/corrections
- **Downstream:** Scored, compressed belief list for context injection

**Connected end-to-end:** Yes. The HRR path only activates when edges exist in the store (populated by `onboard` or `supersede_belief`).

---

### Stage 7: Temporal Re-ranking

**Status: WORKING, WIRED**

- `scoring.py:score_belief()` combines:
  - `decay_factor()` -- content-type-aware exponential decay with half-lives from Exp 58c
  - `lock_boost_typed()` -- relevance-aware boost for locked beliefs
  - `thompson_sample()` -- Beta distribution sampling for exploration
- Called by `retrieval.py:retrieve()` at line 158: `scores[belief.id] = score_belief(belief, query_stripped, current_time)`
- Results sorted by score before packing

**Connected end-to-end:** Yes

**Dead code in this module:**
- `retrieval_frequency_boost()` -- defined but never called by `score_belief()` or `retrieve()`
- `recency_boost()` -- defined but never called
- `core_score()` -- defined, used only by `/mem:core` skill (not the pipeline)
- `uncertainty_score()` -- defined but never called in the pipeline

---

### Stage 8: Type-Aware Compression

**Status: WORKING, WIRED**

- `compression.py:compress_belief()` applies type-aware text compression
- `pack_beliefs()` fits beliefs into token budget
- Both called by `retrieval.py:retrieve()` at lines 164-170
- Types handled: full text (factual, requirement, correction, preference), first sentence (causal, relational), first sentence + key terms (procedural)
- **Upstream:** Scored candidates from stage 7
- **Downstream:** Packed belief list returned as `RetrievalResult`

**Connected end-to-end:** Yes

---

### Stage 9: Context Injection (hooks)

**Status: WORKING, WIRED**

- `agentmemory-inject.sh` is installed and wired in `settings.json` under `SessionStart`
- Reads SQLite directly (no MCP server dependency) for fast startup (~120ms)
- Injects locked beliefs (top 20) + core beliefs (top 10 by type/source weight)
- Uses `hookSpecificOutput.additionalContext` to inject into Claude's context

**Also available but NOT WIRED:**
- `agentmemory-autosearch.sh` -- FTS5 search on every user prompt. File exists at `~/.claude/hooks/` but is NOT in `settings.json` UserPromptSubmit hooks.

**Connected end-to-end:** Yes for SessionStart. UserPromptSubmit auto-search is orphaned.

---

### Stage 10: Correction Detection

**Status: WORKING, WIRED**

- `correction_detection.py:detect_correction()` -- zero-LLM, 92% accuracy
- Called by `ingest.py:ingest_turn()` at line 121 for user turns
- Called by `classification.py:classify_sentences_offline()` for per-sentence classification
- Corrections create locked beliefs with alpha=9.0, beta=1.0
- Corrections trigger `store.supersede_belief()` to replace old beliefs
- Also available via `server.py:correct()` MCP tool for explicit corrections
- **Upstream:** Raw user text from MCP `ingest` or `correct` tool
- **Downstream:** Locked beliefs in store, SUPERSEDES edges

**Connected end-to-end:** Yes

---

### Stage 11: Feedback Loop

**Status: INFRASTRUCTURE EXISTS, NOT WIRED**

- `store.py:record_test_result()` exists -- records outcome and calls `update_confidence()`
- `update_confidence()` implements Bayesian update: 'used' increments alpha, 'harmful' increments beta
- `scoring.py:thompson_sample()` is used in `score_belief()` -- provides exploration
- `scoring.py:retrieval_frequency_boost()` exists but is never called
- `store.py:get_retrieval_stats()` exists but is never called from the pipeline

**What's missing:** Nothing in the pipeline records test results. No hook or tool detects whether a retrieved belief was used, ignored, or harmful. The `record_test_result()` method is never called from `server.py` or any hook. The feedback loop has storage + scoring infrastructure but no data collection mechanism.

**Connected end-to-end:** No. Dead infrastructure.

---

### Stage 12: Triggered Beliefs (Meta-Cognitive)

**Status: NOT IMPLEMENTED**

- No code in `src/agentmemory/` implements triggered beliefs
- No hook, tool, or function implements meta-cognitive checks
- No "TB-" prefixed beliefs or triggered belief detection logic exists
- Exp 51 simulated 15 TBs in a standalone experiment script, not in the pipeline

**Connected end-to-end:** No

---

### Stage 13: Output Gating

**Status: NOT IMPLEMENTED**

- No code in `src/agentmemory/` implements output gating
- No hook blocks or rewrites violating output
- Exp 49 validated the concept in a standalone experiment
- The `PreToolUse` hooks in `settings.json` for `Bash` include `agentmemory commit-check` but this is a commit guard, not output gating

**Connected end-to-end:** No

---

## Data Flow Diagram: What's Actually Wired

```
WIRED (data flows end-to-end):
================================

[Claude Code hooks]
       |
       v
[conversation-logger.sh] ---> ~/.claude/conversation-logs/turns.jsonl (DEAD END)
       |
       | (separate path, not connected to JSONL)
       v
[MCP ingest tool] or [MCP correct/remember/observe tools]
       |
       v
[ingest_turn()]
  |-- extract_sentences()          ... Stage 2
  |-- detect_correction()          ... Stage 10
  |-- classify_sentences_offline() ... Stage 3 (offline only)
  |-- type-to-prior mapping        ... Stage 4
  |-- store.insert_belief()        ... Stage 5
  |     |-- FTS5 search_index
  |     |-- evidence links
  |     '-- content-hash dedup
  '-- store.supersede_belief()     ... Stage 10 (SUPERSEDES edges)
       |
       v
[MCP search tool]
       |
       v
[retrieve()]
  |-- store.get_locked_beliefs()   ... L0
  |-- store.search() via FTS5      ... Stage 6
  |-- HRR graph expansion          ... Stage 6
  |-- score_belief()               ... Stage 7
  |     |-- decay_factor()
  |     |-- lock_boost_typed()
  |     '-- thompson_sample()
  |-- pack_beliefs()               ... Stage 8
  '-- compress_belief()            ... Stage 8
       |
       v
[agentmemory-inject.sh] ---> SessionStart context injection ... Stage 9
  (reads SQLite directly, bypasses MCP for speed)


NOT WIRED (exists but disconnected):
=====================================

[agentmemory-autosearch.sh]  -- file exists, not in settings.json
[agentmemory-ingest-stop.sh] -- file exists, not in settings.json
[ingest_jsonl()]             -- function exists, never called by any tool/hook
[classify_sentences() LLM]   -- function exists, server always uses offline
[record_test_result()]       -- method exists, never called (feedback loop dead)
[retrieval_frequency_boost()] -- function exists, never called
[recency_boost()]            -- function exists, never called
[uncertainty_score()]        -- function exists, never called
[get_retrieval_stats()]      -- method exists, never called from pipeline
[Triggered beliefs]          -- no code exists
[Output gating]              -- no code exists
```

---

## Dead Code Inventory

| Location | Function/File | Purpose | Why Dead |
|---|---|---|---|
| `scoring.py` | `retrieval_frequency_boost()` | Boost beliefs by usage track record | Never called by `score_belief()` or `retrieve()` |
| `scoring.py` | `recency_boost()` | Boost newly created beliefs | Never called by `score_belief()` or `retrieve()` |
| `scoring.py` | `uncertainty_score()` | Measure belief uncertainty | Never called anywhere in pipeline |
| `store.py` | `record_test_result()` | Record retrieval outcomes | Never called from server.py or hooks |
| `store.py` | `get_retrieval_stats()` | Get belief usage statistics | Never called from pipeline |
| `ingest.py` | `ingest_jsonl()` | Batch process JSONL turns | No tool or hook calls it |
| `classification.py` | `classify_sentences()` (LLM) | Haiku-based classification | Server always passes `use_llm=False` |
| `hooks/` | `agentmemory-autosearch.sh` | Auto-search on user prompt | Not wired in settings.json |
| `hooks/` | `agentmemory-ingest-stop.sh` | Auto-ingest on session stop | Not wired in settings.json |

---

## Missing Links (Gaps Where Data Does Not Flow)

1. **JSONL -> Pipeline:** `conversation-logger.sh` writes JSONL but nothing reads it automatically. `ingest_jsonl()` exists but is not exposed as an MCP tool or triggered by any hook.

2. **LLM classification disabled:** Server hardcodes `use_llm=False`. The 99% accuracy LLM path is available but dormant. Users get the 36% accuracy offline classifier.

3. **Feedback loop has no data source:** `record_test_result()` and `update_confidence()` exist in the store. `thompson_sample()` uses the alpha/beta parameters. But nothing detects or records whether a retrieved belief was used, ignored, or harmful. The loop is open.

4. **Auto-search on prompt not wired:** `agentmemory-autosearch.sh` would inject relevant beliefs per-prompt (not just at session start). The file is ready but not in settings.json.

5. **Auto-ingest on stop not wired:** `agentmemory-ingest-stop.sh` would feed conversation text into the pipeline when a session ends. Not in settings.json.

6. **Triggered beliefs:** No code. 15 TBs were designed in Exp 51 but none are implemented.

7. **Output gating:** No code. Exp 49 validated the concept but nothing blocks or rewrites violating output.

---

## Overall Assessment

| Category | Count | Stages |
|---|---|---|
| Fully wired end-to-end | 8 | 2, 3 (offline), 4, 5, 6, 7, 8, 10 |
| Working but partially disconnected | 2 | 1 (JSONL accumulates, not consumed), 9 (SessionStart works, per-prompt search not wired) |
| Infrastructure exists, not wired | 1 | 11 (feedback loop) |
| Not implemented | 2 | 12 (triggered beliefs), 13 (output gating) |

**Functional end-to-end percentage: 8 of 13 stages = 62%**

The core ingest-store-retrieve-inject loop works. What you have is a functional memory system for storing and retrieving beliefs with Bayesian scoring, FTS5 search, HRR expansion, type-aware compression, and locked belief injection. What you do not have is the closed feedback loop, meta-cognitive checks, or output gating. The PIPELINE_STATUS.md assessment that stage 5 is "NOT BUILT" is stale -- it is built and working.

**Highest-leverage fixes (effort vs impact):**

1. Wire `agentmemory-autosearch.sh` into settings.json UserPromptSubmit (5 min, big UX impact)
2. Wire `agentmemory-ingest-stop.sh` into settings.json Stop hooks (5 min, auto-captures sessions)
3. Add `ingest_jsonl` as MCP tool or wire into a hook (15 min, unlocks batch backfill)
4. Add `use_llm` parameter to the `ingest` MCP tool so LLM classification is opt-in (10 min, 99% vs 36% accuracy)
5. Add `recency_boost` to `score_belief()` (5 min, fixes Exp 63 finding about new beliefs)
