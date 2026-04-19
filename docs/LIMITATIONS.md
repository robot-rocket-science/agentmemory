# Known Limitations

[prev: Benchmark Results](BENCHMARK_RESULTS.md)

This document lists every known limitation, failure mode, and boundary condition of agentmemory. Per REQ-016, no known limitation should be undocumented at ship time.

Last updated: 2026-04-18

---

## Retrieval

### Vocabulary mismatch (semantic gap)

FTS5 keyword search cannot retrieve beliefs when the query uses different vocabulary than the stored belief. Example: querying "database choice" will not find a belief containing "PostgreSQL" if neither term appears in the other.

**Impact:** Beliefs are 100% retrievable when queries share vocabulary with stored content. Fails on semantic-gap queries.

**Mitigation:** HRR vocabulary bridge covers 100% of gaps in tested corpus (Exp 53). Entity-aware Layer 2 expansion helps. But gaps in untested vocabulary remain possible.

**Evidence:** REQ-001 validation (2026-04-18, 10-decision cross-session test).

### Negation noise in corrections

FTS5 treats "not" as a content word. In a belief store with many corrections (which structurally contain negation), any query with a negation word gets flooded with correction beliefs that share the negation word but not the topic.

**Impact:** In 4 of 6 counterfactual scenarios tested (CS-032), negation noise was the primary reason search failed. Topical results can be buried at ranks 30-50.

**Mitigation:** Retrieval pipeline includes a negation noise filter that deprioritizes negation-only matches. Topical matches outrank negation-only matches (validated in test_cs032). Not fully solved at scale.

**Evidence:** CS-032, test_cs032_negation_noise.py.

### Cold start

The first session on any new topic has no beliefs to reason over. The system cannot help until the belief store has been populated.

**Impact:** The session that most needs help is the one that produces all the helpful beliefs. This is an inherent bootstrapping problem.

**Mitigation:** `/mem:onboard` populates initial beliefs from project structure. Live conversation capture begins immediately.

**Evidence:** CS-033.

### Token budget ceiling

Retrieval packs beliefs into a fixed 2,000-token budget. At scale (15,000+ beliefs), this means the vast majority of beliefs are never surfaced for any given query.

**Impact:** Important but low-scoring beliefs may be excluded. Locked beliefs and high-confidence corrections consume budget first.

**Mitigation:** Type-aware compression saves ~55% of tokens (Exp 42). Budget is configurable via the `budget` parameter.

**Evidence:** Exp 42 (compression), Exp 55 (rate-distortion optimization showed no improvement over fixed heuristic).

---

## Contradiction Detection

### Negation divergence requirement

The zero-LLM contradiction detector requires one belief to contain negation words and the other not to. When both beliefs contain negation with opposing meaning, it detects SUPPORTS instead of CONTRADICTS.

**Impact:** Contradictions phrased as "X is fixed" vs "X is not fixed" are detected. Contradictions phrased as "X is no longer broken" vs "X is not yet working" may be missed (both contain negation).

**Mitigation:** None currently. Would require semantic understanding beyond keyword patterns.

**Evidence:** CS-029 test development (test_cs029_partial_fix.py).

### Jaccard similarity threshold

Contradiction detection requires Jaccard similarity >= 0.3 on significant terms. Beliefs about the same topic with very different vocabulary will not be detected as contradictions.

**Impact:** Paraphrased contradictions are missed.

**Mitigation:** None currently. HRR bridging does not feed into contradiction detection.

**Evidence:** Relationship detector implementation (relationship_detector.py).

---

## Confidence and Scoring

### Locked beliefs are immutable to feedback

Locked beliefs fully resist confidence drops from "ignored" feedback. This is by design (locked = non-negotiable), but means a locked belief that is genuinely wrong will not self-correct through the feedback loop.

**Impact:** If a locked belief is incorrect, it requires explicit user intervention (`/mem:unlock` or `/mem:correct`) to fix.

**Mitigation:** Evidence threshold policy: locked beliefs resist casual noise but are not immune to evidence when multiple independent signals converge.

**Evidence:** CS-028, test_cs028_correction_ignored.py.

### Bayesian calibration at small scale only

ECE of 0.066 was measured on simulated data (Exp 5b). Real-world calibration has not been independently validated.

**Impact:** Confidence scores may not reflect true retrieval utility at production scale.

**Mitigation:** Feedback loop (+22% MRR, Exp 66) provides real-world calibration over time.

**Evidence:** Exp 5b (simulated), Exp 66 (feedback loop MRR improvement).

---

## Classification

### Correction detection accuracy

Correction detection operates at 92% accuracy (zero-LLM, Exp 1 V2). This was measured on project-a project data, not an external benchmark. Accuracy may vary on other projects.

**Impact:** ~8% of corrections may be misclassified.

**Mitigation:** LLM classification at 99% accuracy (Haiku, Exp 47/50) is available as a higher-accuracy path.

**Evidence:** Exp 1 V2 (correction detection), Exp 47/50 (LLM classification).

### Per-session LLM cost estimate

The ~$0.005/session cost for LLM classification is an internal estimate based on typical session sizes. Not independently audited.

**Impact:** Actual cost depends on session length and belief count.

**Evidence:** Code-level estimate in classification.py.

---

## Platform and Environment

### Claude Code only for hooks

Full behavioral enforcement (SessionStart, UserPromptSubmit, Stop, PreCompact, PostCompact hooks) requires Claude Code. Other MCP clients can use the tools but do not get automatic context injection.

**Impact:** The "zero-configuration" experience (automatic search on every prompt, session-start context loading) is Claude Code only.

**Mitigation:** Other clients can call `search()` and `get_locked()` explicitly.

### Onboarding time varies

Documentation states "10-30 seconds" for onboarding. Actual time depends on project size, git history depth, and disk speed. Large monorepos may take longer.

**Impact:** User expectation mismatch on large projects.

**Evidence:** No systematic timing benchmark exists.

### Single-user design

agentmemory assumes a single user per project database. Multi-user scenarios (shared project, multiple developers) are not designed for or tested.

**Impact:** No access control, no per-user belief scoping, no conflict resolution between users.

---

## Cross-Model

### Not validated on non-Claude models

All testing uses Claude (Opus and Haiku). The MCP interface is model-agnostic, but retrieval quality, correction detection accuracy, and behavioral enforcement have not been validated on ChatGPT, Gemini, or other models.

**Impact:** REQ-011 (cross-model benchmarking) remains unvalidated.

**Evidence:** Blocked on ChatGPT/Gemini MCP client availability.

---

## Benchmark Caveats

### Single evaluator

All benchmarks were run by one person (the author) with Claude as the evaluation model. No independent replication has been performed.

### Score variance

Opus-as-judge scoring introduces variance. The LongMemEval score (59.0%) has a stated judge-agreement rate that should be consulted for confidence intervals.

### Contamination risk

While contamination protocols are in place (verify_clean.py, separate GT files), the benchmarks were adapted to agentmemory's interface. Adapter code may introduce subtle biases not present in the original benchmark implementations.

See [Benchmark Results](BENCHMARK_RESULTS.md) for full methodology disclosure.
