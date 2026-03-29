"""Abstract SimEnvironment interface.

Any physics backend (PyBullet, Isaac Sim, MuJoCo, etc.) must implement
this interface so the MCP server stays backend-agnostic.
"""

from abc import ABC, abstractmethod
import numpy as np


class SimEnvironment(ABC):
    """Abstract base for robot simulation environments."""

    # ── Lifecycle ──

    @abstractmethod
    def reset(self) -> dict:
        """Reset the environment to initial state.

        Returns: initial observation dict (same format as get_observation).
        """

    @abstractmethod
    def close(self) -> None:
        """Clean up resources (physics engine, GUI, etc.)."""

    # ── Robot control ──

    @abstractmethod
    def move_to(self, x: float, y: float, z: float, velocity: str = "normal") -> dict:
        """Move the end-effector to a Cartesian target in robot base frame.

        Args:
            x, y, z: Target position in meters.
            velocity: "slow" | "normal" | "fast"

        Returns:
            {"status": "complete", "final_position": [x, y, z]}
            or {"status": "failed", "reason": str}
        """

    @abstractmethod
    def grasp(self, force: float = 3.0) -> dict:
        """Close the gripper.

        Args:
            force: Target grip force in Newtons.

        Returns:
            {"status": "complete", "force_achieved": float, "contact": bool}
            or {"status": "failed", "contact": false}
        """

    @abstractmethod
    def release(self) -> dict:
        """Open the gripper fully.

        Returns: {"status": "complete"}
        """

    @abstractmethod
    def stop(self) -> dict:
        """Emergency stop.

        Returns: {"status": "stopped"}
        """

    # ── Observation ──

    @abstractmethod
    def get_camera_image(self) -> np.ndarray:
        """Render a camera image from the environment.

        Returns: BGR uint8 numpy array (H, W, 3).
        """

    @abstractmethod
    def get_gripper_state(self) -> dict:
        """Get current gripper/end-effector state.

        Returns:
            {
                "position": [x, y, z],
                "open": bool,
                "holding": str | None,
            }
        """

    @abstractmethod
    def get_object_states(self) -> list[dict]:
        """Get positions and states of all objects in the scene.

        Returns:
            [{"id": str, "type": str, "color": str,
              "position": [x, y, z], "grasped": bool, "graspable": bool}, ...]
        """

    # ── Convenience ──

    def get_observation(self) -> dict:
        """Full observation combining gripper state + object states.

        Default implementation composes get_gripper_state + get_object_states.
        Override if your backend can do this more efficiently.
        """
        return {
            "gripper": self.get_gripper_state(),
            "objects": self.get_object_states(),
        }
