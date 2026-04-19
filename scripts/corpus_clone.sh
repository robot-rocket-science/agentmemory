#!/usr/bin/env bash
# corpus_clone.sh -- Idempotent clone/update of research corpus on server-a
#
# Usage: ./scripts/corpus_clone.sh [--tier small|medium|large|all] [--personal] [--dry-run]
#
# Idempotency:
#   - Existing repos: git fetch --all (update, don't re-clone)
#   - Missing repos: git clone (full history)
#   - Interrupted clones (no .git/HEAD): remove and re-clone
#   - Cache: writes .corpus_state.json with clone timestamps and sizes
#
# Tier sizing (by expected clone size):
#   small:  < 100MB  (smoltcp, quinn, rustls, boa, rclcpp, dealii, su2, commonmark-spec, adr)
#   medium: 100MB-1GB (ludwig, dagster, blitz, saleor, nx, bullet3, micropython)
#   large:  > 1GB    (terraform, pulumi, babel, bevy, duckdb, cockroach, esp-idf, airflow, taichi, mlflow, px4, openssl)
#
set -euo pipefail

server-a="server-a"
BASE="~/agentmemory-corpus"
PROJECTS_DIR="${PROJECTS_DIR:-$HOME/projects}"
TIER="${1:---tier}"
TIER_VAL="small"
DO_PERSONAL=false
DRY_RUN=false

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tier) TIER_VAL="$2"; shift 2 ;;
        --personal) DO_PERSONAL=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) shift ;;
    esac
done

# Repo manifest: category/dirname URL tier
REPOS=(
    # --- small (< 100MB expected) ---
    "networking/smoltcp     https://github.com/smoltcp-rs/smoltcp.git           small"
    "networking/quinn       https://github.com/quinn-rs/quinn.git               small"
    "security/rustls        https://github.com/rustls/rustls.git                small"
    "compiler/boa           https://github.com/boa-dev/boa.git                  small"
    "controls/rclcpp        https://github.com/ros2/rclcpp.git                  small"
    "scicomp/dealii         https://github.com/dealii/dealii.git                small"
    "scicomp/su2            https://github.com/su2code/SU2.git                  small"
    "docs/commonmark-spec   https://github.com/commonmark/commonmark-spec.git   small"
    "docs/adr               https://github.com/joelparkerhenderson/architecture-decision-record.git small"

    # --- medium (100MB - 1GB expected) ---
    "aiml/ludwig            https://github.com/ludwig-ai/ludwig.git             medium"
    "etl/dagster            https://github.com/dagster-io/dagster.git           medium"
    "web/blitz              https://github.com/blitz-js/blitz.git               medium"
    "web/saleor             https://github.com/saleor/saleor.git                medium"
    "monorepo/nx            https://github.com/nrwl/nx.git                      medium"
    "physics/bullet3        https://github.com/bulletphysics/bullet3.git        medium"
    "embedded/micropython   https://github.com/micropython/micropython.git      medium"

    # --- large (> 1GB expected) ---
    "devops/terraform       https://github.com/hashicorp/terraform.git          large"
    "devops/pulumi          https://github.com/pulumi/pulumi.git                large"
    "compiler/babel         https://github.com/babel/babel.git                  large"
    "game/bevy              https://github.com/bevyengine/bevy.git              large"
    "database/duckdb        https://github.com/duckdb/duckdb.git                large"
    "database/cockroach     https://github.com/cockroachdb/cockroach.git        large"
    "embedded/esp-idf       https://github.com/espressif/esp-idf.git            large"
    "etl/airflow            https://github.com/apache/airflow.git               large"
    "physics/taichi         https://github.com/taichi-dev/taichi.git            large"
    "aiml/mlflow            https://github.com/mlflow/mlflow.git                large"
    "controls/px4-autopilot https://github.com/PX4/PX4-Autopilot.git           large"
    "security/openssl       https://github.com/openssl/openssl.git              large"
)

# Personal projects to mirror
PERSONAL_REPOS=(
    "project-a"
    "project-b"
    "gsd-2"
    "project-d"
    "project-e"
    "evolve"
    "bigtime"
    "project-f"
    "project-g-arbitrage"
    "project-a-test"
    "project-c"
)

# Filter repos by tier
should_include() {
    local repo_tier="$1"
    case "$TIER_VAL" in
        small)  [[ "$repo_tier" == "small" ]] ;;
        medium) [[ "$repo_tier" == "small" || "$repo_tier" == "medium" ]] ;;
        large)  [[ "$repo_tier" == "small" || "$repo_tier" == "medium" || "$repo_tier" == "large" ]] ;;
        all)    true ;;
        *)      echo "Unknown tier: $TIER_VAL"; exit 1 ;;
    esac
}

# Remote clone/update function
clone_or_update() {
    local dest="$1"  # relative to BASE/public/
    local url="$2"
    local full_path="${BASE}/public/${dest}"

    echo "==> ${dest}"

    if $DRY_RUN; then
        echo "    [dry-run] would clone/update ${url} -> ${full_path}"
        return 0
    fi

    # Check if repo exists and is valid
    # Note: ~ expands on the remote side inside the heredoc since we don't quote REMOTE_EOF
    ssh "$server-a" bash <<REMOTE_EOF
        set -euo pipefail
        full="\$HOME/agentmemory-corpus/public/${dest}"

        if [ -d "\$full/.git" ] && [ -f "\$full/.git/HEAD" ]; then
            echo "    [fetch] \$full"
            cd "\$full"
            git fetch --all --prune 2>&1 | sed 's/^/    /'
        elif [ -d "\$full" ]; then
            echo "    [broken clone, removing] \$full"
            rm -rf "\$full"
            echo "    [clone] ${url}"
            git clone "${url}" "\$full" 2>&1 | tail -1 | sed 's/^/    /'
        else
            echo "    [clone] ${url}"
            mkdir -p "\$(dirname "\$full")"
            git clone "${url}" "\$full" 2>&1 | tail -1 | sed 's/^/    /'
        fi

        # Record state
        cd "\$full"
        commits=\$(git rev-list --count HEAD 2>/dev/null || echo 0)
        size=\$(du -sh . 2>/dev/null | cut -f1)
        echo "    [done] \${commits} commits, \${size}"
REMOTE_EOF
}

# Mirror personal project
mirror_personal() {
    local name="$1"
    local src="${PROJECTS_DIR}/${name}"
    local dest="${BASE}/personal/${name}"

    echo "==> personal/${name}"

    if $DRY_RUN; then
        echo "    [dry-run] would rsync ${src} -> server-a:~/agentmemory-corpus/personal/${name}"
        return 0
    fi

    # Use rsync with .git included for full history
    local remote_dest="/home/user/agentmemory-corpus/personal/${name}"
    ssh "$server-a" "mkdir -p '${remote_dest}'"
    rsync -az --delete \
        --exclude='.venv' \
        --exclude='node_modules' \
        --exclude='target' \
        --exclude='__pycache__' \
        --exclude='.mypy_cache' \
        --exclude='*.duckdb' \
        --exclude='*.db' \
        --exclude='dist' \
        --exclude='.ruff_cache' \
        --exclude='uv.lock' \
        "${src}/" "${server-a}:${remote_dest}/"

    echo "    [synced]"
}

echo "Corpus clone/update -- tier: ${TIER_VAL}, personal: ${DO_PERSONAL}, dry-run: ${DRY_RUN}"
echo "Target: ${server-a}:${BASE}"
echo ""

# Public repos
count=0
skipped=0
for entry in "${REPOS[@]}"; do
    read -r dest url tier <<< "$entry"
    if should_include "$tier"; then
        clone_or_update "$dest" "$url"
        ((count++))
    else
        ((skipped++))
    fi
done

echo ""
echo "Public repos: ${count} processed, ${skipped} skipped (tier filter)"

# Personal repos
if $DO_PERSONAL; then
    echo ""
    echo "--- Personal projects ---"
    for name in "${PERSONAL_REPOS[@]}"; do
        if [ -d "${PROJECTS_DIR}/${name}" ]; then
            mirror_personal "$name"
        else
            echo "==> personal/${name} [SKIP: not found locally]"
        fi
    done
fi

echo ""
echo "Done."
