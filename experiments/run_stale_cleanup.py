"""Execute stale belief cleanup: auto-supersede agent_inferred beliefs
contradicted by higher-provenance beliefs (locked/user_corrected).

This script modifies the production database. Run the audit first
(stale_cleanup_audit.py) to see what will be changed.
"""
from __future__ import annotations

import hashlib
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

    # Find auto-supersedable pairs
    rows: list[sqlite3.Row] = db.execute(
        """SELECT e.id AS edge_id, e.from_id, e.to_id,
                  a.id AS a_id, a.source_type AS a_src, a.locked AS a_locked, a.content AS a_content,
                  b.id AS b_id, b.source_type AS b_src, b.locked AS b_locked, b.content AS b_content
           FROM edges e
           JOIN beliefs a ON a.id = e.from_id
           JOIN beliefs b ON b.id = e.to_id
           WHERE e.edge_type = 'CONTRADICTS'
             AND a.valid_to IS NULL
             AND b.valid_to IS NULL"""
    ).fetchall()

    def provenance_rank(locked: bool, src: str) -> int:
        if locked:
            return 3
        if src == "user_corrected":
            return 2
        if src == "user_stated":
            return 1
        return 0  # agent_inferred

    now: str = datetime.now(timezone.utc).isoformat()
    superseded: int = 0
    skipped: int = 0

    for r in rows:
        a_rank: int = provenance_rank(bool(r["a_locked"]), r["a_src"])
        b_rank: int = provenance_rank(bool(r["b_locked"]), r["b_src"])

        if a_rank == b_rank:
            skipped += 1
            continue

        # Higher rank wins, lower rank gets superseded
        if a_rank > b_rank:
            winner_id: str = r["a_id"]
            loser_id: str = r["b_id"]
        else:
            winner_id = r["b_id"]
            loser_id = r["a_id"]

        # Supersede the loser
        db.execute(
            "UPDATE beliefs SET valid_to = ?, superseded_by = ?, updated_at = ? WHERE id = ?",
            (now, winner_id, now, loser_id),
        )
        # Create SUPERSEDES edge
        db.execute(
            """INSERT INTO edges (from_id, to_id, edge_type, weight, reason, created_at)
               VALUES (?, ?, 'SUPERSEDES', 1.0, 'provenance_cleanup', ?)""",
            (winner_id, loser_id, now),
        )
        superseded += 1

    db.commit()

    # Verify
    active_after: int = db.execute(
        "SELECT COUNT(*) FROM beliefs WHERE valid_to IS NULL"
    ).fetchone()[0]

    print(f"Stale cleanup complete:")
    print(f"  Superseded: {superseded}")
    print(f"  Skipped (same level): {skipped}")
    print(f"  Active beliefs remaining: {active_after}")

    db.close()


if __name__ == "__main__":
    main()
