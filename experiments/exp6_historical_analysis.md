# Experiment 6: Historical Analysis of Alpha-Seek as Memory Ground Truth

**Date:** 2026-04-09
**Status:** Planning
**Replaces:** Manual labeling approach in Experiments 1, 3 (partially)

## The Insight

The project-a project (~40-50 milestones, hundreds of decisions, full git history,
documentation, research spikes, and conversation-driven development) is a complete
temporal record of a real project built with and without memory systems. The evidence
for what a memory system needs to do -- and whether it's working -- is already encoded
in this history. We don't need to manufacture test data or manually label retrieval
results. We need to mine the history.

## Observable Memory Failure Patterns

These are specific, detectable patterns in the project history that indicate where
a memory system would have helped (or did help, after the prototype was introduced):

### P1: Repeated Decisions

**What it looks like:** Decision D_N is substantially similar to an earlier decision D_M,
issued because the agent (or user) forgot D_M existed.

**How to detect:**
- Compare all decision pairs (D_i, D_j where j > i) for semantic similarity
- Flag pairs where content overlap exceeds threshold AND there's no SUPERSEDES edge
- A genuine supersession (D_j explicitly replaces D_i) is not a failure -- that's intentional
- A re-decision (D_j says the same thing as D_i without referencing it) IS a failure

**What it proves:** The system forgot a prior decision. A working memory system would
have surfaced D_i when the context leading to D_j arose.

**Metric:** Count of re-decisions / total decisions. Higher = worse memory.

### P2: Repeated Research

**What it looks like:** A research spike or investigation covers ground that was already
covered in a prior spike, without building on the prior findings.

**How to detect:**
- Compare research document pairs across milestones for topic overlap
- Check whether the later research cites or references the earlier research
- If it doesn't, and covers the same ground, that's a memory failure

**What it proves:** The system forgot prior research existed. Time wasted re-deriving
known results.

**Metric:** Hours (or milestone count) of redundant research.

### P3: Avoidable Debugging Sessions

**What it looks like:** A debugging session solves a problem that was already solved
in a prior session. The same root cause, same fix, rediscovered from scratch.

**How to detect:**
- Look for error patterns that appear multiple times in the history
- Check if the fix applied later matches or is similar to the earlier fix
- If the later session doesn't reference the earlier one, that's a memory failure

**What it proves:** Procedural knowledge (how to fix X) was lost between sessions.

**Metric:** Count of re-debugged issues. Time spent on second+ occurrences.

### P4: Repeated Procedural Instructions (Runbook Violations)

**What it looks like:** The user has to tell the agent to follow the same procedure
(runbook, dispatch gate, etc.) repeatedly across sessions because the agent keeps
forgetting.

**How to detect:**
- Search conversation history / decisions for repeated instructions about the same procedure
- Identify the runbook and dispatch gate decisions
- Count how many times the user re-issued similar instructions
- Track: did the frequency decrease after the memory prototype was introduced?

**What it proves:** Procedural memory is lost between sessions. The agent can't learn
persistent rules without external memory.

**Metric:** Re-instruction frequency over time. Inflection point (if any) after memory prototype.

### P5: Dispatch Gate Failures

**What it looks like:** The agent attempts a dispatch without following the gate protocol,
causing failures that require cleanup.

**How to detect:**
- Look for error checkpoints or debugging sessions related to dispatch failures
- Cross-reference with the dispatch gate decision(s)
- Check if the gate decision was in the agent's context when the failure occurred

**What it proves:** A critical constraint was not in the agent's working memory at the
time it was needed.

**Metric:** Dispatch failures before vs after memory system. Gate violation count.

### P6: Memory Prototype Impact

**What it looks like:** After the first memory prototype was implemented, some of the
above patterns (P1-P5) decreased in frequency.

**How to detect:**
- Identify the milestone/date when the memory prototype went live
- Compute P1-P5 metrics before and after that date
- Statistical test: is the difference significant?

**What it proves (or disproves):** Whether the memory prototype actually helped.
If the failure patterns didn't decrease, the prototype wasn't solving the real problem.

## Data Sources

| Source | What It Contains | How to Access |
|--------|-----------------|---------------|
| GSD decisions database | 173+ decisions with text, rationale, timestamps, D### references | project-a.db mem_nodes table |
| GSD milestones | ~40-50 milestones with scope, outcomes, dates | project-a.db / .gsd directory |
| Git history | All commits with messages, diffs, timestamps | `git log` in project-a repo |
| Research spikes | Investigation documents with findings | .gsd/workflows/spikes/ |
| KNOWLEDGE.md | Accumulated knowledge entries | Project root or .gsd |
| DECISIONS.md | Decision log with rationale | Project root or .gsd |
| Conversation exports | Claude conversation history (if available) | Varies |
| Activity logs | GSD auto-mode activity records | .gsd/activity/ |
| Context files | Per-milestone CONTEXT.md files | .gsd/phases/ or milestone dirs |

## Methodology

### Phase A: Build the Timeline

1. Extract all events from all sources into a unified timeline:
   - Decisions (D001-D208) with timestamps, content, references
   - Milestones (M001-M036) with start/end dates, outcomes
   - Git commits with timestamps, messages, files changed
   - Knowledge entries with timestamps, content
   - Research spikes with dates, topics, findings

2. Link events temporally (what happened in what order) and causally
   (which commits were driven by which decisions, which decisions cite
   which research).

3. Map the citation graph: D### references in decisions, M### references
   in milestones, commit messages referencing decisions/milestones.

### Phase B: Detect Memory Failure Patterns

4. Run P1 detection: pairwise decision similarity, flag re-decisions
5. Run P2 detection: pairwise research overlap, flag redundant research
6. Run P3 detection: repeated error patterns across debugging sessions
7. Run P4 detection: repeated procedural instructions
8. Run P5 detection: dispatch gate violations

### Phase C: Quantify Impact

9. Compute metrics for each pattern
10. Identify the memory prototype introduction date
11. Compute before/after comparison for each metric
12. Statistical significance test

### Phase D: Derive Requirements

13. For each detected memory failure, determine: what would the memory system
    have needed to provide to prevent this failure?
14. Map failures to our requirements (REQ-001 through REQ-016)
15. Identify any failure patterns not covered by current requirements
16. Derive new requirements if needed

## What This Replaces

This approach replaces manual labeling for retrieval quality measurement.
Instead of asking "is this result relevant to this query?" we ask
"would having this belief in context have prevented this historical failure?"

The ground truth is objective: the failure happened (observable in the record)
and the belief that would have prevented it either existed or didn't. No
subjective labeling needed.

## What This Doesn't Replace

- Experiment 2/5 (Bayesian calibration simulation) -- still valid, tests the
  confidence model in isolation
- Experiment 4 (token budget vs quality) -- still needs to be run, but can use
  the historical failures as test cases instead of synthetic tasks
- The retrieval comparison (Exp 3) can be restructured: instead of blind labeling,
  test whether each method retrieves the belief that would have prevented each
  historical failure

## Phase B Results (2026-04-09)

### Raw Counts

| Pattern | Detections | Notes |
|---------|-----------|-------|
| P1: Repeated decisions | 8 candidate pairs | Jaccard >= 0.25, no citation link |
| P2: Repeated research | 1 uncited overlap | K183 corrects K191 (same OTM baseline fact, wrong value) |
| P3: Repeated debugging | 66 fix clusters (169 fix commits / 1,154 total) | DuckDB NULL crash (6 commits), put intrinsic pricing (4), sys.path (4) |
| P4: Repeated instructions | 9 clusters, 17 dispatch decisions, 4 runbook decisions | 10% of all decisions are about dispatch protocol |
| P5: Dispatch failures | 36 failure commits, 23 knowledge entries | 4.2% of timeline events are dispatch-related |

### Key Observations

1. **P3 (repeated debugging) is the dominant pattern.** 14.6% of commits are fixes, clustering into 66 groups of similar fixes. This is the strongest evidence for procedural memory value.

2. **P4+P5 (dispatch protocol) is the clearest single-topic pain point.** 76 events across decisions, commits, and knowledge entries -- all about a single procedural topic that kept being forgotten between sessions.

3. **P1 (repeated decisions) is lower than expected.** 8 candidates suggests either good citation discipline or detection threshold too high. Jaccard similarity may miss semantically similar decisions with different vocabulary.

4. **P2 (repeated research) is nearly empty.** 1 overlap. Either research was well-managed or the detection method (word overlap on short knowledge entries) isn't capturing the real pattern. The user reported repeated research as a pain point -- this discrepancy needs investigation.

### Phase B v2 Results (Enriched with OVERRIDES.md)

OVERRIDES.md contains 38 timestamped user corrections. 30 of them (79%) cluster into 6 repeated failure topics:

| Failure Topic | Overrides | Span | What Memory Needed |
|---|---|---|---|
| Dispatch gate protocol | 13 | 5 days | Always-loaded L0 procedural belief |
| Calls/puts equal citizens | 4 | 11 days | Always-loaded L0/L1 belief |
| Strict typing | 4 | 4 days | High-confidence procedural belief |
| Capital = $5K | 3 | 10 days | Always-loaded L0 factual belief |
| Agent behavior (don't elaborate) | 3 | 2 days | Always-loaded L0 procedural belief |
| GCP primary compute | 3 | 7 days | Factual belief |

March 27 was the worst day: 10 overrides. The user was correcting the agent ~2.6 times/day during the dispatch gate cluster.

This is the strongest evidence we have: **79% of user overrides are re-statements of things already decided.** A memory system that kept these 6 beliefs in always-loaded context (L0/L1) would have prevented 30 of 38 overrides.

### v1 vs v2 comparison

| Pattern | v1 (Jaccard on decisions) | v2 (OVERRIDES.md) |
|---------|--------------------------|-------------------|
| P1 repeated decisions | 8 candidates | 6 clusters with 30 overrides |
| Quality | Coarse, many false matches | Direct evidence from user corrections |
| Signal | Inferred (similar text = maybe repeated) | Observed (user explicitly re-stated) |

v2 is dramatically better because overrides are ground truth -- the user explicitly said "I already told you this."

### Limitations of Current Detection

- **Zero-LLM similarity (Jaccard) is coarse.** It catches lexical overlap but misses semantic similarity. "Use PostgreSQL for the backend" and "The database should be Postgres" have low Jaccard but high semantic overlap.
- **Duplicate commits from shared repo history inflate P3/P5 counts.** Both project-a and project-a-test share early commits. Need to deduplicate.
- **P2 may undercount because research findings are often expressed very differently.** Two investigations of the same question may produce knowledge entries with completely different wording.
- **P4 detection depends on keyword matching** ("must", "always", "never", etc.). Procedural instructions that don't use these words are missed.

## Phase C Results: Before/After Analysis (2026-04-09)

### Override Rate Over Time

```
Date         Overrides  3-day avg  Notable
2026-03-26     5          5.0
2026-03-27     9          7.0      <-- D089/D097/D106 enforcement rules added (peak frustration day)
2026-03-28     1          5.0      <-- pyright pre-commit hook
2026-03-29     3          4.3
2026-03-30     8          4.0      <-- D137 dispatch runbook created
2026-03-31     1          4.0
2026-04-01     0          3.0
2026-04-02     3          1.3      <-- D194/D195 research checklist
2026-04-03     0          1.0
2026-04-04     0          1.0
2026-04-05     0          0.0
2026-04-06     2          0.7
```

### Key Findings

**Override rate dropped 49% after enforcement mechanisms were added to CLAUDE.md (Mar 27):**
- Before (Mar 24-27): 3.50 overrides/day
- After (Mar 28-Apr 6): 1.80 overrides/day

**Dispatch gate overrides dropped 67% after the runbook was created (Mar 30):**
- Before runbook: 1.50 dispatch overrides/day
- After runbook: 0.50 dispatch overrides/day

**Activity level was also different** (115 commits/day before, 69/day after), so some of the override reduction may be due to less activity rather than better memory. However, the dispatch gate improvement is disproportionate to the activity reduction (67% vs 40%), suggesting the runbook genuinely helped.

### The Critical Insight

The enforcement mechanisms that worked (CLAUDE.md rules, dispatch runbook, pre-commit hooks) are all forms of persistent memory:
- CLAUDE.md is loaded into every session's context (always-loaded L0)
- The dispatch runbook is a procedural belief document (always-available L1)
- Pre-commit hooks are automated enforcement (system-level, not memory-level)

**The user was manually building a memory system** by adding rules to context files. Our project automates this: instead of the user writing CLAUDE.md rules after repeated frustration, the system should learn from the first override and promote the belief to always-loaded context automatically.

### What Would LLM-Enriched Detection Find?

An LLM could:
- Detect semantic similarity beyond word overlap (would likely increase P1 and P2 counts)
- Classify the intent of commits (was this a re-fix or a new fix?)
- Identify when the same question was asked in different sessions
- Parse conversation history for repeated user instructions

This is itself a test case for our zero-LLM vs LLM-enriched architecture question.

---

## Connection to the General Memory System

The patterns detected in project-a generalize:

| Alpha-Seek Pattern | General Pattern | Memory System Feature |
|--------------------|-----------------|----------------------|
| Repeated decisions | Context drift | Cross-session belief persistence (REQ-001) |
| Repeated research | Knowledge loss | Observation/belief extraction (REQ-014) |
| Re-debugging | Procedural memory loss | Test feedback loop (beliefs about what works) |
| Runbook violations | Constraint forgetting | High-confidence procedural beliefs |
| Dispatch gate failures | Critical constraint loss | L0/L1 always-loaded context |
| Post-prototype improvement | Memory system works | Validates the entire approach |

The project-a history is not just test data for project-a. It's a case study
for the general problem of agentic memory. Every pattern we find here is a pattern
that occurs in any long-running project with an AI agent.
