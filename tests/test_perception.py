"""Tests for the perception pipeline (camera, detector, scene graph)."""

import pytest

from mcp_server.perception.camera import Camera, normalize_camera_source
from mcp_server.perception.detector import detect_objects
from mcp_server.perception.scene_graph import build_scene_graph


def test_normalize_camera_source_passes_int():
    assert normalize_camera_source(0) == 0
    assert normalize_camera_source(2) == 2


def test_normalize_camera_source_bare_host_port():
    assert normalize_camera_source("192.168.129.1:8080") == "http://192.168.129.1:8080/video"


def test_normalize_camera_source_preserves_scheme():
    assert normalize_camera_source("http://cam/video") == "http://cam/video"
    assert normalize_camera_source("https://cam:443/stream") == "https://cam:443/stream"
    assert normalize_camera_source("rtsp://cam/live") == "rtsp://cam/live"


def test_normalize_camera_source_appends_video_path():
    assert normalize_camera_source("http://cam:8080") == "http://cam:8080/video"


def test_normalize_camera_source_rejects_empty():
    with pytest.raises(ValueError):
        normalize_camera_source("")


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
