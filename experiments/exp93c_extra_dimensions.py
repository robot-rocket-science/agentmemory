"""Exp 93c: Multi-model scoring with additional non-feedback dimensions.

Hypotheses:
  H2a: Adding content_length and retrieval_frequency dims will reduce
       SIGNAL classification from 63% to <45%.
  H2b: Full-population Gini will cross the 0.15 threshold.

New dimensions (no feedback required):
  D6: content_length_norm -- normalized by population (longer = more substance)
  D7: retrieval_frequency -- times retrieved / max_retrieved (high = system thinks it's relevant)
  D8: entity_density -- number of entity-like tokens / content length

These dimensions are observable for ALL beliefs, not just those with feedback.

Usage:
    uv run python experiments/exp93c_extra_dimensions.py
"""

from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class GenerativeModel:
    name: str
    label: str
    expected_feedback_ratio: tuple[float, float]
    expected_harmful_ratio: tuple[float, float]
    expected_age_decay: tuple[float, float]
    expected_source_quality: tuple[float, float]
    # New dimensions
    expected_content_length: tuple[float, float]
    expected_retrieval_freq: tuple[float, float]
    expected_entity_density: tuple[float, float]
    prior: float = 0.25


MODELS: list[GenerativeModel] = [
    GenerativeModel("M1", "SIGNAL",
                    expected_feedback_ratio=(0.8, 10.0),
                    expected_harmful_ratio=(0.05, 20.0),
                    expected_age_decay=(0.5, 5.0),
                    expected_source_quality=(0.6, 5.0),
                    # SIGNAL beliefs tend to be longer, retrieved more, entity-rich
                    expected_content_length=(0.6, 5.0),
                    expected_retrieval_freq=(0.5, 5.0),
                    expected_entity_density=(0.5, 5.0),
                    prior=0.30),
    GenerativeModel("M2", "NOISE",
                    expected_feedback_ratio=(0.15, 10.0),
                    expected_harmful_ratio=(0.1, 10.0),
                    expected_age_decay=(0.5, 3.0),
                    expected_source_quality=(0.3, 8.0),
                    # NOISE beliefs tend to be short, rarely retrieved, sparse
                    expected_content_length=(0.2, 8.0),
                    expected_retrieval_freq=(0.1, 8.0),
                    expected_entity_density=(0.2, 5.0),
                    prior=0.40),
    GenerativeModel("M3", "STALE",
                    expected_feedback_ratio=(0.4, 5.0),
                    expected_harmful_ratio=(0.15, 8.0),
                    expected_age_decay=(0.85, 10.0),
                    expected_source_quality=(0.5, 3.0),
                    # STALE: moderate length, WAS retrieved but not recently
                    expected_content_length=(0.5, 3.0),
                    expected_retrieval_freq=(0.3, 5.0),
                    expected_entity_density=(0.4, 3.0),
                    prior=0.15),
    GenerativeModel("M4", "CONTESTED",
                    expected_feedback_ratio=(0.5, 3.0),
                    expected_harmful_ratio=(0.35, 8.0),
                    expected_age_decay=(0.3, 3.0),
                    expected_source_quality=(0.5, 3.0),
                    # CONTESTED: long (complex topics generate debate), retrieved often
                    expected_content_length=(0.6, 4.0),
                    expected_retrieval_freq=(0.6, 5.0),
                    expected_entity_density=(0.5, 3.0),
                    prior=0.15),
]

MODEL_CONFIDENCE: dict[str, float] = {
    "M1": 0.85, "M2": 0.25, "M3": 0.35, "M4": 0.55,
}

SOURCE_QUALITY_MAP: dict[str, float] = {
    "user_corrected": 1.0, "user_stated": 0.8,
    "document_recent": 0.5, "document_old": 0.3, "agent_inferred": 0.3,
}

# Simple entity pattern: capitalized words, numbers, paths, identifiers
ENTITY_PATTERN: re.Pattern[str] = re.compile(
    r'[A-Z][a-z]+(?:[A-Z][a-z]+)+|'  # CamelCase
    r'[a-z_]+\.[a-z_]+|'              # module.attr
    r'[A-Z]{2,}|'                      # ACRONYMS
    r'\b\d+\.\d+\b|'                   # version numbers
    r'/[a-z_/]+\.[a-z]+',             # file paths
)


@dataclass
class BeliefEvidence:
    belief_id: str
    belief_type: str
    source_type: str
    locked: bool
    confidence_current: float
    feedback_ratio: float
    harmful_ratio: float
    age_normalized: float
    source_quality: float
    content_length_norm: float
    retrieval_freq_norm: float
    entity_density: float


def parse_ts(ts: str) -> datetime:
    dt: datetime = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def beta_log_likelihood(x: float, mu: float, kappa: float) -> float:
    a: float = max(0.01, mu * kappa)
    b: float = max(0.01, (1.0 - mu) * kappa)
    x_safe: float = max(0.001, min(0.999, x))
    log_p: float = (a - 1.0) * math.log(x_safe) + (b - 1.0) * math.log(1.0 - x_safe)
    log_beta: float = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    return log_p - log_beta


@dataclass
class ModelPosterior:
    belief_id: str
    posteriors: dict[str, float] = field(default_factory=dict)
    map_model: str = ""
    map_probability: float = 0.0
    entropy: float = 0.0


def compute_posterior(ev: BeliefEvidence) -> ModelPosterior:
    log_posteriors: dict[str, float] = {}
    for m in MODELS:
        ll: float = 0.0
        ll += beta_log_likelihood(ev.feedback_ratio, *m.expected_feedback_ratio)
        ll += beta_log_likelihood(ev.harmful_ratio, *m.expected_harmful_ratio)
        ll += beta_log_likelihood(ev.age_normalized, *m.expected_age_decay)
        ll += beta_log_likelihood(ev.source_quality, *m.expected_source_quality)
        # New dimensions
        ll += beta_log_likelihood(ev.content_length_norm, *m.expected_content_length)
        ll += beta_log_likelihood(ev.retrieval_freq_norm, *m.expected_retrieval_freq)
        ll += beta_log_likelihood(ev.entity_density, *m.expected_entity_density)
        log_posteriors[m.name] = ll + math.log(max(1e-10, m.prior))

    max_lp: float = max(log_posteriors.values())
    log_norm: float = max_lp + math.log(
        sum(math.exp(lp - max_lp) for lp in log_posteriors.values())
    )
    posteriors: dict[str, float] = {
        name: math.exp(lp - log_norm) for name, lp in log_posteriors.items()
    }
    map_name: str = max(posteriors, key=lambda k: posteriors[k])
    h: float = -sum(p * math.log2(p) for p in posteriors.values() if p > 1e-10)

    return ModelPosterior(
        belief_id=ev.belief_id, posteriors=posteriors,
        map_model=map_name, map_probability=posteriors[map_name], entropy=h,
    )


def gini(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_v: list[float] = sorted(values)
    n: int = len(sorted_v)
    total: float = sum(sorted_v)
    if total == 0:
        return 0.0
    numer: float = sum((2 * (i + 1) - n - 1) * sorted_v[i] for i in range(n))
    return numer / (n * total)


def main() -> None:
    db_path: str = str(
        Path.home() / ".agentmemory" / "projects" / "2e7ed55e017a" / "memory.db"
    )
    conn: sqlite3.Connection = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Load beliefs with content for entity analysis
    rows: list[sqlite3.Row] = conn.execute(
        """SELECT b.id, b.alpha, b.beta_param, b.confidence, b.content,
                  b.belief_type, b.source_type, b.locked, b.created_at,
                  b.last_retrieved_at,
                  COALESCE(t.used_count, 0) as used_count,
                  COALESCE(t.ignored_count, 0) as ignored_count,
                  COALESCE(t.harmful_count, 0) as harmful_count,
                  COALESCE(t.total_tests, 0) as total_tests
           FROM beliefs b
           LEFT JOIN (
               SELECT belief_id,
                      SUM(CASE WHEN outcome='used' OR outcome='confirmed' THEN 1 ELSE 0 END) as used_count,
                      SUM(CASE WHEN outcome='ignored' THEN 1 ELSE 0 END) as ignored_count,
                      SUM(CASE WHEN outcome='harmful' THEN 1 ELSE 0 END) as harmful_count,
                      COUNT(*) as total_tests
               FROM tests GROUP BY belief_id
           ) t ON b.id = t.belief_id
           WHERE b.superseded_by IS NULL"""
    ).fetchall()

    # Compute normalization bounds
    age_bounds: sqlite3.Row = conn.execute(
        "SELECT MIN(created_at) as oldest, MAX(created_at) as newest FROM beliefs WHERE superseded_by IS NULL"
    ).fetchone()
    oldest_dt: datetime = parse_ts(str(age_bounds["oldest"]))
    newest_dt: datetime = parse_ts(str(age_bounds["newest"]))
    max_age_hours: float = max(1.0, (newest_dt - oldest_dt).total_seconds() / 3600.0)

    # Content length stats for normalization
    lengths: list[int] = [len(str(r["content"])) for r in rows]
    max_length: int = max(lengths) if lengths else 1

    # Retrieval count from tests table
    retrieval_counts: dict[str, int] = {}
    ret_rows: list[sqlite3.Row] = conn.execute(
        "SELECT belief_id, COUNT(*) as cnt FROM tests GROUP BY belief_id"
    ).fetchall()
    for rr in ret_rows:
        retrieval_counts[str(rr["belief_id"])] = int(rr["cnt"])
    max_retrievals: int = max(retrieval_counts.values()) if retrieval_counts else 1

    conn.close()

    # Build evidence vectors
    evidence: list[BeliefEvidence] = []
    for r in rows:
        total: int = int(r["total_tests"])
        used: int = int(r["used_count"])
        harmful: int = int(r["harmful_count"])
        content: str = str(r["content"])
        created_dt: datetime = parse_ts(str(r["created_at"]))

        # Entity density
        entities: list[str] = ENTITY_PATTERN.findall(content)
        words: int = max(1, len(content.split()))
        entity_dens: float = min(1.0, len(entities) / words)

        # Content length normalized
        content_len_norm: float = min(1.0, len(content) / max_length)

        # Retrieval frequency normalized
        ret_count: int = retrieval_counts.get(str(r["id"]), 0)
        ret_freq_norm: float = ret_count / max_retrievals if max_retrievals > 0 else 0.0

        age_norm: float = (newest_dt - created_dt).total_seconds() / 3600.0 / max_age_hours

        evidence.append(BeliefEvidence(
            belief_id=str(r["id"]),
            belief_type=str(r["belief_type"]),
            source_type=str(r["source_type"]),
            locked=bool(r["locked"]),
            confidence_current=float(r["confidence"]),
            feedback_ratio=used / total if total > 0 else 0.5,
            harmful_ratio=harmful / total if total > 0 else 0.0,
            age_normalized=age_norm,
            source_quality=SOURCE_QUALITY_MAP.get(str(r["source_type"]), 0.5),
            content_length_norm=content_len_norm,
            retrieval_freq_norm=ret_freq_norm,
            entity_density=entity_dens,
        ))

    print("=" * 70)
    print("Exp 93c: Multi-Model + Extra Dimensions (No Feedback Required)")
    print("=" * 70)
    print(f"Population: {len(evidence)} active beliefs")
    print()

    # Dimension statistics
    print("## NEW DIMENSION STATISTICS")
    cl_vals: list[float] = [e.content_length_norm for e in evidence]
    rf_vals: list[float] = [e.retrieval_freq_norm for e in evidence]
    ed_vals: list[float] = [e.entity_density for e in evidence]
    for name, vals in [("content_length", cl_vals), ("retrieval_freq", rf_vals), ("entity_density", ed_vals)]:
        avg: float = sum(vals) / len(vals)
        std: float = math.sqrt(sum((v - avg) ** 2 for v in vals) / len(vals))
        mn: float = min(vals)
        mx: float = max(vals)
        print(f"  {name:>18s}: mean={avg:.3f}  std={std:.3f}  min={mn:.3f}  max={mx:.3f}")
    print()

    # Run classification
    posteriors: list[ModelPosterior] = [compute_posterior(e) for e in evidence]
    scores: list[float] = [
        sum(p * MODEL_CONFIDENCE.get(m, 0.5) for m, p in post.posteriors.items())
        for post in posteriors
    ]

    current_confs: list[float] = [e.confidence_current for e in evidence]
    current_gini: float = gini(current_confs)
    new_gini: float = gini(scores)

    print("## POPULATION COMPARISON")
    print(f"  Current Gini:                {current_gini:.4f}")
    print(f"  Multi-model + extra dims:    {new_gini:.4f} ({new_gini - current_gini:+.4f})")
    print()

    # H2a test
    map_counts: Counter[str] = Counter(p.map_model for p in posteriors)
    signal_pct: float = map_counts.get("M1", 0) / len(posteriors) * 100
    h2a_pass: bool = signal_pct < 45.0
    print(f"  H2a (SIGNAL < 45%): {'PASS' if h2a_pass else 'FAIL'} (got {signal_pct:.1f}%)")

    # H2b test
    h2b_pass: bool = new_gini > 0.15
    print(f"  H2b (Gini > 0.15):  {'PASS' if h2b_pass else 'FAIL'} (got {new_gini:.4f})")
    print()

    # MAP distribution
    labels: dict[str, str] = {m.name: m.label for m in MODELS}
    print("  MAP distribution:")
    for name in ["M1", "M2", "M3", "M4"]:
        c: int = map_counts.get(name, 0)
        print(f"    {name} ({labels[name]:>10s}): {c:>6d} ({c/len(posteriors)*100:>5.1f}%)")
    print()

    # Score distribution
    print("  Score distribution:")
    buckets: Counter[str] = Counter()
    for s in scores:
        if s >= 0.7:
            buckets["0.7-1.0"] += 1
        elif s >= 0.5:
            buckets["0.5-0.7"] += 1
        elif s >= 0.3:
            buckets["0.3-0.5"] += 1
        else:
            buckets["0.0-0.3"] += 1
    for b in ["0.0-0.3", "0.3-0.5", "0.5-0.7", "0.7-1.0"]:
        c = buckets.get(b, 0)
        print(f"    {b}: {c:>6d} ({c/len(scores)*100:>5.1f}%)")
    print()

    # Classification confidence
    entropies: list[float] = [p.entropy for p in posteriors]
    avg_h: float = sum(entropies) / len(entropies)
    confident: int = sum(1 for e in entropies if e < 0.5)
    print(f"  Avg entropy: {avg_h:.3f} bits")
    print(f"  Confident (H < 0.5): {confident} ({confident/len(posteriors)*100:.1f}%)")
    print()

    # Dimension contribution analysis: which new dim is most discriminative?
    print("## DIMENSION ABLATION (remove one dim at a time)")
    # Baseline with all 7 dims
    baseline_signal: float = signal_pct

    # Test without each new dimension by setting it to 0.5 (uninformative)
    for dim_name, dim_attr in [
        ("content_length", "content_length_norm"),
        ("retrieval_freq", "retrieval_freq_norm"),
        ("entity_density", "entity_density"),
    ]:
        ablated: list[BeliefEvidence] = []
        for e in evidence:
            e_copy = BeliefEvidence(
                belief_id=e.belief_id, belief_type=e.belief_type,
                source_type=e.source_type, locked=e.locked,
                confidence_current=e.confidence_current,
                feedback_ratio=e.feedback_ratio, harmful_ratio=e.harmful_ratio,
                age_normalized=e.age_normalized, source_quality=e.source_quality,
                content_length_norm=e.content_length_norm,
                retrieval_freq_norm=e.retrieval_freq_norm,
                entity_density=e.entity_density,
            )
            # Zero out the target dimension
            if dim_attr == "content_length_norm":
                e_copy.content_length_norm = 0.5
            elif dim_attr == "retrieval_freq_norm":
                e_copy.retrieval_freq_norm = 0.5
            else:
                e_copy.entity_density = 0.5
            ablated.append(e_copy)

        abl_posts: list[ModelPosterior] = [compute_posterior(e) for e in ablated]
        abl_map: Counter[str] = Counter(p.map_model for p in abl_posts)
        abl_signal: float = abl_map.get("M1", 0) / len(abl_posts) * 100
        abl_scores: list[float] = [
            sum(p * MODEL_CONFIDENCE.get(m, 0.5) for m, p in post.posteriors.items())
            for post in abl_posts
        ]
        abl_gini: float = gini(abl_scores)
        delta_signal: float = abl_signal - baseline_signal

        print(f"  Without {dim_name:>18s}: SIGNAL={abl_signal:>5.1f}% "
              f"(delta={delta_signal:>+5.1f}pp)  Gini={abl_gini:.4f}")

    print()
    print("  (Positive delta = removing the dim INCREASES SIGNAL, meaning")
    print("   the dim was pushing beliefs AWAY from SIGNAL. Negative = dim")
    print("   was pushing beliefs TOWARD SIGNAL.)")


if __name__ == "__main__":
    main()
