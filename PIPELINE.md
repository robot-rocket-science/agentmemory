# Agentmemory Pipeline Reference

## High-Level Architecture

```
                           INPUT LAYER
            +-----------+-----------+-----------+
            |  User Msg |  Asst Msg | Proj Scan |
            +-----+-----+-----+-----+-----+----+
                  |           |           |
                  v           v           v
            +-----------+-----------+-----------+
            | ingest()  | ingest()  | onboard() |
            +-----------+-----------+-----------+
            | search()  | remember()| correct() |
            | observe() | feedback()| status()  |
            +-----------+-----------+-----------+
                       MCP SERVER TOOLS

                       INGESTION PIPELINE
            +------+------+------+------+------+
            | Obs  | Ext  | Corr | Cls  | Per  |
            | save | sent | det  | type | sist |
            +--+---+--+---+--+---+--+---+--+---+
               |      |      |      |      |
               v      v      v      v      v
            +--------------------------------------+
            |          STORAGE (SQLite)             |
            |  observations | beliefs | FTS5 index  |
            |  edges        | sessions | tests      |
            +--------------------------------------+
                            |
            +---------------+---------------+
            |               |               |
            v               v               v
       +----------+   +-----------+   +-----------+
       | L0:Locked|   | L2: FTS5  |   | L3: HRR   |
       | beliefs  |   | search    |   | expansion |
       +----+-----+   +-----+-----+   +-----+-----+
            |               |               |
            +-------+-------+-------+-------+
                    |               |
                    v               v
             +------------+  +-----------+
             | Score+Rank |  | Compress  |
             +-----+------+  +-----+----+
                   |               |
                   v               v
             +---------------------------+
             |     FEEDBACK LOOP         |
             | auto: search->ingest->    |
             |       next search = eval  |
             | explicit: feedback() call |
             |        |                  |
             |        v                  |
             | Bayesian update on belief |
             +---------------------------+
```

---

## Pipeline Stages in Detail

### Stage 1: Input

Three entry points feed text into the system:

| Entry Point | Source | Trigger |
|-------------|--------|---------|
| `ingest(text, source)` | Conversation turns | Agent calls per-turn |
| `onboard(project_path)` | Project files, git history | Agent calls once per project |
| `remember(text)` / `correct(text)` | User-stated rules/corrections | Agent calls on user directive |

---

### Stage 2: Observation

```
    Raw text
        |
        v
    SHA256(text) --> content_hash
        |
        v
    Duplicate? --yes--> Skip
        |
        no
        v
    INSERT INTO observations
        |
        v
    Observation(id, content, type, source, session_id)
```

**Input:** Raw text string + metadata (source, type)
**Output:** `Observation` row (or skip if content-hash already exists)
**Purpose:** Immutable audit trail. Every piece of text that enters the system is recorded exactly once.

---

### Stage 3: Extraction

```
    Raw text
        |
        v
    Strip code blocks (triple backtick)
        |
        v
    Strip URLs
        |
        v
    Strip markdown (headers, bold, italic, tables, lists)
        |
        v
    Split on newlines + sentence boundaries (.!? followed by space)
        |
        v
    Discard fragments < 10 chars
        |
        v
    list[str]  (clean sentences)
```

**Input:** Raw text string
**Output:** `list[str]` -- clean, individual sentences
**Purpose:** Break messy conversation text into atomic units for classification.

**What gets stripped:** Code blocks (triple backtick), inline code, URLs, markdown headers/bold/italic/tables/list markers.

**What gets kept:** Natural language sentences with punctuation.

---

### Stage 4: Correction Detection

```
    Full turn text
        |
        v
    Check 7 signal patterns:
      imperative:   starts with use/add/remove/stop/always/never
      always_never: contains always/never/from now on/permanently
      negation:     contains don't/not/no more/stop
      emphasis:     contains !/hate/zero question
      prior_ref:    contains we've been/I told you/we agreed
      declarative:  pattern "X is Y" or "X needs to be Y"
      directive:    contains must/require/mandatory
        |
        v
    signals >= 1? --no--> is_correction=False
        |
        yes
        v
    is_correction=True, confidence=min(1.0, count*0.3)
```

**Input:** Full turn text (not individual sentences)
**Output:** `(is_correction: bool, signals: list[str], confidence: float)`
**Accuracy:** 92% on real corrections (tested). Runs on full turn only, not per-sentence.

---

### Stage 5: Classification

```
    list[(sentence, source)]
        |
        v
    use_llm? --yes--> Haiku 4.5 (batch 20, 99% accuracy)
        |                  |
        no                 v
        |              Prompt: "classify persist + type"
        v                  |
    Keyword rules          v
    (36% accuracy)     Parse JSON response
        |                  |
        +--------+---------+
                 |
                 v
    list[ClassifiedSentence]
      .text           str
      .source         "user" | "assistant"
      .persist        bool
      .sentence_type  REQUIREMENT | CORRECTION | FACT | ...
      .alpha          float (Bayesian prior)
      .beta_param     float (Bayesian prior)
```

**Classification types and what happens to them:**

| Type | Persisted? | Belief Type | Prior (alpha, beta) | Starting Confidence |
|------|-----------|-------------|---------------------|---------------------|
| REQUIREMENT | Yes | requirement | (9.0, 1.0) | 90% |
| CORRECTION | Yes | correction | (9.0, 1.0) | 90% |
| PREFERENCE | Yes | preference | (9.0, 1.0) | 90% |
| FACT | Yes | factual | (9.0, 1.0) | 90% |
| ASSUMPTION | Yes | factual | (9.0, 1.0) | 90% |
| DECISION | Yes | factual | (5.0, 1.0) | 83% |
| ANALYSIS | Yes | factual | (2.0, 1.0) | 67% |
| QUESTION | No | -- | -- | -- |
| COORDINATION | No | -- | -- | -- |
| META | No | -- | -- | -- |

**LLM accuracy:** 99% (Haiku 4.5, tested exp47/50)
**Offline accuracy:** 36% (keyword rules only)

---

### Stage 6: Persistence

```
    ClassifiedSentence
        |
        v
    persist == True? --no--> Discarded
        |
        yes
        v
    Determine source:
      CORRECTION --> locked=True, source=user_corrected
      user       --> source=user_stated
      assistant  --> source=agent_inferred
        |
        v
    store.insert_belief(content, type, source, alpha, beta, locked)
        |
        +--> Belief row in SQLite
        +--> FTS5 index updated
        +--> Evidence link to Observation
        |
        v  (if CORRECTION)
    Search for contradicted beliefs
        |
        v
    store.supersede_belief(old, new)
```

**What gets locked:**

| Path | Locked? | Who decides? |
|------|---------|-------------|
| `remember()` tool | Always locked | Agent calls it |
| `correct()` tool | Always locked | Agent calls it |
| `ingest()` + CORRECTION fallback | Locked if full-turn flagged and no sentences persisted | Automatic |
| `ingest()` + other types | Never locked | N/A |

**This is where the trust gap lives.** The agent decides when to call `remember()` and `correct()`. The ingest pipeline can also auto-create locked beliefs from the correction fallback path. There is no verification that the user actually said or intended these as permanent rules.

---

### Stage 7: Retrieval

```
    search(query, budget=2000)
        |
        +--> L0: get_locked_beliefs() [cap=100]
        |
        +--> L2: FTS5 search
        |       sanitize query to OR-joined terms
        |       BM25 ranking, top_k=30
        |
        +--> L3: HRR expansion (if edges exist)
                top 5 FTS5 hits as seeds
                query forward+reverse per edge type
                top 3 results per direction
        |
        v
    Merge + Deduplicate (L0 + L2 + L3)
        |
        v
    score_belief() for each candidate
        |
        v
    Sort by score descending
        |
        v
    compress_belief() + pack_beliefs(budget)
        |
        v
    RetrievalResult(beliefs, scores, total_tokens, budget_remaining)
```

**Scoring formula:**

For locked beliefs:
```
score = lock_boost(belief, query_terms) * thompson_sample(alpha, beta)
```

For normal beliefs:
```
score = thompson_sample(alpha, beta) * decay_factor(belief, now)
```

**Decay half-lives:**

| Belief Type | Half-Life | Meaning |
|-------------|-----------|---------|
| factual | 14 days | Slowly lose relevance |
| relational | 14 days | Same |
| procedural | 21 days | Slower decay |
| causal | 30 days | Slowest decay |
| preference | Never | Permanent |
| correction | Never | Permanent |
| requirement | Never | Permanent |

---

### Stage 8: Feedback Loop

```
    AUTO-FEEDBACK (implicit):

      search()  --> buffer retrieved belief IDs
      ingest()  --> buffer ingested text
      next search() or ingest() --> trigger evaluation:
          |
          v
      Extract key terms from ingested text (stop-word filtered)
          |
          v
      Match terms against buffered beliefs
          |
          v
      >= 2 unique terms match? --yes--> outcome = USED
          |                               |
          no                              v
          |                    record_test_result()
          v
      outcome = IGNORED
          |
          v
      record_test_result()


    EXPLICIT FEEDBACK:

      feedback(belief_id, "used"|"ignored"|"harmful")
          |
          v
      record_test_result()


    BAYESIAN UPDATE (inside record_test_result):

      outcome == USED?    --> alpha += weight
      outcome == HARMFUL? --> beta += weight (SKIPPED if locked)
          |
          v
      new confidence = alpha / (alpha + beta)
```

**Key behavior:**
- Locked beliefs can only go UP in confidence (alpha increases on USED, beta never increases)
- Unlocked beliefs can go up or down
- Auto-feedback fires on the search-after-ingest pattern

---

## Tool-to-Pipeline Mapping

| MCP Tool | Pipeline Stages Invoked | Creates Locked Belief? |
|----------|------------------------|----------------------|
| `ingest(text, source)` | Observation -> Extraction -> Correction Detection -> Classification -> Persistence | Only on correction fallback path |
| `search(query)` | Retrieval (L0+L2+L3) -> Scoring -> Packing; triggers auto-feedback | No |
| `remember(text)` | Direct insert into beliefs table | **Yes, always** |
| `correct(text)` | Direct insert + supersede search | **Yes, always** |
| `observe(text)` | Observation only (no belief) | No |
| `feedback(id, outcome)` | Bayesian update on existing belief | No |
| `onboard(path)` | Project scan -> Extraction -> Classification (offline) -> Persistence -> Edge insertion | No |
| `status()` | Read-only counts | No |
| `get_locked()` | Read-only query | No |

---

## Data Model Summary

```
    sessions ----< observations    (created during)
    sessions ----< checkpoints     (milestones)
    sessions ----< tests           (feedback in)

    observations ----< evidence    (supports)
    beliefs      ----< evidence    (supported by)
    beliefs      ----< edges       (from)
    beliefs      ----< edges       (to)
    beliefs      ----< tests       (evaluated by)


    TABLE observations:
      id              text PK
      content_hash    text UNIQUE
      content         text
      observation_type text
      source_type     text
      session_id      text FK

    TABLE beliefs:
      id              text PK
      content_hash    text
      content         text
      belief_type     text
      alpha           real
      beta_param      real
      confidence      real  (GENERATED: alpha/(alpha+beta))
      source_type     text
      locked          int
      valid_from      text
      valid_to        text  (NULL if active)
      superseded_by   text  (NULL if active)

    TABLE evidence:
      id              text PK
      belief_id       text FK
      observation_id  text FK
      source_weight   real
      relationship    text

    TABLE edges:
      id              int PK
      from_id         text FK
      to_id           text FK
      edge_type       text
      weight          real
      reason          text

    TABLE tests:
      id              text PK
      belief_id       text FK
      session_id      text FK
      outcome         text
      detection_layer text
      evidence_weight real

    TABLE sessions:
      id                      text PK
      retrieval_tokens        int
      classification_tokens   int
      beliefs_created         int
      corrections_detected    int
      searches_performed      int
      feedback_given          int
```
