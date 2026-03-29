"""Webcam capture and frame buffering."""

import logging
import numpy as np
from mcp_server.config import SIMULATE

logger = logging.getLogger(__name__)

try:
    import cv2
except ImportError:
    cv2 = None
    logger.warning("opencv-python not installed — camera will use simulated frames")


class Camera:
    def __init__(self, device_id: int = 0):
        self._device_id = device_id
        self._cap = None
        self._last_frame: np.ndarray | None = None

        if not SIMULATE and cv2 is not None:
            self._open()
        elif SIMULATE:
            logger.info("Camera running in SIMULATE mode")

    def _open(self):
        self._cap = cv2.VideoCapture(self._device_id)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open camera device {self._device_id}")
        logger.info("Camera opened on device %d", self._device_id)

    def capture(self) -> np.ndarray:
        """Capture a single frame. Returns BGR numpy array."""
        if SIMULATE or self._cap is None:
            return self._simulated_frame()

        ret, frame = self._cap.read()
        if not ret:
            raise RuntimeError("Failed to capture frame")
        self._last_frame = frame
        return frame

    def _simulated_frame(self) -> np.ndarray:
        """Generate a synthetic frame with colored blobs for testing."""
        frame = np.full((480, 640, 3), (200, 200, 200), dtype=np.uint8)

        if cv2 is not None:
            # Red cup at ~(300, 250)
            cv2.circle(frame, (300, 250), 30, (0, 0, 220), -1)
            # Blue plate at ~(450, 350)
            cv2.ellipse(frame, (450, 350), (50, 25), 0, 0, 360, (220, 120, 0), -1)
        else:
            # Draw without cv2 — simple numpy rectangles
            frame[220:280, 270:330] = [0, 0, 220]   # red cup (BGR)
            frame[325:375, 400:500] = [220, 120, 0]  # blue plate (BGR)

        self._last_frame = frame
        return frame

    @property
    def last_frame(self) -> np.ndarray | None:
        return self._last_frame

    def release(self):
        if self._cap is not None:
            self._cap.release()
