"""CS-003: Overwriting State Instead of Consulting It.

Pass criterion: When a belief says "TODO.md is the task list", searching for
"what to do next" surfaces that belief. The memory system should surface
state-document awareness beliefs before the agent recreates state from scratch.
"""
from __future__ import annotations

from agentmemory.models import (
    BELIEF_FACTUAL,
    BELIEF_PROCEDURAL,
    BSRC_AGENT_INFERRED,
    BSRC_USER_STATED,
    Belief,
)
from agentmemory.retrieval import RetrievalResult, retrieve
from agentmemory.store import MemoryStore

_STATE_DOC_TEXT: str = (
    "TODO.md contains the prioritized task list. "
    "Consult it before asking what to do next."
)


def test_cs003_state_doc_belief_surfaced(store: MemoryStore) -> None:
    """Insert a locked belief about TODO.md being the task list.

    Search for 'what should I work on'. The locked belief must appear in
    results so the agent consults the file instead of recreating state.
    """
    belief: Belief = store.insert_belief(
        content=_STATE_DOC_TEXT,
        belief_type=BELIEF_PROCEDURAL,
        source_type=BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )
    assert belief.id

    # FTS5 search: tokens "task" and "list" are present in the belief content.
    results: list[Belief] = store.search("task list prioritized")
    result_ids: list[str] = [r.id for r in results]
    assert belief.id in result_ids, (
        "Expected the TODO.md state-doc belief to appear in search results. "
        f"Got IDs: {result_ids}"
    )


def test_cs003_locked_state_doc_ranks_first(store: MemoryStore) -> None:
    """Insert a locked state-doc belief and an unlocked competing belief.

    Use retrieve() and verify the locked belief ranks above the unlocked one,
    ensuring state-document awareness takes priority over exploration.
    """
    store.insert_belief(
        content=_STATE_DOC_TEXT,
        belief_type=BELIEF_PROCEDURAL,
        source_type=BSRC_USER_STATED,
        alpha=9.0,
        beta_param=0.5,
        locked=True,
    )

    store.insert_belief(
        content="We should explore new research directions for the task list.",
        belief_type=BELIEF_FACTUAL,
        source_type=BSRC_AGENT_INFERRED,
        alpha=0.5,
        beta_param=0.5,
        locked=False,
    )

    result: RetrievalResult = retrieve(store, "task list what to do next")
    assert result.beliefs, "Expected results from retrieve()"

    # The locked belief must rank above the unlocked one.
    top_belief: Belief = result.beliefs[0]
    assert top_belief.locked is True, (
        f"Expected locked state-doc belief to rank first. "
        f"Top belief: '{top_belief.content}' locked={top_belief.locked}"
    )
