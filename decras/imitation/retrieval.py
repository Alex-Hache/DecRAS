"""Demo store schema for decomposed demonstrations.

Each demonstration is stored as one JSON file per episode with this structure::

    {
        "task": "pick up the red stick",
        "primitives": [
            {"tool": "move_forward", "args": {"distance": 0.05}, "timestamp": 0.0},
            {"tool": "move_down",    "args": {"distance": 0.03}, "timestamp": 0.42},
            {"tool": "grasp",        "args": {},                 "timestamp": 0.91},
            {"tool": "move_up",      "args": {"distance": 0.05}, "timestamp": 1.10}
        ],
        "metadata": {
            "dataset": "sticks_v1",
            "episode": 3
        }
    }

Fields
------
task : str
    Natural-language description of the demonstrated task. Used as the
    retrieval key when selecting few-shot examples for the LLM planner.
primitives : list[Primitive]
    Ordered sequence of MCP tool calls that the segmenter extracted from the
    continuous demonstration trajectory.  Each entry contains:
      - tool:      name of the MCP primitive (must match a server.py tool)
      - args:      keyword arguments passed to the tool (may be empty)
      - timestamp: seconds from episode start when this primitive begins
metadata : DemoMetadata
    Provenance information so we can trace a stored demo back to its source
    recording.  Contains the LeRobot dataset name and episode index.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Primitive:
    """A single MCP tool call extracted from a demonstration."""

    tool: str
    args: dict[str, Any]
    timestamp: float


@dataclass
class DemoMetadata:
    """Provenance info linking a demo back to its source recording."""

    dataset: str
    episode: int


@dataclass
class Demo:
    """A fully decomposed demonstration ready for storage and retrieval."""

    task: str
    primitives: list[Primitive] = field(default_factory=list)
    metadata: DemoMetadata = field(default_factory=lambda: DemoMetadata(dataset="", episode=0))
