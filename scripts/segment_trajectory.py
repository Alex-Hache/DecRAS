"""Segment a recorded teleop episode into discrete MCP primitive calls.

Algorithm:
  1. FK all frames → EE positions (N, 3) in meters
  2. Smooth + detect gripper close/open events (grasp / release)
  3. Divide trajectory into phases: approach, carry, retract
  4. Within each phase, greedily detect dominant-axis direction changes
     and emit one primitive per straight-line segment
  5. Output a Demo JSON matching the decras.imitation.retrieval schema

Usage:
    uv run python -m scripts.segment_trajectory --dataset datasets/sticks_v1 --task "pick stick and place at target"
    uv run python -m scripts.segment_trajectory --dataset datasets/sticks_v1 --episode 0 --task "..."
    uv run python -m scripts.segment_trajectory --dataset datasets/sticks_v1 --task "..." --out sequences/
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from mcp_server.robot.kinematics import joints_to_cartesian

_STATE_JOINT_ORDER = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
_GRIPPER_INDEX = 5
_AXIS_NAMES = {
    (0, +1): "move_forward",
    (0, -1): "move_back",
    (1, +1): "move_left",
    (1, -1): "move_right",
    (2, +1): "move_up",
    (2, -1): "move_down",
}

# Tuning knobs
SMOOTH_K = 15          # moving-average window for EE positions
GRIPPER_SMOOTH_K = 15  # moving-average window for gripper values
GRIPPER_THRESHOLD = 0.4  # fraction of actual gripper range — below this = closed
MIN_PRIM_DIST = 0.008  # m — ignore displacements smaller than this (noise)
VELOCITY_MIN = 0.001   # m/frame — frames below this are considered "still"


# ---------------------------------------------------------------------------
# Data loading helpers (shared with visualize_trajectory)
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


# ---------------------------------------------------------------------------
# Core segmentation
# ---------------------------------------------------------------------------

def _smooth(arr: np.ndarray, k: int) -> np.ndarray:
    kernel = np.ones(k) / k
    if arr.ndim == 1:
        return np.convolve(arr, kernel, mode="same")
    return np.stack([np.convolve(arr[:, i], kernel, mode="same") for i in range(arr.shape[1])], axis=1)


def _find_gripper_events(gripper: np.ndarray) -> tuple[int | None, int | None]:
    """Return (grasp_frame, release_frame). None if not detected."""
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


def _segment_phase(ee: np.ndarray, offset: int = 0) -> list[dict]:
    """
    Greedily segment a phase into axis-aligned primitives.
    Returns dicts with a temporary '_frame' key (absolute frame index) for timestamp resolution.
    """
    if len(ee) < 2:
        return []

    primitives = []
    vel = np.gradient(ee, axis=0)
    accum = np.zeros(3)
    prev_dominant = None
    prim_start = offset

    def _emit(accum: np.ndarray, start_frame: int) -> list[dict]:
        prims = []
        for axis in range(3):
            d = accum[axis]
            if abs(d) >= MIN_PRIM_DIST:
                sign = +1 if d > 0 else -1
                prims.append({
                    "tool": _AXIS_NAMES[(axis, sign)],
                    "args": {"distance_m": round(abs(d), 4)},
                    "_frame": start_frame,
                })
        return prims

    for i in range(len(vel)):
        speed = np.abs(vel[i])
        if speed.max() < VELOCITY_MIN:
            continue

        dominant = int(np.argmax(speed))
        sign = int(np.sign(vel[i, dominant]))

        if prev_dominant is None:
            prev_dominant = (dominant, sign)
            prim_start = offset + i

        if (dominant, sign) != prev_dominant:
            primitives.extend(_emit(accum, prim_start))
            accum = np.zeros(3)
            prev_dominant = (dominant, sign)
            prim_start = offset + i

        accum[dominant] += vel[i, dominant]

    primitives.extend(_emit(accum, prim_start))
    return primitives


def _merge_primitives(primitives: list[dict]) -> list[dict]:
    """Merge consecutive same-tool primitives and drop sub-threshold moves."""
    MERGE_MIN = 0.015  # m — drop any primitive below this after merging

    merged = []
    for p in primitives:
        if "distance_m" not in p.get("args", {}):
            merged.append(p)
            continue
        if merged and merged[-1].get("tool") == p["tool"]:
            merged[-1] = {
                **merged[-1],
                "args": {"distance_m": round(merged[-1]["args"]["distance_m"] + p["args"]["distance_m"], 4)},
            }
        else:
            merged.append(dict(p))

    return [p for p in merged if "distance_m" not in p.get("args", {}) or p["args"]["distance_m"] >= MERGE_MIN]


def segment_episode(ee: np.ndarray, gripper: np.ndarray, timestamps: np.ndarray) -> list[dict]:
    """Full episode → list of primitive dicts matching the Demo schema (tool, args, timestamp)."""
    smooth_ee = _smooth(ee, SMOOTH_K)
    grasp_f, release_f = _find_gripper_events(gripper)

    if grasp_f is None:
        grasp_f = len(ee) // 3
        print("  Warning: grasp event not detected — using frame 1/3 as fallback")
    if release_f is None:
        release_f = 2 * len(ee) // 3
        print("  Warning: release event not detected — using frame 2/3 as fallback")

    print(f"  Gripper events: grasp@{grasp_f}, release@{release_f} (of {len(ee)} frames)")

    approach = smooth_ee[:grasp_f]
    carry    = smooth_ee[grasp_f:release_f]
    retract  = smooth_ee[release_f:]

    primitives: list[dict] = []
    primitives.extend(_segment_phase(approach, offset=0))
    primitives.append({"tool": "grasp",   "args": {"force": 0.5}, "_frame": grasp_f})
    primitives.extend(_segment_phase(carry, offset=grasp_f))
    primitives.append({"tool": "release", "args": {},              "_frame": release_f})
    primitives.extend(_segment_phase(retract, offset=release_f))

    merged = _merge_primitives(primitives)

    # Resolve frame indices → wall-clock timestamps relative to episode start
    t0 = float(timestamps[0])
    for p in merged:
        frame = p.pop("_frame", 0)
        p["timestamp"] = round(float(timestamps[min(frame, len(timestamps) - 1)]) - t0, 4)

    return merged


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Segment teleop episode into MCP primitive sequence")
    parser.add_argument("--dataset", required=True, help="Path to dataset root")
    parser.add_argument("--task", default="", help="Task description for the demo store (e.g. 'pick stick and place at target')")
    parser.add_argument("--episode", type=int, default=None, help="Episode index (default: all)")
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
        primitives = segment_episode(ee, gripper, timestamps)

        demo = {
            "task": args.task,
            "primitives": primitives,
            "metadata": {
                "dataset": dataset_name,
                "episode": int(ep_num),
                "start_ee_position": {"x": round(float(ee[0, 0]), 4), "y": round(float(ee[0, 1]), 4), "z": round(float(ee[0, 2]), 4)},
            },
        }
        results[ep_num] = demo

        print(f"  → {len(primitives)} primitives:")
        for p in primitives:
            if "distance_m" in p.get("args", {}):
                print(f"      {p['tool']}({p['args']['distance_m']:.4f} m)  t={p['timestamp']:.2f}s")
            else:
                print(f"      {p['tool']}()  t={p['timestamp']:.2f}s")

        save_dir = out_dir or (dataset_root / "sequences")
        save_dir.mkdir(parents=True, exist_ok=True)
        out_file = save_dir / f"episode_{int(ep_num):03d}.json"
        out_file.write_text(json.dumps(demo, indent=2))
        print(f"  Saved → {out_file}")

    print("\n--- Full JSON output ---")
    print(json.dumps(list(results.values()), indent=2))


if __name__ == "__main__":
    main()
