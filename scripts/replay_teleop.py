"""Replay a recorded teleoperation episode on the follower arm.

Reads joint positions from the LeRobotDataset Parquet file and replays
them on the hardware at the original FPS.

Usage:
    sg dialout -c "uv run python -m scripts.replay_teleop --out datasets/sticks2"
    sg dialout -c "uv run python -m scripts.replay_teleop --out datasets/sticks2 --episode 1"
    sg dialout -c "uv run python -m scripts.replay_teleop --out datasets/sticks2 --list"
    sg dialout -c "uv run python -m scripts.replay_teleop --out datasets/sticks2 --dry-run"

Controls:
    Ctrl+C  →  stop replay
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from lerobot.utils.robot_utils import precise_sleep

MOTOR_ORDER = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]


def load_dataset(root: Path) -> tuple[pd.DataFrame, dict]:
    parquet_files = sorted(root.glob("data/chunk-*/file-*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {root}/data/")
    df = pd.concat([pd.read_parquet(f) for f in parquet_files], ignore_index=True)

    info = json.loads((root / "meta" / "info.json").read_text())
    return df, info


def list_episodes(df: pd.DataFrame, root: Path):
    tasks_path = root / "meta" / "tasks.jsonl"
    tasks = {}
    if tasks_path.exists():
        for line in tasks_path.read_text().splitlines():
            t = json.loads(line)
            tasks[t["task_index"]] = t["task"]

    print(f"\n{'Episode':>8}  {'Frames':>7}  {'Duration':>9}  Task")
    print("-" * 70)
    for ep_idx, group in df.groupby("episode_index"):
        duration = group["timestamp"].max() - group["timestamp"].min()
        task_idx = group["task_index"].iloc[0]
        task = tasks.get(task_idx, f"task_{task_idx}")
        print(f"  {ep_idx:>6}  {len(group):>7}  {duration:>8.1f}s  {task}")


def replay_episode(df: pd.DataFrame, episode: int, fps: int, dry_run: bool, follower_port: str):
    frames = df[df["episode_index"] == episode].sort_values("frame_index")
    if frames.empty:
        print(f"Episode {episode} not found.")
        return

    n = len(frames)
    duration = frames["timestamp"].max() - frames["timestamp"].min()
    print(f"\nReplaying episode {episode}: {n} frames, {duration:.1f}s at {fps} fps")

    if not dry_run:
        from lerobot.robots.so_follower import SOFollower
        from lerobot.robots.so_follower.config_so_follower import SOFollowerRobotConfig

        robot = SOFollower(SOFollowerRobotConfig(port=follower_port, id="decras_follower", use_degrees=True))
        robot.connect(calibrate=False)
        print("Robot connected. Starting in 2s — get clear of the arm!")
        time.sleep(2.0)
    else:
        robot = None
        print("Dry-run: printing joint positions only, no hardware.")

    try:
        for i, (_, row) in enumerate(frames.iterrows()):
            t0 = time.perf_counter()
            joints = dict(zip(MOTOR_ORDER, row["action"]))

            if dry_run:
                print(f"  frame {i:4d}: " + "  ".join(f"{k}={v:+7.2f}" for k, v in joints.items()))
            else:
                action = {f"{motor}.pos": val for motor, val in joints.items()}
                robot.send_action(action)

            precise_sleep(max(1.0 / fps - (time.perf_counter() - t0), 0.0))

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if robot and robot.is_connected:
            robot.disconnect()

    print(f"Replay complete ({i + 1} frames).")


def parse_args():
    parser = argparse.ArgumentParser(description="Replay a recorded teleoperation episode")
    parser.add_argument("--out", required=True, help="Dataset root directory (e.g. datasets/sticks2)")
    parser.add_argument("--episode", type=int, default=0, help="Episode index to replay (default 0)")
    parser.add_argument("--list", action="store_true", help="List all episodes and exit")
    parser.add_argument("--dry-run", action="store_true", help="Print joint positions without moving hardware")
    parser.add_argument("--follower-port", default=os.environ.get("LEROBOT_FOLLOWER_PORT", "/dev/ttyACM0"))
    return parser.parse_args()


def main():
    args = parse_args()
    root = Path(args.out)

    df, info = load_dataset(root)
    fps = info.get("fps", 30)

    if args.list:
        list_episodes(df, root)
        return

    replay_episode(df, args.episode, fps, args.dry_run, args.follower_port)


if __name__ == "__main__":
    main()
