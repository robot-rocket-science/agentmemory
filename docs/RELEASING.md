# Release Runbook

Step-by-step process for releasing a new version of agentmemory.

## Prerequisites

- All tests passing: `uv run pytest tests/ -x -q`
- pyright clean: `uv run pyright src/agentmemory/`
- Working tree clean: `git status` shows nothing
- On `main` branch

## Steps

### 1. Decide the version number

- **Patch** (x.y.Z): bug fixes, docs, no new features
- **Minor** (x.Y.0): new features, backwards compatible
- **Major** (X.0.0): breaking changes, architectural shifts, significant new capabilities

### 2. Write the CHANGELOG entry

Add an entry to `CHANGELOG.md` under `## [Unreleased]`:

```markdown
## [X.Y.Z] - YYYY-MM-DD

One-sentence summary of what this release does.

### Added
- New features (one bullet per feature)

### Fixed
- Bug fixes

### Changed
- Behavioral changes (non-breaking)

### Removed
- Deprecated items removed
```

Move it from `[Unreleased]` to the versioned heading. The publish script
extracts this entry for the GitHub Release notes.

### 3. Bump version

```bash
# Edit pyproject.toml line 3
# version = "X.Y.Z"

uv lock
```

### 4. Update project docs

Check and update if version/counts changed:
- `CLAUDE.md` (project context paragraph at bottom)
- `README.md` (if benchmark results or feature list changed)

### 5. Commit

```bash
git add pyproject.toml uv.lock CHANGELOG.md CLAUDE.md README.md
git commit -m "chore: bump version to X.Y.Z"
```

### 6. Push to Gitea

```bash
git push origin main
```

### 7. Publish to GitHub + PyPI

```bash
bash scripts/publish-to-github.sh --tag vX.Y.Z
```

This script:
1. Checks `.github-exclude` for files that must not reach GitHub
2. Runs pre-push PII scan on the full tree
3. Asks for confirmation
4. Pushes `main` to the `github` remote
5. Creates and pushes the git tag
6. Creates a GitHub Release with notes from CHANGELOG.md
7. The tag triggers the PyPI publish workflow via GitHub Actions

### 8. Verify

- Check GitHub Actions: CI should pass, PyPI publish should succeed
- Check PyPI: `pip index versions agentmemory-rrs` should show the new version
- Check the update notification: next session start should NOT show an update
  (since you're on the latest)

## Troubleshooting

### PII scan blocks the push

```
BLOCKED: Sensitive patterns found in tracked files!
```

The pre-push hook found hostnames, emails, or internal references. Fix:
- Replace real hostnames with generic ones (e.g., `prodhost.internal`)
- Replace real emails with placeholders
- Remove `user@host` SSH patterns

Then commit the fix and retry.

### CHANGELOG entry not found

If the publish script falls back to auto-generated release notes, the
CHANGELOG.md entry format didn't match. The script looks for:

```
## [vX.Y.Z]    (with v prefix)
## [X.Y.Z]     (without v prefix, fallback)
```

Make sure the heading matches one of these patterns exactly.

### macOS head/sed differences

The publish script uses `sed '$d'` instead of `head -n -1` for macOS
compatibility. If you see `head: illegal line count` errors, the script
needs updating.

## Dry Run

To see what would happen without actually pushing:

```bash
bash scripts/publish-to-github.sh --tag vX.Y.Z --dry-run
```
