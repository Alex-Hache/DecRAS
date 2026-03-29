"""Shared fixtures for DecRAS tests."""

import pytest

from mcp_server.history import PositionHistory
from mcp_server.robot.lerobot import LeRobotInterface


@pytest.fixture
def history():
    """Fresh position history buffer."""
    return PositionHistory()


@pytest.fixture
def mock_robot():
    """LeRobotInterface in offline mode (no hardware)."""
    return LeRobotInterface()
