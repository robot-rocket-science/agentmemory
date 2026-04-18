<sub>[← Chapter 1 - Installation](INSTALL.md) · [Contents](README.md) · Next: [Chapter 3 - Command Reference →](COMMANDS.md)</sub>

# Chapter 2. Workflow

Once installed, the commands you will use most:

```
/mem:search "topic"         # Find what the agent knows about a topic
/mem:core 10                # See the top 10 highest-confidence beliefs
/mem:wonder "topic"         # Broad research with graph context
/mem:reason "question"      # Focused hypothesis testing against evidence
/mem:stats                  # System analytics
/mem:locked                 # Show locked constraints (non-negotiable rules)
```

From the CLI:

```bash
agentmemory search "query terms"
agentmemory core --top 10
agentmemory stats
```

Full command reference in [COMMANDS.md](COMMANDS.md).

## The Core Loop

Discuss, explore, focus, build, repeat.

1. **Discuss.** Start talking about a topic with your agent. agentmemory automatically captures decisions, corrections, and preferences from the conversation. You do not need to do anything special, just work normally.

2. **Explore.** When you want a wider view, run `/mem:wonder "topic"`. Wonder spawns parallel research agents that pull from the belief graph, web sources, and documentation to surface perspectives and hypotheses you have not considered. It produces structured output with uncertainty signals so you can see what is well-supported vs. speculative.

3. **Focus.** When you are ready to commit to a direction, run `/mem:reason "question"`. Reason does graph-aware hypothesis testing. It traces evidence chains, identifies contradictions, and finds the highest-leverage entry points. It tells you what the evidence supports, where the gaps are, and what to investigate next.

4. **Build.** Take the output from wonder/reason into a few more discussion turns to refine the plan, then implement. agentmemory captures what you build and the decisions behind it.

5. **Repeat.** Next session, the agent already has the context. Wonder and reason get sharper as the belief graph grows, because there is more evidence to reason over and more connections to traverse.

---

<sub>[← Chapter 1 - Installation](INSTALL.md) · [Contents](README.md) · Next: [Chapter 3 - Command Reference →](COMMANDS.md)</sub>
