"""PyBullet simulation tests — exercises the SimEnvironment interface."""

import numpy as np
import pytest

from mcp_server.sim.pybullet_env import PyBulletEnv


@pytest.fixture(scope="module")
def sim():
    """Module-scoped PyBullet env — shared across tests for sequential state."""
    env = PyBulletEnv(gui=False)
    yield env
    env.close()


def test_initial_observation(sim):
    obs = sim.get_observation()
    assert "gripper" in obs
    assert "objects" in obs
    assert obs["gripper"]["open"] is True


def test_camera_image(sim):
    img = sim.get_camera_image()
    assert isinstance(img, np.ndarray)
    assert img.ndim == 3
    assert img.shape[2] == 3  # BGR


def test_find_objects(sim):
    obs = sim.get_observation()
    ids = [obj["id"] for obj in obs["objects"]]
    assert "red_cup" in ids
    assert "blue_plate" in ids


def test_pick_and_place(sim):
    """Full pick-and-place: find cup, approach gradually, grasp, lift, place, release."""
    obs = sim.get_observation()
    cup_pos = None
    plate_pos = None
    for obj in obs["objects"]:
        if obj["id"] == "red_cup":
            cup_pos = obj["position"]
        elif obj["id"] == "blue_plate":
            plate_pos = obj["position"]

    assert cup_pos is not None, "Red cup not found"
    assert plate_pos is not None, "Blue plate not found"

    # Warm-up: gradual approach from home (IK needs intermediate waypoints)
    sim.move_to(0.15, 0.0, 0.25, velocity="slow")
    sim.move_to(0.2, 0.0, 0.20, velocity="slow")

    # Move above cup
    result = sim.move_to(cup_pos[0], cup_pos[1], cup_pos[2] + 0.10)
    assert result["status"] == "complete"

    # Move down to cup
    result = sim.move_to(cup_pos[0], cup_pos[1], cup_pos[2] + 0.04)
    assert result["status"] == "complete"

    # Grasp
    result = sim.grasp(force=3.0)
    assert result["status"] in ("grasped", "complete")
    gripper = sim.get_gripper_state()
    assert gripper["open"] is False

    # Lift
    result = sim.move_to(cup_pos[0], cup_pos[1], 0.20)
    assert result["status"] == "complete"

    # Move above plate
    result = sim.move_to(plate_pos[0], plate_pos[1], 0.15)
    assert result["status"] == "complete"

    # Lower and release
    result = sim.move_to(plate_pos[0], plate_pos[1], plate_pos[2] + 0.08)
    assert result["status"] == "complete"
    result = sim.release()
    assert result["status"] in ("released", "complete")

    gripper = sim.get_gripper_state()
    assert gripper["open"] is True


def test_stop(sim):
    result = sim.stop()
    assert result["status"] == "stopped"
