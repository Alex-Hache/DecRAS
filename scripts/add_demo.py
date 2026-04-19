"""Ingest a segmenter-produced sequence JSON into the demo store.

Usage::

    uv run python -m scripts.add_demo datasets/sticks_v2/sequences/episode_000.json \
        --task "pick stick and place at target"

    # re-ingest (overwrite an existing demo with the same id)
    uv run python -m scripts.add_demo <path> --task "..." --overwrite

    # custom store root (defaults to <project>/demos)
    uv run python -m scripts.add_demo <path> --task "..." --store my_demos/
"""

from __future__ import annotations

import argparse
from pathlib import Path

from decras.imitation.store import DEFAULT_STORE_ROOT, ingest_sequence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sequence", type=Path, help="Segmenter output JSON to ingest")
    parser.add_argument(
        "--task",
        type=str,
        default=None,
        help="Task description (overrides the task field in the source JSON, if any)",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE_ROOT,
        help=f"Store root (default: {DEFAULT_STORE_ROOT})",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing demo with the same id",
    )
    args = parser.parse_args()

    path = ingest_sequence(
        args.sequence,
        task=args.task,
        root=args.store,
        overwrite=args.overwrite,
    )
    print(f"Wrote demo → {path}")


if __name__ == "__main__":
    main()
