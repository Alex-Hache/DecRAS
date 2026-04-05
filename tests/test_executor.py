"""Tests for control/executor.py — TrajectoryExecutor dry-run mode."""

import numpy as np
import pytest

from control.executor import TrajectoryExecutor, ARM_JOINT_NAMES
from control.trajectory import minimum_jerk_joint_trajectory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def executor():
    """Executor with no robot attached (dry-run)."""
    return TrajectoryExecutor(robot=None, hz=1000.0)  # fast for tests


@pytest.fixture
def simple_traj():
    """5-step, 5-joint trajectory from all-zeros to all-tens."""
    q_start = {name: 0.0 for name in ARM_JOINT_NAMES}
    q_end = {name: 10.0 for name in ARM_JOINT_NAMES}
    return minimum_jerk_joint_trajectory(q_start, q_end, duration=0.1, hz=50.0)


# ---------------------------------------------------------------------------
# Basic execution
# ---------------------------------------------------------------------------

class TestExecute:
    def test_returns_complete_status(self, executor, simple_traj):
        result = executor.execute(simple_traj)
        assert result["status"] == "complete"

    def test_reports_correct_step_count(self, executor, simple_traj):
        result = executor.execute(simple_traj)
        assert result["steps"] == simple_traj.shape[0]

    def test_wrong_joint_count_fails(self, executor):
        bad_traj = np.zeros((5, 3))  # 3 columns but 5 ARM_JOINT_NAMES
        result = executor.execute(bad_traj)
        assert result["status"] == "failed"
        assert "joint" in result["reason"].lower()

    def test_1d_trajectory_fails(self, executor):
        result = executor.execute(np.zeros(5))
        assert result["status"] == "failed"

    def test_custom_joint_names(self, executor):
        traj = np.zeros((3, 2))
        result = executor.execute(traj, joint_names=["shoulder_pan", "elbow_flex"])
        assert result["status"] == "complete"

    def test_gripper_value_accepted(self, executor, simple_traj):
        result = executor.execute(simple_traj, gripper_value=50.0)
        assert result["status"] == "complete"


# ---------------------------------------------------------------------------
# Position history
# ---------------------------------------------------------------------------

class TestHistory:
    def test_history_populated_after_execute(self, executor, simple_traj):
        executor.execute(simple_traj)
        assert len(executor.history) == simple_traj.shape[0]

    def test_history_last_entry_matches_final_waypoint(self, executor, simple_traj):
        executor.execute(simple_traj)
        last = executor.history[-1]
        expected_last = {ARM_JOINT_NAMES[i]: float(simple_traj[-1, i])
                         for i in range(len(ARM_JOINT_NAMES))}
        for k in ARM_JOINT_NAMES:
            assert last[k] == pytest.approx(expected_last[k], abs=1e-9)

    def test_go_back_one(self, executor, simple_traj):
        executor.execute(simple_traj)
        target = executor.go_back(1)
        assert target is not None
        # go_back(1) = last history entry (most recent)
        expected = executor.history[-1]
        for k in ARM_JOINT_NAMES:
            assert target[k] == pytest.approx(expected[k], abs=1e-9)

    def test_go_back_beyond_history_returns_none(self, executor, simple_traj):
        executor.execute(simple_traj)
        steps_in_traj = simple_traj.shape[0]
        assert executor.go_back(steps_in_traj + 999) is None

    def test_go_back_returns_correct_earlier_state(self, executor):
        # Two sequential trajectories — go_back(1) after first traj should
        # give the last step of the first trajectory
        q_a = {name: 0.0 for name in ARM_JOINT_NAMES}
        q_b = {name: 45.0 for name in ARM_JOINT_NAMES}
        traj_a = minimum_jerk_joint_trajectory(q_a, q_b, duration=0.1, hz=50.0)
        executor.execute(traj_a)
        snapshot = executor.go_back(1)
        for k in ARM_JOINT_NAMES:
            assert snapshot[k] == pytest.approx(45.0, abs=0.1)

    def test_history_size_limit(self):
        small_exec = TrajectoryExecutor(robot=None, hz=1000.0, history_size=5)
        # Execute a 20-step trajectory
        traj = np.zeros((20, 5))
        small_exec.execute(traj)
        assert len(small_exec.history) == 5  # capped at history_size


# ---------------------------------------------------------------------------
# Robot delegation (mock)
# ---------------------------------------------------------------------------

class MockRobot:
    """Minimal mock that records send_joint_positions calls."""
    def __init__(self, fail_at: int | None = None):
        self.calls: list[dict] = []
        self.fail_at = fail_at

    def send_joint_positions(self, positions: dict) -> dict:
        self.calls.append(dict(positions))
        if self.fail_at is not None and len(self.calls) >= self.fail_at:
            return {"status": "failed", "reason": "mock_error"}
        return {"status": "complete"}


class TestWithMockRobot:
    def test_sends_to_robot(self):
        mock = MockRobot()
        exec_ = TrajectoryExecutor(robot=mock, hz=1000.0)
        traj = np.zeros((3, 5))
        exec_.execute(traj)
        assert len(mock.calls) == 3

    def test_robot_failure_stops_execution(self):
        mock = MockRobot(fail_at=2)
        exec_ = TrajectoryExecutor(robot=mock, hz=1000.0)
        traj = np.zeros((5, 5))
        result = exec_.execute(traj)
        assert result["status"] == "failed"
        assert result["step"] == 1  # 0-indexed, failed on 2nd call

    def test_gripper_included_in_robot_commands(self):
        mock = MockRobot()
        exec_ = TrajectoryExecutor(robot=mock, hz=1000.0)
        traj = np.zeros((2, 5))
        exec_.execute(traj, gripper_value=75.0)
        for call in mock.calls:
            assert call.get("gripper") == pytest.approx(75.0)
