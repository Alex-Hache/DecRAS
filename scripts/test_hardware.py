"""Test real SO-101 hardware connection and basic control.

Usage:
    SIMULATE=false python -m scripts.test_hardware
    SIMULATE=false python -m scripts.test_hardware --recalibrate
"""

import json
import os
import sys
import time

# Force real hardware mode
os.environ["SIMULATE"] = "false"

from mcp_server.robot.lerobot import LeRobotInterface, JOINT_NAMES, ARM_JOINT_NAMES

# Upright working position (arm extended, ready to work)
WORK_POSITION = {
    "shoulder_pan": 0.0,
    "shoulder_lift": 75.0,
    "elbow_flex": -75.0,
    "wrist_flex": -60.0,
    "wrist_roll": 0.0,
    "gripper": 0.0,
}

# Folded rest position (arm tucked in, matches power-off pose)
REST_POSITION = {
    "shoulder_pan": -18.0,
    "shoulder_lift": -105.0,
    "elbow_flex": 97.0,
    "wrist_flex": 74.0,
    "wrist_roll": 0.0,
    "gripper": 0.0,
}


def smooth_move(robot: LeRobotInterface, target: dict[str, float],
                steps: int = 30, delay: float = 0.03):
    """Interpolate smoothly from current position to target."""
    current = robot.get_joint_positions()
    for i in range(1, steps + 1):
        alpha = i / steps
        # Ease in-out (smoothstep)
        alpha = alpha * alpha * (3 - 2 * alpha)
        interp = {}
        for name in JOINT_NAMES:
            c = current.get(name, 0.0)
            t = target.get(name, c)
            interp[name] = c + alpha * (t - c)
        robot.send_joint_positions(interp)
        time.sleep(delay)


def main():
    port = os.environ.get("LEROBOT_FOLLOWER_PORT")
    recalibrate = "--recalibrate" in sys.argv

    print("=" * 50)
    print("  DecRAS — SO-101 Hardware Test")
    print("=" * 50)
    print(f"  Port: {port or 'auto-detect'}")
    if recalibrate:
        print("  Mode: RECALIBRATE")
    print()

    # 1. Connect
    print("[1] Connecting to SO-101 follower...")
    try:
        robot = LeRobotInterface(port=port)
    except Exception as e:
        print(f"  FAILED: {e}")
        print("\n  Check: is the robot plugged in? Is the port correct?")
        sys.exit(1)
    print(f"  Connected: {robot.is_connected}")
    print(f"  Calibrated: {robot.is_calibrated()}")

    # 1b. Recalibrate if requested
    if recalibrate:
        print("\n[1b] Running recalibration...")
        print("  Deleting old calibration file first...")
        cal_path = robot.robot.calibration_fpath
        if cal_path.exists():
            cal_path.unlink()
            print(f"  Deleted: {cal_path}")
        # Disconnect and reconnect to trigger fresh calibration
        robot.stop()
        time.sleep(1)
        print("  Reconnecting for fresh calibration...")
        robot = LeRobotInterface(port=port)
        print(f"  Calibrated: {robot.is_calibrated()}")

    # 2. Read joints
    print("\n[2] Reading joint positions...")
    joints = robot.get_joint_positions()
    for name, val in joints.items():
        print(f"  {name:20s}: {val:8.2f}°")

    # 3. Smooth move to work position
    print("\n[3] Move to upright work position.")
    print(f"  Target: {WORK_POSITION}")
    answer = input("  Proceed? (y/N): ").strip().lower()
    if answer == "y":
        print("  Moving smoothly to work position...")
        smooth_move(robot, WORK_POSITION, steps=40, delay=0.03)
        time.sleep(0.5)
        print("  Reached work position. Current positions:")
        joints = robot.get_joint_positions()
        for name, val in joints.items():
            print(f"    {name:20s}: {val:8.2f}°")

    # 4. Small test movement
    print("\n[4] Test movement — move shoulder_pan ±20°")
    answer = input("  Proceed? (y/N): ").strip().lower()
    if answer == "y":
        current = robot.get_joint_positions()
        # Pan right
        target = dict(current)
        target["shoulder_pan"] = current["shoulder_pan"] + 20.0
        print("  Panning right...")
        smooth_move(robot, target, steps=25)
        time.sleep(0.5)

        # Pan left
        target["shoulder_pan"] = current["shoulder_pan"] - 20.0
        print("  Panning left...")
        smooth_move(robot, target, steps=25)
        time.sleep(0.5)

        # Return to center
        target["shoulder_pan"] = current["shoulder_pan"]
        print("  Returning to center...")
        smooth_move(robot, target, steps=25)

    # 5. Gripper test
    print("\n[5] Gripper test.")
    answer = input("  Test gripper open/close? (y/N): ").strip().lower()
    if answer == "y":
        print("  Closing gripper...")
        robot.grasp(force=3.0)
        time.sleep(1)
        print("  Opening gripper...")
        robot.release()
        time.sleep(0.5)

    # 6. Return to folded rest position and disconnect
    print("\n[6] Returning to folded rest position...")
    print(f"  Target: {REST_POSITION}")
    smooth_move(robot, REST_POSITION, steps=60, delay=0.06)

    # Hold to let servos settle
    print("  Holding position (2s)...")
    for _ in range(20):
        robot.send_joint_positions(REST_POSITION)
        time.sleep(0.1)

    print("  Final joint positions:")
    joints = robot.get_joint_positions()
    for name, val in joints.items():
        print(f"    {name:20s}: {val:8.2f}°")

    print("  Releasing torque and disconnecting...")
    robot.stop()
    print("\n  Done!")


if __name__ == "__main__":
    main()
