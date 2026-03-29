"""Tests for episode recording with PyBullet."""

import json
import time
import shutil
from pathlib import Path

import pytest

from mcp_server.sim.pybullet_env import PyBulletEnv
from mcp_server.episode import EpisodeRecorder


@pytest.fixture
def episode_env():
    env = PyBulletEnv(gui=False)
    yield env
    env.close()


def test_episode_recording(episode_env, tmp_path):
    recorder = EpisodeRecorder(task="Test: pick red cup", output_dir=tmp_path)

    # Initial frame
    recorder.record_frame(episode_env.get_camera_image())

    # Scripted steps
    steps = [
        ("observe", {}, lambda: ({"status": "observed"}, episode_env.get_observation())),
        ("move_to", {"x": 0.2, "y": -0.08, "z": 0.12},
         lambda: (episode_env.move_to(0.2, -0.08, 0.12), None)),
        ("grasp", {"force": 3.0},
         lambda: (episode_env.grasp(3.0), None)),
        ("release", {},
         lambda: (episode_env.release(), None)),
    ]

    thoughts = [
        "Let me observe the scene first.",
        "Moving above the red cup.",
        "Grasping the cup.",
        "Releasing the cup.",
    ]

    for (action, args, fn), thought in zip(steps, thoughts):
        t0 = time.time()
        result, extra = fn()
        duration = (time.time() - t0) * 1000

        scene = episode_env.get_observation() if extra is None else extra
        frame = episode_env.get_camera_image()

        recorder.record_step(
            action_name=action,
            action_args=args,
            result=result if isinstance(result, dict) else {"status": "ok"},
            scene=scene,
            thought=thought,
            frame=frame,
            duration_ms=duration,
        )

    ep_dir = recorder.finish(success=True, reason="test_complete")

    # Verify outputs
    assert (ep_dir / "episode.json").exists()
    assert (ep_dir / "episode.mp4").exists()

    frames = list((ep_dir / "frames").glob("*.png"))
    assert len(frames) >= 4

    data = json.loads((ep_dir / "episode.json").read_text())
    assert data["summary"]["success"] is True
    assert data["summary"]["total_steps"] == 4
    assert data["task"] == "Test: pick red cup"


def test_episode_no_frames(tmp_path):
    recorder = EpisodeRecorder(task="Empty episode", output_dir=tmp_path)
    ep_dir = recorder.finish(success=False, reason="no_steps")

    assert (ep_dir / "episode.json").exists()
    data = json.loads((ep_dir / "episode.json").read_text())
    assert data["summary"]["success"] is False
    assert data["summary"]["total_steps"] == 0
