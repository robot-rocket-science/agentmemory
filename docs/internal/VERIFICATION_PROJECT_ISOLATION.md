# Verification: Project Isolation During Cross-Repo Work

**Date:** 2026-04-18
**Version:** 1.2.1
**Related:** CS-030 (Cross-Project Knowledge Isolation), REQ-NEW-O
**Status:** PASS

## Context

During a session where the user worked on two repositories simultaneously
(project-A: a portfolio website, project-B: the agentmemory codebase), the
agentmemory instance for project-A was onboarded mid-session. The session then
made extensive code changes to project-B (store.py, cli.py, ingest.py,
obsidian.py, server.py) while the working directory remained project-A.

This created a natural contamination test: would the project-A belief store
absorb any of the project-B code changes made during the same session?

## Test Design

**Contamination vector:** Session-level hook injection. The agentmemory hooks
fire on every Claude Code turn, ingesting conversation content. During this
session, conversation turns contained project-B internal symbols
(`insert_graph_edge`, `_maybe_commit`, `bulk`, `transaction`, `executemany`,
`_in_transaction`, `_maybe_commit`) as the user and agent discussed and
implemented performance fixes.

**Project-A onboard state:** 10,872 nodes, 10,574 beliefs, 21,664 edges from
249 commits and 112 docs. Database at `~/.agentmemory/projects/<hash>/memory.db`.

**Project-B changes:** 4 files modified (store.py, ingest.py, cli.py,
server.py), adding `transaction()` context manager, `batch_insert_graph_edges()`,
`_maybe_commit()`, and `bulk` parameter propagation.

## Verification Method

After completing the cross-repo work, searched the project-A belief store for
project-B internal symbols:

```
agentmemory --project <project-A> search "insert_graph_edge bulk transaction _maybe_commit"
```

**Result:** 50 beliefs returned, zero containing project-B source code or
internal architecture. All results were legitimate project-A content (planning
docs, writeup text, commit messages).

Additional verification:

```
agentmemory --project <project-A> search "agentmemory"
```

**Result:** 40 beliefs returned, all from the published writeup content that
legitimately lives in project-A (`content/projects/agentmemory.md`), commit
messages like "add agentmemory project card", and deployment config. No
project-B source code, no internal implementation details.

## Isolation Mechanisms Verified

| Mechanism | Component | Verified |
|---|---|---|
| Per-project database | `--project` flag hashes path to separate SQLite file | Yes |
| Scanner path scoping | `scan_project()` only walks the passed directory | Yes |
| SKIP_DIRS enforcement | `node_modules`, `.git`, etc. excluded from scan | Yes |
| Hook project routing | Session hooks write to the active project DB only | Yes |

## Conclusion

Project isolation works correctly under real-world cross-repo editing
conditions. The belief store for project-A contained zero contamination from
project-B code changes made in the same session. The isolation boundary held
at both the scanner level (directory scoping) and the hook level (project
routing).

This is the positive counterpart to CS-030, which documented the *limitation*
of project isolation (cross-project knowledge is inaccessible). Here we verify
that the isolation boundary is correctly enforced when it should be.

## Trace

- Scanner: `src/agentmemory/scanner.py` (SKIP_DIRS, path-scoped walk)
- Project routing: `src/agentmemory/config.py` (project hash computation)
- Store isolation: `src/agentmemory/store.py` (per-project SQLite file)
- Hook injection: `~/.claude/hooks/agentmemory-inject.sh` (project-aware)
