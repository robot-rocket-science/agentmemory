from __future__ import annotations

"""
Generate blind evaluation sheets for Experiment 3.

Runs all 20 queries through FTS5, BFS, and Hybrid retrieval.
Produces a single JSON file with shuffled results for human labeling.
Method attribution is stored separately and revealed only after labeling.
"""

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from experiments.exp3_retrieval_comparison import (
    load_graph, build_fts_index, prepare_blind_evaluation, ALPHA_SEEK_DB
)


def main() -> None:
    nodes, adj = load_graph(ALPHA_SEEK_DB)
    fts_db = build_fts_index(nodes)

    queries: list[dict[str, str]] = json.loads(Path("experiments/exp3_queries.json").read_text())

    all_evals: list[dict[str, Any]] = []
    all_attributions: dict[str, Any] = {}
    total_items = 0

    for q in queries:
        ev: dict[str, Any] = prepare_blind_evaluation(q["query"], q["id"], nodes, fts_db, adj)
        ev["original_query"] = q["original"]

        # Separate attribution from eval sheet
        attribution: Any = ev.pop("_attribution")
        all_attributions[q["id"]] = attribution

        all_evals.append(ev)
        total_items += ev["n_unique_results"]

        print(f"  {q['id']}: {ev['n_unique_results']} items", file=sys.stderr)

    print(f"\nTotal items to label: {total_items}", file=sys.stderr)
    print(f"Queries: {len(queries)}", file=sys.stderr)

    # Write eval sheets (for human labeling -- no method info)
    eval_path = Path("experiments/exp3_eval_sheets.json")
    eval_path.write_text(json.dumps(all_evals, indent=2))
    print(f"Eval sheets: {eval_path}", file=sys.stderr)

    # Write attribution (hidden until after labeling)
    attr_path = Path("experiments/exp3_attribution.json")
    attr_path.write_text(json.dumps(all_attributions, indent=2))
    print(f"Attribution (DO NOT READ UNTIL LABELING COMPLETE): {attr_path}", file=sys.stderr)

    # Write a human-readable labeling form
    form_path = Path("experiments/exp3_labeling_form.md")
    lines: list[str] = [
        "# Experiment 3: Retrieval Quality Labeling Form",
        "",
        "For each query, label every result as:",
        "- **R** = Relevant (this belief should be in the result set)",
        "- **P** = Partially relevant (related but not directly useful)",
        "- **N** = Not relevant (noise)",
        "",
        "Do NOT look at exp3_attribution.json until all labeling is complete.",
        "",
        "---",
        "",
    ]

    for ev in all_evals:
        lines.append(f"## {ev['query_id']}: {ev['original_query']}")
        lines.append(f"*Search terms: {ev['query']}*")
        lines.append("")
        lines.append("| # | Label | Content | Category |")
        lines.append("|---|-------|---------|----------|")
        for item in ev["eval_items"]:
            content_short: str = item["content"][:80].replace("|", "/")
            lines.append(f"| {item['eval_id']} | ___ | {content_short} | {item['category']} |")
        lines.append("")

    form_path.write_text("\n".join(lines))
    print(f"Labeling form: {form_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
