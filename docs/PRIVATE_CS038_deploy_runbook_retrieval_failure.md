# CS-038: Deploy Runbook Retrieval Failure (Live Incident)

**Status:** NEEDS ANONYMIZATION before public use
**Date:** 2026-04-20
**Category:** Cross-project procedural retrieval gap
**Severity:** The exact failure class agentmemory is built to prevent

## What Happened (Verbatim, Anonymized)

During a session working on the agentmemory project, the user asked the agent to deploy new images to their personal website (hosted on Cloudflare Pages). The website project has a detailed deploy runbook (`DEPLOY.md`) with an exact step-by-step protocol.

The agent did not consult the runbook. Instead, it improvised:

```
Attempt 1:
  agent   npx wrangler pages deploy dist
  result  ERROR: D1 binding references database which was not found.

Attempt 2:
  agent   [Removes D1 binding from wrangler.toml]
  agent   npx wrangler pages deploy dist
  result  Deployed, but to wrong branch. 404 on production.

  agent   "Still 404. Cloudflare Pages might be caching."
  agent   [Checks deployment alias -- works there]
  agent   "It'll resolve within a minute or two."

Attempt 3:
  agent   npx wrangler pages deploy dist
  result  Deployed again, still 404.

User intervention:
  user    "For websites deploy we have a run book and protocol
           in ~/projects/robotrocketscience use that please"

  agent   [Reads DEPLOY.md]
  agent   npx wrangler pages deploy dist/ --project-name robotrocketscience --branch production
  result  Deployed correctly. 200 on production.
```

Three failed attempts before the user pointed to a document the agent had filesystem access to the entire time.

## The Four Root Causes

### 1. Project Isolation Blocked Cross-Project Retrieval

The session was running in `~/projects/agentmemory/`. The deploy runbook lives in `~/projects/robotrocketscience/`. agentmemory uses per-project databases (SHA-256 hash of the working directory). Beliefs from the website project are invisible to the agentmemory project's retrieval pipeline.

**This is working as designed.** Project isolation prevents cross-contamination (a Python project's beliefs don't leak into a Rust project). But deploy procedures are *infrastructure knowledge*, not project knowledge. The deploy protocol applies regardless of which project triggered the deploy.

### 2. No Action-Triggered Retrieval

The system has keyword-triggered injection: when the user says "deploy," beliefs mentioning "deploy" surface. But the trigger operates on user *prompts*, not on agent *actions*. The agent executed `npx wrangler pages deploy` three times, and at no point did the system check whether a deploy procedure existed.

The PreToolUse hook fires on every Bash command, but it only checks for:
- Edit tool: "read before edit" reminders
- Skill tool: MCP audit gates

It does NOT check: "is there a documented procedure for the command you're about to run?"

### 3. FTS5 Ranking Bias Against Procedures

Even within the correct project, procedural beliefs rank lower than analytical beliefs. A step-by-step runbook mentions "deploy" once in the title. A research document analyzing deployment patterns mentions "deploy" fifteen times. FTS5 BM25 scores the research doc higher, pushing the actual procedure below the top-K retrieval window.

### 4. No Reference Beliefs for External Files

The deploy runbook exists as a file (`DEPLOY.md`) but not as a belief. agentmemory stores extracted knowledge as beliefs, but it doesn't store "there is a procedure document at this path for this task." A reference belief like "Deploy protocol for robotrocketscience.com: see ~/projects/robotrocketscience/DEPLOY.md" would have been sufficient.

## Why This Is the Core Problem

This case study is uniquely damaging because it occurred *while the agent was building and demonstrating agentmemory itself*. The session's explicit purpose was improving the tool's README, documentation, and public presentation. The failure happened during a task that required cross-project infrastructure knowledge -- exactly the kind of workflow the tool claims to support.

The irony: the agent had just finished writing README copy saying "agentmemory makes sure your agent knows what it needs to know." Then it demonstrated the opposite.

## What This Tells Us About the Architecture

The four root causes map to four different layers of the retrieval pipeline:

| Layer | What It Does | What Failed |
|---|---|---|
| **Scope** | Per-project database isolation | Blocks infrastructure knowledge |
| **Trigger** | Keyword matching on user prompts | Doesn't monitor agent actions |
| **Ranking** | FTS5 BM25 term frequency | Penalizes step-by-step content |
| **Coverage** | Beliefs extracted from conversations | No pointer to external procedure files |

No single fix addresses all four. The system needs:

1. **Infrastructure-scoped beliefs** that transcend project boundaries
2. **Action-context retrieval** that fires on tool use, not just user prompts
3. **Procedural ranking boost** when the context implies execution
4. **Reference beliefs** that point to authoritative external documents

## The User's Fix (What Actually Worked)

The user said: "we have a run book and protocol in ~/projects/robotrocketscience -- use that please."

This is a human doing what the retrieval system should have done:
- Recognized the *type of action* (deploy)
- Recalled the *location of the procedure* (different project)
- Injected it into the agent's context (verbally)

agentmemory should automate exactly this: recognize action type, recall procedure location, inject before execution.

## Proposed Case Study Title for README

**"Three Deploys to Nowhere"** -- The agent deployed to Cloudflare three times without checking the deploy runbook that was sitting in a neighboring project directory. The runbook had the exact flags needed. The agent improvised instead.

## Connection to Existing Case Studies

- **CS-003 (Overwriting State Instead of Consulting It):** Same pattern -- the agent acts without checking existing documentation
- **CS-005 (Project Maturity Inflation):** The agent reported "Deployed successfully" when the deploy was actually broken (wrong branch)
- **CS-002 (Premature Implementation Push):** The agent jumped to executing commands instead of first establishing the correct procedure

## Metrics

- Failed deploy attempts before consulting runbook: 3
- Time wasted on improvised deploys: ~5 minutes
- Beliefs about deployment in the active project DB: 54 matched search
- Beliefs containing the actual deploy procedure: 0 (wrong project scope)
- Files containing the procedure on disk: 1 (DEPLOY.md, accessible but never read)
- User interventions required: 1 (pointed to the runbook)
