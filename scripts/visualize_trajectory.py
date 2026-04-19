"""Visualize EE trajectories from recorded teleop episodes.

Reads a LeRobotDataset Parquet, runs FK on every frame, and plots
the 3D end-effector path — one color per episode.

Usage:
    uv run python -m scripts.visualize_trajectory --dataset datasets/sticks_v1
    uv run python -m scripts.visualize_trajectory --dataset datasets/sticks_v1 --episode 2
    uv run python -m scripts.visualize_trajectory --dataset datasets/sticks_v1 --save traj.png

    # Overlay segmenter v2 output (waypoints + straight-line segments)
    uv run python -m scripts.visualize_trajectory --dataset datasets/sticks_v2 --segment --density low
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from mcp_server.robot.kinematics import JOINT_NAMES_ARM, joints_to_cartesian
from scripts.segment_trajectory import (
    DENSITY_PRESETS,
    compute_ee_trajectory,
    segment_episode_with_waypoints,
)

# Joint order in observation.state (matches info.json feature names)
_STATE_JOINT_ORDER = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
_GRIPPER_INDEX = 5  # last column in observation.state

_COLORS = ["tab:blue", "tab:orange", "tab:green", "tab:red", "tab:purple",
           "tab:brown", "tab:pink", "tab:gray", "tab:olive", "tab:cyan"]


def _load_dataframe(dataset_root: Path) -> pd.DataFrame:
    parquet_files = sorted((dataset_root / "data").rglob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files in {dataset_root}/data")
    return pd.concat([pd.read_parquet(f) for f in parquet_files], ignore_index=True)


def _unwrap_scalar(val):
    """Extract scalar from list/array (LeRobot wraps some columns as 1-element arrays)."""
    if hasattr(val, "__len__"):
        return int(val[0])
    return int(val)


def _compute_ee_and_gripper(episode_df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """FK over all frames → (N,3) EE positions, (N,) gripper values."""
    positions = []
    gripper_vals = []
    for _, row in episode_df.iterrows():
        state = row["observation.state"]
        hw_joints = {name: float(state[i]) for i, name in enumerate(_STATE_JOINT_ORDER)}
        positions.append(joints_to_cartesian(hw_joints))
        gripper_vals.append(float(state[_GRIPPER_INDEX]))
    return np.array(positions), np.array(gripper_vals)


def _find_gripper_events(gripper: np.ndarray, smooth_k: int = 15) -> tuple[int | None, int | None]:
    """Return (grasp_frame, release_frame) indices. None if not found."""
    kernel = np.ones(smooth_k) / smooth_k
    smooth = np.convolve(gripper, kernel, mode="same")
    threshold = gripper.min() + 0.4 * (gripper.max() - gripper.min())  # 40% of actual range

    grasp = release = None
    for i in range(1, len(smooth)):
        # Grasp = gripper opens (UP-crossing): arm opens to grab object
        if smooth[i - 1] < threshold and smooth[i] >= threshold and grasp is None:
            grasp = i
        # Release = gripper closes back (DOWN-crossing after grasp)
        if smooth[i - 1] >= threshold and smooth[i] < threshold and grasp is not None:
            release = i
            break
    return grasp, release


def plot_trajectories(
    dataset_root: Path,
    episode_filter: int | None = None,
    save_path: Path | None = None,
    segment: bool = False,
    density: str = "medium",
) -> None:
    df = _load_dataframe(dataset_root)

    # Normalise episode_index column (may be stored as 1-element list)
    df["_ep"] = df["episode_index"].apply(_unwrap_scalar)
    episodes = sorted(df["_ep"].unique())

    if episode_filter is not None:
        if episode_filter not in episodes:
            raise ValueError(f"Episode {episode_filter} not in dataset (available: {episodes})")
        episodes = [episode_filter]

    fig = plt.figure(figsize=(12, 8))
    ax = fig.add_subplot(111, projection="3d")

    for ep_idx, ep_num in enumerate(episodes):
        color = _COLORS[ep_idx % len(_COLORS)]
        ep_df = df[df["_ep"] == ep_num].reset_index(drop=True)

        print(f"  Episode {ep_num}: {len(ep_df)} frames — running FK...", flush=True)

        if segment:
            ee, gripper, timestamps = compute_ee_trajectory(ep_df)
            prims, smooth_ee, waypoints, grasp_f, release_f = segment_episode_with_waypoints(
                ee, gripper, timestamps, density=density
            )

            # Raw trajectory (faded)
            ax.plot(ee[:, 0], ee[:, 1], ee[:, 2], color=color, linewidth=1.0, alpha=0.35,
                    label=f"Episode {ep_num} (raw)")

            # Segmenter output: dashed straight lines between consecutive waypoints
            wp_xyz = smooth_ee[waypoints]
            ax.plot(wp_xyz[:, 0], wp_xyz[:, 1], wp_xyz[:, 2], color=color, linewidth=2.0,
                    linestyle="--", alpha=0.9, label=f"Ep{ep_num} segments ({density}, {len(prims)} prims)")

            # Waypoint markers
            ax.scatter(wp_xyz[:, 0], wp_xyz[:, 1], wp_xyz[:, 2], color=color, marker="D",
                       s=45, edgecolors="black", linewidths=0.6, zorder=5)

            # Start / end markers on the segment path
            ax.scatter(*wp_xyz[0], color=color, marker="o", s=80, zorder=6)
            ax.scatter(*wp_xyz[-1], color=color, marker="s", s=80, zorder=6)
        else:
            ee, gripper = _compute_ee_and_gripper(ep_df)
            grasp_f, release_f = _find_gripper_events(gripper)

            # Plot path
            ax.plot(ee[:, 0], ee[:, 1], ee[:, 2], color=color, linewidth=1.5,
                    label=f"Episode {ep_num}")

            # Start / end markers
            ax.scatter(*ee[0], color=color, marker="o", s=60, zorder=5)
            ax.scatter(*ee[-1], color=color, marker="s", s=60, zorder=5)

        # Grasp / release markers (same for both modes)
        traj_for_markers = smooth_ee if segment else ee
        if grasp_f is not None:
            ax.scatter(*traj_for_markers[grasp_f], color=color, marker="v", s=110,
                       edgecolors="black", linewidths=0.8, zorder=7, label=f"Ep{ep_num} grasp")
        if release_f is not None:
            ax.scatter(*traj_for_markers[release_f], color=color, marker="^", s=110,
                       edgecolors="black", linewidths=0.8, zorder=7, label=f"Ep{ep_num} release")

    ax.set_xlabel("X — forward (m)")
    ax.set_ylabel("Y — left (m)")
    ax.set_zlabel("Z — up (m)")
    title = f"EE trajectories — {dataset_root.name}"
    if segment:
        title += f"  |  segmenter v2 (density={density})"
    ax.set_title(title)

    # Legend
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles, labels, loc="upper left", fontsize=8)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150)
        print(f"Saved to {save_path}")
    else:
        plt.show()


def main():
    parser = argparse.ArgumentParser(description="Visualize EE trajectories from teleop dataset")
    parser.add_argument("--dataset", required=True, help="Path to dataset root (e.g. datasets/sticks_v1)")
    parser.add_argument("--episode", type=int, default=None, help="Only plot this episode index")
    parser.add_argument("--save", default=None, help="Save plot to this path instead of showing")
    parser.add_argument("--segment", action="store_true",
                        help="Overlay segmenter v2 waypoints + straight-line segments")
    parser.add_argument("--density", choices=list(DENSITY_PRESETS), default="medium",
                        help="Segmenter density when --segment is set")
    args = parser.parse_args()

    dataset_root = Path(args.dataset)
    save_path = Path(args.save) if args.save else None

    print(f"Loading dataset: {dataset_root.resolve()}")
    plot_trajectories(
        dataset_root,
        episode_filter=args.episode,
        save_path=save_path,
        segment=args.segment,
        density=args.density,
    )


if __name__ == "__main__":
    main()
