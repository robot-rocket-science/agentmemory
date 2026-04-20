# mem:reason: Why Did the Agent Fail to Retrieve the Deploy Runbook?

## Query

> Why did the agent fail to retrieve the deploy runbook for robotrocketscience.com despite having access to agentmemory beliefs about the infrastructure and the runbook file on disk? What gaps in the retrieval algorithm allowed this failure, and what would need to change to prevent it?

## Hypothesis

The retrieval system has structural gaps that prevent it from surfacing procedural knowledge (runbooks, protocols) when the agent is performing actions that those procedures govern. The system retrieves beliefs about *what things are* but not *how to do things with them*.

## Methodology

- 2 MCP search queries against the live belief graph (65,276 beliefs)
- Keywords: deploy, runbook, protocol, cloudflare, wrangler, cross-project, retrieval, scope
- 116 beliefs returned across both queries
- No subagents dispatched (evidence sufficient)

## Evidence Chain

### Root Cause 1: Project Isolation Blocks Cross-Project Retrieval

The session was running in `~/projects/agentmemory/` (project hash `4b0f8c37972f`). The deploy runbook lives at `~/projects/robotrocketscience/DEPLOY.md`. These are different projects with separate belief databases.

**Key belief:** `29afa7100fc9` (requirement, 78%): "Default behavior must be: beliefs from project A are NOT retrievable when working on project B, unless explicitly tagged as cross-project."

**Key belief:** `15e5d9911c44` (correction, 91%): "If the target node's project_id is a different project: do not traverse."

The deploy runbook was never onboarded into the agentmemory project's belief database. It exists in the robotrocketscience project's filesystem but has no corresponding beliefs in the active project's store. The retrieval pipeline correctly isolates per-project -- but this isolation prevented cross-project procedural knowledge from surfacing.

**This is working as designed, but the design has a gap for cross-project workflows.**

### Root Cause 2: No Action-Triggered Retrieval for Procedures

**Key belief:** `7d8bf4719da2` (factual, 37%): "Automatic query-seeded injection: When the user's prompt mentions 'dispatch' or 'deploy,' the memory system automatically injects all relevant directives."

**Key belief:** `26eae67efa94` (correction, 90%): "the runbook is re-injected every time the user mentions dispatch/deploy/GCP."

These beliefs describe a system that was designed for a *different* project (the dispatch gate protocol). The keyword-triggered injection ("deploy" -> inject runbook) was implemented for that project's CLAUDE.md, not as a general mechanism. When the user said "deploy" in the agentmemory project context, no injection occurred because:

1. The agentmemory project's CLAUDE.md has no deploy-triggered injection rule
2. The hook_search Layer 0 (activation_condition) found no matching conditions
3. FTS5 search for "deploy" returned beliefs about deployment *concepts* (from research/experiments) but not the actual deploy *procedure*

### Root Cause 3: FTS5 Ranking Pushes Procedural Knowledge Below K=15

**Key belief:** `3100c9d0128b` (factual, 33%): "FTS5's OR query scores D137 low (only 1 of 4 terms matches) and other nodes with more term matches rank higher, pushing D137 below K=15."

**Key belief:** `45b9b3ebd9e2` (factual, 37%): "D137: FTS5 BM25 ranks it at position 17 for query 'dispatch gate deploy protocol.' The content matches on exact substrings but BM25 penalizes it relative to other nodes."

Even when procedural beliefs exist in the database, FTS5 BM25 scoring penalizes them because procedure content is typically longer and more dilute (many terms, low term frequency per term). Research beliefs that mention "deploy" in a dense analysis paragraph score higher than a step-by-step runbook that mentions "deploy" once in a title.

### Root Cause 4: No Tool-Use Interception

The agent executed `npx wrangler pages deploy dist` three times. At no point did the retrieval system intercept the tool use to inject relevant procedural knowledge. The PreToolUse hook exists but only checks for MCP audit gates and read-before-edit reminders. There is no "before running a deploy command, check for deploy procedures" interception.

**What the system has:** PreToolUse hooks for Edit (read-before-edit), Skill (MCP audit gate)
**What the system lacks:** PreToolUse hook for Bash commands matching deploy/build/release patterns

## Result

**ANSWER:** Four independent gaps compounded to cause the failure:

1. **Project isolation** prevented retrieval of the robotrocketscience deploy runbook from within the agentmemory project context. The runbook exists on disk but not in the active belief database.

2. **No action-triggered injection** for deploy procedures. The keyword-triggered injection mechanism was built for a specific project (dispatch gate) and not generalized to detect deploy-related actions across projects.

3. **FTS5 ranking bias** pushes procedural content (step-by-step instructions) below research content (analysis mentioning the same terms) due to BM25 term frequency scoring.

4. **No tool-use interception** for deploy commands. The agent executed `wrangler` three times without any hook checking whether a deploy protocol exists.

**CONFIDENCE:** High (0.85). The evidence chain is well-supported by existing beliefs, the failure was observed in real-time, and the root causes map to known architectural gaps (cross-project retrieval, procedural knowledge ranking, tool-use interception).

## Open Questions

1. Should deploy procedures be cross-project beliefs? The user has multiple projects that all deploy to the same infrastructure (Cloudflare). The deploy runbook is infrastructure knowledge, not project knowledge.

2. Should there be a "procedural" belief type that gets special ranking treatment? Currently procedural beliefs exist as a type but don't get preferential retrieval when actions matching them are detected.

3. Would a PreToolUse hook for Bash commands be too noisy? Intercepting every bash command to check for procedural matches could add latency.

4. Should agentmemory support "reference beliefs" that point to external files (like DEPLOY.md) rather than storing the procedure content as a belief?

## Suggested Updates

| Belief ID | Current | Suggested | Reason |
|---|---|---|---|
| `7d8bf4719da2` | 37% | 60% | The keyword-triggered injection design is validated; the gap is that it wasn't generalized |
| `29afa7100fc9` | 78% | 85% | Project isolation is working correctly; the gap is in cross-project procedural knowledge |
| `3100c9d0128b` | 33% | 55% | FTS5 ranking bias against procedures is now confirmed in a live failure, not just a theoretical observation |

## Proposed Fixes (Prioritized)

### Fix 1: Cross-Project Procedural Beliefs (High Impact)

Allow specific beliefs to be tagged as `scope: infrastructure` (or `scope: global`) so they surface regardless of which project is active. Deploy procedures, server access patterns, and infrastructure conventions are not project-scoped -- they're environment-scoped.

### Fix 2: Action-Context Layer in Retrieval (High Impact)

When the agent is about to execute a command matching known patterns (deploy, build, release, migrate), the retrieval system should automatically search for procedural beliefs containing those action words, with elevated ranking. This is Layer 3 (action-context) which exists but doesn't cover tool-use actions.

### Fix 3: PreToolUse Hook for Deploy/Build Commands (Medium Impact)

Add a PreToolUse hook for Bash commands matching `wrangler|deploy|build|release|migrate` patterns that injects a reminder: "Check for deploy procedures before executing." This is lightweight (regex match) and catches the specific failure mode observed.

### Fix 4: Procedural Belief Ranking Boost (Low Impact)

Boost `belief_type: procedural` in scoring when the query or context contains action verbs (deploy, build, run, install, configure). This addresses the FTS5 ranking bias without changing the ranking algorithm for non-procedural queries.
