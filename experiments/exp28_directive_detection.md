# Research: LLM-in-the-Loop Directive Detection

**Date:** 2026-04-09
**Triggered by:** F1 vocabulary mismatch (D157 missed by all retrieval methods)

## The Reframe

We were trying to detect directives from text patterns (zero-LLM). But the user is already talking to an LLM that understands the directive perfectly. The vocabulary mismatch problem exists only in post-hoc text analysis. At the moment the user says "never use async_bash," the LLM knows exactly what that means.

The architecture should exploit this: the LLM calls a memory tool AT THE MOMENT it understands the directive. Not after. Not during extraction. In the conversation turn where the directive is issued.

## Old Architecture (zero-LLM extraction)

```
User says "never use async_bash"
  -> conversation continues
  -> later: extraction pipeline analyzes text
  -> regex patterns detect negation + imperative (V2: 92%)
  -> creates a belief
  -> belief may or may not be categorized correctly
  -> vocabulary mismatch: future query "agent behavior" won't find "async_bash"
```

## New Architecture (LLM-in-the-loop)

```
User says "never use async_bash"
  -> LLM understands it immediately and completely
  -> LLM calls directive tool:
     directive(
       content="Never use async_bash or await_job",
       scope="always",
       category="tool_usage",
       related_concepts=["agent behavior", "background execution", "tool selection"],
     )
  -> Memory system stores it with rich metadata
  -> On context rollover, re-injected into L0/L1
  -> Future query "agent behavior" finds it via related_concepts
```

The `related_concepts` field is the key. The LLM fills it in at storage time with the semantic connections that keyword matching can't discover. "async_bash" relates to "agent behavior" and "tool selection" -- the LLM knows this, regex doesn't.

## The Tool

```
Tool: directive
Description: "Store a persistent user directive. Call this whenever the user 
  tells you to always do something, never do something, or establishes a 
  permanent rule. The directive will be remembered across sessions."

Parameters:
  content: string       -- the directive in clear language
  scope: enum           -- "always" | "this_project" | "this_session"  
  category: enum        -- "tool_usage" | "behavior" | "communication_style" |
                           "domain_rule" | "preference" | "constraint"
  related_concepts: [string]  -- semantic tags for retrieval
  override_of: string?  -- if this supersedes a prior directive, reference it
```

Internally, this creates:
- A belief with source_type = "user_corrected" 
- Locked = true (REQ-020)
- Loaded in L0 if scope = "always" or category = "behavior" (REQ-021)
- related_concepts stored as searchable tags (bridges vocabulary gap)

## Why This Is Better

| Dimension | Zero-LLM V2 | LLM-in-the-loop |
|-----------|-------------|-----------------|
| Detection accuracy | 92% on known patterns | ~100% when LLM calls the tool |
| Vocabulary bridging | None (keyword-only) | LLM provides related_concepts |
| Category accuracy | Regex heuristic (60% "factual") | LLM understands intent |
| Scope detection | Not attempted | LLM can judge "always" vs "this session" |
| Cost per directive | Zero | One tool call (negligible) |
| Works without LLM? | Yes | No -- but an LLM is always present in this use case |

## The Zero-LLM Fallback

V2 pattern detection (92%) remains as a fallback for cases where:
- The LLM doesn't call the tool (ChatGPT's proactivity problem)
- The directive is embedded in a long message and the LLM misses it
- A local model with poor tool-calling support is used

The system operates in two layers:
1. **Primary:** LLM calls `directive` tool (high accuracy, rich metadata)
2. **Fallback:** Zero-LLM V2 pattern detection (lower accuracy, no semantic tags)

## Connection to /gsd:steer

The user referenced `/gsd:steer` -- a GSD command where the user explicitly steers the agent's behavior. The `directive` tool is the model-agnostic equivalent:

- `/gsd:steer` is CLI-specific (GSD framework)
- `directive` is an MCP tool (works with any LLM client)
- Both achieve the same thing: user permanently alters agent behavior

## Connection to Cross-Model Behavior (Exp 10)

| Model | Will it call `directive` proactively? | Mitigation |
|-------|--------------------------------------|-----------|
| Claude | Yes -- proactively calls tools when relevant | Works out of the box |
| ChatGPT | Only when explicitly told | System prompt instruction: "When the user gives a permanent directive, call the directive tool" |
| Local models | Depends on tool-calling capability | V2 fallback + CLI wrapper that intercepts directives |

## Open Questions

1. **How to prompt the LLM to call `directive` reliably across models?** The tool description needs to trigger calls in Claude AND ChatGPT AND local models.
2. **What if the user doesn't want a directive stored?** Need an "undo" or "forget" mechanism. Maybe: "actually, forget that" -> calls `forget_directive`.
3. **How many `related_concepts` should the LLM generate?** Too few = vocabulary gap persists. Too many = noise. 3-5 seems right.
4. **Should the LLM also call `directive` for IMPLICIT directives?** "I prefer TypeScript" is implicit -- the user didn't say "always use TypeScript." Can the LLM distinguish preferences from directives?

## Impact on PLAN.md

This changes the MCP tool design. The `remember` and `correct` tools from PLAN.md are subsumed by `directive` for the directive use case. `remember` still applies to non-directive facts ("John works at Anthropic"). `correct` still applies to belief revision. But persistent behavioral rules go through `directive` for richer metadata.

Updated tool inventory:
- `observe` -- record raw event (unchanged)
- `believe` -- create belief from evidence (unchanged)  
- `search` -- find relevant beliefs (unchanged)
- `test_result` -- feedback on retrieval (unchanged)
- `revise` -- supersede a belief (unchanged)
- `remember` -- store a persistent fact (unchanged)
- `correct` -- fix a wrong belief (unchanged)
- **`directive`** -- store a persistent behavioral rule with semantic tags (NEW)
- `forget_directive` -- remove a stored directive (NEW)
