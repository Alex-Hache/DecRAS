"""MCP server entry point — registers all robot primitives as tools.

Uses SimEnvironment (PyBullet) when SIMULATE=True, or real hardware when False.
Every tool call is logged structurally + camera frames captured for replay.
"""

import json
import time
import logging
import os
from functools import wraps

from mcp.server.fastmcp import FastMCP

from mcp_server.config import SIMULATE
from mcp_server.history import PositionHistory
from mcp_server.episode import EpisodeRecorder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Initialize backend ──

history = PositionHistory()
recorder: EpisodeRecorder | None = None

if SIMULATE:
    from mcp_server.sim.pybullet_env import PyBulletEnv
    env = PyBulletEnv(gui=os.environ.get("DECRAS_GUI", "").lower() == "true")
    logger.info("Using PyBullet simulation backend")
else:
    env = None
    logger.info("Hardware mode — robot will connect on first tool call")

# Lazy-initialized hardware references
robot = None
camera = None


def _get_robot():
    """Lazy-connect to the robot on first use."""
    global robot
    if robot is not None:
        return robot
    if SIMULATE:
        return None
    from mcp_server.robot.lerobot import LeRobotInterface
    from mcp_server.config import LEROBOT_FOLLOWER_PORT, LEROBOT_FOLLOWER_ID
    robot = LeRobotInterface(port=LEROBOT_FOLLOWER_PORT, robot_id=LEROBOT_FOLLOWER_ID)
    logger.info("Robot connected")
    return robot


def _get_camera():
    """Lazy-init camera on first use."""
    global camera
    if camera is not None:
        return camera
    if SIMULATE:
        return None
    try:
        from mcp_server.perception.camera import Camera
        camera = Camera()
        logger.info("Camera opened")
    except Exception as e:
        logger.warning("Camera not available: %s", e)
    return camera


# Create MCP server
mcp = FastMCP("DecRAS Robot Server")


# ── Helpers ──

def _capture_frame():
    """Grab a camera frame from the active backend."""
    if env is not None:
        return env.get_camera_image()
    return None


def _get_scene_dict() -> dict:
    """Get current scene as dict."""
    if env is not None:
        return {
            "objects": env.get_object_states(),
            "gripper": env.get_gripper_state(),
            "timestamp": round(time.time(), 2),
        }
    return {}


def _log_tool(action_name: str, action_args: dict, result: dict, t0: float):
    """Record to episode + structured log."""
    duration = (time.time() - t0) * 1000
    frame = _capture_frame()
    scene = _get_scene_dict()

    if recorder is not None:
        recorder.record_step(
            action_name=action_name,
            action_args=action_args,
            result=result,
            scene=scene,
            frame=frame,
            duration_ms=duration,
        )
    else:
        logger.info(
            "TOOL %s(%s) -> %s (%.0fms)",
            action_name,
            json.dumps(action_args),
            result.get("status", "?"),
            duration,
        )


def _safe_tool(func):
    """Decorator: catch unexpected exceptions and return structured error JSON."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.exception("Tool %s failed", func.__name__)
            return json.dumps({"status": "error", "reason": str(e)})
    return wrapper


# ── Tools ──

@mcp.tool()
@_safe_tool
def calibrate() -> str:
    """Run interactive motor calibration on the real robot.

    Only works in real hardware mode (SIMULATE=false).
    Follow the on-screen prompts to move each joint through its range.
    """
    if env is not None:
        return json.dumps({"status": "skipped", "reason": "simulation_mode"})
    result = _get_robot().calibrate()
    return json.dumps(result)


@mcp.tool()
@_safe_tool
def read_joints() -> str:
    """Read current joint positions from the real robot.

    Returns joint angles in degrees (gripper 0-100).
    Useful for debugging and verifying calibration.
    """
    if env is not None:
        gripper = env.get_gripper_state()
        return json.dumps({"mode": "simulation", "gripper_position": gripper["position"]})
    positions = _get_robot().get_joint_positions()
    return json.dumps({"mode": "hardware", "joints": positions})


@mcp.tool()
@_safe_tool
def send_joints(
    shoulder_pan: float = 0.0,
    shoulder_lift: float = 0.0,
    elbow_flex: float = 0.0,
    wrist_flex: float = 0.0,
    wrist_roll: float = 0.0,
    gripper: float = 0.0,
) -> str:
    """Send joint positions directly to the robot (degrees, gripper 0-100).

    For manual control and testing. Bypasses IK.
    """
    positions = {
        "shoulder_pan": shoulder_pan,
        "shoulder_lift": shoulder_lift,
        "elbow_flex": elbow_flex,
        "wrist_flex": wrist_flex,
        "wrist_roll": wrist_roll,
        "gripper": gripper,
    }
    if env is not None:
        return json.dumps({"status": "skipped", "reason": "simulation_mode"})
    result = _get_robot().send_joint_positions(positions)
    return json.dumps(result)


@mcp.tool()
@_safe_tool
def start_episode(task: str = "") -> str:
    """Start recording an episode. Call before beginning a task.

    Args:
        task: Description of the task being performed.
    """
    global recorder
    recorder = EpisodeRecorder(task=task)
    frame = _capture_frame()
    if frame is not None:
        recorder.record_frame(frame)
    logger.info("Episode recording started: %s", task)
    return json.dumps({"status": "recording", "dir": str(recorder.episode_dir)})


@mcp.tool()
@_safe_tool
def end_episode(success: bool = False, reason: str = "") -> str:
    """End recording the current episode. Encodes video and saves logs.

    Args:
        success: Whether the task was completed successfully.
        reason: Short description of outcome.
    """
    global recorder
    if recorder is None:
        return json.dumps({"status": "no_episode"})
    ep_dir = recorder.finish(success=success, reason=reason)
    recorder = None
    logger.info("Episode finished: %s", ep_dir)
    return json.dumps({"status": "saved", "dir": str(ep_dir)})


@mcp.tool()
@_safe_tool
def observe() -> str:
    """Capture camera frame, run perception, return scene graph JSON."""
    t0 = time.time()

    if env is not None:
        result = _get_scene_dict()
    elif _get_camera() is not None:
        from mcp_server.perception.detector import detect_objects
        from mcp_server.perception.scene_graph import build_scene_graph
        r = _get_robot()
        frame = _get_camera().capture()
        detections = detect_objects(frame)
        result = build_scene_graph(
            detections,
            gripper_position=r.position,
            gripper_open=r.gripper_open,
            holding=r.holding,
        )
    else:
        r = _get_robot()
        result = {
            "joints": r.get_joint_positions(),
            "gripper_open": r.gripper_open,
            "holding": r.holding,
            "camera": "not_available",
            "timestamp": round(time.time(), 2),
        }

    _log_tool("observe", {}, {"status": "observed"}, t0)
    return json.dumps(result)


@mcp.tool()
@_safe_tool
def move_to(x: float, y: float, z: float, velocity: str = "normal") -> str:
    """Move gripper to target position in robot frame (meters).

    Args:
        x: Target X position (0.0 to 0.4)
        y: Target Y position (-0.2 to 0.2)
        z: Target Z position (0.0 to 0.3)
        velocity: Movement speed — "slow", "normal", or "fast"
    """
    t0 = time.time()
    args = {"x": x, "y": y, "z": z, "velocity": velocity}

    if env is not None:
        old_pos = env.get_gripper_state()["position"]
        history.record(old_pos)
        result = env.move_to(x, y, z, velocity)
    else:
        r = _get_robot()
        history.record(r.position)
        result = r.move_to(x, y, z, velocity)

    _log_tool("move_to", args, result, t0)
    return json.dumps(result)


@mcp.tool()
@_safe_tool
def grasp(force: float = 3.0) -> str:
    """Close gripper with target force.

    Args:
        force: Grip force in Newtons (default 3.0, max 10.0)
    """
    t0 = time.time()
    args = {"force": force}

    if env is not None:
        result = env.grasp(force)
    else:
        result = _get_robot().grasp(force)

    _log_tool("grasp", args, result, t0)
    return json.dumps(result)


@mcp.tool()
@_safe_tool
def release() -> str:
    """Open gripper fully."""
    t0 = time.time()

    if env is not None:
        result = env.release()
    else:
        result = _get_robot().release()

    _log_tool("release", {}, result, t0)
    return json.dumps(result)


@mcp.tool()
@_safe_tool
def stop() -> str:
    """Emergency stop — halts all motion immediately."""
    t0 = time.time()

    if env is not None:
        result = env.stop()
    else:
        result = _get_robot().stop()

    _log_tool("stop", {}, result, t0)
    return json.dumps(result)


@mcp.tool()
@_safe_tool
def go_back(steps: int = 1) -> str:
    """Return gripper to position it was N actions ago.

    Args:
        steps: Number of positions to go back in history (default 1)
    """
    t0 = time.time()
    args = {"steps": steps}

    target = history.go_back(steps)
    if target is None:
        result = {"status": "failed", "reason": "no_history"}
        _log_tool("go_back", args, result, t0)
        return json.dumps(result)

    if env is not None:
        result = env.move_to(target[0], target[1], target[2])
    else:
        result = _get_robot().move_to(target[0], target[1], target[2])

    if result["status"] == "complete":
        result = {"status": "complete", "returned_to": target}

    _log_tool("go_back", args, result, t0)
    return json.dumps(result)


@mcp.tool()
@_safe_tool
def get_status() -> str:
    """Get current robot state without new camera capture."""
    t0 = time.time()

    if env is not None:
        gripper = env.get_gripper_state()
        result = {
            "gripper_position": gripper["position"],
            "gripper_open": gripper["open"],
            "holding": gripper["holding"],
            "last_action": "get_status",
            "last_status": "complete",
        }
    else:
        result = _get_robot().get_status()

    _log_tool("get_status", {}, result, t0)
    return json.dumps(result)


# ── Composable EE-space primitives ──
# All directional moves operate in the robot base Cartesian frame via FK+IK.
# Frame: +X = forward (away from base), +Y = left, +Z = up.
# rotate_gripper / tilt_gripper remain joint-space (orientation control).

def _cartesian_move(dx: float, dy: float, dz: float, action_name: str, action_args: dict) -> str:
    """Shared impl: FK → add Cartesian delta → IK → move."""
    t0 = time.time()
    if env is not None:
        current = env.get_gripper_state()["position"]
        history.record(current)
        result = env.move_to(current[0] + dx, current[1] + dy, current[2] + dz)
    else:
        result = _get_robot().move_cartesian_delta(dx, dy, dz)
    _log_tool(action_name, action_args, result, t0)
    return json.dumps(result)


def _joint_move(joint_deltas: dict, action_name: str, action_args: dict) -> str:
    """Shared impl for joint-space orientation primitives (wrist)."""
    t0 = time.time()
    if env is not None:
        result = {"status": "skipped", "reason": "simulation_mode"}
    else:
        result = _get_robot().relative_move(joint_deltas)
    _log_tool(action_name, action_args, result, t0)
    return json.dumps(result)


@mcp.tool()
@_safe_tool
def move_left(distance_m: float = 0.05) -> str:
    """Move gripper left (+Y) in robot base frame.

    Args:
        distance_m: Distance in meters (default 0.05 = 5 cm)
    """
    return _cartesian_move(0, +distance_m, 0, "move_left", {"distance_m": distance_m})


@mcp.tool()
@_safe_tool
def move_right(distance_m: float = 0.05) -> str:
    """Move gripper right (-Y) in robot base frame.

    Args:
        distance_m: Distance in meters (default 0.05 = 5 cm)
    """
    return _cartesian_move(0, -distance_m, 0, "move_right", {"distance_m": distance_m})


@mcp.tool()
@_safe_tool
def move_up(distance_m: float = 0.05) -> str:
    """Move gripper up (+Z direction).

    Args:
        distance_m: Distance in meters (default 0.05 = 5 cm)
    """
    return _cartesian_move(0, 0, +distance_m, "move_up", {"distance_m": distance_m})


@mcp.tool()
@_safe_tool
def move_down(distance_m: float = 0.05) -> str:
    """Move gripper down (-Z direction).

    Args:
        distance_m: Distance in meters (default 0.05 = 5 cm)
    """
    return _cartesian_move(0, 0, -distance_m, "move_down", {"distance_m": distance_m})


@mcp.tool()
@_safe_tool
def move_forward(distance_m: float = 0.05) -> str:
    """Move gripper forward (+X, away from robot base).

    Args:
        distance_m: Distance in meters (default 0.05 = 5 cm)
    """
    return _cartesian_move(+distance_m, 0, 0, "move_forward", {"distance_m": distance_m})


@mcp.tool()
@_safe_tool
def move_back(distance_m: float = 0.05) -> str:
    """Move gripper backward (-X, toward robot base).

    Args:
        distance_m: Distance in meters (default 0.05 = 5 cm)
    """
    return _cartesian_move(-distance_m, 0, 0, "move_back", {"distance_m": distance_m})


@mcp.tool()
@_safe_tool
def rotate_gripper(degrees: float = 15.0) -> str:
    """Rotate the gripper around its axis (wrist_roll).

    Args:
        degrees: Rotation amount in degrees, positive = counterclockwise (default 15)
    """
    return _joint_move({"wrist_roll": -degrees}, "rotate_gripper", {"degrees": degrees})


@mcp.tool()
@_safe_tool
def tilt_gripper(degrees: float = 15.0) -> str:
    """Tilt the gripper up/down (wrist_flex).

    Args:
        degrees: Tilt amount in degrees, positive = tilt up (default 15)
    """
    return _joint_move({"wrist_flex": -degrees}, "tilt_gripper", {"degrees": degrees})


def main():
    logger.info("Starting DecRAS MCP server (stdio transport)...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
