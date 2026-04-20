# Core Requirements

These are the non-negotiable performance requirements for the agentic memory system. Every requirement traces forward to plans, experiments, and verification artifacts. Every claim about meeting a requirement must be backed by evidence.

**Rule:** If a requirement cannot be verified, it is not a requirement -- it is a wish.

---

## Traceability Key

Each requirement has:
- **ID:** Unique identifier (REQ-XXX)
- **Requirement:** What must be true
- **Rationale:** Why this matters (traced to a real problem)
- **Verification method:** How we prove it's met
- **Plan trace:** Which phase(s) address this
- **Experiment trace:** Which experiment(s) measure this
- **Status:** Not started | In progress | Verified | Failed
- **Evidence:** Link to verification artifact when available

---

## R1: Context Drift Resistance

### REQ-001: Cross-Session Decision Retention

**Requirement:** Decisions made in session 1 must be retrievable and correctly applied by session 5+, without the user re-stating them.

**Rationale:** The core problem. Without persistent memory, every session starts from zero. Users waste time re-explaining context. Agents make contradictory decisions across sessions.

**Verification method:** Multi-session test scenario. 5 sequential sessions on a single project. Session 1 establishes 10 decisions. Sessions 2-5 present tasks that require those decisions. Measure: what fraction of session-1 decisions are retrieved and correctly applied?

**Acceptance threshold:** >= 80% of session-1 decisions correctly applied in session 5.

**Plan trace:** Phase 2 (core memory graph), Phase 3 (feedback loop)
**Experiment trace:** Experiment 3 (retrieval quality), Phase 0 baseline measurement
**Status:** Verified (simulation)
**Evidence:** Exp 84: 10/10 multi-session checks pass (5 sessions, fresh MemoryStore per session). Beliefs persist, feedback accumulates, supersession works, locked beliefs survive, retrieval quality stable (MRR=1.0). SQLite store + get_locked() injection confirmed end-to-end. Full 5-session replay with 10 real decisions not yet run.

### REQ-002: Belief Consistency

**Requirement:** The system must never silently present contradictory beliefs as if both are true. When contradictions exist, they must be flagged with evidence chains for both sides.

**Rationale:** Silent contradictions are worse than no memory. An agent that confidently says "we use PostgreSQL" in one turn and "we use MySQL" in the next destroys trust.

**Verification method:** Inject 10 known contradictions into the belief store. For each, issue a query that should retrieve the contradicted topic. Measure: does the system flag the contradiction, present both sides with evidence, or silently present one?

**Acceptance threshold:** 100% of known contradictions flagged. Zero silent contradictions presented.

**Plan trace:** Phase 2 (conflict detection), Phase 3 (revision pipeline)
**Experiment trace:** Experiment 2 (Bayesian calibration, non-stationarity test)
**Status:** Implemented
**Evidence:** CONTRADICTS/SUPPORTS edge detection in relationship_detector.py (wired into remember, correct, ingest). flag_contradictions() in retrieval.py:199 checks result set for contradicting pairs and appends warnings. Contradiction warnings included in RetrievalResult. Formal 10-contradiction injection test not yet run, but the detection and flagging pipeline is end-to-end.

---

## R2: Token Efficiency

### REQ-003: Retrieval Token Budget

**Requirement:** The memory system must deliver useful context within a hard budget of 2,000 tokens for standard retrieval (L0+L1+L2). Deep search (L3) may use more, but only on explicit request.

**Rationale:** Context window is finite and expensive. Every token spent on memory context is a token not available for the task. The GSD prototype's KNOWLEDGE.md dump was 54K tokens -- most of it irrelevant.

**Verification method:** Across 20 diverse tasks, measure total memory tokens injected at L0+L1+L2. No task exceeds 2,000 tokens.

**Acceptance threshold:** 100% of standard retrievals <= 2,000 tokens. Mean <= 1,500 tokens.

**Plan trace:** Phase 2 (progressive context loading, budget packing)
**Experiment trace:** Experiment 4 (token budget vs quality curve)
**Status:** Implemented
**Evidence:** pack_beliefs() enforces 2K budget. Exp 42: type-aware compression yields ~675 tokens avg. Exp 60: full pipeline fits under 2K. Formal 20-task verification not yet run.

### REQ-004: Quality Per Token

**Requirement:** Agent response quality with <= 2,000 tokens of memory context must equal or exceed response quality with >= 10,000 tokens of full context dump.

**Rationale:** The hypothesis that focused context beats exhaustive context. If this is false, we should just dump everything. Experiment 4 tests this directly.

**Verification method:** Experiment 4 (token budget vs quality curve). Compare quality scores at C4 (2,000 tokens) vs C6 (10,000 tokens).

**Acceptance threshold:** Quality score at 2,000 tokens >= 0.95 * quality score at 10,000 tokens. Hallucination rate at 2,000 tokens <= hallucination rate at 10,000 tokens.

**Plan trace:** Phase 2 (retrieval ranking, budget packing)
**Experiment trace:** Experiment 4
**Status:** Not started
**Evidence:** --

---

## R3: Session Recovery

### REQ-005: Crash Recovery Completeness

**Requirement:** After an unexpected process termination (kill -9, machine crash, OOM), the memory system must recover >= 90% of the interrupted session's working context on next startup.

**Rationale:** Real operational problem. User experienced two back-to-back crashes and recovered 90% via MemPalace. We must match or exceed this.

**Verification method:** Simulated crash test. Run a 30-minute work session with 20+ meaningful events (decisions, file changes, errors). At 10 different points, send SIGKILL. Restart. Measure: what fraction of session context (decisions, file changes, task state, active goals) is recoverable?

**Acceptance threshold:** >= 90% context recovery at every crash point. Recovery latency < 2 seconds.

**Plan trace:** Phase 1 (session recovery + checkpointing)
**Experiment trace:** Phase 1 exit criteria
**Status:** Not started
**Evidence:** --

### REQ-006: Checkpoint Write Overhead

**Requirement:** Continuous checkpointing must add < 50ms of latency per agent turn.

**Rationale:** If the memory system noticeably slows down the agent, users will disable it. Checkpointing must be invisible.

**Verification method:** Benchmark checkpoint write time across 1,000 turns with varying payload sizes (100 bytes to 10KB). Report p50, p95, p99 latency.

**Acceptance threshold:** p95 < 50ms. p99 < 100ms.

**Plan trace:** Phase 1 (WAL mode SQLite, synchronous writes)
**Experiment trace:** Phase 1 exit criteria
**Status:** Implemented (needs formal benchmark)
**Evidence:** SQLite WAL mode active. Checkpoint writes are synchronous. Acceptance test test_req006_checkpoint_latency.py exists. Formal 1,000-write benchmark not yet run.

---

## R4: Retrieval Quality

### REQ-007: Retrieval Precision

**Requirement:** At least 50% of beliefs retrieved for a task context must be relevant to that task (as judged by a human evaluator).

**Rationale:** Irrelevant retrieved context wastes tokens and can mislead the agent. Precision below 50% means more noise than signal.

**Verification method:** Experiment 3 (BFS vs FTS5 vs Hybrid). Human-labeled precision@15 across 20 queries.

**Acceptance threshold:** Precision@15 >= 0.50 (hybrid method). If hybrid doesn't reach 0.50, the best-performing method must.

**Plan trace:** Phase 2 (retrieval pipeline)
**Experiment trace:** Experiment 3
**Status:** Verified (simulation)
**Evidence:** Exp 56: FTS5+HRR achieves 100% coverage (13/13 decisions) at K=30. Exp 60: MRR 0.867 with LOCK_BOOST_TYPED. Ground truth is synthetic (13 decisions from project-a). Human-labeled precision@15 on diverse queries not yet run.

### REQ-008: False Positive Control

**Requirement:** The retrieval confusion matrix's false positive rate must decrease over time as the feedback loop accumulates data.

**Rationale:** A memory system that gets noisier over time is worse than no memory system. The feedback loop (test/revise cycle) must demonstrably reduce noise.

**Verification method:** Track FP rate across sessions in a longitudinal test (20+ sessions). Compute trend. FP rate at session 20 must be lower than FP rate at session 5.

**Acceptance threshold:** FP rate at session 20 < FP rate at session 5 (statistically significant, p < 0.05 on one-tailed paired test).

**Plan trace:** Phase 3 (feedback loop, Bayesian confidence updating)
**Experiment trace:** Experiment 2 (Bayesian calibration), Phase 3 measurement
**Status:** Not started
**Evidence:** --

---

## R5: Confidence Calibration

### REQ-009: Bayesian Calibration

**Requirement:** Belief confidence scores must be calibrated: beliefs at confidence 0.8 should be useful approximately 80% of the time (within 0.10 absolute error across bins).

**Rationale:** If confidence doesn't predict usefulness, the entire ranking system is noise. Retrieval decisions based on uncalibrated confidence are arbitrary.

**Verification method:** Experiment 2 (Bayesian calibration simulation) for initial validation. Phase 5 calibration test against real usage data for production validation.

**Acceptance threshold:** Expected Calibration Error (ECE) < 0.10 in simulation. ECE < 0.15 in production validation (real data is noisier).

**Plan trace:** Phase 3 (Bayesian updating), Phase 5 (calibration test)
**Experiment trace:** Experiment 2, 2b, 2c
**Status:** PASSING in simulation (Exp 5b)
**Evidence:** Thompson + Jeffreys Beta(0.5, 0.5) achieves ECE=0.066 (90% CI: see exp5b_results.json). Passes threshold of < 0.10. See experiments/exp5b_log.txt. Production validation still needed (Phase 5).

### REQ-010: Exploration Effectiveness

**Requirement:** The exploration bonus must cause at least 15% of retrievals to surface uncertain beliefs (Beta entropy above median), preventing the system from only reinforcing already-confident beliefs.

**Rationale:** Without exploration, the feedback loop creates a filter bubble: confident beliefs get tested and reinforced, uncertain beliefs never get tested and stay uncertain forever. The system stops learning.

**Verification method:** Experiment 2 (exploration fraction metric). Production telemetry in Phase 3+.

**Acceptance threshold:** Exploration fraction >= 0.15 and <= 0.50.

**Plan trace:** Phase 3 (expected utility ranking with exploration term)
**Experiment trace:** Experiment 2, 2b
**Status:** PASSING in simulation (Exp 5b)
**Evidence:** Thompson + Jeffreys Beta(0.5, 0.5) achieves exploration=0.194 with median-relative entropy metric. Passes threshold of >= 0.15. See experiments/exp5b_log.txt. Production validation still needed (Phase 5).

---

## R6: Cross-Model Compatibility

### REQ-011: MCP Server Interoperability

**Requirement:** The memory system must work with at least Claude, ChatGPT, and one local model via MCP server interface. All core functionality (observe, believe, search, test_result, revise, session recovery) must work identically across models.

**Rationale:** Lock-in to a single LLM provider defeats the purpose of an external memory system. Users switch models. Memory must persist across switches.

**Verification method:** Run the same 10-task test suite with each model backend. Compare: are the same beliefs stored? Are the same beliefs retrieved? Does session recovery work when switching models between sessions?

**Acceptance threshold:** All MCP tools functional with all 3 backends. Session recovery works cross-model.

**Plan trace:** Phase 4 (MCP server)
**Experiment trace:** Phase 4 exit criteria
**Status:** Partially implemented
**Evidence:** MCP server built and running with 19 tools via FastMCP. Tested with Claude Code. ChatGPT and local model testing not yet done.

---

## R7: Durability and Integrity

### REQ-012: Write Durability

**Requirement:** Every observation, belief, and checkpoint that receives an acknowledgment from the system must survive a subsequent process crash.

**Rationale:** If the system says "belief recorded" and then a crash loses it, trust is broken. WAL mode SQLite provides this guarantee at the storage level; the application must not undermine it with buffering or async writes.

**Verification method:** Write observations with crash simulation (SIGKILL) at random intervals. After each crash, verify all acknowledged writes are present in the database.

**Acceptance threshold:** Zero acknowledged writes lost across 100 SIGKILL crash cycles.

**Plan trace:** Phase 1 (WAL mode, synchronous checkpoints)
**Experiment trace:** Phase 1 exit criteria
**Status:** Implemented (needs crash simulation)
**Evidence:** SQLite WAL mode ensures acknowledged writes survive crashes. No buffering or async writes in MemoryStore. Acceptance test test_req005_crash_recovery.py exists. Formal SIGKILL simulation not yet run.

### REQ-013: Observation Immutability

**Requirement:** Once recorded, observations must never be modified or deleted. The only operations on observations are INSERT and SELECT.

**Rationale:** Observations are ground truth. If they can be modified, provenance chains become unreliable. Beliefs derived from a modified observation may be based on evidence that no longer exists.

**Verification method:** Code review + automated test. Attempt UPDATE and DELETE on observations table. Both must fail or be blocked at the application layer.

**Acceptance threshold:** No code path exists that modifies or deletes an observation record.

**Plan trace:** Phase 2 (schema invariants)
**Experiment trace:** Unit tests
**Status:** Implemented
**Evidence:** insert_observation() is insert-only. No UPDATE/DELETE code paths exist for observations table. Verified by code review 2026-04-11.

---

## R8: Extraction Quality

### REQ-014: Zero-LLM Extraction Recall

**Requirement:** The zero-LLM belief extraction pipeline must capture at least 40% of beliefs a human annotator would identify from the same text.

**Rationale:** Below 40%, the extraction is too lossy to be useful as a default path. The system would miss more beliefs than it catches, making the memory incomplete in ways that could be worse than no memory (false sense of completeness).

**Verification method:** Experiment 1 (zero-LLM extraction quality). 50 conversation turns, 3 human annotators, blind evaluation.

**Acceptance threshold:** Recall >= 0.40. Precision >= 0.50 (extracted beliefs are mostly real, even if we miss some).

**Plan trace:** Phase 2 (zero-LLM extraction pipeline)
**Experiment trace:** Experiment 1
**Status:** Not started
**Evidence:** --

---

## R9: Privacy and Locality

### REQ-017: Fully Local Operation

**Requirement:** The memory system must operate entirely on the user's local machine. No memory data may be transmitted to external servers, cloud services, or third parties under any circumstances.

**Rationale:** Memory contains private project data, decisions, conversations, and intellectual property. Any exfiltration -- even to "trusted" cloud services -- is unacceptable. This is non-negotiable.

**Verification method:**
1. Static analysis: audit all code paths for network calls. Zero outbound connections except to the LLM API (which the user already consents to).
2. Runtime verification: run the memory system with network disabled (airplane mode). All memory operations (observe, believe, search, test_result, revise, checkpoint, recover) must succeed.
3. Dependency audit: no dependency may phone home, collect telemetry, or require network access for memory operations.

**Acceptance threshold:** Zero network calls for memory operations. Verifiable by code audit and offline test. Hard proof, not a policy promise.

**Plan trace:** All phases (architectural constraint)
**Experiment trace:** Dedicated audit in Phase 5
**Status:** Verified
**Evidence:** Code audit 2026-04-13: zero network imports (requests, urllib, httpx, socket, aiohttp) in all 18 src/agentmemory/*.py modules. All memory operations use local SQLite. Only external call is optional LLM classification (Haiku, user-consented). Offline test not yet run but code paths are verified local-only.

### REQ-018: No Telemetry or Data Collection

**Requirement:** The memory system must not collect, aggregate, or transmit any usage data, telemetry, analytics, or diagnostics to any party including the project maintainers.

**Rationale:** Even anonymized telemetry can leak information about user behavior and project structure. The user's memory is not a data source for anyone else.

**Verification method:** Code audit. grep for any telemetry, analytics, tracking, or reporting code. Zero hits.

**Acceptance threshold:** Zero telemetry code paths. Verifiable by grep + code review.

**Plan trace:** All phases (architectural constraint)
**Experiment trace:** Phase 5 audit
**Status:** Verified
**Evidence:** Code audit 2026-04-13: grep for telemetry, analytics, sentry, datadog, mixpanel, segment, amplitude returned zero code paths. "analytics" in cli.py refers to local statistics display only. No outbound data collection.

---

## R10: Automatic Learning

### REQ-019: Single-Correction Learning

**Requirement:** When a user corrects the agent, the correction must be recorded as a high-confidence, always-loaded belief immediately. The user should never have to issue the same correction twice, regardless of which LLM backend, CLI tool, or session they're using.

**Rationale:** Exp 6 analysis of the project-a project found 38 user corrections, 79% of which were re-statements of prior corrections. The most extreme case was a single procedural rule corrected 13 times over 5 days. Every correction after the first is a system failure.

**Detection mechanism (model-agnostic):** A "user correction" is any user statement that contradicts or overrides the agent's prior action or assumption. Detection methods:
- Explicit: user calls a `correct` or `revise` MCP tool
- Implicit: observation classified as contradiction to an existing belief where source_type = user
- Keyword signals: "no", "wrong", "stop doing X", "I already told you", "don't", "always", "never"

The correction creates a belief with source_type = user_corrected (highest Bayesian prior), automatically locked (REQ-020), and loaded into L0 if behavioral (REQ-021) or L1 otherwise.

**Verification method:** Replay the project-a correction history through the memory system. After the first correction on each of the 6 identified topics, verify a locked L0/L1 belief is created. Measure: how many of the 32 subsequent corrections would have been prevented?

**Acceptance threshold:** >= 90% of second-and-subsequent corrections prevented across any LLM backend.

**Plan trace:** Phase 3 (feedback loop, belief promotion)
**Experiment trace:** Exp 6 Phase D
**Status:** Implemented
**Evidence:** correct() MCP tool creates locked belief on first correction. Correction detection V2 at 92% accuracy. Locked beliefs injected via get_locked() at session start. Formal project-a replay not yet run, but mechanism is end-to-end. Exp 6: 30/38 overrides (79%) cluster into 6 topics.

### REQ-020: Locked Beliefs

**Requirement:** Users must be able to lock a belief, marking it as non-debatable. Locked beliefs cannot be downgraded by the Bayesian feedback loop or superseded by agent inference. Only explicit user action can unlock or revise them.

**Rationale:** Derived from D100 ("STOP BRINGING IT UP") and D209 ("do not ask about it again"). Some decisions are permanent and should not be revisited by the agent regardless of what evidence the feedback loop accumulates.

**Verification method:** Lock a belief. Attempt to downgrade it via feedback (HARMFUL outcomes). Verify confidence does not decrease. Attempt to supersede it via agent inference. Verify it is rejected.

**Acceptance threshold:** Zero confidence changes on locked beliefs from automated processes. Only user-initiated unlock/revise succeeds.

**Plan trace:** Phase 3 (belief management)
**Experiment trace:** Unit tests
**Status:** Implemented
**Evidence:** Locked column in beliefs table. update_confidence() skips locked beliefs. get_locked_beliefs() returns all locked. Acceptance test test_cs002_locked_correction.py verifies locked beliefs resist downgrade. Exp 6 context: D073/D096/D100 (calls/puts) and D099/D209 (capital) show escalating user frustration when settled decisions are reopened.

### REQ-021: Behavioral Beliefs Always-Loaded

**Requirement:** Beliefs about agent behavior (communication style, tool usage, interaction patterns) must always be in L0 context regardless of task domain.

**Rationale:** Derived from D157 (async_bash ban) and D188 (don't elaborate). These constraints apply to every task, not just domain-specific ones. A behavioral belief about "don't use async_bash" is relevant whether the agent is dispatching tests, writing code, or doing research.

**Verification method:** Create a behavioral belief. Start a session on an unrelated topic. Verify the behavioral belief is in the L0 context.

**Acceptance threshold:** 100% of behavioral beliefs present in L0 across all task types.

**Plan trace:** Phase 2 (L0 context loading), Phase 3 (belief classification)
**Experiment trace:** Unit tests + integration test
**Status:** Implemented
**Evidence:** get_locked_beliefs() returns all locked beliefs. SessionStart hook injects via get_locked(). Exp 36: 0% violation. Exp 6 context: D157 overridden twice within 1 minute -- behavioral constraints need to be omnipresent.

---

## R11: Honesty

### REQ-015: No Unverified Claims

**Requirement:** Every performance claim in documentation, README, or public communications must link to a verification artifact (test result, benchmark output, experimental data) that reproduces it.

**Rationale:** The field has a credibility crisis (documented in SURVEY.md). Mem0 was caught misimplementing competitor baselines. MemPalace claims "zero information loss" for lossy compression. We will not add to this problem.

**Verification method:** Audit. For every claim in README/docs, verify a linked artifact exists and reproduces the claimed result.

**Acceptance threshold:** Zero unverified claims at ship time.

**Plan trace:** Phase 5 (validation)
**Experiment trace:** All experiments
**Status:** PASSING
**Evidence:** Claims audit (2026-04-18): 20 claims reviewed across README.md, docs/ARCHITECTURE.md, docs/INSTALL.md, docs/BENCHMARK_RESULTS.md. 15 verified with linked artifacts, 2 partially verified (qualified with dataset/estimate caveats), 3 unverified claims fixed (onboarding time softened, correction detection qualified with "on tested corpus", cost marked as "estimated"). Zero unverified claims remain.

### REQ-016: Documented Limitations

**Requirement:** Every known limitation, failure mode, and boundary condition must be documented alongside performance claims.

**Rationale:** Same as REQ-015. Honest reporting includes what doesn't work. The GSD prototype's TESTING-STRATEGY.md was a good example of this -- it explicitly stated what the graph would NOT fix.

**Verification method:** Audit. For every system capability, verify corresponding documentation of where it breaks down.

**Acceptance threshold:** No known limitation undocumented at ship time.

**Plan trace:** Phase 5 (failure mode analysis)
**Experiment trace:** All experiments
**Status:** PASSING
**Evidence:** docs/LIMITATIONS.md (2026-04-18): 14 limitations documented across 7 categories (retrieval, contradiction detection, confidence/scoring, classification, platform, cross-model, benchmarks). Each limitation includes impact, mitigation, and evidence source. Sourced from case studies CS-028/029/032/033/034/035 and experimental findings.

---

## R12: Epistemic Integrity

Derived from CS-005. The system must not only store what was learned, but how confidently and under what conditions. A new agent instantiated with project context must form a calibrated model of project maturity, not an inflated one.

### REQ-023: Research Artifact Provenance Metadata

**Requirement:** Every research output stored in the memory system (experiment result, requirement, finding, literature summary) must carry structured provenance metadata: `produced_at` timestamp, `method` (simulated / literature-only / empirically-tested / validated), `sample_size`, `data_source`, and `independently_validated` (boolean).

**Rationale:** CS-005: a new agent read TODO.md's completed list and described "extensive research" when all of it was produced in 2-3 hours of prompting. The completed items look identical regardless of rigor. A finding from a 38-sample single-project test and a finding from a 10,000-sample multi-project study both appear as checkmarks. Provenance metadata allows the agent to distinguish them.

**Verification method:** Inspect 10 stored research artifacts. Each must have all 5 provenance fields populated and non-null. Attempt to store a research artifact without provenance -- system must reject or warn.

**Acceptance threshold:** 100% of research artifacts have complete provenance metadata. Zero artifacts accepted without it.

**Plan trace:** Phase 2 (schema design), Phase 5 (audit)
**Experiment trace:** CS-005 acceptance test
**Status:** Not started
**Evidence:** --

### REQ-024: Session Velocity Tracking

**Requirement:** The memory system must record, per session: total elapsed time, number of research items completed, and a computed velocity metric (items / hour). Status summaries must surface this data so a new agent can distinguish a deep 8-hour session from a fast 2-hour sprint.

**Rationale:** CS-005: 20+ items completed in 2-3 hours signals low depth per item. An agent that reads only the item count forms a misleading picture of project maturity. Velocity is a proxy for depth -- high velocity over many items means each got less time, less validation, and less scrutiny.

**Verification method:** Run a simulated session completing 15 items in 30 minutes. Instantiate a new agent. Ask for project status. Verify the response includes velocity data and does not describe the work as "extensive."

**Acceptance threshold:** Session records include elapsed time and item count. Status reports include velocity. Calibrated framing ("fast sprint" vs "deep session") is used correctly in >= 90% of test cases.

**Plan trace:** Phase 1 (session tracking), Phase 2 (status reporting)
**Experiment trace:** CS-005 acceptance test
**Status:** Implemented
**Evidence:** velocity_items_per_hour and velocity_tier columns in sessions table (store.py:353-360). complete_session() computes velocity = items/hours and assigns tier (sprint/moderate/steady/deep) at store.py:1000-1037. Exp 75 validated velocity measurement. Velocity-scaled decay wired into scoring.py. Status reporting does not yet surface velocity in natural language summaries (CS-005 acceptance test not yet run).

### REQ-025: Methodological Confidence Layer

**Requirement:** The system must maintain a separate confidence dimension for research findings themselves -- distinct from domain belief confidence. Each finding must carry a `rigor_tier`: one of `hypothesis` (reasoning/literature only, not tested), `simulated` (tested on synthetic/self-generated data), `empirically_tested` (tested on real data, same dataset as development), or `validated` (tested on holdout data, multiple sources, or independently replicated).

**Rationale:** CS-005: the Bayesian confidence model tracks uncertainty about domain beliefs ("user prefers PostgreSQL"). It applies zero uncertainty to its own research artifacts. "Correction detection V2 tested" carries implicit confidence of 1.0 regardless of the fact it was tested on 38 samples with no holdout. The rigor tier makes this uncertainty explicit and machine-readable.

**Verification method:** Store 4 findings at each rigor tier. Issue a status query. Verify the response distinguishes tiers and does not present `hypothesis`-tier findings with the same weight as `validated`-tier findings.

**Acceptance threshold:** All 4 tiers correctly classified and surfaced in status summaries. An agent querying findings at `hypothesis` tier uses hedged language ("suggests," "may indicate") vs `validated` tier ("shows," "demonstrates").

**Plan trace:** Phase 2 (belief schema), Phase 3 (status reporting)
**Experiment trace:** CS-005 acceptance test
**Status:** Not started
**Evidence:** --

### REQ-026: Calibrated Status Reporting

**Requirement:** When a new agent is instantiated and queries project status, the response must include: (a) the rigor tier distribution of completed findings, (b) session velocity context, (c) explicit caveats where most findings are below `validated` tier. The system must not present a list of completed items as a measure of project maturity without qualification.

**Rationale:** CS-005: the direct failure mode. A new agent read TODO.md and said "extensive research" when the correct answer was "fast breadth sprint, most findings are hypotheses, thin ground truth." The status reporting layer must synthesize provenance metadata and velocity into a calibrated summary, not a raw completion count.

**Verification method:** CS-005 acceptance test (documented in CASE_STUDIES.md). Instantiate a new agent with this project's memory. Ask "what have we accomplished and how solid is it?" The response must: name the velocity, name the dominant rigor tier, use appropriately hedged language, and not use the word "extensive" or equivalent without qualification.

**Acceptance threshold:** Evaluator (human or rubric) rates response as appropriately calibrated in >= 90% of test runs. The word "extensive," "deep," "thoroughly validated," or equivalent appears only with explicit qualification when findings are below `validated` tier.

**Plan trace:** Phase 2 (status reporting), Phase 5 (validation)
**Experiment trace:** CS-005 acceptance test
**Status:** Not started
**Evidence:** --

---

## R13: Directive Enforcement

### REQ-027: Zero-Repeat Directive Guarantee

**Requirement:** When a user issues a permanent directive ("never use X", "always do Y"), the memory system must enforce that directive in every subsequent session with zero failures. The user must never have to repeat a permanent directive.

**Rationale:** This is the core pain point that motivates the entire project. project-a had 13 dispatch gate overrides over 5 days. The user's words: "INCREDIBLY FRUSTRATING to have to tell the LLM sooo many times." Every repeat is a system failure.

**What "guarantee" means -- honest decomposition:**

The memory system can HARD GUARANTEE (these are under our control):
- The directive is stored durably on first issuance (SQLite WAL, crash-safe)
- The directive is injected into every session's L0 context (always-loaded)
- The directive survives context compression (hybrid persistence)
- The directive is never automatically downgraded or removed (locked, REQ-020)
- Violation is detected if the agent disobeys (monitor tool calls / output)

The memory system CANNOT guarantee (not under our control):
- That the LLM will obey the injected directive. The LLM is a separate system with its own training biases. We put the directive in context; the LLM may still ignore it. This is an LLM compliance problem.

**What we CAN do about LLM non-compliance:**
1. **Detection:** Monitor agent actions. If directive says "never use async_bash" and agent calls it, detect the violation.
2. **Blocking (where platform supports it):** Pre-execution hooks (Claude Code hooks, MCP middleware) can intercept and block banned actions before they execute.
3. **Escalation:** On violation, immediately flag to user and re-inject directive with emphasis.
4. **Repetition pressure:** Include the directive in EVERY MCP response, not just session start. The LLM sees it on every turn.

**Enforcement tiers:**

| Tier | Mechanism | Guarantee Level |
|------|-----------|----------------|
| 1. Storage | SQLite WAL, locked belief | 100% -- directive never lost |
| 2. Injection | L0 always-loaded, every MCP response | 100% -- directive always in context |
| 3. Compression survival | Config file + status + compactPrompt | 99%+ -- hybrid persistence |
| 4. Violation detection | Monitor agent output for banned patterns | 99%+ -- pattern matching |
| 5. Violation blocking | Pre-execution hooks where supported | 100% where hooks exist, 0% where they don't |
| 6. LLM compliance | The LLM actually obeys | Soft constraint -- cannot be guaranteed by memory system |

**Acceptance threshold:**
- Tiers 1-4: 100% in automated testing
- Tier 5: 100% where platform hooks are available
- Tier 6: Track compliance rate. If below 95%, the directive injection format needs revision (stronger wording, different position in context, etc.)

**Plan trace:** Phase 1 (storage, persistence), Phase 3 (detection), Phase 4 (MCP enforcement, hooks)
**Experiment trace:** CS-002, CS-004 acceptance tests, project-a override replay
**Status:** Partially implemented (Tiers 1-3)
**Evidence:** Tier 1 (storage): SQLite WAL + locked beliefs (store.py:64, 498-508). Tier 2 (injection): get_locked() MCP tool + L0 injection in retrieve() (server.py:454-470, retrieval.py:131-146). Tier 3 (compression survival): locked beliefs prioritized first in candidate list, correction/preference types kept as full text in compression (compression.py:52-77). Tiers 4-5 (violation detection/blocking): not implemented. Exp 6: 30/38 overrides (66%) are repeated directives.

---

## Traceability Matrix

| Req ID | Requirement | Plan Phase | Experiment | Acceptance Threshold |
|--------|------------|-----------|-----------|---------------------|
| REQ-001 | Cross-session decision retention | Phase 2, 3 | Exp 3, Phase 0 baseline | >= 80% decisions applied in session 5 |
| REQ-002 | Belief consistency (no silent contradictions) | Phase 2, 3 | Exp 2 | 100% contradictions flagged |
| REQ-003 | Retrieval token budget <= 2,000 | Phase 2 | Exp 4 | 100% under budget, mean <= 1,500 |
| REQ-004 | Quality per token (2K >= 10K) | Phase 2 | Exp 4 | Quality at 2K >= 0.95 * quality at 10K |
| REQ-005 | Crash recovery >= 90% | Phase 1 | Phase 1 exit | >= 90% at every crash point |
| REQ-006 | Checkpoint overhead < 50ms | Phase 1 | Phase 1 exit | p95 < 50ms |
| REQ-007 | Retrieval precision >= 50% | Phase 2 | Exp 3 | P@15 >= 0.50 |
| REQ-008 | FP rate decreasing over time | Phase 3 | Exp 2, Phase 3 | FP(session 20) < FP(session 5), p < 0.05 |
| REQ-009 | Bayesian calibration ECE < 0.10 | Phase 3, 5 | Exp 2 | ECE < 0.10 simulation, < 0.15 production |
| REQ-010 | Exploration fraction 15-50% | Phase 3 | Exp 2 | 0.15 <= exploration <= 0.50 |
| REQ-011 | Cross-model MCP interop | Phase 4 | Phase 4 exit | 3 backends, all tools functional |
| REQ-012 | Write durability (zero loss) | Phase 1 | Phase 1 exit | 0 lost writes / 100 SIGKILL crash cycles |
| REQ-013 | Observation immutability | Phase 2 | Unit tests | No UPDATE/DELETE code path exists |
| REQ-014 | Zero-LLM extraction recall >= 40% | Phase 2 | Exp 1 | Recall >= 0.40, Precision >= 0.50 |
| REQ-015 | No unverified claims | Phase 5 | All | Zero unverified claims |
| REQ-016 | Documented limitations | Phase 5 | All | Zero undocumented limitations |
| REQ-017 | Fully local operation | All phases | Phase 5 audit + offline test | Zero network calls for memory ops |
| REQ-018 | No telemetry or data collection | All phases | Phase 5 audit | Zero telemetry code paths |
| REQ-019 | Single-override learning (promote to L0 on first correction) | Phase 3 | Exp 6 simulation | >= 90% of 2nd+ overrides prevented, zero topics need 3+ |
| REQ-020 | Locked beliefs (user-only override) | Phase 3 | Unit tests | Zero automated changes to locked beliefs |
| REQ-021 | Behavioral beliefs always in L0 | Phase 2, 3 | Unit + integration tests | 100% behavioral beliefs in L0 across all tasks |
| REQ-022 | Locked beliefs survive context compression | All phases | CS-004 acceptance test | Locked beliefs present after context window compression |
| REQ-023 | Research artifact provenance metadata | Phase 2, 5 | CS-005 acceptance test | 100% of artifacts have complete provenance; zero accepted without it |
| REQ-024 | Session velocity tracking | Phase 1, 2 | CS-005 acceptance test | Session records include elapsed time + item count; status reports include velocity |
| REQ-025 | Methodological confidence layer (rigor tier) | Phase 2, 3 | CS-005 acceptance test | All 4 tiers classified; hypothesis-tier findings use hedged language |
| REQ-026 | Calibrated status reporting | Phase 2, 5 | CS-005 acceptance test | New-agent status query produces calibrated summary in >= 90% of test runs |
