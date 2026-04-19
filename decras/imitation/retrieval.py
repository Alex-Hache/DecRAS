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
            "episode": 3,
            "density": "medium",
            "start_ee_position": {"x": 0.19, "y": 0.05, "z": 0.12},
            "created_at": "2026-04-19T10:12:00+00:00",
            "source_sequence_path": "datasets/sticks_v1/sequences/episode_003.json",
            "segmenter_git_sha": "c67b970"
        }
    }

Only ``dataset`` and ``episode`` are required in metadata; the rest are
populated by the ingest pipeline (``decras.imitation.store``) and carry
provenance information (when/where/which version of the segmenter produced
this demo).
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any


@dataclass
class Primitive:
    """A single MCP tool call extracted from a demonstration."""

    tool: str
    args: dict[str, Any]
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "args": dict(self.args), "timestamp": self.timestamp}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Primitive":
        return cls(
            tool=data["tool"],
            args=dict(data.get("args", {})),
            timestamp=float(data["timestamp"]),
        )


@dataclass
class DemoMetadata:
    """Provenance info linking a demo back to its source recording."""

    dataset: str
    episode: int
    density: str | None = None
    start_ee_position: dict[str, float] | None = None
    created_at: str | None = None
    source_sequence_path: str | None = None
    segmenter_git_sha: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"dataset": self.dataset, "episode": self.episode}
        for f in fields(self):
            if f.name in ("dataset", "episode"):
                continue
            value = getattr(self, f.name)
            if value is not None:
                out[f.name] = value
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DemoMetadata":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Demo:
    """A fully decomposed demonstration ready for storage and retrieval."""

    task: str
    primitives: list[Primitive] = field(default_factory=list)
    metadata: DemoMetadata = field(
        default_factory=lambda: DemoMetadata(dataset="", episode=0)
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "primitives": [p.to_dict() for p in self.primitives],
            "metadata": self.metadata.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Demo":
        return cls(
            task=data["task"],
            primitives=[Primitive.from_dict(p) for p in data.get("primitives", [])],
            metadata=DemoMetadata.from_dict(data.get("metadata", {})),
        )
