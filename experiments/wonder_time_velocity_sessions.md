# Wonder: Session Velocity Tracking and Cross-Session Temporal Linking

**Date:** 2026-04-11
**Status:** Design (pre-experiment)
**Predecessors:** Exp 19 (time as graph dimension), Exp 58c (hour-scale velocity-scaled decay), Exp 57-60 (decay architecture)
**Implements:** CS-005 (maturity inflation), REQ-024 (session metrics)
**Gap Source:** DESIGN_VS_REALITY.md -- "Session velocity tracking -- NOT BUILT"

---

## Problem Statement

Exp 58c proved that velocity-scaled decay is the strongest mechanism for CS-005 (maturity inflation). Items from fast sprints (>10 items/hour) should decay 10x faster than deep-work items. The experiment validated the math against project-a decision data: fast-sprint outputs score 0.273 vs locked constraints at 0.804 by next morning.

None of this was built. The `sessions` table exists in the schema with `started_at`, `completed_at`, and metric counters (`beliefs_created`, `corrections_detected`, etc.), but it has zero rows. The server creates sessions on first tool call, but no velocity computation, no velocity-scaled decay, and no cross-session topic linking exists.

There are 14 logical sessions detectable from observation/belief metadata in the DB, but no session-level analytics run against them.

Meanwhile, cross-session temporal linking is completely absent. When a topic appears across sessions 3, 7, and 12, there is no way to trace that evolution. Exp 19 recommended Model 3 (time as structural dimension with TEMPORAL_NEXT and CROSS_SESSION edges) combined with Model 2 (content-aware decay). Only the decay piece was built.

This document designs four interconnected experiments and the implementation plan to close these gaps.

---

## Experiment 75: Session Velocity Measurement and Calibration

### Objective

Measure actual velocity patterns in the 14 existing sessions. Define the velocity -> half-life multiplier function. Test whether velocity-scaled decay improves retrieval quality vs flat decay on real agentmemory data.

### Phase 1: Reconstruct Session Boundaries from Existing Data

The sessions table is empty, but observations and beliefs have `created_at` timestamps. Reconstruct session boundaries using gap detection:

```
Algorithm:
1. Collect all observation + belief timestamps, sorted ascending.
2. Compute inter-item gaps (time between consecutive items).
3. Session boundary = gap > T_gap (candidate: 30 minutes).
4. Validate against known session count (14 from metadata analysis).
5. Tune T_gap if boundary count diverges from expected 14.
```

Output: a list of (session_start, session_end, item_count) tuples.

### Phase 2: Velocity Profile Analysis

For each reconstructed session, compute:

| Metric | Formula |
|---|---|
| Duration (hours) | `session_end - session_start`, min 0.5h |
| Belief count | beliefs created within session window |
| Correction count | beliefs with `source_type = 'user_corrected'` in window |
| Observation count | observations in window |
| Belief velocity | beliefs / duration_hours |
| Correction velocity | corrections / duration_hours |
| Total item velocity | (beliefs + observations) / duration_hours |

Classify each session into velocity tiers (from Exp 58c):

| Tier | Threshold (items/hr) | Scale Factor | Interpretation |
|---|---|---|---|
| Sprint | >10 | 0.1 | Rapid-fire output, low scrutiny per item |
| Moderate | 5-10 | 0.5 | Active work, some deliberation |
| Steady | 2-5 | 0.8 | Normal pace, moderate scrutiny |
| Deep | <2 | 1.0 | Deliberate, high scrutiny per item |

### Phase 3: Velocity-Scaled Decay vs Flat Decay

Test whether velocity-scaled decay produces better retrieval ranking than the current flat type-aware decay.

**Setup:**
- Take the full belief set from the DB.
- Assign each belief to a reconstructed session.
- Compute velocity per session.
- Score all beliefs at T=now using:
  - A) Current flat type-aware decay (production `scoring.py`)
  - B) Velocity-scaled decay: `half_life_effective = DECAY_HALF_LIVES[type] * velocity_scale(session_velocity)`

**Evaluation:**
- For each locked belief (ground truth "important"), check its rank in the score-sorted list.
- For each superseded belief (ground truth "should be low"), check its rank.
- Metric: mean reciprocal rank (MRR) of locked beliefs. Lower rank for superseded beliefs.
- Also: score separation ratio = mean(locked scores) / mean(unlocked-from-sprint scores). Exp 58c showed 0.804 / 0.273 = 2.95x. Target: >2.0x separation.

### Phase 4: Calibrate the Multiplier Function

The Exp 58c velocity_scale function is a 4-tier step function:

```python
def velocity_scale(velocity: float) -> float:
    if velocity > 10.0:
        return 0.1
    if velocity >= 5.0:
        return 0.5
    if velocity >= 2.0:
        return 0.8
    return 1.0
```

Test alternatives:
- **Continuous:** `scale = max(0.1, 1.0 / (1.0 + velocity / 5.0))` -- smooth sigmoid-like curve.
- **Log-scaled:** `scale = max(0.1, 1.0 - 0.3 * log2(1 + velocity))` -- logarithmic compression.
- **Step function (Exp 58c):** the 4-tier version above.

Pick whichever produces the best score separation ratio on the real data. If all three are within 10% of each other, use the step function (simplest, most interpretable).

### Success Criteria

1. Velocity reconstruction produces session boundaries consistent with the known 14 sessions (within +/- 2).
2. Velocity-scaled decay achieves >2.0x score separation between locked beliefs and sprint-origin unlocked beliefs.
3. Velocity-scaled decay does not degrade MRR for locked beliefs vs flat decay (non-inferiority).

### Script Location

`experiments/exp75_session_velocity.py`

---

## Session Metadata Tracking: Schema and Implementation Plan

### Current Schema

The `sessions` table already has:

```sql
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    model TEXT,
    project_context TEXT,
    summary TEXT,
    retrieval_tokens INTEGER NOT NULL DEFAULT 0,
    classification_tokens INTEGER NOT NULL DEFAULT 0,
    beliefs_created INTEGER NOT NULL DEFAULT 0,
    corrections_detected INTEGER NOT NULL DEFAULT 0,
    searches_performed INTEGER NOT NULL DEFAULT 0,
    feedback_given INTEGER NOT NULL DEFAULT 0
);
```

### Proposed Additions

Add three columns to `sessions`:

```sql
ALTER TABLE sessions ADD COLUMN velocity_items_per_hour REAL;
ALTER TABLE sessions ADD COLUMN velocity_tier TEXT;           -- 'sprint', 'moderate', 'steady', 'deep'
ALTER TABLE sessions ADD COLUMN topics_json TEXT;             -- JSON array of top-N topic keywords
```

`velocity_items_per_hour` and `velocity_tier` are computed at session completion (when `complete_session()` is called). `topics_json` is computed by running FTS5 term frequency on beliefs created in that session and taking the top 10 terms.

### Implementation Changes

**1. `store.py` -- `complete_session()` computes velocity:**

```python
def complete_session(self, session_id: str, summary: str = "") -> None:
    ts: str = _now()
    session = self.get_session(session_id)
    if session is None:
        return

    started = _parse_iso(session.started_at)
    ended = _parse_iso(ts)
    duration_hours = max(0.5, (ended - started).total_seconds() / 3600.0)
    items = session.beliefs_created + session.corrections_detected
    velocity = items / duration_hours

    if velocity > 10.0:
        tier = "sprint"
    elif velocity >= 5.0:
        tier = "moderate"
    elif velocity >= 2.0:
        tier = "steady"
    else:
        tier = "deep"

    self._conn.execute(
        """UPDATE sessions SET
            completed_at = ?, summary = ?,
            velocity_items_per_hour = ?, velocity_tier = ?
           WHERE id = ?""",
        (ts, summary or None, velocity, tier, session_id),
    )
    self._conn.commit()
```

**2. `scoring.py` -- `decay_factor()` accepts optional velocity_scale:**

Add a `session_velocity` parameter to `decay_factor()`. When provided, multiply the half-life by the velocity scale factor. This is backward-compatible: omitting `session_velocity` preserves current behavior.

**3. `server.py` -- Ensure session completion on tool shutdown:**

The server currently creates sessions but does not reliably complete them. Add a completion call when the MCP connection closes or when a new session is created (completing the previous one).

**4. Migration path:**

Add migration in `_migrate_sessions()` to add the three new columns. Backfill existing rows (if any exist by then) using the reconstruction algorithm from Exp 75 Phase 1.

---

## Experiment 76: Cross-Session Topic Continuity

### Objective

Detect when the same topic appears across multiple sessions. Create CROSS_SESSION edges linking related beliefs across session boundaries. Test whether these edges improve retrieval for temporal-evolution queries ("how did X evolve?").

### Phase 1: Topic Extraction per Session

For each session (reconstructed from Exp 75 or from populated sessions table):

1. Collect all belief content from that session.
2. Run FTS5 term extraction to get term frequency vectors.
3. Compute a session topic signature: top-K terms by frequency, excluding stop words and common programming terms.
4. Store as `topics_json` on the session row.

### Phase 2: Cross-Session Similarity

Compare session topic signatures pairwise:

```
Algorithm:
For sessions i, j where i < j:
    overlap = |topics_i INTERSECT topics_j| / min(|topics_i|, |topics_j|)
    if overlap > T_sim (candidate: 0.3):
        mark (session_i, session_j) as topic-linked
```

Also test belief-level linking:
```
For each belief B in session j:
    Run FTS5 search using B.content against beliefs from sessions < j
    If top match score > T_fts (candidate: BM25 rank 1 score > 5.0):
        Create candidate CROSS_SESSION edge (match.id -> B.id)
```

### Phase 3: Create CROSS_SESSION Edges

For each candidate edge from Phase 2:

```sql
INSERT INTO graph_edges (from_id, to_id, edge_type, weight, reason, created_at)
VALUES (?, ?, 'CROSS_SESSION', ?, 'topic continuity: <shared terms>', ?);
```

Weight = overlap score (0.0 to 1.0). Reason includes the shared topic terms for interpretability.

Use the `graph_edges` table (not `edges`) because these link across sessions and may involve beliefs that are not direct parent-child relationships.

### Phase 4: Temporal Evolution Queries

Test whether CROSS_SESSION edges improve retrieval for "how did X evolve?" queries.

**Test set:** Manually identify 5-10 topics that span multiple sessions (e.g., "decay architecture", "correction detection", "retrieval pipeline"). For each topic, write a temporal evolution query.

**Evaluation:**

| Condition | Method |
|---|---|
| Baseline (no edges) | FTS5 search, score, return top-K |
| With CROSS_SESSION edges | FTS5 search, then BFS expand along CROSS_SESSION edges, re-score, return top-K |

Metrics:
- Coverage: what fraction of sessions containing the topic are represented in top-K results?
- Temporal ordering: are results ordered chronologically within the topic thread?
- Recall: do the results include the most recent belief about the topic?

### Phase 5: Edge Pruning

CROSS_SESSION edges will accumulate. Test pruning strategies:
- Remove edges where weight < 0.2 (weak overlap).
- Remove edges older than 90 days unless one endpoint is locked.
- Limit to top-3 cross-session links per belief (prevent fan-out explosion).

### Success Criteria

1. Topic extraction produces non-trivial signatures (>5 terms per session, <80% overlap between all session pairs).
2. CROSS_SESSION edges connect at least 3 multi-session topic threads.
3. Temporal evolution queries with CROSS_SESSION expansion achieve >80% session coverage vs <50% for baseline FTS5-only.
4. Edge count stays under 5x belief count (manageable graph density).

### Script Location

`experiments/exp76_cross_session_linking.py`

---

## Session-Level Decay vs Belief-Level Decay

### The Question

Currently, decay is purely per-belief: each belief's score decays based on its own `created_at`, `belief_type`, and (once implemented) its session's velocity. Should there also be a session-level signal that modifies all beliefs from that session uniformly?

### Argument For Session-Level Signals

Some sessions have a clear character that should affect all their outputs:

| Session type | Signal | Effect |
|---|---|---|
| Brainstorm/exploration | High belief count, low correction count, no locks | Weight everything lower (0.5x) |
| Correction session | High correction count, multiple locks | Weight locked items at 1.0, weight non-locked at 0.8 |
| Decision session | Moderate pace, explicit decisions, some locks | Weight at 1.0 (baseline) |
| Debugging session | High observation count, low belief count | Weight beliefs at 0.7 (tentative conclusions during debug) |
| Onboarding session | Bulk ingestion, scanner output | Weight at 0.6 (unvalidated bulk import) |

### Argument Against Session-Level Signals

- Belief-level signals already capture most of this. Locked beliefs are immune to decay. High-velocity beliefs decay faster via velocity scaling. Type-aware half-lives already handle the content dimension.
- Session-level signals risk penalizing a good decision that happened to occur during a brainstorm. One locked correction from a brainstorm session is still a locked correction.
- The interaction between session-level and belief-level signals creates a multiplicative complexity that is hard to reason about and harder to debug.

### Recommendation: Belief-Level with Session Velocity, No Session-Level Override

Do not implement session-level decay as a separate mechanism. Instead:

1. Use velocity-scaled decay at the belief level (Exp 75 output). This already captures the "fast sprint vs deep work" dimension.
2. Use the session's `corrections_detected` and `beliefs_created` counts as metadata for display and diagnostics, not for scoring.
3. If a session produced 3 locked corrections, those corrections are individually protected by lock immunity. No session-level boost needed.
4. If a session was a brainstorm, its unlocked beliefs will naturally decay faster (high velocity -> low half-life multiplier). No session-level penalty needed.

The one exception: onboarding sessions (bulk scanner output). These should get a source_type of `"document_old"` or `"document_recent"` which already carries a 0.8x or 1.0x source weight in `_SOURCE_WEIGHTS`. No new mechanism needed.

### What to Track for Diagnostics (Not Scoring)

Add to the session model (display only, not used in `score_belief()`):

| Field | Computation | Purpose |
|---|---|---|
| `session_character` | Heuristic from velocity + correction ratio | "brainstorm", "correction", "decision", "debug", "onboard" |
| `lock_ratio` | locked_beliefs_created / beliefs_created | How many items were deemed permanent |
| `correction_ratio` | corrections_detected / beliefs_created | How contentious was this session |

These inform the agent ("your last session was a brainstorm that produced 12 beliefs, 0 of which were locked") without affecting scoring.

---

## Implementation Priority and Dependencies

### Dependency Graph

```
Exp 75 (velocity measurement)
  |
  +--> Schema changes (add velocity columns)
  |      |
  |      +--> scoring.py (velocity-scaled decay_factor)
  |      |
  |      +--> server.py (compute velocity at session completion)
  |
  +--> Exp 76 (cross-session linking)
         |
         +--> Topic extraction per session
         |
         +--> CROSS_SESSION edge creation
         |
         +--> Retrieval expansion along CROSS_SESSION edges
```

### Suggested Order

1. **Exp 75** -- Run the velocity analysis on existing data. This is pure analysis, no code changes. Validates the velocity tiers and multiplier function against real agentmemory data.

2. **Schema migration** -- Add `velocity_items_per_hour`, `velocity_tier`, `topics_json` to sessions table. Implement `complete_session()` velocity computation.

3. **Velocity-scaled decay** -- Modify `scoring.py:decay_factor()` to accept optional session velocity. Wire it through `score_belief()` and `retrieval.py`.

4. **Exp 76** -- Run cross-session topic analysis. This depends on having session boundaries (from Exp 75 or from populated sessions table).

5. **CROSS_SESSION edges** -- If Exp 76 shows retrieval improvement, implement edge creation in the ingestion pipeline.

### Estimated Effort

| Item | Effort |
|---|---|
| Exp 75 script + analysis | 2-3 hours |
| Schema migration + velocity computation | 1-2 hours |
| Velocity-scaled decay in scoring.py | 1 hour |
| Exp 76 script + analysis | 3-4 hours |
| CROSS_SESSION edge creation (if validated) | 2-3 hours |
| Tests for all of the above | 2-3 hours |

Total: 11-16 hours of implementation work, assuming Exp 75 and 76 validate the hypotheses.

---

## Open Questions

1. **Gap threshold for session boundary detection.** 30 minutes is the starting candidate. Should this be adaptive (e.g., based on time-of-day patterns)?

2. **Velocity denominator.** Should velocity use `beliefs_created` only, or `beliefs_created + observations_created`? Observations are cheaper (no classification), so a session that mostly observes is not really "sprinting" in the same way.

3. **Cross-session edge direction.** Should CROSS_SESSION edges point forward (old -> new) or backward (new -> old)? Forward makes "how did X evolve?" traversal natural. Backward makes "what was the origin of X?" traversal natural. Recommendation: forward (old -> new), since temporal evolution queries are the primary use case.

4. **FTS5 vs HRR for cross-session matching.** Phase 2 of Exp 76 proposes FTS5 term overlap. Should HRR vector similarity also be tested as an alternative or complement? HRR might catch semantic similarity that term overlap misses (e.g., "decay function" and "temporal scoring" are the same topic but share no terms).

5. **Session completion reliability.** The MCP server creates sessions but may not always complete them cleanly (crashes, timeouts, user closes terminal). How should incomplete sessions be handled for velocity computation? Candidate: use the timestamp of the last checkpoint as a proxy for `completed_at`.
