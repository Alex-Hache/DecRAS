"""Demo store — write, load, and list decomposed demonstrations.

The store lives at ``demos/`` at the project root, parallel to ``datasets/``.
Each demo is one JSON file named by a deterministic id:

    <dataset>_ep<episode:03d>[_<density>].json

Determinism matters: re-segmenting the same episode at the same density should
land on the same file so segmenter tweaks overwrite the prior version instead
of piling up near-duplicates (use ``overwrite=True`` to opt in).

Provenance fields (``created_at``, ``source_sequence_path``,
``segmenter_git_sha``) are added at ingest time by :func:`ingest_sequence`.

Typical flow::

    # segmenter already ran and produced datasets/sticks_v2/sequences/episode_000.json
    ingest_sequence(Path("datasets/sticks_v2/sequences/episode_000.json"),
                    task="pick stick and place at target")
    # → writes demos/sticks_v2_ep000_medium.json

    demos = list_demos()  # [Demo, ...]
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .retrieval import Demo, DemoMetadata, Primitive

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORE_ROOT = PROJECT_ROOT / "demos"


def demo_id(metadata: DemoMetadata) -> str:
    """Stable filename stem for a demo — deterministic from (dataset, episode, density)."""
    parts = [metadata.dataset, f"ep{int(metadata.episode):03d}"]
    if metadata.density:
        parts.append(metadata.density)
    return "_".join(parts)


def demo_path(demo: Demo, root: Path = DEFAULT_STORE_ROOT) -> Path:
    return Path(root) / f"{demo_id(demo.metadata)}.json"


def save_demo(demo: Demo, root: Path = DEFAULT_STORE_ROOT, *, overwrite: bool = False) -> Path:
    """Write ``demo`` to the store. Raises :class:`FileExistsError` unless ``overwrite``."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = demo_path(demo, root)
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Demo already exists at {path}. Pass overwrite=True to replace."
        )
    path.write_text(json.dumps(demo.to_dict(), indent=2))
    return path


def load_demo(path: Path) -> Demo:
    return Demo.from_dict(json.loads(Path(path).read_text()))


def list_demos(root: Path = DEFAULT_STORE_ROOT) -> list[Demo]:
    root = Path(root)
    if not root.exists():
        return []
    return [load_demo(p) for p in sorted(root.glob("*.json"))]


def _current_git_sha() -> str | None:
    """Best-effort short HEAD sha of the project repo; None if unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=PROJECT_ROOT,
            timeout=2,
        )
        return out.stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None


def ingest_sequence(
    sequence_path: Path,
    task: str | None = None,
    root: Path = DEFAULT_STORE_ROOT,
    *,
    overwrite: bool = False,
) -> Path:
    """Wrap a segmenter-produced sequence JSON as a Demo and write it to the store.

    The source JSON is expected to match the segmenter v2 output shape::

        {"task": ..., "primitives": [...], "metadata": {"dataset", "episode", ...}}

    ``task`` overrides any task present in the source file. If neither is set,
    :class:`ValueError` is raised.
    """
    sequence_path = Path(sequence_path)
    raw = json.loads(sequence_path.read_text())

    effective_task = task if task is not None else raw.get("task")
    if not effective_task:
        raise ValueError(
            f"No task provided and none found in {sequence_path}. "
            f"Pass task=... to ingest_sequence()."
        )

    src_meta = raw.get("metadata") or {}
    if "dataset" not in src_meta or "episode" not in src_meta:
        raise ValueError(
            f"Source sequence {sequence_path} is missing metadata.dataset or metadata.episode"
        )

    try:
        src_rel = str(sequence_path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        src_rel = str(sequence_path.resolve())

    demo_meta = DemoMetadata(
        dataset=src_meta["dataset"],
        episode=int(src_meta["episode"]),
        density=src_meta.get("density"),
        start_ee_position=src_meta.get("start_ee_position"),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_sequence_path=src_rel,
        segmenter_git_sha=_current_git_sha(),
    )
    primitives = [Primitive.from_dict(p) for p in raw.get("primitives", [])]
    demo = Demo(task=effective_task, primitives=primitives, metadata=demo_meta)
    return save_demo(demo, root, overwrite=overwrite)
