"""Tests for robot primitives via LeRobotInterface directly."""

from mcp_server.robot.lerobot import LeRobotInterface
from mcp_server.history import PositionHistory


def test_initial_status(mock_robot):
    status = mock_robot.get_status()
    assert "gripper_position" in status
    assert "gripper_open" in status


def test_move_to(mock_robot, history):
    history.record(mock_robot.position)
    result = mock_robot.move_to(0.1, 0.05, 0.1)
    assert result["status"] == "complete"
    assert len(history) == 1


def test_multiple_moves(mock_robot, history):
    for x, y, z in [(0.1, 0.05, 0.1), (0.2, -0.1, 0.05), (0.3, 0.0, 0.02)]:
        history.record(mock_robot.position)
        mock_robot.move_to(x, y, z)
    assert len(history) == 3


def test_grasp_and_release(mock_robot):
    result = mock_robot.grasp(force=2.5)
    assert result["status"] in ("grasped", "complete", "closed")

    status = mock_robot.get_status()
    assert status["gripper_open"] is False

    result = mock_robot.release()
    assert result["status"] in ("released", "complete", "opened")

    status = mock_robot.get_status()
    assert status["gripper_open"] is True


def test_go_back(mock_robot, history):
    for x, y, z in [(0.1, 0.05, 0.1), (0.2, -0.1, 0.05), (0.3, 0.0, 0.02)]:
        history.record(mock_robot.position)
        mock_robot.move_to(x, y, z)

    target = history.go_back(steps=1)
    assert target is not None
    result = mock_robot.move_to(target[0], target[1], target[2])
    assert result["status"] == "complete"

    target = history.go_back(steps=1)
    assert target is not None
    result = mock_robot.move_to(target[0], target[1], target[2])
    assert result["status"] == "complete"


def test_go_back_no_history(history):
    target = history.go_back(steps=10)
    assert target is None


def test_workspace_clamping(mock_robot, history):
    history.record(mock_robot.position)
    result = mock_robot.move_to(999, 999, 999)
    assert result["status"] == "complete"
    status = mock_robot.get_status()
    pos = status["gripper_position"]
    assert pos[0] <= 0.6
    assert pos[1] <= 0.3
    assert pos[2] <= 0.5


def test_stop(mock_robot):
    result = mock_robot.stop()
    assert result["status"] == "stopped"
