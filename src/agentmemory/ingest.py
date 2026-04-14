"""End-to-end ingest pipeline: extraction -> classification -> store.

Provides two paths:
- ingest_turn(): Fast path for live conversation turns (offline classification).
- extract_turn() + create_beliefs_from_classified(): Two-phase path for batch
  operations like onboard, where LLM subagents classify before belief creation.

Also handles JSONL batch ingestion from conversation-logger.sh hook output.
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
    Observation,
)
from agentmemory.relationship_detector import detect_relationships
from agentmemory.store import MemoryStore
from agentmemory.supersession import check_temporal_supersession


# ---------------------------------------------------------------------------
# Result dataclasses
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


@dataclass
class ExtractedTurn:
    """Result of extract_turn(): observation created, sentences ready for classification."""
    observation: Observation
    sentences: list[tuple[str, str]]  # (text, source) pairs
    full_text_is_correction: bool
    source: str
    created_at: str | None


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
# Phase 1: Extract (observation + sentences, no beliefs)
# ---------------------------------------------------------------------------


def extract_turn(
    store: MemoryStore,
    text: str,
    source: str,
    session_id: str | None = None,
    created_at: str | None = None,
    source_path: str = "",
    source_id: str = "",
) -> ExtractedTurn:
    """Extract observations and sentences from a conversation turn.

    Creates an observation in the store and extracts sentences for classification.
    Does NOT create beliefs -- that happens in create_beliefs_from_classified()
    after LLM classification, or via ingest_turn() for the fast offline path.

    source_id should be a unique identifier for the source (file path, commit SHA,
    turn ID), NOT the source type string. Falls back to source_path if empty.
    """
    resolved_source_id: str = source_id or source_path or ""
    observation: Observation = store.insert_observation(
        content=text,
        observation_type=OBS_TYPE_CONVERSATION,
        source_type=source,
        source_id=resolved_source_id,
        source_path=source_path,
        session_id=session_id,
    )

    sentences: list[str] = extract_sentences(text)
    sentence_pairs: list[tuple[str, str]] = [(s, source) for s in sentences]

    full_text_is_correction: bool = False
    if source == "user":
        is_corr, _signals, _conf = detect_correction(text)
        if is_corr:
            full_text_is_correction = True

    return ExtractedTurn(
        observation=observation,
        sentences=sentence_pairs,
        full_text_is_correction=full_text_is_correction,
        source=source,
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# Phase 2: Create beliefs from pre-classified sentences
# ---------------------------------------------------------------------------


def create_beliefs_from_classified(
    store: MemoryStore,
    observation: Observation,
    classified: list[ClassifiedSentence],
    source: str,
    full_text_is_correction: bool = False,
    full_text: str = "",
    created_at: str | None = None,
    event_time: str | None = None,
    session_id: str | None = None,
    classified_by: str = "offline",
) -> IngestResult:
    """Create beliefs from pre-classified sentences.

    Accepts ClassifiedSentence objects (from either offline or LLM classification)
    and creates beliefs with appropriate types and priors. Handles correction
    supersession.

    This is the second phase of the two-phase ingest path:
    extract_turn() -> classify (LLM or offline) -> create_beliefs_from_classified()

    event_time: bitemporal timestamp for when the fact occurred.
    session_id: session that created these beliefs.
    """
    result: IngestResult = IngestResult()

    for cs in classified:
        if not cs.persist:
            continue

        belief_source: str
        if cs.sentence_type == "CORRECTION":
            belief_source = BSRC_USER_CORRECTED
        elif source == "user":
            belief_source = BSRC_USER_STATED
        else:
            belief_source = BSRC_AGENT_INFERRED

        belief_type: str = _TYPE_TO_BELIEF.get(cs.sentence_type, "factual")

        belief = store.insert_belief(
            content=cs.text,
            belief_type=belief_type,
            source_type=belief_source,
            alpha=cs.alpha,
            beta_param=cs.beta_param,
            locked=False,
            observation_id=observation.id,
            created_at=created_at,
            event_time=event_time,
            session_id=session_id,
            classified_by=classified_by,
        )
        result.beliefs_created += 1
        result.sentences_persisted += 1

        check_temporal_supersession(store, belief)
        detect_relationships(store, belief)

        if cs.sentence_type == "CORRECTION":
            raw_words: list[str] = [
                re.sub(r"[^\w]", "", w) for w in cs.text.split() if len(w) > 3
            ]
            search_terms: list[str] = [w for w in raw_words if w]
            if search_terms:
                query_str: str = " ".join(search_terms[:5])
                existing_beliefs = store.search(query_str, top_k=5)
                for existing in existing_beliefs:
                    if existing.id == belief.id:
                        continue
                    if existing.valid_to is not None:
                        continue
                    if existing.superseded_by is not None:
                        continue
                    if existing.belief_type == belief_type:
                        store.supersede_belief(
                            old_id=existing.id,
                            new_id=belief.id,
                            reason="correction",
                        )
                        break

    # Fallback: full turn flagged as correction but no sentence classified as such
    if full_text_is_correction and result.sentences_persisted == 0 and full_text:
        store.insert_belief(
            content=full_text,
            belief_type="correction",
            source_type=BSRC_USER_CORRECTED,
            alpha=9.0,
            beta_param=1.0,
            locked=False,
            observation_id=observation.id,
            created_at=created_at,
            event_time=event_time,
            session_id=session_id,
        )
        result.beliefs_created += 1
        result.sentences_persisted += 1

    return result


# ---------------------------------------------------------------------------
# Combined path: extract + offline classify + create beliefs (live turns)
# ---------------------------------------------------------------------------


def ingest_turn(
    store: MemoryStore,
    text: str,
    source: str,
    session_id: str | None = None,
    created_at: str | None = None,
    source_path: str = "",
    source_id: str = "",
    event_time: str | None = None,
) -> IngestResult:
    """Process a single conversation turn end-to-end (fast path).

    Uses offline classification for speed. Suitable for live conversation
    turns via hooks. For batch operations (onboard), use extract_turn()
    + LLM classification + create_beliefs_from_classified() instead.
    """
    extracted: ExtractedTurn = extract_turn(
        store, text, source, session_id, created_at, source_path,
        source_id=source_id,
    )

    result: IngestResult = IngestResult()
    result.observations_created = 1
    result.sentences_extracted = len(extracted.sentences)
    if extracted.full_text_is_correction:
        result.corrections_detected += 1

    if not extracted.sentences:
        return result

    classified: list[ClassifiedSentence] = classify_sentences_offline(
        extracted.sentences,
    )

    belief_result: IngestResult = create_beliefs_from_classified(
        store=store,
        observation=extracted.observation,
        classified=classified,
        source=source,
        full_text_is_correction=extracted.full_text_is_correction,
        full_text=text,
        created_at=created_at,
        event_time=event_time,
        session_id=session_id,
    )
    result.merge(belief_result)

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

            turn_result: IngestResult = ingest_turn(
                store=store,
                text=text_val,
                source=event_val,
                session_id=None,
            )
            aggregate.merge(turn_result)

    return aggregate
