# Experiment 53: Vocabulary Gap Prevalence Across Projects

**Date:** 2026-04-10
**Status:** Complete

## 1. Prevalence Summary

| Project | Directives | Corpus Size | Gaps | Gap Rate | HRR Bridgeable |
|---------|-----------|-------------|------|----------|----------------|
| project-a | 174 | 8178 | 66 | 37.9% | 65/66 |
| project-b | 2198 | 128941 | 718 | 32.7% | 718/718 |
| project-d | 63 | 4124 | 31 | 49.2% | 28/31 |
| project-c | 262 | 4072 | 72 | 27.5% | 72/72 |
| project-e | 624 | 26938 | 143 | 22.9% | 142/143 |
| **TOTAL** | **3321** | -- | **1030** | **31.0%** | **1025/1030 (100%)** |

## 2. Gap Categories (across all projects)

| Category | Count | % of Gaps |
|----------|-------|-----------|
| tool_ban | 121 | 12% |
| domain_jargon | 132 | 13% |
| cross_domain_constraint | 38 | 4% |
| implicit_rule | 83 | 8% |
| emphatic_prohibition | 301 | 29% |
| other | 355 | 34% |

## 3. Hypothesis Evaluation

**H1:** Gap prevalence >= 5% across projects: SUPPORTED (observed: 31.0%)

**H2:** Tool bans + domain jargon >= 50% of gaps: NOT SUPPORTED (observed: 25%)

**H3:** >= 80% of gaps are HRR-bridgeable: SUPPORTED (observed: 100%)

**H4:** Doc-rich projects have lower gap rates: NOT SUPPORTED (rich: 33.1%, light: 25.3%)

**Null hypothesis** (gap < 3%, HRR negligible): REJECTED (observed: 31.0%)

## 4. Conclusion

Vocabulary gap prevalence is 31.0%, well above the 10% threshold. HRR is essential infrastructure -- text methods alone leave a significant fraction of directives unreachable.

Of the 1030 vocabulary-gap directives, 1025 (100%) are HRR-bridgeable via co-location or topic overlap with text-reachable directives. This confirms HRR's mechanism: typed edges connect isolated beliefs to the reachable graph.

## 5. Per-Project Gap Details

### project-a

Showing 10 of 66 vocabulary-gap directives:

- **Directive:** "Dead approaches (do not re-propose): price filters, DTE floors >20, highvol gate,"
  - Source: `CLAUDE.md`
  - Category: emphatic_prohibition
  - Queries: ['time until option expires', 'days remaining on contract', 'option expiration window']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Do NOT test fixed OTM planner (dead per approaches registry)."
  - Source: `docs/TRIAGE-15-hypotheses.md`
  - Category: emphatic_prohibition
  - Queries: ['cheap option contract', 'out of money option', 'low probability bet']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Per-ticker PnL breakdown is mandatory for every S03 backtest. SPY = 418% of R12 PnL. Without per-ticker reporting, a sin"
  - Source: `docs/TRIAGE-15-hypotheses.md`
  - Category: domain_jargon
  - Queries: ['profit and loss', 'trading results', 'money made or lost']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Fold 2025 has been running on GCP VM alpha-m024-60hkjc-bandit-20260330-2229 for 16+ hours as of 2026-03-31 00:00 UTC. Pr"
  - Source: `docs/m024-verdict.md`
  - Category: emphatic_prohibition
  - Queries: ['evaluate strategy over time', 'test on rolling periods', 'sequential validation']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "IMPORTANT: Per D120, all backtest runs target GCP as primary compute. Server-A is overflow only."
  - Source: `docs/m014-s01-put-config-selection.md`
  - Category: domain_jargon
  - Queries: ['test strategy on historical data', 'simulate past trades', 'validate approach']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Rules-based exit: Sharpe 1.45. Trailing stop (829) and time exit (797) dominate over stop-loss (206) and take-profit (29"
  - Source: `docs/PRIOR_WORK.md`
  - Category: domain_jargon
  - Queries: ['risk-adjusted performance', 'return per unit risk', 'portfolio quality metric']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Rationale: A continuous BEP penalty in the Q-value risks collapsing MCTS to always pick the cheapest OTM (lowest BEP). B"
  - Source: `docs/DECISIONS-ARCHIVE.md`
  - Category: implicit_rule
  - Queries: ['cheap option contract', 'out of money option', 'low probability bet']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Rationale: Flags-based run entries omit --config and rely on gcp_startup.sh to prepend configs/signal_15pct.yaml. valida"
  - Source: `docs/DECISIONS-ARCHIVE.md`
  - Category: cross_domain_constraint
  - Queries: ['after completing work', 'state changed', 'new information available']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Rationale: H-HJB2 test showed seller SELL fires when buyer pnl median=-0.997 (seller winning = buyer losing). H-HJB3 con"
  - Source: `docs/DECISIONS-ARCHIVE.md`
  - Category: emphatic_prohibition
  - Queries: ['risk-adjusted performance', 'return per unit risk', 'portfolio quality metric']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "when self.cash < required (entry_price  100  qty). This is verified by unit test."
  - Source: `docs/CAPITAL-CORRECTION-AUDIT.md`
  - Category: other
  - Queries: ['ready to deploy code', 'finished implementing feature', 'preparing release']
  - HRR bridgeable: True
  - Low-confidence query: False

### project-b

Showing 10 of 718 vocabulary-gap directives:

- **Directive:** "IMPORTANT: Always build Docker images from server-a (ssh server-a bash -c '...'), not from the Mac."
  - Source: `CLAUDE.md`
  - Category: cross_domain_constraint
  - Queries: ['containerize application', 'build deployment image', 'isolate dependencies']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Deploy to server-b/server-a: Always develop on main. Deploy by running uv run python3 scripts/ops.py deploy [--host server-a] "
  - Source: `CLAUDE.md`
  - Category: tool_ban
  - Queries: ['manage Python packages', 'install dependencies', 'run scripts']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "For experiment dispatch: When dispatching experiments (via ops.py run, manual runs, or any orchestration), these gates r"
  - Source: `CLAUDE.md`
  - Category: domain_jargon
  - Queries: ['send job to compute', 'deploy to server', 'run remotely']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "These were reportedly written on a deploy/gcp branch that was never merged to main and no longer exists locally."
  - Source: `archive/historical/DATA-PIPELINE-STATUS.md`
  - Category: cross_domain_constraint
  - Queries: ['Google cloud computing', 'cloud server', 'remote compute']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Agent sees post-expiry, post-stop state."
  - Source: `archive/historical/agent-decision-flow.md`
  - Category: other
  - Queries: ['working on agent post-expiry post-stop', 'handling post-expiry post-stop sees task', 'approaching agent post-expiry problem']
  - HRR bridgeable: True
  - Low-confidence query: True

- **Directive:** "If it fails: Check YAML syntax (indentation), verify all required keys are present, ensure numeric values are in valid r"
  - Source: `archive/historical/USAGE.md`
  - Category: implicit_rule
  - Queries: ['about to ship code', 'completing a task', 'checking work before submission']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "--input (required): Input directory (backtest results)"
  - Source: `archive/historical/USAGE.md`
  - Category: domain_jargon
  - Queries: ['test strategy on historical data', 'simulate past trades', 'validate approach']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "--no-fail: Always exit 0 (report only, don't fail pipeline)"
  - Source: `archive/historical/USAGE.md`
  - Category: other
  - Queries: ['summarizing findings', 'presenting results', 'communicating status']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "deploy/server-b and deploy/server-a must be derived from the main (development) branch. Always develop on main, then push to"
  - Source: `archive/historical/key-memories.md`
  - Category: cross_domain_constraint
  - Queries: ['shipping to production', 'releasing code', 'pushing to server']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Prediction: This is the highest-risk progressive experiment. RE-ENCODE required (OBS 10->16)."
  - Source: `archive/historical/VnV_Audit.md`
  - Category: other
  - Queries: ['working on experiment highest-risk obs', 'handling highest-risk obs prediction task', 'approaching experiment highest-risk problem']
  - HRR bridgeable: True
  - Low-confidence query: True

### project-d

Showing 10 of 31 vocabulary-gap directives:

- **Directive:** "All fleet machines have SSH config aliases in ~/.ssh/config. Always use the alias. Never guess credentials, IPs, or keys"
  - Source: `CLAUDE.md`
  - Category: tool_ban
  - Queries: ['remote machine access', 'connect to server', 'run command remotely']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "If no UAT tests are found, report this clearly and stop. Do not fabricate test results."
  - Source: `.claude/agents/uat-test-runner.md`
  - Category: emphatic_prohibition
  - Queries: ['user acceptance testing', 'verify feature works for user', 'manual testing']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Do NOT modify test files. You are an executor, not a fixer. If tests fail, report the failure as-is."
  - Source: `.claude/agents/uat-test-runner.md`
  - Category: emphatic_prohibition
  - Queries: ['ready to deploy code', 'finished implementing feature', 'preparing release']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Never modify test files or source code. You execute and report. Period."
  - Source: `.claude/agents/uat-test-runner.md`
  - Category: other
  - Queries: ['ready to deploy code', 'finished implementing feature', 'preparing release']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Never fabricate results. If you cannot run a test, say so. If output is ambiguous, say so."
  - Source: `.claude/agents/uat-test-runner.md`
  - Category: implicit_rule
  - Queries: ['ready to deploy code', 'finished implementing feature', 'preparing release']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Report failures honestly and precisely. Do not minimize or editorialize failures. A fail is a fail."
  - Source: `.claude/agents/uat-test-runner.md`
  - Category: other
  - Queries: ['summarizing findings', 'presenting results', 'communicating status']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Flaky tests: If you suspect flakiness (test passes on retry), note this in the report but do not auto-retry unless the t"
  - Source: `.claude/agents/uat-test-runner.md`
  - Category: implicit_rule
  - Queries: ['ready to deploy code', 'finished implementing feature', 'preparing release']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "When the user asks you to remember something across sessions (e.g., "always use bun", "never auto-commit"), save it — no"
  - Source: `.claude/agents/uat-test-runner.md`
  - Category: other
  - Queries: ['saving code changes', 'recording progress', 'checkpointing work']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Never require human interaction during test execution"
  - Source: `.claude/agents/uat-cli-converter.md`
  - Category: other
  - Queries: ['ready to deploy code', 'finished implementing feature', 'preparing release']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Do not add co-authorship to any generated files"
  - Source: `.claude/agents/uat-cli-converter.md`
  - Category: other
  - Queries: ['working on add co-authorship files', 'handling co-authorship files generated task', 'approaching add co-authorship problem']
  - HRR bridgeable: True
  - Low-confidence query: True

### project-c

Showing 10 of 72 vocabulary-gap directives:

- **Directive:** "PR #249: ~6 months old, ~5 review cycles, peer-approved, never merged. Latest: full overhaul + 2-machine testing, Jose s"
  - Source: `.continue-here.md`
  - Category: other
  - Queries: ['merging pull request', 'approving code change', 'evaluating contribution']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "> Mar 11, 10:46 AM — Jose's response (git training condescension): Jose messaged in the PR support chat: "Hi Jonathan, t"
  - Source: `INCIDENT_LOG.md`
  - Category: tool_ban
  - Queries: ['ready to deploy code', 'finished implementing feature', 'preparing release']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "> Prior context: Jose had already established a mandatory 7-step developer environment setup on Confluence (see Incident"
  - Source: `INCIDENT_LOG.md`
  - Category: cross_domain_constraint
  - Queries: ['containerize application', 'build deployment image', 'isolate dependencies']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "> Jose never acknowledged that this situation validated the Docker proposal, nor did he acknowledge his mistake in aggre"
  - Source: `INCIDENT_LOG.md`
  - Category: tool_ban
  - Queries: ['containerize application', 'build deployment image', 'isolate dependencies']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "> - Meeting transcript available on work PC: C:/Users/v0404417/Documents/mtg transcript 3-4-2026.txt (UTF-8). Do not tra"
  - Source: `INCIDENT_LOG.md`
  - Category: emphatic_prohibition
  - Queries: ['human resources department', 'workplace complaint', 'employment issue']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "> Additionally, Jose authored a separate Confluence page ("Hands-on Training & Exam to get Writing Access to evtol_mbd r"
  - Source: `INCIDENT_LOG.md`
  - Category: implicit_rule
  - Queries: ['merging pull request', 'approving code change', 'evaluating contribution']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "> - Professional autonomy over my own development environment has been removed by a single team member whose authority t"
  - Source: `INCIDENT_LOG.md`
  - Category: tool_ban
  - Queries: ['build project', 'run task', 'compile code']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "> - 02-setup-page-steps1-4-vscode-git-ssh.jpg — Steps 1–4: mandatory VS Code, mandatory Git v2.41.0.3 ("to avoid issues "
  - Source: `INCIDENT_LOG.md`
  - Category: tool_ban
  - Queries: ['remote machine access', 'connect to server', 'run command remotely']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "> - evidence/new chat screenshot from march 5 2026/IMG_2706.HEIC — Jose's 1:56 AM message calling out Jonathan by name; "
  - Source: `INCIDENT_LOG.md`
  - Category: other
  - Queries: ['saving code changes', 'recording progress', 'checkpointing work']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "[ ] Meeting transcript on work PC: C:/Users/v0404417/Documents/mtg transcript 3-4-2026.txt (UTF-8) — do not transfer to "
  - Source: `INCIDENT_LOG.md`
  - Category: emphatic_prohibition
  - Queries: ['human resources department', 'workplace complaint', 'employment issue']
  - HRR bridgeable: True
  - Low-confidence query: False

### project-e

Showing 10 of 143 vocabulary-gap directives:

- **Directive:** "If no UAT tests are found, report this clearly and stop. Do not fabricate test results."
  - Source: `.claude/agents/uat-test-runner.md`
  - Category: emphatic_prohibition
  - Queries: ['user acceptance testing', 'verify feature works for user', 'manual testing']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Do NOT modify test files. You are an executor, not a fixer. If tests fail, report the failure as-is."
  - Source: `.claude/agents/uat-test-runner.md`
  - Category: emphatic_prohibition
  - Queries: ['ready to deploy code', 'finished implementing feature', 'preparing release']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Never modify test files or source code. You execute and report. Period."
  - Source: `.claude/agents/uat-test-runner.md`
  - Category: other
  - Queries: ['ready to deploy code', 'finished implementing feature', 'preparing release']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Never fabricate results. If you cannot run a test, say so. If output is ambiguous, say so."
  - Source: `.claude/agents/uat-test-runner.md`
  - Category: implicit_rule
  - Queries: ['ready to deploy code', 'finished implementing feature', 'preparing release']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Report failures honestly and precisely. Do not minimize or editorialize failures. A fail is a fail."
  - Source: `.claude/agents/uat-test-runner.md`
  - Category: other
  - Queries: ['summarizing findings', 'presenting results', 'communicating status']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Flaky tests: If you suspect flakiness (test passes on retry), note this in the report but do not auto-retry unless the t"
  - Source: `.claude/agents/uat-test-runner.md`
  - Category: implicit_rule
  - Queries: ['ready to deploy code', 'finished implementing feature', 'preparing release']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "When the user asks you to remember something across sessions (e.g., "always use bun", "never auto-commit"), save it — no"
  - Source: `.claude/agents/uat-test-runner.md`
  - Category: other
  - Queries: ['saving code changes', 'recording progress', 'checkpointing work']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Never require human interaction during test execution"
  - Source: `.claude/agents/uat-cli-converter.md`
  - Category: other
  - Queries: ['ready to deploy code', 'finished implementing feature', 'preparing release']
  - HRR bridgeable: True
  - Low-confidence query: False

- **Directive:** "Do not add co-authorship to any generated files"
  - Source: `.claude/agents/uat-cli-converter.md`
  - Category: other
  - Queries: ['working on add co-authorship files', 'handling co-authorship files generated task', 'approaching add co-authorship problem']
  - HRR bridgeable: True
  - Low-confidence query: True

- **Directive:** "Core Value: Surface matching Upwork jobs daily so Jonathan can review, flag, and get a draft proposal — no manual browsi"
  - Source: `.planning/REQUIREMENTS.md`
  - Category: other
  - Queries: ['merging pull request', 'approving code change', 'evaluating contribution']
  - HRR bridgeable: True
  - Low-confidence query: False

## 6. Methodology Notes

- Directives extracted via regex pattern matching on .md files (always/never/banned/must not/mandatory/etc.)
- Queries generated rule-based: tool purpose mappings, domain term translations, behavioral verb situation mappings
- FTS5 with porter stemming, OR-query, top-30 retrieval
- Text match: exact, substring, or >= 70% Jaccard word overlap
- No LLM calls used in any part of the pipeline
