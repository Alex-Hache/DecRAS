import os

# Object definitions for color detection
OBJECTS = {
    "yellow_stick": {
        "hsv_lower": [18, 100, 100],
        "hsv_upper": [35, 255, 255],
        "height": 0.02,   # UHU glue stick lying flat ≈ 2cm diameter
        "graspable": True,
        "type": "stick",
    },
    "red_cup": {
        "hsv_lower": [0, 120, 70],
        "hsv_upper": [10, 255, 255],
        "height": 0.08,
        "graspable": True,
        "type": "cup",
    },
    "blue_plate": {
        "hsv_lower": [100, 120, 70],
        "hsv_upper": [130, 255, 255],
        "height": 0.02,
        "graspable": False,
        "type": "surface",
    },
}

# Camera-to-robot affine transform (populate during calibration)
CAMERA_TO_ROBOT_MATRIX = None  # 3x3 affine, set by calibration script

# Camera source: int for USB device index, str for IP Webcam URL.
# Override via env var DECRAS_CAMERA, e.g. DECRAS_CAMERA=192.168.129.1:8080
#   — bare host:port is normalized to http://host:port/video by Camera().
#   — integers are parsed as USB device indices.
_camera_env = os.environ.get("DECRAS_CAMERA", "").strip()
if _camera_env == "":
    CAMERA_SOURCE: int | str = 0
elif _camera_env.isdigit():
    CAMERA_SOURCE = int(_camera_env)
else:
    CAMERA_SOURCE = _camera_env

# Robot workspace limits (meters, in robot frame)
WORKSPACE = {
    "x_min": 0.0,
    "x_max": 0.6,
    "y_min": -0.3,
    "y_max": 0.3,
    "z_min": 0.0,
    "z_max": 0.5,
}

# Safety
FORCE_LIMIT = 10.0  # Newtons
POSITION_HISTORY_SIZE = 20

# Named joint positions (degrees, gripper 0-100)
REST_POSITION = {
    "shoulder_pan": -18, "shoulder_lift": -105, "elbow_flex": 97,
    "wrist_flex": 74, "wrist_roll": 0, "gripper": 0,
}
WORK_POSITION = {
    "shoulder_pan": -18, "shoulder_lift": -60, "elbow_flex": 37,
    "wrist_flex": 74, "wrist_roll": 0, "gripper": 0,
}

# LeRobot SO-101 settings
LEROBOT_FOLLOWER_PORT = os.environ.get("LEROBOT_FOLLOWER_PORT", "/dev/decras_follower")
LEROBOT_LEADER_PORT = os.environ.get("LEROBOT_LEADER_PORT", "/dev/decras_leader")
LEROBOT_FOLLOWER_ID = os.environ.get("LEROBOT_FOLLOWER_ID", "decras_follower")

# Simulated mode (no real hardware)
SIMULATE = os.environ.get("SIMULATE", "true").lower() == "true"

# Servo P gain (Feetech STS-3215 internal position PID).
# LeRobot default is 32; SO101Follower.configure() lowers it to 16 to reduce shakiness.
# Higher P → less gravity droop (Δq = τ_gravity / Kp_eff) but risks oscillation.
# Sweep empirically: try 16 → 24 → 32 with move_to_delta(0,0,0.05) Z-up test.
# Set via env var DECRAS_SERVO_P_GAIN; 0 = use LeRobot default (don't override).
SERVO_P_GAIN: int = int(os.environ.get("DECRAS_SERVO_P_GAIN", "0"))

# Per-joint servo compliance (deg / N·m).
# Fitted from notebooks/gravity_calibration.ipynb.
# Formula: q_ref[joint] += COMPLIANCE[joint] * τ_gravity[joint]
# where τ_gravity comes from kinematics.gravity_torques_dict().
# Zero = no correction (safe default until calibrated).
SERVO_COMPLIANCE_DEG_PER_NM: dict[str, float] = {
    "shoulder_pan":  0.0,
    "shoulder_lift": 0.0,  # fill after running gravity_calibration.ipynb
    "elbow_flex":    0.0,  # fill after running gravity_calibration.ipynb
    "wrist_flex":    0.0,
    "wrist_roll":    0.0,
}
