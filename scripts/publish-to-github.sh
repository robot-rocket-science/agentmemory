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

# Collect files that should not be on GitHub
EXCLUDE_FILE=".github-exclude"
EXCLUDED_FILES=""
if [ -f "$EXCLUDE_FILE" ]; then
    echo "Checking .github-exclude..."
    while IFS= read -r pattern; do
        [[ "$pattern" =~ ^#.*$ || -z "$pattern" ]] && continue
        MATCHES=$(git ls-files -- "$pattern" 2>/dev/null || true)
        if [ -n "$MATCHES" ]; then
            EXCLUDED_FILES="${EXCLUDED_FILES}${MATCHES}"$'\n'
        fi
    done < "$EXCLUDE_FILE"

    if [ -n "$EXCLUDED_FILES" ]; then
        COUNT=$(echo "$EXCLUDED_FILES" | grep -c . || true)
        echo "  $COUNT file(s) will be excluded from GitHub push."
    else
        echo "  No excluded files found in tracked tree."
    fi
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

# If there are excluded files, create a temporary filtered commit for the push
NEEDS_RESET=false
if [ -n "$EXCLUDED_FILES" ]; then
    echo "Creating filtered commit (excluding private files)..."
    echo "$EXCLUDED_FILES" | while IFS= read -r f; do
        [ -n "$f" ] && git rm --cached -q "$f" 2>/dev/null || true
    done
    git commit -q -m "chore: filtered publish (excluded files removed)" --allow-empty
    NEEDS_RESET=true
fi

# Push (pre-push hook will run PII scan automatically)
git push "$REMOTE" "$BRANCH"

# Reset the temporary commit so excluded files are tracked again for origin
if [ "$NEEDS_RESET" = true ]; then
    echo "Restoring excluded files to local tracking..."
    git reset -q HEAD~1
    git checkout -q -- .
fi

if [ -n "$TAG" ]; then
    git tag "$TAG"
    git push "$REMOTE" "$TAG"
    echo ""
    echo "Tagged $TAG and pushed. PyPI publish workflow will trigger."

    # Create GitHub Release from CHANGELOG entry
    echo "Creating GitHub Release..."
    CHANGELOG_ENTRY=$(sed -n "/^## \[$TAG\]/,/^## \[/p" CHANGELOG.md 2>/dev/null | sed '$d')
    if [ -z "$CHANGELOG_ENTRY" ]; then
        # Try without v prefix
        TAG_NO_V="${TAG#v}"
        CHANGELOG_ENTRY=$(sed -n "/^## \[$TAG_NO_V\]/,/^## \[/p" CHANGELOG.md 2>/dev/null | sed '$d')
    fi
    if [ -n "$CHANGELOG_ENTRY" ]; then
        gh release create "$TAG" --repo "$(git remote get-url "$REMOTE" | sed 's|.*github.com[:/]||;s|\.git$||')" \
            --title "$TAG" --notes "$CHANGELOG_ENTRY" 2>/dev/null && \
            echo "GitHub Release created." || \
            echo "Warning: could not create GitHub Release. Create manually at the repo."
    else
        gh release create "$TAG" --repo "$(git remote get-url "$REMOTE" | sed 's|.*github.com[:/]||;s|\.git$||')" \
            --title "$TAG" --generate-notes 2>/dev/null && \
            echo "GitHub Release created (auto-generated notes)." || \
            echo "Warning: could not create GitHub Release. Create manually at the repo."
    fi
fi

echo ""
echo "Published to GitHub successfully."
