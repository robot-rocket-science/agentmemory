# Architecture: Adaptive Memory System

A jargon-free description of the system's structure and behavior. Use this document when discussing design decisions without getting lost in implementation details.

---

## What the system does in one sentence

Turns conversation into scored claims, retrieves the best ones when asked, and learns which claims are actually useful over time.

---

## Core Data Model

```
┌─────────────┐       derives        ┌─────────────┐
│  Recording   │ ──────────────────>  │    Claim     │
│  (immutable) │                      │  (mutable)   │
└─────────────┘                      └──────┬──────┘
                                            │
                              ┌─────────────┼─────────────┐
                              │             │             │
                         ┌────▼────┐  ┌─────▼─────┐ ┌────▼────┐
                         │  Link   │  │  Outcome  │ │ Version │
                         │(between │  │(retrieval │ │(replaces│
                         │ claims) │  │ feedback) │ │  older) │
                         └─────────┘  └───────────┘ └─────────┘
```

### Recording (immutable input)

The raw text that entered the system. Never modified, never deleted. The ground truth.

- A user message, an assistant response, a document paragraph, a git commit message
- Timestamped, tagged with source (who said it)
- One recording can produce zero, one, or many claims

### Claim (scored assertion)

A single statement the system believes to be true, with a confidence score.

- Extracted from a recording by the classifier
- Has a **type**: fact, correction, preference, requirement, procedure, relationship
- Has a **confidence score** that changes over time (starts high or low depending on type)
- Has a **source strength**: user-stated > user-corrected > document > agent-inferred
- Can be **locked**: confidence floor enforced, cannot weaken (corrections and user rules)
- Can be **superseded**: replaced by a newer claim, kept for history but scored near zero

### Link (relationship between claims)

A directed edge connecting two claims.

- Types: SUPPORTS, CONTRADICTS, SUPERSEDES, RELATES_TO, CITES
- Weighted (stronger connections score higher in retrieval)
- Enable multi-hop retrieval: "find claims connected to the claims that matched the query"

### Outcome (retrieval feedback)

A record of whether a retrieved claim was actually useful.

- Created when the system (or the agent) reports: **used**, **ignored**, or **harmful**
- Drives the confidence update: used = claim gets stronger, harmful = claim gets weaker
- Two sources: **explicit** (agent calls feedback tool) or **implicit** (auto-inferred from context)

### Version (claim replacement)

When a claim is corrected or updated, the old one is superseded, not deleted.

- Old claim points to new claim
- Old claim scores near zero in retrieval (effectively hidden)
- Full revision history preserved for auditing

---

## The Confidence Model

Every claim carries two numbers: **successes** (alpha) and **failures** (beta).

```
confidence = successes / (successes + failures)
```

This is a Beta distribution. It starts at a prior based on claim type:

| Claim type   | Starting confidence | Can weaken? |
|-------------|--------------------:|-------------|
| Requirement  | 90%                | No (locked) |
| Correction   | 90%                | No (locked) |
| Preference   | 90%                | No (locked) |
| Fact         | 90%                | Yes         |
| Decision     | 83%                | Yes         |
| Analysis     | 67%                | Yes         |

**How confidence changes:**

```
Claim retrieved and used     -->  successes += 1  (confidence rises)
Claim retrieved and harmful  -->  failures += 1   (confidence drops)
Claim retrieved and ignored  -->  no change       (neutral signal)
Claim is locked              -->  failures frozen  (can only rise)
```

**Why Beta distribution?**

- Conjugate prior: each update is a single addition, no recomputation
- Natural uncertainty: new claims (few observations) have wide variance; old tested claims are precise
- Thompson sampling: at retrieval time, sample from the distribution to balance exploration (try uncertain claims) vs exploitation (use proven claims)

---

## The Pipeline

```
           INPUT                    PROCESS                    OUTPUT
    ┌───────────────┐       ┌───────────────────┐      ┌──────────────┐
    │ Conversation   │       │                   │      │              │
    │ turn, document,│──────>│  1. Record         │─────>│ Recording    │
    │ commit, etc.   │       │  2. Split sentences│      │              │
    └───────────────┘       │  3. Classify type  │      │ Claims       │
                            │  4. Assign prior   │      │ (with scores)│
                            │  5. Detect fixes   │      │              │
                            │  6. Store          │      │ Links        │
                            └───────────────────┘      └──────────────┘
```

### Step by step

1. **Record**: Store the full input text as an immutable recording
2. **Split**: Break text into individual sentences
3. **Classify**: For each sentence, determine:
   - Should it persist? (yes/no -- greetings and status updates are discarded)
   - What type? (fact, correction, preference, requirement, etc.)
4. **Assign prior**: Based on type, set starting confidence (see table above)
5. **Detect fixes**: If the sentence corrects something, find and supersede the old claim
6. **Store**: Insert claim with confidence score, link to source recording

### Classification methods

Two classifiers, same interface:

| Method   | Accuracy | Cost   | When used           |
|---------|---------|--------|---------------------|
| LLM      | 99%     | ~$0.001/sentence | Live sessions |
| Keywords | 36%     | Free   | Bulk ingestion, offline |

---

## Retrieval

When the agent asks "what do I know about X?":

```
Query: "typing requirements"
         │
         ▼
┌─────────────────────┐
│ 1. Always-loaded     │  Locked claims (corrections, rules).
│    claims            │  Returned regardless of query.
├─────────────────────┤
│ 2. Keyword search    │  Full-text search on claim content.
│                      │  Returns claims containing query terms.
├─────────────────────┤
│ 3. Graph expansion   │  Follow links from keyword hits.
│                      │  Finds related claims that don't
│                      │  contain the query words.
├─────────────────────┤
│ 4. Score and rank    │  Multiply: type_weight * source_weight
│                      │            * time_decay * confidence_sample
│                      │            * usage_track_record
├─────────────────────┤
│ 5. Pack into budget  │  Compress and fit into token budget.
│                      │  Highest-scored claims first.
└─────────────────────┘
         │
         ▼
    Ranked claims with scores
```

### Scoring factors (multiplicative)

| Factor              | What it measures                          | Range     |
|--------------------|-------------------------------------------|-----------|
| Type weight         | Requirements > corrections > facts         | 1.0 - 2.5 |
| Source weight        | User-stated > document > agent-inferred   | 0.8 - 1.5 |
| Time decay          | Newer claims score higher (type-specific half-lives) | 0.0 - 1.0 |
| Confidence sample   | Random draw from Beta(alpha, beta) -- explore/exploit | 0.0 - 1.0 |
| Usage track record  | High-use claims boosted, high-ignore claims penalized | 0.5 - 1.5 |
| Lock boost          | Locked claims get relevance-aware premium  | 1.0 - 3.0 |
| Recency boost       | Brand-new claims surface faster            | 1.0 - 2.0 |

---

## The Feedback Loop

The part that makes claims get better over time.

```
         ┌──────────────────────────────────────────┐
         │                                          │
         ▼                                          │
  ┌─────────────┐    ┌──────────────┐    ┌─────────┴───────┐
  │  Retrieve    │───>│  Agent uses   │───>│  Record outcome  │
  │  claims      │    │  (or ignores) │    │  (used/ignored/  │
  │  for task    │    │  the claims   │    │   harmful)       │
  └─────────────┘    └──────────────┘    └─────────────────┘
         │                                          │
         │           confidence updated             │
         └──────────────────────────────────────────┘
```

### Two feedback mechanisms

**Explicit (agent-driven):** The agent calls a feedback tool with the claim ID and outcome. High signal, low volume. Only source of "harmful" outcomes.

**Implicit (automatic):** When the agent searches again, the system checks whether previously retrieved claims appeared (by key-term overlap) in text ingested since the last search. If 2+ unique key terms from the claim appear in the ingested text, auto-mark "used." Otherwise, auto-mark "ignored." Explicit feedback always overrides implicit.

### What the loop produces over time

- Claims that consistently help rise in confidence and rank higher
- Claims that are retrieved but never used sink in ranking (not confidence -- ignored is neutral)
- Claims that cause harm drop in confidence (unless locked)
- New claims start uncertain and stabilize as evidence accumulates
- The system naturally promotes proven knowledge and demotes noise

---

## Locked Claims (Safety Floor)

Some claims cannot weaken:

- **Corrections**: "Use X, not Y" -- the user corrected us, this is ground truth
- **User-stated rules**: "Always do Z" -- the user's explicit instruction
- **Preferences**: "I prefer A over B" -- the user's stated preference

Locked claims:
- Can gain confidence (alpha increments on "used")
- Cannot lose confidence (beta frozen on "harmful")
- Never time-decay (always fresh)
- Always included in retrieval results (if relevant to query)
- Can only be removed by explicit supersession (user says something new)

---

## Time Decay

Claims lose relevance over time, at different rates depending on type:

| Claim type   | Half-life  | Rationale                                |
|-------------|-----------|------------------------------------------|
| Fact         | 14 days   | Facts about projects change frequently    |
| Procedure    | 21 days   | Workflows change slower than facts        |
| Relationship | 14 days   | Who-works-on-what changes frequently      |
| Causal       | 30 days   | Cause-effect understanding is durable     |
| Correction   | never     | Corrections are permanent (locked)        |
| Preference   | never     | User preferences persist (locked)         |
| Requirement  | never     | Requirements persist until superseded     |

---

## Session Tracking

Each session (one CLI conversation) records:

| Metric                | What it measures                              |
|----------------------|-----------------------------------------------|
| retrieval_tokens      | Tokens injected via search results             |
| classification_tokens | Tokens consumed by classifier                  |
| claims_created        | New claims stored this session                 |
| corrections_detected  | User corrections caught this session           |
| searches_performed    | Number of search calls                         |
| feedback_given        | Feedback events (auto + explicit) this session |

**Loop closure rate** = feedback_given / (searches_performed * avg_claims_per_search)

Measures what fraction of retrievals get feedback. Higher = the system is learning faster.

---

## Glossary: Jargon to Plain English

| Project term         | This document calls it | What it is                                    |
|---------------------|------------------------|-----------------------------------------------|
| Observation          | Recording              | Raw immutable input text                       |
| Belief               | Claim                  | Scored assertion derived from input            |
| Evidence             | (link to source)       | Connection between recording and claim         |
| Edge                 | Link                   | Relationship between two claims                |
| TestResult           | Outcome                | Feedback record: was the claim useful?         |
| Alpha / Beta         | Successes / Failures   | Beta distribution parameters                   |
| Locked               | Locked                 | Cannot weaken (same term)                      |
| Superseded           | Superseded / Versioned | Replaced by newer claim                        |
| FTS5                 | Keyword search         | SQLite full-text search                        |
| HRR                  | Graph expansion        | Holographic reduced representation (math trick for graph traversal) |
| Thompson sampling    | Confidence sample      | Random draw from Beta distribution             |
| L0 / L1 / L2 / L3   | Retrieval layers       | Always-loaded / behavioral / keyword / graph   |
| Percolator           | Feedback loop          | The cycle of retrieve -> use -> update         |
| Conjugate prior      | Starting score         | Initial confidence before any feedback         |
