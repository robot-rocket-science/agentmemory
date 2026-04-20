# Memory Quality Audit -- 2026-04-11

Audit of what agentmemory has actually captured from real usage.

## 1. Database Statistics

### Project DB (~/.agentmemory/projects/2e7ed55e017a/memory.db)

| Metric | Count |
|---|---|
| Total beliefs | 16,067 |
| Locked beliefs | 1 |
| Observations | 15,492 |
| Evidence links | 16,065 |
| Edges (belief-belief) | 1,204 |
| Graph edges | 33,151 |
| Sessions | 0 |
| Checkpoints | 0 |
| Tests | 0 |
| Audit log entries | 0 |
| FTS5 index entries | 31,559 |
| DB file size | 24 MB |

**Belief type breakdown:**

| Type | Count | Pct |
|---|---|---|
| factual | 12,170 | 75.7% |
| correction | 2,911 | 18.1% |
| requirement | 819 | 5.1% |
| preference | 167 | 1.0% |

**Confidence distribution:**

| Confidence | Alpha/Beta | Count | Pct |
|---|---|---|---|
| 0.90 | 9/1 | 15,802 | 98.4% |
| 0.67 | 2/1 | 228 | 1.4% |
| 0.83 | 5/1 | 35 | 0.2% |
| 0.95 | 9/0.5 | 2 | <0.1% |

**Source types:**

| Source | Count |
|---|---|
| agent_inferred | 13,154 |
| user_corrected | 2,911 |
| user_stated | 2 |

**Graph edge types:**

| Type | Count |
|---|---|
| SENTENCE_IN_FILE | 15,311 |
| WITHIN_SECTION | 15,155 |
| CALLS | 1,723 |
| CITES | 364 |
| CONTAINS | 348 |
| COMMIT_TOUCHES | 194 |
| TEMPORAL_NEXT | 50 |
| CO_CHANGED | 6 |

### Main DB (~/.agentmemory/memory.db)

Empty. 0 bytes. No tables. All data lives in the project-specific DB only.

### Conversation Logs (~/.claude/conversation-logs/turns.jsonl)

- 304 turns across 14 unique sessions
- 272 KB of raw conversation data
- Mix of user prompts and assistant responses
- Date range: April 10-11, 2026

**Status: conversation data exists but is small. Most memory content came from document ingestion, not live conversation capture.**

## 2. Belief Quality Assessment

### Signal categories (sampled 80+ beliefs)

**Genuine high-value beliefs (estimated 30-40% of total):**
- Research findings: "HRR's value is fuzzy-start traversal, not multi-hop"
- Architecture decisions: "The MCP server needs to know which project is active"
- Validated claims: "type-aware heuristic captures ~90% of IB benefit"
- Constraints: "No strategy achieves both ECE < 0.10 and exploration >= 0.15"

**Passable but low-density beliefs (estimated 30-40%):**
- Context-dependent fragments that need surrounding beliefs to be useful
- Partial sentences from markdown documents
- Observations that are true but not actionable: "We already knew this from Exp 16"

**Noise (estimated 20-30%):**
- Function definitions as beliefs: 834 entries like "def expand_graph", "def precisionatk"
- Very short fragments (<15 chars): 209 entries like "1 overlap.", "53 experiments."
- Short fragments (<30 chars): 2,651 total (16.5% of all beliefs)
- File paths stored as beliefs: 107+ entries
- Markdown formatting artifacts: table rows, headers as standalone beliefs
- Single-word entries: 48

### Noise estimate

Conservatively, ~3,500 beliefs (22%) are clearly noise (func defs + short fragments + file paths + formatting). The true noise figure is likely 30-35% when including context-dependent fragments that are useless in isolation.

## 3. Correction Detection Accuracy

**Total "corrections": 2,911**

Sampled 45 corrections. Findings:

**Genuine corrections (~60% of sample):**
- "Don't cap retrieval at the injection budget"
- "Never use asyncbash or awaitjob for any command, any duration, any context"
- "A belief backed by evidence should not lose confidence purely because the user expressed disagreement"
- "Cross-layer edges are the missing piece"

**Misclassified as corrections (~35% of sample):**
- Neutral factual statements: "AST parsing is the bottleneck in both (38% and 32% of total time)"
- Questions: "Is this actually a priority?"
- Status updates: "No further experiments planned."
- Design observations: "This is geometric selectivity -- no filtering"

**Clearly wrong classifications (~5%):**
- Code: "def testlockedbeliefsalwaysin_results" classified as correction
- File paths classified as corrections

**Assessment: the correction detector is over-triggering.** It appears to classify negation patterns ("not", "no", "never") as corrections even when the sentence is a factual observation rather than a correction of a prior belief. Precision is roughly 60%.

Only 24 of 2,911 corrections are obviously code/path noise. The bigger problem is that ~1,000+ are factual statements misclassified as corrections.

## 4. Edge/Graph Completeness

### Belief-to-belief edges (edges table)

- 1,204 edges, all type SUPERSEDES with reason "correction"
- These link corrections to the beliefs they supersede
- No other edge types between beliefs (no RELATED_TO, SUPPORTS, CONTRADICTS)
- This means the belief graph has zero semantic relationship edges

### Knowledge graph edges (graph_edges table)

- 33,151 edges across 8 types
- Dominated by structural edges: SENTENCE_IN_FILE (46%) + WITHIN_SECTION (46%) = 92%
- Semantic edges are sparse: CALLS (5.2%), CITES (1.1%), CONTAINS (1.1%)
- Behavioral edges nearly absent: COMMIT_TOUCHES (0.6%), CO_CHANGED (0.02%)
- TEMPORAL_NEXT is minimal (50 edges) despite 304 conversation turns

**Connectivity pattern:**

| From | To | Count |
|---|---|---|
| belief -> belief | | 5,057 |
| belief -> doc/file | | 11,705 |
| doc/file -> belief | | 4,688 |
| doc/file -> doc/file | | 11,701 |

Graph is heavily document-structural. The belief-to-belief subgraph (5,057 edges) exists but is dominated by WITHIN_SECTION proximity edges rather than semantic relationships.

### Missing from the graph

- No session tracking (sessions table empty)
- No checkpoints
- No test results stored
- No audit trail
- No temporal edges linking conversation flow
- No cross-project edges (main DB is empty)

## 5. What's Being Captured vs. What's Missing

### Being captured well
- Document content from markdown files (research notes, experiment results)
- Code structure (function defs extracted from source files)
- File-to-sentence structural relationships
- SUPERSEDES chains for corrections
- FTS5 full-text index is comprehensive (31K entries)

### Being captured poorly
- Correction classification (60% precision)
- Preference detection (only 167 out of 16K -- likely many preferences misclassified as factual)
- Confidence scores (98.4% of beliefs at 0.9 -- no meaningful differentiation)
- Short/fragmentary content not filtered out

### Not being captured at all
- Sessions (table exists, no rows)
- Live conversation turns as they happen (304 turns in log, but observations are 99.5% from "document" source)
- Temporal flow of conversations
- Belief access patterns / retrieval hits
- User feedback on retrieval quality
- Cross-project relationships

## 6. Signal-to-Noise Ratio Assessment

**Overall: roughly 2:1 signal-to-noise by count, but worse by utility.**

Breakdown:
- ~5,000-6,000 beliefs (35-40%) are genuinely useful standalone facts
- ~5,000-6,000 beliefs (35-40%) are low-density fragments that need context
- ~4,000-5,000 beliefs (25-30%) are noise (code defs, short fragments, paths, misclassified types)

The confidence scores provide zero discrimination: everything is 0.9. The Bayesian model has a single prior (alpha=9, beta=1) applied to 98.4% of beliefs. The 228 beliefs at confidence 0.67 (alpha=2, beta=1) represent the only evidence of Bayesian updating, and even these cluster at a single value.

The graph edges are 92% structural (SENTENCE_IN_FILE, WITHIN_SECTION). These are useful for provenance tracking but do not encode semantic relationships. The knowledge graph is more of a "document index" than a "knowledge graph."

## 7. Recommendations

### Critical fixes

1. **Filter noise at ingestion time.** Reject beliefs that are:
   - Function/class definitions (simple regex: starts with `def ` or `class `)
   - File paths with no surrounding context
   - Under 20 characters with no clear semantic content
   - Markdown formatting fragments (lone headers, table separators)

2. **Fix the correction classifier.** Currently over-triggers on negation words. A correction should require evidence of a *prior belief being wrong*, not just the presence of "not" or "no" in the text. Consider requiring:
   - Explicit contrast ("X, not Y" or "instead of X, use Y")
   - Reference to a prior statement being revised
   - User-sourced corrections only (not inferred from document text)

3. **Implement meaningful confidence differentiation.** All beliefs at 0.9 means confidence is useless for retrieval ranking. Options:
   - Source-based priors: user-stated > user-corrected > agent-inferred (already encoded in source_type but not reflected in alpha/beta)
   - Length/specificity heuristic: longer, more specific beliefs start higher
   - Decay: beliefs not accessed in N sessions lose confidence
   - Evidence count: beliefs with more supporting observations get boosted

### Important improvements

4. **Activate session tracking.** The sessions table exists but is empty. Every MCP call should associate with a session_id, enabling temporal queries ("what did we discuss last session?").

5. **Build live conversation capture.** 99.5% of observations come from document ingestion. The conversation log (304 turns, 14 sessions) is not being fed into the memory system. This is the primary knowledge source per project design, but it is not flowing in.

6. **Add semantic edges between beliefs.** The belief graph only has SUPERSEDES edges. There are no SUPPORTS, CONTRADICTS, RELATED_TO, or DEPENDS_ON edges. The graph_edges table has structural edges but these don't encode meaning.

7. **Populate the main DB for cross-project memory.** Currently empty. Global preferences and user profile information should live here.

### Nice to have

8. **Deduplicate beliefs.** With 16K beliefs, there are likely many near-duplicates from overlapping document sections. content_hash exists but may not catch paraphrases.

9. **Prune the ~834 function-definition "beliefs."** These are code index entries, not beliefs. Either move them to a separate code_index table or delete them.

10. **Add retrieval telemetry.** Track which beliefs are actually returned in searches and whether the user acts on them. This enables closed-loop quality improvement.
