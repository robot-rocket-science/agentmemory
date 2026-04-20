# CS-036: Configuration Staleness Detection via Memory Audit

**Status:** NEEDS ANONYMIZATION before public use
**Date:** 2026-04-20
**Category:** Self-referential meta-audit

## Scenario

User asks the agent to audit a static configuration file (CLAUDE.md) for redundancy with the dynamic memory system (agentmemory). The memory system is used to audit itself -- checking whether beliefs it injects at session start duplicate instructions already present in the config file.

## What Happened

1. **User prompt:** "Clean up the root level CLAUDE.md -- agentmemory should be injecting a lot of stuff already that CLAUDE.md does. Can you verify?"

2. **Agent action:** Searched agentmemory for keywords from each CLAUDE.md rule, mapping overlap:
   - 15 rules in CLAUDE.md
   - 2 found redundant with agentmemory beliefs (memory system instruction, em dash rule)
   - 13 correctly identified as behavioral rules requiring prompt-level enforcement (not memory's job)

3. **User challenge:** "I'm sure there are items in CLAUDE.md that are locked beliefs and therefore get injected into every starting session as well, did you check that?"

4. **Agent action:** Called `get_locked()` to see what's injected at session start. Found 6 locked beliefs. None overlapped with behavioral rules, but one overlapped with a newly-added Git Workflow section in CLAUDE.md -- and that locked belief was stale (referenced a removed git remote and an outdated workflow).

5. **Resolution:**
   - Removed 2 redundant lines from CLAUDE.md
   - Superseded the stale locked belief with current workflow
   - Locked the corrected belief

## What This Demonstrates

1. **Cross-layer awareness:** The system correctly distinguished between what belongs in static config (behavioral rules like "never compliment me") vs dynamic memory (project state like git remote setup). Behavioral rules need prompt-level enforcement; project facts should be in memory where they can be updated.

2. **Staleness detection:** A locked belief about git remote configuration became stale after the workflow changed (remote removed, mirror added then removed, publish script created). The audit surfaced this because the static config and dynamic memory told conflicting stories about the same topic.

3. **Self-correction capability:** The system used its own `correct()` and `lock()` tools to fix the stale belief, demonstrating the "evidence must be able to change beliefs" principle even for locked beliefs.

4. **Layered context architecture validation:** The audit confirmed the architecture works as designed:
   - CLAUDE.md: behavioral rules (tone, style, workflow instructions)
   - Project CLAUDE.md: project-specific tool usage instructions
   - Locked beliefs: project state facts (versions, account status, workflow config)
   - Core beliefs: high-confidence project knowledge (injected at session start)
   - Search results: contextual beliefs (injected per-query via hooks)

## Key Insight

The most valuable finding was NOT that items were redundant (only 2 were). It was that a locked belief had gone stale and was telling every new session incorrect information about the git workflow. Without this meta-audit, the stale belief would have continued injecting outdated instructions until someone noticed a conflict.

This validates the principle that locked beliefs need periodic review, not just accumulation. The audit pattern itself (comparing static config against dynamic memory) is a reusable diagnostic.

## Metrics

- Rules audited: 15
- Redundant rules removed: 2
- Stale beliefs corrected: 1
- False positives (incorrectly flagged as redundant): 0
- Time to complete: ~5 minutes of conversation
