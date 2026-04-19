"""Analyze injection relevance for the agentmemory hook system.

Reads conversation logs, simulates hook_search for each user prompt,
and measures how relevant the injected beliefs were to the prompt
and subsequent assistant response.

Usage:
    uv run scripts/analyze_injection_relevance.py
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# Allow importing from src/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agentmemory.hook_search import (  # noqa: E402
    ScoredBelief,
    SearchResult,
    format_ba_injection,
    search_for_prompt,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONV_LOG_DIR = Path.home() / ".claude" / "conversation-logs"
AGENTMEMORY_DIR = Path.home() / ".agentmemory" / "projects"
MIN_PROMPT_LEN = 5
RELEVANT_THRESHOLD = 0.1
PARTIAL_THRESHOLD = 0.05


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class BeliefRelevance:
    """Relevance measurement for a single injected belief."""

    belief_id: str
    content: str
    belief_type: str
    source_type: str
    locked: bool
    jaccard: float
    zone: str


@dataclass
class PromptAnalysis:
    """Analysis of a single prompt's injection."""

    prompt_text: str
    beliefs: list[BeliefRelevance] = field(
        default_factory=lambda: list[BeliefRelevance]()
    )
    injection_chars: int = 0
    avg_jaccard: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def compute_project_hash(cwd: str) -> str:
    """SHA256 hash of resolved CWD path, first 12 chars."""
    resolved = str(Path(cwd).resolve())
    return hashlib.sha256(resolved.encode()).hexdigest()[:12]


def get_db_path(cwd: str) -> Path:
    """Get the memory.db path for a given CWD."""
    h = compute_project_hash(cwd)
    return AGENTMEMORY_DIR / h / "memory.db"


def tokenize(text: str) -> set[str]:
    """Extract lowercase alphanumeric tokens >= 3 chars."""
    return {w.lower() for w in re.findall(r"[a-zA-Z0-9_]+", text) if len(w) >= 3}


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union > 0 else 0.0


def classify_zone(b: ScoredBelief) -> str:
    """Determine which ba-protocol zone a belief lands in."""
    is_recent_correction = (
        b.belief_type in ("correction", "observation")
        and b.age_days is not None
        and b.age_days < 3.0
    )
    is_supersession = b.via == "supersession"
    is_recent_observation = b.via == "recent_observation"
    is_speculative = b.belief_type == "speculative"

    if is_recent_correction or is_supersession or is_recent_observation:
        return "OPERATIONAL STATE"
    elif b.locked:
        return "STANDING CONSTRAINTS"
    elif is_speculative:
        return "ACTIVE HYPOTHESES"
    else:
        return "BACKGROUND"


def truncate(text: str, max_len: int = 80) -> str:
    """Truncate text for display."""
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


# ---------------------------------------------------------------------------
# Load conversation turns
# ---------------------------------------------------------------------------


def load_turns() -> list[dict[str, str]]:
    """Load all turns from JSONL files, sorted by timestamp."""
    turns: list[dict[str, str]] = []

    # Main file
    main_file = CONV_LOG_DIR / "turns.jsonl"
    if main_file.exists():
        turns.extend(_read_jsonl(main_file))

    # Archive files
    archive_dir = CONV_LOG_DIR / "archive"
    if archive_dir.exists():
        for f in sorted(archive_dir.glob("*.jsonl")):
            turns.extend(_read_jsonl(f))

    # Sort by timestamp
    turns.sort(key=lambda t: t.get("timestamp", ""))
    return turns


def _read_jsonl(path: Path) -> list[dict[str, str]]:
    """Read a JSONL file, skipping malformed lines."""
    results: list[dict[str, str]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return results


# ---------------------------------------------------------------------------
# Pair prompts with responses
# ---------------------------------------------------------------------------


def pair_prompts_and_responses(
    turns: list[dict[str, str]],
) -> list[tuple[dict[str, str], dict[str, str] | None]]:
    """Match each user turn with its subsequent assistant turn.

    Returns list of (user_turn, assistant_turn_or_None).
    """
    pairs: list[tuple[dict[str, str], dict[str, str] | None]] = []
    i = 0
    while i < len(turns):
        turn = turns[i]
        if turn.get("event") == "user":
            # Look for the next assistant turn in the same session
            assistant_turn: dict[str, str] | None = None
            session = turn.get("session_id", "")
            for j in range(i + 1, min(i + 20, len(turns))):
                candidate = turns[j]
                if (
                    candidate.get("event") == "assistant"
                    and candidate.get("session_id") == session
                ):
                    assistant_turn = candidate
                    break
                if (
                    candidate.get("event") == "user"
                    and candidate.get("session_id") == session
                ):
                    # Another user turn before assistant response
                    break
            pairs.append((turn, assistant_turn))
        i += 1
    return pairs


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------


def analyze(db_path: Path) -> None:
    """Run the full injection relevance analysis."""
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    # Copy DB to a temp file so search_for_prompt can write
    # (it updates pending_feedback, last_retrieved_at) without
    # mutating the live database.
    tmp_dir = tempfile.mkdtemp(prefix="agentmemory_analysis_")
    tmp_db = Path(tmp_dir) / "memory.db"
    shutil.copy2(db_path, tmp_db)
    # Also copy WAL/SHM if present
    for suffix in ("-wal", "-shm"):
        wal = db_path.parent / (db_path.name + suffix)
        if wal.exists():
            shutil.copy2(wal, tmp_db.parent / (tmp_db.name + suffix))

    db = sqlite3.connect(str(tmp_db))
    db.row_factory = sqlite3.Row

    turns = load_turns()
    pairs = pair_prompts_and_responses(turns)

    print(f"Loaded {len(turns)} turns, {len(pairs)} user prompts")

    all_analyses: list[PromptAnalysis] = []
    zone_counter: Counter[str] = Counter()
    source_counter: Counter[str] = Counter()
    belief_frequency: Counter[str] = Counter()
    total_locked = 0
    total_beliefs = 0
    relevance_buckets = {"relevant": 0, "partial": 0, "irrelevant": 0}

    for user_turn, assistant_turn in pairs:
        prompt_text = user_turn.get("text", "")
        if len(prompt_text) < MIN_PROMPT_LEN:
            continue

        # Run search simulation (read-only DB, so pending_feedback writes will fail silently)
        try:
            result: SearchResult = search_for_prompt(db, prompt_text)
        except Exception:
            continue

        if not result.beliefs:
            # No injection for this prompt
            all_analyses.append(PromptAnalysis(prompt_text=prompt_text))
            continue

        # Build context tokens: prompt + assistant response
        response_text = (assistant_turn or {}).get("text", "")
        context_tokens = tokenize(prompt_text) | tokenize(response_text)

        # Compute formatted injection for size measurement
        injection_text = format_ba_injection(result)
        injection_chars = len(injection_text)

        analysis = PromptAnalysis(
            prompt_text=prompt_text,
            injection_chars=injection_chars,
        )

        for b in result.beliefs:
            belief_tokens = tokenize(b.content)
            jac = jaccard_similarity(belief_tokens, context_tokens)
            zone = classify_zone(b)

            br = BeliefRelevance(
                belief_id=b.id,
                content=b.content,
                belief_type=b.belief_type,
                source_type=b.source_type,
                locked=b.locked,
                jaccard=jac,
                zone=zone,
            )
            analysis.beliefs.append(br)

            # Accumulate stats
            zone_counter[zone] += 1
            source_counter[b.source_type] += 1
            belief_frequency[truncate(b.content, 100)] += 1
            total_beliefs += 1
            if b.locked:
                total_locked += 1

            if jac >= RELEVANT_THRESHOLD:
                relevance_buckets["relevant"] += 1
            elif jac >= PARTIAL_THRESHOLD:
                relevance_buckets["partial"] += 1
            else:
                relevance_buckets["irrelevant"] += 1

        if analysis.beliefs:
            analysis.avg_jaccard = sum(br.jaccard for br in analysis.beliefs) / len(
                analysis.beliefs
            )

        all_analyses.append(analysis)

    db.close()

    # Clean up temp copy
    shutil.rmtree(tmp_dir, ignore_errors=True)

    # ---------------------------------------------------------------------------
    # Report
    # ---------------------------------------------------------------------------

    prompts_with_injection = [a for a in all_analyses if a.beliefs]
    prompts_without = [a for a in all_analyses if not a.beliefs]

    print("\n" + "=" * 70)
    print("INJECTION RELEVANCE ANALYSIS REPORT")
    print("=" * 70)

    print(f"\nTotal prompts analyzed:          {len(all_analyses)}")
    print(f"Prompts with injection:          {len(prompts_with_injection)}")
    print(f"Prompts without injection:       {len(prompts_without)}")

    if prompts_with_injection:
        avg_beliefs = total_beliefs / len(prompts_with_injection)
        avg_chars = sum(a.injection_chars for a in prompts_with_injection) / len(
            prompts_with_injection
        )
        print(f"\nAvg beliefs injected per prompt:  {avg_beliefs:.1f}")
        print(f"Avg injection size (chars):      {avg_chars:.0f}")
    else:
        print("\nNo injections found.")
        return

    # Relevance distribution
    print("\n--- Relevance Distribution ---")
    if total_beliefs > 0:
        for label in ("relevant", "partial", "irrelevant"):
            count = relevance_buckets[label]
            pct = count / total_beliefs * 100
            print(f"  {label:>12s}: {count:5d} ({pct:5.1f}%)")

    # Zone distribution
    print("\n--- Zone Distribution ---")
    for zone, count in zone_counter.most_common():
        pct = count / total_beliefs * 100
        print(f"  {zone:>22s}: {count:5d} ({pct:5.1f}%)")

    # Source type breakdown
    print("\n--- Source Type Breakdown ---")
    for src, count in source_counter.most_common():
        pct = count / total_beliefs * 100
        print(f"  {src:>18s}: {count:5d} ({pct:5.1f}%)")

    # Locked belief injection rate
    locked_pct = total_locked / total_beliefs * 100 if total_beliefs > 0 else 0.0
    print("\n--- Locked Belief Injection Rate ---")
    print(f"  Locked: {total_locked}/{total_beliefs} ({locked_pct:.1f}%)")

    # Top 5 most frequently injected beliefs
    print("\n--- Top 5 Most Frequently Injected Beliefs ---")
    for content, count in belief_frequency.most_common(5):
        print(f"  [{count:3d}x] {truncate(content, 70)}")

    # Top 5 least relevant prompts (with injections)
    sorted_by_relevance = sorted(prompts_with_injection, key=lambda a: a.avg_jaccard)
    print("\n--- Top 5 LEAST Relevant Injections ---")
    for a in sorted_by_relevance[:5]:
        print(
            f"  jaccard={a.avg_jaccard:.4f} | beliefs={len(a.beliefs):2d} | {truncate(a.prompt_text, 60)}"
        )

    # Top 5 most relevant prompts
    print("\n--- Top 5 MOST Relevant Injections ---")
    for a in sorted_by_relevance[-5:][::-1]:
        print(
            f"  jaccard={a.avg_jaccard:.4f} | beliefs={len(a.beliefs):2d} | {truncate(a.prompt_text, 60)}"
        )

    print("\n" + "=" * 70)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    project_cwd = str(Path(__file__).resolve().parent.parent)
    db_path = get_db_path(project_cwd)
    print(f"Project CWD: {project_cwd}")
    print(f"DB path:     {db_path}")
    analyze(db_path)
