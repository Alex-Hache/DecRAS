"""Replay a segmenter v2 sequence JSON on the real arm.

Reads the sequence from datasets/<name>/sequences/episode_NNN[_density].json.
Before running the primitives, positions the arm at the exact starting joint
angles from the first frame of the original Parquet recording.

Usage:
    sg dialout -c "uv run python -m scripts.replay_sequence --dataset datasets/sticks_v3 --episode 0"
    sg dialout -c "uv run python -m scripts.replay_sequence --dataset datasets/sticks_v3 --episode 0 --density high"
    uv run python -m scripts.replay_sequence --dataset datasets/sticks_v3 --episode 0 --dry-run
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# This script always runs on real hardware — force simulate off before any mcp_server import
os.environ.setdefault("SIMULATE", "false")

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))


MOTOR_ORDER = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]


def load_starting_joints(dataset_root: Path, episode: int) -> dict[str, float]:
    parquet_files = sorted(dataset_root.glob("data/chunk-*/file-*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files in {dataset_root}/data/")
    df = pd.concat([pd.read_parquet(f) for f in parquet_files], ignore_index=True)
    frames = df[df["episode_index"] == episode].sort_values("frame_index")
    if frames.empty:
        raise ValueError(f"Episode {episode} not found in {dataset_root}")
    return dict(zip(MOTOR_ORDER, frames.iloc[0]["observation.state"]))


def load_sequence(dataset_root: Path, episode: int, density: str, seq_file: str | None = None) -> list[dict]:
    if seq_file:
        seq_path = Path(seq_file)
    else:
        suffix = f"_{density}" if density != "medium" else ""
        seq_path = dataset_root / "sequences" / f"episode_{episode:03d}{suffix}.json"
    if not seq_path.exists():
        raise FileNotFoundError(f"Sequence not found: {seq_path}")
    return json.loads(seq_path.read_text())["primitives"]


def replay(primitives: list[dict], starting_joints: dict, follower_port: str, dry_run: bool):
    if dry_run:
        print(f"\nDry-run — starting joints: {starting_joints}")
        for i, p in enumerate(primitives):
            args_str = ", ".join(f"{k}={v}" for k, v in p["args"].items())
            print(f"  [{i+1:2d}] {p['tool']}({args_str})")
        return

    from mcp_server.robot.lerobot import LeRobotInterface

    print("Connecting to robot...")
    robot = LeRobotInterface(port=follower_port)  # connects in __init__
    print("Robot connected. Starting in 2s — get clear of the arm!")
    time.sleep(2.0)

    try:
        print(f"\nPositioning to recording start joints...")
        robot.send_joint_positions(starting_joints)
        time.sleep(2.0)

        for i, p in enumerate(primitives):
            tool = p["tool"]
            args = p["args"]
            args_str = ", ".join(f"{k}={v}" for k, v in args.items())
            print(f"\n[{i+1:2d}/{len(primitives)}] {tool}({args_str})")

            if tool == "move_to_delta":
                result = robot.move_cartesian_delta(args["dx"], args["dy"], args["dz"])
                print(f"  → {result}")
            elif tool == "grasp":
                result = robot.grasp(args.get("force", 3.0))
                print(f"  → {result}")
            elif tool == "release":
                result = robot.release()
                print(f"  → {result}")
            else:
                print(f"  → unknown tool '{tool}', skipping")

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        robot.stop()

    print("\nReplay complete.")


def main():
    parser = argparse.ArgumentParser(description="Replay a segmenter sequence on the real arm")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--episode", type=int, default=0)
    parser.add_argument("--density", choices=["low", "medium", "high"], default="medium")
    parser.add_argument("--seq", default=None, help="Path to a specific sequence JSON (overrides --density)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--follower-port", default=os.environ.get("LEROBOT_FOLLOWER_PORT", "/dev/ttyACM0"))
    args = parser.parse_args()

    root = Path(args.dataset)
    starting_joints = load_starting_joints(root, args.episode)
    primitives = load_sequence(root, args.episode, args.density, args.seq)

    print(f"Dataset: {root}, episode {args.episode}, density={args.density}")
    print(f"Starting joints: {starting_joints}")
    print(f"Loaded {len(primitives)} primitives")
    for i, p in enumerate(primitives):
        args_str = ", ".join(f"{k}={v}" for k, v in p["args"].items())
        print(f"  [{i+1:2d}] {p['tool']}({args_str})")

    if not args.dry_run:
        print("\nStarting replay in 3s — get clear of the arm!")
        time.sleep(3.0)

    replay(primitives, starting_joints, args.follower_port, args.dry_run)


if __name__ == "__main__":
    main()
