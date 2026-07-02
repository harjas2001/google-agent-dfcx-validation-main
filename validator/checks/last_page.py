"""
last_page.py — Validates the 'lastPage' parameter across the entire agent.

Rules:
  → Every page (flows/<flow>/pages/*.json) must have lastPage='<page_stem>'
    set SOMEWHERE in the agent — either in:
      (a) the page's own entryFulfillment, or
      (b) a preceding page's transitionRoute that targets this page, or
      (c) the flow-level transition routes.

  → lastPage='<page_stem>' does not need to live inside the page's own JSON.
    The check is agent-wide: scan every setParameterActions in every file and
    build a map of which page stems are covered.

  → A page whose stem never appears as a lastPage value anywhere in the agent
    is flagged as an error.

  → $sys.func.IF() expressions are parsed; each branch value is indexed.
  → Pure session references ($session.params.*) cannot be statically resolved
    and are skipped (not counted as coverage, not flagged as errors).

Example:
  Page file:  flows/activation-setup/pages/activate-esim.purchase-plan.json
  stem:       activate-esim.purchase-plan

  Coverage can come from any of:
    activate-esim.purchase-plan.json   entryFulfillment.setParameterActions
    some-other-page.json               transitionRoutes[n].triggerFulfillment.setParameterActions
    activation-setup.json (flow)       transitionRoutes[n].triggerFulfillment.setParameterActions
"""
from validator.loader import AgentIndex, FileRecord
from validator.extractor import find_parameter_values, extract_static_values, is_dynamic_ref
from validator.checks.models import Finding

_CHECK = "Last Page Parameter"


def check_last_page(agent: AgentIndex) -> list[Finding]:
    """
    Validate 'lastPage' coverage for every page file by scanning the whole agent.

    Phase 1 — Index: collect every lastPage value set anywhere in the agent
               (all flow files and page files) and record which file set it.
    Phase 2 — Check: for each page file, verify its stem appears at least once
               in the index.

    Args:
        agent: Populated AgentIndex from loader.load_agent().

    Returns:
        List of Finding objects.
    """
    # ── Phase 1: build agent-wide lastPage index ──────────────────────────────
    # Maps page_stem → list of (source_file_display_path, breadcrumb)
    coverage: dict[str, list[tuple[str, str]]] = {}

    for rec in agent.all_files:
        for raw_val, crumb in find_parameter_values(rec.data, "lastPage"):
            if is_dynamic_ref(raw_val):
                continue  # $session.params.* — not statically resolvable, skip

            for val in extract_static_values(raw_val):
                if val:
                    coverage.setdefault(val, []).append((rec.relative_display, crumb))

    # ── Phase 2: check each page stem is covered ──────────────────────────────
    findings: list[Finding] = []

    for rec in agent.page_files:
        stem = rec.stem
        sources = coverage.get(stem)

        if sources:
            # Summarise where coverage came from (cap at 2 sources for readability)
            src_parts = [f"{fp}" for fp, _ in sources[:2]]
            src_str = " · ".join(src_parts)
            if len(sources) > 2:
                src_str += f" (+{len(sources) - 2} more)"

            findings.append(Finding(
                severity="pass",
                file_path=rec.relative_display,
                flow_name=rec.flow_name,
                check=_CHECK,
                message=f"lastPage='{stem}' is assigned in the agent",
                detail=f"Set in: {src_str}",
            ))
        else:
            findings.append(Finding(
                severity="error",
                file_path=rec.relative_display,
                flow_name=rec.flow_name,
                check=_CHECK,
                message=f"No lastPage='{stem}' assignment found anywhere in the agent",
                detail=(
                    f"Expected a setParameterActions entry with parameter='lastPage' "
                    f"and value='{stem}' in this page's entryFulfillment, "
                    f"or in the transitionRoute of a preceding page or flow file."
                ),
            ))

    return findings
