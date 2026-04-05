"""Tests for calibration/record_grid.py — data model and utility functions."""

import json
from pathlib import Path

import pytest

from calibration.record_grid import (
    compute_coverage,
    load_existing_data,
    save_data,
    GRID_SPEC,
)


@pytest.fixture
def sample_points():
    return [
        {
            "index": 1,
            "position": {"x": 0.20, "y": 0.00, "z": 0.05},
            "joints": {
                "shoulder_pan": -18.0,
                "shoulder_lift": -60.0,
                "elbow_flex": 37.0,
                "wrist_flex": 74.0,
                "wrist_roll": 0.0,
                "gripper": 0.0,
            },
            "timestamp": "2026-04-05T12:00:00+00:00",
        },
        {
            "index": 2,
            "position": {"x": 0.30, "y": 0.10, "z": 0.12},
            "joints": {
                "shoulder_pan": -10.0,
                "shoulder_lift": -50.0,
                "elbow_flex": 30.0,
                "wrist_flex": 60.0,
                "wrist_roll": 5.0,
                "gripper": 0.0,
            },
            "timestamp": "2026-04-05T12:01:00+00:00",
        },
    ]


class TestSaveLoad:
    def test_save_and_load_roundtrip(self, tmp_path, sample_points):
        path = tmp_path / "calibration_data.json"
        save_data(path, sample_points)

        loaded = load_existing_data(path)
        assert len(loaded) == 2
        assert loaded[0]["position"]["x"] == pytest.approx(0.20)
        assert loaded[1]["joints"]["shoulder_pan"] == pytest.approx(-10.0)

    def test_load_nonexistent_returns_empty(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        assert load_existing_data(path) == []

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "data.json"
        save_data(path, [])
        assert path.exists()

    def test_save_format_version(self, tmp_path, sample_points):
        path = tmp_path / "data.json"
        save_data(path, sample_points)
        with open(path) as f:
            data = json.load(f)
        assert data["format_version"] == 1
        assert data["num_points"] == 2
        assert "grid_spec" in data
        assert "last_updated" in data

    def test_resume_appends(self, tmp_path, sample_points):
        """Saving more points preserves all data."""
        path = tmp_path / "data.json"
        save_data(path, sample_points[:1])
        loaded = load_existing_data(path)
        assert len(loaded) == 1

        loaded.append(sample_points[1])
        save_data(path, loaded)
        reloaded = load_existing_data(path)
        assert len(reloaded) == 2


class TestCoverage:
    def test_empty_coverage(self):
        cov = compute_coverage([])
        assert cov["count"] == 0
        assert cov["x_range"] is None

    def test_single_point_coverage(self, sample_points):
        cov = compute_coverage(sample_points[:1])
        assert cov["count"] == 1
        assert cov["x_range"] == (0.20, 0.20)

    def test_multi_point_coverage(self, sample_points):
        cov = compute_coverage(sample_points)
        assert cov["count"] == 2
        assert cov["x_range"] == pytest.approx((0.20, 0.30))
        assert cov["y_range"] == pytest.approx((0.00, 0.10))
        assert cov["z_range"] == pytest.approx((0.05, 0.12))


class TestGridSpec:
    def test_grid_spec_values(self):
        assert GRID_SPEC["x_range"] == (0.15, 0.35)
        assert GRID_SPEC["y_range"] == (-0.15, 0.15)
        assert GRID_SPEC["z_range"] == (0.00, 0.15)
        assert GRID_SPEC["target_points"] == 75
