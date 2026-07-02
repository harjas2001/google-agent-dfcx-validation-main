"""
rich_media.py — Validates Genesys carousel payload structure in page files.

Checks applied to every genesys_carousel card found in pages/:
  1. title       — must be present and non-empty.
  2. actions     — must be present and non-empty list.
  3. action dicts — two valid shapes:
       Link:     {"type": "Link", "text": ..., "url": ...}
                 All three fields must be populated.
                 type must equal "Link".
                 url must contain ?link_type=<value>.
                 https://vfau... URLs must have link_type=internal.
                 All other URLs must have link_type=external.
       Postback: {"payload": ..., "text": ..., "type": "Postback"}
                 All three fields must be populated.
                 type must equal "Postback".
  4. defaultAction — if present, all its values must be empty strings "".
"""
import re

from validator.loader import AgentIndex, FileRecord
from validator.extractor import find_carousel_payloads
from validator.config import INTERNAL_URL_PREFIXES, LINK_TYPE_PARAM, LINK_TYPE_INTERNAL, LINK_TYPE_EXTERNAL
from validator.checks.models import Finding

_CHECK = "Rich Media"


def check_rich_media(agent: AgentIndex) -> list[Finding]:
    """
    Scan every page file for genesys_carousel payloads and validate their
    structure and link routing.

    Args:
        agent: Populated AgentIndex from loader.load_agent().

    Returns:
        List of Finding objects (errors, warnings, and passes).
    """
    findings: list[Finding] = []

    for rec in agent.page_files:
        for carousel_list, crumb in find_carousel_payloads(rec.data):
            for card_idx, card in enumerate(carousel_list):
                _check_card(card, card_idx, crumb, rec, findings)

    return findings


# ── Card-level checks ─────────────────────────────────────────────────────────

def _check_card(
    card: dict,
    card_idx: int,
    crumb: str,
    rec: FileRecord,
    findings: list[Finding],
) -> None:
    card_ref = f"card[{card_idx}]"

    # 1. title
    title = card.get("title", None)
    if title is None:
        findings.append(_err(rec, "Missing 'title' field", f"{crumb} › {card_ref}"))
    elif not str(title).strip():
        findings.append(_err(rec, "Empty 'title' field", f"{crumb} › {card_ref}"))
    else:
        findings.append(_pass(rec, f"title is populated", f"{crumb} › {card_ref} › title"))

    # 2. actions
    actions = card.get("actions", None)
    if actions is None:
        findings.append(_err(rec, "Missing 'actions' field", f"{crumb} › {card_ref}"))
        return  # Can't check individual actions
    if not isinstance(actions, list) or len(actions) == 0:
        findings.append(_err(rec, "Empty 'actions' list", f"{crumb} › {card_ref}"))
        return

    for action_idx, action in enumerate(actions):
        if isinstance(action, dict):
            _check_action(action, action_idx, crumb, card_ref, rec, findings)
        else:
            findings.append(_err(
                rec,
                f"Action[{action_idx}] is not a dictionary",
                f"{crumb} › {card_ref} › actions[{action_idx}]",
            ))

    # 3. defaultAction — all values must be empty strings
    default_action = card.get("defaultAction")
    if default_action is not None and isinstance(default_action, dict):
        _check_default_action(default_action, crumb, card_ref, rec, findings)


def _check_action(
    action: dict,
    action_idx: int,
    crumb: str,
    card_ref: str,
    rec: FileRecord,
    findings: list[Finding],
) -> None:
    action_ref = f"{crumb} › {card_ref} › actions[{action_idx}]"
    has_url     = "url" in action
    has_payload = "payload" in action

    if has_url and has_payload:
        findings.append(_err(
            rec,
            "Action has both 'url' and 'payload' — must be Link or Postback, not both",
            action_ref,
        ))
        return

    if has_url:
        _check_link_action(action, action_idx, action_ref, rec, findings)
    elif has_payload:
        _check_postback_action(action, action_idx, action_ref, rec, findings)
    else:
        findings.append(_err(
            rec,
            "Action has neither 'url' nor 'payload' — cannot determine type (expected Link or Postback)",
            action_ref,
        ))


def _check_link_action(
    action: dict,
    action_idx: int,
    action_ref: str,
    rec: FileRecord,
    findings: list[Finding],
) -> None:
    """Validate a Link-type action dict."""
    # All three fields must be populated
    for field_name in ("type", "text", "url"):
        val = action.get(field_name, None)
        if val is None:
            findings.append(_err(rec, f"Link action missing field '{field_name}'", action_ref))
        elif not str(val).strip():
            findings.append(_err(rec, f"Link action field '{field_name}' is empty", action_ref))

    # type must equal "Link"
    action_type = action.get("type", "")
    if action_type and action_type != "Link":
        findings.append(_err(
            rec,
            f"Link action has type='{action_type}' — expected 'Link'",
            action_ref,
        ))

    # URL routing validation
    url = action.get("url", "")
    if url and isinstance(url, str):
        _check_url_routing(url, action_ref, rec, findings)


def _check_postback_action(
    action: dict,
    action_idx: int,
    action_ref: str,
    rec: FileRecord,
    findings: list[Finding],
) -> None:
    """Validate a Postback-type action dict."""
    populated_fields = [
        k for k in ("payload", "text", "type")
        if str(action.get(k, "")).strip()
    ]
    # "if any one is filled all should be filled"
    if 0 < len(populated_fields) < 3:
        missing = [f for f in ("payload", "text", "type") if not str(action.get(f, "")).strip()]
        findings.append(_err(
            rec,
            f"Postback action partially filled — missing: {missing}. All three (payload, text, type) must be populated together.",
            action_ref,
        ))
    elif len(populated_fields) == 0:
        # All empty — this is the "empty action" case, treat as a warning
        findings.append(_warn(
            rec,
            "Postback action has all fields empty (payload, text, type)",
            action_ref,
        ))
    else:
        # All populated — check type value
        action_type = action.get("type", "")
        if action_type and action_type != "Postback":
            findings.append(_err(
                rec,
                f"Postback action has type='{action_type}' — expected 'Postback'",
                action_ref,
            ))
        else:
            findings.append(_pass(rec, "Postback action fields are valid", action_ref))


def _check_url_routing(
    url: str,
    action_ref: str,
    rec: FileRecord,
    findings: list[Finding],
) -> None:
    """Validate link_type parameter and internal/external routing.

    Uses regex rather than urlparse/parse_qs to handle malformed URLs seen
    in practice:
      - link_type placed after a # fragment  (...esim#abc123?link_type=external)
      - multiple ? used as separators        (...deals?title=phones?link_type=external)
    Both cases break standard URL parsing but the regex finds link_type regardless.
    """
    # Multiple ? characters in a URL is malformed — flag it even if link_type
    # can still be extracted. The # fragment case (...#anchor?link_type=x) has
    # only one ? so is not flagged here.
    if url.count("?") > 1:
        findings.append(_err(
            rec,
            "Malformed URL — contains multiple '?' characters (use '&' to separate parameters)",
            f"{action_ref} → url: {url}",
        ))

    match = re.search(r"link_type=([^&?\s#]+)", url)

    if not match:
        findings.append(_err(
            rec,
            "URL missing required 'link_type' parameter",
            f"{action_ref} → url: {url}",
        ))
        return

    link_type = match.group(1)

    if link_type not in (LINK_TYPE_INTERNAL, LINK_TYPE_EXTERNAL):
        findings.append(_err(
            rec,
            f"Unknown link_type value '{link_type}' — expected 'internal' or 'external'",
            f"{action_ref} → url: {url}",
        ))
        return

    is_internal_url = url.startswith(INTERNAL_URL_PREFIXES)

    if is_internal_url and link_type != LINK_TYPE_INTERNAL:
        findings.append(_err(
            rec,
            f"Internal URL (starts with 'https://vfau' or 'http://vfau') tagged as link_type='{link_type}' — should be 'internal'",
            f"{action_ref} → url: {url}",
        ))
    elif not is_internal_url and link_type != LINK_TYPE_EXTERNAL:
        findings.append(_err(
            rec,
            f"External URL tagged as link_type='{link_type}' — should be 'external'",
            f"{action_ref} → url: {url}",
        ))
    else:
        findings.append(_pass(
            rec,
            f"URL link_type='{link_type}' is correctly set",
            f"{action_ref} → url: {url}",
        ))


def _check_default_action(
    default_action: dict,
    crumb: str,
    card_ref: str,
    rec: FileRecord,
    findings: list[Finding],
) -> None:
    """All values in defaultAction must be empty strings."""
    non_empty = {k: v for k, v in default_action.items() if str(v).strip()}
    ref = f"{crumb} › {card_ref} › defaultAction"
    if non_empty:
        findings.append(_err(
            rec,
            f"defaultAction has non-empty field(s): {list(non_empty.keys())} — all values must be empty",
            f"{ref}: {non_empty}",
        ))
    else:
        findings.append(_pass(rec, "defaultAction is correctly empty", ref))


# ── Finding constructors ──────────────────────────────────────────────────────

def _err(rec: FileRecord, message: str, detail: str = "") -> Finding:
    return Finding(severity="error", file_path=rec.relative_display,
                   flow_name=rec.flow_name, check=_CHECK, message=message, detail=detail)


def _warn(rec: FileRecord, message: str, detail: str = "") -> Finding:
    return Finding(severity="warning", file_path=rec.relative_display,
                   flow_name=rec.flow_name, check=_CHECK, message=message, detail=detail)


def _pass(rec: FileRecord, message: str, detail: str = "") -> Finding:
    return Finding(severity="pass", file_path=rec.relative_display,
                   flow_name=rec.flow_name, check=_CHECK, message=message, detail=detail)
