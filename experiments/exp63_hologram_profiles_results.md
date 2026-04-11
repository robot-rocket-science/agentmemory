# Experiment 63: Hologram Profiles -- Results

**Date:** 2026-04-11
**Input:** Production memory.db (22,805 non-superseded beliefs post additional ingestion)
**Method:** Type-weight scoring profiles, divergence measurement, serialization, dynamic shaping
**Rigor tier:** Empirically tested (real data, adjusted design based on Exp 62)
**Adjustment:** Tested type-weight profiles instead of frozen subgraphs, per Exp 62 findings

---

## Summary

**Profiles produce maximally divergent retrieval sets** -- Strict Reviewer vs Explorer have Jaccard distance 1.0 (zero overlap in top-30). But **coverage is low across all profiles** (11-22%) because `score_belief()` without FTS5 is essentially random within a type stratum.

**Serialization is trivial** -- round-trip verified, load time 0.02ms (p50).

**Dynamic shaping is zero** -- 20 new correction beliefs produce 0.0 drift in top-30. The existing 3,283 corrections saturate the type stratum.

---

## Phase 2: Profile Divergence

### Jaccard Distances (top-30 belief sets)

| Pair | Mean Jaccard | Interpretation |
|------|-------------|----------------|
| Explorer vs Strict Reviewer | 1.000 | Zero overlap -- maximally opposed |
| Balanced vs Explorer | 0.750 | 75% different |
| Balanced vs Strict Reviewer | 0.571 | 57% different |

Distances are constant across all 6 topics because the type-weight multipliers deterministically stratify rankings by type. With uniform confidence (0.9), Thompson sampling noise is the only within-type differentiator, and the type weights dominate.

### Coverage by Profile

| Profile | Mean Coverage | Min | Max |
|---------|-------------|-----|-----|
| Balanced | 22.2% | 0% | 50% |
| Strict Reviewer | 16.7% | 0% | 50% |
| Explorer | 11.1% | 0% | 33% |

Coverage is low because `score_belief()` does not incorporate text matching. It ranks by Thompson sample * type weight, which is query-independent. The top-30 beliefs are the highest-confidence beliefs of the dominant type, not the most relevant to any query.

### Key Insight

Type-weight profiles are necessary but insufficient. They control WHICH types appear in results, but relevance WITHIN a type requires FTS5 or another text-matching signal. The right architecture is:

```
Profile (type weights) + FTS5 (text relevance) = useful retrieval
```

Neither alone is sufficient.

---

## Phase 3: Serialization

| Metric | Value |
|--------|-------|
| Serialized size | 165-172 bytes |
| Round-trip match | True (all profiles) |
| Load time p50 | 0.017ms |
| Load time p95 | 0.108ms |

Profiles are tiny JSON objects. Serialization is a non-issue.

---

## Phase 4: Dynamic Shaping

Adding 20 synthetic correction beliefs to the store produced **zero drift** (Jaccard 0.0 from baseline at every step). Zero synthetic beliefs appeared in the top-30.

**Why:** With 3,283 existing corrections all at confidence 0.9, Thompson sampling produces scores near 0.9 for all of them. 20 new corrections at the same confidence have a ~20/3303 = 0.6% chance of landing in the top-30 per slot. At 30 slots, expected new entries = 0.18. Essentially zero.

**Implication:** At this corpus size, type-level saturation prevents new beliefs from surfacing through Thompson sampling alone. The system needs either:
1. Higher priors for recent beliefs (temporal recency boost)
2. Query-aware scoring (FTS5 would rank a new correction about "X" highly for queries about "X")
3. Explicit promotion of new beliefs into the top-k regardless of score

---

## Implications for the Hologram Concept

### What profiles CAN do
- Deterministically control the type composition of retrieved context
- Serialize at near-zero cost (sub-ms load, ~170 bytes)
- Produce maximally different retrieval postures (Jaccard 1.0 between opposed profiles)

### What profiles CANNOT do (alone)
- Produce query-relevant results (no text matching)
- Respond to new evidence (type saturation at scale)
- Achieve high coverage on topic-specific ground truth

### Recommended architecture
A profile should be a **modifier on the retrieval pipeline**, not a replacement:

```python
def retrieve_with_profile(store, query, profile, budget):
    # Step 1: FTS5 search (text relevance)
    candidates = store.search(query, top_k=100)
    # Step 2: Score with profile-weighted scoring
    for b in candidates:
        b.score = score_belief(b, query, now) * profile.type_weights[b.belief_type]
    # Step 3: Pack into budget
    return pack_beliefs(sorted(candidates, key=score, reverse=True), budget)
```

This combines FTS5's text relevance with the profile's type preference. Exp 64 tests the compilation side of this.

---

## Limitations

- All beliefs have uniform confidence (0.9) from bulk ingestion. With live usage creating varied confidence, Thompson sampling would produce more meaningful rankings within type strata.
- No locked beliefs exist. In practice, locked beliefs would bypass scoring entirely and appear in every profile.
- Ground truth is adapted from Exp 62 (6 topics, 13 substrings, 86% ceiling).

---

## Files

- `exp63_hologram_profiles.py` -- experiment code
- `exp63_results.json` -- raw data
- `exp63_hologram_profiles_plan.md` -- original design (pre-adjustment)
- `exp63_hologram_profiles_results.md` -- this file
