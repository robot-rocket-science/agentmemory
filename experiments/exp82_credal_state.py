"""Experiment 82: Credal State Visualization.

Analyzes the Beta distribution parameters (alpha, beta_param) across all active
statements to characterize the agent's credal state C(t):

  - How much uncertainty exists?
  - How many statements have been tested (high alpha+beta) vs untested (Jeffreys prior)?
  - What does the confidence distribution look like?
  - Where are the highest-uncertainty statements (candidates for exploration)?

Outputs text histograms and summary statistics (no matplotlib dependency).

Success criteria:
  - Identify the fraction of statements at Jeffreys prior (never tested)
  - Identify high-uncertainty statements (alpha ~ beta, low total evidence)
  - Show the credal state is dominated by untested statements
"""
from __future__ import annotations

import math
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH: str = str(
    Path.home() / ".agentmemory" / "projects" / "2e7ed55e017a" / "memory.db"
)

# Jeffreys prior thresholds
JEFFREYS_ALPHA: float = 0.5
JEFFREYS_BETA: float = 0.5
EVIDENCE_EPSILON: float = 0.1  # tolerance for "at prior"


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class StatementCredal:
    belief_id: str
    content: str
    belief_type: str
    alpha: float
    beta_param: float
    confidence: float
    locked: bool
    total_evidence: float  # alpha + beta_param
    uncertainty: float  # variance of Beta distribution
    entropy: float  # differential entropy of Beta distribution


@dataclass
class CredalSummary:
    total: int
    at_prior: int  # never tested (still at type prior)
    tested: int  # received at least one feedback event
    locked_count: int
    confidence_histogram: dict[str, int]  # binned confidence values
    evidence_histogram: dict[str, int]  # binned total evidence
    uncertainty_histogram: dict[str, int]  # binned uncertainty
    by_type_avg_uncertainty: dict[str, float]
    highest_uncertainty: list[StatementCredal]
    lowest_uncertainty: list[StatementCredal]
    type_priors: dict[str, tuple[float, float]]  # belief_type -> (typical alpha, typical beta)


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------

def beta_variance(alpha: float, beta: float) -> float:
    """Variance of Beta(alpha, beta)."""
    total = alpha + beta
    if total < 0.01:
        return 0.25
    return (alpha * beta) / (total * total * (total + 1))


def beta_entropy(alpha: float, beta: float) -> float:
    """Differential entropy of Beta(alpha, beta)."""
    if alpha <= 0 or beta <= 0:
        return 0.0
    log_beta_fn = math.lgamma(alpha) + math.lgamma(beta) - math.lgamma(alpha + beta)
    psi_sum = _digamma(alpha + beta)
    return log_beta_fn - (alpha - 1) * _digamma(alpha) - (beta - 1) * _digamma(beta) + (alpha + beta - 2) * psi_sum


def _digamma(x: float) -> float:
    """Approximation of digamma function."""
    if x < 1e-6:
        return -1.0 / x - 0.5772156649
    result: float = 0.0
    while x < 6.0:
        result -= 1.0 / x
        x += 1.0
    result += math.log(x) - 0.5 / x
    x2 = 1.0 / (x * x)
    result -= x2 * (1.0 / 12.0 - x2 * (1.0 / 120.0 - x2 / 252.0))
    return result


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze_credal_state() -> CredalSummary:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, content, belief_type, alpha, beta_param, confidence, locked
        FROM beliefs
        WHERE valid_to IS NULL
    """)

    rows: list[sqlite3.Row] = cursor.fetchall()
    conn.close()

    statements: list[StatementCredal] = []
    for row in rows:
        a: float = row["alpha"]
        b: float = row["beta_param"]
        var = beta_variance(a, b)
        ent = beta_entropy(a, b)
        statements.append(StatementCredal(
            belief_id=row["id"],
            content=row["content"],
            belief_type=row["belief_type"],
            alpha=a,
            beta_param=b,
            confidence=row["confidence"],
            locked=bool(row["locked"]),
            total_evidence=a + b,
            uncertainty=var,
            entropy=ent,
        ))

    # Detect type priors (most common alpha/beta per type)
    type_alpha_beta: dict[str, list[tuple[float, float]]] = {}
    for s in statements:
        if s.belief_type not in type_alpha_beta:
            type_alpha_beta[s.belief_type] = []
        type_alpha_beta[s.belief_type].append((s.alpha, s.beta_param))

    type_priors: dict[str, tuple[float, float]] = {}
    for bt, pairs in type_alpha_beta.items():
        # Mode: most common pair
        pair_counter: Counter[tuple[float, float]] = Counter()
        for a, b in pairs:
            pair_counter[(round(a, 1), round(b, 1))] += 1
        most_common = pair_counter.most_common(1)[0][0]
        type_priors[bt] = most_common

    # Classify as "at prior" vs "tested"
    at_prior: int = 0
    tested: int = 0
    for s in statements:
        expected_prior = type_priors.get(s.belief_type, (0.5, 0.5))
        if abs(s.alpha - expected_prior[0]) < EVIDENCE_EPSILON and abs(s.beta_param - expected_prior[1]) < EVIDENCE_EPSILON:
            at_prior += 1
        else:
            tested += 1

    # Histograms
    conf_hist: dict[str, int] = Counter()
    evidence_hist: dict[str, int] = Counter()
    uncertainty_hist: dict[str, int] = Counter()

    for s in statements:
        # Confidence bins
        conf_bin = f"{int(s.confidence * 10) * 10:>3}-{int(s.confidence * 10) * 10 + 10:>3}%"
        conf_hist[conf_bin] += 1

        # Evidence bins
        if s.total_evidence < 1:
            evidence_hist["<1"] += 1
        elif s.total_evidence < 2:
            evidence_hist["1-2"] += 1
        elif s.total_evidence < 5:
            evidence_hist["2-5"] += 1
        elif s.total_evidence < 10:
            evidence_hist["5-10"] += 1
        elif s.total_evidence < 50:
            evidence_hist["10-50"] += 1
        else:
            evidence_hist["50+"] += 1

        # Uncertainty bins (variance)
        if s.uncertainty < 0.005:
            uncertainty_hist["very low (<0.005)"] += 1
        elif s.uncertainty < 0.01:
            uncertainty_hist["low (0.005-0.01)"] += 1
        elif s.uncertainty < 0.02:
            uncertainty_hist["moderate (0.01-0.02)"] += 1
        elif s.uncertainty < 0.05:
            uncertainty_hist["high (0.02-0.05)"] += 1
        else:
            uncertainty_hist["very high (>0.05)"] += 1

    # Per-type average uncertainty
    type_uncertainties: dict[str, list[float]] = defaultdict(list)
    for s in statements:
        type_uncertainties[s.belief_type].append(s.uncertainty)
    by_type_avg: dict[str, float] = {
        bt: sum(vals) / len(vals) for bt, vals in type_uncertainties.items()
    }

    # Sort by uncertainty for examples
    sorted_by_uncertainty = sorted(statements, key=lambda s: s.uncertainty, reverse=True)
    # Filter out locked for highest uncertainty (locked are always low uncertainty)
    unlocked_uncertain = [s for s in sorted_by_uncertainty if not s.locked]

    return CredalSummary(
        total=len(statements),
        at_prior=at_prior,
        tested=tested,
        locked_count=sum(1 for s in statements if s.locked),
        confidence_histogram=dict(conf_hist),
        evidence_histogram=dict(evidence_hist),
        uncertainty_histogram=dict(uncertainty_hist),
        by_type_avg_uncertainty=by_type_avg,
        highest_uncertainty=unlocked_uncertain[:15],
        lowest_uncertainty=sorted_by_uncertainty[-10:],
        type_priors=type_priors,
    )


from collections import defaultdict


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def bar(count: int, total: int, width: int = 40) -> str:
    """Simple text bar."""
    if total == 0:
        return ""
    filled = int(count / total * width)
    return "#" * filled + "." * (width - filled)


def main() -> None:
    results = analyze_credal_state()

    print("=" * 70)
    print("EXPERIMENT 82: CREDAL STATE ANALYSIS")
    print("=" * 70)

    prior_pct = results.at_prior / results.total * 100
    tested_pct = results.tested / results.total * 100
    locked_pct = results.locked_count / results.total * 100

    print(f"\nTotal active statements: {results.total}")
    print(f"  At type prior (untested): {results.at_prior} ({prior_pct:.1f}%)")
    print(f"  Tested (evidence > prior): {results.tested} ({tested_pct:.1f}%)")
    print(f"  Locked: {results.locked_count} ({locked_pct:.1f}%)")

    print(f"\n--- Detected Type Priors ---")
    for bt, (a, b) in sorted(results.type_priors.items()):
        conf = a / (a + b) if (a + b) > 0 else 0
        print(f"  {bt:>15}: alpha={a:.1f}, beta={b:.1f} -> conf={conf:.3f}")

    print(f"\n--- Confidence Distribution ---")
    for bin_label in sorted(results.confidence_histogram.keys()):
        count = results.confidence_histogram[bin_label]
        pct = count / results.total * 100
        print(f"  {bin_label}: {count:>6} ({pct:>5.1f}%) {bar(count, results.total)}")

    print(f"\n--- Total Evidence (alpha + beta) Distribution ---")
    evidence_order = ["<1", "1-2", "2-5", "5-10", "10-50", "50+"]
    for bin_label in evidence_order:
        count = results.evidence_histogram.get(bin_label, 0)
        pct = count / results.total * 100
        print(f"  {bin_label:>8}: {count:>6} ({pct:>5.1f}%) {bar(count, results.total)}")

    print(f"\n--- Uncertainty (Beta variance) Distribution ---")
    unc_order = ["very low (<0.005)", "low (0.005-0.01)", "moderate (0.01-0.02)",
                 "high (0.02-0.05)", "very high (>0.05)"]
    for bin_label in unc_order:
        count = results.uncertainty_histogram.get(bin_label, 0)
        pct = count / results.total * 100
        print(f"  {bin_label:>25}: {count:>6} ({pct:>5.1f}%) {bar(count, results.total)}")

    print(f"\n--- Avg Uncertainty by Type ---")
    for bt, avg_u in sorted(results.by_type_avg_uncertainty.items(), key=lambda x: -x[1]):
        print(f"  {bt:>15}: variance={avg_u:.6f}")

    print(f"\n--- Highest Uncertainty Statements (unlocked, top 10) ---")
    for s in results.highest_uncertainty[:10]:
        snippet = s.content[:80].replace("\n", " ")
        print(f"  [{s.belief_type}] a={s.alpha:.1f} b={s.beta_param:.1f} "
              f"var={s.uncertainty:.4f} conf={s.confidence:.3f}")
        print(f"    {snippet}")

    # Key insight
    print(f"\n--- Key Insight ---")
    print(f"The credal state is {'DOMINATED BY UNTESTED PRIORS' if prior_pct > 80 else 'mixed'}.")
    print(f"{prior_pct:.0f}% of statements have never received feedback.")
    print(f"The agent's 'beliefs' about {results.at_prior} statements are just type-based priors,")
    print(f"not empirically validated credences.")


if __name__ == "__main__":
    main()
