# Ongoing Memory Maintenance: What Changes After Onboarding

**Date:** 2026-04-11
**Type:** Architecture analysis with concrete recommendations

---

## 1. The Post-Onboarding Problem

After LLM onboarding, the memory system has ~15k beliefs at confidence 0.9. This is a snapshot. The project keeps moving: new code, new decisions, old beliefs becoming stale. Three things must happen continuously:

1. **New knowledge enters** the graph (from conversation turns)
2. **Stale knowledge decays** or gets superseded
3. **Confidence calibrates** based on whether beliefs are actually useful

Currently, only #1 partially works. #2 has infrastructure (decay scoring, supersede mechanics) but no automatic staleness detection. #3 has the Bayesian update machinery but the feedback loop is open.

---

## 2. Is HRR Enough Without More LLM Calls?

**No.** HRR solves one problem (vocabulary gap in retrieval) but does not solve the ongoing maintenance problems.

### What HRR does

HRR bridges structural connections: if FTS5 finds belief A, and belief A has a SUPERSEDES edge to belief B, HRR can surface B even if the query keywords don't match B's text. This is purely a retrieval enhancement. It uses zero LLM calls and adds value proportional to the number of edges in the graph.

### What HRR does NOT do

- Classify new conversation turns (is this a decision? a correction? ephemeral?)
- Detect when existing beliefs contradict new information
- Create new edges between new beliefs and old ones
- Determine if a stale factual belief should be superseded

### The quality cliff problem

**This is real, but the severity is lower than stated in the task context.** Here is why:

The PIPELINE_AUDIT claimed the `ingest` MCP tool always uses offline classification (36% accuracy). That is wrong for the current code. The `ingest()` tool in `server.py` (line 501) reads `use_llm` from `config.py:get_bool_setting("ingest", "use_llm")`. The default in `_DEFAULTS` is `True`. The user's `~/.agentmemory/config.json` does NOT override this setting.

**So the live `ingest` tool uses Haiku classification (99% accuracy) as long as ANTHROPIC_API_KEY is set.**

Only the `onboard()` tool hardcodes `use_llm=False` (line 441), which makes sense for bulk ingestion where cost matters (15k nodes x Haiku calls would be expensive).

**The quality cliff exists but only between:**
- Onboarded beliefs: offline classifier, 36% accuracy, all at confidence 0.9 (a flat prior chosen for bulk)
- Conversation-ingested beliefs: Haiku classifier, 99% accuracy, type-appropriate priors

This is actually the *right* direction: new beliefs from live conversation are higher quality than bulk-onboarded ones. The risk would be the opposite: if new beliefs were lower quality, they'd pollute the graph. That is not happening.

**Remaining concern:** the onboarded beliefs at flat 0.9 confidence are over-confident given their 36% classification accuracy. They need the feedback loop to calibrate downward over time, but the feedback loop is open (see section 3).

---

## 3. What Monitoring Mechanisms Exist vs What's Missing

### EXISTS and WIRED

| Mechanism | What it does | Limitation |
|---|---|---|
| Session metrics (server.py) | Tracks retrieval_tokens, classification_tokens, beliefs_created, corrections_detected, searches_performed per session | Per-session only; no cross-session aggregation dashboard |
| Temporal decay (scoring.py) | Factual beliefs decay with 14-day half-life; locked beliefs never decay | Works automatically in scoring; no staleness alerting |
| Supersession (store.py) | Correction detection supersedes old beliefs | Only triggered by explicit corrections, not by implicit contradiction |
| Content-hash dedup (store.py) | Prevents duplicate beliefs on re-ingestion | Works for exact duplicates; near-duplicates still accumulate |

### EXISTS but NOT WIRED

| Mechanism | File | Gap |
|---|---|---|
| Auto-feedback (server.py lines 82-150) | `_process_auto_feedback()` | Called by `search()` -- this IS wired. Key-term overlap with min_unique=2 infers used/ignored. Auto-feedback fires when the *next* search happens after an ingest. |
| Explicit feedback tool (server.py lines 533-579) | `feedback()` MCP tool | Available but requires Claude to explicitly call it. Nothing prompts Claude to do so. |
| record_test_result (store.py) | Called by auto-feedback and explicit feedback | Both paths now exist (auto-feedback was added after the PIPELINE_AUDIT). |
| thompson_sample (scoring.py) | Used in score_belief() | Working -- provides exploration via Beta sampling |
| retrieval_frequency_boost (scoring.py) | Defined but never called | Dead code. Would boost beliefs with good track records. |
| recency_boost (scoring.py) | Defined but never called | Dead code. Would help new beliefs compete with established ones. |

### DOES NOT EXIST

| Need | Description | Impact |
|---|---|---|
| Confidence distribution drift monitoring | Track how the overall confidence distribution changes session-over-session | Without this, cannot detect the 15k-beliefs-at-0.9 problem quantitatively |
| Signal-to-noise ratio tracking | Ratio of PERSIST-classified sentences to total sentences per session | Would reveal if the classifier is over-persisting or under-persisting |
| Stale belief detection | Beliefs not retrieved in N sessions despite relevant queries | Would identify beliefs that should decay faster or be pruned |
| Cross-session aggregation | Dashboard or status tool showing belief health over time | status() only shows counts, not trends |
| Near-duplicate detection | Beliefs with high semantic overlap but different IDs | Onboarding likely created many near-duplicates |

---

## 4. What Hooks Should Be Wired

### Current hook state

| Hook file | settings.json status | Purpose |
|---|---|---|
| `agentmemory-inject.sh` | WIRED (SessionStart) | Injects locked + core beliefs at session start |
| `conversation-logger.sh` | WIRED (UserPromptSubmit, Stop, PreCompact, PostCompact) | Writes JSONL turns; triggers ingestion on compaction |
| `agentmemory-autosearch.sh` | NOT WIRED | FTS5 search on every user prompt, injects matching beliefs |
| `agentmemory-ingest-stop.sh` | NOT WIRED | Ingests conversation text at session end |

### Recommendations

**Wire NOW:**

1. **`agentmemory-autosearch.sh` into UserPromptSubmit** -- This is the highest-leverage unwired hook. Currently, memory context only enters at session start (locked + top-10 core beliefs). Mid-session, the agent only gets memory context when it explicitly calls the `search` MCP tool. Auto-search would inject relevant beliefs per-prompt, making the memory system proactive instead of reactive. The script already exists and handles edge cases (short prompts, slash commands). Estimated 120-200ms latency per prompt.

   **Risk:** Adds latency to every prompt. May inject irrelevant beliefs for simple commands. The script already handles this (skips prompts < 15 chars, skips slash commands).

2. **`agentmemory-ingest-stop.sh` into Stop** -- Currently, conversation turns only enter the memory system when Claude explicitly calls `ingest()`. If Claude forgets (or the session crashes), the conversation is lost to memory. The ingest-stop hook captures the final conversation text and runs ingestion in the background.

   **Concern:** The current ingest-stop.sh is crude -- it calls `agentmemory remember` (which creates a single locked belief) instead of routing through the full `ingest_turn()` pipeline. It should be rewritten to call `agentmemory ingest` or use the JSONL path.

**Wire LATER (after validation):**

3. **JSONL auto-ingestion** -- `conversation-logger.sh` already triggers ingestion on compaction (line 67-69: `agentmemory ingest "$LATEST_ARCHIVE"`) but only if the `agentmemory` CLI command exists. The CLI integration needs verification. Also, `ingest_jsonl()` exists but is not exposed as an MCP tool.

---

## 5. When Should Re-Onboarding Happen?

### What ONBOARDING_RESEARCH.md says

Section 2.3 states "Progressive, Not Batch" -- onboarding should run incrementally each session (new commits since last scan, changed files). Section 6.3 says detect large restructures (>30% of files changed) and trigger full re-onboarding.

Section 8.3 flags this as an open question: "Threshold for 'major restructure' that triggers full re-onboarding. Too low = wasteful re-indexing. Too high = stale graph after refactors. Need empirical calibration."

### Practical triggers

| Trigger | Action | Implementation |
|---|---|---|
| New session start | Check for new commits since last onboard timestamp | Add to SessionStart hook (or inject.sh) |
| >30% of tracked files changed | Full re-onboard | Needs file-change tracking in store |
| Major refactor (directory renames, large deletions) | Full re-onboard | Detect via git diff --stat |
| N commits since last onboard (N~50?) | Incremental re-onboard | Track last-onboard commit hash in store |
| User says "re-onboard" | Full re-onboard | Already works via `/mem:onboard` |

### What is NOT implemented

None of the automatic triggers are implemented. Re-onboarding is manual only (`/mem:onboard` or the `onboard` MCP tool). The incremental onboarding described in ONBOARDING_RESEARCH.md section 2.3 does not exist in code -- every onboard call is a full scan.

---

## 6. The Auto-Feedback Loop: Closer Than It Looks

The PIPELINE_AUDIT (written before the latest server.py changes) said the feedback loop was dead infrastructure. That is no longer accurate.

**What's actually wired now:**

1. `search()` populates `_retrieval_buffer` with belief IDs (line 247-248)
2. `ingest()` populates `_ingest_buffer` with ingested text (line 508)
3. The NEXT call to `search()` triggers `_process_auto_feedback()` (line 230)
4. Auto-feedback compares key terms from retrieved beliefs against ingested text
5. Beliefs with >= 2 matching key terms get outcome "used"; others get "ignored"
6. `record_test_result()` is called, which calls `update_confidence()`
7. Confidence updates flow into future scoring via `thompson_sample()`

**The loop is closed, but narrow:** it only fires when search-then-ingest-then-search happens in sequence within a single session. If a session ends after a search without another search, the buffer is lost. Cross-session feedback does not happen.

**What's still missing:**
- The `feedback()` MCP tool exists but nothing prompts Claude to call it
- No hook triggers feedback collection at session end
- Auto-feedback only works for beliefs retrieved by `search()`, not beliefs injected by `agentmemory-inject.sh`

---

## 7. Concrete Recommendations

### Wire NOW (< 30 minutes total)

1. **Add `agentmemory-autosearch.sh` to settings.json UserPromptSubmit** (5 min)
   - Add after the conversation-logger entry
   - Gives proactive memory context on every prompt

2. **Rewrite and wire `agentmemory-ingest-stop.sh`** (15 min)
   - Replace `agentmemory remember` with proper `ingest` call
   - Wire into settings.json Stop hooks
   - Ensures conversation turns enter the graph even if Claude doesn't call `ingest()`

3. **Add `recency_boost` to `score_belief()` in scoring.py** (5 min)
   - New conversation-derived beliefs need a way to compete with the 15k onboarded beliefs at 0.9
   - Recency boost helps new beliefs surface

4. **Flush auto-feedback buffer at session end** (10 min)
   - Add a `_flush_feedback()` call in a Stop hook or as part of session cleanup
   - Prevents losing in-flight feedback when sessions end

### Wire NEXT WEEK (after the above is validated)

5. **Expose `ingest_jsonl` as MCP tool** -- allows batch backfill of conversation logs
6. **Add incremental onboarding** -- detect new commits since last onboard, scan only those
7. **Confidence distribution monitoring** -- add a `/mem:health` diagnostic that reports confidence histogram, staleness metrics, near-duplicate count
8. **Session-end feedback prompt** -- hook that injects "rate the beliefs you used this session" as a context hint before session close

### Wire LATER (Phase 3)

9. **Stale belief detection** -- background job that checks beliefs not retrieved in N sessions
10. **Near-duplicate pruning** -- post-onboarding cleanup pass using content similarity
11. **Triggered beliefs** -- meta-cognitive checks (the 15 TBs from Exp 51)
12. **Output gating** -- block violating output based on locked beliefs

---

## 8. Summary

The post-onboarding maintenance story is better than the PIPELINE_AUDIT suggested:

- **LLM classification IS active** for live `ingest()` calls (Haiku, 99% accuracy). The quality cliff between onboarded and live beliefs goes in the right direction (live > onboarded).
- **Auto-feedback IS wired** within sessions (search -> ingest -> search cycle). The Bayesian update loop is closed for this specific pattern.
- **HRR is not enough alone** -- it improves retrieval but does not handle classification, staleness, or confidence calibration.
- **Two hooks are ready to wire** (autosearch, ingest-stop) that would significantly improve ongoing maintenance with minimal effort.
- **Incremental onboarding does not exist** -- every onboard is a full scan. Automatic re-onboarding triggers are not implemented.
- **Cross-session feedback does not exist** -- the auto-feedback buffer is lost when the session ends.

The biggest gap is not any single missing feature but the lack of cross-session maintenance. Within a session, the system works. Across sessions, beliefs just accumulate at their initial confidence until someone runs a correction or re-onboard.
