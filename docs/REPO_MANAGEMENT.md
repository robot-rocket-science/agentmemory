# Repository Management Guide

Reference for branch strategy, releases, PRs, CI/CD, and changelog maintenance.

## Branch Strategy: GitHub Flow

`main` is always deployable. All work happens on short-lived branches that merge back via PR.

### Branch naming

```
feature/<description>     new functionality
fix/<description>         bug fixes
hotfix/<description>      urgent production fixes
perf/<description>        performance work
docs/<description>        documentation only
chore/<description>       deps, CI, tooling
```

Lowercase, hyphens, keep it short. Optionally prefix with issue number: `fix/2-onboard-perf`.

### No release branches

At this project size, tag releases directly from `main`. Only use release branches if you need to maintain multiple major versions simultaneously (e.g., backporting security fixes to v1.x while developing v2.x).

Reference: [Vincent Driessen's Gitflow reflection](https://nvie.com/posts/a-successful-git-branching-model/) -- even the creator says Gitflow is overkill for continuously deployed software.

## Versioning (semver)

| Change type | Bump | Example |
|---|---|---|
| Bug fix, no API change | Patch | 2.0.0 -> 2.0.1 |
| New feature, backward compatible | Minor | 2.0.0 -> 2.1.0 |
| Breaking API change | Major | 2.0.0 -> 3.0.0 |
| Pre-release | Suffix | 2.1.0a1, 2.1.0b1, 2.1.0rc1 |

- `pyproject.toml` holds the canonical version: `version = "2.1.0"`
- Git tag matches with `v` prefix: `v2.1.0`
- These must be in sync. CI should verify the match.

Reference: [semver.org](https://semver.org/)

## Release Workflow

1. Work on feature/fix branch, merge to `main` via PR
2. When ready to release, create a release prep PR that:
   - Bumps version in `pyproject.toml`
   - Updates `CHANGELOG.md` (move Unreleased items to the new version)
3. Merge the release prep PR
4. Tag main: `git tag v2.1.0`
5. Push the tag: `git push origin v2.1.0` (and to other remotes)
6. Create a GitHub Release from that tag (copy changelog section as body)
7. CI publishes to PyPI on tag push (when configured)

### Creating a GitHub Release

```bash
gh release create v2.1.0 --title "v2.1.0" --notes-file /tmp/release-notes.md
```

Or use the GitHub web UI: Releases > Draft a new release > choose the tag.

## PR Workflow

### Merge strategy: squash and merge

One commit per PR on main. Full dev history preserved in the PR. Keeps main clean and bisectable.

### PR template

Lives at `.github/pull_request_template.md`:

```markdown
## Summary
<!-- What does this PR do and why? -->

## Changes
-

## Test plan
- [ ] Tests pass locally
- [ ] New tests added (if applicable)

## Related issues
<!-- Closes #123 -->
```

### Linking PRs to issues

Use keywords in the PR body: `Closes #42`, `Fixes #42`, `Resolves #42`. GitHub auto-closes the issue when the PR merges.

### Conventional commit prefixes for PR titles

```
feat: add batch ingestion
fix: correct confidence decay
perf: batch graph edge inserts
docs: update install instructions
chore: bump dependencies
test: add acceptance tests for search
refactor: extract scoring module
```

These become the squash commit messages on main, making `git log --oneline` readable.

## Branch Protection Rules (main)

Configure at Settings > Branches > Add rule for `main`:

- [x] Require a pull request before merging
- [x] Require status checks to pass before merging (CI tests)
- [x] Require branches to be up to date before merging
- [x] Require linear history (no merge commits)

Also enable in Settings > General > Pull Requests:
- [x] Automatically delete head branches

## CI/CD

### Test workflow (`ci.yml`)

Runs on every PR and push to main:

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen
      - run: uv run ruff check
      - run: uv run ruff format --check
      - run: uv run pyright
      - run: uv run pytest --tb=short
```

### Publish workflow (`publish.yml`)

Runs on tag push:

```yaml
name: Publish
on:
  push:
    tags: ["v*"]

jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv build
      - uses: pypa/gh-action-pypi-publish@release/v1
```

Add a version verification step that extracts the version from `pyproject.toml` and compares it to the git tag to catch mismatches.

## Changelog

Hand-maintained `CHANGELOG.md` following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format:

```markdown
# Changelog

## [Unreleased]

## [2.1.0] - 2026-04-20

### Added
- Batch graph edge inserts during onboard (#2)

### Fixed
- Confidence decay for stale beliefs (#43)

### Performance
- 10x onboard speedup via transaction batching

## [2.0.0] - 2026-04-18
...
```

**Sections:** Added, Changed, Fixed, Removed, Breaking, Performance.

**Workflow:** Keep an `[Unreleased]` section at the top. As PRs merge, add entries there. When cutting a release, rename it to the version/date and create a new empty `[Unreleased]`.

Automated tools to consider later if release volume grows:
- [python-semantic-release](https://github.com/python-semantic-release/python-semantic-release)
- [git-cliff](https://git-cliff.org/)

## Issue Management

### Labels

```
bug              Something isn't working
enhancement      New feature or improvement
performance      Performance related
documentation    Documentation only
breaking         Breaking change
good first issue Good for newcomers
help wanted      Extra attention needed
wontfix          Not planned
duplicate        Already exists
```

### Issue templates

Use GitHub's YAML form format at `.github/ISSUE_TEMPLATE/bug_report.yml` and `feature_request.yml`. These auto-apply labels and guide reporters through structured fields.

### Milestones

Group issues/PRs for a specific release (e.g., "v2.1.0"). Close the milestone when the release ships.

## Branch Cleanup

With "Automatically delete head branches" enabled, merged PR branches clean up automatically.

For existing stale branches:

```bash
# Prune remote tracking refs
git fetch --all --prune

# Delete local branches already merged to main
git branch --merged main | grep -v main | xargs git branch -d

# List remote branches with no recent commits
git for-each-ref --sort=committerdate refs/remotes/ --format='%(committerdate:short) %(refname:short)'
```

## Remotes

This project pushes to three remotes:

| Remote | URL | Purpose |
|---|---|---|
| `origin` | gitea:user/agentmemory.git | Primary dev (Gitea) |
| `github` | git@github.com:yoshi280/agentmemory.git | Public install source |
| `github-rrs` | git@github-rrs:robotrocketscience/agentmemory.git | Public-facing (when unlocked) |

Push to all three on release:

```bash
git push origin main --tags
git push github main --tags
git push github-rrs main --tags
```

## Quick Reference: Releasing a Version

```bash
# 1. Ensure main is clean and tests pass
git checkout main && git pull
uv run pytest

# 2. Bump version and update changelog (in a PR)
# Edit pyproject.toml version, move CHANGELOG [Unreleased] to new version

# 3. After PR merges, tag and push
git checkout main && git pull
git tag v2.1.0
git push origin main --tags
git push github main --tags
git push github-rrs main --tags

# 4. Create GitHub Release
gh release create v2.1.0 --repo yoshi280/agentmemory \
  --title "v2.1.0" --notes "$(sed -n '/## \[2.1.0\]/,/## \[/p' CHANGELOG.md | head -n -1)"
```
