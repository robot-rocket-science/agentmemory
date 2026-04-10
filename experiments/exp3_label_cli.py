"""
Interactive CLI labeling tool for Experiment 3.

Shows one result at a time per query. You score 1-5.
Progress is saved after each query so you can stop and resume.

Usage: uv run python experiments/exp3_label_cli.py
"""

import json
import sqlite3
import sys
from pathlib import Path


EVAL_PATH = Path("experiments/exp3_eval_sheets_v2.json")
LABELS_PATH = Path("experiments/exp3_labels.json")
ALPHA_SEEK_DB = Path("/Users/thelorax/projects/.gsd/workflows/spikes/"
                     "260406-1-associative-memory-for-gsd-please-explor/"
                     "sandbox/alpha-seek.db")


def load_rich_content() -> dict[str, str]:
    """Load richer content from source tables for terse mem_nodes entries."""
    enriched = {}
    db = sqlite3.connect(str(ALPHA_SEEK_DB))

    # Decisions: combine decision + choice + rationale
    for row in db.execute("SELECT id, decision, choice, rationale FROM decisions"):
        parts = [row[1] or "", row[2] or ""]
        if row[3]:
            parts.append(f"Rationale: {row[3][:200]}")
        enriched[row[0]] = " | ".join(p for p in parts if p)

    # Milestones: get the title from mem_nodes (already there) but also check milestones table
    for row in db.execute("SELECT id, content FROM mem_nodes WHERE source_type='milestone'"):
        node_id = row[0]
        if node_id not in enriched:
            # Try to find more context from edges
            edges = db.execute(
                "SELECT n.id, n.content FROM mem_edges e JOIN mem_nodes n ON e.from_id = n.id "
                "WHERE e.to_id = ? LIMIT 5", (node_id,)
            ).fetchall()
            if edges:
                related = "; ".join(f"{e[0]}: {e[1][:60]}" for e in edges)
                enriched[node_id] = f"{row[1]} -- Related: {related}"

    # Compute sequence context: what's the ID range so we can show relative age
    max_d = db.execute("SELECT MAX(CAST(SUBSTR(id, 2) AS INTEGER)) FROM mem_nodes WHERE id LIKE 'D%'").fetchone()[0] or 0
    max_m = db.execute("SELECT MAX(CAST(SUBSTR(id, 3) AS INTEGER)) FROM mem_nodes WHERE id LIKE '_M%'").fetchone()[0] or 0
    max_k = db.execute("SELECT MAX(CAST(SUBSTR(id, 2) AS INTEGER)) FROM mem_nodes WHERE id LIKE 'K%'").fetchone()[0] or 0
    enriched["_meta_max_d"] = max_d
    enriched["_meta_max_m"] = max_m
    enriched["_meta_max_k"] = max_k

    # Check supersession
    for row in db.execute("SELECT id, superseded_by FROM mem_nodes WHERE superseded_by IS NOT NULL"):
        enriched[f"_superseded_{row[0]}"] = row[1]

    db.close()
    return enriched


def load_progress() -> dict:
    if LABELS_PATH.exists():
        return json.loads(LABELS_PATH.read_text())
    return {}


def save_progress(labels: dict):
    LABELS_PATH.write_text(json.dumps(labels, indent=2))


def main():
    evals = json.loads(EVAL_PATH.read_text())
    labels = load_progress()
    rich_content = load_rich_content()

    total_items = sum(len(e["eval_items"]) for e in evals)
    labeled_count = sum(len(v) for v in labels.values())

    print(f"\n{'='*60}")
    print(f"Experiment 3: Retrieval Quality Labeling")
    print(f"  {total_items} total items across {len(evals)} queries")
    print(f"  {labeled_count} already labeled")
    print(f"{'='*60}")
    print(f"\nFor each result, score 0-5:")
    print(f"  5 = Directly answers the query -- the LLM needs this")
    print(f"  4 = Strongly relevant -- important supporting context")
    print(f"  3 = Useful but not essential -- helps if token budget allows")
    print(f"  2 = Tangentially related -- same area but doesn't help this query")
    print(f"  1 = Not relevant -- noise, wastes tokens")
    print(f"  0 = Can't assess -- not enough context to judge (temporal, missing detail)")
    print(f"  S = Skip this query")
    print(f"  Q = Quit (progress saved)\n")

    for ev in evals:
        qid = ev["query_id"]

        # Skip already-completed queries
        if qid in labels and len(labels[qid]) == len(ev["eval_items"]):
            continue

        print(f"\n{'─'*60}")
        print(f"Query {qid}: {ev.get('original_query', ev['query'])}")
        print(f"  ({len(ev['eval_items'])} results to label)")
        print(f"{'─'*60}\n")

        if qid not in labels:
            labels[qid] = {}

        for i, item in enumerate(ev["eval_items"]):
            eid = item["eval_id"]

            # Skip already-labeled items
            if eid in labels[qid]:
                continue

            # Show enriched content if available, otherwise the default
            node_id = item["node_id"]
            display = rich_content.get(node_id, item["content"])

            # Temporal context: relative age based on ID sequence
            age_hint = ""
            import re
            if m := re.match(r"D(\d+)", node_id):
                num = int(m.group(1))
                max_d = rich_content.get("_meta_max_d", 999)
                pct = num / max_d if max_d else 0
                age_hint = f"decision {num}/{max_d} ({'early' if pct < 0.3 else 'mid' if pct < 0.7 else 'recent'})"
            elif m := re.match(r"_M(\d+)", node_id):
                num = int(m.group(1))
                max_m = rich_content.get("_meta_max_m", 999)
                pct = num / max_m if max_m else 0
                age_hint = f"milestone {num}/{max_m} ({'early' if pct < 0.3 else 'mid' if pct < 0.7 else 'recent'})"
            elif m := re.match(r"K(\d+)", node_id):
                num = int(m.group(1))
                max_k = rich_content.get("_meta_max_k", 999)
                pct = num / max_k if max_k else 0
                age_hint = f"knowledge {num}/{max_k} ({'early' if pct < 0.3 else 'mid' if pct < 0.7 else 'recent'})"

            # Supersession status
            sup_key = f"_superseded_{node_id}"
            if sup_key in rich_content:
                age_hint += f" [SUPERSEDED by {rich_content[sup_key]}]"

            print(f"  [{i+1}/{len(ev['eval_items'])}] ({node_id}) {display}")
            if node_id in rich_content and rich_content[node_id] != item["content"]:
                print(f"           [short: {item['content'][:80]}]")
            meta_parts = [f"category: {item['category']}", f"source: {item['source_type']}"]
            if age_hint:
                meta_parts.append(age_hint)
            print(f"           {' | '.join(meta_parts)}")

            while True:
                try:
                    choice = input("  Score (1-5/S/Q): ").strip().upper()
                except (EOFError, KeyboardInterrupt):
                    print("\nSaving progress...")
                    save_progress(labels)
                    print(f"Saved. {sum(len(v) for v in labels.values())} labels recorded.")
                    return

                if choice == "Q":
                    save_progress(labels)
                    print(f"\nSaved. {sum(len(v) for v in labels.values())} labels recorded.")
                    return
                elif choice == "S":
                    break
                elif choice in ("0", "1", "2", "3", "4", "5"):
                    labels[qid][eid] = int(choice)
                    break
                else:
                    print("  Invalid. Type 1-5, S, or Q.")

            if choice == "S":
                print(f"  Skipping {qid}")
                break

        save_progress(labels)
        done = sum(len(v) for v in labels.values())
        print(f"  [Saved: {done}/{total_items} labeled]")

    print(f"\n{'='*60}")
    print(f"Labeling complete! {sum(len(v) for v in labels.values())} labels recorded.")
    print(f"Run scoring: uv run python experiments/exp3_score.py")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
