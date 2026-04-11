# Hook Integration Test Plan

Verification plan for H4c, H2, H1, H3 hook implementations.

## H4c: Inline SQLite for read-path hooks

### Test: Latency comparison
```bash
# Baseline: uv run path
time uv run agentmemory search "test query"

# Inline: direct python3+sqlite3
time python3 ~/.claude/hooks/agentmemory-search-inline.py "test query"
```
**Pass criteria:** Inline path < 200ms. uv run path for reference.

### Test: Result equivalence
```bash
# Both paths should return the same belief IDs for the same query
uv run agentmemory search "alpha seek" > /tmp/uv_results.txt
python3 ~/.claude/hooks/agentmemory-search-inline.py "alpha seek" > /tmp/inline_results.txt
diff /tmp/uv_results.txt /tmp/inline_results.txt
```
**Pass criteria:** Same beliefs returned (order may differ due to Thompson sampling).

### Test: Empty DB handling
```bash
AGENTMEMORY_DB=/tmp/empty_test.db python3 ~/.claude/hooks/agentmemory-search-inline.py "anything"
```
**Pass criteria:** Returns empty result, no crash.

---

## H2: Expanded SessionStart hook (locked + core beliefs)

### Test: Hook output format
```bash
# Simulate SessionStart hook input
echo '{}' | bash ~/.claude/hooks/agentmemory-inject.sh
```
**Pass criteria:** Output is valid JSON with `hookSpecificOutput.additionalContext` containing locked beliefs AND top 10 core beliefs.

### Test: Project isolation
```bash
# Run from two different project directories, verify different beliefs
cd /Users/thelorax/projects/agentmemory && echo '{}' | bash ~/.claude/hooks/agentmemory-inject.sh > /tmp/proj1.json
cd /Users/thelorax/projects/alpha-seek-memtest && echo '{}' | bash ~/.claude/hooks/agentmemory-inject.sh > /tmp/proj2.json
# Beliefs should differ
python3 -c "
import json
a = json.load(open('/tmp/proj1.json'))
b = json.load(open('/tmp/proj2.json'))
print('Same:', a == b)
"
```
**Pass criteria:** Output differs between projects.

### Test: Latency
```bash
time (echo '{}' | bash ~/.claude/hooks/agentmemory-inject.sh > /dev/null)
```
**Pass criteria:** < 300ms total.

### Test: Empty project (no beliefs)
```bash
cd /tmp && echo '{}' | bash ~/.claude/hooks/agentmemory-inject.sh
```
**Pass criteria:** Returns valid JSON with empty or minimal context. No crash.

---

## H1: UserPromptSubmit auto-search hook

### Test: Relevant injection
```bash
# Simulate user prompt about a known topic
echo '{"prompt":"how does the scoring pipeline work"}' | bash ~/.claude/hooks/agentmemory-autosearch.sh
```
**Pass criteria:** Output contains `additionalContext` with beliefs about scoring.

### Test: Short prompt filtering
```bash
echo '{"prompt":"ok"}' | bash ~/.claude/hooks/agentmemory-autosearch.sh
```
**Pass criteria:** Returns empty/minimal output (prompt too short to search).

### Test: Noise threshold
```bash
# Generic prompt should not inject garbage
echo '{"prompt":"fix the bug"}' | bash ~/.claude/hooks/agentmemory-autosearch.sh
```
**Pass criteria:** Either returns nothing (no good matches) or returns beliefs actually related to bugs.

### Test: Latency
```bash
time (echo '{"prompt":"what is the retrieval architecture"}' | bash ~/.claude/hooks/agentmemory-autosearch.sh > /dev/null)
```
**Pass criteria:** < 200ms.

### LLM-guided verification
After installing the hook, have a 5-turn conversation on a known topic. Check:
1. Does Claude reference injected beliefs in its responses?
2. Does Claude get confused by irrelevant injected beliefs?
3. Does the user notice any latency increase on prompt submission?

---

## H3: Stop hook for conversation ingestion

### Test: Ingestion creates beliefs
```bash
# Count beliefs before
uv run agentmemory stats | grep "Beliefs:"
# Simulate stop hook with a conversation excerpt
echo '{"conversation":"The user decided to use SQLite for storage because it requires no server process."}' | bash ~/.claude/hooks/agentmemory-ingest-stop.sh
# Count beliefs after
uv run agentmemory stats | grep "Beliefs:"
```
**Pass criteria:** Belief count increased. New beliefs contain "SQLite" or "storage".

### Test: Dedup on re-ingestion
```bash
# Run the same ingestion twice
echo '{"conversation":"The user decided to use SQLite for storage."}' | bash ~/.claude/hooks/agentmemory-ingest-stop.sh
uv run agentmemory stats | grep "Beliefs:"
echo '{"conversation":"The user decided to use SQLite for storage."}' | bash ~/.claude/hooks/agentmemory-ingest-stop.sh
uv run agentmemory stats | grep "Beliefs:"
```
**Pass criteria:** Belief count does not increase on second run (content-hash dedup).

### Test: Async execution
```bash
# Hook should return immediately and run ingestion in background
time (echo '{"conversation":"long conversation text..."}' | bash ~/.claude/hooks/agentmemory-ingest-stop.sh)
```
**Pass criteria:** Returns in < 500ms (background process handles heavy work).

### Test: Precision audit
After running the hook on 10 real conversation turns, manually review:
1. How many extracted beliefs are meaningful decisions/facts?
2. How many are noise (greetings, code output, tool calls)?
3. Target: >= 50% precision on extracted beliefs.

---

## Integration test: Full session lifecycle

After all hooks are installed:

1. Start a new Claude Code session in the agentmemory project
2. Verify SessionStart hook fires (locked + core beliefs in context)
3. Type a domain-specific prompt, verify auto-search injects relevant beliefs
4. Have a 10-turn conversation with decisions and corrections
5. End the session, verify Stop hook ingests the conversation
6. Start a new session, verify new beliefs appear in context

**Pass criteria:** Memory persists across sessions. Relevant context surfaces automatically. No manual /mem:search needed for common queries.
