# Wonder: Temporal Edges Between Beliefs

**Date:** 2026-04-11
**Context:** Exp 19 (time as graph dimension), Exp 48 (commit TEMPORAL_NEXT = zero value), Exp 57 (temporal scoring hurts locked beliefs), Exp 59 (TEMPORAL_NEXT required for 2/10 query types)
**Scope:** Experiments 71-74

---

## Background

The DB currently has ~17K beliefs with timestamps spanning 2026-04-10 to 2026-04-12, 14 sessions, and 50 TEMPORAL_NEXT edges between commit-derived beliefs. The commit-level edges have zero retrieval value (Exp 48) because they reference commit nodes, not belief IDs. Beliefs have no temporal edges linking them to each other.

Key constraints from prior work:
- TEMPORAL_NEXT must be traversal-only, never mixed into scoring (Exp 57)
- TEMPORAL_NEXT is strictly required for adjacency queries (Exp 59)
- The `edges` table has 1,914 SUPERSEDES edges, giving explicit correction chains
- The `graph_edges` table has the 50 commit-level TEMPORAL_NEXT edges plus structural edges (SENTENCE_IN_FILE, WITHIN_SECTION, etc.)
- Beliefs lack session_id directly; linkage goes belief -> evidence -> observation -> session_id (only 3 observations have session_ids currently)
- Most beliefs (13,924) are agent_inferred via onboarding scan; 3,176 are user_corrected; 5 are user_stated

### The Gap

Beliefs created from the same conversation or scan batch share timestamps but have no structural links. Adjacency queries ("what came right before X?") can only use timestamp sorting today, which is lossy when multiple beliefs share the same second.

---

## Experiment 71: Belief-Level TEMPORAL_NEXT Extraction

### Research Question

Does creating TEMPORAL_NEXT edges between consecutive beliefs (ordered by created_at within the same source batch) improve retrieval for adjacency queries compared to a timestamp-only baseline?

### Hypothesis

**H1:** Belief-level TEMPORAL_NEXT edges improve recall@5 for adjacency queries by at least 20% over timestamp-sorted retrieval alone.

**H2:** For beliefs sharing the same timestamp (sub-second collisions), TEMPORAL_NEXT preserves ordering that timestamps lose.

### Null Hypothesis

Timestamp sorting on created_at achieves the same adjacency retrieval performance as TEMPORAL_NEXT traversal. The edges add O(n) storage cost with no retrieval benefit.

### Method

1. **Build belief chains.** Sort all 17K beliefs by created_at. Group by source batch:
   - Same source_type + same created_at date (within 1-hour window) = same batch
   - Within each batch, order by created_at, then by rowid as tiebreaker
   - Create TEMPORAL_NEXT edges between consecutive beliefs in each batch
   - Add SESSION_BOUNDARY edges between the last belief of batch N and first of batch N+1

2. **Define ground truth.** For 20 randomly sampled beliefs (stratified: 10 factual, 5 correction, 5 requirement):
   - Manually identify the 3 beliefs that were truly "discussed right before" and "right after" (6 total per query)
   - Use content similarity + timestamp proximity to validate

3. **Run adjacency queries.** For each ground-truth belief, retrieve neighbors using:
   - **Method A (timestamp-only):** SELECT beliefs WHERE created_at BETWEEN (target - 60s) AND (target + 60s) ORDER BY ABS(created_at - target_created_at) LIMIT 5
   - **Method B (TEMPORAL_NEXT):** BFS 3 hops forward + 3 hops backward along TEMPORAL_NEXT edges from the target belief
   - **Method C (hybrid):** TEMPORAL_NEXT traversal, then re-rank by timestamp distance

4. **Measure:**

| Metric | Definition |
|--------|-----------|
| Recall@5 | Fraction of 6 ground-truth neighbors found in top 5 results |
| MRR | Reciprocal rank of first correct neighbor |
| Ordering accuracy | Kendall tau correlation between predicted order and true order |
| Timestamp collision rate | Fraction of adjacent pairs sharing the exact same timestamp |

### Data Needed

- All from live DB (read-only): beliefs table (id, created_at, source_type, belief_type, content)
- Evidence table to trace belief -> observation -> session_id where available
- Ground truth: manually annotated (20 beliefs x 6 neighbors = 120 annotations)

### Computational Cost

- Edge creation: O(n) for 17K beliefs = trivial (in-memory, not written to DB)
- 20 queries x 3 methods x BFS(6 hops) = ~60 graph traversals, sub-second total
- Ground truth annotation: ~30 minutes manual effort
- Total runtime: < 2 minutes compute + 30 minutes annotation

### Expected Edge Count

~17K TEMPORAL_NEXT edges (one per consecutive pair), ~50 SESSION_BOUNDARY edges between batches. Doubles the current graph_edges table size but all edges are the same lightweight type.

---

## Experiment 72: Implicit Thread Detection via Topic Continuity

### Research Question

When consecutive beliefs share topic continuity ("building on what we just discussed"), can we detect conversation threads and create THREAD edges that group topically related belief runs? Do THREAD edges improve retrieval compared to flat TEMPORAL_NEXT chains?

### Hypothesis

**H1:** Topic continuity within a temporal window (consecutive beliefs with FTS5 term overlap >= 2 shared content words, excluding stopwords) identifies conversation threads with >= 70% precision.

**H2:** THREAD edges improve recall@10 for topic-scoped queries ("what did we discuss about X?") by >= 15% over TEMPORAL_NEXT alone.

### Null Hypothesis

Topic continuity is too noisy to detect reliably. FTS5 search on the topic keyword alone matches or exceeds THREAD-based retrieval.

### Method

1. **Thread detection algorithm.** Scan the TEMPORAL_NEXT chain from Exp 71:
   - For each consecutive pair (A, B), compute Jaccard similarity on content tokens (lowercased, stopwords removed)
   - If Jaccard >= 0.15 (tunable threshold), A and B are in the same thread
   - A thread breaks when Jaccard drops below threshold for 2+ consecutive pairs
   - Create THREAD edges: each belief in a thread links to the thread's anchor (first belief)
   - Also create THREAD_NEXT edges between consecutive beliefs within the same thread

2. **Evaluate thread quality.** Sample 10 detected threads. For each:
   - Manually label: is this a real topical thread, or coincidental vocabulary overlap?
   - Compute precision = real threads / detected threads
   - Compute recall by checking 10 known topical runs (e.g., the SUPERSEDES chains for calls/puts, dispatch gate, capital decisions have known topic continuity)

3. **Compare retrieval methods.** For 15 topic queries (e.g., "typing annotations", "Bayesian confidence", "FTS5 retrieval"):
   - **Method A (FTS5 only):** Standard FTS5 search, top 10
   - **Method B (FTS5 + THREAD expansion):** FTS5 top 5, then expand each hit's THREAD to include thread siblings, re-rank by FTS5 score, top 10
   - **Method C (FTS5 + TEMPORAL_NEXT expansion):** FTS5 top 5, then expand 2 hops along TEMPORAL_NEXT, top 10

4. **Measure:**

| Metric | Definition |
|--------|-----------|
| Thread precision | Fraction of detected threads that are real topical units |
| Thread recall | Fraction of known topical runs that were detected |
| Retrieval recall@10 | Fraction of ground-truth beliefs found in top 10 |
| Retrieval MRR | Reciprocal rank of first relevant result |
| Expansion noise | Fraction of expanded results that are off-topic |

### Data Needed

- TEMPORAL_NEXT chain from Exp 71
- Content tokens for Jaccard computation (from beliefs.content)
- 15 ground-truth topic queries with expected belief sets
- 10 known topical runs for recall measurement (SUPERSEDES chains provide 3; need 7 more from manual inspection)

### Computational Cost

- Jaccard computation: O(n) pairwise over the chain = ~17K pairs, < 1 second
- Thread detection: single pass, O(n)
- 15 queries x 3 methods = 45 retrievals, < 5 seconds
- Manual annotation: ~45 minutes (thread quality + ground truth)
- Total: < 1 minute compute + 45 minutes annotation

### Threshold Sensitivity

Run the thread detector at Jaccard thresholds [0.05, 0.10, 0.15, 0.20, 0.30]. Report thread count and average thread length at each. Select threshold that maximizes F1 on the 10-thread validation set.

---

## Experiment 73: Temporal Co-occurrence Signal

### Research Question

Beliefs created from the same conversation turn (same observation, or observations within the same 10-second window) are semantically related but may use different vocabulary. Does creating CO_OCCURRED edges between same-turn beliefs improve retrieval when one belief is the query target but the query vocabulary matches a co-occurring sibling?

### Hypothesis

**H1:** >= 30% of belief pairs created within 10 seconds of each other share no FTS5 content terms, making them invisible to keyword search from either direction.

**H2:** CO_OCCURRED edges improve recall@5 for vocabulary-mismatched queries by >= 25% over FTS5 alone.

**H3:** CO_OCCURRED expansion adds fewer than 5 off-topic results per query on average (bounded noise).

### Null Hypothesis

Beliefs created in the same turn share enough vocabulary overlap that FTS5 already retrieves them together. CO_OCCURRED edges add redundant connections.

### Method

1. **Identify co-occurring belief clusters.** Group beliefs by created_at within 10-second windows:
   - Sort beliefs by created_at
   - Sliding window: beliefs where |created_at_A - created_at_B| <= 10s belong to the same co-occurrence group
   - Create CO_OCCURRED edges between all pairs in each group (undirected, stored as two directed edges)

2. **Characterize vocabulary overlap.** For each co-occurrence group of size >= 2:
   - Compute pairwise Jaccard on content tokens
   - Classify: HIGH overlap (Jaccard >= 0.3), MEDIUM (0.1-0.3), LOW (< 0.1)
   - Report distribution. H1 predicts >= 30% are LOW.

3. **Vocabulary-mismatch retrieval test.** For each LOW-overlap pair (A, B):
   - Use A's content as query terms, attempt to retrieve B
   - **Method A (FTS5 only):** FTS5 search with A's key terms
   - **Method B (FTS5 + CO_OCCURRED):** FTS5 search, then expand each result's CO_OCCURRED neighbors, re-rank
   - Ground truth: B should appear in results

4. **Bounded-noise test.** For 20 random queries:
   - Run Method B, count how many CO_OCCURRED expansions are off-topic
   - Off-topic defined as: no semantic relationship to the query (manual judgment)

5. **Measure:**

| Metric | Definition |
|--------|-----------|
| Vocabulary gap rate | % of co-occurring pairs with Jaccard < 0.1 |
| Recall@5 (mismatch) | Fraction of LOW-overlap siblings found via each method |
| MRR (mismatch) | Reciprocal rank of the co-occurring sibling |
| Expansion noise | Average off-topic results per query from CO_OCCURRED expansion |
| Cluster size distribution | Histogram of co-occurrence group sizes |

### Data Needed

- All from live DB: beliefs.id, beliefs.content, beliefs.created_at
- No ground truth annotation needed for H1 (automated Jaccard computation)
- Manual judgment for 20 queries (bounded-noise test)

### Computational Cost

- Grouping: O(n log n) sort + O(n) scan = trivial
- Jaccard: O(k^2) per group where k = group size; if groups average 5 beliefs, ~17K/5 * 10 = ~34K pairs
- CO_OCCURRED edge count estimate: if average group size is 5, edges = sum(k*(k-1)) across groups. For 3,400 groups of 5: ~68K edges. This is significant -- 4x the current graph_edges count.
- 20 queries x 2 methods = 40 retrievals, < 5 seconds
- Total: < 30 seconds compute + 20 minutes annotation

### Risk: Edge Explosion

If onboarding produced beliefs in large batches (e.g., 100 beliefs in one 10-second window), CO_OCCURRED creates O(k^2) edges per group. Mitigation: cap group size at 20; for larger groups, only connect to the 5 nearest temporal neighbors via TEMPORAL_NEXT instead.

---

## Experiment 74: Temporal Traversal vs Timestamp Filtering for Scoped Queries

### Research Question

For time-scoped queries like "what did we decide about X last week?" or "what changed after session Y?", which approach finds more relevant beliefs: (a) timestamp-filtered FTS5 search, or (b) seed-and-traverse using temporal graph edges?

### Hypothesis

**H1:** Timestamp-filtered FTS5 achieves higher precision (fewer false positives) because it combines content matching with time filtering.

**H2:** Temporal traversal from a seed node achieves higher recall (fewer false negatives) because it finds beliefs with different vocabulary that are structurally adjacent to relevant results.

**H3:** The hybrid (FTS5 seed + temporal expansion) dominates both pure approaches on F1@10.

### Null Hypothesis

Timestamp-filtered FTS5 achieves both higher precision and higher recall than traversal. Temporal structure provides no additional value for scoped queries.

### Method

1. **Define 12 time-scoped queries** across 3 categories:

   **Category A: Time-range queries (4 queries)**
   - "What beliefs were created on April 11?"
   - "What corrections happened in the last 24 hours?"
   - "What requirements were added this week?"
   - "What changed after session cd89e2a1fac3?"

   **Category B: Topic + time queries (4 queries)**
   - "What did we decide about typing annotations recently?"
   - "What's the latest on FTS5 retrieval?"
   - "Recent beliefs about Bayesian confidence?"
   - "What about temporal edges in the last session?"

   **Category C: Adjacency + time queries (4 queries)**
   - "What was discussed right before the typing correction?"
   - "What followed the FTS5 scaling discussion?"
   - "What beliefs preceded the locked-belief penalty finding?"
   - "What came after the onboarding scan?"

2. **Build ground truth.** For each query, manually identify all relevant beliefs (expect 5-20 per query). Use content inspection + timestamp verification.

3. **Run 4 retrieval methods:**

   - **Method A (timestamp filter):** SQL WHERE created_at BETWEEN start AND end, ordered by created_at DESC, LIMIT 20
   - **Method B (FTS5 + timestamp):** FTS5 search with query keywords, WHERE created_at BETWEEN start AND end, top 20
   - **Method C (seed + traverse):** Find seed belief via FTS5, then BFS along TEMPORAL_NEXT + THREAD edges (from Exp 71-72), collect up to 20 beliefs
   - **Method D (hybrid):** FTS5 + timestamp top 10, then expand each via TEMPORAL_NEXT 2 hops, deduplicate, re-rank by FTS5 score, top 20

4. **Measure per query category:**

| Metric | Definition |
|--------|-----------|
| Precision@10 | Fraction of top 10 results that are relevant |
| Recall@20 | Fraction of ground-truth beliefs found in top 20 |
| F1@10 | Harmonic mean of precision@10 and recall@10 |
| MRR | Reciprocal rank of first relevant result |
| Unique finds | Beliefs found by this method that no other method found |
| Latency | Wall-clock time per query (ms) |

5. **Analyze by category.** Expectation:
   - Category A: Method A dominates (pure time queries need no content matching)
   - Category B: Method B dominates (content + time = standard search)
   - Category C: Method C or D dominates (adjacency requires structural links)

### Data Needed

- TEMPORAL_NEXT and THREAD edges from Exp 71-72 (or timestamp-derived fallback if those haven't run yet)
- Live DB beliefs table
- FTS5 index (search_index virtual table already exists in the DB)
- Ground truth: 12 queries x ~10 relevant beliefs = ~120 annotations

### Computational Cost

- 12 queries x 4 methods = 48 retrievals
- FTS5 queries: < 10ms each
- BFS traversals: < 5ms each (graph is sparse, 3-hop BFS visits ~10 nodes)
- Total compute: < 2 seconds
- Ground truth annotation: ~45 minutes
- Total: < 1 minute compute + 45 minutes annotation

### Dependency

This experiment depends on Exp 71 (TEMPORAL_NEXT edges) and optionally Exp 72 (THREAD edges). If run before those, Method C falls back to timestamp-inferred adjacency (sort by created_at, take neighbors), which is the baseline we want to beat.

---

## Execution Order

| Exp | Depends On | Priority | Rationale |
|-----|-----------|----------|-----------|
| 71 | None | P0 | Foundation -- creates the belief-level temporal chain |
| 72 | 71 | P1 | Requires TEMPORAL_NEXT chain as input |
| 73 | None | P1 | Independent -- uses timestamps only |
| 74 | 71, 72 | P2 | Integration test -- compares all edge types |

Experiments 71 and 73 can run in parallel. Experiment 72 requires 71's output. Experiment 74 is the integration test that consumes all prior outputs.

## Cost Summary

| Exp | Compute | Annotation | New Edges |
|-----|---------|-----------|-----------|
| 71 | < 2 min | 30 min | ~17K TEMPORAL_NEXT + ~50 SESSION_BOUNDARY |
| 72 | < 1 min | 45 min | ~500-2000 THREAD edges (depends on threshold) |
| 73 | < 30 sec | 20 min | ~68K CO_OCCURRED (capped) |
| 74 | < 1 min | 45 min | 0 (consumes edges from 71-73) |
| **Total** | **< 5 min** | **~2.5 hours** | **~85K edges** |

## Key Risk

The biggest risk is that the 17K beliefs were bulk-created during onboarding scans with artificial timestamps (not real conversation timestamps). If created_at reflects scan time rather than the original content's temporal context, all temporal edges will encode "order of scanning" rather than "order of discussion." Exp 71 should start by characterizing the timestamp distribution to confirm whether temporal ordering is meaningful.

## Decision Gate

After Exp 71, check: does the timestamp collision rate exceed 50%? If yes, the timestamps are too coarse for belief-level TEMPORAL_NEXT and we should pivot to observation-level temporal chains instead (observations have richer session context).
