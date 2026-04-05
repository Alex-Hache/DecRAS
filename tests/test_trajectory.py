"""Tests for control/trajectory.py — minimum-jerk trajectory generation."""

import numpy as np
import pytest

from control.trajectory import (
    minimum_jerk_profile,
    minimum_jerk_joint_trajectory,
    compute_duration,
    SPEED_DURATIONS,
)


# ---------------------------------------------------------------------------
# minimum_jerk_profile
# ---------------------------------------------------------------------------

class TestMinimumJerkProfile:
    def test_starts_at_zero(self):
        s = minimum_jerk_profile(np.array([0.0]))
        assert s[0] == pytest.approx(0.0)

    def test_ends_at_one(self):
        s = minimum_jerk_profile(np.array([1.0]))
        assert s[0] == pytest.approx(1.0)

    def test_monotone_increasing(self):
        t = np.linspace(0.0, 1.0, 100)
        s = minimum_jerk_profile(t)
        assert np.all(np.diff(s) >= 0)

    def test_clamps_below_zero(self):
        s = minimum_jerk_profile(np.array([-0.5]))
        assert s[0] == pytest.approx(0.0)

    def test_clamps_above_one(self):
        s = minimum_jerk_profile(np.array([1.5]))
        assert s[0] == pytest.approx(1.0)

    def test_symmetric_about_midpoint(self):
        t = np.linspace(0.0, 1.0, 101)
        s = minimum_jerk_profile(t)
        # s(t) + s(1-t) = 1 for minimum-jerk profile
        assert np.allclose(s + s[::-1], 1.0, atol=1e-10)


# ---------------------------------------------------------------------------
# minimum_jerk_joint_trajectory — array inputs
# ---------------------------------------------------------------------------

class TestTrajectoryArrayInputs:
    def test_shape(self):
        traj = minimum_jerk_joint_trajectory(
            q_start=[0.0, 0.0, 0.0],
            q_end=[90.0, 45.0, 30.0],
            duration=1.0,
            hz=50.0,
        )
        assert traj.shape == (50, 3)

    def test_starts_at_q_start(self):
        q_start = [10.0, -20.0, 5.0]
        q_end = [50.0, 30.0, -10.0]
        traj = minimum_jerk_joint_trajectory(q_start, q_end, duration=1.0)
        assert np.allclose(traj[0], q_start, atol=1e-9)

    def test_ends_at_q_end(self):
        q_start = [10.0, -20.0, 5.0]
        q_end = [50.0, 30.0, -10.0]
        traj = minimum_jerk_joint_trajectory(q_start, q_end, duration=1.0)
        assert np.allclose(traj[-1], q_end, atol=1e-9)

    def test_monotone_for_single_joint_increasing(self):
        traj = minimum_jerk_joint_trajectory([0.0], [90.0], duration=1.0)
        assert np.all(np.diff(traj[:, 0]) >= 0)

    def test_zero_motion_stays_constant(self):
        traj = minimum_jerk_joint_trajectory([20.0, 30.0], [20.0, 30.0], duration=1.0)
        assert np.allclose(traj, [[20.0, 30.0]] * traj.shape[0], atol=1e-9)

    def test_minimum_two_steps(self):
        traj = minimum_jerk_joint_trajectory([0.0], [1.0], duration=0.001, hz=50.0)
        assert traj.shape[0] >= 2


# ---------------------------------------------------------------------------
# minimum_jerk_joint_trajectory — dict inputs
# ---------------------------------------------------------------------------

class TestTrajectoryDictInputs:
    def test_dict_inputs_match_array(self):
        q_start = {"a": 10.0, "b": -20.0}
        q_end = {"a": 50.0, "b": 30.0}
        traj = minimum_jerk_joint_trajectory(q_start, q_end, duration=1.0, hz=50.0)
        assert traj.shape == (50, 2)
        assert np.allclose(traj[0], [10.0, -20.0], atol=1e-9)
        assert np.allclose(traj[-1], [50.0, 30.0], atol=1e-9)


# ---------------------------------------------------------------------------
# compute_duration
# ---------------------------------------------------------------------------

class TestComputeDuration:
    def test_normal_large_move_uses_base_duration(self):
        # 90° move → scale = 1.0 → normal base = 1.5 s
        d = compute_duration([0.0], [90.0], speed="normal")
        assert d == pytest.approx(1.5, rel=0.01)

    def test_small_move_is_shorter(self):
        d_large = compute_duration([0.0], [90.0], speed="normal")
        d_small = compute_duration([0.0], [9.0], speed="normal")
        assert d_small < d_large

    def test_minimum_duration_floor(self):
        # Tiny move should still be at least 0.2 s
        d = compute_duration([0.0], [0.001], speed="fast")
        assert d >= 0.2

    def test_speed_ordering(self):
        q_start, q_end = [0.0], [90.0]
        d_slow = compute_duration(q_start, q_end, speed="slow")
        d_normal = compute_duration(q_start, q_end, speed="normal")
        d_fast = compute_duration(q_start, q_end, speed="fast")
        assert d_slow > d_normal > d_fast

    def test_unknown_speed_falls_back_to_normal(self):
        d = compute_duration([0.0], [90.0], speed="turbo")
        assert d == pytest.approx(compute_duration([0.0], [90.0], speed="normal"))

    def test_dict_inputs(self):
        d = compute_duration({"j": 0.0}, {"j": 90.0}, speed="normal")
        assert d == pytest.approx(1.5, rel=0.01)
