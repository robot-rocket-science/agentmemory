# Wonder: Belief Evolution Tracking and Time-Indexed Retrieval

**Date:** 2026-04-11
**Prereqs:** exp19_time_dimension.md, exp57-60 (decay validation), exp66-69 (feedback/correction/recency)
**Status:** Design phase

## Motivation

The memory system tracks ~17K beliefs across ~14 sessions over ~2 weeks. It handles explicit replacement (SUPERSEDES edges, `valid_to` timestamps) but has three blind spots:

1. **Gradual evolution is invisible.** When understanding deepens across sessions -- "HRR is critical" then "HRR's real value is fuzzy-start traversal" then "HRR bridges structural connections" -- these beliefs coexist. They are all simultaneously true. No edge connects them, so the agent has no way to surface the intellectual trajectory.

2. **Confidence has no history.** A belief's `(alpha, beta_param)` reflects cumulative feedback but not the path it took. A belief that was once high-confidence and then decayed tells a different story than one that was always mediocre. That trajectory is lost.

3. **No point-in-time queries.** "What did we know about retrieval scoring when we designed the recency boost?" is unanswerable without reconstructing the temporal snapshot manually. The `created_at` and `valid_to` fields exist but lack a composite index and a query interface.

4. **No turn-level provenance.** Five beliefs from the same conversation turn share context. A correction that spawned a new belief has a causal relationship to the corrected one. These links are implicit in timestamps at best, invisible at worst.

---

## Exp 77: Belief Evolution Chains

### Problem

SUPERSEDES captures replacement: belief A is wrong, belief B replaces it. But understanding deepens without contradiction. Three beliefs about HRR are all valid -- they represent progressive refinement, not correction. The system treats them as unrelated.

### Detection Algorithm

**Input:** A newly persisted belief B_new.
**Output:** Zero or more EVOLVES_FROM edges to older beliefs on the same topic.

```
def detect_evolution(store, new_belief):
    # 1. Extract significant terms (reuse supersession.extract_terms)
    new_terms = extract_terms(new_belief.content)
    if len(new_terms) < 3:
        return []

    # 2. Search for candidates via FTS5 (same as supersession)
    candidates = store.search(new_belief.content, top_k=20)

    # 3. Filter: same topic but NOT contradictory
    evolution_links = []
    for candidate in candidates:
        if candidate.id == new_belief.id:
            continue
        if candidate.superseded_by is not None:
            continue  # already superseded -- use SUPERSEDES chain instead

        cand_terms = extract_terms(candidate.content)
        jaccard = jaccard_similarity(new_terms, cand_terms)

        # Key difference from supersession: LOWER Jaccard threshold.
        # Evolution means related topic, not identical claim.
        # Supersession uses 0.4; evolution uses 0.2-0.35 range.
        if jaccard < 0.2:
            continue

        # Time ordering: candidate must be older
        age_gap = parse_iso(new_belief.created_at) - parse_iso(candidate.created_at)
        if age_gap.total_seconds() < 600:  # 10 min minimum gap
            continue

        # Contradiction check: if Jaccard > 0.4 AND same belief_type,
        # this is likely supersession territory. Skip.
        if jaccard >= 0.4 and candidate.belief_type == new_belief.belief_type:
            continue

        # Score: combine Jaccard overlap with temporal distance.
        # Closer in time + moderate overlap = stronger evolution signal.
        hours = age_gap.total_seconds() / 3600.0
        evolution_score = jaccard * (1.0 / (1.0 + hours / 168.0))
        # 168h = 1 week half-decay for evolution relevance

        if evolution_score > 0.05:
            evolution_links.append((candidate, evolution_score))

    # Sort by score descending, take top 3
    evolution_links.sort(key=lambda x: -x[1])
    return evolution_links[:3]
```

### New Edge Type: DEEPENS

Semantics: `B_new --DEEPENS--> B_old` means "B_new extends or refines the understanding expressed in B_old."

- Both beliefs remain active (neither gets `valid_to` set).
- The edge carries `weight = evolution_score` and `reason = "topic_evolution"`.
- Uses the existing `edges` table -- no schema change needed.

Why DEEPENS over EVOLVES_FROM: "evolves from" implies the old version is incomplete. "Deepens" is neutral -- both are valid, the newer one adds depth. This matches the actual relationship.

### Experiment Protocol

**Phase 1: Offline detection on existing corpus (~17K beliefs)**

1. Run detection over all beliefs sorted by `created_at`.
2. For each belief, find DEEPENS candidates among older beliefs.
3. Record all detected chains. Expected output: clusters of 2-5 beliefs showing progressive understanding.
4. Manual review: sample 50 detected chains, classify as {correct_evolution, false_positive_unrelated, should_be_supersession}.
5. Target: >70% correct_evolution, <10% should_be_supersession.

**Phase 2: Retrieval quality test**

1. Select 10 queries where the answer requires understanding how a concept evolved.
2. Baseline: standard search (top-5 results by current scoring).
3. Treatment: standard search + expand results along DEEPENS edges (add chain members to result set).
4. Metric: does the agent produce a more complete answer with the chain? Judge by a rubric:
   - Does the response acknowledge the concept evolved?
   - Does it cite the most recent understanding?
   - Does it preserve nuance from earlier beliefs?

**Phase 3: Integration cost**

- Measure: how many DEEPENS edges does the detector create per belief? If >2 on average, the threshold is too loose.
- Measure: FTS5 query cost for 20 candidates vs. current 10 for supersession.
- Constraint: detection must add <50ms per belief ingestion.

### Success Criteria

- Precision > 70% on manual review of detected chains.
- At least 5 out of 10 retrieval queries show measurably better answers with chain expansion.
- Ingestion latency overhead < 50ms per belief.

---

## Exp 78: Confidence History

### Problem

The beliefs table stores `(alpha, beta_param)` as current values. Every feedback event mutates them in place. The trajectory is lost.

Example scenario: belief X starts at (0.5, 0.5), gets 5 positive feedbacks to (5.5, 0.5) -- high confidence. Then 3 negative feedbacks drop it to (5.5, 3.5). The current confidence (0.61) looks mediocre. But the trajectory says: "this was once trusted and then lost trust." That signal matters -- it might be worth re-examining rather than ignoring.

### Schema Change

```sql
CREATE TABLE IF NOT EXISTS confidence_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    belief_id TEXT NOT NULL,
    alpha REAL NOT NULL,
    beta_param REAL NOT NULL,
    confidence REAL GENERATED ALWAYS AS (alpha / (alpha + beta_param)) STORED,
    event_type TEXT NOT NULL,
    event_detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (belief_id) REFERENCES beliefs(id)
);

CREATE INDEX IF NOT EXISTS idx_confhist_belief ON confidence_history(belief_id);
CREATE INDEX IF NOT EXISTS idx_confhist_time ON confidence_history(created_at);
CREATE INDEX IF NOT EXISTS idx_confhist_belief_time ON confidence_history(belief_id, created_at);
```

### Event Types That Trigger a Snapshot

| Event Type | Trigger Point | Detail Recorded |
|---|---|---|
| `created` | `store.persist_belief()` | Initial (alpha, beta_param) values |
| `feedback_positive` | `feedback()` with outcome "used" | belief_id of the search that surfaced it |
| `feedback_negative` | `feedback()` with outcome "ignored" or "harmful" | same |
| `decay_recalc` | Periodic decay recalculation (if implemented) | decay_factor applied |
| `superseded` | `supersede_belief()` | ID of the superseding belief |
| `locked` | `lock()` | "user_confirmed" |
| `unlocked` | `unlock()` | reason |

Implementation: wrap the existing `update_confidence()` and `supersede_belief()` methods to append a row to `confidence_history` before committing.

### Experiment: Does Confidence Trajectory Predict Usefulness?

**Hypothesis:** Beliefs with a "rise then fall" trajectory (peaked high, currently low) are more likely to be useful on re-test than beliefs that were always low.

**Protocol:**

1. Run the system for 2+ weeks with confidence_history recording.
2. Query beliefs where max historical confidence > 0.7 AND current confidence < 0.5. Call these "fallen" beliefs.
3. Query beliefs where max historical confidence was never above 0.5. Call these "always-low" beliefs.
4. Re-test both groups: surface them in relevant contexts, collect feedback.
5. Compare: do fallen beliefs get "used" feedback at a higher rate than always-low beliefs?

**Secondary metric: trajectory shape classification.**

Classify each belief's confidence trajectory into one of:
- **Rising:** monotonically increasing. Healthy belief, gaining trust.
- **Stable-high:** stays above 0.7. Reliable, well-validated.
- **Peaked-and-fell:** rose above 0.7 then dropped below 0.5. Potentially stale or context-dependent.
- **Noisy:** oscillates. Might be ambiguous or context-sensitive.
- **Flatline-low:** never rose above 0.5. Weak signal, possibly noise.

Each shape implies a different retrieval strategy:
- Rising/Stable-high: surface normally.
- Peaked-and-fell: flag for re-evaluation, possibly with a "was once trusted" annotation.
- Noisy: surface with uncertainty warning.
- Flatline-low: deprioritize or prune.

### Success Criteria

- Confidence_history table adds < 5% storage overhead (estimate: ~17K beliefs * ~5 events avg = 85K rows, ~3MB).
- Fallen beliefs show > 1.5x the "used" feedback rate of always-low beliefs.
- At least 3 of the 5 trajectory shapes are distinguishable in real data.

---

## Exp 79: Point-in-Time Snapshots

### Problem

"What did we know about X at time T?" is fundamental for decision auditing. The data exists -- `created_at` and `valid_to` on every belief -- but there is no optimized query path and no API for it.

### Algorithm

```sql
-- Active beliefs about topic X at time T
SELECT b.*
FROM search_index si
JOIN beliefs b ON b.id = si.id
WHERE search_index MATCH :query
  AND b.created_at <= :T
  AND (b.valid_to IS NULL OR b.valid_to > :T)
ORDER BY b.created_at DESC
LIMIT :top_k;
```

This is a temporal window query: include beliefs that existed at time T (created before T, not yet invalidated at T).

### Index Needed

Current indexes:
- `idx_beliefs_valid_to ON beliefs(valid_to)` -- exists, but only on valid_to

Missing:
```sql
CREATE INDEX IF NOT EXISTS idx_beliefs_temporal
    ON beliefs(created_at, valid_to);
```

This composite index allows the query planner to efficiently filter the temporal window. Without it, SQLite must scan all FTS5 matches and filter by timestamp.

For larger corpora, a covering index would help:
```sql
CREATE INDEX IF NOT EXISTS idx_beliefs_temporal_cover
    ON beliefs(created_at, valid_to, id, belief_type, source_type, locked);
```

### API Addition

```python
def search_at_time(
    self,
    query: str,
    at_time: str,  # ISO 8601
    top_k: int = 10,
) -> list[Belief]:
    """Search for beliefs that were active at a specific point in time."""
```

This method combines FTS5 search with the temporal window filter. It returns beliefs ranked by relevance (FTS5 rank) that were alive at `at_time`.

### Experiment: Reconstruct 3 Historical Decision Points

Pick 3 real decisions from project history where we can verify what was known at the time:

**Decision 1: Choosing Thompson sampling for retrieval ranking (~session 3-4)**
- Timestamp: identify from git log or session records.
- Query: "retrieval ranking scoring"
- Expected: should surface experiment results from exp7-exp15, not later refinements.
- Validation: do the surfaced beliefs match what was actually available at that point?

**Decision 2: Adding content-aware decay half-lives (~session 8-9)**
- Timestamp: around exp58c completion.
- Query: "decay half-life content type"
- Expected: should surface exp57-58 results but NOT exp69 recency boost (came later).

**Decision 3: Implementing supersession detection (~session 10-11)**
- Timestamp: when supersession.py was created.
- Query: "belief replacement contradiction detection"
- Expected: should surface related experiment results available at that time.

**Measurement per decision:**
1. Precision: what fraction of returned beliefs were actually available at that time? Target: 100% (this is a correctness check, not a relevance check).
2. Recall: of the beliefs that should have informed the decision, how many appear in top-10? Target: >60%.
3. Gap analysis: were there beliefs available but NOT surfaced that would have changed the decision?

### Success Criteria

- Temporal filter achieves 100% precision (no future-leaked beliefs) on all 3 test cases.
- Recall > 60% for decision-relevant beliefs.
- Query latency with composite index < 50ms on 17K corpus.
- Composite index adds < 1MB storage.

---

## Exp 80: Conversation Flow as Belief Provenance

### Problem

Beliefs do not track which conversation turn produced them. When 5 beliefs come from the same user statement, they share context that is invisible to retrieval. When belief B was created because the user corrected belief A in the same turn, the causal link is lost.

Current state:
- `observations.session_id` links observations to sessions but not to specific turns.
- `observations.source_id` is a free-form text field, currently unused in most paths.
- `evidence` table links beliefs to observations, providing indirect provenance.

### Schema for Turn-Level Provenance

```sql
CREATE TABLE IF NOT EXISTS conversation_turns (
    id TEXT PRIMARY KEY,          -- UUID hex, 12 chars
    session_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL,  -- sequential within session (0, 1, 2, ...)
    role TEXT NOT NULL,           -- 'user' or 'assistant'
    content_hash TEXT NOT NULL,   -- for dedup
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_turns_session ON conversation_turns(session_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_turns_time ON conversation_turns(created_at);
```

Link beliefs to turns via the existing observations path:
- `observations.source_id` gets set to `conversation_turns.id` when the observation comes from a conversation turn.
- No new FK needed (source_id is already TEXT).
- Alternatively, add `turn_id TEXT` to the beliefs table directly for faster joins.

### Causal Links Within a Turn

When a user correction in turn T produces:
1. A `feedback_negative` event on belief A
2. A new belief B (the correction)

These events share a turn_id. The causal link is:

```
B --CORRECTS--> A  (edge, already captured by correct())
B.turn_id == A's feedback turn_id  (provenance link)
```

For co-created beliefs (5 beliefs from one turn), the shared turn_id groups them. Retrieval can then:
- When surfacing belief B, also surface B's turn-siblings if they are relevant.
- When answering "why did we decide X?", find the turn that created the decision beliefs, and surface the full turn context.

### Experiment Protocol

**Phase 1: Annotate existing beliefs with turn provenance (retrospective)**

1. Use `observations.created_at` timestamps to cluster beliefs into turns.
   - Heuristic: beliefs created within 2 seconds of each other from the same session likely share a turn.
   - More precise: parse the ingest pipeline's `source` parameter, which often contains turn-level context.
2. Create synthetic `conversation_turns` rows for each detected cluster.
3. Measure: how many beliefs can be assigned to a turn? Target: >80%.

**Phase 2: Retrieval quality test**

Test query type: "Why did we decide X?"

1. Select 5 decisions that involved multi-belief turns (e.g., a correction that spawned a replacement plus related observations).
2. Baseline: standard search returns top-5 beliefs.
3. Treatment: standard search + expand results by shared turn_id (include turn-siblings).
4. Metric: does the expanded result set provide a more complete causal explanation?

**Rubric for evaluation:**
- Does the result explain *what* was decided? (factual completeness)
- Does the result explain *why* it was decided? (causal completeness)
- Does the result explain *what it replaced*? (supersession context)

Score each dimension 0-2 (0 = absent, 1 = partial, 2 = complete). Treatment should score higher on "why" and "what it replaced" dimensions.

**Phase 3: Provenance-aware dedup**

Beliefs from the same turn are often near-duplicates (the classifier extracts multiple angles from one statement). Turn provenance enables smarter dedup:
- If 3 beliefs share a turn and 2 have Jaccard > 0.6, merge into one.
- Measure: how many beliefs are candidates for turn-aware dedup? Does dedup improve retrieval precision?

### Success Criteria

- >80% of beliefs can be retrospectively assigned to a turn.
- At least 3 of 5 "why" queries score higher on causal completeness with turn expansion.
- Turn-aware dedup identifies >100 candidate merges in the 17K corpus without false positives.

---

## Implementation Order

| Priority | Experiment | Reason | Effort |
|---|---|---|---|
| 1 | Exp 79 (point-in-time) | Cheapest to implement (one index + one query method). Immediate value for decision auditing. No schema migration. | Small |
| 2 | Exp 78 (confidence history) | One new table, straightforward instrumentation at existing write points. Unlocks trajectory analysis. | Medium |
| 3 | Exp 80 (turn provenance) | One new table + backfill from timestamps. Biggest unknown: how clean is the retrospective clustering? | Medium |
| 4 | Exp 77 (evolution chains) | Most algorithmically complex. Depends on tuning Jaccard thresholds and the supersession/evolution boundary. Best done after exp79 provides temporal query capability. | Large |

## Shared Risks

- **Index bloat.** Two new tables + one new composite index. At 17K beliefs this is trivial. At 1M beliefs, confidence_history could reach 5M rows. Needs periodic compaction or rolling windows.
- **False evolution chains.** Beliefs about "retrieval" are common. Low Jaccard threshold risks connecting unrelated retrieval beliefs. Mitigation: require shared non-stopword terms to include at least one domain-specific term (>8 chars or camelCase).
- **Retrospective turn clustering.** Timestamp-based clustering is a heuristic. If ingestion batches beliefs with identical timestamps, turn boundaries blur. Mitigation: use source_id field when available, fall back to timestamp clustering.
- **Confidence history write amplification.** Every feedback event adds a row. At high feedback volume this could slow writes. Mitigation: batch inserts, or only snapshot when confidence changes by > 0.05.

## Dependencies on Existing Code

| File | What It Provides | What Changes |
|---|---|---|
| `src/agentmemory/store.py` | Schema, `supersede_belief()`, `persist_belief()`, `search()` | Add `confidence_history` table to schema, add `search_at_time()`, add composite index |
| `src/agentmemory/supersession.py` | `extract_terms()`, `jaccard_similarity()`, `check_temporal_supersession()` | Reuse for exp77 detection; no changes needed |
| `src/agentmemory/scoring.py` | `decay_factor()`, `score_belief()` | No changes for exp77-79; exp78 may add trajectory-based scoring later |
| `src/agentmemory/models.py` | `Belief`, `Edge` dataclasses | May add `ConversationTurn` dataclass for exp80 |
| `src/agentmemory/server.py` | MCP tool implementations | Add `search_at_time` tool exposure for exp79 |
