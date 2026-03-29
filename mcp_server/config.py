import os

# Object definitions for color detection
OBJECTS = {
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
