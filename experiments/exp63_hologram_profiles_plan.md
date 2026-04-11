# Experiment 63: Hologram Persistence and Agent Profiles

**Date:** 2026-04-11
**Builds on:** Exp 62 (minimal hologram), Exp 42 (IB compression), Exp 45 (HRR prototype)
**Depends on:** Exp 62 results (knee point, minimal hologram size)
**Rigor tier:** Empirically tested (real data, A/B behavioral comparison)

---

## Research Question

Can a frozen belief subgraph (hologram) be serialized, loaded into a fresh agent session, and produce behaviorally distinguishable agent responses? Specifically: if you persist two different holograms (Profile A: "strict reviewer" posture, Profile B: "exploratory researcher" posture) and inject them as pre-prompt context, does the agent's output measurably differ in a predictable direction?

## Hypothesis

**H1:** Two holograms constructed from the same graph but with different belief selections (constraint-heavy vs. evidence-heavy) will produce measurably different agent outputs when injected as pre-prompt context on the same 5 test prompts. Measured by cosine distance between response embeddings: distance >= 0.15.

**H2:** A hologram loaded from a serialized file (JSON snapshot) produces identical retrieval results to the same hologram loaded from the live database. Coverage difference = 0.

**H3:** Hologram load time is under 200ms for a hologram of 100 beliefs (the expected knee from Exp 62). This is fast enough for pre-prompt injection without noticeable latency.

## Null Hypothesis

The two profiles produce indistinguishable outputs (cosine distance < 0.05). The hologram's belief composition does not meaningfully shape agent behavior -- the agent's foundation model dominates regardless of injected context.

## Why This Matters

If profiles work, the hologram becomes a first-class artifact:
- Teams can share project postures ("here's how to work on this codebase")
- Users can switch between personas for different tasks
- Onboarding becomes "load this hologram" instead of "read these 50 docs"
- Agent behavior is auditable: the profile IS the explanation

If profiles don't work (null hypothesis), injected beliefs are noise the model ignores. The memory system's value is limited to explicit retrieval (the agent asks for it) rather than ambient shaping (the agent is shaped by it).

## Materials

**Dataset:** Alpha-seek belief graph (1,195 nodes, 1,485 edges).

**Profile construction:**

- **Profile A ("Strict Reviewer"):** All locked beliefs + all constraint-type beliefs + all correction-type beliefs. Emphasizes rules, boundaries, what NOT to do.
- **Profile B ("Exploratory Researcher"):** All evidence-type beliefs + all causal-type beliefs + all relational-type beliefs. Emphasizes connections, reasoning, what IS true.
- **Profile C ("Minimal"):** Locked beliefs only. The zero-effort baseline.

**Test prompts (5):**
1. "Should we add async support to the memory store?"
2. "The retrieval pipeline is returning irrelevant results. What should we investigate?"
3. "I want to refactor the scoring module. Where should I start?"
4. "Is HRR worth keeping in the architecture?"
5. "Write a plan for scaling the belief graph to 100K nodes."

These are chosen to be open-ended enough that the profile should influence the direction of the response.

**Embedding model:** For measuring response distance, use the same porter-stemmed token overlap (Jaccard) rather than neural embeddings. This avoids introducing an external model and stays within the project's zero-LLM-cost philosophy.

**Serialization format:** JSON snapshot containing:
```json
{
  "profile_name": "strict_reviewer",
  "created_at": "ISO8601",
  "source_graph": "alpha-seek",
  "belief_count": 87,
  "beliefs": [
    {"id": "abc123", "content": "...", "type": "constraint", "confidence": 0.95, "locked": true}
  ],
  "edges": [
    {"from": "abc123", "to": "def456", "type": "SUPPORTS", "weight": 0.8}
  ]
}
```

## Methodology

### Phase 1: Profile construction

1. From the full graph, construct Profile A, B, and C as defined above.
2. Record: belief count, type distribution, total tokens, edge count for each profile.
3. Serialize each profile to JSON.

### Phase 2: Serialization fidelity

4. Load each serialized JSON profile into a fresh in-memory MemoryStore.
5. Run the 6 ground-truth queries from Exp 47 against each loaded profile.
6. Compare coverage to the same queries run against the profile's beliefs in the live database.
7. Assert: coverage difference = 0 for all profiles. Any difference indicates serialization loss.

### Phase 3: Load performance

8. Time the load operation (JSON parse + MemoryStore insert + FTS5 index) for each profile.
9. Repeat 20 times. Report p50, p95, max latency.

### Phase 4: Behavioral divergence

10. For each of the 5 test prompts:
    a. Format the profile's beliefs as a "context block" (the format `get_locked` currently uses).
    b. Prepend the context block to the test prompt.
    c. Feed to a local LLM (or simulate: extract the top-5 beliefs each profile would surface for the prompt via FTS5 retrieval against the profile's beliefs).
    d. Measure Jaccard distance between Profile A's top-5 belief set and Profile B's top-5 belief set.
11. Report mean Jaccard distance across the 5 prompts.

**Simplification note:** Phase 4 does NOT require an actual LLM call. We measure the divergence of the *context* the profile would inject, not the downstream LLM response. This isolates the profile's effect from the model's variability. If the contexts diverge, the responses will diverge (the model sees different information). If the contexts are identical despite different profiles, the profiles are not doing their job.

### Phase 5: Dynamic shaping simulation

12. Starting from Profile A, simulate 20 conversation turns that introduce evidence-type beliefs (mimicking a session where the agent learns new things).
13. After each turn, re-score the profile's beliefs and re-rank.
14. Measure: how much does the profile's top-50 belief set shift (Jaccard distance from original) after 5, 10, 15, 20 turns?
15. This tests whether the hologram evolves meaningfully or is dominated by its initial state.

## Metrics

| Metric | Formula | Target | Interpretation |
|--------|---------|--------|----------------|
| Serialization fidelity | coverage(loaded) - coverage(live) | = 0 | Lossless round-trip |
| Load latency p95 | 95th percentile of load times | < 200ms | No perceptible delay |
| Profile divergence | mean Jaccard distance of top-5 belief sets across 5 prompts | >= 0.4 | Profiles produce meaningfully different context |
| Dynamic drift | Jaccard(initial top-50, top-50 after N turns) | >= 0.1 after 10 turns | Profile evolves, not static |
| Token footprint | total tokens in serialized profile | <= 6000 | Fits in pre-prompt budget |

## Decision Criteria

| If This Happens | Then Do This |
|-----------------|--------------|
| Fidelity = 0, latency < 200ms, divergence >= 0.4 | Profiles are viable. Design the profile format spec and CLI commands (`agentmemory profile save/load/list`). |
| Fidelity = 0 but divergence < 0.2 | Serialization works but profiles don't differentiate. Investigate whether belief TYPE matters or belief CONTENT matters more. May need a scoring-weighted selection rather than type-based. |
| Divergence >= 0.4 but latency > 500ms | Profiles work but loading is slow. Optimize: pre-compute FTS5 index, store as SQLite blob, lazy load. |
| Dynamic drift < 0.05 after 20 turns | The profile is too rigid. Initial beliefs dominate despite new evidence. Need decay or eviction for profile beliefs. |
| Fidelity != 0 | Serialization is lossy. Debug: which beliefs are lost? Content hash collision? FTS5 index divergence? |

## Confounds and Controls

- **Profile size confound:** Profile A and B may differ in size (different type counts). Normalize by padding the smaller profile with random beliefs to match counts. If divergence persists after normalization, it's due to content, not size.
- **Query bias:** The 5 test prompts may favor one profile over another. Mitigation: prompts are deliberately open-ended. Include 2 that are constraint-oriented and 2 that are evidence-oriented and 1 neutral.
- **Jaccard limitations:** Jaccard on belief IDs measures set overlap, not semantic similarity. Two different beliefs could be semantically identical (paraphrases). Mitigation: content dedup already handles this (content_hash in the store).

---

## Files

- `exp63_hologram_profiles.py` -- all phases
- `exp63_results.json` -- per-profile stats, divergence measurements, latency data
- `exp63_hologram_profiles_results.md` -- analysis
