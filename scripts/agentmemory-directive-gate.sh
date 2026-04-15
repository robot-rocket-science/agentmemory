#!/bin/bash
# PreToolUse hook (Bash): check if the proposed command violates any locked
# prohibition beliefs. Blocks execution if a violation is detected.
#
# TB-10 implementation: directive enforcement at Tier 4 (violation detection)
# and Tier 5 (violation blocking) for Bash tool calls.
#
# Scans locked beliefs for prohibition patterns ("never", "do not", "don't",
# "stop", "avoid", "must not") and checks if the command matches key terms.

PAYLOAD=$(cat)
export AGENTMEMORY_HOOK_PAYLOAD="$PAYLOAD"

python3 << 'PYEOF'
import hashlib, json, os, re, sqlite3, sys
from pathlib import Path

raw = os.environ.get("AGENTMEMORY_HOOK_PAYLOAD", "")
if not raw:
    sys.exit(0)

try:
    payload = json.loads(raw)
except Exception:
    sys.exit(0)

# Extract the Bash command from the tool input
tool_input = payload.get("toolInput", {})
command = tool_input.get("command", "")
if not command:
    sys.exit(0)

# Resolve DB
cwd = payload.get("cwd", os.getcwd())
abs_path = str(Path(cwd).resolve())
path_hash = hashlib.sha256(abs_path.encode()).hexdigest()[:12]
db_path = str(Path.home() / ".agentmemory" / "projects" / path_hash / "memory.db")

if not Path(db_path).exists():
    sys.exit(0)

try:
    db = sqlite3.connect(db_path)

    # Load locked prohibition beliefs
    rows = db.execute(
        "SELECT content FROM beliefs WHERE locked = 1 AND valid_to IS NULL"
    ).fetchall()
    db.close()

    if not rows:
        sys.exit(0)

    # Filter to prohibitions only (beliefs containing prohibition keywords)
    prohibition_patterns = [
        r"\bnever\b", r"\bdo not\b", r"\bdon'?t\b", r"\bmust not\b",
        r"\bshould not\b", r"\bshouldn'?t\b", r"\bavoid\b", r"\bstop\b",
        r"\bprohibit", r"\bban\b", r"\bforbid",
    ]

    prohibitions = []
    for row in rows:
        content = row[0].lower()
        for pat in prohibition_patterns:
            if re.search(pat, content):
                prohibitions.append(row[0])
                break

    if not prohibitions:
        sys.exit(0)

    # Extract significant terms from each prohibition
    # Check if any prohibition's key terms appear in the command
    command_lower = command.lower()
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "shall", "should", "may", "might", "must", "can", "could",
        "of", "in", "to", "for", "with", "on", "at", "by", "from",
        "not", "no", "never", "don", "dont", "stop", "avoid",
        "and", "or", "but", "if", "this", "that", "it",
    }

    for prohibition in prohibitions:
        words = re.findall(r"[a-zA-Z0-9_]+", prohibition.lower())
        key_terms = [w for w in words if w not in stopwords and len(w) >= 3]

        # Need at least 2 key term matches to avoid false positives
        matches = sum(1 for t in key_terms if t in command_lower)
        if matches >= 2 and len(key_terms) >= 2:
            # Violation detected -- block the command
            print(json.dumps({
                "decision": "block",
                "reason": f"DIRECTIVE VIOLATION: Command may violate locked belief: \"{prohibition[:120]}\"",
            }))
            sys.exit(0)

except Exception:
    pass

# No violation found -- allow
sys.exit(0)
PYEOF
