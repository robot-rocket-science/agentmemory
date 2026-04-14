# Unified Dynamic Edge System Design

**Date:** 2026-04-14
**Status:** Architecture design -- ready for review
**Synthesizes:** GRAPH_CONSTRUCTION_RESEARCH, BAYESIAN_RESEARCH, INFORMATION_THEORY_RESEARCH, FEEDBACK_LOOP_PLAN, EDGE_TYPE_TAXONOMY, scoring.py, retrieval.py, relationship_detector.py, semantic_linker.py

---

## Motivation

Edges in the current system are static. Once created by `relationship_detector.py` or `semantic_linker.py`, an edge's weight never changes. It has no feedback history, no lifecycle, and no mechanism for self-correction. The belief system has Beta(alpha, beta) updating, Thompson sampling, decay curves, and feedback loops. Edges have none of this.

This document designs a unified dynamic edge system where edges are born, tested, strengthened, weakened, promoted, and pruned -- mirroring the belief lifecycle but adapted for relational semantics.

---

## 1. Edge Lifecycle Model

### 1.1 Birth: What Triggers Edge Creation

Edges are born through four channels, each producing edges at different initial confidence levels:

| Channel | Trigger | Edge Types Produced | Initial alpha/beta | Rationale |
|---|---|---|---|---|
| **Relationship detector** | New belief ingested; Jaccard overlap with existing beliefs | CONTRADICTS, SUPPORTS, RELATES_TO | Beta(1.0, 1.0) | Heuristic detection; uncertain until validated by traversal |
| **Semantic linker** | Post-onboarding LLM batch | RELATES_TO | Beta(3.0, 1.0) | LLM assessment is more reliable than Jaccard; start with mild confidence |
| **User correction** | `correct()` creates new belief superseding old | SUPERSEDES, CONTRADICTS | Beta(9.0, 1.0) | User-initiated; high confidence, hard to dislodge |
| **Co-retrieval** | Two beliefs retrieved and both used in same session | RELATES_TO | Beta(0.5, 0.5) | Jeffreys prior; weakest signal, needs evidence to survive |

The co-retrieval channel is new. When two beliefs are both retrieved in the same `search()` call and both receive "used" feedback, the system creates a RELATES_TO edge between them if none exists. This captures implicit associations the user demonstrates through usage patterns.

```python
def maybe_create_co_retrieval_edge(
    store: MemoryStore,
    used_belief_ids: list[str],
    session_id: str,
) -> int:
    """Create RELATES_TO edges between co-used beliefs.

    Only fires when 2+ beliefs from the same retrieval batch
    both receive 'used' feedback. Max 3 new edges per batch
    to prevent quadratic blowup.
    """
    created: int = 0
    for i, id_a in enumerate(used_belief_ids):
        for id_b in used_belief_ids[i + 1:]:
            if created >= 3:
                return created
            if not store.edge_exists(id_a, id_b):
                store.insert_edge(
                    from_id=id_a,
                    to_id=id_b,
                    edge_type=EDGE_RELATES_TO,
                    alpha=0.5,
                    beta_param=0.5,
                    reason=f"co_retrieval_used (session={session_id})",
                )
                created += 1
    return created
```

### 1.2 Strengthening: Positive Evidence

An edge gains confidence (alpha incremented) when:

| Event | alpha increment | Condition |
|---|---|---|
| Traversed during retrieval AND destination belief marked "used" | +1.0 | The edge led to a useful belief |
| Traversed during retrieval AND destination belief marked "used" AND source also "used" | +0.5 bonus | Both endpoints were useful; the connection itself was valuable |
| LLM semantic linker re-confirms the relationship in a later batch | +2.0 | Independent re-assessment agrees |
| User explicitly creates a related correction | +1.0 | User action corroborates the relationship |

### 1.3 Weakening: Negative Evidence

An edge gains negative evidence (beta_param incremented) when:

| Event | beta_param increment | Condition |
|---|---|---|
| Traversed during retrieval AND destination belief marked "ignored" | +0.5 | Edge led somewhere unhelpful (mild penalty -- the query context may just not have needed it) |
| Traversed during retrieval AND destination belief marked "harmful" | +2.0 | Edge led to harmful content; strong penalty |
| One endpoint belief superseded | +1.0 | The factual basis for the connection changed |
| Contradiction detected between linked beliefs | +1.0 on SUPPORTS edges between them | A SUPPORTS edge between contradicting beliefs is wrong |

Note: "ignored" gets a weaker penalty than for beliefs (where "ignored" gets zero). For edges, being traversed and leading to an ignored belief is mild evidence the edge is noisy. For beliefs, being irrelevant to a query says nothing about correctness.

### 1.4 Death: What Triggers Removal

Edges are never hard-deleted. They are soft-pruned by setting `pruned_at` timestamp. Pruning triggers:

| Condition | Threshold | Rationale |
|---|---|---|
| Confidence drops below floor | `alpha / (alpha + beta) < 0.15` | Edge has been consistently unhelpful |
| Both endpoints superseded | Always prune | Dead-end connection |
| One endpoint soft-deleted | Always prune | Dangling reference |
| Edge age exceeds TTL with no traversals | 90 days for RELATES_TO, never for SUPPORTS/CONTRADICTS | Unused weak edges are noise; strong semantic edges persist |
| Conflict detected (see 4.3) | Manual or auto-resolve | Contradictory edges on same pair |

Pruned edges remain in the database for audit purposes but are excluded from all traversal queries via `WHERE pruned_at IS NULL`.

### 1.5 Transformation: Type Promotion and Demotion

Edges can change type based on accumulated evidence. This is the "evolutionary" aspect -- edges adapt to what the evidence shows.

**Promotion rules (evidence accumulates):**

```
RELATES_TO -> SUPPORTS
  Condition: confidence > 0.75 AND both endpoints have same belief_type
             AND no negation divergence between endpoint contents
  Evidence needed: ~6 successful traversals from Beta(1,1) start

RELATES_TO -> CONTRADICTS
  Condition: confidence > 0.60 AND negation_divergence(a.content, b.content)
             detected after creation
  Evidence needed: ~3 successful traversals + negation signal
```

**Demotion rules (evidence contradicts current type):**

```
SUPPORTS -> RELATES_TO
  Condition: confidence drops below 0.40
  Trigger: endpoint beliefs diverge in meaning after updates

CONTRADICTS -> RELATES_TO
  Condition: user resolves the contradiction (both beliefs updated)
  Trigger: explicit user action via correct() on either endpoint
```

Transformation is logged in `edge_history` (new table, see Section 5) for audit trail.

---

## 2. Edge Scoring Architecture

### 2.1 Edge Parameters

Each edge carries:

| Parameter | Type | Purpose |
|---|---|---|
| `alpha` | REAL | Beta distribution success count |
| `beta_param` | REAL | Beta distribution failure count |
| `traversal_count` | INTEGER | Total times this edge was followed during retrieval |
| `last_traversed_at` | TEXT | ISO 8601; for recency and TTL calculations |
| `created_at` | TEXT | ISO 8601; for age-based TTL |
| `pruned_at` | TEXT | ISO 8601; NULL = active; non-NULL = soft-pruned |

The existing `weight` column is retained for backward compatibility during migration but is superseded by `alpha / (alpha + beta_param)` as the effective weight.

### 2.2 Effective Edge Score

The edge score used for BFS priority is a composite of Bayesian confidence, type weight, and recency:

```python
def edge_score(edge: Edge, current_time: datetime) -> float:
    """Composite score for BFS traversal priority.

    Components:
    - bayesian_confidence: alpha / (alpha + beta_param)
    - type_weight: from _EDGE_TYPE_WEIGHTS (CONTRADICTS=2.0, SUPPORTS=1.8, etc.)
    - recency_factor: 1.0 + 0.5^(hours_since_traversal / 168)
      (half-life of 1 week; recently-traversed edges get mild boost)
    - thompson_sample: sample from Beta(alpha, beta_param) for exploration
    """
    confidence: float = edge.alpha / (edge.alpha + edge.beta_param)
    type_w: float = _EDGE_TYPE_WEIGHTS.get(edge.edge_type, 0.5)

    # Recency of last traversal (not creation)
    recency: float = 1.0
    if edge.last_traversed_at is not None:
        age_hours: float = (current_time - parse_iso(edge.last_traversed_at)).total_seconds() / 3600.0
        recency = 1.0 + math.pow(0.5, age_hours / 168.0)

    # Thompson sampling for exploration of uncertain edges
    sample: float = random.betavariate(edge.alpha, edge.beta_param)

    # Final score: deterministic component * stochastic component
    # The deterministic part (confidence * type_w * recency) anchors ranking.
    # The stochastic part (sample) introduces exploration of uncertain edges.
    return (0.7 * confidence + 0.3 * sample) * type_w * recency
```

### 2.3 Edge Score in BFS Traversal

The current `expand_graph()` sorts neighbors by `edge.weight * type_weight`. Replace with:

```python
# In expand_graph(), replace the sorting key:
def _effective_weight(pair: tuple[Belief, Edge]) -> tuple[float, str]:
    _, e = pair
    score: float = edge_score(e, current_time)
    return (-score, e.created_at)  # Negate for descending sort
```

This means BFS naturally prefers:
1. High-confidence, frequently-validated edges (exploitation)
2. Uncertain but potentially valuable edges (exploration via Thompson)
3. Recently-used edges (recency boost)
4. Semantically important edge types (type weight)

### 2.4 Edge Score Interaction with Belief Score

When a belief is reached via edge traversal, its final retrieval score incorporates the path quality:

```python
def path_adjusted_score(
    belief_score: float,
    path_edges: list[Edge],
    current_time: datetime,
) -> float:
    """Adjust belief score by the quality of the path that reached it.

    For BFS-discovered beliefs (not direct FTS5 hits), the belief score
    is multiplied by the weakest edge in the path. This ensures that
    a high-scoring belief reached via a dubious edge is ranked lower
    than the same belief reached via a strong edge.
    """
    if not path_edges:
        return belief_score  # Direct hit, no path adjustment

    min_edge_conf: float = min(
        e.alpha / (e.alpha + e.beta_param) for e in path_edges
    )
    # Path quality is the weakest link (min composition, per GRAPH_CONSTRUCTION_RESEARCH)
    return belief_score * min_edge_conf
```

This implements the "chain is only as strong as its weakest link" principle from GRAPH_CONSTRUCTION_RESEARCH Section 2.

### 2.5 Update Rule on Traversal

Every time an edge is traversed during retrieval:

```python
def record_edge_traversal(store: MemoryStore, edge_id: int) -> None:
    """Record that an edge was traversed. Updates traversal_count and timestamp.

    Does NOT update alpha/beta -- that happens later when feedback arrives.
    Traversal alone is not evidence of quality; it just means the edge
    was on a path the BFS explored.
    """
    store.execute(
        """UPDATE edges SET
           traversal_count = traversal_count + 1,
           last_traversed_at = ?
           WHERE id = ?""",
        (_now(), edge_id),
    )
```

The alpha/beta update happens asynchronously when feedback arrives (Section 3).

---

## 3. Feedback Loop Design

### 3.1 Credit Assignment: Which Edges Get Credit

When a belief receives feedback ("used", "ignored", "harmful"), credit propagates to the edges that led to its retrieval. The key question: which edges?

**Rule: Only edges actually traversed in the retrieval path receive credit.**

The retrieval pipeline must track which edges were traversed to reach each belief. This requires a small extension to `expand_graph()`:

```python
@dataclass
class TraversalRecord:
    """Record of edges traversed to reach a belief."""
    belief_id: str
    edges_traversed: list[int]  # edge IDs in path order
    hop_distance: int
    source: str  # "fts5", "hrr", "bfs"
```

For direct FTS5 hits: `edges_traversed = []` (no edges involved).
For HRR hits: `edges_traversed = []` (HRR uses holographic encoding, not explicit edges).
For BFS hits: `edges_traversed = [edge_id_hop1, edge_id_hop2, ...]`.

Only BFS-discovered beliefs generate edge feedback.

### 3.2 Credit Magnitude

Credit is distributed based on hop distance. Closer edges get more credit because they had more influence on reaching the destination.

```python
def distribute_edge_feedback(
    store: MemoryStore,
    traversal: TraversalRecord,
    outcome: str,  # "used", "ignored", "harmful"
) -> None:
    """Distribute feedback to edges in a traversal path.

    Hop 1 edges get full credit. Each additional hop halves the credit.
    This reflects that the first hop is the strongest signal -- it was
    chosen from among all neighbors of the seed belief.
    """
    for i, edge_id in enumerate(traversal.edges_traversed):
        hop: int = i + 1
        discount: float = 1.0 / (2.0 ** (hop - 1))  # 1.0, 0.5, 0.25, ...

        if outcome == "used":
            alpha_delta: float = 1.0 * discount
            store.execute(
                "UPDATE edges SET alpha = alpha + ? WHERE id = ?",
                (alpha_delta, edge_id),
            )
        elif outcome == "harmful":
            beta_delta: float = 2.0 * discount  # Harmful gets 2x penalty
            store.execute(
                "UPDATE edges SET beta_param = beta_param + ? WHERE id = ?",
                (beta_delta, edge_id),
            )
        elif outcome == "ignored":
            beta_delta = 0.5 * discount  # Mild penalty
            store.execute(
                "UPDATE edges SET beta_param = beta_param + ? WHERE id = ?",
                (beta_delta, edge_id),
            )

    # Record in edge_history for audit
    store.execute(
        """INSERT INTO edge_history (edge_id, event_type, detail, created_at)
           VALUES (?, ?, ?, ?)""",
        (
            traversal.edges_traversed[0] if traversal.edges_traversed else None,
            f"feedback_{outcome}",
            f"path_len={len(traversal.edges_traversed)}",
            _now(),
        ),
    )
```

### 3.3 Co-Retrieval Edge Formation

When two beliefs are retrieved in the same search batch and both receive "used" feedback within the same session:

```python
def process_co_retrieval(
    store: MemoryStore,
    session_id: str,
    used_belief_ids: list[str],
) -> int:
    """Form RELATES_TO edges between co-used beliefs.

    Conditions:
    1. Both beliefs were in the same search result set
    2. Both received 'used' feedback (explicit or auto)
    3. No existing edge between them (any type)
    4. Max 3 new edges per batch (prevent combinatorial explosion)

    Initial parameters: Jeffreys prior Beta(0.5, 0.5)
    This is the weakest starting point -- the edge must prove itself
    through subsequent traversals to survive pruning.
    """
    created: int = 0
    for i, id_a in enumerate(used_belief_ids):
        if created >= 3:
            break
        for id_b in used_belief_ids[i + 1:]:
            if created >= 3:
                break
            if store.edge_exists_any_type(id_a, id_b):
                continue
            store.insert_edge(
                from_id=id_a,
                to_id=id_b,
                edge_type=EDGE_RELATES_TO,
                alpha=0.5,
                beta_param=0.5,
                reason=f"co_retrieval (session={session_id})",
            )
            created += 1
    return created
```

### 3.4 Feedback Timing

Edge feedback is processed at the same time as belief feedback -- during `_process_auto_feedback()` in the server. The sequence:

```
search() called (batch N)
  |
  +-- Process batch N-1:
  |     For each belief in N-1:
  |       1. Determine outcome (used/ignored) -- existing logic
  |       2. Update belief alpha/beta -- existing logic
  |       3. NEW: Look up TraversalRecord for this belief
  |       4. NEW: Call distribute_edge_feedback() for BFS-discovered beliefs
  |       5. NEW: Collect used_belief_ids for co-retrieval processing
  |     After all beliefs processed:
  |       6. NEW: Call process_co_retrieval() with used_belief_ids
  |
  +-- Execute new search, populate batch N buffer
  +-- Return results
```

---

## 4. Maintenance Operations

### 4.1 Background Edge Pruning

Runs periodically (on session start, or every N searches). Pruning is conservative -- it only removes edges that have demonstrated they are noise.

```python
def prune_edges(store: MemoryStore) -> int:
    """Prune low-quality and stale edges. Returns count pruned.

    Criteria (any match triggers pruning):
    1. Confidence < 0.15 (consistently unhelpful)
    2. RELATES_TO edge with no traversals in 90 days
    3. Either endpoint is soft-deleted (valid_to IS NOT NULL)
    4. Both endpoints superseded

    SUPPORTS and CONTRADICTS edges are never age-pruned (criterion 2)
    because they encode semantic relationships that may be needed
    for contradiction detection even if not recently traversed.
    """
    ts: str = _now()
    pruned: int = 0

    # Criterion 1: Low confidence
    pruned += store.execute(
        """UPDATE edges SET pruned_at = ?
           WHERE pruned_at IS NULL
           AND (alpha / (alpha + beta_param)) < 0.15
           AND (alpha + beta_param) > 3.0""",  # Only prune after enough evidence
        (ts,),
    ).rowcount

    # Criterion 2: Stale RELATES_TO
    pruned += store.execute(
        """UPDATE edges SET pruned_at = ?
           WHERE pruned_at IS NULL
           AND edge_type = 'RELATES_TO'
           AND (last_traversed_at IS NULL
                OR last_traversed_at < datetime('now', '-90 days'))
           AND created_at < datetime('now', '-90 days')""",
        (ts,),
    ).rowcount

    # Criterion 3: Dangling endpoint
    pruned += store.execute(
        """UPDATE edges SET pruned_at = ?
           WHERE pruned_at IS NULL
           AND (from_id IN (SELECT id FROM beliefs WHERE valid_to IS NOT NULL)
                OR to_id IN (SELECT id FROM beliefs WHERE valid_to IS NOT NULL))""",
        (ts,),
    ).rowcount

    return pruned
```

### 4.2 Edge Promotion

Runs after pruning. Checks whether any RELATES_TO edges have accumulated enough evidence to be promoted to SUPPORTS or CONTRADICTS.

```python
def promote_edges(store: MemoryStore) -> int:
    """Promote RELATES_TO edges with strong evidence to SUPPORTS or CONTRADICTS.

    Promotion to SUPPORTS:
    - confidence > 0.75
    - traversal_count >= 5
    - both endpoints have same belief_type
    - no negation divergence between endpoint contents

    Promotion to CONTRADICTS:
    - confidence > 0.60
    - negation_divergence(a.content, b.content) is True
    - traversal_count >= 3

    Returns count of promoted edges.
    """
    promoted: int = 0
    candidates: list[sqlite3.Row] = store.query(
        """SELECT e.id, e.from_id, e.to_id, e.alpha, e.beta_param,
                  e.traversal_count,
                  a.content AS a_content, a.belief_type AS a_type,
                  b.content AS b_content, b.belief_type AS b_type
           FROM edges e
           JOIN beliefs a ON a.id = e.from_id
           JOIN beliefs b ON b.id = e.to_id
           WHERE e.edge_type = 'RELATES_TO'
             AND e.pruned_at IS NULL
             AND e.traversal_count >= 3
             AND (e.alpha / (e.alpha + e.beta_param)) > 0.60"""
    )

    for row in candidates:
        conf: float = row["alpha"] / (row["alpha"] + row["beta_param"])
        has_negation: bool = negation_divergence(row["a_content"], row["b_content"])

        if has_negation and conf > 0.60:
            new_type = EDGE_CONTRADICTS
        elif not has_negation and conf > 0.75 and row["a_type"] == row["b_type"]:
            new_type = EDGE_SUPPORTS
        else:
            continue

        store.execute(
            "UPDATE edges SET edge_type = ? WHERE id = ?",
            (new_type, row["id"]),
        )
        store.execute(
            """INSERT INTO edge_history (edge_id, event_type, detail, created_at)
               VALUES (?, 'promotion', ?, ?)""",
            (row["id"], f"RELATES_TO -> {new_type} (conf={conf:.2f})", _now()),
        )
        promoted += 1

    return promoted
```

### 4.3 Edge Conflict Detection

Detects impossible states: an edge pair where A SUPPORTS B and A CONTRADICTS B simultaneously.

```python
def detect_edge_conflicts(store: MemoryStore) -> list[dict[str, object]]:
    """Find belief pairs with conflicting edge types.

    A pair (A, B) is in conflict if there exists both a SUPPORTS and
    a CONTRADICTS edge between them (in either direction).

    Returns list of conflict records with edge IDs and confidences.
    """
    conflicts: list[sqlite3.Row] = store.query(
        """SELECT
            s.id AS supports_id, s.alpha AS s_alpha, s.beta_param AS s_beta,
            c.id AS contradicts_id, c.alpha AS c_alpha, c.beta_param AS c_beta,
            s.from_id, s.to_id
           FROM edges s
           JOIN edges c ON (
               (s.from_id = c.from_id AND s.to_id = c.to_id)
               OR (s.from_id = c.to_id AND s.to_id = c.from_id)
           )
           WHERE s.edge_type = 'SUPPORTS'
             AND c.edge_type = 'CONTRADICTS'
             AND s.pruned_at IS NULL
             AND c.pruned_at IS NULL"""
    )

    results: list[dict[str, object]] = []
    for row in conflicts:
        s_conf: float = row["s_alpha"] / (row["s_alpha"] + row["s_beta"])
        c_conf: float = row["c_alpha"] / (row["c_alpha"] + row["c_beta"])
        results.append({
            "from_id": row["from_id"],
            "to_id": row["to_id"],
            "supports_edge_id": row["supports_id"],
            "supports_confidence": s_conf,
            "contradicts_edge_id": row["contradicts_id"],
            "contradicts_confidence": c_conf,
            "resolution": "prune_weaker" if abs(s_conf - c_conf) > 0.3 else "flag_for_review",
        })

    return results
```

**Auto-resolution:** If one edge has confidence > 0.3 higher than the other, prune the weaker one. If they are close (within 0.3), flag for user review.

### 4.4 Graph Health Metrics

Computed on demand (e.g., `status()` MCP tool) or during maintenance:

```python
def edge_health_metrics(store: MemoryStore) -> dict[str, object]:
    """Compute graph health metrics for edges."""
    return {
        "total_edges": store.query("SELECT COUNT(*) FROM edges WHERE pruned_at IS NULL")[0][0],
        "pruned_edges": store.query("SELECT COUNT(*) FROM edges WHERE pruned_at IS NOT NULL")[0][0],
        "by_type": dict(store.query(
            """SELECT edge_type, COUNT(*) FROM edges
               WHERE pruned_at IS NULL GROUP BY edge_type"""
        )),
        "mean_confidence": store.query(
            """SELECT AVG(alpha / (alpha + beta_param)) FROM edges
               WHERE pruned_at IS NULL AND (alpha + beta_param) > 0"""
        )[0][0],
        "low_confidence_count": store.query(
            """SELECT COUNT(*) FROM edges
               WHERE pruned_at IS NULL
               AND (alpha / (alpha + beta_param)) < 0.3
               AND (alpha + beta_param) > 2.0"""
        )[0][0],
        "never_traversed_count": store.query(
            "SELECT COUNT(*) FROM edges WHERE pruned_at IS NULL AND traversal_count = 0"
        )[0][0],
        "conflict_count": len(detect_edge_conflicts(store)),
        "orphan_edges": store.query(
            """SELECT COUNT(*) FROM edges
               WHERE pruned_at IS NULL
               AND (from_id NOT IN (SELECT id FROM beliefs WHERE valid_to IS NULL)
                    OR to_id NOT IN (SELECT id FROM beliefs WHERE valid_to IS NULL))"""
        )[0][0],
    }
```

---

## 5. Schema Changes

### 5.1 Additions to `edges` Table

```sql
-- New columns on existing edges table
ALTER TABLE edges ADD COLUMN alpha REAL NOT NULL DEFAULT 1.0;
ALTER TABLE edges ADD COLUMN beta_param REAL NOT NULL DEFAULT 1.0;
ALTER TABLE edges ADD COLUMN traversal_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE edges ADD COLUMN last_traversed_at TEXT;
ALTER TABLE edges ADD COLUMN pruned_at TEXT;
```

### 5.2 New Table: `edge_history`

Audit trail for edge lifecycle events (promotion, demotion, pruning, feedback).

```sql
CREATE TABLE IF NOT EXISTS edge_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edge_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,    -- 'feedback_used', 'feedback_ignored', 'feedback_harmful',
                                -- 'promotion', 'demotion', 'pruned', 'co_retrieval'
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (edge_id) REFERENCES edges(id)
);

CREATE INDEX IF NOT EXISTS idx_edge_history_edge ON edge_history(edge_id);
CREATE INDEX IF NOT EXISTS idx_edge_history_type ON edge_history(event_type);
```

### 5.3 New Table: `traversal_log`

Records which edges were traversed to reach each belief in each retrieval. Used by the feedback loop for credit assignment.

```sql
CREATE TABLE IF NOT EXISTS traversal_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    belief_id TEXT NOT NULL,
    edge_ids_json TEXT NOT NULL,   -- JSON array of edge IDs in path order
    hop_distance INTEGER NOT NULL,
    source TEXT NOT NULL,          -- 'bfs', 'fts5', 'hrr'
    created_at TEXT NOT NULL,
    FOREIGN KEY (belief_id) REFERENCES beliefs(id)
);

CREATE INDEX IF NOT EXISTS idx_traversal_log_session ON traversal_log(session_id);
CREATE INDEX IF NOT EXISTS idx_traversal_log_belief ON traversal_log(belief_id);
```

### 5.4 Indexes for New Queries

```sql
-- Support pruning queries
CREATE INDEX IF NOT EXISTS idx_edges_pruned ON edges(pruned_at);
CREATE INDEX IF NOT EXISTS idx_edges_confidence ON edges(alpha, beta_param)
    WHERE pruned_at IS NULL;

-- Support traversal tracking
CREATE INDEX IF NOT EXISTS idx_edges_last_traversed ON edges(last_traversed_at)
    WHERE pruned_at IS NULL;

-- Support conflict detection
CREATE INDEX IF NOT EXISTS idx_edges_type_pair ON edges(from_id, to_id, edge_type)
    WHERE pruned_at IS NULL;
```

### 5.5 Migration Strategy for Existing ~25K Edges

The migration must be non-destructive, reversible, and handle the existing `weight` column gracefully.

**Phase 1: Add columns with defaults (zero downtime)**

```sql
-- All new columns have defaults, so existing rows get sane values.
-- The existing weight column maps to initial alpha/beta:
--   weight >= 0.7: Beta(3.0, 1.0) -- high-weight edges (LLM-assessed, high Jaccard)
--   weight >= 0.4: Beta(1.0, 1.0) -- medium-weight edges (moderate Jaccard)
--   weight < 0.4:  Beta(0.5, 0.5) -- low-weight edges (weak signal)

ALTER TABLE edges ADD COLUMN alpha REAL NOT NULL DEFAULT 1.0;
ALTER TABLE edges ADD COLUMN beta_param REAL NOT NULL DEFAULT 1.0;
ALTER TABLE edges ADD COLUMN traversal_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE edges ADD COLUMN last_traversed_at TEXT;
ALTER TABLE edges ADD COLUMN pruned_at TEXT;
```

**Phase 2: Backfill alpha/beta from existing weight**

```sql
UPDATE edges SET alpha = 3.0, beta_param = 1.0 WHERE weight >= 0.7;
UPDATE edges SET alpha = 1.0, beta_param = 1.0 WHERE weight >= 0.4 AND weight < 0.7;
UPDATE edges SET alpha = 0.5, beta_param = 0.5 WHERE weight < 0.4;
```

**Phase 3: Prune obviously dead edges**

```sql
-- Edges to soft-deleted beliefs
UPDATE edges SET pruned_at = datetime('now')
WHERE from_id IN (SELECT id FROM beliefs WHERE valid_to IS NOT NULL)
   OR to_id IN (SELECT id FROM beliefs WHERE valid_to IS NOT NULL);
```

**Phase 4: Update code to use alpha/beta instead of weight**

The `weight` column remains in the schema but is no longer written to by new code. The `edge_score()` function computes effective weight from `alpha / (alpha + beta_param)`. Existing code that reads `weight` continues to work during the transition.

---

## 6. Concrete Examples from Existing Belief Corpus

### Example 1: Correction Cascade

User corrects a belief: "use uv, not pip, for Python package management."

1. `correct()` creates new belief B_new, supersedes B_old
2. SUPERSEDES edge: B_new -> B_old, Beta(9.0, 1.0)
3. CONTRADICTS edge: B_new -> B_old, Beta(9.0, 1.0)
4. All SUPPORTS edges pointing to B_old get beta_param += 1.0 (their basis changed)
5. All RELATES_TO edges from B_old survive but start weakening (endpoint superseded)
6. Next session: B_new is retrieved for "Python package" queries
7. User uses B_new (feedback: "used") -> B_new's belief alpha increments
8. The SUPERSEDES edge alpha increments (traversed successfully)
9. The old RELATES_TO edges from B_old are pruned after 90 days with no traversals

### Example 2: Co-Retrieval Edge Formation

Query: "how to configure project settings"

1. FTS5 returns beliefs about `pyproject.toml` (B1) and `CLAUDE.md` (B2)
2. BFS from B1 traverses a RELATES_TO edge to B3 (about uv configuration)
3. User uses B1 and B3 in response, ignores B2
4. Feedback loop:
   - B1: "used" -> alpha += 1.0
   - B2: "ignored" -> no change (per existing policy)
   - B3: "used" -> alpha += 1.0
   - Edge B1->B3: alpha += 1.0 (traversed, destination used)
5. Co-retrieval: B1 and B3 both used -> no new edge needed (already connected)
6. If B1 and B2 had both been used: RELATES_TO edge B1->B2 created, Beta(0.5, 0.5)

### Example 3: Edge Promotion

Over 8 sessions, a RELATES_TO edge between "HRR vocabulary bridging" (B4) and "FTS5 keyword search limitations" (B5) is traversed 7 times. Each time, the destination belief is used.

1. Start: RELATES_TO, Beta(1.0, 1.0), traversal_count=0
2. After 7 traversals with "used" feedback: Beta(8.0, 1.0), traversal_count=7
3. Confidence: 8/9 = 0.89 > 0.75 threshold
4. Both beliefs are type "factual" (same type)
5. No negation divergence between contents
6. Promotion fires: RELATES_TO -> SUPPORTS
7. Edge history records: "promotion: RELATES_TO -> SUPPORTS (conf=0.89)"

### Example 4: Conflict Resolution

Edges detected:
- Edge E1: B6 SUPPORTS B7, Beta(4.0, 2.0), confidence=0.67
- Edge E2: B6 CONTRADICTS B7, Beta(2.0, 1.0), confidence=0.67

Confidence difference: 0.0 < 0.3 threshold. Auto-resolution not possible.
System flags for user review with:
```
CONFLICT: B6 and B7 have both SUPPORTS (0.67) and CONTRADICTS (0.67) edges.
B6: "HRR dimension should be 2048 for 15 edge types"
B7: "HRR dimension 512 is sufficient for production"
Please resolve: which relationship is correct?
```

---

## 7. Integration Points

### 7.1 Modified Functions

| Function | File | Change |
|---|---|---|
| `insert_edge()` | store.py | Accept alpha/beta params; default from edge type |
| `get_neighbors()` | store.py | Filter `pruned_at IS NULL`; return alpha/beta in Edge |
| `expand_graph()` | store.py | Use `edge_score()` for priority; record traversals |
| `score_belief()` | scoring.py | Accept optional path_edges for path-adjusted scoring |
| `retrieve()` | retrieval.py | Track traversal records; pass to feedback loop |
| `_process_auto_feedback()` | server.py | Distribute edge feedback after belief feedback |
| `detect_relationships()` | relationship_detector.py | Set initial alpha/beta based on detection method |
| `apply_links()` | semantic_linker.py | Set alpha=3.0, beta=1.0 for LLM-assessed edges |

### 7.2 New Functions

| Function | File | Purpose |
|---|---|---|
| `edge_score()` | scoring.py | Composite edge score for traversal priority |
| `distribute_edge_feedback()` | store.py | Credit assignment after retrieval feedback |
| `process_co_retrieval()` | store.py | Co-retrieval edge formation |
| `prune_edges()` | store.py | Background edge pruning |
| `promote_edges()` | store.py | Edge type promotion |
| `detect_edge_conflicts()` | store.py | Conflict detection |
| `edge_health_metrics()` | store.py | Graph health reporting |
| `edge_exists_any_type()` | store.py | Check for existing edge between pair |

### 7.3 Edge Dataclass Update

```python
@dataclass
class Edge:
    id: int
    from_id: str
    to_id: str
    edge_type: str
    weight: float               # Legacy; retained for backward compat
    alpha: float                # Beta distribution success count
    beta_param: float           # Beta distribution failure count
    traversal_count: int        # Times traversed during retrieval
    last_traversed_at: str | None
    pruned_at: str | None
    reason: str
    created_at: str
```

---

## 8. Design Constraints and Non-Goals

### Constraints

1. **SQLite-only.** No external services, no Redis, no background workers. All maintenance runs inline (on session start or periodically during search).
2. **No breaking schema changes.** The `weight` column stays. New columns have defaults. Existing code works during incremental migration.
3. **Deterministic tests.** Thompson sampling in edge_score() uses `random.betavariate()` which must be seedable for tests (same as current belief scoring).
4. **Performance budget.** Edge scoring adds O(edges_traversed) work per retrieval. At current scale (~25K edges, ~20 traversed per query), this is <1ms additional overhead.

### Non-Goals

1. **Edge embeddings.** HRR already handles distributed edge representations. The dynamic system operates on the explicit edge table, not on vector space.
2. **Multi-hop credit propagation.** Credit flows only to directly traversed edges, not transitively. If edge A->B leads to B->C, and C is used, both A->B and B->C get credit, but A->C does not get implicit credit. This avoids credit diffusion.
3. **Real-time streaming updates.** Edge feedback is batched per search call, not per-keystroke. This matches the existing auto-feedback cadence.
4. **Graph neural networks.** The system is symbolic and interpretable. GNN-style message passing is not needed at this scale and would reduce auditability.

---

## 9. Implementation Order

| Phase | Scope | Effort | Dependencies |
|---|---|---|---|
| **P1: Schema** | Add columns, create tables, migration script | 1 day | None |
| **P2: Edge scoring** | `edge_score()`, updated `expand_graph()`, Edge dataclass | 1 day | P1 |
| **P3: Traversal tracking** | Record which edges were traversed per retrieval | 1 day | P2 |
| **P4: Edge feedback** | `distribute_edge_feedback()`, wire into auto-feedback | 2 days | P3 |
| **P5: Co-retrieval** | `process_co_retrieval()`, wire into feedback loop | 1 day | P4 |
| **P6: Maintenance** | `prune_edges()`, `promote_edges()`, `detect_edge_conflicts()` | 2 days | P2 |
| **P7: Health metrics** | `edge_health_metrics()`, wire into `status()` | 0.5 day | P6 |
| **P8: Validation** | Integration tests, migration test on live DB copy | 1 day | P1-P7 |

Total: ~9.5 days. Can be parallelized: P2+P6 after P1; P3 after P2; P4+P5 after P3.

---

## 10. Research Thread Mapping

How each research direction contributed to this design:

| Thread | Contribution |
|---|---|
| **Bayesian (BAYESIAN_RESEARCH.md)** | Beta(alpha, beta) per edge; conjugate updates; source-informed priors; Thompson sampling for exploration |
| **Bio-inspired (INFORMATION_THEORY_RESEARCH.md)** | Holographic property: edge quality propagates through HRR encoding; weakest-link path composition from SDM theory |
| **Evolutionary (EDGE_TYPE_TAXONOMY.md)** | Edge type promotion/demotion; edges adapt type based on accumulated evidence; discoverable type sets |
| **Energy-based (GRAPH_CONSTRUCTION_RESEARCH.md)** | Edge weight as epistemic energy; conflict_ratio as energy imbalance; pruning as energy minimization |
| **Feedback loop (FEEDBACK_LOOP_PLAN.md)** | Auto-feedback mechanism extended to edges; credit assignment; co-retrieval formation |
| **Scoring (scoring.py)** | Thompson sampling, recency boost, type weights -- all adapted from belief scoring to edge scoring |
