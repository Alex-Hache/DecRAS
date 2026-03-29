"""Assemble a scene graph JSON from detections + robot state."""

import time
import numpy as np
from mcp_server.config import CAMERA_TO_ROBOT_MATRIX


def pixel_to_robot(px: int, py: int, obj_height: float) -> list[float]:
    """Convert pixel coordinates to robot frame using the calibration matrix.

    If no calibration matrix is available, uses a simple linear mapping
    that roughly maps a 640x480 frame to the robot workspace.
    """
    if CAMERA_TO_ROBOT_MATRIX is not None:
        pt = np.array([px, py, 1.0])
        robot_xy = CAMERA_TO_ROBOT_MATRIX @ pt
        return [round(float(robot_xy[0]), 4),
                round(float(robot_xy[1]), 4),
                round(float(obj_height), 4)]

    # Fallback: approximate linear mapping
    # Frame 640x480 -> workspace x:[0.0, 0.4], y:[-0.2, 0.2]
    x = 0.0 + (px / 640.0) * 0.4
    y = -0.2 + (py / 480.0) * 0.4
    z = obj_height
    return [round(x, 4), round(y, 4), round(z, 4)]


def build_scene_graph(
    detections: list[dict],
    gripper_position: list[float],
    gripper_open: bool,
    holding: str | None,
) -> dict:
    """Build the scene graph dict from detections and robot state."""
    objects = []
    for det in detections:
        px, py = det["pixel_center"]
        pos = pixel_to_robot(px, py, det["height"])
        objects.append({
            "id": det["id"],
            "type": det["type"],
            "color": det["color"],
            "position": pos,
            "grasped": det["id"] == holding,
            "graspable": det["graspable"],
        })

    return {
        "objects": objects,
        "gripper": {
            "position": gripper_position,
            "open": gripper_open,
            "holding": holding,
        },
        "timestamp": round(time.time(), 2),
    }
