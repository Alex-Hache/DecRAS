"""Segment a recorded teleop episode into discrete MCP primitive calls.

**Segmenter v2 — waypoint-based**

Algorithm:
  1. FK all frames → EE positions (N, 3) in meters
  2. Smooth trajectory + detect gripper close/open events (grasp/release)
  3. Walk the trajectory and mark **waypoints** where:
       - the direction changes by more than `angle_threshold` (windowed cosine)
       - the EE speed dips into a local minimum below `dip_ratio * v_max`
       - a gripper event occurs (these are always hard waypoints)
  4. Merge waypoints that are closer than `min_segment_dist` apart in 3D
  5. Emit one `move_to_delta(dx, dy, dz)` per pair of consecutive waypoints,
     inserting `grasp()` / `release()` at gripper-event waypoints.
  6. Write a Demo JSON matching the decras.imitation.retrieval schema.

Density knob:
  --density low      →   ~5 primitives (abstract / intent)
  --density medium   →  ~10 primitives (default)
  --density high     →  ~20 primitives (faithful replay)

Usage:
    uv run python -m scripts.segment_trajectory --dataset datasets/sticks_v2 --task "pick stick and place at target"
    uv run python -m scripts.segment_trajectory --dataset datasets/sticks_v2 --episode 0 --density low
    uv run python -m scripts.segment_trajectory --dataset datasets/sticks_v1 --density high --out sequences/
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from mcp_server.robot.kinematics import joints_to_cartesian

_STATE_JOINT_ORDER = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
_GRIPPER_INDEX = 5

# Shared tuning knobs (not density-dependent)
SMOOTH_K = 15             # moving-average window for EE positions
GRIPPER_SMOOTH_K = 15     # moving-average window for gripper values
GRIPPER_THRESHOLD = 0.4   # fraction of gripper range — above = open (grasp event on UP-crossing)
DIRECTION_WINDOW = 5      # frames on each side used to estimate local direction


@dataclass(frozen=True)
class DensityParams:
    """Tuning knobs that scale with the --density flag."""
    angle_threshold_deg: float    # direction change above this → new waypoint
    dip_ratio: float              # local-min speed below this fraction of v_max → new waypoint
    min_segment_dist_m: float     # merge waypoints closer than this in 3D


DENSITY_PRESETS: dict[str, DensityParams] = {
    "low":    DensityParams(angle_threshold_deg=85.0, dip_ratio=0.05, min_segment_dist_m=0.100),
    "medium": DensityParams(angle_threshold_deg=45.0, dip_ratio=0.15, min_segment_dist_m=0.035),
    "high":   DensityParams(angle_threshold_deg=25.0, dip_ratio=0.20, min_segment_dist_m=0.022),
}


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _load_dataframe(dataset_root: Path) -> pd.DataFrame:
    parquet_files = sorted((dataset_root / "data").rglob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files in {dataset_root}/data")
    return pd.concat([pd.read_parquet(f) for f in parquet_files], ignore_index=True)


def _unwrap_scalar(val):
    if hasattr(val, "__len__"):
        return int(val[0])
    return int(val)


def compute_ee_trajectory(episode_df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """FK over all frames → (N,3) EE positions in meters, (N,) gripper values, (N,) timestamps."""
    positions, grippers, timestamps = [], [], []
    for _, row in episode_df.iterrows():
        state = row["observation.state"]
        hw = {name: float(state[i]) for i, name in enumerate(_STATE_JOINT_ORDER)}
        positions.append(joints_to_cartesian(hw))
        grippers.append(float(state[_GRIPPER_INDEX]))
        timestamps.append(float(row["timestamp"]))
    return np.array(positions), np.array(grippers), np.array(timestamps)


def _smooth(arr: np.ndarray, k: int) -> np.ndarray:
    kernel = np.ones(k) / k
    if arr.ndim == 1:
        return np.convolve(arr, kernel, mode="same")
    return np.stack([np.convolve(arr[:, i], kernel, mode="same") for i in range(arr.shape[1])], axis=1)


def _find_gripper_events(gripper: np.ndarray) -> tuple[int | None, int | None]:
    """Return (grasp_frame, release_frame). None if not detected.

    Gripper convention: 0 = closed, 100 = open. Teleop opens to grab, then closes.
    Grasp = UP-crossing of threshold; release = DOWN-crossing after grasp.
    """
    smooth = _smooth(gripper, GRIPPER_SMOOTH_K)
    threshold = gripper.min() + GRIPPER_THRESHOLD * (gripper.max() - gripper.min())
    grasp = release = None
    for i in range(1, len(smooth)):
        if smooth[i - 1] < threshold and smooth[i] >= threshold and grasp is None:
            grasp = i
        if smooth[i - 1] >= threshold and smooth[i] < threshold and grasp is not None:
            release = i
            break
    return grasp, release


# ---------------------------------------------------------------------------
# Waypoint detection (core of v2)
# ---------------------------------------------------------------------------

def detect_waypoints(
    ee: np.ndarray,
    hard_waypoints: list[int],
    params: DensityParams,
) -> list[int]:
    """Pick frame indices that are segmentation boundaries.

    `hard_waypoints` (gripper events, start, end) are always kept.
    Soft waypoints are added at direction changes and speed dips,
    then merged if too close to a neighbor in 3D space.
    """
    n = len(ee)
    if n < 2:
        return [0, n - 1] if n else []

    # Per-frame speed
    vel = np.gradient(ee, axis=0)
    speed = np.linalg.norm(vel, axis=1)
    v_max = float(speed.max()) if speed.size else 0.0

    candidates: set[int] = set(hard_waypoints)
    candidates.add(0)
    candidates.add(n - 1)

    # 1. Direction changes — cosine angle between averaged displacement vectors
    w = DIRECTION_WINDOW
    angle_thresh_rad = np.deg2rad(params.angle_threshold_deg)
    # We require a minimum arc displacement so pure noise around a still
    # point can't trigger direction changes.
    min_arc = max(params.min_segment_dist_m * 0.25, 0.003)

    for i in range(w, n - w):
        v_before = ee[i] - ee[i - w]
        v_after = ee[i + w] - ee[i]
        n_b = float(np.linalg.norm(v_before))
        n_a = float(np.linalg.norm(v_after))
        if n_b < min_arc or n_a < min_arc:
            continue
        cos_angle = float(np.dot(v_before, v_after) / (n_b * n_a))
        angle = float(np.arccos(max(-1.0, min(1.0, cos_angle))))
        if angle > angle_thresh_rad:
            candidates.add(i)

    # 2. Speed dips — local minima below dip_ratio * v_max
    dip_thresh = params.dip_ratio * v_max
    for i in range(w, n - w):
        window = speed[i - w:i + w + 1]
        if speed[i] == window.min() and speed[i] < dip_thresh:
            candidates.add(i)

    # 3. Sort, then merge candidates that are too close in 3D.
    # Hard waypoints are never removed.
    hard = set(hard_waypoints) | {0, n - 1}
    ordered = sorted(candidates)
    merged: list[int] = [ordered[0]]
    for idx in ordered[1:]:
        if idx in hard:
            merged.append(idx)
            continue
        dist = float(np.linalg.norm(ee[idx] - ee[merged[-1]]))
        if dist >= params.min_segment_dist_m:
            merged.append(idx)
        # else drop — too close to previous waypoint

    # If the last merged entry isn't the final frame (it was dropped as too
    # close), make sure the final frame is present so nothing gets truncated.
    if merged[-1] != n - 1:
        merged.append(n - 1)

    return merged


# ---------------------------------------------------------------------------
# Primitive emission
# ---------------------------------------------------------------------------

def _round_vec(v: np.ndarray, digits: int = 4) -> dict[str, float]:
    return {"dx": round(float(v[0]), digits), "dy": round(float(v[1]), digits), "dz": round(float(v[2]), digits)}


def waypoints_to_primitives(
    ee: np.ndarray,
    timestamps: np.ndarray,
    waypoints: list[int],
    grasp_f: int | None,
    release_f: int | None,
    min_segment_dist: float,
) -> list[dict]:
    """Emit one move_to_delta per segment + grasp/release at gripper events."""
    primitives: list[dict] = []
    t0 = float(timestamps[0])

    def _ts(frame: int) -> float:
        frame = max(0, min(frame, len(timestamps) - 1))
        return round(float(timestamps[frame]) - t0, 4)

    for a, b in zip(waypoints[:-1], waypoints[1:]):
        delta = ee[b] - ee[a]
        dist = float(np.linalg.norm(delta))
        if dist >= min_segment_dist:
            primitives.append({
                "tool": "move_to_delta",
                "args": _round_vec(delta),
                "timestamp": _ts(a),
            })
        # Insert gripper action at the waypoint we've just arrived at
        if grasp_f is not None and b == grasp_f:
            primitives.append({"tool": "grasp", "args": {"force": 0.5}, "timestamp": _ts(b)})
        if release_f is not None and b == release_f:
            primitives.append({"tool": "release", "args": {}, "timestamp": _ts(b)})

    return primitives


def segment_episode(
    ee: np.ndarray,
    gripper: np.ndarray,
    timestamps: np.ndarray,
    density: str = "medium",
) -> list[dict]:
    """Full episode → list of primitive dicts matching the Demo schema."""
    if density not in DENSITY_PRESETS:
        raise ValueError(f"Unknown density '{density}' (expected: {list(DENSITY_PRESETS)})")
    params = DENSITY_PRESETS[density]

    smooth_ee = _smooth(ee, SMOOTH_K)
    grasp_f, release_f = _find_gripper_events(gripper)

    if grasp_f is None:
        grasp_f = len(ee) // 3
        print("  Warning: grasp event not detected — using frame 1/3 as fallback")
    if release_f is None:
        release_f = 2 * len(ee) // 3
        print("  Warning: release event not detected — using frame 2/3 as fallback")

    hard = [grasp_f, release_f]
    waypoints = detect_waypoints(smooth_ee, hard, params)
    print(f"  Gripper events: grasp@{grasp_f}, release@{release_f} (of {len(ee)} frames)")
    print(f"  Density '{density}' → {len(waypoints)} waypoints")

    return waypoints_to_primitives(
        smooth_ee, timestamps, waypoints, grasp_f, release_f, params.min_segment_dist_m
    )


# ---------------------------------------------------------------------------
# Helper for visualization: return waypoint positions alongside primitives
# ---------------------------------------------------------------------------

def segment_episode_with_waypoints(
    ee: np.ndarray,
    gripper: np.ndarray,
    timestamps: np.ndarray,
    density: str = "medium",
) -> tuple[list[dict], np.ndarray, list[int], int | None, int | None]:
    """Same as segment_episode, but also returns smoothed EE, waypoint frame indices, and gripper-event frames.

    Used by `scripts/visualize_trajectory.py --segment` to overlay segment lines.
    """
    params = DENSITY_PRESETS[density]
    smooth_ee = _smooth(ee, SMOOTH_K)
    grasp_f, release_f = _find_gripper_events(gripper)
    if grasp_f is None:
        grasp_f = len(ee) // 3
    if release_f is None:
        release_f = 2 * len(ee) // 3

    waypoints = detect_waypoints(smooth_ee, [grasp_f, release_f], params)
    primitives = waypoints_to_primitives(
        smooth_ee, timestamps, waypoints, grasp_f, release_f, params.min_segment_dist_m
    )
    return primitives, smooth_ee, waypoints, grasp_f, release_f


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Segment teleop episode into MCP primitive sequence (v2, waypoint-based)")
    parser.add_argument("--dataset", required=True, help="Path to dataset root")
    parser.add_argument("--task", default="", help="Task description for the demo store")
    parser.add_argument("--episode", type=int, default=None, help="Episode index (default: all)")
    parser.add_argument("--density", choices=list(DENSITY_PRESETS), default="medium",
                        help="Waypoint density: low=abstract, high=faithful replay")
    parser.add_argument("--out", default=None, help="Directory to save JSON sequences")
    args = parser.parse_args()

    dataset_root = Path(args.dataset)
    dataset_name = dataset_root.name
    out_dir = Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    df = _load_dataframe(dataset_root)
    df["_ep"] = df["episode_index"].apply(_unwrap_scalar)
    episodes = sorted(df["_ep"].unique())

    if args.episode is not None:
        if args.episode not in episodes:
            raise ValueError(f"Episode {args.episode} not found (available: {episodes})")
        episodes = [args.episode]

    results = {}
    for ep_num in episodes:
        ep_df = df[df["_ep"] == ep_num].reset_index(drop=True)
        print(f"\nEpisode {ep_num} ({len(ep_df)} frames) — running FK...")

        ee, gripper, timestamps = compute_ee_trajectory(ep_df)
        primitives = segment_episode(ee, gripper, timestamps, density=args.density)

        demo = {
            "task": args.task,
            "primitives": primitives,
            "metadata": {
                "dataset": dataset_name,
                "episode": int(ep_num),
                "density": args.density,
                "start_ee_position": {"x": round(float(ee[0, 0]), 4), "y": round(float(ee[0, 1]), 4), "z": round(float(ee[0, 2]), 4)},
            },
        }
        results[ep_num] = demo

        print(f"  → {len(primitives)} primitives:")
        for p in primitives:
            args_str = ", ".join(f"{k}={v}" for k, v in p["args"].items()) if p["args"] else ""
            print(f"      {p['tool']}({args_str})  t={p['timestamp']:.2f}s")

        save_dir = out_dir or (dataset_root / "sequences")
        save_dir.mkdir(parents=True, exist_ok=True)
        suffix = f"_{args.density}" if args.density != "medium" else ""
        out_file = save_dir / f"episode_{int(ep_num):03d}{suffix}.json"
        out_file.write_text(json.dumps(demo, indent=2))
        print(f"  Saved → {out_file}")


if __name__ == "__main__":
    main()
