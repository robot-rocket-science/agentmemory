#!/usr/bin/env bash
# pre-push-public-guard.sh
#
# Blocks pushes to the public GitHub remote if sensitive patterns are
# detected in the diff. Runs only for the "github" remote.
#
# Install: cp scripts/pre-push-public-guard.sh .git/hooks/pre-push && chmod +x .git/hooks/pre-push
# Or: uv run pre-commit install --hook-type pre-push

set -euo pipefail

REMOTE="$1"
URL="$2"

# Only gate pushes to the public github remote
if [[ "$URL" != *"robot-rocket-science"* && "$URL" != *"github.com"* ]]; then
    exit 0
fi

echo "[pre-push] Scanning for sensitive patterns before pushing to public remote..."

# Patterns that should never reach the public repo
BLOCKED_PATTERNS=(
    # Personal info
    'jonsobol@gmail\.com'
    '/Users/thelorax/'
    '/home/jso/'
    '\bthelorax\b'
    # Internal hostnames
    '\barchon\b'
    '\bmintaka\b'
    '\bwillow\b'
    'mintaka:2222'
    'gitea:jso/'
    # Private project names
    '\balpha-seek\b'
    '\balpha_seek\b'
    '\boptimus-prime\b'
    '\boptimus_prime\b'
    '\bdebserver\b'
    '\bjose-bully\b'
    '\bjose_bully\b'
    '\bcode-monkey\b'
    '\bemail-secretary\b'
    '\bsports-betting'
    '\bbigtime\b'
    '\bgsd-2\b'
    'alpha-seek-memtest'
    # Infrastructure IDs
    'secretary-487605'
    'dry-term-30e8'
    '3ea14047-e013-455b-80c7-b9d0628d469c'
    '4704e38d-1366-4d13-ac03-c1563096d9f3'
)

# Build combined regex
REGEX=$(IFS='|'; echo "${BLOCKED_PATTERNS[*]}")

# FULL TREE SCAN: check ALL tracked files, not just the diff.
echo "[pre-push] Scanning full tree for sensitive patterns..."
TREE_MATCHES=$(git ls-files -- '*.py' '*.md' '*.txt' '*.sh' '*.toml' '*.json' '*.yaml' '*.yml' \
    ':!:scripts/pre-push-public-guard.sh' ':!:scripts/sanitize-for-public.sh' \
    | xargs grep -ilE "$REGEX" 2>/dev/null || true)

if [ -n "$TREE_MATCHES" ]; then
    echo ""
    echo "BLOCKED: Sensitive patterns found in tracked files!"
    echo ""
    echo "$TREE_MATCHES" | head -20
    FILE_COUNT=$(echo "$TREE_MATCHES" | wc -l | tr -d ' ')
    if [ "$FILE_COUNT" -gt 20 ]; then
        echo "  ... and $((FILE_COUNT - 20)) more files"
    fi
    echo ""
    echo "Run: bash scripts/sanitize-for-public.sh --apply"
    echo "Override: git push --no-verify (use with caution)"
    exit 1
fi

# The full tree scan above is sufficient. No diff-based check needed
# since the tree scan covers all tracked files in their current state.
# (A diff-based check would false-positive on removed lines containing
# PII that existed in the old remote branch.)

echo "[pre-push] Clean. Pushing to $REMOTE."
exit 0
