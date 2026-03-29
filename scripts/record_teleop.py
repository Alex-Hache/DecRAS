"""Teleoperation recording for DecRAS — SO-101 leader → follower.

Wires LeRobot's native SOFollower + SOLeader + LeRobotDataset.
Produces a HuggingFace-compatible dataset (Parquet + MP4) for imitation learning.

Usage:
    uv run python -m scripts.record_teleop \\
        --task "Pick up the red cube" \\
        --episodes 10 \\
        --out datasets/pick_cube

    # With camera:
    uv run python -m scripts.record_teleop \\
        --task "Pick up the red cube" \\
        --episodes 10 \\
        --out datasets/pick_cube \\
        --camera-index 0

    # Resume existing dataset:
    uv run python -m scripts.record_teleop --resume --out datasets/pick_cube ...

Keyboard controls during recording:
    Right arrow  →  exit current episode early (save it)
    Left arrow   →  discard and re-record current episode
    Escape / q   →  stop all recording

Ports (env vars or flags):
    LEROBOT_FOLLOWER_PORT  (default /dev/ttyACM0)
    LEROBOT_LEADER_PORT    (default /dev/ttyACM1)
"""

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path

from lerobot.datasets.image_writer import safe_stop_image_writer
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.datasets.pipeline_features import aggregate_pipeline_dataset_features, create_initial_features
from lerobot.datasets.utils import build_dataset_frame, combine_feature_dicts
from lerobot.datasets.video_utils import VideoEncodingManager
from lerobot.processor import make_default_processors
from lerobot.robots.so_follower import SOFollower
from lerobot.robots.so_follower.config_so_follower import SOFollowerRobotConfig
from lerobot.teleoperators.so_leader import SOLeader
from lerobot.teleoperators.so_leader.config_so_leader import SOLeaderTeleopConfig
from lerobot.utils.constants import ACTION, OBS_STR
from lerobot.utils.robot_utils import precise_sleep
from lerobot.utils.utils import init_logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _make_events() -> tuple[dict, threading.Thread]:
    """Stdin-based event listener. Works inside sg dialout subshells."""
    import threading

    events = {"exit_early": False, "rerecord_episode": False, "stop_recording": False}

    def _listen():
        print("  Controls: Enter=save  r+Enter=re-record  q+Enter=stop all", flush=True)
        for line in sys.stdin:
            cmd = line.strip().lower()
            if cmd == "":
                events["exit_early"] = True
                print("  → saving episode early", flush=True)
            elif cmd == "r":
                events["rerecord_episode"] = True
                events["exit_early"] = True
                print("  → discarding, will re-record", flush=True)
            elif cmd == "q":
                events["stop_recording"] = True
                events["exit_early"] = True
                print("  → stopping all recording", flush=True)

    t = threading.Thread(target=_listen, daemon=True)
    t.start()
    return events, t


@safe_stop_image_writer
def _record_loop(
    robot: SOFollower,
    teleop: SOLeader,
    teleop_action_proc,
    robot_action_proc,
    robot_obs_proc,
    events: dict,
    fps: int,
    control_time_s: float,
    dataset: LeRobotDataset | None = None,
    task: str | None = None,
):
    """Single episode (or reset) recording loop — mirrors lerobot record_loop."""
    timestamp = 0.0
    start = time.perf_counter()

    while timestamp < control_time_s:
        t0 = time.perf_counter()

        if events["exit_early"]:
            events["exit_early"] = False
            break

        obs = robot.get_observation()
        obs_processed = robot_obs_proc(obs)

        act = teleop.get_action()
        act_processed = teleop_action_proc((act, obs))
        robot_action = robot_action_proc((act_processed, obs))
        robot.send_action(robot_action)

        if dataset is not None:
            obs_frame = build_dataset_frame(dataset.features, obs_processed, prefix=OBS_STR)
            act_frame = build_dataset_frame(dataset.features, act_processed, prefix=ACTION)
            dataset.add_frame({**obs_frame, **act_frame, "task": task})

        dt = time.perf_counter() - t0
        precise_sleep(max(1.0 / fps - dt, 0.0))
        timestamp = time.perf_counter() - start


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record SO-101 teleoperation episodes")
    parser.add_argument("--task", required=True, help='Task description, e.g. "Pick up the red cube"')
    parser.add_argument("--episodes", type=int, default=10, help="Number of episodes to record")
    parser.add_argument("--out", default="datasets/decras", help="Local dataset root directory")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--episode-time", type=float, default=60.0, help="Max seconds per episode")
    parser.add_argument("--reset-time", type=float, default=30.0, help="Seconds for env reset between episodes")
    parser.add_argument("--camera-index", type=int, default=None, help="OpenCV camera index (omit = no camera)")
    parser.add_argument("--camera-width", type=int, default=640)
    parser.add_argument("--camera-height", type=int, default=480)
    parser.add_argument("--follower-port", default=os.environ.get("LEROBOT_FOLLOWER_PORT", "/dev/decras_follower"))
    parser.add_argument("--leader-port", default=os.environ.get("LEROBOT_LEADER_PORT", "/dev/decras_leader"))
    parser.add_argument("--resume", action="store_true", help="Resume recording into existing dataset")
    parser.add_argument("--overwrite", action="store_true", help="Delete existing dataset folder and start fresh")
    return parser.parse_args()


def main():
    init_logging()
    args = parse_args()

    # ── Camera config (lazy import to avoid cv2 at module level) ──────────────
    cameras = {}
    if args.camera_index is not None:
        from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
        cameras["top"] = OpenCVCameraConfig(
            index_or_path=args.camera_index,
            width=args.camera_width,
            height=args.camera_height,
            fps=args.fps,
        )

    # ── Robot + teleop ────────────────────────────────────────────────────────
    robot = SOFollower(SOFollowerRobotConfig(port=args.follower_port, id="decras_follower", cameras=cameras, use_degrees=True))
    teleop = SOLeader(SOLeaderTeleopConfig(port=args.leader_port, id="decras_leader", use_degrees=True))

    # ── Processors (identity; swap in normalization here for policy training) ─
    teleop_action_proc, robot_action_proc, robot_obs_proc = make_default_processors()

    # ── Dataset features: derived from robot specs via processors ─────────────
    dataset_features = combine_feature_dicts(
        aggregate_pipeline_dataset_features(
            pipeline=teleop_action_proc,
            initial_features=create_initial_features(action=robot.action_features),
            use_videos=bool(cameras),
        ),
        aggregate_pipeline_dataset_features(
            pipeline=robot_obs_proc,
            initial_features=create_initial_features(observation=robot.observation_features),
            use_videos=bool(cameras),
        ),
    )

    root = Path(args.out)
    repo_id = f"decras/{root.name}"

    if args.overwrite and root.exists():
        import shutil
        shutil.rmtree(root)
        logger.info(f"Deleted existing dataset at {root}")

    # ── Connect hardware first — dataset only created on success ──────────────
    try:
        robot.connect()
        teleop.connect()
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        raise

    # ── Dataset ───────────────────────────────────────────────────────────────
    if args.resume:
        dataset = LeRobotDataset(repo_id, root=root, streaming_encoding=True, encoder_threads=2)
    else:
        dataset = LeRobotDataset.create(
            repo_id,
            fps=args.fps,
            root=root,
            robot_type=robot.name,
            features=dataset_features,
            use_videos=bool(cameras),
            image_writer_processes=0,
            image_writer_threads=4 * max(len(cameras), 1),
            streaming_encoding=True,
            encoder_threads=2,
        )

    try:
        events, _ = _make_events()

        logger.info("=" * 55)
        logger.info("  DecRAS — Teleoperation Recording")
        logger.info(f"  Task:     {args.task}")
        logger.info(f"  Episodes: {args.episodes}  FPS: {args.fps}  Camera: {'yes' if cameras else 'no'}")
        logger.info(f"  Output:   {root.resolve()}")
        logger.info("=" * 55)

        with VideoEncodingManager(dataset):
            recorded = 0
            while recorded < args.episodes and not events["stop_recording"]:
                ep_num = dataset.num_episodes + 1
                logger.info(f"\n[Episode {ep_num}/{args.episodes}] Recording... (max {args.episode_time:.0f}s)")

                _record_loop(
                    robot=robot, teleop=teleop,
                    teleop_action_proc=teleop_action_proc,
                    robot_action_proc=robot_action_proc,
                    robot_obs_proc=robot_obs_proc,
                    events=events, fps=args.fps,
                    control_time_s=args.episode_time,
                    dataset=dataset, task=args.task,
                )

                if events["rerecord_episode"]:
                    logger.info("  Discarding — will re-record this episode")
                    events["rerecord_episode"] = False
                    events["exit_early"] = False
                    dataset.clear_episode_buffer()
                    continue

                dataset.save_episode()
                recorded += 1
                logger.info(f"  Episode {recorded} saved.")

                if not events["stop_recording"] and recorded < args.episodes:
                    logger.info(f"  Reset environment ({args.reset_time:.0f}s) — RightArrow to skip")
                    _record_loop(
                        robot=robot, teleop=teleop,
                        teleop_action_proc=teleop_action_proc,
                        robot_action_proc=robot_action_proc,
                        robot_obs_proc=robot_obs_proc,
                        events=events, fps=args.fps,
                        control_time_s=args.reset_time,
                    )

    finally:
        dataset.finalize()
        if robot.is_connected:
            robot.disconnect()
        if teleop.is_connected:
            teleop.disconnect()
        logger.info(f"\nDone. {dataset.num_episodes} episodes at {root.resolve()}")




if __name__ == "__main__":
    main()
