from __future__ import annotations

"""
Experiment 57: Dumb Extraction + Bayesian Scoring Framework

Tests the "extract everything, score smart" approach:
  1. Extract ALL sentences (period/newline split, no keyword filtering)
  2. Assign source priors (user=Beta(9,1), assistant=Beta(1,1))
  3. Simulate Thompson sampling retrieval over multiple sessions
  4. Compare: does the Bayesian system surface useful beliefs and bury junk
     WITHOUT any keyword classification at extraction time?

This replaces the Exp 56 approach (keyword filtering at extraction) with
a system where extraction is dumb and scoring is smart.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

LOG_FILE = Path.home() / ".claude" / "conversation-logs" / "turns.jsonl"


# ============================================================
# Dumb extraction: just split into sentences
# ============================================================

def extract_sentences(text: str) -> list[str]:
    """Split text into sentences. No filtering, no classification.

    Rules:
    - Split on period+space, exclamation, question mark, newline
    - Remove markdown formatting (bold, headers, code blocks)
    - Skip lines under 10 chars (not enough content to be a belief)
    - That's it. No keyword matching. No type classification.
    """
    # Strip code blocks (they're code, not beliefs)
    text = re.sub(r'```[\s\S]*?```', '', text)
    # Strip inline code but keep surrounding text
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Strip markdown formatting
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    # Strip URLs
    text = re.sub(r'https?://\S+', '', text)
    # Strip markdown table rows
    text = re.sub(r'^\|.*\|$', '', text, flags=re.MULTILINE)
    # Strip list markers
    text = re.sub(r'^[\s]*[-*]\s+', '', text, flags=re.MULTILINE)

    sentences: list[str] = []

    # Split on newlines first (conversation text is line-delimited)
    for line in text.split('\n'):
        line = line.strip()
        if len(line) < 10:
            continue
        # Then split on sentence boundaries within each line
        parts: list[str] = re.split(r'(?<=[.!?])\s+', line)
        for part in parts:
            part = part.strip()
            if len(part) >= 10:
                sentences.append(part)

    return sentences


# ============================================================
# Source-informed Bayesian priors (from Exp 38)
# ============================================================

# These priors encode how much we trust beliefs from different sources
# BEFORE any feedback. The feedback loop adjusts from here.
SOURCE_PRIORS: dict[str, tuple[float, float]] = {
    "user": (9.0, 1.0),       # User said it -> high initial confidence
    "assistant": (1.0, 1.0),  # Assistant said it -> uncertain, needs validation
}


class Belief:
    """A candidate belief with Bayesian confidence tracking."""

    __slots__ = ('text', 'source', 'session', 'alpha', 'beta_param',
                 'retrieval_count', 'used_count', 'ignored_count')

    def __init__(self, text: str, source: str, session: str) -> None:
        self.text: str = text
        self.source: str = source
        self.session: str = session
        prior: tuple[float, float] = SOURCE_PRIORS.get(source, (1.0, 1.0))
        self.alpha: float = prior[0]
        self.beta_param: float = prior[1]
        self.retrieval_count: int = 0
        self.used_count: int = 0
        self.ignored_count: int = 0

    @property
    def confidence(self) -> float:
        """Expected value of Beta distribution = alpha / (alpha + beta)."""
        return self.alpha / (self.alpha + self.beta_param)

    @property
    def uncertainty(self) -> float:
        """Entropy of Beta distribution (higher = less certain)."""
        from scipy.special import betaln, digamma  # type: ignore[import-untyped]
        a: float = self.alpha
        b: float = self.beta_param
        val: float = float(betaln(a, b)  # pyright: ignore[reportUnknownArgumentType]
                          - (a - 1) * digamma(a)
                          - (b - 1) * digamma(b)
                          + (a + b - 2) * digamma(a + b))
        return val

    def thompson_sample(self) -> float:
        """Draw from Beta posterior for Thompson sampling."""
        return float(np.random.beta(self.alpha, self.beta_param))

    def update_used(self) -> None:
        """Belief was retrieved and the user acted on it."""
        self.alpha += 1.0
        self.retrieval_count += 1
        self.used_count += 1

    def update_ignored(self) -> None:
        """Belief was retrieved but the user ignored it."""
        self.beta_param += 1.0
        self.retrieval_count += 1
        self.ignored_count += 1


# ============================================================
# Simulated retrieval sessions
# ============================================================

def simulate_retrieval(
    beliefs: list[Belief],
    n_sessions: int = 20,
    retrievals_per_session: int = 10,
    use_probability_fn: Any = None,
) -> dict[str, Any]:
    """Simulate Thompson sampling retrieval over multiple sessions.

    For each session:
    1. Sample from each belief's Beta distribution
    2. Retrieve top-k by Thompson sample
    3. Simulate whether each retrieved belief is "used" or "ignored"
       based on a use_probability function

    The use_probability function takes a belief and returns P(used).
    Default: user beliefs are used 70% of the time, assistant beliefs 20%.
    """
    _use_prob_fn: Any = use_probability_fn
    if _use_prob_fn is None:
        def _default_use_prob(b: Belief) -> float:
            if b.source == "user":
                # User statements are usually relevant
                return 0.70
            else:
                # Most assistant text is filler
                return 0.20
        _use_prob_fn = _default_use_prob

    history: list[dict[str, Any]] = []

    for session in range(n_sessions):
        # Thompson sampling: draw from each belief's posterior
        samples: list[tuple[float, int]] = [
            (b.thompson_sample(), i) for i, b in enumerate(beliefs)
        ]
        # Sort by sample (highest first)
        samples.sort(key=lambda x: -x[0])

        # Retrieve top-k
        retrieved_indices: list[int] = [
            idx for _, idx in samples[:retrievals_per_session]
        ]

        session_used: int = 0
        session_ignored: int = 0

        for idx in retrieved_indices:
            b: Belief = beliefs[idx]
            p_use: float = _use_prob_fn(b)
            if np.random.random() < p_use:
                b.update_used()
                session_used += 1
            else:
                b.update_ignored()
                session_ignored += 1

        # Snapshot confidence distribution
        user_beliefs: list[Belief] = [b for b in beliefs if b.source == "user"]
        asst_beliefs: list[Belief] = [b for b in beliefs if b.source == "assistant"]

        history.append({
            "session": session,
            "retrieved": retrievals_per_session,
            "used": session_used,
            "ignored": session_ignored,
            "user_mean_conf": float(np.mean([b.confidence for b in user_beliefs]))
            if user_beliefs else 0.0,
            "asst_mean_conf": float(np.mean([b.confidence for b in asst_beliefs]))
            if asst_beliefs else 0.0,
            "user_retrieved": sum(
                1 for idx in retrieved_indices if beliefs[idx].source == "user"
            ),
            "asst_retrieved": sum(
                1 for idx in retrieved_indices if beliefs[idx].source == "assistant"
            ),
        })

    return {
        "n_sessions": n_sessions,
        "retrievals_per_session": retrievals_per_session,
        "history": history,
    }


# ============================================================
# Main
# ============================================================

def main() -> None:
    if not LOG_FILE.exists():
        print("No conversation log found.", file=sys.stderr)
        sys.exit(1)

    # Load turns
    turns: list[dict[str, Any]] = []
    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                turns.append(json.loads(line))

    print(f"Loaded {len(turns)} conversation turns", file=sys.stderr)

    # Dumb extraction: every sentence is a candidate
    beliefs: list[Belief] = []
    source_counts: Counter[str] = Counter()
    total_sentences: int = 0

    for turn in turns:
        text: str = turn.get('text', '')
        if not text:
            continue

        source: str = turn['event']  # "user" or "assistant"
        session: str = turn['session_id'][:12]

        sentences: list[str] = extract_sentences(text)
        total_sentences += len(sentences)

        for sent in sentences:
            beliefs.append(Belief(text=sent, source=source, session=session))
            source_counts[source] += 1

    print(f"\n{'='*70}", file=sys.stderr)
    print("EXPERIMENT 57: DUMB EXTRACTION + BAYESIAN SCORING", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)

    print(f"\nTotal sentences extracted: {total_sentences}", file=sys.stderr)
    print(f"  From user: {source_counts['user']}", file=sys.stderr)
    print(f"  From assistant: {source_counts['assistant']}", file=sys.stderr)

    # Show initial confidence distribution
    user_beliefs: list[Belief] = [b for b in beliefs if b.source == "user"]
    asst_beliefs: list[Belief] = [b for b in beliefs if b.source == "assistant"]

    print(f"\n--- Initial State (before any retrieval) ---", file=sys.stderr)
    print(f"  User beliefs: {len(user_beliefs)}, "
          f"mean confidence: {np.mean([b.confidence for b in user_beliefs]):.2f}"
          if user_beliefs else "  User beliefs: 0", file=sys.stderr)
    print(f"  Assistant beliefs: {len(asst_beliefs)}, "
          f"mean confidence: {np.mean([b.confidence for b in asst_beliefs]):.2f}"
          if asst_beliefs else "  Assistant beliefs: 0", file=sys.stderr)

    # Simulate 20 retrieval sessions
    print(f"\n--- Simulating 20 retrieval sessions ---", file=sys.stderr)
    sim: dict[str, Any] = simulate_retrieval(beliefs, n_sessions=20, retrievals_per_session=10)

    # Show convergence
    print(f"\n  {'Session':>7s} {'Used':>5s} {'Ign':>5s} "
          f"{'User Conf':>9s} {'Asst Conf':>9s} "
          f"{'User Ret':>8s} {'Asst Ret':>8s}", file=sys.stderr)
    print(f"  {'-'*7} {'-'*5} {'-'*5} {'-'*9} {'-'*9} {'-'*8} {'-'*8}",
          file=sys.stderr)
    for h in sim["history"]:
        print(f"  {h['session']:>7d} {h['used']:>5d} {h['ignored']:>5d} "
              f"{h['user_mean_conf']:>9.3f} {h['asst_mean_conf']:>9.3f} "
              f"{h['user_retrieved']:>8d} {h['asst_retrieved']:>8d}",
              file=sys.stderr)

    # Final state
    print(f"\n--- After 20 Sessions ---", file=sys.stderr)

    # Top 10 beliefs by confidence
    sorted_beliefs: list[Belief] = sorted(beliefs, key=lambda b: -b.confidence)
    print(f"\n  Top 10 beliefs (highest confidence):", file=sys.stderr)
    for i, b in enumerate(sorted_beliefs[:10]):
        print(f"    {i+1:>2d}. [{b.source:>9s}] conf={b.confidence:.3f} "
              f"ret={b.retrieval_count} used={b.used_count} "
              f"| {b.text[:90]}", file=sys.stderr)

    # Bottom 10
    print(f"\n  Bottom 10 beliefs (lowest confidence):", file=sys.stderr)
    for i, b in enumerate(sorted_beliefs[-10:]):
        print(f"    {len(sorted_beliefs)-9+i:>2d}. [{b.source:>9s}] "
              f"conf={b.confidence:.3f} "
              f"ret={b.retrieval_count} used={b.used_count} "
              f"| {b.text[:90]}", file=sys.stderr)

    # Key question: does the system separate signal from noise?
    # Count how many user beliefs are in top-20 vs bottom-20
    top20: list[Belief] = sorted_beliefs[:20]
    bottom20: list[Belief] = sorted_beliefs[-20:]
    top20_user: int = sum(1 for b in top20 if b.source == "user")
    bottom20_user: int = sum(1 for b in bottom20 if b.source == "user")

    print(f"\n--- Signal/Noise Separation ---", file=sys.stderr)
    print(f"  User beliefs in top 20: {top20_user}/{len(user_beliefs)} "
          f"({top20_user/len(user_beliefs)*100:.0f}%)" if user_beliefs
          else "  No user beliefs", file=sys.stderr)
    print(f"  User beliefs in bottom 20: {bottom20_user}", file=sys.stderr)
    print(f"  Assistant beliefs in top 20: {20 - top20_user}", file=sys.stderr)
    print(f"  Assistant beliefs in bottom 20: {20 - bottom20_user}",
          file=sys.stderr)

    # Verdict
    print(f"\n--- Verdict ---", file=sys.stderr)
    last: dict[str, Any] = sim["history"][-1]
    if last["user_mean_conf"] > last["asst_mean_conf"] + 0.1:
        print(f"  Source priors + Thompson sampling successfully separates "
              f"user signal from assistant noise.", file=sys.stderr)
        print(f"  User confidence: {last['user_mean_conf']:.3f}, "
              f"Assistant: {last['asst_mean_conf']:.3f}", file=sys.stderr)
    else:
        print(f"  Separation insufficient. Gap: "
              f"{last['user_mean_conf'] - last['asst_mean_conf']:.3f}",
              file=sys.stderr)

    # Save
    output: dict[str, Any] = {
        "experiment": "exp57_dumb_extraction",
        "date": "2026-04-10",
        "input": {
            "turns": len(turns),
            "total_sentences": total_sentences,
            "user_sentences": source_counts["user"],
            "assistant_sentences": source_counts["assistant"],
        },
        "simulation": sim,
        "final_state": {
            "top10": [
                {"text": b.text[:200], "source": b.source,
                 "confidence": round(b.confidence, 3),
                 "retrievals": b.retrieval_count, "used": b.used_count}
                for b in sorted_beliefs[:10]
            ],
            "bottom10": [
                {"text": b.text[:200], "source": b.source,
                 "confidence": round(b.confidence, 3),
                 "retrievals": b.retrieval_count, "used": b.used_count}
                for b in sorted_beliefs[-10:]
            ],
        },
    }

    out_path: Path = Path("experiments/exp57_results.json")
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults saved to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
