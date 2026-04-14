---
  Agentmemory: Design vs Reality Audit

  THE LIVE BUG (blocking)

  search is broken. Every call to mcp__agentmemory__search fails with no such
  column: feedback_given.

  Root cause: store.py:262 -- _migrate_sessions() adds 5 columns to existing DBs
  but misses feedback_given. The schema at line 39 defines it, so fresh DBs work.
  But your live DB was created before feedback_given was added, and the migration
  never backfills it.

  Crash path: search() -> _process_auto_feedback() ->
  increment_session_metrics(feedback_given=count) -> SQL feedback_given =
  feedback_given + ? -> boom.

  Fix: Add "feedback_given" to the new_cols list in _migrate_sessions().

  ---
  WHAT'S WORKING

  ┌────────────────────┬──────────────────┬────────────────────────────────────┐
  │     Component      │      Status      │              Evidence              │
  ├────────────────────┼──────────────────┼────────────────────────────────────┤
  │ SQLite + WAL       │ Solid            │ 9-table schema, crash recovery,    │
  │ persistence        │                  │ content-hash dedup                 │
  ├────────────────────┼──────────────────┼────────────────────────────────────┤
  │ Observation        │ Solid            │ Insert-only, no UPDATE/DELETE      │
  │ immutability       │                  │ paths                              │
  ├────────────────────┼──────────────────┼────────────────────────────────────┤
  │ Locked beliefs +   │                  │ SessionStart hook loads them;      │
  │ L0 injection       │ Solid            │ get_locked() works; 3 locked       │
  │                    │                  │ beliefs active                     │
  ├────────────────────┼──────────────────┼────────────────────────────────────┤
  │ Correction         │                  │                                    │
  │ detection          │ Solid            │ 92% accuracy, 7 signal types       │
  │ (zero-LLM)         │                  │                                    │
  ├────────────────────┼──────────────────┼────────────────────────────────────┤
  │ FTS5 full-text     │ Solid (when      │ BM25, porter tokenizer, 100%       │
  │ search             │ search works)    │ coverage at K=30                   │
  ├────────────────────┼──────────────────┼────────────────────────────────────┤
  │ Type-aware         │ Solid            │ 55% token savings, zero meaning    │
  │ compression        │                  │ loss                               │
  ├────────────────────┼──────────────────┼────────────────────────────────────┤
  │ HRR vocabulary     │ Solid            │ Bridges 31% of vocabulary gaps     │
  │ bridge             │                  │ FTS5 misses                        │
  ├────────────────────┼──────────────────┼────────────────────────────────────┤
  │ MCP server (10     │ Mostly solid     │ search broken by migration bug;    │
  │ tools)             │                  │ other 9 tools work                 │
  ├────────────────────┼──────────────────┼────────────────────────────────────┤
  │ Project onboarding │ Solid            │ 9 extractors, auto-detects project │
  │  scanner           │                  │  type                              │
  ├────────────────────┼──────────────────┼────────────────────────────────────┤
  │ Temporal decay +   │ Working          │ MRR 0.589 -> 0.867 with            │
  │ lock boost         │                  │ LOCK_BOOST_TYPED                   │
  ├────────────────────┼──────────────────┼────────────────────────────────────┤
  │                    │ 234 tests, good  │                                    │
  │ Test suite         │ baseline         │                                    │
  │                    │ coverage         │                                    │
  └────────────────────┴──────────────────┴────────────────────────────────────┘

  WHAT'S NOT WORKING

  1. search is down (migration bug above)

  2. The feedback loop has never fired in production. record_test_result() exists
  in code, the auto-feedback system in server.py is wired, but because search
  crashes before it can process feedback, no confidence updates have ever happened.
   All 16,069 beliefs sit at their ingestion priors. Thompson sampling on uniform
  priors = random noise.

  3. 2,592 correction-type beliefs are NOT locked. Bulk-ingested corrections via
  onboard/ingest get belief_type=correction but locked=False. Only remember() and
  correct() set locked=True. The ingest pipeline doesn't auto-lock corrections.

  4. Type priors are effectively uniform. REQUIREMENT, CORRECTION, PREFERENCE,
  FACT, and ASSUMPTION all get (9.0, 1.0) = 90% confidence. There's no
  differentiation between "user stated a fact" and "agent made an assumption."

  DESIGN GAPS (designed but not built)

  ┌────────────────────────┬──────────────────────────────────────────┬────────┐
  │          Gap           │                  Impact                  │ Phase  │
  ├────────────────────────┼──────────────────────────────────────────┼────────┤
  │ Automated feedback     │ Core value prop untested -- beliefs      │ Phase  │
  │ detection              │ can't improve over time                  │ 3      │
  ├────────────────────────┼──────────────────────────────────────────┼────────┤
  │ Output gating          │ Locked beliefs inform but don't block    │ Phase  │
  │                        │ violating output                         │ 4      │
  ├────────────────────────┼──────────────────────────────────────────┼────────┤
  │ Contradiction          │ No semantic conflict alerting on insert  │ Phase  │
  │ detection              │                                          │ 3      │
  ├────────────────────────┼──────────────────────────────────────────┼────────┤
  │ Triggered beliefs (15  │ Simulated 5/5 pass, not wired to         │ Phase  │
  │ designs)               │ production events                        │ 4      │
  ├────────────────────────┼──────────────────────────────────────────┼────────┤
  │ L1 behavioral layer    │ Design has L0/L1/L2/L3; implementation   │ Phase  │
  │                        │ skips L1                                 │ 3      │
  ├────────────────────────┼──────────────────────────────────────────┼────────┤
  │ Provenance metadata    │ No rigor tier, method, sample size       │ Phase  │
  │                        │ fields                                   │ 5      │
  ├────────────────────────┼──────────────────────────────────────────┼────────┤
  │ Session velocity       │ No items/hour maturity signal            │ Phase  │
  │ tracking               │                                          │ 5      │
  └────────────────────────┴──────────────────────────────────────────┴────────┘

  RESEARCH FINDINGS THAT CHALLENGE THE DESIGN

  These came from Exp 62-65 and are worth internalizing:

  1. Global scoring is meaningless. score_belief() without a query produces
  Thompson sampling noise on uniform confidence. FTS5 is the only real retrieval
  signal right now.
  2. Pre-prompt compilation is a red herring. On-demand retrieval (69.2% coverage)
  crushes pre-compiled context (23.1%). Don't build pre-compilation.
  3. Multi-layer extraction is regressive. Adding commit/file/AST/temporal edges to
   the graph diluted it from 586 to 16,463 nodes and reduced coverage (Exp 48).
  More nodes is not better nodes.
  4. New beliefs can't surface at scale. At 3,283 beliefs, adding 20 corrections
  produces zero drift in top-k results. The system saturates at the type level.
  5. FTS5 K=30 is too low at 15K+ corpus. That's 0.2% coverage. Needs K=50-100 at
  scale.

  STALE DOCUMENTATION

  - PIPELINE_STATUS.md says "belief graph insertion: NOT BUILT" -- false, 176 tests
   prove it works
  - TODO.md header says "No production code" -- 16 production modules exist
  - REQUIREMENTS.md shows most reqs as "Not started" -- many are partially/fully
  done

  RECOMMENDED PRIORITIES

  Immediate (unblock the system):
  1. Fix the feedback_given migration bug -- one line fix, unblocks search
  2. Auto-lock correction-type beliefs in the ingest pipeline
  3. Differentiate type priors (agent assumptions should NOT start at 90%)

  Next (enable the feedback loop -- the core differentiator):
  4. Validate that auto-feedback in server.py actually improves retrieval quality
  over time
  5. Increase FTS5 K to 50 at current corpus scale
  6. Wire _TYPE_WEIGHTS and recency_boost() into score_belief() -- they exist but
  are unused

  Then (close documentation debt):
  7. Update PIPELINE_STATUS.md, TODO.md, REQUIREMENTS.md to reflect reality