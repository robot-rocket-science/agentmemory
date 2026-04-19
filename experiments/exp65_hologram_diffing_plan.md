# Experiment 65: Hologram Diffing and Drift Detection

**Date:** 2026-04-11
**Builds on:** Exp 62 (minimal hologram), Exp 63 (profiles), Exp 45 (HRR prototype)
**Depends on:** Exp 62 results (hologram viability), Exp 63 results (serialization format)
**Rigor tier:** Empirically tested (real data, temporal analysis)

---

## Research Question

Can you meaningfully diff two holograms to detect how an agent's worldview shifted over time? Specifically: given two snapshots of the belief graph taken at different points, can we produce a human-interpretable summary of what changed, what was reinforced, and what was contradicted -- and is this diff more informative than just reading the git log between the two snapshots?

## Hypothesis

**H1 (Structural diff is computable):** A set-theoretic diff (added/removed/modified beliefs, added/removed edges, confidence shifts) between two holograms can be computed in under 100ms for graphs up to 2,000 nodes.

**H2 (Drift is detectable):** Simulating 50 conversation turns on the project-a graph will produce measurable drift in the hologram: at least 10% of the top-100 beliefs at turn 50 will not appear in the top-100 at turn 0. The drift is not random -- it correlates with the topics of the simulated turns.

**H3 (Diff is informative):** The hologram diff between "before a correction" and "after a correction" will surface the corrected belief as the highest-impact change (largest confidence delta). This tests whether the diff captures semantically meaningful shifts, not just noise.

**H4 (Diff beats git log):** For a simulated session involving 10 belief changes spread across 50 conversation turns, the hologram diff will identify all 10 changed beliefs in a single summary, while `git log` on the same period will show file-level changes that do not directly surface the belief-level shifts.

## Null Hypothesis

Hologram diffs are dominated by noise (Thompson sampling variance, temporal decay drift). The meaningful signal (corrections, new decisions, reinforced beliefs) is buried in stochastic score fluctuations. A human reading the diff cannot distinguish real worldview shifts from scoring noise.

## Why This Matters

If diffs work, the hologram becomes a version-controlled artifact:
- "What changed about this agent's understanding since last week?"
- "Before the refactor, the agent believed X. After, it believes Y. Here's why."
- Drift detection: "The agent's posture on async has shifted from cautious to aggressive over the last 20 sessions. Is that intentional?"
- Audit trail: the diff IS the changelog of the agent's mind.

If diffs are noise-dominated, we need to stabilize scoring before diffing is useful (e.g., use MAP estimates instead of Thompson samples, or diff on locked beliefs only).

## Materials

**Dataset:** project-a belief graph (1,195 nodes, 1,485 edges).

**Simulated turns:** 50 conversation turns, each containing 1-3 sentences. Content drawn from the existing observation corpus (reshuffle and replay in different order to simulate a new session).

**Corrections:** 3 explicit corrections inserted at turns 15, 30, and 45:
- Turn 15: "Actually, HRR is useful for fuzzy-start retrieval, not multi-hop." (Aligns with existing locked belief -- should reinforce, not change.)
- Turn 30: "The token budget should be 3000, not 2000." (Contradicts REQ-003 -- should create a high-impact correction.)
- Turn 45: "Forget about temporal edges, they add zero signal." (Aligns with Exp 48 findings -- should reinforce existing evidence.)

**Random seed:** 42 for all stochastic operations.

## Methodology

### Phase 1: Diff computation

Define the diff structure:

```python
@dataclass
class HologramDiff:
    added: list[Belief]           # in B but not A (by content_hash)
    removed: list[Belief]         # in A but not B
    confidence_shifted: list[tuple[Belief, float, float]]  # (belief, old_conf, new_conf)
    edges_added: list[Edge]
    edges_removed: list[Edge]
    locked_changes: list[tuple[Belief, bool, bool]]  # (belief, was_locked, now_locked)
    top_k_turnover: float         # Jaccard distance of top-k sets
```

1. Implement `diff_holograms(a: list[Belief], b: list[Belief], edges_a, edges_b, k=100)`.
2. Benchmark: measure diff time for graph sizes [100, 500, 1000, 2000] (20 reps each).

### Phase 2: Drift measurement

3. Take a snapshot of the hologram at turn 0 (the existing graph).
4. Simulate 50 turns by ingesting reshuffled observations through the existing `ingest_turn` pipeline.
5. After every 5 turns, snapshot the hologram (top-100 by Thompson score, fixed seed).
6. Compute diff between consecutive snapshots (turn 0 vs 5, 5 vs 10, ..., 45 vs 50).
7. Compute cumulative diff (turn 0 vs each snapshot).
8. Measure: top_k_turnover at each snapshot. Plot turnover vs. turn count.

### Phase 3: Correction impact

9. Insert the 3 corrections at turns 15, 30, 45 using `agentmemory correct`.
10. Snapshot immediately before and after each correction.
11. Compute diff for each correction pair.
12. Rank all beliefs in the diff by |confidence_delta|.
13. Check: does the corrected/reinforced belief appear in the top-3 by impact?

### Phase 4: Signal-to-noise ratio

14. Compute the diff between two snapshots taken 1 second apart with NO intervening turns (pure noise from Thompson sampling variance and decay drift).
15. Measure the "noise floor": mean |confidence_delta| across all beliefs in the noise diff.
16. Compare to the mean |confidence_delta| in the correction diffs from Phase 3.
17. SNR = mean_correction_delta / mean_noise_delta. Target: SNR > 5.

### Phase 5: Diff vs. git log comparison

18. Record all file-level changes made during the 50-turn simulation (SQLite writes to memory.db).
19. Run `git log --oneline` equivalent (list the ingested turns with timestamps).
20. Compare: how many of the 10 semantically meaningful changes (3 corrections + 7 largest confidence shifts) are identifiable from the git-level log vs. the hologram diff?
21. Score: diff_recall = (meaningful changes surfaced by diff) / 10, git_recall = (meaningful changes surfaced by git log) / 10.

## Metrics

| Metric | Formula | Target | Interpretation |
|--------|---------|--------|----------------|
| Diff latency p95 | 95th percentile at 1,195 nodes | < 100ms | Real-time diffing is feasible |
| Top-k turnover after 50 turns | Jaccard(top-100 at turn 0, top-100 at turn 50) | 0.10-0.30 | Measurable but not chaotic drift |
| Correction impact rank | rank of corrected belief in diff by \|confidence_delta\| | top-3 | Diff captures semantically meaningful changes |
| SNR (correction vs. noise) | mean_correction_delta / mean_noise_delta | > 5 | Signal is distinguishable from noise |
| Diff recall | meaningful changes surfaced / 10 | >= 0.8 | Diff captures most real shifts |
| Git recall | meaningful changes surfaced / 10 | <= 0.3 | Git log alone misses belief-level changes |

## Expected Results

| Phase | Expected Outcome | Reasoning |
|-------|------------------|-----------|
| Diff latency | < 50ms at 1,195 nodes | Set operations on content_hash, no expensive computation |
| Turnover after 50 turns | 0.15-0.25 | Ingesting reshuffled observations will bump some beliefs up, push others down, but core locked beliefs stay |
| Correction at rank 1-2 | Turn 30 correction (budget change) should be rank 1 | It contradicts an existing belief, creating the largest confidence delta |
| SNR | 8-15 | Corrections create large discrete jumps; noise is small continuous drift |
| Diff recall | 0.9-1.0 | The diff is designed to surface exactly these changes |
| Git recall | 0.1-0.2 | Git sees "modified memory.db" 50 times, no belief-level visibility |

## Decision Criteria

| If This Happens | Then Do This |
|-----------------|--------------|
| SNR > 5 and correction rank <= 3 | Diff is viable. Implement `agentmemory diff <snapshot-a> <snapshot-b>` CLI command. |
| SNR < 2 | Thompson sampling noise drowns out real changes. Switch to MAP estimates for diffing (alpha/(alpha+beta) without sampling). Re-run. |
| Turnover > 0.5 after 50 turns | The hologram is too unstable. Investigate: is decay too aggressive? Are low-confidence beliefs churning? |
| Turnover < 0.05 after 50 turns | The hologram is too rigid. New evidence is not penetrating the top-k. Investigate lock_boost dominance. |
| Diff recall < 0.5 | The diff misses real changes. Investigate: are the changes too small to rank above noise? Need a minimum-delta filter. |

## Confounds and Controls

- **Turn order effects:** Reshuffling observations changes the order of Bayesian updates, which changes final confidence. Mitigation: run Phase 2 with 3 different shuffle seeds. Report mean and variance of turnover.
- **Correction strength:** The 3 corrections are hand-crafted to be unambiguous. Real corrections may be subtler. Mitigation: include 2 "soft" corrections in the simulation ("maybe we should reconsider X") and measure their rank separately.
- **Decay coupling:** Temporal decay changes all scores over time, even without new evidence. Phase 4 (noise floor) explicitly measures this. If the noise floor is high, decay must be factored out of the diff (compare scores at the same reference time).

---

## Files

- `exp65_hologram_diffing.py` -- all phases
- `exp65_results.json` -- drift measurements, SNR data, correction ranks
- `exp65_hologram_diffing_results.md` -- analysis
