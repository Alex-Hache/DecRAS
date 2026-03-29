"""Episode recorder — captures structured logs + camera frames for replay.

Each episode is saved to:
  episodes/<timestamp>/
    ├── episode.json    # Full structured log (every step)
    ├── frames/         # PNG frames from each step
    │   ├── 0000.png
    │   ├── 0001.png
    │   └── ...
    └── episode.mp4     # Encoded video (generated after episode ends)
"""

import json
import time
import logging
from datetime import datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

EPISODES_DIR = Path(__file__).parent.parent / "episodes"


class EpisodeRecorder:
    """Records an episode: structured JSON log + camera frames."""

    def __init__(self, task: str = "", output_dir: Path | None = None):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._dir = (output_dir or EPISODES_DIR) / ts
        self._frames_dir = self._dir / "frames"
        self._frames_dir.mkdir(parents=True, exist_ok=True)

        self._episode = {
            "task": task,
            "start_time": time.time(),
            "start_iso": datetime.now().isoformat(),
            "steps": [],
            "summary": {},
        }
        self._frame_count = 0
        self._step_count = 0
        logger.info("Episode recording to %s", self._dir)

    @property
    def episode_dir(self) -> Path:
        return self._dir

    def record_step(
        self,
        action_name: str,
        action_args: dict,
        result: dict,
        scene: dict | None = None,
        thought: str = "",
        llm_response: str = "",
        frame: np.ndarray | None = None,
        duration_ms: float = 0,
    ):
        """Record a single step in the episode."""
        step = {
            "step": self._step_count,
            "timestamp": time.time(),
            "thought": thought,
            "action": action_name,
            "action_args": action_args,
            "result": result,
            "scene": scene,
            "llm_response": llm_response,
            "duration_ms": round(duration_ms, 1),
        }

        # Save frame
        if frame is not None:
            frame_path = self._save_frame(frame)
            step["frame_file"] = frame_path.name
        else:
            step["frame_file"] = None

        self._episode["steps"].append(step)
        self._step_count += 1

        # Log to stdout for container logs
        logger.info(
            "STEP %03d | action=%s(%s) | status=%s | duration=%.0fms",
            step["step"],
            action_name,
            _compact_args(action_args),
            result.get("status", "?"),
            duration_ms,
        )
        if thought:
            logger.info("  THOUGHT: %s", thought[:200])

    def record_frame(self, frame: np.ndarray) -> Path:
        """Record an extra frame (e.g. for observe calls)."""
        return self._save_frame(frame)

    def finish(self, success: bool = False, reason: str = ""):
        """Finalize the episode: write JSON, encode video."""
        self._episode["end_time"] = time.time()
        self._episode["end_iso"] = datetime.now().isoformat()
        self._episode["total_steps"] = self._step_count
        self._episode["total_frames"] = self._frame_count
        elapsed = self._episode["end_time"] - self._episode["start_time"]
        self._episode["summary"] = {
            "success": success,
            "reason": reason,
            "total_steps": self._step_count,
            "elapsed_seconds": round(elapsed, 2),
        }

        # Write JSON log
        json_path = self._dir / "episode.json"
        json_path.write_text(json.dumps(self._episode, indent=2, default=str))
        logger.info("Episode log saved: %s (%d steps, %.1fs)",
                     json_path, self._step_count, elapsed)

        # Encode video
        video_path = self.encode_video()
        if video_path:
            logger.info("Episode video saved: %s", video_path)

        return self._dir

    def encode_video(self, fps: int = 4) -> Path | None:
        """Encode saved frames to MP4 video."""
        if not HAS_CV2:
            logger.warning("opencv not available, skipping video encoding")
            return None

        frames = sorted(self._frames_dir.glob("*.png"))
        if not frames:
            logger.warning("No frames to encode")
            return None

        # Read first frame to get dimensions
        sample = cv2.imread(str(frames[0]))
        h, w = sample.shape[:2]

        video_path = self._dir / "episode.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(video_path), fourcc, fps, (w, h))

        for frame_path in frames:
            img = cv2.imread(str(frame_path))
            if img is not None:
                # Overlay step info
                step_num = int(frame_path.stem)
                if step_num < len(self._episode["steps"]):
                    step = self._episode["steps"][step_num]
                    text = f"Step {step_num}: {step['action']}({_compact_args(step['action_args'])})"
                    cv2.putText(img, text, (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                    if step.get("thought"):
                        cv2.putText(img, step["thought"][:80], (10, 60),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                    status = step["result"].get("status", "")
                    color = (0, 255, 0) if status == "complete" else (0, 0, 255)
                    cv2.putText(img, f"Result: {status}", (10, h - 20),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                writer.write(img)

        writer.release()
        logger.info("Encoded %d frames to %s at %d fps", len(frames), video_path, fps)
        return video_path

    def _save_frame(self, frame: np.ndarray) -> Path:
        """Save a frame as PNG."""
        path = self._frames_dir / f"{self._frame_count:04d}.png"
        if HAS_CV2:
            cv2.imwrite(str(path), frame)
        else:
            # Fallback: save raw numpy
            np.save(str(path).replace(".png", ".npy"), frame)
            path = Path(str(path).replace(".png", ".npy"))
        self._frame_count += 1
        return path


def _compact_args(args: dict) -> str:
    """Format args dict compactly for logging."""
    if not args:
        return ""
    parts = []
    for k, v in args.items():
        if isinstance(v, float):
            parts.append(f"{k}={v:.3f}")
        else:
            parts.append(f"{k}={v}")
    return ", ".join(parts)
