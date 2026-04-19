# Reframe: The Core Metric Is Correction Burden, Not Retrieval Coverage

**Date:** 2026-04-10
**Status:** Active reframe of research direction
**Triggered by:** Entity detector false positives ("Apple Home" classified as person) exposing a calibration gap in the research

---

## 1. The Distinction

The human does not need help remembering things. The human knows their project, their decisions, their context. Human memory is bad in absolute terms but infinitely better than LLM memory for the human's own work.

What the human needs is an LLM that:
- Does not forget what it was told
- Does not re-ask settled questions
- Does not confidently present wrong information
- Does not create new work for the human in the form of corrections

**The memory system exists to reduce the human's correction burden, not to augment the human's memory.**

Every case study (CS-001 through CS-021) documents the same pattern: the LLM did something wrong, the human had to correct it. The memory system's job is to make those corrections stick and prevent them from recurring.

---

## 2. The Gap in Current Research

The research has been calibrated toward **retrieval coverage**: can the system find the right things?

| Experiment | Metric Measured | What It Actually Tells Us |
|-----------|----------------|--------------------------|
| Exp 9/39 | Coverage (13/13 decisions found) | System can retrieve relevant content |
| Exp 40 | D157 found via HRR | System can bridge vocabulary gaps |
| Exp 45 | Graph connectivity (LCC%) | Graph structure is connected |
| Exp 45b | Precision@5 vs raw FTS5 | Sentence-level retrieval works |
| Exp 45c | HRR added value (20%) | Entity edges enable structural retrieval |

None of these measure: **how many wrong things did the system store that the human will have to fix?**

The entity detector (Exp 45c) found 364 "person" entities in project-d. Most are false positives: "Apple Home", "Smart Home", "Dev Environment", "Home Assistant", "Shelly Plug." Each false positive is a wrong belief in the graph. If any of these gets surfaced to the user as "people involved in the project-d project," the user has to correct it. The memory system just created work instead of reducing it.

### 2.1 The Asymmetry

| Error Type | Impact on Human | Priority |
|-----------|----------------|----------|
| **False negative** (missed entity) | Invisible. Human doesn't know what the system missed. No correction needed. | Low |
| **False positive** (wrong entity) | Active misinformation. Human sees wrong output, must correct it. System created work. | **High** |
| **Missed retrieval** (relevant belief not found) | Human may not notice; at worst, LLM makes a suboptimal decision. | Medium |
| **Wrong retrieval** (irrelevant belief presented as relevant) | Human sees wrong context, must mentally filter or correct. | **High** |

The research has been optimizing for recall (reduce false negatives) when it should be optimizing for precision (reduce false positives). A missed entity is invisible. A wrong entity is a correction.

### 2.2 Where This Matters Most

1. **Entity detection** (Exp 45c): 364 "person" entities on project-d, majority are false positives. Each is a potential future correction.
2. **Belief extraction** (Exp 1): Correction detection V2 at 92% accuracy means 8% of detected "corrections" are false positives -- beliefs the system would lock that shouldn't be locked.
3. **Edge creation** (T0): CO_CHANGED edges at w>=3 have ~100% precision against commit intent. CITES edges at 100% precision. Good. But auto-classified AGENT_CONSTRAINT edges from directive scan depend on pattern matching that could misfire.
4. **Source priors** (Exp 38): If a belief is misclassified as user_stated (Beta(9,1)) when it's actually agent_inferred, it gets locked with false confidence and resists correction. The prior itself becomes the source of correction burden.

---

## 3. The Correct Metric

**Correction burden:** the number of times the human has to correct the system per session, per project, across sessions.

Sub-metrics:

| Metric | Definition | Target |
|--------|-----------|--------|
| **False belief rate** | Fraction of stored beliefs that are factually wrong | < 1% |
| **Misclassification rate** | Fraction of beliefs with wrong type/scope/prior | < 5% |
| **Repeat correction rate** | Fraction of corrections the human has to make more than once | 0% (REQ-019) |
| **Novel correction rate** | Corrections per session for new (not previously corrected) errors | Decreasing over time |
| **Confidence-error alignment** | Do high-confidence beliefs have lower error rates than low-confidence ones? | Monotonically decreasing |

The system is healthy when:
- High-confidence beliefs (Beta(9,1)) are almost never wrong
- Low-confidence beliefs (Beta(1,1)) are flagged as uncertain
- Corrections stick permanently (REQ-019, REQ-020)
- The novel correction rate decreases session over session

---

## 4. What This Changes

### 4.1 Entity Detection: Precision Over Recall

The current detector finds everything that looks like a capitalized bigram. This maximizes recall but floods the graph with false positives.

**New approach:** Only store entity-based edges that meet a confidence threshold:
- Entities appearing >= 5 times in corpus: likely real (frequency as confidence proxy)
- Entities appearing 2-4 times: store with agent_inferred prior Beta(1,1), flag for verification
- Entities appearing 1 time: do not store (single mention is insufficient evidence)

For "person" entities specifically: filter against known non-person patterns:
- Contains a product/service keyword (Home, Assistant, Plug, Environment, Server)
- Both words appear individually as common nouns in the corpus
- Matches a known project-specific concept (detected from headings, README)

### 4.2 Extraction Pipeline: Precision Gate

Every extractor should report its expected false positive rate. Extractors with > 5% FP rate should either:
1. Reduce their FP rate before storing beliefs
2. Store beliefs with agent_inferred priors (low confidence, flaggable)
3. Queue uncertain beliefs for interview verification

| Extractor | Expected FP Rate | Action |
|-----------|-----------------|--------|
| CITES (regex D###) | ~0% (T0.7: 100% precision) | Store with high confidence |
| CO_CHANGED (w>=3) | ~0% against commit intent | Store with high confidence |
| COMMIT_BELIEF (git log) | ~0% (verbatim commit messages) | Store as observations |
| AST CALLS (resolved) | ~0% (syntactically verifiable) | Store with high confidence |
| AST CALLS (unresolved) | Unknown | Do not store (resolution failed) |
| Directive scan (patterns) | ~8% (from V2 accuracy 92%) | Store with medium confidence, flag |
| Entity detection (names) | **~50%+ on project-d** | Must filter or flag everything |

### 4.3 Interview Bursts: Targeted at High-FP Extractors

The interview protocol should prioritize questions about extractions with the highest false positive risk. For project-d onboarding, the first interview burst should be:

> "I detected these as key entities in your project. Which are right?"
> - [x] server-b (hostname)
> - [x] server-a (hostname)
> - [ ] Apple Home (person?)
> - [ ] Smart Home (person?)
> - [x] server-c (hostname)

3 seconds of human time, prevents 2 false beliefs from entering the graph. That's the correct ROI for human attention: catch the system's mistakes before they persist.

### 4.4 Research Experiments: Measure Correction Burden

Every future experiment should include a correction burden metric alongside retrieval metrics. Specifically:

For each extracted belief/edge, estimate: "would a human looking at this need to correct it?" This can be approximated by:
- Manual review of a random sample (gold standard but expensive)
- Cross-validation against other extraction methods (if two independent extractors agree, likely correct)
- Comparison against known ground truth where available (project-a D### decisions are human-authored)

---

## 5. Relationship to Existing Architecture

This reframe does not change the architecture. It changes what we measure and what we optimize for.

| Component | Current Calibration | Correct Calibration |
|-----------|-------------------|-------------------|
| Extractors | Maximize coverage (find everything) | Maximize precision (don't store wrong things) |
| Source priors | Reflect source reliability | Reflect source reliability AND extraction confidence |
| Feedback loop | Correct exceptions over time | Correct exceptions AND measure correction rate |
| Interview bursts | Ask about uncertainty | Ask about high-FP-risk extractions first |
| HRR retrieval | Bridge vocabulary gaps | Bridge gaps WITHOUT surfacing wrong neighbors |

---

## 6. Implications for the Case Study Hierarchy

CS-021 (design-as-research) identified a pattern where the agent produces plausible-looking output without empirical validation. This reframe identifies a related pattern:

**P7: Retrieval-optimized research that ignores the user's actual problem.**

The user's problem is correction burden. The research measures retrieval coverage. These are related but not the same. High retrieval coverage with high false positive rate increases correction burden. The metric should be downstream of the user's experience, not upstream.

This connects to CS-005 (maturity inflation) and CS-007 (volume as validation): reporting "13/13 coverage" sounds impressive but doesn't answer "will the user have to fix things?"

---

## 7. Plain English: What the Correction Burden Metric Means

For every belief/node the extractor pipeline stores in the graph, is it factually correct or is it junk the human would have to fix?

**The two problems found and fixed (Exp 45d):**

1. **Markdown tables stored as "sentences."** Lines like `| File | Status | ...` were parsed as belief nodes. That's not a belief -- it's a table fragment. Nobody wants that retrieved as project context. Fix: skip lines starting with `|` or `---`.

2. **"Apple Home", "Smart Home", "Dev Environment" classified as people.** The entity detector looked for capitalized two-word phrases and assumed person names. On project-d (infrastructure project), this produced 1,196 false edges connecting unrelated sentences through fake "person" links. If the system told the user "Apple Home is a person involved in project-d," the user would have to correct it. Fix: filter out bigrams containing words like "home", "server", "environment", "assistant".

**Before fixes:** project-d stored 17.5 wrong things per session's worth of retrievals. Roughly every third query would surface something incorrect.

**After fixes:** All three projects store < 0.65 wrong things per session. Less than 1 correction per session on average.

**What "1.2% FP rate" means practically:** Out of every ~80 beliefs the system stores, ~1 is junk (a too-short sentence fragment like "Server-A is overflow only." -- 23 characters). That fragment is technically true, just not very useful. It's not misinformation the user would need to actively correct. Noise, not poison.

**What this doesn't yet measure:** Whether the *retrieved* context actually helps the LLM make better decisions. The current metric says "we're not storing garbage." It doesn't say "the stuff we store actually reduces how often the user has to correct the LLM." That requires a running system with real sessions (GAP 5 in TODO.md).

---

## 8. References

- CASE_STUDIES.md: CS-001 through CS-021 (correction patterns)
- REQUIREMENTS.md: REQ-019 (single-correction learning), REQ-020 (locked beliefs)
- FEEDBACK_LOOP_SCALING_RESEARCH.md: source priors (Exp 38)
- ONBOARDING_RESEARCH.md: entity detection results (Exp 45c)
- PLAN.md: retrieval confusion matrix (Section: Retrieval Confusion Matrix)
