"""Prune function-definition beliefs that are code index entries, not beliefs.

Per locked belief: "Prune the ~834 function-definition beliefs.
These are code index entries, not beliefs."

Identifies beliefs matching patterns like "def function_name" that were
bulk-ingested as factual beliefs but are actually code structure metadata.
Soft-deletes them (sets valid_to, does not hard-delete).
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    cwd: str = str(Path.cwd().resolve())
    path_hash: str = hashlib.sha256(cwd.encode()).hexdigest()[:12]
    db_path: Path = Path.home() / ".agentmemory" / "projects" / path_hash / "memory.db"

    if not db_path.exists():
        print(f"No database at {db_path}")
        sys.exit(1)

    db: sqlite3.Connection = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row

    # Find function-definition beliefs
    # Pattern: content starts with "def " or contains only a function signature
    rows: list[sqlite3.Row] = db.execute(
        """SELECT id, content, belief_type, source_type, locked
           FROM beliefs
           WHERE valid_to IS NULL
             AND (content LIKE 'def %' OR content LIKE 'def_%')
             AND source_type = 'agent_inferred'
             AND locked = 0"""
    ).fetchall()

    # Filter to actual function definitions (not sentences that happen to start with "def")
    func_def_pattern: re.Pattern[str] = re.compile(r"^def\s+[a-zA-Z_]\w*")
    candidates: list[sqlite3.Row] = [
        r for r in rows if func_def_pattern.match(r["content"])
    ]

    print(f"Found {len(candidates)} function-definition beliefs to prune")
    print(f"  (from {len(rows)} 'def' matches, filtered by regex)")

    if not candidates:
        db.close()
        return

    # Show first 5 examples
    print("\nExamples:")
    for r in candidates[:5]:
        print(f"  [{r['belief_type']}] {r['content'][:80]}")

    # Soft-delete
    now: str = datetime.now(timezone.utc).isoformat()
    deleted: int = 0
    for r in candidates:
        db.execute(
            "UPDATE beliefs SET valid_to = ?, updated_at = ? WHERE id = ?",
            (now, now, r["id"]),
        )
        deleted += 1

    db.commit()

    active_after: int = db.execute(
        "SELECT COUNT(*) FROM beliefs WHERE valid_to IS NULL"
    ).fetchone()[0]

    print(f"\nPruned {deleted} function-definition beliefs")
    print(f"Active beliefs remaining: {active_after}")

    db.close()


if __name__ == "__main__":
    main()
