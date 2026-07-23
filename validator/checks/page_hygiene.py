"""
page_hygiene.py — Structural and content quality checks on pages.

Rules:
  → Every page should have an entryFulfillment. A page with none says nothing
    when the customer arrives.
  → Every page should say something on entry — a text message, a Genesys
    prompt, quick replies, or a carousel. A page that only sets parameters and
    routes on is a silent hop; that is valid, but worth surfacing.
  → A silent page that ends the session or the flow is not a transit page —
    it terminates the conversation without saying anything. Always a defect.
  → Required form parameters must have an initial prompt, otherwise the bot
    waits for a slot it never asked for.
  → Required form parameters should have reprompt handlers for no-match and
    no-input, otherwise the customer gets the flow-level fallback with no
    context.
  → Pages should carry a description. 'What is this page for' is the single
    most useful thing for anyone maintaining the agent later.
  → Conditional cases should not be empty, and every case needs a condition.
  → Customer-facing text should not contain unresolved template placeholders.
"""
import re

from validator.loader import AgentIndex, FileRecord
from validator.extractor import (
    extract_messages, extract_prompts, extract_set_parameters, form_parameters,
    walk_dicts,
)
from validator.checks.models import Finding

_CHECK = "Page & Fulfillment Hygiene"

# Placeholder patterns that should never survive into customer-facing copy.
_PLACEHOLDER = re.compile(r"(TODO|FIXME|XXX|TBC|TBD|\{\{[^}]*\}\}|<[A-Z_]{3,}>)")

# Events a required form parameter should handle.
_REPROMPT_EVENTS = ("sys.no-match-default", "sys.no-input-default")

# Built-in targets that terminate the conversation rather than continue it.
_TERMINAL_TARGETS = frozenset({
    "End Session",
    "End Flow",
    "End Flow with Failure",
    "End Flow with Cancellation",
})


def check_page_hygiene(agent: AgentIndex) -> list[Finding]:
    """
    Validate page structure and customer-facing content quality.

    Args:
        agent: Populated AgentIndex from loader.load_agent().

    Returns:
        List of Finding objects.
    """
    findings: list[Finding] = []

    for rec in agent.page_files:
        _check_entry_fulfillment(rec, findings)
        _check_description(rec, findings)
        _check_form_parameters(rec, findings)
        _check_conditional_cases(rec, findings)
        _check_placeholders(rec, findings)

    return findings


def _page_name(rec: FileRecord) -> str:
    return rec.data.get("displayName", rec.stem)


def _hands_off_to_agent(fulfillment: dict) -> bool:
    """
    True if the fulfillment emits a liveAgentHandoff directive.

    That is a real response — it transfers the customer to a human — it simply
    carries no text of its own, so the text extractors do not see it.
    """
    return any("liveAgentHandoff" in node for node in walk_dicts(fulfillment))


def _check_entry_fulfillment(rec: FileRecord, findings: list[Finding]) -> None:
    entry = rec.data.get("entryFulfillment")

    if not entry:
        findings.append(Finding(
            severity="warning",
            file_path=rec.relative_display,
            flow_name=rec.flow_name,
            check=_CHECK,
            message=f"Page '{_page_name(rec)}' has no entryFulfillment",
            detail="The page produces no response and sets no parameters when entered.",
        ))
        return

    said = extract_messages(entry) + extract_prompts(entry)
    if said:
        findings.append(Finding(
            severity="pass",
            file_path=rec.relative_display,
            flow_name=rec.flow_name,
            check=_CHECK,
            message=f"Page '{_page_name(rec)}' responds on entry",
            detail=f"First line: {said[0][:120]}",
        ))
        return

    if _hands_off_to_agent(entry):
        findings.append(Finding(
            severity="pass",
            file_path=rec.relative_display,
            flow_name=rec.flow_name,
            check=_CHECK,
            message=f"Page '{_page_name(rec)}' hands the customer to a live agent",
            detail="Emits a liveAgentHandoff directive — a human responds next.",
        ))
        return

    # A silent page that hands on to another page is a transit hop — normal.
    # A silent page whose every route terminates is a dead end the customer
    # experiences as the bot going quiet and the conversation closing.
    #
    # Two exemptions:
    #   - A page with any non-terminal route can still continue, so it is not a
    #     guaranteed dead end.
    #   - A page that assigns 'category' is handing the customer to a live-agent
    #     queue; the human speaks next, so bot silence there is by design.
    targets = [
        route.get("targetPage")
        for route in rec.data.get("transitionRoutes", [])
        if isinstance(route, dict) and isinstance(route.get("targetPage"), str)
    ]
    assigns_queue = any(
        name == "category" for name, _ in extract_set_parameters(entry)
    )
    terminal = sorted(set(targets))

    if targets and all(t in _TERMINAL_TARGETS for t in targets) and not assigns_queue:
        findings.append(Finding(
            severity="error",
            file_path=rec.relative_display,
            flow_name=rec.flow_name,
            check=_CHECK,
            message=(
                f"Page '{_page_name(rec)}' ends the conversation without saying "
                f"anything ({', '.join(terminal)})"
            ),
            detail="The customer's last turn is answered with silence, then the session closes.",
        ))
    else:
        findings.append(Finding(
            severity="warning",
            file_path=rec.relative_display,
            flow_name=rec.flow_name,
            check=_CHECK,
            message=f"Page '{_page_name(rec)}' says nothing on entry",
            detail="entryFulfillment sets parameters or routes only — silent transit page.",
        ))


def _check_description(rec: FileRecord, findings: list[Finding]) -> None:
    if not str(rec.data.get("description", "")).strip():
        findings.append(Finding(
            severity="warning",
            file_path=rec.relative_display,
            flow_name=rec.flow_name,
            check=_CHECK,
            message=f"Page '{_page_name(rec)}' has no description",
            detail="Undocumented pages make the agent hard to hand over or audit.",
        ))


def _check_form_parameters(rec: FileRecord, findings: list[Finding]) -> None:
    for param in form_parameters(rec.data):
        name = param.get("displayName", "(unnamed)")
        if not param.get("required"):
            continue

        behaviour = param.get("fillBehavior") or {}
        initial = behaviour.get("initialPromptFulfillment") or {}

        if not (extract_messages(initial) + extract_prompts(initial)):
            findings.append(Finding(
                severity="error",
                file_path=rec.relative_display,
                flow_name=rec.flow_name,
                check=_CHECK,
                message=(
                    f"Required parameter '{name}' on page '{_page_name(rec)}' has no "
                    f"initial prompt"
                ),
                detail="The bot will wait for a value it never asked the customer for.",
            ))

        handled = {
            h.get("event")
            for h in behaviour.get("repromptEventHandlers", [])
            if isinstance(h, dict)
        }
        missing = [e for e in _REPROMPT_EVENTS if e not in handled]
        if missing:
            findings.append(Finding(
                severity="warning",
                file_path=rec.relative_display,
                flow_name=rec.flow_name,
                check=_CHECK,
                message=(
                    f"Required parameter '{name}' on page '{_page_name(rec)}' has no "
                    f"handler for: {', '.join(missing)}"
                ),
                detail="Without a reprompt handler the customer drops to the flow-level fallback.",
            ))


def _check_conditional_cases(rec: FileRecord, findings: list[Finding]) -> None:
    for node in walk_dicts(rec.data):
        cases = node.get("conditionalCases")
        if not isinstance(cases, list):
            continue
        for group in cases:
            if not isinstance(group, dict):
                continue
            for case in group.get("cases", []):
                if not isinstance(case, dict):
                    continue
                content = case.get("caseContent") or []
                condition = str(case.get("condition", "")).strip()
                # The final else-branch legitimately has no condition, but it
                # must still produce content.
                if not content:
                    findings.append(Finding(
                        severity="warning",
                        file_path=rec.relative_display,
                        flow_name=rec.flow_name,
                        check=_CHECK,
                        message=(
                            f"Page '{_page_name(rec)}' has an empty conditional case"
                            + (f" for condition: {condition}" if condition else "")
                        ),
                        detail="The branch matches but produces no response.",
                    ))


def _check_placeholders(rec: FileRecord, findings: list[Finding]) -> None:
    for text in extract_messages(rec.data) + extract_prompts(rec.data):
        match = _PLACEHOLDER.search(text)
        if match:
            findings.append(Finding(
                severity="error",
                file_path=rec.relative_display,
                flow_name=rec.flow_name,
                check=_CHECK,
                message=(
                    f"Customer-facing text on page '{_page_name(rec)}' contains an "
                    f"unresolved placeholder: '{match.group(0)}'"
                ),
                detail=f"Text: {text[:150]}",
            ))
