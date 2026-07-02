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
