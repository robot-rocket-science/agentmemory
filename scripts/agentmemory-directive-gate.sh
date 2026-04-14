#!/usr/bin/env bash
# agentmemory-directive-gate.sh -- PreToolUse soft gate
# Checks locked beliefs for potential directive violations before tool execution.
# Outputs warning text if conflict detected (injected into agent context).
# Does NOT block the tool call -- soft reminder only.
#
# Filtering to write-like tools (Edit, Write, Bash) is handled by the
# hook matcher in Claude Code settings.json, not by this script.

set -euo pipefail

# Consume stdin (Claude Code hook protocol)
cat > /dev/null

# Get locked beliefs, filter to behavioral directives
DIRECTIVES=$(uv run agentmemory locked 2>/dev/null \
    | grep -iE "never|always|do not|must not|don't|stop|banned" || true)

if [ -n "$DIRECTIVES" ]; then
    echo "ACTIVE DIRECTIVES (locked beliefs -- do not violate):"
    echo "$DIRECTIVES"
fi
