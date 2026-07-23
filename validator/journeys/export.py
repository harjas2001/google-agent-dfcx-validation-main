"""
export.py — Writes journey context to disk.

Two artefacts, for two audiences:

  journey_context.csv    One row per head intent. Sortable, filterable,
                         shareable — the deliverable equivalent to the voicebot
                         playbook's workbook.

  journey_context.json   Full detail per journey: every page, every response,
                         every training phrase. This is the input to the
                         narrative pass (JOURNEY_ANALYSIS_PLAYBOOK.md), which
                         needs the responses and phrases in order to critique
                         them.

If a narrative file produced by that pass is present, its columns are merged
into the CSV and made available to the HTML report.
"""
import csv
import json
from pathlib import Path
from typing import Any

from validator.journeys.tracer import Journey

# Deterministic columns — always written.
_BASE_COLUMNS = [
    "intent",
    "routed",
    "journey_type",
    "entry_points",
    "entry_conditions",
    "flows",
    "pages_in_journey",
    "max_depth",
    "topics",
    "questions_asked",
    "handoff_queues",
    "end_states",
    "uses_rich_media",
    "training_phrases",
    "first_response",
    "all_responses",
    "sample_training_phrases",
    "page_sequence",
]

# Narrative columns — populated by the LLM pass, blank until then.
_NARRATIVE_COLUMNS = [
    "purpose",
    "what_the_journey_does",
    "response_verdict",
    "response_critique",
    "training_phrase_critique",
    "coverage_gaps",
    "health",
    "recommendation",
]

JOURNEY_COLUMNS = _BASE_COLUMNS + _NARRATIVE_COLUMNS

# Cell separator. Newlines inside a CSV cell are legal but make the file
# painful to scan in a spreadsheet, so multi-values are joined on one line.
_SEP = " | "


def write_journey_csv(
    journeys: list[Journey],
    output_path: Path,
    narratives: dict[str, dict[str, str]] | None = None,
) -> None:
    """
    Write one row per head intent.

    Args:
        journeys:    Journey records from tracer.trace_journeys().
        output_path: Destination .csv path.
        narratives:  Optional {intent: {column: value}} from the narrative pass.
    """
    narratives = narratives or {}
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=JOURNEY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for journey in journeys:
            row = _journey_row(journey)
            row.update(narratives.get(journey.intent, {}))
            writer.writerow(row)


def _journey_type(journey: Journey) -> str:
    """How this journey serves the customer — the shape, in one word."""
    if not journey.is_routed:
        return "unrouted"
    if journey.answered_inline:
        return "inline answer"
    if not journey.steps:
        return "routed, no response"
    return "page flow"


def _journey_row(journey: Journey) -> dict[str, Any]:
    responses = journey.all_responses
    return {
        "intent": journey.intent,
        "routed": "yes" if journey.is_routed else "NO — unrouted",
        "journey_type": _journey_type(journey),
        "entry_points": _SEP.join(
            f"{e.source_kind}:{e.source} → {e.target}" for e in journey.entry_points
        ),
        "entry_conditions": _SEP.join(e.condition for e in journey.entry_points if e.condition),
        "flows": _SEP.join(journey.flows),
        "pages_in_journey": journey.page_count,
        "max_depth": journey.max_depth,
        "topics": _SEP.join(journey.topics),
        "questions_asked": _SEP.join(journey.questions_asked),
        "handoff_queues": _SEP.join(journey.handoff_queues),
        "end_states": _SEP.join(journey.end_states),
        "uses_rich_media": "yes" if journey.uses_rich_media else "no",
        "training_phrases": journey.training_phrase_count,
        "first_response": responses[0] if responses else "",
        "all_responses": _SEP.join(responses),
        "sample_training_phrases": _SEP.join(journey.sample_phrases),
        "page_sequence": _SEP.join(f"[{s.depth}] {s.label}" for s in journey.steps),
        **{col: "" for col in _NARRATIVE_COLUMNS},
    }


def write_journey_json(journeys: list[Journey], output_path: Path) -> None:
    """
    Write the full journey context pack.

    Includes every response and every training phrase, because the narrative
    pass is asked to critique both.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "journey_count": len(journeys),
        "journeys": [
            {
                "intent": j.intent,
                "routed": j.is_routed,
                "journey_type": _journey_type(j),
                "training_phrase_count": j.training_phrase_count,
                "training_phrases": j.all_phrases,
                "intent_parameters": j.intent_parameters,
                "inline_responses": j.inline_responses,
                "entry_points": [
                    {
                        "source_kind": e.source_kind,
                        "source": e.source,
                        "condition": e.condition,
                        "target": e.target,
                        "description": e.description,
                        "responses": e.responses,
                    }
                    for e in j.entry_points
                ],
                "flows": j.flows,
                "page_count": j.page_count,
                "max_depth": j.max_depth,
                "topics": j.topics,
                "questions_asked": j.questions_asked,
                "handoff_queues": j.handoff_queues,
                "end_states": j.end_states,
                "uses_rich_media": j.uses_rich_media,
                "steps": [
                    {
                        "depth": s.depth,
                        "page": s.label,
                        "file": s.file_path,
                        "description": s.description,
                        "says": s.says,
                        "asks": s.asks,
                        "sets": s.sets,
                        "has_rich_media": s.has_rich_media,
                        "end_states": s.end_states,
                    }
                    for s in j.steps
                ],
            }
            for j in journeys
        ],
    }

    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)


def load_narratives(path: Path) -> dict[str, dict[str, str]]:
    """
    Load narrative analysis produced by the LLM pass.

    Accepts either a list of objects or an object keyed by intent name. Each
    entry supplies any subset of the narrative columns.

    Returns {} if the file is absent or unreadable, so the pipeline degrades to
    deterministic output rather than failing.
    """
    if not path.exists():
        return {}

    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}

    entries = data.get("journeys", data) if isinstance(data, dict) else data

    out: dict[str, dict[str, str]] = {}

    if isinstance(entries, dict):
        for intent, values in entries.items():
            if isinstance(values, dict):
                out[intent] = _narrative_fields(values)
    elif isinstance(entries, list):
        for item in entries:
            if isinstance(item, dict) and isinstance(item.get("intent"), str):
                out[item["intent"]] = _narrative_fields(item)

    return out


def _narrative_fields(values: dict) -> dict[str, str]:
    return {
        col: str(values[col]) for col in _NARRATIVE_COLUMNS
        if col in values and values[col] is not None
    }
