"""Position history buffer for go_back support."""

from collections import deque
from mcp_server.config import POSITION_HISTORY_SIZE


class PositionHistory:
    def __init__(self, max_size: int = POSITION_HISTORY_SIZE):
        self._buffer: deque[list[float]] = deque(maxlen=max_size)

    def record(self, position: list[float]) -> None:
        self._buffer.append(list(position))

    def go_back(self, steps: int = 1) -> list[float] | None:
        if not self._buffer:
            return None
        steps = min(steps, len(self._buffer))
        # Pop the most recent `steps` entries and return the target
        for _ in range(steps):
            pos = self._buffer.pop()
        return pos

    @property
    def current(self) -> list[float] | None:
        return list(self._buffer[-1]) if self._buffer else None

    def __len__(self) -> int:
        return len(self._buffer)
