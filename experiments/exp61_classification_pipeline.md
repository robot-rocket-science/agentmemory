# Experiment 61: Conversation Classification Pipeline -- Process and Results

**Date:** 2026-04-10
**Status:** Complete
**Answers:** C1b (conversation extraction), C3 (sensitivity), prior model calibration
**Depends on:** Exp 47/50 (LLM accuracy), Exp 38 (source priors), Exp 5b (Thompson sampling)

---

## 1. What We Found

47% of conversation sentences are worth persisting across sessions. The statement type -- not who said it -- determines whether something matters.

| Statement Type | Persist Rate | Prior | Action |
|---|---|---|---|
| Requirement | 100% | Beta(9,1) | Always store |
| Correction | 100% | Beta(9,1) | Always store |
| Preference | 92% | Beta(9,1) | Always store |
| Fact | 93% | Beta(9,1) | Always store |
| Assumption | 80% | Beta(9,1) | Always store |
| Decision | 79% | Beta(5,1) | Store, moderate confidence |
| Analysis | 26% | Beta(2,1) | Store, low confidence, let feedback decide |
| Coordination | 2% | -- | Don't store |
| Question | 0% | -- | Don't store |
| Meta | 0% | -- | Don't store |

Source (user vs assistant) is a minor modifier, not the primary signal. User persist rate: 44%. Assistant persist rate: 48%.

---

## 2. Exact Process (Replicable Pipeline)

This section documents every step from raw conversation turns to classified beliefs with Bayesian priors. This is the process the agentmemory pipeline must automate.

### Step 1: Capture conversation turns

**Input:** Raw conversation text from any source (live hooks, exports, documents).

**Mechanism:** Two hooks in Claude Code settings.json:

```json
{
  "UserPromptSubmit": [{
    "hooks": [{
      "type": "command",
      "command": "/path/to/conversation-logger.sh"
    }]
  }],
  "Stop": [{
    "hooks": [{
      "type": "command",
      "command": "/path/to/conversation-logger.sh"
    }]
  }]
}
```

The logger script reads JSON from stdin. UserPromptSubmit provides `prompt` (user text). Stop provides `last_assistant_message` (assistant text). Both provide `session_id`, `cwd`, `hook_event_name`.

**Output format:** JSONL, one line per turn:

```json
{"timestamp": "2026-04-10T22:05:53Z", "event": "user", "session_id": "abc123", "cwd": "/path", "text": "..."}
```

**Verified:** Hook payloads confirmed in C1a. Both sides of conversation captured. Non-blocking (exit 0, no latency impact).

**Reference implementation:** `~/.claude/hooks/conversation-logger.sh`

### Step 2: Dumb sentence extraction

**Input:** Text field from each conversation turn.

**Process:** Split text into atomic sentences. No keyword filtering. No classification. Rules:

1. Strip code blocks (triple-backtick regions). Code is not a belief.
2. Strip inline code backticks but keep surrounding text.
3. Strip URLs.
4. Strip markdown formatting (headers, bold, italic, table rows, list markers).
5. Split on newlines first (conversation text is line-delimited).
6. Within each line, split on sentence-ending punctuation followed by space: `(?<=[.!?])\s+`
7. Discard any fragment under 10 characters.

That's it. Every surviving fragment is a candidate sentence. No judgment about importance.

**Output:** List of sentences, each tagged with source ("user" or "assistant") and session ID.

**Measured extraction rate on real data:** 381 sentences from 49 turns (~7.8 sentences per turn).

**Reference implementation:** `extract_sentences()` in `experiments/exp57_dumb_extraction.py`

### Step 3: Batch LLM classification

**Input:** Sentences from Step 2, batched in groups of 15-20.

**LLM:** Haiku (cheapest available). Cost: ~$0.001 per batch of 20 items.

**Prompt template:**

```
You are classifying conversation sentences for a memory system.

For EACH sentence, classify on two dimensions:

1. persist: Should this be remembered across sessions?
   - PERSIST: Contains a decision, preference, correction, fact, or
     requirement that would be useful in a future session
   - EPHEMERAL: Only useful in the current moment (greetings, status
     updates, meta-commentary, coordination, questions, announcements)

2. type: What kind of information?
   - DECISION: A choice was made
   - PREFERENCE: A stated like/dislike/style preference
   - CORRECTION: Fixing something previously stated or done wrong
   - FACT: A stated truth about the project or world
   - REQUIREMENT: A constraint or rule that must be followed
   - ASSUMPTION: Something taken as true without firm evidence
   - ANALYSIS: Reasoning, explanation, or derived conclusion
   - QUESTION: Asking for information
   - COORDINATION: Control flow ("ok", "proceed", "next")
   - META: About the conversation process itself

Be conservative with PERSIST. When in doubt, mark EPHEMERAL.

Sentences:
1. [user] "..."
2. [assistant] "..."
...

Respond as JSON array: [{"id": 1, "persist": "...", "type": "..."}, ...]
```

**Key design choices in the prompt:**

- Source tag ([user] or [assistant]) is included so the LLM has context, but the LLM decides persist/type based on content, not source alone.
- "Be conservative with PERSIST" prevents over-classification. The Bayesian system can promote borderline items through feedback; it cannot easily demote false positives that entered at high confidence.
- Type categories are mutually exclusive. A sentence gets exactly one type.

**Parallelization:** Split sentences into batches of ~20. Run batches in parallel via subagents or API calls. In this experiment: 5 parallel Haiku subagents processed 381 sentences in ~20 seconds wall clock.

**Measured accuracy:** 99% on 100 ground-truth items (Exp 47/50). 1 error across entity classification + directive detection tasks. Error rate confirmed acceptable per A032 analysis (11.5x ROI vs heuristic-only).

**Output:** JSON array with id, persist label, and type label for each sentence.

### Step 4: Assign Bayesian priors based on type

**Input:** Classified sentences from Step 3.

**Mapping (derived empirically from this experiment's persist rates):**

```python
TYPE_PRIORS = {
    "REQUIREMENT":  (9.0, 1.0),   # 100% persist rate
    "CORRECTION":   (9.0, 1.0),   # 100% persist rate
    "PREFERENCE":   (9.0, 1.0),   # 92% persist rate
    "FACT":         (9.0, 1.0),   # 93% persist rate
    "ASSUMPTION":   (9.0, 1.0),   # 80% persist rate
    "DECISION":     (5.0, 1.0),   # 79% persist rate
    "ANALYSIS":     (2.0, 1.0),   # 26% persist rate
    "COORDINATION": None,          # 2% -- don't store
    "QUESTION":     None,          # 0% -- don't store
    "META":         None,          # 0% -- don't store
}
```

Sentences with `persist == "EPHEMERAL"` OR type mapping of `None` are not stored in the belief graph. They are kept as raw observations (append-only provenance log) but do not become beliefs.

Sentences with `persist == "PERSIST"` are inserted into the belief graph with the Beta prior corresponding to their type.

**Source modifier (optional, small effect):**

The data shows user and assistant persist rates are similar (44% vs 48%), so the source modifier is minor. If applied:

```python
SOURCE_MODIFIER = {
    "user":      1.2,   # slight boost to alpha
    "assistant": 0.9,   # slight discount to alpha
}
# Applied: alpha = base_alpha * modifier
```

This is a refinement, not a requirement. The type-based prior does the heavy lifting.

### Step 5: Insert into belief graph

**Input:** Classified, prior-assigned sentences.

**Process:**

1. Content-hash dedup: skip if an identical sentence already exists in the graph.
2. Insert as a belief node with:
   - text: the sentence
   - type: the classified type (DECISION, FACT, etc.)
   - alpha, beta: from the type-based prior
   - source: "user" or "assistant"
   - session_id: which session it came from
   - timestamp: when the turn was captured
   - provenance: link back to the raw observation (conversation turn)
3. Edge extraction: connect to existing beliefs via typed edges (SUPPORTS, CONTRADICTS, SUPERSEDES, etc.). This is a separate pipeline step not covered in this experiment.

### Step 6: Thompson sampling handles the rest

**No further classification needed at retrieval time.** The Bayesian system (Thompson sampling with type-based priors, validated in Exp 5b/7/38) handles:

- Promoting beliefs that get retrieved and used (alpha += 1)
- Demoting beliefs that get retrieved and ignored (beta += 1)
- Exploring uncertain beliefs (natural Thompson exploration)
- Converging on calibrated confidence over multiple sessions

The type classification from Step 3 is used at retrieval display time to decide how to present beliefs in context (e.g., constraints shown at full length, analysis truncated per Exp 42), NOT to decide whether to retrieve them.

---

## 3. Cost Analysis

For a typical conversation session of 50 turns:

| Step | Cost | Latency |
|---|---|---|
| Capture (hooks) | $0 | <1ms per turn |
| Sentence extraction | $0 | <10ms per turn |
| LLM classification | ~$0.005 (50 turns x ~8 sentences x 20/batch = ~20 batches) | ~2s total (parallelized) |
| Prior assignment | $0 | <1ms |
| Graph insertion | $0 | <10ms per belief |

Total per session: ~$0.005 and ~2-3 seconds of LLM time. Can run async after each turn or in batch at session end.

At 10 sessions/day for a year: ~$18. Negligible.

---

## 4. What This Pipeline Does NOT Do

- **Edge extraction.** Connecting new beliefs to existing ones (SUPPORTS, CONTRADICTS, etc.) is a separate pipeline stage. This experiment covers observation -> belief only.
- **Conflict detection.** If a new belief contradicts an existing one, that's handled by the conflict check stage in PLAN.md, not by classification.
- **Compression.** Beliefs are stored at full sentence length. Type-aware compression (Exp 42) applies at retrieval time, not storage time.
- **Cross-session re-statement detection.** Detecting that the same fact was stated across sessions (evidence of context loss) is a future experiment.
- **Edge cases in sentence splitting.** Multi-sentence beliefs ("Use PostgreSQL because it handles JSON well and our team knows it") get split into separate nodes. Whether to re-join them is an open question.

---

## 5. Reproduction

To reproduce this experiment on new conversation data:

```bash
# 1. Ensure conversation logger hooks are active in ~/.claude/settings.json
#    (UserPromptSubmit + Stop hooks calling conversation-logger.sh)

# 2. Have conversations. Data accumulates in:
#    ~/.claude/conversation-logs/turns.jsonl

# 3. Extract sentences and generate auto-labels
uv run python experiments/exp58_context_loss_analysis.py --extract
# Output: experiments/exp58_annotated_turns.json (381 entries with guess labels)

# 4. Split into batches for parallel classification
uv run python3 -c "
import json; from pathlib import Path
entries = json.loads(Path('experiments/exp58_annotated_turns.json').read_text())
for i in range(0, len(entries), 76):
    chunk = entries[i:i+76]
    Path(f'experiments/exp58_batch_{i//76}.json').write_text(json.dumps(chunk, indent=2))
"

# 5. Classify each batch via Haiku subagents (or API)
#    Prompt template in Step 3 above
#    Each subagent reads exp58_batch_N.json, writes exp58_classified_N.json

# 6. Merge and analyze
uv run python3 -c "
import json; from pathlib import Path; from collections import Counter
classified = {}
for i in range(5):
    for e in json.loads(Path(f'experiments/exp58_classified_{i}.json').read_text()):
        classified[e['id']] = e
original = json.loads(Path('experiments/exp58_annotated_turns.json').read_text())
for e in original:
    c = classified.get(e['id'], {})
    e['persist'] = c.get('persist', e['persist'])
    e['type'] = c.get('type', e['type'])
Path('experiments/exp58_annotated_turns.json').write_text(json.dumps(original, indent=2))
"

# 7. Run analysis
uv run python experiments/exp58_context_loss_analysis.py --analyze
```

The classification prompt is project-agnostic. It works on any conversation content because the type categories (FACT, DECISION, PREFERENCE, etc.) are universal. No project-specific configuration needed.

---

## 6. Key Findings That Change the Architecture

1. **Keyword classification at extraction time is unnecessary.** The LLM classification at $0.001/batch replaces all heuristic keyword matching with 99% accuracy vs 36% heuristic accuracy.

2. **Source-based priors (user vs assistant) are insufficient.** Both sources carry persist-worthy content at similar rates (44% vs 48%). The statement TYPE is the primary signal.

3. **"Store everything and sort later" is viable.** 47% persist rate means almost half the content has value. Combined with the Bayesian system's ability to demote noise through feedback, aggressive extraction is better than conservative filtering.

4. **Three types should never be stored.** Coordination (2%), Question (0%), and Meta (0%) are reliably ephemeral. Filtering these out before graph insertion removes ~33% of sentences at zero cost.

5. **Analysis is the swing category.** 26% persist rate means most analysis is ephemeral but some is valuable. This is exactly the case the Bayesian feedback loop was designed for: start at Beta(2,1), let retrieval feedback decide.

---

## 7. References

- Exp 47/50: LLM classification accuracy (99% Haiku vs 36% heuristic)
- Exp 38: Source-stratified priors (validated at 50K scale)
- Exp 5b: Thompson sampling with Jeffreys prior (passes calibration + exploration)
- Exp 57: Dumb extraction + Bayesian scoring (source priors alone separate user/assistant)
- A032: Atomic LLM calls for batch classification (design + ROI analysis)
- PLAN.md: Scientific memory model (observation -> belief -> test -> revision)
- HOOK_INJECTION_RESEARCH.md: Hook payload schemas for Claude Code and Codex CLI
- conversation-logger.sh: Reference implementation for turn capture
