# Core Belief Ranking Design (2026-04-11)

## Problem
After bulk onboarding, ~15k beliefs all have confidence 0.9. `/mem:core` needs a ranking that differentiates "most important" from noise.

## Research Summary
4 parallel research agents + data analysis + wonder query. Key findings:

### Available signals (flat DB, post-onboard)
- **Type**: 4 types with meaningful quality correlation. Requirements avg 90 chars, factual avg 60 chars. Corrections are user-vetted overrides.
- **Source**: user_corrected (17%) are deliberate human overrides. agent_inferred (83%) are raw observations.
- **Content length**: 16% are <30 char fragments (noise), 1% are 200+ chars (core). Strong quality proxy.
- **Timestamps**: flat (all same minute). Recoverable from git dates (Tier 2 work).
- **Retrieval frequency**: no data yet. Needs live usage (Tier 3 work).
- **Evidence count**: flat at 1. No variance.

### What doesn't work yet
- Confidence: flat at 0.9 for 5 of 7 types
- Evidence: every belief has exactly 1 evidence link
- Edges: only 0.6% of beliefs participate in edges
- Timestamps: all bulk-ingested in the same minute

## Design: 3-tier composite scoring

### Tier 1: Implement now (works on flat data)
Pure retrieval-time scoring. No schema or storage changes. Fully reversible.

```
core_score = type_weight * source_weight * length_multiplier
```

#### Type weights
Derived from Exp 61 persist rates and Exp 38 source-stratified priors.

| Type | Weight | Rationale |
|------|--------|-----------|
| requirement | 2.5 | Hard constraints, highest structure (38% more commas) |
| correction | 2.0 | User-vetted overrides, deliberate |
| preference | 1.8 | User preferences, strong signal |
| factual | 1.0 | Broadest category, high noise:signal |

#### Source weights
Derived from Exp 38 (21x ranking improvement with source stratification).

| Source | Weight | Rationale |
|--------|--------|-----------|
| user_corrected | 1.5 | Deliberate human override |
| user_stated | 1.3 | Direct user statement |
| document_recent | 1.0 | Baseline |
| document_old | 0.8 | Stale |
| agent_inferred | 1.0 | Baseline (bulk of corpus) |

#### Length multipliers
Derived from content analysis: fragments are noise, dense beliefs are core.

| Length | Multiplier | Corpus % |
|--------|------------|----------|
| < 30 chars | 0.5 | 16% |
| 30-100 chars | 1.0 | 69% |
| 100-200 chars | 1.3 | 14% |
| 200+ chars | 1.6 | 1% |

#### Expected score range
- Worst: short factual agent-inferred fragment: 1.0 * 1.0 * 0.5 = 0.5
- Best: long user-corrected requirement: 2.5 * 1.5 * 1.6 = 6.0
- 12x spread (vs current flat 0.9)

### Tier 2: Source date passthrough (next)
Scanner captures git commit dates in Node.date but ingestion discards them.
Fix: pass node.date through to belief.created_at during onboarding.
Existing decay mechanism (Exp 58c, validated) immediately activates.
Implementation: 3-4 parameter passthrough changes.

### Tier 3: Retrieval frequency (needs live usage)
tests table already exists for outcome tracking.
Add retrieval_count view, integrate frequency_boost into scoring.
Strongest signal but requires the system to be used first.

## Validation
After implementation, verify:
1. `/mem:core 10` returns meaningfully different beliefs than before
2. Requirements and corrections rank above generic factual fragments
3. Short fragments (<30 chars) are deprioritized
4. No locked beliefs are affected (they bypass core scoring)
