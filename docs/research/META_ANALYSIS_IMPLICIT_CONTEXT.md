# Meta-Analysis: Measuring Implicit Context in Live Conversation

## The Experiment

During the 2026-04-17 session, after completing the high-context injection research, the user posed an in-situ test of the theory:

> "Let's try an example right now: when I say 'please document everything and cite all your sources,' what is the mutually understood and implied information that I did not explicitly include in that statement, but that you implicitly understand because of not just your LLM training but also because of hopefully the agentmemory belief percolation system churning through nodes and edges? I can't measure what's attributable to your LLM training but I can measure what's attributable to agentmemory response retrieval and prompt injection every turn"

This is a real-time test of the ba protocol concept: can we decompose a high-context instruction into its explicit vs implicit components, and attribute the implicit understanding to specific sources?

## The Instruction

**What the user said (8 words):** "Please document everything and cite all your sources."

## Decomposition: Three Attribution Layers

### Layer 1: From agentmemory beliefs (measurable)

These were understood because agentmemory injected beliefs or because locked beliefs were loaded at session start:

| Implicit understanding | Source | Injected? |
|---|---|---|
| "Document" means write a .md file in the repo research/ directory | Project structure pattern (repeated across session) | No -- inferred from cwd, not injected |
| "Everything" means synthesized, not raw agent dumps | Feedback belief: "plain language first, no jargon barrage" | In auto-memory, not in hook injection |
| "Cite your sources" means inline URLs, not footnotes | Locked belief: "cite your sources when available (with link)" | Yes -- SessionStart injection |
| Output must not use em dashes | Locked belief: "never use em dashes" | Yes -- SessionStart injection |
| File should be committed and pushed to both remotes | Established pattern from 6+ commits this session | No -- session context, not belief |

**Measurable gap:** Of 5 implicit understandings attributable to agentmemory, only 2 were actually injected by the hook system. The other 3 were either in auto-memory (not queried by hooks), inferred from project structure, or learned from session pattern.

### Layer 2: From conversation context (session-local, not persistent)

These were understood from the current conversation window, not from agentmemory:

| Implicit understanding | Source |
|---|---|
| "Everything" refers to three specific research threads (high-context communication, injection patterns, ba protocol) | Three subagents launched 10 minutes prior |
| Sources are whatever the subagents found via web search | Subagent task descriptions specified web search |
| Document goes in agentmemory project, on the current feature branch | git status: on feature/action-aware-retrieval |
| Document should be a standalone research artifact, not a code comment | Pattern from prior research/ directory files |

**Key observation:** These are ephemeral context items that live and die with the conversation window. If the session were compacted or restarted, all four would be lost. The ba protocol's "background" zone should capture these.

### Layer 3: From LLM training (not measurable, not attributable to agentmemory)

| Implicit understanding | Source |
|---|---|
| Academic citation norms (author, year, title, URL) | Training data |
| What a "research document" looks like structurally (sections, headers, synthesis) | Training data |
| English language comprehension of "everything" as "comprehensive" | Training data |
| "Please" as a politeness marker, not a conditional | Training data |

**Cannot be measured** because these are baked into the model weights. The user correctly identified this as the non-measurable baseline.

## What agentmemory SHOULD Have Injected But Didn't

The UserPromptSubmit hook fired on the "please document everything" prompt. The actual injection (visible in the system-reminder block) contained 50 beliefs, primarily:

- Locked corrections about meta-beliefs and meta-cognitive design
- Factual beliefs about document structures and verbatim exchanges
- Requirements about documentation honesty

**None of the 50 injected beliefs were operationally relevant to the task.** The hook's FTS5 search matched "document" against thousands of beliefs containing the word "document" and returned the highest-scored ones, which were about documentation philosophy rather than documentation mechanics.

What should have been injected (under the ba protocol):

```
== OPERATIONAL STATE ==
[!] Three research subagents completed: high-context communication,
    injection patterns, ba protocol redesign (results pending synthesis)

== STANDING CONSTRAINTS ==
- Cite sources with links when available
- Never use em dashes
- Plain language first, technical metrics only when requested
- Do not commit large data files

== BACKGROUND ==
- Research documents go in research/ directory
- Current branch: feature/action-aware-retrieval
- Both remotes (github, github-rrs) should receive pushes
```

This would have been 8 lines instead of 50 beliefs, and every line would have been operationally relevant.

## Measurement Framework

The user's key insight: "I can't measure what's attributable to your LLM training but I can measure what's attributable to agentmemory response retrieval and prompt injection every turn."

This is correct. The measurement protocol:

1. **What was injected**: The `AGENTMEMORY:` block in each system-reminder is the ground truth for what the hook system contributed. It is logged, timestamped, and reproducible.

2. **What was used**: Compare the injected beliefs against the agent's actual response. Did the agent's behavior reflect any injected belief? This is the "used" signal in the feedback loop.

3. **What was needed but missing**: Compare the agent's behavior against what the user corrected. Each correction represents a belief that should have been injected but wasn't.

4. **Attribution**: If the agent's correct behavior matches an injected belief, that's attributable to agentmemory. If it matches training data patterns (e.g., citation format), it's not attributable. If it matches session context (e.g., "we just launched 3 agents"), it's attributable to the conversation window, not to agentmemory.

This gives three measurable quantities per turn:
- **Hit rate**: injected beliefs that were used / total injected
- **Miss rate**: needed beliefs that were not injected / total needed
- **Noise rate**: injected beliefs that were irrelevant / total injected

For the "document everything" turn:
- Hit rate: 0/50 (none of the 50 injected beliefs were operationally relevant)
- Miss rate: 3/5 (3 of 5 needed understandings were not injected)
- Noise rate: 50/50 (all 50 injected beliefs were about meta-cognition, not documentation)

## Connection to Ba Protocol

The three-zone format directly addresses these metrics:

- **Standing constraints zone** eliminates misses for persistent rules (no em dashes, cite sources) by always including them regardless of query relevance.
- **Operational state zone** eliminates misses for recent state changes by surfacing deviations first.
- **Background zone** reduces noise by limiting background facts to a small, curated set rather than 50 FTS5 matches.

The goal is not 100% hit rate (that would require the system to predict exactly what the agent needs). The goal is: standing constraints always present (0% miss rate on locked beliefs), state changes always visible (0% miss rate on recent corrections), and background noise kept below the attention-scattering threshold identified in the ICLR 2025 research.
