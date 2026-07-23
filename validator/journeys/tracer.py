"""
tracer.py — Builds a Journey record for every sys-head intent.

A journey is everything that happens after a head intent matches:

    head intent
        │  matched by a route in a route group, flow, or page
        ▼
    entry page ──► page ──► page ──► end state
                     │
                     ├─ says   : what the bot tells the customer
                     ├─ asks   : form parameters the bot collects
                     ├─ sets   : session parameters (topic, category, ...)
                     └─ hands off: category assignment = live agent queue

Everything here is derived from the agent export — nothing is inferred. The
interpretation layer (purpose, critique, health) is the narrative pass in
JOURNEY_ANALYSIS_PLAYBOOK.md, which consumes this output.

The traversal deliberately does not follow route groups attached to the flow.
Those are global escape hatches (agent routing, small talk, FAQ) present on
almost every page; following them would make every journey span the whole
agent and tell you nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from validator.loader import AgentIndex, Intent
from validator.graph import (
    AgentGraph, PageRef, Route, SPECIAL_PAGES, SOURCE_FLOW, SOURCE_PAGE,
    SOURCE_ROUTE_GROUP, build_graph,
)
from validator.extractor import (
    extract_messages, extract_prompts, extract_set_parameters, form_parameters,
    extract_static_values, find_carousel_payloads,
)

# Session parameters that carry journey meaning rather than plumbing.
MEANINGFUL_PARAMS = ("topic", "friendlyTitle", "category", "lastPage")

# Maximum pages to walk per journey. Journeys are typically 5-30 pages; the cap
# only bites on flows with dense cross-linking.
MAX_JOURNEY_PAGES = 120

# How many sample training phrases to carry into the CSV.
SAMPLE_PHRASE_COUNT = 12


@dataclass
class JourneyStep:
    """One page in a journey."""

    depth: int
    flow: str
    page: str
    file_path: str
    description: str = ""
    says: list[str] = field(default_factory=list)
    asks: list[str] = field(default_factory=list)
    sets: dict[str, str] = field(default_factory=dict)
    has_rich_media: bool = False
    end_states: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.flow}/{self.page}"


@dataclass
class EntryPoint:
    """Where a head intent is matched, and where it goes."""

    source_kind: str
    source: str
    condition: str
    target: str
    description: str = ""
    # Some routes answer inline — the reply sits in the route's own
    # triggerFulfillment and the customer never moves to a page. That is the
    # whole journey for FAQ and small-talk intents.
    responses: list[str] = field(default_factory=list)

    @property
    def answers_inline(self) -> bool:
        return bool(self.responses) and not self.target


@dataclass
class Journey:
    """Everything derivable about one head intent's journey."""

    intent: str
    training_phrase_count: int = 0
    sample_phrases: list[str] = field(default_factory=list)
    all_phrases: list[str] = field(default_factory=list, repr=False)
    intent_parameters: list[str] = field(default_factory=list)
    entry_points: list[EntryPoint] = field(default_factory=list)
    steps: list[JourneyStep] = field(default_factory=list)

    @property
    def is_routed(self) -> bool:
        return bool(self.entry_points)

    @property
    def flows(self) -> list[str]:
        seen: list[str] = []
        for step in self.steps:
            if step.flow not in seen:
                seen.append(step.flow)
        return seen

    @property
    def page_count(self) -> int:
        return len(self.steps)

    @property
    def max_depth(self) -> int:
        return max((s.depth for s in self.steps), default=0)

    @property
    def inline_responses(self) -> list[str]:
        """Replies delivered by the entry route itself, without visiting a page."""
        out: list[str] = []
        for entry in self.entry_points:
            for line in entry.responses:
                if line not in out:
                    out.append(line)
        return out

    @property
    def answered_inline(self) -> bool:
        """True if this journey is a single inline reply rather than a page flow."""
        return not self.steps and bool(self.inline_responses)

    @property
    def all_responses(self) -> list[str]:
        """Every customer-facing line in the journey, in traversal order."""
        out: list[str] = list(self.inline_responses)
        for step in self.steps:
            out.extend(step.says)
        return out

    @property
    def questions_asked(self) -> list[str]:
        out: list[str] = []
        for step in self.steps:
            for slot in step.asks:
                if slot not in out:
                    out.append(slot)
        return out

    @property
    def topics(self) -> list[str]:
        out: list[str] = []
        for step in self.steps:
            topic = step.sets.get("topic")
            if topic and topic not in out:
                out.append(topic)
        return out

    @property
    def handoff_queues(self) -> list[str]:
        """Live-agent queues this journey can route the customer into."""
        out: list[str] = []
        for step in self.steps:
            raw = step.sets.get("category")
            if not raw:
                continue
            for value in extract_static_values(raw) or ([raw] if raw else []):
                if value and value not in out:
                    out.append(value)
        return out

    @property
    def end_states(self) -> list[str]:
        out: list[str] = []
        for step in self.steps:
            for state in step.end_states:
                if state not in out:
                    out.append(state)
        return out

    @property
    def uses_rich_media(self) -> bool:
        return any(s.has_rich_media for s in self.steps)


def trace_journeys(
    agent: AgentIndex,
    graph: AgentGraph | None = None,
) -> list[Journey]:
    """
    Build a Journey for every sys-head intent in the agent.

    Args:
        agent: Populated AgentIndex from loader.load_agent().
        graph: Prebuilt AgentGraph. Built on demand if not supplied.

    Returns:
        One Journey per head intent, ordered by intent name.
    """
    graph = graph or build_graph(agent)
    return [_trace_one(intent, agent, graph) for intent in agent.head_intents]


def _trace_one(intent: Intent, agent: AgentIndex, graph: AgentGraph) -> Journey:
    journey = Journey(
        intent=intent.display_name,
        training_phrase_count=len(intent.training_phrases),
        sample_phrases=intent.training_phrases[:SAMPLE_PHRASE_COUNT],
        all_phrases=list(intent.training_phrases),
        intent_parameters=[
            p.get("entityType", "") for p in intent.parameters if isinstance(p, dict)
        ],
    )

    starts: list[PageRef] = []

    for route in graph.routes_for_intent(intent.display_name):
        journey.entry_points.append(
            EntryPoint(
                source_kind=route.source_kind,
                source=_entry_source_label(route),
                condition=route.condition,
                target=route.target_display,
                description=route.description,
                responses=(
                    extract_messages(route.fulfillment)
                    + extract_prompts(route.fulfillment)
                ),
            )
        )
        starts.extend(_entry_pages(route, intent.display_name, graph))

    for depth, ref in graph.reachable_from(starts, max_pages=MAX_JOURNEY_PAGES):
        journey.steps.append(_build_step(depth, ref, graph))

    return journey


def _entry_source_label(route: Route) -> str:
    if route.source_kind == SOURCE_ROUTE_GROUP:
        return route.source_display
    if route.source_kind == SOURCE_PAGE:
        return f"{route.source_flow}/{route.source_page}"
    return route.source_flow


def _entry_pages(route: Route, intent_name: str, graph: AgentGraph) -> list[PageRef]:
    """Resolve the page(s) a head-intent route lands the customer on."""
    # A route group that targets a flow drops the customer on that flow's start
    # page, where the flow's own routes are re-evaluated. The matched intent
    # travels with them, so only the flow's routes for this same intent — plus
    # any condition-only route, which evaluates immediately — are entry points.
    # Following every flow-level route here would pull in every sibling
    # journey the flow happens to own.
    if route.target_flow and not route.target_page:
        if route.target_flow not in graph.flows:
            return []
        out: list[PageRef] = []
        for candidate in graph.routes:
            if candidate.source_kind != SOURCE_FLOW:
                continue
            if candidate.source_flow != route.target_flow:
                continue
            if candidate.intent and candidate.intent != intent_name:
                continue
            target = candidate.target_page
            if target and target not in SPECIAL_PAGES:
                if graph.has_page(route.target_flow, target):
                    out.append(PageRef(route.target_flow, target))
        return out

    target = route.target_page
    if not target or target in SPECIAL_PAGES:
        return []

    flow = route.target_flow or route.source_flow
    if flow and graph.has_page(flow, target):
        return [PageRef(flow, target)]

    return [PageRef(f, target) for f in graph.find_page_flows(target)]


def _build_step(depth: int, ref: PageRef, graph: AgentGraph) -> JourneyStep:
    rec = graph.pages[ref]
    data = rec.data
    entry = data.get("entryFulfillment", {})

    step = JourneyStep(
        depth=depth,
        flow=ref.flow,
        page=ref.page,
        file_path=rec.relative_display,
        description=str(data.get("description", "")).strip(),
        says=extract_messages(entry) + extract_prompts(entry),
        asks=[p.get("displayName", "") for p in form_parameters(data) if p.get("displayName")],
        has_rich_media=any(True for _ in find_carousel_payloads(data)),
    )

    for name, value in extract_set_parameters(entry):
        if name in MEANINGFUL_PARAMS and name not in step.sets:
            step.sets[name] = _stringify(value)

    for route in graph.routes_from_page(ref):
        if route.target_page in SPECIAL_PAGES:
            step.end_states.append(route.target_page)
        elif route.target_flow and not route.target_page:
            step.end_states.append(f"[flow] {route.target_flow}")

    return step


def _stringify(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value) if value is not None else ""
