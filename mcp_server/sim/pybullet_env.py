"""PyBullet implementation of SimEnvironment.

Loads the SO-101 URDF, a table, and manipulation objects.
Provides Cartesian IK control, gripper actuation, and camera rendering.
"""

import math
import time
import logging
from pathlib import Path

import numpy as np
import pybullet as p
import pybullet_data

from mcp_server.sim.base import SimEnvironment
from mcp_server.config import WORKSPACE, FORCE_LIMIT

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).parent / "assets"

# SO-101 joint info (from URDF)
# Order: shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper
JOINT_NAMES = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
]

# Home joint angles (arm roughly upright, gripper open)
HOME_JOINTS = [0.0, 0.0, 0.0, 0.0, 0.0, 1.0]

# IK end-effector link index (gripper_frame_link)
EE_LINK_NAME = "gripper_frame_link"

# Gripper joint index (will be resolved at load time)
GRIPPER_OPEN_ANGLE = 1.0
GRIPPER_CLOSED_ANGLE = -0.1

# Camera parameters for rendering
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FOV = 60
CAMERA_NEAR = 0.01
CAMERA_FAR = 2.0


class PyBulletEnv(SimEnvironment):
    """PyBullet-based simulation environment with SO-101 arm."""

    def __init__(self, gui: bool = False):
        self._gui = gui
        self._physics_client = None
        self._robot_id = None
        self._table_id = None
        self._objects: dict[str, dict] = {}  # id -> {body_id, type, color, graspable}

        # State
        self._gripper_open = True
        self._holding: str | None = None
        self._grasp_constraint = None

        # Joint index cache
        self._joint_indices: dict[str, int] = {}
        self._ee_link_index = -1
        self._gripper_joint_index = -1
        self._arm_joint_indices: list[int] = []

        self.reset()

    @property
    def _pc(self) -> int:
        """Physics client ID shorthand."""
        return self._physics_client

    def reset(self) -> dict:
        # Clean up previous session
        if self._physics_client is not None:
            p.disconnect(self._physics_client)

        # Start physics
        mode = p.GUI if self._gui else p.DIRECT
        self._physics_client = p.connect(mode)
        pc = self._pc
        p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=pc)
        p.setGravity(0, 0, -9.81, physicsClientId=pc)
        p.setTimeStep(1.0 / 240.0, physicsClientId=pc)

        # Ground plane
        p.loadURDF("plane.urdf", physicsClientId=pc)

        # Table — position so the surface is at z=0.0 in robot workspace
        self._table_id = p.loadURDF(
            str(ASSETS_DIR / "table.urdf"),
            basePosition=[0.2, 0.0, 0.0],
            useFixedBase=True,
            physicsClientId=pc,
        )

        # Robot — base on the table surface
        self._robot_id = p.loadURDF(
            str(ASSETS_DIR / "so101" / "so101.urdf"),
            basePosition=[0.0, 0.0, 0.0],
            baseOrientation=p.getQuaternionFromEuler([0, 0, 0], physicsClientId=pc),
            useFixedBase=True,
            physicsClientId=pc,
        )

        # Build joint index map
        self._build_joint_map()

        # Move to home position
        for name, angle in zip(JOINT_NAMES, HOME_JOINTS):
            if name in self._joint_indices:
                p.resetJointState(self._robot_id, self._joint_indices[name], angle,
                                  physicsClientId=pc)

        # Spawn objects
        self._objects.clear()
        self._holding = None
        self._gripper_open = True
        self._grasp_constraint = None

        self._spawn_object("red_cup", "cup.urdf", [0.2, -0.08, 0.0],
                           obj_type="cup", color="red", graspable=True)
        self._spawn_object("blue_plate", "plate.urdf", [0.25, 0.10, 0.0],
                           obj_type="surface", color="blue", graspable=False)

        # Step physics to settle
        for _ in range(100):
            p.stepSimulation(physicsClientId=pc)

        logger.info("PyBullet environment reset (gui=%s)", self._gui)
        return self.get_observation()

    def close(self) -> None:
        if self._physics_client is not None:
            p.disconnect(self._physics_client)
            self._physics_client = None

    # ── Robot control ──

    def move_to(self, x: float, y: float, z: float, velocity: str = "normal") -> dict:
        pc = self._pc
        # Clamp to workspace
        ws = WORKSPACE
        x = max(ws["x_min"], min(ws["x_max"], x))
        y = max(ws["y_min"], min(ws["y_max"], y))
        z = max(ws["z_min"], min(ws["z_max"], z))

        target_pos = [x, y, z]
        # Point gripper downward
        target_orn = p.getQuaternionFromEuler([math.pi, 0, 0], physicsClientId=pc)

        # Solve IK — use joint limits for better solutions
        lower_limits, upper_limits, joint_ranges, rest_poses = self._get_joint_limits()
        joint_angles = p.calculateInverseKinematics(
            self._robot_id,
            self._ee_link_index,
            target_pos,
            target_orn,
            lowerLimits=lower_limits,
            upperLimits=upper_limits,
            jointRanges=joint_ranges,
            restPoses=rest_poses,
            maxNumIterations=200,
            residualThreshold=1e-4,
            physicsClientId=pc,
        )

        if joint_angles is None:
            return {"status": "failed", "reason": "ik_failure"}

        # Drive arm joints (not gripper)
        steps = {"slow": 300, "normal": 150, "fast": 50}.get(velocity, 150)

        for i, idx in enumerate(self._arm_joint_indices):
            if i < len(joint_angles):
                p.setJointMotorControl2(
                    self._robot_id, idx,
                    p.POSITION_CONTROL,
                    targetPosition=joint_angles[i],
                    force=50,
                    maxVelocity=2.0,
                    physicsClientId=pc,
                )

        # Step simulation
        for _ in range(steps):
            p.stepSimulation(physicsClientId=pc)

        # Check actual achieved position
        actual = self._get_ee_position()
        error = np.linalg.norm(np.array(target_pos) - np.array(actual))

        if error > 0.08:
            return {"status": "failed", "reason": "unreachable",
                    "final_position": [round(v, 4) for v in actual]}

        return {"status": "complete",
                "final_position": [round(v, 4) for v in actual]}

    def grasp(self, force: float = 3.0) -> dict:
        pc = self._pc
        force = min(force, FORCE_LIMIT)

        # Close gripper
        if self._gripper_joint_index >= 0:
            p.setJointMotorControl2(
                self._robot_id, self._gripper_joint_index,
                p.POSITION_CONTROL,
                targetPosition=GRIPPER_CLOSED_ANGLE,
                force=force,
                physicsClientId=pc,
            )

        # Step to let gripper close
        for _ in range(60):
            p.stepSimulation(physicsClientId=pc)

        self._gripper_open = False

        # Check proximity to graspable objects
        ee_pos = self._get_ee_position()
        grasped_id = None

        for obj_id, obj_info in self._objects.items():
            if not obj_info["graspable"]:
                continue
            if obj_id == self._holding:
                continue

            obj_pos, _ = p.getBasePositionAndOrientation(obj_info["body_id"],
                                                          physicsClientId=pc)
            dist = np.linalg.norm(np.array(ee_pos) - np.array(obj_pos))

            if dist < 0.06:  # grasp proximity threshold
                grasped_id = obj_id
                break

        if grasped_id:
            self._holding = grasped_id
            obj_body = self._objects[grasped_id]["body_id"]

            self._grasp_constraint = p.createConstraint(
                self._robot_id, self._ee_link_index,
                obj_body, -1,
                jointType=p.JOINT_FIXED,
                jointAxis=[0, 0, 0],
                parentFramePosition=[0, 0, 0],
                childFramePosition=[0, 0, 0],
                physicsClientId=pc,
            )

            return {"status": "complete", "force_achieved": force * 0.9, "contact": True}

        return {"status": "complete", "force_achieved": 0.0, "contact": False}

    def release(self) -> dict:
        pc = self._pc
        # Open gripper
        if self._gripper_joint_index >= 0:
            p.setJointMotorControl2(
                self._robot_id, self._gripper_joint_index,
                p.POSITION_CONTROL,
                targetPosition=GRIPPER_OPEN_ANGLE,
                force=5,
                physicsClientId=pc,
            )

        # Remove grasp constraint
        if self._grasp_constraint is not None:
            p.removeConstraint(self._grasp_constraint, physicsClientId=pc)
            self._grasp_constraint = None

        self._gripper_open = True
        self._holding = None

        # Let physics settle
        for _ in range(60):
            p.stepSimulation(physicsClientId=pc)

        return {"status": "complete"}

    def stop(self) -> dict:
        pc = self._pc
        # Zero all joint velocities
        for idx in self._arm_joint_indices:
            p.setJointMotorControl2(
                self._robot_id, idx,
                p.VELOCITY_CONTROL,
                targetVelocity=0,
                force=100,
                physicsClientId=pc,
            )
        return {"status": "stopped"}

    # ── Observation ──

    def get_camera_image(self) -> np.ndarray:
        """Render from a top-down-ish camera above the workspace."""
        pc = self._pc
        view_matrix = p.computeViewMatrix(
            cameraEyePosition=[0.2, 0.0, 0.5],
            cameraTargetPosition=[0.2, 0.0, 0.0],
            cameraUpVector=[0, -1, 0],
            physicsClientId=pc,
        )
        proj_matrix = p.computeProjectionMatrixFOV(
            fov=CAMERA_FOV,
            aspect=CAMERA_WIDTH / CAMERA_HEIGHT,
            nearVal=CAMERA_NEAR,
            farVal=CAMERA_FAR,
            physicsClientId=pc,
        )

        _, _, rgba, _, _ = p.getCameraImage(
            width=CAMERA_WIDTH,
            height=CAMERA_HEIGHT,
            viewMatrix=view_matrix,
            projectionMatrix=proj_matrix,
            renderer=p.ER_TINY_RENDERER,
            physicsClientId=pc,
        )

        # Convert RGBA to BGR (OpenCV format)
        rgba = np.array(rgba, dtype=np.uint8).reshape(CAMERA_HEIGHT, CAMERA_WIDTH, 4)
        bgr = rgba[:, :, [2, 1, 0]]  # RGBA -> BGR
        return bgr

    def get_gripper_state(self) -> dict:
        ee_pos = self._get_ee_position()
        return {
            "position": [round(v, 4) for v in ee_pos],
            "open": self._gripper_open,
            "holding": self._holding,
        }

    def get_object_states(self) -> list[dict]:
        states = []
        for obj_id, obj_info in self._objects.items():
            pos, _ = p.getBasePositionAndOrientation(obj_info["body_id"],
                                                      physicsClientId=self._pc)
            states.append({
                "id": obj_id,
                "type": obj_info["type"],
                "color": obj_info["color"],
                "position": [round(v, 4) for v in pos],
                "grasped": obj_id == self._holding,
                "graspable": obj_info["graspable"],
            })
        return states

    # ── Internal ──

    def _build_joint_map(self):
        """Build joint name → index mapping from URDF."""
        pc = self._pc
        num_joints = p.getNumJoints(self._robot_id, physicsClientId=pc)
        self._joint_indices.clear()
        self._arm_joint_indices.clear()

        for i in range(num_joints):
            info = p.getJointInfo(self._robot_id, i, physicsClientId=pc)
            name = info[1].decode("utf-8")
            link_name = info[12].decode("utf-8")

            self._joint_indices[name] = i

            if link_name == EE_LINK_NAME or name == "gripper_frame_joint":
                self._ee_link_index = i

            if name == "gripper":
                self._gripper_joint_index = i

        # Arm joints (everything except gripper)
        for name in JOINT_NAMES[:-1]:  # exclude "gripper"
            if name in self._joint_indices:
                self._arm_joint_indices.append(self._joint_indices[name])

        logger.info("Joint map: %s", self._joint_indices)
        logger.info("EE link index: %d, Gripper joint: %d",
                     self._ee_link_index, self._gripper_joint_index)
        logger.info("Arm joint indices: %s", self._arm_joint_indices)

    def _get_joint_limits(self):
        """Get joint limits for IK solver."""
        pc = self._pc
        lower, upper, ranges, rests = [], [], [], []
        for idx in self._arm_joint_indices:
            info = p.getJointInfo(self._robot_id, idx, physicsClientId=pc)
            lo, hi = info[8], info[9]
            lower.append(lo)
            upper.append(hi)
            ranges.append(hi - lo)
            rests.append(0.0)
        return lower, upper, ranges, rests

    def _get_ee_position(self) -> list[float]:
        """Get current end-effector Cartesian position."""
        if self._ee_link_index < 0:
            return [0.0, 0.0, 0.0]
        state = p.getLinkState(self._robot_id, self._ee_link_index,
                               physicsClientId=self._pc)
        return list(state[0])  # worldLinkFramePosition

    def _spawn_object(self, obj_id: str, urdf_name: str, position: list[float],
                      obj_type: str = "object", color: str = "gray",
                      graspable: bool = True):
        """Spawn an object in the scene."""
        body_id = p.loadURDF(
            str(ASSETS_DIR / urdf_name),
            basePosition=position,
            useFixedBase=(not graspable),
            physicsClientId=self._pc,
        )
        self._objects[obj_id] = {
            "body_id": body_id,
            "type": obj_type,
            "color": color,
            "graspable": graspable,
        }
        logger.info("Spawned %s at %s (body_id=%d)", obj_id, position, body_id)
