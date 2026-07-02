"""
loader.py — Walks an exported Dialogflow CX agent folder and loads all
relevant JSON files into typed FileRecord objects.

Expected directory layout:
    <agent_root>/
    ├── agent.json
    └── flows/
        └── <flow_name>/
            ├── <flow_name>.json          ← flow-level file (category required)
            └── pages/
                └── <page_name>.json      ← page-level files (lastPage required)
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class FileRecord:
    """Represents a single loaded agent JSON file."""

    path: Path           # Absolute filesystem path
    flow_name: str       # Display name of the parent flow directory
    file_type: str       # "flow" or "page"
    stem: str            # Filename without the .json extension
    data: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def relative_display(self) -> str:
        """
        Human-readable path fragment starting from 'flows/'.
        Used in report output so absolute paths don't leak.
        """
        parts = self.path.parts
        try:
            idx = next(i for i, p in enumerate(parts) if p == "flows")
            return "/".join(parts[idx:])
        except StopIteration:
            return self.path.name


@dataclass
class AgentIndex:
    """All loaded files from one agent export."""

    root: Path
    flow_files: list[FileRecord] = field(default_factory=list)
    page_files: list[FileRecord] = field(default_factory=list)

    @property
    def all_files(self) -> list[FileRecord]:
        return self.flow_files + self.page_files


def load_agent(agent_root: Path) -> AgentIndex:
    """
    Walk the agent folder and load all flow and page JSON files.

    Args:
        agent_root: Root directory of the exported Dialogflow CX agent.

    Returns:
        Populated AgentIndex.

    Raises:
        FileNotFoundError: If the flows/ directory is absent.
    """
    flows_dir = agent_root / "flows"
    if not flows_dir.exists():
        raise FileNotFoundError(
            f"\n[loader] flows/ directory not found under: {agent_root}\n"
            f"  Make sure agent_folder points to the root of an exported "
            f"Dialogflow CX agent (the directory that contains agent.json "
            f"and a flows/ subdirectory)."
        )

    index = AgentIndex(root=agent_root)

    for flow_dir in sorted(flows_dir.iterdir()):
        if not flow_dir.is_dir():
            continue

        flow_name = flow_dir.name

        # ── Flow-level file: flows/<flow>/<flow>.json ─────────────────────
        flow_json = flow_dir / f"{flow_name}.json"
        if flow_json.exists():
            data = _load_json(flow_json)
            if data is not None:
                index.flow_files.append(
                    FileRecord(
                        path=flow_json,
                        flow_name=flow_name,
                        file_type="flow",
                        stem=flow_json.stem,
                        data=data,
                    )
                )
        else:
            log.warning("Flow file not found (expected): %s", flow_json)

        # ── Page-level files: flows/<flow>/pages/*.json ───────────────────
        pages_dir = flow_dir / "pages"
        if pages_dir.exists():
            for page_json in sorted(pages_dir.glob("*.json")):
                data = _load_json(page_json)
                if data is not None:
                    index.page_files.append(
                        FileRecord(
                            path=page_json,
                            flow_name=flow_name,
                            file_type="page",
                            stem=page_json.stem,
                            data=data,
                        )
                    )

    return index


def _load_json(path: Path) -> dict[str, Any] | None:
    """Parse a JSON file. Returns None and logs a warning on failure."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        log.warning("JSON parse error in %s: %s", path.name, exc)
        return None
    except OSError as exc:
        log.warning("Could not read %s: %s", path.name, exc)
        return None
