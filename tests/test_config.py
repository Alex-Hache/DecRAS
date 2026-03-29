"""Tests for configuration module."""

from mcp_server.config import OBJECTS, WORKSPACE, FORCE_LIMIT, POSITION_HISTORY_SIZE


def test_objects_defined():
    assert "red_cup" in OBJECTS
    assert "blue_plate" in OBJECTS


def test_object_properties():
    cup = OBJECTS["red_cup"]
    assert cup["graspable"] is True
    assert "hsv_lower" in cup
    assert "hsv_upper" in cup
    assert len(cup["hsv_lower"]) == 3
    assert len(cup["hsv_upper"]) == 3

    plate = OBJECTS["blue_plate"]
    assert plate["graspable"] is False


def test_workspace_limits():
    assert WORKSPACE["x_min"] < WORKSPACE["x_max"]
    assert WORKSPACE["y_min"] < WORKSPACE["y_max"]
    assert WORKSPACE["z_min"] < WORKSPACE["z_max"]
    assert WORKSPACE["z_min"] >= 0.0  # No negative Z


def test_safety_constants():
    assert FORCE_LIMIT > 0
    assert POSITION_HISTORY_SIZE > 0
