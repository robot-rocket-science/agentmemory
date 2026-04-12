"""End-to-end ingest pipeline: extraction -> classification -> store.

Connects extract_sentences, classify_sentences_offline, detect_correction, and MemoryStore
into a single call per conversation turn. Also handles JSONL batch ingestion from
the conversation-logger.sh hook output format.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from agentmemory.classification import (
    ClassifiedSentence,
    classify_sentences_offline,
)
from agentmemory.correction_detection import detect_correction
from agentmemory.extraction import extract_sentences
from agentmemory.models import (
    BSRC_AGENT_INFERRED,
    BSRC_USER_CORRECTED,
    BSRC_USER_STATED,
    OBS_TYPE_CONVERSATION,
)
from agentmemory.store import MemoryStore
from agentmemory.supersession import check_temporal_supersession


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class IngestResult:
    observations_created: int = field(default=0)
    beliefs_created: int = field(default=0)
    corrections_detected: int = field(default=0)
    sentences_extracted: int = field(default=0)
    sentences_persisted: int = field(default=0)

    def merge(self, other: "IngestResult") -> None:
        """Add counts from another IngestResult into this one."""
        self.observations_created += other.observations_created
        self.beliefs_created += other.beliefs_created
        self.corrections_detected += other.corrections_detected
        self.sentences_extracted += other.sentences_extracted
        self.sentences_persisted += other.sentences_persisted


# ---------------------------------------------------------------------------
# Type-to-belief-type mapping
# ---------------------------------------------------------------------------

# Map Exp 61 classification types to agentmemory belief_type values.
_TYPE_TO_BELIEF: dict[str, str] = {
    "REQUIREMENT":  "requirement",
    "CORRECTION":   "correction",
    "PREFERENCE":   "preference",
    "FACT":         "factual",
    "ASSUMPTION":   "factual",
    "DECISION":     "factual",
    "ANALYSIS":     "factual",
    "COORDINATION": "factual",
    "QUESTION":     "factual",
    "META":         "factual",
}


# ---------------------------------------------------------------------------
# Single turn ingest
# ---------------------------------------------------------------------------


def ingest_turn(
    store: MemoryStore,
    text: str,
    source: str,
    session_id: str | None = None,
    created_at: str | None = None,
    source_path: str = "",
) -> IngestResult:
    """Process a single conversation turn end-to-end.

    Uses offline classification only. LLM-quality classification is handled
    externally by spawning Haiku subagents and calling the reclassify MCP tool.
    See build_classification_prompt() in classification.py.

    Steps:
    1. Insert raw text as observation
    2. Extract sentences
    3. Run correction detector on full text (if source == 'user')
    4. Classify sentences (offline heuristics)
    5. For each PERSIST sentence: insert as belief with type-based prior
    6. For corrections: create locked belief, attempt to find and supersede existing

    Returns IngestResult with counts.
    """
    result: IngestResult = IngestResult()

    # Step 1: insert raw text as observation
    observation = store.insert_observation(
        content=text,
        observation_type=OBS_TYPE_CONVERSATION,
        source_type=source,
        source_id=source,
        source_path=source_path,
        session_id=session_id,
    )
    result.observations_created = 1

    # Step 2: extract sentences
    sentences: list[str] = extract_sentences(text)
    result.sentences_extracted = len(sentences)

    if not sentences:
        return result

    # Step 3: run correction detector on full text (user turns only)
    full_text_is_correction: bool = False
    if source == "user":
        is_corr, _signals, _conf = detect_correction(text)
        if is_corr:
            full_text_is_correction = True
            result.corrections_detected += 1

    # Step 4: classify sentences (offline heuristics)
    sentence_pairs: list[tuple[str, str]] = [(s, source) for s in sentences]
    classified: list[ClassifiedSentence] = classify_sentences_offline(sentence_pairs)

    # Step 5: insert PERSIST sentences as beliefs
    for cs in classified:
        if not cs.persist:
            continue

        # Determine belief source type based on sentence type and source
        belief_source: str
        if cs.sentence_type == "CORRECTION":
            belief_source = BSRC_USER_CORRECTED
        elif source == "user":
            belief_source = BSRC_USER_STATED
        else:
            belief_source = BSRC_AGENT_INFERRED

        belief_type: str = _TYPE_TO_BELIEF.get(cs.sentence_type, "factual")

        # Step 6: corrections are locked (permanent constraints).
        # User-stated beliefs from remember() are also locked at the server layer.
        # Corrections get high confidence but are NOT auto-locked.
        # Only explicit user confirmation via lock() creates locked beliefs.

        belief = store.insert_belief(
            content=cs.text,
            belief_type=belief_type,
            source_type=belief_source,
            alpha=cs.alpha,
            beta_param=cs.beta_param,
            locked=False,
            observation_id=observation.id,
            created_at=created_at,
        )
        result.beliefs_created += 1
        result.sentences_persisted += 1

        # Temporal supersession: check if this belief supersedes an older
        # one about the same topic (time + term overlap).
        check_temporal_supersession(store, belief)

        # For corrections: search for existing beliefs that might be superseded
        if cs.sentence_type == "CORRECTION":
            # Extract key words from the correction sentence to search.
            # Strip non-word characters so FTS5 does not choke on punctuation.
            raw_words: list[str] = [
                re.sub(r"[^\w]", "", w) for w in cs.text.split() if len(w) > 3
            ]
            search_terms: list[str] = [w for w in raw_words if w]
            if search_terms:
                query_str: str = " ".join(search_terms[:5])
                existing_beliefs = store.search(query_str, top_k=5)
                for existing in existing_beliefs:
                    # Skip the belief we just created and already-superseded beliefs
                    if existing.id == belief.id:
                        continue
                    if existing.valid_to is not None:
                        continue
                    if existing.superseded_by is not None:
                        continue
                    # Only supersede beliefs with the same type (corrections override corrections)
                    if existing.belief_type == belief_type:
                        store.supersede_belief(
                            old_id=existing.id,
                            new_id=belief.id,
                            reason="correction",
                        )
                        break

    # If the full turn was flagged as a correction but no sentence was classified
    # as CORRECTION, insert the full text as a high-confidence belief (unlocked).
    # Locking requires explicit user confirmation via the lock() tool.
    if full_text_is_correction and result.sentences_persisted == 0:
        prior_alpha: float = 9.0
        prior_beta: float = 1.0
        store.insert_belief(
            content=text,
            belief_type="correction",
            source_type=BSRC_USER_CORRECTED,
            alpha=prior_alpha,
            beta_param=prior_beta,
            locked=False,
            observation_id=observation.id,
            created_at=created_at,
        )
        result.beliefs_created += 1
        result.sentences_persisted += 1

    return result


# ---------------------------------------------------------------------------
# JSONL batch ingest
# ---------------------------------------------------------------------------


def ingest_jsonl(
    store: MemoryStore,
    jsonl_path: str | Path,
) -> IngestResult:
    """Process a JSONL file of conversation turns (from conversation-logger.sh).

    Each line: {"timestamp": ..., "event": "user"|"assistant", "session_id": ..., "text": ...}
    Calls ingest_turn for each line. Uses offline classification only.
    Returns aggregate IngestResult.
    """
    path: Path = Path(jsonl_path)
    aggregate: IngestResult = IngestResult()

    with path.open("r", encoding="utf-8") as fh:
        for line_raw in fh:
            line_raw = line_raw.strip()
            if not line_raw:
                continue

            record: dict[str, object] = json.loads(line_raw)

            event_val: object = record.get("event")
            text_val: object = record.get("text")
            _session_val: object = record.get("session_id")

            if not isinstance(event_val, str) or not isinstance(text_val, str):
                continue
            if not text_val.strip():
                continue

            # NOTE: session_val is a Claude Code session ID, not an agentmemory session ID.
            # Pass None to avoid FK constraint violation. Observations are linked to
            # agentmemory sessions only when created during a live agentmemory session.
            turn_result: IngestResult = ingest_turn(
                store=store,
                text=text_val,
                source=event_val,
                session_id=None,
            )
            aggregate.merge(turn_result)

    return aggregate
