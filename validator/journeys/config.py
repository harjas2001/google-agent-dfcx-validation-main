"""
config.py — Runtime constants for the DFCX validator.

Valid queue names are loaded from:
  config/valid_queue_names.txt         (your real values — gitignored)
  config/valid_queue_names.example.txt (fallback — committed placeholder)

Copy the .example file and populate it before your first run.
"""
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_CONFIG_DIR    = Path(__file__).parent.parent / "config"
_NAMES_FILE    = _CONFIG_DIR / "valid_queue_names.txt"
_NAMES_EXAMPLE = _CONFIG_DIR / "valid_queue_names.example.txt"

# ── URL routing constants ─────────────────────────────────────────────────────

# URL prefixes that classify a link as internal.
INTERNAL_URL_PREFIXES: tuple[str, ...] = ("https://vfau", "http://vfau")

# The query parameter key that must appear in every action URL.
LINK_TYPE_PARAM:    str = "link_type"
LINK_TYPE_INTERNAL: str = "internal"
LINK_TYPE_EXTERNAL: str = "external"

# Any category value whose name starts with this prefix is invalid.
INVALID_QUEUE_PREFIX: str = "ChatWeb"


# ── Check severity policy ─────────────────────────────────────────────────────
#
# The three original checks fail the build on error. The newer check families
# are introduced in warn-only mode so an existing agent with a backlog of
# findings does not turn CI red the day they are switched on.
#
# Promote a family by moving its name into STRICT_CHECKS.

WARN_ONLY_CHECKS: frozenset[str] = frozenset({
    "Routing & Reachability",
    "NLU / Training Phrases",
    "Page & Fulfillment Hygiene",
    "Agent Config Integrity",
})


def apply_severity_policy(check_label: str, severity: str) -> str:
    """
    Downgrade 'error' to 'warning' for checks still in warn-only mode.

    Args:
        check_label: The check family label (matches the report section title).
        severity:    Severity the check module produced.

    Returns:
        The severity that should actually be reported.
    """
    if severity == "error" and check_label in WARN_ONLY_CHECKS:
        return "warning"
    return severity


# ── Training phrase analysis thresholds ───────────────────────────────────────

# Token Jaccard similarity at or above which two phrases in different intents
# are treated as a near-duplicate collision. Matches the voicebot playbook.
NEAR_DUPLICATE_THRESHOLD: float = 0.6

# Phrases shorter than this many tokens are excluded from near-duplicate
# comparison — short phrases trivially collide and generate noise.
MIN_TOKENS_FOR_COMPARISON: int = 3

# A head intent with fewer than this many training phrases is considered thin.
MIN_PHRASES_PER_HEAD_INTENT: int = 10

# Known ASR mistranscriptions that collide with real words. Sourced from the
# voicebot intent analysis playbook — these are the dangerous ones, because the
# mistranscription is itself a valid English word the model will learn.
ASR_HOMOPHONES: dict[str, str] = {
    "abc": "AVC",
    "nill": "bill",
    "ball": "bill",
    "car": "card",
    "council": "cancel",
    "clothes": "close",
    "plane": "plan",
    "intellect": "internet",
    "emblem": "modem",
    "sport": "port",
    "report": "port",
    "import": "port",
    "drumming": "roaming",
    "swim": "SIM",
}


# ── Queue name loader ─────────────────────────────────────────────────────────

def load_valid_queue_names() -> frozenset[str]:
    """
    Load the set of permitted queue names from disk.

    Resolution order:
      1. config/valid_queue_names.txt  (real values, gitignored)
      2. config/valid_queue_names.example.txt  (fallback)

    Lines starting with '#' and blank lines are ignored.

    Returns:
        frozenset[str] of valid queue name strings.

    Raises:
        FileNotFoundError: If neither config file can be found.
    """
    if _NAMES_FILE.exists():
        source = _NAMES_FILE
    elif _NAMES_EXAMPLE.exists():
        source = _NAMES_EXAMPLE
        log.warning(
            "Queue names loaded from example file (%s). "
            "Copy to valid_queue_names.txt and populate with your agent's values.",
            source.name,
        )
    else:
        raise FileNotFoundError(
            f"\n[config] Queue names config file not found.\n"
            f"  Expected : {_NAMES_FILE}\n"
            f"  Fallback : {_NAMES_EXAMPLE}\n"
            f"  Action   : Copy the .example file and add your valid queue names."
        )

    names: set[str] = set()
    with open(source, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                names.add(stripped)

    return frozenset(names)
