# /mem:wonder Test 2: Install/Command Architecture (2026-04-11)

## Query
"need to fix onboarding, mcp install and tool call issues, /mem:command problems, getting /mem to work natively with claude cli"

## Belief retrieval
- 30 beliefs returned
- 2 locked beliefs surfaced at top (tone preferences)
- Remaining 28 were directly relevant to the install/command architecture problem

## Precision assessment
Much better than the first wonder test (WONDER_BASELINE.md, 24% precision).

### Directly useful beliefs (22/30 = 73%):
- "/mem:onboard, /mem:status, /mem:core... /mem:stats, /mem:new-belief, and so on" -- the command set design
- "The bar is: run one command, everything works -- slash commands, MCP tools, onboarding"
- "we did a ton of research on how to install mcp and tools properly because we keep running into issues"
- "no its not production-ready, because we need the / commands and the onboarding and install to be flawless"
- "Rewrite the skills to call the CLI instead of asking me to call MCP tools"
- "the cleanest way to do a test install is to try installing on an isolated system"
- "no /mem:install doesnt make any sense" -- user decision captured
- "No /mem:correct command" -- dropped feature captured
- "I notice there are still old skills cluttering the skill list" -- known issue captured
- "Command prompt tells Claude which MCP tools to use and when" -- architecture understanding
- Various command-name fragments showing the evolution of naming conventions

### Noise (8/30 = 27%):
- 2 locked beliefs about tone (irrelevant to the query but always surface by design)
- 6 raw command XML fragments (<command-name>, <command-message>) that are conversation artifacts, not insights

## Subagent spawning
4 agents spawned in parallel per wonder protocol:
1. Prior art on CLI install patterns (web research)
2. Gaps in current setup (codebase exploration)
3. Hypotheses for native integration (hooks-based auto-context)
4. Synthesis and critical path mapping

Each agent received the full 30-belief context plus a specific research angle.

## Comparison to WONDER_BASELINE.md

| Metric | Test 1 (ranking) | Test 2 (install) |
|---|---|---|
| Beliefs returned | 29 | 30 |
| Precision | 24% (7/29) | 73% (22/30) |
| Noise source | Broad keyword matching | Locked beliefs + XML fragments |
| Subagents spawned | 0 (CLI only) | 4 (full protocol) |

## Why precision improved
Test 1 used abstract concepts ("confidence flat", "equal evidence") that match broadly.
Test 2 used specific project vocabulary ("onboarding", "mcp install", "/mem:command", "claude cli") that maps directly to beliefs created from this session's conversation. The memory system performs best when the query uses the same vocabulary as the stored beliefs.

## Assessment
Wonder is working as designed for domain-specific queries. The 73% precision is strong for keyword-based retrieval without embeddings. The subagent spawning adds research depth that the CLI output alone can't provide. The main improvement path remains embedding-based search for abstract/natural language queries.
