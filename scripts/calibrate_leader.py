"""Calibrate the SO-101 leader arm (ttyACM1).

Saves calibration to:
  ~/.cache/huggingface/lerobot/calibration/teleoperators/so101_leader/decras_leader.json

Usage:
    sg dialout -c "uv run python -m scripts.calibrate_leader"
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lerobot.teleoperators.so_leader import SOLeader
from lerobot.teleoperators.so_leader.config_so_leader import SOLeaderTeleopConfig

LEADER_PORT = "/dev/ttyACM1"

teleop = SOLeader(SOLeaderTeleopConfig(port=LEADER_PORT, id="decras_leader", use_degrees=True))
teleop.connect(calibrate=True)
teleop.disconnect()
print("Leader arm calibration complete.")
