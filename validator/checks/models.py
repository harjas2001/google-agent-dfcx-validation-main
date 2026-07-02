"""
models.py — Shared data types for validation findings.
"""
from dataclasses import dataclass


@dataclass
class Finding:
    """
    A single validation result produced by a check module.

    Attributes:
        severity:  "error" | "warning" | "pass"
        file_path: Relative display path of the file that produced this finding.
        flow_name: Name of the flow the file belongs to.
        check:     Short label for the specific check (e.g. "Link URL routing").
        message:   Human-readable description of the finding.
        detail:    Optional technical detail — raw value, path, etc.
    """

    severity: str
    file_path: str
    flow_name: str
    check: str
    message: str
    detail: str = ""
