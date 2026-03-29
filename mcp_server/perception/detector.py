"""Color-based object detection for v0."""

import logging
import numpy as np
from mcp_server.config import OBJECTS

logger = logging.getLogger(__name__)

try:
    import cv2
except ImportError:
    cv2 = None


def detect_objects(frame: np.ndarray) -> list[dict]:
    """Detect known objects by HSV color segmentation.

    Returns a list of detections:
        [{"id": "red_cup", "type": "cup", "color": "red",
          "pixel_center": (cx, cy), "area": int, "graspable": bool}, ...]
    """
    if cv2 is None:
        return _detect_fallback(frame)

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    detections = []

    for obj_id, obj_def in OBJECTS.items():
        lower = np.array(obj_def["hsv_lower"], dtype=np.uint8)
        upper = np.array(obj_def["hsv_upper"], dtype=np.uint8)

        mask = cv2.inRange(hsv, lower, upper)

        # Clean up noise
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            continue

        # Take the largest contour
        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)

        if area < 200:  # noise threshold
            continue

        M = cv2.moments(largest)
        if M["m00"] == 0:
            continue

        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])

        # Derive color name from object id (e.g. "red_cup" -> "red")
        color = obj_id.split("_")[0]

        detections.append({
            "id": obj_id,
            "type": obj_def["type"],
            "color": color,
            "pixel_center": (cx, cy),
            "area": int(area),
            "height": obj_def["height"],
            "graspable": obj_def["graspable"],
        })

    return detections


def _detect_fallback(frame: np.ndarray) -> list[dict]:
    """Simple fallback detection without OpenCV — for pure simulation."""
    detections = []
    for obj_id, obj_def in OBJECTS.items():
        # In simulation, return fixed positions
        if "cup" in obj_id:
            detections.append({
                "id": obj_id,
                "type": obj_def["type"],
                "color": obj_id.split("_")[0],
                "pixel_center": (300, 250),
                "area": 2800,
                "height": obj_def["height"],
                "graspable": obj_def["graspable"],
            })
        elif "plate" in obj_id:
            detections.append({
                "id": obj_id,
                "type": obj_def["type"],
                "color": obj_id.split("_")[0],
                "pixel_center": (450, 350),
                "area": 3900,
                "height": obj_def["height"],
                "graspable": obj_def["graspable"],
            })
    return detections
