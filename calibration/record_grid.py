"""Interactive calibration grid recorder for DecRAS.

Connects to leader + follower SO-101 arms. The user teleoperates the arm to
positions across the workspace, measures (x, y, z) with a ruler, and presses
ENTER to record the joint angles together with the Cartesian position.

Saves to calibration/calibration_data.json. Supports resuming (appends to
existing file) and displays workspace coverage summary after each point.

Usage:
    uv run python -m calibration.record_grid

    # Custom ports:
    uv run python -m calibration.record_grid \\
        --follower-port /dev/ttyACM0 \\
        --leader-port /dev/ttyACM1

    # Custom output file:
    uv run python -m calibration.record_grid --output calibration/my_data.json
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Joint names matching the SO-101 arm (same as mcp_server/robot/lerobot.py)
JOINT_NAMES = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
]

ARM_JOINT_NAMES = JOINT_NAMES[:-1]

# Calibration grid spec from ARCHITECTURE.md
GRID_SPEC = {
    "x_range": (0.15, 0.35),  # meters from base
    "y_range": (-0.15, 0.15),
    "z_range": (0.00, 0.15),  # table to +15cm
    "target_points": 75,
}

DEFAULT_OUTPUT = Path(__file__).parent / "calibration_data.json"


def load_existing_data(path: Path) -> list[dict]:
    """Load existing calibration data for resume support."""
    if path.exists():
        with open(path) as f:
            data = json.load(f)
        return data.get("points", [])
    return []


def save_data(path: Path, points: list[dict]) -> None:
    """Save calibration data to JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "format_version": 1,
        "grid_spec": GRID_SPEC,
        "num_points": len(points),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "points": points,
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def compute_coverage(points: list[dict]) -> dict:
    """Compute workspace coverage stats from recorded points."""
    if not points:
        return {"count": 0, "x_range": None, "y_range": None, "z_range": None}

    xs = [p["position"]["x"] for p in points]
    ys = [p["position"]["y"] for p in points]
    zs = [p["position"]["z"] for p in points]

    return {
        "count": len(points),
        "x_range": (min(xs), max(xs)),
        "y_range": (min(ys), max(ys)),
        "z_range": (min(zs), max(zs)),
    }


def print_coverage(points: list[dict]) -> None:
    """Display workspace coverage summary."""
    cov = compute_coverage(points)
    print(f"\n  Recorded points: {cov['count']} / {GRID_SPEC['target_points']}")
    if cov["count"] > 0:
        print(f"  X coverage: {cov['x_range'][0]:.3f} – {cov['x_range'][1]:.3f} m "
              f"(target: {GRID_SPEC['x_range'][0]:.2f} – {GRID_SPEC['x_range'][1]:.2f})")
        print(f"  Y coverage: {cov['y_range'][0]:.3f} – {cov['y_range'][1]:.3f} m "
              f"(target: {GRID_SPEC['y_range'][0]:.2f} – {GRID_SPEC['y_range'][1]:.2f})")
        print(f"  Z coverage: {cov['z_range'][0]:.3f} – {cov['z_range'][1]:.3f} m "
              f"(target: {GRID_SPEC['z_range'][0]:.2f} – {GRID_SPEC['z_range'][1]:.2f})")
    print()


def parse_position(prompt: str) -> tuple[float, float, float] | None:
    """Prompt user for x, y, z position. Returns None on empty/quit input."""
    try:
        raw = input(prompt).strip()
    except EOFError:
        return None

    if not raw or raw.lower() in ("q", "quit", "exit"):
        return None

    parts = raw.replace(",", " ").split()
    if len(parts) != 3:
        print("  Expected 3 values: x y z (meters). Example: 0.25 0.05 0.10")
        return parse_position(prompt)

    try:
        x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
    except ValueError:
        print("  Could not parse numbers. Example: 0.25 0.05 0.10")
        return parse_position(prompt)

    return (x, y, z)


def read_joint_angles(robot) -> dict[str, float]:
    """Read current joint angles from the follower arm."""
    obs = robot.get_observation()
    positions = {}
    for name in JOINT_NAMES:
        key = f"{name}.pos"
        positions[name] = float(obs.get(key, 0.0))
    return positions


def connect_hardware(follower_port: str, leader_port: str):
    """Connect to leader and follower arms. Returns (follower, leader, processors)."""
    from lerobot.robots.so_follower import SOFollower
    from lerobot.robots.so_follower.config_so_follower import SOFollowerRobotConfig
    from lerobot.teleoperators.so_leader import SOLeader
    from lerobot.teleoperators.so_leader.config_so_leader import SOLeaderTeleopConfig
    from lerobot.processor import make_default_processors

    follower = SOFollower(SOFollowerRobotConfig(
        port=follower_port,
        id="decras_follower",
        use_degrees=True,
    ))
    leader = SOLeader(SOLeaderTeleopConfig(
        port=leader_port,
        id="decras_leader",
        use_degrees=True,
    ))

    follower.connect()
    leader.connect()

    teleop_action_proc, robot_action_proc, robot_obs_proc = make_default_processors()

    return follower, leader, teleop_action_proc, robot_action_proc, robot_obs_proc


def teleop_step(follower, leader, teleop_action_proc, robot_action_proc, robot_obs_proc):
    """Execute one teleoperation step: read leader, command follower."""
    obs = follower.get_observation()
    obs_processed = robot_obs_proc(obs)
    act = leader.get_action()
    act_processed = teleop_action_proc((act, obs))
    robot_action = robot_action_proc((act_processed, obs))
    follower.send_action(robot_action)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record calibration grid points for joint-space lookup"
    )
    parser.add_argument(
        "--follower-port",
        default=os.environ.get("LEROBOT_FOLLOWER_PORT", "/dev/decras_follower"),
        help="Follower arm serial port",
    )
    parser.add_argument(
        "--leader-port",
        default=os.environ.get("LEROBOT_LEADER_PORT", "/dev/decras_leader"),
        help="Leader arm serial port",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output JSON file (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--fps", type=int, default=50,
        help="Teleoperation control frequency in Hz (default: 50)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Load existing data for resume
    points = load_existing_data(args.output)
    if points:
        logger.info(f"Resuming: loaded {len(points)} existing points from {args.output}")
    else:
        logger.info(f"Starting fresh. Output: {args.output}")

    # Connect hardware
    logger.info("Connecting to leader + follower arms...")
    try:
        follower, leader, tap, rap, rop = connect_hardware(
            args.follower_port, args.leader_port
        )
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        sys.exit(1)

    logger.info("Connected. Starting teleoperation loop.")
    print("=" * 60)
    print("  DecRAS — Calibration Grid Recorder")
    print("=" * 60)
    print()
    print("  Move the arm using the leader, then press ENTER to record.")
    print("  You will be prompted to enter the measured x, y, z position.")
    print("  Type 'q' or Ctrl+C to stop and save.")
    print("  Type 'd' + ENTER to delete the last recorded point.")
    print()
    print_coverage(points)

    # Teleoperation runs in background; recording happens on ENTER
    import threading
    import select

    stop_event = threading.Event()

    def _teleop_loop():
        """Run teleoperation at target FPS until stopped."""
        dt = 1.0 / args.fps
        while not stop_event.is_set():
            t0 = time.perf_counter()
            try:
                teleop_step(follower, leader, tap, rap, rop)
            except Exception as e:
                logger.warning(f"Teleop step error: {e}")
            elapsed = time.perf_counter() - t0
            remaining = dt - elapsed
            if remaining > 0:
                time.sleep(remaining)

    teleop_thread = threading.Thread(target=_teleop_loop, daemon=True)
    teleop_thread.start()

    try:
        point_num = len(points) + 1
        while True:
            try:
                cmd = input(f"  [{point_num}] Press ENTER to record (or 'q' to quit, 'd' to delete last): ").strip().lower()
            except EOFError:
                break

            if cmd in ("q", "quit", "exit"):
                break

            if cmd == "d":
                if points:
                    removed = points.pop()
                    save_data(args.output, points)
                    print(f"  Deleted point at ({removed['position']['x']:.3f}, "
                          f"{removed['position']['y']:.3f}, {removed['position']['z']:.3f})")
                    point_num = len(points) + 1
                    print_coverage(points)
                else:
                    print("  No points to delete.")
                continue

            if cmd and cmd not in ("", "y", "yes"):
                print(f"  Unknown command: '{cmd}'. Press ENTER to record or 'q' to quit.")
                continue

            # Read joint angles from follower
            joints = read_joint_angles(follower)
            arm_joints = {k: v for k, v in joints.items() if k != "gripper"}

            print(f"  Joint angles: {', '.join(f'{k}={v:.1f}' for k, v in arm_joints.items())}")

            # Get position measurement from user
            pos = parse_position("  Enter position (x y z in meters): ")
            if pos is None:
                break

            x, y, z = pos

            point = {
                "index": point_num,
                "position": {"x": x, "y": y, "z": z},
                "joints": joints,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            points.append(point)
            save_data(args.output, points)

            print(f"  Saved point {point_num}: pos=({x:.3f}, {y:.3f}, {z:.3f})")
            print_coverage(points)
            point_num += 1

    except KeyboardInterrupt:
        print("\n  Interrupted.")

    finally:
        stop_event.set()
        teleop_thread.join(timeout=2.0)
        save_data(args.output, points)
        logger.info(f"Saved {len(points)} points to {args.output}")

        try:
            follower.disconnect()
        except Exception:
            pass
        try:
            leader.disconnect()
        except Exception:
            pass

    print_coverage(points)
    print("Done.")


if __name__ == "__main__":
    main()
