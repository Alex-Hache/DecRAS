"""Tests for control/joint_lookup.py — KDTree + KNN + RBF interpolation."""

import json
from pathlib import Path

import numpy as np
import pytest

from control.joint_lookup import JointLookup, ARM_JOINT_NAMES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_calibration_json(path: Path, points: list[dict]) -> Path:
    """Write a minimal calibration JSON file."""
    path.write_text(json.dumps({
        "format_version": 1,
        "num_points": len(points),
        "points": points,
    }))
    return path


def _make_point(x: float, y: float, z: float, joints: dict | None = None) -> dict:
    if joints is None:
        # Simple synthetic joints: pan = 10*x, lift = 10*y, etc.
        joints = {
            "shoulder_pan":  float(x * 100),
            "shoulder_lift": float(y * 100),
            "elbow_flex":    float(z * 100),
            "wrist_flex":    0.0,
            "wrist_roll":    0.0,
            "gripper":       0.0,
        }
    return {"position": {"x": x, "y": y, "z": z}, "joints": joints}


@pytest.fixture
def calib_path(tmp_path):
    """Calibration file with a 3×3×3 synthetic grid (27 points)."""
    xs = [0.15, 0.25, 0.35]
    ys = [-0.10, 0.00, 0.10]
    zs = [0.00, 0.08, 0.15]
    points = [_make_point(x, y, z) for x in xs for y in ys for z in zs]
    return _make_calibration_json(tmp_path / "calib.json", points)


@pytest.fixture
def lookup_knn(calib_path):
    return JointLookup(calibration_path=calib_path, use_rbf=False)


@pytest.fixture
def lookup_rbf(calib_path):
    return JointLookup(calibration_path=calib_path, use_rbf=True)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

class TestLoad:
    def test_loads_correct_num_points(self, lookup_knn):
        assert lookup_knn.num_points == 27

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            JointLookup(calibration_path=tmp_path / "nonexistent.json")

    def test_empty_points_raises(self, tmp_path):
        p = _make_calibration_json(tmp_path / "empty.json", [])
        with pytest.raises(ValueError, match="No calibration points"):
            JointLookup(calibration_path=p)


# ---------------------------------------------------------------------------
# solve — exact recorded points
# ---------------------------------------------------------------------------

class TestSolveExact:
    def test_exact_recorded_point_returns_recorded_joints(self, calib_path):
        """solve() on a point that is in the dataset must return its exact joints."""
        lookup = JointLookup(calibration_path=calib_path)
        # First point: (0.15, -0.10, 0.00)
        result = lookup.solve([0.15, -0.10, 0.00])
        assert isinstance(result, dict)
        assert set(result.keys()) == set(ARM_JOINT_NAMES)
        # shoulder_pan should be 0.15 * 100 = 15.0
        assert result["shoulder_pan"] == pytest.approx(15.0, abs=1e-6)

    def test_returns_all_five_joints(self, lookup_knn):
        result = lookup_knn.solve([0.25, 0.00, 0.08])
        assert set(result.keys()) == set(ARM_JOINT_NAMES)


# ---------------------------------------------------------------------------
# solve — interpolation
# ---------------------------------------------------------------------------

class TestSolveInterpolation:
    def test_midpoint_is_between_neighbours(self, lookup_knn):
        """Interpolated point should be between its two nearest neighbours."""
        # Midpoint between (0.15, 0.00, 0.00) and (0.25, 0.00, 0.00)
        result = lookup_knn.solve([0.20, 0.00, 0.00])
        # shoulder_pan = x*100: should be between 15 and 25
        assert 15.0 < result["shoulder_pan"] < 25.0

    def test_rbf_midpoint_is_between_neighbours(self, lookup_rbf):
        result = lookup_rbf.solve([0.20, 0.00, 0.00])
        assert 15.0 < result["shoulder_pan"] < 25.0


# ---------------------------------------------------------------------------
# Workspace bounds
# ---------------------------------------------------------------------------

class TestWorkspaceBounds:
    def test_solve_refuses_out_of_bounds(self, lookup_knn):
        """Target more than 5 cm from any recorded point should be refused."""
        with pytest.raises(ValueError, match="cm from the nearest"):
            lookup_knn.solve([1.0, 1.0, 1.0])  # far outside workspace

    def test_get_workspace_bounds_returns_correct_range(self, lookup_knn):
        bounds = lookup_knn.get_workspace_bounds()
        assert bounds["x"] == pytest.approx((0.15, 0.35))
        assert bounds["y"] == pytest.approx((-0.10, 0.10))
        assert bounds["z"] == pytest.approx((0.00, 0.15))
        assert bounds["num_points"] == 27

    def test_custom_max_dist(self, calib_path):
        """With max_dist_m=0.01 a nearby but not recorded point should fail."""
        lookup = JointLookup(calibration_path=calib_path, max_dist_m=0.01)
        with pytest.raises(ValueError):
            # 0.16 is 1 cm from 0.15 — may or may not pass depending on grid
            # 0.18 is 3 cm from 0.15, which is > 1 cm → should always fail
            lookup.solve([0.18, 0.00, 0.00])


# ---------------------------------------------------------------------------
# RBF vs KNN consistency
# ---------------------------------------------------------------------------

class TestRbfKnnConsistency:
    def test_exact_point_consistent_across_modes(self, calib_path):
        knn = JointLookup(calibration_path=calib_path, use_rbf=False)
        rbf = JointLookup(calibration_path=calib_path, use_rbf=True)
        target = [0.25, 0.00, 0.08]
        r_knn = knn.solve(target)
        r_rbf = rbf.solve(target)
        for name in ARM_JOINT_NAMES:
            assert r_knn[name] == pytest.approx(r_rbf[name], abs=5.0)
