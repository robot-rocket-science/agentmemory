#!/usr/bin/env bash
# publish-to-github.sh
#
# Intentional, controlled release of the current branch to GitHub.
# This is NOT a mirror -- it pushes only what you explicitly choose.
#
# Safety layers:
#   1. .github-exclude file lists paths that never go to GitHub
#   2. pre-push hook scans for PII patterns
#   3. Manual confirmation before push
#
# Usage:
#   bash scripts/publish-to-github.sh              # push current branch
#   bash scripts/publish-to-github.sh --tag v3.0.0 # push + tag (triggers PyPI publish)
#   bash scripts/publish-to-github.sh --dry-run    # show what would be pushed, don't push

set -euo pipefail

TAG=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag) TAG="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

BRANCH=$(git rev-parse --abbrev-ref HEAD)
REMOTE="github"

echo "=== Publish to GitHub ==="
echo "Branch: $BRANCH"
echo "Remote: $REMOTE"
if [ -n "$TAG" ]; then
    echo "Tag:    $TAG"
fi
echo ""

# Check for files that should not be on GitHub
EXCLUDE_FILE=".github-exclude"
if [ -f "$EXCLUDE_FILE" ]; then
    echo "Checking .github-exclude..."
    VIOLATIONS=""
    while IFS= read -r pattern; do
        # Skip comments and blank lines
        [[ "$pattern" =~ ^#.*$ || -z "$pattern" ]] && continue
        MATCHES=$(git ls-files -- "$pattern" 2>/dev/null || true)
        if [ -n "$MATCHES" ]; then
            VIOLATIONS="${VIOLATIONS}${MATCHES}\n"
        fi
    done < "$EXCLUDE_FILE"

    if [ -n "$VIOLATIONS" ]; then
        echo ""
        echo "BLOCKED: Files matching .github-exclude are tracked:"
        echo -e "$VIOLATIONS" | head -20
        echo ""
        echo "Remove them from git tracking before publishing:"
        echo "  git rm --cached <file>"
        echo "  git commit -m 'chore: remove private files from tracking'"
        exit 1
    fi
    echo "  No excluded files found in tracked tree."
fi

# Show what will be pushed
echo ""
echo "Commits to push:"
git log --oneline "$REMOTE/$BRANCH..$BRANCH" 2>/dev/null || git log --oneline -5
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "[DRY RUN] Would push $BRANCH to $REMOTE"
    if [ -n "$TAG" ]; then
        echo "[DRY RUN] Would create and push tag $TAG"
    fi
    exit 0
fi

# Confirm
read -p "Push to GitHub? [y/N] " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# Push (pre-push hook will run PII scan automatically)
git push "$REMOTE" "$BRANCH"

if [ -n "$TAG" ]; then
    git tag "$TAG"
    git push "$REMOTE" "$TAG"
    echo ""
    echo "Tagged $TAG and pushed. PyPI publish workflow will trigger."
fi

echo ""
echo "Published to GitHub successfully."
