# Experiment 53: Vocabulary Gap Prevalence Across Projects

**Date:** 2026-04-10
**Status:** Planning
**Depends on:** Exp 39 (vocabulary gap definition), Exp 40 (HRR bridge proof), Exp 49 (onboarding extractors)
**Question:** What fraction of important beliefs are unreachable by text methods across different project archetypes?

---

## 1. Motivation

D157 is the only proven vocabulary-gap case in our ground truth. HRR recovered it where 6 text methods, SimHash, grep, and FTS5 all failed. But 1/13 = 7.7% is a single data point from a single project. Before building HRR into the MVP, we need to know: is the vocabulary gap a rare edge case or a pervasive pattern?

If the prevalence is < 3% across projects, HRR is a nice-to-have optimization. If it's > 10%, HRR is load-bearing infrastructure.

---

## 2. What Counts as a Vocabulary Gap

A belief has a vocabulary gap when:
1. A realistic query SHOULD retrieve it (the belief is relevant to the query's intent)
2. No text method CAN retrieve it (zero shared content words between any reasonable query formulation and the belief text)

The gap exists between the **intent vocabulary** (how a user or agent would describe the need) and the **belief vocabulary** (how the belief is stated).

### Categories of vocabulary gaps (from analysis):

| Category | Example | Query | Belief |
|----------|---------|-------|--------|
| Tool/command ban | D157 | "run in background" | "async_bash BANNED" |
| Domain jargon | D097 | "evaluate performance" | "walk-forward expanding window" |
| Cross-domain constraint | GCP rule | "train a model" | "GCP only, no AWS" |
| Implicit behavioral rule | Reporting | "here's what I found" | "always report sample size" |
| Emphatic prohibition | D100 | "rebalance calls/puts?" | "STOP BRINGING IT UP" |

---

## 3. Methodology

For each project:

### Step 1: Extract behavioral/directive beliefs
Use the directive scanner from Exp 49 (always/never/banned/must not/don't patterns) plus CLAUDE.md rules if present. These are the beliefs most likely to have vocabulary gaps because they state rules in domain-specific terms that queries won't use.

### Step 2: Generate realistic queries
For each directive belief, generate 3 query formulations that describe the SITUATION where the belief should be retrieved, NOT the belief's own vocabulary. Example:
- Belief: "Never use async_bash" 
- Queries: "run long backtest in background", "execute overnight job", "parallel command execution"

This must be done carefully -- the queries should represent what an agent would actually encounter, not what a human who already knows the belief would type.

### Step 3: Test text retrievability
Run FTS5 (porter stemming, OR query) with each query formulation against the project's full belief/sentence corpus. If ANY of the 3 queries retrieves the target belief in top-30, it's text-reachable. If NONE do, it has a vocabulary gap.

### Step 4: Classify the gap type
For each vocabulary-gap belief, classify which category it falls into (tool ban, domain jargon, cross-domain constraint, implicit rule, emphatic prohibition).

### Step 5: Assess HRR bridgeability
For each vocabulary-gap belief, check: does it share a typed edge (AGENT_CONSTRAINT, CITES, DECIDED_IN) with a text-reachable belief? If yes, HRR can bridge it. If no, even HRR can't help -- the belief is structurally isolated.

---

## 4. Target Projects

| Project | Path | Archetype | Expected Gap Rate |
|---------|------|-----------|-------------------|
| alpha-seek | ~/projects/alpha-seek | Quant trading, rich decisions | Known: 7.7% (1/13). Retest with full directive set. |
| optimus-prime | ~/projects/optimus-prime | GSD-managed, process rules | High -- many implicit process constraints |
| debserver | ~/projects/debserver | Infrastructure, service rules | Medium -- service names vs functions |
| jose-bully | ~/projects/jose-bully | Legal case, narrative docs | Unknown -- legal terminology may create gaps |
| code-monkey | ~/projects/code-monkey | Dev tooling | Medium -- tool preferences vs task descriptions |

---

## 5. Hypotheses

**H1:** Vocabulary gap prevalence is >= 5% of directive beliefs across all 5 projects.

**H2:** Tool/command bans and domain jargon are the most common gap categories (>= 50% of gaps).

**H3:** >= 80% of vocabulary-gap beliefs are HRR-bridgeable (share a typed edge with a text-reachable belief).

**H4:** Projects with richer decision documentation (alpha-seek, optimus-prime) have lower gap rates than code-heavy/doc-light projects (debserver, code-monkey), because documentation provides more vocabulary overlap.

**Null:** Vocabulary gap prevalence is < 3% and HRR adds negligible value.

---

## 6. Requirements Traceability

| Requirement | How This Experiment Addresses It |
|-------------|--------------------------------|
| REQ-027 (zero-repeat directive) | Measures how many directives are text-unreachable -- each is a potential repeat correction |
| REQ-007 (retrieval precision >= 50%) | Vocabulary gaps directly reduce recall, which bounds achievable precision |
| REQ-019 (single-correction learning) | A locked directive with a vocabulary gap is a correction that can't be surfaced |

---

## 7. Success Criteria

| Criterion | Threshold |
|-----------|-----------|
| Minimum directives tested per project | >= 10 |
| Query formulations per directive | 3 (situation-based, not keyword-based) |
| Gap classification complete | Every gap categorized |
| HRR bridgeability assessed | Every gap checked for typed edge connectivity |
