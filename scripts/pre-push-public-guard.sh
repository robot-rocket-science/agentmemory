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
    # Internal hostnames
    '\barchon\b'
    '\bmintaka\b'
    'mintaka:2222'
    'gitea:jso/'
    # Private project names
    '\balpha-seek\b'
    '\boptimus-prime\b'
    '\bdebserver\b'
    '\bjose-bully\b'
    '\bcode-monkey\b'
    '\bemail-secretary\b'
    '\bsports-betting'
    '\bbigtime\b'
)

# Build combined regex
REGEX=$(IFS='|'; echo "${BLOCKED_PATTERNS[*]}")

# Check all files that differ from the remote
while read -r local_ref local_oid remote_ref remote_oid; do
    if [ "$local_oid" = "0000000000000000000000000000000000000000" ]; then
        continue  # branch deletion
    fi

    if [ "$remote_oid" = "0000000000000000000000000000000000000000" ]; then
        # New branch, check all files
        RANGE="$local_oid"
    else
        RANGE="${remote_oid}..${local_oid}"
    fi

    # Check diff content for blocked patterns
    MATCHES=$(git diff "$RANGE" -- . ':(exclude).git' 2>/dev/null | grep -iEn "$REGEX" || true)

    if [ -n "$MATCHES" ]; then
        echo ""
        echo "BLOCKED: Sensitive patterns detected in push to public remote!"
        echo ""
        echo "$MATCHES" | head -20
        echo ""
        echo "Fix: Remove or redact the matched content before pushing."
        echo "Override: git push --no-verify (use with caution)"
        exit 1
    fi
done

echo "[pre-push] Clean. Pushing to $REMOTE."
exit 0
