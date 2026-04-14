
Honest answer -- here's what actually changed vs what existed:

  Before this session

  The prototype had time as a flat scalar:
  - created_at timestamp on every belief (but no index on it -- every temporal
  query was a full table scan)
  - valid_to set when superseded
  - decay_factor() computed 0.5^(age/half_life) per belief type
  - SUPERSEDES edges linking corrections to what they replaced (but 70% orphaned)
  - 50 TEMPORAL_NEXT edges between git commits (useless -- they connected commit
  nodes, not beliefs)

  That's it. Time was a number that made old things score lower.

  After this session

  Data foundation fixes (things that were broken):
  - source_id was storing "document" instead of actual file paths -- fixed
  - No index on created_at -- added (plus composite (created_at, valid_to) for
  windowed queries)
  - event_time column separates "when the fact occurred" from "when we ingested it"
   (bitemporal)
  - session_id on beliefs links them to the session that created them
  - Session velocity computed at completion (sprint/moderate/steady/deep)

  New capabilities that didn't exist:
  - timeline(topic, start, end) -- time-ordered beliefs with filters. Before:
  impossible without raw SQL.
  - evolution(belief_id) -- walks SUPERSEDES chains bidirectionally. Before: you
  could see superseded_by on one belief but couldn't follow the full chain.
  - diff(since) -- ADDED/REMOVED/EVOLVED since a timestamp. Before: completely
  impossible. This answers "what changed since my last session?" which is the most
  common session-start question.
  - search_at_time(query, at_time) -- "what did we know about X at time T?" Before:
   impossible.
  - velocity_scale() in scoring -- sprint-origin beliefs decay 10x faster. Before:
  all beliefs decayed at the same rate regardless of how carefully they were
  produced.
  - confidence_history table -- every feedback/lock/supersede event snapshots
  (alpha, beta). Before: only current values stored, trajectory lost.

  What it does NOT do (yet)

  - Does not improve retrieval quality for normal queries. search("HRR
  architecture") returns the same results. The temporal tools are orthogonal --
  they answer different questions.
  - Velocity-scaled decay shows only 1.38x separation on a 2-day-old DB. Needs
  weeks to matter.
  - No structural temporal edges between beliefs (and the data says we don't need
  them -- 0% timestamp collisions).
  - No episodic layer (raw conversation turns as audit trail).
  - No cross-session topic continuity.

  The real value

  The 3 new MCP tools cover query types that were literally impossible before. Exp
  74 confirmed: 3 of 10 temporal queries return zero useful results from keyword
  search. The diff() tool alone -- "what changed since last session?" -- is
  something every session-start should use but couldn't.

  The confidence_history table is a long-term investment. Right now it has 0 rows.
  In a month, it'll have trajectory data that lets us distinguish "once-trusted
  belief that decayed" from "always-mediocre belief." That distinction matters for
  re-testing