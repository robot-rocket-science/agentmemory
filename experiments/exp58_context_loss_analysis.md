# Experiment 58: Context Loss Analysis in Real Conversation Data

**Date:** 2026-04-10
**Status:** Planned
**Depends on:** Conversation logger (C1a)

---

## Research Question

Where does information actually get lost in conversation turns, and what kinds of information would have been worth remembering?

## Background

We've been building extraction classifiers (Exp 56, 57) without first understanding what's in the data. Before deciding how to classify statements or what priors to assign, we need to know:

1. What kinds of information appear in conversation turns?
2. What information is decision-grade (would change agent behavior if remembered)?
3. How much of each conversation is signal vs noise?
4. Do user and assistant messages carry different kinds of signal?
5. When information gets re-stated across sessions, what form did it take the first time?

## Hypotheses

**H1 (Signal density):** Less than 20% of conversation sentences contain information worth persisting across sessions. Most conversation text is coordination ("ok proceed"), meta-commentary ("let me check"), or ephemeral reasoning that's only useful in the moment.

**H2 (Source asymmetry):** User messages and assistant messages carry different kinds of signal. User messages carry decisions and preferences. Assistant messages carry analysis and derived conclusions. Neither source is uniformly valuable or uniformly noise.

**H3 (Ambiguity is the hard problem):** The majority of persist-worthy information is stated ambiguously -- casual phrasing, implicit corrections, preferences disguised as observations. Clear keyword-matchable statements ("I decided to use X") are the minority.

**H4 (Re-statement as ground truth):** When a user re-states something across sessions, the first statement is persist-worthy by definition. Re-statements are direct evidence of context loss -- the user had to repeat themselves because the system forgot.

## Method

### Step 1: Manual annotation of conversation data

Take every sentence from the conversation log. For each sentence, a human annotator (you) labels:

**a) Persist-worthiness (binary):**
- PERSIST: This information would be useful in a future session
- EPHEMERAL: This is only useful in the current turn/session

**b) Information type (one of):**
- DECISION: A choice was made ("use PostgreSQL", "reject this approach")
- PREFERENCE: A stated like/dislike/style ("I prefer terse output")
- CORRECTION: Fixing a prior statement or the assistant's behavior
- FACT: A stated truth about the project/world ("the budget is $5K")
- REQUIREMENT: A constraint or rule ("never commit data files")
- ASSUMPTION: Something taken as true without evidence
- ANALYSIS: Reasoning or explanation ("because X, therefore Y")
- QUESTION: Asking for information or opinion
- COORDINATION: Control flow ("ok", "proceed", "status?")
- META: About the conversation itself ("let me check", "here's what I found")

**c) Statement clarity (one of):**
- EXPLICIT: Clear, keyword-matchable ("I decided to use X")
- IMPLICIT: Meaning is clear to a human but not pattern-matchable ("don't give away the holography thing")
- AMBIGUOUS: Could be persist-worthy or not, depends on context

### Step 2: Compute distributions

From the annotations:
- What % of sentences are persist-worthy?
- What's the type distribution of persist-worthy sentences?
- What's the clarity distribution of persist-worthy sentences?
- How do these differ between user and assistant messages?

### Step 3: Identify extraction gaps

Compare what a regex-based classifier would catch vs what the human annotator marked:
- False negatives: persist-worthy sentences the classifier misses
- False positives: ephemeral sentences the classifier flags
- What patterns would close the gap?

### Step 4: Cross-session repetition analysis

If we have multi-session data:
- Find statements that appear in similar form across sessions
- The first occurrence is ground truth for "should have been persisted"
- What type/clarity were these first occurrences?

## Decision Criteria

The annotations directly inform the prior model:
- Types that are almost always persist-worthy get high priors
- Types that are almost always ephemeral get filtered out entirely
- The clarity distribution tells us how much of the problem is solvable by regex vs needs something smarter

## Output

- Annotated dataset: experiments/exp58_annotated_turns.json
- Distribution analysis: experiments/exp58_results.md
- Revised prior model based on empirical type distributions
