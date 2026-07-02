"""
extractor.py — Recursive JSON traversal utilities.

Provides two main capabilities:
  1. Find all setParameterActions entries for a given parameter name,
     extracting static string values even from $sys.func.IF() expressions.
  2. Find all genesys_carousel payload objects anywhere in a JSON structure.
"""
import re
from typing import Any, Generator


# ── Parameter extraction ──────────────────────────────────────────────────────

def find_parameter_values(
    data: Any,
    param_name: str,
) -> Generator[tuple[str, str], None, None]:
    """
    Recursively search a parsed JSON structure for setParameterActions entries
    whose 'parameter' field matches param_name.

    Args:
        data:       Root of the parsed JSON (dict, list, or scalar).
        param_name: Parameter name to search for (e.g. "category", "lastPage").

    Yields:
        (raw_value, breadcrumb) tuples where raw_value is the string assigned
        to the parameter, and breadcrumb is a dot-notation path for debugging.
    """
    yield from _walk_params(data, param_name, path="root")


def _walk_params(
    data: Any,
    param_name: str,
    path: str,
) -> Generator[tuple[str, str], None, None]:
    if isinstance(data, dict):
        # Check setParameterActions at this level before recursing
        for action in data.get("setParameterActions", []):
            if isinstance(action, dict) and action.get("parameter") == param_name:
                raw = action.get("value", "")
                yield str(raw) if raw is not None else "", path

        # Recurse into all other keys
        for key, val in data.items():
            if key != "setParameterActions":
                yield from _walk_params(val, param_name, f"{path}.{key}")

    elif isinstance(data, list):
        for i, item in enumerate(data):
            yield from _walk_params(item, param_name, f"{path}[{i}]")


def extract_static_values(raw_value: str) -> list[str]:
    """
    Extract concrete string literals from a raw parameter value.

    Handles three cases:
      - Plain literal:   "AppMsg_VF_PostpaidCare" → ["AppMsg_VF_PostpaidCare"]
      - IF expression:   "$sys.func.IF(..., 'Val1', 'Val2')" → ["Val1", "Val2"]
      - Session ref:     "$session.params.xyz" → [] (dynamic — skip validation)

    Args:
        raw_value: The raw string value from a setParameterActions entry.

    Returns:
        List of concrete string values found. Empty list means the value is
        purely dynamic and cannot be statically validated.
    """
    if not raw_value or not isinstance(raw_value, str):
        return []

    stripped = raw_value.strip()

    # Pure session / system parameter reference — not statically resolvable
    if stripped.startswith("$") and not stripped.startswith("$sys.func."):
        return []

    # $sys.func.IF(..., 'ValA', 'ValB') — extract single-quoted string literals
    if stripped.startswith("$sys.func."):
        return re.findall(r"'([^']*)'", stripped)

    # Plain string literal
    return [stripped]


def is_dynamic_ref(raw_value: str) -> bool:
    """
    Return True if raw_value is a session/system reference that cannot be
    resolved statically (e.g. "$session.params.category").
    """
    stripped = (raw_value or "").strip()
    return stripped.startswith("$") and not stripped.startswith("$sys.func.")


# ── Carousel payload extraction ───────────────────────────────────────────────

def find_carousel_payloads(data: Any) -> Generator[tuple[list, str], None, None]:
    """
    Recursively search a parsed JSON structure for genesys_carousel arrays.

    Args:
        data: Root of the parsed JSON.

    Yields:
        (carousel_list, breadcrumb) tuples where carousel_list is the list of
        card objects under the genesys_carousel key.
    """
    yield from _walk_carousels(data, path="root")


def _walk_carousels(
    data: Any,
    path: str,
) -> Generator[tuple[list, str], None, None]:
    if isinstance(data, dict):
        if "genesys_carousel" in data:
            carousel = data["genesys_carousel"]
            if isinstance(carousel, list):
                yield carousel, f"{path}.genesys_carousel"
        else:
            for key, val in data.items():
                yield from _walk_carousels(val, f"{path}.{key}")
    elif isinstance(data, list):
        for i, item in enumerate(data):
            yield from _walk_carousels(item, f"{path}[{i}]")
