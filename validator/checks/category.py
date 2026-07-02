"""
category.py — Validates the 'category' parameter (queue name) across
flow and page files.

Rules:
  Flow files  (flows/<flow>/<flow>.json):
    → REQUIRED: at least one 'category' value must be set somewhere in the file.
    → All static values extracted must be in the valid queue names list.
    → Values must not start with the invalid prefix (e.g. "ChatWeb").

  Page files  (flows/<flow>/pages/*.json):
    → OPTIONAL: category does not need to be set.
    → If set, all static values must be in the valid queue names list.
    → Values must not start with the invalid prefix.

Dynamic references (e.g. $session.params.category) that cannot be statically
resolved are flagged as warnings rather than errors.

$sys.func.IF() expressions are parsed and their string literal values validated.
"""
from validator.loader import AgentIndex, FileRecord
from validator.extractor import find_parameter_values, extract_static_values, is_dynamic_ref
from validator.config import load_valid_queue_names, INVALID_QUEUE_PREFIX
from validator.checks.models import Finding

_CHECK = "Queue Name (category)"


def check_category(agent: AgentIndex) -> list[Finding]:
    """
    Validate the 'category' parameter across all flow and page files.

    Args:
        agent: Populated AgentIndex from loader.load_agent().

    Returns:
        List of Finding objects.
    """
    valid_names = load_valid_queue_names()
    findings: list[Finding] = []

    for rec in agent.flow_files:
        _check_file(rec, required=True, valid_names=valid_names, findings=findings)

    for rec in agent.page_files:
        _check_file(rec, required=False, valid_names=valid_names, findings=findings)

    return findings


def _check_file(
    rec: FileRecord,
    required: bool,
    valid_names: frozenset[str],
    findings: list[Finding],
) -> None:
    raw_values = list(find_parameter_values(rec.data, "category"))

    if not raw_values:
        if required:
            findings.append(Finding(
                severity="error",
                file_path=rec.relative_display,
                flow_name=rec.flow_name,
                check=_CHECK,
                message="Flow file is missing a 'category' parameter — required for all flow files",
                detail="",
            ))
        return  # No category in page file → nothing to validate

    for raw_val, breadcrumb in raw_values:
        _validate_raw_value(raw_val, breadcrumb, rec, valid_names, findings)


def _validate_raw_value(
    raw_val: str,
    breadcrumb: str,
    rec: FileRecord,
    valid_names: frozenset[str],
    findings: list[Finding],
) -> None:
    # Purely dynamic reference — cannot validate statically
    if is_dynamic_ref(raw_val):
        findings.append(Finding(
            severity="warning",
            file_path=rec.relative_display,
            flow_name=rec.flow_name,
            check=_CHECK,
            message=f"Dynamic category value cannot be statically validated: '{raw_val}'",
            detail=f"Location: {breadcrumb}",
        ))
        return

    static_vals = extract_static_values(raw_val)

    if not static_vals:
        findings.append(Finding(
            severity="warning",
            file_path=rec.relative_display,
            flow_name=rec.flow_name,
            check=_CHECK,
            message=f"Could not extract static values from category expression: '{raw_val}'",
            detail=f"Location: {breadcrumb}",
        ))
        return

    for val in static_vals:
        _validate_single(val, raw_val, breadcrumb, rec, valid_names, findings)


def _validate_single(
    val: str,
    raw_val: str,
    breadcrumb: str,
    rec: FileRecord,
    valid_names: frozenset[str],
    findings: list[Finding],
) -> None:
    context = f"value='{val}' (from: {raw_val}) at {breadcrumb}"

    # Check forbidden prefix first
    if val.startswith(INVALID_QUEUE_PREFIX):
        findings.append(Finding(
            severity="error",
            file_path=rec.relative_display,
            flow_name=rec.flow_name,
            check=_CHECK,
            message=f"Invalid category value — starts with forbidden prefix '{INVALID_QUEUE_PREFIX}': '{val}'",
            detail=context,
        ))
        return

    # Check against allowed list
    if val not in valid_names:
        findings.append(Finding(
            severity="error",
            file_path=rec.relative_display,
            flow_name=rec.flow_name,
            check=_CHECK,
            message=f"Category value '{val}' is not in the allowed queue names list",
            detail=f"{context}  |  Allowed: {sorted(valid_names)}",
        ))
    else:
        findings.append(Finding(
            severity="pass",
            file_path=rec.relative_display,
            flow_name=rec.flow_name,
            check=_CHECK,
            message=f"Category value '{val}' is valid",
            detail=context,
        ))
