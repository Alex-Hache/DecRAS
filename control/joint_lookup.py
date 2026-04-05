"""Joint-space lookup table for DecRAS SO-101 arm.

Loads calibration data (position → joint angles pairs recorded via
calibration/record_grid.py) and solves IK as a data-driven nearest-neighbour
interpolation problem.

Algorithm:
  1. Build a KDTree from the recorded Cartesian positions.
  2. For a query, find K=6 nearest neighbours.
  3. Interpolate joint angles using inverse-distance weighting.
  4. Optionally use scipy RBFInterpolator for smoother results.

Workspace bounds:
  Targets more than MAX_DIST_M from the nearest recorded point are refused.
"""

import json
import logging
from pathlib import Path

import numpy as np
from scipy.spatial import KDTree

logger = logging.getLogger(__name__)

DEFAULT_CALIBRATION_PATH = Path(__file__).parent.parent / "calibration" / "calibration_data.json"
ARM_JOINT_NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
K_NEIGHBORS = 6
MAX_DIST_M = 0.05  # 5 cm — refuse targets farther than this from any recorded point


class JointLookup:
    """Data-driven joint-space lookup table using KDTree + KNN interpolation.

    Args:
        calibration_path: Path to calibration_data.json. If None, uses the
            default path at ``calibration/calibration_data.json``.
        use_rbf: If True, use RBFInterpolator (smooth) instead of KNN.
        k: Number of nearest neighbours for KNN interpolation.
        max_dist_m: Maximum allowed distance from the nearest recorded point.
    """

    def __init__(
        self,
        calibration_path: "Path | str | None" = None,
        use_rbf: bool = False,
        k: int = K_NEIGHBORS,
        max_dist_m: float = MAX_DIST_M,
    ):
        self._path = Path(calibration_path) if calibration_path else DEFAULT_CALIBRATION_PATH
        self._use_rbf = use_rbf
        self._k = k
        self._max_dist_m = max_dist_m

        self._positions: "np.ndarray | None" = None  # (N, 3) float64
        self._joints: "np.ndarray | None" = None      # (N, 5) float64
        self._tree: "KDTree | None" = None
        self._rbf_interpolators: "list | None" = None

        self._load()

    # ------------------------------------------------------------------
    # Internal loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load calibration data from JSON and build the KDTree."""
        with open(self._path) as f:
            data = json.load(f)

        points = data.get("points", [])
        if not points:
            raise ValueError(f"No calibration points found in {self._path}")

        positions = []
        joints_list = []
        for p in points:
            pos = p["position"]
            positions.append([pos["x"], pos["y"], pos["z"]])
            j = p["joints"]
            joints_list.append([j.get(name, 0.0) for name in ARM_JOINT_NAMES])

        self._positions = np.array(positions, dtype=np.float64)
        self._joints = np.array(joints_list, dtype=np.float64)
        self._tree = KDTree(self._positions)

        if self._use_rbf:
            self._build_rbf()

        logger.info(
            "JointLookup loaded %d calibration points from %s (mode=%s)",
            len(points),
            self._path,
            "rbf" if self._use_rbf else "knn",
        )

    def _build_rbf(self) -> None:
        """Build one RBFInterpolator per joint dimension."""
        from scipy.interpolate import RBFInterpolator
        self._rbf_interpolators = [
            RBFInterpolator(
                self._positions,
                self._joints[:, i],
                kernel="thin_plate_spline",
            )
            for i in range(len(ARM_JOINT_NAMES))
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def solve(self, target_xyz: "list[float] | np.ndarray") -> "dict[str, float]":
        """Solve for joint angles at a target Cartesian position.

        Args:
            target_xyz: [x, y, z] in metres (robot base frame).

        Returns:
            Dict of joint angles in degrees: ``{"shoulder_pan": ..., ...}``

        Raises:
            ValueError: If the target is too far from the calibrated workspace.
        """
        target = np.array(target_xyz, dtype=np.float64).reshape(1, 3)

        # Workspace bounds check — refuse out-of-reach targets
        dist, _ = self._tree.query(target, k=1)
        nearest_dist = float(dist[0, 0] if dist.ndim == 2 else dist[0])
        if nearest_dist > self._max_dist_m:
            raise ValueError(
                f"Target {list(target_xyz)} is {nearest_dist * 100:.1f} cm from the "
                f"nearest calibration point (max allowed: {self._max_dist_m * 100:.1f} cm). "
                "Record more calibration points near this region."
            )

        if self._use_rbf and self._rbf_interpolators is not None:
            angles = self._solve_rbf(target)
        else:
            angles = self._solve_knn(target)

        return {name: float(angles[i]) for i, name in enumerate(ARM_JOINT_NAMES)}

    def get_workspace_bounds(self) -> dict:
        """Return the axis-aligned bounding box of the calibration point cloud."""
        if self._positions is None or len(self._positions) == 0:
            return {}
        return {
            "x": (float(self._positions[:, 0].min()), float(self._positions[:, 0].max())),
            "y": (float(self._positions[:, 1].min()), float(self._positions[:, 1].max())),
            "z": (float(self._positions[:, 2].min()), float(self._positions[:, 2].max())),
            "num_points": len(self._positions),
        }

    @property
    def num_points(self) -> int:
        return len(self._positions) if self._positions is not None else 0

    # ------------------------------------------------------------------
    # Internal solvers
    # ------------------------------------------------------------------

    def _solve_knn(self, target: np.ndarray) -> np.ndarray:
        """KNN + inverse-distance weighting."""
        k = min(self._k, len(self._positions))
        dists, idxs = self._tree.query(target, k=k)
        dists = dists.flatten()
        idxs = idxs.flatten()

        # Exact match — return recorded joints directly
        if dists[0] == 0.0:
            return self._joints[idxs[0]]

        weights = 1.0 / dists
        weights /= weights.sum()
        return (weights[:, np.newaxis] * self._joints[idxs]).sum(axis=0)

    def _solve_rbf(self, target: np.ndarray) -> np.ndarray:
        """RBF interpolation — smooth but slower than KNN."""
        return np.array([float(rbf(target)[0]) for rbf in self._rbf_interpolators])
