"""Trajectory executor for the SO-101 arm.

Sends pre-computed joint trajectories to the robot at a fixed control rate
(default 50 Hz).  Handles precise timing so waypoints arrive on schedule even
when individual ``send_joint_positions`` calls vary in latency.

Also keeps a fixed-size position history buffer so the MCP ``go_back`` tool
can rewind to an earlier joint state.
"""

import time
import logging
from collections import deque

import numpy as np

logger = logging.getLogger(__name__)

ARM_JOINT_NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
CONTROL_HZ = 50.0


class TrajectoryExecutor:
    """Execute joint trajectories at a fixed control rate.

    Args:
        robot: A ``LeRobotInterface`` instance, or ``None`` for dry-run mode
               (trajectory is timed but no commands are sent).
        hz: Control frequency in Hz. Default 50 Hz.
        history_size: Number of joint states kept in the position history.
    """

    def __init__(self, robot=None, hz: float = CONTROL_HZ, history_size: int = 200):
        self._robot = robot
        self._hz = hz
        self._dt = 1.0 / hz
        self._history: deque = deque(maxlen=history_size)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        trajectory: np.ndarray,
        joint_names: "list[str] | None" = None,
        gripper_value: "float | None" = None,
    ) -> dict:
        """Send a joint trajectory to the robot waypoint-by-waypoint.

        Args:
            trajectory: ``(steps, num_joints)`` array of joint angles in degrees.
            joint_names: Names of the joints corresponding to each column.
                         Defaults to ``ARM_JOINT_NAMES``.
            gripper_value: Gripper position held constant during execution
                           (0 = closed, 100 = open).  If ``None``, gripper is
                           not commanded.

        Returns:
            ``{"status": "complete", "steps": int}`` or
            ``{"status": "failed", "reason": str, "step": int}``
        """
        if joint_names is None:
            joint_names = ARM_JOINT_NAMES

        if trajectory.ndim != 2:
            return {"status": "failed", "reason": "trajectory must be a 2-D array"}

        steps, num_joints = trajectory.shape
        if num_joints != len(joint_names):
            return {
                "status": "failed",
                "reason": (
                    f"trajectory has {num_joints} columns but "
                    f"{len(joint_names)} joint names were given"
                ),
            }

        dt = self._dt

        for i, waypoint in enumerate(trajectory):
            t0 = time.perf_counter()

            joint_positions = {
                name: float(waypoint[j]) for j, name in enumerate(joint_names)
            }
            if gripper_value is not None:
                joint_positions["gripper"] = float(gripper_value)

            # Buffer for go_back
            self._history.append(dict(joint_positions))

            if self._robot is not None:
                result = self._robot.send_joint_positions(joint_positions)
                if result.get("status") != "complete":
                    return {
                        "status": "failed",
                        "reason": result.get("reason", "unknown"),
                        "step": i,
                    }

            # Timing control — sleep for the remainder of the dt window
            elapsed = time.perf_counter() - t0
            remaining = dt - elapsed
            if remaining > 0:
                time.sleep(remaining)

        logger.debug("Trajectory executed: %d steps at %.0f Hz", steps, self._hz)
        return {"status": "complete", "steps": steps}

    def go_back(self, steps: int = 1) -> "dict[str, float] | None":
        """Return the joint state from N positions ago in the history buffer.

        Args:
            steps: How many states to rewind.

        Returns:
            Joint position dict, or ``None`` if there is not enough history.
        """
        if len(self._history) < steps:
            return None
        history_list = list(self._history)
        return dict(history_list[len(history_list) - steps])

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def hz(self) -> float:
        return self._hz

    @property
    def history(self) -> "list[dict[str, float]]":
        return list(self._history)
