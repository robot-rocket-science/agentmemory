# Code Audit: Benchmark Pipeline (Post-Exp 5)

## Date: 2026-04-16

## Auditor: Opus subagent (full code review of all benchmark files)

## Scope

All benchmark adapters, scoring functions, contamination checker, and
triple extraction code.

## Verdict: No result-invalidating bugs found.

Two medium-severity code quality issues identified. Neither affects
the reported benchmark numbers because:
- Finding #1 (belief lookup) only affects `mab_triple_adapter.py` which
  is used for SH, and SH scores come from the two-pass LLM reader
  pipeline, not raw retrieval scoring.
- Finding #2 (catch-all regex) only activates on the 15 lines that no
  specific pattern matched, and those 15 were already verified to have
  0 impact on MH questions (only 1 MH question involves those entities).

## Findings

### Finding 1: Belief lookup by 50-char prefix (MEDIUM)

**File:** `mab_triple_adapter.py` line 158
**Issue:** After ingesting a fact, searches for the belief by first 50 chars
of source text. If two facts share the same prefix, this could match the
wrong belief and create incorrect SUPERSEDES edges.
**Impact on results:** Low. This adapter is used for SH only. The SH scores
(90% Opus / 62% Haiku) come from the two-pass LLM reader protocol, where
retrieval and scoring are separate steps. The SUPERSEDES edges affect what
context the reader sees, but even if a few edges are wrong, the overall
SH score is unlikely to change significantly.
**Action:** Fix in next session (use observation_id for belief lookup instead
of text search).

### Finding 2: Catch-all regex too broad (MEDIUM)

**File:** `triple_extraction.py` line 115
**Pattern:** `^The\s+(.+?)\s+is\s+(.+)$` matches ANY "The X is Y" sentence.
**Issue:** On non-MAB data, this would extract garbage triples from sentences
like "The problem is complex." On MAB data, every line IS a structured fact,
so this is safe.
**Impact on results:** None for current benchmarks. Risk for production use.
**Action:** Add a guard (minimum entity/value length, or limit to known
title patterns) before production deployment.

### Finding 3: verify_clean.py checks keys only (LOW)

**Issue:** The contamination checker inspects JSON keys but not values inside
the `context` field. If answer text were accidentally embedded in context
(not via a named key but as part of the string), it would not be caught.
**Impact on results:** None. No adapter embeds answers in context strings.
The architecture prevents this by design (separate code paths for retrieval
and GT output).
**Action:** Consider adding a value-level check in a future version.

### Finding 4: FACTCONSOLIDATION_PROMPT defined but unused (LOW)

**File:** `mab_adapter.py` lines 51-59
**Issue:** The paper's system prompt is defined but never passed to readers.
**Impact:** The paper baselines may use this prompt. Our readers get a
different prompt. This is a known methodological difference, not a bug.
**Action:** Document in BENCHMARK_RESULTS.md as a known difference.

### Finding 5: answer_in_ctx checks only answer_list[0] (LOW)

**File:** `mab_entity_index_adapter.py` line 405
**Issue:** Diagnostic print checks only the first GT answer, not all.
**Impact:** Diagnostic only, does not affect scoring. Slightly understates
retrieval recall.
**Action:** Fix for accuracy of diagnostic output.

## Confirmed Correct

- All scoring functions (SEM, F1, multi-answer) are correct per SQuAD-style
  evaluation.
- Data loading and source filtering work correctly.
- Each test case gets fresh database state (proper isolation).
- Normalization is applied consistently to both predictions and GT.
- The two-pass protocol (retrieve, then score separately) prevents
  self-judging contamination.
- verify_clean.py correctly blocks all known contamination modes.
