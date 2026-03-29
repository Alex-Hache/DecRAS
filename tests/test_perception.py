"""Tests for the perception pipeline (camera, detector, scene graph)."""

from mcp_server.perception.camera import Camera
from mcp_server.perception.detector import detect_objects
from mcp_server.perception.scene_graph import build_scene_graph


def test_camera_capture():
    camera = Camera()
    frame = camera.capture()
    assert frame.ndim == 3
    assert frame.shape[2] == 3  # BGR


def test_detect_objects():
    camera = Camera()
    frame = camera.capture()
    detections = detect_objects(frame)
    assert len(detections) >= 2
    ids = [d["id"] for d in detections]
    assert "red_cup" in ids
    assert "blue_plate" in ids


def test_scene_graph():
    camera = Camera()
    frame = camera.capture()
    detections = detect_objects(frame)
    scene = build_scene_graph(
        detections,
        gripper_position=[0.2, 0.0, 0.15],
        gripper_open=True,
        holding=None,
    )
    assert "objects" in scene
    assert "gripper" in scene
    assert len(scene["objects"]) >= 2
    assert scene["gripper"]["open"] is True
    assert scene["gripper"]["holding"] is None
    assert "timestamp" in scene
