# F3: Schema Changes for Epistemic Integrity (REQ-023 to REQ-026)

**Date:** 2026-04-09

## The Problem

CS-005 showed that a new agent reading project status forms an inflated picture of maturity. "20+ completed research tasks" sounds extensive when it was 2-3 hours of work. The system stores WHAT was done but not HOW RIGOROUSLY.

## Current Schema (from PLAN.md)

```sql
CREATE TABLE beliefs (
    id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    content TEXT NOT NULL,
    belief_type TEXT NOT NULL,         -- factual, preference, relational, procedural, causal
    alpha REAL NOT NULL DEFAULT 0.5,
    beta_param REAL NOT NULL DEFAULT 0.5,
    confidence REAL GENERATED ALWAYS AS (alpha / (alpha + beta_param)) STORED,
    source_type TEXT NOT NULL,         -- user_stated, user_corrected, document_recent, etc.
    valid_from TEXT,
    valid_to TEXT,
    superseded_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (superseded_by) REFERENCES beliefs(id)
);
```

## Proposed Additions

### For REQ-023 (Provenance Metadata)

```sql
ALTER TABLE beliefs ADD COLUMN method TEXT;
  -- 'reasoning'       : derived from logic/discussion, no empirical test
  -- 'literature'      : summarized from a paper or external source  
  -- 'simulated'       : tested on synthetic or self-generated data
  -- 'empirical_same'  : tested on real data, same dataset as development
  -- 'empirical_holdout' : tested on holdout data
  -- 'replicated'      : independently replicated by different method/agent

ALTER TABLE beliefs ADD COLUMN sample_size INTEGER;
  -- NULL for reasoning/literature
  -- number of test cases for empirical methods

ALTER TABLE beliefs ADD COLUMN data_source TEXT;
  -- 'alpha-seek-overrides' or 'simulation-200-beliefs' etc.

ALTER TABLE beliefs ADD COLUMN independently_validated BOOLEAN DEFAULT FALSE;
```

### For REQ-024 (Session Velocity)

Already have `sessions` table. Add:

```sql
ALTER TABLE sessions ADD COLUMN items_completed INTEGER DEFAULT 0;
ALTER TABLE sessions ADD COLUMN elapsed_seconds REAL;
  -- velocity = items_completed / (elapsed_seconds / 3600)
```

### For REQ-025 (Rigor Tier)

```sql
ALTER TABLE beliefs ADD COLUMN rigor_tier TEXT DEFAULT 'hypothesis';
  -- 'hypothesis'        : reasoning/literature only, not empirically tested
  -- 'simulated'         : tested on synthetic data
  -- 'empirically_tested': tested on real data (same dataset)
  -- 'validated'         : tested on holdout/multiple sources/independently replicated
```

This overlaps with `method` -- the difference is that `method` describes HOW it was produced, while `rigor_tier` is a JUDGMENT about how much to trust it. A belief produced by 'simulated' method could be at 'validated' rigor if the simulation was comprehensive and the results were confirmed on real data.

**Decision:** Keep both. `method` is factual (how it was made). `rigor_tier` is epistemic (how much to trust it). They correlate but aren't identical.

### For REQ-026 (Calibrated Status Reporting)

This isn't a schema change -- it's a query pattern. The `status` MCP tool should:

```python
def generate_status():
    total = count(beliefs)
    by_rigor = group_by(beliefs, rigor_tier)
    
    recent_session = most_recent(sessions)
    velocity = recent_session.items_completed / (recent_session.elapsed_seconds / 3600)
    
    # Calibrated framing
    if by_rigor['hypothesis'] / total > 0.5:
        framing = "early-stage -- majority of findings are hypotheses"
    elif by_rigor['validated'] / total > 0.3:
        framing = "maturing -- significant portion independently validated"
    else:
        framing = "in progress -- mix of tested and untested findings"
    
    return {
        "total_beliefs": total,
        "rigor_distribution": by_rigor,
        "velocity": velocity,
        "framing": framing,
        "caveats": generate_caveats(by_rigor, velocity),
    }
```

## How Rigor Tier Interacts with Bayesian Confidence

The question from OPEN_QUESTIONS.md: "A hypothesis at 0.9 confidence vs a validated finding at 0.6 -- which ranks higher?"

**Proposal:** Rigor tier acts as a multiplier on confidence for status reporting, NOT for retrieval ranking.

For retrieval: Thompson sampling uses alpha/beta_param only. The system retrieves what's relevant regardless of rigor tier.

For status reporting: `effective_confidence = confidence * rigor_weight`
- hypothesis: 0.3
- simulated: 0.5
- empirically_tested: 0.8
- validated: 1.0

So a hypothesis at 0.9 confidence has effective 0.27 for status purposes. A validated finding at 0.6 has effective 0.60. The validated finding wins in status reports even though its raw confidence is lower.

This means: "we found X (confidence 0.9, hypothesis-tier)" is reported as "we suspect X" while "we found Y (confidence 0.6, validated-tier)" is reported as "evidence suggests Y."

## Can Rigor Tier Be Computed Automatically?

Partially:

| Signal | Inferred Rigor |
|--------|---------------|
| Belief created from observation with source_type='document' | 'literature' at best |
| Belief created from agent reasoning with no evidence links | 'hypothesis' |
| Belief has test records with outcome='used' from simulation experiment | 'simulated' |
| Belief has test records from real project data | 'empirically_tested' |
| Belief has test records from multiple data sources | 'validated' (candidate) |
| Belief has independently_validated=true | 'validated' |

The system can auto-assign based on evidence and test records, but 'validated' should require either human confirmation or evidence from multiple independent sources.

## Schema Overhead

Adding 5 columns to the beliefs table:
- method (TEXT): ~20 bytes per row
- sample_size (INTEGER): 4 bytes
- data_source (TEXT): ~30 bytes
- independently_validated (BOOLEAN): 1 byte
- rigor_tier (TEXT): ~15 bytes

Total: ~70 bytes per belief. At 10K beliefs: 700KB. Negligible.

## Summary

| Requirement | Schema Change | Complexity | Value |
|-------------|--------------|-----------|-------|
| REQ-023 | 4 columns on beliefs | Low | High -- enables provenance queries |
| REQ-024 | 2 columns on sessions | Low | Medium -- velocity is a proxy signal |
| REQ-025 | 1 column on beliefs | Low | High -- rigor tiers prevent inflated status |
| REQ-026 | Query pattern, not schema | Medium (logic) | High -- the user-facing output of all the above |

Total schema overhead: 70 bytes per belief + 12 bytes per session. The value is in preventing CS-005-class failures where a new agent misjudges project maturity.
