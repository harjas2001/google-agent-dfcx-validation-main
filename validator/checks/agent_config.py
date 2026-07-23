"""
agent_config.py — Agent-level and shared-resource integrity.

Rules:
  Custom payload templates
    → agent.json declares the shape of each Genesys payload under
      customPayloadTemplates. Every carousel card in the agent is checked
      against the declared template so the contract is validated against what
      the agent itself says it is, not against a hardcoded assumption.

  Entity types
    → Every entity type referenced by an intent parameter or a form parameter
      must exist in entityTypes/ (system entities excepted).
    → Entity types defined but never referenced are dead config.
    → List-kind entity types should have at least one value.

  NLU settings
    → Flows should declare NLU settings.
    → A classification threshold of 0 accepts any match; a very high one
      rejects almost everything. Both are worth surfacing.

  Test coverage
    → Head intents with no test case exercising them.
"""
from validator.loader import AgentIndex
from validator.extractor import walk_dicts, find_carousel_payloads
from validator.checks.models import Finding

_CHECK = "Agent Config Integrity"

# Threshold bounds outside which NLU matching behaviour is likely unintended.
_MIN_SANE_THRESHOLD = 0.15
_MAX_SANE_THRESHOLD = 0.85


def check_agent_config(agent: AgentIndex) -> list[Finding]:
    """
    Validate agent-level settings and shared resources.

    Args:
        agent: Populated AgentIndex from loader.load_agent().

    Returns:
        List of Finding objects.
    """
    findings: list[Finding] = []

    _check_payload_templates(agent, findings)
    _check_entity_types(agent, findings)
    _check_nlu_settings(agent, findings)
    _check_test_coverage(agent, findings)

    return findings


# ── Custom payload templates ──────────────────────────────────────────────────

def _check_payload_templates(agent: AgentIndex, findings: list[Finding]) -> None:
    templates = agent.agent_settings.get("customPayloadTemplates")
    if not isinstance(templates, list) or not templates:
        findings.append(Finding(
            severity="warning",
            file_path="agent.json",
            flow_name="agent",
            check=_CHECK,
            message="No customPayloadTemplates declared in agent.json",
            detail="Rich media payloads cannot be validated against a declared contract.",
        ))
        return

    card_template: dict | None = None
    for template in templates:
        if not isinstance(template, dict):
            continue
        payload = template.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("genesys_carousel"), list):
            cards = payload["genesys_carousel"]
            if cards and isinstance(cards[0], dict):
                card_template = cards[0]
                break

    if card_template is None:
        return

    # Fields the template marks mandatory, by its own placeholder convention
    # ("mandatoryString" vs "optionalString").
    mandatory = {
        key for key, val in card_template.items()
        if isinstance(val, str) and val.lower().startswith("mandatory")
    }
    known_fields = set(card_template)

    findings.append(Finding(
        severity="pass",
        file_path="agent.json",
        flow_name="agent",
        check=_CHECK,
        message="Carousel payload template found in agent.json",
        detail=(
            f"Declared card fields: {', '.join(sorted(known_fields))}"
            + (f"  |  mandatory: {', '.join(sorted(mandatory))}" if mandatory else "")
        ),
    ))

    for rec in agent.page_files:
        for carousel, crumb in find_carousel_payloads(rec.data):
            for idx, card in enumerate(carousel):
                if not isinstance(card, dict):
                    continue

                for field in sorted(mandatory - set(card)):
                    findings.append(Finding(
                        severity="error",
                        file_path=rec.relative_display,
                        flow_name=rec.flow_name,
                        check=_CHECK,
                        message=(
                            f"Carousel card is missing '{field}', declared mandatory by "
                            f"the agent.json payload template"
                        ),
                        detail=f"{crumb} › card[{idx}]",
                    ))

                for field in sorted(set(card) - known_fields):
                    findings.append(Finding(
                        severity="warning",
                        file_path=rec.relative_display,
                        flow_name=rec.flow_name,
                        check=_CHECK,
                        message=(
                            f"Carousel card has field '{field}' which the agent.json "
                            f"payload template does not declare"
                        ),
                        detail=f"{crumb} › card[{idx}]  |  Declared: {', '.join(sorted(known_fields))}",
                    ))


# ── Entity types ──────────────────────────────────────────────────────────────

def _check_entity_types(agent: AgentIndex, findings: list[Finding]) -> None:
    defined = {e.display_name: e for e in agent.entity_types}
    referenced: dict[str, set[str]] = {}

    def note(name: str, source: str) -> None:
        referenced.setdefault(name.lstrip("@"), set()).add(source)

    for intent in agent.intents:
        for param in intent.parameters:
            if isinstance(param, dict) and isinstance(param.get("entityType"), str):
                note(param["entityType"], intent.relative_display)

    for rec in agent.all_files:
        for node in walk_dicts(rec.data):
            entity = node.get("entityType")
            if isinstance(entity, str):
                note(entity, rec.relative_display)

    for name, sources in sorted(referenced.items()):
        if name.startswith("sys."):
            continue  # System entity — always available
        if name not in defined:
            example = sorted(sources)[0]
            findings.append(Finding(
                severity="error",
                file_path=example,
                flow_name="entityTypes",
                check=_CHECK,
                message=f"Entity type '@{name}' is referenced but not defined in entityTypes/",
                detail=f"Referenced by {len(sources)} file(s), e.g. {example}",
            ))

    for name, entity in sorted(defined.items()):
        if name not in referenced:
            findings.append(Finding(
                severity="warning",
                file_path=entity.relative_display,
                flow_name="entityTypes",
                check=_CHECK,
                message=f"Entity type '@{name}' is defined but never referenced",
                detail=f"{len(entity.entities)} value(s) maintained for nothing.",
            ))
        elif entity.kind == "KIND_LIST" and not entity.entities:
            findings.append(Finding(
                severity="error",
                file_path=entity.relative_display,
                flow_name="entityTypes",
                check=_CHECK,
                message=f"List entity type '@{name}' has no values",
                detail="A list entity with no values can never match.",
            ))


# ── NLU settings ──────────────────────────────────────────────────────────────

def _check_nlu_settings(agent: AgentIndex, findings: list[Finding]) -> None:
    for rec in agent.flow_files:
        flow_name = rec.data.get("displayName", rec.stem)
        settings = rec.data.get("nluSettings")

        if not isinstance(settings, dict) or not settings:
            findings.append(Finding(
                severity="warning",
                file_path=rec.relative_display,
                flow_name=flow_name,
                check=_CHECK,
                message=f"Flow '{flow_name}' declares no NLU settings",
                detail="The flow inherits defaults — confirm that is intended.",
            ))
            continue

        threshold = settings.get("classificationThreshold")
        if not isinstance(threshold, (int, float)):
            continue

        if threshold < _MIN_SANE_THRESHOLD:
            findings.append(Finding(
                severity="warning",
                file_path=rec.relative_display,
                flow_name=flow_name,
                check=_CHECK,
                message=(
                    f"Flow '{flow_name}' has a very low classification threshold "
                    f"({threshold:.2f})"
                ),
                detail="Low thresholds accept weak matches and cause misroutes.",
            ))
        elif threshold > _MAX_SANE_THRESHOLD:
            findings.append(Finding(
                severity="warning",
                file_path=rec.relative_display,
                flow_name=flow_name,
                check=_CHECK,
                message=(
                    f"Flow '{flow_name}' has a very high classification threshold "
                    f"({threshold:.2f})"
                ),
                detail="High thresholds reject valid matches and push customers to fallback.",
            ))
        else:
            findings.append(Finding(
                severity="pass",
                file_path=rec.relative_display,
                flow_name=flow_name,
                check=_CHECK,
                message=f"Flow '{flow_name}' classification threshold is {threshold:.2f}",
                detail=f"Model: {settings.get('modelType', 'unspecified')}",
            ))


# ── Test coverage ─────────────────────────────────────────────────────────────

def _check_test_coverage(agent: AgentIndex, findings: list[Finding]) -> None:
    if not agent.test_cases:
        return

    # A turn records the intent it matched under
    # virtualAgentOutput.triggeredIntent.name. Exports also carry an explicit
    # 'intent' key in some turn shapes, so both are collected.
    covered: set[str] = set()
    for case in agent.test_cases:
        for node in walk_dicts(case.turns):
            triggered = node.get("triggeredIntent")
            if isinstance(triggered, dict) and isinstance(triggered.get("name"), str):
                covered.add(triggered["name"])
            if isinstance(node.get("intent"), str):
                covered.add(node["intent"])

    for intent in agent.head_intents:
        if intent.display_name not in covered:
            findings.append(Finding(
                severity="warning",
                file_path=intent.relative_display,
                flow_name="testCases",
                check=_CHECK,
                message=f"Head intent '{intent.display_name}' has no test case covering it",
                detail=f"{len(agent.test_cases)} test case(s) exist; none reference this intent.",
            ))
