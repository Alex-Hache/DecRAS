"""Webcam capture and frame buffering.

``Camera`` accepts either:
  - int   — OpenCV USB device index (``Camera(0)``)
  - str   — an IP Webcam MJPEG stream URL (``Camera("http://192.168.129.1:8080/video")``)
            Bare ``host:port`` is accepted and normalized to ``http://host:port/video``.
"""

import logging
import numpy as np
from mcp_server.config import SIMULATE

logger = logging.getLogger(__name__)

try:
    import cv2
except ImportError:
    cv2 = None
    logger.warning("opencv-python not installed — camera will use simulated frames")


def normalize_camera_source(source: int | str) -> int | str:
    """Pass ints through; coerce string URLs into a form OpenCV can open.

    Rules for strings:
      - If it already has a scheme (``http://``/``https://``/``rtsp://``), leave it.
      - Otherwise prepend ``http://``.
      - If no path is provided (just ``host:port``), append ``/video`` (IP Webcam default MJPEG endpoint).
    """
    if isinstance(source, int):
        return source
    s = str(source).strip()
    if not s:
        raise ValueError("Camera source string is empty")
    lower = s.lower()
    if not (lower.startswith("http://") or lower.startswith("https://") or lower.startswith("rtsp://")):
        s = "http://" + s
    scheme, _, rest = s.partition("://")
    if "/" not in rest:
        s = f"{scheme}://{rest}/video"
    return s


class Camera:
    def __init__(self, source: int | str = 0):
        self._source = normalize_camera_source(source)
        self._cap = None
        self._last_frame: np.ndarray | None = None

        if not SIMULATE and cv2 is not None:
            self._open()
        elif SIMULATE:
            logger.info("Camera running in SIMULATE mode")

    def _open(self):
        self._cap = cv2.VideoCapture(self._source)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open camera source {self._source!r}")
        if isinstance(self._source, str):
            # Minimize latency on HTTP streams — we always want the newest frame, not a backlog.
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        logger.info("Camera opened on source %r", self._source)

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
