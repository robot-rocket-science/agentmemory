# Case Study: Using agentmemory to Research Its Own Positioning

> A real session where wonder + reason produced actionable marketing strategy. Unedited except for PII removal.

## The Problem

The agentmemory README read like a research paper. The project had genuine technical depth (98 experiments, 5 academic benchmarks, 954 tests) but wasn't converting readers into users. The maintainer asked: "How do we market this in an exciting but completely accurate way?"

Rather than guessing, we used agentmemory's own tools to research the question.

## What Happened

### Step 1: The Hook Injection (Automatic)

Before the session even started, agentmemory's SessionStart hook fired and injected context into the agent's system prompt:

```
AGENTMEMORY:

LOCKED BELIEFS (obey without exception):
- Two-repo git workflow: origin (Gitea, private) is the development repo.
  github (public) is the release repo. Publishing is intentional via
  scripts/publish-to-github.sh with PII guard checks.
- Evidence MUST be able to change beliefs, including locked ones...

BEHAVIORAL DIRECTIVES:
- Do not overclaim rigor. Say "simulated" or "tested on N samples"
  instead of implying broad validation.

CORE BELIEFS:
- [correction] v3.0.0, 98 experiments, 954 tests, 31 MCP tools,
  33 production modules. Production system in daily use.
```

This context -- accumulated over weeks of prior sessions -- meant the agent already knew the project's constraints, version, architecture, and communication style before a single word was typed.

### Step 2: The Wonder Query

The user typed:

```
/mem:wonder How should agentmemory be positioned and marketed to developers?
The project has genuine utility but the README reads like a research paper
rather than a tool that solves a pain point...
```

### Step 3: Belief Retrieval (Automatic)

agentmemory's UserPromptSubmit hook fired and ran a 7-layer search against the memory database. It retrieved 53 direct beliefs, 22 graph-connected beliefs, and 32 uncertain beliefs relevant to the query. Key retrieval:

```
[100%] User quote from prior session: "if i told you that all that
       research is extensive we did in like 2-3 hours with some good
       prompting would that change your posture about how extensive
       and how deep this project is?"

[99%]  The user is trapped in a correction loop that never converges
       because the agent has no persistent memory of what was tried.

[78%]  Agentmemory is a research project that has done genuine,
       rigorous research and then built a working MVP.
```

That first belief (100% confidence, from a prior session) directly informed the research direction: the project's depth is real, but communicating it wrong undermines credibility.

### Step 4: Parallel Research Agents

The wonder system spawned 4 research agents in parallel:

| Agent | Assignment | Duration |
|---|---|---|
| 1 | Study how htmx, ruff, uv, sqlite, zod, tRPC position themselves | 2.5 min |
| 2 | Psychology of developer adoption, invisible product marketing | 2.9 min |
| 3 | Brutally honest critique of the current README | 0.8 min |
| 4 | Write 3 alternative README structures | 0.9 min |

Each agent had access to web search and independently produced findings.

### Step 5: Agent Findings (Summarized)

**Agent 1 (Marketing Patterns)** studied 6 top developer tools and found a common structure:

1. One-line identity (<15 words)
2. Visual proof (benchmark, GIF, or code snippet)
3. Install command (frictionless)
4. Progressive disclosure (depth is linked, not inlined)

Key insight: "The tools that succeed fastest combine a single dramatic claim with visual proof and a 'replaces N tools' consolidation narrative."

**Agent 2 (Emotional Resonance)** researched adoption psychology:

- Primary trigger: frustration relief (2x conversion for frustrated users)
- 73% of developers want hands-on experience within 10 minutes
- Tools that buried research and led with UX won adoption; tools that led with research lost
- For invisible tools: show the counterfactual (what would have gone wrong without it)

**Agent 3 (README Critique)** gave a 6/10 rating:

> "The github-push worked example is the most compelling content in the entire README and it's buried at line 180. The before/after table says one idea in 5 rows. The fix is structural, not editorial."

**Agent 4 (Alternative Structures)** produced 3 complete README openings:
- Option A: Terminal session (live the problem in 10 seconds)
- Option B: Single dramatic moment ("Session 47. Eleventh time.")
- Option C: Confidence-first (lead with numbers)

### Step 6: The Reason Query

After reviewing the wonder output, the user asked a follow-up:

```
/mem:reason Would it make sense to include a meta-demonstration of how
wonder and reason work together -- like this conversation log -- or
should we stick to the wonder's recommendations?
```

The reason system retrieved evidence, built a chain, and concluded:

```
ANSWER: Yes, create the meta-demonstration. No, don't put it in the README.

Structure:
- README: Tight, follows wonder recommendations (hook fast, install fast)
- Case study (separate doc): Full transparent session showing the pipeline

Why: Progressive disclosure. The README hooks in 10 seconds.
The case study converts skeptics who want proof of depth.
```

### Step 7: Execution

Based on the synthesized findings, the README was rewritten:

- **Before:** Pain -> generic table -> install (line 125) -> 3 narrative examples -> architecture (line 177)
- **After:** Pain -> install (line 10) -> worked example (github-push, moved up) -> concrete "you say / it stores" table -> stats block -> one example -> architecture link

The before/after table was killed. The strongest content moved to the top. Research credibility became one line ("98 experiments. 954 tests.") with a link, not a section.

## What agentmemory Contributed

Without the memory system, this session would have started from zero. The agent wouldn't have known:

- The project's version, module count, or test count
- The two-repo git workflow and publish constraints
- The user's prior frustration about research being overclaimed
- The behavioral directive to not overclaim rigor
- That the system was already in production daily use

Every one of those facts was injected automatically from prior sessions. The wonder and reason tools then used the memory graph to ground their research in project-specific context rather than generic advice.

The result: a complete marketing strategy, grounded in evidence, executed in one session -- with the memory system contributing both the research methodology and the accumulated context that made the research specific rather than generic.

## The Research Artifacts

All findings were saved automatically:

- `experiments/wonder_20260420_160000_readme_positioning.md` -- Full wonder output with 4 agent findings
- `experiments/reason_20260420_161500_meta_demo_decision.md` -- Reason chain for the meta-demo question

These persist across sessions. The next time someone asks about README positioning or marketing strategy, the system will retrieve these findings and build on them rather than starting over.
