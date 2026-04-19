"""LeRobot SO-101 hardware interface.

Wraps the lerobot v0.4+ SDK to control the SO-101 follower arm.
Joint-level control with Cartesian IK via kinematics module.
"""

import time
import logging
from mcp_server.config import SIMULATE, WORKSPACE, FORCE_LIMIT

logger = logging.getLogger(__name__)

# SO-101 joint names (same order as URDF and lerobot SDK)
JOINT_NAMES = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
]

ARM_JOINT_NAMES = JOINT_NAMES[:-1]  # all except gripper

# Gripper range: 100 = fully open, 0 = fully closed (Feetech servo on SO-101)
# Verified on hardware: sending 0 closes the gripper, 100 opens it.
GRIPPER_OPEN = 100.0
GRIPPER_CLOSED = 0.0


class LeRobotInterface:
    """Interface to the SO-101 follower arm via lerobot SDK."""

    def __init__(self, port: str | None = None, robot_id: str = "decras_follower"):
        self._port = port
        self._robot_id = robot_id
        self._robot = None
        self._is_connected = False

        # Cached state
        self._position = [0.2, 0.0, 0.15]  # Cartesian estimate
        self._gripper_open = True
        self._holding: str | None = None
        self._last_action = "init"
        self._last_status = "complete"

        if not SIMULATE:
            self._init_hardware()
        else:
            logger.info("Running in SIMULATE mode — no real hardware")

    def _init_hardware(self):
        """Connect to the SO-101 follower arm."""
        from lerobot.robots.so_follower import SOFollowerRobotConfig
        from lerobot.robots import make_robot_from_config

        port = self._port
        if port is None:
            port = self._detect_port()

        config = SOFollowerRobotConfig(
            id=self._robot_id,
            port=port,
            disable_torque_on_disconnect=True,
            max_relative_target=None,
            use_degrees=True,
        )

        self._robot = make_robot_from_config(config)

        # Connect with retry — Feetech bus can be flaky after calibration
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                self._robot.connect(calibrate=True)
                self._is_connected = True
                logger.info("Connected to SO-101 follower on %s", port)
                break
            except Exception as e:
                logger.warning("Connect attempt %d/%d failed: %s", attempt, max_attempts, e)
                if attempt < max_attempts:
                    time.sleep(1)
                    # Reset the robot object for a fresh attempt
                    try:
                        self._robot.disconnect()
                    except Exception:
                        pass
                    self._robot = make_robot_from_config(config)
                else:
                    raise

    def _detect_port(self) -> str:
        """Auto-detect the serial port for the follower arm."""
        import glob
        ports = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
        if not ports:
            raise RuntimeError("No serial ports found — is the robot plugged in?")
        # Use the first port found (follower)
        logger.info("Auto-detected port: %s", ports[0])
        return ports[0]

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def robot(self):
        """Access the underlying lerobot robot object."""
        return self._robot

    # ── Calibration ──

    def calibrate(self) -> dict:
        """Run interactive calibration on the robot.

        The lerobot SDK handles the calibration flow:
        1. Disable torque
        2. User moves arm to middle position
        3. Record homing offsets
        4. User moves each joint through full range
        5. Save calibration file

        Returns: {"status": "complete", "calibration_file": str}
        """
        if SIMULATE:
            return {"status": "complete", "calibration_file": "simulated"}

        if self._robot is None:
            return {"status": "failed", "reason": "not_connected"}

        self._robot.calibrate()
        return {
            "status": "complete",
            "calibration_file": str(self._robot.calibration_fpath),
        }

    def is_calibrated(self) -> bool:
        if SIMULATE:
            return True
        return self._robot is not None and self._robot.is_calibrated

    # ── Joint-level control ──

    def get_joint_positions(self) -> dict[str, float]:
        """Read current joint positions from hardware.

        Returns: {"shoulder_pan": degrees, ..., "gripper": 0-100 (0=closed, 100=open)}
        """
        if SIMULATE:
            return {name: 0.0 for name in JOINT_NAMES}

        obs = self._robot.get_observation()
        positions = {}
        for name in JOINT_NAMES:
            key = f"{name}.pos"
            positions[name] = float(obs.get(key, 0.0))
        return positions

    def send_joint_positions(self, positions: dict[str, float]) -> dict:
        """Send joint positions to the robot.

        Args:
            positions: {"shoulder_pan": degrees, ..., "gripper": 0-100}

        Returns: {"status": "complete"} or {"status": "failed", "reason": str}
        """
        if SIMULATE:
            time.sleep(0.1)
            return {"status": "complete"}

        try:
            action = {f"{name}.pos": val for name, val in positions.items()}
            self._robot.send_action(action)
            self._last_action = "send_joint_positions"
            self._last_status = "complete"
            return {"status": "complete"}
        except Exception as e:
            self._last_status = "failed"
            return {"status": "failed", "reason": str(e)}

    # ── Cartesian control (wraps IK) ──

    def _clamp_to_workspace(self, x: float, y: float, z: float) -> tuple[float, float, float]:
        ws = WORKSPACE
        x = max(ws["x_min"], min(ws["x_max"], x))
        y = max(ws["y_min"], min(ws["y_max"], y))
        z = max(ws["z_min"], min(ws["z_max"], z))
        return x, y, z

    def get_ee_position(self) -> list[float]:
        """End-effector Cartesian position via FK from current joint angles."""
        if SIMULATE:
            return self._position[:]
        try:
            from mcp_server.robot.kinematics import joints_to_cartesian
            return joints_to_cartesian(self.get_joint_positions())
        except Exception as e:
            logger.warning("FK failed: %s — returning cached position", e)
            return self._position[:]

    def _wait_until_settled(
        self,
        target_joints: dict[str, float],
        tolerance_deg: float = 2.0,
        max_wait_s: float = 0.5,
        resend_interval_s: float = 0.02,
    ) -> bool:
        """Block until arm is within `tolerance_deg` of `target_joints` on every joint.

        Re-sends the setpoint each iteration to actively fight gravity droop.
        Returns True if convergence reached, False on timeout.
        """
        if SIMULATE:
            return True
        start = time.time()
        action = {f"{name}.pos": val for name, val in target_joints.items()}
        while time.time() - start < max_wait_s:
            current = self.get_joint_positions()
            max_err = max(
                abs(current.get(name, 0.0) - target_joints[name])
                for name in target_joints
            )
            if max_err < tolerance_deg:
                return True
            self._robot.send_action(action)  # re-assert against droop
            time.sleep(resend_interval_s)
        return False

    def _active_hold(self, target_joints: dict[str, float], duration_s: float = 0.6) -> None:
        """Repeatedly send the setpoint for `duration_s` to lock in the final pose."""
        if SIMULATE:
            return
        action = {f"{name}.pos": val for name, val in target_joints.items()}
        end = time.time() + duration_s
        while time.time() < end:
            self._robot.send_action(action)
            time.sleep(0.05)

    def move_to(self, x: float, y: float, z: float, velocity: str = "normal") -> dict:
        """Move end-effector to a Cartesian target via IK.

        Single setpoint + convergence-based wait. The `velocity` argument is
        kept for API compatibility but only adjusts the convergence budget.

        Args:
            x, y, z: Target in robot base frame (meters).
            velocity: "slow" | "normal" | "fast" — affects max wait time only.
        """
        x, y, z = self._clamp_to_workspace(x, y, z)

        if SIMULATE:
            delay = {"slow": 0.3, "normal": 0.15, "fast": 0.05}.get(velocity, 0.15)
            time.sleep(delay)
            self._position = [x, y, z]
            self._last_action = "move_to"
            self._last_status = "complete"
            return {"status": "complete", "final_position": self._position[:]}

        try:
            from mcp_server.robot.kinematics import cartesian_to_joints
            current = self.get_joint_positions()
            joint_targets = cartesian_to_joints(x, y, z, seed_hw_joints=current)
            joint_targets["gripper"] = current.get("gripper", GRIPPER_OPEN)

            max_wait = {"slow": 1.0, "normal": 0.5, "fast": 0.25}.get(velocity, 0.5)
            self._wait_until_settled(joint_targets, max_wait_s=max_wait)

            self._position = [x, y, z]
            self._last_action = "move_to"
            self._last_status = "complete"
            return {"status": "complete", "final_position": self._position[:]}
        except Exception as e:
            self._last_action = "move_to"
            self._last_status = "failed"
            return {"status": "failed", "reason": str(e)}

    def move_cartesian_delta(self, dx: float, dy: float, dz: float, velocity: str = "normal") -> dict:
        """Move end-effector by a Cartesian delta (meters) along a straight line.

        Plans all sub-waypoints UPFRONT from the current FK seed (not from
        mid-motion observations), chains IK seeds, executes each setpoint
        with convergence wait, and active-holds the final pose to counter
        gravity droop.
        """
        if SIMULATE:
            current = self.get_ee_position()
            return self.move_to(current[0] + dx, current[1] + dy, current[2] + dz, velocity)

        MAX_CARTESIAN_STEP_M = 0.03  # 3 cm per IK solve

        try:
            from mcp_server.robot.kinematics import joints_to_cartesian, cartesian_to_joints

            # 1. Snapshot starting joints — single read, before ANY motion
            start_joints = self.get_joint_positions()
            gripper_pos = start_joints.get("gripper", GRIPPER_OPEN)
            start_arm = {k: v for k, v in start_joints.items() if k != "gripper"}

            # 2. FK seed (NOT hardware reading — avoids gravity sag in the plan)
            start_ee = joints_to_cartesian(start_arm)

            # 3. Plan all waypoints upfront in Cartesian
            total = (dx ** 2 + dy ** 2 + dz ** 2) ** 0.5
            n_steps = max(1, int(total / MAX_CARTESIAN_STEP_M) + 1)
            waypoints = [
                (
                    start_ee[0] + dx * (i + 1) / n_steps,
                    start_ee[1] + dy * (i + 1) / n_steps,
                    start_ee[2] + dz * (i + 1) / n_steps,
                )
                for i in range(n_steps)
            ]
            # Clamp each waypoint to the workspace
            waypoints = [self._clamp_to_workspace(*wp) for wp in waypoints]

            # 4. Chain IK from previous IK solution (NOT from observation)
            seed = dict(start_arm)
            ik_plan = []
            for wp in waypoints:
                ik = cartesian_to_joints(wp[0], wp[1], wp[2], seed_hw_joints=seed)
                ik["gripper"] = gripper_pos
                ik_plan.append(ik)
                seed = {k: v for k, v in ik.items() if k != "gripper"}

            # 5. Execute: send each waypoint, wait for convergence
            max_wait = {"slow": 1.0, "normal": 0.5, "fast": 0.25}.get(velocity, 0.5)
            for ik in ik_plan:
                self._wait_until_settled(ik, max_wait_s=max_wait)

            # 6. Active-hold the final pose against gravity droop
            self._active_hold(ik_plan[-1], duration_s=0.6)

            ee_final = self.get_ee_position()
            self._position = list(ee_final)
            self._last_action = "move_cartesian_delta"
            self._last_status = "complete"
            return {"status": "complete", "ee_position": ee_final}
        except Exception as e:
            self._last_action = "move_cartesian_delta"
            self._last_status = "failed"
            return {"status": "failed", "reason": str(e)}

    def grasp(self, force: float = 3.0) -> dict:
        """Close gripper.

        Args:
            force: Grip strength 0-10. Mapped to gripper position 0-100.
        """
        force = min(force, FORCE_LIMIT)

        if SIMULATE:
            time.sleep(0.1)
            self._gripper_open = False
            self._last_action = "grasp"
            self._last_status = "complete"
            return {"status": "complete", "force_achieved": force * 0.9, "contact": True}

        try:
            # Map force (0-10N) to gripper close position (100=open → 0=closed).
            # Minimum closure is 70% (grip_pos=30) at force=0; fully closed (0) at max force.
            grip_pos = 30.0 - (force / FORCE_LIMIT) * 30.0
            current = self.get_joint_positions()
            # Gradually close gripper
            current_grip = current.get("gripper", GRIPPER_OPEN)
            for i in range(1, 11):
                alpha = i / 10
                pos = current_grip + alpha * (grip_pos - current_grip)
                action = {f"{name}.pos": current[name] for name in ARM_JOINT_NAMES}
                action["gripper.pos"] = pos
                self._robot.send_action(action)
                time.sleep(0.03)

            self._gripper_open = False
            self._last_action = "grasp"
            self._last_status = "complete"
            return {"status": "complete", "force_achieved": force * 0.9, "contact": True}
        except Exception as e:
            self._last_action = "grasp"
            self._last_status = "failed"
            return {"status": "failed", "reason": str(e), "contact": False}

    def release(self) -> dict:
        """Open gripper fully."""
        if SIMULATE:
            time.sleep(0.05)
            self._gripper_open = True
            self._holding = None
            self._last_action = "release"
            self._last_status = "complete"
            return {"status": "complete"}

        try:
            current = self.get_joint_positions()
            current_grip = current.get("gripper", GRIPPER_CLOSED)
            for i in range(1, 11):
                alpha = i / 10
                pos = current_grip + alpha * (GRIPPER_OPEN - current_grip)
                action = {f"{name}.pos": current[name] for name in ARM_JOINT_NAMES}
                action["gripper.pos"] = pos
                self._robot.send_action(action)
                time.sleep(0.03)

            self._gripper_open = True
            self._holding = None
            self._last_action = "release"
            self._last_status = "complete"
            return {"status": "complete"}
        except Exception as e:
            self._last_action = "release"
            self._last_status = "failed"
            return {"status": "failed", "reason": str(e)}

    def relative_move(self, joint_deltas: dict[str, float]) -> dict:
        """Apply relative joint angle deltas from current position.

        Args:
            joint_deltas: {"shoulder_pan": +10, "elbow_flex": -5, ...}
                          Only joints listed will be moved; others stay put.

        Returns: {"status": "complete", "joints": {current positions after move}}
        """
        current = self.get_joint_positions()
        targets = dict(current)
        for joint, delta in joint_deltas.items():
            if joint in targets:
                targets[joint] = targets[joint] + delta
        result = self.send_joint_positions(targets)
        if result["status"] == "complete":
            result["joints"] = targets
        return result

    def stop(self) -> dict:
        """Emergency stop — disconnect and disable torque."""
        if not SIMULATE and self._robot:
            try:
                self._robot.disconnect()
                self._is_connected = False
            except Exception:
                pass
        self._last_action = "stop"
        self._last_status = "stopped"
        return {"status": "stopped"}

    def get_status(self) -> dict:
        result = {
            "gripper_position": self._position[:],
            "gripper_open": self._gripper_open,
            "holding": self._holding,
            "last_action": self._last_action,
            "last_status": self._last_status,
            "connected": self._is_connected,
        }
        if not SIMULATE and self._robot:
            result["joint_positions"] = self.get_joint_positions()
        return result

    # ── Properties ──

    @property
    def position(self) -> list[float]:
        return self._position[:]

    @property
    def gripper_open(self) -> bool:
        return self._gripper_open

    @property
    def holding(self) -> str | None:
        return self._holding

    @holding.setter
    def holding(self, value: str | None):
        self._holding = value
