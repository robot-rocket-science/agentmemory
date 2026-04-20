# Release Runbook

## Prerequisites

- All tests pass: `uv run pytest tests/ -x -q`
- CHANGELOG.md has an entry for the new version under `## [X.Y.Z] - YYYY-MM-DD`
- `pyproject.toml` version matches the release you're about to cut
- Working tree is clean (`git status` shows no changes)
- You're on the `main` branch

## Steps

```bash
# 1. Bump version
#    Edit pyproject.toml: version = "X.Y.Z"
#    Add CHANGELOG entry under ## [X.Y.Z] - YYYY-MM-DD

# 2. Lock and commit
uv lock
git add pyproject.toml uv.lock CHANGELOG.md
git commit -m "chore: bump version to X.Y.Z"

# 3. Push to Gitea (private dev repo)
git push origin main

# 4. Publish to GitHub with tag (triggers PyPI workflow)
bash scripts/publish-to-github.sh --tag vX.Y.Z
```

## What the publish script does

1. Checks `.github-exclude` for files that shouldn't reach GitHub
2. Shows commits that will be pushed, asks for confirmation
3. Pushes current branch to `github` remote
4. Creates local tag `vX.Y.Z`
5. Pushes tag to `github` remote
6. Creates a GitHub Release (from CHANGELOG or auto-generated notes)

## What the tag triggers

Pushing a `v*` tag to GitHub triggers `.github/workflows/publish.yml`:

1. Checks out the tagged commit
2. Installs deps with `uv sync --frozen --all-groups`
3. Runs `uv run pytest tests/ --tb=short -q`
4. Builds with `uv build`
5. Publishes to PyPI via trusted publisher (OIDC, no API key)

## Verifying the release

```bash
# Check PyPI (may take 1-2 minutes after workflow completes)
curl -s "https://pypi.org/pypi/agentmemory-rrs/json" | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])"

# Check the badge (shields.io caches for up to 3 hours)
# Direct PyPI is authoritative; the badge will catch up.

# Check GitHub release exists
gh release list --repo robot-rocket-science/agentmemory --limit 3
```

## Troubleshooting

### Badge shows old version

shields.io caches badges for up to 3 hours (`max-age=10800`). PyPI is
authoritative. The badge will update on its own. Do not cut a new release
just because the badge is stale.

### PyPI workflow didn't trigger

- Verify the tag exists on GitHub: `git ls-remote github --tags 'vX*'`
- Check workflow runs: `gh run list --repo robot-rocket-science/agentmemory --limit 5`
- Common cause: tag was created but not pushed (script does both, but network failure between push and tag-push can split them)
- Fix: `git push github vX.Y.Z`

### Version mismatch between pyproject.toml and tag

The tag is what triggers the workflow. The workflow builds whatever
`pyproject.toml` says at that commit. They must match. If they don't:

```bash
# Delete the bad tag
git tag -d vX.Y.Z
git push github --delete vX.Y.Z

# Fix pyproject.toml, commit, re-tag
git commit --amend  # or new commit
bash scripts/publish-to-github.sh --tag vX.Y.Z
```

### PyPI publish fails with "version already exists"

You cannot overwrite a PyPI version. Bump to X.Y.Z+1, update CHANGELOG,
and cut a new release.
