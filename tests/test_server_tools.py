"""Tests for MCP server tool functions (simulation mode)."""

import json
import os

# Ensure simulation mode for these tests
os.environ["SIMULATE"] = "true"

from mcp_server.server import (
    observe, move_to, grasp, release, stop, go_back, get_status,
    start_episode, end_episode, read_joints, calibrate, send_joints,
)


def _parse(result: str) -> dict:
    return json.loads(result)


class TestObserve:
    def test_returns_scene(self):
        result = _parse(observe())
        assert "objects" in result
        assert "gripper" in result

    def test_has_timestamp(self):
        result = _parse(observe())
        assert "timestamp" in result


class TestMoveAndGoBack:
    def test_move_to_returns_json(self):
        result = _parse(move_to(0.2, 0.0, 0.2))
        assert "status" in result

    def test_go_back_no_history_fails(self):
        result = _parse(go_back(steps=100))
        assert result["status"] == "failed"


class TestGraspRelease:
    def test_grasp(self):
        result = _parse(grasp(force=3.0))
        assert "status" in result

    def test_release(self):
        result = _parse(release())
        assert "status" in result


class TestMeta:
    def test_get_status(self):
        result = _parse(get_status())
        assert "gripper_position" in result
        assert "gripper_open" in result

    def test_stop(self):
        result = _parse(stop())
        assert result["status"] == "stopped"

    def test_read_joints(self):
        result = _parse(read_joints())
        assert result["mode"] == "simulation"

    def test_calibrate_skipped_in_sim(self):
        result = _parse(calibrate())
        assert result["status"] == "skipped"

    def test_send_joints_skipped_in_sim(self):
        result = _parse(send_joints(shoulder_pan=10.0))
        assert result["status"] == "skipped"


class TestEpisode:
    def test_start_and_end_episode(self):
        result = _parse(start_episode(task="test task"))
        assert result["status"] == "recording"
        assert "dir" in result

        result = _parse(end_episode(success=True, reason="test"))
        assert result["status"] == "saved"

    def test_end_without_start(self):
        # Ensure no active recorder
        from mcp_server import server
        server.recorder = None

        result = _parse(end_episode())
        assert result["status"] == "no_episode"
