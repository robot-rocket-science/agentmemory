"""LLM-based entity/property/value extraction for Exp 5.

Sends batches of fact statements to Haiku and extracts structured triples.
Replaces regex triple extraction for the Treatment B condition.

This module is benchmark-only. It is NOT part of the production pipeline.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Final

import anthropic

from agentmemory.triple_extraction import FactTriple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HAIKU_MODEL: Final[str] = "claude-haiku-4-5-20251001"
BATCH_SIZE: Final[int] = (
    50  # facts per Haiku call (larger than classification; simpler task)
)

_EXTRACTION_PROMPT: Final[
    str
] = """Extract structured facts from these numbered statements.
For each statement, extract:
- entity: the primary subject (use its canonical/short name)
- property: what relationship is being stated (use snake_case)
- value: the object/answer

Normalize entity names: strip "The name of the current head of" prefixes,
use the core entity name. Examples:
- "The name of the current head of the Pittsburgh government is Bill Peduto"
  -> entity: "Pittsburgh", property: "head_of_government", value: "Bill Peduto"
- "Satyajit Ray's child is Sandip Ray"
  -> entity: "Satyajit Ray", property: "child", value: "Sandip Ray"
- "The chief executive officer of Philips is Frans van Houten"
  -> entity: "Philips", property: "ceo", value: "Frans van Houten"

Return a JSON array. For each statement, include its id number.
If a statement does not express a factual relationship, return null for that entry.

[{{"id": 1, "entity": "...", "property": "...", "value": "..."}}]

Statements:
{statements}"""


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMExtractedTriple:
    """A triple extracted by the LLM, with provenance."""

    entity: str
    property_name: str
    value: str
    serial: int | None
    source_text: str
    raw_llm_response: str  # for audit trail


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _build_batch_prompt(lines: list[tuple[int, str]]) -> str:
    """Format numbered lines into the extraction prompt."""
    block: str = "\n".join(f"{serial}. {text}" for serial, text in lines)
    return _EXTRACTION_PROMPT.format(statements=block)


def _parse_extraction_response(
    raw: str,
    lines: list[tuple[int, str]],
) -> list[FactTriple]:
    """Parse the JSON array from LLM response into FactTriple objects."""
    match: re.Match[str] | None = re.search(r"\[[\s\S]*\]", raw)
    if match is None:
        return []

    raw_items: list[object] = json.loads(match.group())
    results: list[FactTriple] = []

    # Build serial -> source_text lookup
    serial_to_text: dict[int, str] = {serial: text for serial, text in lines}

    for raw_item in raw_items:
        if raw_item is None or not isinstance(raw_item, dict):
            continue
        item: dict[str, object] = dict(raw_item)  # type: ignore[arg-type]
        raw_id: object = item.get("id", 0)
        item_id: int = int(raw_id) if isinstance(raw_id, (int, float, str)) else 0
        entity: object = item.get("entity")
        prop: object = item.get("property")
        value: object = item.get("value")

        if not entity or not prop or not value:
            continue
        if (
            not isinstance(entity, str)
            or not isinstance(prop, str)
            or not isinstance(value, str)
        ):
            continue

        entity = entity.strip()
        prop = prop.strip()
        value = value.strip()

        if not entity or not value:
            continue

        results.append(
            FactTriple(
                entity=entity,
                property_name=prop,
                value=value,
                serial=item_id if item_id > 0 else None,
                source_text=serial_to_text.get(item_id, ""),
            )
        )

    return results


def extract_triples_llm(
    lines: list[str],
    verbose: bool = False,
) -> tuple[list[FactTriple], list[dict[str, object]]]:
    """Extract triples from fact lines using Haiku LLM.

    Args:
        lines: Raw fact lines (may include serial numbers like "123. fact text")
        verbose: Print progress

    Returns:
        (triples, audit_log) where audit_log contains full prompt/response for each batch.
    """
    client: anthropic.Anthropic = anthropic.Anthropic()

    # Parse serial numbers from lines
    serial_re: re.Pattern[str] = re.compile(r"^(\d+)\.\s+(.+)$")
    parsed: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        m: re.Match[str] | None = serial_re.match(line)
        if m:
            parsed.append((int(m.group(1)), m.group(2).strip()))
        else:
            parsed.append((i + 1, line))

    all_triples: list[FactTriple] = []
    audit_log: list[dict[str, object]] = []

    # Process in batches
    total_batches: int = (len(parsed) + BATCH_SIZE - 1) // BATCH_SIZE
    for batch_idx in range(total_batches):
        start: int = batch_idx * BATCH_SIZE
        end: int = min(start + BATCH_SIZE, len(parsed))
        batch: list[tuple[int, str]] = parsed[start:end]

        prompt: str = _build_batch_prompt(batch)

        t0: float = time.monotonic()
        response = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed: float = time.monotonic() - t0

        content_block = response.content[0]
        raw_text: str = str(getattr(content_block, "text", content_block))
        triples: list[FactTriple] = _parse_extraction_response(raw_text, batch)
        all_triples.extend(triples)

        input_tok: int = response.usage.input_tokens
        output_tok: int = response.usage.output_tokens
        audit_entry: dict[str, object] = {
            "batch_idx": batch_idx,
            "batch_size": len(batch),
            "serials": [s for s, _ in batch],
            "triples_extracted": len(triples),
            "elapsed_s": round(elapsed, 3),
            "input_tokens": input_tok,
            "output_tokens": output_tok,
            "prompt": prompt[:200] + "..." if len(prompt) > 200 else prompt,
            "response_preview": raw_text[:300] + "..."
            if len(raw_text) > 300
            else raw_text,
        }
        audit_log.append(audit_entry)

        if verbose:
            print(
                f"  Batch {batch_idx + 1}/{total_batches}: "
                f"{len(triples)}/{len(batch)} extracted, "
                f"{elapsed:.1f}s, "
                f"{response.usage.input_tokens}+{response.usage.output_tokens} tokens"
            )

    return all_triples, audit_log
