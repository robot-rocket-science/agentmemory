#!/usr/bin/env bash
# extract_all.sh -- Run all extractors + HRR encoder on every repo in the corpus.
#
# Usage: ./scripts/extract_all.sh [--skip-existing]
#
# Idempotent: each extractor caches by HEAD hash. --skip-existing skips
# repos that already have all 4 extraction outputs.
set -euo pipefail

BASE="$HOME/agentmemory-corpus"
EXTRACTED="$BASE/extracted"
SCRIPTS="$BASE/scripts"
SKIP_EXISTING="${1:-}"

mkdir -p "$EXTRACTED"/{git_edges,import_edges,structural_edges,node_types,hrr,validation}

# Collect all repos
repos=()
for d in "$BASE"/personal/*; do
    [ -d "$d/.git" ] && repos+=("$d")
done
for d in "$BASE"/public/*/*; do
    [ -d "$d/.git" ] && repos+=("$d")
done

echo "Found ${#repos[@]} repos"
echo ""

total=${#repos[@]}
i=0
for repo in "${repos[@]}"; do
    i=$((i+1))
    name=$(basename "$repo")
    echo "================================================================"
    echo "[$i/$total] $name"
    echo "================================================================"

    # Check if already fully extracted
    if [ "$SKIP_EXISTING" = "--skip-existing" ]; then
        if [ -f "$EXTRACTED/git_edges/$name.json" ] && \
           [ -f "$EXTRACTED/import_edges/$name.json" ] && \
           [ -f "$EXTRACTED/structural_edges/$name.json" ] && \
           [ -f "$EXTRACTED/node_types/$name.json" ] && \
           [ -f "$EXTRACTED/hrr/$name.json" ]; then
            echo "  [skip] all outputs exist"
            echo ""
            continue
        fi
    fi

    # Git edges
    echo "  --- git edges ---"
    python3 "$SCRIPTS/extract_git_edges.py" "$repo" --output "$EXTRACTED/git_edges/$name.json" 2>&1 | sed 's/^/  /'

    # Import edges
    echo "  --- import edges ---"
    python3 "$SCRIPTS/extract_import_edges.py" "$repo" --output "$EXTRACTED/import_edges/$name.json" 2>&1 | sed 's/^/  /'

    # Structural edges
    echo "  --- structural edges ---"
    python3 "$SCRIPTS/extract_structural_edges.py" "$repo" --output "$EXTRACTED/structural_edges/$name.json" 2>&1 | sed 's/^/  /'

    # Node types
    echo "  --- node types ---"
    python3 "$SCRIPTS/classify_nodes.py" "$repo" --output "$EXTRACTED/node_types/$name.json" 2>&1 | sed 's/^/  /'

    # HRR encoding (adaptive threshold + routing)
    echo "  --- HRR encoding ---"
    PYTHONPATH="$SCRIPTS" python3 "$SCRIPTS/hrr_encoder.py" "$EXTRACTED" "$name" --routing routed --output "$EXTRACTED/hrr/$name.json" 2>&1 | sed 's/^/  /'

    echo ""
done

echo "================================================================"
echo "Done. All $total repos processed."
echo "================================================================"

# Summary
echo ""
echo "Output counts:"
for subdir in git_edges import_edges structural_edges node_types hrr; do
    count=$(ls "$EXTRACTED/$subdir"/*.json 2>/dev/null | wc -l)
    echo "  $subdir: $count files"
done
