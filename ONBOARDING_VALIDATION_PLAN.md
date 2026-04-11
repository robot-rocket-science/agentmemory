# Onboarding Validation Plan: LLM Classification + Time Dimension

**Date:** 2026-04-11
**Purpose:** Validate that the onboarding pipeline with LLM classification produces higher-quality beliefs than offline classification, and that git commit timestamps flow correctly into temporal scoring.

---

## Selected Repos (4, representative spread)

| Repo | Commits | Files | Languages | Archetype |
|---|---|---|---|---|
| debserver | 538 | 189 | Python, YAML, MD | Large personal project with T0 data |
| email-secretary | 101 | 109 | Python, MD | Medium project with directives |
| bigtime | 14 | 15 | MD, JSON | Tiny doc-heavy project |
| mud_rust | 5 | 16 | Rust, MD | Minimal cross-language project |

## What We're Testing

### H1: LLM classification produces higher signal-to-noise than offline
- **Method:** Onboard each repo twice: once with `use_llm=False`, once with `use_llm=True`
- **Measure:** Sample 30 beliefs from each, manually assess: correct type? should persist? is it noise?
- **Success:** LLM accuracy > 80%, offline accuracy < 50% (matching Exp 50 findings)

### H2: Git commit dates flow through to belief created_at
- **Method:** Query beliefs with source_type containing "git", check created_at matches actual commit date
- **Measure:** 100% of commit-sourced beliefs have ISO 8601 dates, not "now()"
- **Success:** All commit beliefs have historical dates, newest belief date < today

### H3: Temporal decay scoring respects time ordering
- **Method:** Search for beliefs across different ages, verify older factual beliefs score lower than newer ones (corrections/requirements should be immune)
- **Measure:** Decay factor for 30-day-old factual belief < decay factor for 1-day-old factual belief
- **Success:** Monotonic decay for non-locked types, constant 1.0 for locked/correction/requirement

### H4: Small projects don't over-generate
- **Method:** Compare belief count for bigtime (14 commits) vs debserver (538 commits)
- **Measure:** bigtime should produce proportionally fewer beliefs, not a similar volume of noise
- **Success:** bigtime < 200 beliefs, debserver < 5000 beliefs (proportional to content, not inflated by noise)

## Execution Steps

### Phase 1: Quick validation scripts (local, no API cost)
1. Run scanner on each repo, check node counts and date extraction
2. Verify commit dates are ISO 8601 and in the past
3. Dry-run ingest on 10 sentences from debserver with offline classifier
4. Check that created_at survives through to the beliefs table

### Phase 2: Offline onboarding baseline
1. Onboard all 4 repos with `use_llm=False` into isolated test DBs
2. Record: node counts, belief counts, edge counts, timing
3. Sample 30 beliefs per repo, tag quality (correct/noise/misclassified)

### Phase 3: LLM onboarding comparison
1. Onboard all 4 repos with `use_llm=True` into separate test DBs
2. Record same metrics + Haiku token usage and cost
3. Sample same 30 belief positions, compare classification quality
4. Run temporal scoring on both DBs, compare decay correctness

### Phase 4: Verification
1. Compare offline vs LLM belief quality side-by-side
2. Verify H1-H4
3. Compare debserver results against T0 extracted data on archon
4. Document findings

## Infrastructure

- **Run locally on lorax** (has ANTHROPIC_API_KEY, agentmemory installed)
- **Isolated test DBs** via AGENTMEMORY_DB env var (don't pollute production DB)
- **Compare against archon T0 data** via SSH for debserver validation
