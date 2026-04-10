# Exp 6 Cluster Audit: Verifying the 79% Claim

**Date:** 2026-04-09
**Purpose:** Review each override-to-cluster assignment for false matches.

## Methodology

For each override in each cluster, judge: does this override actually belong to this topic?
- **YES** = correctly classified
- **NO** = false match (keyword hit on unrelated content)
- **PARTIAL** = related but not the core topic

## Audit Results

### dispatch_gate (claimed 13, actual 7)

| # | Date | Override | Verdict | Correct Topic |
|---|------|---------|---------|---------------|
| 1 | 03-26 | "make sure GCP build is fully up to date before dispatching" | YES | dispatch_gate |
| 2 | 03-26 | "archon for overflow, GCP is primary compute" | NO | gcp_primary |
| 3 | 03-27 | "always satisfy the deploy gate" | YES | dispatch_gate |
| 4 | 03-27 | "copy from optimus-prime directly into alpha-seek" | NO | code_organization (new topic) |
| 5 | 03-27 | "please report returns in annualized terms" | NO | reporting_format (new topic) |
| 6 | 03-27 | "follow exactly what the dispatch gate requires" | YES | dispatch_gate |
| 7 | 03-29 | "do not implement artificial contract filters" | NO | no_artificial_filters |
| 8 | 03-29 | "illiquid option filter is fine" | NO | no_artificial_filters |
| 9 | 03-29 | "archon is overflow only, do not run tests directly" | PARTIAL | gcp_primary / dispatch_gate overlap |
| 10 | 03-30 | "leave enough headroom when dispatching" | YES | dispatch_gate |
| 11 | 03-30 | "update the runbook" (first) | YES | dispatch_gate |
| 12 | 03-30 | "update the runbook" (duplicate, same minute) | YES | dispatch_gate (duplicate) |
| 13 | 03-31 | "Quota limit hit, 8 VMs running" | YES | dispatch_gate |

**Corrected count:** 7 YES + 1 duplicate = 7 unique dispatch_gate overrides (was 13)
**False matches:** 5 overrides miscategorized, 1 partial

### calls_puts_equal_citizens (claimed 4, actual 3-4)

| # | Date | Override | Verdict |
|---|------|---------|---------|
| 1 | 03-26 | "calls and puts both need to be in the strategy" | YES |
| 2 | 03-27 | "d073 equal citizens doesnt mean same config" | YES |
| 3 | 03-27 | "stop telling me to use or not use puts or calls. STOP" | YES |
| 4 | 04-06 | "ignore puts for now, calls only for paper trading" | PARTIAL -- scoped exception to D073, not a re-statement |

**Corrected count:** 3 clear + 1 partial = 3-4

### strict_typing (claimed 4, actual 2)

| # | Date | Override | Verdict | Correct Topic |
|---|------|---------|---------|---------------|
| 1 | 03-26 | "convert all code to typed python" | YES | strict_typing |
| 2 | 03-27 | "add the new backtesting protocol to decisions" | NO | backtesting_protocol (D097/D098) |
| 3 | 03-30 | "use strict static typing" | YES | strict_typing |
| 4 | 03-30 | "every statement needs to be backed up with evidence and citations" | NO | citation_sources |

**Corrected count:** 2 (was 4)

### capital_5k (claimed 3, actual 3)

| # | Date | Override | Verdict |
|---|------|---------|---------|
| 1 | 03-27 | "capital needs to be 5k, not 100k" | YES |
| 2 | 03-27 | "we are always working with a starting bankroll of 5k USD" | YES (duplicate, same session) |
| 3 | 04-06 | "5k is the hard cap, do not ask about it again" | YES |

**Corrected count:** 3 (2 unique + 1 duplicate same day)

### agent_behavior (claimed 3, actual 3)

| # | Date | Override | Verdict |
|---|------|---------|---------|
| 1 | 03-30 | "do not use async_bash ever again" | YES |
| 2 | 03-30 | "do not use async_bash ever again" (duplicate, 1 min later) | YES (duplicate) |
| 3 | 04-02 | "dont pontificate, just do exactly what I told you" | YES |

**Corrected count:** 3 (2 unique + 1 duplicate)

### gcp_primary (claimed 3, actual 3+)

| # | Date | Override | Verdict |
|---|------|---------|---------|
| 1 | 03-26 | "use GCP, archon is overflow only" | YES |
| 2 | 03-28 | "use gcp as often as you like" | YES |
| 3 | 04-02 | "$219 credit remaining on gcp" | PARTIAL -- informational, not a correction |

Plus the false matches from dispatch_gate that belong here:
| 2 | 03-26 | "archon for overflow, GCP is primary" | YES (moved from dispatch_gate) |
| 9 | 03-29 | "archon is overflow only, do not run tests directly" | YES (moved from dispatch_gate) |

**Corrected count:** 4-5

## New Topics Identified (from false matches)

| Topic | Overrides | Content |
|-------|-----------|---------|
| code_organization | 1 | "copy from optimus-prime directly" (D090) |
| reporting_format | 1 | "report returns in annualized terms" (D103) |
| no_artificial_filters | 2 | D118 (no hard filters) + D119 (illiquidity gate ok) |
| backtesting_protocol | 1 | D097/D098 backtesting rules |
| citation_sources | 1 | D136 cite everything with evidence |

## Corrected Summary

| Topic | Original Count | Corrected Count | Change |
|-------|---------------|-----------------|--------|
| dispatch_gate | 13 | 7 | -6 (false matches removed) |
| calls_puts_equal_citizens | 4 | 3-4 | -0 to -1 |
| strict_typing | 4 | 2 | -2 |
| capital_5k | 3 | 3 | 0 |
| agent_behavior | 3 | 3 | 0 |
| gcp_primary | 3 | 4-5 | +1 to +2 (absorbed from dispatch) |
| no_artificial_filters | 0 | 2 | +2 (new cluster) |
| backtesting_protocol | 0 | 1 | +1 (new, single) |
| citation_sources | 0 | 1 | +1 (new, single) |
| reporting_format | 0 | 1 | +1 (new, single) |
| code_organization | 0 | 1 | +1 (new, single) |

**Original claim:** 30/38 overrides (79%) in 6 clusters
**Corrected:** 24-27/38 overrides (63-71%) in 6 clusters with 2+ overrides, plus 5 single-override topics

The core finding holds -- repeated corrections are the dominant pattern -- but the dispatch_gate cluster was inflated (13 -> 7) and strict_typing was inflated (4 -> 2). The overall percentage drops from 79% to ~66% in multi-override clusters.

## Impact on Requirements

REQ-019 (single-correction learning) is still strongly supported: 24-27 overrides across 6 repeated topics.
REQ-020 (locked beliefs) is still supported: D100 ("STOP") and D209 ("do not ask again") are verified.
REQ-021 (behavioral beliefs in L0) is still supported: agent_behavior cluster is clean.

The inflated dispatch_gate count (13 -> 7) doesn't change the conclusion that it was the biggest pain point -- 7 overrides on one topic over 5 days is still severe.
