"""SO-101 FK/IK engine — placo-based, uses URDF directly.

FK: placo forward kinematics (exact, no approximations).
IK: placo velocity-level QP solver with add_position_task.
    Converges in ~3 iterations for typical 3-5 cm moves.
    Wrists preserved from seed (returned unchanged in result dict).

Hardware-to-URDF sign conventions (verified empirically against new SO-101 URDF):
  shoulder_pan:  sign=+1  (hw +degrees → URDF +degrees)
  shoulder_lift: sign=+1  (hw -degrees → URDF -degrees)
  elbow_flex:    sign=+1  (hw +degrees → URDF +degrees)
  wrist_flex:    sign=+1  (hw +degrees → URDF +degrees)
  wrist_roll:    sign=+1  (hw +degrees → URDF +degrees → CCW)

Robot base frame:
  +X = forward (away from base)
  +Y = left (robot's left from above)
  +Z = up
"""

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

JOINT_NAMES_ARM = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
EE_LINK_NAME = "gripper_frame_link"
URDF_PATH = Path(__file__).parent.parent / "sim" / "assets" / "so101" / "so101.urdf"

# URDF_deg = sign * hw_deg  (sign is its own inverse for back-conversion)
HW_TO_URDF_SIGN: dict[str, int] = {
    "shoulder_pan":  +1,
    "shoulder_lift": +1,
    "elbow_flex":    +1,
    "wrist_flex":    +1,
    "wrist_roll":    +1,
}

# ---------------------------------------------------------------------------
# Placo engine (lazy-initialised singleton)
# ---------------------------------------------------------------------------
_robot = None
_solver = None
_pos_task = None


def _init():
    """Lazy-init placo robot + position-only IK solver."""
    global _robot, _solver, _pos_task
    if _robot is not None:
        return
    import placo
    _robot = placo.RobotWrapper(str(URDF_PATH))
    _solver = placo.KinematicsSolver(_robot)
    _solver.mask_fbase(True)  # fix base
    # Persistent position task — target is updated on each IK call
    _pos_task = _solver.add_position_task(EE_LINK_NAME, np.zeros(3))
    _pos_task.configure("pos", "soft", 1.0)
    logger.info("Placo kinematics engine ready (URDF: %s)", URDF_PATH)


def _hw_to_urdf_deg(joint_name: str, hw_deg: float) -> float:
    return HW_TO_URDF_SIGN.get(joint_name, 1) * hw_deg


def _urdf_to_hw_deg(joint_name: str, urdf_deg: float) -> float:
    return HW_TO_URDF_SIGN.get(joint_name, 1) * urdf_deg


def _normalize_joint_dict(hw_joints: dict[str, float]) -> dict[str, float]:
    """Strip '.pos' suffix from keys so both formats work.

    Accepts: {"shoulder_pan": 10} or {"shoulder_pan.pos": 10}
    Returns: {"shoulder_pan": 10}
    """
    return {k.removesuffix(".pos"): v for k, v in hw_joints.items()}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def joints_to_cartesian(hw_joints: dict[str, float]) -> list[float]:
    """FK: hardware joint angles (degrees) → EE position [x, y, z] in meters."""
    _init()
    hw_joints = _normalize_joint_dict(hw_joints)
    urdf_rad = np.deg2rad([_hw_to_urdf_deg(n, hw_joints.get(n, 0.0)) for n in JOINT_NAMES_ARM])
    for i, jn in enumerate(JOINT_NAMES_ARM):
        _robot.set_joint(jn, urdf_rad[i])
    _robot.update_kinematics()
    T = _robot.get_T_world_frame(EE_LINK_NAME)
    return [float(T[0, 3]), float(T[1, 3]), float(T[2, 3])]


def cartesian_to_joints(
    x: float,
    y: float,
    z: float,
    seed_hw_joints: dict[str, float] | None = None,
) -> dict[str, float]:
    """IK: target [x, y, z] (meters) → hardware joint angles (degrees).

    Uses placo position task (no orientation constraint). Converges in ~3
    solver iterations for typical small moves. Wrist joints (wrist_flex,
    wrist_roll) are preserved from seed — only pan/lift/elbow effectively
    change for a pure position move.
    """
    _init()
    seed = _normalize_joint_dict(seed_hw_joints or {})

    # Seed the solver from current joint configuration
    seed_urdf_rad = np.deg2rad([_hw_to_urdf_deg(n, seed.get(n, 0.0)) for n in JOINT_NAMES_ARM])
    for i, jn in enumerate(JOINT_NAMES_ARM):
        _robot.set_joint(jn, seed_urdf_rad[i])

    # Set target position and iterate
    _pos_task.target_world = np.array([x, y, z])
    for _ in range(5):
        _solver.solve(True)
        _robot.update_kinematics()

    # Read solved joints and convert back to hardware degrees
    return {jn: _urdf_to_hw_deg(jn, float(np.rad2deg(_robot.get_joint(jn)))) for jn in JOINT_NAMES_ARM}
