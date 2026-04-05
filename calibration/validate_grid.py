"""Calibration grid validator for DecRAS.

Commands the follower arm to each recorded calibration position sequentially
using the joint-space lookup table, then prompts the user to visually verify
that the arm reaches the correct location.  Points with large errors can be
flagged for re-recording.

Usage:
    uv run python -m calibration.validate_grid

    # Custom calibration file:
    uv run python -m calibration.validate_grid --input calibration/calibration_data.json

    # Skip confirmation prompts (automated sweep):
    uv run python -m calibration.validate_grid --auto

Note: This script requires hardware access.
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

DEFAULT_INPUT = Path(__file__).parent / "calibration_data.json"
MOVE_PAUSE_S = 1.5  # seconds to pause at each position for visual inspection
JOINT_NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]


def load_calibration(path: Path) -> list[dict]:
    """Load calibration points from JSON."""
    if not path.exists():
        logger.error("Calibration file not found: %s", path)
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    points = data.get("points", [])
    logger.info("Loaded %d calibration points from %s", len(points), path)
    return points


def connect_hardware(follower_port: str):
    """Connect to the follower arm. Returns follower object."""
    from lerobot.robots.so_follower import SOFollower
    from lerobot.robots.so_follower.config_so_follower import SOFollowerRobotConfig

    follower = SOFollower(SOFollowerRobotConfig(
        port=follower_port,
        id="decras_follower",
        use_degrees=True,
    ))
    follower.connect()
    logger.info("Connected to follower on %s", follower_port)
    return follower


def send_joints(follower, joints: dict) -> None:
    """Send joint positions to the follower arm."""
    action = {f"{name}.pos": joints[name] for name in JOINT_NAMES if name in joints}
    action["gripper.pos"] = joints.get("gripper", 0.0)
    follower.send_action(action)


def run_validation(
    points: list[dict],
    follower,
    auto: bool = False,
    start_idx: int = 0,
) -> list[dict]:
    """Step through each calibration point and collect user verdicts.

    Args:
        points: List of calibration point dicts.
        follower: Connected follower arm object.
        auto: If True, skip confirmation prompts (timed sweep only).
        start_idx: Index to start from (for resuming).

    Returns:
        List of result dicts: {index, position, verdict, note}
    """
    results = []

    for i, point in enumerate(points[start_idx:], start=start_idx):
        pos = point["position"]
        joints = point["joints"]
        idx = point.get("index", i + 1)

        print(f"\n  [{idx}/{len(points)}] Moving to "
              f"({pos['x']:.3f}, {pos['y']:.3f}, {pos['z']:.3f}) m")
        print(f"  Joints: " + ", ".join(f"{k}={joints.get(k, 0):.1f}°" for k in JOINT_NAMES))

        # Send joint positions
        try:
            send_joints(follower, joints)
        except Exception as e:
            logger.warning("Failed to send joints for point %d: %s", idx, e)
            results.append({
                "index": idx,
                "position": pos,
                "verdict": "error",
                "note": str(e),
            })
            continue

        # Pause at position
        time.sleep(MOVE_PAUSE_S)

        if auto:
            verdict = "unchecked"
            note = ""
        else:
            try:
                raw = input(
                    "  Correct position? [y/n/s(skip)/q(quit)]: "
                ).strip().lower()
            except EOFError:
                raw = "q"

            if raw in ("q", "quit"):
                print("  Stopping validation.")
                break
            elif raw in ("s", "skip"):
                verdict = "skipped"
                note = ""
            elif raw in ("n", "no"):
                try:
                    note = input("  Note (describe the error): ").strip()
                except EOFError:
                    note = ""
                verdict = "fail"
            else:
                verdict = "ok"
                note = ""

        results.append({
            "index": idx,
            "position": pos,
            "verdict": verdict,
            "note": note,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        if not auto:
            symbol = {"ok": "✓", "fail": "✗", "skipped": "—", "error": "!", "unchecked": "?"}.get(verdict, "?")
            print(f"  {symbol} {verdict}")

    return results


def print_summary(results: list[dict]) -> None:
    """Print validation summary."""
    if not results:
        print("\n  No results to summarise.")
        return

    ok = sum(1 for r in results if r["verdict"] == "ok")
    fail = sum(1 for r in results if r["verdict"] == "fail")
    skip = sum(1 for r in results if r["verdict"] == "skipped")
    err = sum(1 for r in results if r["verdict"] == "error")

    print(f"\n{'=' * 50}")
    print(f"  Validation summary")
    print(f"{'=' * 50}")
    print(f"  Total checked : {len(results)}")
    print(f"  OK            : {ok}")
    print(f"  Failed        : {fail}")
    print(f"  Skipped       : {skip}")
    print(f"  Errors        : {err}")

    if fail:
        print(f"\n  Failed points (re-record these):")
        for r in results:
            if r["verdict"] == "fail":
                pos = r["position"]
                print(f"    #{r['index']:3d}: ({pos['x']:.3f}, {pos['y']:.3f}, {pos['z']:.3f})"
                      + (f" — {r['note']}" if r["note"] else ""))
    print()


def save_results(results: list[dict], output_path: Path) -> None:
    """Save validation results to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump({
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "num_checked": len(results),
            "results": results,
        }, f, indent=2)
    logger.info("Saved validation results to %s", output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate calibration grid by commanding the arm to each recorded position"
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Calibration JSON file (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--follower-port",
        default=os.environ.get("LEROBOT_FOLLOWER_PORT", "/dev/decras_follower"),
        help="Follower arm serial port",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Skip interactive prompts (timed sweep only, no verdicts)",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help="Index to start from (0-based, for resuming interrupted validation)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Optional path to save validation results JSON",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    points = load_calibration(args.input)

    if not points:
        print("No calibration points found.")
        sys.exit(0)

    print("=" * 60)
    print("  DecRAS — Calibration Grid Validator")
    print("=" * 60)
    print(f"  Points to validate: {len(points)}")
    print(f"  Starting at index : {args.start}")
    print(f"  Mode              : {'automatic sweep' if args.auto else 'interactive'}")
    print()

    logger.info("Connecting to follower arm...")
    try:
        follower = connect_hardware(args.follower_port)
    except Exception as e:
        logger.error("Failed to connect: %s", e)
        sys.exit(1)

    try:
        results = run_validation(points, follower, auto=args.auto, start_idx=args.start)
    finally:
        try:
            follower.disconnect()
        except Exception:
            pass

    print_summary(results)

    if args.output:
        save_results(results, args.output)
    elif results:
        default_out = args.input.parent / "validation_results.json"
        save_results(results, default_out)


if __name__ == "__main__":
    main()
