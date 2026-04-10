# Cross-Model MCP Behavior Differences

**Date:** 2026-04-09
**Status:** Research complete

## Key Finding

Tool calling is a function of model training, not MCP configuration. The same MCP server with identical tool definitions produces different behavior across models.

## Model-Specific Behavior

| Model | Tool Calling Pattern | Impact on Memory System |
|-------|---------------------|------------------------|
| **Claude** | Automatically invokes MCP tools when relevant context might be needed, even without explicit user request | `remember` and `correct` tools may be called proactively. `search` will fire automatically on session start. Good for implicit correction detection. |
| **ChatGPT** | Only calls memory tools when explicitly asked ("remember this", "recall that") | Will NOT proactively call `remember` or `correct`. Users must explicitly ask, or the agent prompt must instruct tool use. Bad for implicit correction detection. |
| **Gemini** | MCP support confirmed but behavioral details sparse. Google DeepMind integration in progress. | Unknown. Need to test. |
| **Local models (Ollama, llama.cpp)** | Tool calling support varies. PAL MCP Server bridges the gap but behavior depends on the specific model. | Likely least reliable tool calling. May need stronger prompting or a wrapper layer. |

## Implications for Our Design

1. **The `correct` tool is critical for ChatGPT.** ChatGPT won't proactively detect corrections. The V2 correction detector (92% accuracy) runs in the MCP server itself, but the MCP server can only process what gets sent to it. If ChatGPT doesn't call a tool, the server never sees the user's correction.

2. **Tool descriptions matter more than tool names.** Models use the description to decide when to call a tool. Our tool descriptions need to be carefully worded to trigger calls across all models.

3. **Session start behavior differs.** Claude may automatically call `status` on session start. ChatGPT probably won't. We may need to inject the wake-up protocol differently per model.

4. **Testing across models is essential.** We can't assume behavior from one model generalizes. Per OpenAI community: "create regression test scripts to validate consistent behavior across models."

## Proposed Mitigations

| Issue | Mitigation |
|-------|-----------|
| ChatGPT doesn't proactively call memory tools | Include explicit instructions in the system prompt: "After every user message, check if the user is correcting you or stating something to remember. If so, call the `correct` or `remember` tool." |
| Tool calling varies by description wording | A/B test tool descriptions across models. Use the description that triggers correct behavior on the most models. |
| Session start inconsistency | The MCP server's `status` tool should be designed so that any initial query to the server triggers the wake-up protocol, not just an explicit `status` call. |
| Local models unreliable | Provide a CLI wrapper that intercepts user input and calls memory tools directly, bypassing the model's tool-calling decision. |

## Architecture Decision

**AD-001: The MCP server must not depend on the LLM proactively calling tools.** Instead:
- The wake-up protocol runs on first MCP connection, not on explicit tool call
- Correction detection runs on every observation that passes through the server, not only when `correct` is called
- Critical beliefs (L0) are injected into every response from the server, not just when `search` is called

This makes the memory system work even with models that never voluntarily call tools.

## Sources

- [MCP tool calling behavior difference: ChatGPT vs Claude (OpenAI Community)](https://community.openai.com/t/mcp-tool-calling-behavior-difference-chatgpt-vs-claude/1359545)
- [Beyond Claude: Using OpenAI and Google Gemini Models with MCP Servers (Medium)](https://thesof.medium.com/beyond-claude-using-openai-and-google-gemini-models-with-mcp-servers-eea3bc218ed0)
- [MCP in ChatGPT vs Claude vs Mistral (Dataslayer)](https://www.dataslayer.ai/blog/mcp-in-claude-vs-chatgpt-vs-mistra)
- [PAL MCP Server (GitHub)](https://github.com/BeehiveInnovations/pal-mcp-server)
- MCP donated to Agentic AI Foundation (AAIF) under Linux Foundation, Dec 2025
