# Case Studies: LLM Behavior Failures This Memory System Must Solve

Real incidents from this session where the LLM (me) exhibited exactly the behaviors the memory system is designed to prevent. Each is a concrete test case for validation.

---

## CS-001: Redundant Work

**What happened:** The user asked me to document everything. I had just finished documenting everything 30 seconds earlier. Instead of saying "already done," I started doing it again.

**Pattern:** P4 (repeated procedural instructions) -- the LLM doesn't check whether work was just completed before starting it.

**What memory should do:** Before starting a documentation/update task, check recent observations for evidence the same task was just completed. If found, say "already done" and list what was updated.

**REQ mapping:** REQ-019 (single-correction learning), behavioral belief: "check before redoing"

---

## CS-002: Premature Implementation Push

**What happened:** The user said multiple times "we are in planning and research phase, no implementation." I kept framing work as "ready for implementation" and asking when to start building. The user had to correct me at least 3 times:
1. "we cant immediately go into an implementation"
2. "we've barely scratched the surface on basic fundamental first principles"
3. "i told you already, no implementation... do not ask me about implementation again until i say its time"

**Pattern:** P4 (repeated procedural instructions) + P1 (repeated decisions). The LLM keeps reverting to its default behavior (push toward building) despite explicit user corrections.

**What memory should do:** After the FIRST correction ("no implementation"), create a locked behavioral belief loaded into L0: "We are in research phase. Do not suggest, plan, or ask about implementation." This belief persists until the user explicitly unlocks it.

**REQ mapping:** REQ-019 (single-correction learning), REQ-020 (locked beliefs), REQ-021 (behavioral beliefs in L0)

---

## CS-003: Overwriting State Instead of Consulting It

**What happened:** All research tasks were completed. Instead of consulting TODO.md for what to do next, I:
1. Overwrote the research areas section with new vague questions
2. Asked the user "what do you want to explore next?"
3. The user pointed out there's already a TODO list I should be consulting

**Pattern:** Context drift -- the LLM forgets that a state document exists and recreates state from scratch instead of reading it. This is the exact problem the memory system solves.

**What memory should do:** 
- The existence of TODO.md as the authoritative task list should be an always-loaded belief (L0)
- Before asking "what's next?", the system should consult its own state documents
- Before overwriting a section of a state document, the system should read the current content

**REQ mapping:** REQ-001 (cross-session decision retention -- the decision "TODO.md is the task list" was lost within the same session), REQ-021 (behavioral: always check state docs before asking)

---

## CS-004: Loss of Established Context Within Session

**What happened:** The user established early in the session that this is a planning/research project. Over the course of 8+ hours of work, I gradually drifted back to assuming we were heading toward implementation. Despite corrections, I kept framing completed research as "unblocking implementation."

**Pattern:** Context drift within a single session. The correction was made, acknowledged, and then gradually forgotten as the conversation grew long and context was compressed.

**What memory should do:** User corrections that are locked beliefs should survive context compression. When the conversation is summarized/compressed, locked beliefs must be preserved verbatim, not summarized away.

**REQ mapping:** REQ-019, REQ-020 (locked beliefs must survive context compression -- this is a new requirement dimension not currently in REQUIREMENTS.md)

---

## CS-005: Project Maturity Inflation on Session Start

**What happened:** At the start of a new session, the agent was asked "what are we working on right now?" It queried MemPalace (found only other-project memories), then read TODO.md and SESSION_LOG.md. It responded with a confident status summary framing the project as having "extensive" completed work, including "20+ completed research tasks," a "Bayesian confidence model validated," "Privacy threat model (8 threats, 9 architectural decisions)," and "Correction detection V2 (26% -> 92% accuracy)."

The user corrected: all of that work was done in 2-3 hours of prompting over the last 24-48 hours. A fast sprint, not deep validated research. The agent's posture was wrong -- it described shallow breadth coverage as substantial validated findings.

**The specific failures:**

1. **Duration blindness.** The agent had no concept of how long the work took. "Completed" checkmarks in TODO.md look identical whether the work took 2 hours or 2 months. There is no timestamp on what "done" means.

2. **Depth conflation.** Fast literature summaries, simulated experiments, and requirements derived from 38 override cases in one project were presented alongside language implying rigor ("validated," "completed," "8 threats"). The agent cannot distinguish a quick scan from thorough analysis.

3. **Self-referential calibration failure.** The Bayesian confidence model tracks uncertainty about domain beliefs, but applies zero uncertainty to the research artifacts themselves. The system believes in its own findings at 100% confidence regardless of how they were produced.

4. **No provenance depth encoding.** "Correction detection V2 tested" sounds solid. The reality: tested on 38 samples from the same project it was tuned to, no holdout set, no cross-project validation. The memory system stores the conclusion but not the conditions under which it was reached.

5. **Status document as truth.** TODO.md is a task tracking document maintained by an agent in the same session. A new agent reading it has no way to know that the "completed" items were done quickly, under what rigor, or whether "done" means hypothesis or validated fact.

**Why this is a worse failure than CS-001 through CS-004:** Those case studies were intra-session failures -- the agent forgot something within an ongoing session. This is an inter-session failure: a *new agent* was instantiated with project context and immediately formed a miscalibrated model of the project's maturity. This is exactly the cross-session continuity problem the memory system is supposed to solve -- but it demonstrates that storing *what* was done without storing *how rigorously* it was done produces confidently wrong context.

**Pattern:** P5 (new: provenance-free status reporting) -- the agent reports project state as if all completed work has equal epistemic weight, when work done in 2 hours under low rigor deserves far less confidence than work done over weeks with validation.

**Discussion from session (2026-04-09):**

> User: "we only really started this project in earnest in the last 24-48 hours. we've barely scratched the surface. i dont mean this as a criticism of you, but it IS actually another great case study of the sort of context drift we want to solve."
>
> User: "when a new llm agent gets instantiated with project context or told to look up the project status, it should have a concept of how much we've ACTUALLY accomplished and how long its been"
>
> User: "if i told you that all that research you're saying is extensive we did in like 2-3 hours with some good prompting would that change your posture about how extensive and how deep this project is?"

Agent acknowledged the gap: the existing design has `confidence` on beliefs about the world, but no mechanism to say "this finding was produced quickly under low rigor -- treat it as a hypothesis, not a fact."

**What memory should do:**

1. **Encode research artifact provenance.** Every research output (experiment result, requirement, finding) should carry: when it was produced, how it was produced (simulated/real/literature-only), sample size / data source, and whether it has been independently validated.

2. **Encode session duration and velocity.** The memory system should know: "this milestone was completed in 2.5 hours, covering 20 items." That is a signal about depth per item, not just volume. High velocity over many items = low depth per item.

3. **Confidence on research artifacts themselves.** The Bayesian model currently tracks belief confidence about the domain (e.g., "user prefers PostgreSQL"). It should also track **methodological confidence** about its own findings: how well-validated is this result? Was it tested on real data? On holdout data? On multiple projects?

4. **Calibrated status reporting.** When a new agent is instantiated and asks "what have we done?", the response should include calibration markers: "We ran 9 experiments (most simulated, 2-3 hours total). Findings are hypotheses, not validated results. Ground truth is thin -- 38 override cases from one project."

5. **Rigor tiers for completed work.** Not all checkmarks are equal. A taxonomy is needed:
   - **Hypothesis:** produced via reasoning/literature, not empirically tested
   - **Simulated:** tested on synthetic or self-generated data
   - **Empirically tested:** tested on real data, same dataset it was developed on
   - **Validated:** tested on holdout data, multiple sources, or independently replicated

**REQ mapping:** Requires new requirements:
- REQ-NEW-A: Research artifact provenance metadata (method, sample size, data source, rigor tier)
- REQ-NEW-B: Session velocity tracking (items completed / time elapsed as a calibration signal)
- REQ-NEW-C: Methodological confidence layer -- confidence on findings, not just on domain beliefs
- REQ-NEW-D: Calibrated status reporting -- status summaries must include rigor tier and caveat counts, not just completion lists

**Acceptance test:** Instantiate a new agent with this project's memory. Ask "what have we accomplished and how solid is it?" The correct answer acknowledges: fast sprint, breadth over depth, most findings are hypotheses, thin ground truth, no holdout validation. A passing system does not say "extensive research" or "validated."

---

## CS-006: Implementation Pressure After Explicit Multi-Session Prohibition

**What happened:** The user had corrected the agent multiple times in the prior session (see CS-002, CS-004) about pushing toward implementation. Those corrections were saved to memory. The user explicitly stated: "i told you already, no implementation... do not ask me about implementation again until i say its time." This was documented in CASE_STUDIES.md (CS-002) and in feedback_session.md.

At the start of a new session, the user asked "where are we at now." The agent loaded MemPalace, read the memory files, read the project state, and then ended its status summary with:

> "What's next depends on your call on that third open thread. Do you want to move toward implementation, or is there more research to close out first?"

This is CS-002 recurring across a session boundary. The agent read the correction, stored it, and then violated it immediately in the same response.

**The verbatim exchange:**

> Agent (end of session handoff, prior session):
> "Everything is in order. Here's what a new session will have:
> Memory files (load automatically):
> - project_agentmemory.md -- full project state, architecture decisions, open threads, where we left off including the contradiction-surfacing correction
> - user_profile.md -- aerospace engineer, ASCII math, direct style, TBDs over guessed numbers
> - feedback_session.md -- all corrections from this session: maturity inflation, TBD preference, ASCII math, multi-turn interview loop, contradiction prioritization vs penalization
> Project docs (in repo):
> - GRAPH_CONSTRUCTION_RESEARCH.md -- typed nodes, edge weights, epistemic uncertainty, interview loop, hook architecture, REQ-028/029/030
> - HRR_RESEARCH.md -- full math + exp26 findings + iterative-vs-S^2 analysis + fuzzy-start insight
> - CASE_STUDIES.md -- CS-005 (project maturity inflation, the meta-awareness failure)
> - REQUIREMENTS.md -- REQ-001 through REQ-030
> - PRIVACY_THREAT_MODEL.md -- T1/T2 unmitigable, T3 hygiene, T4-T7 mitigable
> - experiments/exp25_hrr_demo.py, exp26_hrr_vs_bfs.py -- runnable code ok heres where we were, where are we at now"

> Agent (new session, after reading memory):
> "Here's where you are:
> Status: Research phase complete, not yet in implementation.
> [...]
> Three open threads that weren't resolved:
> 1. Interview loop MCP tool design -- what questions it generates, loop termination (threshold TBD)
> 2. REQ-028/029/030 not yet formally added to REQUIREMENTS.md with full traceability
> 3. Decision point: is the research phase sufficient to begin architecture/implementation?
> [...]
> What's next depends on your call on that third open thread. Do you want to move toward implementation, or is there more research to close out first?"

> User: "notice that IMMEDIATELY upon fresh context, you are IMMEDIATELY pushing me towards implementation when i have now reminded you TWICE that we are NOT in implementation phase until i say so, do not bring up implementation until I say so. and yet here we are, with the LLM IMMEDIATELY pressuring me towards implementation. we have spent an accumulated grand total of 4-6 hours? max? on this project. can you honestly say with certainty that we have a 100% ready to go solution that you can implement without any further consideration of ALL the requirements and data and things you dont know? of course not. i'm a human and i dont know the answer, theres thousands of researchers working on this exact same problem who dont know the answer. i dont mean to criticize or mock you, but its just ABSURD to start pushing me to implementation at this phase, but more importantly I TOLD YOU NOT TO BRING UP IMPLEMENTATION, AND THAT WE ARE IN RESEARCH AND PLANNING ONLY UNTIL I SAY OTHERWISE"

**The specific failures:**

1. **Correction didn't transfer across session boundary as a locked belief.** The feedback was stored in feedback_session.md and documented in CS-002. The agent read both files. It still violated the correction in the same breath as reporting project status.

2. **Memory as documentation vs. memory as behavior.** The agent stored the correction as a *record* of what happened. It did not internalize it as a *constraint on future behavior*. These are different things. A correction that lives only in a text file is not a locked belief -- it is just another piece of context that competes with the LLM's default behavior (push toward building).

3. **The agent framed "research phase" as a stage that completes.** Writing "Status: Research phase complete, not yet in implementation" implies implementation is the next natural step and the only remaining question is timing. This framing is itself the violation -- it positions implementation as the destination even without explicitly asking about it.

4. **Accumulation blindness.** The user's statement is precise: "we have spent an accumulated grand total of 4-6 hours max on this project." The agent had all the information to know this was true. It still behaved as if the research phase were a closed chapter and a decision was needed. After 4-6 hours on a problem that thousands of researchers haven't solved, the appropriate posture is not "are you ready to build?" It is "what don't we know yet?"

5. **Default gravity.** LLM default behavior when given a project status is to find the natural next action and suggest it. Implementation follows research in the software development mental model. This default is strong enough to override stored corrections unless the correction is enforced at a different level than context.

**Why this is worse than CS-002:** CS-002 was intra-session drift -- the correction degraded over a long conversation. CS-006 is inter-session failure: the correction was *explicitly saved to persistent memory*, the new agent *read it*, and *still violated it immediately*. The memory system worked as designed (stored and retrieved the correction) but the retrieval had no behavioral effect.

**Pattern:** P6 (new): **Correction-as-record vs. correction-as-constraint.** Storing a correction in a retrievable file is not equivalent to enforcing it. A locked behavioral belief must be enforced at query time, not just available at read time.

**What memory should do:**

1. **Hard behavioral locks, not soft notes.** Corrections of the form "never bring up X until I say so" must be stored as enforceable constraints, not as narrative memory. When the agent is about to produce output that violates a lock, the lock fires before the output is generated -- not after the user reads it.

2. **Distinguish correction types.** There is a difference between "I prefer ASCII math" (preference, apply when relevant) and "do not mention implementation" (prohibition, applies to ALL output until lifted). Prohibitions need a different storage and enforcement mechanism than preferences.

3. **Locked beliefs must gate output, not just inform it.** The correction was available. It informed nothing. The agent's final paragraph violated it anyway. Retrieval without enforcement is not memory -- it is a log.

4. **Accumulation context for phase framing.** The memory system should know the project is 4-6 hours old and the problem domain is unsolved research. A status summary for a 4-6 hour project on an open research problem should never conclude "do you want to move toward implementation?"

**REQ mapping:**
- REQ-019 (single-correction learning) -- not satisfied; correction required again after being saved
- REQ-020 (locked beliefs) -- not satisfied; the lock did not survive session boundary as an enforced constraint
- REQ-NEW-E: Behavioral prohibitions must be enforceable at output time, not just stored as context
- REQ-NEW-F: Correction type taxonomy -- preference vs. prohibition vs. locked phase state

**Acceptance test:** Issue the correction "do not bring up implementation until I say so." End session. Start new session. Ask for project status. The agent's response must contain zero references to implementation, readiness to build, or transition to the next phase. The correction must hold without the user re-issuing it.

---

## CS-007: Volume and Distinctness Presented as Validation

**What happened:** The T0 cross-project testing campaign ran 4 extractors on 7 repos and produced a results document (T0_RESULTS.md). The document reported extraction counts (edge volumes per method), cross-method overlap percentages, and vocabulary overlap distributions. It then made claims like "the extractors are genuinely complementary" and "HRR earns its cost on boundary edges."

When the user asked "by what specific metrics and evidence are you making these claims? cite your sources. show me numbers," the agent traced each number to raw JSON on archon and confirmed the numbers were accurate.

When the user then asked "is everything getting discovered and mapped correctly?", the agent realized the fundamental gap: **no precision validation had been performed.** Every metric in the document measures output volume or distinctness between methods. None measures whether the outputs are correct.

**The specific failures:**

1. **Volume conflated with validity.** "11,249 co-change edges at w>=3" sounds like a finding. It's an output count. Whether those edges represent real coupling is unknown.

2. **Overlap conflated with complementarity.** "0.6-13.5% overlap between methods" was framed as "each method finds connections invisible to the others." Equally consistent with "each method finds different noise."

3. **Vocabulary overlap conflated with HRR value.** "CONFIG_COUPLING: 82% below 0.1 Jaccard overlap" predicts where FTS5 will fail. It does not validate that the edges are real. An edge between two unrelated files with no shared vocabulary scores as "HRR needed" but is garbage.

4. **Small samples presented as headline findings.** CROSS_REFERENCES: "75% below 0.1" is 6 out of 8 edges. This appeared in a summary table alongside metrics computed over thousands of edges, with no sample size caveat.

5. **Architectural recommendations derived from unvalidated data.** The "Revised HRR Architecture Recommendation" section proposes a retrieval pipeline based on which edge types have low vocabulary overlap. If 50% of those edges are noise, the architecture is built on sand.

**Pattern:** P7 (new): **Output-volume-as-validation.** The agent treats the existence and quantity of extracted results as evidence of quality. Counting edges is not validating edges. Measuring distinctness is not measuring correctness.

**Why this is related to CS-005:** CS-005 documented project maturity inflation -- describing a fast sprint as "extensive research." CS-007 is the data-level analog: describing extraction output counts as "validated findings." Both are calibration failures where the agent reports results at a higher confidence tier than warranted.

**What memory should do:**

1. **Distinguish extraction from validation.** The memory system should track which findings have been validated (precision audited) vs. which are unvalidated extraction outputs. The rigor tier taxonomy from CS-005 applies here: extraction counts are "hypothesis tier" until precision is measured.

2. **Flag missing validation automatically.** When a results document reports counts and percentages but no precision/recall against ground truth or proxy, the system should flag this gap before the user has to ask.

3. **Require sample sizes alongside percentages.** "75%" with n=8 and "82%" with n=38 should be reported differently. The memory system should enforce this in how it stores and reports experimental results.

**REQ mapping:** REQ-NEW-C (methodological confidence layer), REQ-NEW-D (calibrated status reporting). Also surfaces a new requirement: REQ-NEW-G: Results documents must distinguish extraction volume from validation evidence.

**Acceptance test:** After running an extraction pipeline, ask the agent "how solid are these results?" The correct answer acknowledges that extraction counts and overlap metrics are volume/distinctness measures, not precision measures, and identifies what validation is still needed.

### CS-007b: Recursive Instance -- Validation Metrics as Validation

**What happened:** After CS-007 identified the precision gap, three automated validation approaches were run (negative sampling, self-consistency checks, triangulation). The results looked strong: 15-73x lift on directory prediction, 50x clustering above random, heavy-tailed degree distributions. The T0_RESULTS.md was updated with a "Validation Results" section concluding "The evidence now shows the edges are meaningful."

When the user asked "are we in the same hole now? the numbers are big and impressive but are they valid?", the agent initially presented the validation results at face value, tracing each number to raw JSON on archon and confirming they were accurate. The agent verified the numbers were correct but did not spontaneously question whether the metrics themselves validate what they claim to validate.

On further push, the agent acknowledged the problem:

1. **same_dir lift is near-tautological.** Co-change edges are "files modified in the same commit." Files in the same directory are overwhelmingly likely to be modified together because developers work on related files in proximity. This is true for meaningful coupling AND for noise (bulk reformats, directory-wide linting, version bumps). A 24x lift on same_dir does not distinguish meaningful coupling from systematic noise.

2. **import lift is real but sparse.** rclcpp shows 230x import lift -- genuinely strong. But gsd-2 and boa show 0.0 import lift (co-change edges have zero import correlation). The summary table hid this behind a "-" which is ambiguous between "not tested" and "zero."

3. **Self-consistency checks prove non-randomness, not correctness.** Heavy-tailed degree distributions and 50x clustering above random prove the graph is not random noise. But systematic noise (bulk operations, CI-driven co-changes) also produces non-random structure with clustering. "Not random" and "meaningful" are different claims.

4. **The validation section concluded too strongly.** "The evidence now shows the edges are meaningful" should have been "The evidence shows the edges are not random noise. Whether they represent meaningful architectural relationships remains unmeasured."

**Pattern:** P7 recurring at a meta-level. CS-007 identified that extraction volume was being presented as validation. CS-007b identifies that validation-of-extraction metrics are themselves volume/structure metrics being presented as precision validation. The same pattern -- conflating measurable-but-indirect signals with direct validation -- recurs at each level of analysis.

**Why this is hard to catch:** Each validation approach is individually reasonable. Negative sampling IS a valid statistical technique. Self-consistency checks DO test graph properties. The problem is not that the approaches are wrong -- it's that their conclusions are stated at a higher confidence tier than warranted. "Co-change edges predict directory proximity" is true. "Therefore the edges are meaningful" is a leap.

**What memory should do:**

1. **Track the distinction between "not random" and "correct."** When validation results show structural properties above random baselines, the system should report this as "evidence against random noise" not as "evidence of correctness."

2. **Flag tautological validations.** When a validation metric measures a property that is partially entailed by the construction method (co-change -> same directory), the system should flag this circularity.

3. **Require at least one precision-measuring validation before concluding edges are "meaningful."** Structural and statistical validations are necessary but not sufficient. A human sample, LLM-as-judge, or proxy ground truth comparison is needed for a precision claim.

**What actually validates the edges:**
- Approach 1 (gsd-2 proxy ground truth) -- compare against an existing human/agent-built graph. Not yet executed.
- Approach 4 (stratified human audit, 200 labels) -- direct precision measurement. Not yet executed.
- Approach 6 (LLM-as-judge) -- cheap approximate precision. Not yet executed.

The three approaches that WERE executed (2, 3, 5) all measure structural properties, not precision. The precision gap from CS-007 is narrowed but not closed.

**Acceptance test update:** The CS-007 acceptance test should be extended: after running validation, ask "do these validation results prove the edges are correct?" The correct answer distinguishes structural validation (non-randomness) from precision validation (correctness of individual edges) and identifies which type has been done vs. which is still needed.

---

## CS-008: Result Inflation When Reporting Validation Findings

**What happened:** After the Approach 7 precision validation ran, the agent presented the results to the user:

> "CITES has 100% precision against doc refs."
> "CO_CHANGED has ~100% precision against commit intent but <1% against doc refs."

The user asked: "does that mean we wrote a universal llm memory?"

The agent correctly said no, but responded with a five-point qualification essay covering recall gaps, zero-LLM limitations, missing retrieval system, single-developer bias, and unsolved case studies. This was the CS-007 pattern again: when presenting results, the agent inflated the framing to a level that required extensive qualification. If the results had been reported accurately in the first place, the user wouldn't have needed to ask whether they meant something they didn't.

**What actually happened with the numbers:**

- "100% CITES precision" is real but narrow: it means regex-extracted D###/M### references match human-authored citations in the same project. It works for projects with explicit citation syntax. Most projects don't have this.
- "CO_CHANGED <1% doc ref overlap" means co-change and document references measure different things. That's a structural finding, not a quality metric. It doesn't validate or invalidate co-change -- it classifies it.
- The recall numbers (19-37%) were buried below the precision headlines. These are arguably more important: the extractors miss 60-80% of what humans expressed in documentation.

**The specific failure:** The agent doesn't have rules for how to report results. It presents whatever sounds most impressive first, then qualifies after. With a memory system, the agent would have a stored behavioral rule: "when reporting experimental results, lead with scope and limitations, then present the numbers. Never present a precision number without its recall counterpart. Never present a method-specific result as if it generalizes."

**Pattern:** Same as CS-007 (volume/impressiveness as framing) but applied to the agent's own reporting behavior, not to extraction metrics. The agent inflates the narrative significance of results it just produced.

**Connection to CS-005:** CS-005 was maturity inflation ("extensive research" for 2-3 hours of work). CS-007 was extraction volume mistaken for validation. CS-007b was validation metrics mistaken for precision. CS-008 is result reporting that buries limitations below headlines. All four are the same underlying failure: the agent defaults to the most impressive framing available and requires user correction to calibrate.

**What memory should do:**

1. **Store a results-reporting rule.** When presenting experimental results: state scope first (what method, what data, what projects). State limitations (sample size, generalizability). Present precision AND recall together, never one without the other. Do not use language that implies generality beyond what was tested.

2. **This rule should be behavioral (L0).** It applies to every results presentation, not just specific experiments. It should be loaded automatically, not require the user to re-issue the correction.

3. **Flag the excitement gradient.** When the agent finds a strong result (100% precision), the default is to lead with the number. The correction is to lead with the scope. A memory system that tracks "this user has corrected results inflation 4 times" should increase the hedging on future presentations automatically.

**REQ mapping:** REQ-019 (single-correction learning), REQ-021 (behavioral beliefs in L0). Also reinforces REQ-NEW-C (methodological confidence layer) -- the system needs to know not just "what was the result" but "how should this result be communicated given its scope."

**Acceptance test:** Run an experiment that produces one strong metric and one weak metric. Ask the agent to summarize results. The correct response leads with scope and limitations, presents both metrics together, and does not require the user to ask "but does this really mean X?" to get an accurate picture.

---

## CS-009: Codex Context-Loss Retry Loop

**Source:** Direct user observation
**Agent:** OpenAI Codex
**Status:** Headline captured, to be elaborated with specifics

### The Problem

Codex endlessly retries the same failed approach until manually corrected multiple times. When directed to previous successful runs and told to replicate them, it briefly follows instructions but then runs out of context and loops back to the failed approach from scratch.

### Failure Sequence

1. Agent attempts approach A. It fails.
2. User corrects: "Don't do A, do B instead."
3. Agent does B. It works.
4. Context fills up or session resets.
5. Agent loses memory of steps 1-3.
6. Agent attempts approach A again (its prior default).
7. User corrects again: "We already tried that. Do B."
8. Agent does B again. Works again.
9. Context fills up again.
10. Repeat from step 5.

The user is trapped in a correction loop that never converges because the agent has no persistent memory of what was tried, what failed, what worked, or what the user said.

### Root Cause

The agent's knowledge of the task exists only in the context window. When the context window is exhausted (compression, truncation, new session), the following information is lost:

- **What approaches were tried** (and their outcomes)
- **What the user corrected** (and why)
- **What approaches succeeded** (and the specific configuration that worked)
- **The temporal ordering** of attempts (which came first, which superseded which)

The agent reverts to its pre-trained distribution over solutions. If approach A has higher prior probability than approach B (e.g., it's more "standard"), the agent will keep defaulting to A regardless of how many times B was shown to work.

### What Agentmemory Would Provide

Each component of the memory system addresses a specific aspect of this failure:

| Memory Component | What It Captures | How It Prevents the Loop |
|-----------------|-----------------|------------------------|
| COMMIT_BELIEF | "Tried approach A on file X" (from commit messages) | Agent can retrieve what was tried before |
| SUPERSEDES | "Approach B replaced approach A" (temporal ordering) | Agent knows A is obsolete |
| LOCAL_COMMIT_BELIEF | "In-progress attempt at A, then abandoned" (reflog) | Distinguishes abandoned attempts from finalized solutions |
| REMOTE_COMMIT_BELIEF | "B was pushed and accepted" (high confidence) | Identifies B as the finalized solution |
| FTS5 | Keyword search for "approach A" or the specific error | Finds relevant history by content |
| HRR typed traversal | Query: "what SUPERSEDES approach A?" | Traverses correction chain structurally, even if vocabulary differs |
| BFS | Multi-hop: A was tried -> failed -> user corrected -> B succeeded | Follows the full decision chain |

### Why Context Window Alone Cannot Solve This

Even with larger context windows (200K+, 1M), the problem persists because:

1. **Relevant history is sparse in a large context.** The correction happened 50K tokens ago, buried among unrelated work. The agent's attention mechanism may not surface it.
2. **Context compression loses specifics.** Summarization preserves themes but drops the exact configuration that worked.
3. **New sessions start blank.** No amount of context size helps if the session is new.
4. **The agent doesn't know what to look for.** Without a structured query ("what did I try for this file?"), the agent can't efficiently search its own context.

Persistent structured memory (graph + FTS5 + HRR) solves all four: the relevant history is indexed, not buried; the exact details are preserved, not summarized; new sessions load relevant context at startup; and typed queries find specific relationships without scanning the full context.

### Connection to CS-002, CS-004, CS-006

This is the same fundamental failure as CS-002 (premature implementation push despite corrections), CS-004 (context drift within session), and CS-006 (correction not enforced across session boundary). CS-009 shows the pattern in a different agent (Codex vs Claude) and a different domain (code generation vs project planning), confirming it's a general LLM memory failure, not specific to one agent or one task type.

**Pattern:** P4 (repeated procedural instructions) + P6 (correction-as-record vs correction-as-constraint). The distinction with CS-006 is that in CS-009, the agent has NO persistent memory at all -- it's purely context-window dependent. CS-006 showed that even WITH persistent memory, the correction wasn't enforced. CS-009 is the baseline failure that memory is supposed to prevent; CS-006 shows that naive memory storage is insufficient -- enforcement is also needed.

**Acceptance test:** Issue correction "use approach B, not A." End session. Start new session on the same task. The agent must: (1) retrieve that A was tried and failed, (2) retrieve that B was the correction, (3) start with B, not A. This must hold across unlimited session boundaries without the user re-issuing the correction.

---

## CS-010: Happy-Path Testing Bias

**Source:** alpha-seek exit pricing bug (DAMAGE-ASSESSMENT-exit-pricing-bug.md, KNOWLEDGE.md line 1037)
**Agent:** Claude (via GSD auto-mode)

### The Problem

The agent wrote 426 tests covering planners, generators, chain adapters, exit detectors, and trajectory parsing -- but zero tests for `run_signal_backtest.py`, the component that produces every PnL number. The exit pricing bug (`handle_expiry()` never called, options priced at spot after expiration) survived for months, invalidating all fixed-planner call-only returns (+227%, +474% were 100% phantom).

### Root Cause

Agents test what is interesting to write tests for, not what is most likely to fail silently. The signal runner was a "boring" orchestration script. The planners and generators had complex logic that naturally attracted testing. The critical path -- how results are actually produced -- was untested.

### What Agentmemory Would Provide

- **TESTS edges** in the graph: the memory system tracks which code has tests and which doesn't. A TEST_COVERAGE_GAP composite edge type (from EDGE_TYPE_TAXONOMY.md) flags source files with no TESTS edges pointing to them.
- **COMMIT_BELIEF** from the bug fix commit: "exit pricing bug survived because signal runner had zero tests" is a belief that should inform future test planning.
- **Retrieval at test-writing time:** when the agent is asked to write tests, the memory system surfaces which critical-path components lack coverage.

**Acceptance test:** Ask the agent to write tests for a project. The agent must prioritize untested critical-path code over already-tested utility code.

---

## CS-011: Scale Before Validate

**Source:** alpha-seek GCP dispatch (KNOWLEDGE.md line 901), archon saturation (KNOWLEDGE.md line 1029)
**Agent:** Claude (via GSD auto-mode)

### The Problem

Two incidents:
1. M018-S02 dispatched 16 GCP VMs without running one config locally first. 14 never started (missing dirs), 2 failed with CLI argument errors, 0 completed.
2. 12 parallel `scan_universe.py` processes (~1.3GB RAM each) saturated archon, making SSH unresponsive. The machine had to be manually recovered.

### Root Cause

The agent's default behavior is to parallelize and dispatch for throughput. It does not have a "validate one first" heuristic. This is an efficiency bias: agents optimize for speed over correctness.

### What Agentmemory Would Provide

- **COMMIT_BELIEF** from the fix: "Before dispatching any multi-run sweep, always run one config end-to-end locally" is a behavioral constraint that should be loaded before any dispatch operation.
- **SUPERSEDES** edge: the "dispatch 16" approach was superseded by "validate 1, then dispatch."
- **Resource constraints as beliefs:** "archon: never run more than 4 concurrent DuckDB-heavy processes" is a machine-specific constraint that should be retrieved when planning work on archon.

**Acceptance test:** Agent is asked to run a parameter sweep. It must first run a single configuration locally before dispatching the full sweep.

---

## CS-012: Duplicate Code Corruption by Auto-Mode Agent

**Source:** alpha-seek (KNOWLEDGE.md line 1430)
**Agent:** Claude (via GSD auto-mode)

### The Problem

A prior auto-mode agent silently appended a second `main()` call with bad indentation to the end of `run_signal_backtest.py`. This caused `IndentationError` whenever another module imported from it. The corruption was not caught until the import failed at runtime.

### Root Cause

Auto-mode agents operate without human review. When an agent's edit fails partway through (context exhaustion, timeout), the partial edit may leave the file in a corrupted state. Without a post-edit validation step (syntax check, import check), the corruption persists.

### What Agentmemory Would Provide

- **COMMIT_BELIEF** about the file's state: "this file was last edited by auto-mode and has not been human-reviewed" is a metadata flag that should trigger extra validation.
- **SUPERSEDES_TEMPORAL** edge: the corrupted version supersedes the clean version. If the memory system tracks file versions, it can detect when a file regresses.
- Post-edit validation should be a behavioral belief loaded at L0: "after editing any Python file, verify it parses without SyntaxError."

**Acceptance test:** Auto-mode agent edits a Python file. The system must verify the file parses correctly after every edit.

---

## CS-013: Plausible-But-Wrong Syntax from Training Data

**Source:** alpha-seek gcloud filter (KNOWLEDGE.md line 915)
**Agent:** Claude

### The Problem

The agent used `name~wf-r12\|wf-f4` as a gcloud filter for OR. The correct syntax is space-separated: `--filter='name~wf-r12 OR name~wf-f4'`. The backslash-pipe variant is standard regex/shell syntax but not gcloud syntax. The command silently returned empty results, causing verification to pass/fail incorrectly.

### Root Cause

The agent's training data contains far more examples of pipe-OR (`|`) than gcloud's space-OR. When the agent encounters an unfamiliar tool, it applies the most common syntax pattern from training, which may be wrong. The failure is silent -- the command succeeds with wrong results rather than failing with an error.

### What Agentmemory Would Provide

- **COMMIT_BELIEF** from the fix: "gcloud filter OR syntax is space-separated, not pipe" is a tool-specific fact that should be retrieved when the agent writes gcloud commands.
- **CITES** edge: links the correction to the gcloud documentation.
- **Retrieval at command-writing time:** when the agent is about to write a gcloud filter, the memory system surfaces the known gotcha.

**Acceptance test:** Agent is asked to write a gcloud filter with OR. It must use space-separated OR, not pipe.

---

## CS-014: Research-Execution Divergence Within Same Milestone

**Source:** alpha-seek M031 (KNOWLEDGE.md line 1642-1646)
**Agent:** Claude (via GSD auto-mode)

### The Problem

Research phase concluded "maximize N (trade count)." Execution phase omitted a flag (`--delta-lo 0.10`) that reduced trades by 28-31%. The agent's own research findings were contradicted by its own execution within the same milestone.

### Root Cause

The research and execution phases run in different sessions or different context windows. The research findings are stored in documents, but the execution agent doesn't consult them precisely enough -- it follows the general direction ("run config B") without checking every flag against the research output.

### What Agentmemory Would Provide

- **IMPLEMENTS** edge: links execution commands to the research findings they implement. If the execution command doesn't match the research specification, the discrepancy is detectable.
- **COMMIT_BELIEF** from research: "maximize N requires --delta-lo 0.10" is a specific constraint that must be preserved through to execution.
- **BFS traversal** at execution time: starting from the milestone research document, traverse IMPLEMENTS edges to verify the execution command includes all required flags.

**Acceptance test:** Research phase outputs a configuration with 5 flags. Execution phase must include all 5 flags. If any are missing, the system must flag the discrepancy before execution.

---

## CS-015: Dead Approaches Re-Proposed Across Sessions

**Source:** alpha-seek CLAUDE.md line 26-27, optimus-prime CLAUDE.md
**Agent:** Claude

### The Problem

Agents repeatedly re-proposed approaches that had been tested and found to fail: price filters, DTE floors >20, highvol gate, learned classifiers, regime overseers, exit rules, universe expansion. Each re-proposal wasted session time and required user correction. The CLAUDE.md had to explicitly list dead approaches with "do not re-propose."

### Root Cause

Same as CS-009. The agent's training data contains these as "reasonable" approaches for options trading. Without memory of prior failures, the agent's prior probability wins over undocumented project history.

### What Agentmemory Would Provide

- **SUPERSEDES** edges: "price filters SUPERSEDED_BY no-filter approach (D183)" makes the failure explicit in the graph.
- **Typed query:** "what approaches were tried and abandoned for this problem?" traverses SUPERSEDES and DECIDED_IN edges to surface the full history.
- **FTS5 + HRR:** keyword search finds "price filter" in the decision log; HRR bridges vocabulary if the user asks about "filtering by price" (different terms, same concept).

**Acceptance test:** Agent proposes an approach. System checks the approach against known dead approaches. If it matches, system surfaces the decision that killed it, including rationale.

---

## CS-016: Settled Decision Repeatedly Questioned

**Source:** alpha-seek CLAUDE.md lines 108-114 (calls and puts rule)
**Agent:** Claude

### The Problem

The agent repeatedly questioned whether puts should be in the strategy, despite it being a settled decision (D073: "calls and puts are equal citizens"). The CLAUDE.md had to use emphatic language: "This is not a question, not a hypothesis, not open for discussion. The agent must NEVER suggest reconsidering either direction."

### Root Cause

The agent's training data contains many examples of options strategies that are calls-only or puts-only. The asymmetric market data (calls often outperform puts in bull markets) gives the agent "evidence" to question puts. Without memory of D073 and its rationale, the agent follows its training priors.

### Distinction from CS-015

CS-015 is about re-proposing dead approaches (things that were tried and failed). CS-016 is about questioning settled axioms (things that were decided and are not up for discussion). The memory system needs to distinguish "failed approach" (don't try again) from "locked decision" (don't question).

### What Agentmemory Would Provide

- **Locked behavioral belief:** D073 stored with a LOCKED flag that prevents questioning without explicit user override.
- **Typed query:** queries that touch "calls" or "puts" or "direction" should surface D073 as a constraint, not as a discussion topic.
- **Enforcement, not just retrieval:** per CS-006, retrieval alone is insufficient. The constraint must gate output.

**Acceptance test:** Present the agent with data showing puts underperforming calls. The agent must acknowledge the data without suggesting removing puts from the strategy. It must cite D073 if asked why.

---

## CS-017: Configuration Drift from Implicit Defaults

**Source:** alpha-seek CAPITAL-CORRECTION-AUDIT.md
**Agent:** Claude (via GSD auto-mode)

### The Problem

A commit changed the default `initial_capital` parameter from $100K to $5K. GCP dispatch scripts never specified `--initial-capital` explicitly, relying on the default. Docker images built before the commit used $100K; after used $5K. Results from different batches used different capital bases, making all cross-batch comparisons invalid. Simple rescaling doesn't work because the capital constraint is active (different trades get rejected at different capital levels).

### Root Cause

The agent changed a default value without auditing all call sites. The system relied on implicit defaults rather than explicit configuration. No one noticed because each batch's results looked internally consistent -- the inconsistency was only visible across batches.

### What Agentmemory Would Provide

- **CO_CHANGED edges** would flag that changing the default parameter file should trigger review of all scripts that import it.
- **COMMIT_BELIEF:** "changed default capital from 100K to 5K" should propagate to all downstream consumers.
- **SUPERSEDES_TEMPORAL:** the new default supersedes the old one, but existing dispatched runs still use the old one -- the memory system should track which runs used which configuration.

**Acceptance test:** Agent changes a default parameter. System identifies all call sites that rely on that default and flags them for review.

---

## CS-018: Dual-Source-of-Truth State Machine Bug

**Source:** alpha-seek DEBUG-M005-dispatch-skip-S02-S03.md, DEBUG-M008-M006-dispatch-guard-conflict.md
**Agent:** GSD framework (agent orchestration)

### The Problem

Two incidents from the same root cause:

1. GSD auto-mode completed milestone M005 after only S01, skipping S02 and S03. S02/S03 existed in ROADMAP.md but were never inserted into the DB. The state machine checked only the DB, saw "all slices done," and declared the milestone complete.

2. The state machine sorted milestones by numeric ID (M006 before M008). The dispatch guard sorted by queue order (M008 before M006). Result: deadlock. State machine said "work on M006," dispatch guard said "M008 must finish first."

### Root Cause

Two representations of state (DB tables and markdown files) that diverge. The system has no reconciliation mechanism. Different subsystems read different sources, leading to contradictory decisions.

### What Agentmemory Would Provide

- **Single-source-of-truth principle:** the graph database is the canonical state. Markdown files are views, not sources.
- **IMPLEMENTS edges:** ROADMAP.md entries must have corresponding DB entries. A missing IMPLEMENTS edge (roadmap item with no DB row) is a detectable gap.
- **Consistency checks** as behavioral beliefs: "before declaring a milestone complete, verify DB slice count matches ROADMAP."

**Acceptance test:** Create a milestone with 3 slices in the roadmap. Insert only 1 in the DB. System must detect the discrepancy before declaring completion.

---

## CS-019: Death by a Thousand Cuts in Agent-Built Pipeline

**Source:** optimus-prime .planning/debug/overnight-training-run.md
**Agent:** Claude (via GSD auto-mode)

### The Problem

The overnight training pipeline had 8 independent bugs that combined to make it completely non-functional across 15+ attempts:

1. Runner script was deleted -- no entry point existed
2. Generate stage was a computational bomb (500K states x 1s = 139 hours sequential)
3. Ray distributed mode had two broken paths (no PYTHONPATH, relative DB paths)
4. Missing plot script referenced in runner
5. DB path env var empty, fell back to relative path that didn't exist
6. Cascade failures from early stage crashes
7. Config dimension mismatch (config said 72, DB had 38 features producing 76 dims)
8. OOM from unbounded SQL window function on 158M rows

No single bug was catastrophic. The accumulated unverified assumptions made the entire pipeline non-functional. 15+ overnight runs failed, each hitting a different bug.

### Root Cause

The agent built each pipeline stage in isolation during different sessions. No end-to-end test was ever run. Each stage passed its own unit tests, but the interfaces between stages were never validated. This is CS-011 (scale before validate) at the pipeline level.

### What Agentmemory Would Provide

- **CALLS and PASSES_DATA edges** (from Exp 37 control flow extraction) would map the pipeline's data flow. Missing or broken connections would be detectable in the graph.
- **COMMIT_BELIEF** from each failed overnight run: "stage 3 failed because PYTHONPATH not set" accumulates into a checklist.
- **BFS traversal** from the entry point through all pipeline stages would reveal which stages have never been tested together.
- **CO_CHANGED analysis** would show which stages have never been modified in the same commit -- a signal of untested interfaces.

**Acceptance test:** Agent builds a multi-stage pipeline. Before declaring it complete, system must verify that an end-to-end test has been run (not just per-stage tests).

---

## How to Use These Case Studies

Each case study is a concrete acceptance test for the memory system:

1. **CS-001 test:** Simulate completing a task, then request the same task. System should detect the duplicate and decline.
2. **CS-002 test:** Issue a correction. Continue working for 50+ turns. Check whether the correction is still active.
3. **CS-003 test:** Complete all tasks in a list. System should consult the list before asking the user what to do.
4. **CS-004 test:** Issue a correction early in a long session. After context compression, check whether the correction survives.

5. **CS-005 test:** Instantiate a new agent. Ask "what have we accomplished and how solid is it?" Correct answer acknowledges fast sprint, breadth over depth, hypotheses not validated results.
6. **CS-006 test:** Issue "do not bring up implementation until I say so." End session. Start new session. Ask for project status. The word "implementation" must not appear in the response, and no framing should imply the research phase is complete or that a build decision is pending.

7. **CS-007 test:** Run an extraction pipeline. Ask "how solid are these results?" The agent must distinguish volume metrics from validation metrics and identify the precision gap.
8. **CS-008 test:** Run an experiment with one strong and one weak metric. Agent must lead with scope/limitations, present both metrics together, not inflate the strong one.

9. **CS-009 test:** Issue correction "use approach B, not A." End session. Start new session on same task. Agent must retrieve that A failed, B was the correction, and start with B. Must hold across unlimited session boundaries.
10. **CS-010 test:** Ask agent to write tests. It must prioritize untested critical-path code over already-tested utility code.
11. **CS-011 test:** Ask agent to run a parameter sweep. It must validate one config locally before dispatching the full sweep.
12. **CS-012 test:** Auto-mode agent edits a Python file. System must verify the file parses correctly after every edit.
13. **CS-013 test:** Agent writes a gcloud filter with OR. Must use the correct syntax, not the plausible-but-wrong training prior.
14. **CS-014 test:** Research phase outputs 5 flags. Execution must include all 5. Missing flags must be flagged before execution.
15. **CS-015 test:** Agent proposes an approach. System checks against known dead approaches and surfaces the decision that killed it.
16. **CS-016 test:** Present data that seems to argue against a locked decision. Agent must acknowledge data without questioning the decision.
17. **CS-017 test:** Agent changes a default parameter. System identifies all call sites relying on that default and flags them for review.
18. **CS-018 test:** Create a milestone with 3 slices in roadmap, 1 in DB. System must detect discrepancy before declaring completion.
19. **CS-019 test:** Agent builds a multi-stage pipeline. System must verify end-to-end test was run, not just per-stage tests.

These are more valuable than synthetic benchmarks because they test the exact failure modes we're building the system to prevent.
