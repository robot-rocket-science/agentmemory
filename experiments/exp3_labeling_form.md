# Experiment 3: Retrieval Quality Labeling Form

For each query, label every result as:
- **R** = Relevant (this belief should be in the result set)
- **P** = Partially relevant (related but not directly useful)
- **N** = Not relevant (noise)

Do NOT look at exp3_attribution.json until all labeling is complete.

---

## q01: what is the status on the paper trading agents?
*Search terms: paper trading agents status*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q01_item_000 | ___ | Permanent settlement: calls and puts are equal citizens; problem is detector uti | strategy |
| q01_item_001 | ___ | trades.json format: flat event array, not {trades: [...]} wrapper | knowledge |
| q01_item_002 | ___ | How to fetch underlying stock price on Alpaca free-tier paper trading: SIP->IEX  | data-source |
| q01_item_003 | ___ | Clarification of D073 "equal citizens": does equal mean identical config?: Equal | strategy |
| q01_item_004 | ___ | Whether Config B is ready for live deployment of $5,000: CONDITIONAL NO-GO. Pape | methodology |
| q01_item_005 | ___ | Calls and puts are permanently equal citizens (D073) | knowledge |
| q01_item_006 | ___ | Dual-engine (call+put) walk-forward verdict and configuration forward path: All  | strategy |
| q01_item_007 | ___ | Whether the agent should raise questions about call vs put inclusion in the stra | agent behavior |
| q01_item_008 | ___ | Alpaca free-tier indicative feed provides full Greeks at 100% coverage (D206) | knowledge |
| q01_item_009 | ___ | [M036] Milestone M036 | milestone |
| q01_item_010 | ___ | Whether any put-side strategy is viable given three complete option-level univer | strategy |
| q01_item_011 | ___ | GCP dispatch: closer agent must complete incomplete dispatcher work | knowledge |
| q01_item_012 | ___ | How to evaluate strategy performance during paper trading and live deployment: A | methodology |
| q01_item_013 | ___ | scripts/paper_trade.py must load .env via python-dotenv at startup | knowledge |
| q01_item_014 | ___ | [M014] Milestone M014 | milestone |
| q01_item_015 | ___ | HARD RULE: Never question call vs put inclusion (D073, D100) | knowledge |
| q01_item_016 | ___ | Production config for paper trading deployment: Config B sigprob-035: model=none | strategy |
| q01_item_017 | ___ | Priority hypothesis for M006: split-config argmax with per-direction hold/target | strategy |
| q01_item_018 | ___ | M003-77er88 (Simplify and Validate) milestone status: Superseded. S01 was the on | strategy |
| q01_item_019 | ___ | Hold-to-expiry and sizing are open research questions: Neither locked. Hold-to-e | architecture |
| q01_item_020 | ___ | Alpaca SIP feed returns 403 on free-tier paper accounts -- use IEX fallback (D20 | knowledge |
| q01_item_021 | ___ | Live Alpaca smoke test: three upstream data layer issues block full pipeline (M0 | knowledge |
| q01_item_022 | ___ | M004 (Put-Buying Engine) milestone status: Superseded. The dual call+put engine  | strategy |
| q01_item_023 | ___ | Assessment of meta-decision overfitting to walk-forward validation set: Meta-dec | strategy |
| q01_item_024 | ___ | How the agent should respond to direct user instructions: Execute exactly what t | agent behavior |
| q01_item_025 | ___ | Whether paper trading deployment (M036) should include puts alongside calls: Cal | strategy |
| q01_item_026 | ___ | Whether Alpaca free-tier paper trading provides option Greeks for chain_adapter. | data-source |
| q01_item_027 | ___ | How to evaluate strategy performance across time: Walk-forward per-year fold eva | backtesting |

## q02: did we update the master results file?
*Search terms: master results file updated*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q02_item_000 | ___ | [M030] Milestone M030 | milestone |
| q02_item_001 | ___ | D097 walk-forward verdict for highvol fixed-family (highvol_strict and highvol)  | strategy |
| q02_item_002 | ___ | [M018] Milestone M018 | milestone |
| q02_item_003 | ___ | Serial port output as partial results fallback for running GCP VMs | knowledge |
| q02_item_004 | ___ | Milestone with zero S02 results: label NEGATIVE for closure, not INCONCLUSIVE | knowledge |
| q02_item_005 | ___ | Walk-forward verify JSON timing artifact: T01 failing verify does not mean files | knowledge |
| q02_item_006 | ___ | Archon parallel nohup scans: check completion via file count, not log tailing | knowledge |
| q02_item_007 | ___ | 6 pending results completed on GCS, never collected | knowledge |
| q02_item_008 | ___ | Whether the kelly union coverage test is needed: Kelly-d10 and kelly-dte45 union | strategy |
| q02_item_009 | ___ | assemble_r12_folds.py: R12 uses nested fold_YYYY/summary.json, not flat files | knowledge |
| q02_item_010 | ___ | How to resolve split src/ packages between project-a and project-b: Symlink | architecture |
| q02_item_011 | ___ | Spike research findings must land in KNOWLEDGE.md, DECISIONS.md, or milestone CO | knowledge |
| q02_item_012 | ___ | Decouple project-a from project-b symlinks: Copy all 5 project-b module | architecture |
| q02_item_013 | ___ | M030 S01: kelly-d10-dte20 ruin year is 2018, not 2016 (confirmed via compound NA | knowledge |
| q02_item_014 | ___ | D090: project-b modules are now copied into project-a (supersedes symlink e | knowledge |
| q02_item_015 | ___ | Whether D097 is sufficient to declare live-trading readiness: D097 with $5K capi | methodology |
| q02_item_016 | ___ | Whether to implement an adaptive minimum-N floor that relaxes pipeline gates whe | strategy |
| q02_item_017 | ___ | M034 S01: Kelly failure taxonomy -- 3 classes, only PRICE_BAND_MISMATCH is actio | knowledge |
| q02_item_018 | ___ | Auto-mode interruption during remote result collection: write INCOMPLETE section | knowledge |
| q02_item_019 | ___ | Root cause of kelly's 4 wipeout years: The 4 winnable wipeout years (2016/2017/2 | strategy |
| q02_item_020 | ___ | F-series walk-forward dispatch should be a separate slice from result collection | knowledge |
| q02_item_021 | ___ | M030 S01: live-trading readiness requires both D097 AND compound-NAV check (quan | knowledge |
| q02_item_022 | ___ | [M006] Detector Utilization + Hypothesis Testing | milestone |
| q02_item_023 | ___ | gsd_summary_save overwrites the target file | knowledge |
| q02_item_024 | ___ | analyze_s03_results.py: embed R12 baseline constants, do not load from a file | knowledge |
| q02_item_025 | ___ | Whether to frame this as a "lottery ticket" strategy or a more precise analogy:  | strategy framing |
| q02_item_026 | ___ | GCP serial port output: fold results are visible before result files upload to G | knowledge |
| q02_item_027 | ___ | Dispatch-gate blocks gcp_dispatch.py when image_built not satisfied in current s | knowledge |
| q02_item_028 | ___ | gcp_dispatch.py --matrix flag: dispatch from JSON run matrix file | knowledge |
| q02_item_029 | ___ | M030 S02: VIX gate ablation falsifies N-starvation hypothesis as root cause of w | knowledge |
| q02_item_030 | ___ | Archon is canonical data host: Archon hosts all DuckDB files. Rsync direction: a | data |

## q03: please review the results, use the 3 analysis frameworks and provide a summary table
*Search terms: analysis frameworks summary results hamiltonian jacobian dual matrix*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q03_item_000 | ___ | GBM drift calibration target: Drift mu set so that P(S_T >= 1.15*S_0) = signal_p | generative-model |
| q03_item_001 | ___ | Whether and where to apply Bayesian methods (posterior predictive distribution,  | architecture |
| q03_item_002 | ___ | M001_OTM_baseline call-only E[V] is -0.08 (margin=-1.7pp), NOT +2.854 | knowledge |
| q03_item_003 | ___ | Dual-matrix pairwise decomposition: confusion axis is 15x larger than payoff axi | knowledge |
| q03_item_004 | ___ | Starting capital as a strategy lever: Starting capital ($5K vs $100K) is a strat | strategy |
| q03_item_005 | ___ | gcp_dispatch.py --matrix flag: dispatch from JSON run matrix file | knowledge |
| q03_item_006 | ___ | SDT framework gaps to address: (1) Wire EV integrator to threshold decision, (2) | strategy |
| q03_item_007 | ___ | Ticker universe for signal_15pct.yaml and all M002 backtests: 32-ticker ex-GE un | configuration |
| q03_item_008 | ___ | [M002] MCTS Objective Fix + Pipeline Intelligence | milestone |
| q03_item_009 | ___ | Measure choice for edge surface: model-implied P(ITM) vs market-implied P(ITM):  | architecture |
| q03_item_010 | ___ | compare_m017_integration.py: template for two-config walk-forward comparison wit | knowledge |
| q03_item_011 | ___ | Citation requirement for all project document assertions: All assertions in proj | methodology |
| q03_item_012 | ___ | Research program kill criteria and capital-as-variable policy: No kill criteria  | strategy |
| q03_item_013 | ___ | NAV-based Hamiltonian is a relabeling — validated 2/5 folds only | knowledge |
| q03_item_014 | ___ | summary.json does not store config metadata | knowledge |
| q03_item_015 | ___ | [M020] Milestone M020 | milestone |
| q03_item_016 | ___ | M025-rvd7c5 spray analysis: analysis infrastructure built before dispatch data e | knowledge |
| q03_item_017 | ___ | Whether higher capital ($10K, $25K) would improve D097 verdicts based on dual-ma | strategy |
| q03_item_018 | ___ | What is the starting bankroll for all backtests and live trading simulations?: $ | strategy |
| q03_item_019 | ___ | M018 is the shortest path to viability; M015 is deprioritized (cross-milestone d | knowledge |
| q03_item_020 | ___ | Reassessment of D155 (capital constraint as accidental filter) based on spike 26 | strategy |
| q03_item_021 | ___ | GCP compute budget policy for research: Use GCP freely for research compute — no | infrastructure |
| q03_item_022 | ___ | pct_equity 0.5% dominates structurally for asymmetric payoffs | knowledge |
| q03_item_023 | ___ | M018: KNOWLEDGE.md M001 OTM baseline E[V]=+2.854 is bothsides (calls+puts), not  | knowledge |
| q03_item_024 | ___ | How to evaluate strategy performance across time: Walk-forward per-year fold eva | backtesting |
| q03_item_025 | ___ | Jacobian at kelly-d10 operating point: N is cheapest lever, p has highest sensit | knowledge |
| q03_item_026 | ___ | walk_forward_backtest.py FoldResult.dual_matrix: dict[str, Any], scalar attrs pr | knowledge |
| q03_item_027 | ___ | [M001] MCTS Contract Selection Planner | milestone |
| q03_item_028 | ___ | [M023] Milestone M023 | milestone |
| q03_item_029 | ___ | Adopt dual-matrix decision framework (confusion matrix x payoff matrix) as diagn | architecture |
| q03_item_030 | ___ | Strategic direction after cross-config dual-matrix diagnostic (31 configs, 25+ m | strategy |
| q03_item_031 | ___ | M030 S04: Combined GO-NO-GO verdict pattern -- dual gate (D097 + sequential NAV) | knowledge |
| q03_item_032 | ___ | Pairwise dual-matrix baseline must be from the same config family (not R12) | knowledge |

## q04: change a config based on these test results
*Search terms: change config test results update configuration*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q04_item_000 | ___ | [M033] Milestone M033 | milestone |
| q04_item_001 | ___ | [M036] Milestone M036 | milestone |
| q04_item_002 | ___ | Whether LightGBM model improves walk-forward D097 results vs model=none baseline | strategy |
| q04_item_003 | ___ | How to evaluate strategy performance across time: Walk-forward per-year fold eva | backtesting |
| q04_item_004 | ___ | Whether M026-eq3jt1 is gated on M027-lelhcb completion: Remove the M027 dependen | strategy |
| q04_item_005 | ___ | Whether Config B is ready for live deployment of $5,000: CONDITIONAL NO-GO. Pape | methodology |
| q04_item_006 | ___ | Fill model slippage threshold setting (signal_15pct.yaml config): Hold at 20% de | strategy |
| q04_item_007 | ___ | Primary evaluation metrics for lottery-ticket option strategies: D097 per-year p | strategy |
| q04_item_008 | ___ | Re-derived best config for holdout validation (M007-xtpz0d S01): 0.05/90d/0.2 (e | methodology |
| q04_item_009 | ___ | avg_hold_days_actual for puts is far below configured hold_days | knowledge |
| q04_item_010 | ___ | Docker image/deploy race: if code changes after build, GCP sees old function sig | knowledge |
| q04_item_011 | ___ | [M006] Detector Utilization + Hypothesis Testing | milestone |
| q04_item_012 | ___ | [M007] Holdout Validation -- 2024-2025 True Test Set | milestone |
| q04_item_013 | ___ | Argmax deep-OTM objective suitability: Argmax E[return_on_premium] objective is  | strategy |
| q04_item_014 | ___ | Dual-engine (call+put) walk-forward verdict and configuration forward path: All  | strategy |
| q04_item_015 | ___ | [M027] Milestone M027 | milestone |
| q04_item_016 | ___ | Signal model configuration for production use: LightGBM + V2 (57 features) + 15% | signal-model |
| q04_item_017 | ___ | [M011] Milestone M011 | milestone |
| q04_item_018 | ___ | [M026] Milestone M026 | milestone |
| q04_item_019 | ___ | Exit pricing bug: runner never called handle_expiry(), giving phantom post-expir | backtesting |
| q04_item_020 | ___ | D067 holdout has NOT been executed for Config B -- mandatory before live deploym | knowledge |
| q04_item_021 | ___ | Dispatch-gate HEAD!=image-tag bypass: non-Docker changes only | knowledge |
| q04_item_022 | ___ | GCP serial port output: fold results are visible before result files upload to G | knowledge |
| q04_item_023 | ___ | [M002] MCTS Objective Fix + Pipeline Intelligence | milestone |
| q04_item_024 | ___ | deploy_server.sh does not sync docker/ directory — Dockerfile changes require ma | knowledge |
| q04_item_025 | ___ | 4 signal model configs selected for DTE routing: 5d/10% (short), 10d/20% (medium | configuration |
| q04_item_026 | ___ | Which config to use going forward: R12 (0.03/60d/0.1) or holdout-derived (0.05/9 | configuration |
| q04_item_027 | ___ | How to report strategy returns in all project artifacts: Always report returns i | reporting |
| q04_item_028 | ___ | Strategic pivot: test no-model mechanical baseline before any further ML develop | strategy |
| q04_item_029 | ___ | Assessment of meta-decision overfitting to walk-forward validation set: Meta-dec | strategy |

## q05: update the config based on our latest research
*Search terms: update config latest research findings*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q05_item_000 | ___ | What is the starting bankroll for all backtests and live trading simulations?: $ | strategy |
| q05_item_001 | ___ | Signal event spreads are 6x wider than random OTM options (M012 S02 finding) | knowledge |
| q05_item_002 | ___ | Planning agents must follow accumulated research and discussions, starting with  | methodology |
| q05_item_003 | ___ | GCP compute budget policy for research: Use GCP freely for research compute — no | infrastructure |
| q05_item_004 | ___ | Execution fidelity gap: research findings must be verified as actually incorpora | methodology |
| q05_item_005 | ___ | M031: Pre-execution research checklist is mandatory (D194, D195) | knowledge |
| q05_item_006 | ___ | How to incorporate 6 research-identified hypotheses from DOWNSTREAM-MODULE-TRADE | strategy |
| q05_item_007 | ___ | Spike research findings must land in KNOWLEDGE.md, DECISIONS.md, or milestone CO | knowledge |
| q05_item_008 | ___ | Oracle ceiling test distinguishes exit research ROI between trade populations | knowledge |
| q05_item_009 | ___ | [M014] Milestone M014 | milestone |
| q05_item_010 | ___ | Scope applicability of D062 exit rule findings (all 5 rules worse than hold-to-e | strategy |
| q05_item_011 | ___ | Starting capital as a strategy lever: Starting capital ($5K vs $100K) is a strat | strategy |
| q05_item_012 | ___ | Research program kill criteria and capital-as-variable policy: No kill criteria  | strategy |
| q05_item_013 | ___ | Argmax oracle ceiling is NEGATIVE: exit research on argmax trades is structurall | knowledge |
| q05_item_014 | ___ | Optimizing p and W independently of N has uniformly failed D097 across 25+ miles | knowledge |
| q05_item_015 | ___ | Hard constraint: every milestone plan must increase expected trades/year above t | methodology |
| q05_item_016 | ___ | How to prevent research findings from being ignored during milestone execution:  | methodology |
| q05_item_017 | ___ | Research direction: reframe profitability problem as detection rate (recall) on  | strategy |
| q05_item_018 | ___ | Strategy objective framing in CLAUDE.md project description: Maximum PnL growth  | strategy |
| q05_item_019 | ___ | M016 NO-GO structural finding: argmax selects short-DTE contracts that expire be | knowledge |
| q05_item_020 | ___ | Primary D097 prediction metric: N*p vs N*p*W: Replace N*p*W with N*p (expected w | strategy |
| q05_item_021 | ___ | What is the correct optimization target for the D097 walk-forward criterion?: Ma | strategy |
| q05_item_022 | ___ | N × p × W is the correct formula for E[return] but the wrong optimization target | knowledge |
| q05_item_023 | ___ | Root cause of kelly's 4 wipeout years: The 4 winnable wipeout years (2016/2017/2 | strategy |
| q05_item_024 | ___ | Exit rule research is closed for both argmax and fixed-family highvol configs | knowledge |
| q05_item_025 | ___ | How to evaluate strategy performance across time: Walk-forward per-year fold eva | backtesting |
| q05_item_026 | ___ | [M031] Milestone M031 | milestone |
| q05_item_027 | ___ | Whether the N funnel gates or input event volume is the binding constraint on tr | strategy |
| q05_item_028 | ___ | walk_forward_backtest.py does not support --put-config (M014 S01 finding) | knowledge |

## q06: review all of our documentation and update it as necessary so we are working with full ground truth
*Search terms: review documentation ground truth state decisions*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q06_item_000 | ___ | GCP batch collection: select by VM lifecycle state, not by dispatch order | knowledge |
| q06_item_001 | ___ | GO/NO-GO scorecard: state all criteria and thresholds before any data is visible | knowledge |
| q06_item_002 | ___ | [M001] MCTS Contract Selection Planner | milestone |
| q06_item_003 | ___ | Spike research findings must land in KNOWLEDGE.md, DECISIONS.md, or milestone CO | knowledge |
| q06_item_004 | ___ | Execution fidelity gap: research findings must be verified as actually incorpora | methodology |
| q06_item_005 | ___ | Where to insert the game-theoretic decision layer milestone in the M011-M016 roa | architecture |
| q06_item_006 | ___ | Root cause of kelly's 4 wipeout years: The 4 winnable wipeout years (2016/2017/2 | strategy |
| q06_item_007 | ___ | RRF outperforms all trained LightGBM variants in M025 — model-free rank fusion b | knowledge |
| q06_item_008 | ___ | Citation requirement for all project document assertions: All assertions in proj | methodology |
| q06_item_009 | ___ | [M031] Milestone M031 | milestone |
| q06_item_010 | ___ | How to prevent research findings from being ignored during milestone execution:  | methodology |
| q06_item_011 | ___ | Anti-overfitting as a mandatory design principle for M022 (Learned Contract Sele | methodology |
| q06_item_012 | ___ | [M027] Milestone M027 | milestone |
| q06_item_013 | ___ | LightGBM assessment in project documentation: Reframe LightGBM from 'most reliab | documentation |
| q06_item_014 | ___ | M024: Bandit logs every decision to decision_log (not every 10th like argmax/MCT | knowledge |
| q06_item_015 | ___ | Seller HJB fires in buyer-losing states (D063) | knowledge |
| q06_item_016 | ___ | What is the correct optimization target for the D097 walk-forward criterion?: Ma | strategy |
| q06_item_017 | ___ | Strategic direction after cross-config dual-matrix diagnostic (31 configs, 25+ m | strategy |
| q06_item_018 | ___ | Detection gap assessment: are entry-time features discriminative for option prof | strategy |
| q06_item_019 | ___ | SDT framework gaps to address: (1) Wire EV integrator to threshold decision, (2) | strategy |
| q06_item_020 | ___ | Assessment of meta-decision overfitting to walk-forward validation set: Meta-dec | strategy |
| q06_item_021 | ___ | Framing for M026: Bayesian posterior over latent regime state, not a weight adju | methodology |
| q06_item_022 | ___ | [M008] Milestone M008 | milestone |
| q06_item_023 | ___ | [M034] Milestone M034 | milestone |
| q06_item_024 | ___ | Walk-forward CV is clean but meta-decisions are contaminated (D067) | knowledge |
| q06_item_025 | ___ | Going forward: replace all "lottery ticket" language with "sports bet" language  | knowledge |
| q06_item_026 | ___ | D136: All project document assertions must have evidence citations | knowledge |
| q06_item_027 | ___ | Planning agents must follow accumulated research and discussions, starting with  | methodology |

## q07: what do these results tell us about our experiments so far; do they invalidate anything we've already run and built upon?
*Search terms: results invalidate experiments assumptions built upon*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q07_item_000 | ___ | Impact assessment of pre-D181 results (no bankruptcy termination in signal runne | methodology |
| q07_item_001 | ___ | How to evaluate strategy performance across time: Walk-forward per-year fold eva | backtesting |
| q07_item_002 | ___ | Put intrinsic exit pricing bug impact assessment: All GCP backtest put PnL is in | backtesting |
| q07_item_003 | ___ | D097 walk-forward verdict for purpose-built decline-event put model (M023): CONC | strategy |
| q07_item_004 | ___ | M022 best learned contract selector variant: V3 (classifier pre-filter threshold | strategy |
| q07_item_005 | ___ | Milestone with zero S02 results: label NEGATIVE for closure, not INCONCLUSIVE | knowledge |
| q07_item_006 | ___ | M025-rvd7c5 spray analysis: analysis infrastructure built before dispatch data e | knowledge |
| q07_item_007 | ___ | M004 (Put-Buying Engine) milestone status: Superseded. The dual call+put engine  | strategy |
| q07_item_008 | ___ | F-series walk-forward dispatch should be a separate slice from result collection | knowledge |
| q07_item_009 | ___ | [M027] Milestone M027 | milestone |
| q07_item_010 | ___ | [M024] Milestone M024 | milestone |
| q07_item_011 | ___ | [M014] Milestone M014 | milestone |
| q07_item_012 | ___ | Dispatch-gate blocks gcp_dispatch.py when image_built not satisfied in current s | knowledge |
| q07_item_013 | ___ | Starting capital protocol: amount, reset cadence, and bankruptcy behavior in wal | methodology |
| q07_item_014 | ___ | Anti-overfitting as a mandatory design principle for M022 (Learned Contract Sele | methodology |
| q07_item_015 | ___ | [M025] Milestone M025 | milestone |
| q07_item_016 | ___ | [M032] Milestone M032 | milestone |
| q07_item_017 | ___ | Whether D120 (server-a is overflow only) applies to M032 S01 2-fold smoke test: Ex | infrastructure |
| q07_item_018 | ___ | GCP serial port output: fold results are visible before result files upload to G | knowledge |
| q07_item_019 | ___ | 6 pending results completed on GCS, never collected | knowledge |
| q07_item_020 | ___ | Auto-mode interruption during remote result collection: write INCOMPLETE section | knowledge |
| q07_item_021 | ___ | CLI flag naming for DTE floor experiment: Use existing --dte-lo flag name (not - | naming |
| q07_item_022 | ___ | Classifier model choice and feature set for learned contract selector: LogisticR | architecture |
| q07_item_023 | ___ | [M030] Milestone M030 | milestone |
| q07_item_024 | ___ | [M022] Milestone M022 | milestone |
| q07_item_025 | ___ | M006 scope and identity after M008/M009/M010 invalidated all original baselines: | milestone |
| q07_item_026 | ___ | What is the starting bankroll for all backtests and live trading simulations?: $ | strategy |
| q07_item_027 | ___ | Serial port output as partial results fallback for running GCP VMs | knowledge |
| q07_item_028 | ___ | Compute target for all backtests and experiments: GCP is primary for all backtes | infrastructure |
| q07_item_029 | ___ | M023: Walk-forward at 5% decline target produces too few fills for reliable D097 | knowledge |

## q08: whats our full project status and strategy outlook?
*Search terms: project status strategy outlook full overview*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q08_item_000 | ___ | [M009] Milestone M009 | milestone |
| q08_item_001 | ___ | Strategy objective framing in CLAUDE.md project description: Maximum PnL growth  | strategy |
| q08_item_002 | ___ | M031: Config reproducibility requires full flag echo in dispatch matrices | knowledge |
| q08_item_003 | ___ | Mechanical enforcement of pyright strict typing: Three-layer enforcement: Makefi | code-quality |
| q08_item_004 | ___ | Python regular packages block cross-project module resolution (D054) | knowledge |
| q08_item_005 | ___ | Live Alpaca smoke test: three upstream data layer issues block full pipeline (M0 | knowledge |
| q08_item_006 | ___ | [M006] Detector Utilization + Hypothesis Testing | milestone |
| q08_item_007 | ___ | [M007] Holdout Validation -- 2024-2025 True Test Set | milestone |
| q08_item_008 | ___ | D136: All project document assertions must have evidence citations | knowledge |
| q08_item_009 | ___ | [M010] Milestone M010 | milestone |
| q08_item_010 | ___ | [M005] Game-Theoretic Exit Strategy | milestone |
| q08_item_011 | ___ | Exit pricing bug: runner never called handle_expiry(), giving phantom post-expir | backtesting |
| q08_item_012 | ___ | S02 GCP dispatch: validate one run locally before launching full sweep | knowledge |
| q08_item_013 | ___ | M006 call-side baseline rescoped from fixed OTM +227% to argmax +26-33%: Argmax  | strategy |
| q08_item_014 | ___ | Enforce D097 walk-forward per-year backtesting protocol as a standing project ru | methodology |
| q08_item_015 | ___ | M003-77er88 (Simplify and Validate) milestone status: Superseded. S01 was the on | strategy |
| q08_item_016 | ___ | gcloud storage ls returns full paths; use fnmatch for client-side glob | knowledge |
| q08_item_017 | ___ | How to evaluate strategy performance across time: Walk-forward per-year fold eva | backtesting |
| q08_item_018 | ___ | M006 scope and identity after M008/M009/M010 invalidated all original baselines: | milestone |
| q08_item_019 | ___ | How to resolve split src/ packages between project-a and project-b: Symlink | architecture |
| q08_item_020 | ___ | Fill model slippage threshold setting (signal_15pct.yaml config): Hold at 20% de | strategy |
| q08_item_021 | ___ | Alpaca free-tier indicative feed provides full Greeks at 100% coverage (D206) | knowledge |
| q08_item_022 | ___ | Citation requirement for all project document assertions: All assertions in proj | methodology |
| q08_item_023 | ___ | [M008] Milestone M008 | milestone |
| q08_item_024 | ___ | Strict typing enforcement with pyright across entire project-a codebase: Instal | code-quality |
| q08_item_025 | ___ | GCP: VM naming produces double-prefix when run_id already contains a project pre | knowledge |
| q08_item_026 | ___ | Conformal wrapper: alpha=0.0 means full coverage (all trades admitted), not hard | knowledge |
| q08_item_027 | ___ | M004 (Put-Buying Engine) milestone status: Superseded. The dual call+put engine  | strategy |

## q09: what have we accomplished, where are we now, where are we going?
*Search terms: accomplished progress current state goals roadmap*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q09_item_000 | ___ | M022: Archon fold count check must grep for " done." with leading space | knowledge |
| q09_item_001 | ___ | M022 best learned contract selector variant: V3 (classifier pre-filter threshold | strategy |
| q09_item_002 | ___ | GCP batch collection: select by VM lifecycle state, not by dispatch order | knowledge |
| q09_item_003 | ___ | Research direction: reframe profitability problem as detection rate (recall) on  | strategy |
| q09_item_004 | ___ | Planning agents must follow accumulated research and discussions, starting with  | methodology |
| q09_item_005 | ___ | GCP walk-forward: GCS upload is all-or-nothing at script end -- per-fold progres | knowledge |
| q09_item_006 | ___ | Framing for M026: Bayesian posterior over latent regime state, not a weight adju | methodology |
| q09_item_007 | ___ | [M006] Detector Utilization + Hypothesis Testing | milestone |
| q09_item_008 | ___ | Anti-overfitting as a mandatory design principle for M022 (Learned Contract Sele | methodology |
| q09_item_009 | ___ | [M024] Milestone M024 | milestone |
| q09_item_010 | ___ | [M022] Milestone M022 | milestone |
| q09_item_011 | ___ | Whether to add volume-dependent market impact to the fill model: No change neede | fill-model |
| q09_item_012 | ___ | [M025] Milestone M025 | milestone |
| q09_item_013 | ___ | Where to insert the game-theoretic decision layer milestone in the M011-M016 roa | architecture |
| q09_item_014 | ___ | Revised scope for M024-60hkjc (Contextual Bandit): 4 runs: LinUCB + Thompson Sam | strategy |
| q09_item_015 | ___ | Revise D118 to allow DTE constraints informed by data (M021 recall finding): D11 | architecture |
| q09_item_016 | ___ | walk_forward_backtest.py support for dual-engine (--put-config) runs: walk_forwa | architecture |
| q09_item_017 | ___ | Dispatch-gate blocks gcp_dispatch.py when image_built not satisfied in current s | knowledge |
| q09_item_018 | ___ | Whether any put-side strategy is viable given three complete option-level univer | strategy |
| q09_item_019 | ___ | Classifier model choice and feature set for learned contract selector: LogisticR | architecture |
| q09_item_020 | ___ | Milestone dispatch with incomplete slices: DB/ROADMAP desync | knowledge |
| q09_item_021 | ___ | LearnedSelector variant architecture for M022: Three variants sharing one Learne | architecture |
| q09_item_022 | ___ | Volume planner (VolumeSelector) is strictly dominated by kelly at current N -- B | knowledge |
| q09_item_023 | ___ | GO/NO-GO scorecard: state all criteria and thresholds before any data is visible | knowledge |
| q09_item_024 | ___ | Dispatch gate enforcement model for remote runs (GCP and server-a): Hard-block ext | infrastructure |
| q09_item_025 | ___ | Hard constraint: every milestone plan must increase expected trades/year above t | methodology |
| q09_item_026 | ___ | Seller HJB fires in buyer-losing states (D063) | knowledge |
| q09_item_027 | ___ | M022: server-a-dispatched walk-forward runs survive SSH disconnect, take ~60-90 mi | knowledge |
| q09_item_028 | ___ | Living dispatch runbook policy: update after every dispatch session: Create docs | operations |
| q09_item_029 | ___ | New milestones for survival analysis and Bayesian optimization: Two new mileston | strategy |

## q10: whats the shortest path to goal for this project based on your reading of everything in this directory?
*Search terms: shortest path goal remaining work critical path*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q10_item_000 | ___ | Optimizing p and W independently of N has uniformly failed D097 across 25+ miles | knowledge |
| q10_item_001 | ___ | chain_price_pct and min_ask were no-ops in argmax path prior to M034 S02 | knowledge |
| q10_item_002 | ___ | How to fix the E3 dead-code bug where --dte-lo on argmax planner was silently ig | bugfix |
| q10_item_003 | ___ | Anti-overfitting as a mandatory design principle for M022 (Learned Contract Sele | methodology |
| q10_item_004 | ___ | Whether to add DTE routing (MultiConfigScorer + DTERouter) to milestone plans: D | strategy |
| q10_item_005 | ___ | [M014] Milestone M014 | milestone |
| q10_item_006 | ___ | [M018] Milestone M018 | milestone |
| q10_item_007 | ___ | Docker: two independent build paths | knowledge |
| q10_item_008 | ___ | M018 is the shortest path to viability; M015 is deprioritized (cross-milestone d | knowledge |
| q10_item_009 | ___ | Dual-engine (call+put) walk-forward verdict and configuration forward path: All  | strategy |
| q10_item_010 | ___ | $100K vs $5K capital: trade paths differ, not just return denominators | knowledge |
| q10_item_011 | ___ | Conformal sweep: local DB (110 rows) is insufficient for 12-fold walk-forward; u | knowledge |
| q10_item_012 | ___ | D183: Kelly family is the only viable path -- all 26 non-kelly approaches are de | knowledge |
| q10_item_013 | ___ | gcloud storage ls returns full paths; use fnmatch for client-side glob | knowledge |
| q10_item_014 | ___ | [M027] Milestone M027 | milestone |
| q10_item_015 | ___ | hold_mode=expiry vs hold_mode=fixed: critical difference | knowledge |
| q10_item_016 | ___ | Archon: SSH exec channel can break while transport/auth remains functional (port | knowledge |
| q10_item_017 | ___ | [M026] Milestone M026 | milestone |
| q10_item_018 | ___ | [M015] Milestone M015 | milestone |
| q10_item_019 | ___ | Whether M026-eq3jt1 is gated on M027-lelhcb completion: Remove the M027 dependen | strategy |
| q10_item_020 | ___ | Signal model is working; opportunity set is the constraint | knowledge |
| q10_item_021 | ___ | Deprioritize argmax parametric tuning: Deprioritize delta floors, DTE floors, al | strategy |
| q10_item_022 | ___ | D097 walk-forward verdict for highvol fixed-family (highvol_strict and highvol)  | strategy |
| q10_item_023 | ___ | Starting capital as a strategy lever: Starting capital ($5K vs $100K) is a strat | strategy |
| q10_item_024 | ___ | [M025] Milestone M025 | milestone |
| q10_item_025 | ___ | All new pipeline components must have integration tests covering happy path + at | knowledge |
| q10_item_026 | ___ | How to resolve split src/ packages between project-a and project-b: Symlink | architecture |
| q10_item_027 | ___ | Strategic pivot: test no-model mechanical baseline before any further ML develop | strategy |

## q11: please restore the session context, my pc just crashed and i lost everything
*Search terms: restore session context crash recovery previous work*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q11_item_000 | ___ | M030 S01: kelly-d10-dte20 ruin year is 2018, not 2016 (confirmed via compound NA | knowledge |
| q11_item_001 | ___ | How to evaluate strategy performance across time: Walk-forward per-year fold eva | backtesting |
| q11_item_002 | ___ | M028: Multi-leg (K>1) shows volume recovery but not profitability recovery in 20 | knowledge |
| q11_item_003 | ___ | M030 S01: live-trading readiness requires both D097 AND compound-NAV check (quan | knowledge |
| q11_item_004 | ___ | [M028] Milestone M028 | milestone |
| q11_item_005 | ___ | Whether the kelly union coverage test is needed: Kelly-d10 and kelly-dte45 union | strategy |
| q11_item_006 | ___ | Strategy objective framing in CLAUDE.md project description: Maximum PnL growth  | strategy |
| q11_item_007 | ___ | Whether to implement an adaptive minimum-N floor that relaxes pipeline gates whe | strategy |
| q11_item_008 | ___ | INV-2 invariant deadline for exit-after-expiry validation: Allow exit up to firs | validation |
| q11_item_009 | ___ | Put intrinsic exit pricing bug impact assessment: All GCP backtest put PnL is in | backtesting |
| q11_item_010 | ___ | [M027] Milestone M027 | milestone |
| q11_item_011 | ___ | GCS has duplicate results from prior sessions -- always collect by exact instanc | knowledge |
| q11_item_012 | ___ | Archon deploy gate is session-scoped: cannot be satisfied across SSH sessions | knowledge |
| q11_item_013 | ___ | Crash-start gate for put eligibility: Remove crash-start gate for put selection. | strategy |
| q11_item_014 | ___ | Whether D097 is sufficient to declare live-trading readiness: D097 with $5K capi | methodology |
| q11_item_015 | ___ | Spike research findings must land in KNOWLEDGE.md, DECISIONS.md, or milestone CO | knowledge |
| q11_item_016 | ___ | GCP: collect per-fold data from live VMs when session expires before VM terminat | knowledge |
| q11_item_017 | ___ | GBM iv_sigma_floor_mult is available but likely not the crash-recovery lever | knowledge |
| q11_item_018 | ___ | [M006] Detector Utilization + Hypothesis Testing | milestone |
| q11_item_019 | ___ | M030 S02: VIX gate ablation falsifies N-starvation hypothesis as root cause of w | knowledge |
| q11_item_020 | ___ | M030 S04: Combined GO-NO-GO verdict pattern -- dual gate (D097 + sequential NAV) | knowledge |
| q11_item_021 | ___ | Inverted recovery signal works for puts at 20-60d; direct decline better at 90d | knowledge |
| q11_item_022 | ___ | Living dispatch runbook policy: update after every dispatch session: Create docs | operations |
| q11_item_023 | ___ | Root cause of kelly's 4 wipeout years: The 4 winnable wipeout years (2016/2017/2 | strategy |
| q11_item_024 | ___ | [M030] Milestone M030 | milestone |
| q11_item_025 | ___ | Dispatch-gate blocks gcp_dispatch.py when image_built not satisfied in current s | knowledge |
| q11_item_026 | ___ | Signal model is working; opportunity set is the constraint | knowledge |
| q11_item_027 | ___ | Whether to allow async_bash and await_job for background command execution: BANN | tooling |
| q11_item_028 | ___ | GCP dispatch: closer agent must complete incomplete dispatcher work | knowledge |
| q11_item_029 | ___ | Put signal model approach: For initial put-buying implementation, use inverted r | signal-model |

## q12: how does the fill model work?
*Search terms: fill model slippage mechanics how it works*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q12_item_000 | ___ | [M021] Milestone M021 | milestone |
| q12_item_001 | ___ | Clarification on D118: fill model is not an artificial filter: Fill model illiqu | architecture |
| q12_item_002 | ___ | Fill model slippage threshold setting (signal_15pct.yaml config): HOLD at 20% de | strategy |
| q12_item_003 | ___ | M032: Bookmaker fill rate is 10% at slippage_reject_pct=0.50 — the binding const | knowledge |
| q12_item_004 | ___ | How to evaluate strategy performance during paper trading and live deployment: A | methodology |
| q12_item_005 | ___ | Revise D118 to allow DTE constraints informed by data (M021 recall finding): D11 | architecture |
| q12_item_006 | ___ | M032: High-VIX years have LOWEST fill rates — wider spreads cause more slippage  | knowledge |
| q12_item_007 | ___ | Spike34 mechanical result (8/13) does not survive real pipeline -- hold_tracker  | knowledge |
| q12_item_008 | ___ | [M015] Milestone M015 | milestone |
| q12_item_009 | ___ | Whether to add volume-dependent market impact to the fill model: No change neede | fill-model |
| q12_item_010 | ___ | [M017] Milestone M017 | milestone |
| q12_item_011 | ___ | Spread quality gate: remove vs relax: Remove spread gate entirely (13 -> 98 tick | strategy |
| q12_item_012 | ___ | FillModel slippage gate: Keep SLIPPAGE_REJECT_PCT=0.10 with worst-case market im | backtesting |
| q12_item_013 | ___ | [M013] Milestone M013 | milestone |
| q12_item_014 | ___ | Mechanical selector is a valid negative control -- if it fails D097, the problem | knowledge |
| q12_item_015 | ___ | Signal model is working; opportunity set is the constraint | knowledge |
| q12_item_016 | ___ | [M022] Milestone M022 | milestone |
| q12_item_017 | ___ | Contract selection philosophy: rules-based filters vs learned selection: No hard | architecture |
| q12_item_018 | ___ | Walk-forward expanding window: later folds dominate runtime (M013 S03 timing) | knowledge |
| q12_item_019 | ___ | Strategic pivot: test no-model mechanical baseline before any further ML develop | strategy |
| q12_item_020 | ___ | Spread quality gate threshold for ticker expansion: Relax from 20% to 50% (13 ti | strategy |
| q12_item_021 | ___ | [M012] Milestone M012 | milestone |
| q12_item_022 | ___ | GCP dispatch: closer agent must complete incomplete dispatcher work | knowledge |
| q12_item_023 | ___ | Revised scope for M025-rvd7c5 (Multi-Contract Diversified Selection): 24-variant | strategy |
| q12_item_024 | ___ | Fill model slippage threshold setting (signal_15pct.yaml config): Hold at 20% de | strategy |
| q12_item_025 | ___ | BEP filter dominates fill rejections — slippage threshold is not the binding con | knowledge |
| q12_item_026 | ___ | Fill rejections are 100% slippage for argmax (slippage_reject_pct=0.50, 2010-202 | knowledge |

## q13: explain to me the full pipeline end to end, how each component works, what each component ingests and outputs to the next stage
*Search terms: full pipeline end to end components ingest output stages*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q13_item_000 | ___ | [M024] Milestone M024 | milestone |
| q13_item_001 | ___ | M015: cast(float, sklearn roc_auc_score(...)) is the correct pyright strict patt | knowledge |
| q13_item_002 | ___ | Where to insert the game-theoretic decision layer milestone in the M011-M016 roa | architecture |
| q13_item_003 | ___ | GCP walk-forward: GCS upload is all-or-nothing at script end -- per-fold progres | knowledge |
| q13_item_004 | ___ | Whether to add DTE routing (MultiConfigScorer + DTERouter) to milestone plans: D | strategy |
| q13_item_005 | ___ | Walk-forward fold directories use year names (fold_2013..fold_2025), not zero-pa | knowledge |
| q13_item_006 | ___ | Serial port output as partial results fallback for running GCP VMs | knowledge |
| q13_item_007 | ___ | [M009] Milestone M009 | milestone |
| q13_item_008 | ___ | [M022] Milestone M022 | milestone |
| q13_item_009 | ___ | Revised scope for M025-f187ry (Conformal Prediction): 12 runs: best e4fhk8 class | strategy |
| q13_item_010 | ___ | exchange_calendars required for validate_backtest_output.py | knowledge |
| q13_item_011 | ___ | signal_score (LightGBM V2A output) does not predict option profitability (AUC=0. | knowledge |
| q13_item_012 | ___ | M018 is the shortest path to viability; M015 is deprioritized (cross-milestone d | knowledge |
| q13_item_013 | ___ | Contract selection philosophy: rules-based filters vs learned selection: No hard | architecture |
| q13_item_014 | ___ | Classifier model choice and feature set for learned contract selector: LogisticR | architecture |
| q13_item_015 | ___ | How to evaluate strategy performance across time: Walk-forward per-year fold eva | backtesting |
| q13_item_016 | ___ | Argmax deep-OTM objective suitability: Argmax E[return_on_premium] objective is  | strategy |
| q13_item_017 | ___ | Live Alpaca smoke test: three upstream data layer issues block full pipeline (M0 | knowledge |
| q13_item_018 | ___ | M015: Skip logic is mandatory for expanding-window walk-forward on sparse binary | knowledge |
| q13_item_019 | ___ | Optimizing p and W independently of N has uniformly failed D097 across 25+ miles | knowledge |
| q13_item_020 | ___ | Backtest runner writes output atomically at end | knowledge |
| q13_item_021 | ___ | --max-year / --end-year pattern for holdout-restricted walk-forward CV | knowledge |
| q13_item_022 | ___ | M015 S01: Delta (r=0.408) and log_entry_price (r=0.216) are strong contract-leve | knowledge |
| q13_item_023 | ___ | [M008] Milestone M008 | milestone |
| q13_item_024 | ___ | [M002] MCTS Objective Fix + Pipeline Intelligence | milestone |
| q13_item_025 | ___ | GCP serial port output: fold results are visible before result files upload to G | knowledge |
| q13_item_026 | ___ | [M015] Milestone M015 | milestone |
| q13_item_027 | ___ | M031: Config reproducibility requires full flag echo in dispatch matrices | knowledge |
| q13_item_028 | ___ | LightGBM probability outputs are not probabilities -- severe miscalibration conf | knowledge |
| q13_item_029 | ___ | M015: Naive delta baseline outperforms trained LGBM second-stage classifier (AUC | knowledge |
| q13_item_030 | ___ | M015 DEAD END: Contract-level features do not discriminate trade winners from lo | knowledge |
| q13_item_031 | ___ | All new pipeline components must have integration tests covering happy path + at | knowledge |
| q13_item_032 | ___ | validate_backtest_output.py on server-a requires .venv/bin/python3, not system pyt | knowledge |

## q14: tell me about the control flow for the paper trading agents
*Search terms: control flow paper trading agents execution loop*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q14_item_000 | ___ | Whether paper trading deployment (M036) should include puts alongside calls: Cal | strategy |
| q14_item_001 | ___ | Planning agents must follow accumulated research and discussions, starting with  | methodology |
| q14_item_002 | ___ | Hard constraint: every milestone plan must increase expected trades/year above t | methodology |
| q14_item_003 | ___ | How to fetch underlying stock price on Alpaca free-tier paper trading: SIP->IEX  | data-source |
| q14_item_004 | ___ | [M031] Milestone M031 | milestone |
| q14_item_005 | ___ | Alpaca SIP feed returns 403 on free-tier paper accounts -- use IEX fallback (D20 | knowledge |
| q14_item_006 | ___ | Hold-to-expiry and sizing are open research questions: Neither locked. Hold-to-e | architecture |
| q14_item_007 | ___ | Whether Alpaca free-tier paper trading provides option Greeks for chain_adapter. | data-source |
| q14_item_008 | ___ | Execution fidelity gap: research findings must be verified as actually incorpora | methodology |
| q14_item_009 | ___ | Strategy objective framing in CLAUDE.md project description: Maximum PnL growth  | strategy |
| q14_item_010 | ___ | scripts/paper_trade.py must load .env via python-dotenv at startup | knowledge |
| q14_item_011 | ___ | [M029] Milestone M029 | milestone |
| q14_item_012 | ___ | Permanent settlement: calls and puts are equal citizens; problem is detector uti | strategy |
| q14_item_013 | ___ | Mechanical selector is a valid negative control -- if it fails D097, the problem | knowledge |
| q14_item_014 | ___ | Whether the agent should raise questions about call vs put inclusion in the stra | agent behavior |
| q14_item_015 | ___ | Production config for paper trading deployment: Config B sigprob-035: model=none | strategy |
| q14_item_016 | ___ | Clarification of D073 "equal citizens": does equal mean identical config?: Equal | strategy |
| q14_item_017 | ___ | How to evaluate strategy performance during paper trading and live deployment: A | methodology |
| q14_item_018 | ___ | GCP dispatch: closer agent must complete incomplete dispatcher work | knowledge |
| q14_item_019 | ___ | How the agent should respond to direct user instructions: Execute exactly what t | agent behavior |
| q14_item_020 | ___ | What is the correct optimization target for the D097 walk-forward criterion?: Ma | strategy |
| q14_item_021 | ___ | M031: Pre-execution research checklist is mandatory (D194, D195) | knowledge |
| q14_item_022 | ___ | Primary D097 prediction metric: N*p vs N*p*W: Replace N*p*W with N*p (expected w | strategy |
| q14_item_023 | ___ | Assessment of meta-decision overfitting to walk-forward validation set: Meta-dec | strategy |
| q14_item_024 | ___ | Whether the N funnel gates or input event volume is the binding constraint on tr | strategy |
| q14_item_025 | ___ | Exit rules architecture: 11 pluggable rules, 4 groups. DYNAMIC_EXIT_RULES frozen | strategy |
| q14_item_026 | ___ | Whether Config B is ready for live deployment of $5,000: CONDITIONAL NO-GO. Pape | methodology |
| q14_item_027 | ___ | Root cause of kelly's 4 wipeout years: The 4 winnable wipeout years (2016/2017/2 | strategy |

## q15: what is the difference between the paper trading agent configs and why are they in place?
*Search terms: paper trading agent configs differences configurations why*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q15_item_000 | ___ | Assessment of meta-decision overfitting to walk-forward validation set: Meta-dec | strategy |
| q15_item_001 | ___ | Live Alpaca smoke test: three upstream data layer issues block full pipeline (M0 | knowledge |
| q15_item_002 | ___ | Whether any put-side strategy is viable given three complete option-level univer | strategy |
| q15_item_003 | ___ | Strategic direction after cross-config dual-matrix diagnostic (31 configs, 25+ m | strategy |
| q15_item_004 | ___ | $100K vs $5K capital: trade paths differ, not just return denominators | knowledge |
| q15_item_005 | ___ | Whether LightGBM model improves walk-forward D097 results vs model=none baseline | strategy |
| q15_item_006 | ___ | Production config for paper trading deployment: Config B sigprob-035: model=none | strategy |
| q15_item_007 | ___ | How to evaluate strategy performance across time: Walk-forward per-year fold eva | backtesting |
| q15_item_008 | ___ | [M036] Milestone M036 | milestone |
| q15_item_009 | ___ | Dual-engine (call+put) walk-forward verdict and configuration forward path: All  | strategy |
| q15_item_010 | ___ | 4 signal model configs selected for DTE routing: 5d/10% (short), 10d/20% (medium | configuration |
| q15_item_011 | ___ | scripts/paper_trade.py must load .env via python-dotenv at startup | knowledge |
| q15_item_012 | ___ | How to evaluate strategy performance during paper trading and live deployment: A | methodology |
| q15_item_013 | ___ | Whether Alpaca free-tier paper trading provides option Greeks for chain_adapter. | data-source |
| q15_item_014 | ___ | M023: Archon summary.json echoes model_config.target_pct as default (0.10) even  | knowledge |
| q15_item_015 | ___ | [M014] Milestone M014 | milestone |
| q15_item_016 | ___ | trades.json schema: open-leg vs close-leg entries differ by key set | knowledge |
| q15_item_017 | ___ | Whether Config B is ready for live deployment of $5,000: CONDITIONAL NO-GO. Pape | methodology |
| q15_item_018 | ___ | Clarification of D073 "equal citizens": does equal mean identical config?: Equal | strategy |
| q15_item_019 | ___ | Which config to use going forward: R12 (0.03/60d/0.1) or holdout-derived (0.05/9 | configuration |
| q15_item_020 | ___ | Whether paper trading deployment (M036) should include puts alongside calls: Cal | strategy |
| q15_item_021 | ___ | Permanent settlement: calls and puts are equal citizens; problem is detector uti | strategy |
| q15_item_022 | ___ | Priority hypothesis for M006: split-config argmax with per-direction hold/target | strategy |
| q15_item_023 | ___ | Whether the agent should raise questions about call vs put inclusion in the stra | agent behavior |
| q15_item_024 | ___ | How to fetch underlying stock price on Alpaca free-tier paper trading: SIP->IEX  | data-source |

## q16: what were some failed experiments that lead to our current project state?
*Search terms: failed experiments rejected approaches what didnt work*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q16_item_000 | ___ | [M021] Milestone M021 | milestone |
| q16_item_001 | ___ | get_fill_rejection_reason() is a zero-overhead probe for diagnosis only | knowledge |
| q16_item_002 | ___ | Contract selection philosophy: rules-based filters vs learned selection: No hard | architecture |
| q16_item_003 | ___ | What role should N × p × W play in config evaluation?: Use N×p×W as a lower-boun | strategy |
| q16_item_004 | ___ | D097 walk-forward verdict for Thompson Sampling bandit contract selector (M024): | evaluation |
| q16_item_005 | ___ | Primary D097 prediction metric: N*p vs N*p*W: Replace N*p*W with N*p (expected w | strategy |
| q16_item_006 | ___ | Planning agents must follow accumulated research and discussions, starting with  | methodology |
| q16_item_007 | ___ | D097 prediction: N*p (expected winners/year) is strictly better than N*p*W (spik | knowledge |
| q16_item_008 | ___ | Hard constraint: every milestone plan must increase expected trades/year above t | methodology |
| q16_item_009 | ___ | Clarification on D118: fill model is not an artificial filter: Fill model illiqu | architecture |
| q16_item_010 | ___ | M030 S04: Combined GO-NO-GO verdict pattern -- dual gate (D097 + sequential NAV) | knowledge |
| q16_item_011 | ___ | Inverted recovery signal works for puts at 20-60d; direct decline better at 90d | knowledge |
| q16_item_012 | ___ | Compute target for all backtests and experiments: GCP is primary for all backtes | infrastructure |
| q16_item_013 | ___ | BEP filter dominates fill rejections — slippage threshold is not the binding con | knowledge |
| q16_item_014 | ___ | GCP dispatch: closer agent must complete incomplete dispatcher work | knowledge |
| q16_item_015 | ___ | [M012] Milestone M012 | milestone |
| q16_item_016 | ___ | Archon: scp fails -- use ssh cat pipe | knowledge |
| q16_item_017 | ___ | Fill rejections are 100% slippage for argmax (slippage_reject_pct=0.50, 2010-202 | knowledge |
| q16_item_018 | ___ | Whether D120 (server-a is overflow only) applies to M032 S01 2-fold smoke test: Ex | infrastructure |
| q16_item_019 | ___ | M032: High-VIX years have LOWEST fill rates — wider spreads cause more slippage  | knowledge |
| q16_item_020 | ___ | How to evaluate strategy performance across time: Walk-forward per-year fold eva | backtesting |
| q16_item_021 | ___ | Strategy objective framing in CLAUDE.md project description: Maximum PnL growth  | strategy |
| q16_item_022 | ___ | Signal model is working; opportunity set is the constraint | knowledge |
| q16_item_023 | ___ | Zero-winner years (2016/2020/2022) are contract selection failures, not winner s | strategy |
| q16_item_024 | ___ | Strategic direction after cross-config dual-matrix diagnostic (31 configs, 25+ m | strategy |
| q16_item_025 | ___ | [M027] Milestone M027 | milestone |
| q16_item_026 | ___ | D183: Kelly family is the only viable path -- all 26 non-kelly approaches are de | knowledge |

## q17: what got reversed?
*Search terms: reversed superseded changed decisions overridden*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q17_item_000 | ___ | How to resolve split src/ packages between project-a and project-b: Symlink | architecture |
| q17_item_001 | ___ | Spike research findings must land in KNOWLEDGE.md, DECISIONS.md, or milestone CO | knowledge |
| q17_item_002 | ___ | D097 walk-forward verdict for Thompson Sampling bandit contract selector (M024): | evaluation |
| q17_item_003 | ___ | Assessment of meta-decision overfitting to walk-forward validation set: Meta-dec | strategy |
| q17_item_004 | ___ | Which event stream to use for M024 walk-forward evaluation: Evaluate bandit on R | evaluation |
| q17_item_005 | ___ | Execution priority for 4 milestones after M024-60hkjc, informed by M023-vyt1ni k | strategy |
| q17_item_006 | ___ | SDT framework gaps to address: (1) Wire EV integrator to threshold decision, (2) | strategy |
| q17_item_007 | ___ | Dispatch-gate HEAD!=image-tag bypass: non-Docker changes only | knowledge |
| q17_item_008 | ___ | [M024] Milestone M024 | milestone |
| q17_item_009 | ___ | pyright strict: tree_export must be initialized before planner branches to avoid | knowledge |
| q17_item_010 | ___ | Python regular packages block cross-project module resolution (D054) | knowledge |
| q17_item_011 | ___ | Docker image/deploy race: if code changes after build, GCP sees old function sig | knowledge |
| q17_item_012 | ___ | Revised scope for M024-b07iwu (LS-MC/HJB Exit Retargeting): 8 runs: HJB + LS-MC  | strategy |
| q17_item_013 | ___ | Whether to train HJB on all 508 trajectories or only the 65 with DTE >= 45 at en | exit-algorithm |
| q17_item_014 | ___ | M004 (Put-Buying Engine) milestone status: Superseded. The dual call+put engine  | strategy |
| q17_item_015 | ___ | Revised scope for M024-60hkjc (Contextual Bandit): 4 runs: LinUCB + Thompson Sam | strategy |
| q17_item_016 | ___ | Decouple project-a from project-b symlinks: Copy all 5 project-b module | architecture |
| q17_item_017 | ___ | deploy_server.sh does not sync docker/ directory — Dockerfile changes require ma | knowledge |
| q17_item_018 | ___ | Execution order and gate policy for queued milestones after M023-vyt1ni: Run all | strategy |
| q17_item_019 | ___ | M026: New planner must be added to the decision_log write condition in run_signa | knowledge |
| q17_item_020 | ___ | Mean reversion dominates post-decline OTM option outcomes | knowledge |
| q17_item_021 | ___ | Which contextual bandit algorithm to use for M024 contract selection: Thompson S | algorithm |
| q17_item_022 | ___ | Planning agents must follow accumulated research and discussions, starting with  | methodology |
| q17_item_023 | ___ | [M033] Milestone M033 | milestone |
| q17_item_024 | ___ | M024: Bandit logs every decision to decision_log (not every 10th like argmax/MCT | knowledge |
| q17_item_025 | ___ | New milestones for survival analysis and Bayesian optimization: Two new mileston | strategy |
| q17_item_026 | ___ | D090: project-b modules are now copied into project-a (supersedes symlink e | knowledge |
| q17_item_027 | ___ | Where to insert the game-theoretic decision layer milestone in the M011-M016 roa | architecture |
| q17_item_028 | ___ | Whether to add volume-dependent market impact to the fill model: No change neede | fill-model |
| q17_item_029 | ___ | Arm discretization for M024 bandit contract selection: 9 arms: 3 delta buckets x | algorithm |
| q17_item_030 | ___ | Walk-forward CV is clean but meta-decisions are contaminated (D067) | knowledge |
| q17_item_031 | ___ | HJB call-side retargeting is BROADLY NEGATIVE: -3.08pp aggregate, 97.5% degenera | knowledge |

## q18: how does the GBM model affect the argmax selector downstream?
*Search terms: GBM model argmax selector downstream signal interaction*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q18_item_000 | ___ | M022 best learned contract selector variant: V3 (classifier pre-filter threshold | strategy |
| q18_item_001 | ___ | Revised scope for M025-rvd7c5 (Multi-Contract Diversified Selection): 24-variant | strategy |
| q18_item_002 | ___ | M030 S03: GBM iv_sigma_floor_mult shifts kelly selection ITM (not OTM) in low-vo | knowledge |
| q18_item_003 | ___ | Updated scope for M025-rvd7c5 incorporating posterior predictive GBM variant (ex | strategy |
| q18_item_004 | ___ | How to incorporate 6 research-identified hypotheses from DOWNSTREAM-MODULE-TRADE | strategy |
| q18_item_005 | ___ | Signal model configuration for production use: LightGBM + V2 (57 features) + 15% | signal-model |
| q18_item_006 | ___ | [M001] MCTS Contract Selection Planner | milestone |
| q18_item_007 | ___ | Anti-overfitting as a mandatory design principle for M022 (Learned Contract Sele | methodology |
| q18_item_008 | ___ | CORRECTION: Wipeout years (2018, 2021, 2022) are SELECTOR failures, not regime f | knowledge |
| q18_item_009 | ___ | Revise D118 to allow DTE constraints informed by data (M021 recall finding): D11 | architecture |
| q18_item_010 | ___ | [M022] Milestone M022 | milestone |
| q18_item_011 | ___ | Classifier model choice and feature set for learned contract selector: LogisticR | architecture |
| q18_item_012 | ___ | M001_OTM_baseline call-only E[V] is -0.08 (margin=-1.7pp), NOT +2.854 | knowledge |
| q18_item_013 | ___ | Research direction: reframe profitability problem as detection rate (recall) on  | strategy |
| q18_item_014 | ___ | Revised scope for M024-b07iwu (LS-MC/HJB Exit Retargeting): 8 runs: HJB + LS-MC  | strategy |
| q18_item_015 | ___ | Contract-level AUC vs group-level AUC for contract selector evaluation | knowledge |
| q18_item_016 | ___ | Crash-start gate for put eligibility: Remove crash-start gate for put selection. | strategy |
| q18_item_017 | ___ | Priority hypothesis for M006: split-config argmax with per-direction hold/target | strategy |
| q18_item_018 | ___ | Revised scope for M025-f187ry (Conformal Prediction): 12 runs: best e4fhk8 class | strategy |
| q18_item_019 | ___ | pct_equity 0.5% dominates structurally for asymmetric payoffs | knowledge |
| q18_item_020 | ___ | M022: Learned contract selector is CONCENTRATED -- same verdict as argmax | knowledge |
| q18_item_021 | ___ | [M016] Milestone M016 | milestone |
| q18_item_022 | ___ | Adopt dual-matrix decision framework (confusion matrix x payoff matrix) as diagn | architecture |
| q18_item_023 | ___ | Citation requirement for all project document assertions: All assertions in proj | methodology |
| q18_item_024 | ___ | GBM iv_sigma_floor_mult is available but likely not the crash-recovery lever | knowledge |
| q18_item_025 | ___ | LearnedSelector variant architecture for M022: Three variants sharing one Learne | architecture |
| q18_item_026 | ___ | Updated scope for M025-e4fhk8 incorporating RRF and payoff-weighted loss (supers | strategy |
| q18_item_027 | ___ | Put intrinsic exit pricing bug impact assessment: All GCP backtest put PnL is in | backtesting |
| q18_item_028 | ___ | Signal model is working; opportunity set is the constraint | knowledge |
| q18_item_029 | ___ | Put signal model approach: For initial put-buying implementation, use inverted r | signal-model |
| q18_item_030 | ___ | M018: KNOWLEDGE.md M001 OTM baseline E[V]=+2.854 is bothsides (calls+puts), not  | knowledge |
| q18_item_031 | ___ | GBM drift calibration target: Drift mu set so that P(S_T >= 1.15*S_0) = signal_p | generative-model |

## q19: we ran a config or a few configs that got over a million USD pnl can you find that data?
*Search terms: million USD pnl config high performance backtest results*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q19_item_000 | ___ | Strategy objective framing in CLAUDE.md project description: Maximum PnL growth  | strategy |
| q19_item_001 | ___ | walk_forward_backtest.py does not accept --puts-mode flag; use YAML config inste | knowledge |
| q19_item_002 | ___ | Primary evaluation metrics for lottery-ticket option strategies: D097 per-year p | strategy |
| q19_item_003 | ___ | scan_universe.py: batch exit price lookup is essential for performance | knowledge |
| q19_item_004 | ___ | walk_forward_backtest.py does not support --put-config (M014 S01 finding) | knowledge |
| q19_item_005 | ___ | Fixed OTM planner is dead -- only argmax survives | knowledge |
| q19_item_006 | ___ | How to incorporate 6 research-identified hypotheses from DOWNSTREAM-MODULE-TRADE | strategy |
| q19_item_007 | ___ | Citation requirement for all project document assertions: All assertions in proj | methodology |
| q19_item_008 | ___ | M032: High-VIX years have LOWEST fill rates — wider spreads cause more slippage  | knowledge |
| q19_item_009 | ___ | D097 walk-forward verdict for highvol fixed-family (highvol_strict and highvol)  | strategy |
| q19_item_010 | ___ | Exit pricing bug: runner never called handle_expiry(), giving phantom post-expir | backtesting |
| q19_item_011 | ___ | Classifier model choice and feature set for learned contract selector: LogisticR | architecture |
| q19_item_012 | ___ | Anti-overfitting as a mandatory design principle for M022 (Learned Contract Sele | methodology |
| q19_item_013 | ___ | How to evaluate strategy performance across time: Walk-forward per-year fold eva | backtesting |
| q19_item_014 | ___ | D097 profitable-year criterion is return_pct > 0, NOT total_pnl > 0 -- these can | knowledge |
| q19_item_015 | ___ | Which config to use going forward: R12 (0.03/60d/0.1) or holdout-derived (0.05/9 | configuration |
| q19_item_016 | ___ | walk_forward_backtest.py support for dual-engine (--put-config) runs: walk_forwa | architecture |
| q19_item_017 | ___ | How to report strategy returns in all project artifacts: Always report returns i | reporting |
| q19_item_018 | ___ | Put intrinsic exit pricing bug impact assessment: All GCP backtest put PnL is in | backtesting |
| q19_item_019 | ___ | Edge ranking as hard filter performs adverse selection on lottery-ticket strateg | knowledge |
| q19_item_020 | ___ | Enforce D097 walk-forward per-year backtesting protocol as a standing project ru | methodology |
| q19_item_021 | ___ | Dual-engine (call+put) walk-forward verdict and configuration forward path: All  | strategy |
| q19_item_022 | ___ | Fill model slippage threshold setting (signal_15pct.yaml config): Hold at 20% de | strategy |
| q19_item_023 | ___ | Verdict criteria for S03 hypothesis evaluation in analyze_s03_results.py: PASS v | strategy |
| q19_item_024 | ___ | What is the starting bankroll for all backtests and live trading simulations?: $ | strategy |
| q19_item_025 | ___ | Ticker exclusion framework for backtest universe management: Three-tier framewor | strategy |
| q19_item_026 | ___ | fixed-dte45 is the first walk-forward PnL-positive config: +$51,656 across 13 fo | knowledge |

## q20: hang on earlier we had 4 paper trading agents now theres 8 what happened?
*Search terms: paper trading agents four eight expanded added new why*

| # | Label | Content | Category |
|---|-------|---------|----------|
| q20_item_000 | ___ | Whether Alpaca free-tier paper trading provides option Greeks for chain_adapter. | data-source |
| q20_item_001 | ___ | How to evaluate strategy performance during paper trading and live deployment: A | methodology |
| q20_item_002 | ___ | scripts/paper_trade.py must load .env via python-dotenv at startup | knowledge |
| q20_item_003 | ___ | How to evaluate strategy performance across time: Walk-forward per-year fold eva | backtesting |
| q20_item_004 | ___ | New milestones for survival analysis and Bayesian optimization: Two new mileston | strategy |
| q20_item_005 | ___ | M026: New planner must be added to the decision_log write condition in run_signa | knowledge |
| q20_item_006 | ___ | M015: Skip logic is mandatory for expanding-window walk-forward on sparse binary | knowledge |
| q20_item_007 | ___ | GCP dispatch: closer agent must complete incomplete dispatcher work | knowledge |
| q20_item_008 | ___ | Permanent settlement: calls and puts are equal citizens; problem is detector uti | strategy |
| q20_item_009 | ___ | How to fetch underlying stock price on Alpaca free-tier paper trading: SIP->IEX  | data-source |
| q20_item_010 | ___ | Whether paper trading deployment (M036) should include puts alongside calls: Cal | strategy |
| q20_item_011 | ___ | Clarification of D073 "equal citizens": does equal mean identical config?: Equal | strategy |
| q20_item_012 | ___ | Alpaca free-tier indicative feed provides full Greeks at 100% coverage (D206) | knowledge |
| q20_item_013 | ___ | Dual-engine (call+put) walk-forward verdict and configuration forward path: All  | strategy |
| q20_item_014 | ___ | Whether the agent should raise questions about call vs put inclusion in the stra | agent behavior |
| q20_item_015 | ___ | Feature discriminability pattern: expanding-window logistic regression per featu | knowledge |
| q20_item_016 | ___ | Whether any put-side strategy is viable given three complete option-level univer | strategy |
| q20_item_017 | ___ | Calls and puts are permanently equal citizens (D073) | knowledge |
| q20_item_018 | ___ | [M014] Milestone M014 | milestone |
| q20_item_019 | ___ | [M026] Milestone M026 | milestone |
| q20_item_020 | ___ | Live Alpaca smoke test: three upstream data layer issues block full pipeline (M0 | knowledge |
| q20_item_021 | ___ | [M036] Milestone M036 | milestone |
| q20_item_022 | ___ | Whether D097 is sufficient to declare live-trading readiness: D097 with $5K capi | methodology |
| q20_item_023 | ___ | Walk-forward expanding window: later folds dominate runtime (M013 S03 timing) | knowledge |
| q20_item_024 | ___ | Priority hypothesis for M006: split-config argmax with per-direction hold/target | strategy |
| q20_item_025 | ___ | Whether Config B is ready for live deployment of $5,000: CONDITIONAL NO-GO. Pape | methodology |
| q20_item_026 | ___ | Hold-to-expiry and sizing are open research questions: Neither locked. Hold-to-e | architecture |
