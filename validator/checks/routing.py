"""
routing.py — Validates the agent's conversation graph.

Rules:
  Head intent coverage
    → Every sys-head intent should be routed by at least one head-intent route
      group. An uncovered head intent can only ever be matched by a flow-level
      route, so it is unreachable from most of the conversation.
    → Head intent route groups are compared pairwise. An intent present in one
      brand/segment group but absent from its sibling is flagged, because that
      asymmetry is almost always an oversight rather than a decision.

  Intent reachability
    → Every intent defined in intents/ should be referenced by at least one
      route somewhere. An intent no route mentions is dead weight in the NLU
      model — it can win the match and then strand the customer.

  Reference integrity
    → Every route's intent must exist in intents/.
    → Every targetPage must resolve to a real page or a built-in page name.
    → Every targetFlow must resolve to a real flow.
    → Every route group named by a flow must exist.

  Page reachability
    → Every page should have at least one inbound route.
    → Every page should have at least one outbound route or an explicit end
      state, otherwise the conversation dead-ends there.
"""
from collections import defaultdict

from validator.loader import AgentIndex
from validator.graph import (
    AgentGraph, PageRef, SPECIAL_PAGES, SOURCE_ROUTE_GROUP, build_graph,
)
from validator.checks.models import Finding

_CHECK = "Routing & Reachability"

# Route groups whose job is to route top-level customer intents. Matched by
# prefix so head-intents-postpaid / head-intents-prepaid are both picked up.
_HEAD_GROUP_PREFIX = "head-intents"


def check_routing(agent: AgentIndex, graph: AgentGraph | None = None) -> list[Finding]:
    """
    Validate intent coverage, reference integrity and page reachability.

    Args:
        agent: Populated AgentIndex from loader.load_agent().
        graph: Prebuilt AgentGraph. Built on demand if not supplied.

    Returns:
        List of Finding objects.
    """
    graph = graph or build_graph(agent)
    findings: list[Finding] = []

    _check_head_intent_coverage(agent, findings)
    _check_head_group_symmetry(agent, findings)
    _check_intent_references(agent, graph, findings)
    _check_target_references(agent, graph, findings)
    _check_route_group_references(agent, graph, findings)
    _check_page_reachability(agent, graph, findings)

    return findings


# ── Head intent coverage ──────────────────────────────────────────────────────

def _head_groups(agent: AgentIndex) -> list:
    return [g for g in agent.route_groups if g.display_name.startswith(_HEAD_GROUP_PREFIX)]


def _check_head_intent_coverage(agent: AgentIndex, findings: list[Finding]) -> None:
    groups = _head_groups(agent)
    if not groups:
        return

    covered: set[str] = set()
    for group in groups:
        covered.update(group.intents)

    group_names = ", ".join(g.display_name for g in groups)

    for intent in agent.head_intents:
        if intent.display_name in covered:
            findings.append(Finding(
                severity="pass",
                file_path=intent.relative_display,
                flow_name="intents",
                check=_CHECK,
                message=f"Head intent '{intent.display_name}' is routed by a head-intent route group",
                detail="",
            ))
        else:
            findings.append(Finding(
                severity="error",
                file_path=intent.relative_display,
                flow_name="intents",
                check=_CHECK,
                message=(
                    f"Head intent '{intent.display_name}' is not routed by any "
                    f"head-intent route group"
                ),
                detail=(
                    f"Checked: {group_names}. Without a route group entry this "
                    f"intent can only match where a flow routes it explicitly."
                ),
            ))


def _check_head_group_symmetry(agent: AgentIndex, findings: list[Finding]) -> None:
    """Flag intents present in one head-intent group but missing from a sibling."""
    groups = _head_groups(agent)
    if len(groups) < 2:
        return

    membership = {g.display_name: set(g.intents) for g in groups}

    for name, intents in membership.items():
        for other_name, other_intents in membership.items():
            if name >= other_name:
                continue  # Compare each pair once
            for missing in sorted(intents - other_intents):
                findings.append(Finding(
                    severity="warning",
                    file_path=f"agentTransitionRouteGroups/{other_name}.json",
                    flow_name="routeGroups",
                    check=_CHECK,
                    message=(
                        f"Intent '{missing}' is routed by '{name}' but not by "
                        f"'{other_name}'"
                    ),
                    detail="Asymmetric head-intent coverage — confirm this is deliberate.",
                ))
            for missing in sorted(other_intents - intents):
                findings.append(Finding(
                    severity="warning",
                    file_path=f"agentTransitionRouteGroups/{name}.json",
                    flow_name="routeGroups",
                    check=_CHECK,
                    message=(
                        f"Intent '{missing}' is routed by '{other_name}' but not by "
                        f"'{name}'"
                    ),
                    detail="Asymmetric head-intent coverage — confirm this is deliberate.",
                ))


# ── Reference integrity ───────────────────────────────────────────────────────

def _check_intent_references(
    agent: AgentIndex,
    graph: AgentGraph,
    findings: list[Finding],
) -> None:
    known = set(agent.intents_by_name)
    referenced: dict[str, list] = defaultdict(list)

    for route in graph.routes:
        if route.intent:
            referenced[route.intent].append(route)

    # Routes pointing at an intent that does not exist.
    for intent_name, routes in sorted(referenced.items()):
        if intent_name in known:
            continue
        for route in routes:
            findings.append(Finding(
                severity="error",
                file_path=route.source_display,
                flow_name=route.source_flow or "routeGroups",
                check=_CHECK,
                message=f"Route references intent '{intent_name}' which does not exist",
                detail=f"Target: {route.target_display or '(none)'}  |  {route.breadcrumb}",
            ))

    # Intents no route mentions at all.
    for intent in agent.intents:
        if intent.display_name in referenced:
            continue
        findings.append(Finding(
            severity="warning",
            file_path=intent.relative_display,
            flow_name="intents",
            check=_CHECK,
            message=f"Intent '{intent.display_name}' is never referenced by any route",
            detail=(
                f"{len(intent.training_phrases)} training phrase(s) are training the "
                f"NLU model for an intent nothing handles."
            ),
        ))


def _check_target_references(
    agent: AgentIndex,
    graph: AgentGraph,
    findings: list[Finding],
) -> None:
    for route in graph.routes:
        if route.target_flow and route.target_flow not in graph.flows:
            findings.append(Finding(
                severity="error",
                file_path=route.source_display,
                flow_name=route.source_flow or "routeGroups",
                check=_CHECK,
                message=f"Route targets flow '{route.target_flow}' which does not exist",
                detail=route.breadcrumb,
            ))

        target = route.target_page
        if not target or target in SPECIAL_PAGES:
            continue

        # Route groups are attached to many flows, so their page targets are
        # resolved against the whole agent rather than one flow.
        if route.source_kind == SOURCE_ROUTE_GROUP:
            if not graph.find_page_flows(target):
                findings.append(Finding(
                    severity="error",
                    file_path=route.source_display,
                    flow_name="routeGroups",
                    check=_CHECK,
                    message=f"Route targets page '{target}' which does not exist in any flow",
                    detail=route.breadcrumb,
                ))
            continue

        flow = route.target_flow or route.source_flow
        if graph.has_page(flow, target):
            continue

        owners = graph.find_page_flows(target)
        if owners:
            findings.append(Finding(
                severity="warning",
                file_path=route.source_display,
                flow_name=route.source_flow,
                check=_CHECK,
                message=(
                    f"Route targets page '{target}', which does not exist in flow "
                    f"'{flow}'"
                ),
                detail=(
                    f"A page of that name exists in: {', '.join(owners)}. "
                    f"Set targetFlow explicitly to cross flows.  |  {route.breadcrumb}"
                ),
            ))
        else:
            findings.append(Finding(
                severity="error",
                file_path=route.source_display,
                flow_name=route.source_flow,
                check=_CHECK,
                message=f"Route targets page '{target}' which does not exist",
                detail=route.breadcrumb,
            ))


def _check_route_group_references(
    agent: AgentIndex,
    graph: AgentGraph,
    findings: list[Finding],
) -> None:
    known = {g.display_name for g in agent.route_groups}

    for flow_name, group_names in graph.flow_route_groups.items():
        for group_name in group_names:
            if group_name not in known:
                findings.append(Finding(
                    severity="error",
                    file_path=f"flows/{flow_name}/{flow_name}.json",
                    flow_name=flow_name,
                    check=_CHECK,
                    message=f"Flow references route group '{group_name}' which does not exist",
                    detail=f"Known route groups: {', '.join(sorted(known))}",
                ))


# ── Page reachability ─────────────────────────────────────────────────────────

def _check_page_reachability(
    agent: AgentIndex,
    graph: AgentGraph,
    findings: list[Finding],
) -> None:
    inbound: set[PageRef] = set()

    for route in graph.routes:
        target = route.target_page
        if not target or target in SPECIAL_PAGES:
            continue
        if route.source_kind == SOURCE_ROUTE_GROUP:
            for flow in graph.find_page_flows(target):
                inbound.add(PageRef(flow, target))
            continue
        flow = route.target_flow or route.source_flow
        if graph.has_page(flow, target):
            inbound.add(PageRef(flow, target))
        else:
            for owner in graph.find_page_flows(target):
                inbound.add(PageRef(owner, target))

    for ref, rec in sorted(graph.pages.items(), key=lambda kv: str(kv[0])):
        if ref not in inbound:
            findings.append(Finding(
                severity="warning",
                file_path=rec.relative_display,
                flow_name=ref.flow,
                check=_CHECK,
                message=f"Page '{ref.page}' has no inbound route — it is unreachable",
                detail="No flow, page or route group transitions to this page.",
            ))

        routes_out = graph.routes_from_page(ref)
        if not routes_out:
            findings.append(Finding(
                severity="warning",
                file_path=rec.relative_display,
                flow_name=ref.flow,
                check=_CHECK,
                message=f"Page '{ref.page}' has no outbound routes — the conversation dead-ends",
                detail="Add a transition route, or route explicitly to End Flow / End Session.",
            ))
