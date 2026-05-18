"""Hardware validation script for gravity compensation tuning.

Connects to the real arm, moves to WORK_POSITION, then commands a Z-up move
and reports actual reach vs commanded distance. Use to sweep SERVO_P_GAIN
and later to validate SERVO_COMPLIANCE_DEG_PER_NM.

Usage:
    # P-gain sweep: try 16, 24, 32 one at a time
    DECRAS_SERVO_P_GAIN=16  sg dialout -c "SIMULATE=false uv run python -m scripts.validate_gravity"
    DECRAS_SERVO_P_GAIN=24  sg dialout -c "SIMULATE=false uv run python -m scripts.validate_gravity"
    DECRAS_SERVO_P_GAIN=32  sg dialout -c "SIMULATE=false uv run python -m scripts.validate_gravity"

    # Diagnostic data collection (writes waypoint_errors JSON to stdout):
    sg dialout -c "SIMULATE=false LOG_GRAVITY_ERRORS=true uv run python -m scripts.validate_gravity --log"

    # Custom delta (default: Z-up 5cm):
    sg dialout -c "SIMULATE=false uv run python -m scripts.validate_gravity --dz 0.08"
"""

import os
import sys
import json
import time
import argparse

# Must be set before any mcp_server import
os.environ.setdefault("SIMULATE", "false")

from mcp_server.config import WORK_POSITION, LEROBOT_FOLLOWER_PORT, SERVO_P_GAIN
from mcp_server.robot.lerobot import LeRobotInterface
from mcp_server.robot.kinematics import joints_to_cartesian


def move_to_work(robot: LeRobotInterface) -> None:
    print("Moving to WORK_POSITION ...", flush=True)
    robot.send_joint_positions(WORK_POSITION)
    time.sleep(2.0)  # let servos settle
    actual = robot.get_joint_positions()
    ee = joints_to_cartesian({k: v for k, v in actual.items() if k != "gripper"})
    print(f"  EE at WORK: x={ee[0]:.3f}  y={ee[1]:.3f}  z={ee[2]:.3f} m")


def measure_z_up(
    robot: LeRobotInterface,
    dz: float = 0.05,
    dx: float = 0.0,
    dy: float = 0.0,
) -> dict:
    # Snapshot before
    before_joints = robot.get_joint_positions()
    before_ee = joints_to_cartesian({k: v for k, v in before_joints.items() if k != "gripper"})

    print(f"\nCommanding move_to_delta(dx={dx}, dy={dy}, dz={dz}) ...", flush=True)
    result = robot.move_cartesian_delta(dx, dy, dz)

    # Snapshot after (fresh read)
    after_joints = robot.get_joint_positions()
    after_ee = joints_to_cartesian({k: v for k, v in after_joints.items() if k != "gripper"})

    actual_dz = after_ee[2] - before_ee[2]
    actual_dx = after_ee[0] - before_ee[0]
    actual_dy = after_ee[1] - before_ee[1]

    commanded_dist = (dx**2 + dy**2 + dz**2) ** 0.5
    actual_dist = (actual_dx**2 + actual_dy**2 + actual_dz**2) ** 0.5
    reach_pct = 100.0 * actual_dist / commanded_dist if commanded_dist > 0 else 0.0

    summary = {
        "p_gain": SERVO_P_GAIN if SERVO_P_GAIN != 0 else 16,
        "commanded": {"dx": dx, "dy": dy, "dz": dz},
        "actual": {
            "dx": round(actual_dx, 4),
            "dy": round(actual_dy, 4),
            "dz": round(actual_dz, 4),
        },
        "reach_pct": round(reach_pct, 1),
        "before_ee": [round(v, 4) for v in before_ee],
        "after_ee": [round(v, 4) for v in after_ee],
    }

    if "waypoint_errors" in result:
        summary["waypoint_errors"] = result["waypoint_errors"]

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate gravity compensation on hardware")
    parser.add_argument("--dz", type=float, default=0.05, help="Z delta in meters (default 0.05)")
    parser.add_argument("--dx", type=float, default=0.0, help="X delta in meters")
    parser.add_argument("--dy", type=float, default=0.0, help="Y delta in meters")
    parser.add_argument("--log", action="store_true",
                        help="Print full waypoint_errors JSON (use with LOG_GRAVITY_ERRORS=true)")
    parser.add_argument("--port", default=LEROBOT_FOLLOWER_PORT)
    args = parser.parse_args()

    print("=" * 60)
    print(f"Gravity validation  |  SERVO_P_GAIN={SERVO_P_GAIN or 16} (0=lerobot default)")
    print(f"Commanded delta: dx={args.dx} dy={args.dy} dz={args.dz} m")
    print("=" * 60)

    robot = LeRobotInterface(port=args.port)

    try:
        move_to_work(robot)
        time.sleep(0.5)

        summary = measure_z_up(robot, dz=args.dz, dx=args.dx, dy=args.dy)

        print(f"\n--- RESULT ---")
        print(f"  P gain        : {summary['p_gain']}")
        print(f"  Commanded dz  : {args.dz * 100:.1f} cm")
        print(f"  Actual dz     : {summary['actual']['dz'] * 100:.1f} cm")
        print(f"  Reach         : {summary['reach_pct']:.1f}%")
        print(f"  Before EE     : {summary['before_ee']}")
        print(f"  After  EE     : {summary['after_ee']}")

        if args.log and "waypoint_errors" in summary:
            print("\n--- WAYPOINT ERRORS (q_desired vs q_actual) ---")
            print(json.dumps(summary["waypoint_errors"], indent=2))
        elif args.log:
            print("\nNo waypoint_errors in result — did you set LOG_GRAVITY_ERRORS=true?")

        print(f"\nFull summary JSON:")
        summary_no_wp = {k: v for k, v in summary.items() if k != "waypoint_errors"}
        print(json.dumps(summary_no_wp, indent=2))

    finally:
        robot.stop()


if __name__ == "__main__":
    main()
